from __future__ import annotations

import ast
from pathlib import Path
import unittest


BACKEND = Path(__file__).resolve().parents[1]
SOURCE = BACKEND / "api/warehouse/stocktake.py"


def _function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _source(node: ast.AST, source: str) -> str:
    segment = ast.get_source_segment(source, node)
    assert segment is not None
    return segment


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


class VehicleReconciliationLockOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, feature_version=(3, 11))
        cls.loader = _function(cls.tree, "_load_stocktake_session")
        cls.start = _function(cls.tree, "start_unified_stocktake")
        cls.approve = _function(cls.tree, "approve_stocktake_session")
        cls.loader_source = _source(cls.loader, cls.source)
        cls.start_source = _source(cls.start, cls.source)
        cls.approve_source = _source(cls.approve, cls.source)

    def test_vehicle_recon_start_locks_work_session_before_location_guard(self):
        validate = self.start_source.index("await validate_vehicle_recon_work_session(")
        guard = self.start_source.index("await acquire_inventory_location_guard(")
        self.assertLess(validate, guard)
        self.assertIn("work_session_id=payload.related_work_session_id", self.start_source)

    def test_vehicle_recon_start_revalidates_strict_custody_after_guard(self):
        guard = self.start_source.index("await acquire_inventory_location_guard(")
        strict = self.start_source.index("await resolve_vehicle_custody_location_id(")
        effects = self.start_source.index("existing_recon_id = (")
        self.assertLess(guard, strict)
        self.assertLess(strict, effects)
        self.assertIn("expected_location_id=int(payload.location_id)", self.start_source)

    def test_warehouse_start_does_not_require_work_session(self):
        vehicle_if = next(
            node for node in ast.walk(self.start)
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "payload.stocktake_type == 'VEHICLE_RECON'"
            and any(
                isinstance(child, ast.Call)
                and _call_name(child) == "validate_vehicle_recon_work_session"
                for child in ast.walk(node)
            )
        )
        self.assertIsNotNone(vehicle_if)
        self.assertIn("if payload.stocktake_type != 'VEHICLE_RECON':", self.start_source)
        self.assertIn("InventoryLocation.is_active.is_(True)", self.start_source)
        self.assertEqual(self.start_source.count("validate_vehicle_recon_work_session("), 1)

    def test_approval_plain_probe_prelocks_vehicle_work_session(self):
        self.assertIn("for_update: bool = False", self.loader_source)
        self.assertIn("lock_vehicle_recon_work_session: bool = False", self.loader_source)
        probe = self.loader_source.index("stmt = select(StocktakeSession)")
        vehicle_gate = self.loader_source.index(
            "if lock_vehicle_recon_work_session and session.stocktake_type == 'VEHICLE_RECON':"
        )
        missing = self.loader_source.index("if session.related_work_session_id is None:")
        lock = self.loader_source.index("select(WorkSession.id).filter_by(")
        self.assertLess(probe, vehicle_gate)
        self.assertLess(vehicle_gate, missing)
        self.assertLess(missing, lock)
        work_session_select = next(
            call for call in ast.walk(self.loader)
            if isinstance(call, ast.Call)
            and _call_name(call) == "select"
            and any(
                isinstance(arg, ast.Attribute)
                and isinstance(arg.value, ast.Name)
                and arg.value.id == "WorkSession"
                and arg.attr == "id"
                for arg in call.args
            )
        )
        self.assertIsNotNone(work_session_select)
        self.assertIn(".with_for_update()", self.loader_source[lock:])

    def test_vehicle_recon_approval_locks_work_session_before_guard_and_reload(self):
        probe = self.approve_source.index("probe = await _load_stocktake_session(")
        prelock = self.approve_source.index("lock_vehicle_recon_work_session=True")
        guard = self.approve_source.index("await acquire_inventory_location_guard(")
        reload = self.approve_source.index(
            "session = await _load_stocktake_session(db, company_id, session_id, for_update=True)"
        )
        approved = self.approve_source.index("session.status = 'APPROVED'")
        posting = self.approve_source.index("movements = await post_approved_stocktake_adjustments(")
        self.assertLess(probe, prelock)
        self.assertLess(prelock, guard)
        self.assertLess(guard, reload)
        self.assertLess(reload, approved)
        self.assertLess(approved, posting)

    def test_invalid_or_missing_vehicle_work_session_stops_before_guard(self):
        missing = self.loader_source.index("if session.related_work_session_id is None:")
        missing_raise = self.loader_source.index("VEHICLE_RECON بدون WorkSession مرتبط.")
        work_lock = self.loader_source.index("select(WorkSession.id).filter_by(")
        locked_missing = self.loader_source.index("if locked_work_session_id is None:")
        self.assertLess(missing, missing_raise)
        self.assertLess(missing_raise, work_lock)
        self.assertLess(work_lock, locked_missing)
        self.assertNotIn("acquire_inventory_location_guard", self.loader_source)

    def test_no_vehicle_row_lock_is_introduced(self):
        for function in (self.loader, self.start, self.approve):
            for call in (
                node for node in ast.walk(function) if isinstance(node, ast.Call)
            ):
                if _call_name(call) != "select":
                    continue
                self.assertFalse(
                    any(isinstance(arg, ast.Name) and arg.id == "Vehicle" for arg in call.args),
                    function.name,
                )

    def test_approval_delegates_posting_once_and_preserves_rollback_contract(self):
        self.assertEqual(self.approve_source.count("post_approved_stocktake_adjustments("), 1)
        self.assertGreaterEqual(self.approve_source.count("await db.rollback()"), 4)
        posting = self.approve_source.index("movements = await post_approved_stocktake_adjustments(")
        success_commit = self.approve_source.index("await db.commit()", posting)
        self.assertLess(posting, success_commit)
        handlers = [node for node in self.approve.body if isinstance(node, ast.Try)][0].handlers
        self.assertEqual(len(handlers), 4)
        for handler in handlers:
            body = "\n".join(ast.unparse(statement) for statement in handler.body)
            self.assertIn("await db.rollback()", body)


if __name__ == "__main__":
    unittest.main()
