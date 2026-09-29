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
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
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
from services import apply_inventory_movements_batch, reverse_inventory_movements_batch


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
                "production_date": date.today() - timedelta(days=30),
                "expiry_date": date.today() + timedelta(days=730),
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

    async def _outbound_cost_gate(self, method: str, *, reverse: bool = False):
        # The sale-like inventory movement is intentionally tested at the
        # inventory costing boundary. It is NOT a full VisitItem/sales-API gate.
        await self._select_method(method)
        older_receipt = uuid4()
        newer_receipt = uuid4()
        physical_older_lot = "C2-LATE-EXP-" + older_receipt.hex[:12]
        physical_earlier_expiry_lot = "C2-EARLY-EXP-" + newer_receipt.hex[:12]
        first = self._inbound(
            older_receipt, "C2-FIN-" + older_receipt.hex[:12],
            physical_older_lot, price="2",
        )
        first.items[0].expiry_date = date.today() + timedelta(days=1100)
        second = self._inbound(
            newer_receipt, "C2-FIN-" + newer_receipt.hex[:12],
            physical_earlier_expiry_lot, price="4",
        )
        # First purchased lot expires LATER; physical expiry-based withdrawal
        # deliberately chooses the second lot. Accounting FIFO must still
        # consume the first acquisition cost layer.
        await warehouse_inbound(payload=first, db=self.db, current_admin=self.actor)
        await warehouse_inbound(payload=second, db=self.db, current_admin=self.actor)
        physical_lots = (
            await self.db.execute(
                text(
                    "SELECT batch_number,id FROM product_batches "
                    "WHERE company_id=:company_id AND batch_number IN (:b1,:b2)"
                ),
                {
                    "company_id": self.company_id,
                    "b1": physical_older_lot,
                    "b2": physical_earlier_expiry_lot,
                },
            )
        ).all()
        ids_by_batch = {str(row.batch_number): int(row.id) for row in physical_lots}
        self.assertEqual(len(ids_by_batch), 2)

        unique = uuid4()
        spec = {
            "product_variant_id": self.variant["id"],
            "batch_id": ids_by_batch[physical_earlier_expiry_lot],
            "quantity": Decimal("3"),
            "movement_kind": "PHYSICAL",
            "reference_type": "VISIT_ITEM_OUT",
            "reference_id": "C2-TEST-VISIT-" + unique.hex[:12],
            "idempotency_key": "C2-TEST-OUT-" + unique.hex,
            "source_location_id": self.location_id,
            "destination_location_id": None,
            "source_stock_status": "AVAILABLE",
            "destination_stock_status": None,
        }
        [withdrawal] = await apply_inventory_movements_batch(
            self.db,
            company_id=self.company_id,
            performed_by=self.actor.id,
            movements=[spec],
        )
        await self.db.commit()
        rows = (
            await self.db.execute(
                text(
                    "SELECT e.method,e.event_type,e.cost_basis,e.total_cost,"
                    "e.batch_id,e.quantity_after,e.value_after "
                    "FROM inventory_cost_events e "
                    "WHERE e.company_id=:company_id AND e.event_type='OUTBOUND'"
                ),
                {"company_id": self.company_id},
            )
        ).mappings().all()
        self.assertEqual(len(rows), 1)
        cost = rows[0]
        expected_cogs = Decimal("6") if method == "FIFO" else Decimal("9")
        expected_value = Decimal("54") if method == "FIFO" else Decimal("51")
        self.assertEqual(Decimal(cost["total_cost"]), expected_cogs)
        self.assertEqual(Decimal(cost["value_after"]), expected_value)
        self.assertEqual(Decimal(cost["quantity_after"]), Decimal("17"))
        self.assertEqual(cost["batch_id"], ids_by_batch[physical_earlier_expiry_lot])
        self.assertEqual(cost["cost_basis"], "FIFO_LAYER" if method == "FIFO" else "MOVING_AVERAGE")
        balances = (
            await self.db.execute(
                text(
                    "SELECT p.batch_number,b.on_hand_quantity FROM inventory_balances b "
                    "JOIN product_batches p ON p.company_id=b.company_id AND p.id=b.batch_id "
                    "WHERE b.company_id=:company_id"
                ),
                {"company_id": self.company_id},
            )
        ).all()
        self.assertEqual(
            {name: Decimal(q) for name, q in balances},
            {physical_older_lot: Decimal("10"),
             physical_earlier_expiry_lot: Decimal("7")},
        )

        if method == "FIFO":
            consumed = (
                await self.db.execute(
                    text(
                        "SELECT l.batch_id,a.quantity,a.amount "
                        "FROM inventory_cost_allocations a "
                        "JOIN inventory_cost_layers l "
                        " ON a.company_id=l.company_id AND a.cost_layer_id=l.id "
                        "WHERE a.company_id=:company_id AND a.allocation_type='CONSUME'"
                    ),
                    {"company_id": self.company_id},
                )
            ).all()
            self.assertEqual(len(consumed), 1)
            self.assertEqual(consumed[0].batch_id, ids_by_batch[physical_older_lot])
            self.assertEqual(Decimal(consumed[0].quantity), Decimal("3"))
            self.assertEqual(Decimal(consumed[0].amount), Decimal("6"))

        # Retry the same physical movement: same movement and cost event.
        [replayed] = await apply_inventory_movements_batch(
            self.db,
            company_id=self.company_id,
            performed_by=self.actor.id,
            movements=[spec],
        )
        self.assertEqual(replayed.id, withdrawal.id)
        self.assertEqual(await self._count("inventory_cost_events"), 3)

        if reverse:
            [returned] = await reverse_inventory_movements_batch(
                self.db,
                originals=[withdrawal],
                performed_by=self.actor.id,
                reference_type="VISIT_REVERSAL",
                reference_id="C2-REV-" + unique.hex[:12],
            )
            self.assertEqual(returned.product_variant_id, withdrawal.product_variant_id)
            self.assertEqual(returned.batch_id, withdrawal.batch_id)
            await self.db.commit()
            [again] = await reverse_inventory_movements_batch(
                self.db,
                originals=[withdrawal],
                performed_by=self.actor.id,
                reference_type="VISIT_REVERSAL",
                reference_id="C2-REV-" + unique.hex[:12],
            )
            self.assertEqual(again.id, returned.id)
            self.assertEqual(await self._count("inventory_cost_events"), 4)
            restored = (
                await self.db.execute(
                    text(
                        "SELECT event_type,cost_basis,reversal_of_cost_event_id,"
                        "total_cost,quantity_after,value_after "
                        "FROM inventory_cost_events "
                        "WHERE company_id=:company_id AND event_type='REVERSAL_IN'"
                    ),
                    {"company_id": self.company_id},
                )
            ).mappings().one()
            self.assertEqual(restored["cost_basis"], "ORIGINAL_REVERSAL")
            self.assertEqual(Decimal(restored["total_cost"]), expected_cogs)
            self.assertEqual(Decimal(restored["quantity_after"]), Decimal("20"))
            self.assertEqual(Decimal(restored["value_after"]), Decimal("60"))

    async def test_fifo_outbound_uses_first_acquisition_even_if_other_lot_expires_first(self):
        await self._outbound_cost_gate("FIFO")

    async def test_moving_average_outbound_uses_inventory_average_not_selected_lot_cost(self):
        await self._outbound_cost_gate("MOVING_AVERAGE")

    async def test_fifo_reversal_restores_original_accounting_cost_once(self):
        await self._outbound_cost_gate("FIFO", reverse=True)

    async def test_moving_average_reversal_restores_original_accounting_cost_once(self):
        await self._outbound_cost_gate("MOVING_AVERAGE", reverse=True)

    async def _assert_atomic_failure_before_commit(self, method: str) -> None:
        """A thrown exception AFTER stock/cost writes must roll it ALL back."""
        await self._select_method(method)
        rid = uuid4()
        reference = "C2-FAIL-" + rid.hex[:16]
        lot = "C2-FAIL-" + rid.hex[:16]
        payload = self._inbound(rid, reference, lot, quantity="7", price="3")

        def simulate_failure_after_idempotency_completion(record, result):
            from services import complete_idempotent_operation as real_complete

            real_complete(record, result)
            raise RuntimeError("C2 simulated failure AFTER stock and cost; BEFORE commit")

        with patch(
            "api.warehouse.inbound.complete_idempotent_operation",
            side_effect=simulate_failure_after_idempotency_completion,
        ) as injected:
            with self.assertRaises(HTTPException) as caught:
                await warehouse_inbound(
                    payload=payload, db=self.db, current_admin=self.actor,
                )
        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(caught.exception.detail["code"], "INBOUND_INTERNAL_ERROR")
        injected.assert_called_once()
        for table in (
            "inventory_movements",
            "inventory_cost_events",
            "inventory_cost_states",
            "inventory_cost_layers",
            "inventory_balances",
            "product_batches",
            "operation_idempotency",
        ):
            self.assertEqual(await self._count(table), 0, table)

        # Choice was saved by the earlier authorized policy PUT. Failed first
        # supplier receipt must leave it selected but not active/locked.
        policy = (
            await self.db.execute(
                text(
                    "SELECT method,is_active,locked_at,selected_at,version "
                    "FROM inventory_cost_policies WHERE company_id=:company_id"
                ),
                {"company_id": self.company_id},
            )
        ).mappings().one()
        self.assertEqual(policy["method"], method)
        self.assertFalse(policy["is_active"])
        self.assertIsNone(policy["locked_at"])
        self.assertIsNotNone(policy["selected_at"])
        self.assertEqual(policy["version"], 1)

        # Retry same request_id with ORIGINAL payload when transient injected
        # error has gone away; there is no poisoned/pending idempotency row.
        response = await warehouse_inbound(
            payload=payload, db=self.db, current_admin=self.actor,
        )
        self.assertEqual(response, {"message": "INBOUND_POSTED"})
        self.assertEqual(await self._count("inventory_movements"), 1)
        self.assertEqual(await self._count("inventory_cost_events"), 1)
        self.assertEqual(await self._count("operation_idempotency"), 1)
        self.assertEqual(
            await self._count("inventory_cost_layers"),
            1 if method == "FIFO" else 0,
        )
        self.assertEqual(
            Decimal((await self._source_costs())[0]["total_cost"]),
            Decimal("21"),
        )
        replay = await warehouse_inbound(
            payload=payload, db=self.db, current_admin=self.actor,
        )
        self.assertEqual(replay, response)
        self.assertEqual(await self._count("inventory_cost_events"), 1)

    async def test_fifo_rollback_after_cost_events_and_before_commit_then_retry(self):
        await self._assert_atomic_failure_before_commit("FIFO")

    async def test_average_rollback_after_cost_events_and_before_commit_then_retry(self):
        await self._assert_atomic_failure_before_commit("MOVING_AVERAGE")


if __name__ == "__main__":
    unittest.main()
