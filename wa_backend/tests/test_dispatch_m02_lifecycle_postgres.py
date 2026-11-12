"""M02 real restricted PG16 + authenticated Backoffice Bearer lifecycle gate.

RUN ONLY after M01 #940 is MERGED and the M02 follow-up index migration is
applied. This fixture seeds genuine explicit FIELD custodian acceptance; it
never claims an unreviewed vehicle was implicitly handed to anyone.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from models import (
    DispatchRoute, WorkSession, RouteCommercialContext, InventoryMovement, Zone,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_route_launch_d07_postgres import _prepared_route, _state
from tests.test_dispatch_p0_route_stock_safety_postgres import _vehicle
from tests.canonical_actor_fixtures import seed_field_fixture
from domains.authorization.field_provisioning import assign_new_representative_default
from services import get_company_local_date
from tests.test_dispatch_shop_finance_edit_v1_postgres import _owner, _real_http

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_DISPATCH_M02_PG_GATE") != "1",
        reason="Requires disposable PG16 M01+M02 accepted migrations and real Bearer",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _body(action, revision, *, period=None, driver=None, vehicle=None, custody=None, key=None):
    result = {
        "action": action,
        "request_id": str(key or uuid4()),
        "expected_context_revision": revision,
        "expected_period_id": period,
    }
    if action == "RESUME":
        result.update({
            "target_driver_id": driver,
            "target_vehicle_id": vehicle,
            "expected_vehicle_custody_revision": custody,
        })
    return result


async def _snapshot(pg, tenant, route_id, vehicle_location, launch_key):
    from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
    async with pg.session() as db:
        route = await db.scalar(select(DispatchRoute).where(
            DispatchRoute.company_id == tenant.company_id,
            DispatchRoute.id == route_id,
        ))
        periods = (await db.scalars(select(DispatchRouteExecutionPeriod).where(
            DispatchRouteExecutionPeriod.company_id == tenant.company_id,
            DispatchRouteExecutionPeriod.route_id == route_id,
        ).order_by(DispatchRouteExecutionPeriod.id))).all()
        return {
            "status": route.status,
            "assignment_revision": int(route.assignment_context_revision),
            "legacy_session": route.work_session_id,
            "periods": [(int(p.id), p.state, p.driver_id, p.vehicle_id,
                         int(p.context_revision), p.ended_at is not None)
                        for p in periods],
            "real_stock": await _state(pg, tenant, launch_key, vehicle_location),
        }


async def _explicitly_accept_vehicle(pg, tenant, *, driver_id, vehicle_id, vehicle_location):
    """Synthetic fixture simulates signed receiver evidence, NOT API handoff.

    M04 owns production signed acceptance. This helper seeds that prerequisite
    under restricted tenant RLS so M02 can test rejection/approval honestly.
    """
    from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
    from domains.identity.migration.models import IdentityLegacyDriverMap
    async with pg.session() as db:
        bridge = await db.scalar(select(IdentityLegacyDriverMap).where(
            IdentityLegacyDriverMap.company_id == tenant.company_id,
            IdentityLegacyDriverMap.legacy_driver_id == driver_id,
        ))
        assert bridge and bridge.field_principal_id and bridge.field_representative_id
        current = await db.scalar(select(VehicleCustodyEpoch).where(
            VehicleCustodyEpoch.company_id == tenant.company_id,
            VehicleCustodyEpoch.vehicle_id == vehicle_id,
            VehicleCustodyEpoch.ended_at.is_(None),
        ).with_for_update())
        revision = int(await db.scalar(select(func.coalesce(
            func.max(VehicleCustodyEpoch.context_revision), 0,
        )).where(
            VehicleCustodyEpoch.company_id == tenant.company_id,
            VehicleCustodyEpoch.vehicle_id == vehicle_id,
        )) or 0) + 1
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if current is not None:
            assert current.state == "NEEDS_REVIEW", "Existing accepted custodian cannot be overwritten"
            # Review closes the unknown responsibility window at signed
            # acceptance time; no physical transfer or backdated ownership.
            current.started_at = current.started_at or now
            current.ended_at = now
        signed = VehicleCustodyEpoch(
            company_id=tenant.company_id,
            vehicle_id=vehicle_id,
            vehicle_location_id=vehicle_location,
            custodian_kind="FIELD_REPRESENTATIVE",
            custodian_principal_id=int(bridge.field_principal_id),
            field_representative_id=int(bridge.field_representative_id),
            accepted_by_principal_id=int(bridge.field_principal_id),
            state="ACCEPTED", context_revision=revision,
            started_at=now,
            request_id=str(uuid4()),
            payload_hash=hashlib.sha256(b"m02-synthetic-field-signed-acceptance").hexdigest(),
            handoff_reference="M02-SIGNED-FIELD-FIXTURE",
        )
        db.add(signed)
        await db.commit()
        return revision


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_m02_postpone_bound_s1_resume_signed_custody_replay_aba_and_no_stock(pg):
    tenant, foreign = pg.tenants
    key, launch, car_location = await _prepared_route(pg, tenant)
    async with _real_http() as http:
        owner = await _owner(http, pg, tenant)
        foreign_owner = await _owner(http, pg, foreign)
        launch_result = await http.post("/dispatch/route", headers=owner, json=launch)
        assert launch_result.status_code == 201, launch_result.text
        route_id = int(launch_result.json()["route_id"])
        async with pg.session() as db:
            context_id = await db.scalar(select(RouteCommercialContext.id).where(
                RouteCommercialContext.company_id == tenant.company_id,
                RouteCommercialContext.dispatch_route_id == route_id,
            ))
            assert context_id
            # Existing M01-compatible session-bound route under the same
            # legitimate FIELD driver; M02 command itself is real Bearer HTTP.
            s1 = WorkSession(
                company_id=tenant.company_id, driver_id=int(launch["driver_id"]),
                commercial_context_id=context_id,
                session_date=datetime.now(timezone.utc).date(),
                start_time=datetime.now(timezone.utc).replace(tzinfo=None),
                is_settled=False,
            )
            db.add(s1)
            await db.flush()
            route = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == tenant.company_id,
                DispatchRoute.id == route_id,
            ).with_for_update())
            route.work_session_id = s1.id
            await db.commit()

        before = await _snapshot(pg, tenant, route_id, car_location, key)
        pause_key = uuid4()
        pause = _body("POSTPONE", 1, key=pause_key)
        url = f"/dispatch/route/{route_id}/lifecycle"
        missing_bearer = await http.put(url, json=pause)
        assert missing_bearer.status_code == 401, missing_bearer.text
        wrong_tenant = await http.put(url, headers=foreign_owner, json=pause)
        assert wrong_tenant.status_code in (403, 404), wrong_tenant.text

        paused = await http.put(url, headers=owner, json=pause)
        assert paused.status_code == 200, paused.text
        assert paused.json()["status"] == "postponed"
        assert paused.json()["context_revision"] == 2
        assert paused.json()["live_assets_reserved"] is False
        replay = await http.put(url, headers=owner, json=pause)
        assert replay.status_code == 200 and replay.json() == paused.json()
        wrong_payload = await http.put(
            url, headers=owner, json={**pause, "expected_context_revision": 2},
        )
        assert wrong_payload.status_code == 409, wrong_payload.text
        legacy_bypass = await http.put(
            f"/dispatch/route/{route_id}/status", headers=owner,
            json={"status": "active"},
        )
        assert legacy_bypass.status_code == 409, legacy_bypass.text

        after_pause = await _snapshot(pg, tenant, route_id, car_location, key)
        assert after_pause["status"] == "postponed"
        assert before["real_stock"]["balances"] == after_pause["real_stock"]["balances"]
        assert before["real_stock"]["movements"] == after_pause["real_stock"]["movements"]
        assert before["real_stock"]["visits"] == after_pause["real_stock"]["visits"]
        assert before["real_stock"]["cost_events"] == after_pause["real_stock"]["cost_events"]
        assert after_pause["legacy_session"] == before["legacy_session"]

        # A historical S1 can be fully settled after POSTPONE. Resuming this
        # yesterday route must create a NEW period, never reopen S1 or rewrite
        # its prior commercial/visit/stock attribution.
        yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
        async with pg.session() as db:
            historical_session = await db.scalar(select(WorkSession).where(
                WorkSession.company_id == tenant.company_id,
                WorkSession.id == int(before["legacy_session"]),
            ).with_for_update())
            historical_route = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == tenant.company_id,
                DispatchRoute.id == route_id,
            ).with_for_update())
            assert historical_session and historical_route
            historical_session.session_date = yesterday
            historical_session.end_time = datetime.now(timezone.utc).replace(tzinfo=None)
            historical_session.is_settled = True
            historical_route.dispatch_date = yesterday
            await db.commit()

        # Before any explicit signed acceptance, old loaded vehicle ownership
        # must NOT be inferred from the legacy route, even when it is the same
        # driver's earlier car.
        premature = await http.put(
            url, headers=owner, json=_body(
                "RESUME", 2, driver=int(launch["driver_id"]),
                vehicle=int(launch["vehicle_id"]), custody=1,
            ),
        )
        assert premature.status_code == 409, premature.text

        # Real PostgreSQL unique-index check: POSTPONED reserves zone only,
        # not old Driver/Vehicle. A second different-zone route can use both;
        # the postponed zone remains fully protected at DB level.
        async with pg.session() as db:
            duplicate_zone = DispatchRoute(
                company_id=tenant.company_id, zone_id=int(launch["zone_id"]),
                driver_id=int(launch["driver_id"]),
                vehicle_id=int(launch["vehicle_id"]),
                source_location_id=tenant.location_id,
                status="waiting",
                dispatch_date=datetime.now(timezone.utc).date(),
            )
            db.add(duplicate_zone)
            with pytest.raises(IntegrityError):
                await db.flush()
            await db.rollback()
        async with pg.session() as db:
            second_zone = Zone(
                company_id=tenant.company_id,
                name="M02-SECOND-" + uuid4().hex[:10],
                is_active=True,
            )
            db.add(second_zone)
            await db.flush()
            second_route = DispatchRoute(
                company_id=tenant.company_id, zone_id=second_zone.id,
                driver_id=int(launch["driver_id"]),
                vehicle_id=int(launch["vehicle_id"]),
                source_location_id=tenant.location_id,
                status="waiting",
                dispatch_date=datetime.now(timezone.utc).date(),
            )
            db.add(second_route)
            await db.commit()
            second_route_id = int(second_route.id)
        # Even with the original car's signed custody, concurrent occupation
        # on a different live route must reject the old paused route's RESUME.
        custody_revision = await _explicitly_accept_vehicle(
            pg, tenant, driver_id=int(launch["driver_id"]),
            vehicle_id=int(launch["vehicle_id"]), vehicle_location=car_location,
        )
        attempted_conflict = _body(
            "RESUME", 2, driver=int(launch["driver_id"]),
            vehicle=int(launch["vehicle_id"]), custody=custody_revision,
        )
        conflict_response = await http.put(url, headers=owner, json=attempted_conflict)
        assert conflict_response.status_code == 409, conflict_response.text
        async with pg.session() as db:
            secondary = await db.scalar(select(DispatchRoute).where(
                DispatchRoute.company_id == tenant.company_id,
                DispatchRoute.id == second_route_id,
            ).with_for_update())
            assert secondary.status == "waiting"
            secondary.status = "closed"  # Setup cleanup, not a lifecycle proof.
            await db.commit()
        assert (await _snapshot(pg, tenant, route_id, car_location, key))[
            "real_stock"
        ]["movements"] == before["real_stock"]["movements"]

        # A signed current holder is not enough: a mismatched expected epoch
        # revision must still reject (and must not create a second period).
        denied = _body("RESUME", 2, driver=int(launch["driver_id"]),
                       vehicle=int(launch["vehicle_id"]), custody=custody_revision + 1)
        stale_custody = await http.put(url, headers=owner, json=denied)
        assert stale_custody.status_code == 409, stale_custody.text
        resume = _body("RESUME", 2, driver=int(launch["driver_id"]),
                       vehicle=int(launch["vehicle_id"]), custody=custody_revision)
        simultaneous = await asyncio.gather(*[
            http.put(url, headers=owner, json=resume) for _ in range(2)
        ])
        assert [x.status_code for x in simultaneous] == [200, 200], [
            x.text for x in simultaneous
        ]
        assert simultaneous[0].json() == simultaneous[1].json()
        assert simultaneous[0].json()["context_revision"] == 3
        assert simultaneous[0].json()["status"] == "active"
        after_resume = await _snapshot(pg, tenant, route_id, car_location, key)
        assert len(after_resume["periods"]) == len(after_pause["periods"]) + 1
        assert after_resume["periods"][-1][4] == 3
        assert after_resume["real_stock"]["balances"] == before["real_stock"]["balances"]
        assert after_resume["real_stock"]["movements"] == before["real_stock"]["movements"]
        assert after_resume["real_stock"]["visits"] == before["real_stock"]["visits"]
        assert after_resume["legacy_session"] == before["legacy_session"]
        # A previously valid legacy Adjust Load request must not touch old
        # physical car A after canonical assignment rev > 1, even when the
        # legacy vehicle happens to equal the current car (ABA protection).
        obsolete_adjust = await http.put(
            f"/dispatch/route/{route_id}/adjust_inventory",
            headers=owner,
            json={
                "request_id": str(uuid4()),
                "context": {
                    "version": "ADJUST_LOAD_CONTEXT_V2",
                    "vehicle_id": int(launch["vehicle_id"]),
                    "source_warehouse_id": tenant.location_id,
                    "work_session_id": int(after_resume["legacy_session"]),
                    "route_context_revision": 1,
                },
                "deltas": [{
                    "product_id": tenant.variant_id,
                    "delta_base": "1",
                }],
            },
        )
        assert obsolete_adjust.status_code == 409, obsolete_adjust.text
        assert "ROUTE_CURRENT_EPOCH_REQUIRED" in obsolete_adjust.text
        assert (await _snapshot(pg, tenant, route_id, car_location, key))[
            "real_stock"
        ]["movements"] == before["real_stock"]["movements"]
        stale = await http.put(
            url, headers=owner,
            json=_body("POSTPONE", 2, period=after_resume["periods"][-1][0]),
        )
        assert stale.status_code == 409
        closed_period = await http.put(
            url, headers=owner,
            json=_body("POSTPONE", 3, period=after_resume["periods"][-1][0]),
        )
        assert closed_period.status_code == 200, closed_period.text
        assert closed_period.json()["context_revision"] == 4
        after_second_pause = await _snapshot(pg, tenant, route_id, car_location, key)
        assert after_second_pause["real_stock"]["balances"] == before["real_stock"]["balances"]
        assert after_second_pause["real_stock"]["movements"] == before["real_stock"]["movements"]
        assert after_second_pause["periods"][-1][-1] is True

        # M02 multi-actor/multi-car: a newly authorized FIELD representative
        # with explicitly accepted responsibility for empty B can resume the
        # ORIGINAL postponed route. A's stock and prior S1 identity stay put.
        async with pg.session() as db:
            another_field = await seed_field_fixture(db, tenant.company_id)
            await assign_new_representative_default(
                db, tenant.company_id, another_field.context.representative_id,
            )
            await db.commit()
            other_driver = int(another_field.driver.id)
        other_vehicle, other_location = await _vehicle(pg, tenant)
        other_custody_revision = await _explicitly_accept_vehicle(
            pg, tenant, driver_id=other_driver,
            vehicle_id=other_vehicle, vehicle_location=other_location,
        )
        other_resume = _body(
            "RESUME", 4, driver=other_driver,
            vehicle=other_vehicle, custody=other_custody_revision,
        )
        active_other = await http.put(url, headers=owner, json=other_resume)
        assert active_other.status_code == 200, active_other.text
        assert active_other.json()["context_revision"] == 5
        new_assignment = await _snapshot(pg, tenant, route_id, car_location, key)
        assert new_assignment["periods"][-1][1:4] == (
            "PLANNED", other_driver, other_vehicle
        )
        assert new_assignment["legacy_session"] == before["legacy_session"]
        assert new_assignment["real_stock"]["balances"] == before["real_stock"]["balances"]
        assert new_assignment["real_stock"]["movements"] == before["real_stock"]["movements"]
        assert new_assignment["real_stock"]["visits"] == before["real_stock"]["visits"]
        async with pg.session() as db:
            assert int(await db.scalar(select(func.count()).select_from(
                InventoryMovement
            ).where(
                InventoryMovement.company_id == tenant.company_id,
                InventoryMovement.source_location_id == other_location,
            )) or 0) == 0
        # Repeating stale earlier A period against now-visible B cannot
        # mutate anything, even though the route ID remains the same.
        old_period_again = await http.put(
            url, headers=owner, json=_body(
                "POSTPONE", 3, period=after_resume["periods"][-1][0],
            ),
        )
        assert old_period_again.status_code == 409

        # An explicit recurring zone schedule moves to the next company
        # business date when closing. It does NOT revive this historical
        # route ID or touch its old visit/finance/stock evidence.
        async with pg.session() as db:
            zone = await db.scalar(select(Zone).where(
                Zone.company_id == tenant.company_id,
                Zone.id == int(launch["zone_id"]),
            ).with_for_update())
            local_day = await get_company_local_date(db, tenant.company_id)
            zone.start_date = local_day
            zone.interval_days = 7
            await db.commit()

        closed = await http.put(
            url, headers=owner,
            json=_body("CLOSE", 5, period=new_assignment["periods"][-1][0]),
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"
        assert closed.json()["zone_reserved"] is False
        final = await _snapshot(pg, tenant, route_id, car_location, key)
        assert final["real_stock"]["balances"] == before["real_stock"]["balances"]
        assert final["real_stock"]["movements"] == before["real_stock"]["movements"]
        assert final["real_stock"]["visits"] == before["real_stock"]["visits"]
        async with pg.session() as db:
            zone = await db.scalar(select(Zone).where(
                Zone.company_id == tenant.company_id,
                Zone.id == int(launch["zone_id"]),
            ))
            assert zone.start_date == local_day + timedelta(days=7)
            assert zone.interval_days == 7
            replacement = DispatchRoute(
                company_id=tenant.company_id,
                zone_id=int(launch["zone_id"]),
                driver_id=other_driver,
                vehicle_id=other_vehicle,
                source_location_id=tenant.location_id,
                status="waiting",
                dispatch_date=zone.start_date,
            )
            db.add(replacement)
            await db.commit()
            assert replacement.id != route_id
        assert (await _snapshot(pg, tenant, route_id, car_location, key))[
            "real_stock"
        ]["movements"] == before["real_stock"]["movements"]
        print("M02_BOUND_S1_POSTPONE_RESUME_SIGNED_CUSTODY_ABA_NO_STOCK=PASS", flush=True)


@pytest.mark.parametrize("pg", ["FIFO"], indirect=True)
async def test_m02_different_request_ids_same_expected_revision_one_wins_one_409(pg):
    """Distinct UUIDs are NOT replays: concurrent same-version RESUMEs race."""
    tenant = pg.tenants[0]
    key, launch, car_location = await _prepared_route(pg, tenant)
    async with _real_http() as http:
        owner = await _owner(http, pg, tenant)
        launched = await http.post("/dispatch/route", headers=owner, json=launch)
        assert launched.status_code == 201, launched.text
        rid = int(launched.json()["route_id"])
        url = f"/dispatch/route/{rid}/lifecycle"
        before = await _snapshot(pg, tenant, rid, car_location, key)
        paused = await http.put(
            url, headers=owner, json=_body("POSTPONE", 1),
        )
        assert paused.status_code == 200, paused.text
        epoch = await _explicitly_accept_vehicle(
            pg, tenant, driver_id=int(launch["driver_id"]),
            vehicle_id=int(launch["vehicle_id"]), vehicle_location=car_location,
        )
        first = _body("RESUME", 2, driver=int(launch["driver_id"]),
                      vehicle=int(launch["vehicle_id"]), custody=epoch)
        second = _body("RESUME", 2, driver=int(launch["driver_id"]),
                       vehicle=int(launch["vehicle_id"]), custody=epoch)
        assert first["request_id"] != second["request_id"]
        results = await asyncio.gather(
            http.put(url, headers=owner, json=first),
            http.put(url, headers=owner, json=second),
        )
        assert sorted(r.status_code for r in results) == [200, 409], [
            (r.status_code, r.text) for r in results
        ]
        winner = next(r for r in results if r.status_code == 200)
        loser = first if results[0].status_code == 409 else second
        assert winner.json()["context_revision"] == 3
        after = await _snapshot(pg, tenant, rid, car_location, key)
        assert len(after["periods"]) == 1
        assert after["periods"][0][4] == 3
        assert after["real_stock"]["balances"] == before["real_stock"]["balances"]
        assert after["real_stock"]["movements"] == before["real_stock"]["movements"]
        assert after["real_stock"]["visits"] == before["real_stock"]["visits"]
        retry_loser = await http.put(url, headers=owner, json=loser)
        assert retry_loser.status_code == 409
        assert (await _snapshot(pg, tenant, rid, car_location, key))[
            "real_stock"
        ] == after["real_stock"]
        print("M02_DISTINCT_UUID_CONCURRENT_RESUME_ONE_200_ONE_409=PASS", flush=True)
