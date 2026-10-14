"""Focused strict Vehicle custody gates for Dispatch access and live-stock projections."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DISPATCH_ACCESS = (ROOT / "dispatch_access.py").read_text(encoding="utf-8")
LIVE_STOCK = (ROOT / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
PROJECTION = (ROOT / "domains" / "live_stock_projection" / "service.py").read_text(encoding="utf-8")
RESERVATIONS = (ROOT / "domains" / "dispatch_reservations.py").read_text(encoding="utf-8")
ARCHIVE = (ROOT / "domains" / "dispatch_archive_navigation.py").read_text(encoding="utf-8")


def strict_ready(rows, *, company_id, vehicle_id):
    historical = [r for r in rows if r["company_id"] == company_id and r["vehicle_id"] == vehicle_id and r["type"] == "VEHICLE"]
    return len(historical) == 1 and historical[0]["active"]


class VehicleDispatchAccessCustodyTests(unittest.TestCase):
    def test_strict_custody_truth_table(self):
        one = [{"company_id": 1, "vehicle_id": 7, "type": "VEHICLE", "active": True}]
        self.assertTrue(strict_ready(one, company_id=1, vehicle_id=7))
        self.assertFalse(strict_ready(one + [{"company_id": 1, "vehicle_id": 7, "type": "VEHICLE", "active": False}], company_id=1, vehicle_id=7))
        self.assertFalse(strict_ready([], company_id=1, vehicle_id=7))
        self.assertFalse(strict_ready([{**one[0], "active": False}], company_id=1, vehicle_id=7))
        self.assertTrue(strict_ready(one + [{"company_id": 2, "vehicle_id": 7, "type": "VEHICLE", "active": False}], company_id=1, vehicle_id=7))

    def test_dispatch_access_requires_historical_cardinality_and_active_exact_row(self):
        self.assertIn("select(func.count(history.id))", DISPATCH_ACCESS)
        self.assertIn('history.location_type == "VEHICLE"', DISPATCH_ACCESS)
        self.assertGreaterEqual(DISPATCH_ACCESS.count("_strict_vehicle_custody_count(access.company_id"), 2)
        self.assertIn("InventoryLocation.is_active.is_(True)", DISPATCH_ACCESS)

    def test_location_scope_and_any_location_authority_are_preserved(self):
        self.assertIn("access.allows(code, InventoryLocation.id)", DISPATCH_ACCESS)
        self.assertIn("await access.require(code, any_location=True)", DISPATCH_ACCESS)
        self.assertNotIn("vehicle.read", DISPATCH_ACCESS)
        self.assertNotIn("vehicle.manage", DISPATCH_ACCESS)

    def test_live_stock_readable_vehicle_rows_are_strict_only(self):
        body = LIVE_STOCK[LIVE_STOCK.index("def _readable_vehicle_locations_subquery"):LIVE_STOCK.index("def _latest_readable_vehicle_sources_subquery")]
        self.assertIn("historical_count == 1", body)
        self.assertIn("access.location_filter(\"inventory.read\")", body)
        self.assertIn("InventoryLocation.is_active.is_(True)", body)

    def test_projection_all_canonical_vehicle_attribution_paths_are_strict(self):
        self.assertEqual(PROJECTION.count('_strict_vehicle_custody_count(company_id, InventoryLocation.vehicle_id) == 1'), 4)
        for marker in ("live_stock_vehicle_agg", "live_stock_candidate_latest_route", "live_stock_attribution_vehicle_ids", "live_stock_rebuild_latest_route"):
            self.assertIn(marker, PROJECTION)

    def test_live_stock_never_writes_inventory_balance(self):
        for source in (LIVE_STOCK, PROJECTION):
            self.assertNotIn("update(InventoryBalance)", source)
            self.assertNotIn("delete(InventoryBalance)", source)
            self.assertNotIn("InventoryBalance(", source)

    def test_reservations_continue_to_inherit_route_filter(self):
        self.assertEqual(RESERVATIONS.count('route_filter(access, "dispatch.read")'), 2)
        self.assertIn('access.location_filter("inventory.read", h.source_location_id)', RESERVATIONS)

    def test_archive_continues_to_inherit_route_filter(self):
        self.assertGreaterEqual(ARCHIVE.count('route_filter(access, "dispatch.read")'), 2)
        self.assertIn('route_filter(access, "dispatch.execute")', ARCHIVE)


if __name__ == "__main__":
    unittest.main()
