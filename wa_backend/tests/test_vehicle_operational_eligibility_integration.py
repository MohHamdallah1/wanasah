from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
