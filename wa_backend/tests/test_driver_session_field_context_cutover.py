"""Execute the three unchanged route bodies with real SQL and dependency caching.

Load only the selected source functions so unrelated driver workflows are not
imported. SQLAlchemy results and external business services are mocked; the
FastAPI dependency graph and canonical operational mapping are real.
"""
import ast
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from domains.dispatch_transfer_quantity import is_canonical_base_handshake, canonical_field_base_quantity
from httpx import ASGITransport, AsyncClient
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

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
from api.authentication.field_authorization import require_field_capability, get_current_field_capability_access
from domains.auth_sessions.codec import issue_access_token
from domains.auth_sessions.context import FieldRequestContext
from domains.pricing.core import PricingError
from domains.vehicles import (
    VehicleError, require_vehicle_operational_state, resolve_vehicle_custody_location_id,
)
from models import (
    DispatchRoute, Driver, InventoryBalance, InventoryLocation,
    InventoryTransferHeader, InventoryMovement, ProductVariant, SessionInventorySnapshot, Shop, Visit,
    VisitItem, VisitReturn, Vehicle, SystemAuditLog, ShortageRequest,
    WorkBreakLog, WorkSession,
)
from quantity import QUANTITY_MAX
from services import InventoryMutationError, InventoryReversalError
from domains.sales_calculation.core import CalculationError
from domains.sales_evidence.core import SalesEvidenceError
from schemas import BreakToggleRequest, SessionStartRequest
from api.field_transfer_contracts import transfer_batch_error, attributed_transfer_error
from api.field_visit_contracts import (
    canonicalize_visit_returns, revalidate_return_provenance,
    revalidate_return_batch_metadata, invoice_from_calculation,
)

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
        read_vehicle_operational_state=AsyncMock(
            return_value=SimpleNamespace(is_active=True, maintenance_status="Active")
        ),
        vehicle_is_operational=Mock(
            side_effect=lambda vehicle: bool(
                vehicle is not None
                and vehicle.is_active
                and vehicle.maintenance_status == "Active"
            )
        ),
    )
    # Keep the real decorators, annotations, signatures and function bodies.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BACKEND / "api" / "driver.py"),
                 "exec", dont_inherit=True), namespace)
    return namespace


def result(value=None, rows=()):
    synchronous = Mock()
    synchronous.scalar_one_or_none.return_value = value
    synchronous.scalars.return_value.first.return_value = value
    synchronous.scalars.return_value.all.return_value = [] if value is None else [value]
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
        db.scalar.side_effect = lambda statement: any(
            item.get("entity") is InventoryLocation
            for item in getattr(statement, "column_descriptions", ())
        )
        results = [result(OperationalLocator()), result(), result(route), result(),
                   result(501), result(501), result(501),
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
        self.assertEqual(len(queries), 9)
        self.assertEqual(sql(queries[0].whereclause), "drivers.company_id = 7 AND drivers.id = 303")
        for index, table in ((1, "work_sessions"), (2, "dispatch_routes"), (3, "work_sessions"), (8, "visits")):
            self.assert_scoped_legacy_query(queries[index], table)
        self.assertIn("work_sessions.is_settled IS false", sql(queries[1]))
        self.assertIn("work_sessions.end_time IS NOT NULL", sql(queries[1]))
        self.assertIn("dispatch_routes.dispatch_date = '2026-10-12'", sql(queries[2]))
        self.assertIn("dispatch_routes.status = 'active'", sql(queries[2]))
        for index in (0, 2, 3, 5):
            self.assertIsNotNone(queries[index]._for_update_arg)
            self.assertEqual(queries[index]._for_update_arg.read, index == 5)
        for index in (4, 5, 6):
            location_sql = sql(queries[index])
            for condition in ("inventory_locations.company_id = 7", "inventory_locations.vehicle_id = 801",
                              "inventory_locations.location_type = 'VEHICLE'"):
                self.assertIn(condition, location_sql)
            if index == 5:
                self.assertIn("inventory_locations.is_active = true", location_sql)
            else:
                self.assertNotIn("inventory_locations.is_active", location_sql)
                self.assertIsNone(queries[index]._limit_clause)
                self.assertIsNone(queries[index]._for_update_arg)
        for call in db.scalar.await_args_list:
            self.assertIsNone(call.args[0]._for_update_arg)
            self.assertIn("inventory_locations.id = 501", sql(call.args[0]))
        self.assertEqual(db.scalar.await_count, 2)
        self.assertIn("inventory_balances.company_id = 7", sql(queries[7]))
        self.assertIn("inventory_balances.location_id = 501", sql(queries[7]))
        self.assertIn("work_session_id=601", sql(queries[8]))
        self.assertIn("shops.company_id = 7", sql(queries[8]))
        self.namespace["get_company_local_date"].assert_awaited_once_with(db, 7)
        self.namespace["require_route_commercial_context"].assert_awaited_once_with(db, company_id=7, dispatch_route_id=701)
        self.namespace["acquire_inventory_location_guard"].assert_awaited_once_with(db, 7, 501, exclusive=True)
        self.namespace["read_vehicle_operational_state"].assert_awaited_once_with(
            db, company_id=7, vehicle_id=801
        )
        self.namespace["vehicle_is_operational"].assert_called_once()
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

    async def test_start_rejects_vehicle_in_maintenance_after_location_guard(self):
        setup = fixture("start_work_session")
        self.namespace["read_vehicle_operational_state"].return_value = SimpleNamespace(
            is_active=True, maintenance_status="In_Maintenance"
        )
        with self.assertRaises(HTTPException) as rejected:
            await self.invoke("start_work_session", setup)
        self.assertEqual(rejected.exception.status_code, 409)
        self.namespace["acquire_inventory_location_guard"].assert_awaited_once_with(
            setup.db, 7, 501, exclusive=True
        )
        self.namespace["read_vehicle_operational_state"].assert_awaited_once_with(
            setup.db, company_id=7, vehicle_id=801
        )
        setup.db.add.assert_not_called()
        setup.db.flush.assert_not_awaited()
        self.assert_transactions(setup.db, commits=0, rollbacks=2)

    async def test_start_rejects_inactive_canonical_custody_without_snapshot(self):
        setup = fixture("start_work_session")
        setup.db.scalar.side_effect = None
        setup.db.scalar.return_value = False
        with self.assertRaises(HTTPException) as rejected:
            await self.invoke("start_work_session", setup)
        self.assertEqual(rejected.exception.status_code, 409)
        self.assertEqual(rejected.exception.detail["code"], "VEHICLE_CUSTODY_LOCATION_INACTIVE")
        self.namespace["acquire_inventory_location_guard"].assert_not_awaited()
        setup.db.add.assert_not_called()
        self.assert_transactions(setup.db, commits=0, rollbacks=1)

    async def test_start_rejects_duplicate_history_before_and_after_location_guard(self):
        for index in (4, 6):
            with self.subTest(query=index):
                self.namespace = load_routes()
                setup = fixture("start_work_session")
                setup.results[index].scalars.return_value.all.return_value = [501, 502]
                with self.assertRaises(HTTPException) as rejected:
                    await self.invoke("start_work_session", setup)
                self.assertEqual(rejected.exception.status_code, 409)
                self.assertEqual(rejected.exception.detail["code"], "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS")
                self.assertEqual(rejected.exception.detail["context"], {"location_count": 2})
                self.assertEqual(self.namespace["acquire_inventory_location_guard"].await_count, index == 6)
                self.namespace["read_vehicle_operational_state"].assert_not_awaited()
                setup.db.add.assert_not_called()
                setup.db.flush.assert_not_awaited()
                self.assert_transactions(setup.db, commits=0, rollbacks=1)

    async def test_start_rechecks_canonical_location_activity_under_guard(self):
        setup = fixture("start_work_session")
        setup.db.scalar.side_effect = [True, False]
        with self.assertRaises(HTTPException) as rejected:
            await self.invoke("start_work_session", setup)
        self.assertEqual(rejected.exception.status_code, 409)
        self.assertEqual(rejected.exception.detail["code"], "VEHICLE_CUSTODY_LOCATION_INACTIVE")
        self.namespace["acquire_inventory_location_guard"].assert_awaited_once()
        self.namespace["read_vehicle_operational_state"].assert_not_awaited()
        setup.db.add.assert_not_called()
        self.assert_transactions(setup.db, commits=0, rollbacks=1)

    async def test_start_rejects_lost_or_replaced_custody_under_guard(self):
        for ids, code in (
            ([], "VEHICLE_CUSTODY_LOCATION_MISSING"),
            ([502], "VEHICLE_CUSTODY_LOCATION_INCONSISTENT"),
        ):
            with self.subTest(ids=ids):
                self.namespace = load_routes()
                setup = fixture("start_work_session")
                setup.results[6].scalars.return_value.all.return_value = ids
                with self.assertRaises(HTTPException) as rejected:
                    await self.invoke("start_work_session", setup)
                self.assertEqual(rejected.exception.status_code, 409)
                self.assertEqual(rejected.exception.detail["code"], code)
                self.namespace["acquire_inventory_location_guard"].assert_awaited_once()
                self.namespace["read_vehicle_operational_state"].assert_not_awaited()
                setup.db.add.assert_not_called()
                self.assert_transactions(setup.db, commits=0, rollbacks=1)

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
                self.assert_transactions(setup.db, commits=0, rollbacks=1 if reason == "missing_location" else 2)

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
                    granted = SimpleNamespace(require_all=AsyncMock())
                    app.dependency_overrides[get_current_field_capability_access] = lambda: granted
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
                    granted.require_all.assert_awaited_once_with(("work_session.execute",))
                    decode.assert_called_once_with(token, secret=SECRET, expected_type="access")
                    context.assert_awaited_once()
                    self.assertEqual(context.await_args.args[1].principal_id, 101)
                    resolve.assert_awaited_once_with(setup.db, CONTEXT)
                    mapping_result.one_or_none.assert_called_once_with()
                    driver_result.scalar_one_or_none.assert_called_once_with()
                    self.assertEqual(setup.db.execute.await_count, 2 + len(setup.results))
                    setup.db.connection.assert_awaited_once_with()
                    self.assert_transactions(setup.db)



def load_custody_routes(**dependencies):
    tree = ast.parse((BACKEND / "api/driver.py").read_text(encoding="utf-8"))
    names = {
        "_driver_vehicle_custody_location_id", "_load_active_driver_route_and_vehicle_location",
        "_load_vehicle_inventory_projection", "_require_driver_mobile_integral_quantity",
        "_validate_handshake_locations", "respond_to_transfer", "batch_respond_to_transfers", "update_visit",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    nodes += [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
        node.returns = None
        for arg in (*node.args.args, *node.args.kwonlyargs):
            arg.annotation = None
        node.args.defaults = [
            ast.Constant(None) if isinstance(value, ast.Call) else value for value in node.args.defaults
        ]
    namespace = dict(globals(), logger=Mock(), **dependencies)
    namespace.setdefault("lock_session_load_plan", AsyncMock())
    namespace.setdefault("synchronize_session_load_plans", AsyncMock())
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(BACKEND / "api/driver.py"), "exec"), namespace)
    return namespace


def custody_db():
    db = MagicMock(spec=AsyncSession)
    state = SimpleNamespace(is_active=True, maintenance_status="Active")
    db.scalar.side_effect = lambda statement: (
        state if statement.column_descriptions[0].get("entity") is Vehicle else True
    )
    return db, state


class DriverCustodyCutoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_and_inventory_projection_reject_all_invalid_custody_shapes(self):
        for helper in ("_load_active_driver_route_and_vehicle_location", "_load_vehicle_inventory_projection"):
            for ids, active, code in (
                ([], True, "VEHICLE_CUSTODY_LOCATION_MISSING"),
                ([501, 502], True, "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"),
                ([501], False, "VEHICLE_CUSTODY_LOCATION_INACTIVE"),
            ):
                with self.subTest(helper=helper, code=code):
                    db, _ = custody_db()
                    history = result()
                    history.scalars.return_value.all.return_value = ids
                    route = SimpleNamespace(vehicle_id=801)
                    db.execute.side_effect = (
                        [result(route), history] if "active_driver" in helper else [history]
                    )
                    db.scalar.return_value = active
                    db.scalar.side_effect = None
                    namespace = load_custody_routes()
                    kwargs = dict(db=db, company_id=7)
                    if "active_driver" in helper:
                        kwargs.update(driver_id=303, work_session_id=601)
                    else:
                        kwargs.update(vehicle_id=801)
                    with self.assertRaises(HTTPException) as rejected:
                        await namespace[helper](**kwargs)
                    self.assertEqual((rejected.exception.status_code, rejected.exception.detail["code"]), (409, code))
                    db.add.assert_not_called()

    async def test_historical_pending_helper_accepts_the_single_inactive_custody_without_maintenance_gate(self):
        db, state = custody_db()
        state.is_active = False
        state.maintenance_status = "In_Maintenance"
        route = SimpleNamespace(vehicle_id=801)
        db.execute.side_effect = [result(route), result(501)]
        namespace = load_custody_routes()
        found_route, location_id = await namespace["_load_active_driver_route_and_vehicle_location"](
            db, company_id=7, driver_id=303, work_session_id=601,
            require_active_route=False, require_active_vehicle_location=False,
        )
        self.assertIs(found_route, route)
        self.assertEqual(location_id, 501)
        db.scalar.assert_not_awaited()

    async def test_empty_vehicle_inventory_projection_uses_the_single_canonical_row(self):
        db, _ = custody_db()
        db.execute.side_effect = [result(501), result(rows=[])]
        namespace = load_custody_routes()
        self.assertEqual(await namespace["_load_vehicle_inventory_projection"](
            db, company_id=7, vehicle_id=801
        ), (501, []))
        history = db.execute.await_args_list[0].args[0]
        self.assertNotIn("is_active", sql(history))
        self.assertIsNone(history._limit_clause)

    def visit_setup(self, *, invalid_at_guard=False):
        db, state = custody_db()
        session = SimpleNamespace(id=601, inventory_reconciled_at=None,
            break_start_time=None, break_end_time=None, is_authorized_to_sell=True)
        shop = SimpleNamespace(id=901, zone_id=1001, current_balance=Decimal("0"))
        visit = SimpleNamespace(id=701, shop_id=901, driver_id=303, status="Pending",
            work_session=None, work_session_id=None, is_emergency=False, latitude=None, longitude=None)
        route = SimpleNamespace(id=1101, vehicle_id=801, zone_id=1001)
        history = result(501)
        after = result(501)
        if invalid_at_guard:
            after.scalars.return_value.all.return_value = [501, 502]
        db.execute.side_effect = [
            result(session), result(901), result(shop), result(visit), result(route),
            result(), history, result(), after,
        ]
        events = []
        namespace = load_custody_routes(
            begin_idempotent_operation=AsyncMock(return_value=(SimpleNamespace(), None)),
            check_inventory_locks_batch=AsyncMock(),
            acquire_product_lifecycle_guards=AsyncMock(side_effect=lambda *a, **k: events.append("products")),
            acquire_inventory_location_guard=AsyncMock(side_effect=lambda *a, **k: events.append("guard")),
            get_utc_now=Mock(return_value=NOW),
        )
        payload = SimpleNamespace(request_id="stable-visit", cart_items=[], returns=[],
            is_emergency=False, debt_paid=Decimal("0"), cash_collected=Decimal("0"), outcome="NoSale",
            notes=None, latitude=None, longitude=None,
            model_dump=Mock(return_value={"cart_items": [], "returns": []}))
        kwargs = dict(visit_id=701, payload=payload, db=db, field_context=CONTEXT,
                      legacy_actor=OperationalLocator())
        return SimpleNamespace(db=db, state=state, history=history, namespace=namespace, events=events, kwargs=kwargs)

    async def test_update_visit_rejects_missing_duplicate_inactive_or_maintenance_before_business_effects(self):
        for ids, active, maintenance, code in (
            ([], True, "Active", "VEHICLE_CUSTODY_LOCATION_MISSING"),
            ([501, 502], True, "Active", "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"),
            ([501], False, "Active", "VEHICLE_CUSTODY_LOCATION_INACTIVE"),
            ([501], True, "In_Maintenance", "VEHICLE_NOT_OPERATIONAL"),
        ):
            with self.subTest(code=code):
                setup = self.visit_setup()
                setup.history.scalars.return_value.all.return_value = ids
                setup.state.maintenance_status = maintenance
                if not active:
                    setup.db.scalar.side_effect = None
                    setup.db.scalar.return_value = False
                with self.assertRaises(HTTPException) as rejected:
                    await setup.namespace["update_visit"](**setup.kwargs)
                self.assertEqual((rejected.exception.status_code, rejected.exception.detail["code"]), (409, code))
                setup.namespace["check_inventory_locks_batch"].assert_not_awaited()
                setup.db.add.assert_not_called()
                setup.db.commit.assert_not_awaited()
                setup.db.rollback.assert_awaited_once()

    async def test_update_visit_revalidates_custody_after_product_then_location_guards(self):
        setup = self.visit_setup(invalid_at_guard=True)
        with self.assertRaises(HTTPException) as rejected:
            await setup.namespace["update_visit"](**setup.kwargs)
        self.assertEqual((rejected.exception.status_code, rejected.exception.detail["code"]),
                         (409, "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"))
        self.assertEqual(setup.events, ["products", "guard"])
        setup.db.add.assert_not_called()
        setup.db.commit.assert_not_awaited()
        setup.db.rollback.assert_awaited_once()

    async def test_update_visit_replay_preserves_original_result_before_custody_queries(self):
        setup = self.visit_setup()
        replay = {"new_balance": "0.000"}
        setup.namespace["begin_idempotent_operation"].return_value = (None, replay)
        self.assertIs(await setup.namespace["update_visit"](**setup.kwargs), replay)
        setup.db.execute.assert_not_awaited()
        setup.db.add.assert_not_called()

    def transfer_setup(self, batch=False, reject=False, late_duplicate=False):
        db, state = custody_db()
        header = SimpleNamespace(id=21, work_session_id=601, source_location_id=901,
            destination_location_id=501, status="PENDING", received_by=None, decision_reason=None)
        session = SimpleNamespace(id=601, end_time=None, is_settled=False)
        route = SimpleNamespace(id=701, vehicle_id=801)
        variant = SimpleNamespace(id=111, lifecycle_status="ACTIVE", operational_hold="NONE")
        history, after = result(501), result(501)
        if late_duplicate:
            after.scalars.return_value.all.return_value = [501, 502]
        headers = result(header)
        headers.scalars.return_value.all.return_value = [header]
        variants = result(variant)
        variants.scalars.return_value.all.return_value = [variant]
        db.execute.side_effect = (
            [headers, result(session), variants] if reject else
            [headers, result(session), result(route), history, result(SimpleNamespace(id=901)), variants, after]
        )
        events = []
        namespace = load_custody_routes(
            _load_handshake_lines_for_update=AsyncMock(return_value={21: [SimpleNamespace(product_variant_id=111)]}),
            acquire_product_lifecycle_guards=AsyncMock(side_effect=lambda *a, **k: events.append("products")),
            acquire_inventory_location_guards=AsyncMock(side_effect=lambda *a, **k: events.append("guard")),
            evaluate_product_capability=Mock(return_value=SimpleNamespace(allowed=True)),
            INBOUND_COMPLETE="INBOUND_COMPLETE",
            _resolve_handshake_destination_statuses=AsyncMock(return_value={}),
            _build_handshake_movement_specs=Mock(return_value=[{"synthetic": True}]),
            apply_inventory_movements_batch=AsyncMock(), get_utc_now=Mock(return_value=NOW),
        )
        status = "rejected" if reject else "accepted"
        payload = (
            SimpleNamespace(transfers=[SimpleNamespace(transfer_id=21, status=status, reason="reason" if reject else None)])
            if batch else SimpleNamespace(response=status, reason="reason" if reject else None)
        )
        kwargs = dict(payload=payload, db=db, field_context=CONTEXT, legacy_actor=OperationalLocator())
        if not batch:
            kwargs["transfer_id"] = 21
        return SimpleNamespace(db=db, state=state, header=header, history=history,
            namespace=namespace, events=events, kwargs=kwargs)

    async def test_single_and_batch_handshake_accept_use_strict_custody_and_preserve_replay(self):
        for batch, endpoint in ((False, "respond_to_transfer"), (True, "batch_respond_to_transfers")):
            with self.subTest(batch=batch):
                setup = self.transfer_setup(batch=batch)
                await setup.namespace[endpoint](**setup.kwargs)
                self.assertEqual(setup.events, ["products", "guard"])
                self.assertEqual((setup.header.status, setup.header.received_by), ("POSTED", 303))
                setup.namespace["apply_inventory_movements_batch"].assert_awaited_once()
                self.assertEqual(setup.namespace["apply_inventory_movements_batch"].await_args.kwargs["performed_by"], 303)
                self.assertEqual(setup.db.add.call_args.args[0].admin_id, 303)
                setup.db.execute.side_effect = [result(setup.header)]
                setup.db.execute.return_value = result(setup.header)
                replay_headers = result(setup.header)
                replay_headers.scalars.return_value.all.return_value = [setup.header]
                setup.db.execute.side_effect = [replay_headers]
                await setup.namespace[endpoint](**setup.kwargs)
                setup.namespace["apply_inventory_movements_batch"].assert_awaited_once()

    async def test_single_and_batch_handshake_reject_ambiguous_custody_before_posting(self):
        for batch, endpoint in ((False, "respond_to_transfer"), (True, "batch_respond_to_transfers")):
            for late in (False, True):
                with self.subTest(batch=batch, late=late):
                    setup = self.transfer_setup(batch=batch, late_duplicate=late)
                    if not late:
                        setup.history.scalars.return_value.all.return_value = [501, 502]
                    with self.assertRaises(HTTPException) as rejected:
                        await setup.namespace[endpoint](**setup.kwargs)
                    self.assertEqual((rejected.exception.status_code, rejected.exception.detail["code"]),
                                     (409, "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"))
                    self.assertEqual(setup.header.status, "PENDING")
                    setup.namespace["apply_inventory_movements_batch"].assert_not_awaited()
                    setup.db.commit.assert_not_awaited()
                    setup.db.rollback.assert_awaited_once()

    async def test_single_and_batch_rejection_remain_available_without_vehicle_eligibility(self):
        for batch, endpoint in ((False, "respond_to_transfer"), (True, "batch_respond_to_transfers")):
            with self.subTest(batch=batch):
                setup = self.transfer_setup(batch=batch, reject=True)
                setup.state.maintenance_status = "In_Maintenance"
                await setup.namespace[endpoint](**setup.kwargs)
                self.assertEqual(setup.header.status, "REJECTED")
                setup.namespace["acquire_inventory_location_guards"].assert_not_awaited()
                setup.db.scalar.assert_not_awaited()
                setup.db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
