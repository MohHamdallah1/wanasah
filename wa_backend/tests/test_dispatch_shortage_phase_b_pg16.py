"""#1067 signed HTTP acceptance: run against migrated isolated restricted PostgreSQL16.

WANASAH_SHORTAGE_PHASE_B_PG_GATE=1; no mock auth, DB or HTTP.
The test fixture enforces two tenants and NOBYPASSRLS/FORCE RLS.
"""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from database import engine as http_engine
from models import (
    OperationIdempotency, ShortageRequest, ShortageUrgentAssignment,
    ShortageDeliveryEvent, Visit,
)
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401
from tests.test_dispatch_shortages_group_v1_postgres import _setup, _item, _snapshot
from tests.test_dispatch_shop_finance_edit_v1_postgres import (
    _real_http, _token, _add_shop, _grant_company_dispatch_capability,
)

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_SHORTAGE_PHASE_B_PG_GATE") != "1",
        reason="Requires isolated migrated PostgreSQL16 signed HTTP and FORCE RLS",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]


async def _rls():
    async with http_engine.connect() as db:
        role = (await db.execute(text(
            "SELECT current_database(),current_user,inet_server_port(),"
            "rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ))).one()
        assert tuple(role) == (
            "wanasah_no_lot_contract_test", "wanasah_app", 55439, False, False,
        )
        for table in (
            "shortage_requests", "shortage_urgent_assignments",
            "shortage_delivery_events", "operation_idempotency",
        ):
            flags = (await db.execute(text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE oid=to_regclass(:table)"
            ), {"table": table})).one()
            assert tuple(flags) == (True, True), table
    await http_engine.dispose()


def _command(request_id, shop, zone, driver, product, quantity=10):
    return {
        "version": 2, "request_id": str(request_id), "shop_id": shop,
        "zone_id": zone, "requested_driver_id": driver,
        "lines": [{"product_id": product, "quantity_base": quantity}],
    }


async def test_durable_exact_receipt_retry_conflicts_tenants_pending_only(pg):
    await _rls()
    company, zone, products, driver = await _setup(pg)
    foreign = pg.tenants[1]
    async with _real_http() as client:
        owner = await _token(client, pg, company, company.owner, "NoLotSyntheticFixture123")
        other_owner = await _token(
            client, pg, foreign, foreign.owner, "NoLotSyntheticFixture123",
        )
        shop, _ = await _add_shop(client, owner, zone, balance="0", cap="0")
        intent = _command(uuid4(), shop, zone, driver, products[0], 10)
        initial = await _snapshot(pg, company, shop)
        response = await client.post(
            "/dispatch/shortage-commands", headers=owner, json=intent,
        )
        assert response.status_code == 201, response.text
        receipt = response.json()
        assert receipt["request_id"] == intent["request_id"]
        assert receipt["status"] == "PENDING_REPLENISHMENT"
        assert receipt["lines"][0]["requested_base"] == 10
        assert receipt["lines"][0]["fulfilled_base"] == 0
        assert receipt["lines"][0]["outstanding_base"] == 10
        after = await _snapshot(pg, company, shop)
        assert len(after[0]) == len(initial[0]) + 1
        assert after[1] == initial[1], "Demand cannot manufacture an emergency Visit"
        assert after[4:] == initial[4:], "Demand cannot move stock or cost"
        stored = await client.get(
            f"/dispatch/shortage-commands/{intent['request_id']}", headers=owner,
        )
        assert stored.status_code == 200 and stored.json() == receipt
        # Lost 201: same exact original UUID and intent must replay the
        # immutable persisted receipt with zero extra business mutations.
        replay = await client.post(
            "/dispatch/shortage-commands", headers=owner, json=intent,
        )
        assert replay.status_code == 201 and replay.json() == receipt, replay.text
        assert await _snapshot(pg, company, shop) == after
        collision = {**intent, "lines": [
            {"product_id": products[0], "quantity_base": 11},
        ]}
        changed = await client.post(
            "/dispatch/shortage-commands", headers=owner, json=collision,
        )
        assert changed.status_code == 409, changed.text
        assert await _snapshot(pg, company, shop) == after
        denied = await client.get(
            f"/dispatch/shortage-commands/{intent['request_id']}", headers=other_owner,
        )
        assert denied.status_code in (403, 404), denied.text
        stolen = await client.post(
            "/dispatch/shortage-commands", headers=other_owner, json=intent,
        )
        assert stolen.status_code in (403, 404, 409), stolen.text
        assert await _snapshot(pg, company, shop) == after
        listed = await client.get("/dispatch/shortages", headers=owner)
        assert listed.status_code == 200
        row = next(x for x in listed.json() if int(x["id"]) == receipt["lines"][0]["shortage_id"])
        assert row["fulfilledBase"] == 0
        assert row["outstandingBase"] == 10
        assert row["fulfillmentEvidence"] == "SIGNED_V1"


async def test_duplicate_lines_max80_unknown_custody_and_legacy_no_auto_visit(pg):
    company, zone, products, driver = await _setup(pg)
    async with _real_http() as client:
        owner = await _token(client, pg, company, company.owner, "NoLotSyntheticFixture123")
        shop, _ = await _add_shop(client, owner, zone, balance="0", cap="0")
        duplicates = _command(uuid4(), shop, zone, driver, products[0])
        duplicates["lines"].append(duplicates["lines"][0])
        assert (await client.post(
            "/dispatch/shortage-commands", headers=owner, json=duplicates,
        )).status_code == 422
        beyond = _command(uuid4(), shop, zone, driver, products[0])
        beyond["lines"] = [
            {"product_id": product, "quantity_base": 1}
            for product in range(1, 82)
        ]
        assert (await client.post(
            "/dispatch/shortage-commands", headers=owner, json=beyond,
        )).status_code == 422
        valid = _command(uuid4(), shop, zone, driver, products[0], 10)
        result = await client.post("/dispatch/shortage-commands", headers=owner, json=valid)
        assert result.status_code == 201, result.text
        shortage_id = result.json()["lines"][0]["shortage_id"]
        # Never use vehicle UNKNOWN as numeric zero or make an urgent Visit.
        before = await _snapshot(pg, company, shop)
        denied = await client.post(
            f"/dispatch/shortages/{shortage_id}/promote-urgent",
            headers=owner, json={
                "request_id": str(uuid4()), "driver_id": driver, "quantity_base": 4,
            },
        )
        assert denied.status_code in (403, 409), denied.text
        assert await _snapshot(pg, company, shop) == before
        outside, _ = await _add_shop(client, owner, zone, balance="0", cap="0")
        old = await client.post("/dispatch/shortages", headers=owner, json=[
            _item(outside, zone, driver, products[0], 1),
        ])
        assert old.status_code == 201, old.text
        old_after = await _snapshot(pg, company, outside)
        assert not any(row[2] for row in old_after[1])


async def test_concurrent_same_uuid_and_actor_revocation(pg):
    company, zone, products, driver = await _setup(pg)
    async with _real_http() as client:
        owner = await _token(client, pg, company, company.owner, "NoLotSyntheticFixture123")
        shop, _ = await _add_shop(client, owner, zone, balance="0", cap="0")
        cmd = _command(uuid4(), shop, zone, driver, products[0], 10)
        left, right = await asyncio.wait_for(asyncio.gather(
            client.post("/dispatch/shortage-commands", headers=owner, json=cmd),
            client.post("/dispatch/shortage-commands", headers=owner, json=cmd),
        ), timeout=35)
        assert left.status_code == right.status_code == 201, (left.text, right.text)
        assert left.json() == right.json()
        async with pg.session() as db:
            rows = int(await db.scalar(select(func.count()).select_from(
                ShortageRequest,
            ).where(
                ShortageRequest.company_id == company.company_id,
                ShortageRequest.shop_id == shop,
            )) or 0)
            receipts = int(await db.scalar(select(func.count()).select_from(
                OperationIdempotency,
            ).where(
                OperationIdempotency.company_id == company.company_id,
                OperationIdempotency.operation == "DISPATCH_SHORTAGE_DEMAND_V2",
                OperationIdempotency.request_id == cmd["request_id"],
            )) or 0)
        assert rows == 1 and receipts == 1
        # Non-owner with read-only grant has no ability to create or replay.
        await _grant_company_dispatch_capability(
            pg, company, company.ordinary, "shortage.read",
        )
        ordinary = await _token(client, pg, company, company.ordinary, "SyntheticFixture123")
        assert (await client.post(
            "/dispatch/shortage-commands", headers=ordinary, json=cmd,
        )).status_code == 403
        # Receipt is actor-bound, even if a reviewer has shortage.read.
        other_read = await client.get(
            f"/dispatch/shortage-commands/{cmd['request_id']}", headers=ordinary,
        )
        assert other_read.status_code in (403, 404), other_read.text
