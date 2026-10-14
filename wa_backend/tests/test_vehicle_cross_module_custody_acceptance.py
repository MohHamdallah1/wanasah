from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text

from api import reconciliation as reconciliation_api
from api.warehouse import stocktake as stocktake_api
from dispatch_access import require_vehicle, vehicle_filter
from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    refresh_live_stock_vehicle_attribution,
)
from domains.vehicles.contracts import VehicleError
from models import (
    DispatchRoute,
    InventoryBalance,
    InventoryLiveStockProjection,
    InventoryLocation,
    InventoryMovement,
    ProductVariant,
    SessionInventorySnapshot,
    StocktakeSession,
    Vehicle,
    WorkSession,
    Zone,
    utc_now,
)
from schemas import (
    StocktakeApprovalRequest,
    UnifiedStocktakeCountRequest,
    UnifiedStocktakeStartRequest,
)
from services import InventoryMutationError
from tests.canonical_actor_fixtures import (
    seed_field_fixture,
    seed_ordinary_backoffice_fixture,
)
from tests.test_vehicle_dispatch_inventory_acceptance import (
    _add_historical_custody,
    _count,
    _create_vehicle,
    _seed_batch_and_balance,
    _vehicle_and_custody,
    gate,
)


async def _seed_ended_vehicle_session(
    gate,
    *,
    suffix: str,
    balance_quantity: int = 0,
):
    db = gate["db"]
    company_id = gate["company_id"]
    field = await seed_field_fixture(
        db,
        company_id,
        password=f"SyntheticRecon{suffix[:8]}123",
    )
    vehicle = await _create_vehicle(
        db,
        gate["owner"],
        company_id,
        plate=f"XR-{suffix[:14]}",
    )
    vehicle_id = int(vehicle["id"])
    _, custody_rows = await _vehicle_and_custody(db, company_id, vehicle_id)
    assert len(custody_rows) == 1
    custody_id = int(custody_rows[0].id)

    zone = Zone(company_id=company_id, name=f"Cross module {suffix} zone")
    db.add(zone)
    await db.flush()

    ended_at = utc_now()
    session = WorkSession(
        company_id=company_id,
        driver_id=int(field.driver.id),
        session_date=date.today(),
        start_time=ended_at - timedelta(hours=1),
        end_time=ended_at,
        is_authorized_to_sell=False,
        is_settled=False,
    )
    db.add(session)
    await db.flush()

    route = DispatchRoute(
        company_id=company_id,
        zone_id=int(zone.id),
        driver_id=int(field.driver.id),
        vehicle_id=vehicle_id,
        work_session_id=int(session.id),
        source_location_id=gate["wh_a_id"],
        dispatch_date=await reconciliation_api.get_company_local_date(db, company_id)
        if hasattr(reconciliation_api, "get_company_local_date")
        else date.today(),
        status="closed",
    )
    db.add(route)
    await db.flush()

    batch_id = None
    if balance_quantity:
        batch_id = await _seed_batch_and_balance(
            gate,
            location_id=custody_id,
            quantity=balance_quantity,
            suffix=f"XR-{suffix[:8]}",
        )
        db.add(SessionInventorySnapshot(
            company_id=company_id,
            work_session_id=int(session.id),
            location_id=custody_id,
            product_variant_id=gate["variant_id"],
            stock_status="AVAILABLE",
            starting_quantity=Decimal(balance_quantity),
        ))
        await db.flush()

    await db.commit()
    return SimpleNamespace(
        field=field,
        driver=field.driver,
        driver_id=int(field.driver.id),
        vehicle_id=vehicle_id,
        custody_id=custody_id,
        session_id=int(session.id),
        route_id=int(route.id),
        batch_id=batch_id,
    )


async def _vehicle_balance_total(db, *, company_id: int, location_id: int) -> Decimal:
    value = await db.scalar(
        select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
        )
    )
    return Decimal(value or 0)


async def _recon_movement_count(db, *, company_id: int, session_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(InventoryMovement)
            .where(
                InventoryMovement.company_id == company_id,
                InventoryMovement.work_session_id == session_id,
                InventoryMovement.reference_type.in_(["DRIVER_SHORTAGE", "DRIVER_SURPLUS"]),
            )
        )
        or 0
    )


async def _open_recon_stocktake(gate, ctx):
    return await stocktake_api.start_unified_stocktake(
        UnifiedStocktakeStartRequest(
            location_id=ctx.custody_id,
            stocktake_type="VEHICLE_RECON",
            related_work_session_id=ctx.session_id,
        ),
        db=gate["db"],
        access=gate["owner"].access(gate["db"]),
        legacy_actor=gate["owner"].operational_driver,
    )


async def _submit_recon_count(gate, ctx, stocktake_id: int, *, actual_quantity: int):
    db = gate["db"]
    variant = await db.get(ProductVariant, gate["variant_id"])
    assert variant is not None and ctx.batch_id is not None
    return await stocktake_api.submit_stocktake_count(
        stocktake_id,
        UnifiedStocktakeCountRequest(
            items=[{
                "product_variant_id": gate["variant_id"],
                "batch_id": ctx.batch_id,
                "stock_status": "AVAILABLE",
                "actual_quantity": actual_quantity,
                "uom_id": int(variant.base_uom_id),
            }]
        ),
        db=db,
        access=gate["owner"].access(db),
        legacy_actor=gate["owner"].operational_driver,
    )


async def _approve_recon(gate, stocktake_id: int, attempt_id: int):
    return await stocktake_api.approve_stocktake_session(
        stocktake_id,
        StocktakeApprovalRequest(
            count_attempt_id=attempt_id,
            password="SyntheticOwner123",
        ),
        db=gate["db"],
        access=gate["owner"].access(gate["db"]),
        legacy_actor=gate["owner"].operational_driver,
    )


@pytest.mark.asyncio
async def test_01_end_of_day_reconcile_canonical_positive(gate):
    ctx = await _seed_ended_vehicle_session(gate, suffix="RPOS")
    result = await reconciliation_api.reconcile_driver_end_of_day(
        ctx.session_id,
        reconciliation_api.VehicleReconciliationRequest(counts=[]),
        db=gate["db"],
        field_context=ctx.field.context,
        legacy_actor=ctx.driver,
    )
    assert result["requires_audit"] is False
    work_session = await gate["db"].get(WorkSession, ctx.session_id)
    assert work_session.inventory_reconciled_at is not None
    assert int(work_session.inventory_reconciled_by) == ctx.driver_id


@pytest.mark.asyncio
async def test_02_end_of_day_reconcile_duplicate_custody_fails_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_ended_vehicle_session(gate, suffix="RDUP")
    await _add_historical_custody(
        db,
        company_id=company_id,
        vehicle_id=ctx.vehicle_id,
        suffix="RDUP",
        active=False,
    )
    await db.commit()
    before_movements = await _recon_movement_count(
        db, company_id=company_id, session_id=ctx.session_id
    )
    before_stocktakes = await _count(
        db,
        StocktakeSession,
        StocktakeSession.company_id == company_id,
        StocktakeSession.related_work_session_id == ctx.session_id,
        StocktakeSession.stocktake_type == "VEHICLE_RECON",
    )

    caught = None
    try:
        await reconciliation_api.reconcile_driver_end_of_day(
            ctx.session_id,
            reconciliation_api.VehicleReconciliationRequest(counts=[]),
            db=db,
            field_context=ctx.field.context,
            legacy_actor=ctx.driver,
        )
    except HTTPException as exc:
        caught = exc

    work_session = await db.get(WorkSession, ctx.session_id)
    after_movements = await _recon_movement_count(
        db, company_id=company_id, session_id=ctx.session_id
    )
    after_stocktakes = await _count(
        db,
        StocktakeSession,
        StocktakeSession.company_id == company_id,
        StocktakeSession.related_work_session_id == ctx.session_id,
        StocktakeSession.stocktake_type == "VEHICLE_RECON",
    )
    assert caught is not None and caught.status_code == 409, (
        "end-of-day reconciliation accepted active + historical duplicate custody; "
        f"reconciled_at={work_session.inventory_reconciled_at!r}"
    )
    assert after_movements == before_movements
    assert after_stocktakes == before_stocktakes
    assert work_session.inventory_reconciled_at is None
    assert work_session.inventory_reconciled_by is None


@pytest.mark.asyncio
async def test_03_end_of_day_reconcile_missing_custody_fails_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_ended_vehicle_session(gate, suffix="RMISS")
    await db.execute(
        delete(InventoryLocation).where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.id == ctx.custody_id,
        )
    )
    await db.commit()
    with pytest.raises(HTTPException) as caught:
        await reconciliation_api.reconcile_driver_end_of_day(
            ctx.session_id,
            reconciliation_api.VehicleReconciliationRequest(counts=[]),
            db=db,
            field_context=ctx.field.context,
            legacy_actor=ctx.driver,
        )
    assert caught.value.status_code == 409
    work_session = await db.get(WorkSession, ctx.session_id)
    assert work_session.inventory_reconciled_at is None


@pytest.mark.asyncio
async def test_04_end_of_day_reconcile_inactive_custody_fails_closed(gate):
    db = gate["db"]
    ctx = await _seed_ended_vehicle_session(gate, suffix="RINACT")
    custody = await db.get(InventoryLocation, ctx.custody_id)
    custody.is_active = False
    await db.commit()
    with pytest.raises(HTTPException) as caught:
        await reconciliation_api.reconcile_driver_end_of_day(
            ctx.session_id,
            reconciliation_api.VehicleReconciliationRequest(counts=[]),
            db=db,
            field_context=ctx.field.context,
            legacy_actor=ctx.driver,
        )
    assert caught.value.status_code == 409
    work_session = await db.get(WorkSession, ctx.session_id)
    assert work_session.inventory_reconciled_at is None


@pytest.mark.asyncio
async def test_05_vehicle_recon_stocktake_start_canonical_positive(gate):
    ctx = await _seed_ended_vehicle_session(gate, suffix="SPOS")
    result = await _open_recon_stocktake(gate, ctx)
    session = await gate["db"].get(StocktakeSession, int(result["session_id"]))
    assert session.stocktake_type == "VEHICLE_RECON"
    assert session.status == "COUNTING"
    assert int(session.location_id) == ctx.custody_id
    assert int(session.related_work_session_id) == ctx.session_id


@pytest.mark.asyncio
async def test_06_vehicle_recon_stocktake_start_duplicate_fails_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_ended_vehicle_session(gate, suffix="SDUP")
    await _add_historical_custody(
        db,
        company_id=company_id,
        vehicle_id=ctx.vehicle_id,
        suffix="SDUP",
        active=False,
    )
    await db.commit()
    before_count = await _count(
        db,
        StocktakeSession,
        StocktakeSession.company_id == company_id,
        StocktakeSession.related_work_session_id == ctx.session_id,
    )
    caught = None
    try:
        await _open_recon_stocktake(gate, ctx)
    except HTTPException as exc:
        caught = exc
    after_count = await _count(
        db,
        StocktakeSession,
        StocktakeSession.company_id == company_id,
        StocktakeSession.related_work_session_id == ctx.session_id,
    )
    assert caught is not None and caught.status_code == 409, (
        "VEHICLE_RECON start accepted explicit active location while Vehicle has historical duplicate"
    )
    assert after_count == before_count


@pytest.mark.asyncio
async def test_07_vehicle_recon_stocktake_start_wrong_vehicle_location_fails_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_ended_vehicle_session(gate, suffix="SWRONG")
    other = await _create_vehicle(db, gate["owner"], company_id, plate="XR-WRONG-OTHER")
    _, other_custody = await _vehicle_and_custody(db, company_id, int(other["id"]))
    assert len(other_custody) == 1
    wrong_location_id = int(other_custody[0].id)
    await db.commit()

    with pytest.raises(HTTPException) as caught:
        await stocktake_api.start_unified_stocktake(
            UnifiedStocktakeStartRequest(
                location_id=wrong_location_id,
                stocktake_type="VEHICLE_RECON",
                related_work_session_id=ctx.session_id,
            ),
            db=db,
            access=gate["owner"].access(db),
            legacy_actor=gate["owner"].operational_driver,
        )
    assert caught.value.status_code == 409
    assert await _count(
        db,
        StocktakeSession,
        StocktakeSession.company_id == company_id,
        StocktakeSession.related_work_session_id == ctx.session_id,
    ) == 0


@pytest.mark.asyncio
async def test_08_vehicle_recon_post_revalidates_duplicate_before_movement(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_ended_vehicle_session(
        gate,
        suffix="POSTDUP",
        balance_quantity=5,
    )
    opened = await _open_recon_stocktake(gate, ctx)
    stocktake_id = int(opened["session_id"])
    counted = await _submit_recon_count(
        gate,
        ctx,
        stocktake_id,
        actual_quantity=6,
    )
    await _add_historical_custody(
        db,
        company_id=company_id,
        vehicle_id=ctx.vehicle_id,
        suffix="POSTDUP",
        active=False,
    )
    await db.commit()

    balance_before = await _vehicle_balance_total(
        db, company_id=company_id, location_id=ctx.custody_id
    )
    movement_before = await _recon_movement_count(
        db, company_id=company_id, session_id=ctx.session_id
    )
    caught = None
    try:
        await _approve_recon(gate, stocktake_id, int(counted["attempt_id"]))
    except HTTPException as exc:
        caught = exc

    balance_after = await _vehicle_balance_total(
        db, company_id=company_id, location_id=ctx.custody_id
    )
    movement_after = await _recon_movement_count(
        db, company_id=company_id, session_id=ctx.session_id
    )
    stocktake = await db.get(StocktakeSession, stocktake_id)
    work_session = await db.get(WorkSession, ctx.session_id)
    assert caught is not None and caught.status_code == 409, (
        "VEHICLE_RECON post accepted ambiguous custody; "
        f"status={stocktake.status}, balance={balance_after}, movements={movement_after}"
    )
    assert balance_after == balance_before
    assert movement_after == movement_before
    assert stocktake.status == "PENDING_REVIEW"
    assert stocktake.posted_at is None
    assert work_session.inventory_reconciled_at is None


@pytest.mark.asyncio
async def test_09_vehicle_recon_seal_revalidates_duplicate_without_partial_state(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_ended_vehicle_session(
        gate,
        suffix="SEALDUP",
        balance_quantity=5,
    )
    opened = await _open_recon_stocktake(gate, ctx)
    stocktake_id = int(opened["session_id"])
    counted = await _submit_recon_count(
        gate,
        ctx,
        stocktake_id,
        actual_quantity=5,
    )
    await _add_historical_custody(
        db,
        company_id=company_id,
        vehicle_id=ctx.vehicle_id,
        suffix="SEALDUP",
        active=False,
    )
    await db.commit()

    movement_before = await _recon_movement_count(
        db, company_id=company_id, session_id=ctx.session_id
    )
    caught = None
    try:
        await _approve_recon(gate, stocktake_id, int(counted["attempt_id"]))
    except HTTPException as exc:
        caught = exc

    movement_after = await _recon_movement_count(
        db, company_id=company_id, session_id=ctx.session_id
    )
    stocktake = await db.get(StocktakeSession, stocktake_id)
    work_session = await db.get(WorkSession, ctx.session_id)
    assert caught is not None and caught.status_code == 409, (
        "VEHICLE_RECON seal accepted ambiguous custody; "
        f"stocktake={stocktake.status}, reconciled_at={work_session.inventory_reconciled_at!r}"
    )
    assert movement_after == movement_before
    assert stocktake.status == "PENDING_REVIEW"
    assert stocktake.posted_at is None
    assert work_session.inventory_reconciled_at is None
    assert work_session.inventory_reconciled_by is None


async def _filtered_vehicle_ids(db, access, company_id: int) -> list[int]:
    return list(
        (
            await db.scalars(
                select(Vehicle.id)
                .where(
                    Vehicle.company_id == company_id,
                    vehicle_filter(access, "dispatch.read"),
                )
                .order_by(Vehicle.id.asc())
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_10_dispatch_access_canonical_vehicle_positive(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    vehicle = await _create_vehicle(db, gate["owner"], company_id, plate="XR-ACCESS-A")
    vehicle_id = int(vehicle["id"])
    await db.commit()
    access = gate["owner"].access(db)
    await require_vehicle(access, "dispatch.read", vehicle_id)
    assert vehicle_id in await _filtered_vehicle_ids(db, access, company_id)


@pytest.mark.asyncio
async def test_11_dispatch_access_duplicate_custody_fails_closed(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    vehicle = await _create_vehicle(db, gate["owner"], company_id, plate="XR-ACCESS-B")
    vehicle_id = int(vehicle["id"])
    await _add_historical_custody(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
        suffix="ACCESS-B",
        active=False,
    )
    await db.commit()
    access = gate["owner"].access(db)
    caught = None
    try:
        await require_vehicle(access, "dispatch.read", vehicle_id)
    except HTTPException as exc:
        caught = exc
    filtered = await _filtered_vehicle_ids(db, access, company_id)
    violations = []
    if caught is None or caught.status_code not in {403, 404, 409}:
        violations.append("require_vehicle authorized ambiguity")
    if vehicle_id in filtered:
        violations.append("vehicle_filter included ambiguity")
    assert not violations, "; ".join(violations)


@pytest.mark.asyncio
async def test_12_dispatch_access_missing_inactive_and_cross_company_are_isolated(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    access = gate["owner"].access(db)

    missing = await _create_vehicle(db, gate["owner"], company_id, plate="XR-ACCESS-C")
    missing_id = int(missing["id"])
    _, missing_custody = await _vehicle_and_custody(db, company_id, missing_id)
    await db.execute(delete(InventoryLocation).where(InventoryLocation.id == int(missing_custody[0].id)))

    inactive = await _create_vehicle(db, gate["owner"], company_id, plate="XR-ACCESS-D")
    inactive_id = int(inactive["id"])
    _, inactive_custody = await _vehicle_and_custody(db, company_id, inactive_id)
    inactive_custody[0].is_active = False

    other = await _create_vehicle(
        db,
        gate["other_owner"],
        gate["other_company_id"],
        plate="XR-ACCESS-X",
    )
    other_id = int(other["id"])
    await _add_historical_custody(
        db,
        company_id=gate["other_company_id"],
        vehicle_id=other_id,
        suffix="ACCESS-X",
        active=False,
    )
    await db.commit()

    for vehicle_id in (missing_id, inactive_id, other_id):
        with pytest.raises(HTTPException):
            await require_vehicle(access, "dispatch.read", vehicle_id)
    filtered = await _filtered_vehicle_ids(db, access, company_id)
    assert missing_id not in filtered
    assert inactive_id not in filtered
    assert other_id not in filtered


async def _grant_location_dispatch_read(gate, location_id: int):
    db = gate["db"]
    company_id = gate["company_id"]
    ordinary = await seed_ordinary_backoffice_fixture(
        db,
        company_id,
        password="SyntheticScopedDispatch123",
    )
    role_id = (
        await db.execute(
            text(
                "INSERT INTO roles(company_id,name,is_system_role) "
                "VALUES (:c,:n,false) RETURNING id"
            ),
            {"c": company_id, "n": f"dispatch-scope-{uuid4().hex[:10]}"},
        )
    ).scalar_one()
    permission_id = (
        await db.execute(
            text(
                "INSERT INTO permissions(code) VALUES ('dispatch.read') "
                "ON CONFLICT(code) DO UPDATE SET code=EXCLUDED.code RETURNING id"
            )
        )
    ).scalar_one()
    await db.execute(
        text(
            "INSERT INTO role_permissions(company_id,role_id,permission_id) "
            "VALUES (:c,:r,:p)"
        ),
        {"c": company_id, "r": role_id, "p": permission_id},
    )
    await db.execute(
        text(
            "INSERT INTO user_location_access(company_id,driver_id,location_id,role_id) "
            "VALUES (:c,:d,:l,:r)"
        ),
        {
            "c": company_id,
            "d": ordinary.driver_id,
            "l": location_id,
            "r": role_id,
        },
    )
    await db.commit()
    return ordinary.access(db)


@pytest.mark.asyncio
async def test_13_dispatch_access_location_scope_duplicate_never_widens_vehicle_set(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    vehicle = await _create_vehicle(db, gate["owner"], company_id, plate="XR-SCOPE-DUP")
    vehicle_id = int(vehicle["id"])
    _, custody_rows = await _vehicle_and_custody(db, company_id, vehicle_id)
    assert len(custody_rows) == 1
    canonical_location_id = int(custody_rows[0].id)
    await _add_historical_custody(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
        suffix="SCOPE-DUP",
        active=False,
    )
    await db.commit()

    access = await _grant_location_dispatch_read(gate, canonical_location_id)
    caught = None
    try:
        await require_vehicle(access, "dispatch.read", vehicle_id)
    except HTTPException as exc:
        caught = exc
    filtered = await _filtered_vehicle_ids(db, access, company_id)
    violations = []
    if caught is None or caught.status_code not in {403, 404, 409}:
        violations.append("location-scoped require_vehicle authorized ambiguity")
    if vehicle_id in filtered:
        violations.append("location-scoped vehicle_filter included ambiguity")
    assert not violations, "; ".join(violations)


@pytest.mark.asyncio
async def test_14_live_stock_attribution_canonical_positive_without_balance_mutation(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_ended_vehicle_session(
        gate,
        suffix="LSPOS",
        balance_quantity=5,
    )
    before_total = await _vehicle_balance_total(
        db, company_id=company_id, location_id=ctx.custody_id
    )
    before_rows = await _count(
        db,
        InventoryBalance,
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == ctx.custody_id,
    )

    await refresh_live_stock_vehicle_attribution(
        db,
        company_id=company_id,
        vehicle_ids=[ctx.vehicle_id],
        previous_sources={},
    )
    await db.commit()

    projection = await db.scalar(
        select(InventoryLiveStockProjection).where(
            InventoryLiveStockProjection.company_id == company_id,
            InventoryLiveStockProjection.warehouse_location_id == gate["wh_a_id"],
            InventoryLiveStockProjection.product_variant_id == gate["variant_id"],
        )
    )
    assert projection is not None
    assert Decimal(projection.vehicle_packs or 0) >= Decimal("5")
    assert await _vehicle_balance_total(
        db, company_id=company_id, location_id=ctx.custody_id
    ) == before_total
    assert await _count(
        db,
        InventoryBalance,
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == ctx.custody_id,
    ) == before_rows


@pytest.mark.asyncio
async def test_15_live_stock_attribution_ambiguous_custody_fails_closed_without_balance_mutation(gate):
    db = gate["db"]
    company_id = gate["company_id"]
    ctx = await _seed_ended_vehicle_session(
        gate,
        suffix="LSDUP",
        balance_quantity=5,
    )
    await _add_historical_custody(
        db,
        company_id=company_id,
        vehicle_id=ctx.vehicle_id,
        suffix="LSDUP",
        active=False,
    )
    await db.commit()

    before_total = await _vehicle_balance_total(
        db, company_id=company_id, location_id=ctx.custody_id
    )
    before_rows = await _count(
        db,
        InventoryBalance,
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == ctx.custody_id,
    )
    caught = None
    try:
        await refresh_live_stock_vehicle_attribution(
            db,
            company_id=company_id,
            vehicle_ids=[ctx.vehicle_id],
            previous_sources={},
        )
        await db.commit()
    except (LiveStockProjectionError, VehicleError, InventoryMutationError) as exc:
        caught = exc
        await db.rollback()

    projection = await db.scalar(
        select(InventoryLiveStockProjection).where(
            InventoryLiveStockProjection.company_id == company_id,
            InventoryLiveStockProjection.warehouse_location_id == gate["wh_a_id"],
            InventoryLiveStockProjection.product_variant_id == gate["variant_id"],
        )
    )
    assert await _vehicle_balance_total(
        db, company_id=company_id, location_id=ctx.custody_id
    ) == before_total
    assert await _count(
        db,
        InventoryBalance,
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == ctx.custody_id,
    ) == before_rows
    assert caught is not None, (
        "Live Stock attribution silently accepted ambiguous Vehicle custody; "
        f"vehicle_packs={getattr(projection, 'vehicle_packs', None)!r}; "
        "InventoryBalance remained unchanged"
    )
