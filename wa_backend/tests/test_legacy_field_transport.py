"""Canonical Field dependency graph acceptance after legacy transport retirement.

The historical filename remains a focused test anchor. Probes compile the exact
authentication arguments from all twelve production functions, while business
bodies are covered by full-body parity gates and the session execution tests.
No identity/context/subject resolver is patched here; only DB results are mocked.
"""
import ast
import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
import jwt
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
SECRET = "FieldRuntimeCutoverSyntheticSecret123456789012345678901234567890"
with patch.dict(os.environ, {
    "ENVIRONMENT": "test", "SECRET_KEY": SECRET,
    "DATABASE_URL": "postgresql+asyncpg://field_unit@127.0.0.1:1/field_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://field_admin@127.0.0.1:1/field_unit",
}):
    from api.authentication import dependencies as canonical
    from api.authentication import field_compatibility as compatibility

from database import get_db
from domains.auth_sessions.codec import issue_access_token
from domains.auth_sessions.context import FieldRequestContext
from models import Driver

TARGETS = (
    "start_work_session", "end_work_session", "toggle_break", "update_visit",
    "get_driver_dashboard", "respond_to_transfer", "batch_respond_to_transfers",
    "get_pending_transfers", "add_new_shop", "get_products",
    "get_driver_visits", "get_active_session",
)


class Bridge(SimpleNamespace):
    @property
    def classification(self):
        raise AssertionError("Bridge classification is not authentication authority")


class OperationalRow(SimpleNamespace):
    @property
    def is_admin(self):
        raise AssertionError("Driver flags are not authentication authority")


def bridge(**changes):
    values = dict(company_id=7, field_principal_id=101, field_representative_id=202,
                  legacy_driver_id=303, backoffice_principal_id=None, backoffice_user_id=None)
    values.update(changes)
    return Bridge(**values)


def actor(**changes):
    values = dict(id=303, company_id=7, is_active=True)
    values.update(changes)
    return OperationalRow(**values)


def database(mapping, driver, *, dashboard=False):
    mapping_result, driver_result = Mock(), Mock()
    mapping_result.one_or_none.return_value = mapping
    driver_result.scalar_one_or_none.return_value = driver
    db = MagicMock(spec=AsyncSession)
    db.in_transaction.return_value = False
    db.execute.side_effect = [mapping_result, driver_result]
    principal_type = "BACKOFFICE" if dashboard else "FIELD_REPRESENTATIVE"
    principal = SimpleNamespace(id=101, company_id=7, is_active=True,
                                auth_revision=13, principal_type=principal_type)
    profile = SimpleNamespace(id=505 if dashboard else 202, company_id=7,
                              principal_id=101, principal_type=principal_type)
    # Real canonical repositories: blacklist, active company, principal, profile.
    persisted = [False, SimpleNamespace(id=7, is_active=True), principal, profile]
    if dashboard:
        persisted.append(SimpleNamespace(company_id=7, backoffice_user_id=505))
    db.scalar.side_effect = persisted
    return SimpleNamespace(db=db, mapping=mapping_result, driver=driver_result,
                           principal=principal, profile=profile, persisted=persisted)


def application(db, *, actor_first=False):
    tree = ast.parse((BACKEND / "api" / "driver.py").read_text(encoding="utf-8"))
    probe_body = ast.parse("""
async def probe():
    return dict(company_id=field_context.company_id,
                principal_id=field_context.principal_id,
                representative_id=field_context.representative_id,
                legacy_driver_id=legacy_actor.id)
""").body[0].body
    namespace = dict(
        Depends=Depends, AsyncSession=AsyncSession, FieldRequestContext=FieldRequestContext,
        Driver=Driver, get_db=get_db,
        get_current_field_context=canonical.get_current_field_context,
        get_current_field_legacy_driver=compatibility.get_current_field_legacy_driver,
    )
    app = FastAPI()

    async def request_db():
        return db

    app.dependency_overrides[get_db] = request_db
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef) or node.name not in TARGETS:
            continue
        probe = copy.deepcopy(node)
        defaults = dict(zip([arg.arg for arg in probe.args.args][-len(probe.args.defaults):],
                            probe.args.defaults))
        arguments = [arg for arg in probe.args.args
                     if arg.arg in {"db", "field_context", "legacy_actor"}]
        if actor_first:
            arguments.reverse()
        probe.args = ast.arguments(posonlyargs=[], args=arguments, kwonlyargs=[],
                                   kw_defaults=[], defaults=[defaults[arg.arg] for arg in arguments])
        probe.decorator_list = []
        probe.body = copy.deepcopy(probe_body)
        ast.fix_missing_locations(probe)
        exec(compile(ast.Module(body=[probe], type_ignores=[]), str(BACKEND / "api" / "driver.py"),
                     "exec", dont_inherit=True), namespace)
        app.add_api_route("/" + node.name, namespace[node.name], methods=["GET"])
    return app


def token(*, dashboard=False):
    return issue_access_token(principal_id=101, company_id=7, auth_revision=13,
                              channel="DASHBOARD" if dashboard else "FIELD",
                              principal_type="BACKOFFICE" if dashboard else "FIELD_REPRESENTATIVE",
                              secret=SECRET)


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(),
                                 compile_kwargs={"literal_binds": True}))


class FieldRuntimeTransportCutoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        secret = patch.object(canonical.Config, "SECRET_KEY", SECRET)
        secret.start()
        self.addCleanup(secret.stop)
        previous = canonical.tenant_context.set(None)
        self.addCleanup(canonical.tenant_context.reset, previous)

    def assert_request_owns_transaction(self, db):
        for name in ("commit", "rollback", "begin", "begin_nested", "flush", "add", "delete"):
            getattr(db, name).assert_not_called()

    def assert_opaque(self, response):
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json(), {"detail": canonical._AUTH_REJECTION_DETAIL})
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    async def request(self, setup, name, raw=None, *, actor_first=False):
        app = application(setup.db, actor_first=actor_first)
        headers = {} if raw is None else {"Authorization": "Bearer " + raw}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://field.test") as client:
            return await client.get("/" + name, headers=headers)

    async def test_all_twelve_graphs_accept_field_only_mapping_with_distinct_ids_and_either_legacy_flag(self):
        for name in TARGETS:
            for flag in (False, True):
                with self.subTest(endpoint=name, operational_flag=flag):
                    current = Driver(id=303, company_id=7, is_active=True, is_admin=flag)
                    setup = database(bridge(), current)
                    raw = token()
                    with patch.object(canonical, "decode_company_token",
                                      wraps=canonical.decode_company_token) as decode:
                        response = await self.request(setup, name, raw)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json(), dict(company_id=7, principal_id=101,
                                                           representative_id=202, legacy_driver_id=303))
                    decode.assert_called_once_with(raw, secret=SECRET, expected_type="access")
                    self.assertEqual(setup.db.scalar.await_count, 4)
                    self.assertEqual(setup.db.execute.await_count, 2)
                    setup.mapping.one_or_none.assert_called_once_with()
                    setup.driver.scalar_one_or_none.assert_called_once_with()
                    setup.db.connection.assert_awaited_once_with()
                    mapping, operational = [call.args[0] for call in setup.db.execute.await_args_list]
                    self.assertEqual([(item.left.name, item.right.value)
                                      for item in mapping.whereclause.clauses],
                                     [("company_id", 7), ("field_principal_id", 101),
                                      ("field_representative_id", 202)])
                    self.assertEqual([(item.left.name, item.right.value)
                                      for item in operational.whereclause.clauses],
                                     [("company_id", 7), ("id", 303)])
                    self.assertNotIn("classification", sql(mapping))
                    self.assertNotIn("is_admin", sql(mapping) + sql(operational.whereclause))
                    self.assert_request_owns_transaction(setup.db)

    async def test_dashboard_even_company_owner_is_rejected_before_operational_mapping_on_every_route(self):
        for name in TARGETS:
            with self.subTest(endpoint=name):
                setup = database(bridge(), actor(), dashboard=True)
                response = await self.request(setup, name, token(dashboard=True))
                self.assert_opaque(response)
                setup.db.execute.assert_not_awaited()
                self.assert_request_owns_transaction(setup.db)

    async def test_missing_inactive_mismatched_identity_and_revision_fail_closed_upstream(self):
        cases = ("company_missing_or_inactive", "principal_missing", "principal_inactive",
                 "principal_company", "principal_id", "wrong_principal_type", "revision",
                 "profile_missing", "profile_company", "profile_principal", "wrong_profile_type",
                 "blacklisted")
        for reason in cases:
            with self.subTest(reason=reason):
                setup = database(bridge(), actor())
                if reason == "company_missing_or_inactive":
                    setup.persisted[1] = None
                elif reason == "principal_missing":
                    setup.persisted[2] = None
                elif reason == "principal_inactive":
                    setup.principal.is_active = False
                elif reason == "principal_company":
                    setup.principal.company_id = 8
                elif reason == "principal_id":
                    setup.principal.id = 303
                elif reason == "wrong_principal_type":
                    setup.principal.principal_type = "BACKOFFICE"
                elif reason == "revision":
                    setup.principal.auth_revision = 14
                elif reason == "profile_missing":
                    setup.persisted[3] = None
                elif reason == "profile_company":
                    setup.profile.company_id = 8
                elif reason == "profile_principal":
                    setup.profile.principal_id = 303
                elif reason == "wrong_profile_type":
                    setup.profile.principal_type = "BACKOFFICE"
                else:
                    setup.persisted[0] = True
                # Reassign after list mutations: AsyncMock consumes an iterator.
                setup.db.scalar.side_effect = setup.persisted
                response = await self.request(setup, "get_active_session", token())
                self.assert_opaque(response)
                setup.db.execute.assert_not_awaited()
                self.assert_request_owns_transaction(setup.db)

    async def test_missing_ambiguous_cross_company_and_wrong_field_bridge_fail_closed(self):
        invalid = (None, bridge(company_id=8), bridge(field_principal_id=303),
                   bridge(field_representative_id=303),
                   bridge(field_principal_id=None, field_representative_id=None),
                   bridge(legacy_driver_id=None))
        for mapping in invalid:
            with self.subTest(mapping=mapping):
                setup = database(mapping, actor())
                response = await self.request(setup, "get_active_session", token())
                self.assert_opaque(response)
                self.assertEqual(setup.db.execute.await_count, 1)
                setup.driver.scalar_one_or_none.assert_not_called()
                self.assert_request_owns_transaction(setup.db)
        setup = database(bridge(), actor())
        setup.mapping.one_or_none.side_effect = MultipleResultsFound("synthetic internal identity")
        self.assert_opaque(await self.request(setup, "get_active_session", token()))
        setup.driver.scalar_one_or_none.assert_not_called()
        self.assert_request_owns_transaction(setup.db)

    async def test_missing_inactive_foreign_and_wrong_operational_rows_cannot_authorize(self):
        for current in (None, actor(is_active=False), actor(company_id=8),
                        actor(id=101), actor(id=202)):
            with self.subTest(actor=current):
                setup = database(bridge(), current)
                self.assert_opaque(await self.request(setup, "get_active_session", token()))
                self.assertEqual(setup.db.execute.await_count, 2)
                self.assert_request_owns_transaction(setup.db)
        setup = database(bridge(), actor())
        setup.driver.scalar_one_or_none.side_effect = MultipleResultsFound("synthetic internal rows")
        self.assert_opaque(await self.request(setup, "get_active_session", token()))
        self.assert_request_owns_transaction(setup.db)

    async def test_no_admin_or_bridge_classification_reads_and_cache_works_in_both_orders(self):
        for actor_first in (False, True):
            with self.subTest(actor_first=actor_first):
                setup = database(bridge(), actor())
                with patch.object(canonical, "decode_company_token",
                                  wraps=canonical.decode_company_token) as decode:
                    response = await self.request(setup, "update_visit", token(), actor_first=actor_first)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["legacy_driver_id"], 303)
                decode.assert_called_once()
                self.assertEqual(setup.db.scalar.await_count, 4)
                self.assertEqual(setup.db.execute.await_count, 2)
                self.assert_request_owns_transaction(setup.db)

    async def test_missing_expired_or_legacy_driver_subject_token_is_rejected_before_any_db_use(self):
        legacy = jwt.encode(dict(sub="303", company_id=7, type="access",
                                 exp=datetime.now(timezone.utc) + timedelta(minutes=5)),
                            SECRET, algorithm="HS256")
        expired = issue_access_token(principal_id=101, company_id=7, channel="FIELD",
                                     principal_type="FIELD_REPRESENTATIVE", auth_revision=13,
                                     secret=SECRET, now=datetime.now(timezone.utc) - timedelta(hours=1))
        for raw in (None, legacy, expired, "malformed"):
            with self.subTest(token_kind="missing" if raw is None else "invalid"):
                setup = database(bridge(), actor())
                self.assert_opaque(await self.request(setup, "get_active_session", raw))
                setup.db.scalar.assert_not_awaited()
                setup.db.execute.assert_not_awaited()
                setup.db.connection.assert_not_awaited()
                self.assert_request_owns_transaction(setup.db)


if __name__ == "__main__":
    unittest.main()
