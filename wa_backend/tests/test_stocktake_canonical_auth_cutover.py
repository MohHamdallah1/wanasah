from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)
from api.warehouse import stocktake
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "api" / "warehouse" / "stocktake.py"


class _ScalarSession:
    def __init__(self, values):
        self.values = list(values)
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        if not self.values:
            raise AssertionError("unexpected scalar call")
        return self.values.pop(0)


def _subject(*, owner=False, locator=903):
    return BackofficeAuthorizationSubject(
        principal_id=101,
        backoffice_user_id=202,
        company_id=77,
        is_company_owner=owner,
        legacy_grant_driver_id=locator,
    )


def _dependency(function, parameter):
    default = inspect.signature(function).parameters[parameter].default
    return default.dependency, default.use_cache


class _ExecuteResult:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class _SecondaryCredentialDB:
    def __init__(self, execute_rows, scalar_rows=()):
        self.execute_rows = list(execute_rows)
        self.scalar_rows = list(scalar_rows)
        self.execute_statements = []
        self.scalar_statements = []

    async def execute(self, statement):
        self.execute_statements.append(statement)
        if not self.execute_rows:
            raise AssertionError("unexpected execute call")
        return _ExecuteResult(self.execute_rows.pop(0))

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        if not self.scalar_rows:
            raise AssertionError("unexpected scalar call")
        return self.scalar_rows.pop(0)


class StocktakeCanonicalAuthCutoverTests(unittest.IsolatedAsyncioTestCase):
    def test_source_has_zero_legacy_request_authority(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("get_current_driver", source)
        self.assertNotIn("InventoryAccess", source)
        self.assertNotIn("current_admin", source)
        self.assertNotIn(".is_admin", source)
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("principal_id == legacy_actor.id", source)
        self.assertNotIn("principal_id == Driver.id", source)
        self.assertIn("get_current_backoffice_capability_access", source)
        self.assertIn("get_current_backoffice_legacy_driver", source)

    def test_all_routes_use_canonical_backoffice_access(self):
        endpoints = (
            stocktake.list_stocktake_cycle_batches,
            stocktake.list_vehicle_recon_candidates,
            stocktake.list_active_stocktake_sessions,
            stocktake.get_stocktake_session_context,
            stocktake.start_unified_stocktake,
            stocktake.get_stocktake_count_sheet,
            stocktake.submit_stocktake_count,
            stocktake.get_stocktake_review,
            stocktake.approve_stocktake_session,
            stocktake.recount_stocktake_session,
            stocktake.cancel_stocktake_session,
        )
        for endpoint in endpoints:
            dependency, use_cache = _dependency(endpoint, "access")
            self.assertIs(dependency, get_current_backoffice_capability_access)
            self.assertTrue(use_cache)

    def test_only_genuine_operational_routes_load_legacy_actor(self):
        actor_endpoints = (
            stocktake.start_unified_stocktake,
            stocktake.get_stocktake_count_sheet,
            stocktake.submit_stocktake_count,
            stocktake.approve_stocktake_session,
            stocktake.recount_stocktake_session,
            stocktake.cancel_stocktake_session,
        )
        read_only_without_actor = (
            stocktake.list_stocktake_cycle_batches,
            stocktake.list_vehicle_recon_candidates,
            stocktake.list_active_stocktake_sessions,
            stocktake.get_stocktake_session_context,
            stocktake.get_stocktake_review,
        )
        for endpoint in actor_endpoints:
            dependency, use_cache = _dependency(endpoint, "legacy_actor")
            self.assertIs(dependency, get_current_backoffice_legacy_driver)
            self.assertTrue(use_cache)
        for endpoint in read_only_without_actor:
            self.assertNotIn("legacy_actor", inspect.signature(endpoint).parameters)

    def test_exact_capability_mapping_is_preserved(self):
        expected = {
            stocktake.list_stocktake_cycle_batches: "stocktake.start",
            stocktake.list_vehicle_recon_candidates: "stocktake.start",
            stocktake.list_active_stocktake_sessions: "stocktake.read",
            stocktake.get_stocktake_session_context: "stocktake.read",
            stocktake.start_unified_stocktake: "stocktake.start",
            stocktake.get_stocktake_count_sheet: "stocktake.count",
            stocktake.submit_stocktake_count: "stocktake.count",
            stocktake.get_stocktake_review: "stocktake.review",
            stocktake.approve_stocktake_session: "stocktake.approve",
            stocktake.recount_stocktake_session: "stocktake.recount",
            stocktake.cancel_stocktake_session: "stocktake.cancel",
        }
        for endpoint, code in expected.items():
            body = inspect.getsource(endpoint)
            self.assertIn(code, body, msg=endpoint.__name__)
        vehicle_body = inspect.getsource(stocktake.list_vehicle_recon_candidates)
        self.assertIn("location.read", vehicle_body)
        self.assertIn("location_filter('stocktake.start')", vehicle_body)

    async def test_owner_and_ordinary_exact_location_authority(self):
        owner_db = _ScalarSession([11])
        owner_access = BackofficeCapabilityAccess(
            owner_db, _subject(owner=True, locator=None)
        )
        await stocktake._require_location_capability(owner_access, "stocktake.review", 11)
        self.assertEqual(len(owner_db.statements), 1)

        ordinary_db = _ScalarSession([11, True])
        ordinary_access = BackofficeCapabilityAccess(ordinary_db, _subject())
        await stocktake._require_location_capability(
            ordinary_access, "stocktake.review", 11
        )
        self.assertEqual(len(ordinary_db.statements), 2)

    async def test_missing_capability_and_wrong_location_fail_closed(self):
        missing = BackofficeCapabilityAccess(_ScalarSession([11, False]), _subject())
        with self.assertRaises(HTTPException) as caught:
            await stocktake._require_location_capability(
                missing, "stocktake.review", 11
            )
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail, "Authorization denied.")

        foreign = BackofficeCapabilityAccess(_ScalarSession([None]), _subject())
        with self.assertRaises(HTTPException) as caught:
            await stocktake._require_location_capability(
                foreign, "stocktake.cancel", 999
            )
        self.assertEqual(caught.exception.status_code, 403)

    def test_review_and_cancel_use_capabilities_not_admin_persona(self):
        review = inspect.getsource(stocktake.get_stocktake_review)
        cancel = inspect.getsource(stocktake.cancel_stocktake_session)
        self.assertIn("'stocktake.review'", review)
        self.assertIn("'stocktake.cancel'", cancel)
        self.assertNotIn("is_admin", review)
        self.assertNotIn("is_admin", cancel)

    def test_legacy_actor_is_only_operational_attribution_or_credentials(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("legacy_actor.company_id", source)
        self.assertNotIn("legacy_actor.is_admin", source)
        self.assertIn("started_by=legacy_actor.id", source)
        self.assertIn("counted_by=legacy_actor.id", source)
        self.assertIn("session.approved_by = legacy_actor.id", source)
        self.assertIn("cancelled_by = legacy_actor.id", source)
        self.assertIn("admin_id=legacy_actor.id", source)
        self.assertNotIn("legacy_actor.password_hash", source)
        cancel = inspect.getsource(stocktake.cancel_stocktake_session)
        self.assertIn("verify_existing_password", cancel)
        self.assertIn("access.subject.principal_id", cancel)
        self.assertIn("company_id = access.company_id", source)

    async def test_secondary_credentials_resolve_independent_canonical_identity_and_recount(self):
        legacy = SimpleNamespace(
            id=903,
            company_id=77,
            username="supervisor",
            password_hash="hash",
            is_active=True,
            is_admin=False,
        )
        bridge = SimpleNamespace(
            company_id=77,
            legacy_driver_id=903,
            backoffice_principal_id=101,
            backoffice_user_id=202,
        )
        principal = SimpleNamespace(
            id=101,
            company_id=77,
            principal_type="BACKOFFICE",
            is_active=True,
            auth_revision=4,
        )
        profile = SimpleNamespace(
            id=202,
            company_id=77,
            principal_id=101,
            principal_type="BACKOFFICE",
        )
        owner = None
        # Authenticate once at the canonical boundary; this unit case checks
        # the independent legacy FK map and the scoped recount grant.
        identity = SimpleNamespace(
            principal_id=101, company_id=77, backoffice_user_id=202,
            auth_revision=4, is_company_owner=False,
        )
        db = _SecondaryCredentialDB([bridge], scalar_rows=[11, True, legacy])
        subject = _subject(owner=False, locator=903)
        with patch(
            "domains.identity.authentication.authenticate_identity",
            new=AsyncMock(return_value=identity),
        ), patch.object(
            stocktake,
            "resolve_backoffice_authorization_subject",
            new=AsyncMock(return_value=subject),
        ) as resolver:
            resolved = await stocktake._verify_stocktake_admin_credentials(
                db, 77, "supervisor", "pw", 11
            )
        self.assertIs(resolved, legacy)
        self.assertEqual({101, 202, 903}, {principal.id, profile.id, legacy.id})
        context = resolver.await_args.args[1]
        self.assertEqual(context.principal_id, 101)
        self.assertEqual(context.backoffice_user_id, 202)
        self.assertEqual(context.company_id, 77)
        self.assertFalse(context.is_company_owner)
        self.assertEqual(len(db.scalar_statements), 3)
        self.assertEqual(len(db.execute_statements), 1)

    async def test_secondary_credentials_fail_closed_on_cross_company_mapping(self):
        legacy = SimpleNamespace(
            id=903,
            company_id=77,
            password_hash="hash",
            is_active=True,
        )
        bridge = SimpleNamespace(
            company_id=88,
            legacy_driver_id=903,
            backoffice_principal_id=101,
            backoffice_user_id=202,
        )
        db = _SecondaryCredentialDB([bridge], scalar_rows=[11, True])
        identity = SimpleNamespace(
            principal_id=101, company_id=77, backoffice_user_id=202,
            auth_revision=4, is_company_owner=False,
        )
        with patch(
            "domains.identity.authentication.authenticate_identity",
            new=AsyncMock(return_value=identity),
        ), patch.object(
            stocktake, "resolve_backoffice_authorization_subject",
            new=AsyncMock(return_value=_subject()),
        ):
            resolved = await stocktake._verify_stocktake_admin_credentials(
                db, 77, "supervisor", "pw", 11
            )
        self.assertIsNone(resolved)
        self.assertEqual(len(db.execute_statements), 1)

    def test_secondary_credential_source_has_no_legacy_authority_shortcut(self):
        source = inspect.getsource(stocktake._verify_stocktake_admin_credentials)
        self.assertIn("IdentityLegacyDriverMap", source)
        self.assertIn("CompanyPrincipal", source)
        self.assertIn("BackofficeUser", source)
        self.assertIn("CompanyOwner", source)
        self.assertIn("DashboardRequestContext", source)
        self.assertIn("resolve_backoffice_authorization_subject", source)
        self.assertIn("BackofficeCapabilityAccess", source)
        self.assertIn("'stocktake.recount'", source)
        self.assertNotIn("is_admin", source)
        self.assertNotIn("classification", source)
        self.assertNotIn("principal_id == legacy_candidate.id", source)
        self.assertNotIn("principal_id == legacy_actor.id", source)
        self.assertNotIn("principal_id == Driver.id", source)

    def test_locks_state_machine_posting_cursors_and_transactions_remain(self):
        source = SOURCE_PATH.read_text(encoding="utf-8")
        for marker in (
            "acquire_inventory_location_guard(",
            ".with_for_update()",
            "post_approved_stocktake_adjustments(",
            "validate_vehicle_recon_work_session(",
            "requires_independent_recount",
            "pending_recount_authorized_by",
            "SystemAuditLog(",
            "await db.commit()",
            "await db.rollback()",
            "_encode_stocktake_cursor(",
            "_decode_stocktake_cursor(",
            "_encode_stocktake_cycle_batch_cursor(",
            "_decode_stocktake_cycle_batch_cursor(",
        ):
            self.assertIn(marker, source)
        self.assertGreaterEqual(source.count(".with_for_update()"), 4)


@unittest.skipUnless(
    __import__("os").environ.get("WANASAH_ST997_PG_GATE") == "1",
    "Explicit disposable restricted PG16 56597 st997_cancel_reauth database only",
)
class StocktakeCancelCanonicalPasswordRealPG16(unittest.IsolatedAsyncioTestCase):
    async def test_real_bearer_differs_from_legacy_and_releases_only_after_canonical_password(self):
        """One real HTTP/Bearer/PG16 differential; never override dependencies."""
        import os
        from uuid import uuid4
        from datetime import datetime, timezone

        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy import func, select, text
        from sqlalchemy.engine import make_url
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import NullPool

        from api import auth
        from domains.authorization.capabilities import PERMISSIONS
        from domains.identity.models import CompanyPrincipal
        from models import (
            Company, Driver, InventoryLocation, InventoryLock,
            InventoryMovement, Permission, Role, StocktakeSession,
            SystemAuditLog, UserLocationAccess, role_permissions,
        )
        from tests.canonical_actor_fixtures import seed_ordinary_backoffice_fixture

        port, db_name = 56597, "st997_cancel_reauth"
        canonical_password = "ST997BackofficeCurrentPassword"
        old_legacy_password = "ST997OldDriverDifferentPassword"
        other_password = "ST997OtherPrincipalPassword"
        runtime_url = make_url(os.environ["DATABASE_URL"])
        admin_url = make_url(os.environ["DATABASE_URL_MIGRATION"])
        for url in (runtime_url, admin_url):
            assert (url.drivername, url.host, url.port, url.database) == (
                "postgresql+asyncpg", "127.0.0.1", port, db_name,
            ), "Refusing any database except disposable Stocktake #997 PG16"
        assert runtime_url.username == "st997_app" and admin_url.username == "st997_admin"

        runtime = create_async_engine(runtime_url, poolclass=NullPool)
        migration = create_async_engine(admin_url, poolclass=NullPool)
        try:
            async with runtime.connect() as conn:
                identity = (await conn.execute(text(
                    "SELECT current_database(), current_user, inet_server_port(), "
                    "rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                ))).one()
                assert tuple(identity) == (db_name, "st997_app", port, False, False)
                for table in ("stocktake_sessions", "inventory_locks", "inventory_movements"):
                    protected = (await conn.execute(text(
                        "SELECT relrowsecurity, relforcerowsecurity "
                        "FROM pg_class WHERE oid = to_regclass(:table)"
                    ), {"table": table})).one()
                    assert tuple(protected) == (True, True), (table, protected)

            async with AsyncSession(migration, expire_on_commit=False) as db:
                companies = [
                    Company(name="ST997 A", company_code="ST997-A-"+uuid4().hex[:10], timezone="UTC"),
                    Company(name="ST997 B", company_code="ST997-B-"+uuid4().hex[:10], timezone="UTC"),
                ]
                db.add_all(companies)
                await db.flush()
                fixtures = []
                for index, company in enumerate(companies):
                    await db.execute(text(
                        "SELECT set_config('app.current_tenant', :company, true)"
                    ), {"company": str(company.id)})
                    actor_password = canonical_password if index == 0 else other_password
                    actor = await seed_ordinary_backoffice_fixture(
                        db, company.id, password=actor_password,
                    )
                    denied = await seed_ordinary_backoffice_fixture(
                        db, company.id, password=other_password,
                    ) if index == 0 else None
                    principal = await db.get(CompanyPrincipal, actor.context.principal_id)
                    driver = await db.get(Driver, actor.driver_id)
                    assert principal is not None and driver is not None
                    driver.set_password(old_legacy_password)
                    assert principal.password_hash != driver.password_hash

                    location = InventoryLocation(
                        company_id=company.id, name="ST997 Warehouse", code="ST997-WH",
                        location_type="WAREHOUSE", is_active=True, version=1,
                    )
                    db.add(location)
                    await db.flush()
                    for capability in ("stocktake.cancel", "stocktake.read"):
                        assert capability in PERMISSIONS
                        permission = await db.scalar(select(Permission).where(
                            Permission.code == capability,
                        ))
                        if permission is None:
                            permission = Permission(code=capability)
                            db.add(permission)
                            await db.flush()
                        role = Role(company_id=company.id,
                                    name="ST997-"+capability+"-"+uuid4().hex[:8])
                        db.add(role)
                        await db.flush()
                        await db.execute(role_permissions.insert().values(
                            company_id=company.id, role_id=role.id,
                            permission_id=permission.id,
                        ))
                        db.add(UserLocationAccess(
                            company_id=company.id, driver_id=actor.driver_id,
                            location_id=location.id, role_id=role.id,
                        ))
                        # Read-only BACKOFFICE can log in, but never cancel.
                        if denied is not None and capability == "stocktake.read":
                            db.add(UserLocationAccess(
                                company_id=company.id, driver_id=denied.driver_id,
                                location_id=location.id, role_id=role.id,
                            ))
                        await db.flush()
                    session = StocktakeSession(
                        company_id=company.id, location_id=location.id,
                        reference_number="ST997-"+uuid4().hex, stocktake_type="FULL_COUNT",
                        status="COUNTING", snapshot_cutoff_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        started_by=actor.driver_id,
                    )
                    db.add(session)
                    await db.flush()
                    lock = InventoryLock(
                        company_id=company.id, stocktake_session_id=session.id,
                        location_id=location.id, created_by=actor.driver_id,
                    )
                    db.add(lock)
                    await db.flush()
                    fixtures.append({
                        "company": int(company.id), "code": company.company_code,
                        "username": principal.username, "actor": int(actor.driver_id),
                        "session": int(session.id), "location": int(location.id),
                        "lock": int(lock.id),
                        "denied_username": None if denied is None else str(
                            await db.scalar(select(CompanyPrincipal.username).where(
                                CompanyPrincipal.id == denied.context.principal_id,
                            ))
                        ),
                    })
                await db.commit()

            app = FastAPI()
            app.include_router(auth.router)
            app.include_router(stocktake.router)
            a, b = fixtures

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://st997.local",
                timeout=30.0,
            ) as client:
                async def login(fixture, password, username=None):
                    response = await client.post("/login", json={
                        "company_code": fixture["code"],
                        "username": username or fixture["username"],
                        "password": password,
                    })
                    assert response.status_code == 200, response.text
                    return {"Authorization": "Bearer "+response.json()["token"]}

                signed = await login(a, canonical_password)
                denied = await login(a, other_password, a["denied_username"])
                other_tenant = await login(b, other_password)
                route = f"/warehouse/unified/stocktake/{a['session']}/cancel"

                def command(password):
                    return {
                        "request_id": str(uuid4()),
                        "password": password,
                        "reason": "ST997 signed cancellation reauthentication",
                    }

                # The legacy Driver secret and another wrong secret may NOT cancel.
                for incorrect in (old_legacy_password, "ST997NotAValidPassword"):
                    response = await client.post(
                        route, headers=signed, json=command(incorrect),
                    )
                    assert response.status_code == 403, (incorrect, response.text)
                # A genuinely authenticated principal without the grant cannot cancel.
                response = await client.post(
                    route, headers=denied, json=command(other_password),
                )
                assert response.status_code == 403, response.text
                # Cross-company stocktake ID is hidden with 404, not disclosed.
                response = await client.post(
                    route, headers=other_tenant, json=command(other_password),
                )
                assert response.status_code == 404, response.text

                async with AsyncSession(migration, expire_on_commit=False) as db:
                    unchanged = await db.get(StocktakeSession, a["session"])
                    original_lock = await db.get(InventoryLock, a["lock"])
                    assert unchanged.status == "COUNTING"
                    assert original_lock.released_at is None
                    rejections = (await db.scalars(select(SystemAuditLog).where(
                        SystemAuditLog.company_id == a["company"],
                        SystemAuditLog.target_id == f"Stocktake_{a['session']}",
                        SystemAuditLog.action_type == "STOCKTAKE_CANCEL_REJECTED",
                    ))).all()
                    assert len(rejections) == 2
                    assert all(log.admin_id == a["actor"]
                               and log.new_value == "Wrong password"
                               for log in rejections)

                request = command(canonical_password)
                response = await client.post(route, headers=signed, json=request)
                assert response.status_code == 200, response.text
                payload = response.json()
                assert payload["status"] == "CANCELLED"
                assert payload["released_lock_count"] == 1

                # A fresh real BACKOFFICE login must see durable cancellation.
                signed_again = await login(a, canonical_password)
                replay = await client.post(route, headers=signed_again, json=request)
                assert replay.status_code == 200, replay.text
                assert replay.json() == payload

            async with AsyncSession(migration, expire_on_commit=False) as db:
                persisted = await db.get(StocktakeSession, a["session"])
                released = await db.get(InventoryLock, a["lock"])
                assert persisted.status == "CANCELLED"
                assert persisted.cancelled_by == a["actor"]
                assert persisted.cancellation_reason == request["reason"]
                assert persisted.cancelled_at is not None
                assert released.released_at is not None
                assert released.released_by == a["actor"]
                assert released.release_reason == "STOCKTAKE_CANCELLED"
                assert int(await db.scalar(select(func.count()).select_from(
                    InventoryMovement).where(
                    InventoryMovement.company_id == a["company"],
                    InventoryMovement.stocktake_session_id == a["session"],
                ))) == 0
                audits = (await db.scalars(select(SystemAuditLog).where(
                    SystemAuditLog.company_id == a["company"],
                    SystemAuditLog.target_id == f"Stocktake_{a['session']}",
                    SystemAuditLog.action_type == "STOCKTAKE_CANCELLED",
                ))).all()
                assert len(audits) == 1 and audits[0].admin_id == a["actor"]
                other = await db.get(StocktakeSession, b["session"])
                other_lock = await db.get(InventoryLock, b["lock"])
                assert other.status == "COUNTING" and other_lock.released_at is None
                print(
                    "ST997_REAL_PG16_SIGNED_CANONICAL_CANCEL=PASS "
                    "login_different_driver_password=DENIED wrong_password_audited=2 "
                    "no_grant=403 cross_tenant_hidden=404 persisted=1 released_lock=1 "
                    "movement=0 retry_exactly_once=1"
                )
        finally:
            await runtime.dispose()
            await migration.dispose()


if __name__ == "__main__":
    unittest.main()
