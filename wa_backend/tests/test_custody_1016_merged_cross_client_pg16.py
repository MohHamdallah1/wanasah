"""#1016: ONE real merged, two-Bearer Backoffice/FIELD custody integration on disposable PG16.

No production DB, no mocked HTTP, no random fabricated UI response shapes.
Tests current merged server/client JSON schemas by capturing real HTTP response
bodies for the Dashboard Vitest and Flutter Dart parser contract checks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine as runtime_engine
from models import InventoryBalance, InventoryCostEvent, InventoryMovement, Vehicle
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from tests.test_dispatch_m03_period_postgres import gate, _headers
from tests.test_dispatch_c01_c02_custody_postgres import (
    _setup_cars, _login_owner, _ledger_signature,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CUSTODY_1016_PG_GATE") != "1",
        reason="Explicit unique disposable PG16 signed integration only",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


def _uuid() -> str:
    return str(uuid4())


def _fields_only(data: dict, *keys: str):
    return {key: data[key] for key in keys}


async def test_merged_manager_field_custody_real_signed_e2e(gate):
    """Real HTTP authenticated manager and FIELD A/B, cancellation/change,
    physical count, old-request rejection and immutable original ledger.
    """
    g = gate
    assert os.environ["DATABASE_URL"].endswith("/m03_941_custody_1016")
    assert "@127.0.0.1:56616/" in os.environ["DATABASE_URL"]
    assert "custody1016_app@" in os.environ["DATABASE_URL"]
    manager = await _login_owner(g)
    other_manager = await _login_owner(g, g.foreign)
    field_a = _headers(g.token)
    field_b = _headers(g.other_token)
    unrelated_field = _headers(g.foreign_token)
    car, _, _ = await _setup_cars(g)
    vehicle_id = car[0]
    url = f"/vehicles/{vehicle_id}/custody/handoffs"
    readiness = f"/vehicles/{vehicle_id}/custody/readiness"
    review_url = f"/vehicles/{vehicle_id}/custody/stock-review"
    history_url = f"/vehicles/{vehicle_id}/custody/history?limit=20"

    async with runtime_engine.connect() as conn:
        role_flags = (await conn.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ))).one()
        assert tuple(role_flags) == (False, False)
        for table in ("vehicle_custody_handoffs", "vehicle_custody_epochs", "inventory_balances"):
            flags = (await conn.execute(text(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE oid=to_regclass(:name)"
            ), {"name": table})).one()
            assert tuple(flags) == (True, True), table
        version = (await conn.execute(text(
            "SELECT count(*) FROM information_schema.tables WHERE table_name='vehicle_custody_handoffs'"
        ))).scalar_one()
        assert version == 1
    original_inventory_signature = await _ledger_signature(g)
    async with AsyncSession(g.admin) as db:
        cost_before = int(await db.scalar(select(func.count()).select_from(
            InventoryCostEvent).where(InventoryCostEvent.company_id == g.tenant)) or 0)

    current_none = await g.client.get(url + "/current", headers=manager)
    assert current_none.status_code == 200 and current_none.json() is None, current_none.text
    preflight = await g.client.get(readiness, headers=manager)
    stock = await g.client.get(review_url, headers=manager)
    assert preflight.status_code == 200 and stock.status_code == 200, (preflight.text,stock.text)
    ready, stock_data = preflight.json(), stock.json()
    assert ready["state"] == "NEEDS_REVIEW"
    assert stock_data["vehicle_id"] == vehicle_id
    assert stock_data["context_revision"] == ready["context_revision"]
    assert stock_data["stock_snapshot"] == ready["stock_snapshot"]
    assert stock_data["stock_lines"] and stock_data["vehicle_plate"]
    assert any(
        line["product_name"] and line["base_uom"] and "batch_number" in line
        and "stock_status" in line and "on_hand_base" in line
        for line in stock_data["stock_lines"]
    )
    assert (await g.client.get(review_url, headers=other_manager)).status_code in (403, 404)

    def create_body(driver_id: int, evidence: dict) -> dict:
        return {
            "request_id": _uuid(), "target_driver_id": driver_id,
            "expected_context_revision": evidence["context_revision"],
            "expected_stock_snapshot": evidence["stock_snapshot"],
        }

    # Manager first chooses A, FIELD A confirms. Manager then explicitly cancels
    # AFTER A's count: A's confirmed evidence stays in audit but is NOT usable.
    first_body = create_body(g.field.driver.id, ready)
    first = await g.client.post(url, headers=manager, json=first_body)
    assert first.status_code == 200, first.text
    a_pending = first.json()
    a_id = a_pending["handoff_id"]
    assert type(a_id) is int and a_id > 0 and a_pending["state"] == "PENDING"
    manager_relogin = await _login_owner(g)
    restored = await g.client.get(url + "/current", headers=manager_relogin)
    assert restored.status_code == 200 and restored.json()["handoff_id"] == a_id
    assert restored.json()["target_driver_id"] == g.field.driver.id
    assert (await g.client.get(f"/driver/custody/handoffs/{a_id}",headers=field_b)).status_code == 404
    assert (await g.client.get(f"/driver/custody/handoffs/{a_id}",headers=unrelated_field)).status_code == 404
    a_inbox = await g.client.get("/driver/custody/handoffs/pending", headers=field_a)
    assert a_inbox.status_code == 200 and any(i["handoff_id"]==a_id for i in a_inbox.json()["items"])
    a_detail = await g.client.get(f"/driver/custody/handoffs/{a_id}", headers=field_a)
    assert a_detail.status_code == 200 and a_detail.json()["stock_lines"], a_detail.text
    a_confirm = await g.client.post(f"/driver/custody/handoffs/{a_id}/decision",headers=field_a,json={
        "request_id":_uuid(), "decision":"CONFIRM",
        "confirmed_stock_snapshot":a_detail.json()["stock_snapshot"],
        "receiver_confirms_physical_count":True,
    })
    assert a_confirm.status_code == 200 and a_confirm.json()["state"] == "CONFIRMED", a_confirm.text
    cancel_body = {"request_id": _uuid()}
    a_cancel = await g.client.post(f"{url}/{a_id}/cancel", headers=manager, json=cancel_body)
    assert a_cancel.status_code == 200 and a_cancel.json()["state"] == "CANCELLED", a_cancel.text
    assert a_cancel.json()["receiver_confirmed_at"]
    same_cancel = await g.client.post(f"{url}/{a_id}/cancel", headers=manager, json=cancel_body)
    assert same_cancel.status_code == 200 and same_cancel.json()["handoff_id"]==a_id
    reject_old = await g.client.post(f"{url}/{a_id}/approve",headers=manager,json={"request_id":_uuid()})
    assert reject_old.status_code == 409, reject_old.text
    old_detail = await g.client.get(f"/driver/custody/handoffs/{a_id}",headers=field_a)
    assert old_detail.status_code == 200 and old_detail.json()["state"]=="CANCELLED"
    assert old_detail.json()["stock_lines"]==[]

    # Real recipient change A -> B. Current revision/stock still unchanged.
    next_ready = await g.client.get(readiness,headers=manager)
    assert next_ready.status_code == 200 and next_ready.json()["context_revision"]==ready["context_revision"]
    b_body = create_body(g.other.driver.id, next_ready.json())
    created_b = await g.client.post(url,headers=manager,json=b_body)
    assert created_b.status_code == 200 and created_b.json()["state"]=="PENDING",created_b.text
    b_id=created_b.json()["handoff_id"]
    assert b_id>a_id
    assert (await g.client.get(f"/driver/custody/handoffs/{b_id}",headers=field_a)).status_code==404
    assert (await g.client.get(f"/driver/custody/handoffs/{b_id}",headers=unrelated_field)).status_code==404
    # This read is EXACTLY one bounded SQL statement for the entire inbox.
    seen = []
    def observe(conn,cursor,statement,params,ctx,executemany):
        if "SELECT" in statement and "vehicle_custody_handoffs" in statement:
            seen.append(statement)
    event.listen(runtime_engine.sync_engine,"before_cursor_execute",observe)
    try:
        b_inbox = await g.client.get("/driver/custody/handoffs/pending",headers=field_b)
    finally:
        event.remove(runtime_engine.sync_engine,"before_cursor_execute",observe)
    assert b_inbox.status_code==200 and len(seen)==1,(b_inbox.text,len(seen))
    b_rows=b_inbox.json()["items"]
    assert len(b_rows)==1 and b_rows[0]["handoff_id"]==b_id
    assert b_rows[0]["vehicle_plate"]==stock_data["vehicle_plate"]
    assert type(b_rows[0]["handoff_id"]) is int
    b_detail = await g.client.get(f"/driver/custody/handoffs/{b_id}", headers=field_b)
    assert b_detail.status_code==200 and b_detail.json()["stock_lines"],b_detail.text
    assert b_detail.json()["stock_snapshot"]==stock_data["stock_snapshot"]
    assert b_detail.json()["vehicle_plate"]==stock_data["vehicle_plate"]
    assert (await g.client.get(f"/driver/custody/handoffs/{b_id}",headers=field_a)).status_code==404
    b_confirm=await g.client.post(f"/driver/custody/handoffs/{b_id}/decision",headers=field_b,json={
        "request_id":_uuid(),"decision":"CONFIRM",
        "confirmed_stock_snapshot":b_detail.json()["stock_snapshot"],
        "receiver_confirms_physical_count":True,
    })
    assert b_confirm.status_code==200 and b_confirm.json()["state"]=="CONFIRMED",b_confirm.text
    manager_seen=await g.client.get(url+"/current",headers=manager_relogin)
    assert manager_seen.status_code==200 and manager_seen.json()["state"]=="CONFIRMED"
    approved=await g.client.post(f"{url}/{b_id}/approve",headers=manager_relogin,json={"request_id":_uuid()})
    assert approved.status_code==200 and approved.json()["state"]=="COMMITTED",approved.text
    assert approved.json()["stock_movements"]==0
    b_epoch=approved.json()["epoch_id"]
    eligibility=await g.client.get(readiness,headers=manager)
    assert eligibility.status_code==200 and eligibility.json()["context_revision"]==ready["context_revision"]+1
    first_history=await g.client.get(history_url,headers=manager)
    assert first_history.status_code==200 and len(first_history.json()["items"])>=2
    first_accepted=next(e for e in first_history.json()["items"] if e["epoch_id"]==b_epoch)
    assert first_accepted["recipient_label"] and first_accepted["approved_by_label"]
    assert first_accepted["started_at"] and first_accepted["accepted_and_counted"]
    assert any(e["legacy_unconfirmed"] and not e["recipient_label"]
               for e in first_history.json()["items"])

    # New legitimate B -> A handoff, so the first ACCEPTED B is not erased.
    new_a=await g.client.post(url,headers=manager,json=create_body(g.field.driver.id,eligibility.json()))
    assert new_a.status_code==200,new_a.text
    new_a_id=new_a.json()["handoff_id"]
    a_rejoin=await g.client.get(f"/driver/custody/handoffs/{new_a_id}",headers=field_a)
    assert a_rejoin.status_code==200 and a_rejoin.json()["stock_lines"],a_rejoin.text
    a_decision=await g.client.post(f"/driver/custody/handoffs/{new_a_id}/decision",headers=field_a,json={
        "request_id":_uuid(),"decision":"CONFIRM",
        "confirmed_stock_snapshot":a_rejoin.json()["stock_snapshot"],
        "receiver_confirms_physical_count":True,
    })
    assert a_decision.status_code==200 and a_decision.json()["state"]=="CONFIRMED",a_decision.text
    approve_a=await g.client.post(f"{url}/{new_a_id}/approve",headers=manager,json={"request_id":_uuid()})
    assert approve_a.status_code==200 and approve_a.json()["stock_movements"]==0,approve_a.text
    history=await g.client.get(history_url,headers=manager)
    assert history.status_code==200,history.text
    old=next(e for e in history.json()["items"] if e["epoch_id"]==b_epoch)
    newest=next(e for e in history.json()["items"] if e["epoch_id"]==approve_a.json()["epoch_id"])
    assert old["recipient_label"]!=newest["recipient_label"]
    assert old["started_at"] and old["ended_at"]
    assert newest["started_at"] and not newest["ended_at"]
    assert old["approved_by_label"] and newest["approved_by_label"]
    assert old["handoff_evidence_hash"] and newest["handoff_evidence_hash"]
    assert (await g.client.get(history_url,headers=other_manager)).status_code in (403,404)

    # Current holder A is NOT silently changed by B's explicit DECLINE.
    decline_preflight=(await g.client.get(readiness,headers=manager)).json()
    final_b=await g.client.post(url,headers=manager,json=create_body(g.other.driver.id,decline_preflight))
    assert final_b.status_code==200,final_b.text
    final_id=final_b.json()["handoff_id"]
    b_refuse=await g.client.post(f"/driver/custody/handoffs/{final_id}/decision",headers=field_b,json={
        "request_id":_uuid(),"decision":"DECLINE",
        "reason_code":"DIFFERENCE", "reason_text":"Physical count differs",
    })
    assert b_refuse.status_code==200 and b_refuse.json()["state"]=="DECLINED",b_refuse.text
    terminal=await g.client.get(f"/driver/custody/handoffs/{final_id}",headers=field_b)
    assert terminal.status_code==200 and terminal.json()["state"]=="DECLINED"
    assert terminal.json()["stock_lines"]==[]
    assert terminal.json()["reason_code"]=="DIFFERENCE"
    assert (await g.client.post(f"{url}/{final_id}/approve",headers=manager,
             json={"request_id":_uuid()})).status_code==409
    current=await g.client.get(url+"/current",headers=manager)
    assert current.status_code==200 and current.json()["state"]=="DECLINED"
    assert (await _ledger_signature(g))==original_inventory_signature
    async with AsyncSession(g.admin) as db:
        cost_after=int(await db.scalar(select(func.count()).select_from(InventoryCostEvent)
                                     .where(InventoryCostEvent.company_id==g.tenant)) or 0)
        accepted=(await db.scalars(select(VehicleCustodyEpoch).where(
            VehicleCustodyEpoch.company_id==g.tenant,
            VehicleCustodyEpoch.vehicle_id==vehicle_id,
            VehicleCustodyEpoch.state=="ACCEPTED",
        ).order_by(VehicleCustodyEpoch.context_revision))).all()
    assert cost_after==cost_before
    assert len(accepted)==2
    assert accepted[0].custodian_principal_id==g.other.context.principal_id
    assert accepted[1].custodian_principal_id==g.field.context.principal_id
    assert accepted[0].ended_at and accepted[1].ended_at is None

    # No tokens/passwords or raw signed receipts: exactly the real HTTP JSON
    # evidence envelopes consumed by the existing Dashboard/Flutter parsers.
    evidence = {
        "manager_pending": created_b.json(), "manager_reloaded": manager_seen.json(),
        "manager_approved": approved.json(), "manager_history": history.json(),
        "manager_stock": stock_data, "manager_readiness": ready,
        "manager_cancelled": a_cancel.json(), "field_inbox": b_inbox.json(),
        "field_detail": b_detail.json(), "field_confirmed": b_confirm.json(),
        "field_declined": b_refuse.json(), "field_terminal": terminal.json(),
        "field_original_pending": a_inbox.json(),
    }
    destination=os.environ.get("WANASAH_CUSTODY_1016_CAPTURE")
    if destination:
        target=Path(destination)
        assert target.is_absolute() and target.parent.is_dir()
        assert target.name=="custody1016-real-http.json"
        target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2,sort_keys=True),
                          encoding="utf-8")
    print("CUSTODY1016_REAL_MERGED_MANAGER_FIELD_PG16: PASS; 2 signed accepted epochs, "
          "1 canceled confirmed, 1 declined, 0 movement/cost changes",flush=True)
