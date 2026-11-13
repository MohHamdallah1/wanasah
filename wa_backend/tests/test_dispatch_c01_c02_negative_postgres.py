"""Only C02 new threat boundaries: signed stock revisions, active routes, unsettled sessions."""
from __future__ import annotations
import os
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from context import tenant_context
from models import DispatchRoute, Zone
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from services import apply_inventory_movements_batch
from tests.test_dispatch_m03_period_postgres import gate
from tests.test_dispatch_c01_c02_custody_postgres import (
    _field_proof, _login_owner, _movement_count, _offer, _setup_cars,
)

pytestmark = [
    pytest.mark.skipif(os.getenv("RUN_C01_C02_CUSTODY_PG16") != "1",
                       reason="Disposable C02 PostgreSQL16/Bearer isolation only"),
    pytest.mark.asyncio(loop_scope="module"),
]


async def test_c02_snapshot_changes_and_live_route_unsettled_fail_closed(gate):
    g = gate
    (car, loc, _, _), _, _ = await _setup_cars(g)
    manager = await _login_owner(g)
    url = f"/vehicles/{car}/custody"
    first = await g.client.get(url + "/readiness", headers=manager)
    assert first.status_code == 200, first.text
    offer = await _offer(g, manager, car, g.field.driver.id, first.json())
    assert offer["stock_lines"]
    proof = await _field_proof(g, car, offer, g.token)
    before = await _movement_count(g)
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            await apply_inventory_movements_batch(
                db, company_id=g.tenant, performed_by=g.actor.id,
                movements=[{
                    "product_variant_id": g.variant["id"],
                    "batch_id": g.batch, "quantity": Decimal("1"),
                    "movement_kind": "PHYSICAL",
                    "reference_type": "C02_CHANGED_AFTER_HANDSHAKE",
                    "reference_id": "C02-STOCK-" + uuid4().hex[:12],
                    "idempotency_key": "C02-LOAD-" + uuid4().hex[:13],
                    "source_location_id": g.location,
                    "destination_location_id": loc,
                    "source_stock_status": "AVAILABLE",
                    "destination_stock_status": "AVAILABLE",
                    "work_session_id": None,
                }],
            )
            await db.commit()
    finally:
        tenant_context.reset(token)
    expected = await _movement_count(g)
    assert expected > before
    denied = await g.client.post(url + "/accept", headers=manager,
        json={"request_id": str(uuid4()), "receiver_proof": proof})
    assert denied.status_code == 409, denied.text
    assert denied.json()["error"]["code"] == "CUSTODY_STOCK_SNAPSHOT_STALE"
    assert await _movement_count(g) == expected

    refreshed = await g.client.get(url + "/readiness", headers=manager)
    assert refreshed.status_code == 200, refreshed.text
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            zone = Zone(company_id=g.tenant, name="C02 live " + uuid4().hex[:7],
                        is_active=True)
            db.add(zone)
            await db.flush()
            route = DispatchRoute(
                company_id=g.tenant, zone_id=zone.id,
                # The baseline R1 already reserves Khaled. A distinct
                # representative demonstrates the vehicle-specific lock.
                driver_id=g.other.driver.id, vehicle_id=car,
                source_location_id=g.warehouse_id, status="active",
            )
            db.add(route)
            await db.commit()
            route_id = route.id
    finally:
        tenant_context.reset(token)
    payload = {
        "target_driver_id": g.field.driver.id,
        "expected_context_revision": refreshed.json()["context_revision"],
        "expected_stock_snapshot": refreshed.json()["stock_snapshot"],
    }
    blocked = await g.client.post(url + "/offer", headers=manager, json=payload)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "CUSTODY_LIVE_ROUTE_MUST_SETTLE_FIRST"

    # Even a rev2 active route with an incomplete/missing period must block
    # reassignment; only the genuine settled transition may free custody.
    tenant = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            live = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == g.tenant,
                DispatchRoute.id == route_id,
            ).with_for_update())
            live.assignment_context_revision = 2
            await db.commit()
    finally:
        tenant_context.reset(tenant)
    blocked_rev2 = await g.client.post(url + "/offer", headers=manager, json=payload)
    assert blocked_rev2.status_code == 409, blocked_rev2.text
    assert blocked_rev2.json()["error"]["code"] == "CUSTODY_LIVE_ROUTE_MUST_SETTLE_FIRST"

    # A historical M01 epoch linked to an OPEN session must not use the
    # absence of an M03 period as a settlement bypass.
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            live = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == g.tenant,
                DispatchRoute.id == route_id,
            ).with_for_update())
            live.status = "postponed"
            epoch = await db.scalar(select(VehicleCustodyEpoch).where(
                VehicleCustodyEpoch.company_id == g.tenant,
                VehicleCustodyEpoch.vehicle_id == car,
                VehicleCustodyEpoch.ended_at.is_(None),
            ).with_for_update())
            epoch.related_session_id = g.session
            await db.commit()
    finally:
        tenant_context.reset(token)
    unsettled = await g.client.post(url + "/offer", headers=manager, json=payload)
    assert unsettled.status_code == 409, unsettled.text
    assert unsettled.json()["error"]["code"] == "CUSTODY_PREVIOUS_SESSION_UNSETTLED"
    assert await _movement_count(g) == expected


async def test_c02_loaded_vehicle_missing_epoch_not_implicitly_accepted(gate):
    g = gate
    (car, loc, _, _), _, _ = await _setup_cars(g)
    manager = await _login_owner(g)
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin, expire_on_commit=False) as db:
            epoch = await db.scalar(select(VehicleCustodyEpoch).where(
                VehicleCustodyEpoch.company_id == g.tenant,
                VehicleCustodyEpoch.vehicle_id == car,
                VehicleCustodyEpoch.ended_at.is_(None),
            ))
            assert epoch is not None and epoch.state == "NEEDS_REVIEW"
            await db.delete(epoch)  # Simulate missing one-time M01 evidence.
            await db.commit()
    finally:
        tenant_context.reset(token)
    choices = await g.client.get("/dispatch/launch/resource-availability",
        headers=manager, params={
            "selected_driver_id": g.field.driver.id,
            "selected_vehicle_id": car,
        })
    assert choices.status_code == 200, choices.text
    row = next(x for x in choices.json()["vehicles"] if x["id"] == str(car))
    assert row["code"] == "CUSTODY_STOCK_WITHOUT_EPOCH" and not row["available"]
    ready = await g.client.get(f"/vehicles/{car}/custody/readiness", headers=manager)
    assert ready.status_code == 200 and ready.json()["stocked"]
    assert ready.json()["state"] == "NO_EPOCH"
    before = await _movement_count(g)
    offer = await _offer(g, manager, car, g.field.driver.id, ready.json())
    assert offer["action"] == "FIRST_ACCEPT"
    wrong_stock_confirmation = await g.client.post(
        f"/driver/vehicles/{car}/custody/confirm",
        headers={"Authorization": "Bearer " + g.token}, json={
            "offer_token": offer["offer_token"],
            "confirmed_stock_snapshot": "f" * 64,
            "receiver_confirms_physical_count": True,
        },
    )
    assert wrong_stock_confirmation.status_code == 403
    assert wrong_stock_confirmation.json()["error"]["code"] == "CUSTODY_RECEIVER_CONFIRMATION_DENIED"
    proof = await _field_proof(g, car, offer, g.token)
    first = await g.client.post(f"/vehicles/{car}/custody/accept", headers=manager,
        json={"request_id": str(uuid4()), "receiver_proof": proof})
    assert first.status_code == 201, first.text
    assert first.json()["context_revision"] == 1
    assert await _movement_count(g) == before
    print("C02_STOCKED_NO_EPOCH_REQUIRES_SIGNED_COUNT=PASS", flush=True)
