"""Real migrated PostgreSQL FIELD calculator/exchange/custody/replay acceptance."""
import os
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from models import (
    DispatchRoute, InventoryLocation, InventoryMovement, Product, ProductBatch, ProductLocation,
    ProductVariant, Shop, Visit, WorkSession, utc_now,
)
from schemas import AddShopRequest, UpgradedInboundRequest, VisitUpdateRequest
from api.driver import add_new_shop, update_visit
from api.warehouse.inbound import warehouse_inbound
from domains.field_operations.contracts import FieldContractError, InvoicePreviewRequest, ReturnResolutionRequest
from domains.field_operations.context import shop_commercial_state
from domains.field_operations.custody import read_custody
from domains.field_operations.invoice import preview_invoice, read_invoice
from domains.field_operations.returns import resolve_return
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS
from services import apply_inventory_movements_batch

import test_costed_driver_customer_return_c2_db as customer_fixture
import test_costed_driver_sale_correction_real_c2_db as sale_fixture


@unittest.skipUnless(os.getenv("WANASAH_FIELD_CONTRACT_PG_GATE") == "1", "Disposable GitHub PostgreSQL only")
class FieldContractPostgresTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the genuine inbound/cost/vehicle and commercial fixture authorities.
    # Each test's outer rollback leaves the canonical fixture company empty.
    asyncSetUp = customer_fixture.RealCustomerReturnC2DatabaseTests.asyncSetUp
    asyncTearDown = customer_fixture.RealCustomerReturnC2DatabaseTests.asyncTearDown
    _create_business_fixture = customer_fixture.RealCustomerReturnC2DatabaseTests._create_business_fixture
    _create_real_commercial_context = sale_fixture.RealDriverSaleCorrectionC2DatabaseTests._create_real_commercial_context

    async def new_visit(self, source_id):
        source = await self.db.get(Visit, source_id)
        target = Visit(
            id=1_700_000_000 + uuid4().int % 300_000_000,
            company_id=self.tenant, shop_id=source.shop_id, driver_id=self.field.driver.id,
            work_session_id=source.work_session_id, operational_date=source.operational_date,
            status="Pending", outcome="Pending",
        )
        self.db.add(target)
        await self.db.commit()
        return int(target.id)

    async def test_real_invoice_three_return_reasons_custody_and_exact_lost_response_replay(self):
        visit_id, vehicle_location, batch_id = await self._create_business_fixture(
            "FIFO", commercial_context_factory=self._create_real_commercial_context)
        preview = await preview_invoice(
            self.db, context=self.field.context, driver_id=self.field.driver.id, visit_id=visit_id,
            request=InvoicePreviewRequest(cart_items=[{
                "product_variant_id": self.variant["id"], "packs_quantity": 10,
            }]))
        self.assertEqual(Decimal(preview["invoice"]["totals"]["final_amount"]), Decimal("50"))
        self.assertEqual(preview["invoice"]["currency_code"], "JOD")
        self.assertIsNone(await self.db.scalar(select(Visit.current_sales_revision_id).where(
            Visit.company_id == self.tenant, Visit.id == visit_id)))
        sale = VisitUpdateRequest(request_id=uuid4(), outcome="Sale", cash_collected="50",
                                  cart_items=[{"product_variant_id": self.variant["id"], "packs_quantity": 10}])
        posted = await update_visit(visit_id, sale, self.db, self.field.context, self.field.driver)
        self.assertEqual(Decimal(posted["invoice"]["totals"]["final_amount"]), Decimal("50"))
        frozen = await read_invoice(self.db, context=self.field.context, driver_id=self.field.driver.id, visit_id=visit_id)
        self.assertEqual(frozen["invoice"]["totals"], posted["invoice"]["totals"])
        self.assertEqual(frozen["invoice"]["lines"], posted["invoice"]["lines"])
        target_id = await self.new_visit(visit_id)
        resolved = []
        for reason in ("Damaged", "Expired", "Factory_Defect"):
            response = await resolve_return(
                self.db, context=self.field.context, driver_id=self.field.driver.id, visit_id=target_id,
                request=ReturnResolutionRequest(product_variant_id=self.variant["id"], packs_quantity=1, return_type=reason))
            self.assertNotIn("batch_id", response)
            resolved.append({
                "product_variant_id": self.variant["id"], "packs_quantity": 1,
                "return_type": reason, "resolution_token": response["resolution_token"],
            })
        command = VisitUpdateRequest(request_id=uuid4(), outcome="NoSale", returns=resolved)
        result = await update_visit(target_id, command, self.db, self.field.context, self.field.driver)
        self.assertEqual(Decimal(result["new_balance"]), Decimal("0"))
        custody = await read_custody(self.db, context=self.field.context, driver_id=self.field.driver.id)
        self.assertEqual(custody["items"][0]["stock_status"], "DAMAGED")
        self.assertEqual(Decimal(custody["items"][0]["quantity"]), Decimal("3"))
        self.assertNotIn("batch_id", custody["items"][0])
        movements_before = await self.db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == self.tenant))
        replay = await update_visit(target_id, command, self.db, self.field.context, self.field.driver)
        self.assertEqual(replay, result)
        await self.db.refresh(self.field.driver)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == self.tenant)), movements_before)
        # Revalidation is skipped only for a durably completed EXACT replay.
        session_id = await self.db.scalar(select(Visit.work_session_id).where(
            Visit.company_id == self.tenant, Visit.id == target_id))
        session = await self.db.get(WorkSession, session_id)
        session.end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.db.commit()
        self.assertEqual(await update_visit(target_id, command, self.db, self.field.context, self.field.driver), result)
        await self.db.refresh(self.field.driver)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == self.tenant)), movements_before)

    async def test_shop_tax_completion_and_durable_create_replay(self):
        visit_id, _, _ = await self._create_business_fixture(
            "FIFO", commercial_context_factory=self._create_real_commercial_context)
        command = AddShopRequest(
            request_id=uuid4(), name="FIELD new shop", phone_number="F-" + uuid4().hex[:12],
            latitude=Decimal("31.9"), longitude=Decimal("35.9"))
        result = await add_new_shop(command, self.db, self.field.context, self.field.driver)
        self.assertFalse(result["commercial_readiness"]["sale_ready"])
        self.assertEqual(result["commercial_readiness"]["required_action"], "BACKOFFICE_SET_SHOP_TAX_JURISDICTION")
        shop_id = result["shop"]["id"]
        new_visit_id = await self.db.scalar(select(Visit.id).where(
            Visit.company_id == self.tenant, Visit.shop_id == shop_id))
        shop = await self.db.get(Shop, shop_id)
        self.assertIsNone(shop.tax_jurisdiction_id)
        with self.assertRaises(FieldContractError) as blocked:
            await preview_invoice(
                self.db, context=self.field.context, driver_id=self.field.driver.id, visit_id=new_visit_id,
                request=InvoicePreviewRequest(cart_items=[{
                    "product_variant_id": self.variant["id"], "packs_quantity": 1}]))
        self.assertEqual(blocked.exception.code, "SHOP_TAX_JURISDICTION_REQUIRED")
        original = await self.db.get(Visit, visit_id)
        original_shop = await self.db.get(Shop, original.shop_id)
        # Fixture simulates the existing authorized Backoffice completion; FIELD
        # has no jurisdiction write or geographic inference in its contract.
        shop.tax_jurisdiction_id = original_shop.tax_jurisdiction_id
        await self.db.commit()
        self.assertTrue((await shop_commercial_state(self.db, company_id=self.tenant, shop=shop))["sale_ready"])
        replay = await add_new_shop(command, self.db, self.field.context, self.field.driver)
        self.assertEqual(replay, result)
        await self.db.refresh(self.field.driver)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(Shop).where(
            Shop.company_id == self.tenant, Shop.phone_number == command.phone_number)), 1)
        changed = command.model_copy(update={"name": "Different input"})
        with self.assertRaises(HTTPException) as conflict:
            await add_new_shop(changed, self.db, self.field.context, self.field.driver)
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(conflict.exception.detail["code"], "FIELD_SHOP_IDEMPOTENCY_CONFLICT")

    async def test_foreign_visit_and_foreign_company_cannot_read_or_resolve(self):
        visit_id, _, _ = await self._create_business_fixture("FIFO")
        for context, driver_id in ((self.field.context, self.field.driver.id + 1),
                                   (NS(company_id=self.tenant + 100, principal_id=1, representative_id=2), self.field.driver.id)):
            with self.assertRaises(FieldContractError) as blocked:
                await resolve_return(
                    self.db, context=context, driver_id=driver_id, visit_id=visit_id,
                    request=ReturnResolutionRequest(product_variant_id=self.variant["id"], packs_quantity=1))
            self.assertEqual(blocked.exception.status_code, 404)

    async def test_real_no_lot_receipts_are_distinct_and_ambiguity_never_selects_first(self):
        source_id, location_id, _ = await self._create_business_fixture("FIFO")
        source = await self.db.get(Visit, source_id)
        product = Product(company_id=self.tenant, code="NOLOT-" + uuid4().hex, name="Anonymous SKU master")
        self.db.add(product)
        await self.db.flush()
        sku = ProductVariant(
            company_id=self.tenant, product_id=product.id, name="Anonymous SKU",
            sku="NOLOT-" + uuid4().hex, base_uom_id=self.variant["base_uom_id"],
            packs_per_carton=1, lot_control_mode="NONE", expiry_control_mode="NONE",
            lifecycle_status="ACTIVE", published_at=utc_now())
        self.db.add(sku)
        await self.db.flush()
        sku_id = int(sku.id)
        self.db.add(ProductLocation(company_id=self.tenant, product_variant_id=sku_id,
                                   location_id=location_id, created_by=self.actor.id,
                                   operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS)))
        await self.db.commit()
        for iteration in range(2):
            receipt_id = uuid4()
            await warehouse_inbound(
                UpgradedInboundRequest(request_id=receipt_id, supplier_id=self.supplier_id,
                    location_id=self.warehouse_id, reference_id="FIELD-NOLOT-" + receipt_id.hex,
                    items=[{"product_variant_id": sku_id, "quantity": "5",
                            "uom_id": self.variant["base_uom_id"], "unit_cost": "2"}]),
                self.db, self.owner.access(self.db), self.actor)
            batches = (await self.db.execute(select(ProductBatch).where(
                ProductBatch.company_id == self.tenant, ProductBatch.product_variant_id == sku_id,
            ).order_by(ProductBatch.id))).scalars().all()
            current = batches[-1]
            self.assertTrue(current.batch_number.startswith("__WANASAH_NOLOT__:"))
            await apply_inventory_movements_batch(self.db, company_id=self.tenant, performed_by=self.actor.id,
                movements=[{
                    "product_variant_id": sku_id, "batch_id": current.id, "quantity": Decimal("5"),
                    "movement_kind": "PHYSICAL", "reference_type": "FIELD_TEST_LOAD",
                    "reference_id": receipt_id.hex, "idempotency_key": "FIELD-LOAD-" + receipt_id.hex,
                    "source_location_id": self.warehouse_id, "destination_location_id": location_id,
                    "source_stock_status": "AVAILABLE", "destination_stock_status": "AVAILABLE",
                    "work_session_id": source.work_session_id,
                }])
            await self.db.commit()
            delivery_id = source_id if iteration == 0 else target_id
            await update_visit(delivery_id, VisitUpdateRequest(request_id=uuid4(), outcome="NoSale",
                cart_items=[{"product_variant_id": sku_id, "sample_packs_quantity": 5, "sample_reason": "FIELD evidence"}]),
                self.db, self.field.context, self.field.driver)
            target_id = await self.new_visit(source_id)
            request = ReturnResolutionRequest(product_variant_id=sku_id, packs_quantity=1)
            if iteration == 0:
                response = await resolve_return(self.db, context=self.field.context, driver_id=self.field.driver.id,
                                                visit_id=target_id, request=request)
                self.assertEqual(response["status"], "RESOLVED")
                self.assertIsNone(response["evidence"]["lot_number"])
            else:
                with self.assertRaises(FieldContractError) as ambiguity:
                    await resolve_return(self.db, context=self.field.context, driver_id=self.field.driver.id,
                                         visit_id=target_id, request=request)
                self.assertEqual(ambiguity.exception.context, {"required_evidence": ["delivery_date"]})
                self.assertNotIn("__WANASAH", str(ambiguity.exception.context))
                self.assertEqual(len(batches), 2)
                delivered_batches = (await self.db.execute(select(InventoryMovement.batch_id).where(
                    InventoryMovement.company_id == self.tenant,
                    InventoryMovement.product_variant_id == sku_id,
                    InventoryMovement.reference_type == "VISIT_SAMPLE_OUT",
                ).distinct())).scalars().all()
                self.assertEqual(set(delivered_batches), {batch.id for batch in batches})
