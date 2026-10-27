from __future__ import annotations

import ast
import asyncio
import hashlib
import json
from uuid import uuid4
from datetime import date, timedelta
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy import and_, create_engine, func, or_, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domains.pricing.core import PricingError
from domains.vehicles import (
    VehicleError, resolve_vehicle_custody_location_id, resolve_vehicle_custody_location_ids,
    vehicle_custody_ready_predicate, vehicle_operational_predicate,
)
from dispatch_access import vehicle_filter
from domains.vehicles import repository as vehicle_repository
from models import (
    DispatchRoute, Driver, InventoryBalance, InventoryLocation, Shop,
    ShortageRequest, SystemAuditLog, Vehicle, Visit, WorkSession,
    ProductVariant, ProductLocation, InventoryTransferHeader, InventoryTransferLine,
    SessionInventorySnapshot, InventoryMovement,
)
from services import InventoryMutationError

from domains.vehicles.eligibility import (
    route_requires_operational_vehicle,
    vehicle_is_operational,
)


BACKEND = Path(__file__).resolve().parents[1]
DISPATCH = BACKEND / "api" / "dispatch.py"
DRIVER = BACKEND / "api" / "driver.py"
ELIGIBILITY = BACKEND / "domains" / "vehicles" / "eligibility.py"


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"function {name} not found in {path}")


class VehicleOperationalEligibilityIntegrationTests(unittest.TestCase):
    def test_pure_operational_state_requires_active_and_not_in_maintenance(self):
        self.assertTrue(vehicle_is_operational(SimpleNamespace(is_active=True, maintenance_status="Active")))
        self.assertFalse(vehicle_is_operational(SimpleNamespace(is_active=False, maintenance_status="Active")))
        self.assertFalse(vehicle_is_operational(SimpleNamespace(is_active=True, maintenance_status="In_Maintenance")))
        self.assertFalse(vehicle_is_operational(None))

    def test_route_eligibility_trigger_does_not_block_plain_close(self):
        self.assertFalse(route_requires_operational_vehicle(target_status="closed"))
        self.assertTrue(route_requires_operational_vehicle(target_status="active"))
        self.assertTrue(route_requires_operational_vehicle(target_status="waiting"))
        self.assertTrue(route_requires_operational_vehicle(target_status="postponed"))
        self.assertTrue(route_requires_operational_vehicle(target_status="closed", vehicle_changed=True))
        self.assertTrue(route_requires_operational_vehicle(target_status="closed", inventory_mutation=True))

    def test_dispatch_init_advertises_only_operational_vehicles(self):
        source = _function_source(DISPATCH, "dispatch_init")
        self.assertGreaterEqual(source.count("vehicle_operational_predicate(Vehicle)"), 2)

    def test_route_create_and_status_use_the_shared_operational_seam(self):
        create = _function_source(DISPATCH, "dispatch_route")
        status = _function_source(DISPATCH, "update_route_status")
        self.assertIn("vehicle_is_operational(vehicle)", create)
        self.assertGreaterEqual(status.count("vehicle_is_operational("), 2)
        self.assertGreaterEqual(status.count("route_requires_operational_vehicle("), 2)
        self.assertIn("vehicle_changed", status)

    def test_adjust_inventory_serializes_on_location_before_plain_vehicle_read(self):
        source = _function_source(DISPATCH, "adjust_route_inventory")
        guard = source.index("acquire_inventory_location_guard(")
        read = source.index("read_vehicle_operational_state(")
        check = source.index("vehicle_is_operational(vehicle_state)")
        current = source.index("_dispatch_available_totals(")
        self.assertLess(guard, read)
        self.assertLess(read, check)
        self.assertLess(check, current)
        self.assertNotIn("select(Vehicle)", source)

    def test_undo_end_work_requires_operational_historical_vehicle(self):
        source = _function_source(DISPATCH, "undo_end_work")
        self.assertIn("vehicle_is_operational(vehicle)", source)

    def test_driver_start_rechecks_vehicle_under_existing_location_guard_without_vehicle_row_lock(self):
        source = _function_source(DRIVER, "start_work_session")
        guard = source.index("acquire_inventory_location_guard(")
        read = source.index("read_vehicle_operational_state(")
        session = source.index("new_session = WorkSession(")
        self.assertLess(guard, read)
        self.assertLess(read, session)
        self.assertNotIn("select(Vehicle)", source)

    def test_plain_state_reader_never_takes_vehicle_for_update(self):
        source = _function_source(ELIGIBILITY, "read_vehicle_operational_state")
        self.assertIn("select(Vehicle)", source)
        self.assertNotIn("with_for_update", source)
        self.assertIn("populate_existing=True", source)


def _load_dispatch_functions(*names, **dependencies):
    tree = ast.parse(DISPATCH.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in names
    ]
    for node in nodes:
        node.decorator_list = []
        node.returns = None
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            arg.annotation = None
        node.args.defaults = [
            ast.Constant(None) if isinstance(value, ast.Call) else value
            for value in node.args.defaults
        ]
    namespace = dict(globals(), **dependencies)
    # The new session-plan guard is an independent DB seam in these isolated
    # legacy route-status tests; its real serialization is exercised by PG tests.
    namespace.setdefault("lock_session_load_plan", AsyncMock())
    namespace.setdefault("lock_route_adjustment_context", AsyncMock(return_value=None))
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, str(DISPATCH), "exec"), namespace)
    return namespace


def _result(value=None, ids=(), rows=()):
    result = Mock()
    result.scalar_one_or_none.return_value = value
    result.first.return_value = value
    result.one_or_none.return_value = value
    result.scalars.return_value.all.return_value = list(ids)
    result.all.return_value = list(rows)
    return result


def _sql(statement):
    return str(statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))


class VehicleCustodyResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_exactly_one_custody_row_and_tenant_scope(self):
        db = MagicMock(spec=AsyncSession)
        db.execute.return_value = _result(ids=[501])
        db.scalar.return_value = True
        self.assertEqual(await resolve_vehicle_custody_location_id(
            db, company_id=7, vehicle_id=801
        ), 501)
        history = db.execute.await_args.args[0]
        active = db.scalar.await_args.args[0]
        for statement in (history, active):
            text = _sql(statement)
            self.assertIn("inventory_locations.company_id = 7", text)
            self.assertIn("inventory_locations.vehicle_id = 801", text)
            self.assertIn("inventory_locations.location_type = 'VEHICLE'", text)
            self.assertIsNone(statement._limit_clause)
            self.assertIsNone(statement._for_update_arg)
        self.assertNotIn("inventory_locations.is_active", _sql(history))
        self.assertIn("inventory_locations.id = 501", _sql(active))
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_zero_custody_rows_fail_closed(self):
        db = MagicMock(spec=AsyncSession)
        db.execute.return_value = _result()
        with self.assertRaises(VehicleError) as rejected:
            await resolve_vehicle_custody_location_id(db, company_id=7, vehicle_id=801)
        self.assertEqual(rejected.exception.code, "VEHICLE_CUSTODY_LOCATION_MISSING")
        self.assertEqual(rejected.exception.status_code, 409)
        db.scalar.assert_not_awaited()
        db.add.assert_not_called()

    async def test_duplicate_history_fails_before_any_active_filter_or_first_row_choice(self):
        for active_states in ((False, False), (True, False), (False, True), (True, True)):
            for require_active in (False, True):
                with self.subTest(states=active_states, require_active=require_active):
                    db = MagicMock(spec=AsyncSession)
                    db.execute.return_value = _result(ids=[501, 502])
                    db.scalar.return_value = active_states[0]
                    with self.assertRaises(VehicleError) as rejected:
                        await resolve_vehicle_custody_location_id(
                            db, company_id=7, vehicle_id=801, require_active=require_active
                        )
                    self.assertEqual(rejected.exception.code, "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS")
                    self.assertEqual(rejected.exception.context, {"location_count": 2})
                    db.scalar.assert_not_awaited()
                    self.assertNotIn("is_active", _sql(db.execute.await_args.args[0]))
                    db.add.assert_not_called()

    async def test_inactive_exact_row_is_rejected_only_when_active_is_required(self):
        db = MagicMock(spec=AsyncSession)
        db.execute.return_value = _result(ids=[501])
        db.scalar.return_value = False
        self.assertEqual(await resolve_vehicle_custody_location_id(
            db, company_id=7, vehicle_id=801, require_active=False
        ), 501)
        db.scalar.assert_not_awaited()
        with self.assertRaises(VehicleError) as rejected:
            await resolve_vehicle_custody_location_id(db, company_id=7, vehicle_id=801)
        self.assertEqual(rejected.exception.code, "VEHICLE_CUSTODY_LOCATION_INACTIVE")
        self.assertEqual(rejected.exception.status_code, 409)

    async def test_lifecycle_lock_reuses_strict_resolver_and_same_inactive_row(self):
        db = MagicMock(spec=AsyncSession)
        location = SimpleNamespace(id=501, is_active=False)
        db.execute.side_effect = [_result(ids=[501]), _result(location)]
        with patch.object(vehicle_repository, "acquire_inventory_location_guard", AsyncMock()) as guard:
            self.assertIs(await vehicle_repository.lock_canonical_custody(
                db, company_id=7, vehicle_id=801
            ), location)
        guard.assert_awaited_once_with(db, 7, 501, exclusive=True)
        history, locked = [call.args[0] for call in db.execute.await_args_list]
        self.assertIsNone(history._for_update_arg)
        self.assertIsNotNone(locked._for_update_arg)
        self.assertIn("inventory_locations.id = 501", _sql(locked))
        self.assertNotIn("vehicles", _sql(locked))
        db.scalar.assert_not_awaited()
        db.add.assert_not_called()

    async def test_dispatch_adapter_maps_domain_conflicts_to_coded_409(self):
        namespace = _load_dispatch_functions("_dispatch_vehicle_location_id")
        for ids, active, code in (
            ([], True, "VEHICLE_CUSTODY_LOCATION_MISSING"),
            ([501, 502], True, "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"),
            ([501], False, "VEHICLE_CUSTODY_LOCATION_INACTIVE"),
        ):
            with self.subTest(code=code):
                db = MagicMock(spec=AsyncSession)
                db.execute.return_value = _result(ids=ids)
                db.scalar.return_value = active
                with self.assertRaises(HTTPException) as rejected:
                    await namespace["_dispatch_vehicle_location_id"](
                        db, company_id=7, vehicle_id=801
                    )
                self.assertEqual(rejected.exception.status_code, 409)
                self.assertEqual(rejected.exception.detail["code"], code)
                self.assertIsInstance(rejected.exception.detail["context"], dict)

    def test_all_dispatch_callers_delegate_to_the_strict_domain_seam(self):
        tree = ast.parse(DISPATCH.read_text(encoding="utf-8"))
        callers = {
            node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "_dispatch_vehicle_location_id"
        }
        self.assertEqual(callers, {
            "dispatch_route", "get_vehicle_inventory", "get_route_live_inventory",
            "_dispatch_apply_pack_deltas", "_dispatch_absolute_targets",
            "_dispatch_sync_route_plan_to_current_vehicle", "adjust_route_inventory",
            "update_route_status", "undo_end_work",
        })
        adapter = _function_source(DISPATCH, "_dispatch_vehicle_location_id")
        self.assertIn("resolve_vehicle_custody_location_id(", adapter)
        self.assertNotIn("select(", adapter)
        self.assertNotIn("with_for_update", adapter)


class DispatchCustodyWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def _adjust_setup(self, before=(501,), after=(501,), operational=True):
        db = MagicMock(spec=AsyncSession)
        route = SimpleNamespace(id=701, driver_id=303, vehicle_id=801, source_location_id=901)
        db.execute.side_effect = [_result(route), _result(ids=before), _result(ids=after)]
        db.scalar.return_value = True
        events = []
        guard = AsyncMock(side_effect=lambda *args, **kwargs: events.append("guard"))
        read = AsyncMock(side_effect=lambda *args, **kwargs: (
            events.append("vehicle_read") or
            SimpleNamespace(is_active=True, maintenance_status="Active" if operational else "In_Maintenance")
        ))
        namespace = _load_dispatch_functions(
            "_dispatch_vehicle_location_id", "adjust_route_inventory",
            require_route=AsyncMock(), begin_idempotent_operation=AsyncMock(return_value=(SimpleNamespace(), None)),
            _dispatch_bound_session=AsyncMock(return_value=None),
            _dispatch_variant_map=AsyncMock(return_value={111: SimpleNamespace(packs_per_carton=5)}),
            acquire_inventory_location_guard=guard, read_vehicle_operational_state=read,
            _dispatch_available_totals=AsyncMock(return_value={}),
            _dispatch_apply_pack_deltas=AsyncMock(return_value="DIRECT"),
            complete_idempotent_operation=Mock(), _DB_INT_MAX_DISPATCH=2_147_483_647,
            dispatch_manager=SimpleNamespace(broadcast=AsyncMock()), logger=Mock(),
        )
        kwargs = dict(
            route_id=701, payload=SimpleNamespace(request_id="stable-command-id",
                deltas=[SimpleNamespace(product_id=111, delta_cartons=2)]),
            db=db, access=SimpleNamespace(company_id=7), legacy_actor=SimpleNamespace(id=303),
        )
        return SimpleNamespace(db=db, namespace=namespace, events=events, kwargs=kwargs)

    async def test_adjust_preserves_location_guard_then_plain_vehicle_read_and_movement_seam(self):
        setup = self._adjust_setup()
        await setup.namespace["adjust_route_inventory"](**setup.kwargs)
        self.assertEqual(setup.events, ["guard", "vehicle_read"])
        setup.namespace["acquire_inventory_location_guard"].assert_awaited_once_with(
            setup.db, 7, 501, exclusive=True
        )
        setup.namespace["_dispatch_apply_pack_deltas"].assert_awaited_once()
        movement = setup.namespace["_dispatch_apply_pack_deltas"].await_args.kwargs
        self.assertEqual(movement["route"].source_location_id, 901)
        self.assertEqual(movement["pack_deltas"], {111: 10})
        self.assertEqual(movement["plan_targets"], {111: 10})
        queries = [call.args[0] for call in setup.db.execute.await_args_list]
        self.assertIsNotNone(queries[0]._for_update_arg)
        self.assertTrue(all(query._for_update_arg is None for query in queries[1:]))
        setup.db.commit.assert_awaited_once()
        setup.db.rollback.assert_not_awaited()

    async def test_adjust_replay_returns_original_result_before_custody_or_inventory_work(self):
        setup = self._adjust_setup()
        replay = {"message": "replayed-result"}
        setup.namespace["begin_idempotent_operation"].return_value = (None, replay)
        self.assertIs(await setup.namespace["adjust_route_inventory"](**setup.kwargs), replay)
        idem = setup.namespace["begin_idempotent_operation"].await_args.kwargs
        self.assertEqual(idem["request_id"], "stable-command-id")
        self.assertEqual(idem["operation"], "DISPATCH_ADJUST_ROUTE_INVENTORY")
        setup.db.execute.assert_not_awaited()
        setup.namespace["_dispatch_apply_pack_deltas"].assert_not_awaited()
        setup.db.commit.assert_not_awaited()
        setup.db.rollback.assert_awaited_once()

    async def test_adjust_rejects_bad_custody_before_movements_and_commit(self):
        for before, after, code, guarded in (
            ((), (501,), "VEHICLE_CUSTODY_LOCATION_MISSING", False),
            ((501, 502), (501,), "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS", False),
            ((501,), (501, 502), "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS", True),
            ((501,), (), "VEHICLE_CUSTODY_LOCATION_MISSING", True),
            ((501,), (502,), "VEHICLE_CUSTODY_LOCATION_INCONSISTENT", True),
        ):
            with self.subTest(code=code, guarded=guarded):
                setup = self._adjust_setup(before=before, after=after)
                with self.assertRaises(HTTPException) as rejected:
                    await setup.namespace["adjust_route_inventory"](**setup.kwargs)
                self.assertEqual(rejected.exception.status_code, 409)
                self.assertEqual(rejected.exception.detail["code"], code)
                self.assertEqual(setup.namespace["acquire_inventory_location_guard"].await_count, guarded)
                setup.namespace["read_vehicle_operational_state"].assert_not_awaited()
                setup.namespace["_dispatch_apply_pack_deltas"].assert_not_awaited()
                setup.db.commit.assert_not_awaited()
                setup.db.rollback.assert_awaited_once()

    async def test_adjust_rejects_inactive_custody_and_maintenance(self):
        for inactive in (True, False):
            with self.subTest(inactive_custody=inactive):
                setup = self._adjust_setup(operational=inactive)
                setup.db.scalar.return_value = not inactive
                with self.assertRaises(HTTPException) as rejected:
                    await setup.namespace["adjust_route_inventory"](**setup.kwargs)
                self.assertEqual(rejected.exception.status_code, 409)
                setup.namespace["_dispatch_apply_pack_deltas"].assert_not_awaited()
                setup.db.commit.assert_not_awaited()
                setup.db.rollback.assert_awaited_once()

    async def test_pre_session_activation_rejects_invalid_custody_without_mutating_route(self):
        for ids, active, code in (
            ((), True, "VEHICLE_CUSTODY_LOCATION_MISSING"),
            ((501, 502), True, "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"),
            ((501,), False, "VEHICLE_CUSTODY_LOCATION_INACTIVE"),
        ):
            with self.subTest(code=code):
                db = MagicMock(spec=AsyncSession)
                route = SimpleNamespace(id=701, driver_id=303, vehicle_id=801, zone_id=901,
                                        work_session_id=None, status="postponed")
                snapshot = SimpleNamespace(**vars(route))
                driver = SimpleNamespace(id=303, is_active=True)
                vehicle = SimpleNamespace(id=801, is_active=True, maintenance_status="Active")
                db.execute.side_effect = [
                    _result(snapshot), _result(rows=[(driver, True)]), _result(ids=[vehicle]),
                    _result(route), _result(ids=ids),
                ]
                db.scalar.return_value = active
                namespace = _load_dispatch_functions(
                    "_dispatch_vehicle_location_id", "update_route_status",
                    require_route=AsyncMock(), require_vehicle=AsyncMock(),
                    has_canonical_field_identity=Mock(return_value=True),
                    _dispatch_lock_zone_rows=AsyncMock(return_value={901: SimpleNamespace(is_active=True)}),
                    logger=Mock(),
                )
                with self.assertRaises(HTTPException) as rejected:
                    await namespace["update_route_status"](
                        route_id=701, payload=SimpleNamespace(status="active", driverId=None,
                            vehicleId=None, inventory=None),
                        db=db, access=SimpleNamespace(company_id=7), legacy_actor=SimpleNamespace(id=404),
                    )
                self.assertEqual(rejected.exception.status_code, 409)
                self.assertEqual(rejected.exception.detail["code"], code)
                self.assertEqual(route.status, "postponed")
                db.add.assert_not_called()
                db.commit.assert_not_awaited()
                db.rollback.assert_awaited_once()

    async def test_bound_route_can_close_with_maintenance_vehicle_without_custody_or_stock_reassignment(self):
        db = MagicMock(spec=AsyncSession)
        route = SimpleNamespace(id=701, driver_id=303, vehicle_id=801, zone_id=901,
                                work_session_id=601, status="active")
        session = SimpleNamespace(id=601, end_time=None)
        snapshot = SimpleNamespace(**vars(route))
        vehicle = SimpleNamespace(id=801, is_active=True, maintenance_status="In_Maintenance")
        driver = SimpleNamespace(id=303, is_active=True)
        db.execute.side_effect = [_result(snapshot), _result(session), _result((driver, True)),
                                  _result(vehicle), _result(route), _result(), _result()]
        custody = AsyncMock(side_effect=AssertionError("Plain close must not enter custody eligibility"))
        namespace = _load_dispatch_functions(
            "update_route_status", require_route=AsyncMock(), require_vehicle=AsyncMock(),
            has_canonical_field_identity=Mock(return_value=True),
            _dispatch_lock_zone_rows=AsyncMock(return_value={901: SimpleNamespace(is_active=True,
                start_date=None, interval_days=None)}),
            _dispatch_vehicle_location_id=custody, get_company_local_date=AsyncMock(return_value=date(2026, 10, 14)),
            dispatch_manager=SimpleNamespace(broadcast=AsyncMock()), logger=Mock(),
        )
        await namespace["update_route_status"](
            route_id=701, payload=SimpleNamespace(status="closed", driverId=None, vehicleId=None, inventory=None),
            db=db, access=SimpleNamespace(company_id=7), legacy_actor=SimpleNamespace(id=404),
        )
        self.assertEqual((route.status, route.vehicle_id, route.driver_id), ("closed", 801, 303))
        custody.assert_not_awaited()
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()
        self.assertEqual(len(db.add.call_args_list), 1)
        self.assertIsInstance(db.add.call_args.args[0], SystemAuditLog)



class CompleteCustodyReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_bulk_resolver_checks_all_history_in_one_query(self):
        db = MagicMock(spec=AsyncSession)
        db.execute.return_value = _result(rows=[(801, 501, True), (802, 502, False)])
        self.assertEqual(await resolve_vehicle_custody_location_ids(
            db, company_id=7, vehicle_ids=[801, 802], require_active=False
        ), {801: 501, 802: 502})
        db.execute.assert_awaited_once()
        statement = db.execute.await_args.args[0]
        self.assertIsNone(statement._limit_clause)
        self.assertIsNone(statement._for_update_arg)
        self.assertNotIn("is_active IS", _sql(statement))

    async def test_bulk_missing_duplicate_and_inactive_mapping_fail_closed(self):
        for rows, active, code in (
            ([], False, "VEHICLE_CUSTODY_LOCATION_MISSING"),
            ([(801, 501, True), (801, 502, False)], False, "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"),
            ([(801, 501, False), (801, 502, False)], True, "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"),
            ([(801, 501, False)], True, "VEHICLE_CUSTODY_LOCATION_INACTIVE"),
        ):
            with self.subTest(code=code):
                db = MagicMock(spec=AsyncSession)
                db.execute.return_value = _result(rows=rows)
                with self.assertRaises(VehicleError) as rejected:
                    await resolve_vehicle_custody_location_ids(
                        db, company_id=7, vehicle_ids=[801], require_active=active
                    )
                self.assertEqual(rejected.exception.code, code)
                db.execute.assert_awaited_once()

    def test_dispatch_ready_sql_filters_custody_maintenance_tenant_and_location_grants(self):
        # Execute the real SQL predicate in SQLite memory, not PostgreSQL acceptance.
        engine = create_engine("sqlite://")
        with engine.begin() as db:
            db.exec_driver_sql("CREATE TABLE vehicles (id INTEGER, company_id INTEGER, is_active BOOLEAN, maintenance_status TEXT)")
            db.exec_driver_sql("CREATE TABLE inventory_locations (id INTEGER, company_id INTEGER, vehicle_id INTEGER, location_type TEXT, is_active BOOLEAN)")
            for vehicle_id in range(1, 12):
                db.exec_driver_sql("INSERT INTO vehicles VALUES (?, ?, ?, ?)", (
                    vehicle_id, 9 if vehicle_id == 8 else 7, vehicle_id != 7,
                    "In_Maintenance" if vehicle_id == 6 else "Active",
                ))
            rows = [
                (11, 7, 1, "VEHICLE", True), (31, 7, 3, "VEHICLE", False),
                (41, 7, 4, "VEHICLE", True), (42, 7, 4, "VEHICLE", False),
                (51, 7, 5, "VEHICLE", False), (52, 7, 5, "VEHICLE", False),
                (61, 7, 6, "VEHICLE", True), (71, 7, 7, "VEHICLE", True),
                (81, 9, 8, "VEHICLE", True), (91, 7, 9, "WAREHOUSE", True),
                (101, 9, 10, "VEHICLE", True), (111, 7, 11, "VEHICLE", True),
            ]
            db.exec_driver_sql("INSERT INTO inventory_locations VALUES (?, ?, ?, ?, ?)", rows)
            for code in ("dispatch.read", "dispatch.execute"):
                access = SimpleNamespace(company_id=7, allows=lambda code, column: column.in_([11, 41, 61, 71, 81, 91, 101]))
                query = select(Vehicle.id).where(
                    Vehicle.company_id == 7, vehicle_operational_predicate(Vehicle),
                    vehicle_custody_ready_predicate(Vehicle), vehicle_filter(access, code, Vehicle.id),
                )
                self.assertEqual(list(db.scalars(query)), [1])
        engine.dispose()
        source = _function_source(DISPATCH, "dispatch_init")
        self.assertEqual(source.count("vehicle_custody_ready_predicate(Vehicle)"), 2)
        self.assertIn("vehicle_filter(access, 'dispatch.read'", source)
        self.assertIn("vehicle_filter(access, 'dispatch.execute'", source)

    async def test_dispatch_session_fallback_uses_bulk_strict_mapping_and_allows_historical_inactive_row(self):
        from sqlalchemy.orm import joinedload
        db = MagicMock(spec=AsyncSession)
        session = SimpleNamespace(id=601, inventory_reconciled_at=None)
        route = SimpleNamespace(work_session_id=601, vehicle_id=801)
        db.execute.side_effect = [
            _result(ids=[route]), _result(rows=[]), _result(rows=[(801, 501, False)]),
            _result(rows=[]), _result(rows=[]),
        ]
        namespace = _load_dispatch_functions("_dispatch_session_inventory_projection", joinedload=joinedload)
        projection, routes = await namespace["_dispatch_session_inventory_projection"](db, company_id=7, sessions=[session])
        self.assertEqual(projection, {601: []})
        self.assertIs(routes[601], route)
        self.assertEqual(db.execute.await_count, 5)

    async def test_dispatch_session_fallback_rejects_missing_and_duplicate_history(self):
        from sqlalchemy.orm import joinedload
        for rows, code in (
            ([], "VEHICLE_CUSTODY_LOCATION_MISSING"),
            ([(801, 501, True), (801, 502, False)], "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"),
        ):
            with self.subTest(code=code):
                db = MagicMock(spec=AsyncSession)
                db.execute.side_effect = [
                    _result(ids=[SimpleNamespace(work_session_id=601, vehicle_id=801)]),
                    _result(rows=[]), _result(rows=rows),
                ]
                namespace = _load_dispatch_functions("_dispatch_session_inventory_projection", joinedload=joinedload)
                with self.assertRaises(HTTPException) as rejected:
                    await namespace["_dispatch_session_inventory_projection"](db, company_id=7, sessions=[SimpleNamespace(id=601)])
                self.assertEqual((rejected.exception.status_code, rejected.exception.detail["code"]), (409, code))
                self.assertEqual(db.execute.await_count, 3)

    async def test_transfer_history_query_intentionally_keeps_all_custody_ids(self):
        db = MagicMock(spec=AsyncSession)
        db.execute.return_value = _result(ids=[501, 502])
        namespace = _load_dispatch_functions("_dispatch_vehicle_location_ids")
        self.assertEqual(await namespace["_dispatch_vehicle_location_ids"](db, company_id=7, vehicle_id=801), [501, 502])
        query = db.execute.await_args.args[0]
        self.assertIsNone(query._limit_clause)
        self.assertNotIn("is_active", _sql(query))
        self.assertIn("Historical transfer evidence", _function_source(DISPATCH, "_dispatch_vehicle_location_ids"))

    def test_no_operational_router_query_chooses_vehicle_custody_directly(self):
        remaining = {}
        for path in (DRIVER, DISPATCH):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            owners = []
            for node in tree.body:
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                selects = [
                    call for call in ast.walk(node) if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name) and call.func.id == "select"
                    and any(isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name)
                            and arg.value.id == "InventoryLocation" for arg in call.args)
                ]
                filters = [
                    call for call in ast.walk(node) if isinstance(call, ast.Call)
                    and any(kw.arg == "vehicle_id" for kw in call.keywords)
                    and any(kw.arg == "location_type" and isinstance(kw.value, ast.Constant)
                            and kw.value.value == "VEHICLE" for kw in call.keywords)
                ] + [
                    attribute for attribute in ast.walk(node) if isinstance(attribute, ast.Attribute)
                    and isinstance(attribute.value, ast.Name) and attribute.value.id == "InventoryLocation"
                    and attribute.attr == "vehicle_id"
                ]
                if selects and filters:
                    owners.append(node.name)
            remaining[path.name] = owners
        self.assertEqual(remaining, {
            "driver.py": ["start_work_session"], "dispatch.py": ["_dispatch_vehicle_location_ids"],
        })
        source = _function_source(DRIVER, "start_work_session")
        self.assertIn("id=vehicle_location_id", source)
        self.assertEqual(source.count("resolve_vehicle_custody_location_id("), 2)


class RouteStatusAbsoluteInventoryRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setup_route(self, bound=False, fail=False):
        db = MagicMock(spec=AsyncSession)
        route = SimpleNamespace(id=701, driver_id=303, vehicle_id=801, zone_id=1001,
            work_session_id=601 if bound else None, status="active", source_location_id=901)
        driver = SimpleNamespace(id=303, is_active=True)
        vehicle = SimpleNamespace(id=801, is_active=True, maintenance_status="Active")
        session = SimpleNamespace(id=601, end_time=None, inventory_reconciled_at=None, commercial_context_id=1001)
        snapshot = SimpleNamespace(**vars(route))
        def execute(statement):
            descriptions = getattr(statement, "column_descriptions", ())
            entity = descriptions[0].get("entity") if descriptions else None
            if entity is DispatchRoute:
                if len(descriptions) == 5:
                    return _result(snapshot)
                return _result(route) if descriptions[0]["name"] == "DispatchRoute" else _result()
            if entity is Driver:
                return _result((driver, True), rows=[(driver, True)])
            if entity is Vehicle:
                return _result(vehicle, ids=[vehicle])
            if entity is WorkSession:
                return _result(session)
            if entity is InventoryLocation:
                return _result(ids=[501])
            if entity in (InventoryBalance, Shop):
                return _result()
            raise AssertionError(f"Unexpected SQL: {statement}")
        db.execute.side_effect = execute
        db.scalar.return_value = True
        db.scalars.return_value = _result(rows=[SimpleNamespace(product_variant_id=111, operational_flags={})])
        current, pending = {}, {}
        async def movements(*args, **kwargs):
            if fail:
                raise InventoryMutationError("synthetic downstream inventory failure")
            for spec in kwargs["movements"]:
                sign = -1 if spec["source_location_id"] == 501 else 1
                if spec["movement_kind"] == "RESERVATION":
                    pending[111] = pending.get(111, 0) + sign * spec["quantity"]
                else:
                    current[111] = (current.get(111, (0, 0))[0] + sign * spec["quantity"], 0)
        async def flush():
            for call in db.add.call_args_list:
                if isinstance(call.args[0], InventoryTransferHeader) and call.args[0].id is None:
                    call.args[0].id = 21
        db.flush.side_effect = flush
        namespace = _load_dispatch_functions(
            "_dispatch_vehicle_location_id", "_dispatch_absolute_targets", "_dispatch_apply_pack_deltas", "update_route_status",
            require_route=AsyncMock(), require_vehicle=AsyncMock(),
            has_canonical_field_identity=Mock(return_value=True),
            _dispatch_lock_zone_rows=AsyncMock(return_value={1001: SimpleNamespace(is_active=True, start_date=None, interval_days=None)}),
            _dispatch_assert_vehicle_custody_reconciled=AsyncMock(),
            _dispatch_source_warehouse=AsyncMock(return_value=SimpleNamespace(id=901)),
            _dispatch_available_totals=AsyncMock(side_effect=lambda *a, **k: dict(current)),
            _dispatch_pending_handshake_net=AsyncMock(side_effect=lambda *a, **k: dict(pending)),
            _dispatch_variant_map=AsyncMock(return_value={111: SimpleNamespace(variant_name="Synthetic",
                packs_per_carton=5, lifecycle_status="ACTIVE", operational_hold="NONE", lifecycle_revision=1)}),
            acquire_inventory_location_guards=AsyncMock(), acquire_product_lifecycle_guards=AsyncMock(),
            check_inventory_lock=AsyncMock(), evaluate_product_capability=Mock(return_value=SimpleNamespace(allowed=True)),
            product_location_allows=Mock(return_value=True), ROUTE_LOAD_NEW="ROUTE_LOAD_NEW",
            _dispatch_allocate_available_batches=AsyncMock(side_effect=lambda *a, **k: [(1, k["quantity"])]),
            apply_inventory_movements_batch=AsyncMock(side_effect=movements),
            _dispatch_set_load_plan_target=AsyncMock(), _DB_INT_MAX_DISPATCH=2_147_483_647,
            get_company_local_date=AsyncMock(return_value=date(2026, 10, 14)),
            lock_route_commercial_context=AsyncMock(return_value=SimpleNamespace(id=1001)),
            require_route_commercial_context=AsyncMock(return_value=SimpleNamespace(id=1001)),
            commercial_context_payload=Mock(return_value={"id": 1001}),
            dispatch_manager=SimpleNamespace(broadcast=AsyncMock()), logger=Mock(),
        )
        kwargs = dict(route_id=701, payload=SimpleNamespace(status=None, driverId=None, vehicleId=None, inventory={"111": 2}),
            db=db, access=SimpleNamespace(company_id=7, principal_id=101, backoffice_user_id=202), legacy_actor=SimpleNamespace(id=404))
        return SimpleNamespace(db=db, namespace=namespace, kwargs=kwargs, route=route)

    async def test_route_status_inventory_before_and_during_session_forwards_exact_legacy_provenance(self):
        for bound in (False, True):
            with self.subTest(bound=bound):
                setup = self.setup_route(bound)
                await setup.namespace["update_route_status"](**setup.kwargs)
                movement = setup.namespace["apply_inventory_movements_batch"]
                movement.assert_awaited_once()
                self.assertEqual(movement.await_args.kwargs["performed_by"], 404)
                self.assertTrue(all(spec["movement_kind"] == ("RESERVATION" if bound else "PHYSICAL")
                                    for spec in movement.await_args.kwargs["movements"]))
                self.assertEqual(setup.namespace["_dispatch_set_load_plan_target"].await_args.kwargs["updated_by"], 404)
                audits = [call.args[0] for call in setup.db.add.call_args_list if isinstance(call.args[0], SystemAuditLog)]
                self.assertTrue(audits)
                self.assertTrue(all(audit.admin_id == 404 for audit in audits))
                if bound:
                    header = next(call.args[0] for call in setup.db.add.call_args_list if isinstance(call.args[0], InventoryTransferHeader))
                    self.assertEqual((header.dispatched_by, header.source_location_id, header.destination_location_id), (404, 901, 501))
                setup.db.commit.assert_awaited_once()
                setup.db.rollback.assert_not_awaited()

    async def test_absolute_target_retry_with_no_delta_does_not_duplicate_stock_transfer_or_audit(self):
        for bound in (False, True):
            with self.subTest(bound=bound):
                setup = self.setup_route(bound)
                await setup.namespace["update_route_status"](**setup.kwargs)
                added = setup.db.add.call_count
                await setup.namespace["update_route_status"](**setup.kwargs)
                setup.namespace["apply_inventory_movements_batch"].assert_awaited_once()
                self.assertEqual(setup.db.add.call_count, added)
                self.assertEqual(setup.namespace["_dispatch_set_load_plan_target"].await_count, 2)
                self.assertEqual(setup.db.commit.await_count, 2)

    async def test_route_status_inventory_rolls_back_real_downstream_error_type(self):
        for bound in (False, True):
            with self.subTest(bound=bound):
                setup = self.setup_route(bound, fail=True)
                with self.assertRaises(HTTPException) as rejected:
                    await setup.namespace["update_route_status"](**setup.kwargs)
                self.assertEqual(rejected.exception.status_code, 409)
                setup.db.commit.assert_not_awaited()
                setup.db.rollback.assert_awaited_once()
                setup.namespace["_dispatch_set_load_plan_target"].assert_not_awaited()
                self.assertFalse(any(isinstance(call.args[0], SystemAuditLog) for call in setup.db.add.call_args_list))


if __name__ == "__main__":
    unittest.main()
