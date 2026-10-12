"""Real FastAPI/canonical dependencies and SQLAlchemy queries; persistence is mocked."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import inspect
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
import jwt
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SECRET = "SalesReturnCanonicalSyntheticSecret123456789012345678901234567890"
with patch.dict(os.environ, {
    "ENVIRONMENT": "test", "SECRET_KEY": SECRET,
    "DATABASE_URL": "postgresql+asyncpg://return_unit@127.0.0.1:1/return_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://return_admin@127.0.0.1:1/return_unit",
}):
    from api import sales_returns as module
    from api import dependencies as legacy

from api.authentication.legacy_backoffice_transport import get_legacy_transport_backoffice_context
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.sales_returns import service
from domains.sales_returns.core import SalesReturnError

CAPABILITY = "sales_return.create"
ROUTES = (
    ("GET", "/sales-returns?limit=12&before_id=900", "list_sales_returns",
     dict(limit=12, before_id=900)),
    ("GET", "/sales-returns/sources?search=Shop&limit=13&before_revision_id=701",
     "list_returnable_sales", dict(search="Shop", limit=13, before_revision_id=701,
                                  date_from=None, date_to=None)),
    ("GET", "/sales-returns/source/401", "source_summary", dict(visit_id=401)),
    ("GET", "/sales-returns/501", "get_sales_return", dict(return_id=501)),
    ("POST", "/sales-returns", "create_sales_return", {}),
)


class TransportActor:
    id = 903
    company_id = 77
    is_active = True

    def __init__(self, legacy_flag):
        self._legacy_flag = legacy_flag

    @property
    def is_admin(self):
        raise AssertionError("Legacy Driver flags must never supply authority")


class Bridge(SimpleNamespace):
    @property
    def classification(self):
        raise AssertionError("Bridge classification must never supply authority")


def result(value=None, rows=()):
    synchronous = Mock()
    synchronous.one_or_none.return_value = value
    synchronous.scalar_one_or_none.return_value = value
    synchronous.all.return_value = list(rows)
    synchronous.scalars.return_value = synchronous
    return synchronous


def database():
    db = MagicMock(spec=AsyncSession)
    db.in_transaction.return_value = False
    db.execute.return_value = result()
    db.scalar.return_value = None
    return db


def access(db, *, owner=False):
    return BackofficeCapabilityAccess(db, BackofficeAuthorizationSubject(
        principal_id=101, backoffice_user_id=202, company_id=77,
        is_company_owner=owner, legacy_grant_driver_id=None if owner else 903,
    ))


def payload():
    return module.SalesReturnCreate(
        request_id=uuid4(), original_sales_revision_id=701, reason="Return reason",
        components=[dict(original_price_component_id=501, quantity="1")],
    )


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class SalesReturnsCanonicalCutoverTests(unittest.IsolatedAsyncioTestCase):
    def assert_no_transaction_mutation(self, db):
        for name in ("commit", "rollback", "begin", "begin_nested", "flush", "add", "delete"):
            getattr(db, name).assert_not_called()

    async def test_ordinary_backoffice_exact_company_capability_uses_independent_grant_locator(self):
        db = database()
        db.scalar.return_value = True
        current = access(db)
        self.assertIs(await module._sales_return_access(current), current)
        query = sql(db.scalar.await_args.args[0])
        for condition in ("user_roles.company_id = 77", "user_roles.driver_id = 903",
                          "role_permissions.company_id = 77", "'sales_return.create'"):
            self.assertIn(condition, query)
        self.assertNotIn("user_location_access", query)
        self.assertNotIn("drivers.", query)
        db.scalar.assert_awaited_once()
        self.assert_no_transaction_mutation(db)

    async def test_missing_company_capability_fails_opaque_403_without_location_grant_fallback(self):
        db = database()
        db.scalar.return_value = False
        with self.assertRaises(HTTPException) as denied:
            await module._sales_return_access(access(db))
        self.assertEqual((denied.exception.status_code, denied.exception.detail),
                         (403, "Authorization denied."))
        self.assertNotIn("user_location_access", sql(db.scalar.await_args.args[0]))
        self.assert_no_transaction_mutation(db)

    async def test_owner_succeeds_through_central_canonical_owner_state_without_grant_lookup(self):
        db = database()
        current = access(db, owner=True)
        self.assertIs(await module._sales_return_access(current), current)
        db.scalar.assert_not_awaited()
        self.assert_no_transaction_mutation(db)

    async def request_route(self, route, *, owner, allowed, legacy_flag, identity_problem=None):
        method, path, service_name, filters = route
        db = database()
        actor = TransportActor(legacy_flag)
        authentication_result = result((actor, False))
        db.execute.return_value = authentication_result
        bridge = Bridge(company_id=77, legacy_driver_id=903, backoffice_principal_id=101,
                        backoffice_user_id=202)
        principal = SimpleNamespace(company_id=77, id=101, principal_type="BACKOFFICE",
                                    is_active=True, auth_revision=4)
        profile = SimpleNamespace(company_id=77, id=202, principal_id=101, principal_type="BACKOFFICE")
        persisted_owner = SimpleNamespace(company_id=77, backoffice_user_id=202) if owner else None
        if identity_problem == "missing":
            db.scalar.side_effect = [None]
        elif identity_problem == "cross_company":
            bridge.company_id = 88
            db.scalar.side_effect = [bridge]
        elif identity_problem == "field":
            principal.principal_type = "FIELD_REPRESENTATIVE"
            db.scalar.side_effect = [bridge, principal]
        else:
            db.scalar.side_effect = [bridge, principal, profile, persisted_owner] + (
                [] if owner else [bridge, allowed]
            )

        app = FastAPI()
        app.include_router(module.router)
        db_calls = []

        async def override_db():
            db_calls.append(True)
            return db

        app.dependency_overrides[get_db] = override_db
        request = payload()
        token = jwt.encode(dict(
            sub="903", company_id=77, type="access", role="Owner", is_admin=True,
            exp=datetime.now(timezone.utc) + timedelta(minutes=5),
        ), SECRET, algorithm="HS256")
        previous = legacy.tenant_context.set(None)
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(legacy.Config, "SECRET_KEY", SECRET))
                decode = stack.enter_context(patch.object(legacy.jwt, "decode", wraps=jwt.decode))
                services = {
                    name: stack.enter_context(patch.object(module, name, new=AsyncMock(
                        return_value={"service": name}
                    )))
                    for name in {entry[2] for entry in ROUTES}
                }
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    response = await client.request(
                        method, path, headers={"Authorization": f"Bearer {token}"},
                        **({"json": request.model_dump(mode="json")} if method == "POST" else {}),
                    )
        finally:
            legacy.tenant_context.reset(previous)

        rejected_identity = identity_problem is not None
        authorized = not rejected_identity and (owner or allowed)
        expected = 401 if rejected_identity else (201 if method == "POST" else 200) if authorized else 403
        self.assertEqual(response.status_code, expected, response.text)
        decode.assert_called_once()
        authentication_result.one_or_none.assert_called_once_with()
        self.assertEqual(db.execute.await_count, 1, "No second legacy actor/JWT authentication on POST")
        self.assertEqual(len(db_calls), 1)
        for name, call in services.items():
            if authorized and name == service_name:
                call.assert_awaited_once()
                self.assertEqual(call.await_args.args, (db,))
                self.assertEqual(call.await_args.kwargs["company_id"], 77)
                for key, value in filters.items():
                    self.assertEqual(call.await_args.kwargs[key], value)
                if method == "POST":
                    self.assertEqual(call.await_args.kwargs["actor_id"], 903)
                    self.assertEqual(call.await_args.kwargs["payload"], request)
                    self.assertEqual(len({77, 101, 202, call.await_args.kwargs["actor_id"]}), 4)
                else:
                    self.assertNotIn("actor_id", call.await_args.kwargs)
            else:
                call.assert_not_awaited()
        if not rejected_identity and not owner:
            self.assertEqual(db.scalar.await_count, 6)
            grant_query = sql(db.scalar.await_args.args[0])
            self.assertIn("'sales_return.create'", grant_query)
            self.assertIn("user_roles.company_id = 77", grant_query)
            self.assertIn("user_roles.driver_id = 903", grant_query)
            self.assertNotIn("user_location_access", grant_query)
            mapping_query = sql(db.scalar.await_args_list[4].args[0])
            for condition in ("company_id = 77", "backoffice_principal_id = 101", "backoffice_user_id = 202"):
                self.assertIn(condition, mapping_query)
        if authorized and method == "POST":
            db.commit.assert_awaited_once_with()
        else:
            db.commit.assert_not_awaited()
        db.rollback.assert_not_awaited()
        db.begin.assert_not_called()
        db.begin_nested.assert_not_called()
        db.flush.assert_not_awaited()
        db.add.assert_not_called()
        if not authorized and not rejected_identity:
            self.assertEqual(response.json(), {"detail": "Authorization denied."})

    async def test_all_five_real_routes_allow_capability_or_canonical_owner_and_ignore_driver_flags(self):
        for owner in (False, True):
            for legacy_flag in (False, True):
                for route in ROUTES:
                    with self.subTest(owner=owner, legacy_flag=legacy_flag, route=route[:2]):
                        await self.request_route(route, owner=owner, allowed=True, legacy_flag=legacy_flag)

    async def test_all_five_real_routes_deny_missing_capability_despite_legacy_flag_and_owner_token_claim(self):
        for legacy_flag in (False, True):
            for route in ROUTES:
                with self.subTest(legacy_flag=legacy_flag, route=route[:2]):
                    await self.request_route(route, owner=False, allowed=False, legacy_flag=legacy_flag)

    async def test_missing_cross_company_and_field_identity_fail_before_service_or_transaction(self):
        for problem in ("missing", "cross_company", "field"):
            with self.subTest(problem=problem):
                await self.request_route(ROUTES[-1], owner=False, allowed=True,
                                         legacy_flag=True, identity_problem=problem)

    def test_get_routes_have_no_explicit_legacy_actor_dependency_and_post_reuses_cached_transport(self):
        for endpoint in (module.list_returns, module.returnable_sales, module.return_source, module.return_detail):
            parameters = inspect.signature(endpoint).parameters
            self.assertNotIn("legacy_actor", parameters)
            self.assertIs(parameters["access"].default.dependency, module._sales_return_access)
        post = inspect.signature(module.post_return).parameters["legacy_actor"].default
        upstream = inspect.signature(get_legacy_transport_backoffice_context).parameters["current_driver"].default
        self.assertIs(post.dependency, legacy.get_current_driver)
        self.assertIs(upstream.dependency, post.dependency)
        self.assertTrue(post.use_cache)
        self.assertTrue(upstream.use_cache)

    async def test_actual_source_and_return_queries_reject_foreign_objects_by_canonical_company(self):
        for function, kwargs, table, locator, error_code in (
            (service.source_summary, dict(visit_id=401), "visits", "id = 401", "SALES_RETURN_SOURCE_NOT_FOUND"),
            (service.get_sales_return, dict(return_id=501), "sales_return_documents", "id = 501", "SALES_RETURN_NOT_FOUND"),
        ):
            with self.subTest(function=function.__name__):
                db = database()
                db.execute.return_value = result(None)
                with self.assertRaises(SalesReturnError) as denied:
                    await function(db, company_id=77, **kwargs)
                self.assertEqual(denied.exception.status_code, 404)
                self.assertEqual(denied.exception.code, error_code)
                query = sql(db.execute.await_args.args[0])
                self.assertIn(f"{table}.company_id = 77", query)
                self.assertIn(f"{table}.{locator}", query)
                db.execute.assert_awaited_once()
                self.assert_no_transaction_mutation(db)

    async def test_original_source_revision_requires_current_completed_sale_frozen_evidence_and_row_locks(self):
        visit = SimpleNamespace(id=401)
        for frozen in (None, datetime.now(timezone.utc)):
            with self.subTest(frozen=frozen):
                db = database()
                revision = SimpleNamespace(frozen_at=frozen)
                db.execute.side_effect = [result(visit), result(revision)]
                if frozen is None:
                    with self.assertRaises(SalesReturnError) as denied:
                        await service._source_visit_revision(db, company_id=77, revision_id=701, lock=True)
                    self.assertEqual(denied.exception.code, "SALES_RETURN_SOURCE_NOT_FROZEN")
                else:
                    self.assertEqual(await service._source_visit_revision(
                        db, company_id=77, revision_id=701, lock=True), (visit, revision))
                visit_query, revision_query = [sql(call.args[0]) for call in db.execute.await_args_list]
                for condition in ("visits.company_id = 77", "visits.current_sales_revision_id = 701",
                                  "visits.status = 'Completed'", "visits.outcome = 'Sale'", "FOR UPDATE OF visits"):
                    self.assertIn(condition, visit_query)
                for condition in ("sales_visit_revisions.company_id = 77", "sales_visit_revisions.id = 701",
                                  "sales_visit_revisions.visit_id = 401", "FOR UPDATE"):
                    self.assertIn(condition, revision_query)
                self.assert_no_transaction_mutation(db)

    async def test_existing_idempotency_replay_and_conflicting_hash_preserve_first_advisory_lock(self):
        request = payload()
        for matching in (False, True):
            with self.subTest(matching=matching):
                db = database()
                existing = SimpleNamespace(id=801, request_hash=service._request_hash(request) if matching else "different")
                db.execute.side_effect = [result(), result(existing)]
                with patch.object(service, "get_sales_return", new=AsyncMock(return_value={"id": 801})) as detail:
                    if matching:
                        self.assertEqual(await service.create_sales_return(
                            db, company_id=77, actor_id=903, payload=request), {"id": 801})
                        detail.assert_awaited_once_with(db, company_id=77, return_id=801)
                    else:
                        with self.assertRaises(SalesReturnError) as denied:
                            await service.create_sales_return(db, company_id=77, actor_id=903, payload=request)
                        self.assertEqual(denied.exception.code, "SALES_RETURN_REQUEST_REUSED")
                        detail.assert_not_awaited()
                lock, lookup = [call.args[0] for call in db.execute.await_args_list]
                self.assertIn("pg_advisory_xact_lock", sql(lock))
                self.assertIn(77, lock.compile().params.values())
                self.assertIn(str(request.request_id), lock.compile().params.values())
                self.assertIn("sales_return_documents.company_id = 77", sql(lookup))
                self.assertIn("sales_return_documents.request_id", sql(lookup))
                self.assert_no_transaction_mutation(db)

    async def test_idempotency_is_rechecked_after_actual_source_row_locks_before_new_evidence(self):
        db = database()
        request = payload()
        existing = SimpleNamespace(id=801, request_hash=service._request_hash(request))
        visit = SimpleNamespace(id=401)
        revision = SimpleNamespace(frozen_at=datetime.now(timezone.utc))
        db.execute.side_effect = [result(), result(None), result(visit), result(revision), result(existing)]
        with patch.object(service, "get_sales_return", new=AsyncMock(return_value={"id": 801})) as detail:
            self.assertEqual(await service.create_sales_return(
                db, company_id=77, actor_id=903, payload=request), {"id": 801})
        detail.assert_awaited_once_with(db, company_id=77, return_id=801)
        queries = [sql(call.args[0]) for call in db.execute.await_args_list]
        self.assertEqual(len(queries), 5)
        self.assertIn("pg_advisory_xact_lock", queries[0])
        self.assertIn("FOR UPDATE OF visits", queries[2])
        self.assertIn("FOR UPDATE", queries[3])
        self.assertIn("sales_return_documents.company_id = 77", queries[4])
        self.assert_no_transaction_mutation(db)

    async def test_foreign_price_component_is_rejected_before_any_return_evidence_write(self):
        db = database()
        visit = SimpleNamespace(id=401)
        revision = SimpleNamespace(frozen_at=datetime.now(timezone.utc))
        db.execute.side_effect = [result(), result(None), result(visit), result(revision), result(None), result(rows=[])]
        with self.assertRaises(SalesReturnError) as denied:
            await service.create_sales_return(db, company_id=77, actor_id=903, payload=payload())
        self.assertEqual(denied.exception.code, "SALES_RETURN_SOURCE_COMPONENT_INVALID")
        self.assertEqual(denied.exception.status_code, 404)
        query = sql(db.execute.await_args.args[0])
        self.assertIn("sales_line_price_components.company_id = 77", query)
        self.assertIn("sales_line_price_components.id IN (501)", query)
        self.assert_no_transaction_mutation(db)


if __name__ == "__main__":
    unittest.main()
