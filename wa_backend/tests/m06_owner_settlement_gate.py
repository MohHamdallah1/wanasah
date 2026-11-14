"""M06 only: close the *same* signed A->B->A S1 after a PAUSE cycle.

Uses the established M04 HTTP count/financial contracts; never mocks stock,
marks a session settled, or changes another stage's fixtures.
"""
from datetime import datetime, timezone, date
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Company, Shop, SystemAuditLog, Visit, WorkSession
from domains.representative_settlement_multi_vehicle.models import VehicleCustodyCheckpoint
from tests.test_dispatch_m03_integrated_postgres import _current, _physical, _move_count


async def seed_one_original_pending_shop(g):
    """A genuinely pending Zone A visit must survive S1 and appear once in S2."""
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        first = await db.scalar(select(Visit).where(
            Visit.company_id == g.tenant, Visit.id == g.visit))
        original = await db.scalar(select(Shop).where(
            Shop.company_id == g.tenant, Shop.id == first.shop_id))
        shop = Shop(
            company_id=g.tenant, zone_id=g.zone, is_active=True,
            name="M06 next day " + uuid4().hex[:8],
            tax_jurisdiction_id=original.tax_jurisdiction_id,
            max_debt_limit=Decimal("500000"))
        db.add(shop)
        await db.flush()
        identifier = 1_827_000_000 + int(uuid4().hex[:5], 16)
        db.add(Visit(
            id=identifier, company_id=g.tenant, shop_id=shop.id,
            driver_id=g.field.driver.id, operational_date=date.today(),
            status="Pending", outcome="Pending", sequence=9))
        await db.commit()
        return identifier


async def accept_signed_two_car_settlement_and_s2(
    g, manager, field, vehicle_b, location_b, pending_visit_id, historic_periods
):
    before = await _move_count(g)
    settle_path = f"/admin/sessions/{g.session}/settle"
    financial = {"request_id": str(uuid4()), "actual_cash": "3.000"}
    denied = await g.client.put(settle_path, json=financial, headers=manager)
    assert denied.status_code == 409, denied.text

    vehicles_path = f"/admin/sessions/{g.session}/inventory-custody/vehicles"
    owners = await g.client.get(vehicles_path, headers=manager)
    assert owners.status_code == 200, owners.text
    assert {int(v["vehicle_id"]) for v in owners.json()["vehicles"]} == {
        int(g.vehicle), int(vehicle_b)}
    assert owners.json()["all_vehicle_counts_signed"] is False
    for idx, car in enumerate((g.vehicle, vehicle_b)):
        path = f"{vehicles_path}/{car}"
        snapshot = await g.client.get(path, headers=manager)
        assert snapshot.status_code == 200, snapshot.text
        command = {
            "request_id": str(uuid4()), "mode": "COUNT_IN_PLACE",
            "receiver_confirms_count": True,
            "snapshot_token": snapshot.json()["snapshot_token"],
            "items": [{"line_key": row["line_key"],
                       "actual_quantity": row["expected_quantity"]}
                      for row in snapshot.json()["lines"]],
        }
        counted = await g.client.post(path + "/count", headers=manager, json=command)
        assert counted.status_code == 200, counted.text
        assert counted.json()["movement_count"] == 0
        replay = await g.client.post(path + "/count", headers=manager, json=command)
        assert replay.status_code == 200 and replay.json() == counted.json()
        assert await _move_count(g) == before
        if idx == 0:
            half = await g.client.put(settle_path, headers=manager, json=financial)
            assert half.status_code == 409, half.text

    all_counted = await g.client.get(vehicles_path, headers=manager)
    assert all_counted.status_code == 200
    assert all_counted.json()["all_vehicle_counts_signed"]
    posted = await g.client.put(settle_path, headers=manager, json=financial)
    assert posted.status_code == 200 and posted.json()["is_settled"], posted.text
    replay = await g.client.put(settle_path, headers=manager, json=financial)
    assert replay.status_code == 200 and replay.json() == posted.json()
    collision = await g.client.put(settle_path, headers=manager, json={
        **financial, "request_id": str(uuid4())})
    assert collision.status_code == 409
    assert await _move_count(g) == before
    assert (await _physical(g, g.location), await _physical(g, location_b)) == (83, 53)

    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        s1 = await db.scalar(select(WorkSession).where(
            WorkSession.company_id == g.tenant, WorkSession.id == g.session))
        assert s1.end_time is not None and s1.is_settled is True
        assert await db.scalar(select(func.count()).select_from(VehicleCustodyCheckpoint).where(
            VehicleCustodyCheckpoint.company_id == g.tenant,
            VehicleCustodyCheckpoint.work_session_id == g.session)) == 2
        assert await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
            SystemAuditLog.company_id == g.tenant,
            SystemAuditLog.action_type == "FINANCIAL_SETTLEMENT",
            SystemAuditLog.target_id == f"Session_{g.session}_Driver_{g.field.driver.id}")) == 1
        assert await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
            SystemAuditLog.company_id == g.tenant,
            SystemAuditLog.action_type == "REPRESENTATIVE_CUSTODY_RECEIVED",
            SystemAuditLog.target_id == f"WorkSession_{g.session}")) == 0
        company = await db.scalar(select(Company).where(
            Company.id == g.tenant).with_for_update())
        company.timezone = "Pacific/Kiritimati"
        await db.commit()

    assert datetime.now(timezone.utc).astimezone(
        ZoneInfo("Pacific/Kiritimati")).date() > s1.session_date
    same_key = {**field, "Idempotency-Key": str(uuid4())}
    s2 = await g.client.post("/driver/sessions/start", headers=same_key, json={})
    assert s2.status_code == 201, s2.text
    assert s2.json()["session_id"] != g.session
    again = await g.client.post("/driver/sessions/start", headers=same_key, json={})
    assert again.status_code == 201 and again.json() == s2.json()
    current = await _current(g)
    assert current["session_id"] == s2.json()["session_id"]
    assert current["route_id"] == g.route
    assert current["vehicle_location_id"] == g.location
    assert current["period_id"] not in historic_periods
    visits = await g.client.get("/driver/visits", headers=field)
    assert visits.status_code == 200, visits.text
    assert [row["visit_id"] for row in visits.json()["visits"]].count(pending_visit_id) == 1
    async with AsyncSession(g.admin) as db:
        new = await db.scalar(select(WorkSession).where(
            WorkSession.company_id == g.tenant,
            WorkSession.id == s2.json()["session_id"]))
        assert new is not None and not new.is_settled
        assert new.inventory_reconciled_at is None
        assert await db.scalar(select(func.count()).select_from(Visit).where(
            Visit.company_id == g.tenant,
            Visit.work_session_id == new.id)) == 0
        historic = await db.scalar(select(Visit).where(
            Visit.company_id == g.tenant, Visit.id == pending_visit_id))
        assert historic.status == "Pending"
    assert (await _physical(g, g.location), await _physical(g, location_b)) == (83, 53)
    assert await _move_count(g) == before
    return {"s2": s2.json()["session_id"], "cash": "3.000", "stock_a": 83,
            "stock_b": 53, "signed_car_counts": 2}
