"""Cross-domain V1 atomicity and SaaS-isolation closure.

Only missing acceptance is added here. Existing inbound/transfer/stocktake/R1
proofs remain authoritative and are not re-run as duplicate journeys.

Stock and cost are created only through canonical production commands.
Authorization rows are fixture/reference setup, never inventory fixture writes.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.vehicles import load as vehicle_load_api
from api.vehicles.load_schemas import VehicleLoadMutationRequest
from domains.authorization.capabilities import PERMISSIONS
from domains.inventory_vehicle_load import service as vehicle_load_service
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from models import (
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostState,
    InventoryLiveStockProjection,
    InventoryLiveStockWarehouseSummary,
    InventoryLocation,
    InventoryMovement,
    InventoryMovementImpact,
    OperationIdempotency,
    Permission,
    Role,
    UserLocationAccess,
    UserRole,
    role_permissions,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401


D = Decimal

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_FINAL_ATOMICITY_ISOLATION_PG_GATE") != "1",
        reason="Explicit disposable PostgreSQL 16 atomicity/isolation gate only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _grant_role(
    db: AsyncSession,
    *,
    company_id: int,
    driver_id: int,
    codes: set[str],
    location_id: int | None,
    label: str,
) -> int:
    assert codes <= PERMISSIONS
    present = set(
        (
            await db.scalars(
                select(Permission.code).where(Permission.code.in_(codes))
            )
        ).all()
    )
    db.add_all(Permission(code=code) for code in sorted(codes - present))
    await db.flush()
    role = Role(company_id=company_id, name=f"{label}-{uuid4().hex}")
    db.add(role)
    await db.flush()
    permission_ids = list(
        (
            await db.scalars(
                select(Permission.id).where(Permission.code.in_(codes))
            )
        ).all()
    )
    await db.execute(
        role_permissions.insert(),
        [
            {
                "company_id": company_id,
                "role_id": int(role.id),
                "permission_id": int(permission_id),
            }
            for permission_id in permission_ids
        ],
    )
    assignment = {
        "company_id": company_id,
        "role_id": int(role.id),
        "driver_id": driver_id,
    }
    if location_id is None:
        db.add(UserRole(**assignment))
    else:
        db.add(UserLocationAccess(**assignment, location_id=location_id))
    await db.flush()
    return int(role.id)


async def _prepare_party(pg_gate, party: int):
    tenant = pg_gate.tenants[party]

    # Canonical supplier receipt: 12 base units @ 2 = exact inventory value 24.
    receipt = pg_gate.request(
        party=party,
        quantity="12",
        cost="2",
        lot=f"ATOMIC-{party}-{uuid4().hex[:10]}",
    )
    async with pg_gate.session(party) as db:
        assert await pg_gate.post(db, receipt, party=party) == {
            "message": "INBOUND_POSTED"
        }

    # Canonical vehicle creation owns the strict 1:1 custody location.
    async with pg_gate.session(party) as db:
        vehicle = await create_vehicle(
            db,
            company_id=tenant.company_id,
            actor_id=int(tenant.owner.driver_id),
            command=CreateVehicleCommand(
                request_id=str(uuid4()),
                plate_number=f"AT-{party}-{uuid4().hex[:8]}",
                vehicle_type="Van",
                maintenance_status="Active",
            ),
        )
        vehicle_id = int(vehicle["id"])

    async with pg_gate.session(party) as db:
        vehicle_location_id = int(
            await db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == tenant.company_id,
                    InventoryLocation.vehicle_id == vehicle_id,
                    InventoryLocation.location_type == "VEHICLE",
                )
            )
        )

    # Restricted backoffice actor gets only the real mutation capabilities.
    # This is authorization/reference fixture setup, not an inventory mutation.
    async with AsyncSession(pg_gate.admin_engine, expire_on_commit=False) as admin:
        await admin.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(tenant.company_id)},
        )
        await _grant_role(
            admin,
            company_id=tenant.company_id,
            driver_id=tenant.ordinary.driver_id,
            codes={"vehicle.read"},
            location_id=None,
            label="Atomic vehicle read",
        )
        await _grant_role(
            admin,
            company_id=tenant.company_id,
            driver_id=tenant.ordinary.driver_id,
            codes={"inventory.read", "transfer.send", "transfer.destination"},
            location_id=tenant.location_id,
            label="Atomic warehouse mutation",
        )
        vehicle_role_id = await _grant_role(
            admin,
            company_id=tenant.company_id,
            driver_id=tenant.ordinary.driver_id,
            codes={"inventory.read", "transfer.send", "transfer.destination"},
            location_id=vehicle_location_id,
            label="Atomic vehicle mutation",
        )
        await admin.commit()

    return NS(
        tenant=tenant,
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        vehicle_role_id=vehicle_role_id,
        receipt_id=receipt.request_id,
    )


async def _runtime_identity_and_rls(pg_gate, party: int) -> None:
    async with pg_gate.session(party) as db:
        identity = (
            await db.execute(
                text(
                    "SELECT current_user, current_setting('server_version_num')::int, "
                    "r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname=current_user"
                )
            )
        ).one()
        assert identity[0] == "wanasah_app"
        assert 160000 <= int(identity[1]) < 170000
        assert tuple(identity[2:]) == (False, False)
        for table_name in (
            "inventory_balances",
            "inventory_movements",
            "inventory_movement_impacts",
            "inventory_cost_events",
            "inventory_cost_states",
            "operation_idempotency",
            "inventory_live_stock_projection",
            "inventory_live_stock_warehouse_summaries",
        ):
            flags = (
                await db.execute(
                    text(
                        "SELECT relrowsecurity, relforcerowsecurity "
                        "FROM pg_class WHERE oid=to_regclass(:table_name)"
                    ),
                    {"table_name": table_name},
                )
            ).one()
            assert tuple(flags) == (True, True), table_name


async def _truth(pg_gate, party: int, case, request_id: UUID | None = None):
    tenant = case.tenant
    async with pg_gate.session(party) as db:
        warehouse = D(
            await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0))
                .where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.location_id == tenant.location_id,
                    InventoryBalance.product_variant_id == tenant.variant_id,
                )
            )
        )
        vehicle = D(
            await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0))
                .where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.location_id == case.vehicle_location_id,
                    InventoryBalance.product_variant_id == tenant.variant_id,
                )
            )
        )
        total = D(
            await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0))
                .where(
                    InventoryBalance.company_id == tenant.company_id,
                    InventoryBalance.product_variant_id == tenant.variant_id,
                )
            )
        )
        movement_count = int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovement)
                .where(
                    InventoryMovement.company_id == tenant.company_id,
                    InventoryMovement.product_variant_id == tenant.variant_id,
                )
            )
        )
        impact_count = int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryMovementImpact)
                .where(InventoryMovementImpact.company_id == tenant.company_id)
            )
        )
        state = await db.scalar(
            select(InventoryCostState).where(
                InventoryCostState.company_id == tenant.company_id,
                InventoryCostState.product_variant_id == tenant.variant_id,
            )
        )
        cost_events = int(
            await db.scalar(
                select(func.count())
                .select_from(InventoryCostEvent)
                .where(
                    InventoryCostEvent.company_id == tenant.company_id,
                    InventoryCostEvent.product_variant_id == tenant.variant_id,
                )
            )
        )
        projection = await db.scalar(
            select(InventoryLiveStockProjection).where(
                InventoryLiveStockProjection.company_id == tenant.company_id,
                InventoryLiveStockProjection.warehouse_location_id
                == tenant.location_id,
                InventoryLiveStockProjection.product_variant_id
                == tenant.variant_id,
            )
        )
        summary = await db.scalar(
            select(InventoryLiveStockWarehouseSummary).where(
                InventoryLiveStockWarehouseSummary.company_id == tenant.company_id,
                InventoryLiveStockWarehouseSummary.warehouse_location_id
                == tenant.location_id,
            )
        )
        request_rows = 0
        request_completed = 0
        if request_id is not None:
            request_rows = int(
                await db.scalar(
                    select(func.count())
                    .select_from(OperationIdempotency)
                    .where(
                        OperationIdempotency.company_id == tenant.company_id,
                        OperationIdempotency.request_id == str(request_id),
                    )
                )
            )
            request_completed = int(
                await db.scalar(
                    select(func.count())
                    .select_from(OperationIdempotency)
                    .where(
                        OperationIdempotency.company_id == tenant.company_id,
                        OperationIdempotency.request_id == str(request_id),
                        OperationIdempotency.completed_at.is_not(None),
                    )
                )
            )
        assert state is not None
        assert projection is not None
        assert summary is not None
        return {
            "warehouse": warehouse,
            "vehicle": vehicle,
            "total": total,
            "movement_count": movement_count,
            "impact_count": impact_count,
            "cost_quantity": D(state.quantity),
            "cost_value": D(state.inventory_value),
            "cost_events": cost_events,
            "projection": (
                D(projection.warehouse_on_hand),
                D(projection.warehouse_reserved),
                D(projection.warehouse_sellable_on_hand),
                D(projection.warehouse_sellable_reserved),
                bool(projection.has_warehouse_presence),
                int(projection.revision),
            ),
            "summary": (
                int(summary.alert_count),
                int(summary.nonactive_visible_count),
                int(summary.projected_row_count),
                str(summary.projection_state),
                int(summary.revision),
            ),
            "request_rows": request_rows,
            "request_completed": request_completed,
        }


def _payload(case, *, request_id: UUID, quantity: str, warehouse_id: int | None = None):
    return VehicleLoadMutationRequest(
        request_id=request_id,
        warehouse_id=warehouse_id or case.tenant.location_id,
        items=[
            {
                "product_variant_id": case.tenant.variant_id,
                "quantity": D(quantity),
                "stock_status": "AVAILABLE",
            }
        ],
    )


async def _add(pg_gate, party: int, case, payload: VehicleLoadMutationRequest):
    tenant = case.tenant
    async with pg_gate.session(party) as db:
        return await vehicle_load_api.add_vehicle_load(
            case.vehicle_id,
            payload,
            db,
            tenant.ordinary.access(db),
            tenant.ordinary.operational_driver,
        )


async def _unload(pg_gate, party: int, case, payload: VehicleLoadMutationRequest):
    tenant = case.tenant
    async with pg_gate.session(party) as db:
        return await vehicle_load_api.unload_vehicle_load(
            case.vehicle_id,
            payload,
            db,
            tenant.ordinary.access(db),
            tenant.ordinary.operational_driver,
        )


async def test_direct_vehicle_load_precommit_failure_is_fully_atomic_and_retryable(pg):
    case = await _prepare_party(pg, 0)
    await _runtime_identity_and_rls(pg, 0)

    request_id = uuid4()
    payload = _payload(case, request_id=request_id, quantity="4")
    before = await _truth(pg, 0, case, request_id)

    # Independent business expectations are fixed before the mutation.
    assert (
        before["warehouse"],
        before["vehicle"],
        before["total"],
        before["cost_quantity"],
        before["cost_value"],
        before["cost_events"],
        before["request_rows"],
    ) == (
        D("12"),
        D("0"),
        D("12"),
        D("12"),
        D("24"),
        1,
        0,
    )
    assert before["summary"][3] == "READY"
    assert before["projection"][0] == D("12")

    # Inject after the authoritative movement + transactional projection hooks
    # have run, but before the operation record can be completed/committed.
    with patch.object(
        vehicle_load_service,
        "complete_idempotent_operation",
        side_effect=RuntimeError("synthetic failure after vehicle movement"),
    ):
        with pytest.raises(RuntimeError, match="synthetic failure after vehicle movement"):
            await _add(pg, 0, case, payload)

    rolled_back = await _truth(pg, 0, case, request_id)
    assert rolled_back == before
    assert rolled_back["summary"][3] == "READY"
    assert rolled_back["projection"][0] == rolled_back["warehouse"] == D("12")

    # Ambiguous/lost outcome rule: retry the SAME request. It can now succeed
    # exactly once because the failed transaction did not poison idempotency.
    first = await _add(pg, 0, case, payload)
    assert first["direction"] == "ADD" and first["movement_count"] == 1
    after = await _truth(pg, 0, case, request_id)
    assert (
        after["warehouse"],
        after["vehicle"],
        after["total"],
        after["cost_quantity"],
        after["cost_value"],
        after["cost_events"],
        after["request_rows"],
        after["request_completed"],
    ) == (
        D("8"),
        D("4"),
        D("12"),
        D("12"),
        D("24"),
        1,
        1,
        1,
    )
    assert after["movement_count"] == before["movement_count"] + 1
    assert after["impact_count"] == before["impact_count"] + 2
    assert after["projection"][0] == D("8")
    assert after["summary"][3] == "READY"

    # Exact replay is side-effect free.
    assert await _add(pg, 0, case, payload) == first
    assert await _truth(pg, 0, case, request_id) == after

    # Reusing the same identity with changed cargo is a hard conflict and does
    # not roll forward any partial balance/projection/idempotency evidence.
    changed = _payload(case, request_id=request_id, quantity="3")
    with pytest.raises(HTTPException) as mismatch:
        await _add(pg, 0, case, changed)
    assert mismatch.value.status_code == 409
    assert mismatch.value.detail["code"] == "VEHICLE_LOAD_IDEMPOTENCY_CONFLICT"
    assert await _truth(pg, 0, case, request_id) == after


async def test_direct_vehicle_mutation_request_identity_is_tenant_scoped_and_revocation_fails_closed(pg):
    left, right = await asyncio.gather(
        _prepare_party(pg, 0),
        _prepare_party(pg, 1),
    )
    await _runtime_identity_and_rls(pg, 0)
    await _runtime_identity_and_rls(pg, 1)

    shared_request_id = uuid4()
    left_payload = _payload(left, request_id=shared_request_id, quantity="2")
    right_payload = _payload(right, request_id=shared_request_id, quantity="2")

    # Same UUID + same operation is intentionally independent across tenants.
    left_result, right_result = await asyncio.gather(
        _add(pg, 0, left, left_payload),
        _add(pg, 1, right, right_payload),
    )
    assert left_result["direction"] == right_result["direction"] == "ADD"

    left_truth = await _truth(pg, 0, left, shared_request_id)
    right_truth = await _truth(pg, 1, right, shared_request_id)
    for truth in (left_truth, right_truth):
        assert (
            truth["warehouse"],
            truth["vehicle"],
            truth["total"],
            truth["cost_quantity"],
            truth["cost_value"],
            truth["request_rows"],
            truth["request_completed"],
        ) == (
            D("10"),
            D("2"),
            D("12"),
            D("12"),
            D("24"),
            1,
            1,
        )

    # FORCE RLS: even an unscoped request-id lookup sees only this tenant's row.
    for party, case in ((0, left), (1, right)):
        async with pg.session(party) as db:
            rows = list(
                (
                    await db.scalars(
                        select(OperationIdempotency).where(
                            OperationIdempotency.request_id
                            == str(shared_request_id)
                        )
                    )
                ).all()
            )
            assert len(rows) == 1
            assert rows[0].company_id == case.tenant.company_id

    baseline_left = await _truth(pg, 0, left)
    baseline_right = await _truth(pg, 1, right)

    # Foreign vehicle identity cannot be rebound to the current company.
    forged_vehicle = _payload(left, request_id=uuid4(), quantity="1")
    async with pg.session(0) as db:
        with pytest.raises(HTTPException) as foreign_vehicle:
            await vehicle_load_api.add_vehicle_load(
                right.vehicle_id,
                forged_vehicle,
                db,
                left.tenant.ordinary.access(db),
                left.tenant.ordinary.operational_driver,
            )
        assert foreign_vehicle.value.status_code in {404, 409}
    assert await _truth(pg, 0, left) == baseline_left
    assert await _truth(pg, 1, right) == baseline_right

    # Foreign location and an ungranted same-company location both fail before
    # an idempotency row/movement is allowed to persist.
    for warehouse_id in (
        right.tenant.location_id,
        left.tenant.other_location_id,
    ):
        forged_id = uuid4()
        forged = _payload(
            left,
            request_id=forged_id,
            quantity="1",
            warehouse_id=warehouse_id,
        )
        with pytest.raises(HTTPException) as denied:
            await _add(pg, 0, left, forged)
        assert denied.value.status_code in {403, 404}
        truth = await _truth(pg, 0, left, forged_id)
        assert truth["request_rows"] == 0
        for key in (
            "warehouse",
            "vehicle",
            "total",
            "movement_count",
            "impact_count",
            "cost_quantity",
            "cost_value",
            "cost_events",
            "projection",
            "summary",
        ):
            assert truth[key] == baseline_left[key], key

    # Revoke only the Vehicle location grants between requests. Authorization is
    # evaluated before replay, so even the completed ADD identity cannot bypass
    # the newly revoked persisted grant.
    async with AsyncSession(pg.admin_engine, expire_on_commit=False) as admin:
        await admin.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": str(left.tenant.company_id)},
        )
        await admin.execute(
            UserLocationAccess.__table__.delete().where(
                UserLocationAccess.company_id == left.tenant.company_id,
                UserLocationAccess.driver_id == left.tenant.ordinary.driver_id,
                UserLocationAccess.location_id == left.vehicle_location_id,
            )
        )
        await admin.commit()

    with pytest.raises(HTTPException) as revoked_replay:
        await _add(pg, 0, left, left_payload)
    assert revoked_replay.value.status_code == 403
    assert await _truth(pg, 0, left, shared_request_id) == left_truth

    unload_id = uuid4()
    with pytest.raises(HTTPException) as revoked_unload:
        await _unload(
            pg,
            0,
            left,
            _payload(left, request_id=unload_id, quantity="1"),
        )
    assert revoked_unload.value.status_code == 403
    assert (await _truth(pg, 0, left, unload_id))["request_rows"] == 0

    # Revocation in company A cannot alter company B's replay identity or truth.
    assert await _add(pg, 1, right, right_payload) == right_result
    assert await _truth(pg, 1, right, shared_request_id) == right_truth
