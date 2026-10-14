"""Structural identity and workflow gates for the three Driver session routes."""
import ast
from collections import Counter
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "api" / "driver.py"
SESSION_ROUTES = {
    "start_work_session": ("post", "/driver/sessions/start"),
    "end_work_session": ("put", "/driver/sessions/end"),
    "toggle_break": ("put", "/driver/sessions/break"),
}


def _named_calls(node, name):
    return [
        part
        for part in ast.walk(node)
        if isinstance(part, ast.Call)
        and (
            (isinstance(part.func, ast.Name) and part.func.id == name)
            or (isinstance(part.func, ast.Attribute) and part.func.attr == name)
        )
    ]


def _keyword(call, name):
    return next((item.value for item in call.keywords if item.arg == name), None)


def _db_operations(node):
    return Counter(
        part.func.attr
        for part in ast.walk(node)
        if isinstance(part, ast.Call)
        and isinstance(part.func, ast.Attribute)
        and isinstance(part.func.value, ast.Name)
        and part.func.value.id == "db"
        and part.func.attr
        in {"commit", "rollback", "begin", "begin_nested", "flush", "add"}
    )


class DriverSessionFieldContextBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        self.functions = {
            node.name: node
            for node in self.tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name in SESSION_ROUTES
        }
        self.assertEqual(set(self.functions), set(SESSION_ROUTES))

    def test_all_three_routes_use_canonical_field_and_cached_legacy_dependencies(self):
        for name, node in self.functions.items():
            with self.subTest(endpoint=name):
                arguments = {arg.arg: arg for arg in node.args.args}
                defaults = dict(
                    zip(
                        [arg.arg for arg in node.args.args][-len(node.args.defaults):],
                        node.args.defaults,
                    )
                )
                self.assertEqual(arguments["field_context"].annotation.id, "FieldRequestContext")
                self.assertEqual(arguments["legacy_actor"].annotation.id, "Driver")
                for parameter, dependency in (
                    ("field_context", "get_current_field_context"),
                    ("legacy_actor", "get_current_field_legacy_driver"),
                ):
                    self.assertEqual(defaults[parameter].func.id, "Depends")
                    self.assertEqual(defaults[parameter].args[0].id, dependency)
                    self.assertEqual(defaults[parameter].keywords, [])

    def test_company_is_canonical_and_driver_id_is_only_the_operational_locator(self):
        for name, node in self.functions.items():
            with self.subTest(endpoint=name):
                bindings = {
                    item.targets[0].id: ast.unparse(item.value)
                    for item in node.body[:2]
                }
                self.assertEqual(
                    bindings,
                    {
                        "company_id": "field_context.company_id",
                        "driver_id": "legacy_actor.id",
                    },
                )
                for part in ast.walk(node):
                    if isinstance(part, ast.Attribute):
                        self.assertNotIn(
                            part.attr,
                            {"is_admin", "classification", "role", "roles", "decode"},
                        )
                        if (
                            isinstance(part.value, ast.Name)
                            and part.value.id
                            in {"legacy_actor", "current_driver", "locked_driver"}
                        ):
                            self.assertNotEqual(part.attr, "company_id")
                    if isinstance(part, ast.Name):
                        self.assertNotIn(
                            part.id,
                            {"current_driver", "jwt", "decode_company_token"},
                        )

    def test_route_contracts_and_business_workflow_guards_are_structural(self):
        for name, (method, path) in SESSION_ROUTES.items():
            node = self.functions[name]
            with self.subTest(endpoint=name):
                route = next(
                    item
                    for item in node.decorator_list
                    if isinstance(item, ast.Call)
                    and isinstance(item.func, ast.Attribute)
                    and item.func.attr == method
                )
                self.assertEqual(route.args[0].value, path)
                source = ast.unparse(node)
                self.assertIn("company_id = field_context.company_id", source)
                self.assertIn("driver_id = legacy_actor.id", source)
                self.assertIn("WorkSession", source)

        start = ast.unparse(self.functions["start_work_session"])
        for token in (
            "DispatchRoute",
            "resolve_vehicle_custody_location_id",
            "acquire_inventory_location_guard",
            "read_vehicle_operational_state",
            "vehicle_is_operational",
            "SessionInventorySnapshot",
            "VehicleError",
        ):
            with self.subTest(start_token=token):
                self.assertIn(token, start)

        end = ast.unparse(self.functions["end_work_session"])
        for token in (
            "InventoryTransferHeader",
            "workflow_type == 'HANDSHAKE'",
            "active_session.end_time = get_utc_now()",
        ):
            with self.subTest(end_token=token):
                self.assertIn(token, end)

        toggle = ast.unparse(self.functions["toggle_break"])
        for token in ("WorkBreakLog", "break_start_time", "break_end_time"):
            with self.subTest(toggle_token=token):
                self.assertIn(token, toggle)

    def test_driver_auth_imports_allow_approved_mixed_context_without_legacy_authority(self):
        imports = {
            node.module: [alias.name for alias in node.names]
            for node in self.tree.body
            if isinstance(node, ast.ImportFrom)
        }
        dependency_names = imports["api.authentication.dependencies"]
        self.assertIn("get_current_field_context", dependency_names)
        # Approved mixed visit-detail authorization also needs principal context.
        self.assertIn("get_current_principal_context", dependency_names)
        self.assertEqual(
            imports["api.authentication.field_compatibility"],
            ["get_current_field_legacy_driver"],
        )
        all_imported_names = {
            alias.name
            for node in self.tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertNotIn("get_current_driver", all_imported_names)

    def test_strict_custody_guard_and_operational_check_order_remain(self):
        node = self.functions["start_work_session"]
        resolves = sorted(
            _named_calls(node, "resolve_vehicle_custody_location_id"),
            key=lambda call: call.lineno,
        )
        self.assertEqual(len(resolves), 2)
        first_resolve, revalidate = resolves
        guard = _named_calls(node, "acquire_inventory_location_guard")
        self.assertEqual(len(guard), 1)
        guard = guard[0]
        state_reads = _named_calls(node, "read_vehicle_operational_state")
        operational_checks = _named_calls(node, "vehicle_is_operational")
        self.assertEqual(len(state_reads), 1)
        self.assertEqual(len(operational_checks), 1)

        self.assertIsInstance(_keyword(first_resolve, "require_active"), ast.Constant)
        self.assertTrue(_keyword(first_resolve, "require_active").value)
        self.assertIsInstance(_keyword(revalidate, "expected_location_id"), ast.Name)
        self.assertEqual(_keyword(revalidate, "expected_location_id").id, "vehicle_location_id")
        self.assertTrue(_keyword(revalidate, "require_active").value)
        self.assertTrue(_keyword(guard, "exclusive").value)

        self.assertLess(first_resolve.lineno, guard.lineno)
        self.assertLess(guard.lineno, revalidate.lineno)
        self.assertLess(revalidate.lineno, state_reads[0].lineno)
        self.assertLess(state_reads[0].lineno, operational_checks[0].lineno)

        row_locks = sorted(
            [
                part
                for part in ast.walk(node)
                if isinstance(part, ast.Call)
                and isinstance(part.func, ast.Attribute)
                and part.func.attr == "with_for_update"
            ],
            key=lambda call: call.lineno,
        )
        self.assertTrue(
            any(guard.lineno < lock.lineno < revalidate.lineno for lock in row_locks),
            "Expected exact Vehicle InventoryLocation row lock between guard and custody revalidation",
        )

    def test_row_locks_and_exclusive_vehicle_inventory_guard_remain(self):
        for name, node in self.functions.items():
            locks = [
                part
                for part in ast.walk(node)
                if isinstance(part, ast.Call)
                and isinstance(part.func, ast.Attribute)
                and part.func.attr == "with_for_update"
            ]
            self.assertEqual(len(locks), 4 if name == "start_work_session" else 1)
            self.assertTrue(all(not lock.args for lock in locks))
            modes = [
                tuple((keyword.arg, keyword.value.value) for keyword in lock.keywords)
                for lock in locks
            ]
            self.assertEqual(
                Counter(modes),
                Counter({(): 3, (("read", True),): 1})
                if name == "start_work_session"
                else Counter({(): 1}),
            )

    def test_transaction_boundaries_are_semantic_not_body_fingerprints(self):
        expected = {
            "start_work_session": {"add": 2, "flush": 1, "commit": 1},
            "end_work_session": {"commit": 1},
            "toggle_break": {"add": 1, "commit": 1},
        }
        for name, node in self.functions.items():
            with self.subTest(endpoint=name):
                actual = _db_operations(node)
                for operation, count in expected[name].items():
                    self.assertEqual(actual[operation], count)
                self.assertEqual(actual["begin"], 0)
                self.assertEqual(actual["begin_nested"], 0)

                transaction_try = next(
                    item for item in node.body if isinstance(item, ast.Try)
                )
                self.assertGreaterEqual(len(transaction_try.handlers), 2)
                for handler in transaction_try.handlers:
                    rollback_calls = [
                        part
                        for part in ast.walk(handler)
                        if isinstance(part, ast.Call)
                        and isinstance(part.func, ast.Attribute)
                        and isinstance(part.func.value, ast.Name)
                        and part.func.value.id == "db"
                        and part.func.attr == "rollback"
                    ]
                    self.assertTrue(
                        rollback_calls,
                        f"{name} exception path must rollback before propagating/translation",
                    )


if __name__ == "__main__":
    unittest.main()
