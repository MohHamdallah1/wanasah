"""Migrated PostgreSQL acceptance for Representative RBAC provisioning."""
from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException

from api.auth import router as auth_router
from api.inventory_permissions import router as access_router
from api.representatives import router as representatives_router
from database import engine as runtime_engine, get_db
from domains.authorization.capabilities import COMPANY_ONLY
from domains.identity.models import CompanyPrincipal
from main import WanasahRawASGIMiddleware, custom_http_exception_handler, validation_exception_handler
from models import Company, Permission
from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_ordinary_backoffice_fixture

pytestmark = pytest.mark.skipif(
    os.getenv("WANASAH_REPRESENTATIVES_ROLE_DB_GATE") != "1",
    reason="isolated Representative role-provisioning PostgreSQL gate only",
)

CAPS = {
    "representative.read",
    "representative.manage",
    "representative.credentials.reset",
}
OWNER_PASSWORD = "RepresentativeRoleOwner123"
USER_PASSWORD = "RepresentativeRoleUser123"
FIELD_PASSWORD = "RepresentativeRoleField123"
RESET_PASSWORD = "RepresentativeRoleReset456"


async def _username(db: AsyncSession, principal_id: int) -> str:
    value = await db.scalar(select(CompanyPrincipal.username).where(CompanyPrincipal.id == principal_id))
    assert isinstance(value, str) and value
    return value


@pytest_asyncio.fixture(scope="module")
async def gate():
    admin_url = os.environ["DATABASE_URL_MIGRATION"]
    runtime_url = os.environ["DATABASE_URL"]
    assert make_url(admin_url).database == "representatives_role_gate"
    assert make_url(runtime_url).database == "representatives_role_gate"
    assert make_url(str(runtime_engine.url)).database == "representatives_role_gate"

    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
        migrated = set((await seed.scalars(
            select(Permission.code).where(Permission.code.in_(CAPS))
        )).all())
        assert migrated == CAPS
        assert CAPS <= COMPANY_ONLY

        companies = [
            Company(name="Representative RBAC A", company_code="RRA"),
            Company(name="Representative RBAC B", company_code="RRB"),
        ]
        seed.add_all(companies)
        await seed.flush()
        owners = [
            await seed_company_owner_fixture(seed, company.id, password=OWNER_PASSWORD)
            for company in companies
        ]
        users = {
            name: await seed_ordinary_backoffice_fixture(seed, companies[0].id, password=USER_PASSWORD)
            for name in ("read", "manage", "reset", "all", "none")
        }
        foreign_user = await seed_ordinary_backoffice_fixture(
            seed, companies[1].id, password=USER_PASSWORD
        )
        owner_names = [await _username(seed, owner.context.principal_id) for owner in owners]
        user_names = {
            name: await _username(seed, actor.context.principal_id)
            for name, actor in users.items()
        }
        await seed.commit()

    async def runtime_db():
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            yield db

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(access_router)
    app.include_router(representatives_router)
    app.add_exception_handler(HTTPException, custom_http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_middleware(WanasahRawASGIMiddleware)
    app.dependency_overrides[get_db] = runtime_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://representative-rbac-gate"
    ) as client:
        owner_tokens = []
        for company, username in zip(companies, owner_names):
            response = await client.post("/login", json={
                "company_code": company.company_code,
                "username": username,
                "password": OWNER_PASSWORD,
            })
            assert response.status_code == 200, response.text
            owner_tokens.append(response.json()["token"])
        yield SimpleNamespace(
            client=client,
            companies=companies,
            owners=owners,
            users=users,
            foreign_user=foreign_user,
            user_names=user_names,
            owner_tokens=owner_tokens,
        )

    await runtime_engine.dispose()
    await admin_engine.dispose()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def owner_auth(gate, index: int = 0) -> dict[str, str]:
    return auth(gate.owner_tokens[index])


def rep_body(prefix: str) -> dict[str, object]:
    suffix = uuid4().hex[:10]
    return {
        "request_id": str(uuid4()),
        "full_name": f"RBAC Representative {prefix} {suffix}",
        "username": f"rbac_{prefix}_{suffix}",
        "phone_number": "+962790001234",
        "password": FIELD_PASSWORD,
        "can_allow_debt": False,
        "max_debt_limit": "0.000",
    }


async def create_role(gate, name: str, permissions: list[str], company: int = 0):
    response = await gate.client.post(
        "/inventory/access/roles",
        json={"name": name, "permissions": permissions},
        headers=owner_auth(gate, company),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def grant(gate, user_id: int, role_id: int, company: int = 0):
    return await gate.client.post(
        f"/inventory/access/users/{user_id}/grants",
        json={"role_id": role_id, "location_id": None},
        headers=owner_auth(gate, company),
    )


async def login(gate, name: str) -> str:
    response = await gate.client.post("/login", json={
        "company_code": gate.companies[0].company_code,
        "username": gate.user_names[name],
        "password": USER_PASSWORD,
    })
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def create_rep(gate, headers: dict[str, str], prefix: str):
    response = await gate.client.post("/representatives", json=rep_body(prefix), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def assert_denied(response: httpx.Response):
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_roles_grants_revocation_matrix_and_tenant_isolation(gate):
    owner = owner_auth(gate)
    catalog = await gate.client.get("/inventory/access/catalog", headers=owner)
    assert catalog.status_code == 200
    assert CAPS <= set(catalog.json()["permissions"])
    assert CAPS <= set(catalog.json()["company_only"])

    roles = {
        "read": await create_role(gate, "Representative read", ["representative.read"]),
        "manage": await create_role(gate, "Representative read manage", ["representative.read", "representative.manage"]),
        "reset": await create_role(gate, "Representative read reset", ["representative.read", "representative.credentials.reset"]),
        "all": await create_role(gate, "Representative all", sorted(CAPS)),
        "none": await create_role(gate, "Other dashboard access", ["inventory.read"]),
    }
    foreign_role = await create_role(gate, "Foreign Representative all", sorted(CAPS), 1)

    page = await gate.client.get("/inventory/access/roles?limit=100", headers=owner)
    assert page.status_code == 200
    by_id = {row["id"]: row for row in page.json()["items"]}
    for role in roles.values():
        assert by_id[role["id"]]["permissions"] == role["permissions"]

    grant_ids = {}
    for name, role in roles.items():
        user_id = gate.users[name].context.backoffice_user_id
        first = await grant(gate, user_id, role["id"])
        second = await grant(gate, user_id, role["id"])
        assert first.status_code == second.status_code == 201
        assert first.json() == {"created": True}
        assert second.json() == {"created": False}
        current = await gate.client.get(
            f"/inventory/access/users/{user_id}/grants?scope=company", headers=owner
        )
        rows = [row for row in current.json()["items"] if row["role_id"] == role["id"]]
        assert len(rows) == 1
        grant_ids[name] = rows[0]["id"]

    assert (await grant(
        gate, gate.foreign_user.context.backoffice_user_id, roles["all"]["id"]
    )).status_code == 404
    assert (await grant(
        gate, gate.users["all"].context.backoffice_user_id, foreign_role["id"]
    )).status_code == 404

    tokens = {name: await login(gate, name) for name in roles}
    headers = {name: auth(token) for name, token in tokens.items()}
    expected = {
        "read": {"representative.read"},
        "manage": {"representative.read", "representative.manage"},
        "reset": {"representative.read", "representative.credentials.reset"},
        "all": CAPS,
        "none": set(),
    }
    for name in roles:
        me = await gate.client.get("/inventory/access/me", headers=headers[name])
        assert me.status_code == 200
        assert set(me.json()["permissions"]) & CAPS == expected[name]

    owner_me = await gate.client.get("/inventory/access/me", headers=owner)
    assert owner_me.status_code == 200
    assert owner_me.json()["is_company_owner"] is True
    assert CAPS <= set(owner_me.json()["permissions"])
    owner_grants = await gate.client.get(
        f"/inventory/access/users/{gate.owners[0].context.backoffice_user_id}/grants?scope=company",
        headers=owner,
    )
    assert owner_grants.status_code == 200
    assert owner_grants.json()["items"] == []

    common = await create_rep(gate, owner, "common")

    # Read-only role.
    assert (await gate.client.get("/representatives", headers=headers["read"])).status_code == 200
    assert (await gate.client.get(f"/representatives/{common['id']}", headers=headers["read"])).status_code == 200
    assert_denied(await gate.client.post("/representatives", json=rep_body("read-denied"), headers=headers["read"]))
    assert_denied(await gate.client.patch(
        f"/representatives/{common['id']}",
        json={"request_id": str(uuid4()), "full_name": "Denied update"}, headers=headers["read"]
    ))
    for action in ("deactivate", "reactivate"):
        assert_denied(await gate.client.post(
            f"/representatives/{common['id']}/{action}",
            json={"request_id": str(uuid4())}, headers=headers["read"]
        ))
    assert_denied(await gate.client.post(
        f"/representatives/{common['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD}, headers=headers["read"]
    ))

    # Read + manage role.
    managed = await create_rep(gate, headers["manage"], "manage")
    assert (await gate.client.patch(
        f"/representatives/{managed['id']}",
        json={"request_id": str(uuid4()), "full_name": "Managed Updated"}, headers=headers["manage"]
    )).status_code == 200
    assert (await gate.client.post(
        f"/representatives/{managed['id']}/deactivate",
        json={"request_id": str(uuid4())}, headers=headers["manage"]
    )).status_code == 204
    assert (await gate.client.post(
        f"/representatives/{managed['id']}/reactivate",
        json={"request_id": str(uuid4())}, headers=headers["manage"]
    )).status_code == 204
    assert_denied(await gate.client.post(
        f"/representatives/{managed['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD}, headers=headers["manage"]
    ))

    # Read + reset role.
    reset_target = await create_rep(gate, owner, "reset")
    assert (await gate.client.post(
        f"/representatives/{reset_target['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD}, headers=headers["reset"]
    )).status_code == 204
    assert_denied(await gate.client.post("/representatives", json=rep_body("reset-denied"), headers=headers["reset"]))
    assert_denied(await gate.client.patch(
        f"/representatives/{reset_target['id']}",
        json={"request_id": str(uuid4()), "full_name": "Denied reset update"}, headers=headers["reset"]
    ))
    for action in ("deactivate", "reactivate"):
        assert_denied(await gate.client.post(
            f"/representatives/{reset_target['id']}/{action}",
            json={"request_id": str(uuid4())}, headers=headers["reset"]
        ))

    # All Representative capabilities.
    full = await create_rep(gate, headers["all"], "all")
    assert (await gate.client.get(f"/representatives/{full['id']}", headers=headers["all"])).status_code == 200
    assert (await gate.client.patch(
        f"/representatives/{full['id']}",
        json={"request_id": str(uuid4()), "full_name": "All Updated"}, headers=headers["all"]
    )).status_code == 200
    assert (await gate.client.post(
        f"/representatives/{full['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD}, headers=headers["all"]
    )).status_code == 204
    assert (await gate.client.post(
        f"/representatives/{full['id']}/deactivate",
        json={"request_id": str(uuid4())}, headers=headers["all"]
    )).status_code == 204
    assert (await gate.client.post(
        f"/representatives/{full['id']}/reactivate",
        json={"request_id": str(uuid4())}, headers=headers["all"]
    )).status_code == 204

    # No Representative capabilities despite unrelated Dashboard access.
    assert_denied(await gate.client.get("/representatives", headers=headers["none"]))
    assert_denied(await gate.client.post("/representatives", json=rep_body("none-denied"), headers=headers["none"]))
    assert_denied(await gate.client.post(
        f"/representatives/{common['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD}, headers=headers["none"]
    ))

    # Owner authority is canonical and independent of role grants.
    owner_target = await create_rep(gate, owner, "owner")
    assert (await gate.client.patch(
        f"/representatives/{owner_target['id']}",
        json={"request_id": str(uuid4()), "full_name": "Owner Updated"}, headers=owner
    )).status_code == 200
    assert (await gate.client.post(
        f"/representatives/{owner_target['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD}, headers=owner
    )).status_code == 204

    # Same active token reflects role capability revocation on the next request.
    for name, revoked_capability in (("manage", "representative.manage"), ("reset", "representative.credentials.reset")):
        role = roles[name]
        changed = await gate.client.put(
            f"/inventory/access/roles/{role['id']}",
            json={"name": role["name"], "permissions": ["representative.read"]}, headers=owner
        )
        assert changed.status_code == 200, changed.text
        if revoked_capability == "representative.manage":
            assert_denied(await gate.client.post("/representatives", json=rep_body("revoked-manage"), headers=headers[name]))
        else:
            assert_denied(await gate.client.post(
                f"/representatives/{common['id']}/credentials/reset",
                json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD}, headers=headers[name]
            ))
        assert (await gate.client.get("/representatives", headers=headers[name])).status_code == 200
        me = await gate.client.get("/inventory/access/me", headers=headers[name])
        assert set(me.json()["permissions"]) & CAPS == {"representative.read"}

    # Removing the role assignment also affects the already-issued token immediately.
    all_user_id = gate.users["all"].context.backoffice_user_id
    revoked = await gate.client.delete(
        f"/inventory/access/users/{all_user_id}/grants/{grant_ids['all']}?scope=company",
        headers=owner,
    )
    assert revoked.status_code == 200
    assert revoked.json() == {"revoked": True}
    assert_denied(await gate.client.get("/representatives", headers=headers["all"]))

    # Company A authority cannot expose Company B Representative data.
    foreign = await create_rep(gate, owner_auth(gate, 1), "foreign")
    assert (await gate.client.get(
        f"/representatives/{foreign['id']}", headers=headers["read"]
    )).status_code == 404

    # Reloaded role state preserves the revocation exactly.
    final_page = await gate.client.get("/inventory/access/roles?limit=100", headers=owner)
    final_by_id = {row["id"]: row for row in final_page.json()["items"]}
    assert final_by_id[roles["manage"]["id"]]["permissions"] == ["representative.read"]
    assert final_by_id[roles["reset"]["id"]]["permissions"] == ["representative.read"]
