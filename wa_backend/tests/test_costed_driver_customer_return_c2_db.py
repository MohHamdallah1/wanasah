"""Genuine driver visit return/exchange and costing paths on isolated dev RLS.

Customer return is handled by REAL update_visit (not a mocked inventory
return). Fixture creates synthetic active driver route, work session, shop,
vehicle, costed warehouse receipt and stock transfer to vehicle. All handler
commits operate inside external PostgreSQL outer transaction (SAVEPOINTs);
tearDown rolls back everything. No customer data is created or persisted.

NOT the complete driver SALE/P&L gate: commercial pricing/rounding/tax context
for this synthetic tenant is absent. Return-only NoSale is explicitly distinct
from correcting an existing Sale and separate from refunding customer cash.
"""
from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.driver import update_visit
from api.warehouse.inbound import warehouse_inbound
from context import tenant_context
from database import engine
from domains.inventory_costing.service import set_cost_policy
from models import (
    DispatchRoute, Driver, InventoryLocation, ProductBatch,
    ProductLocation, ProductUomConversion, Shop, Vehicle, Visit, WorkSession, Zone,
)
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS
from schemas import UpgradedInboundRequest, VisitUpdateRequest
from services import apply_inventory_movements_batch


@unittest.skipUnless(
    os.environ.get("WANASAH_C2_CUSTOMER_RETURN_DB_GATE") == "1",
    "Authorized synthetic developer DB/tenant opt-in required",
)
class RealCustomerReturnC2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tenant = int(os.environ["WANASAH_C2_CUSTOMER_RETURN_TEST_TENANT"])
        self.token = tenant_context.set(self.tenant)
        self.conn = await engine.connect()
        self.outer = await self.conn.begin()
        self.db = AsyncSession(
            bind=self.conn, expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        await self.db.execute(
            text("SELECT set_config('app.current_tenant',:tenant,true)"),
            {"tenant": str(self.tenant)},
        )
        self.assertEqual(
            await self.db.scalar(text("SELECT current_database()")),
            os.environ["WANASAH_C2_CUSTOMER_RETURN_EXPECTED_DB"],
        )
        for table in (
            "inventory_cost_policies", "inventory_cost_events", "inventory_balances",
            "work_sessions", "dispatch_routes", "visits", "shops", "vehicles",
            "route_commercial_contexts", "tax_jurisdictions",
        ):
            self.assertEqual(
                int(await self.db.scalar(
                    text("SELECT count(*) FROM " + table + " WHERE company_id=:c"),
                    {"c": self.tenant},
                )), 0, table,
            )
        self.actor = await self.db.scalar(
            select(Driver).where(
                Driver.company_id == self.tenant,
                Driver.is_admin.is_(True),
                Driver.is_active.is_(True),
            ).limit(1),
        )
        self.assertIsNotNone(self.actor)
        self.warehouse_id = await self.db.scalar(
            text(
                "SELECT id FROM inventory_locations "
                "WHERE company_id=:c AND location_type='WAREHOUSE' "
                "AND is_active=true LIMIT 1"
            ),
            {"c": self.tenant},
        )
        self.assertIsNotNone(self.warehouse_id)
        self.variant = (
            await self.db.execute(
                text(
                    "SELECT id,base_uom_id,packs_per_carton "
                    "FROM product_variants WHERE company_id=:c "
                    "AND lifecycle_status='ACTIVE' AND operational_hold='NONE' "
                    "AND expiry_control_mode='REQUIRED' LIMIT 1"
                ), {"c": self.tenant},
            )
        ).mappings().one()

    async def asyncTearDown(self):
        try:
            await self.db.close()
            if self.outer.is_active:
                await self.outer.rollback()
        finally:
            await self.conn.close()
            tenant_context.reset(self.token)
            await engine.dispose()

    async def _create_business_fixture(self, method: str, *, commercial_context_factory=None):
        await set_cost_policy(
            self.db,
            company_id=self.tenant,
            actor_id=self.actor.id,
            method=method,
            expected_version=0,
        )
        await self.db.commit()

        req = uuid4()
        inbound = UpgradedInboundRequest(
            request_id=req, location_id=self.warehouse_id,
            reference_id="C2-CUST-IN-" + req.hex[:14],
            items=[{
                "product_variant_id": self.variant["id"],
                "quantity": "200",
                "uom_id": self.variant["base_uom_id"],
                "unit_cost": "2",
                "batch_number": "C2-CUST-LOT-" + req.hex[:14],
                "production_date": date.today() - timedelta(days=30),
                "expiry_date": date.today() + timedelta(days=730),
            }],
        )
        response = await warehouse_inbound(
            payload=inbound, db=self.db, current_admin=self.actor,
        )
        self.assertEqual(response["message"], "INBOUND_POSTED")
        batch_id = await self.db.scalar(
            select(ProductBatch.id).where(
                ProductBatch.company_id == self.tenant,
                ProductBatch.product_variant_id == self.variant["id"],
                ProductBatch.batch_number == inbound.items[0].batch_number,
            )
        )
        self.assertIsNotNone(batch_id)

        tag = uuid4().hex[:12]
        zone = Zone(company_id=self.tenant, name="C2-Return-Zone-" + tag)
        vehicle = Vehicle(
            company_id=self.tenant,
            plate_number="C2R" + tag[:9],
            maintenance_status="Active",
            is_active=True,
        )
        self.db.add_all((zone, vehicle))
        await self.db.flush()
        vehicle_location = InventoryLocation(
            company_id=self.tenant, name="C2 Return Vehicle " + tag,
            code="C2-RET-" + tag,
            location_type="VEHICLE", vehicle_id=vehicle.id,
            is_active=True, is_system_managed=False,
        )
        shop = Shop(
            company_id=self.tenant, name="C2 Customer " + tag,
            zone_id=zone.id, current_balance=Decimal("0"),
            max_debt_limit=Decimal("0"), is_active=True,
        )
        self.db.add_all((vehicle_location, shop))
        await self.db.flush()
        # Route is not active until the commercial pricing lock exists.
        # Session context is DB-immutable after INSERT: it must be supplied
        # AT CREATION, not patched into an existing session.
        session = None
        if commercial_context_factory is None:
            session = WorkSession(
                company_id=self.tenant, driver_id=self.actor.id,
                session_date=date.today(),
                is_authorized_to_sell=True,
                is_settled=False,
            )
            self.db.add(session)
            await self.db.flush()
        route = DispatchRoute(
            company_id=self.tenant, zone_id=zone.id,
            driver_id=self.actor.id,
            vehicle_id=vehicle.id,
            work_session_id=(session.id if session is not None else None),
            source_location_id=self.warehouse_id,
            status=("active" if session is not None else "waiting"),
            dispatch_date=date.today(),
        )
        # The legacy Visit PK in the developer schema does not generate a
        # value for a direct ORM fixture insert. Use an isolated synthetic id;
        # the external test transaction rolls it back.
        visit = Visit(
            id=1_700_000_000 + int(tag[:7], 16) % 300_000_000,
            company_id=self.tenant, shop_id=shop.id,
            driver_id=self.actor.id,
            operational_date=date.today(),
            status="Pending", outcome="Pending",
        )
        # Real driver mobile quantity authority requires exact carton->EACH
        # conversion. The synthetic active test SKU in tenant 2 has no such
        # published conversion; create it only in this outer-rollback fixture.
        carton_uom_id = await self.db.scalar(
            text("SELECT id FROM uom WHERE code='CARTON' LIMIT 1")
        )
        self.assertIsNotNone(carton_uom_id)
        self.db.add(ProductUomConversion(
            company_id=self.tenant,
            product_variant_id=self.variant["id"],
            from_uom_id=carton_uom_id,
            to_uom_id=self.variant["base_uom_id"],
            numerator=Decimal(self.variant["packs_per_carton"]),
            denominator=Decimal("1"),
            quantity_scale=0,
        ))
        flags = ProductLocation(
            company_id=self.tenant,
            product_variant_id=self.variant["id"],
            location_id=vehicle_location.id,
            operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
            created_by=self.actor.id,
        )
        self.db.add_all((route, visit, flags))
        await self.db.flush()
        if commercial_context_factory is not None:
            commercial_id = await commercial_context_factory(visit.id)
            session = WorkSession(
                company_id=self.tenant, driver_id=self.actor.id,
                commercial_context_id=commercial_id,
                session_date=date.today(),
                is_authorized_to_sell=True,
                is_settled=False,
            )
            self.db.add(session)
            await self.db.flush()
            route.work_session_id = session.id
            route.status = "active"
            await self.db.flush()

        movement = {
            "product_variant_id": self.variant["id"],
            "batch_id": batch_id,
            "quantity": Decimal("150"),
            "movement_kind": "PHYSICAL",
            "reference_type": "C2_TEST_VEHICLE_LOAD",
            "reference_id": "C2-LOAD-" + tag,
            "idempotency_key": "C2-RETURN-LOAD-" + tag,
            "source_location_id": self.warehouse_id,
            "destination_location_id": vehicle_location.id,
            "source_stock_status": "AVAILABLE",
            "destination_stock_status": "AVAILABLE",
            "work_session_id": session.id,
        }
        await apply_inventory_movements_batch(
            self.db, company_id=self.tenant,
            performed_by=self.actor.id, movements=[movement],
        )
        await self.db.commit()
        self.assertEqual(
            await self.db.scalar(
                text(
                    "SELECT on_hand_quantity FROM inventory_balances "
                    "WHERE company_id=:c AND location_id=:loc "
                    "AND product_variant_id=:variant AND batch_id=:batch "
                    "AND stock_status='AVAILABLE'"
                ),
                {"c": self.tenant, "loc": vehicle_location.id,
                 "variant": self.variant["id"], "batch": batch_id},
            ),
            Decimal("150"),
        )
        return int(visit.id), int(vehicle_location.id), int(batch_id)

    async def _assert_real_return_exchange(self, method: str):
        visit_id, vehicle_id, batch_id = await self._create_business_fixture(method)
        ref = uuid4()
        # NoSale with a real customer DAMAGED return requests one-for-one
        # FEFO replacement from the vehicle and creates an actual VisitReturn.
        request = VisitUpdateRequest(
            request_id=ref,
            outcome="NoSale",
            notes="Damaged delivery exchange",
            cart_items=[],
            returns=[{
                "product_variant_id": self.variant["id"],
                "batch_id": batch_id,
                "quantity": 0,
                "packs_quantity": 3,
                "return_type": "Damaged",
                "reason": "Damaged at customer",
            }],
        )
        response = await update_visit(
            visit_id=visit_id,
            payload=request,
            db=self.db,
            current_driver=self.actor,
        )
        self.assertEqual(response["message"], "Visit updated successfully")
        recorded = (
            await self.db.execute(
                text(
                    "SELECT product_variant_id,batch_id,packs_quantity,return_type,"
                    "is_cancelled FROM visit_returns "
                    "WHERE company_id=:c AND visit_id=:visit"
                ), {"c": self.tenant, "visit": visit_id},
            )
        ).mappings().all()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["product_variant_id"], self.variant["id"])
        self.assertEqual(recorded[0]["batch_id"], batch_id)
        self.assertEqual(recorded[0]["packs_quantity"], 3)
        self.assertEqual(recorded[0]["return_type"], "Damaged")
        self.assertFalse(recorded[0]["is_cancelled"])

        items = (
            await self.db.execute(
                text(
                    "SELECT reference_type,source_stock_status,"
                    "destination_stock_status,quantity FROM inventory_movements "
                    "WHERE company_id=:c AND reference_id=:v "
                    "AND reference_type IN ('VISIT_EXCHANGE_OUT','VISIT_RETURN_IN') "
                    "ORDER BY reference_type"
                ), {"c": self.tenant, "v": str(visit_id)},
            )
        ).mappings().all()
        self.assertEqual(len(items), 2)
        self.assertEqual(
            {row["reference_type"] for row in items},
            {"VISIT_EXCHANGE_OUT", "VISIT_RETURN_IN"},
        )
        self.assertEqual(
            {row["reference_type"]: Decimal(row["quantity"]) for row in items},
            {"VISIT_EXCHANGE_OUT": Decimal("3"), "VISIT_RETURN_IN": Decimal("3")},
        )
        # Physical AVAILABLE->DAMAGED stays in the same vehicle. A financial
        # accounting policy still controls its cost rather than lot profit.
        stock = (
            await self.db.execute(
                text(
                    "SELECT stock_status,on_hand_quantity FROM inventory_balances "
                    "WHERE company_id=:c AND location_id=:loc "
                    "AND product_variant_id=:variant AND batch_id=:batch"
                ),
                {"c": self.tenant, "loc": vehicle_id,
                 "variant": self.variant["id"], "batch": batch_id},
            )
        ).mappings().all()
        self.assertEqual(
            {r["stock_status"]: Decimal(r["on_hand_quantity"]) for r in stock},
            {"AVAILABLE": Decimal("147"), "DAMAGED": Decimal("3")},
        )

        # Retry exact visit return must not double replace/damage/count.
        replay = await update_visit(
            visit_id=visit_id, payload=request,
            db=self.db, current_driver=self.actor,
        )
        self.assertEqual(replay, response)
        self.assertEqual(
            await self.db.scalar(
                text("SELECT count(*) FROM visit_returns "
                     "WHERE company_id=:c AND visit_id=:v"),
                {"c": self.tenant, "v": visit_id},
            ),
            1,
        )

    async def test_fifo_actual_customer_damaged_return_and_exchange(self):
        await self._assert_real_return_exchange("FIFO")

    async def test_average_actual_customer_damaged_return_and_exchange(self):
        await self._assert_real_return_exchange("MOVING_AVERAGE")


if __name__ == "__main__":
    unittest.main()
