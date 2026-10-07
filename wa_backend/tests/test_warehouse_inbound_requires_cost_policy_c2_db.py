"""Opt-in real SQL+FastAPI-handler C2 negative gate for first costed inbound.

Uses an authorized empty developer tenant; validates whole operation rollback.
The inventory posting function is patched to raise if unexpectedly reached,
so this regression cannot accidentally commit a sale/receipt on a bad code path.
"""
from __future__ import annotations

from tests.supplier_fixtures import seed_receipt_supplier

import os
import unittest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text

from api.warehouse.inbound import warehouse_inbound
from database import engine
from domains.inventory_costing.service import get_cost_policy
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    open_tenant_session,
)
from models import Driver
from schemas import UpgradedInboundRequest


@unittest.skipUnless(
    os.getenv("WANASAH_C2_DB_GATE") == "1",
    "Requires explicit developer DB, tenant and empty-policy opt-in.",
)
class WarehouseInboundCostSelectionC2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.company_id = int(os.environ["WANASAH_C2_TEST_TENANT"])
        self.token, self.db = await open_tenant_session(self.company_id)
        actual_db = await self.db.scalar(text("SELECT current_database()"))
        self.assertEqual(actual_db, os.environ["WANASAH_C2_EXPECTED_DB"])
        self.assertEqual(
            await self.db.scalar(
                text("SELECT current_setting('app.current_tenant',true)")
            ), str(self.company_id),
        )
        self.assertIsNone(
            await get_cost_policy(self.db, company_id=self.company_id),
            "Test company must have no existing costing policy.",
        )
        self.actor = await self.db.scalar(
            select(Driver).where(
                Driver.company_id == self.company_id,
                Driver.is_active.is_(True),
                Driver.is_admin.is_(True),
            ).limit(1)
        )
        self.assertIsNotNone(self.actor)
        self.supplier_id = await seed_receipt_supplier(self.db, self.actor)
        self.location_id = await self.db.scalar(text(
            "SELECT id FROM inventory_locations WHERE company_id=:company_id "
            "AND location_type='WAREHOUSE' AND is_active=true "
            "AND is_system_managed=false ORDER BY id LIMIT 1"
        ), {"company_id": self.company_id})
        self.variant = (
            await self.db.execute(text(
                "SELECT id,base_uom_id FROM product_variants "
                "WHERE company_id=:company_id AND lifecycle_status='ACTIVE' "
                "AND operational_hold='NONE' AND expiry_control_mode='REQUIRED' "
                "ORDER BY id LIMIT 1"
            ), {"company_id": self.company_id})
        ).mappings().first()
        self.assertIsNotNone(self.location_id)
        self.assertIsNotNone(self.variant)

    async def asyncTearDown(self):
        await self.db.rollback()
        await close_tenant_session(self.token, self.db)
        await engine.dispose()

    async def test_unselected_policy_blocks_actual_inbound_handler_without_partial_writes(self):
        request_id = uuid4()
        batch = "C2-NEG-" + uuid4().hex[:12]
        supplier_ref = "C2-NEG-" + uuid4().hex[:12]
        payload = UpgradedInboundRequest(
            supplier_id=self.supplier_id,
            request_id=request_id,
            location_id=self.location_id,
            reference_id=supplier_ref,
            items=[{
                "product_variant_id": self.variant["id"],
                "quantity": "1",
                "uom_id": self.variant["base_uom_id"],
                "unit_cost": "2",
                "batch_number": batch,
                "production_date": date.today() - timedelta(days=30),
                "expiry_date": date.today() + timedelta(days=730),
            }],
        )
        with patch(
            "api.warehouse.inbound.apply_inventory_movements_batch",
            new_callable=AsyncMock,
        ) as apply_inventory:
            apply_inventory.side_effect = AssertionError(
                "Unselected receipt reached physical stock posting."
            )
            with self.assertRaises(HTTPException) as caught:
                await warehouse_inbound(
                    payload=payload, db=self.db, current_admin=self.actor,
                )
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(
                caught.exception.detail["code"],
                "INVENTORY_COST_POLICY_SELECTION_REQUIRED",
            )
            apply_inventory.assert_not_awaited()

        # The route's CostingError handler must roll back its own transaction,
        # including any earlier idempotency, batch and location assignment work.
        for table, column, value in (
            ("operation_idempotency", "request_id", str(request_id)),
            ("product_batches", "batch_number", batch),
            ("inventory_movements", "reference_id", supplier_ref),
        ):
            count = await self.db.scalar(
                text(
                    f"SELECT count(*) FROM {table} WHERE "
                    f"company_id=:company_id AND {column}=:value"
                ),
                {"company_id": self.company_id, "value": value},
            )
            self.assertEqual(count, 0, f"Partial {table} write survived.")
        self.assertIsNone(
            await get_cost_policy(self.db, company_id=self.company_id)
        )


if __name__ == "__main__":
    unittest.main()
