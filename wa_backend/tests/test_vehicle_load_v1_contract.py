import unittest
from pathlib import Path

from domains.inventory_vehicle_load.service import (
    _preserve_or_tighten_unload_status,
)


BACKEND = Path(__file__).resolve().parents[1]
SERVICE = (BACKEND / "domains/inventory_vehicle_load/service.py").read_text(
    encoding="utf-8"
)
API = (BACKEND / "api/vehicles/load.py").read_text(encoding="utf-8")
SCHEMAS = (BACKEND / "api/vehicles/load_schemas.py").read_text(encoding="utf-8")
ROUTER = (BACKEND / "api/vehicles/__init__.py").read_text(encoding="utf-8")


class VehicleLoadV1ContractTests(unittest.TestCase):
    def test_inventory_engine_remains_the_only_quantity_mutation_authority(self):
        self.assertIn("apply_inventory_movements_batch(", SERVICE)
        self.assertNotIn("InventoryBalance(", SERVICE)
        self.assertNotIn("packs_per_carton", SERVICE)
        self.assertIn('"movement_kind": "PHYSICAL"', SERVICE)
        self.assertIn('"movement_kind": "STATUS_CHANGE"', SERVICE)

    def test_exact_location_capabilities_not_vehicle_manage_authorize_stock(self):
        for fragment in (
            '"inventory.read"',
            '"transfer.send"',
            '"transfer.destination"',
        ):
            self.assertIn(fragment, SERVICE)
        self.assertNotIn("vehicle.manage", SERVICE)
        self.assertNotIn("vehicle.manage", API)
        self.assertIn('require_backoffice_capability("vehicle.read")', API)

    def test_route_and_settlement_ownership_block_direct_mutation(self):
        self.assertIn('WorkSession.inventory_reconciled_at.is_(None)', SERVICE)
        self.assertIn("_MODE_ROUTE", SERVICE)
        self.assertIn("_MODE_SETTLEMENT", SERVICE)
        self.assertIn("CURRENT_ROUTE_STATUSES", SERVICE)
        self.assertIn('owner.mode != _MODE_DIRECT', SERVICE)
        self.assertIn("_lock_direct_context(", SERVICE)

    def test_add_path_is_operational_lifecycle_product_location_and_fefo_guarded(self):
        for fragment in (
            "vehicle_is_operational(vehicle)",
            "ROUTE_LOAD_NEW",
            "acquire_product_lifecycle_guards(",
            "product_location_allows(",
            "allocate_fefo_inventory_batch(",
            '"VEHICLE_LOAD_DIRECT"',
        ):
            self.assertIn(fragment, SERVICE)

    def test_unload_preserves_custody_and_tightens_current_safety(self):
        for fragment in (
            "_allocate_vehicle_status(",
            "_ensure_unload_product_locations(",
            "resolve_inflight_transfer_destination_statuses(",
            "_preserve_or_tighten_unload_status(",
            '"VEHICLE_UNLOAD_DIRECT"',
            '"VEHICLE_UNLOAD_SAFE_STATUS"',
        ):
            self.assertIn(fragment, SERVICE)
        self.assertEqual(
            _preserve_or_tighten_unload_status("AVAILABLE", "RECALLED"),
            "RECALLED",
        )
        self.assertEqual(
            _preserve_or_tighten_unload_status("AVAILABLE", "QUARANTINED"),
            "QUARANTINED",
        )
        self.assertEqual(
            _preserve_or_tighten_unload_status("DAMAGED", "RECALLED"),
            "DAMAGED",
        )
        self.assertEqual(
            _preserve_or_tighten_unload_status("BLOCKED", "AVAILABLE"),
            "BLOCKED",
        )

    def test_durable_request_identity_and_replay_are_server_owned(self):
        self.assertIn("begin_idempotent_operation(", SERVICE)
        self.assertIn("complete_idempotent_operation(", SERVICE)
        self.assertIn('operation=f"VEHICLE_LOAD_{normalized_direction}"', SERVICE)
        self.assertIn("request_hash=_request_hash(", SERVICE)
        self.assertIn("if replay is not None:", SERVICE)

    def test_vehicle_load_http_surface_is_bounded_and_mounted(self):
        for fragment in (
            '@router.get(\n    "/{vehicle_id}/load"',
            '"/{vehicle_id}/load/warehouses"',
            '"/{vehicle_id}/load/source-inventory"',
            '"/{vehicle_id}/load/add"',
            '"/{vehicle_id}/load/unload"',
        ):
            self.assertIn(fragment, API)
        self.assertIn("router.include_router(load_router, prefix=\"/vehicles\")", ROUTER)
        self.assertIn('Literal["DIRECT", "ROUTE", "SETTLEMENT_REQUIRED"]', SCHEMAS)
        self.assertIn("max_length=500", SCHEMAS)


if __name__ == "__main__":
    unittest.main()
