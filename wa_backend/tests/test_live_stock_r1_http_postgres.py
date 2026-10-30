"""Real bearer-token HTTP/RLS acceptance for the corrected Live Stock R1 list.

Only disposable migrated PostgreSQL16, the production FastAPI application/router,
actual /login and get_db, and persisted canonical identity/capability dependencies.
No dependency_overrides, fabricated token, patched auth, or direct handler call.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from main import app
from models import Company, Permission, UserLocationAccess
from domains.identity.models import CompanyPrincipal
from tests.test_inbound_no_lot_frozen_postgres import pg
from tests.live_stock_r1_support import D, WAIT, assert_truth, move, r1case, spec

pytestmark = [
    pytest.mark.skipif(
        os.getenv("WANASAH_R1_PG_GATE") != "1",
        reason="Only migrated disposable PostgreSQL with actual bearer HTTP",
    ),
    pytest.mark.asyncio(loop_scope="function"),
]

PATH = "/warehouse/inventory/cursor"
OWNER_PASSWORD = "NoLotSyntheticFixture123"
READER_PASSWORD = "SyntheticFixture123"


def auth(token):
    return {"Authorization": "Bearer " + token}


def row_for(page, variant_id):
    return next(x for x in page["items"] if x["id"] == variant_id)


async def read(client, token, warehouse, **params):
    return await client.get(PATH, headers=auth(token),
                            params={"location_id": warehouse, "limit": 50, **params})


async def login(client, company, username, password):
    response = await client.post("/login", json={
        "company_code": company, "username": username, "password": password,
    })
    assert response.status_code == 200, response.text
    assert response.json().get("token")
    return response.json()["token"]


@pytest_asyncio.fixture(loop_scope="function")
async def http_case(r1case):
    case = r1case
    # Distinct foreign-cost and stock witness; canonical inbound engine, not a
    # manufactured read response or a bypass of tenant/RLS checks.
    async with case.pg.session(1) as db:
        await case.pg.post(db, case.pg.request(
            party=1, quantity="7", cost="17"), party=1)
        await db.commit()

    async with AsyncSession(case.pg.admin_engine) as db:
        identities = []
        for tenant in (case.tenant, case.pg.tenants[1]):
            company_code = await db.scalar(
                select(Company.company_code).where(Company.id == tenant.company_id))
            owner_name = await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == tenant.owner.context.principal_id))
            ordinary_name = await db.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == tenant.ordinary.context.principal_id))
            identities.append((company_code, owner_name, ordinary_name))

    # Real main.app registration (including middleware and production auth
    # dependencies), no get_db or authentication dependency overrides.
    assert any(
        getattr(route, "path", None) == PATH and "GET" in (getattr(route, "methods", None) or ())
        and route.endpoint.__name__ == "get_warehouse_inventory"
        for route in app.routes
    )
    assert not app.dependency_overrides, "A real-auth test must not inherit overrides"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://r1-http-acceptance.test",
    ) as client:
        owner = await login(client, identities[0][0], identities[0][1], OWNER_PASSWORD)
        reader = await login(client, identities[0][0], identities[0][2], READER_PASSWORD)
        foreign = await login(client, identities[1][0], identities[1][1], OWNER_PASSWORD)
        yield NS(case=case, client=client, owner=owner, reader=reader, foreign=foreign)


async def test_real_http_bearer_owner_reader_scope_revocation_and_no_cost_leak(http_case):
    g = http_case
    c, client = g.case, g.client
    foreign = c.pg.tenants[1]
    variant = c.tenant.variant_id

    # No authentication overrides, and inventory-only is exactly one
    # persisted permission, not privileged dashboard/Owner access.
    async with c.pg.session() as db:
        codes = await c.tenant.ordinary.access(db).codes(location_id=c.warehouse_id)
        assert codes == ["inventory.read"]
        assert not await db.scalar(select(c.tenant.ordinary.access(db).allows("inventory.read")))

    for headers in ({}, {"Authorization": "Bearer intentionally.invalid"}):
        denied = await client.get(PATH, params={"location_id": c.warehouse_id}, headers=headers)
        assert denied.status_code == 401, denied.text

    for token in (g.owner, g.reader):
        response = await read(client, token, c.warehouse_id)
        assert response.status_code == 200, response.text
        assert response.headers.get("x-request-id")
        page = response.json()
        assert {item["id"] for item in page["items"]} == {variant}
        item = row_for(page, variant)
        assert D(item["on_hand_quantity"]) == D("10")
        assert D(item["vehicle_quantity"]) == D("10")
        assert D(item["total_quantity"]) == D("20")
        assert Decimal(item["average_cost_display"]) == D("2")
        assert Decimal(item["last_purchase_cost"]) == D("2")
        assert foreign.variant_id not in {item["id"] for item in page["items"]}
        assert all(
            entry["last_purchase_cost"] is None
            or Decimal(entry["last_purchase_cost"]) != D("17")
            for entry in page["items"]
        )

        # Same-company ungranted warehouse fails even though it structurally exists.
        other = await read(client, token, c.tenant.other_location_id)
        if token == g.reader:
            assert other.status_code == 403, other.text
        else:
            assert other.status_code == 200, other.text

        foreign_denied = await read(client, token, foreign.location_id)
        assert foreign_denied.status_code == 404, foreign_denied.text
        assert str(foreign.variant_id) not in str(foreign_denied.json())

    # Foreign-company Owner legitimately sees their own separate stock/cost
    # but cannot query this tenant by passing a warehouse id.
    own_foreign = await read(client, g.foreign, foreign.location_id)
    assert own_foreign.status_code == 200, own_foreign.text
    foreign_item = row_for(own_foreign.json(), foreign.variant_id)
    assert D(foreign_item["on_hand_quantity"]) == D("7")
    assert Decimal(foreign_item["last_purchase_cost"]) == D("17")
    cross = await read(client, g.foreign, c.warehouse_id)
    assert cross.status_code == 404, cross.text

    # Revoke vehicle location via committed DB grant mutation, with *same*
    # original access token. Exact warehouse permission remains.
    async with c.pg.session() as db:
        await db.execute(delete(UserLocationAccess).where(
            UserLocationAccess.company_id == c.tenant.company_id,
            UserLocationAccess.driver_id == c.tenant.ordinary.driver_id,
            UserLocationAccess.location_id == c.vehicle_id,
        ))
        await db.commit()
    hidden = await read(client, g.reader, c.warehouse_id)
    assert hidden.status_code == 200, hidden.text
    hidden_item = row_for(hidden.json(), variant)
    assert D(hidden_item["on_hand_quantity"]) == D("10")
    assert D(hidden_item["vehicle_quantity"]) == D("0")
    assert D(hidden_item["total_quantity"]) == D("10")
    vehicle_filter = await read(client, g.reader, c.warehouse_id, has_vehicle="true")
    assert vehicle_filter.status_code == 200, vehicle_filter.text
    assert vehicle_filter.json()["items"] == []

    # Revoking the remaining warehouse scope must deny this SAME bearer token.
    async with c.pg.session() as db:
        await db.execute(delete(UserLocationAccess).where(
            UserLocationAccess.company_id == c.tenant.company_id,
            UserLocationAccess.driver_id == c.tenant.ordinary.driver_id,
            UserLocationAccess.location_id == c.warehouse_id,
        ))
        await db.commit()
    denied = await read(client, g.reader, c.warehouse_id)
    assert denied.status_code == 403, denied.text
    assert "items" not in denied.json()
    # Canonical owner is unaffected by another principal's grant removal.
    owner_still_works = await read(client, g.owner, c.warehouse_id)
    assert owner_still_works.status_code == 200, owner_still_works.text
    await assert_truth(c, warehouse="10", vehicle="10")


async def test_http_combined_statement_keeps_precommit_snapshot_after_real_transfer(http_case):
    g = http_case
    c = g.case
    reached, release = asyncio.Event(), asyncio.Event()
    original_execute = AsyncSession.execute
    paused = False

    async def boundary(self, statement, *args, **kwargs):
        nonlocal paused
        sql = str(statement.compile(dialect=postgresql.dialect()))
        result = await original_execute(self, statement, *args, **kwargs)
        # Observe the actual combined PostgreSQL statement after its snapshot
        # completes; never intercept auth, create rows or substitute results.
        if ("inventory_page_candidates" in sql
                and "inventory_detail_keys" in sql and not paused):
            paused = True
            reached.set()
            await asyncio.wait_for(release.wait(), WAIT)
        return result

    task = None
    with patch.object(AsyncSession, "execute", boundary):
        try:
            task = asyncio.create_task(read(g.client, g.reader, c.warehouse_id))
            await asyncio.wait_for(reached.wait(), WAIT)
            async with c.pg.session() as db:
                await move(db, c, spec(
                    c, source=c.vehicle_id, destination=c.warehouse_id))
                await db.commit()
        finally:
            release.set()
        assert task is not None
        response = await asyncio.wait_for(task, WAIT)
    assert paused, "No real combined statement boundary was reached"
    assert response.status_code == 200, response.text
    item = row_for(response.json(), c.tenant.variant_id)
    assert (D(item["on_hand_quantity"]), D(item["vehicle_quantity"])) == (D("10"), D("10"))
    assert D(item["total_quantity"]) == D("20")
    await assert_truth(c, warehouse="20", vehicle="0")
    subsequent = await read(g.client, g.reader, c.warehouse_id)
    assert subsequent.status_code == 200, subsequent.text
    item = row_for(subsequent.json(), c.tenant.variant_id)
    assert (D(item["on_hand_quantity"]), D(item["vehicle_quantity"])) == (D("20"), D("0"))
    assert D(item["total_quantity"]) == D("20")
