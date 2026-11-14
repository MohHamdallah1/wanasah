"""#1021 — genuine signed FIELD bearer, canonical physical custody without route.

ONLY disposable m03_941_custody_1021 on loopback PG16:56621, runtime NOSUPERUSER.
Never modifies production tenants or inventory outside this isolated fixture.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from database import engine as runtime_engine
from domains.authorization.field_models import FieldRepresentativeRole
from models import InventoryBalance, InventoryLocation, InventoryMovement, WorkSession
from tests.test_dispatch_m03_period_postgres import gate, _headers
from tests.test_dispatch_c01_c02_custody_postgres import _setup_cars, _login_owner, _ledger_signature

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_CUSTODY_1021_PG_GATE") != "1",
                       reason="Explicit isolated PG16 56621 vehicle read only"),
    pytest.mark.asyncio(loop_scope="module"),
]


async def test_route_independent_verified_vehicle_stock_dual_bearer_and_denials(gate):
    g = gate
    assert "127.0.0.1:56621/m03_941_custody_1021" in os.environ["DATABASE_URL"]
    assert "custody1021_app@" in os.environ["DATABASE_URL"]

    async with runtime_engine.connect() as conn:
        flags = (await conn.execute(text(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ))).one()
        assert tuple(flags) == (False, False)
        for table in ("vehicle_custody_epochs", "inventory_balances"):
            scope = (await conn.execute(text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE oid=to_regclass(:t)"
            ), {"t": table})).one()
            assert tuple(scope) == (True, True), table

    unknown, other_accepted, _empty = await _setup_cars(g)
    target_vehicle, target_location, _, _ = unknown
    other_vehicle, other_location, _, _ = other_accepted
    field = _headers(g.token)
    other = _headers(g.other_token)
    foreign = _headers(g.foreign_token)
    manager = await _login_owner(g)
    path = "/driver/vehicle-stock"
    stock_before = await _ledger_signature(g)
    target_ledger_before = int((
        await _actual_vehicle_quantity(g, target_location)
    ))

    # Truthfully signed other FIELD custodian has NO session/route. This is
    # the exact old-session-null reproduction, not a fake response fixture.
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            session = await db.scalar(select(WorkSession.id).where(
                WorkSession.company_id == g.tenant,
                WorkSession.driver_id == g.other.driver.id,
                WorkSession.end_time.is_(None),
            ).limit(1))
            assert session is None
    finally:
        tenant_context.reset(token)
    dashboard = await g.client.get("/driver/dashboard", headers=other)
    assert dashboard.status_code == 200 and dashboard.json()["active_session"] is None, dashboard.text
    old_custody = await g.client.get("/driver/custody", headers=other)
    assert old_custody.status_code in (403, 409), old_custody.text
    assert old_custody.json()["error"]["code"] == "FIELD_SESSION_REQUIRED"

    trusted = await g.client.get(path, headers=other)
    assert trusted.status_code == 200, trusted.text
    payload = trusted.json()
    assert payload["status"] == "VERIFIED" and payload["source"] == "INVENTORY_BALANCE"
    assert payload["vehicle_id"] == other_vehicle
    assert payload["vehicle_location_id"] == other_location
    assert type(payload["custody_epoch_id"]) is int and payload["custody_epoch_id"] > 0
    assert payload["sellable_items"] == [{
        "product_variant_id": g.variant["id"],
        "product_name": "Synthetic tracked item",
        "stock_status": "AVAILABLE", "uom_code": "EACH",
        "quantity": "8", "packs_per_carton": 50,
    }]
    assert payload["non_sellable_items"] == []
    assert payload["next_cursor"] is None

    assert (await g.client.get(path)).status_code == 401
    assert (await g.client.get(path, headers=manager)).status_code == 401
    outsider = await g.client.get(path, headers=foreign)
    assert outsider.status_code == 403 and outsider.json()["error"]["code"] == "FIELD_VEHICLE_CUSTODY_NOT_ACCEPTED"
    unaccepted = await g.client.get(path, headers=field)
    assert unaccepted.status_code == 403
    assert unaccepted.json()["error"]["code"] == "FIELD_VEHICLE_CUSTODY_NOT_ACCEPTED"

    # The legitimate FIELD actor currently has an active session/route to a
    # DIFFERENT vehicle. The physical signed stock must never follow it.
    before_dashboard = await g.client.get("/driver/dashboard", headers=field)
    assert before_dashboard.status_code == 200, before_dashboard.text
    assert before_dashboard.json()["active_session"]["session_id"] == g.session
    original_route_inventory = before_dashboard.json()["active_session"]["inventory"]

    readiness = await g.client.get(
        f"/vehicles/{target_vehicle}/custody/readiness", headers=manager,
    )
    assert readiness.status_code == 200 and readiness.json()["state"] == "NEEDS_REVIEW"
    body = {
        "request_id": str(uuid4()), "target_driver_id": g.field.driver.id,
        "expected_context_revision": readiness.json()["context_revision"],
        "expected_stock_snapshot": readiness.json()["stock_snapshot"],
    }
    create = await g.client.post(
        f"/vehicles/{target_vehicle}/custody/handoffs", headers=manager, json=body,
    )
    assert create.status_code == 200 and create.json()["state"] == "PENDING", create.text
    handoff_id = create.json()["handoff_id"]
    for phase in ("PENDING", "CONFIRMED"):
        denied = await g.client.get(path, headers=field)
        assert denied.status_code == 403, (phase, denied.text)
        assert denied.json()["error"]["code"] == "FIELD_VEHICLE_CUSTODY_NOT_ACCEPTED"
        if phase == "PENDING":
            review = await g.client.get(
                f"/driver/custody/handoffs/{handoff_id}", headers=field,
            )
            assert review.status_code == 200 and review.json()["stock_lines"]
            count = await g.client.post(
                f"/driver/custody/handoffs/{handoff_id}/decision", headers=field,
                json={
                    "request_id": str(uuid4()), "decision": "CONFIRM",
                    "confirmed_stock_snapshot": review.json()["stock_snapshot"],
                    "receiver_confirms_physical_count": True,
                },
            )
            assert count.status_code == 200 and count.json()["state"] == "CONFIRMED", count.text

    approved = await g.client.post(
        f"/vehicles/{target_vehicle}/custody/handoffs/{handoff_id}/approve",
        headers=manager, json={"request_id":str(uuid4())},
    )
    assert approved.status_code == 200 and approved.json()["state"] == "COMMITTED", approved.text
    assert approved.json()["stock_movements"] == 0

    current = await g.client.get(path, headers=field)
    assert current.status_code == 200, current.text
    data = current.json()
    assert data["vehicle_id"] == target_vehicle and data["vehicle_location_id"] == target_location
    assert data["custody_epoch_id"] == approved.json()["epoch_id"]
    assert data["sellable_items"][0]["quantity"] == str(target_ledger_before)
    assert data["non_sellable_items"] == []
    assert data["stock_snapshot"] == readiness.json()["stock_snapshot"]
    assert await _ledger_signature(g) == stock_before  # zero physical movements
    assert (await _actual_vehicle_quantity(g, target_location)) == target_ledger_before
    after_dashboard = await g.client.get("/driver/dashboard", headers=field)
    assert after_dashboard.status_code == 200
    assert after_dashboard.json()["active_session"]["inventory"] == original_route_inventory
    assert after_dashboard.json()["active_session"]["session_id"] == g.session

    invalid_cursor = await g.client.get(path, headers=field, params={"cursor":"not-signed"})
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["error"]["code"] == "FIELD_REFERENCE_INVALID"
    assert (await g.client.get(path, headers=other)).json()["vehicle_id"] == other_vehicle

    # Corrupt canonical location is a typed failure, not verified zero.
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            row = await db.scalar(select(InventoryLocation).where(
                InventoryLocation.company_id == g.tenant,
                InventoryLocation.id == target_location,
            ))
            row.is_active = False
            await db.commit()
        stale = await g.client.get(path, headers=field)
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"]["code"] in {
            "VEHICLE_CUSTODY_LOCATION_INACTIVE", "CUSTODY_LOCATION_CHANGED",
        }
    finally:
        async with AsyncSession(g.admin) as db:
            row = await db.scalar(select(InventoryLocation).where(
                InventoryLocation.company_id == g.tenant,
                InventoryLocation.id == target_location,
            ))
            row.is_active = True
            await db.commit()
        tenant_context.reset(token)

    # Persisted FIELD grant revocation rechecked on every HTTP request.
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            await db.execute(delete(FieldRepresentativeRole).where(
                FieldRepresentativeRole.company_id == g.tenant,
                FieldRepresentativeRole.field_representative_id == g.field.context.representative_id,
            ))
            await db.commit()
    finally:
        tenant_context.reset(token)
    revoked = await g.client.get(path, headers=field)
    assert revoked.status_code == 403, revoked.text
    assert revoked.json()["error"]["code"] == "FIELD_CAPABILITY_DENIED"
    assert await _ledger_signature(g) == stock_before


async def _actual_vehicle_quantity(g, location_id):
    token = tenant_context.set(g.tenant)
    try:
        async with AsyncSession(g.admin) as db:
            total = await db.scalar(select(func.coalesce(func.sum(
                InventoryBalance.on_hand_quantity
            ), 0)).where(
                InventoryBalance.company_id == g.tenant,
                InventoryBalance.location_id == location_id,
                InventoryBalance.stock_status == "AVAILABLE",
            ))
            return int(total)
    finally:
        tenant_context.reset(token)
