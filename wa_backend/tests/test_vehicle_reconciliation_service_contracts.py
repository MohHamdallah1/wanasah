"""Focused service contracts using exact production bodies and recorded I/O.

No packages/OS event loop are needed. Query doubles record predicates and locks;
they do not claim PostgreSQL, SQLAlchemy compilation or HTTP integration proof.
Inventory movements remain a mocked collaborator, not a second inventory engine.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
SOURCE = BACKEND / "services.py"
NOW = datetime(2026, 10, 12, 12)
FIELD_DRIVER = 9003
APPROVER = 9004
TARGETS = {
    "open_vehicle_reconciliation_stocktake",
    "finalize_vehicle_inventory_reconciliation",
    "post_approved_stocktake_adjustments",
}
# Base 8e200258: only reviewed flag retirement/error changes normalized.
BUSINESS_DIGESTS = {
    "open_vehicle_reconciliation_stocktake": "c2cb93ac36f13bf40a3a21415588ce827141154cd8568528ae78ab570463c65b",
    "finalize_vehicle_inventory_reconciliation": "6d839b1fd6eaca5bdf8a621fb0622cf4370eb4e53703913d0b272898af895709",
    "post_approved_stocktake_adjustments": "5500d67d5130332d5eabeba0c1fc234dabf9c54b0a2942d9b06f15113c6f97d9",
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
    def __init__(self, case, *, driver_id=FIELD_DRIVER, flag=False, company_id=7, active=True):
        self.case = case
        self.actor_id = driver_id
        self.actor = SimpleNamespace(id=driver_id, company_id=company_id, is_active=active, is_admin=flag)
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
    parsed = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = TARGETS | {"_seal_vehicle_inventory_reconciliation", "validate_vehicle_recon_work_session",
                       "_strict_int", "_quantity_decimal", "InventoryMutationError"}
    nodes = [node for node in parsed.body if getattr(node, "name", None) in names]
    future = ast.parse("from __future__ import annotations").body[0]
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

    def test_source_audit_and_business_body_parity(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("is_admin", source)
        parsed = ast.parse(source)
        functions = {node.name: deepcopy(node) for node in parsed.body if isinstance(node, ast.AsyncFunctionDef)}
        field = functions["finalize_vehicle_inventory_reconciliation"]
        self.assertEqual(ast.unparse(field.body[-1].value.value.func), "_seal_vehicle_inventory_reconciliation")
        seal = functions["_seal_vehicle_inventory_reconciliation"]
        field.body = field.body[:-1] + seal.body[1:]  # expand only the private effect/docstring extraction
        post = functions["post_approved_stocktake_adjustments"]
        class ExpandComposition(ast.NodeTransformer):
            def visit_Assign(self, node):
                if isinstance(node.targets[0], ast.Name) and node.targets[0].id == "vehicle_work_session":
                    return ast.Expr(value=node.value)
                return self.generic_visit(node)
            def visit_Call(self, node):
                if isinstance(node.func, ast.Name) and node.func.id == "_seal_vehicle_inventory_reconciliation":
                    node.func.id = "finalize_vehicle_inventory_reconciliation"
                    for keyword in node.keywords:
                        if keyword.arg == "work_session":
                            keyword.arg = "work_session_id"
                            keyword.value = ast.parse("session.related_work_session_id", mode="eval").body
                return self.generic_visit(node)
        ExpandComposition().visit(post)
        for name, expected in BUSINESS_DIGESTS.items():
            self.assertEqual(hashlib.sha256(ast.dump(functions[name], include_attributes=False).encode()).hexdigest(), expected, name)
        for node in ast.walk(parsed):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_seal_vehicle_inventory_reconciliation":
                owner = next(fn for fn in parsed.body if isinstance(fn, ast.AsyncFunctionDef) and node in list(ast.walk(fn)))
                self.assertIn(owner.name, {"finalize_vehicle_inventory_reconciliation", "post_approved_stocktake_adjustments"})

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
