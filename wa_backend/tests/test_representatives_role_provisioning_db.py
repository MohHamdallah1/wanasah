"""PostgreSQL acceptance for Representative capability provisioning through Roles."""
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
from database import get_db
from domains.authorization.capabilities import COMPANY_ONLY
from domains.identity.models import CompanyPrincipal
from main import (
    WanasahRawASGIMiddleware,
    custom_http_exception_handler,
    validation_exception_handler,
)
from models import Company, Permission
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)

pytestmark = pytest.mark.skipif(
    os.getenv("WANASAH_REPRESENTATIVES_ROLE_DB_GATE") != "1",
    reason="Explicit isolated Representative role-provisioning PostgreSQL gate only",
)

OWNER_PASSWORD = "RepresentativeRoleOwner123"
USER_PASSWORD = "RepresentativeRoleUser123"
REPRESENTATIVE_PASSWORD = "RepresentativeRoleField123"
RESET_PASSWORD = "RepresentativeRoleReset456"
CAPABILITIES = {
    "representative.read",
    "representative.manage",
    "representative.credentials.reset",
}


async def _username(db: AsyncSession, principal_id: int) -> str:
    value = await db.scalar(
        select(CompanyPrincipal.username).where(CompanyPrincipal.id == principal_id)
    )
    assert isinstance(value, str) and value
    return value


@pytest_asyncio.fixture(scope="module")
async def gate():
    admin_url = os.environ["DATABASE_URL_MIGRATION"]
    runtime_url = os.environ["DATABASE_URL"]
    assert make_url(admin_url).database == "representatives_role_gate"
    assert make_url(runtime_url).database == "representatives_role_gate"

    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)

    async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
        catalog = set((await seed.scalars(
            select(Permission.code).where(Permission.code.in_(CAPABILITIES))
        )).all())
        assert catalog == CAPABILITIES, (
            "Representative permission rows must come from Alembic migration; "
            f"found {sorted(catalog)}"
        )
        assert CAPABILITIES <= COMPANY_ONLY

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
            name: await seed_ordinary_backoffice_fixture(
                seed, companies[0].id, password=USER_PASSWORD
            )
            for name in ("read", "manage", "reset", "all", "none")
        }
        foreign_user = await seed_ordinary_backoffice_fixture(
            seed, companies[1].id, password=USER_PASSWORD
        )

        owner_usernames = [
            await _username(seed, owner.context.principal_id) for owner in owners
        ]
        usernames = {
            name: await _username(seed, fixture.context.principal_id)
            for name, fixture in users.items()
        }
        foreign_username = await _username(seed, foreign_user.context.principal_id)
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

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://representative-role-gate") as client:
        state = SimpleNamespace(
            client=client,
            admin_engine=admin_engine,
            runtime_engine=runtime_engine,
            companies=companies,
            owners=owners,
            users=users,
            foreign_user=foreign_user,
            owner_usernames=owner_usernames,
            usernames=usernames,
            foreign_username=foreign_username,
        )

        state.owner_tokens = []
        for company, username in zip(companies, owner_usernames):
            response = await client.post("/login", json={
                "company_code": company.company_code,
                "username": username,
                "password": OWNER_PASSWORD,
            })
            assert response.status_code == 200, response.text
            state.owner_tokens.append(response.json()["token"])

        yield state

    await runtime_engine.dispose()
    await admin_engine.dispose()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def owner_auth(gate, company_index: int = 0) -> dict[str, str]:
    return bearer(gate.owner_tokens[company_index])


def create_body(prefix: str) -> dict[str, object]:
    suffix = uuid4().hex[:10]
    return {
        "request_id": str(uuid4()),
        "full_name": f"RBAC Representative {prefix} {suffix}",
        "username": f"rbac_{prefix}_{suffix}",
        "phone_number": "+962790001234",
        "password": REPRESENTATIVE_PASSWORD,
        "can_allow_debt": False,
        "max_debt_limit": "0.000",
    }


async def create_role(gate, name: str, permissions: list[str], *, company_index: int = 0):
    response = await gate.client.post(
        "/inventory/access/roles",
        json={"name": name, "permissions": permissions},
        headers=owner_auth(gate, company_index),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def grant_role(gate, user_id: int, role_id: int, *, company_index: int = 0):
    return await gate.client.post(
        f"/inventory/access/users/{user_id}/grants",
        json={"role_id": role_id, "location_id": None},
        headers=owner_auth(gate, company_index),
    )


async def login_user(gate, name: str) -> str:
    response = await gate.client.post("/login", json={
        "company_code": gate.companies[0].company_code,
        "username": gate.usernames[name],
        "password": USER_PASSWORD,
    })
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def create_rep(gate, headers: dict[str, str], prefix: str):
    response = await gate.client.post(
        "/representatives", json=create_body(prefix), headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def assert_forbidden(response: httpx.Response):
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_representative_roles_can_be_provisioned_revoked_and_consumed(gate):
    owner_headers = owner_auth(gate)

    catalog = await gate.client.get("/inventory/access/catalog", headers=owner_headers)
    assert catalog.status_code == 200, catalog.text
    assert CAPABILITIES <= set(catalog.json()["permissions"])
    assert CAPABILITIES <= set(catalog.json()["company_only"])

    roles = {
        "read": await create_role(gate, "Representative read", ["representative.read"]),
        "manage": await create_role(
            gate,
            "Representative read and manage",
            ["representative.read", "representative.manage"],
        ),
        "reset": await create_role(
            gate,
            "Representative read and reset",
            ["representative.read", "representative.credentials.reset"],
        ),
        "all": await create_role(gate, "Representative full", sorted(CAPABILITIES)),
        "none": await create_role(gate, "Non Representative access", ["inventory.read"]),
    }
    foreign_role = await create_role(
        gate, "Foreign Representative full", sorted(CAPABILITIES), company_index=1
    )

    role_page = await gate.client.get(
        "/inventory/access/roles?limit=100", headers=owner_headers
    )
    assert role_page.status_code == 200, role_page.text
    reloaded = {item["id"]: item for item in role_page.json()["items"]}
    for role in roles.values():
        assert reloaded[role["id"]]["permissions"] == role["permissions"]

    grant_ids: dict[str, int] = {}
    for name, role in roles.items():
        user_id = gate.users[name].context.backoffice_user_id
        first = await grant_role(gate, user_id, role["id"])
        assert first.status_code == 201, first.text
        assert first.json() == {"created": True}
        duplicate = await grant_role(gate, user_id, role["id"])
        assert duplicate.status_code == 201, duplicate.text
        assert duplicate.json() == {"created": False}
        grants = await gate.client.get(
            f"/inventory/access/users/{user_id}/grants?scope=company",
            headers=owner_headers,
        )
        assert grants.status_code == 200, grants.text
        matches = [item for item in grants.json()["items"] if item["role_id"] == role["id"]]
        assert len(matches) == 1
        grant_ids[name] = matches[0]["id"]

    cross_user = await grant_role(
        gate, gate.foreign_user.context.backoffice_user_id, roles["all"]["id"]
    )
    assert cross_user.status_code == 404, cross_user.text
    cross_role = await grant_role(
        gate, gate.users["all"].context.backoffice_user_id, foreign_role["id"]
    )
    assert cross_role.status_code == 404, cross_role.text

    tokens = {name: await login_user(gate, name) for name in roles}
    headers = {name: bearer(token) for name, token in tokens.items()}

    me_expected = {
        "read": {"representative.read"},
        "manage": {"representative.read", "representative.manage"},
        "reset": {"representative.read", "representative.credentials.reset"},
        "all": CAPABILITIES,
        "none": set(),
    }
    for name in roles:
        response = await gate.client.get("/inventory/access/me", headers=headers[name])
        assert response.status_code == 200, response.text
        representative_codes = set(response.json()["permissions"]) & CAPABILITIES
        assert representative_codes == me_expected[name]

    owner_me = await gate.client.get("/inventory/access/me", headers=owner_headers)
    assert owner_me.status_code == 200
    assert owner_me.json()["is_company_owner"] is True
    assert CAPABILITIES <= set(owner_me.json()["permissions"])
    owner_grants = await gate.client.get(
        f"/inventory/access/users/{gate.owners[0].context.backoffice_user_id}/grants?scope=company",
        headers=owner_headers,
    )
    assert owner_grants.status_code == 200
    assert owner_grants.json()["items"] == []

    common = await create_rep(gate, owner_headers, "common")

    # READ ONLY: read surface works, every mutation family remains denied.
    assert (await gate.client.get("/representatives", headers=headers["read"])).status_code == 200
    assert (await gate.client.get(
        f"/representatives/{common['id']}", headers=headers["read"]
    )).status_code == 200
    await assert_forbidden(await gate.client.post(
        "/representatives", json=create_body("read_denied"), headers=headers["read"]
    ))
    await assert_forbidden(await gate.client.patch(
        f"/representatives/{common['id']}",
        json={"request_id": str(uuid4()), "full_name": "Denied read-only update"},
        headers=headers["read"],
    ))
    for action in ("deactivate", "reactivate"):
        await assert_forbidden(await gate.client.post(
            f"/representatives/{common['id']}/{action}",
            json={"request_id": str(uuid4())}, headers=headers["read"],
        ))
    await assert_forbidden(await gate.client.post(
        f"/representatives/{common['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD},
        headers=headers["read"],
    ))

    # READ + MANAGE: management/lifecycle works, credential reset remains independent.
    managed = await create_rep(gate, headers["manage"], "managed")
    updated = await gate.client.patch(
        f"/representatives/{managed['id']}",
        json={"request_id": str(uuid4()), "full_name": "Managed Representative Updated"},
        headers=headers["manage"],
    )
    assert updated.status_code == 200, updated.text
    deactivated = await gate.client.post(
        f"/representatives/{managed['id']}/deactivate",
        json={"request_id": str(uuid4())}, headers=headers["manage"],
    )
    assert deactivated.status_code == 204, deactivated.text
    reactivated = await gate.client.post(
        f"/representatives/{managed['id']}/reactivate",
        json={"request_id": str(uuid4())}, headers=headers["manage"],
    )
    assert reactivated.status_code == 204, reactivated.text
    await assert_forbidden(await gate.client.post(
        f"/representatives/{managed['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD},
        headers=headers["manage"],
    ))

    # READ + RESET: credential reset works while management/lifecycle stays denied.
    reset_target = await create_rep(gate, owner_headers, "reset_target")
    reset = await gate.client.post(
        f"/representatives/{reset_target['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD},
        headers=headers["reset"],
    )
    assert reset.status_code == 204, reset.text
    assert (await gate.client.get("/representatives", headers=headers["reset"])).status_code == 200
    await assert_forbidden(await gate.client.post(
        "/representatives", json=create_body("reset_denied"), headers=headers["reset"]
    ))
    await assert_forbidden(await gate.client.patch(
        f"/representatives/{reset_target['id']}",
        json={"request_id": str(uuid4()), "full_name": "Denied reset-only update"},
        headers=headers["reset"],
    ))
    for action in ("deactivate", "reactivate"):
        await assert_forbidden(await gate.client.post(
            f"/representatives/{reset_target['id']}/{action}",
            json={"request_id": str(uuid4())}, headers=headers["reset"],
        ))

    # ALL THREE: every Representative route family is usable.
    all_target = await create_rep(gate, headers["all"], "all")
    assert (await gate.client.get("/representatives", headers=headers["all"])).status_code == 200
    assert (await gate.client.get(
        f"/representatives/{all_target['id']}", headers=headers["all"]
    )).status_code == 200
    assert (await gate.client.patch(
        f"/representatives/{all_target['id']}",
        json={"request_id": str(uuid4()), "full_name": "Full Capability Representative"},
        headers=headers["all"],
    )).status_code == 200
    assert (await gate.client.post(
        f"/representatives/{all_target['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD},
        headers=headers["all"],
    )).status_code == 204
    assert (await gate.client.post(
        f"/representatives/{all_target['id']}/deactivate",
        json={"request_id": str(uuid4())}, headers=headers["all"],
    )).status_code == 204
    assert (await gate.client.post(
        f"/representatives/{all_target['id']}/reactivate",
        json={"request_id": str(uuid4())}, headers=headers["all"],
    )).status_code == 204

    # NO Representative permissions: user can have other Dashboard access but no Representative route authority.
    await assert_forbidden(await gate.client.get("/representatives", headers=headers["none"]))
    await assert_forbidden(await gate.client.get(
        f"/representatives/{common['id']}", headers=headers["none"]
    ))
    await assert_forbidden(await gate.client.post(
        "/representatives", json=create_body("none_denied"), headers=headers["none"]
    ))
    await assert_forbidden(await gate.client.post(
        f"/representatives/{common['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD},
        headers=headers["none"],
    ))

    # Company Owner has full canonical authority without a persisted UserRole grant.
    owner_target = await create_rep(gate, owner_headers, "owner")
    assert (await gate.client.get("/representatives", headers=owner_headers)).status_code == 200
    assert (await gate.client.patch(
        f"/representatives/{owner_target['id']}",
        json={"request_id": str(uuid4()), "full_name": "Owner Managed Representative"},
        headers=owner_headers,
    )).status_code == 200
    assert (await gate.client.post(
        f"/representatives/{owner_target['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD},
        headers=owner_headers,
    )).status_code == 204

    # Active sessions pick up role edits on the next request; no login/refresh is required.
    manage_role = roles["manage"]
    edit_manage = await gate.client.put(
        f"/inventory/access/roles/{manage_role['id']}",
        json={"name": manage_role["name"], "permissions": ["representative.read"]},
        headers=owner_headers,
    )
    assert edit_manage.status_code == 200, edit_manage.text
    await assert_forbidden(await gate.client.post(
        "/representatives", json=create_body("manage_revoked"), headers=headers["manage"]
    ))
    assert (await gate.client.get("/representatives", headers=headers["manage"])).status_code == 200
    manage_me = await gate.client.get("/inventory/access/me", headers=headers["manage"])
    assert set(manage_me.json()["permissions"]) & CAPABILITIES == {"representative.read"}

    reset_role = roles["reset"]
    edit_reset = await gate.client.put(
        f"/inventory/access/roles/{reset_role['id']}",
        json={"name": reset_role["name"], "permissions": ["representative.read"]},
        headers=owner_headers,
    )
    assert edit_reset.status_code == 200, edit_reset.text
    await assert_forbidden(await gate.client.post(
        f"/representatives/{common['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD},
        headers=headers["reset"],
    ))
    assert (await gate.client.get("/representatives", headers=headers["reset"])).status_code == 200

    # Removing the company grant itself also removes authority from the already-issued token.
    all_user_id = gate.users["all"].context.backoffice_user_id
    revoked = await gate.client.delete(
        f"/inventory/access/users/{all_user_id}/grants/{grant_ids['all']}?scope=company",
        headers=owner_headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {"revoked": True}
    await assert_forbidden(await gate.client.get("/representatives", headers=headers["all"]))

    # A Company A grant cannot expose a Company B representative.
    foreign_rep = await create_rep(gate, owner_auth(gate, 1), "foreign")
    foreign_detail = await gate.client.get(
        f"/representatives/{foreign_rep['id']}", headers=headers["read"]
    )
    assert foreign_detail.status_code == 404, foreign_detail.text

    # Role edit/reload reflects revoked permissions exactly.
    final_roles = await gate.client.get(
        "/inventory/access/roles?limit=100", headers=owner_headers
    )
    assert final_roles.status_code == 200
    final_by_id = {item["id"]: item for item in final_roles.json()["items"]}
    assert final_by_id[manage_role["id"]]["permissions"] == ["representative.read"]
    assert final_by_id[reset_role["id"]]["permissions"] == ["representative.read"]
