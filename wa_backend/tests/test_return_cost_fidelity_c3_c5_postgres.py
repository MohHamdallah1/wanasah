"""Committed V1 customer-return cost fidelity and reconciliation proof.

Runs only on a disposable PostgreSQL 16 database. All business operations use
canonical supplier inbound and FIELD visit handlers; no inventory/cost tables
are seeded directly. Each CI matrix job owns one costing method and destroys
its database with the runner.
"""
from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import test_costed_driver_customer_return_c2_db as customer_fixture
import test_costed_driver_sale_correction_real_c2_db as sale_fixture
from api.driver import update_visit
from api.warehouse import live_stock
from api.warehouse.inbound import warehouse_inbound
from context import tenant_context
from database import engine
from models import Driver, ProductBatch
from schemas import UpgradedInboundRequest, VisitUpdateRequest
from tests.canonical_actor_fixtures import load_company_owner_fixture, seed_field_fixture
from tests.supplier_fixtures import seed_receipt_supplier


D = Decimal


@unittest.skipUnless(
    os.environ.get("WANASAH_RETURN_COST_FIDELITY_PG_GATE") == "1",
    "Disposable committed PostgreSQL 16 return-cost gate only",
)
class ReturnCostFidelityCommittedPostgresTests(unittest.IsolatedAsyncioTestCase):
    _create_business_fixture = (
        customer_fixture.RealCustomerReturnC2DatabaseTests._create_business_fixture
    )
    _create_real_commercial_context = (
        sale_fixture.RealDriverSaleCorrectionC2DatabaseTests._create_real_commercial_context
    )

    async def asyncSetUp(self):
        self.method = os.environ["WANASAH_RETURN_COST_FIDELITY_METHOD"]
        self.assertIn(self.method, {"FIFO", "MOVING_AVERAGE"})
        self.tenant = int(os.environ["WANASAH_C2_REAL_SALE_TEST_TENANT"])
        self.token = tenant_context.set(self.tenant)
        self.conn = await engine.connect()
        self.db = AsyncSession(bind=self.conn, expire_on_commit=False)
        await self.db.execute(
            text("SELECT set_config('app.current_tenant',:t,false)"),
            {"t": str(self.tenant)},
        )
        identity = (
            await self.db.execute(
                text("SELECT current_database(),current_user,"
                     "current_setting('app.current_tenant',true)")
            )
        ).one()
        self.assertEqual(
            tuple(identity),
            ("wanasah_field_contracts", "return_cost_runtime", str(self.tenant)),
        )
        for table in (
            "inventory_cost_policies",
            "inventory_cost_events",
            "inventory_movements",
            "inventory_balances",
            "work_sessions",
            "dispatch_routes",
            "visits",
            "shops",
            "vehicles",
        ):
            self.assertEqual(
                await self.db.scalar(
                    text("SELECT count(*) FROM " + table + " WHERE company_id=:t"),
                    {"t": self.tenant},
                ),
                0,
                table,
            )
        self.owner = await load_company_owner_fixture(self.db, self.tenant)
        self.actor = self.owner.operational_driver
        self.field = await seed_field_fixture(self.db, self.tenant)
        self.field_driver_id = int(self.field.driver.id)
        self.field_context = self.field.context
        self.supplier_id = await seed_receipt_supplier(self.db, self.actor)
        self.warehouse_id = await self.db.scalar(
            text(
                "SELECT id FROM inventory_locations WHERE company_id=:t "
                "AND location_type='WAREHOUSE' AND is_active=true LIMIT 1"
            ),
            {"t": self.tenant},
        )
        self.variant = (
            await self.db.execute(
                text(
                    "SELECT id,base_uom_id,packs_per_carton "
                    "FROM product_variants WHERE company_id=:t "
                    "AND lifecycle_status='ACTIVE' AND operational_hold='NONE' "
                    "AND expiry_control_mode='REQUIRED' LIMIT 1"
                ),
                {"t": self.tenant},
            )
        ).mappings().one()
        self.assertIsNotNone(self.warehouse_id)

    async def asyncTearDown(self):
        try:
            await self.db.close()
            await self.conn.close()
        finally:
            tenant_context.reset(self.token)
            await engine.dispose()

    async def _new_session(self):
        conn = await engine.connect()
        db = AsyncSession(bind=conn, expire_on_commit=False)
        await db.execute(
            text("SELECT set_config('app.current_tenant',:t,false)"),
            {"t": str(self.tenant)},
        )
        return conn, db

    async def _state(self, db):
        row = (
            await db.execute(
                text(
                    "SELECT quantity,inventory_value,average_unit_cost "
                    "FROM inventory_cost_states WHERE company_id=:t "
                    "AND product_variant_id=:p"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().one()
        return tuple(D(row[key]) for key in (
            "quantity", "inventory_value", "average_unit_cost"
        ))

    async def _purchase_history(self, db):
        return (
            await db.execute(
                text(
                    "SELECT id,batch_id,quantity,input_quantity,input_unit_cost,"
                    "input_uom_id,total_cost,created_at "
                    "FROM inventory_cost_events WHERE company_id=:t "
                    "AND product_variant_id=:p AND event_type='PURCHASE_IN' "
                    "ORDER BY id"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().all()

    async def test_committed_sale_correction_linked_return_cost_fidelity(self):
        # Independent expectations are frozen BEFORE any cost-bearing mutation.
        purchase_qty = D("300")
        purchase_value = D("800.000000")
        expected_average = D("2.666667")
        sale_qty = D("4")
        sale_cogs = D("8.000000") if self.method == "FIFO" else D("10.666668")
        after_sale_value = purchase_value - sale_cogs
        return_qty = D("2")
        exchange_cost = D("4.000000") if self.method == "FIFO" else D("5.333334")
        corrected_value = D("800.000000")

        # Genuine first supplier receipt + route/vehicle load. The helper is the
        # accepted C2 business setup, but this test uses a normal committing
        # session rather than its historical outer-rollback harness.
        visit_id, vehicle_id, batch_id = await self._create_business_fixture(
            self.method,
            commercial_context_factory=self._create_real_commercial_context,
        )

        # Second genuine receipt deliberately reuses the SAME manufacturer lot
        # at a different actual cost. Physical Batch identity therefore cannot
        # be used as financial FIFO layer identity.
        batch = await self.db.scalar(
            select(ProductBatch).where(
                ProductBatch.company_id == self.tenant,
                ProductBatch.id == batch_id,
            )
        )
        self.assertIsNotNone(batch)
        second_id = uuid4()
        second = UpgradedInboundRequest(
            supplier_id=self.supplier_id,
            request_id=second_id,
            location_id=self.warehouse_id,
            reference_id="RET-COST-SECOND-" + second_id.hex[:12],
            items=[{
                "product_variant_id": self.variant["id"],
                "quantity": "100",
                "uom_id": self.variant["base_uom_id"],
                "unit_cost": "4",
                "batch_number": batch.batch_number,
                "production_date": batch.production_date,
                "expiry_date": batch.expiry_date,
            }],
        )
        self.assertEqual(
            await warehouse_inbound(
                payload=second,
                db=self.db,
                access=self.owner.access(self.db),
                legacy_actor=self.actor,
            ),
            {"message": "INBOUND_POSTED"},
        )

        purchases_before = await self._purchase_history(self.db)
        self.assertEqual(len(purchases_before), 2)
        self.assertEqual(
            [
                (
                    int(row["batch_id"]),
                    D(row["quantity"]),
                    D(row["input_unit_cost"]),
                    D(row["total_cost"]),
                )
                for row in purchases_before
            ],
            [
                (batch_id, D("200"), D("2"), D("400")),
                (batch_id, D("100"), D("4"), D("400")),
            ],
        )
        self.assertEqual(
            await self._state(self.db),
            (purchase_qty, purchase_value, expected_average),
        )

        sale_request = VisitUpdateRequest(
            request_id=uuid4(),
            outcome="Sale",
            cart_items=[{
                "product_variant_id": self.variant["id"],
                "quantity": 0,
                "packs_quantity": int(sale_qty),
            }],
            returns=[],
            cash_collected="20.000",
        )
        sale_response = await update_visit(
            visit_id=visit_id,
            payload=sale_request,
            db=self.db,
            field_context=self.field_context,
            legacy_actor=self.field.driver,
        )
        self.assertEqual(sale_response["message"], "Visit updated successfully")
        self.assertEqual(
            await self._state(self.db),
            (D("296"), after_sale_value, (after_sale_value / D("296")).quantize(D("0.000001"))),
        )

        sale_event = (
            await self.db.execute(
                text(
                    "SELECT e.id,e.total_cost,e.cost_basis FROM inventory_cost_events e "
                    "JOIN inventory_movements m ON m.company_id=e.company_id "
                    "AND m.id=e.inventory_movement_id "
                    "WHERE e.company_id=:t AND m.reference_id=:v "
                    "AND m.reference_type='VISIT_ITEM_OUT'"
                ),
                {"t": self.tenant, "v": str(visit_id)},
            )
        ).mappings().one()
        self.assertEqual(D(sale_event["total_cost"]), sale_cogs)
        self.assertEqual(
            sale_event["cost_basis"],
            "FIFO_LAYER" if self.method == "FIFO" else "MOVING_AVERAGE",
        )

        # Force a genuine correction failure AFTER the old visit has been
        # reversed and a replacement sale movement has been attempted. The
        # handler rejects excessive cash late and must roll the whole mutation
        # back, preserving the original completed sale and COGS.
        before_failed_counts = (
            await self.db.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM inventory_movements WHERE company_id=:t) m,"
                    "(SELECT count(*) FROM inventory_cost_events WHERE company_id=:t) e"
                ),
                {"t": self.tenant},
            )
        ).one()
        bad_correction = VisitUpdateRequest(
            request_id=uuid4(),
            outcome="Sale",
            cart_items=[{
                "product_variant_id": self.variant["id"],
                "quantity": 0,
                "packs_quantity": 1,
            }],
            returns=[],
            cash_collected="999.000",
        )
        with self.assertRaises(HTTPException) as rejected:
            await update_visit(
                visit_id=visit_id,
                payload=bad_correction,
                db=self.db,
                field_context=self.field_context,
                legacy_actor=self.field.driver,
            )
        self.assertEqual(rejected.exception.status_code, 400)

        verify_conn, verify = await self._new_session()
        try:
            self.assertEqual(
                await self._state(verify),
                (D("296"), after_sale_value, (after_sale_value / D("296")).quantize(D("0.000001"))),
            )
            after_failed_counts = (
                await verify.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM inventory_movements WHERE company_id=:t) m,"
                        "(SELECT count(*) FROM inventory_cost_events WHERE company_id=:t) e"
                    ),
                    {"t": self.tenant},
                )
            ).one()
            self.assertEqual(tuple(after_failed_counts), tuple(before_failed_counts))
            persisted_visit = (
                await verify.execute(
                    text(
                        "SELECT status,outcome,final_amount_due FROM visits "
                        "WHERE company_id=:t AND id=:v"
                    ),
                    {"t": self.tenant, "v": visit_id},
                )
            ).one()
            self.assertEqual(
                (persisted_visit.status, persisted_visit.outcome, D(persisted_visit.final_amount_due)),
                ("Completed", "Sale", D("20.000")),
            )
        finally:
            await verify.close()
            await verify_conn.close()

        # Same legitimate correction is then submitted concurrently through two
        # independent restricted-runtime sessions. Canonical visit/idempotency
        # locks must serialize to one physical+financial result.
        correction_id = uuid4()
        correction = VisitUpdateRequest(
            request_id=correction_id,
            outcome="NoSale",
            notes="Committed damaged exchange with authoritative cost provenance",
            cart_items=[],
            cash_collected="0.000",
            returns=[{
                "product_variant_id": self.variant["id"],
                "batch_id": batch_id,
                "quantity": 0,
                "packs_quantity": int(return_qty),
                "return_type": "Damaged",
                "reason": "Committed return cost fidelity",
            }],
        )

        async def submit_correction():
            conn, db = await self._new_session()
            try:
                actor = await db.get(Driver, self.field_driver_id)
                self.assertIsNotNone(actor)
                return await update_visit(
                    visit_id=visit_id,
                    payload=correction,
                    db=db,
                    field_context=self.field_context,
                    legacy_actor=actor,
                )
            finally:
                await db.close()
                await conn.close()

        results = await asyncio.wait_for(
            asyncio.gather(submit_correction(), submit_correction()),
            timeout=30,
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["message"], "Visit updated successfully")

        committed_conn, committed = await self._new_session()
        try:
            self.assertEqual(
                await self._state(committed),
                (purchase_qty, corrected_value, expected_average),
            )
            exchange_and_return = (
                await committed.execute(
                    text(
                        "SELECT m.id movement_id,m.reference_type,e.id event_id,"
                        "e.event_type,e.cost_basis,e.total_cost,e.source_cost_event_id "
                        "FROM inventory_movements m "
                        "JOIN inventory_cost_events e ON e.company_id=m.company_id "
                        "AND e.inventory_movement_id=m.id "
                        "WHERE m.company_id=:t AND m.reference_id=:v "
                        "AND m.reference_type IN ('VISIT_EXCHANGE_OUT','VISIT_RETURN_IN') "
                        "ORDER BY m.id"
                    ),
                    {"t": self.tenant, "v": str(visit_id)},
                )
            ).mappings().all()
            self.assertEqual(len(exchange_and_return), 2)
            by_type = {row["reference_type"]: row for row in exchange_and_return}
            exchange = by_type["VISIT_EXCHANGE_OUT"]
            returned = by_type["VISIT_RETURN_IN"]
            self.assertEqual(D(exchange["total_cost"]), exchange_cost)
            self.assertEqual(D(returned["total_cost"]), exchange_cost)
            self.assertEqual(returned["event_type"], "ADJUSTMENT_IN")
            self.assertEqual(returned["cost_basis"], "LINKED_RETURN_COST")
            self.assertEqual(
                int(returned["source_cost_event_id"]),
                int(exchange["event_id"]),
            )

            if self.method == "FIFO":
                allocations = (
                    await committed.execute(
                        text(
                            "SELECT cost_event_id,cost_layer_id,allocation_type,quantity,amount "
                            "FROM inventory_cost_allocations WHERE company_id=:t "
                            "AND cost_event_id IN (:exchange,:returned) "
                            "ORDER BY cost_event_id,id"
                        ),
                        {
                            "t": self.tenant,
                            "exchange": int(exchange["event_id"]),
                            "returned": int(returned["event_id"]),
                        },
                    )
                ).mappings().all()
                consumed = [
                    (int(row["cost_layer_id"]), D(row["quantity"]), D(row["amount"]))
                    for row in allocations
                    if int(row["cost_event_id"]) == int(exchange["event_id"])
                    and row["allocation_type"] == "CONSUME"
                ]
                restored = [
                    (int(row["cost_layer_id"]), D(row["quantity"]), D(row["amount"]))
                    for row in allocations
                    if int(row["cost_event_id"]) == int(returned["event_id"])
                    and row["allocation_type"] == "RESTORE"
                ]
                self.assertEqual(restored, consumed)
                self.assertEqual(
                    sum((row[1] for row in restored), D("0")),
                    return_qty,
                )
                self.assertEqual(
                    sum((row[2] for row in restored), D("0")),
                    exchange_cost,
                )
            else:
                self.assertEqual(
                    await committed.scalar(
                        text(
                            "SELECT count(*) FROM inventory_cost_allocations "
                            "WHERE company_id=:t AND cost_event_id IN (:exchange,:returned)"
                        ),
                        {
                            "t": self.tenant,
                            "exchange": int(exchange["event_id"]),
                            "returned": int(returned["event_id"]),
                        },
                    ),
                    0,
                )

            physical = (
                await committed.execute(
                    text(
                        "SELECT stock_status,on_hand_quantity FROM inventory_balances "
                        "WHERE company_id=:t AND location_id=:loc "
                        "AND product_variant_id=:p AND batch_id=:b "
                        "AND on_hand_quantity<>0 ORDER BY stock_status"
                    ),
                    {
                        "t": self.tenant,
                        "loc": vehicle_id,
                        "p": self.variant["id"],
                        "b": batch_id,
                    },
                )
            ).all()
            self.assertEqual(
                {row.stock_status: D(row.on_hand_quantity) for row in physical},
                {"AVAILABLE": D("148"), "DAMAGED": D("2")},
            )

            purchases_after = await self._purchase_history(committed)
            self.assertEqual(
                [tuple(row.values()) for row in purchases_after],
                [tuple(row.values()) for row in purchases_before],
            )
            self.assertEqual(D(purchases_after[-1]["input_unit_cost"]), D("4"))

            # One narrow Live Stock read verifies presentation costs still come
            # from the same purchase/state authority; this is not a new R1/#668
            # read-consistency journey.
            page = await live_stock.get_warehouse_inventory(
                location_id=int(self.warehouse_id),
                cursor=None,
                limit=50,
                search=None,
                only_alerts=False,
                stock_state="all",
                family_id=None,
                has_reserved=False,
                has_unavailable=False,
                has_damaged=False,
                has_recalled=False,
                has_vehicle=False,
                minimum_unset=False,
                sort="name_asc",
                db=committed,
                access=self.owner.access(committed),
            )
            item = next(
                row for row in page["items"]
                if int(row["id"]) == int(self.variant["id"])
            )
            self.assertEqual(D(item["last_purchase_cost"]), D("4"))
            factor = D(item["display_factor_to_base"])
            self.assertEqual(
                D(item["average_cost_display"]),
                (expected_average * factor).quantize(D("0.000001")),
            )
        finally:
            await committed.close()
            await committed_conn.close()

        # Exact replay was already concurrent. Reusing the SAME request id with
        # a changed body must fail and cannot append another return.
        conflict = VisitUpdateRequest(
            request_id=correction_id,
            outcome="NoSale",
            notes="Changed duplicate body",
            cart_items=[],
            cash_collected="0.000",
            returns=[{
                "product_variant_id": self.variant["id"],
                "batch_id": batch_id,
                "quantity": 0,
                "packs_quantity": int(return_qty),
                "return_type": "Damaged",
                "reason": "Changed duplicate body",
            }],
        )
        conflict_conn, conflict_db = await self._new_session()
        try:
            actor = await conflict_db.get(Driver, self.field_driver_id)
            with self.assertRaises(HTTPException) as duplicate:
                await update_visit(
                    visit_id=visit_id,
                    payload=conflict,
                    db=conflict_db,
                    field_context=self.field_context,
                    legacy_actor=actor,
                )
            self.assertEqual(duplicate.exception.status_code, 409)
        finally:
            await conflict_db.close()
            await conflict_conn.close()

        final_conn, final = await self._new_session()
        try:
            self.assertEqual(
                await final.scalar(
                    text(
                        "SELECT count(*) FROM inventory_movements "
                        "WHERE company_id=:t AND reference_id=:v "
                        "AND reference_type='VISIT_RETURN_IN'"
                    ),
                    {"t": self.tenant, "v": str(visit_id)},
                ),
                1,
            )
            self.assertEqual(
                await final.scalar(
                    text(
                        "SELECT count(*) FROM visit_returns "
                        "WHERE company_id=:t AND visit_id=:v AND is_cancelled=false"
                    ),
                    {"t": self.tenant, "v": visit_id},
                ),
                1,
            )
            self.assertEqual(await self._state(final), (
                purchase_qty, corrected_value, expected_average
            ))
            self.assertEqual(
                await final.scalar(
                    text(
                        "SELECT count(*) FROM inventory_cost_events "
                        "WHERE company_id=:t AND product_variant_id=:p "
                        "AND event_type='PURCHASE_IN'"
                    ),
                    {"t": self.tenant, "p": self.variant["id"]},
                ),
                2,
            )
        finally:
            await final.close()
            await final_conn.close()

        print(
            "RETURN_COST_FIDELITY_COMMITTED=PASS",
            self.method,
            "purchase=300/800",
            f"sale_cogs={sale_cogs}",
            f"exchange={exchange_cost}",
            f"return={exchange_cost}",
            "corrected=300/800",
            "same_batch_two_receipts=true",
            "concurrent_replay=true",
            "post_mutation_rollback=true",
        )


if __name__ == "__main__":
    unittest.main()
