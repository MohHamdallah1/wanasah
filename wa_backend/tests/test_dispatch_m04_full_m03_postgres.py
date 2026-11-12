"""Real M03+M04 overlay-only A/B/A FIELD/Backoffice acceptance.

This is not checked into PR #944 until M03 owner merges and LEAD supplies MAIN.
No fake is_settled, no manual stock balance mutations during lifecycle, and
no runtime overrides. All commands are genuine HTTP on isolated PG16.
"""
from decimal import Decimal
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from models import Company, InventoryMovement, SystemAuditLog, Visit, WorkSession, Shop
from domains.representative_settlement_multi_vehicle.models import VehicleCustodyCheckpoint
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from tests.field_authorization_phase3_fixture import PASSWORD
from tests.test_dispatch_m03_integrated_postgres import (
    gate, _set_period, _prepare_real_b, _physical, _move_count, _current,
    _sale, _headers, _intent,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("RUN_M04_FULL_INTEGRATED") != "1",
        reason="Exact isolated M03+M04 migration and PG16 required",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


async def test_real_field_aba_end_then_signed_two_car_count_real_finance_once_and_s2_guard(gate):
    g = gate
    p1, a_epoch, _ = await _set_period(g)
    r2, vehicle_b, location_b, visit_b, visit_a3, epoch_b = await _prepare_real_b(g)
    assert (await _physical(g, g.location), await _physical(g, location_b)) == (100, 60)
    # Separate original pending Zone A shop survives real financial close and
    # is carried forward as the SAME Visit identity on next-day S2.
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        first_visit = await db.scalar(select(Visit).where(
            Visit.company_id == g.tenant, Visit.id == g.visit,
        ))
        shop = await db.scalar(select(Shop).where(
            Shop.company_id == g.tenant, Shop.id == first_visit.shop_id,
        ))
        pending_shop = Shop(company_id=g.tenant, zone_id=g.zone,
                            name="M04 remaining " + uuid4().hex[:8],
                            tax_jurisdiction_id=shop.tax_jurisdiction_id,
                            max_debt_limit=Decimal("500000"), is_active=True)
        db.add(pending_shop)
        await db.flush()
        pending_id = 1_819_000_000 + int(uuid4().hex[:5], 16)
        db.add(Visit(id=pending_id, company_id=g.tenant, shop_id=pending_shop.id,
                     driver_id=g.field.driver.id, operational_date=date.today(),
                     status="Pending", outcome="Pending", sequence=4))
        await db.commit()

    login = await g.client.post("/login", json={
        "company_code": g.company_code, "username": g.owner_name, "password": PASSWORD,
    })
    assert login.status_code == 200, login.text
    owner = {"Authorization": "Bearer " + login.json()["token"]}
    field = _headers(g.token)
    reject = await g.client.put("/driver/transfers/batch_respond", json={
        "transfers": [
            {"transfer_id": t, "status": "rejected", "reason": "M04 acceptance"}
            for t in g.transfers
        ],
    }, headers=field)
    assert reject.status_code == 200, reject.text

    proof_a1 = await _current(g)
    assert proof_a1["session_id"] == g.session and proof_a1["period_id"] == p1
    await _sale(g, g.visit, 12, proof_a1)
    assert await _physical(g, g.location) == 88

    p = await g.client.put(
        f"/dispatch/route/{g.route}/lifecycle",
        headers=owner, json=_intent("POSTPONE", 2, period=p1),
    )
    assert p.status_code == 200, p.text
    p = await g.client.put(
        f"/dispatch/route/{r2}/lifecycle",
        headers=owner,
        json=_intent("RESUME", 1, driver=g.field.driver.id,
                     vehicle=vehicle_b, custody=1),
    )
    assert p.status_code == 200, p.text
    proof_b = await _current(g)
    assert proof_b["vehicle_location_id"] == location_b
    await _sale(g, visit_b, 7, proof_b)
    assert await _physical(g, location_b) == 53

    p = await g.client.put(
        f"/dispatch/route/{r2}/lifecycle", headers=owner,
        json=_intent("POSTPONE", 2, period=proof_b["period_id"]),
    )
    assert p.status_code == 200, p.text
    p = await g.client.put(
        f"/dispatch/route/{g.route}/lifecycle", headers=owner,
        json=_intent("RESUME", 3, driver=g.field.driver.id,
                     vehicle=g.vehicle, custody=1),
    )
    assert p.status_code == 200, p.text
    proof_a3 = await _current(g)
    await _sale(g, visit_a3, 5, proof_a3)
    assert (await _physical(g, g.location), await _physical(g, location_b)) == (83, 53)
    sales_movements = await _move_count(g)

    # True FIELD End Work closes S1's daily periods without closing the route,
    # moving stock or auto-settling any inventory/financial responsibility.
    ending = await g.client.put("/driver/sessions/end", headers=field)
    assert ending.status_code == 200, ending.text
    assert await _move_count(g) == sales_movements
    async with AsyncSession(g.admin) as db:
        periods = (await db.scalars(select(DispatchRouteExecutionPeriod).where(
            DispatchRouteExecutionPeriod.company_id == g.tenant,
            DispatchRouteExecutionPeriod.work_session_id == g.session,
        ))).all()
        assert len(periods) == 3 and all(x.state == "CLOSED" for x in periods)

    # No S2 before full S1: prior-unsettled FIELD rule remains untouched.
    denied = await g.client.post("/driver/sessions/start",
                                 headers={**field, "Idempotency-Key": str(uuid4())},
                                 json={})
    assert denied.status_code == 400, denied.text

    financial_path = f"/admin/sessions/{g.session}/settle"
    financial = {"request_id": str(uuid4()), "actual_cash": "3.000"}
    before = await g.client.put(financial_path, headers=owner, json=financial)
    assert before.status_code == 409, before.text

    sheets_path = f"/admin/sessions/{g.session}/inventory-custody/vehicles"
    membership = await g.client.get(sheets_path, headers=owner)
    assert membership.status_code == 200, membership.text
    assert {x["vehicle_id"] for x in membership.json()["vehicles"]} == {
        g.vehicle, vehicle_b,
    }
    assert not membership.json()["all_vehicle_counts_signed"]

    for index, vehicle_id in enumerate((g.vehicle, vehicle_b)):
        path = sheets_path + f"/{vehicle_id}"
        sheet = await g.client.get(path, headers=owner)
        assert sheet.status_code == 200, sheet.text
        command = {
            "request_id": str(uuid4()), "mode": "COUNT_IN_PLACE",
            "receiver_confirms_count": True,
            "snapshot_token": sheet.json()["snapshot_token"],
            "items": [
                {"line_key": row["line_key"], "actual_quantity": row["expected_quantity"]}
                for row in sheet.json()["lines"]
            ],
        }
        first = await g.client.post(path + "/count", headers=owner, json=command)
        assert first.status_code == 200, first.text
        assert first.json()["movement_count"] == 0
        assert await _move_count(g) == sales_movements
        replay = await g.client.post(path + "/count", headers=owner, json=command)
        assert replay.status_code == 200 and replay.json() == first.json()
        if index == 0:
            incomplete = await g.client.put(financial_path, headers=owner, json=financial)
            assert incomplete.status_code == 409, incomplete.text
    final_list = await g.client.get(sheets_path, headers=owner)
    assert final_list.status_code == 200 and final_list.json()["all_vehicle_counts_signed"]
    posted = await g.client.put(financial_path, headers=owner, json=financial)
    assert posted.status_code == 200 and posted.json()["is_settled"], posted.text
    again = await g.client.put(financial_path, headers=owner, json=financial)
    assert again.status_code == 200 and again.json() == posted.json()
    collision = await g.client.put(financial_path, headers=owner, json={
        **financial, "request_id": str(uuid4()),
    })
    assert collision.status_code == 409, collision.text

    assert (await _physical(g, g.location), await _physical(g, location_b)) == (83, 53)
    assert await _move_count(g) == sales_movements
    async with AsyncSession(g.admin) as db:
        settled = await db.scalar(select(WorkSession.is_settled).where(
            WorkSession.company_id == g.tenant, WorkSession.id == g.session,
        ))
        assert settled is True
        assert await db.scalar(select(func.count()).select_from(VehicleCustodyCheckpoint).where(
            VehicleCustodyCheckpoint.company_id == g.tenant,
            VehicleCustodyCheckpoint.work_session_id == g.session,
        )) == 2
        assert await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
            SystemAuditLog.company_id == g.tenant,
            SystemAuditLog.action_type == "FINANCIAL_SETTLEMENT",
            SystemAuditLog.target_id == f"Session_{g.session}_Driver_{g.field.driver.id}",
        )) == 1
        assert await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
            SystemAuditLog.company_id == g.tenant,
            SystemAuditLog.action_type == "REPRESENTATIVE_CUSTODY_RECEIVED",
            SystemAuditLog.target_id == f"WorkSession_{g.session}",
        )) == 0
        old_visits = (await db.scalars(select(Visit).where(
            Visit.company_id == g.tenant,
            Visit.id.in_([g.visit, visit_b, visit_a3]),
        ))).all()
        assert len(old_visits) == 3
        assert {x.work_session_id for x in old_visits} == {g.session}
        assert sum(Decimal(x.cash_collected) for x in old_visits) == Decimal("3.000")

    # M03 e0c34ce currently lacks automatic next-day PLANNED period/visit
    # carry-forward. The genuine M04 settlement IS complete here; expose the
    # still-unimplemented S2 continuity as an explicit cross-worker blocker.
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        current_company = await db.scalar(select(Company).where(
            Company.id == g.tenant).with_for_update())
        current_company.timezone = "Pacific/Kiritimati"
        await db.commit()
    assert datetime.now(timezone.utc).astimezone(ZoneInfo("Pacific/Kiritimati")).date() > (
        await _s1_business_date(g)
    )
    day2_headers = {**field, "Idempotency-Key": str(uuid4())}
    s2 = await g.client.post("/driver/sessions/start", json={}, headers=day2_headers)
    assert s2.status_code == 201, s2.text
    s2_id = s2.json()["session_id"]
    assert s2_id != g.session
    # Same original signed route and accepted vehicle, but NEW S2 proof.
    s2_proof = await _current(g)
    assert s2_proof["session_id"] == s2_id
    assert s2_proof["route_id"] == g.route
    assert s2_proof["vehicle_location_id"] == g.location
    assert s2_proof["assignment_context_revision"] == 5
    assert s2_proof["period_id"] not in {p1, proof_b["period_id"], proof_a3["period_id"]}
    retry = await g.client.post("/driver/sessions/start", json={}, headers=day2_headers)
    assert retry.status_code == 201 and retry.json() == s2.json()
    old_visits_response = await g.client.get("/driver/visits", headers=field)
    assert old_visits_response.status_code == 200, old_visits_response.text
    assert [item["visit_id"] for item in old_visits_response.json()["visits"]].count(pending_id) == 1
    async with AsyncSession(g.admin) as db:
        s2_row = await db.scalar(select(WorkSession).where(
            WorkSession.company_id == g.tenant, WorkSession.id == s2_id,
        ))
        assert s2_row is not None and not s2_row.is_settled
        assert s2_row.inventory_reconciled_at is None
        assert await db.scalar(select(func.count()).select_from(Visit).where(
            Visit.company_id == g.tenant, Visit.work_session_id == s2_id,
        )) == 0
        old_pending = await db.scalar(select(Visit).where(
            Visit.company_id == g.tenant, Visit.id == pending_id,
        ))
        assert old_pending.status == "Pending"
    assert (await _physical(g, g.location), await _physical(g, location_b)) == (83, 53)


async def _s1_business_date(g):
    async with AsyncSession(g.admin) as db:
        return await db.scalar(select(WorkSession.session_date).where(
            WorkSession.company_id == g.tenant,
            WorkSession.id == g.session,
        ))
