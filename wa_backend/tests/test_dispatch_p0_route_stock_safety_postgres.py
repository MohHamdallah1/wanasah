"""P0: status/assignment cannot post physical stock; only explicit Adjust Load can."""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
import httpx
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from api import dispatch
from main import app
from database import engine as http_runtime_engine
from domains.identity.models import CompanyPrincipal
from domains.inventory_vehicle_load.service import mutate_vehicle_load
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from models import (
    Company, DispatchRoute, InventoryBalance, InventoryCostEvent, InventoryLocation,
    InventoryMovement, OperationIdempotency, utc_now,
)
from schemas import AdjustRouteInventoryRequest, DispatchRouteRequest, UpdateRouteStatusRequest
from services import recover_idempotent_operation
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_live_stock_v1_route_sale_unload_postgres import (
    _seed_commercial_master, _seed_mobile_uom_and_field,
)

D = Decimal
pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_P0_PG_GATE") != "1",
        reason="Requires explicit isolated PG16 Dispatch safety fixture",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _snapshot(gate, tenant, vehicle_locations):
    location_ids = [tenant.location_id, *vehicle_locations]
    async with gate.session() as db:
        rows = (await db.execute(
            select(InventoryBalance.location_id, InventoryBalance.batch_id,
                   InventoryBalance.stock_status,
                   func.sum(InventoryBalance.on_hand_quantity),
                   func.sum(InventoryBalance.reserved_quantity))
            .where(InventoryBalance.company_id == tenant.company_id,
                   InventoryBalance.product_variant_id == tenant.variant_id,
                   InventoryBalance.location_id.in_(location_ids))
            .group_by(InventoryBalance.location_id, InventoryBalance.batch_id,
                      InventoryBalance.stock_status)
        )).all()
        movements = int(await db.scalar(
            select(func.count()).select_from(InventoryMovement)
            .where(InventoryMovement.company_id == tenant.company_id)) or 0)
        financial = int(await db.scalar(
            select(func.count()).select_from(InventoryCostEvent)
            .where(InventoryCostEvent.company_id == tenant.company_id)) or 0)
        return {
            "rows": {
                (int(loc), int(batch), str(status)): (D(on_hand), D(reserved))
                for loc, batch, status, on_hand, reserved in rows
            },
            "movements": movements,
            "cost_events": financial,
        }


def _total(snapshot, loc):
    return sum((on_hand for (location, _, status), (on_hand, _) in snapshot["rows"].items()
                if location == loc and status == "AVAILABLE"), D("0"))


async def _route_adjust_context(gate, route_id):
    async with gate.session() as db:
        route = await db.get(DispatchRoute, route_id)
        assert route is not None and route.vehicle_id is not None and route.source_location_id is not None
        return {
            "version": "ADJUST_LOAD_CONTEXT_V2",
            "vehicle_id": int(route.vehicle_id),
            "source_warehouse_id": int(route.source_location_id),
            "work_session_id": int(route.work_session_id) if route.work_session_id is not None else None,
            "route_context_revision": int(route.adjustment_context_revision),
        }


async def _vehicle(gate, tenant):
    async with gate.session() as db:
        result = await create_vehicle(
            db,
            company_id=tenant.company_id,
            actor_id=int(tenant.owner.operational_driver.id),
            command=CreateVehicleCommand(
                request_id=str(uuid4()), plate_number="P0S-" + uuid4().hex[:10],
                vehicle_type="Van", maintenance_status="Active",
            ),
        )
        vehicle_id = int(result["id"])
        location = await db.scalar(
            select(InventoryLocation.id).where(
                InventoryLocation.company_id == tenant.company_id,
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
                InventoryLocation.is_active.is_(True),
            )
        )
        assert location is not None
        return vehicle_id, int(location)


@pytest.mark.parametrize("base_qty", [D("1"), D("8"), D("25"), D("32")])
async def test_route_status_never_mutates_stock_even_with_legacy_carton_targets(pg, base_qty):
    tenant = pg.tenants[0]
    field = await _seed_mobile_uom_and_field(pg, tenant)
    zone_id, _ = await _seed_commercial_master(pg, tenant, field)
    # Two genuine receipts/lots, preserving FEFO and financial provenance.
    for count in ("16", "64"):
        request = pg.request(
            lot="P0-STATUS-" + uuid4().hex[:12], quantity=count, cost="2",
        )
        async with pg.session() as db:
            assert await pg.post(db, request) == {"message": "INBOUND_POSTED"}

    vehicle_id, vehicle_loc = await _vehicle(pg, tenant)
    async with pg.session() as db:
        posted = await mutate_vehicle_load(
            db,
            access=tenant.owner.access(db), actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id, warehouse_id=tenant.location_id,
            direction="ADD", request_id=uuid4(),
            items=[{"product_variant_id": tenant.variant_id, "quantity": base_qty}],
        )
        assert posted["movement_count"] > 0

    route_request = DispatchRouteRequest(
        zone_id=zone_id, driver_id=field.driver.id, vehicle_id=vehicle_id,
        source_location_id=tenant.location_id,
        inventory_base={str(tenant.variant_id): base_qty},
        expected_inventory_base={str(tenant.variant_id): base_qty},
    )
    async with pg.session() as db:
        route_result = await dispatch.dispatch_route(
            route_request, db, tenant.owner.access(db), tenant.owner.operational_driver,
        )
    route_id = int(route_result["route_id"])
    before = await _snapshot(pg, tenant, [vehicle_loc])
    assert _total(before, vehicle_loc) == base_qty
    assert _total(before, tenant.location_id) == D("80") - base_qty

    # The old path WOULD unload one loose pack for 25 -> 3 cartons, or ALL
    # loose-only stock for 1 -> 0 cartons. Exercise actual canonical movement
    # in a disposable transaction, then roll it back before production API proof.
    legacy_cartons = int(base_qty // D("8"))
    if base_qty % D("8"):
        async with pg.session() as db:
            route = await db.get(DispatchRoute, route_id)
            assert route is not None
            legacy = await dispatch._dispatch_absolute_targets(
                db, company_id=tenant.company_id, route=route,
                legacy_actor_id=tenant.owner.driver_id,
                session=None, inventory={str(tenant.variant_id): legacy_cartons},
            )
            assert legacy == "DIRECT"
            after_legacy_on_hand = await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0))
                .where(InventoryBalance.company_id == tenant.company_id,
                       InventoryBalance.location_id == vehicle_loc,
                       InventoryBalance.product_variant_id == tenant.variant_id,
                       InventoryBalance.stock_status == "AVAILABLE")
            )
            assert D(after_legacy_on_hand) == base_qty - (base_qty % D("8"))
            await db.rollback()
        assert await _snapshot(pg, tenant, [vehicle_loc]) == before

    for stock_target in ({str(tenant.variant_id): legacy_cartons}, {}):
        async with pg.session() as db:
            with pytest.raises(HTTPException) as denied:
                await dispatch.update_route_status(
                    route_id, UpdateRouteStatusRequest(status="waiting", inventory=stock_target),
                    db, tenant.owner.access(db), tenant.owner.operational_driver,
                )
            assert denied.value.status_code == 409
            assert denied.value.detail["code"] == "DISPATCH_ROUTE_STATUS_INVENTORY_FORBIDDEN"
        assert await _snapshot(pg, tenant, [vehicle_loc]) == before

    # Pure status calls can transition both ways without inventory data.
    for status in ("waiting", "active"):
        async with pg.session() as db:
            result = await dispatch.update_route_status(
                route_id, UpdateRouteStatusRequest(status=status),
                db, tenant.owner.access(db), tenant.owner.operational_driver,
            )
            assert result["message"] == "تم تحديث خط السير بنجاح"
        assert await _snapshot(pg, tenant, [vehicle_loc]) == before

    # A restricted reader cannot bypass route.execute by directly calling API.
    async with pg.session() as db:
        with pytest.raises(HTTPException) as denied:
            await dispatch.update_route_status(
                route_id, UpdateRouteStatusRequest(status="waiting"),
                db, tenant.ordinary.access(db), tenant.ordinary.operational_driver,
            )
        assert denied.value.status_code == 403
    assert await _snapshot(pg, tenant, [vehicle_loc]) == before

    if base_qty == D("25"):
        # Explicit operation is precise, idempotent, and independently audited.
        adjustment = AdjustRouteInventoryRequest(
            request_id=uuid4(),
            context=await _route_adjust_context(pg, route_id),
            deltas=[{"product_id": tenant.variant_id, "delta_base": D("1")}],
        )
        async with pg.session() as db:
            result = await dispatch.adjust_route_inventory(
                route_id, adjustment, db,
                tenant.owner.access(db), tenant.owner.operational_driver,
            )
            assert result["mode"] == "DIRECT"
        after_explicit = await _snapshot(pg, tenant, [vehicle_loc])
        assert _total(after_explicit, vehicle_loc) == D("26")
        assert _total(after_explicit, tenant.location_id) == D("54")
        assert after_explicit["movements"] > before["movements"]
        assert after_explicit["cost_events"] == before["cost_events"]
        async with pg.session() as db:
            replay = await dispatch.adjust_route_inventory(
                route_id, adjustment, db,
                tenant.owner.access(db), tenant.owner.operational_driver,
            )
            assert replay == result
        assert await _snapshot(pg, tenant, [vehicle_loc]) == after_explicit


async def test_vehicle_reassignment_only_changes_route_assignment_not_custody(pg):
    tenant = pg.tenants[0]
    field = await _seed_mobile_uom_and_field(pg, tenant)
    zone_id, _ = await _seed_commercial_master(pg, tenant, field)
    async with pg.session() as db:
        assert await pg.post(
            db, pg.request(lot="P0-VEH-" + uuid4().hex[:10], quantity="40", cost="2")
        ) == {"message": "INBOUND_POSTED"}
    first, loc_first = await _vehicle(pg, tenant)
    second, loc_second = await _vehicle(pg, tenant)
    async with pg.session() as db:
        await mutate_vehicle_load(
            db, access=tenant.owner.access(db), actor_id=tenant.owner.driver_id,
            vehicle_id=first, warehouse_id=tenant.location_id, direction="ADD",
            request_id=uuid4(),
            items=[{"product_variant_id": tenant.variant_id, "quantity": D("25")}],
        )
    async with pg.session() as db:
        created = await dispatch.dispatch_route(
            DispatchRouteRequest(
                zone_id=zone_id, driver_id=field.driver.id, vehicle_id=first,
                source_location_id=tenant.location_id,
                inventory_base={str(tenant.variant_id): D("25")},
                expected_inventory_base={str(tenant.variant_id): D("25")},
            ), db, tenant.owner.access(db), tenant.owner.operational_driver,
        )
    route_id = int(created["route_id"])
    before = await _snapshot(pg, tenant, [loc_first, loc_second])
    async with pg.session() as db:
        await dispatch.update_route_status(
            route_id, UpdateRouteStatusRequest(status="waiting"),
            db, tenant.owner.access(db), tenant.owner.operational_driver,
        )
    async with pg.session() as db:
        await dispatch.update_route_status(
            route_id, UpdateRouteStatusRequest(vehicleId=second),
            db, tenant.owner.access(db), tenant.owner.operational_driver,
        )
        route = await db.get(DispatchRoute, route_id)
        assert int(route.vehicle_id) == second
    assert await _snapshot(pg, tenant, [loc_first, loc_second]) == before
    assert _total(before, loc_first) == D("25")
    assert _total(before, loc_second) == D("0")


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_actual_fastapi_bearer_http_status_and_adjust_are_exact_and_idempotent(pg):
    """Real production FastAPI router/login, actual restricted app engine and PG16.

    The React route-only payload and explicit Adjust Load body are frozen by the
    focused Dashboard wire serializer tests; NO handler invocation or auth mocks.
    """
    tenant, foreign = pg.tenants
    field = await _seed_mobile_uom_and_field(pg, tenant)
    zone, _ = await _seed_commercial_master(pg, tenant, field)
    for qty in ("16", "64"):
        async with pg.session() as db:
            assert await pg.post(db, pg.request(
                lot="P0-WIRE-" + uuid4().hex[:10], quantity=qty, cost="2",
            )) == {"message": "INBOUND_POSTED"}
    vehicle_id, vehicle_location = await _vehicle(pg, tenant)
    second_vehicle_id, second_vehicle_location = await _vehicle(pg, tenant)
    async with pg.session() as db:
        await mutate_vehicle_load(
            db, access=tenant.owner.access(db), actor_id=tenant.owner.driver_id,
            vehicle_id=vehicle_id, warehouse_id=tenant.location_id,
            direction="ADD", request_id=uuid4(),
            items=[{"product_variant_id": tenant.variant_id, "quantity": D("25")}],
        )
    async with pg.session() as db:
        created = await dispatch.dispatch_route(
            DispatchRouteRequest(
                zone_id=zone, driver_id=field.driver.id, vehicle_id=vehicle_id,
                source_location_id=tenant.location_id,
                inventory_base={str(tenant.variant_id): D("25")},
                expected_inventory_base={str(tenant.variant_id): D("25")},
            ),
            db, tenant.owner.access(db), tenant.owner.operational_driver,
        )
    route_id = int(created["route_id"])
    before = await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location])
    assert (_total(before, vehicle_location), _total(before, tenant.location_id)) == (D("25"), D("55"))
    assert not app.dependency_overrides
    assert any(route.path == "/dispatch/route/{route_id}/status" and "PUT" in (route.methods or ())
               for route in app.routes)
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(pg.admin_engine) as db:
        credentials = []
        for company, actor in ((tenant, tenant.owner), (foreign, foreign.owner)):
            code = await db.scalar(select(Company.company_code).where(Company.id == company.company_id))
            username = await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == actor.context.principal_id))
            credentials.append((code, username))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://dispatch-physical-pg16.test") as client:
            tokens = []
            for (code, username) in credentials:
                login = await client.post("/login", json={
                    "company_code": code, "username": username,
                    "password": "NoLotSyntheticFixture123",
                })
                assert login.status_code == 200, login.text
                tokens.append(login.json()["token"])
            headers = {"Authorization": "Bearer " + tokens[0]}
            foreign_headers = {"Authorization": "Bearer " + tokens[1]}
            endpoint = f"/dispatch/route/{route_id}/status"
            for forbidden in ({str(tenant.variant_id): 3}, {}):
                response = await client.put(endpoint, headers=headers, json={
                    "status": "waiting", "inventory": forbidden,
                })
                assert response.status_code == 409, response.text
                assert response.json()["error"]["code"] == "DISPATCH_ROUTE_STATUS_INVENTORY_FORBIDDEN"
                assert response.headers.get("x-request-id")
                assert await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location]) == before
            # The exact route-only Dashboard body has no inventory property.
            route_only = {"status": "waiting", "driverId": str(field.driver.id),
                          "vehicleId": str(vehicle_id)}
            updated = await client.put(endpoint, headers=headers, json=route_only)
            assert updated.status_code == 200, updated.text
            active = await client.put(endpoint, headers=headers, json={**route_only, "status": "active"})
            assert active.status_code == 200, active.text
            assert await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location]) == before
            stranger = await client.put(endpoint, headers=foreign_headers, json=route_only)
            assert stranger.status_code in (403, 404), stranger.text
            assert await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location]) == before

            # Server-side ABA proof: a contextless request that was constructed
            # before V1 -> V2 -> V1 must never become a new executable operation,
            # even if the old visible Vehicle/Warehouse headers match again.
            contextless_absent = {
                "request_id": str(uuid4()),
                "deltas": [{"product_id": tenant.variant_id, "delta_base": "1"}],
            }
            waiting = await client.put(endpoint, headers=headers, json={**route_only, "status": "waiting"})
            assert waiting.status_code == 200, waiting.text
            to_second = await client.put(endpoint, headers=headers, json={
                "status": "waiting", "driverId": str(field.driver.id),
                "vehicleId": str(second_vehicle_id),
            })
            assert to_second.status_code == 200, to_second.text
            back_first = await client.put(endpoint, headers=headers, json=route_only)
            assert back_first.status_code == 200, back_first.text
            reactivated = await client.put(endpoint, headers=headers, json={**route_only, "status": "active"})
            assert reactivated.status_code == 200, reactivated.text
            aba_before = await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location])
            expected_headers = {**headers,
                "X-Dispatch-Expected-Vehicle-Id": str(vehicle_id),
                "X-Dispatch-Expected-Source-Warehouse-Id": str(tenant.location_id)}
            adjust_path = f"/dispatch/route/{route_id}/adjust_inventory"
            absent = await client.put(adjust_path, headers=expected_headers, json=contextless_absent)
            assert absent.status_code == 409, absent.text
            assert absent.json()["error"]["code"] == "DISPATCH_ADJUSTMENT_CONTEXT_REQUIRED"
            assert await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location]) == aba_before
            async with pg.session() as db:
                assert await db.scalar(select(func.count()).select_from(OperationIdempotency).where(
                    OperationIdempotency.company_id == tenant.company_id,
                    OperationIdempotency.operation == "DISPATCH_ADJUST_ROUTE_INVENTORY",
                    OperationIdempotency.request_id == contextless_absent["request_id"],
                )) == 0

            adjustment = {
                "request_id": str(uuid4()),
                "context": await _route_adjust_context(pg, route_id),
                "deltas": [{"product_id": tenant.variant_id, "delta_base": "1"}],
            }
            recovery_path = f"/dispatch/route/{route_id}/adjust_inventory/recovery"
            initial_probe = await client.post(recovery_path, headers=headers, json=adjustment)
            assert initial_probe.status_code == 200, initial_probe.text
            assert initial_probe.json() == {
                "state": "NOT_CONFIRMED", "request_id": adjustment["request_id"],
            }
            foreign_probe = await client.post(recovery_path, headers=foreign_headers, json=adjustment)
            assert foreign_probe.status_code in (403, 404), foreign_probe.text
            assert await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location]) == before
            stale = await client.put(adjust_path, headers=expected_headers, json={
                **adjustment,
                "context": {**adjustment["context"], "route_context_revision": adjustment["context"]["route_context_revision"] - 1},
            })
            assert stale.status_code == 409, stale.text
            assert stale.json()["error"]["code"] == "DISPATCH_ROUTE_CONTEXT_CHANGED"
            assert await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location]) == aba_before
            response = await client.put(adjust_path,
                                        headers=expected_headers, json=adjustment)
            assert response.status_code == 200, response.text
            assert response.json()["mode"] == "DIRECT"
            after = await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location])
            assert (_total(after, vehicle_location), _total(after, tenant.location_id)) == (D("26"), D("54"))
            assert after["movements"] > before["movements"]
            assert after["cost_events"] == before["cost_events"]
            replay = await client.put(adjust_path,
                                      headers=expected_headers, json=adjustment)
            assert replay.status_code == 200 and replay.json() == response.json(), replay.text
            assert await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location]) == after
            # Exact UUID and canonical payload verification never replays the
            # old operation. A changed payload is a conflict, not a new UUID.
            verified = await client.post(recovery_path, headers=headers, json=adjustment)
            assert verified.status_code == 200, verified.text
            assert verified.json() == {
                "state": "COMMITTED", "request_id": adjustment["request_id"],
                "response": response.json(),
            }
            mismatched = await client.post(recovery_path, headers=headers, json={
                "request_id": adjustment["request_id"],
                "deltas": [{"product_id": tenant.variant_id, "delta_base": "8"}],
            })
            assert mismatched.status_code == 409, mismatched.text
            assert mismatched.json()["error"]["code"] == "DISPATCH_RECOVERY_PAYLOAD_CONFLICT"
            assert await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location]) == after

            # COMMITTED always wins over a later cancellation attempt and returns
            # the original evidence without replay.
            cancel_path = recovery_path + "/cancel"
            committed_cancel = await client.post(cancel_path, headers=headers, json=adjustment)
            assert committed_cancel.status_code == 200, committed_cancel.text
            assert committed_cancel.json() == {
                "state": "COMMITTED", "request_id": adjustment["request_id"],
                "response": response.json(),
            }
            assert await _snapshot(pg, tenant, [vehicle_location, second_vehicle_location]) == after

            # NOT_CONFIRMED -> immutable CANCELLED terminal fence. Repeated
            # cancellation is idempotent and every late original arrival is 409.
            cancelled_request = {
                "request_id": str(uuid4()),
                "deltas": [{"product_id": tenant.variant_id, "delta_base": "8"}],
            }
            probe = await client.post(recovery_path, headers=headers, json=cancelled_request)
            assert probe.status_code == 200 and probe.json()["state"] == "NOT_CONFIRMED", probe.text
            cancel_before = await _snapshot(pg, tenant, [vehicle_location])
            first_cancel = await client.post(cancel_path, headers=headers, json=cancelled_request)
            second_cancel = await client.post(cancel_path, headers=headers, json=cancelled_request)
            assert first_cancel.status_code == second_cancel.status_code == 200
            assert first_cancel.json()["state"] == second_cancel.json()["state"] == "CANCELLED"
            assert await _snapshot(pg, tenant, [vehicle_location]) == cancel_before
            late = await client.put(adjust_path, headers=expected_headers, json=cancelled_request)
            assert late.status_code == 409, late.text
            assert late.json()["error"]["code"] == "DISPATCH_ADJUSTMENT_CANCELLED"
            assert await _snapshot(pg, tenant, [vehicle_location]) == cancel_before
            cancel_mismatch = await client.post(cancel_path, headers=headers, json={
                "request_id": cancelled_request["request_id"],
                "deltas": [{"product_id": tenant.variant_id, "delta_base": "1"}],
            })
            assert cancel_mismatch.status_code == 409, cancel_mismatch.text
            assert cancel_mismatch.json()["error"]["code"] == "DISPATCH_RECOVERY_PAYLOAD_CONFLICT"
            async with pg.session() as db:
                tombstone = await db.scalar(select(OperationIdempotency).where(
                    OperationIdempotency.company_id == tenant.company_id,
                    OperationIdempotency.operation == "DISPATCH_ADJUST_ROUTE_INVENTORY",
                    OperationIdempotency.request_id == cancelled_request["request_id"],
                ))
                assert tombstone is not None
                assert tombstone.state == "CANCELLED"
                assert tombstone.response_json is None and tombstone.completed_at is None
                assert tombstone.cancelled_at is not None
                assert int(tombstone.cancelled_by) == int(tenant.owner.driver_id)

            # DB-level terminal permanence: neither a direct rewrite nor delete
            # may remove a CANCELLED fence, even outside application helpers.
            async with pg.session() as db:
                with pytest.raises(IntegrityError):
                    await db.execute(text("""
                        UPDATE operation_idempotency
                        SET state = 'PENDING', cancelled_at = NULL, cancelled_by = NULL
                        WHERE company_id = :company
                          AND operation = 'DISPATCH_ADJUST_ROUTE_INVENTORY'
                          AND request_id = :request_id
                    """), {
                        "company": tenant.company_id,
                        "request_id": cancelled_request["request_id"],
                    })
                    await db.flush()
                await db.rollback()
            async with pg.session() as db:
                with pytest.raises(IntegrityError):
                    await db.execute(text("""
                        DELETE FROM operation_idempotency
                        WHERE company_id = :company
                          AND operation = 'DISPATCH_ADJUST_ROUTE_INVENTORY'
                          AND request_id = :request_id
                    """), {
                        "company": tenant.company_id,
                        "request_id": cancelled_request["request_id"],
                    })
                    await db.flush()
                await db.rollback()
            assert await _snapshot(pg, tenant, [vehicle_location]) == cancel_before

            # Rolling-upgrade compatibility: a legacy direct writer may omit
            # the new state column entirely. The original completion pair remains
            # authoritative and is observed as COMMITTED without replay.
            legacy_null = AdjustRouteInventoryRequest(
                request_id=uuid4(),
                deltas=[{"product_id": tenant.variant_id, "delta_base": D("1")}],
            )
            legacy_null_hash = dispatch._dispatch_adjust_request_hash(route_id, legacy_null)
            legacy_null_response = {"mode": "NO_CHANGE"}
            async with pg.session() as db:
                db.add(OperationIdempotency(
                    company_id=tenant.company_id,
                    operation="DISPATCH_ADJUST_ROUTE_INVENTORY",
                    request_id=str(legacy_null.request_id),
                    request_hash=legacy_null_hash,
                    created_by=tenant.owner.driver_id,
                    state=None,
                    response_json=legacy_null_response,
                    completed_at=utc_now(),
                ))
                await db.commit()
            legacy_null_json = legacy_null.model_dump(mode="json")
            legacy_probe = await client.post(recovery_path, headers=headers, json=legacy_null_json)
            assert legacy_probe.status_code == 200
            assert legacy_probe.json() == {
                "state": "COMMITTED",
                "request_id": str(legacy_null.request_id),
                "response": legacy_null_response,
            }
            legacy_retry = await client.put(adjust_path, headers=expected_headers, json=legacy_null_json)
            assert legacy_retry.status_code == 200
            assert legacy_retry.json() == legacy_null_response
            assert await _snapshot(pg, tenant, [vehicle_location]) == cancel_before

            # A rolled-back cancellation attempt leaves no tombstone; retrying
            # the read-only proof remains NOT_CONFIRMED.
            rollback_request = AdjustRouteInventoryRequest(
                request_id=uuid4(),
                deltas=[{"product_id": tenant.variant_id, "delta_base": D("1")}],
            )
            rollback_hash = dispatch._dispatch_adjust_request_hash(route_id, rollback_request)
            async with pg.session() as db:
                state, _ = await recover_idempotent_operation(
                    db, company_id=tenant.company_id, actor_id=tenant.owner.driver_id,
                    operation="DISPATCH_ADJUST_ROUTE_INVENTORY",
                    request_id=str(rollback_request.request_id), request_hash=rollback_hash,
                    cancel_if_absent=True,
                )
                assert state == "CANCELLED"
                await db.rollback()
            rollback_probe = await client.post(
                recovery_path, headers=headers, json=rollback_request.model_dump(mode="json")
            )
            assert rollback_probe.status_code == 200
            assert rollback_probe.json()["state"] == "NOT_CONFIRMED"

            # Persisted incomplete evidence is forensic INDETERMINATE: neither
            # cancellation nor the original operation may advance it.
            indeterminate = AdjustRouteInventoryRequest(
                request_id=uuid4(),
                deltas=[{"product_id": tenant.variant_id, "delta_base": D("1")}],
            )
            indeterminate_hash = dispatch._dispatch_adjust_request_hash(route_id, indeterminate)
            async with pg.session() as db:
                db.add(OperationIdempotency(
                    company_id=tenant.company_id,
                    operation="DISPATCH_ADJUST_ROUTE_INVENTORY",
                    request_id=str(indeterminate.request_id),
                    request_hash=indeterminate_hash,
                    created_by=tenant.owner.driver_id,
                    state="PENDING",
                ))
                await db.commit()
            indeterminate_json = indeterminate.model_dump(mode="json")
            forensic = await client.post(recovery_path, headers=headers, json=indeterminate_json)
            assert forensic.status_code == 200 and forensic.json()["state"] == "INDETERMINATE"
            forensic_cancel = await client.post(cancel_path, headers=headers, json=indeterminate_json)
            assert forensic_cancel.status_code == 409
            assert forensic_cancel.json()["error"]["code"] == "DISPATCH_RECOVERY_INDETERMINATE"
            forensic_late = await client.put(adjust_path, headers=expected_headers, json=indeterminate_json)
            assert forensic_late.status_code == 409
            assert forensic_late.json()["error"]["code"] == "DISPATCH_ADJUSTMENT_INDETERMINATE"
            assert await _snapshot(pg, tenant, [vehicle_location]) == cancel_before

            # Actor mismatch is detected under the unique identity rather than
            # being mistaken for an absent request.
            actor_request = AdjustRouteInventoryRequest(
                request_id=uuid4(),
                deltas=[{"product_id": tenant.variant_id, "delta_base": D("1")}],
            )
            actor_hash = dispatch._dispatch_adjust_request_hash(route_id, actor_request)
            async with pg.session() as db:
                db.add(OperationIdempotency(
                    company_id=tenant.company_id,
                    operation="DISPATCH_ADJUST_ROUTE_INVENTORY",
                    request_id=str(actor_request.request_id),
                    request_hash=actor_hash,
                    created_by=tenant.ordinary.driver_id,
                    state="PENDING",
                ))
                await db.commit()
            actor_conflict = await client.post(
                cancel_path, headers=headers, json=actor_request.model_dump(mode="json")
            )
            assert actor_conflict.status_code == 409
            assert actor_conflict.json()["error"]["code"] == "DISPATCH_RECOVERY_ACTOR_CONFLICT"

            # Current route authorization is still mandatory for cancellation.
            async with pg.session() as db:
                with pytest.raises(HTTPException) as denied_cancel:
                    await dispatch.cancel_route_adjust_recovery(
                        route_id,
                        AdjustRouteInventoryRequest(
                            request_id=uuid4(),
                            deltas=[{"product_id": tenant.variant_id, "delta_base": D("1")}],
                        ),
                        db, tenant.ordinary.access(db), tenant.ordinary.operational_driver,
                    )
                assert denied_cancel.value.status_code == 403

            # Two cancellation clients serialize on the exact canonical lock.
            double_cancel = {
                "request_id": str(uuid4()),
                "deltas": [{"product_id": tenant.variant_id, "delta_base": "1"}],
            }
            double_before = await _snapshot(pg, tenant, [vehicle_location])
            first, second = await asyncio.gather(
                client.post(cancel_path, headers=headers, json=double_cancel),
                client.post(cancel_path, headers=headers, json=double_cancel),
            )
            assert first.status_code == second.status_code == 200
            assert first.json()["state"] == second.json()["state"] == "CANCELLED"
            assert await _snapshot(pg, tenant, [vehicle_location]) == double_before

            # Simultaneous original execution vs cancellation has exactly one
            # authoritative winner under the same advisory lock.
            race_request = {
                "request_id": str(uuid4()),
                "context": await _route_adjust_context(pg, route_id),
                "deltas": [{"product_id": tenant.variant_id, "delta_base": "1"}],
            }
            race_before = await _snapshot(pg, tenant, [vehicle_location])
            executed, cancelled = await asyncio.gather(
                client.put(adjust_path, headers=expected_headers, json=race_request),
                client.post(cancel_path, headers=headers, json=race_request),
            )
            race_after = await _snapshot(pg, tenant, [vehicle_location])
            if executed.status_code == 200:
                assert executed.json()["mode"] == "DIRECT"
                assert cancelled.status_code == 200 and cancelled.json()["state"] == "COMMITTED"
                assert _total(race_after, vehicle_location) == _total(race_before, vehicle_location) + D("1")
                assert _total(race_after, tenant.location_id) == _total(race_before, tenant.location_id) - D("1")
                assert race_after["movements"] > race_before["movements"]
            else:
                assert executed.status_code == 409
                assert executed.json()["error"]["code"] == "DISPATCH_ADJUSTMENT_CANCELLED"
                assert cancelled.status_code == 200 and cancelled.json()["state"] == "CANCELLED"
                assert race_after == race_before
            assert race_after["cost_events"] == race_before["cost_events"]
    finally:
        await http_runtime_engine.dispose()
