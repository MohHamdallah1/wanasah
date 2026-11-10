"""#858 F06: real restricted PG16 + genuine Backoffice Bearer Shop-create proof.

All writes run through actual FastAPI, canonical authorization, and FORCE RLS.
Failure injection affects only a disposable PG16 audit trigger, never auth.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
import json
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from main import app
from models import (
    InventoryCostEvent, InventoryMovement, OperationIdempotency,
    Shop, SystemAuditLog, UserRole,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_shop_finance_edit_v1_postgres import (
    _grant_company_dispatch_capability, _owner, _real_http, _token, _zone,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_SHOP_CREATE_F06_PG_GATE") != "1",
        reason="Opt-in disposable PG16 real Shop create F06 gate",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


def _request(zone, *, request_id=None, name=None, phone=None, money="100.125"):
    body = {
        "name": name or "F06 " + uuid4().hex[:12],
        "zoneId": zone,
        "phone": phone or "F06-" + uuid4().hex[:12],
        "owner": "F06 owner",
        "initialDebt": money,
        "maxDebtLimit": "250.500",
    }
    if request_id is not None:
        body["request_id"] = str(request_id)
    return body


async def _state(gate, tenant, *, name, request_id, party=0):
    async with gate.session(party) as db:
        shops = (await db.execute(select(Shop).where(
            Shop.company_id == tenant.company_id, Shop.name == name,
        ))).scalars().all()
        operations = (await db.execute(select(OperationIdempotency).where(
            OperationIdempotency.company_id == tenant.company_id,
            OperationIdempotency.operation == "DISPATCH_SHOP_CREATE_V1",
            OperationIdempotency.request_id == str(request_id),
        ))).scalars().all()
        audit = (await db.execute(select(SystemAuditLog).where(
            SystemAuditLog.company_id == tenant.company_id,
            SystemAuditLog.action_type == "SHOP_CREATED",
            SystemAuditLog.target_id.in_([f"Shop_{shop.id}" for shop in shops]),
        ))).scalars().all()
        movements = int(await db.scalar(select(func.count()).select_from(
            InventoryMovement).where(InventoryMovement.company_id == tenant.company_id)
        ) or 0)
        cost_events = int(await db.scalar(select(func.count()).select_from(
            InventoryCostEvent).where(InventoryCostEvent.company_id == tenant.company_id)
        ) or 0)
        return shops, operations, audit, (movements, cost_events)


class DropCommittedShopReply(httpx.AsyncBaseTransport):
    """Discard actual POST 201 *after* the app has committed, like lost network reply."""

    def __init__(self):
        self.inner = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        self.dropped = False

    async def handle_async_request(self, request):
        response = await self.inner.handle_async_request(request)
        if request.method == "POST" and request.url.path == "/dispatch/shops" and response.status_code == 201:
            self.dropped = True
            await response.aclose()
            raise httpx.ReadError("F06 injected lost 201 after commit", request=request)
        return response

    async def aclose(self):
        await self.inner.aclose()


async def test_f06_lost_201_durable_lookup_and_identical_retry_money_once(pg):
    tenant = pg.tenants[0]
    zone = await _zone(pg, tenant)
    rid = uuid4()
    body = _request(zone, request_id=rid)
    transport = DropCommittedShopReply()
    async with _real_http() as client:
        token = await _owner(client, pg, tenant)
        baseline = await _state(pg, tenant, name=body["name"], request_id=rid)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://dispatch-f06-lost-reply.test",
            timeout=30,
        ) as broken_client:
            with pytest.raises(httpx.ReadError, match="lost 201"):
                await broken_client.post("/dispatch/shops", headers=token, json=body)
        assert transport.dropped
        lookup = await client.get(
            f"/dispatch/shops/create-operations/{rid}", headers=token,
        )
        assert lookup.status_code == 200, lookup.text
        assert lookup.json()["state"] == "COMMITTED"
        receipt = lookup.json()["response"]
        assert receipt["request_id"] == str(rid)
        assert receipt["opening_evidence"]["opening_receivable"] == "100.125"
        assert receipt["opening_evidence"]["opening_credit_cap"] == "250.500"
        shop_id = int(receipt["shop_id"])
        replay = await client.post("/dispatch/shops", headers=token, json=body)
        assert replay.status_code == 201 and replay.json() == receipt, replay.text
        shops, operations, audit, (movements, cost_events) = await _state(
            pg, tenant, name=body["name"], request_id=rid,
        )
        assert len(shops) == len(operations) == len(audit) == 1
        assert int(shops[0].id) == shop_id
        assert (shops[0].current_balance, shops[0].max_debt_limit) == (
            Decimal("100.125"), Decimal("250.500"),
        )
        assert operations[0].state == "COMMITTED"
        assert operations[0].response_json == receipt
        assert str(audit[0].id) == receipt["opening_evidence"]["audit_id"]
        assert json.loads(audit[0].new_value)["opening_receivable"] == "100.125"
        assert (movements, cost_events) == baseline[-1]
        print("F06_LOST_201_REPLAY_AND_OPENING_MONEY_ONCE PASS")


async def test_f06_two_parallel_same_key_one_shop_no_duplicate_money(pg):
    tenant = pg.tenants[0]
    zone = await _zone(pg, tenant)
    rid = uuid4()
    body = _request(zone, request_id=rid)
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        responses = await asyncio.gather(*(
            client.post("/dispatch/shops", headers=owner, json=body)
            for _ in range(2)
        ))
        assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
        assert responses[0].json() == responses[1].json()
        shops, operations, audit, baseline = await _state(
            pg, tenant, name=body["name"], request_id=rid,
        )
        assert len(shops) == len(operations) == len(audit) == 1
        assert operations[0].response_json["shop_id"] == str(shops[0].id)
        print("F06_CONCURRENT_SAME_UUID_ONE_SHOP_ONE_AUDIT PASS")


async def test_f06_changed_payload_actor_tenant_revoke_and_new_intent(pg):
    home, foreign = pg.tenants
    zone_a = await _zone(pg, home)
    zone_b = await _zone(pg, foreign, party=1)
    rid = uuid4()
    body = _request(zone_a, request_id=rid, phone="F06-" + uuid4().hex[:12])
    second_key = uuid4()
    name_same = "F06 legitimate same name " + uuid4().hex[:8]
    # A distinct request with the same commercial name is a legitimate intent
    # when the phone/address do not collide. No name-based replay inference.
    body["name"] = name_same
    await _grant_company_dispatch_capability(pg, home, home.ordinary, "dispatch.read")
    role_id = await _grant_company_dispatch_capability(
        pg, home, home.ordinary, "dispatch.execute",
    )
    async with _real_http() as client:
        owner = await _owner(client, pg, home)
        other_actor = await _token(
            client, pg, home, home.ordinary, "SyntheticFixture123",
        )
        other_owner = await _owner(client, pg, foreign)
        first = await client.post("/dispatch/shops", headers=owner, json=body)
        assert first.status_code == 201, first.text
        shop_id = first.json()["shop_id"]
        wrong = await client.post("/dispatch/shops", headers=owner, json={
            **body, "maxDebtLimit": "999.999",
        })
        assert wrong.status_code == 409, wrong.text
        assert "PAYLOAD_CONFLICT" in wrong.text
        actor_reuse = await client.post("/dispatch/shops", headers=other_actor, json=body)
        assert actor_reuse.status_code == 409, actor_reuse.text
        assert "ACTOR_CONFLICT" in actor_reuse.text
        actor_lookup = await client.get(
            f"/dispatch/shops/create-operations/{rid}", headers=other_actor,
        )
        assert actor_lookup.status_code == 200
        assert actor_lookup.json()["state"] == "UNKNOWN"
        alternate = await client.post("/dispatch/shops", headers=owner, json={
            **body, "request_id": str(second_key), "phone": "F06-" + uuid4().hex[:12],
        })
        assert alternate.status_code == 201, alternate.text
        assert alternate.json()["shop_id"] != shop_id

        # Same request key in another tenant is a separate namespace;
        # another company's receipt is never returned to home.
        foreign_rid = uuid4()
        foreign_body = _request(zone_b, request_id=foreign_rid)
        foreign_post = await client.post(
            "/dispatch/shops", headers=other_owner, json=foreign_body,
        )
        assert foreign_post.status_code == 201, foreign_post.text
        cross = await client.get(
            f"/dispatch/shops/create-operations/{foreign_rid}", headers=owner,
        )
        assert cross.status_code == 200 and cross.json()["state"] == "UNKNOWN"
        invalid = await client.get(
            f"/dispatch/shops/create-operations/{rid}",
        )
        assert invalid.status_code == 401, invalid.text
        # Persisted revocation defeats a still-valid previous JWT.
        async with pg.session() as db:
            await db.execute(delete(UserRole).where(
                UserRole.company_id == home.company_id,
                UserRole.driver_id == home.ordinary.driver_id,
                UserRole.role_id == role_id,
            ))
            await db.commit()
        revoked = await client.get(
            f"/dispatch/shops/create-operations/{rid}", headers=other_actor,
        )
        assert revoked.status_code == 403, revoked.text
        revoked_post = await client.post(
            "/dispatch/shops", headers=other_actor,
            json={**body, "request_id": str(uuid4())},
        )
        assert revoked_post.status_code == 403, revoked_post.text

        # Authorized tenant scope survives malicious client-provided IDs.
        forbidden = await client.post(
            "/dispatch/shops", headers=owner,
            json={**body, "request_id": str(uuid4()), "zoneId": zone_b},
        )
        assert forbidden.status_code in (400, 404), forbidden.text
        shops, ops, audit, _ = await _state(
            pg, home, name=name_same, request_id=rid,
        )
        assert len(shops) == 2 and len(ops) == 1 and len(audit) == 2
        print("F06_PAYLOAD_ACTOR_TENANT_REVOCATION_NEW_INTENT PASS")


async def test_f06_late_sql_failure_rolls_back_shop_receipt_and_audit_then_retries(pg):
    tenant = pg.tenants[0]
    zone = await _zone(pg, tenant)
    rid = uuid4()
    body = _request(zone, request_id=rid)
    # The actual database aborts AFTER Shop flush, when inserting the audit.
    # Only disposable test schema gets this fault; no auth overrides or fake DB.
    function = "f06_test_abort_shop_audit"
    trigger = "f06_test_abort_shop_audit_row"
    sql = f"""
        CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.action_type = 'SHOP_CREATED'
               AND NEW.new_value::jsonb->>'request_id' = '{rid}' THEN
                RAISE EXCEPTION 'F06_REAL_AUDIT_ROLLBACK' USING ERRCODE = 'P0001';
            END IF;
            RETURN NEW;
        END
        $$;
    """
    async with AsyncSession(pg.admin_engine) as admin:
        await admin.execute(text(sql))
        await admin.execute(text(
            f"CREATE TRIGGER {trigger} BEFORE INSERT ON system_audit_logs "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        ))
        await admin.commit()
    try:
        async with _real_http() as client:
            owner = await _owner(client, pg, tenant)
            failed = await client.post("/dispatch/shops", headers=owner, json=body)
            assert failed.status_code == 500, failed.text
            shops, ops, audit, baseline = await _state(
                pg, tenant, name=body["name"], request_id=rid,
            )
            assert len(shops) == len(ops) == len(audit) == 0
    finally:
        async with AsyncSession(pg.admin_engine) as admin:
            await admin.execute(text(f"DROP TRIGGER {trigger} ON system_audit_logs"))
            await admin.execute(text(f"DROP FUNCTION {function}()"))
            await admin.commit()

    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        unknown = await client.get(
            f"/dispatch/shops/create-operations/{rid}", headers=owner,
        )
        assert unknown.status_code == 200 and unknown.json()["state"] == "UNKNOWN"
        retried = await client.post("/dispatch/shops", headers=owner, json=body)
        assert retried.status_code == 201, retried.text
        assert retried.json()["shop_id"]
        shops, ops, audit, after = await _state(
            pg, tenant, name=body["name"], request_id=rid,
        )
        assert len(shops) == len(ops) == len(audit) == 1
        assert baseline == after
        print("F06_POSTGRES_LATE_AUDIT_EXCEPTION_FULL_ROLLBACK_AND_RETRY PASS")


async def test_f06_legacy_has_no_receipt_and_unknown_not_a_name_match(pg):
    tenant = pg.tenants[0]
    zone = await _zone(pg, tenant)
    body = _request(zone)
    unknown_key = uuid4()
    async with _real_http() as client:
        owner = await _owner(client, pg, tenant)
        legacy = await client.post("/dispatch/shops", headers=owner, json=body)
        assert legacy.status_code == 201 and "request_id" not in legacy.json()
        unknown = await client.get(
            f"/dispatch/shops/create-operations/{unknown_key}", headers=owner,
        )
        assert unknown.status_code == 200 and unknown.json() == {
            "request_id": str(unknown_key), "state": "UNKNOWN",
        }
        same = await client.post(
            "/dispatch/shops", headers=owner,
            json={**body, "request_id": str(unknown_key)},
        )
        assert same.status_code == 409 and same.json()["is_duplicate"] is True
        still_unknown = await client.get(
            f"/dispatch/shops/create-operations/{unknown_key}", headers=owner,
        )
        assert still_unknown.json()["state"] == "UNKNOWN"
        print("F06_LEGACY_NO_FALSE_RECEIPT_AND_DUPLICATE_WARNING PASS")
