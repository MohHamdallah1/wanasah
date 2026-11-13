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
from tests.test_dispatch_m02_lifecycle_postgres import _body, _explicitly_accept_vehicle
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


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_m05_signed_pause_keeps_same_vehicle_rep_zone_and_no_stock(pg):
    """P0 PAUSE uses signed M02 epoch, never legacy WAITING PUT or POSTPONE."""
    from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod

    home, foreign = pg.tenants
    stock_key, body, vehicle_location = await _prepared_route(pg, home)
    driver_id = int(body["driver_id"])
    vehicle_id = int(body["vehicle_id"])
    zone_id = int(body["zone_id"])
    availability_path = "/dispatch/launch/resource-availability"
    async with _real_http() as http:
        owner = await _owner(http, pg, home)
        foreign_owner = await _owner(http, pg, foreign)
        created = await http.post("/dispatch/route", headers=owner, json=body)
        assert created.status_code == 201, created.text
        rid = int(created.json()["route_id"])
        url = f"/dispatch/route/{rid}/lifecycle"
        async with pg.session() as db:
            stock_before = await db.scalar(select(func.count(InventoryMovement.id)).where(
                InventoryMovement.company_id == home.company_id))
        postponed = await http.put(url, headers=owner, json=_body("POSTPONE", 1))
        assert postponed.status_code == 200, postponed.text
        assert postponed.json()["status"] == "postponed"
        custody_revision = await _explicitly_accept_vehicle(
            pg, home, driver_id=driver_id, vehicle_id=vehicle_id,
            vehicle_location=vehicle_location,
        )
        resumed = await http.put(url, headers=owner, json=_body(
            "RESUME", 2, driver=driver_id, vehicle=vehicle_id,
            custody=custody_revision))
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "active"
        assert resumed.json()["context_revision"] == 3
        async with pg.session() as db:
            old = await db.scalar(select(DispatchRouteExecutionPeriod).where(
                DispatchRouteExecutionPeriod.company_id == home.company_id,
                DispatchRouteExecutionPeriod.route_id == rid,
                DispatchRouteExecutionPeriod.ended_at.is_(None),
            ))
            assert old and old.context_revision == 3
            old_id = int(old.id)
            old_driver = int(old.driver_id)
            old_vehicle = int(old.vehicle_id)
            old_rep = int(old.field_representative_id)
            old_location = int(old.vehicle_location_id)
            old_commercial = int(old.commercial_context_id)
        pause_cmd = _body("PAUSE", 3, period=old_id)
        assert (await http.put(url, json=pause_cmd)).status_code == 401
        assert (await http.put(url, headers=foreign_owner, json=pause_cmd)).status_code in (403, 404)
        first = await http.put(url, headers=owner, json=pause_cmd)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "waiting"
        assert first.json()["context_revision"] == 4
        assert first.json()["zone_reserved"] is True
        assert first.json()["live_assets_reserved"] is True
        replay = await http.put(url, headers=owner, json=pause_cmd)
        assert replay.status_code == 200 and replay.json() == first.json()
        assert (await http.put(url, headers=owner, json={
            **pause_cmd, "expected_period_id": old_id + 1000,
        })).status_code == 409
        stale = await http.put(url, headers=owner, json=_body("PAUSE", 3, period=old_id))
        assert stale.status_code == 409, stale.text
        legacy = await http.put(f"/dispatch/route/{rid}/status",
                                headers=owner, json={"status": "waiting"})
        assert legacy.status_code == 409, legacy.text
        after_pause = await http.get(availability_path, headers=owner)
        assert after_pause.status_code == 200, after_pause.text
        choices = after_pause.json()
        assert _item(choices, "zones", zone_id)["code"] == "ZONE_ROUTE_RESERVED"
        assert _item(choices, "drivers", driver_id)["code"] == "REPRESENTATIVE_ON_ROUTE"
        assert _item(choices, "vehicles", vehicle_id)["code"] == "VEHICLE_ON_ROUTE"
        async with pg.session() as db:
            rows = (await db.scalars(select(DispatchRouteExecutionPeriod).where(
                DispatchRouteExecutionPeriod.company_id == home.company_id,
                DispatchRouteExecutionPeriod.route_id == rid,
            ).order_by(DispatchRouteExecutionPeriod.id))).all()
            assert len(rows) == 2 and rows[0].ended_at is not None
            assert rows[1].ended_at is None and rows[1].context_revision == 4
            assert (rows[1].driver_id, rows[1].vehicle_id,
                    rows[1].field_representative_id, rows[1].vehicle_location_id,
                    rows[1].commercial_context_id) == (
                        old_driver, old_vehicle, old_rep, old_location, old_commercial)
            paused_period_id = int(rows[1].id)
            assert await db.scalar(select(func.count(InventoryMovement.id)).where(
                InventoryMovement.company_id == home.company_id)) == stock_before
        ready = await http.get(
            f"{url}/readiness?target_driver_id={driver_id}&target_vehicle_id={vehicle_id}",
            headers=owner,
        )
        assert ready.status_code == 200, ready.text
        assert ready.json()["custodyRevision"] == custody_revision
        assert ready.json()["assignmentContextRevision"] == 4
        resumed_again_cmd = _body("RESUME", 4, period=paused_period_id,
                                  driver=driver_id, vehicle=vehicle_id,
                                  custody=custody_revision)
        resumed_again = await http.put(url, headers=owner, json=resumed_again_cmd)
        assert resumed_again.status_code == 200, resumed_again.text
        assert resumed_again.json()["status"] == "active"
        assert resumed_again.json()["context_revision"] == 5
        again_replay = await http.put(url, headers=owner, json=resumed_again_cmd)
        assert again_replay.status_code == 200 and again_replay.json() == resumed_again.json()
        assert (await http.put(url, headers=owner, json=_body(
            "RESUME", 4, period=paused_period_id,
            driver=driver_id, vehicle=vehicle_id, custody=custody_revision,
        ))).status_code == 409
        async with pg.session() as db:
            periods = (await db.scalars(select(DispatchRouteExecutionPeriod).where(
                DispatchRouteExecutionPeriod.company_id == home.company_id,
                DispatchRouteExecutionPeriod.route_id == rid,
            ).order_by(DispatchRouteExecutionPeriod.id))).all()
            assert len(periods) == 3 and periods[1].ended_at is not None
            assert periods[2].ended_at is None and periods[2].context_revision == 5
            assert (periods[2].driver_id, periods[2].vehicle_id,
                    periods[2].field_representative_id) == (old_driver, old_vehicle, old_rep)
            continued_period_id = int(periods[2].id)
            assert await db.scalar(select(func.count(InventoryMovement.id)).where(
                InventoryMovement.company_id == home.company_id)) == stock_before
        occupied_again = (await http.get(availability_path, headers=owner)).json()
        assert _item(occupied_again, "zones", zone_id)["code"] == "ZONE_ROUTE_RESERVED"
        assert _item(occupied_again, "drivers", driver_id)["code"] == "REPRESENTATIVE_ON_ROUTE"
        assert _item(occupied_again, "vehicles", vehicle_id)["code"] == "VEHICLE_ON_ROUTE"
        deferred = await http.put(url, headers=owner,
                                  json=_body("POSTPONE", 5, period=continued_period_id))
        assert deferred.status_code == 200, deferred.text
        assert deferred.json()["status"] == "postponed"
        choices = (await http.get(availability_path, headers=owner)).json()
        assert _item(choices, "zones", zone_id)["code"] == "ZONE_POSTPONED_RESERVED"
        assert _item(choices, "drivers", driver_id)["code"] != "REPRESENTATIVE_ON_ROUTE"
        assert _item(choices, "vehicles", vehicle_id)["code"] != "VEHICLE_ON_ROUTE"
        closed = await http.put(url, headers=owner,
                                json=_body("CLOSE", 6))
        assert closed.status_code == 200, closed.text
        choices = (await http.get(availability_path, headers=owner)).json()
        assert _item(choices, "zones", zone_id)["code"] == "AVAILABLE"
        async with pg.session() as db:
            assert await db.scalar(select(func.count(InventoryMovement.id)).where(
                InventoryMovement.company_id == home.company_id)) == stock_before
    print("M05_SIGNED_PAUSE_VS_POSTPONE_VS_CLOSE_REAL_PG16_BEARER=PASS")
