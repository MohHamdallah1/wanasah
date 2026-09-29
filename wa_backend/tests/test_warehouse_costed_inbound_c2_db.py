"""C2 positive costed-inbound DB gates, including durable request replay.

Opt in only with WANASAH_C2_POSITIVE_DB_GATE=1,
WANASAH_C2_POSITIVE_EXPECTED_DB and WANASAH_C2_POSITIVE_TEST_TENANT.
A real warehouse handler is executed under a PostgreSQL outer transaction,
with SQLAlchemy sessions configured to commit SAVEPOINTs. All fixtures,
idempotency rows and stock/cost postings are rolled back by the outer
transaction. Do not run this against production or use shared customer data.
"""
from __future__ import annotations

import os
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse.inbound import (
    update_warehouse_costing_policy,
    warehouse_inbound,
)
from context import tenant_context
from database import engine
from schemas import InventoryCostPolicyUpdateRequest, UpgradedInboundRequest


@unittest.skipUnless(
    os.environ.get("WANASAH_C2_POSITIVE_DB_GATE") == "1",
    "Explicit authorized developer database only.",
)
class CostedInboundC2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.company_id = int(os.environ["WANASAH_C2_POSITIVE_TEST_TENANT"])
        self.token = tenant_context.set(self.company_id)
        self.conn = await engine.connect()
        self.outer = await self.conn.begin()
        self.db = AsyncSession(
            bind=self.conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        await self.db.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(self.company_id)},
        )
        self.assertEqual(
            await self.db.scalar(text("SELECT current_database()")),
            os.environ["WANASAH_C2_POSITIVE_EXPECTED_DB"],
        )
        self.assertEqual(
            await self.db.scalar(text("SELECT current_setting('app.current_tenant',true)")),
            str(self.company_id),
        )
        # Tenant 2 on the approved synthetic developer database has one active
        # test SKU and an empty financial policy and stock. Do not repurpose.
        for table in (
            "inventory_cost_policies",
            "inventory_cost_events",
            "inventory_balances",
            "operation_idempotency",
        ):
            self.assertEqual(await self._count(table), 0, table)
        actor = await self.db.scalar(
            text(
                "SELECT id FROM drivers WHERE company_id=:company_id "
                "AND is_admin=true AND is_active=true ORDER BY id LIMIT 1"
            ),
            {"company_id": self.company_id},
        )
        self.assertIsNotNone(actor)
        self.actor = SimpleNamespace(
            company_id=self.company_id, id=actor,
            is_admin=True, is_active=True,
        )
        self.location_id = await self.db.scalar(
            text(
                "SELECT id FROM inventory_locations WHERE company_id=:company_id "
                "AND location_type='WAREHOUSE' AND is_active=true "
                "AND is_system_managed=false ORDER BY id LIMIT 1"
            ),
            {"company_id": self.company_id},
        )
        self.variant = (
            await self.db.execute(
                text(
                    "SELECT id, base_uom_id FROM product_variants "
                    "WHERE company_id=:company_id "
                    "AND lifecycle_status='ACTIVE' AND operational_hold='NONE' "
                    "AND expiry_control_mode='REQUIRED' ORDER BY id LIMIT 1"
                ),
                {"company_id": self.company_id},
            )
        ).mappings().first()
        self.assertIsNotNone(self.location_id)
        self.assertIsNotNone(self.variant)

    async def asyncTearDown(self):
        try:
            await self.db.close()
            if self.outer.is_active:
                await self.outer.rollback()
        finally:
            await self.conn.close()
            tenant_context.reset(self.token)
            await engine.dispose()

    async def _count(self, table: str) -> int:
        assert table in {
            "inventory_cost_policies", "inventory_cost_events",
            "inventory_balances", "inventory_movements",
            "inventory_cost_states", "inventory_cost_layers",
            "operation_idempotency", "product_batches",
        }
        return int(await self.db.scalar(
            text("SELECT count(*) FROM " + table + " WHERE company_id=:company_id"),
            {"company_id": self.company_id},
        ))

    async def _select_method(self, method: str) -> None:
        request = InventoryCostPolicyUpdateRequest(
            request_id=uuid4(), method=method, expected_version=0,
        )
        selected = await update_warehouse_costing_policy(
            payload=request, db=self.db, current_admin=self.actor,
        )
        self.assertEqual(selected["method"], method)
        self.assertEqual(selected["selection_status"], "SELECTED")
        self.assertTrue(selected["is_selected"])
        self.assertFalse(selected["is_locked"])
        self.assertEqual(selected["version"], 1)

    def _inbound(
        self,
        request_id,
        reference: str,
        batch: str,
        *,
        quantity: str = "10",
        price: str = "2",
    ):
        return UpgradedInboundRequest(
            request_id=request_id,
            location_id=self.location_id,
            reference_id=reference,
            items=[{
                "product_variant_id": self.variant["id"],
                "quantity": quantity,
                "uom_id": self.variant["base_uom_id"],
                "unit_cost": price,
                "batch_number": batch,
                "production_date": date(2026, 1, 1),
                "expiry_date": date(2027, 12, 31),
            }],
        )

    async def _source_costs(self):
        return (
            await self.db.execute(
                text(
                    "SELECT e.id,e.method,e.event_type,e.batch_id,"
                    "e.input_quantity,e.input_unit_cost,e.total_cost,"
                    "e.quantity_after,e.value_after "
                    "FROM inventory_cost_events e "
                    "WHERE e.company_id=:company_id ORDER BY e.id"
                ),
                {"company_id": self.company_id},
            )
        ).mappings().all()

    async def _assert_one_post_and_replay(self, method: str) -> None:
        await self._select_method(method)
        uid = uuid4()
        reference = "C2-ONE-" + uid.hex[:16]
        batch = "C2-ONE-" + uid.hex[:16]
        receipt = self._inbound(uid, reference, batch)
        first = await warehouse_inbound(
            payload=receipt, db=self.db, current_admin=self.actor,
        )
        self.assertEqual(first, {"message": "INBOUND_POSTED"})
        self.assertEqual(await self._count("inventory_movements"), 1)
        self.assertEqual(await self._count("inventory_cost_events"), 1)
        self.assertEqual(await self._count("inventory_balances"), 1)
        self.assertEqual(await self._count("inventory_cost_states"), 1)
        self.assertEqual(
            await self._count("inventory_cost_layers"),
            1 if method == "FIFO" else 0,
        )
        policy = (
            await self.db.execute(
                text(
                    "SELECT method,is_active,locked_at,selected_at,selected_by,version "
                    "FROM inventory_cost_policies WHERE company_id=:company_id"
                ),
                {"company_id": self.company_id},
            )
        ).mappings().one()
        self.assertEqual(policy["method"], method)
        self.assertTrue(policy["is_active"])
        self.assertIsNotNone(policy["locked_at"])
        self.assertIsNotNone(policy["selected_at"])
        self.assertEqual(policy["selected_by"], self.actor.id)
        self.assertEqual(policy["version"], 2)
        costs = await self._source_costs()
        self.assertEqual(len(costs), 1)
        self.assertEqual(costs[0]["method"], method)
        self.assertEqual(costs[0]["event_type"], "PURCHASE_IN")
        self.assertEqual(Decimal(costs[0]["input_quantity"]), Decimal("10"))
        self.assertEqual(Decimal(costs[0]["input_unit_cost"]), Decimal("2"))
        self.assertEqual(Decimal(costs[0]["total_cost"]), Decimal("20"))
        self.assertEqual(Decimal(costs[0]["value_after"]), Decimal("20"))

        # Retry after the first write has committed its SAVEPOINT. Returned
        # evidence must be identical and there must be NO duplicate movement.
        replayed = await warehouse_inbound(
            payload=receipt, db=self.db, current_admin=self.actor,
        )
        self.assertEqual(replayed, first)
        self.assertEqual(await self._count("inventory_movements"), 1)
        self.assertEqual(await self._count("inventory_cost_events"), 1)
        self.assertEqual(await self._count("inventory_cost_layers"), 1 if method == "FIFO" else 0)

        changed = self._inbound(uid, reference, batch, price="3")
        with self.assertRaises(HTTPException) as caught:
            await warehouse_inbound(
                payload=changed, db=self.db, current_admin=self.actor,
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(await self._count("inventory_cost_events"), 1)

        # Changing request ID but recycling the supplier's invoice number also
        # must fail (even though it is a different idempotency key).
        duplicate_ref = self._inbound(uuid4(), reference, batch)
        with self.assertRaises(HTTPException) as caught_ref:
            await warehouse_inbound(
                payload=duplicate_ref, db=self.db, current_admin=self.actor,
            )
        self.assertEqual(caught_ref.exception.status_code, 409)
        self.assertEqual(caught_ref.exception.detail["code"], "INBOUND_REFERENCE_DUPLICATE")
        self.assertEqual(await self._count("inventory_cost_events"), 1)
        self.assertEqual(await self._count("inventory_movements"), 1)

    async def test_fifo_first_costed_receipt_and_retry(self):
        await self._assert_one_post_and_replay("FIFO")

    async def test_moving_average_first_costed_receipt_and_retry(self):
        await self._assert_one_post_and_replay("MOVING_AVERAGE")

    async def _assert_same_lot_multiple_receipt_costs(self, method: str):
        await self._select_method(method)
        common_batch = "C2-LOT-" + uuid4().hex[:16]
        for quantity, price in (("10", "2"), ("5", "3")):
            uid = uuid4()
            posted = await warehouse_inbound(
                payload=self._inbound(
                    uid, "C2-LOT-" + uid.hex[:16], common_batch,
                    quantity=quantity, price=price,
                ),
                db=self.db,
                current_admin=self.actor,
            )
            self.assertEqual(posted, {"message": "INBOUND_POSTED"})

        self.assertEqual(await self._count("product_batches"), 1)
        self.assertEqual(await self._count("inventory_movements"), 2)
        self.assertEqual(await self._count("inventory_cost_events"), 2)
        self.assertEqual(
            await self._count("inventory_cost_layers"),
            2 if method == "FIFO" else 0,
        )
        events = await self._source_costs()
        self.assertEqual({event["batch_id"] for event in events}, {events[0]["batch_id"]})
        self.assertEqual(
            [(Decimal(event["input_quantity"]), Decimal(event["input_unit_cost"]),
              Decimal(event["total_cost"])) for event in events],
            [(Decimal("10"), Decimal("2"), Decimal("20")),
             (Decimal("5"), Decimal("3"), Decimal("15"))],
        )
        state = (
            await self.db.execute(
                text(
                    "SELECT quantity,inventory_value,average_unit_cost "
                    "FROM inventory_cost_states WHERE company_id=:company_id "
                    "AND product_variant_id=:variant_id"
                ),
                {"company_id": self.company_id, "variant_id": self.variant["id"]},
            )
        ).mappings().one()
        self.assertEqual(Decimal(state["quantity"]), Decimal("15"))
        self.assertEqual(Decimal(state["inventory_value"]), Decimal("35"))
        self.assertEqual(Decimal(state["average_unit_cost"]), Decimal("2.333333"))
        # This is purchase-event provenance, NOT one "actual price of lot" and
        # NOT an alternative official per-manufacturer-lot profit calculation.

    async def test_fifo_two_receipts_same_manufacturer_lot_different_prices(self):
        await self._assert_same_lot_multiple_receipt_costs("FIFO")

    async def test_moving_average_two_receipts_same_manufacturer_lot_different_prices(self):
        await self._assert_same_lot_multiple_receipt_costs("MOVING_AVERAGE")


if __name__ == "__main__":
    unittest.main()
