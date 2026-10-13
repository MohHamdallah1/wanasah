"""Real PostgreSQL acceptance for the merged Representatives backend."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException

from api.auth import router as auth_router
from api.authentication.dependencies import get_current_field_context
from api.representatives import router as representatives_router
from config import Config
from database import get_db
from domains.auth_sessions.codec import issue_access_token
from domains.auth_sessions.context import FieldRequestContext
from domains.auth_sessions.models import PrincipalRefreshToken
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.identity.migration.models import IdentityLegacyDriverMap
from main import (
    WanasahRawASGIMiddleware,
    custom_http_exception_handler,
    validation_exception_handler,
)
from models import (
    Base,
    Company,
    DispatchRoute,
    Driver,
    InventoryLocation,
    InventoryTransferHeader,
    OperationIdempotency,
    StocktakeSession,
    SystemAuditLog,
    WorkSession,
    Zone,
    utc_now,
)
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_ordinary_backoffice_fixture,
)

pytestmark = pytest.mark.skipif(
    os.getenv("WANASAH_REPRESENTATIVES_DB_GATE") != "1",
    reason="Explicit isolated Representatives PostgreSQL gate only",
)

OWNER_PASSWORD = "RepresentativeOwnerGate123"
ORDINARY_PASSWORD = "RepresentativeOrdinaryGate123"
INITIAL_PASSWORD = "RepresentativeInitial123"
RESET_PASSWORD = "RepresentativeReset456"
PUBLIC_KEYS = {
    "id",
    "full_name",
    "username",
    "phone_number",
    "is_active",
    "can_allow_debt",
    "max_debt_limit",
}


@pytest_asyncio.fixture(scope="module")
async def gate():
    admin_url = os.environ["DATABASE_URL_MIGRATION"]
    assert make_url(admin_url).database == "representatives_gate"
    schema = "representatives_gate_" + uuid4().hex
    root_engine = create_async_engine(admin_url, poolclass=NullPool)
    async with root_engine.begin() as conn:
        for extension in ("btree_gist", "btree_gin", "pg_trgm"):
            await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
        await conn.execute(text(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='representatives_runtime') "
            "THEN CREATE ROLE representatives_runtime LOGIN; END IF; END $$"
        ))
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    settings = {"server_settings": {"search_path": f"{schema},public"}}
    admin_engine = create_async_engine(admin_url, poolclass=NullPool, connect_args=settings)
    async with admin_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO representatives_runtime'))
        await conn.execute(text(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" '
            "TO representatives_runtime"
        ))
        await conn.execute(text(
            f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" '
            "TO representatives_runtime"
        ))

    async with AsyncSession(admin_engine, expire_on_commit=False) as seed:
        companies = [
            Company(name="Representatives Gate One", company_code="RG1"),
            Company(name="Representatives Gate Two", company_code="RG2"),
        ]
        seed.add_all(companies)
        await seed.flush()
        owners = [
            await seed_company_owner_fixture(seed, company.id, password=OWNER_PASSWORD)
            for company in companies
        ]
        ordinary = await seed_ordinary_backoffice_fixture(
            seed, companies[0].id, password=ORDINARY_PASSWORD
        )
        zones = [Zone(company_id=c.id, name=f"Gate Zone {i}") for i, c in enumerate(companies, 1)]
        locations = []
        for i, company in enumerate(companies, 1):
            locations.extend([
                InventoryLocation(
                    company_id=company.id,
                    code=f"RG{i}-A",
                    name=f"Gate Warehouse {i}A",
                    location_type="WAREHOUSE",
                ),
                InventoryLocation(
                    company_id=company.id,
                    code=f"RG{i}-B",
                    name=f"Gate Warehouse {i}B",
                    location_type="WAREHOUSE",
                ),
            ])
        seed.add_all(zones + locations)
        await seed.flush()
        owner_usernames = [
            await seed.scalar(select(CompanyPrincipal.username).where(
                CompanyPrincipal.id == owner.context.principal_id
            ))
            for owner in owners
        ]
        await seed.commit()

    # Make auto-created canonical profile/principal/legacy Driver IDs provably independent.
    async with admin_engine.begin() as conn:
        for table, value in (
            ("company_principals", 10_000),
            ("field_representatives", 20_000),
            ("drivers", 30_000),
        ):
            await conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}','id'), {value}, true)"
            ))

    runtime_engine = create_async_engine(
        os.environ["DATABASE_URL"], poolclass=NullPool, connect_args=settings
    )

    async def runtime_db():
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            yield db

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(representatives_router)

    @app.get("/__field_probe")
    async def field_probe(current: FieldRequestContext = Depends(get_current_field_context)):
        return {
            "principal_id": current.principal_id,
            "representative_id": current.representative_id,
            "company_id": current.company_id,
            "auth_revision": current.auth_revision,
        }

    app.add_exception_handler(HTTPException, custom_http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_middleware(WanasahRawASGIMiddleware)
    app.dependency_overrides[get_db] = runtime_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://representatives-gate") as client:
        state = SimpleNamespace(
            client=client,
            engine=runtime_engine,
            admin_engine=admin_engine,
            companies=companies,
            owners=owners,
            ordinary=ordinary,
            owner_usernames=owner_usernames,
            zones=zones,
            locations=locations,
            schema=schema,
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

        # A no-grant Backoffice principal is rejected at Dashboard admission before
        # public login can issue a token. Mint the exact production token format so
        # the persisted canonical dependency and Representative capability denial
        # can be exercised without weakening the capability check itself.
        state.ordinary_token = issue_access_token(
            principal_id=ordinary.context.principal_id,
            company_id=ordinary.context.company_id,
            channel="DASHBOARD",
            principal_type="BACKOFFICE",
            auth_revision=ordinary.context.auth_revision,
            secret=Config.SECRET_KEY,
        )
        yield state

    await runtime_engine.dispose()
    await admin_engine.dispose()
    await root_engine.dispose()


def auth(gate, company_index=0):
    return {"Authorization": f"Bearer {gate.owner_tokens[company_index]}"}


def ordinary_auth(gate):
    return {"Authorization": f"Bearer {gate.ordinary_token}"}


def create_body(*, request_id=None, prefix="runtime"):
    suffix = uuid4().hex[:10]
    return {
        "request_id": str(request_id or uuid4()),
        "full_name": f"Runtime Representative {suffix}",
        "username": f"{prefix}_{suffix}",
        "phone_number": "+962790001234",
        "password": INITIAL_PASSWORD,
        "can_allow_debt": True,
        "max_debt_limit": "12.500",
    }


async def create_rep(gate, company_index=0, *, body=None):
    body = body or create_body()
    response = await gate.client.post(
        "/representatives", json=body, headers=auth(gate, company_index)
    )
    assert response.status_code == 201, response.text
    return response.json(), body


async def identity_state(gate, company_id, representative_id):
    async with AsyncSession(gate.engine, expire_on_commit=False) as db:
        profile = await db.scalar(select(FieldRepresentative).where(
            FieldRepresentative.company_id == company_id,
            FieldRepresentative.id == representative_id,
        ))
        assert profile is not None
        principal = await db.scalar(select(CompanyPrincipal).where(
            CompanyPrincipal.company_id == company_id,
            CompanyPrincipal.id == profile.principal_id,
        ))
        mapping = await db.scalar(select(IdentityLegacyDriverMap).where(
            IdentityLegacyDriverMap.company_id == company_id,
            IdentityLegacyDriverMap.field_representative_id == representative_id,
        ))
        assert principal is not None and mapping is not None
        driver = await db.scalar(select(Driver).where(
            Driver.company_id == company_id,
            Driver.id == mapping.legacy_driver_id,
        ))
        assert driver is not None
        return SimpleNamespace(
            profile_id=profile.id,
            principal_id=principal.id,
            driver_id=driver.id,
            mapping_key=(mapping.company_id, mapping.legacy_driver_id),
            classification=mapping.classification,
            company_ids=(profile.company_id, principal.company_id, mapping.company_id, driver.company_id),
            principal_active=principal.is_active,
            principal_revision=principal.auth_revision,
            principal_password_hash=principal.password_hash,
            driver_password_hash=driver.password_hash,
            principal_name=principal.full_name,
            principal_username=principal.username,
            principal_phone=principal.phone_number,
            driver_name=driver.full_name,
            driver_username=driver.username,
            driver_phone=driver.phone_number,
            profile_debt=profile.can_allow_debt,
            profile_limit=str(profile.max_debt_limit),
            driver_debt=driver.can_allow_debt,
            driver_limit=str(driver.max_debt_limit),
        )


async def row_count(gate, model, *, company_id=None):
    async with AsyncSession(gate.engine) as db:
        stmt = select(func.count()).select_from(model)
        if company_id is not None and hasattr(model, "company_id"):
            stmt = stmt.where(model.company_id == company_id)
        return int(await db.scalar(stmt) or 0)


async def field_login(gate, company_index, username, password):
    return await gate.client.post("/driver/login", json={
        "company_code": gate.companies[company_index].company_code,
        "username": username,
        "password": password,
    })


async def seed_reconciled_session(gate, *, company_index, driver_id, settled=False):
    company = gate.companies[company_index]
    owner_driver_id = gate.owners[company_index].driver_id
    now = utc_now()
    async with AsyncSession(gate.engine, expire_on_commit=False) as db:
        session = WorkSession(
            company_id=company.id,
            driver_id=driver_id,
            end_time=now,
            inventory_reconciled_at=now,
            inventory_reconciled_by=owner_driver_id,
            is_settled=settled,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session.id


@pytest.mark.asyncio
async def test_end_to_end_identity_session_and_http_contract(gate):
    company = gate.companies[0]
    before_counts = {
        model: await row_count(gate, model, company_id=company.id)
        for model in (CompanyPrincipal, FieldRepresentative, Driver, IdentityLegacyDriverMap)
    }
    row, _body = await create_rep(gate)
    assert set(row) == PUBLIC_KEYS
    first = await identity_state(gate, company.id, row["id"])
    assert len({first.profile_id, first.principal_id, first.driver_id}) == 3
    assert first.classification == "FIELD_ONLY"
    assert set(first.company_ids) == {company.id}
    for model in before_counts:
        assert await row_count(gate, model, company_id=company.id) == before_counts[model] + 1

    page = await gate.client.get("/representatives", headers=auth(gate))
    assert page.status_code == 200, page.text
    assert any(item["id"] == row["id"] for item in page.json()["items"])
    assert all(set(item) == PUBLIC_KEYS for item in page.json()["items"])
    detail = await gate.client.get(f"/representatives/{row['id']}", headers=auth(gate))
    assert detail.status_code == 200 and detail.json() == row

    patch = {
        "request_id": str(uuid4()),
        "full_name": "Runtime Representative Updated",
        "username": "runtime_updated_" + uuid4().hex[:8],
        "phone_number": "+962790009999",
        "can_allow_debt": False,
        "max_debt_limit": "3.750",
    }
    updated = await gate.client.patch(
        f"/representatives/{row['id']}", json=patch, headers=auth(gate)
    )
    assert updated.status_code == 200, updated.text
    state = await identity_state(gate, company.id, row["id"])
    assert state.principal_name == state.driver_name == patch["full_name"]
    assert state.principal_username == state.driver_username == patch["username"]
    assert state.principal_phone == state.driver_phone == patch["phone_number"]
    assert state.profile_debt is state.driver_debt is False
    assert state.profile_limit == state.driver_limit == "3.750"

    login = await field_login(gate, 0, patch["username"], INITIAL_PASSWORD)
    assert login.status_code == 200, login.text
    field_session = login.json()
    assert field_session["principal_id"] == state.principal_id
    assert field_session["representative_id"] == state.profile_id
    assert field_session["legacy_driver_id"] == field_session["driver_id"] == state.driver_id
    stale_access = field_session["token"]
    stale_refresh = field_session["refresh_token"]
    probe = await gate.client.get(
        "/__field_probe", headers={"Authorization": f"Bearer {stale_access}"}
    )
    assert probe.status_code == 200, probe.text
    async with AsyncSession(gate.engine) as db:
        refresh_row = await db.scalar(select(PrincipalRefreshToken).where(
            PrincipalRefreshToken.token == stale_refresh
        ))
        assert refresh_row is not None and not refresh_row.is_revoked

    ids_before_lifecycle = (
        state.profile_id, state.principal_id, state.driver_id, state.mapping_key
    )
    revision_before = state.principal_revision
    deactivated = await gate.client.post(
        f"/representatives/{row['id']}/deactivate",
        json={"request_id": str(uuid4())},
        headers=auth(gate),
    )
    assert deactivated.status_code == 204 and not deactivated.content
    inactive = await identity_state(gate, company.id, row["id"])
    assert not inactive.principal_active
    assert inactive.principal_revision == revision_before + 1
    assert (
        inactive.profile_id, inactive.principal_id, inactive.driver_id, inactive.mapping_key
    ) == ids_before_lifecycle
    assert (await gate.client.get(
        "/__field_probe", headers={"Authorization": f"Bearer {stale_access}"}
    )).status_code == 401
    refresh_attempt = await gate.client.post("/refresh", json={"refresh_token": stale_refresh})
    assert refresh_attempt.status_code in {401, 403}
    async with AsyncSession(gate.engine) as db:
        revoked = await db.scalar(select(PrincipalRefreshToken).where(
            PrincipalRefreshToken.token == stale_refresh
        ))
        assert revoked is not None and revoked.is_revoked

    reactivated = await gate.client.post(
        f"/representatives/{row['id']}/reactivate",
        json={"request_id": str(uuid4())},
        headers=auth(gate),
    )
    assert reactivated.status_code == 204 and not reactivated.content
    active_again = await identity_state(gate, company.id, row["id"])
    assert active_again.principal_active
    assert active_again.principal_revision == inactive.principal_revision
    assert (
        active_again.profile_id,
        active_again.principal_id,
        active_again.driver_id,
        active_again.mapping_key,
    ) == ids_before_lifecycle
    async with AsyncSession(gate.engine) as db:
        still_revoked = await db.scalar(select(PrincipalRefreshToken).where(
            PrincipalRefreshToken.token == stale_refresh
        ))
        assert still_revoked is not None and still_revoked.is_revoked

    current_login = await field_login(gate, 0, patch["username"], INITIAL_PASSWORD)
    assert current_login.status_code == 200, current_login.text
    current_access = current_login.json()["token"]
    current_refresh = current_login.json()["refresh_token"]
    before_reset = await identity_state(gate, company.id, row["id"])
    reset = await gate.client.post(
        f"/representatives/{row['id']}/credentials/reset",
        json={"request_id": str(uuid4()), "new_password": RESET_PASSWORD},
        headers=auth(gate),
    )
    assert reset.status_code == 204 and not reset.content
    after_reset = await identity_state(gate, company.id, row["id"])
    assert after_reset.principal_password_hash != before_reset.principal_password_hash
    assert after_reset.driver_password_hash == before_reset.driver_password_hash
    assert after_reset.principal_revision == before_reset.principal_revision + 1
    assert (await gate.client.get(
        "/__field_probe", headers={"Authorization": f"Bearer {current_access}"}
    )).status_code == 401
    async with AsyncSession(gate.engine) as db:
        current_refresh_row = await db.scalar(select(PrincipalRefreshToken).where(
            PrincipalRefreshToken.token == current_refresh
        ))
        assert current_refresh_row is not None and current_refresh_row.is_revoked
    assert (await field_login(gate, 0, patch["username"], INITIAL_PASSWORD)).status_code == 401
    assert (await field_login(gate, 0, patch["username"], RESET_PASSWORD)).status_code == 200

    assert (await gate.client.get("/representatives")).status_code == 401
    assert (await gate.client.get("/representatives", headers=ordinary_auth(gate))).status_code == 403
    assert (await gate.client.get("/representatives/999999999", headers=auth(gate))).status_code == 404
    malformed = await gate.client.post(
        "/representatives", json={"request_id": "not-a-uuid"}, headers=auth(gate)
    )
    assert malformed.status_code == 422
    assert (await gate.client.delete(f"/representatives/{row['id']}", headers=auth(gate))).status_code == 405


@pytest.mark.asyncio
async def test_real_database_idempotency_and_cross_company_scope(gate):
    request_id = uuid4()
    body = create_body(request_id=request_id, prefix="idemcreate")
    first, _ = await create_rep(gate, body=body)
    replay = await gate.client.post("/representatives", json=body, headers=auth(gate))
    assert replay.status_code == 201 and replay.json() == first
    mismatch = await gate.client.post(
        "/representatives",
        json={**body, "full_name": "Different payload"},
        headers=auth(gate),
    )
    assert mismatch.status_code == 409

    update_id = uuid4()
    patch = {"request_id": str(update_id), "full_name": "Idempotent Update"}
    changed = await gate.client.patch(
        f"/representatives/{first['id']}", json=patch, headers=auth(gate)
    )
    assert changed.status_code == 200, changed.text
    update_replay = await gate.client.patch(
        f"/representatives/{first['id']}", json=patch, headers=auth(gate)
    )
    assert update_replay.status_code == 200 and update_replay.json() == changed.json()

    cross_family_id = uuid4()
    family_row, _ = await create_rep(
        gate, body=create_body(request_id=cross_family_id, prefix="family")
    )
    cross_update = await gate.client.patch(
        f"/representatives/{family_row['id']}",
        json={"request_id": str(cross_family_id), "full_name": "Should conflict"},
        headers=auth(gate),
    )
    assert cross_update.status_code == 409

    deact_id = uuid4()
    target, _ = await create_rep(gate)
    first_deact = await gate.client.post(
        f"/representatives/{target['id']}/deactivate",
        json={"request_id": str(deact_id)}, headers=auth(gate)
    )
    replay_deact = await gate.client.post(
        f"/representatives/{target['id']}/deactivate",
        json={"request_id": str(deact_id)}, headers=auth(gate)
    )
    assert first_deact.status_code == replay_deact.status_code == 204

    reset_target, _ = await create_rep(gate)
    reset_id = uuid4()
    reset_body = {"request_id": str(reset_id), "new_password": "IdempotentReset789"}
    reset_first = await gate.client.post(
        f"/representatives/{reset_target['id']}/credentials/reset",
        json=reset_body, headers=auth(gate)
    )
    reset_replay = await gate.client.post(
        f"/representatives/{reset_target['id']}/credentials/reset",
        json=reset_body, headers=auth(gate)
    )
    assert reset_first.status_code == reset_replay.status_code == 204
    reset_to_create = await gate.client.post(
        "/representatives",
        json=create_body(request_id=reset_id, prefix="resetfamily"),
        headers=auth(gate),
    )
    assert reset_to_create.status_code == 409

    shared = uuid4()
    c1, _ = await create_rep(gate, 0, body=create_body(request_id=shared, prefix="tenant1"))
    c2, _ = await create_rep(gate, 1, body=create_body(request_id=shared, prefix="tenant2"))
    assert c1["id"] != c2["id"]
    assert (await gate.client.get(
        f"/representatives/{c2['id']}", headers=auth(gate, 0)
    )).status_code == 404

    async with AsyncSession(gate.engine) as db:
        create_rows = int(await db.scalar(select(func.count()).select_from(OperationIdempotency).where(
            OperationIdempotency.company_id == gate.companies[0].id,
            OperationIdempotency.request_id == str(request_id),
            OperationIdempotency.operation == "REPRESENTATIVE_CREATE",
        )) or 0)
        shared_rows = (await db.execute(select(
            OperationIdempotency.company_id,
            OperationIdempotency.operation,
        ).where(OperationIdempotency.request_id == str(shared)))).all()
    assert create_rows == 1
    assert {(r.company_id, r.operation) for r in shared_rows} == {
        (gate.companies[0].id, "REPRESENTATIVE_CREATE"),
        (gate.companies[1].id, "REPRESENTATIVE_CREATE"),
    }


async def assert_deactivate_blocked(gate, representative_id):
    before = await identity_state(gate, gate.companies[0].id, representative_id)
    response = await gate.client.post(
        f"/representatives/{representative_id}/deactivate",
        json={"request_id": str(uuid4())}, headers=auth(gate)
    )
    assert response.status_code == 409, response.text
    encoded = str(response.json()).lower()
    for forbidden in (
        "principal_id", "driver_id", "mapping", "session_id", "password", "hash", "token"
    ):
        assert forbidden not in encoded
    after = await identity_state(gate, gate.companies[0].id, representative_id)
    assert after.principal_active
    assert after.principal_revision == before.principal_revision


@pytest.mark.asyncio
async def test_database_backed_deactivation_blocker_matrix(gate):
    company = gate.companies[0]
    location = gate.locations[0]
    other_location = gate.locations[1]
    zone = gate.zones[0]
    owner_driver_id = gate.owners[0].driver_id

    rep, _ = await create_rep(gate)
    state = await identity_state(gate, company.id, rep["id"])
    async with AsyncSession(gate.engine) as db:
        db.add(WorkSession(company_id=company.id, driver_id=state.driver_id))
        await db.commit()
    await assert_deactivate_blocked(gate, rep["id"])

    for status in ("active", "waiting", "postponed"):
        rep, _ = await create_rep(gate)
        state = await identity_state(gate, company.id, rep["id"])
        async with AsyncSession(gate.engine) as db:
            db.add(DispatchRoute(
                company_id=company.id,
                zone_id=zone.id,
                driver_id=state.driver_id,
                source_location_id=location.id,
                status=status,
            ))
            await db.commit()
        await assert_deactivate_blocked(gate, rep["id"])

    rep, _ = await create_rep(gate)
    state = await identity_state(gate, company.id, rep["id"])
    async with AsyncSession(gate.engine) as db:
        db.add(WorkSession(
            company_id=company.id, driver_id=state.driver_id, end_time=utc_now()
        ))
        await db.commit()
    await assert_deactivate_blocked(gate, rep["id"])

    rep, _ = await create_rep(gate)
    state = await identity_state(gate, company.id, rep["id"])
    session_id = await seed_reconciled_session(
        gate, company_index=0, driver_id=state.driver_id, settled=False
    )
    async with AsyncSession(gate.engine) as db:
        db.add(InventoryTransferHeader(
            company_id=company.id,
            reference_number="HS-" + uuid4().hex.upper(),
            source_location_id=location.id,
            destination_location_id=other_location.id,
            workflow_type="HANDSHAKE",
            status="PENDING",
            transfer_purpose="ROUTE_RETURN",
            commercial_context={"schema_version": 1, "source": "representatives-runtime-gate"},
            dispatched_by=owner_driver_id,
            expected_receiver_id=state.driver_id,
            work_session_id=session_id,
        ))
        await db.commit()
    await assert_deactivate_blocked(gate, rep["id"])

    for status in ("DRAFT", "APPROVED"):
        rep, _ = await create_rep(gate)
        state = await identity_state(gate, company.id, rep["id"])
        session_id = await seed_reconciled_session(
            gate, company_index=0, driver_id=state.driver_id, settled=False
        )
        now = utc_now()
        kwargs = {}
        if status == "APPROVED":
            kwargs.update(snapshot_cutoff_at=now, approved_by=owner_driver_id, approved_at=now)
        async with AsyncSession(gate.engine) as db:
            db.add(StocktakeSession(
                company_id=company.id,
                location_id=location.id,
                reference_number=f"VR-{status}-{uuid4().hex}",
                stocktake_type="VEHICLE_RECON",
                status=status,
                related_work_session_id=session_id,
                started_by=owner_driver_id,
                **kwargs,
            ))
            await db.commit()
        await assert_deactivate_blocked(gate, rep["id"])

    rep, _ = await create_rep(gate)
    state = await identity_state(gate, company.id, rep["id"])
    await seed_reconciled_session(
        gate, company_index=0, driver_id=state.driver_id, settled=False
    )
    allowed = await gate.client.post(
        f"/representatives/{rep['id']}/deactivate",
        json={"request_id": str(uuid4())}, headers=auth(gate)
    )
    assert allowed.status_code == 204, allowed.text

    company1_rep, _ = await create_rep(gate, 0)
    company2_rep, _ = await create_rep(gate, 1)
    company2_state = await identity_state(
        gate, gate.companies[1].id, company2_rep["id"]
    )
    async with AsyncSession(gate.engine) as db:
        db.add(WorkSession(
            company_id=gate.companies[1].id, driver_id=company2_state.driver_id
        ))
        await db.commit()
    unrelated = await gate.client.post(
        f"/representatives/{company1_rep['id']}/deactivate",
        json={"request_id": str(uuid4())}, headers=auth(gate, 0)
    )
    assert unrelated.status_code == 204, unrelated.text


async def audit_count(gate, representative_id):
    async with AsyncSession(gate.engine) as db:
        return int(await db.scalar(select(func.count()).select_from(SystemAuditLog).where(
            SystemAuditLog.company_id == gate.companies[0].id,
            SystemAuditLog.target_id == f"FieldRepresentative_{representative_id}",
        )) or 0)


@pytest.mark.asyncio
async def test_focused_concurrency_lock_safety(gate):
    # Two distinct deactivates: exactly one mutation/revision/audit succeeds.
    rep, _ = await create_rep(gate)
    before = await identity_state(gate, gate.companies[0].id, rep["id"])
    audit_before = await audit_count(gate, rep["id"])
    r1, r2 = await asyncio.gather(*[
        gate.client.post(
            f"/representatives/{rep['id']}/deactivate",
            json={"request_id": str(uuid4())}, headers=auth(gate)
        )
        for _ in range(2)
    ])
    assert sorted((r1.status_code, r2.status_code)) == [204, 409]
    after = await identity_state(gate, gate.companies[0].id, rep["id"])
    assert not after.principal_active
    assert after.principal_revision == before.principal_revision + 1
    assert await audit_count(gate, rep["id"]) == audit_before + 1

    # Deactivate/reactivate serialize safely. Depending lock acquisition order,
    # reactivate either conflicts while still active or follows deactivate.
    rep, _ = await create_rep(gate)
    before = await identity_state(gate, gate.companies[0].id, rep["id"])
    audit_before = await audit_count(gate, rep["id"])
    deact, react = await asyncio.gather(
        gate.client.post(
            f"/representatives/{rep['id']}/deactivate",
            json={"request_id": str(uuid4())}, headers=auth(gate)
        ),
        gate.client.post(
            f"/representatives/{rep['id']}/reactivate",
            json={"request_id": str(uuid4())}, headers=auth(gate)
        ),
    )
    statuses = sorted((deact.status_code, react.status_code))
    assert statuses in ([204, 204], [204, 409])
    after = await identity_state(gate, gate.companies[0].id, rep["id"])
    assert after.principal_revision == before.principal_revision + 1
    assert after.principal_active is (statuses == [204, 204])
    assert await audit_count(gate, rep["id"]) == audit_before + (
        2 if statuses == [204, 204] else 1
    )

    # Distinct reset identities are distinct authorized mutations and must serialize.
    rep, _ = await create_rep(gate)
    before = await identity_state(gate, gate.companies[0].id, rep["id"])
    audit_before = await audit_count(gate, rep["id"])
    passwords = ("ConcurrentResetOne123", "ConcurrentResetTwo456")
    a, b = await asyncio.gather(*[
        gate.client.post(
            f"/representatives/{rep['id']}/credentials/reset",
            json={"request_id": str(uuid4()), "new_password": password},
            headers=auth(gate),
        )
        for password in passwords
    ])
    assert a.status_code == b.status_code == 204
    after = await identity_state(gate, gate.companies[0].id, rep["id"])
    assert after.principal_revision == before.principal_revision + 2
    assert after.driver_password_hash == before.driver_password_hash
    assert await audit_count(gate, rep["id"]) == audit_before + 2
    successful_passwords = 0
    for password in passwords:
        response = await field_login(gate, 0, rep["username"], password)
        successful_passwords += response.status_code == 200
    assert successful_passwords == 1

    # Same request identity races collapse into one mutation plus one replay.
    rep, _ = await create_rep(gate)
    before = await identity_state(gate, gate.companies[0].id, rep["id"])
    request_id = str(uuid4())
    audit_before = await audit_count(gate, rep["id"])
    results = await asyncio.gather(*[
        gate.client.post(
            f"/representatives/{rep['id']}/credentials/reset",
            json={"request_id": request_id, "new_password": "ConcurrentReplay789"},
            headers=auth(gate),
        )
        for _ in range(2)
    ])
    assert [result.status_code for result in results] == [204, 204]
    after = await identity_state(gate, gate.companies[0].id, rep["id"])
    assert after.principal_revision == before.principal_revision + 1
    assert await audit_count(gate, rep["id"]) == audit_before + 1
    async with AsyncSession(gate.engine) as db:
        idem_count = int(await db.scalar(select(func.count()).select_from(OperationIdempotency).where(
            OperationIdempotency.company_id == gate.companies[0].id,
            OperationIdempotency.request_id == request_id,
            OperationIdempotency.operation == "REPRESENTATIVE_CREDENTIAL_RESET",
        )) or 0)
    assert idem_count == 1


@pytest.mark.asyncio
async def test_list_cursor_and_query_count_sanity(gate):
    for index in range(12):
        body = create_body(prefix=f"page{index}")
        body["full_name"] = f"Paging Representative {index:02d}"
        await create_rep(gate, body=body)

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "field_representatives" in statement.lower():
            statements.append(statement)

    event.listen(gate.engine.sync_engine, "before_cursor_execute", capture)
    try:
        first = await gate.client.get(
            "/representatives",
            params={"search": "Paging Representative", "limit": 5},
            headers=auth(gate),
        )
    finally:
        event.remove(gate.engine.sync_engine, "before_cursor_execute", capture)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert len(payload["items"]) == 5 and payload["has_more"] and payload["next_cursor"]
    assert len(statements) == 1

    second = await gate.client.get(
        "/representatives",
        params={
            "search": "Paging Representative",
            "limit": 5,
            "cursor": payload["next_cursor"],
        },
        headers=auth(gate),
    )
    assert second.status_code == 200, second.text
    ids1 = [item["id"] for item in payload["items"]]
    ids2 = [item["id"] for item in second.json()["items"]]
    assert not set(ids1) & set(ids2)
    names1 = [item["full_name"] for item in payload["items"]]
    names2 = [item["full_name"] for item in second.json()["items"]]
    assert names1 == sorted(names1)
    assert names2 == sorted(names2)
    assert names1[-1] < names2[0]
