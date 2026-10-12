"""Execute the three unchanged route bodies with real SQL and dependency caching.

Load only the selected source functions so unrelated driver workflows are not
imported. SQLAlchemy results and external business services are mocked; the
FastAPI dependency graph and canonical operational mapping are real.
"""
import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
SECRET = "SessionFieldCutoverSyntheticSecret123456789012345678901234567890"
with patch.dict(os.environ, {
    "ENVIRONMENT": "test", "SECRET_KEY": SECRET,
    "DATABASE_URL": "postgresql+asyncpg://session_unit@127.0.0.1:1/session_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://session_admin@127.0.0.1:1/session_unit",
}):
    from api.authentication import dependencies as canonical
    from api.authentication import field_compatibility as compatibility

from database import get_db
from domains.auth_sessions.codec import issue_access_token
from domains.auth_sessions.context import FieldRequestContext
from domains.pricing.core import PricingError
from models import (
    DispatchRoute, Driver, InventoryBalance, InventoryLocation,
    InventoryTransferHeader, SessionInventorySnapshot, Shop, Visit,
    WorkBreakLog, WorkSession,
)
from quantity import QUANTITY_MAX
from schemas import BreakToggleRequest, SessionStartRequest

CONTEXT = FieldRequestContext(101, 7, 202, 13)
NOW = datetime(2026, 10, 12, 10, 0)
LOCAL_DATE = date(2026, 10, 12)
ENDPOINTS = {
    "start_work_session": ("POST", "/driver/sessions/start", 201),
    "end_work_session": ("PUT", "/driver/sessions/end", 200),
    "toggle_break": ("PUT", "/driver/sessions/break", 200),
}


class OperationalLocator:
    id = 303

    @property
    def company_id(self):
        raise AssertionError("The endpoint must use canonical company authority")

    @property
    def is_admin(self):
        raise AssertionError("The endpoint must not classify an operational actor")


class Bridge(SimpleNamespace):
    @property
    def classification(self):
        raise AssertionError("Bridge labels are not Field identity authority")


def load_routes():
    tree = ast.parse((BACKEND / "api" / "driver.py").read_text(encoding="utf-8"))
    names = {*ENDPOINTS, "_require_driver_mobile_integral_quantity"}
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    namespace = dict(globals())
    namespace.update(
        router=APIRouter(), logger=Mock(),
        get_current_field_context=canonical.get_current_field_context,
        get_current_field_legacy_driver=compatibility.get_current_field_legacy_driver,
        get_company_local_date=AsyncMock(return_value=LOCAL_DATE),
        require_route_commercial_context=AsyncMock(return_value=SimpleNamespace(id=1001)),
        commercial_context_payload=Mock(return_value={"id": 1001}),
        acquire_inventory_location_guard=AsyncMock(), get_utc_now=Mock(return_value=NOW),
    )
    # Keep the real decorators, annotations, signatures and function bodies.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BACKEND / "api" / "driver.py"),
                 "exec", dont_inherit=True), namespace)
    return namespace


def result(value=None, rows=()):
    synchronous = Mock()
    synchronous.scalar_one_or_none.return_value = value
    synchronous.scalars.return_value.first.return_value = value
    synchronous.one_or_none.return_value = value
    synchronous.all.return_value = list(rows)
    return synchronous


def fixture(name):
    db = MagicMock(spec=AsyncSession)
    db.in_transaction.return_value = False
    db.scalar.return_value = False
    session = SimpleNamespace(id=601, company_id=7, driver_id=303, end_time=None,
                              break_start_time=None, break_end_time=None, is_settled=False)
    route = SimpleNamespace(id=701, vehicle_id=801, zone_id=901, work_session_id=None)
    if name == "start_work_session":
        results = [result(OperationalLocator()), result(), result(route), result(),
                   result(501), result(501),
                   result(rows=[(1111, "AVAILABLE", Decimal("5")),
                                (1112, "QUARANTINED", Decimal("0.5"))]), result()]

        async def assign_session_id():
            next(call.args[0] for call in db.add.call_args_list
                 if isinstance(call.args[0], WorkSession)).id = 601

        db.flush.side_effect = assign_session_id
    else:
        results = [result(session)]
        if name == "end_work_session":
            results.append(result())
    # AsyncSession.execute returns synchronous Result objects, never AsyncMocks.
    db.execute.side_effect = results
    return SimpleNamespace(db=db, results=results, session=session, route=route)


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class DriverSessionFieldContextCutoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.namespace = load_routes()
        setting = patch.object(canonical.Config, "SECRET_KEY", SECRET)
        setting.start()
        self.addCleanup(setting.stop)
        previous = canonical.tenant_context.set(None)
        self.addCleanup(canonical.tenant_context.reset, previous)

    async def invoke(self, name, setup, actor=None, action="start"):
        kwargs = dict(db=setup.db, field_context=CONTEXT,
                      legacy_actor=actor if actor is not None else OperationalLocator())
        if name == "start_work_session":
            kwargs["payload"] = SessionStartRequest(latitude=31.9, longitude=35.9)
        elif name == "toggle_break":
            kwargs["payload"] = SimpleNamespace(action=action)
        return await self.namespace[name](**kwargs)

    def assert_transactions(self, db, *, commits=1, rollbacks=0):
        self.assertEqual(db.commit.await_count, commits)
        self.assertEqual(db.rollback.await_count, rollbacks)
        db.begin.assert_not_called()
        db.begin_nested.assert_not_called()

    def assert_scoped_legacy_query(self, statement, table):
        where = sql(statement.whereclause)
        self.assertIn(f"{table}.company_id = 7", where)
        self.assertIn(f"{table}.driver_id = 303", where)
        self.assertNotIn(f"{table}.driver_id = 101", where)
        self.assertNotIn(f"{table}.driver_id = 202", where)

    async def test_start_uses_canonical_company_independent_ids_and_preserves_snapshot_visit_path(self):
        setup = fixture("start_work_session")
        response = await self.invoke("start_work_session", setup)
        db = setup.db
        self.assertEqual(response["session_id"], 601)
        self.assertEqual(response["commercial_context"], {"id": 1001})
        added = [call.args[0] for call in db.add.call_args_list]
        session = added[0]
        self.assertIsInstance(session, WorkSession)
        self.assertEqual((session.company_id, session.driver_id, session.commercial_context_id), (7, 303, 1001))
        self.assertEqual((session.session_date, session.start_time), (LOCAL_DATE, NOW))
        self.assertEqual((session.start_latitude, session.start_longitude), (31.9, 35.9))
        self.assertFalse(session.is_authorized_to_sell)
        self.assertEqual(setup.route.work_session_id, 601)
        self.assertTrue(all(isinstance(item, SessionInventorySnapshot) for item in added[1:]))
        self.assertEqual([(item.company_id, item.work_session_id, item.location_id,
                           item.product_variant_id, item.stock_status, item.starting_quantity)
                          for item in added[1:]],
                         [(7, 601, 501, 1111, "AVAILABLE", Decimal("5")),
                          (7, 601, 501, 1112, "QUARANTINED", Decimal("0.5"))])
        queries = [call.args[0] for call in db.execute.await_args_list]
        self.assertEqual(len(queries), 8)
        self.assertEqual(sql(queries[0].whereclause), "drivers.company_id = 7 AND drivers.id = 303")
        for index, table in ((1, "work_sessions"), (2, "dispatch_routes"), (3, "work_sessions"), (7, "visits")):
            self.assert_scoped_legacy_query(queries[index], table)
        self.assertIn("work_sessions.is_settled IS false", sql(queries[1]))
        self.assertIn("work_sessions.end_time IS NOT NULL", sql(queries[1]))
        self.assertIn("dispatch_routes.dispatch_date = '2026-10-12'", sql(queries[2]))
        self.assertIn("dispatch_routes.status = 'active'", sql(queries[2]))
        for index in (0, 2, 3, 5):
            self.assertIsNotNone(queries[index]._for_update_arg)
            self.assertEqual(queries[index]._for_update_arg.read, index == 5)
        for index in (4, 5):
            location_sql = sql(queries[index])
            for condition in ("inventory_locations.company_id = 7", "inventory_locations.vehicle_id = 801",
                              "inventory_locations.location_type = 'VEHICLE'", "inventory_locations.is_active = true"):
                self.assertIn(condition, location_sql)
        self.assertIn("inventory_balances.company_id = 7", sql(queries[6]))
        self.assertIn("inventory_balances.location_id = 501", sql(queries[6]))
        self.assertIn("work_session_id=601", sql(queries[7]))
        self.assertIn("shops.company_id = 7", sql(queries[7]))
        self.namespace["get_company_local_date"].assert_awaited_once_with(db, 7)
        self.namespace["require_route_commercial_context"].assert_awaited_once_with(db, company_id=7, dispatch_route_id=701)
        self.namespace["acquire_inventory_location_guard"].assert_awaited_once_with(db, 7, 501, exclusive=True)
        db.flush.assert_awaited_once_with()
        self.assert_transactions(db)

    async def test_all_three_flows_ignore_operational_company_and_both_admin_flags(self):
        for name in ENDPOINTS:
            for flag in (False, True):
                with self.subTest(endpoint=name, operational_flag=flag):
                    self.namespace = load_routes()
                    setup = fixture(name)
                    # Deliberately conflicting operational company: endpoint scopes remain canonical.
                    actor = SimpleNamespace(id=303, company_id=999, is_active=True, is_admin=flag)
                    await self.invoke(name, setup, actor)
                    query = setup.db.execute.await_args_list[0].args[0]
                    self.assertIn("company_id = 7", sql(query.whereclause))
                    self.assertNotIn("company_id = 999", sql(query.whereclause))
                    self.assert_transactions(setup.db)

    async def test_start_rejects_unsettled_custody_before_route_lookup(self):
        setup = fixture("start_work_session")
        setup.results[1].scalars.return_value.first.return_value = SimpleNamespace(id=600)
        with self.assertRaises(HTTPException) as rejected:
            await self.invoke("start_work_session", setup)
        self.assertEqual(rejected.exception.status_code, 400)
        self.assertEqual(setup.db.execute.await_count, 2)
        setup.db.add.assert_not_called()
        setup.db.flush.assert_not_awaited()
        self.assert_transactions(setup.db, commits=0, rollbacks=2)

    async def test_start_retains_driver_route_vehicle_and_active_session_guards(self):
        cases = (("missing_driver", 0, 403), ("missing_route", 2, 400),
                 ("missing_vehicle", 2, 409), ("route_already_linked", 2, 409),
                 ("active_session", 3, 409), ("missing_location", 4, 409),
                 ("location_changed", 5, 409))
        for reason, index, status in cases:
            with self.subTest(reason=reason):
                self.namespace = load_routes()
                setup = fixture("start_work_session")
                if reason == "missing_vehicle":
                    setup.route.vehicle_id = None
                elif reason == "route_already_linked":
                    setup.route.work_session_id = 999
                else:
                    setup.results[index] = result(SimpleNamespace(id=999) if reason == "active_session" else None)
                with self.assertRaises(HTTPException) as rejected:
                    await self.invoke("start_work_session", setup)
                self.assertEqual(rejected.exception.status_code, status)
                self.assertEqual(setup.db.execute.await_count, index + 1)
                setup.db.add.assert_not_called()
                setup.db.flush.assert_not_awaited()
                self.assert_transactions(setup.db, commits=0, rollbacks=2)

    async def test_end_uses_canonical_company_and_legacy_handshake_receiver_without_settling(self):
        setup = fixture("end_work_session")
        await self.invoke("end_work_session", setup)
        active, handshake = [call.args[0] for call in setup.db.execute.await_args_list]
        self.assert_scoped_legacy_query(active, "work_sessions")
        self.assertIn("work_sessions.end_time IS NULL", sql(active))
        self.assertIn("ORDER BY work_sessions.id DESC", sql(active))
        self.assertIsNotNone(active._for_update_arg)
        for condition in ("inventory_transfer_headers.company_id = 7", "inventory_transfer_headers.work_session_id = 601",
                          "inventory_transfer_headers.expected_receiver_id = 303",
                          "inventory_transfer_headers.workflow_type = 'HANDSHAKE'", "inventory_transfer_headers.status = 'PENDING'"):
            self.assertIn(condition, sql(handshake))
        self.assertEqual(setup.session.end_time, NOW)
        self.assertFalse(setup.session.is_settled)
        self.assert_transactions(setup.db)

    async def test_end_rejects_active_break_and_pending_handshake_without_closing_session(self):
        for reason in ("missing_session", "active_break", "pending_handshake"):
            with self.subTest(reason=reason):
                setup = fixture("end_work_session")
                if reason == "missing_session":
                    setup.results[0].scalars.return_value.first.return_value = None
                elif reason == "active_break":
                    setup.session.break_start_time = NOW
                else:
                    setup.results[1].scalar_one_or_none.return_value = 777
                with self.assertRaises(HTTPException) as rejected:
                    await self.invoke("end_work_session", setup)
                self.assertEqual(rejected.exception.status_code, 404 if reason == "missing_session" else 400)
                self.assertEqual(setup.db.execute.await_count, 2 if reason == "pending_handshake" else 1)
                self.assertIsNone(setup.session.end_time)
                self.assertFalse(setup.session.is_settled)
                self.assert_transactions(setup.db, commits=0, rollbacks=1)

    async def test_break_start_and_end_preserve_state_timestamps_duration_and_log_company(self):
        setup = fixture("toggle_break")
        await self.invoke("toggle_break", setup)
        query = setup.db.execute.await_args.args[0]
        self.assert_scoped_legacy_query(query, "work_sessions")
        self.assertIsNotNone(query._for_update_arg)
        self.assertEqual(setup.session.break_start_time, NOW)
        self.assertIsNone(setup.session.break_end_time)
        setup.db.add.assert_not_called()
        self.assert_transactions(setup.db)
        setup = fixture("toggle_break")
        start = NOW - timedelta(minutes=12, seconds=45)
        setup.session.break_start_time = start
        await self.invoke("toggle_break", setup, action="end")
        log = setup.db.add.call_args.args[0]
        self.assertIsInstance(log, WorkBreakLog)
        self.assertEqual((log.company_id, log.work_session_id, log.break_start, log.break_end, log.duration_minutes),
                         (7, 601, start, NOW, 12))
        self.assertIsNone(setup.session.break_start_time)
        self.assertIsNone(setup.session.break_end_time)
        self.assert_transactions(setup.db)

    async def test_break_invalid_transitions_rollback_without_logging_or_committing(self):
        cases = (("missing_session", "start"), ("already_started", "start"),
                 ("not_started", "end"), ("already_ended", "end"), ("invalid_action", "invalid"))
        for reason, action in cases:
            with self.subTest(reason=reason):
                setup = fixture("toggle_break")
                if reason == "missing_session":
                    setup.results[0].scalars.return_value.first.return_value = None
                if reason in {"already_started", "already_ended"}:
                    setup.session.break_start_time = NOW - timedelta(minutes=5)
                if reason == "already_ended":
                    setup.session.break_end_time = NOW
                before = (setup.session.break_start_time, setup.session.break_end_time)
                with self.assertRaises(HTTPException) as rejected:
                    await self.invoke("toggle_break", setup, action=action)
                self.assertEqual(rejected.exception.status_code, 404 if reason == "missing_session" else 400)
                self.assertEqual((setup.session.break_start_time, setup.session.break_end_time), before)
                setup.db.add.assert_not_called()
                self.assert_transactions(setup.db, commits=0, rollbacks=1)

    async def test_each_flow_retains_rollback_on_database_failure(self):
        for name in ENDPOINTS:
            with self.subTest(endpoint=name):
                setup = fixture(name)
                setup.db.execute.side_effect = RuntimeError("synthetic storage failure")
                with self.assertRaises(HTTPException) as rejected:
                    await self.invoke(name, setup)
                self.assertEqual(rejected.exception.status_code, 500)
                self.assertNotIn("synthetic storage failure", str(rejected.exception.detail))
                self.assert_transactions(setup.db, commits=0, rollbacks=1)

    async def test_real_fastapi_graph_authenticates_once_and_maps_canonical_field_for_every_route(self):
        original_resolver = compatibility.resolve_field_authorization_subject
        for name, (method, path, status) in ENDPOINTS.items():
            for flag in (False, True):
                with self.subTest(endpoint=name, operational_flag=flag):
                    self.namespace = load_routes()
                    setup = fixture(name)
                    actor = SimpleNamespace(id=303, company_id=7, is_active=True, is_admin=flag)
                    mapping = Bridge(company_id=7, legacy_driver_id=303,
                                     field_principal_id=101, field_representative_id=202)
                    mapping_result, driver_result = result(mapping), result(actor)
                    setup.db.execute.side_effect = [mapping_result, driver_result, *setup.results]

                    async def override_db():
                        return setup.db

                    app = FastAPI()
                    app.include_router(self.namespace["router"])
                    app.dependency_overrides[get_db] = override_db
                    token = issue_access_token(principal_id=101, company_id=7, channel="FIELD",
                                               principal_type="FIELD_REPRESENTATIVE", auth_revision=13,
                                               secret=SECRET)
                    kwargs = {"headers": {"Authorization": f"Bearer {token}"}}
                    if name == "start_work_session":
                        kwargs["json"] = {"latitude": 31.9, "longitude": 35.9}
                    elif name == "toggle_break":
                        kwargs["json"] = {"action": "start"}
                    with patch.object(canonical, "decode_company_token",
                                      wraps=canonical.decode_company_token) as decode, \
                         patch.object(canonical, "resolve_access_context",
                                      AsyncMock(return_value=CONTEXT)) as context, \
                         patch.object(compatibility, "resolve_field_authorization_subject",
                                      wraps=original_resolver) as resolve:
                        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                            response = await client.request(method, path, **kwargs)
                    self.assertEqual(response.status_code, status, response.text)
                    decode.assert_called_once_with(token, secret=SECRET, expected_type="access")
                    context.assert_awaited_once()
                    self.assertEqual(context.await_args.args[1].principal_id, 101)
                    resolve.assert_awaited_once_with(setup.db, CONTEXT)
                    mapping_result.one_or_none.assert_called_once_with()
                    driver_result.scalar_one_or_none.assert_called_once_with()
                    self.assertEqual(setup.db.execute.await_count, 2 + len(setup.results))
                    setup.db.connection.assert_awaited_once_with()
                    self.assert_transactions(setup.db)


if __name__ == "__main__":
    unittest.main()
