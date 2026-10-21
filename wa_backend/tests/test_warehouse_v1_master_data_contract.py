import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from pydantic import ValidationError

from api.warehouse import locations
from models import InventoryLocation
from schemas import WarehouseLocationCreateRequest, WarehouseLocationUpdateRequest


class WarehouseV1MasterDataContractTests(unittest.IsolatedAsyncioTestCase):
    def test_create_normalizes_code_and_optional_physical_metadata(self):
        payload = WarehouseLocationCreateRequest(
            request_id=uuid4(),
            name=" Main Warehouse ",
            code=" wh-001 ",
            address=" Amman, Marka ",
            location_link=" https://maps.google.com/example ",
            latitude=31.9539,
            longitude=35.9106,
        )
        self.assertEqual(payload.name, "Main Warehouse")
        self.assertEqual(payload.code, "WH-001")
        self.assertEqual(payload.address, "Amman, Marka")
        self.assertEqual(payload.location_link, "https://maps.google.com/example")
        self.assertEqual(payload.latitude, 31.9539)
        self.assertEqual(payload.longitude, 35.9106)
        self.assertIsNone(payload.branch_id)

    def test_create_and_update_reject_partial_coordinate_pairs(self):
        with self.assertRaises(ValidationError):
            WarehouseLocationCreateRequest(
                request_id=uuid4(),
                name="Warehouse",
                code="WH-001",
                latitude=31.9539,
            )

        with self.assertRaises(ValidationError):
            WarehouseLocationUpdateRequest(
                request_id=uuid4(),
                expected_version=1,
                latitude=31.9539,
            )

    def test_update_can_clear_coordinates_without_touching_branch(self):
        payload = WarehouseLocationUpdateRequest(
            request_id=uuid4(),
            expected_version=4,
            latitude=None,
            longitude=None,
            address="Updated address",
        )
        self.assertIn("latitude", payload.model_fields_set)
        self.assertIn("longitude", payload.model_fields_set)
        self.assertNotIn("branch_id", payload.model_fields_set)
        self.assertEqual(payload.address, "Updated address")

    def test_inventory_location_has_v1_location_columns_and_database_guards(self):
        columns = InventoryLocation.__table__.c
        for name in ("address", "location_link", "latitude", "longitude"):
            self.assertIn(name, columns)
        constraint_names = {constraint.name for constraint in InventoryLocation.__table__.constraints}
        self.assertTrue(any(name and name.endswith("chk_inv_loc_coordinates_pair") for name in constraint_names))
        self.assertTrue(any(name and name.endswith("chk_inv_loc_latitude_range") for name in constraint_names))
        self.assertTrue(any(name and name.endswith("chk_inv_loc_longitude_range") for name in constraint_names))
        self.assertIn("uq_inv_loc_company_code", constraint_names)

    async def test_code_suggestion_is_company_scoped_sequence_and_not_a_reservation(self):
        db = SimpleNamespace(scalar=AsyncMock(return_value=7))
        access = SimpleNamespace(company_id=42, require=AsyncMock())

        result = await locations.suggest_warehouse_location_code(db=db, access=access)

        self.assertEqual(result, {"code": "WH-008"})
        access.require.assert_awaited_once_with(
            "location.create",
            location_id=None,
            any_location=False,
        )
        db.scalar.assert_awaited_once()

    def test_response_payload_exposes_physical_metadata_and_preserves_branch_relation(self):
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        row = SimpleNamespace(
            id=9,
            name="Main Warehouse",
            code="WH-009",
            address="Amman",
            location_link="https://maps.google.com/example",
            latitude=Decimal("31.9539000"),
            longitude=Decimal("35.9106000"),
            branch_id=3,
            is_active=True,
            version=2,
            created_at=now,
            updated_at=now,
        )
        result = locations._warehouse_location_to_payload(row, branch_name="Legacy Branch")
        self.assertEqual(result["address"], "Amman")
        self.assertEqual(result["location_link"], "https://maps.google.com/example")
        self.assertEqual(result["latitude"], 31.9539)
        self.assertEqual(result["longitude"], 35.9106)
        self.assertEqual(result["branch_id"], 3)
        self.assertEqual(result["branch_name"], "Legacy Branch")


if __name__ == "__main__":
    unittest.main()
