"""Dependency-free identity and workflow parity gates for the three session routes."""
import ast
from collections import Counter
import hashlib
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "api" / "driver.py"
# Business-body fingerprints from main a936f616; the two identity bindings are excluded.
BODY_DIGESTS = {
    "start_work_session": "00566cb59269c821834bbda5fd72ef8932e1fe1e89f777944e7f8932aac36b1c",
    "end_work_session": "7e9c926eb3e83af84d7896300006887d7dd5f4a747ab7a18bf62cea0a8b7591b",
    "toggle_break": "793da3021eca89551d710c2043d03c474f2b573ebad457a88a0d2463ba4cf42b",
}
UNRELATED_DIGEST = "62e4b36fc87f83ca85381d0accc0895b42010ebdafb7f83f9a7c3ea6e381c3a4"


def digest(nodes):
    tree = ast.Module(body=nodes, type_ignores=[])
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


class DriverSessionFieldContextBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        self.functions = {node.name: node for node in self.tree.body
                          if isinstance(node, ast.AsyncFunctionDef) and node.name in BODY_DIGESTS}
        self.assertEqual(set(self.functions), set(BODY_DIGESTS))

    def test_all_three_routes_use_canonical_field_and_cached_legacy_dependencies(self):
        for name, node in self.functions.items():
            with self.subTest(endpoint=name):
                arguments = {arg.arg: arg for arg in node.args.args}
                defaults = dict(zip([arg.arg for arg in node.args.args][-len(node.args.defaults):], node.args.defaults))
                self.assertEqual(arguments["field_context"].annotation.id, "FieldRequestContext")
                self.assertEqual(arguments["legacy_actor"].annotation.id, "Driver")
                for parameter, dependency in (("field_context", "get_legacy_transport_field_context"),
                                               ("legacy_actor", "get_current_driver")):
                    self.assertEqual(defaults[parameter].func.id, "Depends")
                    self.assertEqual(defaults[parameter].args[0].id, dependency)
                    self.assertEqual(defaults[parameter].keywords, [])

    def test_company_is_canonical_and_driver_id_is_only_the_operational_locator(self):
        for name, node in self.functions.items():
            with self.subTest(endpoint=name):
                bindings = {item.targets[0].id: ast.unparse(item.value) for item in node.body[:2]}
                self.assertEqual(bindings, {"company_id": "field_context.company_id", "driver_id": "legacy_actor.id"})
                for part in ast.walk(node):
                    if isinstance(part, ast.Attribute):
                        self.assertNotIn(part.attr, {"is_admin", "classification", "role", "roles", "decode"})
                        if isinstance(part.value, ast.Name) and part.value.id in {"legacy_actor", "current_driver", "locked_driver"}:
                            self.assertNotEqual(part.attr, "company_id")
                    if isinstance(part, ast.Name):
                        self.assertNotIn(part.id, {"current_driver", "jwt", "decode_company_token"})

    def test_business_rules_queries_responses_and_snapshot_path_are_unchanged(self):
        for name, expected in BODY_DIGESTS.items():
            self.assertEqual(digest(self.functions[name].body[2:]), expected, name)

    def test_no_unrelated_driver_module_or_endpoint_changes(self):
        allowed_imports = {"api.authentication.legacy_field_transport": "get_legacy_transport_field_context",
                           "domains.auth_sessions.context": "FieldRequestContext"}
        remainder = []
        for node in self.tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name in BODY_DIGESTS:
                continue
            if isinstance(node, ast.ImportFrom) and node.module in allowed_imports:
                self.assertEqual([alias.name for alias in node.names], [allowed_imports[node.module]])
                continue
            remainder.append(node)
        self.assertEqual(digest(remainder), UNRELATED_DIGEST)

    def test_row_locks_and_exclusive_vehicle_inventory_guard_remain(self):
        for name, node in self.functions.items():
            locks = [part for part in ast.walk(node) if isinstance(part, ast.Call)
                     and isinstance(part.func, ast.Attribute) and part.func.attr == "with_for_update"]
            self.assertEqual(len(locks), 4 if name == "start_work_session" else 1)
            self.assertTrue(all(not lock.args for lock in locks))
            modes = [tuple((keyword.arg, keyword.value.value) for keyword in lock.keywords) for lock in locks]
            self.assertEqual(Counter(modes), Counter({(): 3, (("read", True),): 1})
                             if name == "start_work_session" else Counter({(): 1}))
        guard = next(part for part in ast.walk(self.functions["start_work_session"])
                     if isinstance(part, ast.Call) and isinstance(part.func, ast.Name)
                     and part.func.id == "acquire_inventory_location_guard")
        self.assertEqual([ast.unparse(arg) for arg in guard.args], ["db", "company_id", "vehicle_location_id"])
        self.assertEqual([(item.arg, item.value.value) for item in guard.keywords], [("exclusive", True)])

    def test_existing_transaction_boundaries_remain(self):
        expected = {"start_work_session": {"add": 2, "flush": 1, "commit": 1, "rollback": 11},
                    "end_work_session": {"commit": 1, "rollback": 2},
                    "toggle_break": {"add": 1, "commit": 1, "rollback": 2}}
        for name, node in self.functions.items():
            actual = Counter(part.func.attr for part in ast.walk(node)
                             if isinstance(part, ast.Call) and isinstance(part.func, ast.Attribute)
                             and isinstance(part.func.value, ast.Name) and part.func.value.id == "db"
                             and part.func.attr in {"commit", "rollback", "begin", "begin_nested", "flush", "add"})
            self.assertEqual(dict(actual), expected[name], name)


if __name__ == "__main__":
    unittest.main()
