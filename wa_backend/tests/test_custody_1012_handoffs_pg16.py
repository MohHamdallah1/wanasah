"""CUSTODY-P0 one genuine restricted PostgreSQL16 + two authenticated principal journey."""
from __future__ import annotations
import os
from datetime import timedelta
from uuid import uuid4
import asyncio

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from database import engine as restricted_engine
from domains.dispatch.route_execution.custody.handoffs_model import VehicleCustodyHandoff
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.identity.models import CompanyPrincipal
from domains.authorization.field_models import FieldRepresentativeRole
from models import InventoryCostEvent, InventoryMovement, SystemAuditLog, Vehicle
from tests.test_dispatch_m03_period_postgres import gate, _headers
from tests.test_dispatch_c01_c02_custody_postgres import (
    _setup_cars, _login_owner, _ledger_signature,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_CUSTODY_1012_PG_GATE") != "1",
        reason="Only isolated m03_941_custody_1012 PG16 at port 56612",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


async def test_durable_custody_two_bearers_revoke_reassign_expire_and_keep_history(gate):
    g = gate
    assert os.getenv("DATABASE_URL", "").endswith("/m03_941_custody_1012")
    assert "127.0.0.1:56612" in os.environ["DATABASE_URL"]
    a_car, _other_car, empty_car = await _setup_cars(g)
    vehicle_id, location_id, _, _ = a_car
    manager = await _login_owner(g)
    outsider = await _login_owner(g, g.foreign)
    field_a = _headers(g.token)
    field_b = _headers(g.other_token)
    outside_field = _headers(g.foreign_token)
    url = f"/vehicles/{vehicle_id}/custody/handoffs"
    readiness_url = f"/vehicles/{vehicle_id}/custody/readiness"

    async with restricted_engine.connect() as db:
        flags = (await db.execute(text(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ))).one()
        assert tuple(flags) == (False, False)
        rls = (await db.execute(text(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
            "WHERE oid=to_regclass('vehicle_custody_handoffs')"
        ))).one()
        assert tuple(rls) == (True, True)

    original_ledger = await _ledger_signature(g)
    async with AsyncSession(g.admin) as db:
        cost_before = int(await db.scalar(select(__import__("sqlalchemy").func.count())
                      .select_from(InventoryCostEvent).where(InventoryCostEvent.company_id == g.tenant)) or 0)
    original = (await g.client.get(readiness_url, headers=manager)).json()
    assert original["state"] == "NEEDS_REVIEW" and original["stocked"]
    assert (await g.client.get(url+"/current")).status_code == 401
    assert (await g.client.get(url+"/current", headers=outsider)).status_code in (403, 404)

    # An OLD HMAC issued before the new durable request MUST be fenced out.
    old_offer = await g.client.post(
        f"/vehicles/{vehicle_id}/custody/offer", headers=manager, json={
            "target_driver_id": g.field.driver.id,
            "expected_context_revision": original["context_revision"],
            "expected_stock_snapshot": original["stock_snapshot"],
        },
    )
    assert old_offer.status_code == 200, old_offer.text
    old_receipt = await g.client.post(
        f"/driver/vehicles/{vehicle_id}/custody/confirm",
        headers=field_a, json={
            "offer_token": old_offer.json()["offer_token"],
            "confirmed_stock_snapshot": original["stock_snapshot"],
            "receiver_confirms_physical_count": True,
        },
    )
    assert old_receipt.status_code == 200, old_receipt.text

    create_a = {
        "request_id": str(uuid4()), "target_driver_id": g.field.driver.id,
        "expected_context_revision": original["context_revision"],
        "expected_stock_snapshot": original["stock_snapshot"],
    }
    first = await g.client.post(url, headers=manager, json=create_a)
    assert first.status_code == 200, first.text
    a = first.json()
    assert a["state"] == "PENDING" and a["target_driver_id"] == g.field.driver.id
    assert a["recipient_label"] and a["vehicle_id"] == vehicle_id
    manager_relogin = await _login_owner(g)
    persisted_after_relogin = await g.client.get(
        url+"/current", headers=manager_relogin,
    )
    assert persisted_after_relogin.status_code == 200
    assert persisted_after_relogin.json()["handoff_id"] == a["handoff_id"]
    assert persisted_after_relogin.json()["state"] == "PENDING"
    assert "offer_token" not in first.text and "receiver_proof" not in first.text
    a_id = a["handoff_id"]
    assert type(a_id) is int and a_id > 0  # canonical positive BIGSERIAL, never UUID
    old_accept = await g.client.post(
        f"/vehicles/{vehicle_id}/custody/accept", headers=manager,
        json={"request_id":str(uuid4()),"receiver_proof":old_receipt.json()["receiver_proof"]},
    )
    assert old_accept.status_code == 409, old_accept.text
    assert (await g.client.post(url, headers=manager, json=create_a)).json()["handoff_id"] == a_id
    changed = await g.client.post(url, headers=manager, json={
        **create_a, "target_driver_id": g.other.driver.id,
    })
    assert changed.status_code == 409, changed.text
    competing = await g.client.post(url, headers=manager, json={
        **create_a, "request_id": str(uuid4()), "target_driver_id": g.other.driver.id,
    })
    assert competing.status_code == 409, competing.text
    old_preview = await g.client.post(
        f"/driver/vehicles/{vehicle_id}/custody/offer-preview",
        headers=field_a, json={"offer_token": old_offer.json()["offer_token"]},
    )
    assert old_preview.status_code == 409, old_preview.text
    old_confirm = await g.client.post(
        f"/driver/vehicles/{vehicle_id}/custody/confirm",
        headers=field_a, json={
            "offer_token": old_offer.json()["offer_token"],
            "confirmed_stock_snapshot": original["stock_snapshot"],
            "receiver_confirms_physical_count": True,
        },
    )
    assert old_confirm.status_code == 409, old_confirm.text
    assert (await g.client.get(f"/driver/custody/handoffs/{a_id}",headers=field_b)).status_code == 404
    assert (await g.client.get(f"/driver/custody/handoffs/{a_id}",headers=outside_field)).status_code == 404
    # Two distinct company vehicles, one authenticated FIELD recipient. The
    # pending endpoint MUST provide both genuine plates in one bounded JOIN;
    # its SQL query count must stay constant with 2 rows (no recipient N+1).
    empty_car_id = empty_car[0]
    empty_ready = (await g.client.get(
        f"/vehicles/{empty_car_id}/custody/readiness", headers=manager,
    )).json()
    second_payload = {
        "request_id": str(uuid4()), "target_driver_id": g.field.driver.id,
        "expected_context_revision": empty_ready["context_revision"],
        "expected_stock_snapshot": empty_ready["stock_snapshot"],
    }
    second_pending = await g.client.post(
        f"/vehicles/{empty_car_id}/custody/handoffs",
        headers=manager, json=second_payload,
    )
    assert second_pending.status_code == 200, second_pending.text
    second_id = second_pending.json()["handoff_id"]
    assert type(second_id) is int and second_id > a_id
    async with AsyncSession(g.admin) as db:
        plates = dict((await db.execute(select(
            Vehicle.id, Vehicle.plate_number,
        ).where(
            Vehicle.company_id == g.tenant,
            Vehicle.id.in_((vehicle_id, empty_car_id)),
        ))).all())
    seen_reads = []
    def count_handoff_reads(conn, cursor, statement, parameters, context, executemany):
        if "SELECT" in statement and "vehicle_custody_handoffs" in statement:
            seen_reads.append(statement)
    event.listen(restricted_engine.sync_engine, "before_cursor_execute", count_handoff_reads)
    try:
        inbox_a = await g.client.get("/driver/custody/handoffs/pending", headers=field_a)
    finally:
        event.remove(restricted_engine.sync_engine, "before_cursor_execute", count_handoff_reads)
    inbox_b = await g.client.get("/driver/custody/handoffs/pending", headers=field_b)
    assert inbox_a.status_code == inbox_b.status_code == 200
    assert len(seen_reads) == 1, f"FIELD inbox must not N+1 SQL: {len(seen_reads)}"
    rows = inbox_a.json()["items"]
    assert [item["handoff_id"] for item in rows] == [second_id, a_id]
    assert all(type(item["handoff_id"]) is int and item["handoff_id"] > 0 for item in rows)
    assert {item["vehicle_id"]: item["vehicle_plate"] for item in rows} == plates
    assert all(item["recipient_label"] and item["vehicle_plate"] for item in rows)
    assert inbox_b.json()["items"] == []
    secondary_cancel = await g.client.post(
        f"/vehicles/{empty_car_id}/custody/handoffs/{second_id}/cancel",
        headers=manager, json={"request_id": str(uuid4())},
    )
    assert secondary_cancel.status_code == 200 and secondary_cancel.json()["state"] == "CANCELLED", secondary_cancel.text
    detail = await g.client.get(f"/driver/custody/handoffs/{a_id}", headers=field_a)
    assert detail.status_code == 200 and detail.json()["stock_lines"], detail.text
    assert detail.json()["stock_snapshot"] == original["stock_snapshot"]
    premature = await g.client.post(
        f"{url}/{a_id}/approve", headers=manager,
        json={"request_id":str(uuid4())},
    )
    assert premature.status_code == 409, premature.text
    refused_count = await g.client.post(
        f"/driver/custody/handoffs/{a_id}/decision",headers=field_a,
        json={"request_id":str(uuid4()),"decision":"CONFIRM",
              "receiver_confirms_physical_count":True,
              "confirmed_stock_snapshot":"0"*64},
    )
    assert refused_count.status_code == 409, refused_count.text
    decision_a = {
        "request_id": str(uuid4()), "decision":"CONFIRM",
        "confirmed_stock_snapshot":original["stock_snapshot"],
        "receiver_confirms_physical_count":True,
    }
    confirmed = await g.client.post(
        f"/driver/custody/handoffs/{a_id}/decision",headers=field_a,json=decision_a,
    )
    assert confirmed.status_code == 200 and confirmed.json()["state"] == "CONFIRMED", confirmed.text
    replay = await g.client.post(
        f"/driver/custody/handoffs/{a_id}/decision",headers=field_a,json=decision_a,
    )
    assert replay.status_code == 200 and replay.json()["state"] == "CONFIRMED", replay.text
    altered_replay = await g.client.post(
        f"/driver/custody/handoffs/{a_id}/decision",headers=field_a,
        json={**decision_a,"decision":"DECLINE","reason_code":"DIFFERENCE"},
    )
    assert altered_replay.status_code == 409, altered_replay.text
    approve_a = {"request_id":str(uuid4())}
    foreign_approve = await g.client.post(f"{url}/{a_id}/approve",headers=outsider,json=approve_a)
    assert foreign_approve.status_code in (403,404), foreign_approve.text
    accepted_a = await g.client.post(f"{url}/{a_id}/approve",headers=manager,json=approve_a)
    assert accepted_a.status_code == 200 and accepted_a.json()["state"] == "COMMITTED", accepted_a.text
    assert accepted_a.json()["stock_movements"] == 0
    a_epoch = accepted_a.json()["epoch_id"]
    same = await g.client.post(f"{url}/{a_id}/approve",headers=manager,json=approve_a)
    assert same.status_code == 200 and same.json()["epoch_id"] == a_epoch, same.text
    assert same.json()["context_revision"] == accepted_a.json()["context_revision"]
    assert same.json()["replayed"] is True

    # A's ACCEPTED epoch is never replaced with UNKNOWN during B's reassign.
    next_readiness = (await g.client.get(readiness_url,headers=manager)).json()
    assert next_readiness["context_revision"] == original["context_revision"]+1
    stale_create = await g.client.post(url,headers=manager,json={
        "request_id":str(uuid4()),"target_driver_id":g.other.driver.id,
        "expected_context_revision":original["context_revision"],
        "expected_stock_snapshot":original["stock_snapshot"],
    })
    assert stale_create.status_code == 409, stale_create.text
    create_b = {
        "request_id":str(uuid4()),"target_driver_id":g.other.driver.id,
        "expected_context_revision":next_readiness["context_revision"],
        "expected_stock_snapshot":next_readiness["stock_snapshot"],
    }
    b1 = await g.client.post(url,headers=manager,json=create_b)
    assert b1.status_code == 200, b1.text
    b1_id = b1.json()["handoff_id"]
    declined = await g.client.post(f"/driver/custody/handoffs/{b1_id}/decision",
        headers=field_b,json={"request_id":str(uuid4()),"decision":"DECLINE",
                              "reason_code":"NOT_MY_GOODS","reason_text":"Different vehicle"})
    assert declined.status_code == 200 and declined.json()["state"] == "DECLINED", declined.text
    assert (await g.client.post(f"{url}/{b1_id}/approve",headers=manager,
            json={"request_id":str(uuid4())})).status_code == 409
    b2 = await g.client.post(url,headers=manager,json={**create_b,"request_id":str(uuid4())})
    assert b2.status_code == 200, b2.text
    b2_id = b2.json()["handoff_id"]
    b_confirm = {"request_id":str(uuid4()),"decision":"CONFIRM",
                 "confirmed_stock_snapshot":next_readiness["stock_snapshot"],
                 "receiver_confirms_physical_count":True}
    assert (await g.client.post(f"/driver/custody/handoffs/{b2_id}/decision",
            headers=field_b,json=b_confirm)).json()["state"] == "CONFIRMED"
    cancelled = await g.client.post(f"{url}/{b2_id}/cancel",headers=manager,
        json={"request_id":str(uuid4())})
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "CANCELLED", cancelled.text
    assert cancelled.json()["receiver_confirmed_at"] is not None
    assert (await g.client.post(f"{url}/{b2_id}/approve",headers=manager,
            json={"request_id":str(uuid4())})).status_code == 409
    assert (await g.client.post(f"/driver/custody/handoffs/{b2_id}/decision",
            headers=field_b,json={**b_confirm,"request_id":str(uuid4())})).status_code == 409
    b3 = await g.client.post(url,headers=manager,json={**create_b,"request_id":str(uuid4())})
    assert b3.status_code == 200, b3.text
    b3_id = b3.json()["handoff_id"]
    assert b3_id > b2_id > b1_id > a_id
    assert (await g.client.post(f"/driver/custody/handoffs/{b3_id}/decision",
            headers=field_b,json={**b_confirm,"request_id":str(uuid4())})).json()["state"] == "CONFIRMED"
    # Signed FIELD identity revoked AFTER count but BEFORE the manager's click
    # must not allow replaying its still-valid cryptographic receipt.
    principal_id_b = g.other.context.principal_id
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        principal = await db.scalar(select(CompanyPrincipal).where(
            CompanyPrincipal.company_id==g.tenant, CompanyPrincipal.id==principal_id_b))
        principal.is_active = False
        await db.commit()
    approve_b_req = {"request_id":str(uuid4())}
    revoked = await g.client.post(f"{url}/{b3_id}/approve",headers=manager,json=approve_b_req)
    assert revoked.status_code == 409, revoked.text
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        principal = await db.scalar(select(CompanyPrincipal).where(
            CompanyPrincipal.company_id==g.tenant, CompanyPrincipal.id==principal_id_b))
        principal.is_active = True
        await db.commit()
    # A previously signed count does NOT replace current FIELD grants.
    # Remove and restore only synthetic test company role assignments.
    saved_roles = []
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        assignments = (await db.scalars(select(FieldRepresentativeRole).where(
            FieldRepresentativeRole.company_id == g.tenant,
            FieldRepresentativeRole.field_representative_id == g.other.context.representative_id,
        ))).all()
        assert assignments
        for assignment in assignments:
            saved_roles.append((assignment.company_id,assignment.field_representative_id,assignment.role_id))
            await db.delete(assignment)
        await db.commit()
    revoked_role = await g.client.post(f"{url}/{b3_id}/approve",headers=manager,json=approve_b_req)
    assert revoked_role.status_code == 409, revoked_role.text
    async with AsyncSession(g.admin, expire_on_commit=False) as db:
        for company_id, representative_id, role_id in saved_roles:
            db.add(FieldRepresentativeRole(
                company_id=company_id, field_representative_id=representative_id,
                role_id=role_id,
            ))
        await db.commit()
    commit_b = await g.client.post(f"{url}/{b3_id}/approve",headers=manager,
        json=approve_b_req)
    assert commit_b.status_code == 200 and commit_b.json()["state"] == "COMMITTED", commit_b.text
    history = await g.client.get(f"/vehicles/{vehicle_id}/custody/history",
                                 headers=manager,params={"limit":10})
    assert history.status_code == 200, history.text
    items = history.json()["items"]
    signed = [item for item in items if item["state"]=="ACCEPTED"]
    assert len(signed)==2
    assert signed[0]["epoch_id"] == commit_b.json()["epoch_id"]
    assert signed[1]["epoch_id"] == a_epoch
    assert signed[0]["recipient_label"] != signed[1]["recipient_label"]
    assert signed[1]["ended_at"] and signed[1]["started_at"]
    assert signed[1]["accepted_and_counted"] and signed[0]["accepted_and_counted"]
    assert signed[0]["approved_by_label"] and signed[1]["approved_by_label"]
    unknown = next(row for row in items if row["legacy_unconfirmed"])
    assert unknown["recipient_label"] is None and not unknown["accepted_and_counted"]
    assert (await g.client.get(f"/vehicles/{vehicle_id}/custody/history",
          headers=outsider)).status_code in (403,404)
    assert (await g.client.get(f"/vehicles/{vehicle_id}/custody/history",
          headers=manager,params={"limit":101})).status_code == 422

    # Two independent concurrent send requests for one vehicle: one must
    # win the vehicle lock; the other never creates a second live offer.
    stable = (await g.client.get(readiness_url,headers=manager)).json()
    competing_payload = {
        "target_driver_id":g.field.driver.id,
        "expected_context_revision":stable["context_revision"],
        "expected_stock_snapshot":stable["stock_snapshot"],
    }
    contenders = await asyncio.gather(*(
        g.client.post(url,headers=manager,json={
            **competing_payload,"request_id":str(uuid4()),
        }) for _ in range(2)
    ))
    assert sorted(x.status_code for x in contenders)==[200,409], [x.text for x in contenders]
    winning = next(x.json() for x in contenders if x.status_code == 200)
    assert (await g.client.post(f"{url}/{winning['handoff_id']}/cancel",
        headers=manager,json={"request_id":str(uuid4())})).status_code == 200

    # Synthetic expiry uses an admin-only fixture mutation of REQUEST metadata,
    # NEVER inventory, financial state, real customer data or old custody epochs.
    fresh_car = empty_car[0]
    fresh_ready = (await g.client.get(
        f"/vehicles/{fresh_car}/custody/readiness",headers=manager)).json()
    expire_body = {
        "request_id":str(uuid4()),"target_driver_id":g.field.driver.id,
        "expected_context_revision":fresh_ready["context_revision"],
        "expected_stock_snapshot":fresh_ready["stock_snapshot"],
    }
    expired_req = await g.client.post(
        f"/vehicles/{fresh_car}/custody/handoffs",headers=manager,json=expire_body)
    assert expired_req.status_code == 200, expired_req.text
    expired_id = expired_req.json()["handoff_id"]
    async with AsyncSession(g.admin,expire_on_commit=False) as db:
        row = await db.scalar(select(VehicleCustodyHandoff).where(
            VehicleCustodyHandoff.company_id == g.tenant,VehicleCustodyHandoff.id == expired_id))
        row.expires_at = row.expires_at - timedelta(hours=1)
        await db.commit()
    expired_decision = await g.client.post(
        f"/driver/custody/handoffs/{expired_id}/decision",headers=field_a,
        json={"request_id":str(uuid4()),"decision":"CONFIRM",
              "confirmed_stock_snapshot":fresh_ready["stock_snapshot"],
              "receiver_confirms_physical_count":True})
    assert expired_decision.status_code == 409, expired_decision.text
    reissue = await g.client.post(
        f"/vehicles/{fresh_car}/custody/handoffs",headers=manager,
        json={**expire_body,"request_id":str(uuid4())})
    assert reissue.status_code == 200 and reissue.json()["handoff_id"]>expired_id, reissue.text

    # After explicit cancellation the LEGACY UI can still finish a fresh
    # two-principal signed handoff. Its newly minted HMAC carries the current
    # server fence; the pre-request old receipt was already rejected above.
    latest_id = reissue.json()["handoff_id"]
    cancelled_latest = await g.client.post(
        f"/vehicles/{fresh_car}/custody/handoffs/{latest_id}/cancel",
        headers=manager,json={"request_id":str(uuid4())})
    assert cancelled_latest.status_code == 200, cancelled_latest.text
    signed_offer = await g.client.post(
        f"/vehicles/{fresh_car}/custody/offer",headers=manager,json={
            "target_driver_id":g.field.driver.id,
            "expected_context_revision":fresh_ready["context_revision"],
            "expected_stock_snapshot":fresh_ready["stock_snapshot"],
        })
    assert signed_offer.status_code == 200, signed_offer.text
    signed_receipt = await g.client.post(
        f"/driver/vehicles/{fresh_car}/custody/confirm",headers=field_a,json={
            "offer_token":signed_offer.json()["offer_token"],
            "confirmed_stock_snapshot":fresh_ready["stock_snapshot"],
            "receiver_confirms_physical_count":True,
        })
    assert signed_receipt.status_code == 200, signed_receipt.text
    legacy_accepted = await g.client.post(
        f"/vehicles/{fresh_car}/custody/accept",headers=manager,json={
            "request_id":str(uuid4()),"receiver_proof":signed_receipt.json()["receiver_proof"],
        })
    assert legacy_accepted.status_code == 201, legacy_accepted.text
    assert legacy_accepted.json()["stock_movements"] == 0

    old = await g.client.get(f"/vehicles/{fresh_car}/custody/handoffs/{expired_id}/approve",
                             headers=manager)
    assert old.status_code in (404,405)
    assert await _ledger_signature(g) == original_ledger
    async with AsyncSession(g.admin) as db:
        cost_after = int(await db.scalar(select(__import__("sqlalchemy").func.count())
                .select_from(InventoryCostEvent).where(InventoryCostEvent.company_id==g.tenant)) or 0)
        audit = (await db.scalars(select(SystemAuditLog.action_type).where(
            SystemAuditLog.company_id==g.tenant,
            SystemAuditLog.action_type.like("CUSTODY_HANDOFF_%")))).all()
        epochs = (await db.scalars(select(VehicleCustodyEpoch).where(
            VehicleCustodyEpoch.company_id==g.tenant,
            VehicleCustodyEpoch.vehicle_id==vehicle_id).order_by(VehicleCustodyEpoch.context_revision))).all()
    assert cost_after == cost_before
    assert {"CUSTODY_HANDOFF_REQUESTED","CUSTODY_HANDOFF_CONFIRMED",
            "CUSTODY_HANDOFF_DECLINED","CUSTODY_HANDOFF_CANCELLED",
            "CUSTODY_HANDOFF_COMMITTED","CUSTODY_HANDOFF_EXPIRED"} <= set(audit)
    assert [ep.state for ep in epochs] == ["NEEDS_REVIEW","ACCEPTED","ACCEPTED"]
    assert [ep.context_revision for ep in epochs] == [1,2,3]
    assert epochs[1].custodian_principal_id != epochs[2].custodian_principal_id
    assert epochs[1].ended_at is not None and epochs[2].ended_at is None
    print("CUSTODY1012_REAL_PG16_TWO_BEARER_RLS_HISTORY_ZERO_MOVEMENTS=PASS",flush=True)
