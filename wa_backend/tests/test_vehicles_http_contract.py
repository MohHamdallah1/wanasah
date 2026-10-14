import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


class VehicleHttpContractTests(unittest.TestCase):
    def test_six_routes_and_capabilities_are_frozen(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (BACKEND / "api/vehicles").glob("*.py")
        )
        for fragment in (
            '@router.get(""',
            '@router.get("/{vehicle_id}"',
            '@router.post(""',
            '@router.patch("/{vehicle_id}"',
            '@router.post("/{vehicle_id}/deactivate"',
            '@router.post("/{vehicle_id}/reactivate"',
        ):
            self.assertIn(fragment, combined)
        self.assertIn('require_backoffice_capability("vehicle.read")', combined)
        self.assertIn('require_backoffice_capability("vehicle.manage")', combined)
        self.assertNotIn("is_admin", combined)

    def test_read_routes_do_not_load_legacy_driver(self):
        source = (BACKEND / "api/vehicles/read.py").read_text(encoding="utf-8")
        self.assertNotIn("get_current_backoffice_legacy_driver", source)
        self.assertNotIn("from models import Driver", source)

    def test_custody_resolution_never_picks_one_with_limit(self):
        source = (BACKEND / "domains/vehicles/repository.py").read_text(encoding="utf-8")
        start = source.index("async def _custody_ids")
        end = source.index("def _custody_cardinality_error", start)
        self.assertNotIn("limit(1)", source[start:end])
        self.assertIn("len(ids) != 1", source)

    def test_query_seam_is_future_scope_ready_without_balance_join(self):
        source = (BACKEND / "domains/vehicles/queries.py").read_text(encoding="utf-8")
        self.assertIn("visibility_filter=None", source)
        self.assertIn('scope_tag: str = "company"', source)
        self.assertNotIn("InventoryBalance", source)


if __name__ == "__main__":
    unittest.main()
