"""Dependency-free Dispatch identity, locking, and transaction source guards."""
import ast
from collections import Counter
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "api" / "dispatch.py"
HELPER = ROOT / "domains" / "dispatch_representatives.py"


class DispatchRepresentativeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = DISPATCH.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)
        self.helper_source = HELPER.read_text(encoding="utf-8")
        self.helper_tree = ast.parse(self.helper_source)
        self.functions = {node.name: node for node in self.tree.body if isinstance(node, ast.AsyncFunctionDef)}

    def test_zero_legacy_boolean_or_bridge_label_authority(self):
        self.assertNotIn("is_admin", self.source)
        self.assertNotIn("is_admin", self.helper_source)
        self.assertNotIn("classification", self.helper_source)

    def test_all_seven_classification_sites_use_the_canonical_predicate(self):
        counts = {}
        for name, node in self.functions.items():
            count = sum(isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                        and item.func.id == "has_canonical_field_identity" for item in ast.walk(node))
            if count:
                counts[name] = count
        self.assertEqual(counts, {"dispatch_init": 1, "dispatch_route": 1,
                                 "update_route_status": 2, "undo_end_work": 1, "add_shortages": 2})

    def test_identity_helper_has_no_authentication_capability_or_transaction_operations(self):
        names = {node.id for node in ast.walk(self.helper_tree) if isinstance(node, ast.Name)}
        attributes = {node.attr for node in ast.walk(self.helper_tree) if isinstance(node, ast.Attribute)}
        self.assertTrue(names.isdisjoint({"Driver", "InventoryAccess", "HTTPException", "Depends", "jwt"}))
        self.assertTrue(attributes.isdisjoint({"commit", "rollback", "begin", "begin_nested", "execute",
                                             "add", "delete", "flush", "decode", "capabilities"}))
        self.assertFalse(any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(self.helper_tree)))

    def test_request_transaction_calls_remain_at_the_existing_boundaries(self):
        expected = {"dispatch_init": {}, "dispatch_route": {"commit": 1, "rollback": 5},
                    "update_route_status": {"commit": 1, "rollback": 5},
                    "undo_end_work": {"commit": 1, "rollback": 2},
                    "add_shortages": {"commit": 1, "rollback": 3}}
        for name, calls in expected.items():
            actual = Counter(node.func.attr for node in ast.walk(self.functions[name])
                             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                             and isinstance(node.func.value, ast.Name) and node.func.value.id == "db"
                             and node.func.attr in {"commit", "rollback", "begin", "begin_nested"})
            self.assertEqual(dict(actual), calls, name)

    def test_locked_identity_projections_do_not_filter_historical_operational_rows(self):
        projected = {"driver_row", "driver_rows", "drivers"}
        queries = []
        for name in ("update_route_status", "add_shortages"):
            for node in ast.walk(self.functions[name]):
                if not isinstance(node, ast.Assign) or not any(
                    isinstance(target, ast.Name) and target.id in projected for target in node.targets
                ):
                    continue
                selections = [part for part in ast.walk(node.value) if isinstance(part, ast.Call)
                              and isinstance(part.func, ast.Name) and part.func.id == "select"
                              and part.args and isinstance(part.args[0], ast.Name) and part.args[0].id == "Driver"]
                if selections:
                    queries.append(node)
                    self.assertEqual(len(selections[0].args), 2)
                    self.assertEqual(selections[0].args[1].func.id, "has_canonical_field_identity")
                    locks = [part for part in ast.walk(node.value) if isinstance(part, ast.Call)
                             and isinstance(part.func, ast.Attribute) and part.func.attr == "with_for_update"]
                    self.assertEqual(len(locks), 1)
                    self.assertEqual(locks[0].args, [])
                    self.assertEqual(locks[0].keywords, [])
        self.assertEqual(len(queries), 3)
        live_assets = next(node for node in ast.walk(self.functions["update_route_status"])
                           if isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                           and node.test.id == "requires_live_assets")
        self.assertIn("driver_has_field_identity", ast.unparse(live_assets.body[0].test))


if __name__ == "__main__":
    unittest.main()
