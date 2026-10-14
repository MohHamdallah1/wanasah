"""Focused service contracts using exact production bodies and recorded I/O.

No packages/OS event loop are needed. Query doubles record predicates and locks;
they do not claim PostgreSQL, SQLAlchemy compilation or HTTP integration proof.
Inventory movements remain a mocked collaborator, not a second inventory engine.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from textwrap import dedent
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
SOURCE = BACKEND / "services.py"
VEHICLE_CONTRACTS = BACKEND / "domains/vehicles/contracts.py"
VEHICLE_REPOSITORY = BACKEND / "domains/vehicles/repository.py"
VEHICLE_CUSTODY = BACKEND / "domains/vehicles/custody.py"
NOW = datetime(2026, 10, 12, 12)
FIELD_DRIVER = 9003
APPROVER = 9004
TARGETS = {
    "open_vehicle_reconciliation_stocktake",
    "finalize_vehicle_inventory_reconciliation",
    "post_approved_stocktake_adjustments",
}



def finish(operation):
    """All mocked awaits complete immediately; fail if actual I/O is attempted."""
    try:
        operation.send(None)
    except StopIteration as result:
        return result.value
    finally:
        operation.close()
    raise AssertionError("Unexpected asynchronous I/O in focused contract")


class Column:
    def __init__(self, name):
        self.name = name

    def __getattr__(self, method):
        return lambda *args: Column(f"{self.name}.{method}")

    def __eq__(self, other):
        return Column(f"{self.name} == {other}")

    def __ne__(self, other):
        return Column(f"{self.name} != {other}")

    def __gt__(self, other):
        return Column(f"{self.name} > {other}")


class ModelType(type):
    def __getattr__(cls, field):
        if cls.__name__ == "Driver" and field == "is_admin":
            raise AssertionError("Driver flags cannot be projected or filtered")
        return Column(f"{cls.__name__}.{field}")


class Query:
    def __init__(self, *entities, operation="select"):
        self.entities = entities
        self.label = getattr(entities[0], "name", None) if isinstance(entities[0], Column) else entities[0].__name__
        self.operation = operation
        self.filters = {}
        self.lock = None
        self.calls = []
        self.changes = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def with_for_update(self, **kwargs):
        self.lock = kwargs
        return self

    def values(self, **kwargs):
        self.changes.update(kwargs)
        return self

    def __getattr__(self, method):
        def call(*args, **kwargs):
            self.calls.append((method, args, kwargs))
            return self
        return call


class Result:
    def __init__(self, value=None, rows=()):
        self.value = value
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.value

    def one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Database:
    def __init__(self, case, *, driver_id=FIELD_DRIVER, flag=False, company_id=7, active=True, custody_history=None):
        self.case = case
        self.actor_id = driver_id
        self.actor = SimpleNamespace(id=driver_id, company_id=company_id, is_active=active, is_admin=flag)
        self.custody_history = [(11, True)] if custody_history is None else list(custody_history)
        self.script = []
        self.queries = []
        self.events = []
        self.added = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.begin = AsyncMock()

    async def execute(self, query):
        self.queries.append(query)
        self.events.append(query.label)
        if query.label == "InventoryLocation.id":
            return Result(rows=[location_id for location_id, _ in self.custody_history])
        if query.label == "Driver.id":
            self.case.assertEqual([c.name for c in query.entities], ["Driver.id"])
            self.case.assertEqual(query.lock, {"read": True})
            self.case.assertEqual(query.filters, {"company_id": 7, "id": self.actor_id, "is_active": True})
            usable = self.actor is not None and all(getattr(self.actor, name) == value for name, value in query.filters.items())
            return Result(value=self.actor.id if usable else None)
        self.case.assertTrue(self.script, f"Unexpected query {query.label}")
        label, result = self.script.pop(0)
        self.case.assertEqual((query.operation, query.label), label)
        return result

    async def scalar(self, query):
        self.queries.append(query)
        self.events.append(query.label)
        if query.label != "InventoryLocation.is_active":
            raise AssertionError(f"Unexpected scalar query {query.label}")
        if len(self.custody_history) != 1:
            raise AssertionError("Active custody state must only be read after cardinality resolves to one row")
        return self.custody_history[0][1]

    def add(self, row):
        if "id" not in vars(row):
            row.id = 1000 + len(self.added)
        self.added.append(row)

    def expect(self, label, value=None, rows=(), *, operation="select"):
        self.script.append(((operation, label), Result(value, rows)))


def namespace(db):
    ns = dict(globals())
    for name in ("Driver", "InventoryLocation", "WorkSession", "DispatchRoute",
                 "StocktakeSession", "ProductVariant", "InventoryLock", "InventoryBalance",
                 "StocktakeLine", "SessionInventorySnapshot", "StocktakeCountAttempt",
                 "StocktakeCountAttemptLine", "InventoryMovement"):
        ns[name] = ModelType(name, (SimpleNamespace,), {})
    quantity_source = BACKEND / "quantity.py"
    exec(compile(quantity_source.read_text(encoding="utf-8"), str(quantity_source), "exec"), ns)
    ns.update(select=Query, update=lambda entity: Query(entity, operation="update"),
              and_=lambda *args: Column("and"), or_=lambda *args: Column("or"),
              tuple_=lambda *args: Column("tuple"), utc_now=lambda: NOW,
              _DB_INT_MAX=2147483647, _MAX_STOCKTAKE_POST_LINES=10000,
              _MONEY_12_3_MAX=Decimal("999999999.999"),
              _INVENTORY_STOCK_STATUSES={"AVAILABLE"})
    async def guard(*args, **kwargs):
        db.events.append("location-guard")
    ns["acquire_inventory_location_guard"] = AsyncMock(side_effect=guard)
    ns["apply_inventory_movements_batch"] = AsyncMock(return_value=[SimpleNamespace(id=555)])
    ns["resolve_work_session_pack_prices_bulk"] = AsyncMock()
    vehicle_ns = dict(ns)
    contract_tree = ast.parse(VEHICLE_CONTRACTS.read_text(encoding="utf-8"))
    vehicle_error = next(node for node in contract_tree.body
                         if isinstance(node, ast.ClassDef) and node.name == "VehicleError")
    repository_tree = ast.parse(VEHICLE_REPOSITORY.read_text(encoding="utf-8"))
    repository_names = {
        "_custody_ids", "_custody_cardinality_error", "_canonical_custody_id",
        "read_canonical_custody_location_id",
    }
    repository_nodes = [node for node in repository_tree.body
                        if getattr(node, "name", None) in repository_names]
    custody_tree = ast.parse(VEHICLE_CUSTODY.read_text(encoding="utf-8"))
    custody_node = next(node for node in custody_tree.body
                        if getattr(node, "name", None) == "resolve_vehicle_custody_location_id")
    future = ast.parse("from __future__ import annotations").body[0]
    exec(compile(ast.Module(body=[future, vehicle_error, *repository_nodes, custody_node], type_ignores=[]),
                 str(VEHICLE_CUSTODY), "exec", dont_inherit=True), vehicle_ns)
    vehicle_module = ModuleType("domains.vehicles")
    vehicle_module.VehicleError = vehicle_ns["VehicleError"]
    vehicle_module.resolve_vehicle_custody_location_id = vehicle_ns["resolve_vehicle_custody_location_id"]
    sys.modules["domains.vehicles"] = vehicle_module

    parsed = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = TARGETS | {"_require_vehicle_reconciliation_custody",
                       "_seal_vehicle_inventory_reconciliation", "validate_vehicle_recon_work_session",
                       "_strict_int", "_quantity_decimal", "InventoryMutationError"}
    nodes = [node for node in parsed.body if getattr(node, "name", None) in names]
    exec(compile(ast.Module(body=[future, *nodes], type_ignores=[]), str(SOURCE), "exec", dont_inherit=True), ns)
    return ns


def work_session(*, driver_id=FIELD_DRIVER):
    return SimpleNamespace(id=55, company_id=7, driver_id=driver_id, end_time=NOW,
                           is_settled=False, inventory_reconciled_at=None, inventory_reconciled_by=None)


def snapshot():
    return SimpleNamespace(id=201, location_id=11, product_variant_id=91, stock_status="AVAILABLE",
                           starting_quantity=Decimal(5), ending_quantity=None, settled_by=None, settled_at=None)


class VehicleReconciliationServiceContracts(unittest.TestCase):
    def no_transaction_mutation(self, db):
        db.commit.assert_not_awaited()
        db.rollback.assert_not_awaited()
        db.begin.assert_not_awaited()

    def open_case(self, *, flag=False, driver_id=FIELD_DRIVER, company_id=7, active=True, existing=None):
        db = Database(self, flag=flag, driver_id=driver_id, company_id=company_id, active=active)
        ns = namespace(db)
        db.expect("InventoryLocation", SimpleNamespace(vehicle_id=22))
        db.expect("WorkSession", work_session())
        db.expect("DispatchRoute.id", 33)
        db.expect("ProductVariant.id", rows=[91])
        db.expect("StocktakeSession", existing)
        if existing is None:
            db.expect("StocktakeSession.id")
            db.expect("InventoryLock.id")
            db.expect("InventoryBalance", rows=[SimpleNamespace(product_variant_id=91, batch_id=101,
                                                                 stock_status="AVAILABLE", on_hand_quantity=Decimal(5))])
        call = lambda: ns["open_vehicle_reconciliation_stocktake"](
            db, company_id=7, work_session_id=55, vehicle_location_id=11,
            started_by=driver_id, product_variant_ids=[91], notes=" variance ")
        return db, ns, call

    def final_case(self, *, flag=False, driver_id=FIELD_DRIVER, company_id=7, active=True):
        db = Database(self, flag=flag, driver_id=driver_id, company_id=company_id, active=active)
        ns = namespace(db)
        work, snap = work_session(), snapshot()
        db.expect("WorkSession", work)
        db.expect("InventoryLocation", SimpleNamespace(vehicle_id=22))
        db.expect("DispatchRoute.id", 33)
        db.expect("SessionInventorySnapshot", rows=[snap])
        db.expect("InventoryBalance", rows=[SimpleNamespace(product_variant_id=91, stock_status="AVAILABLE", on_hand_quantity=Decimal(6), reserved_quantity=0)])
        call = lambda: ns["finalize_vehicle_inventory_reconciliation"](
            db, company_id=7, work_session_id=55, vehicle_location_id=11, settled_by=driver_id)
        return db, ns, call, work, snap

    def post_case(self, *, flag=False, company_id=7, active=True, vehicle=False, replay=False):
        db = Database(self, flag=flag, driver_id=APPROVER, company_id=company_id, active=active)
        ns = namespace(db)
        kind, related = ("VEHICLE_RECON", 55) if vehicle else ("FULL_COUNT", None)
        session = SimpleNamespace(id=66, company_id=7, location_id=11, stocktake_type=kind,
            related_work_session_id=related, status="POSTED" if replay else "APPROVED",
            approved_by=APPROVER, approved_at=NOW, posted_at=NOW if replay else None,
            snapshot_cutoff_at=NOW-timedelta(minutes=3), scope_product_variant_id=None, scope_batch_id=None,
            reference_number="REF")
        attempt = SimpleNamespace(id=77, attempt_number=1, submitted_at=NOW-timedelta(minutes=1),
                                  recount_of_attempt_id=None, requires_independent_recount=False)
        line = SimpleNamespace(id=88, company_id=7, stocktake_session_id=66, product_variant_id=91,
                               batch_id=101, stock_status="AVAILABLE", expected_quantity=Decimal(5))
        counted = SimpleNamespace(id=99, company_id=7, stocktake_session_id=66, stocktake_line_id=88,
                                  count_attempt_id=77, expected_quantity=Decimal(5), actual_quantity=Decimal(6),
                                  variance_quantity=Decimal(1))
        work, snap = work_session(), snapshot()
        db.expect("StocktakeSession.location_id", (11, kind, related))
        if vehicle:
            db.expect("WorkSession.id", 55)
        db.expect("StocktakeSession", session)
        db.expect("InventoryLocation.location_type", ("VEHICLE" if vehicle else "WAREHOUSE", True, 22 if vehicle else None))
        if vehicle and not replay:
            db.expect("WorkSession", work)
            db.expect("DispatchRoute.id", 33)
        db.expect("StocktakeCountAttempt", attempt)
        db.expect("StocktakeLine", rows=[(line, counted)])
        db.expect("InventoryLock", rows=[] if replay else [SimpleNamespace(product_variant_id=None, batch_id=None)])
        if not replay:
            db.expect("InventoryLock.id")
        movement = SimpleNamespace(performed_by=APPROVER, source_location_id=None, destination_location_id=11,
            source_stock_status=None, destination_stock_status="AVAILABLE", product_variant_id=91, batch_id=101,
            movement_kind="PHYSICAL", reservation_action=None, quantity=Decimal(1), work_session_id=related,
            transfer_header_id=None, stocktake_session_id=66, stocktake_count_attempt_id=77,
            reference_type="DRIVER_SURPLUS" if vehicle else "AUDIT_ADJUSTMENT", reference_id="REF",
            idempotency_key="AUDIT-66-77-99", financial_unit_price_snapshot=None)
        db.expect("InventoryMovement", rows=[movement] if replay else [])
        if replay and vehicle:
            db.expect("WorkSession.inventory_reconciled_at", SimpleNamespace(inventory_reconciled_at=NOW, inventory_reconciled_by=APPROVER))
            db.expect("SessionInventorySnapshot.id")
        elif not replay:
            db.expect("InventoryBalance", rows=[SimpleNamespace(product_variant_id=91, batch_id=101,
                                                               stock_status="AVAILABLE", on_hand_quantity=Decimal(5))])
            db.expect("InventoryLock.id")
            db.expect("InventoryLock", operation="update")
            if vehicle:
                db.expect("InventoryLocation", SimpleNamespace(vehicle_id=22))
                db.expect("DispatchRoute.id", 33)
                db.expect("SessionInventorySnapshot", rows=[snap])
                db.expect("InventoryBalance", rows=[SimpleNamespace(product_variant_id=91, stock_status="AVAILABLE", on_hand_quantity=Decimal(6), reserved_quantity=0)])
        call = lambda: ns["post_approved_stocktake_adjustments"](
            db, company_id=7, stocktake_session_id=66, stocktake_count_attempt_id=77, performed_by=APPROVER)
        return db, ns, call, session, work, snap, movement

    def test_own_driver_opens_snapshot_for_both_flags(self):
        for flag in (False, True):
            with self.subTest(flag=flag):
                db, ns, call = self.open_case(flag=flag)
                session, created = finish(call())
                self.assertTrue(created)
                self.assertEqual((session.status, session.started_by, session.snapshot_cutoff_at), ("COUNTING", FIELD_DRIVER, NOW))
                self.assertEqual(db.added[1].created_by, FIELD_DRIVER)
                self.assertEqual(db.added[2].expected_quantity, Decimal(5))
                self.assertEqual(db.queries[2].lock, {})  # WorkSession before location guard
                self.assertLess(db.events.index("WorkSession"), db.events.index("location-guard"))
                self.assertFalse(db.script)
                self.no_transaction_mutation(db)

    def test_open_existing_stocktake_replays_without_new_snapshot(self):
        existing = SimpleNamespace(id=66, status="COUNTING")
        db, ns, call = self.open_case(existing=existing)
        self.assertEqual(finish(call()), (existing, False))
        self.assertFalse(db.added)
        db.flush.assert_not_awaited()
        self.no_transaction_mutation(db)

    def test_other_driver_cannot_open_or_finalize_even_with_true_flag(self):
        for flag in (False, True):
            for factory in (self.open_case, self.final_case):
                with self.subTest(flag=flag, service=factory.__name__):
                    db, ns, call, *rest = factory(flag=flag, driver_id=9005)
                    with self.assertRaises(ns["InventoryMutationError"]):
                        finish(call())
                    ns["acquire_inventory_location_guard"].assert_not_awaited()
                    self.assertFalse(db.added)
                    db.flush.assert_not_awaited()
                    self.no_transaction_mutation(db)

    def test_own_driver_finalizes_snapshots_for_both_flags(self):
        for flag in (False, True):
            with self.subTest(flag=flag):
                db, ns, call, work, snap = self.final_case(flag=flag)
                self.assertIs(finish(call()), work)
                self.assertEqual((snap.ending_quantity, snap.settled_by, snap.settled_at), (Decimal(6), FIELD_DRIVER, NOW))
                self.assertEqual((work.inventory_reconciled_by, work.inventory_reconciled_at), (FIELD_DRIVER, NOW))
                self.assertFalse(work.is_settled)
                self.assertEqual(db.queries[1].lock, {})
                self.assertLess(db.events.index("WorkSession"), db.events.index("location-guard"))
                self.assertFalse(db.script)
                db.flush.assert_awaited_once()
                self.no_transaction_mutation(db)

    def test_finalization_replays_complete_seal_without_rewriting(self):
        db, ns, call, work, snap = self.final_case()
        work.inventory_reconciled_at, work.inventory_reconciled_by = NOW, FIELD_DRIVER
        snap.ending_quantity, snap.settled_at, snap.settled_by = Decimal(6), NOW, FIELD_DRIVER
        self.assertIs(finish(call()), work)
        db.flush.assert_not_awaited()
        self.assertNotIn("InventoryBalance", db.events)
        self.no_transaction_mutation(db)

    def test_operational_actor_active_and_company_checks_for_all_three_services(self):
        for factory in (self.open_case, self.final_case, self.post_case):
            for flag in (False, True):
                for invalid in ({"active": False}, {"company_id": 8}, {"missing": True}):
                    with self.subTest(service=factory.__name__, flag=flag, invalid=invalid):
                        db, ns, call, *rest = factory(flag=flag, **{k: v for k, v in invalid.items() if k != "missing"})
                        if invalid.get("missing"):
                            db.actor = None
                        with self.assertRaises(ns["InventoryMutationError"]):
                            finish(call())
                        self.assertEqual(len(db.queries), 1)
                        ns["apply_inventory_movements_batch"].assert_not_awaited()
                        db.flush.assert_not_awaited()
                        self.no_transaction_mutation(db)

    def test_approved_posting_accepts_ordinary_operational_actor_and_keeps_provenance(self):
        for flag in (False, True):
            for vehicle in (False, True):
                with self.subTest(flag=flag, vehicle=vehicle):
                    db, ns, call, session, work, snap, movement = self.post_case(flag=flag, vehicle=vehicle)
                    result = finish(call())
                    self.assertEqual(result[0].id, 555)
                    self.assertEqual((session.status, session.posted_at), ("POSTED", NOW))
                    applied = ns["apply_inventory_movements_batch"].call_args.kwargs
                    self.assertEqual(applied["performed_by"], APPROVER)
                    self.assertEqual(applied["movements"][0]["idempotency_key"], "AUDIT-66-77-99")
                    release = next(query for query in db.queries if query.operation == "update")
                    self.assertEqual(release.changes["released_by"], APPROVER)
                    if vehicle:
                        self.assertNotEqual(APPROVER, work.driver_id)
                        self.assertEqual((work.inventory_reconciled_by, snap.settled_by), (APPROVER, APPROVER))
                        self.assertFalse(work.is_settled)
                        self.assertLess(db.events.index("WorkSession.id"), db.events.index("location-guard"))
                        self.assertLess(db.events.index("WorkSession"), db.events.index("InventoryLock"))
                    self.assertFalse(db.script)
                    self.no_transaction_mutation(db)

    def test_posted_replay_does_not_reapply_movements_or_reseal_vehicle(self):
        for vehicle in (False, True):
            db, ns, call, session, work, snap, movement = self.post_case(vehicle=vehicle, replay=True)
            ns["_seal_vehicle_inventory_reconciliation"] = AsyncMock(side_effect=AssertionError("No reseal"))
            self.assertEqual(finish(call()), [movement])
            ns["apply_inventory_movements_batch"].assert_not_awaited()
            ns["_seal_vehicle_inventory_reconciliation"].assert_not_awaited()
            self.assertFalse(db.script)
            self.no_transaction_mutation(db)

    def test_work_session_and_stocktake_state_attempt_guards_remain(self):
        db, ns, call, work, snap = self.final_case()
        work.end_time = None
        with self.assertRaises(ns["InventoryMutationError"]):
            finish(call())
        ns["acquire_inventory_location_guard"].assert_not_awaited()
        for invalid in ("status", "attempt"):
            db, ns, call, session, *rest = self.post_case()
            if invalid == "status":
                session.status = "DRAFT"
            else:
                next(result for (op, label), result in db.script if label == "StocktakeCountAttempt").value.id = 78
            with self.assertRaises(ns["InventoryMutationError"]):
                finish(call())
            ns["apply_inventory_movements_batch"].assert_not_awaited()
            self.assertIsNone(session.posted_at)
            self.no_transaction_mutation(db)

    def _assert_preserved_service_contract(
        self, function, *, parameters, statements, decisions, rejections, returns,
    ):
        # Both expected snippets and production are parsed/rendered by this
        # interpreter. No serialized AST fields or Python-version fingerprints.
        def normalized(code, *, expression=False):
            parsed = ast.parse(dedent(code).strip(), mode="eval" if expression else "exec",
                               feature_version=(3, 11))
            if expression:
                return ast.unparse(parsed.body)
            self.assertEqual(len(parsed.body), 1)
            return ast.unparse(parsed.body[0])

        self.assertEqual([arg.arg for arg in function.args.args], ["db_session"])
        self.assertEqual([arg.arg for arg in function.args.kwonlyargs], parameters)
        self.assertEqual(function.args.defaults, [])
        for argument, default in zip(function.args.kwonlyargs, function.args.kw_defaults):
            if argument.arg == "notes":
                self.assertIsInstance(default, ast.Constant)
                self.assertIsNone(default.value)
            else:
                self.assertIsNone(default, (function.name, argument.arg))
        self.assertIsNone(function.args.vararg)
        self.assertIsNone(function.args.kwarg)
        nodes = list(ast.walk(function))
        by_statement = {}
        for node in nodes:
            if isinstance(node, ast.stmt):
                by_statement.setdefault(ast.unparse(node), []).append(node)
        positions = []
        for code in statements:
            expected = normalized(code)
            matching = by_statement.get(expected, [])
            self.assertEqual(len(matching), 1, (function.name, expected))
            positions.append(matching[0].lineno)
        # Preserve query/guard/effect ordering, including WorkSession locks
        # before the location guard and sealing after approved posting.
        self.assertEqual(positions, sorted(positions), function.name)

        actual_decisions = [
            (type(node).__name__, ast.unparse(node.test))
            for node in nodes if isinstance(node, (ast.If, ast.IfExp))
        ]
        self.assertEqual(actual_decisions, [
            (kind, normalized(test, expression=True)) for kind, test in decisions
        ], function.name)
        actual_rejections = [
            (ast.unparse(node.test), ast.unparse(node.body[0]))
            for node in nodes if isinstance(node, ast.If)
            and node.body and isinstance(node.body[0], ast.Raise)
        ]
        self.assertEqual(actual_rejections, [
            (normalized(test, expression=True), normalized(rejection))
            for test, rejection in rejections
        ], function.name)
        actual_returns = sorted(
            (node for node in nodes if isinstance(node, ast.Return)),
            key=lambda node: node.lineno,
        )
        self.assertEqual([ast.unparse(node.value) for node in actual_returns],
                         [normalized(value, expression=True) for value in returns],
                         function.name)
        self.assertFalse(any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"begin", "commit", "rollback"}
            for node in nodes
        ), function.name)
        forbidden = {"is_owner", "is_supervisor", "is_manager", "is_superuser",
                     "allow_admin", "allow_override", "is_company_owner"}
        identifiers = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in nodes if isinstance(node, (ast.Name, ast.Attribute))
        }
        self.assertTrue(forbidden.isdisjoint(identifiers), function.name)

    def test_source_audit_and_business_body_parity(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("is_admin", source)
        parsed = ast.parse(source, feature_version=(3, 11))
        functions = {node.name: node for node in parsed.body
                     if isinstance(node, ast.AsyncFunctionDef)}
        # Shared company/session/vehicle validation; ended, unsettled and unreconciled state.
        self._assert_preserved_service_contract(
            functions['validate_vehicle_recon_work_session'],
            parameters=['company_id', 'work_session_id', 'vehicle_id'],
            statements=(
                'work_session = (await db_session.execute(select(WorkSession).execution_options(populate_existing=True).filter_by(company_id=company_id, id=work_session_id).with_for_update())).scalar_one_or_none()',
                'route_id = (await db_session.execute(select(DispatchRoute.id).filter(DispatchRoute.company_id == company_id, DispatchRoute.work_session_id == work_session.id, DispatchRoute.driver_id == work_session.driver_id, DispatchRoute.vehicle_id == vehicle_id).order_by(DispatchRoute.id.desc()).limit(1))).scalar_one_or_none()',
            ),
            decisions=(
                ('If', 'work_session is None'),
                ('If', 'work_session.end_time is None'),
                ('If', 'work_session.is_settled'),
                ('If', 'work_session.inventory_reconciled_at is not None'),
                ('If', 'route_id is None'),
            ),
            rejections=(
                ('work_session is None', "raise InventoryMutationError('جلسة العمل غير موجودة أو لا تتبع الشركة.')"),
                ('work_session.end_time is None', "raise InventoryMutationError('لا يمكن بدء أو ترحيل VEHICLE_RECON قبل إنهاء جلسة العمل.')"),
                ('work_session.is_settled', "raise InventoryMutationError('جلسة العمل تمت تسويتها مالياً مسبقاً ولا تقبل VEHICLE_RECON جديداً.')"),
                ('work_session.inventory_reconciled_at is not None', "raise InventoryMutationError('عهدة مخزون جلسة العمل تمت مطابقتها مسبقاً ولا تقبل VEHICLE_RECON جديداً.')"),
                ('route_id is None', "raise InventoryMutationError('جلسة العمل المحددة لا ترتبط بهذه السيارة داخل الشركة.')"),
            ),
            returns=['work_session'],
        )
        # Operational actor, exact self ownership, open-session reuse, locks and snapshot creation.
        self._assert_preserved_service_contract(
            functions['open_vehicle_reconciliation_stocktake'],
            parameters=['company_id', 'work_session_id', 'vehicle_location_id', 'started_by', 'product_variant_ids', 'notes'],
            statements=(
                'actor = (await db_session.execute(select(Driver.id).filter_by(company_id=company_id, id=started_by, is_active=True).with_for_update(read=True))).one_or_none()',
                "location = (await db_session.execute(select(InventoryLocation).filter_by(company_id=company_id, id=vehicle_location_id, location_type='VEHICLE').with_for_update(read=True))).scalar_one_or_none()",
                'work_session = await validate_vehicle_recon_work_session(db_session, company_id=company_id, work_session_id=work_session_id, vehicle_id=int(location.vehicle_id))',
                'valid_variant_ids = set((await db_session.execute(select(ProductVariant.id).filter(ProductVariant.company_id == company_id, ProductVariant.id.in_(normalized_variant_ids)))).scalars().all())',
                'await acquire_inventory_location_guard(db_session, company_id, vehicle_location_id, exclusive=True)',
                'await _require_vehicle_reconciliation_custody(db_session, company_id=company_id, vehicle_id=int(location.vehicle_id), vehicle_location_id=vehicle_location_id)',
                "existing = (await db_session.execute(select(StocktakeSession).filter(StocktakeSession.company_id == company_id, StocktakeSession.stocktake_type == 'VEHICLE_RECON', StocktakeSession.related_work_session_id == work_session_id, StocktakeSession.status != 'CANCELLED').order_by(StocktakeSession.id.desc()).limit(1).with_for_update())).scalar_one_or_none()",
                """\
                if existing is not None:
                    return (existing, False)
                """,
                "conflicting_session_id = (await db_session.execute(select(StocktakeSession.id).filter(StocktakeSession.company_id == company_id, StocktakeSession.location_id == vehicle_location_id, StocktakeSession.status.in_(['DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED'])).order_by(StocktakeSession.id.asc()).limit(1).with_for_update())).scalar_one_or_none()",
                'conflicting_lock_id = (await db_session.execute(select(InventoryLock.id).filter(InventoryLock.company_id == company_id, InventoryLock.location_id == vehicle_location_id, InventoryLock.released_at.is_(None)).order_by(InventoryLock.id.asc()).limit(1).with_for_update())).scalar_one_or_none()',
                "reference_number = f'VREC-{uuid4().hex[:12].upper()}'",
                "session = StocktakeSession(company_id=company_id, location_id=vehicle_location_id, reference_number=reference_number, stocktake_type='VEHICLE_RECON', status='DRAFT', related_work_session_id=work_session_id, started_by=started_by, notes=notes)",
                'db_session.add(session)',
                'db_session.add(InventoryLock(company_id=company_id, stocktake_session_id=session.id, location_id=vehicle_location_id, product_variant_id=None, batch_id=None, created_by=started_by))',
                'balances = (await db_session.execute(select(InventoryBalance).filter(InventoryBalance.company_id == company_id, InventoryBalance.location_id == vehicle_location_id, InventoryBalance.product_variant_id.in_(normalized_variant_ids), InventoryBalance.on_hand_quantity > 0).order_by(InventoryBalance.product_variant_id.asc(), InventoryBalance.batch_id.asc(), InventoryBalance.stock_status.asc(), InventoryBalance.id.asc()).limit(_MAX_STOCKTAKE_POST_LINES + 1).with_for_update())).scalars().all()',
                """\
                for balance in balances:
                    db_session.add(StocktakeLine(company_id=company_id, stocktake_session_id=session.id, product_variant_id=balance.product_variant_id, batch_id=balance.batch_id, stock_status=balance.stock_status, line_origin='SNAPSHOT', expected_quantity=_quantity_decimal(balance.on_hand_quantity)))
                """,
                'cutoff = utc_now()',
                'session.snapshot_cutoff_at = cutoff',
                "session.status = 'COUNTING'",
                'session.updated_at = cutoff',
            ),
            decisions=(
                ('If', 'not normalized_variant_ids'),
                ('If', 'len(normalized_variant_ids) > 5000'),
                ('If', 'notes is not None'),
                ('If', 'actor is None'),
                ('If', 'location is None or location.vehicle_id is None'),
                ('If', 'started_by != work_session.driver_id'),
                ('If', 'valid_variant_ids != set(normalized_variant_ids)'),
                ('If', 'existing is not None'),
                ('If', 'conflicting_session_id is not None'),
                ('If', 'conflicting_lock_id is not None'),
                ('If', 'len(balances) > _MAX_STOCKTAKE_POST_LINES'),
                ('If', 'not isinstance(notes, str)'),
                ('If', "notes is not None and ('\\x00' in notes or len(notes) > 4000)"),
            ),
            rejections=(
                ('not normalized_variant_ids', "raise InventoryMutationError('VEHICLE_RECON الموجّه يتطلب صنفاً واحداً على الأقل.')"),
                ('len(normalized_variant_ids) > 5000', "raise InventoryMutationError('عدد أصناف VEHICLE_RECON يتجاوز الحد الآمن.')"),
                ('actor is None', "raise InventoryMutationError('منشئ التسوية غير موجود/غير فعال أو خارج الشركة.')"),
                ('location is None or location.vehicle_id is None', "raise InventoryMutationError('موقع السيارة غير موجود أو غير فعال أو لا يحمل vehicle_id صالحاً.')"),
                ('started_by != work_session.driver_id', "raise InventoryMutationError('لا يجوز لمندوب آخر فتح تسوية عهدة هذه الجلسة.')"),
                ('valid_variant_ids != set(normalized_variant_ids)', "raise InventoryMutationError('أحد أصناف فرق العهدة غير موجود أو لا يتبع الشركة.')"),
                ('conflicting_session_id is not None', "raise InventoryMutationError('يوجد جرد نشط على السيارة؛ لا يمكن فتح تسوية موازية.')"),
                ('conflicting_lock_id is not None', "raise InventoryMutationError('يوجد قفل جرد فعال على السيارة؛ لا يمكن فتح تسوية جديدة.')"),
                ('len(balances) > _MAX_STOCKTAKE_POST_LINES', "raise InventoryMutationError('VEHICLE_RECON يتجاوز الحد الآمن لأسطر الجرد.')"),
                ('not isinstance(notes, str)', "raise InventoryMutationError('notes يجب أن تكون نصاً أو None.')"),
                ("notes is not None and ('\\x00' in notes or len(notes) > 4000)", "raise InventoryMutationError('notes غير صالحة أو تتجاوز 4000 حرف.')"),
            ),
            returns=['(existing, False)', '(session, True)'],
        )
        # Field-only ownership precedes private sealing; no privileged alternative.
        self._assert_preserved_service_contract(
            functions['finalize_vehicle_inventory_reconciliation'],
            parameters=['company_id', 'work_session_id', 'vehicle_location_id', 'settled_by'],
            statements=(
                'actor = (await db_session.execute(select(Driver.id).filter_by(company_id=company_id, id=settled_by, is_active=True).with_for_update(read=True))).one_or_none()',
                'work_session = (await db_session.execute(select(WorkSession).execution_options(populate_existing=True).filter_by(company_id=company_id, id=work_session_id).with_for_update())).scalar_one_or_none()',
                'return await _seal_vehicle_inventory_reconciliation(db_session, company_id=company_id, work_session=work_session, vehicle_location_id=vehicle_location_id, settled_by=settled_by)',
            ),
            decisions=(
                ('If', 'actor is None'),
                ('If', 'work_session is None'),
                ('If', 'work_session.end_time is None'),
                ('If', 'settled_by != work_session.driver_id'),
            ),
            rejections=(
                ('actor is None', "raise InventoryMutationError('منفذ التسوية غير موجود/غير فعال أو خارج الشركة.')"),
                ('work_session is None', "raise InventoryMutationError('جلسة العمل غير موجودة أو لا تتبع الشركة.')"),
                ('work_session.end_time is None', "raise InventoryMutationError('لا يمكن تسوية عهدة جلسة عمل لم تنتهِ بعد.')"),
                ('settled_by != work_session.driver_id', "raise InventoryMutationError('تثبيت عهدة الجلسة مسموح لصاحب الجلسة فقط.')"),
            ),
            returns=['await _seal_vehicle_inventory_reconciliation(db_session, company_id=company_id, work_session=work_session, vehicle_location_id=vehicle_location_id, settled_by=settled_by)'],
        )
        # Vehicle/route/tenant validation, ending balances and Driver provenance; no financial settlement.
        self._assert_preserved_service_contract(
            functions['_seal_vehicle_inventory_reconciliation'],
            parameters=['company_id', 'work_session', 'vehicle_location_id', 'settled_by'],
            statements=(
                'await acquire_inventory_location_guard(db_session, company_id, vehicle_location_id, exclusive=True)',
                "location = (await db_session.execute(select(InventoryLocation).filter_by(company_id=company_id, id=vehicle_location_id, location_type='VEHICLE').with_for_update(read=True))).scalar_one_or_none()",
                'await _require_vehicle_reconciliation_custody(db_session, company_id=company_id, vehicle_id=int(location.vehicle_id), vehicle_location_id=vehicle_location_id)',
                'route_id = (await db_session.execute(select(DispatchRoute.id).filter(DispatchRoute.company_id == company_id, DispatchRoute.work_session_id == work_session.id, DispatchRoute.driver_id == work_session.driver_id, DispatchRoute.vehicle_id == location.vehicle_id).order_by(DispatchRoute.id.desc()).limit(1))).scalar_one_or_none()',
                'snapshots = (await db_session.execute(select(SessionInventorySnapshot).execution_options(populate_existing=True).filter_by(company_id=company_id, work_session_id=work_session.id).order_by(SessionInventorySnapshot.product_variant_id.asc(), SessionInventorySnapshot.stock_status.asc(), SessionInventorySnapshot.id.asc()).with_for_update())).scalars().all()',
                'final_rows = (await db_session.execute(select(InventoryBalance).filter(InventoryBalance.company_id == company_id, InventoryBalance.location_id == vehicle_location_id, or_(InventoryBalance.on_hand_quantity > 0, InventoryBalance.reserved_quantity > 0)).order_by(InventoryBalance.product_variant_id.asc(), InventoryBalance.batch_id.asc(), InventoryBalance.stock_status.asc(), InventoryBalance.id.asc()).limit(_MAX_STOCKTAKE_POST_LINES + 1).with_for_update())).scalars().all()',
                """\
                for balance in final_rows:
                    key = (int(balance.product_variant_id), str(balance.stock_status))
                    next_value = final_map.get(key, Decimal('0')) + _quantity_decimal(balance.on_hand_quantity or 0)
                    if next_value < 0 or next_value > QUANTITY_MAX:
                        raise InventoryMutationError('إجمالي عهدة نهاية الجلسة يتجاوز سعة NUMERIC(20,6).')
                    final_map[key] = next_value
                """,
                """\
                for row in snapshots:
                    key = (int(row.product_variant_id), str(row.stock_status))
                    if key in snapshot_map:
                        raise InventoryMutationError('لقطة الجلسة تحتوي صنف/حالة مكررة.')
                    snapshot_map[key] = row
                """,
                'settled_at = utc_now()',
                """\
                for key in sorted(set(snapshot_map) | set(final_map)):
                    ending_quantity = final_map.get(key, Decimal('0'))
                    row = snapshot_map.get(key)
                    if row is None:
                        product_variant_id, stock_status = key
                        row = SessionInventorySnapshot(company_id=company_id, work_session_id=work_session.id, location_id=vehicle_location_id, product_variant_id=product_variant_id, stock_status=stock_status, starting_quantity=Decimal('0'))
                        db_session.add(row)
                    row.ending_quantity = ending_quantity
                    row.settled_by = settled_by
                    row.settled_at = settled_at
                """,
                'work_session.inventory_reconciled_at = settled_at',
                'work_session.inventory_reconciled_by = settled_by',
            ),
            decisions=(
                ('If', 'location is None or location.vehicle_id is None'),
                ('If', 'route_id is None'),
                ('If', 'any((int(row.location_id) != vehicle_location_id for row in snapshots))'),
                ('If', 'work_session.is_settled and work_session.inventory_reconciled_at is None'),
                ('If', 'work_session.inventory_reconciled_at is not None'),
                ('If', 'work_session.inventory_reconciled_by is not None'),
                ('If', 'any((row.ending_quantity is not None or row.settled_by is not None or row.settled_at is not None for row in snapshots))'),
                ('If', 'len(final_rows) > _MAX_STOCKTAKE_POST_LINES'),
                ('If', 'any((_quantity_decimal(row.reserved_quantity or 0) != 0 for row in final_rows))'),
                ('If', 'work_session.inventory_reconciled_by is None'),
                ('If', 'any((row.ending_quantity is None or row.settled_by is None or row.settled_at is None for row in snapshots))'),
                ('If', 'next_value < 0 or next_value > QUANTITY_MAX'),
                ('If', 'key in snapshot_map'),
                ('If', 'row is None'),
            ),
            rejections=(
                ('location is None or location.vehicle_id is None', "raise InventoryMutationError('موقع السيارة غير موجود أو غير فعال أو لا يحمل vehicle_id صالحاً.')"),
                ('route_id is None', "raise InventoryMutationError('جلسة العمل لا ترتبط بموقع السيارة المحدد داخل الشركة.')"),
                ('any((int(row.location_id) != vehicle_location_id for row in snapshots))', "raise InventoryMutationError('لقطة جلسة المندوب مرتبطة بموقع سيارة مختلف؛ تم رفض التسوية.')"),
                ('work_session.is_settled and work_session.inventory_reconciled_at is None', "raise InventoryMutationError('جلسة مسواة مالياً بدون ختم تسوية مخزنية؛ البيانات غير متسقة.')"),
                ('work_session.inventory_reconciled_by is not None', "raise InventoryMutationError('تم اكتشاف ختم تسوية مخزنية جزئي على WorkSession.')"),
                ('any((row.ending_quantity is not None or row.settled_by is not None or row.settled_at is not None for row in snapshots))', "raise InventoryMutationError('تم اكتشاف تسوية مخزنية جزئية في SessionInventorySnapshot.')"),
                ('len(final_rows) > _MAX_STOCKTAKE_POST_LINES', "raise InventoryMutationError('رصيد السيارة يتجاوز الحد الآمن لتثبيت Ending Snapshot.')"),
                ('any((_quantity_decimal(row.reserved_quantity or 0) != 0 for row in final_rows))', "raise InventoryMutationError('لا يمكن ختم عهدة السيارة بوجود مخزون محجوز؛ يجب تحرير جميع الحجوزات أولاً.')"),
                ('work_session.inventory_reconciled_by is None', "raise InventoryMutationError('ختم التسوية المخزنية ناقص هوية المنفذ.')"),
                ('any((row.ending_quantity is None or row.settled_by is None or row.settled_at is None for row in snapshots))', "raise InventoryMutationError('جلسة مخزون معلّمة كمطابقة لكن Ending Snapshot ناقص.')"),
                ('next_value < 0 or next_value > QUANTITY_MAX', "raise InventoryMutationError('إجمالي عهدة نهاية الجلسة يتجاوز سعة NUMERIC(20,6).')"),
                ('key in snapshot_map', "raise InventoryMutationError('لقطة الجلسة تحتوي صنف/حالة مكررة.')"),
            ),
            returns=['work_session', 'work_session'],
        )
        # Approved/replay states, count/line integrity, scoped locks, movements/idempotency and approver sealing.
        self._assert_preserved_service_contract(
            functions['post_approved_stocktake_adjustments'],
            parameters=['company_id', 'stocktake_session_id', 'stocktake_count_attempt_id', 'performed_by'],
            statements=(
                'actor_id = (await db_session.execute(select(Driver.id).filter_by(company_id=company_id, id=performed_by, is_active=True).with_for_update(read=True))).scalar_one_or_none()',
                'probe = (await db_session.execute(select(StocktakeSession.location_id, StocktakeSession.stocktake_type, StocktakeSession.related_work_session_id).filter_by(company_id=company_id, id=stocktake_session_id))).one_or_none()',
                'locked_probe_session = (await db_session.execute(select(WorkSession.id).filter_by(company_id=company_id, id=probe_work_session_id).with_for_update())).scalar_one_or_none()',
                'await acquire_inventory_location_guard(db_session, company_id, int(probe_location_id), exclusive=True)',
                'session = (await db_session.execute(select(StocktakeSession).execution_options(populate_existing=True).filter_by(company_id=company_id, id=stocktake_session_id).with_for_update())).scalar_one_or_none()',
                'location_row = (await db_session.execute(select(InventoryLocation.location_type, InventoryLocation.is_active, InventoryLocation.vehicle_id).filter_by(company_id=company_id, id=session.location_id).with_for_update(read=True))).one_or_none()',
                "expected_location_type = 'VEHICLE' if session.stocktake_type == 'VEHICLE_RECON' else 'WAREHOUSE'",
                'await _require_vehicle_reconciliation_custody(db_session, company_id=company_id, vehicle_id=int(location_vehicle_id), vehicle_location_id=int(session.location_id))',
                'vehicle_work_session = await validate_vehicle_recon_work_session(db_session, company_id=company_id, work_session_id=session.related_work_session_id, vehicle_id=location_vehicle_id)',
                'latest_attempt = (await db_session.execute(select(StocktakeCountAttempt).execution_options(populate_existing=True).filter_by(company_id=company_id, stocktake_session_id=session.id).order_by(StocktakeCountAttempt.attempt_number.desc(), StocktakeCountAttempt.id.desc()).limit(1))).scalar_one_or_none()',
                'parent_attempt = None',
                'parent_attempt = (await db_session.execute(select(StocktakeCountAttempt).execution_options(populate_existing=True).filter_by(company_id=company_id, stocktake_session_id=session.id, id=latest_attempt.recount_of_attempt_id))).scalar_one_or_none()',
                'stmt_lines = select(StocktakeLine, StocktakeCountAttemptLine).execution_options(populate_existing=True).outerjoin(StocktakeCountAttemptLine, and_(StocktakeCountAttemptLine.company_id == StocktakeLine.company_id, StocktakeCountAttemptLine.stocktake_session_id == StocktakeLine.stocktake_session_id, StocktakeCountAttemptLine.stocktake_line_id == StocktakeLine.id, StocktakeCountAttemptLine.count_attempt_id == latest_attempt.id)).filter(StocktakeLine.company_id == company_id, StocktakeLine.stocktake_session_id == session.id).order_by(StocktakeLine.product_variant_id.asc(), StocktakeLine.batch_id.asc(), StocktakeLine.stock_status.asc(), StocktakeLine.id.asc()).limit(_MAX_STOCKTAKE_POST_LINES + 1)',
                'line_rows = (await db_session.execute(stmt_lines)).all()',
                'own_locks = (await db_session.execute(select(InventoryLock).execution_options(populate_existing=True).filter(InventoryLock.company_id == company_id, InventoryLock.stocktake_session_id == session.id, InventoryLock.location_id == session.location_id, InventoryLock.released_at.is_(None)).order_by(InventoryLock.id.asc()).with_for_update())).scalars().all()',
                'stmt_conflict = select(InventoryLock.id).filter(InventoryLock.company_id == company_id, InventoryLock.location_id == session.location_id, InventoryLock.stocktake_session_id != session.id, InventoryLock.released_at.is_(None))',
                'stmt_conflict = stmt_conflict.filter(conflict_scope)',
                'conflicting_lock_id = (await db_session.execute(stmt_conflict.order_by(InventoryLock.id.asc()).limit(1).with_for_update())).scalar_one_or_none()',
                "specs.append({'attempt_line': attempt_line, 'product_variant_id': stocktake_line.product_variant_id, 'batch_id': stocktake_line.batch_id, 'stock_status': stock_status, 'variance': variance, 'quantity': abs(variance), 'source_location_id': source_location_id, 'destination_location_id': destination_location_id, 'source_stock_status': source_stock_status, 'destination_stock_status': destination_stock_status, 'reference_type': reference_type, 'reference_id': session.reference_number, 'idempotency_key': f'AUDIT-{session.id}-{latest_attempt.id}-{attempt_line.id}', 'work_session_id': session.related_work_session_id if session.stocktake_type == 'VEHICLE_RECON' else None})",
                "expected_idempotency_keys = {spec['idempotency_key'] for spec in specs}",
                'existing_movements = (await db_session.execute(select(InventoryMovement).execution_options(populate_existing=True).filter(InventoryMovement.company_id == company_id, InventoryMovement.stocktake_session_id == session.id, InventoryMovement.stocktake_count_attempt_id == latest_attempt.id).order_by(InventoryMovement.id.asc()))).scalars().all()',
                'existing_map = {movement.idempotency_key: movement for movement in existing_movements}',
                "expected = {'performed_by': performed_by, 'source_location_id': spec['source_location_id'], 'destination_location_id': spec['destination_location_id'], 'source_stock_status': spec['source_stock_status'], 'destination_stock_status': spec['destination_stock_status'], 'product_variant_id': spec['product_variant_id'], 'batch_id': spec['batch_id'], 'movement_kind': 'PHYSICAL', 'reservation_action': None, 'quantity': spec['quantity'], 'work_session_id': spec['work_session_id'], 'transfer_header_id': None, 'stocktake_session_id': session.id, 'stocktake_count_attempt_id': latest_attempt.id, 'reference_type': spec['reference_type'], 'reference_id': spec['reference_id']}",
                'validate_existing(spec, movement)',
                'ordered_existing.append(movement)',
                'stmt_balances = select(InventoryBalance).execution_options(populate_existing=True).filter(InventoryBalance.company_id == company_id, InventoryBalance.location_id == session.location_id)',
                'stmt_balances = stmt_balances.filter(InventoryBalance.product_variant_id == session.scope_product_variant_id)',
                'stmt_balances = stmt_balances.filter(InventoryBalance.batch_id == session.scope_batch_id)',
                'stmt_balances = stmt_balances.filter(InventoryBalance.product_variant_id.in_(recon_variant_ids))',
                'stmt_balances = stmt_balances.filter(InventoryBalance.id == -1)',
                'stmt_balances = stmt_balances.filter(or_(InventoryBalance.on_hand_quantity > 0, tuple_(InventoryBalance.product_variant_id, InventoryBalance.batch_id, InventoryBalance.stock_status).in_(sorted(expected_by_key))))',
                'balances = (await db_session.execute(stmt_balances.order_by(InventoryBalance.product_variant_id.asc(), InventoryBalance.batch_id.asc(), InventoryBalance.stock_status.asc()).limit(_MAX_STOCKTAKE_POST_LINES + 1).with_for_update())).scalars().all()',
                'stmt_conflict_recheck = select(InventoryLock.id).filter(InventoryLock.company_id == company_id, InventoryLock.location_id == session.location_id, InventoryLock.stocktake_session_id != session.id, InventoryLock.released_at.is_(None))',
                'stmt_conflict_recheck = stmt_conflict_recheck.filter(conflict_scope)',
                'movement_specs = []',
                "movement_specs.append({'product_variant_id': spec['product_variant_id'], 'batch_id': spec['batch_id'], 'quantity': spec['quantity'], 'movement_kind': 'PHYSICAL', 'reference_type': spec['reference_type'], 'reference_id': spec['reference_id'], 'idempotency_key': spec['idempotency_key'], 'source_location_id': spec['source_location_id'], 'destination_location_id': spec['destination_location_id'], 'source_stock_status': spec['source_stock_status'], 'destination_stock_status': spec['destination_stock_status'], 'reservation_action': None, 'work_session_id': spec['work_session_id'], 'transfer_header_id': None, 'stocktake_session_id': session.id, 'stocktake_count_attempt_id': latest_attempt.id, 'financial_unit_price_snapshot': spec.get('financial_unit_price_snapshot'), 'notes': 'ترحيل فرق آخر محاولة عد معتمدة.'})",
                'applied_movements = []',
                'applied_movements = await apply_inventory_movements_batch(db_session, company_id=company_id, performed_by=performed_by, movements=movement_specs)',
                'now = utc_now()',
                "await db_session.execute(update(InventoryLock).where(InventoryLock.company_id == company_id, InventoryLock.stocktake_session_id == session.id, InventoryLock.released_at.is_(None)).values(released_by=performed_by, released_at=now, release_reason='STOCKTAKE_POSTED'))",
                "session.status = 'POSTED'",
                'session.posted_at = now',
                'session.updated_at = now',
                'await _seal_vehicle_inventory_reconciliation(db_session, company_id=company_id, work_session=vehicle_work_session, vehicle_location_id=session.location_id, settled_by=performed_by)',
            ),
            decisions=(
                ('If', 'actor_id is None'),
                ('If', 'probe is None'),
                ('If', "probe_type == 'VEHICLE_RECON'"),
                ('If', 'session is None or session.location_id != probe_location_id or session.stocktake_type != probe_type or (session.related_work_session_id != probe_work_session_id)'),
                ('If', "session.status not in {'APPROVED', 'POSTED'}"),
                ('If', 'session.approved_by is None or session.approved_at is None'),
                ('If', "session.stocktake_type == 'VEHICLE_RECON'"),
                ('If', "session.stocktake_type not in {'FULL_COUNT', 'CYCLE_COUNT', 'VEHICLE_RECON'}"),
                ('If', 'location_row is None'),
                ('If', 'location_type != expected_location_type'),
                ('If', "session.stocktake_type == 'VEHICLE_RECON' and session.status == 'APPROVED'"),
                ('If', "session.status == 'APPROVED' and (not location_is_active)"),
                ('If', "session.stocktake_type == 'VEHICLE_RECON' and session.status == 'APPROVED'"),
                ('If', 'latest_attempt is None'),
                ('If', 'latest_attempt.id != stocktake_count_attempt_id'),
                ('If', 'latest_attempt.submitted_at is None or session.snapshot_cutoff_at is None or latest_attempt.submitted_at < session.snapshot_cutoff_at or (latest_attempt.submitted_at > session.approved_at)'),
                ('If', 'latest_attempt.recount_of_attempt_id is not None'),
                ('If', 'latest_attempt.requires_independent_recount and (parent_attempt is None or not parent_attempt.requires_independent_recount)'),
                ('If', 'any((attempt_line is None for _, attempt_line in line_rows))'),
                ('If', 'len(line_rows) > _MAX_STOCKTAKE_POST_LINES'),
                ('If', "session.stocktake_type == 'CYCLE_COUNT'"),
                ('If', "session.status == 'APPROVED'"),
                ('If', 'len(existing_map) != len(existing_movements)'),
                ('If', "session.status == 'POSTED'"),
                ('If', 'existing_movements'),
                ('If', "session.stocktake_type == 'CYCLE_COUNT'"),
                ('If', 'len(balances) > _MAX_STOCKTAKE_POST_LINES'),
                ('If', "session.status == 'APPROVED'"),
                ('If', 'shortage_variant_ids'),
                ('If', 'movement_specs'),
                ('If', "session.stocktake_type == 'VEHICLE_RECON'"),
                ('If', 'probe_work_session_id is None'),
                ('If', 'locked_probe_session is None'),
                ('If', 'session.related_work_session_id is None'),
                ('If', 'session.related_work_session_id is not None'),
                ('IfExp', "session.stocktake_type == 'VEHICLE_RECON'"),
                ('If', 'location_vehicle_id is None'),
                ('If', 'location_vehicle_id is None'),
                ('If', 'parent_attempt is None or parent_attempt.attempt_number != latest_attempt.attempt_number - 1 or parent_attempt.submitted_at > latest_attempt.submitted_at'),
                ('If', 'parent_attempt.requires_independent_recount and parent_attempt.counted_by == latest_attempt.counted_by'),
                ('If', 'session.scope_product_variant_id is None'),
                ('If', 'session.scope_product_variant_id is not None or session.scope_batch_id is not None'),
                ('If', "session.stocktake_type in {'FULL_COUNT', 'VEHICLE_RECON'}"),
                ('If', 'not own_scope_ok'),
                ('If', 'conflict_scope is not None'),
                ('If', 'conflicting_lock_id is not None'),
                ('If', 'stocktake_line.company_id != company_id or stocktake_line.stocktake_session_id != session.id or attempt_line.company_id != company_id or (attempt_line.stocktake_session_id != session.id) or (attempt_line.stocktake_line_id != stocktake_line.id) or (attempt_line.count_attempt_id != latest_attempt.id)'),
                ('If', 'stock_status not in _INVENTORY_STOCK_STATUSES'),
                ('If', 'key in expected_by_key'),
                ('If', 'attempt_line.expected_quantity != stocktake_line.expected_quantity'),
                ('If', 'variance != attempt_line.actual_quantity - attempt_line.expected_quantity'),
                ('If', 'variance == 0'),
                ('If', 'variance < 0'),
                ('If', "spec['reference_type'] == 'DRIVER_SHORTAGE'"),
                ('If', 'session.posted_at is None'),
                ('If', 'set(existing_map) != expected_idempotency_keys'),
                ('If', "session.stocktake_type == 'VEHICLE_RECON'"),
                ('If', 'session.scope_batch_id is not None'),
                ('If', "session.stocktake_type == 'VEHICLE_RECON'"),
                ('If', 'key not in expected_by_key and balance.on_hand_quantity != 0'),
                ('If', 'current_quantity != expected_quantity'),
                ('If', 'conflict_scope is not None'),
                ('If', '(await db_session.execute(stmt_conflict_recheck.limit(1))).scalar_one_or_none() is not None'),
                ('If', 'session.related_work_session_id is None'),
                ('If', 'len(applied_movements) != len(movement_specs)'),
                ('If', 'stocktake_line.product_variant_id != session.scope_product_variant_id'),
                ('If', 'session.scope_batch_id is not None and stocktake_line.batch_id != session.scope_batch_id'),
                ('If', 'session.scope_batch_id is None'),
                ('If', 'getattr(movement, field_name) != expected_value'),
                ('If', 'snap is None'),
                ('If', 'not snap_dec.is_finite() or snap_dec < 0 or snap_dec > _MONEY_12_3_MAX or (not total_value.is_finite()) or (total_value > _MONEY_12_3_MAX)'),
                ('If', 'snap is not None'),
                ('If', 'movement is None'),
                ('If', 'recon_state is None or recon_state.inventory_reconciled_at is None or recon_state.inventory_reconciled_by is None'),
                ('If', 'incomplete_snapshot_id is not None'),
                ('If', 'recon_variant_ids'),
                ('IfExp', 'balance is not None'),
                ('If', "spec['reference_type'] != 'DRIVER_SHORTAGE'"),
                ('If', 'not total_value.is_finite() or total_value > _MONEY_12_3_MAX'),
                ('IfExp', "session.stocktake_type == 'VEHICLE_RECON'"),
                ('IfExp', "session.stocktake_type == 'VEHICLE_RECON'"),
                ('IfExp', "session.stocktake_type == 'VEHICLE_RECON'"),
            ),
            rejections=(
                ('actor_id is None', "raise InventoryMutationError('منفذ ترحيل الجرد غير موجود/غير فعال أو خارج الشركة.')"),
                ('probe is None', "raise InventoryMutationError('جلسة الجرد غير موجودة أو لا تتبع الشركة.')"),
                ('session is None or session.location_id != probe_location_id or session.stocktake_type != probe_type or (session.related_work_session_id != probe_work_session_id)', "raise InventoryMutationError('جلسة الجرد تغيرت أو لم تعد صالحة للترحيل.')"),
                ("session.status not in {'APPROVED', 'POSTED'}", "raise InventoryMutationError(f'ترحيل الجرد يتطلب حالة APPROVED؛ الحالة الحالية ({session.status}).')"),
                ('session.approved_by is None or session.approved_at is None', "raise InventoryMutationError('جلسة الجرد لا تحمل اعتماداً موثقاً صالحاً.')"),
                ("session.stocktake_type not in {'FULL_COUNT', 'CYCLE_COUNT', 'VEHICLE_RECON'}", "raise InventoryMutationError('نوع جلسة الجرد غير صالح.')"),
                ('location_row is None', "raise InventoryMutationError('موقع جلسة الجرد غير موجود أو لا يتبع الشركة.')"),
                ('location_type != expected_location_type', "raise InventoryMutationError('نوع موقع جلسة الجرد لا يطابق نوع الجرد المعتمد.')"),
                ("session.status == 'APPROVED' and (not location_is_active)", "raise InventoryMutationError('لا يمكن ترحيل جرد جديد على موقع مخزون غير فعال.')"),
                ('latest_attempt is None', "raise InventoryMutationError('لا توجد محاولة عد مثبتة لجلسة الجرد.')"),
                ('latest_attempt.id != stocktake_count_attempt_id', "raise InventoryMutationError('المحاولة المطلوب ترحيلها ليست آخر محاولة عد مثبتة؛ أعد فتح المراجعة.')"),
                ('latest_attempt.submitted_at is None or session.snapshot_cutoff_at is None or latest_attempt.submitted_at < session.snapshot_cutoff_at or (latest_attempt.submitted_at > session.approved_at)', "raise InventoryMutationError('توقيت آخر محاولة عد لا يطابق اللقطة والاعتماد.')"),
                ('latest_attempt.requires_independent_recount and (parent_attempt is None or not parent_attempt.requires_independent_recount)', "raise InventoryMutationError('العجز المادي يتطلب إعادة عد مستقلة قبل الترحيل.')"),
                ('any((attempt_line is None for _, attempt_line in line_rows))', "raise InventoryMutationError('آخر محاولة عد ناقصة ولا تغطي جميع أسطر Snapshot؛ تم رفض الترحيل.')"),
                ('len(line_rows) > _MAX_STOCKTAKE_POST_LINES', "raise InventoryMutationError('جلسة الجرد تتجاوز الحد الآمن لعدد الأسطر في عملية ترحيل واحدة.')"),
                ('len(existing_map) != len(existing_movements)', "raise InventoryMutationError('تم اكتشاف مفاتيح idempotency مكررة في حركات الجرد؛ البيانات غير متسقة.')"),
                ('existing_movements', "raise InventoryMutationError('تم العثور على حركات جرد سابقة بينما الجلسة ما زالت APPROVED؛ تم رفض الحالة الجزئية.')"),
                ('len(balances) > _MAX_STOCKTAKE_POST_LINES', "raise InventoryMutationError('الأرصدة الفعلية تتجاوز نطاق لقطة الجرد المسموح.')"),
                ('probe_work_session_id is None', "raise InventoryMutationError('VEHICLE_RECON بدون WorkSession مرتبط.')"),
                ('locked_probe_session is None', "raise InventoryMutationError('جلسة العمل المرتبطة بـ VEHICLE_RECON غير موجودة أو خارج الشركة.')"),
                ('session.related_work_session_id is None', "raise InventoryMutationError('VEHICLE_RECON يجب أن يرتبط بجلسة العمل التي تتم تسويتها.')"),
                ('session.related_work_session_id is not None', "raise InventoryMutationError('related_work_session_id غير مسموح لغير VEHICLE_RECON.')"),
                ('location_vehicle_id is None', "raise InventoryMutationError('موقع VEHICLE_RECON لا يحمل vehicle_id صالحاً.')"),
                ('location_vehicle_id is None', "raise InventoryMutationError('موقع VEHICLE_RECON لا يحمل vehicle_id صالحاً.')"),
                ('parent_attempt is None or parent_attempt.attempt_number != latest_attempt.attempt_number - 1 or parent_attempt.submitted_at > latest_attempt.submitted_at', "raise InventoryMutationError('سلسلة إعادة العد لا ترتبط بالمحاولة السابقة مباشرة.')"),
                ('parent_attempt.requires_independent_recount and parent_attempt.counted_by == latest_attempt.counted_by', "raise InventoryMutationError('إعادة العد الإلزامية يجب أن ينفذها مستخدم مستقل.')"),
                ('session.scope_product_variant_id is None', "raise InventoryMutationError('CYCLE_COUNT بدون نطاق صنف صالح.')"),
                ('session.scope_product_variant_id is not None or session.scope_batch_id is not None', "raise InventoryMutationError('FULL_COUNT/VEHICLE_RECON لا يجوز أن يحملا نطاق صنف أو دفعة.')"),
                ('not own_scope_ok', "raise InventoryMutationError('قفل الجرد الفعال لا يطابق نطاق الجلسة المعتمدة.')"),
                ('conflicting_lock_id is not None', "raise InventoryMutationError('يوجد قفل جرد آخر متعارض مع نطاق الجلسة الحالية.')"),
                ('stocktake_line.company_id != company_id or stocktake_line.stocktake_session_id != session.id or attempt_line.company_id != company_id or (attempt_line.stocktake_session_id != session.id) or (attempt_line.stocktake_line_id != stocktake_line.id) or (attempt_line.count_attempt_id != latest_attempt.id)', "raise InventoryMutationError('هوية سطر العد لا تطابق لقطة الجرد والمحاولة.')"),
                ('stock_status not in _INVENTORY_STOCK_STATUSES', "raise InventoryMutationError('حالة مخزون غير صالحة في سطر الجرد.')"),
                ('key in expected_by_key', "raise InventoryMutationError('لقطة الجرد تحتوي هوية صنف/دفعة/حالة مكررة.')"),
                ('attempt_line.expected_quantity != stocktake_line.expected_quantity', "raise InventoryMutationError('الكمية المتوقعة في العد تختلف عن لقطة الجرد المقفلة.')"),
                ('variance != attempt_line.actual_quantity - attempt_line.expected_quantity', "raise InventoryMutationError('تم اكتشاف فرق جرد غير متسق حسابياً.')"),
                ('session.posted_at is None', "raise InventoryMutationError('جلسة POSTED بدون posted_at؛ البيانات غير متسقة.')"),
                ('set(existing_map) != expected_idempotency_keys', "raise InventoryMutationError('جلسة POSTED لا تحتوي حصراً على مجموعة حركات الجرد المتوقعة.')"),
                ('key not in expected_by_key and balance.on_hand_quantity != 0', "raise InventoryMutationError('يوجد رصيد فعلي خارج أسطر لقطة الجرد؛ تم رفض الترحيل.')"),
                ('current_quantity != expected_quantity', "raise InventoryMutationError('الرصيد الحي تغيّر عن لقطة الجرد المقفلة؛ تم رفض الترحيل.')"),
                ('(await db_session.execute(stmt_conflict_recheck.limit(1))).scalar_one_or_none() is not None', "raise InventoryMutationError('ظهر قفل جرد متعارض أثناء الترحيل؛ أعد المحاولة لضمان لقطة متسقة.')"),
                ('session.related_work_session_id is None', "raise InventoryMutationError('DRIVER_SHORTAGE يتطلب WorkSession مرتبطاً بالسياق التجاري.')"),
                ('len(applied_movements) != len(movement_specs)', "raise InventoryMutationError('المحرك الموحد لم يعد جميع حركات فروقات الجرد المتوقعة.')"),
                ('stocktake_line.product_variant_id != session.scope_product_variant_id', "raise InventoryMutationError('Snapshot الجرد الدوري يحتوي صنفاً خارج نطاق الجلسة.')"),
                ('session.scope_batch_id is not None and stocktake_line.batch_id != session.scope_batch_id', "raise InventoryMutationError('Snapshot الجرد الدوري يحتوي دفعة خارج نطاق الجلسة.')"),
                ('getattr(movement, field_name) != expected_value', "raise InventoryMutationError('سجل حركة جرد موجود يحمل نفس idempotency لكنه لا يطابق النتيجة المعتمدة.')"),
                ('snap is None', "raise InventoryMutationError('حركة DRIVER_SHORTAGE تاريخية بلا سعر مالي مثبت؛ البيانات غير مكتملة.')"),
                ('not snap_dec.is_finite() or snap_dec < 0 or snap_dec > _MONEY_12_3_MAX or (not total_value.is_finite()) or (total_value > _MONEY_12_3_MAX)', "raise InventoryMutationError('قيمة DRIVER_SHORTAGE التاريخية خارج النطاق المالي.')"),
                ('snap is not None', "raise InventoryMutationError('حركة جرد غير DRIVER_SHORTAGE تحمل سعراً مالياً لا يخصها.')"),
                ('movement is None', "raise InventoryMutationError('حركة جرد متوقعة مفقودة من جلسة POSTED.')"),
                ('recon_state is None or recon_state.inventory_reconciled_at is None or recon_state.inventory_reconciled_by is None', "raise InventoryMutationError('VEHICLE_RECON بحالة POSTED لكن WorkSession بلا ختم تسوية مخزنية مكتمل.')"),
                ('incomplete_snapshot_id is not None', "raise InventoryMutationError('VEHICLE_RECON بحالة POSTED لكن Ending Snapshot غير مكتمل.')"),
                ('not total_value.is_finite() or total_value > _MONEY_12_3_MAX', "raise InventoryMutationError('قيمة عجز المندوب الناتجة تتجاوز السعة المالية Numeric(12,3).')"),
            ),
            returns=['ordered_existing', 'applied_movements'],
        )
        sealing_calls = [
            (function.name, call)
            for function in functions.values() for call in ast.walk(function)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "_seal_vehicle_inventory_reconciliation"
        ]
        self.assertEqual([name for name, call in sealing_calls], [
            "finalize_vehicle_inventory_reconciliation", "post_approved_stocktake_adjustments",
        ])
        # Financial settlement stays separate from ending inventory evidence.
        seal = functions["_seal_vehicle_inventory_reconciliation"]
        self.assertFalse(any(
            isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Attribute) and target.attr == "is_settled"
                for target in node.targets
            ) for node in ast.walk(seal)
        ))

    def test_runtime_callers_keep_field_and_canonical_stocktake_authority(self):
        reconciliation = (BACKEND / "api/reconciliation.py").read_text(encoding="utf-8")
        self.assertIn("field_context: FieldRequestContext = Depends(get_current_field_context)", reconciliation)
        self.assertIn("company_id = int(field_context.company_id)", reconciliation)
        self.assertIn("started_by=driver_id", reconciliation)
        self.assertIn("settled_by=driver_id", reconciliation)
        stocktake = ast.parse((BACKEND / "api/warehouse/stocktake.py").read_text(encoding="utf-8"))
        approve = next(node for node in stocktake.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "approve_stocktake_session")
        body = ast.unparse(approve)
        self.assertLess(body.index("'stocktake.approve'"), body.index("post_approved_stocktake_adjustments("))
        self.assertIn("company_id = access.company_id", body)
        self.assertIn("performed_by=legacy_actor.id", body)


if __name__ == "__main__":
    unittest.main()
