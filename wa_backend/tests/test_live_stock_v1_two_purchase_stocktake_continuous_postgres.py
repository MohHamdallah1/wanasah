"""One continuous two-purchase -> FIELD sale -> correction -> stocktake journey.

The commercial fixture is reused from the already-accepted C2 foundation, but
this test is a new continuous history: both purchase rows, the FIELD sale, the
authorized visit correction/return, and the independent stocktake all belong to
one company/product/batch history before final valuation is reconciled.
"""
from __future__ import annotations

import os
import unittest
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, text

import test_costed_driver_customer_return_c2_db as customer_fixture
from api.driver import update_visit
from api.warehouse import stocktake
from domains.authorization.capabilities import PERMISSIONS
from domains.stocktake.contracts import (
    StocktakeApprovalCommand,
    StocktakeCountCommand,
    StocktakeRecountCommand,
    StocktakeStartCommand,
)
from models import (
    Driver,
    Permission,
    Role,
    UserLocationAccess,
    role_permissions,
)
from schemas import VisitUpdateRequest
from tests.canonical_actor_fixtures import seed_ordinary_backoffice_fixture
from tests import test_costed_driver_sale_correction_real_c2_db as sale_correction_fixture


@unittest.skipUnless(
    os.environ.get("WANASAH_REMAINING_ACCOUNTING_PG_GATE") == "1",
    "Explicit disposable PostgreSQL 16 remaining-accounting gate only",
)
class ContinuousTwoPurchaseSaleReturnStocktakeTests(
    sale_correction_fixture.RealDriverSaleCorrectionC2DatabaseTests
):
    # Reuse accepted setup/helpers, but do not re-collect #664's two inherited
    # acceptance cases. This wave owns only the two continuous-history tests.
    test_fifo_real_priced_sale_and_authorized_return_correction = None
    test_average_real_priced_sale_and_authorized_return_correction = None

    async def _seed_stocktake_actors(self):
        """Identity/capability fixture only; no inventory/cost/ledger writes."""
        password = "RemainingConsistencyCount123"
        counter = await seed_ordinary_backoffice_fixture(
            self.db, self.tenant, password=password
        )
        recounter = await seed_ordinary_backoffice_fixture(
            self.db, self.tenant, password=password
        )
        needed = {
            "inventory.read",
            "stocktake.read",
            "stocktake.start",
            "stocktake.count",
            "stocktake.review",
            "stocktake.recount",
        }
        self.assertTrue(needed <= PERMISSIONS)
        existing = set(
            (
                await self.db.scalars(
                    select(Permission.code).where(Permission.code.in_(needed))
                )
            ).all()
        )
        self.db.add_all(
            [Permission(code=code) for code in sorted(needed - existing)]
        )
        await self.db.flush()
        permission_ids = list(
            (
                await self.db.scalars(
                    select(Permission.id).where(Permission.code.in_(needed))
                )
            ).all()
        )
        for actor in (counter, recounter):
            role = Role(
                company_id=self.tenant,
                name="Remaining stocktake " + uuid4().hex,
            )
            self.db.add(role)
            await self.db.flush()
            await self.db.execute(
                role_permissions.insert(),
                [
                    {
                        "company_id": self.tenant,
                        "role_id": role.id,
                        "permission_id": permission_id,
                    }
                    for permission_id in permission_ids
                ],
            )
            self.db.add(
                UserLocationAccess(
                    company_id=self.tenant,
                    driver_id=actor.driver_id,
                    location_id=self.warehouse_id,
                    role_id=role.id,
                )
            )
        await self.db.commit()
        recounter_username = await self.db.scalar(
            select(Driver.username).where(
                Driver.company_id == self.tenant,
                Driver.id == recounter.driver_id,
            )
        )
        self.assertIsNotNone(recounter_username)
        return counter, recounter, str(recounter_username), password

    async def _assert_continuous_history(self, method: str):
        # ALL Decimal/business expectations are fixed before any purchase, load,
        # sale, correction, return or stocktake mutation is executed.
        purchase_1_quantity = Decimal("200")
        purchase_1_unit_cost = Decimal("2")
        purchase_1_value = Decimal("400")
        purchase_2_quantity = Decimal("100")
        purchase_2_unit_cost = Decimal("4")
        purchase_2_value = Decimal("400")
        expected_purchase_quantity = Decimal("300")
        expected_purchase_value = Decimal("800")
        expected_initial_average = Decimal("2.666667")

        expected_vehicle_after_load = Decimal("150")
        expected_warehouse_first_after_load = Decimal("50")
        expected_warehouse_second_after_load = Decimal("100")

        expected_sale_quantity = Decimal("4")
        expected_sale_cogs = (
            Decimal("8.000000")
            if method == "FIFO"
            else Decimal("10.666668")
        )
        expected_after_sale_quantity = Decimal("296")
        expected_after_sale_value = expected_purchase_value - expected_sale_cogs

        expected_return_quantity = Decimal("2")
        expected_exchange_cost = (
            Decimal("4.000000")
            if method == "FIFO"
            else Decimal("5.333334")
        )
        # Current V1 financial contract: VISIT_RETURN_IN is an external increase
        # without authoritative source-cost linkage, so it is valued at the
        # current average estimate. Under FIFO this deliberately differs from
        # the FIFO-layer cost of the 1:1 replacement outbound. Source-cost
        # fidelity for returns remains an explicitly open architecture gate.
        expected_return_cost = (
            Decimal("5.342282")
            if method == "FIFO"
            else Decimal("5.333334")
        )
        expected_after_correction_quantity = Decimal("300")
        expected_after_correction_value = (
            Decimal("801.342282")
            if method == "FIFO"
            else Decimal("800.000000")
        )
        expected_vehicle_available_after_correction = Decimal("148")
        expected_vehicle_damaged_after_correction = Decimal("2")

        expected_stocktake_actual = Decimal("40")
        expected_stocktake_shortage = Decimal("10")
        expected_stocktake_cost = (
            Decimal("20.000000")
            if method == "FIFO"
            else Decimal("26.666670")
        )
        expected_final_quantity = Decimal("290")
        expected_final_value = (
            Decimal("781.342282")
            if method == "FIFO"
            else Decimal("773.333330")
        )
        expected_final_average = (
            Decimal("2.694284")
            if method == "FIFO"
            else Decimal("2.666667")
        )
        expected_final_movement_count = 8
        expected_final_cost_event_count = 7

        visit_id, vehicle_location_id, first_batch_id = (
            await customer_fixture.RealCustomerReturnC2DatabaseTests
            ._create_business_fixture(
                self,
                method,
                commercial_context_factory=self._create_real_commercial_context,
                second_purchase_price="4",
            )
        )

        purchase_history_before = (
            await self.db.execute(
                text(
                    "SELECT id,batch_id,quantity,input_quantity,input_unit_cost,"
                    "input_uom_id,total_cost,created_at "
                    "FROM inventory_cost_events "
                    "WHERE company_id=:t AND product_variant_id=:p "
                    "AND event_type='PURCHASE_IN' ORDER BY id"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().all()
        self.assertEqual(len(purchase_history_before), 2)
        self.assertEqual(
            [
                (
                    Decimal(row["quantity"]),
                    Decimal(row["input_unit_cost"]),
                    Decimal(row["total_cost"]),
                )
                for row in purchase_history_before
            ],
            [
                (purchase_1_quantity, purchase_1_unit_cost, purchase_1_value),
                (purchase_2_quantity, purchase_2_unit_cost, purchase_2_value),
            ],
        )
        second_batch_id = int(purchase_history_before[1]["batch_id"])

        before_sale_state = (
            await self.db.execute(
                text(
                    "SELECT quantity,inventory_value,average_unit_cost "
                    "FROM inventory_cost_states "
                    "WHERE company_id=:t AND product_variant_id=:p"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().one()
        self.assertEqual(
            (
                Decimal(before_sale_state["quantity"]),
                Decimal(before_sale_state["inventory_value"]),
                Decimal(before_sale_state["average_unit_cost"]),
            ),
            (
                expected_purchase_quantity,
                expected_purchase_value,
                expected_initial_average,
            ),
        )

        physical_before_sale = (
            await self.db.execute(
                text(
                    "SELECT location_id,batch_id,stock_status,on_hand_quantity "
                    "FROM inventory_balances WHERE company_id=:t "
                    "AND product_variant_id=:p AND on_hand_quantity<>0"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().all()
        physical_map = {
            (int(row["location_id"]), int(row["batch_id"]), row["stock_status"]):
                Decimal(row["on_hand_quantity"])
            for row in physical_before_sale
        }
        self.assertEqual(
            physical_map[
                (int(self.warehouse_id), int(first_batch_id), "AVAILABLE")
            ],
            expected_warehouse_first_after_load,
        )
        self.assertEqual(
            physical_map[
                (int(self.warehouse_id), second_batch_id, "AVAILABLE")
            ],
            expected_warehouse_second_after_load,
        )
        self.assertEqual(
            physical_map[
                (int(vehicle_location_id), int(first_batch_id), "AVAILABLE")
            ],
            expected_vehicle_after_load,
        )

        # Canonical FIELD sale on the exact active visit.
        sale = VisitUpdateRequest(
            request_id=uuid4(),
            outcome="Sale",
            cart_items=[{
                "product_variant_id": self.variant["id"],
                "quantity": 0,
                "packs_quantity": int(expected_sale_quantity),
            }],
            returns=[],
            cash_collected="20.000",
        )
        sold = await update_visit(
            visit_id=visit_id,
            payload=sale,
            db=self.db,
            field_context=self.field.context,
            legacy_actor=self.field.driver,
        )
        self.assertEqual(sold["message"], "Visit updated successfully")

        sale_cost = (
            await self.db.execute(
                text(
                    "SELECT e.event_type,e.total_cost,e.method,e.cost_basis "
                    "FROM inventory_cost_events e "
                    "JOIN inventory_movements m "
                    "ON m.company_id=e.company_id "
                    "AND m.id=e.inventory_movement_id "
                    "WHERE e.company_id=:t AND m.reference_id=:v "
                    "AND m.reference_type='VISIT_ITEM_OUT'"
                ),
                {"t": self.tenant, "v": str(visit_id)},
            )
        ).mappings().one()
        self.assertEqual(sale_cost["event_type"], "OUTBOUND")
        self.assertEqual(Decimal(sale_cost["total_cost"]), expected_sale_cogs)
        self.assertEqual(sale_cost["method"], method)
        self.assertEqual(
            sale_cost["cost_basis"],
            "FIFO_LAYER" if method == "FIFO" else "MOVING_AVERAGE",
        )
        after_sale_state = (
            await self.db.execute(
                text(
                    "SELECT quantity,inventory_value FROM inventory_cost_states "
                    "WHERE company_id=:t AND product_variant_id=:p"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().one()
        self.assertEqual(
            (
                Decimal(after_sale_state["quantity"]),
                Decimal(after_sale_state["inventory_value"]),
            ),
            (expected_after_sale_quantity, expected_after_sale_value),
        )

        # Authorized correction of that SAME visit: exact reversal of sale cost
        # plus a 1:1 damaged customer return/exchange for two base units.
        correction = VisitUpdateRequest(
            request_id=uuid4(),
            outcome="NoSale",
            notes="Continuous accounting correction and damaged return",
            cart_items=[],
            cash_collected="0.000",
            returns=[{
                "product_variant_id": self.variant["id"],
                "batch_id": int(first_batch_id),
                "quantity": 0,
                "packs_quantity": int(expected_return_quantity),
                "return_type": "Damaged",
                "reason": "Continuous accounting damaged return",
            }],
        )
        corrected = await update_visit(
            visit_id=visit_id,
            payload=correction,
            db=self.db,
            field_context=self.field.context,
            legacy_actor=self.field.driver,
        )
        self.assertEqual(corrected["message"], "Visit updated successfully")

        exchange_cost_rows = (
            await self.db.execute(
                text(
                    "SELECT m.reference_type,e.event_type,e.cost_basis,e.total_cost "
                    "FROM inventory_movements m "
                    "JOIN inventory_cost_events e "
                    "ON e.company_id=m.company_id "
                    "AND e.inventory_movement_id=m.id "
                    "WHERE m.company_id=:t AND m.reference_id=:v "
                    "AND m.reference_type IN ('VISIT_EXCHANGE_OUT','VISIT_RETURN_IN') "
                    "ORDER BY m.id"
                ),
                {"t": self.tenant, "v": str(visit_id)},
            )
        ).mappings().all()
        self.assertEqual(len(exchange_cost_rows), 2)
        by_reference = {
            row["reference_type"]: row for row in exchange_cost_rows
        }
        self.assertEqual(
            Decimal(by_reference["VISIT_EXCHANGE_OUT"]["total_cost"]),
            expected_exchange_cost,
        )
        self.assertEqual(
            Decimal(by_reference["VISIT_RETURN_IN"]["total_cost"]),
            expected_return_cost,
        )
        self.assertEqual(
            by_reference["VISIT_RETURN_IN"]["cost_basis"],
            "CURRENT_AVERAGE_ESTIMATE",
        )

        after_correction_state = (
            await self.db.execute(
                text(
                    "SELECT quantity,inventory_value,average_unit_cost "
                    "FROM inventory_cost_states "
                    "WHERE company_id=:t AND product_variant_id=:p"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().one()
        self.assertEqual(
            (
                Decimal(after_correction_state["quantity"]),
                Decimal(after_correction_state["inventory_value"]),
            ),
            (
                expected_after_correction_quantity,
                expected_after_correction_value,
            ),
        )
        vehicle_rows = (
            await self.db.execute(
                text(
                    "SELECT stock_status,on_hand_quantity "
                    "FROM inventory_balances WHERE company_id=:t "
                    "AND location_id=:loc AND product_variant_id=:p "
                    "AND batch_id=:b AND on_hand_quantity<>0"
                ),
                {
                    "t": self.tenant,
                    "loc": vehicle_location_id,
                    "p": self.variant["id"],
                    "b": first_batch_id,
                },
            )
        ).mappings().all()
        self.assertEqual(
            {
                row["stock_status"]: Decimal(row["on_hand_quantity"])
                for row in vehicle_rows
            },
            {
                "AVAILABLE": expected_vehicle_available_after_correction,
                "DAMAGED": expected_vehicle_damaged_after_correction,
            },
        )

        # Preserve acquisition evidence BEFORE the final count.
        purchase_history_after_correction = (
            await self.db.execute(
                text(
                    "SELECT id,batch_id,quantity,input_quantity,input_unit_cost,"
                    "input_uom_id,total_cost,created_at "
                    "FROM inventory_cost_events "
                    "WHERE company_id=:t AND product_variant_id=:p "
                    "AND event_type='PURCHASE_IN' ORDER BY id"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().all()
        self.assertEqual(
            [tuple(row.values()) for row in purchase_history_after_correction],
            [tuple(row.values()) for row in purchase_history_before],
        )

        # Independent count/recount/Owner approval on the SAME original batch.
        counter, recounter, recounter_username, counter_password = (
            await self._seed_stocktake_actors()
        )
        started = await stocktake.start_unified_stocktake(
            StocktakeStartCommand(
                request_id=uuid4(),
                location_id=int(self.warehouse_id),
                stocktake_type="CYCLE_COUNT",
                product_variant_id=int(self.variant["id"]),
                batch_id=int(first_batch_id),
            ),
            self.db,
            counter.access(self.db),
            counter.operational_driver,
        )
        stocktake_session_id = int(started["session_id"])

        count_command = StocktakeCountCommand(
            request_id=uuid4(),
            items=[{
                "product_variant_id": int(self.variant["id"]),
                "batch_id": int(first_batch_id),
                "stock_status": "AVAILABLE",
                "actual_quantity": expected_stocktake_actual,
                "uom_id": int(self.variant["base_uom_id"]),
            }],
        )
        first_count = await stocktake.submit_stocktake_count(
            stocktake_session_id,
            count_command,
            self.db,
            counter.access(self.db),
            counter.operational_driver,
        )
        self.assertTrue(first_count["requires_independent_recount"])
        first_attempt = int(first_count["attempt_id"])

        recount = await stocktake.recount_stocktake_session(
            stocktake_session_id,
            StocktakeRecountCommand(
                request_id=uuid4(),
                count_attempt_id=first_attempt,
                reason="Independent confirmation of predetermined ten-unit shortage",
                authorizer_username=recounter_username,
                authorizer_password=counter_password,
            ),
            self.db,
            counter.access(self.db),
            counter.operational_driver,
        )
        self.assertEqual(recount["status"], "RECOUNT_REQUIRED")
        self.assertTrue(recount["requires_independent_counter"])

        second_count = await stocktake.submit_stocktake_count(
            stocktake_session_id,
            count_command.model_copy(update={"request_id": uuid4()}),
            self.db,
            recounter.access(self.db),
            recounter.operational_driver,
        )
        second_attempt = int(second_count["attempt_id"])
        self.assertNotEqual(second_attempt, first_attempt)
        self.assertEqual(second_count["attempt_number"], 2)

        posted = await stocktake.approve_stocktake_session(
            stocktake_session_id,
            StocktakeApprovalCommand(
                request_id=uuid4(),
                count_attempt_id=second_attempt,
                password="FieldSyntheticFixture123",
            ),
            self.db,
            self.owner.access(self.db),
            self.actor,
        )
        self.assertEqual(posted["status"], "POSTED")
        self.assertEqual(posted["movement_count"], 1)

        final_state = (
            await self.db.execute(
                text(
                    "SELECT quantity,inventory_value,average_unit_cost "
                    "FROM inventory_cost_states "
                    "WHERE company_id=:t AND product_variant_id=:p"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().one()
        self.assertEqual(
            (
                Decimal(final_state["quantity"]),
                Decimal(final_state["inventory_value"]),
                Decimal(final_state["average_unit_cost"]),
            ),
            (
                expected_final_quantity,
                expected_final_value,
                expected_final_average,
            ),
        )

        stocktake_cost = (
            await self.db.execute(
                text(
                    "SELECT e.event_type,e.quantity,e.total_cost,e.quantity_before,"
                    "e.quantity_after,e.value_before,e.value_after "
                    "FROM inventory_cost_events e "
                    "JOIN inventory_movements m "
                    "ON m.company_id=e.company_id "
                    "AND m.id=e.inventory_movement_id "
                    "WHERE e.company_id=:t AND m.stocktake_session_id=:s"
                ),
                {"t": self.tenant, "s": stocktake_session_id},
            )
        ).mappings().one()
        self.assertEqual(stocktake_cost["event_type"], "OUTBOUND")
        self.assertEqual(
            (
                Decimal(stocktake_cost["quantity"]),
                Decimal(stocktake_cost["total_cost"]),
                Decimal(stocktake_cost["quantity_before"]),
                Decimal(stocktake_cost["quantity_after"]),
                Decimal(stocktake_cost["value_before"]),
                Decimal(stocktake_cost["value_after"]),
            ),
            (
                expected_stocktake_shortage,
                expected_stocktake_cost,
                expected_after_correction_quantity,
                expected_final_quantity,
                expected_after_correction_value,
                expected_final_value,
            ),
        )

        final_first_warehouse = await self.db.scalar(
            text(
                "SELECT on_hand_quantity FROM inventory_balances "
                "WHERE company_id=:t AND location_id=:loc "
                "AND product_variant_id=:p AND batch_id=:b "
                "AND stock_status='AVAILABLE'"
            ),
            {
                "t": self.tenant,
                "loc": self.warehouse_id,
                "p": self.variant["id"],
                "b": first_batch_id,
            },
        )
        self.assertEqual(
            Decimal(final_first_warehouse),
            expected_stocktake_actual,
        )
        self.assertEqual(
            await self.db.scalar(
                text(
                    "SELECT COUNT(*) FROM inventory_movements "
                    "WHERE company_id=:t AND product_variant_id=:p"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            ),
            expected_final_movement_count,
        )
        self.assertEqual(
            await self.db.scalar(
                text(
                    "SELECT COUNT(*) FROM inventory_cost_events "
                    "WHERE company_id=:t AND product_variant_id=:p"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            ),
            expected_final_cost_event_count,
        )

        purchase_history_final = (
            await self.db.execute(
                text(
                    "SELECT id,batch_id,quantity,input_quantity,input_unit_cost,"
                    "input_uom_id,total_cost,created_at "
                    "FROM inventory_cost_events "
                    "WHERE company_id=:t AND product_variant_id=:p "
                    "AND event_type='PURCHASE_IN' ORDER BY id"
                ),
                {"t": self.tenant, "p": self.variant["id"]},
            )
        ).mappings().all()
        self.assertEqual(
            [tuple(row.values()) for row in purchase_history_final],
            [tuple(row.values()) for row in purchase_history_before],
        )

        print(
            "REMAINING_CONTINUOUS_ACCOUNTING "
            f"method={method} quantity={expected_final_quantity} "
            f"value={expected_final_value} shortage_cost={expected_stocktake_cost}",
            flush=True,
        )

    async def test_fifo_two_purchase_sale_return_stocktake_one_history(self):
        await self._assert_continuous_history("FIFO")

    async def test_moving_average_two_purchase_sale_return_stocktake_one_history(self):
        await self._assert_continuous_history("MOVING_AVERAGE")


if __name__ == "__main__":
    unittest.main()
