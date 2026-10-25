from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from domains.inventory_vehicle_load.service import mutate_vehicle_load
from domains.vehicles.contracts import CreateVehicleCommand, VehicleError, VehicleLifecycleCommand
from domains.vehicles.lifecycle import deactivate_vehicle
from domains.vehicles.management import create_vehicle
from models import (
    Company,
    DispatchRoute,
    InventoryBalance,
    InventoryLocation,
    Product,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    UOM,
    Vehicle,
    Zone,
    utc_now,
)
from product_lifecycle import DEFAULT_PRODUCT_LOCATION_FLAGS
from tests.canonical_actor_fixtures import seed_company_owner_fixture


GATE_ENV = "WANASAH_VEHICLE_LOAD_PG_GATE"
class VehicleLoadV1Postgres(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if os.environ.get(GATE_ENV) != "1":
            raise unittest.SkipTest(f"set {GATE_ENV}=1 to run the real PostgreSQL gate")
        raw_url = os.environ.get("DATABASE_URL_MIGRATION") or os.environ.get("DATABASE_URL")
        if not raw_url:
            raise unittest.SkipTest("DATABASE_URL[_MIGRATION] is required")
        parsed = make_url(raw_url)
        if not str(parsed.drivername).startswith("postgresql"):
            raise unittest.SkipTest("PostgreSQL is required")
        cls.raw_url = raw_url

    @classmethod
    def _engine(cls):
        return create_async_engine(
            cls.raw_url,
            poolclass=NullPool,
            connect_args={
                "server_settings": {
                    "lock_timeout": "5000",
                    "statement_timeout": "12000",
                }
            },
        )

    async def asyncSetUp(self) -> None:
        self.engine = self._engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.db = self.Session()

        suffix = uuid4().hex[:8]
        company = Company(
            name=f"Vehicle Load {suffix}",
            company_code=f"VL-{suffix}",
            timezone="UTC",
        )
        self.db.add(company)
        await self.db.flush()
        self.company_id = int(company.id)
        self.owner = await seed_company_owner_fixture(
            self.db,
            self.company_id,
            password="SyntheticOwner123",
        )

        self.warehouse_a = InventoryLocation(
            company_id=self.company_id,
            name=f"Warehouse A {suffix}",
            code=f"WHA-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        self.warehouse_b = InventoryLocation(
            company_id=self.company_id,
            name=f"Warehouse B {suffix}",
            code=f"WHB-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        self.db.add_all([self.warehouse_a, self.warehouse_b])
        await self.db.flush()
        self.warehouse_a_id = int(self.warehouse_a.id)
        self.warehouse_b_id = int(self.warehouse_b.id)

        uom = UOM(name=f"Each {suffix}", code=f"E{suffix.upper()}")
        self.db.add(uom)
        await self.db.flush()
        product = Product(
            company_id=self.company_id,
            code=f"P-{suffix}",
            name=f"Product {suffix}",
        )
        self.db.add(product)
        await self.db.flush()
        self.variant = ProductVariant(
            company_id=self.company_id,
            product_id=int(product.id),
            base_uom_id=int(uom.id),
            name=f"Variant {suffix}",
            sku=f"SKU-{suffix}",
            quantity_scale=0,
            quantity_step=1,
            lot_control_mode="NONE",
            expiry_control_mode="NONE",
            lifecycle_status="ACTIVE",
            operational_hold="NONE",
            lifecycle_revision=1,
            version=1,
            published_at=utc_now().replace(tzinfo=None),
            packs_per_carton=1,
        )
        self.db.add(self.variant)
        await self.db.flush()
        self.variant_id = int(self.variant.id)

        self.db.add(
            ProductLocation(
                company_id=self.company_id,
                location_id=self.warehouse_a_id,
                product_variant_id=self.variant_id,
                operational_flags=dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
                created_by=int(self.owner.operational_driver.id),
            )
        )
        self.batch = ProductBatch(
            company_id=self.company_id,
            product_variant_id=self.variant_id,
            batch_number=f"B-{suffix}",
            disposition="RELEASED",
            is_active=True,
        )
        self.db.add(self.batch)
        await self.db.flush()
        self.batch_id = int(self.batch.id)
        self.db.add(
            InventoryBalance(
                company_id=self.company_id,
                location_id=self.warehouse_a_id,
                product_variant_id=self.variant_id,
                batch_id=self.batch_id,
                stock_status="AVAILABLE",
                on_hand_quantity=Decimal("10"),
                reserved_quantity=Decimal("0"),
            )
        )

        created = await create_vehicle(
            self.db,
            company_id=self.company_id,
            actor_id=int(self.owner.operational_driver.id),
            command=CreateVehicleCommand(
                request_id=str(uuid4()),
                plate_number=f"VL-{suffix}",
                vehicle_type="Van",
                maintenance_status="Active",
            ),
        )
        self.vehicle_id = int(created["id"])
        self.vehicle_location_id = int(
            await self.db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == self.company_id,
                    InventoryLocation.vehicle_id == self.vehicle_id,
                    InventoryLocation.location_type == "VEHICLE",
                )
            )
        )
        await self.db.commit()

    async def asyncTearDown(self) -> None:
        try:
            await self.db.rollback()
        except Exception:
            pass
        await self.db.close()
        await self.engine.dispose()

    async def _mutate(
        self,
        db: AsyncSession,
        *,
        direction: str,
        warehouse_id: int,
        quantity: str,
        request_id=None,
        stock_status: str | None = None,
    ):
        item = {
            "product_variant_id": self.variant_id,
            "quantity": Decimal(quantity),
        }
        if stock_status is not None:
            item["stock_status"] = stock_status
        return await mutate_vehicle_load(
            db,
            access=self.owner.access(db),
            actor_id=int(self.owner.operational_driver.id),
            vehicle_id=self.vehicle_id,
            warehouse_id=int(warehouse_id),
            direction=direction,
            request_id=request_id or uuid4(),
            items=[item],
        )

    async def _vehicle_balance(self, status: str = "AVAILABLE") -> Decimal:
        value = await self.db.scalar(
            select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == self.company_id,
                InventoryBalance.location_id == self.vehicle_location_id,
                InventoryBalance.product_variant_id == self.variant_id,
                InventoryBalance.batch_id == self.batch_id,
                InventoryBalance.stock_status == status,
            )
        )
        return Decimal(value or 0)

    async def test_fefo_shortage_is_stable_business_conflict(self):
        with self.assertRaises(VehicleError) as ctx:
            await self._mutate(
                self.db,
                direction="ADD",
                warehouse_id=self.warehouse_a_id,
                quantity="11",
            )
        self.assertEqual(ctx.exception.code, "VEHICLE_LOAD_SOURCE_STOCK_CHANGED")
        await self.db.rollback()
        self.assertEqual(await self._vehicle_balance(), Decimal("0"))

    async def test_existing_inbound_disabled_destination_is_not_overwritten(self):
        await self._mutate(
            self.db,
            direction="ADD",
            warehouse_id=self.warehouse_a_id,
            quantity="2",
        )
        flags = dict(DEFAULT_PRODUCT_LOCATION_FLAGS)
        flags["inbound_enabled"] = False
        self.db.add(
            ProductLocation(
                company_id=self.company_id,
                location_id=self.warehouse_b_id,
                product_variant_id=self.variant_id,
                operational_flags=flags,
                created_by=int(self.owner.operational_driver.id),
            )
        )
        await self.db.commit()

        with self.assertRaises(VehicleError) as ctx:
            await self._mutate(
                self.db,
                direction="UNLOAD",
                warehouse_id=self.warehouse_b_id,
                quantity="1",
                stock_status="AVAILABLE",
            )
        self.assertEqual(ctx.exception.code, "PRODUCT_LOCATION_INBOUND_DISABLED")
        await self.db.rollback()
        self.assertEqual(await self._vehicle_balance(), Decimal("2"))

        row = await self.db.scalar(
            select(ProductLocation).where(
                ProductLocation.company_id == self.company_id,
                ProductLocation.location_id == self.warehouse_b_id,
                ProductLocation.product_variant_id == self.variant_id,
            )
        )
        self.assertFalse(bool(row.operational_flags["inbound_enabled"]))

    async def test_recall_during_vehicle_custody_unloads_into_recalled_bucket(self):
        await self._mutate(
            self.db,
            direction="ADD",
            warehouse_id=self.warehouse_a_id,
            quantity="3",
        )
        variant = await self.db.get(ProductVariant, self.variant_id)
        self.assertIsNotNone(variant)
        variant.operational_hold = "RECALL"
        variant.lifecycle_revision = int(variant.lifecycle_revision) + 1
        await self.db.commit()

        await self._mutate(
            self.db,
            direction="UNLOAD",
            warehouse_id=self.warehouse_b_id,
            quantity="3",
            stock_status="AVAILABLE",
        )
        await self.db.commit()

        recalled = await self.db.scalar(
            select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == self.company_id,
                InventoryBalance.location_id == self.warehouse_b_id,
                InventoryBalance.product_variant_id == self.variant_id,
                InventoryBalance.batch_id == self.batch_id,
                InventoryBalance.stock_status == "RECALLED",
            )
        )
        available = await self.db.scalar(
            select(InventoryBalance.on_hand_quantity).where(
                InventoryBalance.company_id == self.company_id,
                InventoryBalance.location_id == self.warehouse_b_id,
                InventoryBalance.product_variant_id == self.variant_id,
                InventoryBalance.batch_id == self.batch_id,
                InventoryBalance.stock_status == "AVAILABLE",
            )
        )
        self.assertEqual(Decimal(recalled or 0), Decimal("3"))
        self.assertEqual(Decimal(available or 0), Decimal("0"))
        self.assertEqual(await self._vehicle_balance(), Decimal("0"))

    async def test_completed_unload_replay_survives_later_vehicle_deactivation(self):
        await self._mutate(
            self.db,
            direction="ADD",
            warehouse_id=self.warehouse_a_id,
            quantity="1",
        )
        request_id = uuid4()
        first = await self._mutate(
            self.db,
            direction="UNLOAD",
            warehouse_id=self.warehouse_b_id,
            quantity="1",
            stock_status="AVAILABLE",
            request_id=request_id,
        )
        vehicle = await self.db.get(Vehicle, self.vehicle_id)
        await deactivate_vehicle(
            self.db,
            company_id=self.company_id,
            actor_id=int(self.owner.operational_driver.id),
            vehicle_id=self.vehicle_id,
            command=VehicleLifecycleCommand(
                request_id=str(uuid4()),
                expected_version=int(vehicle.version),
            ),
        )

        replay = await self._mutate(
            self.db,
            direction="UNLOAD",
            warehouse_id=self.warehouse_b_id,
            quantity="1",
            stock_status="AVAILABLE",
            request_id=request_id,
        )
        self.assertEqual(replay, first)
        custody = await self.db.get(InventoryLocation, self.vehicle_location_id)
        self.assertFalse(custody.is_active)

    async def test_vehicle_row_serializes_direct_mutation_against_new_route_owner(self):
        zone = Zone(company_id=self.company_id, name="Zone " + uuid4().hex[:8])
        self.db.add(zone)
        await self.db.flush()
        route = DispatchRoute(
            company_id=self.company_id,
            zone_id=int(zone.id),
            driver_id=int(self.owner.operational_driver.id),
            vehicle_id=self.vehicle_id,
            source_location_id=self.warehouse_a_id,
            dispatch_date=date.today(),
            status="closed",
        )
        self.db.add(route)
        await self.db.commit()

        holder = self.Session()
        contender = self.Session()
        try:
            locked_vehicle = await holder.scalar(
                select(Vehicle)
                .where(
                    Vehicle.company_id == self.company_id,
                    Vehicle.id == self.vehicle_id,
                )
                .with_for_update()
            )
            self.assertIsNotNone(locked_vehicle)
            locked_route = await holder.get(DispatchRoute, int(route.id))
            locked_route.status = "waiting"
            await holder.flush()

            task = asyncio.create_task(
                self._mutate(
                    contender,
                    direction="ADD",
                    warehouse_id=self.warehouse_a_id,
                    quantity="1",
                )
            )
            await asyncio.sleep(0.15)
            self.assertFalse(task.done(), "direct mutation must wait on Vehicle ownership lock")

            await holder.commit()
            with self.assertRaises(VehicleError) as ctx:
                await task
            self.assertEqual(ctx.exception.code, "VEHICLE_LOAD_OWNED_BY_WORKFLOW")
            await contender.rollback()
        finally:
            await holder.close()
            await contender.close()


if __name__ == "__main__":
    unittest.main()
