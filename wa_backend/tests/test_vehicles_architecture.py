import ast
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PACKAGES = (BACKEND / "api/vehicles", BACKEND / "domains/vehicles")


class VehicleArchitectureTests(unittest.TestCase):
    def test_dedicated_modules_exist_and_do_not_import_legacy_http_business_modules(self):
        expected = {
            "domains/vehicles/contracts.py", "domains/vehicles/repository.py",
            "domains/vehicles/queries.py", "domains/vehicles/management.py",
            "domains/vehicles/validation.py", "domains/vehicles/custody.py",
            "domains/vehicles/lifecycle_guards.py", "domains/vehicles/lifecycle.py",
            "api/vehicles/schemas.py", "api/vehicles/read.py",
            "api/vehicles/management.py", "api/vehicles/lifecycle.py",
        }
        self.assertTrue(all((BACKEND / path).exists() for path in expected))
        violations = []
        for root in PACKAGES:
            for path in root.glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module in {
                        "api.dispatch", "api.driver", "dispatch_access"
                    }:
                        violations.append((path.name, node.module))
        self.assertEqual(violations, [])

    def test_lifecycle_blocker_queries_take_no_row_locks_and_scan_all_stock_statuses(self):
        source = (BACKEND / "domains/vehicles/lifecycle_guards.py").read_text(encoding="utf-8")
        self.assertNotIn("with_for_update", source)
        self.assertIn("InventoryBalance.on_hand_quantity", source)
        self.assertIn("InventoryBalance.reserved_quantity", source)
        self.assertNotIn('InventoryBalance.stock_status == "AVAILABLE"', source)

    def test_custody_lock_hierarchy_is_vehicle_then_location_guard_then_location_row(self):
        management = (BACKEND / "domains/vehicles/management.py").read_text(encoding="utf-8")
        lifecycle = (BACKEND / "domains/vehicles/lifecycle.py").read_text(encoding="utf-8")
        repository = (BACKEND / "domains/vehicles/repository.py").read_text(encoding="utf-8")
        self.assertLess(management.index("load_vehicle("), management.index("lock_vehicle_custody("))
        self.assertLess(lifecycle.index("load_vehicle("), lifecycle.index("lock_vehicle_custody("))
        start = repository.index("async def lock_canonical_custody")
        body = repository[start:]
        self.assertLess(body.index("acquire_inventory_location_guard("), body.index(".with_for_update()"))

    def test_main_mounts_dedicated_vehicle_router(self):
        source = (BACKEND / "main.py").read_text(encoding="utf-8-sig")
        self.assertIn("app.include_router(vehicles.router)", source)


if __name__ == "__main__":
    unittest.main()
