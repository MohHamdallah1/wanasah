from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from asyncpg import Range
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api import dispatch
from api.driver import (
    end_work_session,
    respond_to_transfer,
    start_work_session,
    update_visit,
)
from api.representative_settlement import (
    CustodyConfirm,
    read_representative_custody,
    receive_representative_custody,
)
from api.warehouse import live_stock
from domains.authorization.field_access import (
    FieldCapabilityAccess,
    FieldCapabilityAccessRejected,
)
from domains.authorization.field_provisioning import assign_new_representative_default
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from domains.sales_calculation.policy import publish_commercial_rounding_policy
from domains.taxation.models import (
    TaxJurisdiction,
    TaxRuleComponent,
    TaxRuleScope,
    TaxRuleSet,
    TaxRuleSetVersion,
)
from domains.taxation.publishing import publish_version as publish_tax_version
from models import (
    DispatchRoute,
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostLayer,
    InventoryCostState,
    InventoryMovement,
    InventoryTransferHeader,
    PriceBook,
    PriceBookAssignment,
    PriceBookEntry,
    PricePublication,
    ProductUomConversion,
    ProductVariant,
    SessionInventorySnapshot,
    Shop,
    UOM,
    Visit,
    WorkSession,
    Zone,
)
from schemas import (
    AdjustRouteInventoryRequest,
    AuthorizeSessionRequest,
    DispatchRouteRequest,
    SessionStartRequest,
    SettleSessionRequest,
    TransferResponseRequest,
    UpdateRouteStatusRequest,
    UpgradedInboundRequest,
    VisitUpdateRequest,
)
from tests.canonical_actor_fixtures import seed_field_fixture
from tests.test_inbound_no_lot_frozen_postgres import pg
from tests.test_live_stock_v1_quantity_reconciliation_postgres import (
    CARTON_TO_BASE,
    EXPECTED_BASE_UNIT_COST,
    EXPECTED_INBOUND_BASE,
    EXPECTED_PURCHASE_VALUE,
    INBOUND_CARTONS,
    PURCHASE_COST_PER_CARTON,
    _create_vehicle_with_historical_attribution,
    _seed_carton_conversion,
)


pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_NO_LOT_PG_GATE") != "1",
        reason="Explicit disposable PostgreSQL 16 acceptance only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


# Independent lifecycle truth. These values are fixed before API reads.
INITIAL_WAREHOUSE = Decimal("800")
INITIAL_VEHICLE = Decimal("0")
DIRECT_LOAD = Decimal("240")
POST_LOAD_WAREHOUSE = Decimal("560")
POST_LOAD_VEHICLE = Decimal("240")
ROUTE_TARGET = Decimal("240")
ACTIVE_ROUTE_DELTA = Decimal("80")
POST_ADJUST_WAREHOUSE = Decimal("480")
POST_ADJUST_VEHICLE = Decimal("320")
SALE_BASE = Decimal("80")
POST_SALE_WAREHOUSE = Decimal("480")
POST_SALE_VEHICLE = Decimal("240")
POST_SALE_PHYSICAL = Decimal("720")
FINAL_WAREHOUSE = Decimal("720")
FINAL_VEHICLE = Decimal("0")
SALE_COGS = SALE_BASE * EXPECTED_BASE_UNIT_COST
FINAL_INVENTORY_VALUE = EXPECTED_PURCHASE_VALUE - SALE_COGS
SALE_UNIT_PRICE = Decimal("1")
SALE_CASH = SALE_BASE * SALE_UNIT_PRICE

assert INITIAL_WAREHOUSE == EXPECTED_INBOUND_BASE == Decimal("800")
assert DIRECT_LOAD == Decimal("240")
assert POST_LOAD_WAREHOUSE + POST_LOAD_VEHICLE == EXPECTED_INBOUND_BASE
assert POST_ADJUST_WAREHOUSE + POST_ADJUST_VEHICLE == EXPECTED_INBOUND_BASE
assert POST_SALE_WAREHOUSE + POST_SALE_VEHICLE == POST_SALE_PHYSICAL
assert POST_SALE_PHYSICAL == EXPECTED_INBOUND_BASE - SALE_BASE
assert FINAL_WAREHOUSE + FINAL_VEHICLE == POST_SALE_PHYSICAL
assert SALE_COGS == Decimal("160")
assert FINAL_INVENTORY_VALUE == Decimal("1440")
assert SALE_CASH == Decimal("80")


async def _seed_mobile_uom_and_field(pg_gate, tenant):
    """Master/auth fixture only; never writes inventory truth."""
    async with pg_gate.session() as db:
        variant = await db.scalar(
            select(ProductVariant).where(
                ProductVariant.company_id == tenant.company_id,
                ProductVariant.id == tenant.variant_id,
            )
        )
        variant.packs_per_carton = int(CARTON_TO_BASE)

        carton = await db.scalar(select(UOM).where(UOM.code == "CARTON"))
        assert carton is not None
        existing = await db.scalar(
            select(ProductUomConversion).where(
                ProductUomConversion.company_id == tenant.company_id,
                ProductUomConversion.product_variant_id == tenant.variant_id,
                ProductUomConversion.from_uom_id == int(carton.id),
                ProductUomConversion.to_uom_id == tenant.uom_id,
            )
        )
        if existing is None:
            db.add(
                ProductUomConversion(
                    company_id=tenant.company_id,
                    product_variant_id=tenant.variant_id,
                    from_uom_id=int(carton.id),
                    to_uom_id=tenant.uom_id,
                    numerator=CARTON_TO_BASE,
                    denominator=Decimal("1"),
                    quantity_scale=0,
                    version=1,
                )
            )

        field = await seed_field_fixture(db, tenant.company_id)
        field_access = FieldCapabilityAccess(db, field.context)
        with pytest.raises(FieldCapabilityAccessRejected):
            await field_access.require("visit.execute")
        await assign_new_representative_default(
            db, tenant.company_id, field.context.representative_id
        )
        await db.flush()
        assert {
            "work_session.execute",
            "visit.execute",
            "transfer.read",
            "transfer.receive",
            "inventory.read",
            "pricing.view",
        }.issubset(await field_access.codes())
        await db.commit()
        return field


async def _seed_commercial_master(pg_gate, tenant, field):
    """Published pricing/tax configuration plus one route shop; no active route."""
    async with pg_gate.session() as db:
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=5)
        tag = uuid4().hex[:10].upper()

        book = PriceBook(
            company_id=tenant.company_id,
            code="QTYSALE-" + tag,
            name="Quantity lifecycle sale price",
            currency_code="JOD",
            status="ACTIVE",
            created_by=tenant.owner.driver_id,
        )
        db.add(book)
        await db.flush()
        publication = PricePublication(
            company_id=tenant.company_id,
            price_book_id=book.id,
            revision=1,
            status="PUBLISHED",
            effective_at=earlier,
            published_at=earlier,
            approved_at=earlier,
            approved_by=tenant.owner.driver_id,
            created_by=tenant.owner.driver_id,
            request_id=uuid4(),
        )
        db.add(publication)
        await db.flush()
        window = Range(lower=earlier, upper=None, lower_inc=True)
        db.add_all(
            [
                PriceBookEntry(
                    company_id=tenant.company_id,
                    price_book_id=book.id,
                    publication_id=publication.id,
                    product_variant_id=tenant.variant_id,
                    uom_id=tenant.uom_id,
                    amount=SALE_UNIT_PRICE,
                    effectivity=window,
                    is_published=True,
                    priority=0,
                    entry_metadata={},
                ),
                PriceBookAssignment(
                    company_id=tenant.company_id,
                    price_book_id=book.id,
                    scope_type="COMPANY_DEFAULT",
                    scope_id=None,
                    revision=1,
                    priority=0,
                    allow_offers=False,
                    effectivity=window,
                    created_by=tenant.owner.driver_id,
                ),
            ]
        )

        jurisdiction = TaxJurisdiction(
            company_id=tenant.company_id,
            code="QTYJO-" + tag,
            name="Quantity proof zero tax",
            jurisdiction_type="COUNTRY",
            country_code="JO",
            created_by=tenant.owner.driver_id,
            is_active=True,
        )
        ruleset = TaxRuleSet(
            company_id=tenant.company_id,
            code="QTYTAX-" + tag,
            name="Quantity proof tax",
            created_by=tenant.owner.driver_id,
        )
        db.add_all([jurisdiction, ruleset])
        await db.flush()
        revision = TaxRuleSetVersion(
            company_id=tenant.company_id,
            tax_rule_set_id=ruleset.id,
            revision=1,
            definition_version=1,
            status="DRAFT",
            price_mode="EXCLUSIVE",
            priority=0,
            effective_from=earlier,
            effective_to=None,
            created_by=tenant.owner.driver_id,
            request_id=uuid4(),
        )
        db.add(revision)
        await db.flush()
        db.add_all(
            [
                TaxRuleComponent(
                    company_id=tenant.company_id,
                    tax_rule_set_version_id=revision.id,
                    component_code="ZERO",
                    name="Zero tax",
                    sequence=1,
                    rate=Decimal("0"),
                    basis_mode="TAXABLE_BASE",
                ),
                TaxRuleScope(
                    company_id=tenant.company_id,
                    tax_rule_set_version_id=revision.id,
                    scope_type="JURISDICTION",
                    jurisdiction_id=jurisdiction.id,
                ),
            ]
        )
        await db.flush()
        published = await publish_tax_version(
            db,
            company_id=tenant.company_id,
            actor_id=tenant.owner.driver_id,
            version_id=revision.id,
            expected_version=revision.version,
        )
        assert published.status == "PUBLISHED"
        rounding = await publish_commercial_rounding_policy(
            db,
            company_id=tenant.company_id,
            actor_id=tenant.owner.driver_id,
            expected_revision=0,
            precision=3,
            mode="HALF_UP",
        )
        assert rounding.rounding_policy.currency_code == "JOD"

        zone = Zone(
            company_id=tenant.company_id,
            name="Quantity route " + tag,
            is_active=True,
        )
        db.add(zone)
        await db.flush()
        shop = Shop(
            company_id=tenant.company_id,
            name="Quantity sale shop " + tag,
            zone_id=zone.id,
            tax_jurisdiction_id=jurisdiction.id,
            current_balance=Decimal("0"),
            max_debt_limit=Decimal("1000"),
            is_active=True,
        )
        db.add(shop)
        await db.commit()
        return int(zone.id), int(shop.id)


async def _balance(
    db,
    *,
    company_id: int,
    location_id: int,
    variant_id: int,
    batch_id: int,
) -> tuple[Decimal, Decimal]:
    row = (
        await db.execute(
            select(
                InventoryBalance.on_hand_quantity,
                InventoryBalance.reserved_quantity,
            ).where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id == variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
        )
    ).one_or_none()
    if row is None:
        return Decimal("0"), Decimal("0")
    return Decimal(row.on_hand_quantity), Decimal(row.reserved_quantity)


async def _assert_inventory_truth(
    pg_gate,
    tenant,
    *,
    batch_id: int,
    vehicle_location_id: int,
    warehouse: Decimal,
    vehicle: Decimal,
    warehouse_reserved: Decimal = Decimal("0"),
    cost_quantity: Decimal,
    cost_value: Decimal,
    expected_cost_events: int,
):
    async with pg_gate.session() as db:
        wh_on, wh_reserved = await _balance(
            db,
            company_id=tenant.company_id,
            location_id=tenant.location_id,
            variant_id=tenant.variant_id,
            batch_id=batch_id,
        )
        vh_on, vh_reserved = await _balance(
            db,
            company_id=tenant.company_id,
            location_id=vehicle_location_id,
            variant_id=tenant.variant_id,
            batch_id=batch_id,
        )
        assert (wh_on, wh_reserved) == (warehouse, warehouse_reserved)
        assert (vh_on, vh_reserved) == (vehicle, Decimal("0"))
        assert wh_on + vh_on == cost_quantity

        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id,
                InventoryCostState.product_variant_id == tenant.variant_id,
            )
        )
        assert state is not None
        assert Decimal(state.quantity) == cost_quantity
        assert Decimal(state.inventory_value) == cost_value
        assert Decimal(state.average_unit_cost) == EXPECTED_BASE_UNIT_COST

        assert int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryCostEvent)
                .where(
                    InventoryCostEvent.company_id == tenant.company_id,
                    InventoryCostEvent.product_variant_id == tenant.variant_id,
                )
            )
            or 0
        ) == expected_cost_events

        page = await live_stock.get_warehouse_inventory(
            location_id=tenant.location_id,
            cursor=None,
            limit=50,
            search=None,
            only_alerts=False,
            stock_state="all",
            family_id=None,
            has_reserved=False,
            has_unavailable=False,
            has_damaged=False,
            has_recalled=False,
            has_vehicle=False,
            minimum_unset=False,
            sort="name_asc",
            db=db,
            access=tenant.owner.access(db),
        )
        row = next(item for item in page["items"] if item["id"] == tenant.variant_id)
        assert Decimal(row["on_hand_quantity"]) == warehouse
        assert Decimal(row["vehicle_quantity"]) == vehicle
        assert Decimal(row["total_quantity"]) == warehouse + vehicle
        assert Decimal(row["display_factor_to_base"]) == CARTON_TO_BASE

        detail = await live_stock.get_warehouse_inventory_batches(
            product_variant_id=tenant.variant_id,
            location_id=tenant.location_id,
            cursor=None,
            limit=100,
            db=db,
            access=tenant.owner.access(db),
        )
        batch = next(item for item in detail["batches"] if item["batch_id"] == batch_id)
        assert Decimal(batch["on_hand_quantity"]) == warehouse
        assert Decimal(batch["reserved_quantity"]) == warehouse_reserved
        assert int(batch["purchase_event_count"]) == 1
        assert Decimal(batch["latest_purchase_cost"]) == PURCHASE_COST_PER_CARTON

        sources = await live_stock.get_batch_stock_sources(
            batch_id=batch_id,
            db=db,
            access=tenant.owner.access(db),
        )
        by_location = {}
        for source in sources["sources"]:
            available = next(
                (
                    status
                    for status in source["statuses"]
                    if status["stock_status"] == "AVAILABLE"
                ),
                None,
            )
            if available is not None:
                by_location[int(source["location_id"])] = (
                    Decimal(available["on_hand_quantity"]),
                    Decimal(available["reserved_quantity"]),
                )
        assert by_location.get(tenant.location_id, (Decimal("0"), Decimal("0"))) == (
            warehouse,
            warehouse_reserved,
        )
        assert by_location.get(vehicle_location_id, (Decimal("0"), Decimal("0"))) == (
            vehicle,
            Decimal("0"),
        )


async def _movement_count(db, company_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(InventoryMovement)
            .where(InventoryMovement.company_id == company_id)
        )
        or 0
    )


async def test_route_sale_and_receiver_unload_preserve_quantity_and_cost_truth(pg):
    tenant = pg.tenants[0]

    carton_uom_id = await _seed_carton_conversion(pg, tenant)
    field = await _seed_mobile_uom_and_field(pg, tenant)
    zone_id, shop_id = await _seed_commercial_master(pg, tenant, field)

    # 1) Real supplier inbound: 100 cartons x 8 = 800 base.
    inbound_id = uuid4()
    inbound = UpgradedInboundRequest(
        request_id=inbound_id,
        supplier_id=tenant.supplier_id,
        location_id=tenant.location_id,
        reference_id="ROUTE-SALE-IN-" + inbound_id.hex,
        items=[
            {
                "product_variant_id": tenant.variant_id,
                "quantity": INBOUND_CARTONS,
                "uom_id": carton_uom_id,
                "unit_cost": PURCHASE_COST_PER_CARTON,
                "batch_number": "ROUTE-SALE-" + inbound_id.hex[:14],
            }
        ],
    )
    async with pg.session() as db:
        assert await pg.post(db, inbound) == {"message": "INBOUND_POSTED"}
    async with pg.session() as db:
        assert await pg.post(db, inbound) == {"message": "INBOUND_POSTED"}
        inbound_movement = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.reference_type == "INBOUND_SUPPLIER",
                InventoryMovement.reference_id == inbound.reference_id,
            )
        )
        assert inbound_movement is not None
        batch_id = int(inbound_movement.batch_id)
        assert Decimal(inbound_movement.quantity) == INITIAL_WAREHOUSE

    # Vehicle is canonical; historical CLOSED route only supplies existing
    # Live Stock attribution semantics and never moves stock.
    vehicle_id, vehicle_location_id = await _create_vehicle_with_historical_attribution(
        pg, tenant
    )

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=INITIAL_WAREHOUSE,
        vehicle=INITIAL_VEHICLE,
        cost_quantity=EXPECTED_INBOUND_BASE,
        cost_value=EXPECTED_PURCHASE_VALUE,
        expected_cost_events=1,
    )

    # 2) Real direct load: 240 base into vehicle, with exact replay.
    load_id = uuid4()
    load_items = [{"product_variant_id": tenant.variant_id, "quantity": DIRECT_LOAD}]
    async with pg.session() as db:
        first_load = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db),
            actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id,
            warehouse_id=tenant.location_id,
            direction="ADD",
            request_id=load_id,
            items=load_items,
        )
    async with pg.session() as db:
        before = await _movement_count(db, tenant.company_id)
        assert (
            await mutate_vehicle_load(
                db,
                access=tenant.owner.access(db),
                actor_id=tenant.owner.driver_id,
                vehicle_id=vehicle_id,
                warehouse_id=tenant.location_id,
                direction="ADD",
                request_id=load_id,
                items=load_items,
            )
            == first_load
        )
        assert await _movement_count(db, tenant.company_id) == before

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=POST_LOAD_WAREHOUSE,
        vehicle=POST_LOAD_VEHICLE,
        cost_quantity=EXPECTED_INBOUND_BASE,
        cost_value=EXPECTED_PURCHASE_VALUE,
        expected_cost_events=1,
    )

    # Persisted FIELD authority is required independently of operational scope.
    async with pg.session() as db:
        field_access = FieldCapabilityAccess(db, field.context)
        await field_access.require("work_session.execute")
        await field_access.require("visit.execute")
        await field_access.require("transfer.receive")

    route_payload = DispatchRouteRequest(
        zone_id=zone_id,
        driver_id=field.driver.id,
        vehicle_id=vehicle_id,
        source_location_id=tenant.location_id,
        inventory_base={str(tenant.variant_id): ROUTE_TARGET},
        expected_inventory_base={str(tenant.variant_id): POST_LOAD_VEHICLE},
    )

    # Authority failure is checked before the one permitted non-idempotent launch.
    async with pg.session() as db:
        before = await _movement_count(db, tenant.company_id)
        with pytest.raises(HTTPException) as denied:
            await dispatch.dispatch_route(
                route_payload,
                db,
                tenant.ordinary.access(db),
                tenant.ordinary.operational_driver,
            )
        assert denied.value.status_code == 403
        await db.rollback()
        assert await _movement_count(db, tenant.company_id) == before

    # 3) Launch existing 240 target exactly once. DispatchRouteRequest has no
    # request UUID by contract, so a network replay is intentionally not invented.
    async with pg.session() as db:
        before_launch = await _movement_count(db, tenant.company_id)
        launched = await dispatch.dispatch_route(
            route_payload,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        route_id = int(launched["route_id"])
    async with pg.session() as db:
        assert await _movement_count(db, tenant.company_id) == before_launch
        assert (
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.company_id == tenant.company_id,
                    InventoryMovement.reference_id == str(route_id),
                    InventoryMovement.reference_type.in_(
                        ["DISPATCH_LOAD", "DISPATCH_UNLOAD"]
                    ),
                )
            )
            == 0
        )

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=POST_LOAD_WAREHOUSE,
        vehicle=POST_LOAD_VEHICLE,
        cost_quantity=EXPECTED_INBOUND_BASE,
        cost_value=EXPECTED_PURCHASE_VALUE,
        expected_cost_events=1,
    )

    # Start the actual FIELD WorkSession. Opening snapshot is evidence only.
    async with pg.session() as db:
        started = await start_work_session(
            SessionStartRequest(),
            db,
            field.context,
            field.driver,
        )
        session_id = int(started["session_id"])
        snapshot = await db.scalar(
            select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id == tenant.company_id,
                SessionInventorySnapshot.work_session_id == session_id,
                SessionInventorySnapshot.product_variant_id == tenant.variant_id,
                SessionInventorySnapshot.stock_status == "AVAILABLE",
            )
        )
        assert snapshot is not None
        assert Decimal(snapshot.starting_quantity) == POST_LOAD_VEHICLE
        visit_id = int(
            await db.scalar(
                select(Visit.id).where(
                    Visit.company_id == tenant.company_id,
                    Visit.work_session_id == session_id,
                    Visit.shop_id == shop_id,
                    Visit.status == "Pending",
                )
            )
        )

    # Backoffice sale authorization is separate from FIELD identity.
    async with pg.session() as db:
        await dispatch.authorize_session(
            session_id,
            AuthorizeSessionRequest(is_authorized=True),
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        work = await db.scalar(
            select(WorkSession).where(
                WorkSession.company_id == tenant.company_id,
                WorkSession.id == session_id,
            )
        )
        assert work.is_authorized_to_sell is True

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=POST_LOAD_WAREHOUSE,
        vehicle=POST_LOAD_VEHICLE,
        cost_quantity=EXPECTED_INBOUND_BASE,
        cost_value=EXPECTED_PURCHASE_VALUE,
        expected_cost_events=1,
    )

    # 4) Active-session +80 is a HANDSHAKE reservation first; physical stock
    # must remain 560/240 until the assigned representative accepts it.
    adjust = AdjustRouteInventoryRequest(
        request_id=uuid4(),
        deltas=[{"product_id": tenant.variant_id, "delta_base": ACTIVE_ROUTE_DELTA}],
    )
    async with pg.session() as db:
        first_adjust = await dispatch.adjust_route_inventory(
            route_id,
            adjust,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert first_adjust["mode"] == "HANDSHAKE"
    async with pg.session() as db:
        pending = await db.scalar(
            select(InventoryTransferHeader).where(
                InventoryTransferHeader.company_id == tenant.company_id,
                InventoryTransferHeader.work_session_id == session_id,
                InventoryTransferHeader.workflow_type == "HANDSHAKE",
                InventoryTransferHeader.status == "PENDING",
            )
        )
        assert pending is not None
        transfer_id = int(pending.id)
        before_replay = await _movement_count(db, tenant.company_id)
        assert (
            await dispatch.adjust_route_inventory(
                route_id,
                adjust,
                db,
                tenant.owner.access(db),
                tenant.owner.operational_driver,
            )
            == first_adjust
        )
        assert await _movement_count(db, tenant.company_id) == before_replay
        assert (
            await db.scalar(
                select(func.count())
                .select_from(InventoryTransferHeader)
                .where(
                    InventoryTransferHeader.company_id == tenant.company_id,
                    InventoryTransferHeader.work_session_id == session_id,
                    InventoryTransferHeader.workflow_type == "HANDSHAKE",
                )
            )
            == 1
        )
        reserve = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.transfer_header_id == transfer_id,
                InventoryMovement.reference_type == "HANDSHAKE_RESERVE",
            )
        )
        assert reserve is not None
        assert reserve.movement_kind == "RESERVATION"
        assert reserve.reservation_action == "RESERVE"
        assert Decimal(reserve.quantity) == ACTIVE_ROUTE_DELTA

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=POST_LOAD_WAREHOUSE,
        vehicle=POST_LOAD_VEHICLE,
        warehouse_reserved=ACTIVE_ROUTE_DELTA,
        cost_quantity=EXPECTED_INBOUND_BASE,
        cost_value=EXPECTED_PURCHASE_VALUE,
        expected_cost_events=1,
    )

    async with pg.session() as db:
        accepted = await respond_to_transfer(
            transfer_id,
            TransferResponseRequest(response="accepted"),
            db,
            field.context,
            field.driver,
        )
    async with pg.session() as db:
        before_accept_replay = await _movement_count(db, tenant.company_id)
        assert (
            await respond_to_transfer(
                transfer_id,
                TransferResponseRequest(response="accepted"),
                db,
                field.context,
                field.driver,
            )
            == accepted
        )
        assert await _movement_count(db, tenant.company_id) == before_accept_replay
        header = await db.get(InventoryTransferHeader, transfer_id)
        assert header.status == "POSTED"
        rows = (
            await db.scalars(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == tenant.company_id,
                    InventoryMovement.transfer_header_id == transfer_id,
                )
            )
        ).all()
        by_ref = {row.reference_type: row for row in rows}
        assert set(by_ref) == {
            "HANDSHAKE_RESERVE",
            "HANDSHAKE_RELEASE",
            "HANDSHAKE_POST",
        }
        assert Decimal(by_ref["HANDSHAKE_RELEASE"].quantity) == ACTIVE_ROUTE_DELTA
        assert Decimal(by_ref["HANDSHAKE_POST"].quantity) == ACTIVE_ROUTE_DELTA

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=POST_ADJUST_WAREHOUSE,
        vehicle=POST_ADJUST_VEHICLE,
        cost_quantity=EXPECTED_INBOUND_BASE,
        cost_value=EXPECTED_PURCHASE_VALUE,
        expected_cost_events=1,
    )

    # 5) Actual authorized FIELD sale: 10 cartons x 8 = 80 base.
    sale = VisitUpdateRequest(
        request_id=uuid4(),
        outcome="Sale",
        cart_items=[
            {
                "product_variant_id": tenant.variant_id,
                "quantity": 10,
                "packs_quantity": 0,
            }
        ],
        returns=[],
        cash_collected=SALE_CASH,
    )
    async with pg.session() as db:
        first_sale = await update_visit(
            visit_id,
            sale,
            db,
            field.context,
            field.driver,
        )
        assert first_sale["message"] == "Visit updated successfully"
    async with pg.session() as db:
        before_sale_replay = await _movement_count(db, tenant.company_id)
        assert (
            await update_visit(
                visit_id,
                sale,
                db,
                field.context,
                field.driver,
            )
            == first_sale
        )
        assert await _movement_count(db, tenant.company_id) == before_sale_replay

        visit = await db.scalar(
            select(Visit).where(
                Visit.company_id == tenant.company_id,
                Visit.id == visit_id,
            )
        )
        assert visit.status == "Completed"
        assert Decimal(visit.cash_collected) == SALE_CASH
        assert Decimal(visit.final_amount_due) == SALE_CASH

        sale_movement = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.reference_type == "VISIT_ITEM_OUT",
                InventoryMovement.reference_id == str(visit_id),
            )
        )
        assert sale_movement is not None
        assert int(sale_movement.batch_id) == batch_id
        assert Decimal(sale_movement.quantity) == SALE_BASE
        assert int(sale_movement.source_location_id) == vehicle_location_id
        assert sale_movement.destination_location_id is None

        sale_cost = await db.scalar(
            select(InventoryCostEvent).where(
                InventoryCostEvent.company_id == tenant.company_id,
                InventoryCostEvent.inventory_movement_id == sale_movement.id,
            )
        )
        assert sale_cost is not None
        assert sale_cost.event_type == "OUTBOUND"
        assert Decimal(sale_cost.quantity) == SALE_BASE
        assert Decimal(sale_cost.unit_cost) == EXPECTED_BASE_UNIT_COST
        assert Decimal(sale_cost.total_cost) == SALE_COGS
        assert sale_cost.cost_basis == (
            "FIFO_LAYER" if pg.method == "FIFO" else "MOVING_AVERAGE"
        )

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=POST_SALE_WAREHOUSE,
        vehicle=POST_SALE_VEHICLE,
        cost_quantity=POST_SALE_PHYSICAL,
        cost_value=FINAL_INVENTORY_VALUE,
        expected_cost_events=2,
    )

    # 6) End work, close route, receive the exact remaining custody into the
    # warehouse, then financially settle. None may create or destroy stock.
    async with pg.session() as db:
        assert (
            await end_work_session(db, field.context, field.driver)
        )["message"] == "تم إنهاء الجلسة بنجاح."

    async with pg.session() as db:
        closed = await dispatch.update_route_status(
            route_id,
            UpdateRouteStatusRequest(status="closed"),
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert closed["status"] == "closed"

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=POST_SALE_WAREHOUSE,
        vehicle=POST_SALE_VEHICLE,
        cost_quantity=POST_SALE_PHYSICAL,
        cost_value=FINAL_INVENTORY_VALUE,
        expected_cost_events=2,
    )

    async with pg.session() as db:
        custody = await read_representative_custody(
            session_id,
            db,
            tenant.owner.access(db),
        )
        assert custody["inventory_reconciled"] is False
        assert custody["custody_received"] is False
        assert len(custody["lines"]) == 1
        assert Decimal(custody["lines"][0]["expected_quantity"]) == POST_SALE_VEHICLE
        custody_payload = CustodyConfirm(
            request_id=uuid4(),
            destination_location_id=tenant.location_id,
            receiver_confirms_handoff=True,
            items=[
                {
                    "line_key": custody["lines"][0]["line_key"],
                    "actual_quantity": str(POST_SALE_VEHICLE),
                }
            ],
            notes="Exact end-of-route custody handoff",
        )
        first_receive = await receive_representative_custody(
            session_id,
            custody_payload,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert first_receive["status"] == "CUSTODY_RECEIVED"
        assert first_receive["inventory_reconciled"] is True
        assert first_receive["movement_count"] == 1

    async with pg.session() as db:
        before_receive_replay = await _movement_count(db, tenant.company_id)
        assert (
            await receive_representative_custody(
                session_id,
                custody_payload,
                db,
                tenant.owner.access(db),
                tenant.owner.operational_driver,
            )
            == first_receive
        )
        assert await _movement_count(db, tenant.company_id) == before_receive_replay
        handoff = await db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.reference_type == "REPRESENTATIVE_CUSTODY_RECEIPT",
                InventoryMovement.reference_id == str(session_id),
            )
        )
        assert handoff is not None
        assert int(handoff.batch_id) == batch_id
        assert Decimal(handoff.quantity) == POST_SALE_VEHICLE
        assert int(handoff.source_location_id) == vehicle_location_id
        assert int(handoff.destination_location_id) == tenant.location_id

        snapshot = await db.scalar(
            select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id == tenant.company_id,
                SessionInventorySnapshot.work_session_id == session_id,
                SessionInventorySnapshot.product_variant_id == tenant.variant_id,
                SessionInventorySnapshot.stock_status == "AVAILABLE",
            )
        )
        assert Decimal(snapshot.starting_quantity) == POST_LOAD_VEHICLE
        assert Decimal(snapshot.ending_quantity) == POST_SALE_VEHICLE
        assert snapshot.settled_by is not None
        assert snapshot.settled_at is not None

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=FINAL_WAREHOUSE,
        vehicle=FINAL_VEHICLE,
        cost_quantity=POST_SALE_PHYSICAL,
        cost_value=FINAL_INVENTORY_VALUE,
        expected_cost_events=2,
    )

    settlement = SettleSessionRequest(
        request_id=uuid4(),
        actual_cash=SALE_CASH,
        inventory_jard=[],
        notes="Exact cash settlement",
    )
    async with pg.session() as db:
        first_settle = await dispatch.settle_session(
            session_id,
            settlement,
            db,
            tenant.owner.access(db),
            tenant.owner.operational_driver,
        )
        assert first_settle["is_settled"] is True
        assert Decimal(first_settle["cash_difference"]) == Decimal("0")

    async with pg.session() as db:
        before_settle_replay = await _movement_count(db, tenant.company_id)
        assert (
            await dispatch.settle_session(
                session_id,
                settlement,
                db,
                tenant.owner.access(db),
                tenant.owner.operational_driver,
            )
            == first_settle
        )
        assert await _movement_count(db, tenant.company_id) == before_settle_replay

        work = await db.scalar(
            select(WorkSession).where(
                WorkSession.company_id == tenant.company_id,
                WorkSession.id == session_id,
            )
        )
        route = await db.scalar(
            select(DispatchRoute).where(
                DispatchRoute.company_id == tenant.company_id,
                DispatchRoute.id == route_id,
            )
        )
        assert work.end_time is not None
        assert work.inventory_reconciled_at is not None
        assert work.is_settled is True
        assert route.status == "closed"

        event_types = (
            await db.execute(
                select(
                    InventoryCostEvent.event_type,
                    InventoryCostEvent.quantity,
                    InventoryCostEvent.total_cost,
                )
                .where(
                    InventoryCostEvent.company_id == tenant.company_id,
                    InventoryCostEvent.product_variant_id == tenant.variant_id,
                )
                .order_by(InventoryCostEvent.id)
            )
        ).all()
        assert [(row.event_type, Decimal(row.quantity), Decimal(row.total_cost)) for row in event_types] == [
            ("PURCHASE_IN", EXPECTED_INBOUND_BASE, EXPECTED_PURCHASE_VALUE),
            ("OUTBOUND", SALE_BASE, SALE_COGS),
        ]

        layer_totals = (
            await db.execute(
                select(
                    func.coalesce(func.sum(InventoryCostLayer.remaining_quantity), 0),
                    func.coalesce(func.sum(InventoryCostLayer.remaining_value), 0),
                ).where(
                    InventoryCostLayer.company_id == tenant.company_id,
                    InventoryCostLayer.product_variant_id == tenant.variant_id,
                )
            )
        ).one()
        if pg.method == "FIFO":
            assert Decimal(layer_totals[0]) == POST_SALE_PHYSICAL
            assert Decimal(layer_totals[1]) == FINAL_INVENTORY_VALUE
        else:
            assert Decimal(layer_totals[0]) == Decimal("0")
            assert Decimal(layer_totals[1]) == Decimal("0")

    await _assert_inventory_truth(
        pg,
        tenant,
        batch_id=batch_id,
        vehicle_location_id=vehicle_location_id,
        warehouse=FINAL_WAREHOUSE,
        vehicle=FINAL_VEHICLE,
        cost_quantity=POST_SALE_PHYSICAL,
        cost_value=FINAL_INVENTORY_VALUE,
        expected_cost_events=2,
    )
