"""End-to-end real driver Sale -> correction/return for each cost formula.

No calculator, pricing, FEFO, freeze, visit update, or inventory engine mocks.
Builds a minimal synthetic commercial environment (approved 0% tax,
published price entry/assignment, published rounding policy and locked route
context) in an external ROLLBACK-ONLY transaction on developer tenant 2.
The test helper reuses the real inbound/vehicle-load fixture. It exercises
POSTED SALE financial evidence and the same visit's authorized correction to
NoSale with a damaged 1:1 exchange; this is not a cash refund workflow.
"""
from __future__ import annotations

import os
import unittest
from tests.canonical_actor_fixtures import load_company_owner_fixture, seed_field_fixture
from tests.supplier_fixtures import seed_receipt_supplier
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from asyncpg import Range
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import test_costed_driver_customer_return_c2_db as customer_fixture
from api.driver import update_visit
from api.warehouse import live_stock
from context import tenant_context
from database import engine
from domains.pricing.context import lock_route_commercial_context
from domains.sales_calculation.policy import publish_commercial_rounding_policy
from domains.taxation.publishing import publish_version as publish_tax_version
from domains.taxation.models import (
    TaxJurisdiction, TaxRuleComponent, TaxRuleScope,
    TaxRuleSet, TaxRuleSetVersion,
)
from models import (
    DispatchRoute, Driver, PriceBook, PriceBookAssignment, PriceBookEntry,
    PricePublication, RouteCommercialContext, Shop, Visit, WorkSession,
)
from schemas import VisitUpdateRequest


@unittest.skipUnless(
    os.environ.get("WANASAH_C2_REAL_SALE_DB_GATE") == "1",
    "Explicit authorized empty synthetic developer tenant required",
)
class RealDriverSaleCorrectionC2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tenant = int(os.environ["WANASAH_C2_REAL_SALE_TEST_TENANT"])
        self.token = tenant_context.set(self.tenant)
        self.conn = await engine.connect()
        self.outer = await self.conn.begin()
        self.db = AsyncSession(
            bind=self.conn, expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        await self.db.execute(
            text("SELECT set_config('app.current_tenant',:t,true)"),
            {"t": str(self.tenant)},
        )
        self.assertEqual(
            await self.db.scalar(text("SELECT current_database()")),
            os.environ["WANASAH_C2_REAL_SALE_EXPECTED_DB"],
        )
        for table in (
            "shops", "vehicles", "route_commercial_contexts",
            "price_books", "price_book_assignments", "price_publications",
            "tax_rule_sets", "tax_jurisdictions",
            "inventory_cost_policies", "inventory_balances",
        ):
            self.assertEqual(
                await self.db.scalar(
                    text("SELECT count(*) FROM " + table + " WHERE company_id=:t"),
                    {"t": self.tenant},
                ), 0, table,
            )
        self.owner = await load_company_owner_fixture(self.db, self.tenant)
        self.actor = self.owner.operational_driver
        self.field = await seed_field_fixture(self.db, self.tenant)
        self.assertIsNotNone(self.actor)
        self.supplier_id = await seed_receipt_supplier(self.db, self.actor)
        self.warehouse_id = await self.db.scalar(
            text("SELECT id FROM inventory_locations WHERE company_id=:t "
                 "AND location_type='WAREHOUSE' AND is_active=true LIMIT 1"),
            {"t": self.tenant},
        )
        self.variant = (
            await self.db.execute(
                text(
                    "SELECT id,base_uom_id,packs_per_carton "
                    "FROM product_variants WHERE company_id=:t "
                    "AND lifecycle_status='ACTIVE' AND operational_hold='NONE' "
                    "AND expiry_control_mode='REQUIRED' LIMIT 1"
                ), {"t": self.tenant},
            )
        ).mappings().one()
        self.assertIsNotNone(self.warehouse_id)

    async def asyncTearDown(self):
        try:
            await self.db.close()
            if self.outer.is_active:
                await self.outer.rollback()
        finally:
            await self.conn.close()
            tenant_context.reset(self.token)
            await engine.dispose()

    async def _create_real_commercial_context(self, visit_id: int):
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(days=5)
        code = uuid4().hex[:10].upper()
        book = PriceBook(
            company_id=self.tenant, code="C2BOOK" + code,
            name="C2 real sale price book",
            currency_code="JOD", status="ACTIVE",
            created_by=self.actor.id,
        )
        self.db.add(book)
        await self.db.flush()
        publication = PricePublication(
            company_id=self.tenant, price_book_id=book.id,
            revision=1, status="PUBLISHED",
            effective_at=earlier, published_at=earlier,
            approved_at=earlier, approved_by=self.actor.id,
            created_by=self.actor.id, request_id=uuid4(),
        )
        self.db.add(publication)
        await self.db.flush()
        window = Range(lower=earlier, upper=None, lower_inc=True)
        self.db.add_all([
            PriceBookEntry(
                company_id=self.tenant, price_book_id=book.id,
                publication_id=publication.id,
                product_variant_id=self.variant["id"],
                uom_id=self.variant["base_uom_id"],
                amount=Decimal("5.000000"),
                effectivity=window, is_published=True,
                priority=0, entry_metadata={},
            ),
            PriceBookAssignment(
                company_id=self.tenant, price_book_id=book.id,
                scope_type="COMPANY_DEFAULT", scope_id=None,
                revision=1, priority=0, allow_offers=False,
                effectivity=window, created_by=self.actor.id,
            ),
        ])

        jurisdiction = TaxJurisdiction(
            company_id=self.tenant,
            code="C2JO" + code, name="C2 zero-rated jurisdiction",
            jurisdiction_type="COUNTRY", country_code="JO",
            created_by=self.actor.id, is_active=True,
        )
        rule = TaxRuleSet(
            company_id=self.tenant,
            code="C2TAX" + code, name="C2 verified zero-rate tax",
            created_by=self.actor.id,
        )
        self.db.add_all([jurisdiction, rule])
        await self.db.flush()
        tax_revision = TaxRuleSetVersion(
            company_id=self.tenant, tax_rule_set_id=rule.id,
            revision=1, definition_version=1,
            status="DRAFT", price_mode="EXCLUSIVE",
            priority=0, effective_from=earlier, effective_to=None,
            created_by=self.actor.id,
            request_id=uuid4(),
        )
        self.db.add(tax_revision)
        await self.db.flush()
        self.db.add_all([
            TaxRuleComponent(
                company_id=self.tenant,
                tax_rule_set_version_id=tax_revision.id,
                component_code="ZERO", name="Zero tax",
                sequence=1, rate=Decimal("0"),
                basis_mode="TAXABLE_BASE",
            ),
            TaxRuleScope(
                company_id=self.tenant,
                tax_rule_set_version_id=tax_revision.id,
                scope_type="JURISDICTION",
                jurisdiction_id=jurisdiction.id,
            ),
        ])
        await self.db.flush()
        # The deployed trigger forbids adding components to published rules.
        # Publish through the real business service after staging draft children.
        tax_revision = await publish_tax_version(
            self.db, company_id=self.tenant,
            actor_id=self.actor.id,
            version_id=tax_revision.id,
            expected_version=tax_revision.version,
        )
        self.assertEqual(tax_revision.status, "PUBLISHED")

        policy = await publish_commercial_rounding_policy(
            self.db, company_id=self.tenant, actor_id=self.actor.id,
            expected_revision=0, precision=3, mode="HALF_UP",
        )
        self.assertEqual(policy.rounding_policy.currency_code, "JOD")
        visit = await self.db.scalar(
            select(Visit).where(
                Visit.company_id == self.tenant, Visit.id == visit_id,
            )
        )
        shop = await self.db.scalar(
            select(Shop).where(
                Shop.company_id == self.tenant, Shop.id == visit.shop_id,
            )
        )
        shop.tax_jurisdiction_id = jurisdiction.id
        shop.max_debt_limit = Decimal("1000")
        route = await self.db.scalar(
            select(DispatchRoute).where(
                DispatchRoute.company_id == self.tenant,
                DispatchRoute.driver_id == self.field.driver.id,
            )
        )
        self.assertIsNotNone(route)
        locked = await lock_route_commercial_context(
            self.db,
            company_id=self.tenant,
            dispatch_route_id=route.id,
        )
        self.assertEqual(locked.price_publication_revision, 1)
        self.assertEqual(locked.tax_ruleset_version, 1)
        # The fixture creates the active WorkSession with the immutable
        # context ID at INSERT time, after this route lock has been created.
        await self.db.flush()
        return int(locked.id)

    async def _assert_sale_and_correction(self, method: str):
        visit_id, vehicle_id, batch_id = (
            await customer_fixture.RealCustomerReturnC2DatabaseTests._create_business_fixture(
                self, method,
                commercial_context_factory=self._create_real_commercial_context,
                second_purchase_price="4",
            )
        )
        # Independent accounting expectations are defined before the sale.
        # Two genuine supplier receipts are immutable acquisition evidence:
        # 200 x 2 + 100 x 4 = 300 base units valued at JOD 800.
        purchase_history_before = (
            await self.db.execute(text(
                "SELECT id,batch_id,quantity,input_quantity,input_unit_cost,"
                "input_uom_id,total_cost,created_at "
                "FROM inventory_cost_events WHERE company_id=:t "
                "AND product_variant_id=:p AND event_type='PURCHASE_IN' "
                "ORDER BY id"
            ), {"t": self.tenant, "p": self.variant["id"]})
        ).mappings().all()
        self.assertEqual(len(purchase_history_before), 2)
        self.assertEqual(
            [
                (
                    Decimal(row["quantity"]),
                    Decimal(row["input_quantity"]),
                    Decimal(row["input_unit_cost"]),
                    int(row["input_uom_id"]),
                    Decimal(row["total_cost"]),
                )
                for row in purchase_history_before
            ],
            [
                (Decimal("200"), Decimal("200"), Decimal("2"),
                 int(self.variant["base_uom_id"]), Decimal("400")),
                (Decimal("100"), Decimal("100"), Decimal("4"),
                 int(self.variant["base_uom_id"]), Decimal("400")),
            ],
        )
        expected_average = (Decimal("800") / Decimal("300")).quantize(
            Decimal("0.000001")
        )
        cost_state_before = (
            await self.db.execute(text(
                "SELECT quantity,inventory_value,average_unit_cost "
                "FROM inventory_cost_states WHERE company_id=:t "
                "AND product_variant_id=:p"
            ), {"t": self.tenant, "p": self.variant["id"]})
        ).mappings().one()
        self.assertEqual(
            (
                Decimal(cost_state_before["quantity"]),
                Decimal(cost_state_before["inventory_value"]),
                Decimal(cost_state_before["average_unit_cost"]),
            ),
            (Decimal("300"), Decimal("800"), expected_average),
        )

        base_uom_code = await self.db.scalar(
            text("SELECT code FROM uom WHERE id=:u"),
            {"u": int(self.variant["base_uom_id"])},
        )
        live_page = await live_stock.get_warehouse_inventory(
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
            db=self.db,
            access=self.owner.access(self.db),
        )
        live_row = next(
            row for row in live_page["items"]
            if row["id"] == self.variant["id"]
        )
        self.assertEqual(Decimal(live_row["last_purchase_cost"]), Decimal("4"))
        self.assertEqual(live_row["last_purchase_uom_code"], base_uom_code)
        self.assertEqual(Decimal(live_row["average_cost_display"]), expected_average)

        batch_page = await live_stock.get_warehouse_inventory_batches(
            self.variant["id"], int(self.warehouse_id), None, 100,
            self.db, self.owner.access(self.db),
        )
        purchase_by_batch = {
            int(row["batch_id"]): (
                Decimal(row["latest_purchase_cost"]),
                row["latest_purchase_uom_code"],
                int(row["purchase_event_count"]),
            )
            for row in batch_page["batches"]
        }
        self.assertEqual(
            purchase_by_batch[int(purchase_history_before[0]["batch_id"])],
            (Decimal("2"), base_uom_code, 1),
        )
        self.assertEqual(
            purchase_by_batch[int(purchase_history_before[1]["batch_id"])],
            (Decimal("4"), base_uom_code, 1),
        )

        # Route and work session already received one immutable context during
        # fixture construction. Do not publish the same commercial revision twice.
        sale_uuid = uuid4()
        sale = VisitUpdateRequest(
            request_id=sale_uuid, outcome="Sale",
            cart_items=[{
                "product_variant_id": self.variant["id"],
                "quantity": 0, "packs_quantity": 4,
            }],
            returns=[], cash_collected="20.000",
        )
        first = await update_visit(
            visit_id=visit_id, payload=sale, db=self.db,
            field_context=self.field.context, legacy_actor=self.field.driver,
        )
        self.assertEqual(first["message"], "Visit updated successfully")
        self.assertEqual(Decimal(first["new_balance"]), Decimal("0"))
        rows = (
            await self.db.execute(text(
                "SELECT e.event_type,e.total_cost,e.method,e.cost_basis "
                "FROM inventory_cost_events e "
                "JOIN inventory_movements m ON m.company_id=e.company_id "
                "AND m.id=e.inventory_movement_id "
                "WHERE e.company_id=:t AND m.reference_id=:v "
                "AND m.reference_type='VISIT_ITEM_OUT'"
            ), {"t":self.tenant,"v":str(visit_id)})
        ).mappings().all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["method"], method)
        expected_sale_cogs = (
            Decimal("8.000000") if method == "FIFO"
            else Decimal("10.666668")
        )
        self.assertEqual(Decimal(rows[0]["total_cost"]), expected_sale_cogs)
        self.assertEqual(
            rows[0]["cost_basis"],
            "FIFO_LAYER" if method == "FIFO" else "MOVING_AVERAGE",
        )
        state_after_sale = (
            await self.db.execute(text(
                "SELECT quantity,inventory_value FROM inventory_cost_states "
                "WHERE company_id=:t AND product_variant_id=:p"
            ), {"t": self.tenant, "p": self.variant["id"]})
        ).mappings().one()
        self.assertEqual(Decimal(state_after_sale["quantity"]), Decimal("296"))
        self.assertEqual(
            Decimal(state_after_sale["inventory_value"]),
            Decimal("800") - expected_sale_cogs,
        )

        original = (
            await self.db.execute(text(
                "SELECT current_sales_revision_id,final_amount_due,status,"
                "financial_evidence_version FROM visits WHERE company_id=:t AND id=:v"
            ), {"t": self.tenant, "v": visit_id})
        ).mappings().one()
        self.assertEqual(original["status"], "Completed")
        self.assertIsNotNone(original["current_sales_revision_id"])
        self.assertEqual(original["financial_evidence_version"], 4)
        self.assertEqual(Decimal(original["final_amount_due"]), Decimal("20"))
        self.assertEqual(
            (await update_visit(
                visit_id=visit_id, payload=sale,
                db=self.db, field_context=self.field.context, legacy_actor=self.field.driver,
            )), first,
        )
        # A successful idempotency replay deliberately calls session.rollback.
        # Reload our test actor via explicit async IO before its next use.
        await self.db.refresh(self.field.driver)

        correction = VisitUpdateRequest(
            request_id=uuid4(), outcome="NoSale",
            notes="Correction: customer returned damaged delivery",
            cart_items=[], cash_collected="0.000",
            returns=[{
                "product_variant_id": self.variant["id"],
                "batch_id": batch_id, "quantity": 0,
                "packs_quantity": 2, "return_type": "Damaged",
                "reason": "Damaged carton exchange",
            }],
        )
        response = await update_visit(
            visit_id=visit_id, payload=correction,
            db=self.db, field_context=self.field.context, legacy_actor=self.field.driver,
        )
        self.assertEqual(response["message"], "Visit updated successfully")
        visit = (
            await self.db.execute(text(
                "SELECT status,outcome,current_sales_revision_id,final_amount_due "
                "FROM visits WHERE company_id=:t AND id=:v"
            ), {"t": self.tenant, "v": visit_id})
        ).mappings().one()
        self.assertEqual((visit["status"],visit["outcome"]),("Completed","NoSale"))
        self.assertIsNone(visit["current_sales_revision_id"])
        self.assertEqual(Decimal(visit["final_amount_due"]),Decimal("0"))
        lines = (
            await self.db.execute(text(
                "SELECT reference_type,COUNT(*) n "
                "FROM inventory_movements WHERE company_id=:t "
                "AND reference_id=:v AND reference_type LIKE 'VISIT_%' "
                "GROUP BY reference_type"
            ), {"t": self.tenant, "v": str(visit_id)})
        ).all()
        kinds = {k:n for k,n in lines}
        self.assertEqual(kinds["VISIT_ITEM_OUT"],1)
        self.assertEqual(kinds["VISIT_REVERSAL"],1)
        self.assertEqual(kinds["VISIT_EXCHANGE_OUT"],1)
        self.assertEqual(kinds["VISIT_RETURN_IN"],1)
        reversed_costs = (
            await self.db.execute(text(
                "SELECT e.event_type,e.total_cost,e.reversal_of_cost_event_id "
                "FROM inventory_cost_events e JOIN inventory_movements m "
                "ON m.company_id=e.company_id AND m.id=e.inventory_movement_id "
                "WHERE e.company_id=:t AND m.reference_id=:v "
                "AND m.reference_type='VISIT_REVERSAL'"
            ), {"t":self.tenant,"v":str(visit_id)})
        ).mappings().all()
        self.assertEqual(len(reversed_costs), 1)
        self.assertEqual(reversed_costs[0]["event_type"], "REVERSAL_IN")
        self.assertEqual(
            Decimal(reversed_costs[0]["total_cost"]), expected_sale_cogs
        )
        self.assertIsNotNone(
            reversed_costs[0]["reversal_of_cost_event_id"]
        )
        self.assertEqual(
            await self.db.scalar(text(
                "SELECT COUNT(*) FROM visit_returns "
                "WHERE company_id=:t AND visit_id=:v AND is_cancelled=false"
            ), {"t":self.tenant,"v":visit_id}),
            1,
        )
        versions = await self.db.scalar(text(
            "SELECT COUNT(*) FROM sales_visit_revisions "
            "WHERE company_id=:t AND visit_id=:v"
        ), {"t":self.tenant,"v":visit_id})
        self.assertEqual(versions,1)
        self.assertEqual(
            await update_visit(
                visit_id=visit_id, payload=correction,
                db=self.db, field_context=self.field.context, legacy_actor=self.field.driver,
            ), response,
        )
        self.assertEqual(
            await self.db.scalar(text(
                "SELECT COUNT(*) FROM inventory_movements "
                "WHERE company_id=:t AND reference_id=:v "
                "AND reference_type='VISIT_REVERSAL'"
            ),{"t":self.tenant,"v":str(visit_id)}),
            1,
        )

        # Sale/correction/exchange must never rewrite either acquisition row.
        purchase_history_after = (
            await self.db.execute(text(
                "SELECT id,batch_id,quantity,input_quantity,input_unit_cost,"
                "input_uom_id,total_cost,created_at "
                "FROM inventory_cost_events WHERE company_id=:t "
                "AND product_variant_id=:p AND event_type='PURCHASE_IN' "
                "ORDER BY id"
            ), {"t": self.tenant, "p": self.variant["id"]})
        ).mappings().all()
        self.assertEqual(
            [tuple(row.values()) for row in purchase_history_after],
            [tuple(row.values()) for row in purchase_history_before],
        )

    async def test_fifo_real_priced_sale_and_authorized_return_correction(self):
        await self._assert_sale_and_correction("FIFO")

    async def test_average_real_priced_sale_and_authorized_return_correction(self):
        await self._assert_sale_and_correction("MOVING_AVERAGE")


if __name__ == "__main__":
    unittest.main()
