"""Migrated PostgreSQL acceptance for Representative audit/evidence security."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException

from api.auth import router as auth_router
from api.representatives import router as representatives_router
from database import engine as runtime_engine, get_db
from domains.auth_sessions.models import PrincipalRefreshToken
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.representatives.credentials import (
    fingerprint_initial_password,
    fingerprint_reset_password,
)
from main import (
    WanasahRawASGIMiddleware,
    custom_http_exception_handler,
    global_exception_handler,
    validation_exception_handler,
)
from models import (
    Company,
    DomainAuditEvent,
    Driver,
    OperationIdempotency,
    SystemAuditLog,
    TransactionalOutbox,
    utc_now,
)
from observability.http_errors import shutdown_http_error_logging
from tests.canonical_actor_fixtures import seed_company_owner_fixture

pytestmark = pytest.mark.skipif(
    os.getenv("WANASAH_REPRESENTATIVES_AUDIT_DB_GATE") != "1",
    reason="isolated Representative audit/security PostgreSQL gate only",
)

OWNER_PASSWORD = "RepresentativeAuditOwner123"
CREATE_PASSWORD = "RepresentativeCreateSecret123"
RESET_PASSWORD = "RepresentativeResetSecret456"
FIELD_REFRESH_TOKEN = "field-refresh-secret-representative-audit-gate"
PUBLIC_KEYS = {
    "id",
    "full_name",
    "username",
    "phone_number",
    "is_active",
    "can_allow_debt",
    "max_debt_limit",
}
REPRESENTATIVE_OPERATIONS = {
    "REPRESENTATIVE_CREATE",
    "REPRESENTATIVE_UPDATE",
    "REPRESENTATIVE_DEACTIVATE",
    "REPRESENTATIVE_REACTIVATE",
    "REPRESENTATIVE_CREDENTIAL_RESET",
}
REPRESENTATIVE_ACTIONS = [
    "REPRESENTATIVE_CREATED",
    "REPRESENTATIVE_UPDATED",
    "REPRESENTATIVE_DEACTIVATED",
    "REPRESENTATIVE_REACTIVATED",
    "REPRESENTATIVE_CREDENTIALS_RESET",
]


@pytest_asyncio.fixture(scope="module")
async def gate():
    admin_url = os.environ["DATABASE_URL_MIGRATION"]
    runtime_url = os.environ["DATABASE_URL"]
    assert make_url(admin_url).database == "representatives_audit_gate"
    assert make_url(runtime_url).database == "representatives_audit_gate"
    assert make_url(str(runtime_engine.url)).database == "representatives_audit_gate"

    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
        companies = [
            Company(name="Representative Audit A", company_code="RAA"),
            Company(name="Representative Audit B", company_code="RAB"),
        ]
        seed.add_all(companies)
        await seed.flush()
        owners = [
            await seed_company_owner_fixture(seed, company.id, password=OWNER_PASSWORD)
            for company in companies
        ]
        owner_usernames = [
            await seed.scalar(
                select(CompanyPrincipal.username).where(
                    CompanyPrincipal.id == owner.context.principal_id
                )
            )
            for owner in owners
        ]
        await seed.commit()

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

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://representative-audit-gate",
    ) as client:
        owner_tokens: list[str] = []
        for company, username in zip(companies, owner_usernames):
            response = await client.post(
                "/login",
                json={
                    "company_code": company.company_code,
                    "username": username,
                    "password": OWNER_PASSWORD,
                },
            )
            assert response.status_code == 200, response.text
            owner_tokens.append(response.json()["token"])

        yield SimpleNamespace(
            client=client,
            companies=companies,
            owners=owners,
            owner_tokens=owner_tokens,
            admin_engine=admin_engine,
        )

    shutdown_http_error_logging()
    await runtime_engine.dispose()
    await admin_engine.dispose()


def auth(gate, company_index: int = 0) -> dict[str, str]:
    return {"Authorization": f"Bearer {gate.owner_tokens[company_index]}"}


def create_body(
    prefix: str,
    *,
    request_id: str | None = None,
    password: str = CREATE_PASSWORD,
) -> dict[str, object]:
    suffix = uuid4().hex[:10]
    return {
        "request_id": request_id or str(uuid4()),
        "full_name": f"Audit Representative {prefix} {suffix}",
        "username": f"audit_{prefix}_{suffix}",
        "phone_number": "+962790001234",
        "password": password,
        "can_allow_debt": False,
        "max_debt_limit": "0.000",
    }


async def create_rep(gate, company_index: int, body: dict[str, object]):
    response = await gate.client.post(
        "/representatives", json=body, headers=auth(gate, company_index)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def target_state(gate, company_id: int, representative_id: int):
    async with AsyncSession(gate.admin_engine, expire_on_commit=False) as db:
        row = (
            await db.execute(
                select(
                    FieldRepresentative,
                    CompanyPrincipal,
                    IdentityLegacyDriverMap,
                    Driver,
                )
                .join(
                    CompanyPrincipal,
                    (CompanyPrincipal.company_id == FieldRepresentative.company_id)
                    & (CompanyPrincipal.id == FieldRepresentative.principal_id),
                )
                .join(
                    IdentityLegacyDriverMap,
                    (IdentityLegacyDriverMap.company_id == FieldRepresentative.company_id)
                    & (
                        IdentityLegacyDriverMap.field_representative_id
                        == FieldRepresentative.id
                    )
                    & (
                        IdentityLegacyDriverMap.field_principal_id
                        == CompanyPrincipal.id
                    ),
                )
                .join(
                    Driver,
                    (Driver.company_id == IdentityLegacyDriverMap.company_id)
                    & (Driver.id == IdentityLegacyDriverMap.legacy_driver_id),
                )
                .where(
                    FieldRepresentative.company_id == company_id,
                    FieldRepresentative.id == representative_id,
                )
            )
        ).one_or_none()
        assert row is not None
        profile, principal, bridge, driver = row
        return SimpleNamespace(
            profile_id=int(profile.id),
            principal_id=int(principal.id),
            legacy_driver_id=int(driver.id),
            principal_active=bool(principal.is_active),
            principal_revision=int(principal.auth_revision),
            principal_password_hash=str(principal.password_hash),
            driver_password_hash=str(driver.password_hash),
            full_name=str(principal.full_name),
            username=str(principal.username),
            bridge=bridge,
        )


async def audit_rows(gate, company_id: int, representative_id: int):
    async with AsyncSession(gate.admin_engine) as db:
        return list(
            (
                await db.scalars(
                    select(SystemAuditLog)
                    .where(
                        SystemAuditLog.company_id == company_id,
                        SystemAuditLog.target_id
                        == f"FieldRepresentative_{representative_id}",
                    )
                    .order_by(SystemAuditLog.id.asc())
                )
            ).all()
        )


async def idempotency_rows(gate, company_id: int, request_ids: set[str]):
    async with AsyncSession(gate.admin_engine) as db:
        return list(
            (
                await db.scalars(
                    select(OperationIdempotency)
                    .where(
                        OperationIdempotency.company_id == company_id,
                        OperationIdempotency.request_id.in_(tuple(sorted(request_ids))),
                    )
                    .order_by(OperationIdempotency.id.asc())
                )
            ).all()
        )


def json_value(value: str | None):
    return None if value is None else json.loads(value)


def evidence_blob(audits, idempotency) -> str:
    payload: list[object] = []
    for row in audits:
        payload.extend(
            [
                row.company_id,
                row.admin_id,
                row.target_id,
                row.action_type,
                row.old_value,
                row.new_value,
            ]
        )
    for row in idempotency:
        payload.extend(
            [
                row.company_id,
                row.created_by,
                row.operation,
                row.request_id,
                row.request_hash,
                row.response_json,
            ]
        )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


async def assert_no_idempotency(gate, company_id: int, request_id: str) -> None:
    async with AsyncSession(gate.admin_engine) as db:
        count = int(
            await db.scalar(
                select(func.count())
                .select_from(OperationIdempotency)
                .where(
                    OperationIdempotency.company_id == company_id,
                    OperationIdempotency.request_id == request_id,
                )
            )
            or 0
        )
        assert count == 0


async def seed_field_refresh(gate, *, company_id: int, representative_id: int, token: str):
    state = await target_state(gate, company_id, representative_id)
    async with AsyncSession(gate.admin_engine, expire_on_commit=False) as db:
        row = PrincipalRefreshToken(
            company_id=company_id,
            principal_id=state.principal_id,
            channel="FIELD",
            token=token,
            expires_at=utc_now() + timedelta(days=1),
            is_revoked=False,
            auth_revision=state.principal_revision,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return int(row.id)


async def refresh_revoked(gate, refresh_id: int) -> bool:
    async with AsyncSession(gate.admin_engine) as db:
        value = await db.scalar(
            select(PrincipalRefreshToken.is_revoked).where(
                PrincipalRefreshToken.id == refresh_id
            )
        )
        assert value is not None
        return bool(value)


async def install_audit_failure_trigger(gate) -> None:
    async with gate.admin_engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION test_representative_audit_reject()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    IF NEW.action_type LIKE 'REPRESENTATIVE_%' THEN
                        RAISE EXCEPTION 'representative audit gate rejection';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TRIGGER test_representative_audit_reject_trigger
                BEFORE INSERT ON system_audit_logs
                FOR EACH ROW EXECUTE FUNCTION test_representative_audit_reject()
                """
            )
        )


async def remove_audit_failure_trigger(gate) -> None:
    async with gate.admin_engine.begin() as conn:
        await conn.execute(
            text(
                "DROP TRIGGER IF EXISTS test_representative_audit_reject_trigger "
                "ON system_audit_logs"
            )
        )
        await conn.execute(
            text("DROP FUNCTION IF EXISTS test_representative_audit_reject()")
        )


@pytest.mark.asyncio
async def test_all_mutations_audit_once_replay_redacts_and_stays_tenant_scoped(gate):
    company = gate.companies[0]
    owner = gate.owners[0]

    create_request = str(uuid4())
    create = create_body("primary", request_id=create_request)
    created = await create_rep(gate, 0, create)
    replay = await gate.client.post("/representatives", json=create, headers=auth(gate))
    assert replay.status_code == 201 and replay.json() == created
    representative_id = int(created["id"])

    update_request = str(uuid4())
    update = {
        "request_id": update_request,
        "full_name": "Representative Audit Updated",
        "phone_number": "+962790009999",
        "can_allow_debt": True,
        "max_debt_limit": "25.500",
    }
    updated = await gate.client.patch(
        f"/representatives/{representative_id}", json=update, headers=auth(gate)
    )
    assert updated.status_code == 200, updated.text
    replay = await gate.client.patch(
        f"/representatives/{representative_id}", json=update, headers=auth(gate)
    )
    assert replay.status_code == 200 and replay.json() == updated.json()

    deactivate_request = str(uuid4())
    lifecycle_body = {"request_id": deactivate_request}
    first = await gate.client.post(
        f"/representatives/{representative_id}/deactivate",
        json=lifecycle_body,
        headers=auth(gate),
    )
    second = await gate.client.post(
        f"/representatives/{representative_id}/deactivate",
        json=lifecycle_body,
        headers=auth(gate),
    )
    assert first.status_code == second.status_code == 204

    reactivate_request = str(uuid4())
    lifecycle_body = {"request_id": reactivate_request}
    first = await gate.client.post(
        f"/representatives/{representative_id}/reactivate",
        json=lifecycle_body,
        headers=auth(gate),
    )
    second = await gate.client.post(
        f"/representatives/{representative_id}/reactivate",
        json=lifecycle_body,
        headers=auth(gate),
    )
    assert first.status_code == second.status_code == 204

    state_before_reset = await target_state(gate, company.id, representative_id)
    refresh_id = await seed_field_refresh(
        gate,
        company_id=company.id,
        representative_id=representative_id,
        token=FIELD_REFRESH_TOKEN,
    )
    reset_request = str(uuid4())
    reset = {"request_id": reset_request, "new_password": RESET_PASSWORD}
    first = await gate.client.post(
        f"/representatives/{representative_id}/credentials/reset",
        json=reset,
        headers=auth(gate),
    )
    second = await gate.client.post(
        f"/representatives/{representative_id}/credentials/reset",
        json=reset,
        headers=auth(gate),
    )
    assert first.status_code == second.status_code == 204
    state_after_reset = await target_state(gate, company.id, representative_id)
    assert state_after_reset.principal_revision == state_before_reset.principal_revision + 1
    assert state_after_reset.principal_password_hash != state_before_reset.principal_password_hash
    assert state_after_reset.driver_password_hash == state_before_reset.driver_password_hash
    assert await refresh_revoked(gate, refresh_id) is True

    audits = await audit_rows(gate, company.id, representative_id)
    assert [row.action_type for row in audits] == REPRESENTATIVE_ACTIONS
    assert all(row.company_id == company.id for row in audits)
    assert all(row.admin_id == owner.driver_id for row in audits)
    assert all(row.target_id == f"FieldRepresentative_{representative_id}" for row in audits)

    # The persisted audit actor is the existing Driver FK, but it is the exact
    # operational locator of the canonical Dashboard principal/profile actor.
    async with AsyncSession(gate.admin_engine) as db:
        actor_map = await db.scalar(
            select(IdentityLegacyDriverMap).where(
                IdentityLegacyDriverMap.company_id == company.id,
                IdentityLegacyDriverMap.backoffice_principal_id
                == owner.context.principal_id,
                IdentityLegacyDriverMap.backoffice_user_id
                == owner.context.backoffice_user_id,
            )
        )
        assert actor_map is not None
        assert int(actor_map.legacy_driver_id) == owner.driver_id

    created_audit, updated_audit, deactivated_audit, reactivated_audit, reset_audit = audits
    assert created_audit.old_value is None
    assert set(json_value(created_audit.new_value)) == PUBLIC_KEYS

    update_before = json_value(updated_audit.old_value)
    update_after = json_value(updated_audit.new_value)
    assert set(update_before) == set(update_after) == PUBLIC_KEYS
    assert update_before["full_name"] != update_after["full_name"]
    assert update_after["full_name"] == update["full_name"]
    for forbidden in (
        "principal_id",
        "legacy_driver_id",
        "password",
        "password_hash",
        "auth_revision",
        "company_id",
    ):
        assert forbidden not in update_before
        assert forbidden not in update_after

    deactivated_before = json_value(deactivated_audit.old_value)
    deactivated_after = json_value(deactivated_audit.new_value)
    assert deactivated_before["is_active"] is True
    assert deactivated_after["is_active"] is False
    assert deactivated_after["request_id"] == deactivate_request
    assert deactivated_after["auth_revision"] == deactivated_before["auth_revision"] + 1

    reactivated_before = json_value(reactivated_audit.old_value)
    reactivated_after = json_value(reactivated_audit.new_value)
    assert reactivated_before["is_active"] is False
    assert reactivated_after["is_active"] is True
    assert reactivated_after["request_id"] == reactivate_request
    assert reactivated_after["auth_revision"] == reactivated_before["auth_revision"]

    reset_before = json_value(reset_audit.old_value)
    reset_after = json_value(reset_audit.new_value)
    assert set(reset_before) == {"auth_revision"}
    assert set(reset_after) == {
        "auth_revision",
        "refresh_sessions_revoked",
        "request_id",
    }
    assert reset_after["request_id"] == reset_request
    assert reset_after["auth_revision"] == reset_before["auth_revision"] + 1
    assert reset_after["refresh_sessions_revoked"] == 1

    request_ids = {
        create_request,
        update_request,
        deactivate_request,
        reactivate_request,
        reset_request,
    }
    idempotency = await idempotency_rows(gate, company.id, request_ids)
    assert len(idempotency) == 5
    assert {row.operation for row in idempotency} == REPRESENTATIVE_OPERATIONS
    assert {row.request_id for row in idempotency} == request_ids
    assert all(row.created_by == owner.driver_id for row in idempotency)
    assert all(row.completed_at is not None and row.response_json is not None for row in idempotency)
    assert all(len(row.request_hash) == 64 for row in idempotency)

    initial_fingerprint = fingerprint_initial_password(CREATE_PASSWORD)
    reset_fingerprint = fingerprint_reset_password(RESET_PASSWORD)
    evidence = evidence_blob(audits, idempotency)
    for secret in (
        CREATE_PASSWORD,
        RESET_PASSWORD,
        state_before_reset.principal_password_hash,
        state_after_reset.principal_password_hash,
        state_after_reset.driver_password_hash,
        initial_fingerprint,
        reset_fingerprint,
        FIELD_REFRESH_TOKEN,
        gate.owner_tokens[0],
    ):
        assert secret not in evidence
    assert "$2" not in evidence

    # Representative mutations do not currently use structured domain-event/outbox
    # evidence; prove the runtime did not create an accidental parallel secret surface.
    async with AsyncSession(gate.admin_engine) as db:
        domain_count = int(
            await db.scalar(
                select(func.count())
                .select_from(DomainAuditEvent)
                .where(DomainAuditEvent.event_type.like("REPRESENTATIVE%"))
            )
            or 0
        )
        outbox_count = int(
            await db.scalar(
                select(func.count())
                .select_from(TransactionalOutbox)
                .where(TransactionalOutbox.event_type.like("REPRESENTATIVE%"))
            )
            or 0
        )
        assert domain_count == outbox_count == 0

    # Tenant B has independent evidence and actor provenance.
    foreign_body = create_body("foreign")
    foreign = await create_rep(gate, 1, foreign_body)
    foreign_audits = await audit_rows(gate, gate.companies[1].id, int(foreign["id"]))
    assert len(foreign_audits) == 1
    assert foreign_audits[0].company_id == gate.companies[1].id
    assert foreign_audits[0].admin_id == gate.owners[1].driver_id

    cross_request = str(uuid4())
    denied = await gate.client.patch(
        f"/representatives/{foreign['id']}",
        json={"request_id": cross_request, "full_name": "Cross tenant denied"},
        headers=auth(gate, 0),
    )
    assert denied.status_code == 404, denied.text
    await assert_no_idempotency(gate, company.id, cross_request)
    assert await audit_rows(gate, company.id, int(foreign["id"])) == []
    assert len(await audit_rows(gate, gate.companies[1].id, int(foreign["id"]))) == 1


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_every_representative_mutation_and_logs_no_secret(gate):
    company = gate.companies[0]

    active_body = create_body("atomic-active")
    active = await create_rep(gate, 0, active_body)
    active_id = int(active["id"])

    inactive_body = create_body("atomic-inactive")
    inactive = await create_rep(gate, 0, inactive_body)
    inactive_id = int(inactive["id"])
    setup_deactivate = await gate.client.post(
        f"/representatives/{inactive_id}/deactivate",
        json={"request_id": str(uuid4())},
        headers=auth(gate),
    )
    assert setup_deactivate.status_code == 204

    active_before = await target_state(gate, company.id, active_id)
    inactive_before = await target_state(gate, company.id, inactive_id)
    assert active_before.principal_active is True
    assert inactive_before.principal_active is False

    atomic_refresh_token = "atomic-refresh-secret-representative-audit-gate"
    refresh_id = await seed_field_refresh(
        gate,
        company_id=company.id,
        representative_id=active_id,
        token=atomic_refresh_token,
    )

    log_path = Path(os.environ.get("WANASAH_ERROR_LOG_PATH", "/tmp/representatives-audit-security.log"))
    shutdown_http_error_logging()
    log_path.unlink(missing_ok=True)

    failed_request_ids: list[str] = []
    failed_create_password = "AtomicCreateSecret789"
    failed_reset_password = "AtomicResetSecret987"
    try:
        await install_audit_failure_trigger(gate)

        create_request = str(uuid4())
        failed_request_ids.append(create_request)
        failed_create = create_body(
            "atomic-failed-create",
            request_id=create_request,
            password=failed_create_password,
        )
        response = await gate.client.post(
            "/representatives", json=failed_create, headers=auth(gate)
        )
        assert response.status_code == 500, response.text
        async with AsyncSession(gate.admin_engine) as db:
            assert (
                await db.scalar(
                    select(CompanyPrincipal.id).where(
                        CompanyPrincipal.company_id == company.id,
                        CompanyPrincipal.username == failed_create["username"],
                    )
                )
                is None
            )
            assert (
                await db.scalar(
                    select(Driver.id).where(
                        Driver.company_id == company.id,
                        Driver.username == failed_create["username"],
                    )
                )
                is None
            )
        await assert_no_idempotency(gate, company.id, create_request)

        update_request = str(uuid4())
        failed_request_ids.append(update_request)
        response = await gate.client.patch(
            f"/representatives/{active_id}",
            json={"request_id": update_request, "full_name": "Must Roll Back"},
            headers=auth(gate),
        )
        assert response.status_code == 500, response.text
        after_failed_update = await target_state(gate, company.id, active_id)
        assert after_failed_update.full_name == active_before.full_name
        await assert_no_idempotency(gate, company.id, update_request)

        deactivate_request = str(uuid4())
        failed_request_ids.append(deactivate_request)
        response = await gate.client.post(
            f"/representatives/{active_id}/deactivate",
            json={"request_id": deactivate_request},
            headers=auth(gate),
        )
        assert response.status_code == 500, response.text
        after_failed_deactivate = await target_state(gate, company.id, active_id)
        assert after_failed_deactivate.principal_active is True
        assert after_failed_deactivate.principal_revision == active_before.principal_revision
        await assert_no_idempotency(gate, company.id, deactivate_request)

        reactivate_request = str(uuid4())
        failed_request_ids.append(reactivate_request)
        response = await gate.client.post(
            f"/representatives/{inactive_id}/reactivate",
            json={"request_id": reactivate_request},
            headers=auth(gate),
        )
        assert response.status_code == 500, response.text
        after_failed_reactivate = await target_state(gate, company.id, inactive_id)
        assert after_failed_reactivate.principal_active is False
        assert after_failed_reactivate.principal_revision == inactive_before.principal_revision
        await assert_no_idempotency(gate, company.id, reactivate_request)

        reset_request = str(uuid4())
        failed_request_ids.append(reset_request)
        response = await gate.client.post(
            f"/representatives/{active_id}/credentials/reset",
            json={"request_id": reset_request, "new_password": failed_reset_password},
            headers=auth(gate),
        )
        assert response.status_code == 500, response.text
        after_failed_reset = await target_state(gate, company.id, active_id)
        assert after_failed_reset.principal_password_hash == active_before.principal_password_hash
        assert after_failed_reset.principal_revision == active_before.principal_revision
        assert await refresh_revoked(gate, refresh_id) is False
        await assert_no_idempotency(gate, company.id, reset_request)
    finally:
        await remove_audit_failure_trigger(gate)

    shutdown_http_error_logging()
    assert log_path.exists()
    logged = log_path.read_text(encoding="utf-8")
    assert logged.count('"event":"http_server_error"') >= 5
    assert "representative audit gate rejection" in logged

    failed_create_fingerprint = fingerprint_initial_password(failed_create_password)
    failed_reset_fingerprint = fingerprint_reset_password(failed_reset_password)
    for secret in (
        failed_create_password,
        failed_reset_password,
        failed_create_fingerprint,
        failed_reset_fingerprint,
        active_before.principal_password_hash,
        active_before.driver_password_hash,
        atomic_refresh_token,
        gate.owner_tokens[0],
    ):
        assert secret not in logged
    assert "$2" not in logged

    # The failed business requests leave neither audit evidence nor durable
    # idempotency completion behind; the whole transaction rolled back.
    async with AsyncSession(gate.admin_engine) as db:
        failed_idem_count = int(
            await db.scalar(
                select(func.count())
                .select_from(OperationIdempotency)
                .where(OperationIdempotency.request_id.in_(tuple(failed_request_ids)))
            )
            or 0
        )
        assert failed_idem_count == 0


def test_representative_sources_do_not_add_parallel_event_or_request_body_logging_surfaces():
    backend = Path(__file__).resolve().parents[1]
    representative_files = list((backend / "domains" / "representatives").glob("*.py"))
    representative_files += list((backend / "api" / "representatives").glob("*.py"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in representative_files)

    assert "record_domain_event" not in combined
    assert "DomainAuditEvent" not in combined
    assert "TransactionalOutbox" not in combined
    assert "request.body" not in combined
    assert "logger." not in combined
    assert "logging." not in combined

    http_errors = (backend / "observability" / "http_errors.py").read_text(encoding="utf-8")
    main_source = (backend / "main.py").read_text(encoding="utf-8")
    assert "request.body" not in http_errors
    assert "request.body" not in main_source
    for marker in ("PASSWORD", "ACCESS_TOKEN", "REFRESH_TOKEN"):
        assert marker in http_errors
