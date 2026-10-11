"""Canonical field-to-Driver compatibility checks; persistence is mocked."""
from __future__ import annotations

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
SECRET = "FieldCompatibilitySyntheticSecret123456789012345678901234567890"
# These synthetic URLs are never connected to by the mocked sessions.
with patch.dict(os.environ, {
    "ENVIRONMENT": "test",
    "SECRET_KEY": SECRET,
    "DATABASE_URL": "postgresql+asyncpg://field_unit@127.0.0.1:1/field_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://field_admin@127.0.0.1:1/field_unit",
}):
    from api.authentication import dependencies as deps
    from api.authentication import field_compatibility as module

from domains.auth_sessions.codec import issue_access_token
from domains.auth_sessions.context import (
    DashboardRequestContext,
    FieldRequestContext,
    RequestContextRejected,
)
from domains.authorization.field_subject import FieldAuthorizationSubject
from models import Driver


def field_context():
    return FieldRequestContext(
        principal_id=101, representative_id=202, company_id=7, auth_revision=3,
    )


class Bridge(SimpleNamespace):
    @property
    def classification(self):
        raise AssertionError("Bridge classification must never grant authority")


def bridge():
    return Bridge(
        company_id=7, field_principal_id=101,
        field_representative_id=202, legacy_driver_id=303,
    )


class OperationalRow(SimpleNamespace):
    @property
    def is_admin(self):
        raise AssertionError("Operational flags must never grant authority")


def operational_row(**changes):
    values = dict(id=303, company_id=7, is_active=True)
    values.update(changes)
    return OperationalRow(**values)


def database(mapping, driver):
    mapping_result, driver_result = Mock(), Mock()
    mapping_result.one_or_none.return_value = mapping
    driver_result.scalar_one_or_none.return_value = driver
    db = MagicMock(spec=AsyncSession)
    db.execute.side_effect = [mapping_result, driver_result]
    db.in_transaction.return_value = False
    db.scalar.return_value = False
    return db, mapping_result, driver_result


class CanonicalFieldRuntimeCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        secret = patch.object(deps.Config, "SECRET_KEY", SECRET)
        secret.start()
        self.addCleanup(secret.stop)
        previous = deps.tenant_context.set(None)
        self.addCleanup(deps.tenant_context.reset, previous)

    def assert_opaque_rejection(self, error):
        self.assertEqual(error.status_code, 401)
        self.assertEqual(error.detail, deps._AUTH_REJECTION_DETAIL)
        self.assertEqual(error.headers, {"WWW-Authenticate": "Bearer"})

    def assert_request_owns_transaction(self, db):
        for name in ("commit", "rollback", "begin", "begin_nested", "flush", "add", "delete"):
            getattr(db, name).assert_not_called()

    async def resolve(self, db, current=None):
        return await module.get_current_field_legacy_driver(
            current=field_context() if current is None else current, db=db,
        )

    async def test_canonical_field_context_returns_exact_orm_object_with_independent_ids(self):
        for flag in (False, True):
            with self.subTest(legacy_flag=flag):
                driver = Driver(id=303, company_id=7, is_active=True, is_admin=flag)
                db, _, result = database(bridge(), driver)
                self.assertIs(await self.resolve(db), driver)
                self.assertEqual((field_context().principal_id, field_context().representative_id, driver.id),
                                 (101, 202, 303))
                self.assertEqual(db.execute.await_count, 2)
                result.scalar_one_or_none.assert_called_once_with()
                self.assert_request_owns_transaction(db)
                db.connection.assert_not_called()

    async def test_existing_subject_resolver_is_the_only_mapping_authority(self):
        current = field_context()
        driver = operational_row(id=909)
        db, _, driver_result = database(None, driver)
        db.execute.side_effect = [driver_result]
        subject = FieldAuthorizationSubject(101, 202, 7, 909)
        with patch.object(module, "resolve_field_authorization_subject",
                          AsyncMock(return_value=subject)) as resolve:
            self.assertIs(await self.resolve(db, current), driver)
        resolve.assert_awaited_once_with(db, current)
        db.execute.assert_awaited_once()
        driver_result.scalar_one_or_none.assert_called_once_with()
        self.assert_request_owns_transaction(db)
        predicates = db.execute.await_args.args[0].whereclause.clauses
        self.assertEqual([(item.left.name, item.right.value) for item in predicates],
                         [("company_id", 7), ("id", 909)])

    async def test_driver_query_requires_exact_company_and_legacy_locator(self):
        db, _, _ = database(bridge(), operational_row())
        await self.resolve(db)
        statement = db.execute.await_args_list[1].args[0]
        self.assertEqual([table.name for table in statement.get_final_froms()], ["drivers"])
        self.assertEqual(statement.column_descriptions[0]["entity"], Driver)
        predicates = statement.whereclause.clauses
        self.assertEqual([(item.left.name, item.right.value) for item in predicates],
                         [("company_id", 7), ("id", 303)])
        compiled = statement.compile(dialect=postgresql.dialect())
        self.assertEqual(list(compiled.params.values()), [7, 303])
        self.assertNotIn("is_admin", str(statement.whereclause))

    async def test_missing_bridge_rejected_before_driver_lookup(self):
        db, _, result = database(None, operational_row())
        with self.assertRaises(HTTPException) as rejected:
            await self.resolve(db)
        self.assert_opaque_rejection(rejected.exception)
        self.assertEqual(db.execute.await_count, 1)
        result.scalar_one_or_none.assert_not_called()
        self.assert_request_owns_transaction(db)

    async def test_missing_cross_company_wrong_id_and_inactive_rows_rejected(self):
        for row in (None, operational_row(company_id=8), operational_row(id=101),
                    operational_row(id=202), operational_row(is_active=False),
                    operational_row(is_active=None)):
            with self.subTest(row=row):
                db, _, _ = database(bridge(), row)
                with self.assertRaises(HTTPException) as rejected:
                    await self.resolve(db)
                self.assert_opaque_rejection(rejected.exception)
                self.assert_request_owns_transaction(db)

    async def test_noncanonical_context_rejected_before_any_operational_lookup(self):
        dashboard = DashboardRequestContext(
            principal_id=101, company_id=7, backoffice_user_id=202,
            auth_revision=3, is_company_owner=True,
        )
        for current in (dashboard, None, SimpleNamespace(**vars(field_context()))):
            with self.subTest(context_type=type(current)):
                db, _, _ = database(bridge(), operational_row())
                with self.assertRaises(HTTPException) as rejected:
                    await module.get_current_field_legacy_driver(current=current, db=db)
                self.assert_opaque_rejection(rejected.exception)
                db.execute.assert_not_awaited()
                self.assert_request_owns_transaction(db)

    async def test_ambiguous_bridge_or_driver_result_fails_closed(self):
        for ambiguous in ("bridge", "driver"):
            with self.subTest(ambiguous=ambiguous):
                db, mapping_result, driver_result = database(bridge(), operational_row())
                result_method = (mapping_result.one_or_none if ambiguous == "bridge"
                                 else driver_result.scalar_one_or_none)
                result_method.side_effect = MultipleResultsFound("synthetic internal identity")
                with self.assertRaises(HTTPException) as rejected:
                    await self.resolve(db)
                self.assert_opaque_rejection(rejected.exception)
                self.assert_request_owns_transaction(db)

    async def test_mapping_and_driver_persistence_errors_remain_opaque_without_transaction_changes(self):
        for failure_stage in ("mapping", "driver", "result"):
            with self.subTest(failure_stage=failure_stage):
                db, mapping_result, driver_result = database(bridge(), operational_row())
                failure = RuntimeError("synthetic SQL / internal identity detail")
                if failure_stage == "mapping":
                    db.execute.side_effect = failure
                elif failure_stage == "driver":
                    db.execute.side_effect = [mapping_result, failure]
                else:
                    driver_result.scalar_one_or_none.side_effect = failure
                with self.assertRaises(HTTPException) as rejected:
                    await self.resolve(db)
                self.assert_opaque_rejection(rejected.exception)
                self.assertIsNone(rejected.exception.__cause__)
                self.assertTrue(rejected.exception.__suppress_context__)
                self.assert_request_owns_transaction(db)

    async def test_no_legacy_flag_or_classification_read_and_no_second_decode(self):
        driver = operational_row()
        db, _, _ = database(bridge(), driver)
        with patch.object(deps, "decode_company_token",
                          side_effect=AssertionError("Canonical context already authenticated")) as decode:
            self.assertIs(await self.resolve(db), driver)
        decode.assert_not_called()

    def test_depends_uses_existing_field_authentication_and_request_session(self):
        parameters = inspect.signature(module.get_current_field_legacy_driver).parameters
        self.assertEqual(list(parameters), ["current", "db"])
        self.assertIs(parameters["current"].default.dependency, deps.get_current_field_context)
        self.assertIs(parameters["db"].default.dependency, deps.get_db)
        self.assertTrue(parameters["current"].default.use_cache)
        self.assertTrue(parameters["db"].default.use_cache)

    def application(self, db):
        app, captured = FastAPI(), []

        async def request_db():
            return db

        async def endpoint(
            current=Depends(deps.get_current_field_context),
            driver=Depends(module.get_current_field_legacy_driver),
            session=Depends(deps.get_authenticated_access_session),
        ):
            captured.append((current, driver, session))
            return {"principal_id": current.principal_id, "representative_id": current.representative_id,
                    "legacy_driver_id": driver.id}

        app.dependency_overrides[deps.get_db] = request_db
        app.add_api_route("/field", endpoint)
        return app, captured

    async def test_fastapi_uses_trusted_field_context_and_decodes_only_once(self):
        trusted, driver = field_context(), operational_row()
        db, _, _ = database(bridge(), driver)
        app, captured = self.application(db)
        token = issue_access_token(
            principal_id=trusted.principal_id, company_id=trusted.company_id,
            channel=trusted.channel.value, principal_type=trusted.principal_type.value,
            auth_revision=trusted.auth_revision, secret=SECRET,
        )
        with patch.object(deps, "decode_company_token", wraps=deps.decode_company_token) as decode, \
             patch.object(deps, "resolve_access_context", AsyncMock(return_value=trusted)) as context:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://field.test") as client:
                response = await client.get("/field", headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"principal_id": 101, "representative_id": 202,
                                           "legacy_driver_id": 303})
        current, operational, carrier = captured[0]
        self.assertIs(current, trusted)
        self.assertIs(operational, driver)
        self.assertIs(carrier.context, trusted)
        self.assertEqual(decode.call_count, 1)
        self.assertEqual(context.await_count, 1)
        self.assertEqual(db.scalar.await_count, 1)
        self.assertEqual(db.execute.await_count, 2)
        self.assert_request_owns_transaction(db)

    async def test_http_authentication_denial_never_loads_operational_driver(self):
        dashboard = DashboardRequestContext(
            principal_id=101, company_id=7, backoffice_user_id=202,
            auth_revision=3, is_company_owner=True,
        )
        for authority in (None, dashboard, RequestContextRejected()):
            with self.subTest(authority=type(authority)):
                db, _, _ = database(bridge(), operational_row())
                app, captured = self.application(db)
                resolution = AsyncMock(return_value=authority)
                if isinstance(authority, Exception):
                    resolution.side_effect = authority
                headers = {} if authority is None else {"Authorization": "Bearer synthetic-access"}
                with patch.object(deps, "decode_company_token", return_value=SimpleNamespace(company_id=7)), \
                     patch.object(deps, "resolve_access_context", resolution):
                    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://field.test") as client:
                        response = await client.get("/field", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": deps._AUTH_REJECTION_DETAIL})
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
                self.assertEqual(captured, [])
                db.execute.assert_not_awaited()
                self.assert_request_owns_transaction(db)


if __name__ == "__main__":
    unittest.main()
