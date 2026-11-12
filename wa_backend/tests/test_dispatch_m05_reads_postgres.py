"""M05: real restricted PG16 + original Backoffice Bearer read-only M02 authority.

Reuses approved D07 canonical FIELD, vehicle, commercial and route fixtures.
No dependency overrides, fake RLS, fabricated HTTP authorization or fixture
migrations. All M05 API reads leave stock, settlement and periods unchanged.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, select

from database import engine as runtime_engine
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.identity.migration.models import IdentityLegacyDriverMap
from models import DispatchRoute, RouteCommercialContext, UserLocationAccess
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_route_launch_d07_postgres import _prepared_route
from tests.test_dispatch_shop_finance_edit_v1_postgres import _owner, _real_http, _token
from tests.test_dispatch_d06_secure_shop_reads_postgres import _location_read

pytestmark = [
    pytest.mark.skipif(os.getenv("WANASAH_DISPATCH_M05_PG_GATE") != "1",
                       reason="Requires isolated PG16 real signed M05 gate"),
    pytest.mark.asyncio(loop_scope="function"),
]


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_m05_signed_current_period_scoped_read_target_custody_and_revocation(pg):
    home, foreign = pg.tenants
    key, body, vehicle_location = await _prepared_route(pg, home)
    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        outsider = await _owner(client, pg, foreign)
        created = await client.post("/dispatch/route", json=body, headers=owner)
        assert created.status_code == 201, created.text
        rid = int(created.json()["route_id"])

        # A legacy route's old driver/car do not magically become an M01 period.
        before = await client.get("/dispatch/active_routes", headers=owner)
        assert before.status_code == 200, before.text
        old = next(row for row in before.json() if int(row["id"]) == rid)
        assert old["assignmentContextRevision"] == 1
        assert old["currentPeriodId"] is None
        assert old["currentDriverId"] is None
        assert old["currentVehicleId"] is None
        assert old["currentVehicleLocationId"] is None
        assert old["driverId"] == str(body["driver_id"])  # historic compatibility only

        async with pg.session() as db:
            bridge = (await db.execute(select(IdentityLegacyDriverMap).where(
                IdentityLegacyDriverMap.company_id == home.company_id,
                IdentityLegacyDriverMap.legacy_driver_id == body["driver_id"],
            ))).scalar_one()
            rep_id = int(bridge.field_representative_id)
            principal_id = int(bridge.field_principal_id)
            commercial = await db.scalar(select(RouteCommercialContext).where(
                RouteCommercialContext.company_id == home.company_id,
                RouteCommercialContext.dispatch_route_id == rid,
            ))
            assert commercial is not None
            route = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == home.company_id, DispatchRoute.id == rid,
            ))
            route.assignment_context_revision = 2
            started = datetime.utcnow() - timedelta(seconds=2)
            period = DispatchRouteExecutionPeriod(
                company_id=home.company_id, route_id=rid,
                driver_id=int(body["driver_id"]), field_representative_id=rep_id,
                vehicle_id=int(body["vehicle_id"]), vehicle_location_id=vehicle_location,
                commercial_context_id=commercial.id,
                state="PLANNED", context_revision=2, started_at=started,
                started_by_principal_id=home.owner.context.principal_id,
                evidence_origin="CANONICAL", request_id=str(uuid4()),
                payload_hash="a" * 64,
            )
            db.add(period)
            await db.flush()
            pid = int(period.id)
            await db.commit()

        count = 0
        def sql(*_args):
            nonlocal count
            count += 1
        event.listen(runtime_engine.sync_engine, "before_cursor_execute", sql)
        try:
            current = await client.get("/dispatch/active_routes", headers=owner)
        finally:
            event.remove(runtime_engine.sync_engine, "before_cursor_execute", sql)
        assert current.status_code == 200, current.text
        assert count <= 30, f"Read must remain batched like accepted D12: {count} SQL"
        live = next(row for row in current.json() if int(row["id"]) == rid)
        assert live["assignmentContextRevision"] == 2
        assert live["currentPeriodId"] == pid
        assert live["currentDriverId"] == int(body["driver_id"])
        assert live["currentVehicleId"] == int(body["vehicle_id"])
        assert live["currentVehicleLocationId"] == vehicle_location
        assert live["currentPeriodState"] == "PLANNED"

        foreign_read = await client.get("/dispatch/active_routes", headers=outsider)
        assert foreign_read.status_code == 200
        assert all(int(x["id"]) != rid for x in foreign_read.json())
        foreign_probe = await client.get(
            f"/dispatch/route/{rid}/lifecycle/readiness",
            params={"target_driver_id": int(body["driver_id"]),
                    "target_vehicle_id": int(body["vehicle_id"])},
            headers=outsider,
        )
        assert foreign_probe.status_code in (403, 404)
        assert (await client.get("/dispatch/active_routes")).status_code == 401

        # Old period is closed: without ACCEPTED vehicle proof there is no
        # positive readiness, irrespective of historical route.car/driver.
        async with pg.session() as db:
            period = await db.get(DispatchRouteExecutionPeriod, pid)
            period.state = "CLOSED"
            period.ended_at = started + timedelta(seconds=1)
            route = await db.get(DispatchRoute, rid)
            route.status = "postponed"
            route.assignment_context_revision = 3
            await db.commit()

        path = f"/dispatch/route/{rid}/lifecycle/readiness"
        params = {"target_driver_id": int(body["driver_id"]),
                  "target_vehicle_id": int(body["vehicle_id"])}
        no_epoch = await client.get(path, params=params, headers=owner)
        assert no_epoch.status_code == 409, no_epoch.text
        # The canonical HTTP error envelope is error.code, not raw detail.
        assert no_epoch.json()["error"]["code"] == "M05_CUSTODY_REQUIRED"
        invalid_driver = await client.get(path, params={
            **params, "target_driver_id": int(home.owner.operational_driver.id),
        }, headers=owner)
        assert invalid_driver.status_code in (403, 404, 409)
        assert "custodyRevision" not in invalid_driver.text

        async with pg.session() as db:
            db.add(VehicleCustodyEpoch(
                company_id=home.company_id, vehicle_id=int(body["vehicle_id"]),
                vehicle_location_id=vehicle_location,
                custodian_kind="FIELD_REPRESENTATIVE",
                custodian_principal_id=principal_id,
                field_representative_id=rep_id,
                accepted_by_principal_id=home.owner.context.principal_id,
                state="ACCEPTED", context_revision=1,
                started_at=datetime.utcnow(), evidence_origin="CANONICAL",
                request_id=str(uuid4()), payload_hash="b" * 64,
            ))
            await db.commit()
        good = await client.get(path, params=params, headers=owner)
        assert good.status_code == 200, good.text
        assert good.json() == {
            "driverId": int(body["driver_id"]), "vehicleId": int(body["vehicle_id"]),
            "custodyRevision": 1, "assignmentContextRevision": 3,
            "accepted": True, "authorized": True,
        }
        assert (await client.get(path, params=params)).status_code == 401

        # Real read-only role sees route assignment at its granted locations,
        # but cannot run readiness; revocation is effective on the SAME token.
        _role = await _location_read(pg, home, warehouse=home.location_id,
                                     vehicle_custody=vehicle_location)
        restricted = await _token(client, pg, home, home.ordinary, "SyntheticFixture123")
        limited_read = await client.get("/dispatch/active_routes", headers=restricted)
        assert limited_read.status_code == 200, limited_read.text
        entry = next(x for x in limited_read.json() if int(x["id"]) == rid)
        assert entry["can_execute"] is False
        assert entry["currentPeriodId"] is None
        denied = await client.get(path, params=params, headers=restricted)
        assert denied.status_code in (403, 404), denied.text
        async with pg.session() as db:
            await db.execute(delete(UserLocationAccess).where(
                UserLocationAccess.company_id == home.company_id,
                UserLocationAccess.driver_id == home.ordinary.driver_id,
                UserLocationAccess.role_id == _role,
            ))
            await db.commit()
        revoked = await client.get("/dispatch/active_routes", headers=restricted)
        assert revoked.status_code in (200, 403)
        if revoked.status_code == 200:
            assert all(int(row["id"]) != rid for row in revoked.json())
        assert (await client.get(path, params=params, headers=restricted)).status_code in (403, 404)

    print("M05_REAL_PG16_SIGNED_LIVE_PERIOD_CUSTODY_RLS_REVOKE PASS")
