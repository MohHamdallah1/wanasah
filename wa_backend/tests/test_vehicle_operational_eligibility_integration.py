from __future__ import annotations

import ast
import asyncio
import hashlib
import json
from datetime import date, timedelta
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domains.pricing.core import PricingError
from domains.vehicles import VehicleError, resolve_vehicle_custody_location_id
from domains.vehicles import repository as vehicle_repository
from models import (
    DispatchRoute, Driver, InventoryBalance, InventoryLocation, Shop,
    ShortageRequest, SystemAuditLog, Vehicle, Visit, WorkSession,
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


if __name__ == "__main__":
    unittest.main()
