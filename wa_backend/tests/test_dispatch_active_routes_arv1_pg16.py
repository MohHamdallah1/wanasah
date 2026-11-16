"""ARV1-B #1045 — original pending visits survive route POSTPONE in the manager read.

Unlike accepted M02/M06 transition and S1/S2 proofs, this regression tests
that the live Active Routes *projection* keeps an actionable remaining-shop
count while M02 deliberately preserves already assigned pending visits.

Use ONLY the explicit disposable PG16 fixture at 127.0.0.1:55439, non-BYPASSRLS
runtime, separate migrator, real signed FIELD/Backoffice HTTP and FORCE RLS.
No production tenant data, fake inventory movement or DB/authorization mocks.
"""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select

from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal
from models import (
    Company, DispatchRoute, InventoryMovement, Shop, Visit, WorkSession, Zone,
)
from database import engine as http_runtime_engine
from services import get_company_local_date
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_route_launch_d07_postgres import _prepared_route, _state
from tests.test_dispatch_m02_lifecycle_postgres import (
    _body, _explicitly_accept_vehicle,
)
from tests.test_dispatch_shop_finance_edit_v1_postgres import _owner, _real_http

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_ARV1_PG_GATE") != "1",
        reason="ARV1 exact isolated PG16 signed read/transition acceptance only",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _pending_evidence(pg, tenant, zone):
    async with pg.session() as db:
        rows = (await db.execute(
            select(Visit.id, Visit.driver_id, Visit.status, Visit.work_session_id)
            .join(Shop, Shop.id == Visit.shop_id)
            .where(
                Visit.company_id == tenant.company_id,
                Shop.company_id == tenant.company_id,
                Shop.zone_id == zone,
                Visit.status == "Pending",
                Shop.is_active.is_(True),
                Shop.is_archived.is_(False),
            )
            .order_by(Visit.id)
        )).all()
        physical_movements = int(await db.scalar(
            select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == tenant.company_id,
            )
        ) or 0)
        sessions = int(await db.scalar(
            select(func.count()).select_from(WorkSession).where(
                WorkSession.company_id == tenant.company_id,
            )
        ) or 0)
        return tuple(tuple(row) for row in rows), physical_movements, sessions


async def _visible_route(client, bearer, route_id):
    res = await client.get(
        "/dispatch/active_routes",
        params={"route_id": route_id}, headers=bearer,
    )
    assert res.status_code == 200, res.text
    matched = [entry for entry in res.json() if int(entry["id"]) == route_id]
    assert len(matched) == 1, res.text
    return matched[0]


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_postponed_pending_visits_remain_counted_and_signed_cross_tenant_isolated(pg):
    home, foreign = pg.tenants
    launch_key, payload, vehicle_location = await _prepared_route(pg, home)

    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        foreign_owner = await _owner(client, pg, foreign)
        launch = await client.post("/dispatch/route", json=payload, headers=owner)
        assert launch.status_code == 201, launch.text
        rid = int(launch.json()["route_id"])
        zone = int(payload["zone_id"])

        original_visits, original_movements, original_sessions = (
            await _pending_evidence(pg, home, zone)
        )
        assert len(original_visits) == 1
        assert original_visits[0][1] == int(payload["driver_id"])
        assert original_visits[0][2] == "Pending"
        assert original_sessions == 0
        physical_start = await _state(pg, home, launch_key, vehicle_location)

        # A second unrelated zone has real pending visits, including a
        # historic driver assignment. The route_id read may not aggregate it.
        async with pg.session() as db:
            other_zone = Zone(
                company_id=home.company_id,
                name="ARV1 secondary " + uuid4().hex[:12],
                is_active=True,
            )
            db.add(other_zone)
            await db.flush()
            other_shop = Shop(
                company_id=home.company_id,
                zone_id=other_zone.id,
                name="ARV1 other shop " + uuid4().hex[:12],
                current_balance=Decimal("0"),
                max_debt_limit=Decimal("1000"),
                is_active=True,
            )
            db.add(other_shop)
            await db.flush()
            db.add(Visit(
                company_id=home.company_id,
                shop_id=other_shop.id,
                driver_id=int(payload["driver_id"]),
                operational_date=await get_company_local_date(db, home.company_id),
                status="Pending",
                sequence=1,
                is_emergency=False,
            ))
            other_zone_id = int(other_zone.id)
            await db.commit()
        assert len((await _pending_evidence(pg, home, other_zone_id))[0]) == 1

        # Authorization is canonical: one company never observes another's
        # active-route ID, even when the query supplies that exact integer.
        outsider = await client.get(
            "/dispatch/active_routes",
            params={"route_id": rid}, headers=foreign_owner,
        )
        assert outsider.status_code == 200, outsider.text
        assert outsider.json() == []
        unsigned = await client.get(
            "/dispatch/active_routes", params={"route_id": rid},
        )
        assert unsigned.status_code == 401

        # Genuine FIELD Bearer is not a Backoffice dispatch.read grant.
        async with pg.session() as db:
            bridge = await db.scalar(select(IdentityLegacyDriverMap).where(
                IdentityLegacyDriverMap.company_id == home.company_id,
                IdentityLegacyDriverMap.legacy_driver_id == payload["driver_id"],
            ))
            assert bridge is not None and bridge.field_principal_id is not None
            username = await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == bridge.field_principal_id,
            ))
            company_code = await db.scalar(select(Company.company_code).where(
                Company.id == home.company_id,
            ))
        field_login = await client.post("/driver/login", json={
            "company_code": company_code, "username": username,
            "password": "SyntheticFixture123",
        })
        assert field_login.status_code == 200, field_login.text
        field_bearer = {"Authorization": "Bearer " + field_login.json()["token"]}
        field_read = await client.get("/dispatch/active_routes", headers=field_bearer)
        assert field_read.status_code in (401, 403), field_read.text

        before = await _visible_route(client, owner, rid)
        assert before["status"] == "active"
        assert before["shopsRemaining"] == 1
        assert before["assignmentContextRevision"] == 1

        intent = _body("POSTPONE", 1)
        url = f"/dispatch/route/{rid}/lifecycle"
        denied = await client.put(url, headers=foreign_owner, json=intent)
        assert denied.status_code in (403, 404), denied.text
        denied_field = await client.put(url, headers=field_bearer, json=intent)
        assert denied_field.status_code in (401, 403), denied_field.text
        assert (await _pending_evidence(pg, home, zone))[0] == original_visits

        postponed = await client.put(url, headers=owner, json=intent)
        assert postponed.status_code == 200, postponed.text
        assert postponed.json()["status"] == "postponed"
        assert postponed.json()["context_revision"] == 2
        assert postponed.json()["zone_reserved"] is True

        # THE MISSING ARV1-B CONTRACT: saved pending visits are still assigned
        # to their original rep. They must not vanish from the zone's remaining
        # count just because the live assignment was released on POSTPONE.
        # Capture the SQL generated by genuine HTTP. This proves both the
        # zone-bound aggregate and zero aggregate when no route is visible,
        # not merely correct output after Python-side filtering.
        count_sql = []
        def capture_count(conn, cursor, statement, parameters, context, many):
            lowered = statement.lower()
            if "count(distinct" in lowered and "visits" in lowered:
                count_sql.append((statement, parameters))

        event.listen(http_runtime_engine.sync_engine, "before_cursor_execute", capture_count)
        try:
            after = await _visible_route(client, owner, rid)
            empty = await client.get(
                "/dispatch/active_routes",
                params={"route_id": 2147483646}, headers=owner,
            )
            assert empty.status_code == 200 and empty.json() == []
        finally:
            event.remove(http_runtime_engine.sync_engine, "before_cursor_execute", capture_count)
        assert len(count_sql) == 1, count_sql
        bounded_sql, bind_values = count_sql[0]
        assert "shops.zone_id IN (" in bounded_sql, bounded_sql
        assert int(zone) in bind_values, bind_values
        assert int(other_zone_id) not in bind_values, bind_values
        assert after["status"] == "postponed"
        assert after["currentDriverId"] is None
        assert after["shopsRemaining"] == len(original_visits), (
            "POSTPONE must retain original pending shops; route count cannot "
            "be based only on visits with driver_id IS NULL",
            after, original_visits,
        )

        # Repeated response uses same canonical idempotency receipt. The route
        # has not created/closed any session, changed receivables or moved stock.
        replay = await client.put(url, headers=owner, json=intent)
        assert replay.status_code == 200 and replay.json() == postponed.json()
        assert await _pending_evidence(pg, home, zone) == (
            original_visits, original_movements, original_sessions,
        )
        physical_after = await _state(pg, home, launch_key, vehicle_location)
        assert physical_after["balances"] == physical_start["balances"]
        assert physical_after["movements"] == physical_start["movements"]
        assert physical_after["cost_events"] == physical_start["cost_events"]

        # Real signed receiver evidence is required before same-vehicle RESUME.
        premature = await client.put(url, headers=owner, json=_body(
            "RESUME", 2,
            driver=int(payload["driver_id"]),
            vehicle=int(payload["vehicle_id"]), custody=1,
        ))
        assert premature.status_code == 409, premature.text
        custody_revision = await _explicitly_accept_vehicle(
            pg, home, driver_id=int(payload["driver_id"]),
            vehicle_id=int(payload["vehicle_id"]),
            vehicle_location=vehicle_location,
        )
        resumed = await client.put(url, headers=owner, json=_body(
            "RESUME", 2, driver=int(payload["driver_id"]),
            vehicle=int(payload["vehicle_id"]), custody=custody_revision,
        ))
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "active"
        live = await _visible_route(client, owner, rid)
        assert live["shopsRemaining"] == len(original_visits)
        assert live["currentDriverId"] == int(payload["driver_id"])
        assert await _pending_evidence(pg, home, zone) == (
            original_visits, original_movements, original_sessions,
        )
        final_physical = await _state(pg, home, launch_key, vehicle_location)
        assert final_physical["balances"] == physical_start["balances"]
        assert final_physical["movements"] == physical_start["movements"]
        print("ARV1_POSTPONE_PENDING_VISITS_SIGNED_PG16=PASS", flush=True)
