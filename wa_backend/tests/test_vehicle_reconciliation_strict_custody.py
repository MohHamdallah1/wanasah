"""Execute reconciliation/stocktake source bodies with real Vehicles SQL.

Database rows, advisory guards and the inventory engine are controlled doubles.
This suite does not claim PostgreSQL transaction/concurrency acceptance.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import services
import api.reconciliation as reconciliation
from domains.vehicles import VehicleError, resolve_vehicle_custody_location_id
from models import (
    DispatchRoute, Driver, InventoryBalance, InventoryLocation, InventoryLock,
    InventoryMovement, ProductBatch, ProductVariant, SessionInventorySnapshot,
    StocktakeCountAttempt, StocktakeCountAttemptLine, StocktakeLine, StocktakeSession,
    SystemAuditLog, WorkSession,
)

BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 14, 12)
COMPANY, VEHICLE, LOCATION, WORK, FIELD, APPROVER = 7, 22, 11, 55, 9003, 9004
SERVICE_FUNCTIONS = {
    "_require_vehicle_reconciliation_custody", "validate_vehicle_recon_work_session",
    "open_vehicle_reconciliation_stocktake", "finalize_vehicle_inventory_reconciliation",
    "_seal_vehicle_inventory_reconciliation", "post_approved_stocktake_adjustments",
}


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    for node in nodes:
        node.decorator_list, node.returns = [], None
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            arg.annotation = None
        node.args.defaults = [ast.Constant(None) if isinstance(value, ast.Call) else value
                              for value in node.args.defaults]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 str(path), "exec"), namespace)
    return namespace


class Result:
    def __init__(self, one=None, rows=()):
        self.one, self.rows = one, list(rows)

    def scalar_one_or_none(self):
        return self.one

    def one_or_none(self):
        return self.one

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Database:
    """Script non-custody I/O; execute the real public resolver against supplied history."""
    def __init__(self, case, history=None):
        self.case = case
        self.history = [(LOCATION, True)] if history is None else list(history)
        self.script, self.statements, self.events, self.added = [], [], [], []
        self.active_reads = 0
        self.commit, self.rollback = AsyncMock(), AsyncMock()
        self.flush = AsyncMock(side_effect=self.assign_ids)

    async def assign_ids(self):
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = 1000 + self.added.index(row)

    def expect(self, entity, one=None, rows=()):
        self.script.append((entity, Result(one, rows)))

    async def execute(self, statement):
        self.statements.append(statement)
        descriptions = getattr(statement, "column_descriptions", ())
        if (len(descriptions) == 1 and descriptions[0].get("entity") is InventoryLocation
                and descriptions[0].get("name") == "id"):
            self.events.append("custody")
            params = statement.compile().params
            self.case.assertEqual(params["company_id_1"], COMPANY)
            self.case.assertEqual(params["vehicle_id_1"], VEHICLE)
            self.case.assertEqual(params["location_type_1"], "VEHICLE")
            self.case.assertIsNone(statement._limit_clause)
            self.case.assertIsNone(statement._for_update_arg)
            self.case.assertNotIn("is_active", str(statement))
            return Result(rows=[location for location, _ in self.history])
        entity = descriptions[0].get("entity") if descriptions else getattr(statement, "table", None)
        if not descriptions:
            self.events.append("release")
            self.case.assertEqual(getattr(entity, "name", None), "inventory_locks")
            return Result()
        label = descriptions[0].get("name")
        self.events.append(entity.__name__ + ".id" if label == "id" else label)
        self.case.assertTrue(self.script, f"Unexpected SQL: {statement}")
        expected, result = self.script.pop(0)
        self.case.assertIs(entity, expected, f"Unexpected SQL: {statement}")
        return result

    async def scalar(self, statement):
        self.statements.append(statement)
        self.active_reads += 1
        self.events.append("active")
        params = statement.compile().params
        self.case.assertEqual(params["company_id_1"], COMPANY)
        self.case.assertEqual(params["vehicle_id_1"], VEHICLE)
        found = [active for location, active in self.history if location == params["id_1"]]
        return found[0] if found else None

    def add(self, row):
        self.added.append(row)


def work_session():
    return SimpleNamespace(id=WORK, company_id=COMPANY, driver_id=FIELD, end_time=NOW,
        is_settled=False, inventory_reconciled_at=None, inventory_reconciled_by=None)


def snapshot():
    return SimpleNamespace(id=201, location_id=LOCATION, product_variant_id=91,
        stock_status="AVAILABLE", starting_quantity=Decimal("5"),
        ending_quantity=None, settled_by=None, settled_at=None)


def service_namespace(db, *, guard_effect=None):
    async def guard(*args, **kwargs):
        db.events.append("guard")
        if guard_effect:
            guard_effect()
    namespace = dict(vars(services))
    namespace.update(
        acquire_inventory_location_guard=AsyncMock(side_effect=guard),
        apply_inventory_movements_batch=AsyncMock(return_value=[SimpleNamespace(id=555)]),
        utc_now=lambda: NOW,
    )
    return load_functions(BACKEND / "services.py", SERVICE_FUNCTIONS, namespace)


def end_of_day_namespace(service_ns):
    ns = dict(vars(reconciliation))
    ns.update({name: service_ns[name] for name in SERVICE_FUNCTIONS})
    ns.update(acquire_inventory_location_guard=service_ns["acquire_inventory_location_guard"],
              VehicleError=VehicleError, resolve_vehicle_custody_location_id=resolve_vehicle_custody_location_id)
    return load_functions(BACKEND / "api/reconciliation.py", {"reconcile_driver_end_of_day"}, ns)


def start_namespace(service_ns):
    ns = dict(globals(), logger=Mock(), _MAX_STOCKTAKE_LINES=10000,
        _STOCKTAKE_ACTIVE_STATUSES=["DRAFT", "COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED", "APPROVED"],
        _require_location_capability=AsyncMock(),
        InventoryMutationError=services.InventoryMutationError,
        acquire_inventory_location_guard=service_ns["acquire_inventory_location_guard"],
        validate_vehicle_recon_work_session=service_ns["validate_vehicle_recon_work_session"],
    )
    from sqlalchemy.exc import IntegrityError
    ns["IntegrityError"] = IntegrityError
    return load_functions(BACKEND / "api/warehouse/stocktake.py", {
        "start_unified_stocktake", "_stocktake_session_overlap_predicate",
        "_inventory_lock_overlap_predicate", "_utc_naive_now",
    }, ns)


class VehicleReconciliationCustodyTests(unittest.IsolatedAsyncioTestCase):
    def assert_no_effects(self, db, ns):
        ns["apply_inventory_movements_batch"].assert_not_awaited()
        self.assertFalse(db.added)
        db.flush.assert_not_awaited()
        db.commit.assert_not_awaited()

    def invalid_cases(self):
        return (
            ([], "VEHICLE_CUSTODY_LOCATION_MISSING"),
            ([(LOCATION, True), (12, False)], "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"),
            ([(LOCATION, False), (12, False)], "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS"),
            ([(LOCATION, False)], "VEHICLE_CUSTODY_LOCATION_INACTIVE"),
            ([(12, True)], "VEHICLE_CUSTODY_LOCATION_INCONSISTENT"),
        )

    def eod_setup(self, history=None, *, balance="5", actual="5", guard_effect=None):
        db = Database(self, history)
        work = work_session()
        db.expect(WorkSession, work)
        db.expect(DispatchRoute, SimpleNamespace(vehicle_id=VEHICLE))
        db.expect(WorkSession, work)
        db.expect(DispatchRoute, 33)
        db.expect(StocktakeSession)
        db.expect(InventoryLock)
        db.expect(ProductVariant, rows=[SimpleNamespace(id=91, quantity_scale=0, quantity_step=Decimal("1"))])
        db.expect(InventoryBalance, rows=[SimpleNamespace(product_variant_id=91,
            on_hand_quantity=Decimal(balance), reserved_quantity=Decimal("0"))])
        ns = service_namespace(db, guard_effect=guard_effect)
        endpoint = end_of_day_namespace(ns)
        payload = reconciliation.VehicleReconciliationRequest(counts=[
            reconciliation.VehicleCountItem(product_variant_id=91, actual_quantity=actual)
        ])
        kwargs = dict(session_id=WORK, payload=payload, db=db,
            field_context=SimpleNamespace(company_id=COMPANY, principal_id=7001, field_representative_id=8002),
            legacy_actor=SimpleNamespace(id=FIELD, company_id=999))
        return SimpleNamespace(db=db, work=work, ns=ns, endpoint=endpoint, kwargs=kwargs)

    async def test_canonical_active_end_of_day_seals_snapshot_and_preserves_provenance(self):
        setup = self.eod_setup()
        snap = snapshot()
        setup.db.expect(Driver, FIELD)
        setup.db.expect(WorkSession, setup.work)
        setup.db.expect(InventoryLocation, SimpleNamespace(vehicle_id=VEHICLE))
        setup.db.expect(DispatchRoute, 33)
        setup.db.expect(SessionInventorySnapshot, rows=[snap])
        setup.db.expect(InventoryBalance, rows=[SimpleNamespace(product_variant_id=91,
            stock_status="AVAILABLE", on_hand_quantity=Decimal("5"), reserved_quantity=0)])
        response = await setup.endpoint["reconcile_driver_end_of_day"](**setup.kwargs)
        self.assertFalse(response["requires_audit"])
        self.assertEqual((setup.work.inventory_reconciled_at, setup.work.inventory_reconciled_by), (NOW, FIELD))
        self.assertEqual((snap.ending_quantity, snap.settled_by), (Decimal("5"), FIELD))
        self.assertFalse(setup.work.is_settled)
        self.assertEqual(setup.db.added[0].admin_id, FIELD)
        self.assertEqual(setup.db.added[0].company_id, COMPANY)
        setup.db.commit.assert_awaited_once()
        setup.ns["apply_inventory_movements_batch"].assert_not_awaited()
        self.assertFalse(setup.db.script)
        self.assertLess(setup.db.events.index("guard"), setup.db.events.index("InventoryBalance"))


    async def test_end_of_day_variance_opens_only_targeted_recon_without_sealing(self):
        setup = self.eod_setup(actual="4")
        setup.db.expect(Driver, FIELD)
        setup.db.expect(InventoryLocation, SimpleNamespace(vehicle_id=VEHICLE))
        setup.db.expect(WorkSession, setup.work)
        setup.db.expect(DispatchRoute, 33)
        setup.db.expect(ProductVariant, rows=[91])
        setup.db.expect(StocktakeSession)
        setup.db.expect(StocktakeSession)
        setup.db.expect(InventoryLock)
        setup.db.expect(InventoryBalance, rows=[SimpleNamespace(product_variant_id=91, batch_id=101,
            stock_status="AVAILABLE", on_hand_quantity=Decimal("5"))])
        result = await setup.endpoint["reconcile_driver_end_of_day"](**setup.kwargs)
        self.assertTrue(result["requires_audit"])
        self.assertEqual(result["variance_product_ids"], [91])
        self.assertEqual(result["stocktake_status"], "COUNTING")
        self.assertIsNone(setup.work.inventory_reconciled_at)
        self.assertEqual(setup.db.added[0].started_by, FIELD)
        self.assertEqual(setup.db.added[-1].admin_id, FIELD)
        self.assertFalse(setup.db.script)
        setup.ns["apply_inventory_movements_batch"].assert_not_awaited()
        setup.db.commit.assert_awaited_once()

    async def test_end_of_day_downstream_failure_rolls_back_without_audit_or_commit(self):
        setup = self.eod_setup()
        setup.endpoint["finalize_vehicle_inventory_reconciliation"] = AsyncMock(
            side_effect=services.InventoryMutationError("synthetic downstream failure"))
        with self.assertRaises(HTTPException) as caught:
            await setup.endpoint["reconcile_driver_end_of_day"](**setup.kwargs)
        self.assertEqual(caught.exception.status_code, 409)
        self.assert_no_effects(setup.db, setup.ns)
        self.assertIsNone(setup.work.inventory_reconciled_at)
        setup.db.rollback.assert_awaited_once()

    async def test_end_of_day_missing_duplicate_or_inactive_fails_before_reconciliation(self):
        for history, code in self.invalid_cases()[:-1]:
            with self.subTest(code=code):
                setup = self.eod_setup(history)
                with self.assertRaises(HTTPException) as caught:
                    await setup.endpoint["reconcile_driver_end_of_day"](**setup.kwargs)
                self.assertEqual((caught.exception.status_code, caught.exception.detail["code"]), (409, code))
                self.assert_no_effects(setup.db, setup.ns)
                self.assertNotIn("InventoryBalance", setup.db.events)
                self.assertIsNone(setup.work.inventory_reconciled_at)
                setup.db.rollback.assert_awaited_once()
                if len(history) != 1:
                    self.assertEqual(setup.db.active_reads, 0)

    async def test_end_of_day_revalidates_under_guard_before_effects(self):
        setup = self.eod_setup()
        setup.ns["acquire_inventory_location_guard"].side_effect = lambda *a, **k: (
            setup.db.events.append("guard"), setup.db.history.append((12, False)))
        with self.assertRaises(HTTPException) as caught:
            await setup.endpoint["reconcile_driver_end_of_day"](**setup.kwargs)
        self.assertEqual(caught.exception.detail["code"], "VEHICLE_CUSTODY_LOCATION_AMBIGUOUS")
        self.assert_no_effects(setup.db, setup.ns)
        self.assertIsNone(setup.work.inventory_reconciled_at)
        setup.db.rollback.assert_awaited_once()

    async def test_end_of_day_existing_seal_replay_never_reopens_custody_or_mutates(self):
        db = Database(self, [])
        work = work_session()
        work.inventory_reconciled_at, work.inventory_reconciled_by = NOW, FIELD
        db.expect(WorkSession, work)
        ns = service_namespace(db)
        result = await end_of_day_namespace(ns)["reconcile_driver_end_of_day"](
            WORK, reconciliation.VehicleReconciliationRequest(counts=[]), db,
            SimpleNamespace(company_id=COMPANY), SimpleNamespace(id=FIELD))
        self.assertTrue(result["already_reconciled"])
        self.assertEqual(db.events, ["WorkSession"])
        self.assert_no_effects(db, ns)
        db.rollback.assert_awaited_once()

    def open_setup(self, history=None, *, wrong=LOCATION, existing=None, guard_effect=None):
        db = Database(self, history)
        ns = service_namespace(db, guard_effect=guard_effect)
        work = work_session()
        db.expect(Driver, FIELD)
        db.expect(InventoryLocation, SimpleNamespace(vehicle_id=VEHICLE))
        db.expect(WorkSession, work)
        db.expect(DispatchRoute, 33)
        db.expect(ProductVariant, rows=[91])
        db.expect(StocktakeSession, existing)
        if existing is None:
            db.expect(StocktakeSession)
            db.expect(InventoryLock)
            db.expect(InventoryBalance, rows=[SimpleNamespace(product_variant_id=91, batch_id=101,
                stock_status="AVAILABLE", on_hand_quantity=Decimal("5"))])
        kwargs = dict(company_id=COMPANY, work_session_id=WORK, vehicle_location_id=wrong,
            started_by=FIELD, product_variant_ids=[91], notes=" variance ")
        return SimpleNamespace(db=db, ns=ns, work=work, kwargs=kwargs)

    async def test_open_requires_canonical_custody_before_stocktake_lock_or_snapshot_creation(self):
        for history, code in self.invalid_cases():
            with self.subTest(code=code):
                setup = self.open_setup(history)
                with self.assertRaises(services.InventoryMutationError) as caught:
                    await setup.ns["open_vehicle_reconciliation_stocktake"](setup.db, **setup.kwargs)
                self.assertIn(code, str(caught.exception))
                self.assert_no_effects(setup.db, setup.ns)
                self.assertIsNone(setup.work.inventory_reconciled_at)

    async def test_open_canonical_success_and_existing_replay_preserve_stocktake_state(self):
        setup = self.open_setup()
        session, created = await setup.ns["open_vehicle_reconciliation_stocktake"](setup.db, **setup.kwargs)
        self.assertTrue(created)
        self.assertEqual((session.status, session.started_by, session.related_work_session_id), ("COUNTING", FIELD, WORK))
        self.assertEqual((setup.db.added[1].location_id, setup.db.added[1].created_by), (LOCATION, FIELD))
        self.assertEqual(setup.db.added[2].expected_quantity, Decimal("5"))
        self.assertFalse(setup.db.script)
        existing = SimpleNamespace(id=66, status="COUNTING")
        replay = self.open_setup(existing=existing)
        self.assertEqual(await replay.ns["open_vehicle_reconciliation_stocktake"](replay.db, **replay.kwargs), (existing, False))
        self.assert_no_effects(replay.db, replay.ns)

    async def test_open_guard_closes_custody_change_before_creation(self):
        setup = self.open_setup()
        setup.ns["acquire_inventory_location_guard"].side_effect = lambda *a, **k: setup.db.history.append((12, False))
        with self.assertRaises(services.InventoryMutationError) as caught:
            await setup.ns["open_vehicle_reconciliation_stocktake"](setup.db, **setup.kwargs)
        self.assertIn("VEHICLE_CUSTODY_LOCATION_AMBIGUOUS", str(caught.exception))
        self.assert_no_effects(setup.db, setup.ns)

    def start_setup(self, history=None, *, location_id=LOCATION, kind="VEHICLE_RECON"):
        db = Database(self, history)
        ns = service_namespace(db)
        endpoint = start_namespace(ns)
        payload = SimpleNamespace(location_id=location_id, stocktake_type=kind,
            related_work_session_id=WORK if kind == "VEHICLE_RECON" else None,
            product_variant_id=None, batch_id=None, notes=None)
        db.expect(InventoryLocation, SimpleNamespace(vehicle_id=VEHICLE if kind == "VEHICLE_RECON" else None))
        if kind == "VEHICLE_RECON":
            db.expect(WorkSession, work_session())
            db.expect(DispatchRoute, 33)
            db.expect(StocktakeSession)
        db.expect(StocktakeSession)
        db.expect(InventoryLock)
        db.expect(InventoryBalance, rows=[])
        kwargs = dict(payload=payload, db=db, access=SimpleNamespace(company_id=COMPANY),
            legacy_actor=SimpleNamespace(id=APPROVER, company_id=999))
        return SimpleNamespace(db=db, ns=ns, endpoint=endpoint, kwargs=kwargs)

    async def test_vehicle_recon_explicit_location_must_equal_strict_canonical_identity(self):
        for history, code in self.invalid_cases():
            with self.subTest(code=code):
                setup = self.start_setup(history)
                with self.assertRaises(HTTPException) as caught:
                    await setup.endpoint["start_unified_stocktake"](**setup.kwargs)
                self.assertEqual((caught.exception.status_code, caught.exception.detail["code"]), (409, code))
                self.assert_no_effects(setup.db, setup.ns)
                setup.db.rollback.assert_awaited_once()
                if len(history) != 1:
                    self.assertEqual(setup.db.active_reads, 0)

    async def test_vehicle_recon_rejects_wrong_supplied_location_even_when_active(self):
        setup = self.start_setup(location_id=99)
        with self.assertRaises(HTTPException) as caught:
            await setup.endpoint["start_unified_stocktake"](**setup.kwargs)
        self.assertEqual(caught.exception.detail["code"], "VEHICLE_CUSTODY_LOCATION_INCONSISTENT")
        self.assert_no_effects(setup.db, setup.ns)
        setup.db.rollback.assert_awaited_once()

    async def test_vehicle_recon_location_must_belong_to_the_work_session_vehicle(self):
        setup = self.start_setup()
        setup.db.script[2] = (DispatchRoute, Result())
        with self.assertRaises(HTTPException) as caught:
            await setup.endpoint["start_unified_stocktake"](**setup.kwargs)
        self.assertEqual(caught.exception.status_code, 409)
        self.assert_no_effects(setup.db, setup.ns)
        setup.db.rollback.assert_awaited_once()

    async def test_vehicle_recon_canonical_start_and_normal_warehouse_start(self):
        for kind in ("VEHICLE_RECON", "FULL_COUNT"):
            with self.subTest(kind=kind):
                setup = self.start_setup(kind=kind)
                response = await setup.endpoint["start_unified_stocktake"](**setup.kwargs)
                self.assertEqual(response["stocktake_type"], kind)
                self.assertEqual(setup.db.added[0].started_by, APPROVER)
                self.assertEqual(setup.db.added[1].created_by, APPROVER)
                setup.db.commit.assert_awaited_once()
                self.assertFalse(setup.db.script)
                first = setup.db.statements[0]
                self.assertEqual("is_active IS true" in str(first), kind == "FULL_COUNT")
                if kind == "FULL_COUNT":
                    self.assertNotIn("custody", setup.db.events)
                    self.assertEqual(setup.db.active_reads, 0)

    async def test_warehouse_start_still_rejects_missing_or_inactive_location(self):
        setup = self.start_setup(kind="FULL_COUNT")
        setup.db.script[0] = (InventoryLocation, Result())
        with self.assertRaises(HTTPException) as caught:
            await setup.endpoint["start_unified_stocktake"](**setup.kwargs)
        self.assertEqual(caught.exception.status_code, 404)
        self.assert_no_effects(setup.db, setup.ns)
        setup.db.rollback.assert_awaited_once()

    def seal_setup(self, history=None, *, wrong=LOCATION):
        db = Database(self, history)
        ns = service_namespace(db)
        work, snap = work_session(), snapshot()
        db.expect(InventoryLocation, SimpleNamespace(vehicle_id=VEHICLE))
        db.expect(DispatchRoute, 33)
        db.expect(SessionInventorySnapshot, rows=[snap])
        db.expect(InventoryBalance, rows=[SimpleNamespace(product_variant_id=91, stock_status="AVAILABLE",
            on_hand_quantity=Decimal("6"), reserved_quantity=0)])
        kwargs = dict(company_id=COMPANY, work_session=work, vehicle_location_id=wrong, settled_by=APPROVER)
        return SimpleNamespace(db=db, ns=ns, work=work, snap=snap, kwargs=kwargs)

    async def test_ambiguity_or_stale_identity_before_seal_never_writes_ending_snapshot(self):
        for history, code in self.invalid_cases():
            with self.subTest(code=code):
                setup = self.seal_setup(history)
                with self.assertRaises(services.InventoryMutationError) as caught:
                    await setup.ns["_seal_vehicle_inventory_reconciliation"](setup.db, **setup.kwargs)
                self.assertIn(code, str(caught.exception))
                self.assertIsNone(setup.work.inventory_reconciled_at)
                self.assertIsNone(setup.snap.ending_quantity)
                self.assert_no_effects(setup.db, setup.ns)

    async def test_successful_seal_and_seal_replay_preserve_inventory_financial_boundary(self):
        setup = self.seal_setup()
        self.assertIs(await setup.ns["_seal_vehicle_inventory_reconciliation"](setup.db, **setup.kwargs), setup.work)
        self.assertEqual((setup.work.inventory_reconciled_by, setup.snap.settled_by), (APPROVER, APPROVER))
        self.assertEqual(setup.snap.ending_quantity, Decimal("6"))
        self.assertFalse(setup.work.is_settled)
        setup.db.commit.assert_not_awaited()
        replay = self.seal_setup()
        replay.work.inventory_reconciled_at, replay.work.inventory_reconciled_by = NOW, APPROVER
        replay.snap.ending_quantity, replay.snap.settled_by, replay.snap.settled_at = Decimal("6"), APPROVER, NOW
        self.assertIs(await replay.ns["_seal_vehicle_inventory_reconciliation"](replay.db, **replay.kwargs), replay.work)
        replay.db.flush.assert_not_awaited()
        self.assertNotIn("InventoryBalance", replay.db.events)

    def post_setup(self, history=None, *, kind="VEHICLE_RECON", replay=False):
        vehicle = kind == "VEHICLE_RECON"
        db = Database(self, history)
        ns = service_namespace(db)
        work, snap = work_session(), snapshot()
        session = SimpleNamespace(id=66, company_id=COMPANY, location_id=LOCATION,
            stocktake_type=kind, related_work_session_id=WORK if vehicle else None,
            status="POSTED" if replay else "APPROVED", approved_by=APPROVER, approved_at=NOW,
            posted_at=NOW if replay else None, snapshot_cutoff_at=NOW-timedelta(minutes=3),
            scope_product_variant_id=91 if kind == "CYCLE_COUNT" else None, scope_batch_id=None,
            reference_number="REF")
        attempt = SimpleNamespace(id=77, attempt_number=1, submitted_at=NOW-timedelta(minutes=1),
            recount_of_attempt_id=None, requires_independent_recount=False)
        line = SimpleNamespace(id=88, company_id=COMPANY, stocktake_session_id=66,
            product_variant_id=91, batch_id=101, stock_status="AVAILABLE", expected_quantity=Decimal("5"))
        counted = SimpleNamespace(id=99, company_id=COMPANY, stocktake_session_id=66,
            stocktake_line_id=88, count_attempt_id=77, expected_quantity=Decimal("5"),
            actual_quantity=Decimal("6"), variance_quantity=Decimal("1"))
        movement = SimpleNamespace(id=555, performed_by=APPROVER, source_location_id=None,
            destination_location_id=LOCATION, source_stock_status=None, destination_stock_status="AVAILABLE",
            product_variant_id=91, batch_id=101, movement_kind="PHYSICAL", reservation_action=None,
            quantity=Decimal("1"), work_session_id=WORK if vehicle else None, transfer_header_id=None,
            stocktake_session_id=66, stocktake_count_attempt_id=77,
            reference_type="DRIVER_SURPLUS" if vehicle else "AUDIT_ADJUSTMENT",
            reference_id="REF", idempotency_key="AUDIT-66-77-99", financial_unit_price_snapshot=None)
        ns["apply_inventory_movements_batch"].return_value = [movement]
        db.expect(Driver, APPROVER)
        db.expect(StocktakeSession, (LOCATION, kind, WORK if vehicle else None))
        if vehicle:
            db.expect(WorkSession, WORK)
        db.expect(StocktakeSession, session)
        db.expect(InventoryLocation, ("VEHICLE" if vehicle else "WAREHOUSE", True, VEHICLE if vehicle else None))
        if vehicle and not replay:
            db.expect(WorkSession, work)
            db.expect(DispatchRoute, 33)
        db.expect(StocktakeCountAttempt, attempt)
        db.expect(StocktakeLine, rows=[(line, counted)])
        db.expect(InventoryLock, rows=[] if replay else [SimpleNamespace(
            product_variant_id=91 if kind == "CYCLE_COUNT" else None, batch_id=None)])
        if not replay:
            db.expect(InventoryLock)
        db.expect(InventoryMovement, rows=[movement] if replay else [])
        if replay and vehicle:
            db.expect(WorkSession, SimpleNamespace(inventory_reconciled_at=NOW, inventory_reconciled_by=APPROVER))
            db.expect(SessionInventorySnapshot)
        elif not replay:
            db.expect(InventoryBalance, rows=[SimpleNamespace(product_variant_id=91, batch_id=101,
                stock_status="AVAILABLE", on_hand_quantity=Decimal("5"))])
            db.expect(InventoryLock)
            if vehicle:
                db.expect(InventoryLocation, SimpleNamespace(vehicle_id=VEHICLE))
                db.expect(DispatchRoute, 33)
                db.expect(SessionInventorySnapshot, rows=[snap])
                db.expect(InventoryBalance, rows=[SimpleNamespace(product_variant_id=91, stock_status="AVAILABLE",
                    on_hand_quantity=Decimal("6"), reserved_quantity=0)])
        kwargs = dict(company_id=COMPANY, stocktake_session_id=66,
            stocktake_count_attempt_id=77, performed_by=APPROVER)
        return SimpleNamespace(db=db, ns=ns, work=work, snap=snap, session=session,
            movement=movement, counted=counted, kwargs=kwargs)

    async def test_ambiguity_introduced_after_creation_blocks_post_before_any_movement(self):
        opened = self.open_setup()
        _, created = await opened.ns["open_vehicle_reconciliation_stocktake"](opened.db, **opened.kwargs)
        self.assertTrue(created)
        opened.db.history.append((12, False))
        posting = self.post_setup(opened.db.history)
        with self.assertRaises(services.InventoryMutationError) as caught:
            await posting.ns["post_approved_stocktake_adjustments"](posting.db, **posting.kwargs)
        self.assertIn("VEHICLE_CUSTODY_LOCATION_AMBIGUOUS", str(caught.exception))
        self.assert_no_effects(posting.db, posting.ns)
        self.assertEqual(posting.session.status, "APPROVED")
        self.assertIsNone(posting.work.inventory_reconciled_at)
        self.assertNotIn("release", posting.db.events)

    async def test_post_missing_inactive_or_changed_custody_never_moves_stock(self):
        for history, code in self.invalid_cases():
            with self.subTest(code=code):
                setup = self.post_setup(history)
                with self.assertRaises(services.InventoryMutationError) as caught:
                    await setup.ns["post_approved_stocktake_adjustments"](setup.db, **setup.kwargs)
                self.assertIn(code, str(caught.exception))
                self.assert_no_effects(setup.db, setup.ns)
                self.assertIsNone(setup.snap.ending_quantity)
                self.assertIsNone(setup.session.posted_at)
                self.assertNotIn("release", setup.db.events)

    async def test_canonical_post_and_normal_warehouse_post_preserve_engine_and_provenance(self):
        for kind in ("VEHICLE_RECON", "FULL_COUNT", "CYCLE_COUNT"):
            with self.subTest(kind=kind):
                setup = self.post_setup(kind=kind)
                self.assertEqual(await setup.ns["post_approved_stocktake_adjustments"](setup.db, **setup.kwargs), [setup.movement])
                movement = setup.ns["apply_inventory_movements_batch"].await_args.kwargs
                self.assertEqual(movement["performed_by"], APPROVER)
                self.assertEqual(movement["movements"][0]["idempotency_key"], "AUDIT-66-77-99")
                self.assertEqual(setup.session.status, "POSTED")
                self.assertFalse(setup.db.script)
                self.assertEqual(setup.db.events.count("release"), 1)
                setup.db.commit.assert_not_awaited()
                if kind == "VEHICLE_RECON":
                    self.assertEqual((setup.work.inventory_reconciled_by, setup.snap.settled_by), (APPROVER, APPROVER))
                    self.assertFalse(setup.work.is_settled)
                    self.assertLess(setup.db.events.index("WorkSession.id"), setup.db.events.index("guard"))
                else:
                    self.assertNotIn("custody", setup.db.events)
                    self.assertIsNone(setup.work.inventory_reconciled_at)

    async def test_posted_replay_remains_historical_and_does_not_reapply_or_reseal(self):
        for kind in ("VEHICLE_RECON", "FULL_COUNT"):
            with self.subTest(kind=kind):
                setup = self.post_setup([], kind=kind, replay=True)
                setup.ns["_seal_vehicle_inventory_reconciliation"] = AsyncMock(side_effect=AssertionError("no reseal"))
                self.assertEqual(await setup.ns["post_approved_stocktake_adjustments"](setup.db, **setup.kwargs), [setup.movement])
                self.assert_no_effects(setup.db, setup.ns)
                setup.ns["_seal_vehicle_inventory_reconciliation"].assert_not_awaited()
                self.assertNotIn("custody", setup.db.events)

    async def test_failed_approval_rolls_back_and_does_not_commit_partial_state(self):
        setup = self.post_setup([(LOCATION, True), (12, False)])
        ns = dict(globals(), logger=Mock(), InventoryMutationError=services.InventoryMutationError)
        from sqlalchemy.exc import IntegrityError
        ns.update(IntegrityError=IntegrityError, _require_stocktake_capability=AsyncMock(),
            _probe_stocktake_location_id=AsyncMock(return_value=LOCATION),
            acquire_inventory_location_guard=setup.ns["acquire_inventory_location_guard"],
            _load_stocktake_session=AsyncMock(return_value=setup.session),
            _latest_stocktake_attempt=AsyncMock(return_value=SimpleNamespace(id=77, attempt_number=1)),
            _utc_naive_now=lambda: NOW, post_approved_stocktake_adjustments=setup.ns["post_approved_stocktake_adjustments"])
        import asyncio
        ns["asyncio"] = asyncio
        ns["bcrypt"] = SimpleNamespace(checkpw=Mock(return_value=True))
        setup.session.status = "PENDING_REVIEW"
        endpoint = load_functions(BACKEND / "api/warehouse/stocktake.py", {"approve_stocktake_session"}, ns)
        payload = SimpleNamespace(password="synthetic", count_attempt_id=77, notes=None)
        with self.assertRaises(HTTPException) as caught:
            await endpoint["approve_stocktake_session"](
                66, payload, setup.db, SimpleNamespace(company_id=COMPANY),
                SimpleNamespace(id=APPROVER, password_hash="synthetic"))
        self.assertEqual(caught.exception.status_code, 409)
        setup.db.rollback.assert_awaited_once()
        setup.db.commit.assert_not_awaited()
        setup.ns["apply_inventory_movements_batch"].assert_not_awaited()
        self.assertIsNone(setup.work.inventory_reconciled_at)
        self.assertNotIn("release", setup.db.events)

    def test_custody_validation_never_adds_vehicle_row_locks_or_duplicate_selection(self):
        for path, names in (
            (BACKEND / "services.py", SERVICE_FUNCTIONS),
            (BACKEND / "api/reconciliation.py", {"reconcile_driver_end_of_day"}),
            (BACKEND / "api/warehouse/stocktake.py", {"start_unified_stocktake"}),
        ):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in tree.body:
                if getattr(node, "name", None) not in names:
                    continue
                calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
                self.assertFalse(any(isinstance(call.func, ast.Name) and call.func.id == "select"
                    and any(isinstance(arg, ast.Name) and arg.id == "Vehicle" for arg in call.args)
                    for call in calls))
                if node.name == "_require_vehicle_reconciliation_custody":
                    self.assertIn("from domains.vehicles import", ast.get_source_segment(source, node))
                    self.assertEqual(ast.get_source_segment(source, node).count("resolve_vehicle_custody_location_id("), 1)


if __name__ == "__main__":
    unittest.main()
