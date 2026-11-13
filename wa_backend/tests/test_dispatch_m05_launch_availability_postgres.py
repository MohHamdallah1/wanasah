"""M05 launch-choice availability: real restricted PG16 / Bearer read + writer.

This is a short addon to the already accepted M05 route test fixture. No
fake authorization dependencies or changes to M02/M04 accounting/lifecycle.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from models import DispatchRoute, InventoryMovement
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_route_launch_d07_postgres import _prepared_route
from tests.test_dispatch_shop_finance_edit_v1_postgres import _owner, _real_http

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_DISPATCH_M05_PG_GATE") != "1",
                       reason="Requires isolated real PG16 M05 gate"),
    pytest.mark.asyncio(loop_scope="function"),
]


def _item(data, kind: str, item_id: int):
    rows = [r for r in data[kind] if r["id"] == str(item_id)]
    assert len(rows) == 1, (kind, item_id, len(rows))
    return rows[0]


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_m05_real_bearer_launch_availability_postponed_releases_only_resources(pg):
    home, foreign = pg.tenants
    _, body, _ = await _prepared_route(pg, home)
    driver_id = int(body["driver_id"])
    vehicle_id = int(body["vehicle_id"])
    zone_id = int(body["zone_id"])
    source_id = int(body["source_location_id"])
    path = "/dispatch/launch/resource-availability"
    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        outsider = await _owner(client, pg, foreign)
        assert (await client.get(path)).status_code == 401
        before = await client.get(path, headers=owner)
        assert before.status_code == 200, before.text
        before_data = before.json()
        assert before_data["advisory"] is True
        assert _item(before_data, "zones", zone_id)["available"]
        assert _item(before_data, "drivers", driver_id)["available"]
        assert _item(before_data, "vehicles", vehicle_id)["available"]
        assert _item(before_data, "warehouses", source_id)["available"]
        foreign_data = await client.get(path, headers=outsider)
        assert foreign_data.status_code == 200, foreign_data.text
        assert all(x["id"] != str(driver_id) for x in foreign_data.json()["drivers"])

        async with pg.session() as db:
            before_movement = await db.scalar(select(func.count(InventoryMovement.id)).where(
                InventoryMovement.company_id == home.company_id,
            ))
        created = await client.post("/dispatch/route", json=body, headers=owner)
        assert created.status_code == 201, created.text
        rid = int(created.json()["route_id"])
        async with pg.session() as db:
            after_create_movement = await db.scalar(select(func.count(InventoryMovement.id)).where(
                InventoryMovement.company_id == home.company_id,
            ))
        busy = await client.get(path, headers=owner)
        assert busy.status_code == 200, busy.text
        occupied = busy.json()
        assert _item(occupied, "zones", zone_id)["code"] == "ZONE_ROUTE_RESERVED"
        assert _item(occupied, "drivers", driver_id)["code"] == "REPRESENTATIVE_ON_ROUTE"
        assert _item(occupied, "vehicles", vehicle_id)["code"] == "VEHICLE_ON_ROUTE"

        # A different idempotency UUID cannot launch the same three resources
        # while the real route is active; actual locked route writer still wins.
        another = await client.post("/dispatch/route", json={
            **body, "request_id": str(uuid4()),
        }, headers=owner)
        assert another.status_code == 409, another.text

        postponed = await client.put(
            f"/dispatch/route/{rid}/status",
            json={"status": "postponed"}, headers=owner,
        )
        assert postponed.status_code == 200, postponed.text
        deferred = await client.get(path, headers=owner)
        assert deferred.status_code == 200, deferred.text
        deferred_data = deferred.json()
        assert _item(deferred_data, "zones", zone_id)["code"] == "ZONE_POSTPONED_RESERVED"
        assert _item(deferred_data, "drivers", driver_id)["code"] not in (
            "REPRESENTATIVE_ON_ROUTE", "PREVIOUS_SESSION_UNSETTLED",
        )
        assert _item(deferred_data, "vehicles", vehicle_id)["code"] != "VEHICLE_ON_ROUTE"

        # Actual legacy rev1 restore preserves resource reservation; canonical
        # rev2 uses separate M02 accepted custodian and cannot use this path.
        restored = await client.put(
            f"/dispatch/route/{rid}/status",
            json={"status": "active"}, headers=owner,
        )
        assert restored.status_code == 200, restored.text
        waiting = await client.get(path, headers=owner)
        assert _item(waiting.json(), "drivers", driver_id)["code"] == "REPRESENTATIVE_ON_ROUTE"
        assert _item(waiting.json(), "vehicles", vehicle_id)["code"] == "VEHICLE_ON_ROUTE"

        closed = await client.put(
            f"/dispatch/route/{rid}/status",
            json={"status": "closed"}, headers=owner,
        )
        assert closed.status_code == 200, closed.text
        after = await client.get(path, headers=owner)
        assert after.status_code == 200, after.text
        assert _item(after.json(), "zones", zone_id)["code"] == "AVAILABLE"
        assert _item(after.json(), "drivers", driver_id)["code"] != "REPRESENTATIVE_ON_ROUTE"
        assert _item(after.json(), "vehicles", vehicle_id)["code"] != "VEHICLE_ON_ROUTE"
        async with pg.session() as db:
            after_movement = await db.scalar(select(func.count(InventoryMovement.id)).where(
                InventoryMovement.company_id == home.company_id,
            ))
            route = await db.get(DispatchRoute, rid)
            assert route.status == "closed"
            assert route.assignment_context_revision == 1
        # The original D07 creation may physically load stock; later READ,
        # POSTPONE, RESUME and CLOSE never issue any implied movement.
        assert after_create_movement >= before_movement
        assert after_movement == after_create_movement
    print("M05_LAUNCH_REAL_PG16_BEARER_POSTPONED_RESOURCE_RELEASE=PASS")
