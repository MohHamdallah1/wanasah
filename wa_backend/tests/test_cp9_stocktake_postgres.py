from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import bcrypt
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.warehouse import locations as warehouse_locations
from api.warehouse import stocktake as stocktake_api
from domains.sales_evidence import models as _sales_evidence_models  # noqa: F401
from domains.suppliers import models as _supplier_models  # noqa: F401
from domains.stocktake.contracts import (
    StocktakeApprovalCommand,
    StocktakeCancelCommand,
    StocktakeCountCommand,
    StocktakeRecountCommand,
    StocktakeStartCommand,
)
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from models import (
    Base,
    Company,
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    InventoryMovement,
    Product,
    ProductBatch,
    ProductVariant,
    SessionInventorySnapshot,
    StocktakeCountAttempt,
    StocktakeSession,
    UOM,
    WorkSession,
    Zone,
    utc_now,
)
from schemas import WarehouseLocationStateRequest
from services import InventoryMutationError


GATE_ENV = "WANASAH_CP9_PG_GATE"
SCHEMA_PREFIX = "cp9_stocktake_"
PASSWORD = "SyntheticCP9Password123"


class ScopedAccess:
    """Minimal non-owner canonical-style capability surface for route acceptance."""

    def __init__(self, db: AsyncSession, company_id: int, grants: dict[str, set[int]]):
        self.db = db
        self.company_id = company_id
        self.grants = {code: set(ids) for code, ids in grants.items()}
        self.require_calls: list[tuple[str, int | None]] = []

    async def require(self, code: str, location_id: int | None = None, *, any_location: bool = False):
        self.require_calls.append((code, location_id))
        allowed = self.grants.get(code, set())
        if any_location:
            if not allowed:
                raise HTTPException(status_code=403, detail="Forbidden")
            return
        if location_id is None or location_id not in allowed:
            raise HTTPException(status_code=403, detail="Forbidden")

    def location_filter(self, code: str, model=InventoryLocation):
        allowed = sorted(self.grants.get(code, set()))
        return model.id.in_(allowed)


class CP9StocktakePostgresAcceptance(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if os.environ.get(GATE_ENV) != "1":
            raise unittest.SkipTest(f"set {GATE_ENV}=1 to run CP9 PostgreSQL acceptance")
        raw_url = os.environ.get("DATABASE_URL_MIGRATION") or os.environ.get("DATABASE_URL")
        if not raw_url:
            raise unittest.SkipTest("DATABASE_URL[_MIGRATION] is required")
        parsed = make_url(raw_url)
        if not str(parsed.drivername).startswith("postgresql"):
            raise unittest.SkipTest("PostgreSQL is required")
        cls.raw_url = raw_url
        cls.schema = SCHEMA_PREFIX + uuid4().hex
        asyncio.run(cls._create_schema())

    @classmethod
    def _new_engine(cls):
        return create_async_engine(
            cls.raw_url,
            poolclass=NullPool,
            connect_args={
                "server_settings": {
                    "search_path": f'"{cls.schema}",public',
                    "lock_timeout": "7000",
                    "statement_timeout": "20000",
                }
            },
        )

    @classmethod
    async def _create_schema(cls) -> None:
        admin = create_async_engine(cls.raw_url, poolclass=NullPool)
        try:
            async with admin.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
            engine = cls._new_engine()
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            finally:
                await engine.dispose()
        except Exception:
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{cls.schema}" CASCADE'))
            raise
        finally:
            await admin.dispose()

    @classmethod
    def tearDownClass(cls) -> None:
        async def cleanup() -> int:
            admin = create_async_engine(cls.raw_url, poolclass=NullPool)
            try:
                async with admin.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA IF EXISTS "{cls.schema}" CASCADE'))
                    return int(await conn.scalar(
                        text("SELECT count(*) FROM pg_namespace WHERE nspname LIKE :prefix"),
                        {"prefix": SCHEMA_PREFIX + "%"},
                    ) or 0)
            finally:
                await admin.dispose()

        leftovers = asyncio.run(cleanup())
        print(f"CP9_DISPOSABLE_SCHEMA_CLEANUP={leftovers}", flush=True)
        if leftovers:
            raise AssertionError(f"leftover CP9 schemas: {leftovers}")
        super().tearDownClass()

    async def asyncSetUp(self) -> None:
        self.engine = self._new_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.db = self.Session()
        suffix = uuid4().hex[:8]

        company_a = Company(name=f"CP9 Company A {suffix}", company_code=f"CP9A-{suffix}", timezone="UTC")
        company_b = Company(name=f"CP9 Company B {suffix}", company_code=f"CP9B-{suffix}", timezone="UTC")
        self.db.add_all([company_a, company_b])
        await self.db.flush()
        self.company_a = int(company_a.id)
        self.company_b = int(company_b.id)

        password_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
        actor_a = Driver(company_id=self.company_a, username=f"cp9-a-{suffix}", password_hash=password_hash, full_name="CP9 non-owner A")
        actor_a2 = Driver(company_id=self.company_a, username=f"cp9-a2-{suffix}", password_hash=password_hash, full_name="CP9 non-owner A2")
        actor_b = Driver(company_id=self.company_b, username=f"cp9-b-{suffix}", password_hash=password_hash, full_name="CP9 non-owner B")
        self.db.add_all([actor_a, actor_a2, actor_b])
        await self.db.flush()
        self.actor_a, self.actor_a2, self.actor_b = actor_a, actor_a2, actor_b

        a1 = InventoryLocation(company_id=self.company_a, name="Warehouse Shared", code=f"A1-{suffix}", location_type="WAREHOUSE", is_active=True, version=1)
        a2 = InventoryLocation(company_id=self.company_a, name="Warehouse Shared", code=f"A2-{suffix}", location_type="WAREHOUSE", is_active=True, version=1)
        b1 = InventoryLocation(company_id=self.company_b, name="Warehouse Shared", code=f"B1-{suffix}", location_type="WAREHOUSE", is_active=True, version=1)
        empty = InventoryLocation(company_id=self.company_a, name="CP9 empty blocker warehouse", code=f"AE-{suffix}", location_type="WAREHOUSE", is_active=True, version=1)
        self.db.add_all([a1, a2, b1, empty])
        await self.db.flush()
        self.a1, self.a2, self.b1, self.empty = map(int, (a1.id, a2.id, b1.id, empty.id))

        uom = UOM(name=f"Each CP9 {suffix}", code=f"C9{suffix.upper()}")
        self.db.add(uom)
        await self.db.flush()
        self.uom = int(uom.id)

        self.product_a, self.variant_a = await self._product(self.company_a, "Overlapping Product", "OVERLAP-SKU")
        self.product_b, self.variant_b = await self._product(self.company_b, "Overlapping Product", "OVERLAP-SKU")

        shared_batch = ProductBatch(company_id=self.company_a, product_variant_id=self.variant_a, batch_number="OVERLAP-BATCH", disposition="RELEASED", is_active=True)
        a1_only = ProductBatch(company_id=self.company_a, product_variant_id=self.variant_a, batch_number="A1-ONLY", disposition="RELEASED", is_active=True)
        a2_only = ProductBatch(company_id=self.company_a, product_variant_id=self.variant_a, batch_number="A2-ONLY", disposition="RELEASED", is_active=True)
        no_lot = ProductBatch(company_id=self.company_a, product_variant_id=self.variant_a, batch_number="__WANASAH_NOLOT__:CP9", disposition="RELEASED", is_active=True)
        b_batch = ProductBatch(company_id=self.company_b, product_variant_id=self.variant_b, batch_number="OVERLAP-BATCH", disposition="RELEASED", is_active=True)
        self.db.add_all([shared_batch, a1_only, a2_only, no_lot, b_batch])
        await self.db.flush()
        self.shared_batch = int(shared_batch.id)
        self.a1_only = int(a1_only.id)
        self.a2_only = int(a2_only.id)
        self.no_lot = int(no_lot.id)
        self.b_batch = int(b_batch.id)

        await self._balance(self.company_a, self.a1, self.variant_a, self.shared_batch, 10)
        await self._balance(self.company_a, self.a1, self.variant_a, self.a1_only, 5)
        await self._balance(self.company_a, self.a1, self.variant_a, self.no_lot, 2)
        await self._balance(self.company_a, self.a2, self.variant_a, self.shared_batch, 10)
        await self._balance(self.company_a, self.a2, self.variant_a, self.a2_only, 5)
        await self._balance(self.company_b, self.b1, self.variant_b, self.b_batch, 10)

        self.va, self.va_location, self.va_work = await self._vehicle_context(
            company_id=self.company_a,
            actor=actor_a,
            source_location_id=self.a1,
            suffix="VA" + suffix,
        )
        self.vb, self.vb_location, self.vb_work = await self._vehicle_context(
            company_id=self.company_b,
            actor=actor_b,
            source_location_id=self.b1,
            suffix="VB" + suffix,
        )
        await self.db.commit()

        # Durable replay rollback must not expire the legacy actor test fixtures.
        self.actor_a = SimpleNamespace(id=int(actor_a.id), username=str(actor_a.username), full_name=str(actor_a.full_name), password_hash=password_hash)
        self.actor_a2 = SimpleNamespace(id=int(actor_a2.id), username=str(actor_a2.username), full_name=str(actor_a2.full_name), password_hash=password_hash)
        self.actor_b = SimpleNamespace(id=int(actor_b.id), username=str(actor_b.username), full_name=str(actor_b.full_name), password_hash=password_hash)

        all_a = {self.a1, self.a2, self.empty, self.va_location}
        self.access_a_all = ScopedAccess(self.db, self.company_a, {
            "location.read": all_a,
            "stocktake.read": all_a,
            "stocktake.start": all_a,
            "stocktake.count": all_a,
            "stocktake.review": all_a,
            "stocktake.approve": all_a,
            "stocktake.recount": all_a,
            "stocktake.cancel": all_a,
        })
        self.access_a1 = ScopedAccess(self.db, self.company_a, {
            "location.read": {self.a1},
            "stocktake.read": {self.a1},
            "stocktake.start": {self.a1},
            "stocktake.count": {self.a1},
            "stocktake.review": {self.a1},
            "stocktake.approve": {self.a1},
            "stocktake.recount": {self.a1},
            "stocktake.cancel": {self.a1},
        })
        self.access_a2_read = ScopedAccess(self.db, self.company_a, {
            "location.read": {self.a2}, "stocktake.read": {self.a2},
        })
        self.access_b = ScopedAccess(self.db, self.company_b, {
            "location.read": {self.b1, self.vb_location},
            "stocktake.read": {self.b1, self.vb_location},
            "stocktake.start": {self.b1, self.vb_location},
            "stocktake.count": {self.b1, self.vb_location},
            "stocktake.review": {self.b1, self.vb_location},
            "stocktake.approve": {self.b1, self.vb_location},
            "stocktake.recount": {self.b1, self.vb_location},
            "stocktake.cancel": {self.b1, self.vb_location},
        })

    async def asyncTearDown(self) -> None:
        try:
            await self.db.rollback()
        except Exception:
            pass
        await self.db.close()
        await self.engine.dispose()

    async def _product(self, company_id: int, name: str, sku: str) -> tuple[int, int]:
        suffix = uuid4().hex[:8]
        product = Product(company_id=company_id, code=f"P-{suffix}", name=name)
        self.db.add(product)
        await self.db.flush()
        variant = ProductVariant(
            company_id=company_id,
            product_id=int(product.id),
            base_uom_id=self.uom,
            name=name,
            sku=sku,
            quantity_scale=0,
            quantity_step=1,
            lot_control_mode="OPTIONAL",
            expiry_control_mode="OPTIONAL",
            lifecycle_status="ACTIVE",
            operational_hold="NONE",
            lifecycle_revision=1,
            version=1,
            published_at=utc_now().replace(tzinfo=None),
            packs_per_carton=10,
        )
        self.db.add(variant)
        await self.db.flush()
        return int(product.id), int(variant.id)

    async def _balance(self, company_id: int, location_id: int, variant_id: int, batch_id: int, qty: int) -> None:
        self.db.add(InventoryBalance(
            company_id=company_id,
            location_id=location_id,
            product_variant_id=variant_id,
            batch_id=batch_id,
            stock_status="AVAILABLE",
            on_hand_quantity=Decimal(qty),
            reserved_quantity=Decimal("0"),
        ))
        await self.db.flush()

    async def _vehicle_context(self, *, company_id: int, actor: Driver, source_location_id: int, suffix: str):
        created = await create_vehicle(
            self.db,
            company_id=company_id,
            actor_id=int(actor.id),
            command=CreateVehicleCommand(
                request_id=str(uuid4()),
                plate_number="CP9-" + suffix[:12],
                vehicle_type="Van",
                maintenance_status="Active",
            ),
        )
        vehicle_id = int(created["id"])
        custody = await self.db.scalar(select(InventoryLocation).where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.vehicle_id == vehicle_id,
            InventoryLocation.location_type == "VEHICLE",
            InventoryLocation.is_active.is_(True),
        ))
        zone = Zone(company_id=company_id, name="Zone " + suffix)
        self.db.add(zone)
        await self.db.flush()
        ended = utc_now().replace(tzinfo=None)
        work = WorkSession(
            company_id=company_id,
            driver_id=int(actor.id),
            session_date=date.today(),
            start_time=ended - timedelta(hours=1),
            end_time=ended,
            is_authorized_to_sell=False,
            is_settled=False,
        )
        self.db.add(work)
        await self.db.flush()
        route = DispatchRoute(
            company_id=company_id,
            zone_id=int(zone.id),
            driver_id=int(actor.id),
            vehicle_id=vehicle_id,
            work_session_id=int(work.id),
            source_location_id=source_location_id,
            dispatch_date=date.today(),
            status="closed",
        )
        self.db.add(route)
        await self.db.flush()
        return vehicle_id, int(custody.id), int(work.id)

    async def _start(self, location_id: int, access: ScopedAccess, actor: Driver, *, stocktake_type="FULL_COUNT", product_variant_id=None, batch_id=None, work_session_id=None, request_id=None):
        return await stocktake_api.start_unified_stocktake(
            StocktakeStartCommand(
                request_id=request_id or uuid4(),
                location_id=location_id,
                stocktake_type=stocktake_type,
                product_variant_id=product_variant_id,
                batch_id=batch_id,
                related_work_session_id=work_session_id,
            ),
            db=self.db,
            access=access,
            legacy_actor=actor,
        )

    async def _count(self, session_id: int, access: ScopedAccess, actor: Driver, quantities: dict[int, int], *, request_id=None):
        sheet = await stocktake_api.get_stocktake_count_sheet(
            session_id, db=self.db, access=access, legacy_actor=actor,
        )
        items = []
        for row in sheet:
            items.append({
                "product_variant_id": row["product_variant_id"],
                "batch_id": row["batch_id"],
                "stock_status": row["stock_status"],
                "actual_quantity": Decimal(quantities.get(row["batch_id"], 0)),
                "uom_id": row["base_uom_id"],
            })
        command = StocktakeCountCommand(request_id=request_id or uuid4(), items=items)
        response = await stocktake_api.submit_stocktake_count(session_id, command, db=self.db, access=access, legacy_actor=actor)
        return response, command

    async def _approve(self, session_id: int, attempt_id: int, access: ScopedAccess, actor: Driver, *, request_id=None):
        command = StocktakeApprovalCommand(
            request_id=request_id or uuid4(),
            count_attempt_id=attempt_id,
            password=PASSWORD,
        )
        response = await stocktake_api.approve_stocktake_session(session_id, command, db=self.db, access=access, legacy_actor=actor)
        return response, command

    async def test_company_location_candidate_context_and_vehicle_isolation(self):
        # A1 and A2 share visible product/SKU/batch data, but location-specific candidates stay scoped.
        a1_page = await stocktake_api.list_stocktake_cycle_batches(
            location_id=self.a1, product_variant_id=self.variant_a, search=None, cursor=None, limit=100,
            db=self.db, access=self.access_a1,
        )
        a1_ids = {item["id"] for item in a1_page["items"]}
        self.assertIn(self.shared_batch, a1_ids)
        self.assertIn(self.a1_only, a1_ids)
        self.assertNotIn(self.a2_only, a1_ids)
        no_lot_item = next(item for item in a1_page["items"] if item["id"] == self.no_lot)
        self.assertIsNone(no_lot_item["batch_number"])
        self.assertNotIn("__WANASAH_NOLOT__", repr(a1_page))

        a2_page = await stocktake_api.list_stocktake_cycle_batches(
            location_id=self.a2, product_variant_id=self.variant_a, search=None, cursor=None, limit=100,
            db=self.db, access=self.access_a_all,
        )
        a2_ids = {item["id"] for item in a2_page["items"]}
        self.assertIn(self.shared_batch, a2_ids)
        self.assertIn(self.a2_only, a2_ids)
        self.assertNotIn(self.a1_only, a2_ids)

        with self.assertRaises(HTTPException) as denied_location:
            await stocktake_api.list_stocktake_cycle_batches(
                location_id=self.a1, product_variant_id=self.variant_a, search=None, cursor=None, limit=50,
                db=self.db, access=self.access_a2_read,
            )
        self.assertEqual(denied_location.exception.status_code, 403)

        # Foreign-company product/location IDs remain opaque even if numeric IDs are supplied.
        malicious = ScopedAccess(self.db, self.company_a, {
            "stocktake.start": {self.b1}, "stocktake.read": {self.b1}, "location.read": {self.b1},
        })
        with self.assertRaises(HTTPException) as foreign_location:
            await stocktake_api.list_stocktake_cycle_batches(
                location_id=self.b1, product_variant_id=self.variant_b, search=None, cursor=None, limit=50,
                db=self.db, access=malicious,
            )
        self.assertEqual(foreign_location.exception.status_code, 404)

        # Warehouse-only stocktake.start must not authorize its vehicle custody location.
        warehouse_only = ScopedAccess(self.db, self.company_a, {
            "location.read": {self.a1}, "stocktake.start": {self.a1},
        })
        no_vehicle = await stocktake_api.list_vehicle_recon_candidates(
            source_location_id=self.a1, search=None, cursor=None, limit=50,
            db=self.db, access=warehouse_only,
        )
        self.assertEqual(no_vehicle["items"], [])

        vehicle_access = ScopedAccess(self.db, self.company_a, {
            "location.read": {self.a1}, "stocktake.start": {self.va_location},
        })
        vehicle_page = await stocktake_api.list_vehicle_recon_candidates(
            source_location_id=self.a1, search=None, cursor=None, limit=50,
            db=self.db, access=vehicle_access,
        )
        self.assertEqual([item["vehicle_location_id"] for item in vehicle_page["items"]], [self.va_location])
        self.assertEqual(vehicle_page["items"][0]["work_session_id"], self.va_work)
        self.assertNotIn(self.vb_location, {item["vehicle_location_id"] for item in vehicle_page["items"]})

        # Start A1 and prove active-list/context cannot be crossed by A2-only or Company B.
        started = await self._start(self.a1, self.access_a_all, self.actor_a)
        sid = int(started["session_id"])
        a1_active = await stocktake_api.list_active_stocktake_sessions(
            location_id=self.a1, cursor=None, limit=50, db=self.db, access=self.access_a1,
        )
        self.assertEqual([item["id"] for item in a1_active["items"]], [sid])
        with self.assertRaises(HTTPException) as a2_reader:
            await stocktake_api.get_stocktake_session_context(
                sid, anchor_location_id=self.a1, db=self.db, access=self.access_a2_read,
            )
        self.assertEqual(a2_reader.exception.status_code, 403)
        with self.assertRaises(HTTPException) as foreign_session:
            await stocktake_api.get_stocktake_session_context(
                sid, anchor_location_id=self.b1, db=self.db, access=self.access_b,
            )
        self.assertEqual(foreign_session.exception.status_code, 404)

    async def test_normal_variance_recount_cancel_idempotency_locks_and_posting(self):
        # Normal no-variance count: same start/count/approve command replays without duplicate side effects.
        start_id = uuid4()
        first = await self._start(self.a1, self.access_a_all, self.actor_a, request_id=start_id)
        replay = await self._start(self.a1, self.access_a_all, self.actor_a, request_id=start_id)
        self.assertEqual(replay, first)
        sid = int(first["session_id"])
        self.assertEqual(int(await self.db.scalar(select(func.count()).select_from(StocktakeSession).where(StocktakeSession.id == sid))), 1)
        self.assertGreater(int(await self.db.scalar(select(func.count()).select_from(InventoryLock).where(InventoryLock.stocktake_session_id == sid, InventoryLock.released_at.is_(None))) or 0), 0)

        counted, count_cmd = await self._count(
            sid, self.access_a_all, self.actor_a,
            {self.shared_batch: 10, self.a1_only: 5, self.no_lot: 2},
        )
        replay_count = await stocktake_api.submit_stocktake_count(
            sid, count_cmd, db=self.db, access=self.access_a_all, legacy_actor=self.actor_a,
        )
        self.assertEqual(replay_count, counted)
        self.assertEqual(int(await self.db.scalar(select(func.count()).select_from(StocktakeCountAttempt).where(StocktakeCountAttempt.stocktake_session_id == sid))), 1)

        approved, approve_cmd = await self._approve(sid, int(counted["attempt_id"]), self.access_a_all, self.actor_a)
        replay_approve = await stocktake_api.approve_stocktake_session(
            sid, approve_cmd, db=self.db, access=self.access_a_all, legacy_actor=self.actor_a,
        )
        self.assertEqual(replay_approve, approved)
        self.assertEqual(approved["movement_count"], 0)
        self.assertEqual(int(await self.db.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.stocktake_session_id == sid))) or 0, 0)
        self.assertEqual(int(await self.db.scalar(select(func.count()).select_from(InventoryLock).where(InventoryLock.stocktake_session_id == sid, InventoryLock.released_at.is_(None)))) or 0, 0)

        # Positive variance posts authoritative movement/evidence exactly once.
        positive = await self._start(self.a2, self.access_a_all, self.actor_a)
        positive_sid = int(positive["session_id"])
        positive_count, _ = await self._count(
            positive_sid, self.access_a_all, self.actor_a,
            {self.shared_batch: 12, self.a2_only: 5},
        )
        pos_approved, pos_cmd = await self._approve(positive_sid, int(positive_count["attempt_id"]), self.access_a_all, self.actor_a)
        self.assertGreater(pos_approved["movement_count"], 0)
        movement_count = int(await self.db.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.stocktake_session_id == positive_sid)) or 0)
        self.assertEqual(movement_count, pos_approved["movement_count"])
        self.assertEqual(await self.db.scalar(select(InventoryBalance.on_hand_quantity).where(
            InventoryBalance.company_id == self.company_a,
            InventoryBalance.location_id == self.a2,
            InventoryBalance.batch_id == self.shared_batch,
        )), Decimal("12"))
        self.assertEqual(await stocktake_api.approve_stocktake_session(positive_sid, pos_cmd, db=self.db, access=self.access_a_all, legacy_actor=self.actor_a), pos_approved)
        self.assertEqual(int(await self.db.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.stocktake_session_id == positive_sid)) or 0), movement_count)

        # Negative variance must not post before an independent recount.
        negative = await self._start(self.a2, self.access_a_all, self.actor_a)
        negative_sid = int(negative["session_id"])
        negative_count, _ = await self._count(
            negative_sid, self.access_a_all, self.actor_a,
            {self.shared_batch: 9, self.a2_only: 5},
        )
        with self.assertRaises(HTTPException) as direct_negative_approval:
            await self._approve(
                negative_sid, int(negative_count["attempt_id"]),
                self.access_a_all, self.actor_a,
            )
        self.assertEqual(direct_negative_approval.exception.status_code, 409)
        self.assertIn("إعادة عد مستقلة", str(direct_negative_approval.exception.detail))

        negative_recount_cmd = StocktakeRecountCommand(
            request_id=uuid4(),
            count_attempt_id=int(negative_count["attempt_id"]),
            reason="independent recount required for negative variance",
            authorizer_username=self.actor_a2.username,
            authorizer_password=PASSWORD,
        )
        with patch.object(stocktake_api, "_verify_stocktake_admin_credentials", AsyncMock(return_value=self.actor_a2)):
            negative_recount = await stocktake_api.recount_stocktake_session(
                negative_sid, negative_recount_cmd, db=self.db,
                access=self.access_a_all, legacy_actor=self.actor_a,
            )
        self.assertEqual(negative_recount["status"], "RECOUNT_REQUIRED")
        negative_second, _ = await self._count(
            negative_sid, self.access_a_all, self.actor_a2,
            {self.shared_batch: 9, self.a2_only: 5},
        )
        neg_approved, _ = await self._approve(
            negative_sid, int(negative_second["attempt_id"]),
            self.access_a_all, self.actor_a,
        )
        self.assertGreater(neg_approved["movement_count"], 0)
        self.assertEqual(await self.db.scalar(select(InventoryBalance.on_hand_quantity).where(
            InventoryBalance.company_id == self.company_a,
            InventoryBalance.location_id == self.a2,
            InventoryBalance.batch_id == self.shared_batch,
        )), Decimal("9"))

        # Explicit recount remains available as a distinct workflow on a new session.
        recount_started = await self._start(self.a2, self.access_a_all, self.actor_a)
        recount_sid = int(recount_started["session_id"])
        first_attempt, _ = await self._count(
            recount_sid, self.access_a_all, self.actor_a,
            {self.shared_batch: 10, self.a2_only: 5},
        )
        recount_cmd = StocktakeRecountCommand(
            request_id=uuid4(),
            count_attempt_id=int(first_attempt["attempt_id"]),
            reason="independent verification requested",
            authorizer_username=self.actor_a2.username,
            authorizer_password=PASSWORD,
        )
        with patch.object(stocktake_api, "_verify_stocktake_admin_credentials", AsyncMock(return_value=self.actor_a2)):
            recount = await stocktake_api.recount_stocktake_session(
                recount_sid, recount_cmd, db=self.db, access=self.access_a_all, legacy_actor=self.actor_a,
            )
            replay_recount = await stocktake_api.recount_stocktake_session(
                recount_sid, recount_cmd, db=self.db, access=self.access_a_all, legacy_actor=self.actor_a,
            )
        self.assertEqual(replay_recount, recount)
        self.assertEqual(recount["status"], "RECOUNT_REQUIRED")
        self.assertGreater(int(await self.db.scalar(select(func.count()).select_from(InventoryLock).where(InventoryLock.stocktake_session_id == recount_sid, InventoryLock.released_at.is_(None))) or 0), 0)
        second_attempt, _ = await self._count(
            recount_sid, self.access_a_all, self.actor_a2,
            {self.shared_batch: 9, self.a2_only: 5},
        )
        self.assertGreater(int(second_attempt["attempt_number"]), int(first_attempt["attempt_number"]))

        # Cancellation is terminal/idempotent, releases locks once, and creates no movement.
        cancel_started = await self._start(self.a1, self.access_a_all, self.actor_a)
        cancel_sid = int(cancel_started["session_id"])
        movement_before = int(await self.db.scalar(select(func.count()).select_from(InventoryMovement)) or 0)
        cancel_cmd = StocktakeCancelCommand(request_id=uuid4(), password=PASSWORD, reason="operator cancelled acceptance session")
        cancelled = await stocktake_api.cancel_stocktake_session(cancel_sid, cancel_cmd, db=self.db, access=self.access_a_all, legacy_actor=self.actor_a)
        replay_cancel = await stocktake_api.cancel_stocktake_session(cancel_sid, cancel_cmd, db=self.db, access=self.access_a_all, legacy_actor=self.actor_a)
        self.assertEqual(replay_cancel, cancelled)
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(int(await self.db.scalar(select(func.count()).select_from(InventoryLock).where(InventoryLock.stocktake_session_id == cancel_sid, InventoryLock.released_at.is_(None)))) or 0, 0)
        self.assertEqual(int(await self.db.scalar(select(func.count()).select_from(InventoryMovement)) or 0), movement_before)

    async def test_rollback_cp4_blocker_terminal_release_and_query_growth(self):
        # Failure during authoritative posting rolls the session state/lock back atomically.
        started = await self._start(self.a1, self.access_a_all, self.actor_a)
        sid = int(started["session_id"])
        counted, _ = await self._count(
            sid, self.access_a_all, self.actor_a,
            {self.shared_batch: 11, self.a1_only: 5, self.no_lot: 2},
        )
        with patch.object(stocktake_api, "post_approved_stocktake_adjustments", AsyncMock(side_effect=InventoryMutationError("synthetic posting failure"))):
            with self.assertRaises(HTTPException) as failed:
                await self._approve(sid, int(counted["attempt_id"]), self.access_a_all, self.actor_a)
        self.assertEqual(failed.exception.status_code, 409)
        await self.db.rollback()
        session = await self.db.get(StocktakeSession, sid)
        self.assertEqual(session.status, "PENDING_REVIEW")
        self.assertGreater(int(await self.db.scalar(select(func.count()).select_from(InventoryLock).where(InventoryLock.stocktake_session_id == sid, InventoryLock.released_at.is_(None))) or 0), 0)
        self.assertEqual(int(await self.db.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.stocktake_session_id == sid))) or 0, 0)

        # CP4 regression: a non-final stocktake blocks deactivation; terminal stocktake does not remain that blocker.
        raw_session = StocktakeSession(
            company_id=self.company_a,
            reference_number="CP9-BLOCK-" + uuid4().hex[:8],
            stocktake_type="FULL_COUNT",
            status="COUNTING",
            location_id=self.empty,
            started_by=int(self.actor_a.id),
            snapshot_cutoff_at=utc_now().replace(tzinfo=None),
        )
        self.db.add(raw_session)
        await self.db.flush()
        raw_session_id = int(raw_session.id)
        await self.db.commit()
        location_access = SimpleNamespace(company_id=self.company_a)
        with patch.object(warehouse_locations, "_require_location_capability", AsyncMock(return_value=None)), patch.object(warehouse_locations, "acquire_inventory_location_guard", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as blocked:
                await warehouse_locations.deactivate_warehouse_location(
                    self.empty,
                    WarehouseLocationStateRequest(request_id=uuid4(), expected_version=1, reason="CP9 regression"),
                    self.db,
                    location_access,
                    self.actor_a,
                )
            self.assertEqual(blocked.exception.status_code, 409)
            detail = blocked.exception.detail
            self.assertEqual(detail["code"], "LOCATION_DEACTIVATION_BLOCKED")
            self.assertEqual(detail["context"]["blocker_type"], "OPEN_STOCKTAKE")
            await self.db.rollback()
            raw_session = await self.db.get(StocktakeSession, raw_session_id)
            raw_session.status = "CANCELLED"
            raw_session.cancelled_by = int(self.actor_a.id)
            raw_session.cancelled_at = utc_now().replace(tzinfo=None)
            raw_session.cancellation_reason = "CP9 terminal blocker regression"
            await self.db.commit()
            deactivated = await warehouse_locations.deactivate_warehouse_location(
                self.empty,
                WarehouseLocationStateRequest(request_id=uuid4(), expected_version=1, reason="terminal stocktake cleared"),
                self.db,
                location_access,
                self.actor_a,
            )
        self.assertFalse(deactivated["location"]["is_active"])

        # Query-count evidence: fixed-query read paths do not grow per returned row.
        perf_session = await self._start(self.a2, self.access_a_all, self.actor_a)
        perf_sid = int(perf_session["session_id"])
        statements: list[str] = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if str(statement).lstrip().lower().startswith("select"):
                statements.append(str(statement))
        event.listen(self.engine.sync_engine, "before_cursor_execute", capture)
        try:
            statements.clear()
            await stocktake_api.list_active_stocktake_sessions(location_id=self.a1, cursor=None, limit=1, db=self.db, access=self.access_a1)
            active_small = len(statements)
            statements.clear()
            await stocktake_api.list_active_stocktake_sessions(location_id=self.a1, cursor=None, limit=100, db=self.db, access=self.access_a1)
            active_large = len(statements)
            statements.clear()
            await stocktake_api.get_stocktake_count_sheet(
                perf_sid, db=self.db, access=self.access_a_all, legacy_actor=self.actor_a,
            )
            sheet_queries = len(statements)
            statements.clear()
            await stocktake_api.list_stocktake_cycle_batches(location_id=self.a1, product_variant_id=self.variant_a, search=None, cursor=None, limit=1, db=self.db, access=self.access_a1)
            cycle_small = len(statements)
            statements.clear()
            await stocktake_api.list_stocktake_cycle_batches(location_id=self.a1, product_variant_id=self.variant_a, search=None, cursor=None, limit=100, db=self.db, access=self.access_a1)
            cycle_large = len(statements)
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", capture)
        self.assertLessEqual(active_large, active_small + 1)
        self.assertLessEqual(cycle_large, cycle_small + 1)
        self.assertLessEqual(sheet_queries, 6)
        print(f"CP9_QUERY_COUNTS active_small={active_small} active_large={active_large} count_sheet={sheet_queries} cycle_small={cycle_small} cycle_large={cycle_large}", flush=True)


if __name__ == "__main__":
    unittest.main()
