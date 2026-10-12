"""Focused tests for canonical Backoffice legacy operational compatibility."""
from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]
SECRET = "BackofficeCompatibilitySyntheticSecret123456789012345678901234"

with patch.dict(
    os.environ,
    {
        "ENVIRONMENT": "test",
        "SECRET_KEY": SECRET,
        "DATABASE_URL": "postgresql+asyncpg://bo_unit@127.0.0.1:1/bo_unit",
        "DATABASE_URL_MIGRATION": "postgresql+asyncpg://bo_admin@127.0.0.1:1/bo_unit",
    },
):
    from api.authentication import backoffice_compatibility as api_module
    from api.authentication import dependencies as deps
    from domains.identity import backoffice_legacy_actor as domain

from domains.auth_sessions.codec import issue_access_token
from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
from models import Driver


def dashboard_context(
    *,
    principal_id=101,
    backoffice_user_id=202,
    company_id=7,
    owner=False,
):
    return DashboardRequestContext(
        principal_id=principal_id,
        backoffice_user_id=backoffice_user_id,
        company_id=company_id,
        auth_revision=3,
        is_company_owner=owner,
    )


class Bridge(SimpleNamespace):
    @property
    def classification(self):
        raise AssertionError("Bridge classification is not compatibility authority")


def bridge(
    *,
    company_id=7,
    principal_id=101,
    backoffice_user_id=202,
    legacy_driver_id=303,
):
    return Bridge(
        company_id=company_id,
        backoffice_principal_id=principal_id,
        backoffice_user_id=backoffice_user_id,
        legacy_driver_id=legacy_driver_id,
    )


def driver(*, driver_id=303, company_id=7, active=True):
    return Driver(
        id=driver_id,
        company_id=company_id,
        is_active=active,
    )


def mapping_db(mapping):
    result = Mock()
    result.scalar_one_or_none.return_value = mapping
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=result)
    return db, result


def compatibility_db(mapping, operational):
    mapping_result = Mock()
    mapping_result.scalar_one_or_none.return_value = mapping
    driver_result = Mock()
    driver_result.scalar_one_or_none.return_value = operational
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=[mapping_result, driver_result])
    db.scalar = AsyncMock(return_value=False)
    db.connection = AsyncMock()
    db.in_transaction.return_value = False
    return db, mapping_result, driver_result


def driver_only_db(operational):
    result = Mock()
    result.scalar_one_or_none.return_value = operational
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=result)
    db.scalar = AsyncMock(return_value=False)
    db.connection = AsyncMock()
    db.in_transaction.return_value = False
    return db, result


class CanonicalBackofficeRuntimeCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        secret = patch.object(deps.Config, "SECRET_KEY", SECRET)
        secret.start()
        self.addCleanup(secret.stop)
        previous = deps.tenant_context.set(None)
        self.addCleanup(deps.tenant_context.reset, previous)

    def assert_opaque_401(self, error):
        self.assertEqual(error.status_code, 401)
        self.assertEqual(error.detail, deps._AUTH_REJECTION_DETAIL)
        self.assertEqual(error.headers, {"WWW-Authenticate": "Bearer"})

    def assert_no_transaction_mutation(self, db):
        for name in (
            "commit",
            "rollback",
            "begin",
            "begin_nested",
            "flush",
            "add",
            "delete",
        ):
            getattr(db, name).assert_not_called()

    async def test_owner_and_ordinary_contexts_resolve_exact_operational_mapping(self):
        for owner in (True, False):
            with self.subTest(owner=owner):
                db, result = mapping_db(bridge())
                locator = await domain.resolve_backoffice_legacy_actor_locator(
                    db, dashboard_context(owner=owner)
                )
                self.assertEqual(
                    (
                        locator.principal_id,
                        locator.backoffice_user_id,
                        locator.company_id,
                        locator.legacy_driver_id,
                    ),
                    (101, 202, 7, 303),
                )
                result.scalar_one_or_none.assert_called_once_with()
                self.assert_no_transaction_mutation(db)

    async def test_principal_profile_and_legacy_driver_ids_remain_independent(self):
        db, _ = mapping_db(
            bridge(principal_id=11, backoffice_user_id=22, legacy_driver_id=33)
        )
        locator = await domain.resolve_backoffice_legacy_actor_locator(
            db,
            dashboard_context(principal_id=11, backoffice_user_id=22),
        )
        self.assertEqual(
            (
                locator.principal_id,
                locator.backoffice_user_id,
                locator.legacy_driver_id,
            ),
            (11, 22, 33),
        )

    async def test_bridge_query_is_exact_company_principal_and_backoffice_profile(self):
        db, _ = mapping_db(bridge())
        await domain.resolve_backoffice_legacy_actor_locator(db, dashboard_context())
        statement = db.execute.await_args.args[0]
        predicates = statement.whereclause.clauses
        self.assertEqual(
            [(item.left.name, item.right.value) for item in predicates],
            [
                ("company_id", 7),
                ("backoffice_principal_id", 101),
                ("backoffice_user_id", 202),
            ],
        )
        compiled = statement.compile(dialect=postgresql.dialect())
        self.assertEqual(list(compiled.params.values()), [7, 101, 202])

    async def test_wrong_context_and_invalid_ids_rejected_before_bridge_lookup(self):
        field = FieldRequestContext(
            principal_id=101,
            representative_id=202,
            company_id=7,
            auth_revision=3,
        )
        db, _ = mapping_db(bridge())
        with self.assertRaises(domain.BackofficeLegacyActorLocatorRejected):
            await domain.resolve_backoffice_legacy_actor_locator(  # type: ignore[arg-type]
                db, field
            )
        db.execute.assert_not_awaited()

        for field_name in ("principal_id", "backoffice_user_id", "company_id"):
            for bad in (0, -1, True, "101"):
                with self.subTest(field=field_name, bad=bad):
                    values = {
                        "principal_id": 101,
                        "backoffice_user_id": 202,
                        "company_id": 7,
                    }
                    values[field_name] = bad
                    db, _ = mapping_db(bridge())
                    with self.assertRaises(
                        domain.BackofficeLegacyActorLocatorRejected
                    ):
                        await domain.resolve_backoffice_legacy_actor_locator(
                            db,
                            dashboard_context(**values),  # type: ignore[arg-type]
                        )
                    db.execute.assert_not_awaited()

    async def test_missing_and_duplicate_bridge_rejected(self):
        db, _ = mapping_db(None)
        with self.assertRaises(domain.BackofficeLegacyActorLocatorRejected):
            await domain.resolve_backoffice_legacy_actor_locator(
                db, dashboard_context()
            )

        db, result = mapping_db(bridge())
        result.scalar_one_or_none.side_effect = MultipleResultsFound(
            "synthetic duplicate"
        )
        with self.assertRaises(domain.BackofficeLegacyActorLocatorRejected):
            await domain.resolve_backoffice_legacy_actor_locator(
                db, dashboard_context()
            )

    async def test_bridge_mismatches_and_malformed_legacy_id_rejected(self):
        rows = (
            bridge(company_id=8),
            bridge(principal_id=999),
            bridge(backoffice_user_id=999),
            bridge(legacy_driver_id=0),
            bridge(legacy_driver_id=-1),
            bridge(legacy_driver_id=True),
            bridge(legacy_driver_id="303"),
        )
        for row in rows:
            with self.subTest(row=row):
                db, _ = mapping_db(row)
                with self.assertRaises(domain.BackofficeLegacyActorLocatorRejected):
                    await domain.resolve_backoffice_legacy_actor_locator(
                        db, dashboard_context()
                    )

    async def test_api_driver_load_is_exact_company_plus_legacy_driver_id(self):
        operational = driver()
        db, result = driver_only_db(operational)
        locator = domain.BackofficeLegacyActorLocator(101, 202, 7, 303)
        with patch.object(
            api_module,
            "resolve_backoffice_legacy_actor_locator",
            AsyncMock(return_value=locator),
        ) as resolve:
            returned = await api_module.get_current_backoffice_legacy_driver(
                current=dashboard_context(), db=db
            )

        self.assertIs(returned, operational)
        resolve.assert_awaited_once_with(db, dashboard_context())
        statement = db.execute.await_args.args[0]
        self.assertEqual([table.name for table in statement.get_final_froms()], ["drivers"])
        predicates = statement.whereclause.clauses
        self.assertEqual(
            [(item.left.name, item.right.value) for item in predicates],
            [("company_id", 7), ("id", 303)],
        )
        compiled = statement.compile(dialect=postgresql.dialect())
        self.assertEqual(list(compiled.params.values()), [7, 303])
        result.scalar_one_or_none.assert_called_once_with()
        self.assert_no_transaction_mutation(db)

    async def test_missing_cross_company_wrong_id_inactive_and_ambiguous_driver_rejected(self):
        rows = (
            None,
            driver(company_id=8),
            driver(driver_id=999),
            driver(active=False),
            driver(active=None),
        )
        locator = domain.BackofficeLegacyActorLocator(101, 202, 7, 303)
        for row in rows:
            with self.subTest(row=row):
                db, _ = driver_only_db(row)
                with patch.object(
                    api_module,
                    "resolve_backoffice_legacy_actor_locator",
                    AsyncMock(return_value=locator),
                ):
                    with self.assertRaises(HTTPException) as rejected:
                        await api_module.get_current_backoffice_legacy_driver(
                            current=dashboard_context(), db=db
                        )
                self.assert_opaque_401(rejected.exception)
                self.assert_no_transaction_mutation(db)

        db, result = driver_only_db(driver())
        result.scalar_one_or_none.side_effect = MultipleResultsFound(
            "synthetic duplicate"
        )
        with patch.object(
            api_module,
            "resolve_backoffice_legacy_actor_locator",
            AsyncMock(return_value=locator),
        ):
            with self.assertRaises(HTTPException) as rejected:
                await api_module.get_current_backoffice_legacy_driver(
                    current=dashboard_context(), db=db
                )
        self.assert_opaque_401(rejected.exception)

    async def test_legacy_is_admin_true_or_false_has_zero_effect_for_owner_and_ordinary(self):
        for owner in (False, True):
            for flag in (False, True):
                with self.subTest(owner=owner, legacy_flag=flag):
                    operational = SimpleNamespace(id=303, company_id=7, is_active=True, is_admin=flag)
                    db, _, _ = compatibility_db(bridge(), operational)
                    returned = await api_module.get_current_backoffice_legacy_driver(
                        current=dashboard_context(owner=owner), db=db
                    )
                    self.assertIs(returned, operational)
                    self.assert_no_transaction_mutation(db)

    async def test_bridge_or_persistence_failure_becomes_opaque_401_without_mutation(self):
        for failure in (
            domain.BackofficeLegacyActorLocatorRejected(),
            RuntimeError("synthetic persistence detail"),
        ):
            with self.subTest(failure=type(failure)):
                db, _ = driver_only_db(driver())
                with patch.object(
                    api_module,
                    "resolve_backoffice_legacy_actor_locator",
                    AsyncMock(side_effect=failure),
                ):
                    with self.assertRaises(HTTPException) as rejected:
                        await api_module.get_current_backoffice_legacy_driver(
                            current=dashboard_context(), db=db
                        )
                self.assert_opaque_401(rejected.exception)
                db.execute.assert_not_awaited()
                self.assert_no_transaction_mutation(db)

    def test_dependency_signature_uses_trusted_context_and_request_session(self):
        params = inspect.signature(
            api_module.get_current_backoffice_legacy_driver
        ).parameters
        self.assertEqual(list(params), ["current", "db"])
        self.assertIs(
            params["current"].default.dependency,
            deps.get_current_backoffice_context,
        )
        self.assertIs(params["db"].default.dependency, deps.get_db)
        self.assertTrue(params["current"].default.use_cache)
        self.assertTrue(params["db"].default.use_cache)

    async def test_canonical_upstream_authentication_failure_prevents_legacy_lookup(self):
        db, _ = driver_only_db(driver())
        app = FastAPI()

        async def request_db():
            return db

        async def endpoint(
            legacy=Depends(api_module.get_current_backoffice_legacy_driver),
        ):
            return {"legacy_driver_id": legacy.id}

        app.dependency_overrides[deps.get_db] = request_db
        app.add_api_route("/backoffice", endpoint)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://backoffice.test",
        ) as client:
            response = await client.get("/backoffice")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": deps._AUTH_REJECTION_DETAIL})
        db.execute.assert_not_awaited()
        self.assert_no_transaction_mutation(db)

    async def test_fastapi_request_cache_reuses_compatibility_dependency_and_decodes_once(self):
        trusted = dashboard_context(owner=True)
        operational = driver()
        db, result = driver_only_db(operational)
        locator = domain.BackofficeLegacyActorLocator(101, 202, 7, 303)

        app = FastAPI()
        captured = []

        async def request_db():
            return db

        async def endpoint(
            first=Depends(api_module.get_current_backoffice_legacy_driver),
            second=Depends(api_module.get_current_backoffice_legacy_driver),
            current=Depends(deps.get_current_backoffice_context),
            session=Depends(deps.get_authenticated_access_session),
        ):
            captured.append((first, second, current, session))
            return {"legacy_driver_id": first.id}

        app.dependency_overrides[deps.get_db] = request_db
        app.add_api_route("/backoffice", endpoint)
        token = issue_access_token(
            principal_id=trusted.principal_id,
            company_id=trusted.company_id,
            channel=trusted.channel.value,
            principal_type=trusted.principal_type.value,
            auth_revision=trusted.auth_revision,
            secret=SECRET,
        )

        with patch.object(
            deps,
            "decode_company_token",
            wraps=deps.decode_company_token,
        ) as decode, patch.object(
            deps,
            "resolve_access_context",
            AsyncMock(return_value=trusted),
        ) as resolve_context, patch.object(
            api_module,
            "resolve_backoffice_legacy_actor_locator",
            AsyncMock(return_value=locator),
        ) as resolve_locator:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://backoffice.test",
            ) as client:
                response = await client.get(
                    "/backoffice",
                    headers={"Authorization": "Bearer " + token},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"legacy_driver_id": 303})
        first, second, current, session = captured[0]
        self.assertIs(first, operational)
        self.assertIs(second, operational)
        self.assertIs(current, trusted)
        self.assertIs(session.context, trusted)
        self.assertEqual(decode.call_count, 1)
        resolve_context.assert_awaited_once()
        resolve_locator.assert_awaited_once_with(db, trusted)
        self.assertEqual(db.execute.await_count, 1)
        result.scalar_one_or_none.assert_called_once_with()
        self.assert_no_transaction_mutation(db)

    def test_source_guards_keep_compatibility_data_out_of_authority(self):
        domain_source = (
            ROOT / "domains" / "identity" / "backoffice_legacy_actor.py"
        ).read_text(encoding="utf-8")
        api_source = (
            ROOT / "api" / "authentication" / "backoffice_compatibility.py"
        ).read_text(encoding="utf-8")

        for source in (domain_source, api_source):
            tree = ast.parse(source)
            attributes = {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
            }
            calls = {
                node.func.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            }
            self.assertNotIn("is_admin", attributes)
            self.assertNotIn("classification", attributes)
            self.assertNotIn("is_company_owner", attributes)
            self.assertNotIn("decode_company_token", source)
            self.assertNotIn("jwt", source.lower())
            for mutation in (
                "commit",
                "rollback",
                "begin",
                "begin_nested",
                "flush",
                "add",
                "delete",
                "update",
            ):
                self.assertNotIn(mutation, calls)

        domain_tree = ast.parse(domain_source)
        imported = {
            alias.name
            for node in ast.walk(domain_tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        loaded = {
            node.id
            for node in ast.walk(domain_tree)
            if isinstance(node, ast.Name)
        }
        self.assertNotIn("Driver", imported)
        self.assertNotIn("Driver", loaded)

        for source in (domain_source, api_source):
            self.assertNotIn("UserRole", source)
            self.assertNotIn("UserLocationAccess", source)
            self.assertNotIn("PERMISSIONS", source)
            self.assertNotIn("BackofficeCapabilityAccess", source)

        forbidden_aliases = (
            "legacy_driver_id == context.principal_id",
            "legacy_driver_id == context.backoffice_user_id",
            "context.principal_id == legacy_driver_id",
            "context.backoffice_user_id == legacy_driver_id",
        )
        for needle in forbidden_aliases:
            self.assertNotIn(needle, domain_source)


if __name__ == "__main__":
    unittest.main()
