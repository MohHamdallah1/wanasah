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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from asyncpg import Range
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import test_costed_driver_customer_return_c2_db as customer_fixture
from api.driver import update_visit
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
        self.actor = await self.db.scalar(
            select(Driver).where(
                Driver.company_id == self.tenant,
                Driver.is_active.is_(True),
                Driver.is_admin.is_(True),
            ).limit(1),
        )
        self.assertIsNotNone(self.actor)
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
                DispatchRoute.driver_id == self.actor.id,
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
            )
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
            current_driver=self.actor,
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
        self.assertEqual(Decimal(rows[0]["total_cost"]), Decimal("8"))

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
                db=self.db, current_driver=self.actor,
            )), first,
        )
        # A successful idempotency replay deliberately calls session.rollback.
        # Reload our test actor via explicit async IO before its next use.
        await self.db.refresh(self.actor)

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
            db=self.db, current_driver=self.actor,
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
                db=self.db, current_driver=self.actor,
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

    async def test_fifo_real_priced_sale_and_authorized_return_correction(self):
        await self._assert_sale_and_correction("FIFO")

    async def test_average_real_priced_sale_and_authorized_return_correction(self):
        await self._assert_sale_and_correction("MOVING_AVERAGE")


if __name__ == "__main__":
    unittest.main()
