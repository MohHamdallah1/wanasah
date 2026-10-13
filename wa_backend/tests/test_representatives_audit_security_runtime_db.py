"""PostgreSQL acceptance for Representative audit/idempotency security."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException

from api.auth import router as auth_router
from api.representatives import router as representatives_router
from database import engine as runtime_engine, get_db
from domains.auth_sessions.models import PrincipalRefreshToken
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.representatives.credentials import fingerprint_initial_password, fingerprint_reset_password
from main import WanasahRawASGIMiddleware, custom_http_exception_handler, global_exception_handler, validation_exception_handler
from models import Company, Driver, OperationIdempotency, SystemAuditLog, utc_now
from tests.canonical_actor_fixtures import seed_company_owner_fixture

pytestmark = pytest.mark.skipif(
    os.getenv("WANASAH_REPRESENTATIVES_AUDIT_DB_GATE") != "1",
    reason="isolated Representative audit DB gate only",
)

CREATE_PASSWORD = "Create-" + uuid4().hex
RESET_PASSWORD = "Reset-" + uuid4().hex
OWNER_PASSWORD = "Owner-" + uuid4().hex
PUBLIC_KEYS = {"id", "full_name", "username", "phone_number", "is_active", "can_allow_debt", "max_debt_limit"}
ACTIONS = [
    "REPRESENTATIVE_CREATED",
    "REPRESENTATIVE_UPDATED",
    "REPRESENTATIVE_DEACTIVATED",
    "REPRESENTATIVE_REACTIVATED",
    "REPRESENTATIVE_CREDENTIALS_RESET",
]
OPERATIONS = {
    "REPRESENTATIVE_CREATE", "REPRESENTATIVE_UPDATE", "REPRESENTATIVE_DEACTIVATE",
    "REPRESENTATIVE_REACTIVATE", "REPRESENTATIVE_CREDENTIAL_RESET",
}


@pytest_asyncio.fixture(scope="module")
async def gate():
    admin_engine = create_async_engine(os.environ["DATABASE_URL_MIGRATION"], poolclass=NullPool)
    async with AsyncSession(admin_engine, expire_on_commit=False) as db:
        companies = [Company(name="Audit A", company_code="AUD-A"), Company(name="Audit B", company_code="AUD-B")]
        db.add_all(companies)
        await db.flush()
        owners = [await seed_company_owner_fixture(db, c.id, password=OWNER_PASSWORD) for c in companies]
        usernames = [await db.scalar(select(CompanyPrincipal.username).where(CompanyPrincipal.id == o.context.principal_id)) for o in owners]
        await db.commit()

    async def runtime_db():
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            yield db

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(representatives_router)
    app.add_exception_handler(HTTPException, custom_http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    app.add_middleware(WanasahRawASGIMiddleware)
    app.dependency_overrides[get_db] = runtime_db

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://audit-gate") as client:
        tokens = []
        for company, username in zip(companies, usernames):
            r = await client.post("/login", json={"company_code": company.company_code, "username": username, "password": OWNER_PASSWORD})
            assert r.status_code == 200, r.text
            tokens.append(r.json()["token"])
        yield SimpleNamespace(client=client, companies=companies, owners=owners, tokens=tokens, admin=admin_engine)

    await runtime_engine.dispose()
    await admin_engine.dispose()


def headers(gate, index=0):
    return {"Authorization": f"Bearer {gate.tokens[index]}"}


def create_payload(prefix, request_id=None, password=CREATE_PASSWORD):
    suffix = uuid4().hex[:8]
    return {
        "request_id": request_id or str(uuid4()), "full_name": f"Rep {prefix} {suffix}",
        "username": f"rep_{prefix}_{suffix}", "phone_number": "+962790001234",
        "password": password, "can_allow_debt": False, "max_debt_limit": "0.000",
    }


async def create_rep(gate, index, payload):
    r = await gate.client.post("/representatives", json=payload, headers=headers(gate, index))
    assert r.status_code == 201, r.text
    return r.json()


async def state(gate, company_id, representative_id):
    async with AsyncSession(gate.admin) as db:
        row = (await db.execute(
            select(FieldRepresentative, CompanyPrincipal, Driver)
            .join(CompanyPrincipal, (CompanyPrincipal.company_id == FieldRepresentative.company_id) & (CompanyPrincipal.id == FieldRepresentative.principal_id))
            .join(IdentityLegacyDriverMap, (IdentityLegacyDriverMap.company_id == FieldRepresentative.company_id) & (IdentityLegacyDriverMap.field_representative_id == FieldRepresentative.id))
            .join(Driver, (Driver.company_id == IdentityLegacyDriverMap.company_id) & (Driver.id == IdentityLegacyDriverMap.legacy_driver_id))
            .where(FieldRepresentative.company_id == company_id, FieldRepresentative.id == representative_id)
        )).one()
        profile, principal, driver = row
        return SimpleNamespace(
            principal_id=principal.id, active=principal.is_active, revision=principal.auth_revision,
            password_hash=principal.password_hash, driver_hash=driver.password_hash, full_name=principal.full_name,
        )


async def audit_rows(gate, company_id, representative_id):
    async with AsyncSession(gate.admin) as db:
        return list((await db.scalars(select(SystemAuditLog).where(
            SystemAuditLog.company_id == company_id,
            SystemAuditLog.target_id == f"FieldRepresentative_{representative_id}",
        ).order_by(SystemAuditLog.id))).all())


async def idem_rows(gate, company_id, request_ids):
    async with AsyncSession(gate.admin) as db:
        return list((await db.scalars(select(OperationIdempotency).where(
            OperationIdempotency.company_id == company_id,
            OperationIdempotency.request_id.in_(tuple(request_ids)),
        ))).all())


async def seed_refresh(gate, company_id, representative_id, token):
    current = await state(gate, company_id, representative_id)
    async with AsyncSession(gate.admin, expire_on_commit=False) as db:
        row = PrincipalRefreshToken(
            company_id=company_id, principal_id=current.principal_id, channel="FIELD", token=token,
            expires_at=utc_now() + timedelta(days=1), is_revoked=False, auth_revision=current.revision,
        )
        db.add(row)
        await db.commit(); await db.refresh(row)
        return row.id


@pytest.mark.asyncio
async def test_success_replay_redaction_actor_and_tenant_isolation(gate):
    company, owner = gate.companies[0], gate.owners[0]
    ids = {}

    ids["create"] = str(uuid4()); create = create_payload("main", ids["create"])
    rep = await create_rep(gate, 0, create); rep_id = rep["id"]
    assert (await gate.client.post("/representatives", json=create, headers=headers(gate))).json() == rep
    created_state = await state(gate, company.id, rep_id)

    ids["update"] = str(uuid4()); update = {"request_id": ids["update"], "full_name": "Updated Representative", "can_allow_debt": True, "max_debt_limit": "25.500"}
    first = await gate.client.patch(f"/representatives/{rep_id}", json=update, headers=headers(gate))
    second = await gate.client.patch(f"/representatives/{rep_id}", json=update, headers=headers(gate))
    assert first.status_code == second.status_code == 200 and first.json() == second.json()

    for op in ("deactivate", "reactivate"):
        ids[op] = str(uuid4())
        for _ in range(2):
            r = await gate.client.post(f"/representatives/{rep_id}/{op}", json={"request_id": ids[op]}, headers=headers(gate))
            assert r.status_code == 204

    before_reset = await state(gate, company.id, rep_id)
    refresh_token = "refresh-" + uuid4().hex
    refresh_id = await seed_refresh(gate, company.id, rep_id, refresh_token)
    ids["reset"] = str(uuid4()); reset = {"request_id": ids["reset"], "new_password": RESET_PASSWORD}
    for _ in range(2):
        r = await gate.client.post(f"/representatives/{rep_id}/credentials/reset", json=reset, headers=headers(gate))
        assert r.status_code == 204
    after_reset = await state(gate, company.id, rep_id)

    async with AsyncSession(gate.admin) as db:
        assert await db.scalar(select(PrincipalRefreshToken.is_revoked).where(PrincipalRefreshToken.id == refresh_id)) is True
        mapping = await db.scalar(select(IdentityLegacyDriverMap).where(
            IdentityLegacyDriverMap.company_id == company.id,
            IdentityLegacyDriverMap.backoffice_principal_id == owner.context.principal_id,
            IdentityLegacyDriverMap.backoffice_user_id == owner.context.backoffice_user_id,
        ))
        assert mapping is not None and mapping.legacy_driver_id == owner.driver_id

    rows = await audit_rows(gate, company.id, rep_id)
    assert [r.action_type for r in rows] == ACTIONS
    assert all(r.company_id == company.id and r.admin_id == owner.driver_id for r in rows)
    assert all(r.target_id == f"FieldRepresentative_{rep_id}" for r in rows)
    assert set(json.loads(rows[0].new_value)) == PUBLIC_KEYS
    before, after = json.loads(rows[1].old_value), json.loads(rows[1].new_value)
    assert set(before) == set(after) == PUBLIC_KEYS and after["full_name"] == update["full_name"]
    assert not ({"principal_id", "legacy_driver_id", "company_id", "auth_revision", "password", "password_hash"} & set(after))
    d0, d1 = json.loads(rows[2].old_value), json.loads(rows[2].new_value)
    assert d0["is_active"] is True and d1["is_active"] is False and d1["auth_revision"] == d0["auth_revision"] + 1
    r0, r1 = json.loads(rows[3].old_value), json.loads(rows[3].new_value)
    assert r0["is_active"] is False and r1["is_active"] is True and r1["auth_revision"] == r0["auth_revision"]
    c0, c1 = json.loads(rows[4].old_value), json.loads(rows[4].new_value)
    assert set(c0) == {"auth_revision"} and set(c1) == {"auth_revision", "refresh_sessions_revoked", "request_id"}
    assert c1["auth_revision"] == c0["auth_revision"] + 1 and c1["refresh_sessions_revoked"] == 1
    assert after_reset.revision == before_reset.revision + 1 and after_reset.password_hash != before_reset.password_hash

    idem = await idem_rows(gate, company.id, set(ids.values()))
    assert len(idem) == 5 and {r.operation for r in idem} == OPERATIONS
    assert all(r.created_by == owner.driver_id and len(r.request_hash) == 64 and r.completed_at is not None for r in idem)
    evidence = json.dumps([(r.old_value, r.new_value) for r in rows] + [(r.request_hash, r.response_json) for r in idem])
    for secret in (
        CREATE_PASSWORD, RESET_PASSWORD, created_state.password_hash, created_state.driver_hash,
        after_reset.password_hash, fingerprint_initial_password(CREATE_PASSWORD),
        fingerprint_reset_password(RESET_PASSWORD), refresh_token, gate.tokens[0],
    ):
        assert secret not in evidence

    foreign = await create_rep(gate, 1, create_payload("foreign")); foreign_id = foreign["id"]
    cross_id = str(uuid4())
    denied = await gate.client.patch(f"/representatives/{foreign_id}", json={"request_id": cross_id, "full_name": "Denied"}, headers=headers(gate))
    assert denied.status_code == 404
    assert await audit_rows(gate, company.id, foreign_id) == []
    assert len(await audit_rows(gate, gate.companies[1].id, foreign_id)) == 1
    assert await idem_rows(gate, company.id, {cross_id}) == []


@pytest.mark.asyncio
async def test_audit_insert_failure_rolls_back_mutations(gate):
    company = gate.companies[0]
    active = await create_rep(gate, 0, create_payload("atomic-a")); active_id = active["id"]
    inactive = await create_rep(gate, 0, create_payload("atomic-i")); inactive_id = inactive["id"]
    assert (await gate.client.post(f"/representatives/{inactive_id}/deactivate", json={"request_id": str(uuid4())}, headers=headers(gate))).status_code == 204
    active_before = await state(gate, company.id, active_id); inactive_before = await state(gate, company.id, inactive_id)
    refresh_id = await seed_refresh(gate, company.id, active_id, "refresh-" + uuid4().hex)

    async with gate.admin.begin() as conn:
        await conn.execute(text("""
            CREATE FUNCTION test_rep_audit_fail() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.action_type LIKE 'REPRESENTATIVE_%' THEN RAISE EXCEPTION 'audit rejected'; END IF; RETURN NEW; END; $$
        """))
        await conn.execute(text("""
            CREATE TRIGGER test_rep_audit_fail BEFORE INSERT ON system_audit_logs
            FOR EACH ROW EXECUTE FUNCTION test_rep_audit_fail()
        """))
    requests = []
    try:
        create_id = str(uuid4()); requests.append(create_id); failed_create = create_payload("fail", create_id, "FailCreate-" + uuid4().hex)
        assert (await gate.client.post("/representatives", json=failed_create, headers=headers(gate))).status_code == 500
        async with AsyncSession(gate.admin) as db:
            assert await db.scalar(select(CompanyPrincipal.id).where(CompanyPrincipal.company_id == company.id, CompanyPrincipal.username == failed_create["username"])) is None

        update_id = str(uuid4()); requests.append(update_id)
        assert (await gate.client.patch(f"/representatives/{active_id}", json={"request_id": update_id, "full_name": "Rollback"}, headers=headers(gate))).status_code == 500
        assert (await state(gate, company.id, active_id)).full_name == active_before.full_name

        deactivate_id = str(uuid4()); requests.append(deactivate_id)
        assert (await gate.client.post(f"/representatives/{active_id}/deactivate", json={"request_id": deactivate_id}, headers=headers(gate))).status_code == 500
        failed = await state(gate, company.id, active_id); assert failed.active is True and failed.revision == active_before.revision

        reactivate_id = str(uuid4()); requests.append(reactivate_id)
        assert (await gate.client.post(f"/representatives/{inactive_id}/reactivate", json={"request_id": reactivate_id}, headers=headers(gate))).status_code == 500
        failed = await state(gate, company.id, inactive_id); assert failed.active is False and failed.revision == inactive_before.revision

        reset_id = str(uuid4()); requests.append(reset_id)
        assert (await gate.client.post(f"/representatives/{active_id}/credentials/reset", json={"request_id": reset_id, "new_password": "FailReset-" + uuid4().hex}, headers=headers(gate))).status_code == 500
        failed = await state(gate, company.id, active_id); assert failed.password_hash == active_before.password_hash and failed.revision == active_before.revision
        async with AsyncSession(gate.admin) as db:
            assert await db.scalar(select(PrincipalRefreshToken.is_revoked).where(PrincipalRefreshToken.id == refresh_id)) is False
            count = await db.scalar(select(func.count()).select_from(OperationIdempotency).where(OperationIdempotency.request_id.in_(tuple(requests))))
            assert int(count or 0) == 0
    finally:
        async with gate.admin.begin() as conn:
            await conn.execute(text("DROP TRIGGER IF EXISTS test_rep_audit_fail ON system_audit_logs"))
            await conn.execute(text("DROP FUNCTION IF EXISTS test_rep_audit_fail()"))
