"""Phase 4 uses the mounted application and disposable CI PostgreSQL only.

Reuse the accepted Phase 3 business fixture, not an alternate authority engine.
All protected operations run through HTTP with the real restricted runtime role.
Privileged connections are used only for synthetic setup and evidence inspection.
"""
import os
from uuid import uuid4

import httpx
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from context import tenant_context
from database import engine as runtime_engine
from main import app
from tests.field_authorization_phase3_fixture import (
    PASSWORD, auth, call, denied, evidence, new_transfers, seed_business,
)


async def login_scene(g, client):
    g.client = client
    async def login(name, path):
        response = await client.post(path, json={
            "company_code": g.company_code, "username": name, "password": PASSWORD,
        })
        assert response.status_code == 200, response.text
        return response.json()
    g.login = await login(g.field_name, "/driver/login")
    g.token = g.login["token"]
    g.other_token = (await login(g.other_name, "/driver/login"))["token"]
    g.owner_token = (await login(g.owner_name, "/login"))["token"]
    g.bo_token = (await login(g.bo_name, "/login"))["token"]
    return g


@pytest_asyncio.fixture
async def scene():
    assert os.getenv("GITHUB_ACTIONS") == "true", "Disposable GitHub CI only"
    assert os.getenv("WANASAH_FIELD_AUTH_PHASE4_GATE") == "1"
    for key in ("DATABASE_URL", "DATABASE_URL_MIGRATION"):
        url = make_url(os.environ[key])
        assert url.database == "field_auth_phase4_gate"
        assert url.host in ("127.0.0.1", "localhost")
    original = tenant_context.set(None)
    admin = create_async_engine(os.environ["DATABASE_URL_MIGRATION"], poolclass=NullPool)
    @event.listens_for(admin.sync_engine, "begin")
    def seed_tenant(connection):
        connection.execute(text("SELECT set_config('app.current_tenant',:c,true)"),
                           {"c": str(tenant_context.get() or "")})
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://field-phase4",
        ) as client:
            g = await login_scene(await seed_business(admin), client)
            async def foreign():
                return await login_scene(await seed_business(admin), client)
            g.foreign_scene = foreign
            async with runtime_engine.connect() as db:
                row = (await db.execute(text(
                    "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ))).one()
                assert row == ("field_auth_runtime", False, False)
            assert not app.dependency_overrides, "No mocked auth or business dependency"
            yield g
    finally:
        await runtime_engine.dispose()
        await admin.dispose()
        tenant_context.reset(original)


async def revoke_default(g):
    response = await call(g, "POST",
        f"/representatives/{g.field.context.representative_id}/field-roles/{g.default_role}/revoke",
        {"request_id": str(uuid4())}, token=g.owner_token)
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True


async def grant_default(g):
    response = await call(g, "POST",
        f"/representatives/{g.field.context.representative_id}/field-roles",
        {"request_id": str(uuid4()), "role_id": g.default_role}, token=g.owner_token)
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True


async def no_effect(g, method, path, body=None, *, token=None, statuses=(403, 404), code=None, foreign=None):
    before = await evidence(g)
    foreign_before = await evidence(foreign) if foreign else None
    response = await call(g, method, path, body, token=token)
    assert response.status_code in statuses, response.text
    error = response.json()["error"]
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["context"], dict) and error["request_id"]
    if code:
        assert error["code"] == code, error
    assert await evidence(g) == before, "Denied request changed tenant rows"
    if foreign:
        assert await evidence(foreign) == foreign_before, "Denied request changed foreign tenant rows"
    return response


def sale(g, packs=10):
    return {"request_id": str(uuid4()), "outcome": "Sale", "cash_collected": str(packs * 5),
            "cart_items": [{"product_variant_id": g.variant["id"], "packs_quantity": packs}]}


async def posted(g, method, path, body, status=200):
    response = await call(g, method, path, body)
    assert response.status_code == status, response.text
    return response


async def completed_replay_revocation(g, method, path, body, initial):
    """A successful command exists BEFORE revocation; identical token/body are retained."""
    before = await evidence(g)
    replay = await posted(g, method, path, body, initial.status_code)
    assert replay.json() == initial.json()
    assert await evidence(g) == before
    token = g.token
    await revoke_default(g)
    await no_effect(g, method, path, body, statuses=(403,), code="FIELD_CAPABILITY_DENIED")
    assert g.token == token
    await grant_default(g)
    before = await evidence(g)
    replay = await posted(g, method, path, body, initial.status_code)
    assert replay.json() == initial.json()
    assert await evidence(g) == before, "Reauthorized replay applied a second effect"
