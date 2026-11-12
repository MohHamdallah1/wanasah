"""M06 independent, test-only signed FIELD A/B/A edge acceptance on merged M01–M04.

M04's accepted real S1 count A+B -> money once -> automatic S2 scenario is
REUSED as existing evidence, not copied into this module. This extra gate
targets cross-route competition and stale offline commands between its steps.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DispatchRoute, Visit, WorkSession
from tests.field_authorization_phase3_fixture import PASSWORD
from tests.test_dispatch_m03_integrated_postgres import (
    gate, _set_period, _prepare_real_b, _physical, _move_count,
    _current, _sale, _headers, _intent,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("RUN_M06_OWNER_PG16") != "1",
        reason="M06 only: disposable restricted PG16 plus real FIELD/Backoffice HTTP",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


async def test_owner_a_b_a_cross_route_stale_auth_race_without_phantom_stock(gate):
    g = gate
    a_period, a_epoch, _ = await _set_period(g)
    b_route, b_vehicle, b_location, b_visit, a_last_visit, _ = await _prepare_real_b(g)
    assert (await _physical(g, g.location), await _physical(g, b_location)) == (100, 60)
    sign_in = await g.client.post("/login", json={
        "company_code": g.company_code,
        "username": g.owner_name, "password": PASSWORD,
    })
    assert sign_in.status_code == 200, sign_in.text
    manager = {"Authorization": "Bearer " + sign_in.json()["token"]}
    foreign_sign_in = await g.client.post("/login", json={
        "company_code": g.foreign.company_code,
        "username": g.foreign.owner_name, "password": PASSWORD,
    })
    assert foreign_sign_in.status_code == 200, foreign_sign_in.text
    foreign_manager = {"Authorization": "Bearer " + foreign_sign_in.json()["token"]}

    # The historical test fixture creates genuinely pending inbound transfers.
    # Resolve them with FIELD authorization before the commercial journey.
    rejected = await g.client.put(
        "/driver/transfers/batch_respond", headers=_headers(g.token), json={
            "transfers": [
                {"transfer_id": t, "status": "rejected", "reason": "M06 owner acceptance"}
                for t in g.transfers
            ],
        },
    )
    assert rejected.status_code == 200, rejected.text

    a = await _current(g)
    assert a["period_id"] == a_period and a["custody_epoch_id"] == a_epoch
    assert a["session_id"] == g.session
    await _sale(g, g.visit, 12, a)
    assert (await _physical(g, g.location), await _physical(g, b_location)) == (88, 60)
    baseline = await _move_count(g)

    r1 = f"/dispatch/route/{g.route}/lifecycle"
    r2 = f"/dispatch/route/{b_route}/lifecycle"
    postpone = _intent("POSTPONE", 2, period=a_period)
    missing = await g.client.put(r1, json=postpone)
    assert missing.status_code == 401
    foreign = await g.client.put(r1, headers=foreign_manager, json=postpone)
    assert foreign.status_code in (403, 404), foreign.text
    paused = await g.client.put(r1, headers=manager, json=postpone)
    assert paused.status_code == 200 and paused.json()["status"] == "postponed", paused.text
    duplicate = await g.client.put(r1, headers=manager, json=postpone)
    assert duplicate.status_code == 200 and duplicate.json() == paused.json()
    assert await _move_count(g) == baseline

    # Zone A remains reserved; the driver and car A are released by A's
    # POSTPONE. They are not implicitly reassigned or stripped of physical stock.
    async with AsyncSession(g.admin) as db:
        route = await db.scalar(select(DispatchRoute).where(
            DispatchRoute.company_id == g.tenant, DispatchRoute.id == g.route,
        ))
        assert route.status == "postponed"
    assert (await _physical(g, g.location), await _physical(g, b_location)) == (88, 60)

    # TWO genuinely distinct manager UUIDs compete for the same B revision.
    # The DB lock/CAS, not frontend disabled buttons, decides the winner.
    candidate_1 = _intent(
        "RESUME", 1, driver=g.field.driver.id, vehicle=b_vehicle, custody=1,
    )
    candidate_2 = _intent(
        "RESUME", 1, driver=g.field.driver.id, vehicle=b_vehicle, custody=1,
    )
    results = await asyncio.gather(
        g.client.put(r2, headers=manager, json=candidate_1),
        g.client.put(r2, headers=manager, json=candidate_2),
    )
    assert sorted(x.status_code for x in results) == [200, 409], [
        (x.status_code, x.text[:200]) for x in results
    ]
    winning = candidate_1 if results[0].status_code == 200 else candidate_2
    losing = candidate_2 if results[0].status_code == 200 else candidate_1
    again = await g.client.put(r2, headers=manager, json=winning)
    assert again.status_code == 200
    assert again.json() == next(x.json() for x in results if x.status_code == 200)
    denied_again = await g.client.put(r2, headers=manager, json=losing)
    assert denied_again.status_code == 409
    assert await _move_count(g) == baseline

    b = await _current(g)
    assert b["route_id"] == b_route and b["vehicle_location_id"] == b_location
    assert b["session_id"] == g.session
    assert b["period_id"] != a_period
    stale_a = await g.client.put(
        f"/visits/{a_last_visit}", headers=_headers(
            g.token, a_period, a["assignment_context_revision"], a_epoch,
        ),
        json={"request_id": str(uuid4()), "outcome": "Sale", "cash_collected": "1",
              "cart_items": [{"product_variant_id": g.variant["id"], "packs_quantity": 1}]},
    )
    assert stale_a.status_code == 409, stale_a.text
    forbidden_visit = await g.client.put(
        f"/visits/{b_visit}", headers=_headers(
            g.foreign_token, b["period_id"],
            b["assignment_context_revision"], b["custody_epoch_id"],
        ),
        json={"request_id": str(uuid4()), "outcome": "Sale", "cash_collected": "1",
              "cart_items": [{"product_variant_id": g.variant["id"], "packs_quantity": 1}]},
    )
    assert forbidden_visit.status_code == 409, forbidden_visit.text
    assert forbidden_visit.json()["error"]["code"] == "M03_NO_ACTIVE_EXECUTION_PERIOD"
    assert await _move_count(g) == baseline

    await _sale(g, b_visit, 7, b)
    assert (await _physical(g, g.location), await _physical(g, b_location)) == (88, 53)
    after_b_sale = await _move_count(g)
    p_b = await g.client.put(
        r2, headers=manager,
        json=_intent("POSTPONE", 2, period=b["period_id"]),
    )
    assert p_b.status_code == 200, p_b.text
    resumed = await g.client.put(
        r1, headers=manager,
        json=_intent("RESUME", 3, driver=g.field.driver.id,
                     vehicle=g.vehicle, custody=1),
    )
    assert resumed.status_code == 200, resumed.text
    assert await _move_count(g) == after_b_sale

    a_again = await _current(g)
    assert a_again["session_id"] == g.session
    assert a_again["route_id"] == g.route
    assert a_again["vehicle_location_id"] == g.location
    assert a_again["period_id"] not in (a_period, b["period_id"])
    stale_b = await g.client.put(
        f"/visits/{a_last_visit}", headers=_headers(
            g.token, b["period_id"], b["assignment_context_revision"],
            b["custody_epoch_id"],
        ),
        json={"request_id": str(uuid4()), "outcome": "Sale", "cash_collected": "1",
              "cart_items": [{"product_variant_id": g.variant["id"], "packs_quantity": 1}]},
    )
    assert stale_b.status_code == 409, stale_b.text
    assert await _move_count(g) == after_b_sale

    await _sale(g, a_last_visit, 5, a_again)
    assert (await _physical(g, g.location), await _physical(g, b_location)) == (83, 53)
    async with AsyncSession(g.admin) as db:
        completed = (await db.scalars(select(Visit).where(
            Visit.company_id == g.tenant,
            Visit.id.in_([g.visit, b_visit, a_last_visit]),
        ))).all()
        assert len(completed) == 3
        assert {v.work_session_id for v in completed} == {g.session}
        assert {v.execution_period_id for v in completed} == {
            a_period, b["period_id"], a_again["period_id"],
        }
        assert sum(Decimal(v.cash_collected) for v in completed) == Decimal("3.000")
        assert all(v.status == "Completed" for v in completed)

    done = await g.client.put("/driver/sessions/end", headers=_headers(g.token))
    assert done.status_code == 200, done.text
    assert (await _physical(g, g.location), await _physical(g, b_location)) == (83, 53)
    early_s2 = await g.client.post(
        "/driver/sessions/start",
        headers={**_headers(g.token), "Idempotency-Key": str(uuid4())},
        json={},
    )
    assert early_s2.status_code == 400, early_s2.text
    async with AsyncSession(g.admin) as db:
        s1 = await db.scalar(select(WorkSession).where(
            WorkSession.company_id == g.tenant, WorkSession.id == g.session,
        ))
        assert s1.end_time is not None and s1.is_settled is False
    print("M06_SIGNED_A_B_A_OWNERSHIP_RACE_REPLAY_STALE_TENANT_PHYSICAL=PASS", flush=True)
