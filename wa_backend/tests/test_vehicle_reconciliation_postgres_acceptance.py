from __future__ import annotations

import asyncio
import os
import re
import time
import unittest
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api import reconciliation as reconciliation_api
from api.warehouse import stocktake as stocktake_api
from domains.vehicles.contracts import CreateVehicleCommand
from domains.vehicles.management import create_vehicle
from models import (
    Base,
    Company,
    DispatchRoute,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    InventoryMovement,
    Product,
    ProductBatch,
    ProductVariant,
    SessionInventorySnapshot,
    StocktakeSession,
    UOM,
    WorkSession,
    Zone,
    utc_now,
)
from schemas import (
    StocktakeApprovalRequest,
    UnifiedStocktakeCountRequest,
    UnifiedStocktakeStartRequest,
)
from services import (
    InventoryMutationError,
    acquire_inventory_location_guard,
    finalize_vehicle_inventory_reconciliation,
    post_approved_stocktake_adjustments,
)
from tests.canonical_actor_fixtures import (
    seed_company_owner_fixture,
    seed_field_fixture,
)


GATE_ENV = "WANASAH_VEHICLE_RECON_POSTGRES_GATE"
SCHEMA_PREFIX = "vehicle_reconciliation_accept_"


@dataclass(frozen=True)
class OperationOutcome:
    kind: str
    code: int | str | None
    detail: str | None
    completed_at: float


class PairBarrier:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._arrivals = 0

    async def wait(self) -> None:
        async with self._condition:
            self._arrivals += 1
            if self._arrivals >= 2:
                self._condition.notify_all()
                return
            await self._condition.wait_for(lambda: self._arrivals >= 2)


def _sqlstate(exc: BaseException) -> str | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        value = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if value:
            return str(value)
        current = getattr(current, "orig", None) or getattr(current, "__cause__", None)
    return None


def _classify(exc: BaseException | None) -> OperationOutcome:
    completed = time.monotonic()
    if exc is None:
        return OperationOutcome("success", None, None, completed)
    if isinstance(exc, HTTPException):
        return OperationOutcome("business_conflict", exc.status_code, str(exc.detail), completed)
    if isinstance(exc, InventoryMutationError):
        return OperationOutcome("domain_conflict", "InventoryMutationError", str(exc), completed)
    state = _sqlstate(exc)
    if state == "40P01":
        return OperationOutcome("deadlock", state, str(exc), completed)
    if state == "55P03":
        return OperationOutcome("lock_timeout", state, str(exc), completed)
    if state == "57014":
        return OperationOutcome("statement_timeout", state, str(exc), completed)
    if isinstance(exc, DBAPIError):
        return OperationOutcome("db_error", state, str(exc), completed)
    return OperationOutcome("error", state, f"{type(exc).__name__}: {exc}", completed)


class VehicleReconciliationPostgresAcceptance(unittest.IsolatedAsyncioTestCase):
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
        cls.schema = SCHEMA_PREFIX + uuid4().hex
        asyncio.run(cls._create_schema())

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
    def _new_engine(cls):
        return create_async_engine(
            cls.raw_url,
            poolclass=NullPool,
            connect_args={
                "server_settings": {
                    "search_path": f'"{cls.schema}",public',
                    "lock_timeout": "3000",
                    "statement_timeout": "10000",
                }
            },
        )

    @classmethod
    def tearDownClass(cls) -> None:
        async def cleanup() -> int:
            admin = create_async_engine(cls.raw_url, poolclass=NullPool)
            try:
                async with admin.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA IF EXISTS "{cls.schema}" CASCADE'))
                    count = await conn.scalar(
                        text("SELECT count(*) FROM pg_namespace WHERE nspname LIKE :prefix"),
                        {"prefix": SCHEMA_PREFIX + "%"},
                    )
                    return int(count or 0)
            finally:
                await admin.dispose()

        leftovers = asyncio.run(cleanup())
        print(f"DISPOSABLE_SCHEMA_CLEANUP={leftovers}", flush=True)
        if leftovers != 0:
            raise AssertionError(f"leftover reconciliation acceptance schemas: {leftovers}")
        super().tearDownClass()

    async def asyncSetUp(self) -> None:
        self.engine = self._new_engine()
        self.Session = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        self.db = self.Session()
        suffix = uuid4().hex[:8]
        company = Company(
            name=f"Recon PG {suffix}",
            company_code=f"RP-{suffix}",
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
        self.field = await seed_field_fixture(
            self.db,
            self.company_id,
            password="SyntheticField123",
        )
        wh_a = InventoryLocation(
            company_id=self.company_id,
            name=f"Warehouse A {suffix}",
            code=f"WHA-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        wh_b = InventoryLocation(
            company_id=self.company_id,
            name=f"Warehouse B {suffix}",
            code=f"WHB-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        self.db.add_all([wh_a, wh_b])
        await self.db.flush()
        self.wh_a_id = int(wh_a.id)
        self.wh_b_id = int(wh_b.id)

        uom = UOM(name=f"Recon Each {suffix}", code=f"E{suffix.upper()}")
        self.db.add(uom)
        await self.db.flush()
        product = Product(
            company_id=self.company_id,
            code=f"P-{suffix}",
            name=f"Recon Product {suffix}",
        )
        self.db.add(product)
        await self.db.flush()
        variant = ProductVariant(
            company_id=self.company_id,
            product_id=int(product.id),
            base_uom_id=int(uom.id),
            name=f"Recon Variant {suffix}",
            sku=f"R-{suffix}",
            quantity_scale=0,
            quantity_step=1,
            lot_control_mode="NONE",
            expiry_control_mode="NONE",
            lifecycle_status="ACTIVE",
            operational_hold="NONE",
            lifecycle_revision=1,
            version=1,
            published_at=utc_now().replace(tzinfo=None),
            packs_per_carton=10,
        )
        self.db.add(variant)
        await self.db.commit()
        self.variant_id = int(variant.id)
        self.uom_id = int(uom.id)

    async def asyncTearDown(self) -> None:
        try:
            await self.db.rollback()
        except Exception:
            pass
        await self.db.close()
        await self.engine.dispose()

    async def _count(self, model, *criteria) -> int:
        return int(
            await self.db.scalar(select(func.count()).select_from(model).where(*criteria))
            or 0
        )

    async def _create_vehicle(self, *, plate: str | None = None) -> tuple[int, int]:
        plate = plate or ("RPG-" + uuid4().hex[:12])
        payload = await create_vehicle(
            self.db,
            company_id=self.company_id,
            actor_id=self.owner.driver_id,
            command=CreateVehicleCommand(
                request_id=str(uuid4()),
                plate_number=plate,
                vehicle_type="Van",
                maintenance_status="Active",
            ),
        )
        vehicle_id = int(payload["id"])
        rows = (
            await self.db.execute(
                select(InventoryLocation).where(
                    InventoryLocation.company_id == self.company_id,
                    InventoryLocation.vehicle_id == vehicle_id,
                    InventoryLocation.location_type == "VEHICLE",
                )
            )
        ).scalars().all()
        self.assertEqual(len(rows), 1)
        return vehicle_id, int(rows[0].id)

    async def _add_history(self, vehicle_id: int, *, active: bool = False, label: str = "HIST") -> int:
        row = InventoryLocation(
            company_id=self.company_id,
            name=f"{label} {uuid4().hex[:8]}",
            code=f"VR-{label[:8]}-{uuid4().hex[:12]}",
            location_type="VEHICLE",
            vehicle_id=vehicle_id,
            is_active=active,
            version=1,
        )
        self.db.add(row)
        await self.db.flush()
        return int(row.id)

    async def _seed_balance(self, location_id: int, quantity: int) -> int:
        batch = ProductBatch(
            company_id=self.company_id,
            product_variant_id=self.variant_id,
            batch_number=f"RB-{uuid4().hex[:16]}",
            disposition="RELEASED",
            is_active=True,
        )
        self.db.add(batch)
        await self.db.flush()
        self.db.add(
            InventoryBalance(
                company_id=self.company_id,
                location_id=location_id,
                product_variant_id=self.variant_id,
                batch_id=int(batch.id),
                stock_status="AVAILABLE",
                on_hand_quantity=Decimal(quantity),
                reserved_quantity=Decimal("0"),
            )
        )
        await self.db.flush()
        return int(batch.id)

    async def _seed_ended_session(
        self,
        *,
        balance_quantity: int = 0,
        seed_snapshot: bool = False,
    ):
        vehicle_id, custody_id = await self._create_vehicle()
        zone = Zone(
            company_id=self.company_id,
            name=f"Recon Zone {uuid4().hex[:10]}",
        )
        self.db.add(zone)
        await self.db.flush()
        ended_at = utc_now().replace(tzinfo=None)
        work = WorkSession(
            company_id=self.company_id,
            driver_id=int(self.field.driver.id),
            session_date=date.today(),
            start_time=ended_at - timedelta(hours=1),
            end_time=ended_at,
            is_authorized_to_sell=False,
            is_settled=False,
        )
        self.db.add(work)
        await self.db.flush()
        route = DispatchRoute(
            company_id=self.company_id,
            zone_id=int(zone.id),
            driver_id=int(self.field.driver.id),
            vehicle_id=vehicle_id,
            work_session_id=int(work.id),
            source_location_id=self.wh_a_id,
            dispatch_date=date.today(),
            status="closed",
        )
        self.db.add(route)
        await self.db.flush()
        batch_id = None
        if balance_quantity:
            batch_id = await self._seed_balance(custody_id, balance_quantity)
            if seed_snapshot:
                self.db.add(
                    SessionInventorySnapshot(
                        company_id=self.company_id,
                        work_session_id=int(work.id),
                        location_id=custody_id,
                        product_variant_id=self.variant_id,
                        stock_status="AVAILABLE",
                        starting_quantity=Decimal(balance_quantity),
                    )
                )
                await self.db.flush()
        await self.db.commit()
        return SimpleNamespace(
            vehicle_id=vehicle_id,
            custody_id=custody_id,
            work_session_id=int(work.id),
            route_id=int(route.id),
            batch_id=batch_id,
            field_context=self.field.context,
            field_driver=self.field.driver,
        )

    async def _balance_total(self, db: AsyncSession, location_id: int) -> Decimal:
        value = await db.scalar(
            select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
                InventoryBalance.company_id == self.company_id,
                InventoryBalance.location_id == location_id,
            )
        )
        return Decimal(value or 0)

    async def _movement_count(
        self,
        db: AsyncSession,
        *,
        work_session_id: int | None = None,
        stocktake_session_id: int | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.company_id == self.company_id
        )
        if work_session_id is not None:
            stmt = stmt.where(InventoryMovement.work_session_id == work_session_id)
        if stocktake_session_id is not None:
            stmt = stmt.where(InventoryMovement.stocktake_session_id == stocktake_session_id)
        return int(await db.scalar(stmt) or 0)

    async def _stocktake_count(self, db: AsyncSession, work_session_id: int) -> int:
        return int(
            await db.scalar(
                select(func.count()).select_from(StocktakeSession).where(
                    StocktakeSession.company_id == self.company_id,
                    StocktakeSession.stocktake_type == "VEHICLE_RECON",
                    StocktakeSession.related_work_session_id == work_session_id,
                )
            )
            or 0
        )

    def _eod_payload(self, actual_quantity: int | None = None):
        counts = []
        if actual_quantity is not None:
            counts = [
                {
                    "product_variant_id": self.variant_id,
                    "actual_quantity": Decimal(actual_quantity),
                }
            ]
        return reconciliation_api.VehicleReconciliationRequest(counts=counts)

    async def _run_eod(self, db: AsyncSession, ctx, *, actual_quantity: int | None = None):
        return await reconciliation_api.reconcile_driver_end_of_day(
            ctx.work_session_id,
            self._eod_payload(actual_quantity),
            db=db,
            field_context=ctx.field_context,
            legacy_actor=ctx.field_driver,
        )

    async def _start_recon(self, ctx, *, location_id: int | None = None, db: AsyncSession | None = None):
        db = db or self.db
        return await stocktake_api.start_unified_stocktake(
            UnifiedStocktakeStartRequest(
                location_id=int(location_id if location_id is not None else ctx.custody_id),
                stocktake_type="VEHICLE_RECON",
                related_work_session_id=ctx.work_session_id,
            ),
            db=db,
            access=self.owner.access(db),
            legacy_actor=self.owner.operational_driver,
        )

    async def _submit_count(
        self,
        ctx,
        stocktake_id: int,
        *,
        actual_quantity: int,
        db: AsyncSession | None = None,
    ):
        db = db or self.db
        self.assertIsNotNone(ctx.batch_id)
        return await stocktake_api.submit_stocktake_count(
            stocktake_id,
            UnifiedStocktakeCountRequest(
                items=[
                    {
                        "product_variant_id": self.variant_id,
                        "batch_id": int(ctx.batch_id),
                        "stock_status": "AVAILABLE",
                        "actual_quantity": Decimal(actual_quantity),
                        "uom_id": self.uom_id,
                    }
                ]
            ),
            db=db,
            access=self.owner.access(db),
            legacy_actor=self.owner.operational_driver,
        )

    async def _approve(
        self,
        stocktake_id: int,
        attempt_id: int,
        *,
        db: AsyncSession | None = None,
    ):
        db = db or self.db
        return await stocktake_api.approve_stocktake_session(
            stocktake_id,
            StocktakeApprovalRequest(
                count_attempt_id=attempt_id,
                password="SyntheticOwner123",
            ),
            db=db,
            access=self.owner.access(db),
            legacy_actor=self.owner.operational_driver,
        )

    async def _assert_rejected_eod_safe(self, ctx, *, expected_status: int = 409) -> None:
        before_movements = await self._movement_count(
            self.db,
            work_session_id=ctx.work_session_id,
        )
        before_stocktakes = await self._stocktake_count(self.db, ctx.work_session_id)
        with self.assertRaises(HTTPException) as caught:
            await self._run_eod(self.db, ctx)
        self.assertEqual(caught.exception.status_code, expected_status)
        self.assertLess(caught.exception.status_code, 500)
        work = await self.db.get(WorkSession, ctx.work_session_id)
        self.assertIsNone(work.inventory_reconciled_at)
        self.assertIsNone(work.inventory_reconciled_by)
        self.assertEqual(
            await self._movement_count(self.db, work_session_id=ctx.work_session_id),
            before_movements,
        )
        self.assertEqual(
            await self._stocktake_count(self.db, ctx.work_session_id),
            before_stocktakes,
        )

    async def _assert_no_partial_start(self, ctx, location_id: int, call) -> HTTPException:
        before_sessions = await self._stocktake_count(self.db, ctx.work_session_id)
        before_locks = await self._count(
            InventoryLock,
            InventoryLock.company_id == self.company_id,
            InventoryLock.location_id == location_id,
        )
        with self.assertRaises(HTTPException) as caught:
            await call()
        self.assertLess(caught.exception.status_code, 500)
        self.assertEqual(await self._stocktake_count(self.db, ctx.work_session_id), before_sessions)
        self.assertEqual(
            await self._count(
                InventoryLock,
                InventoryLock.company_id == self.company_id,
                InventoryLock.location_id == location_id,
            ),
            before_locks,
        )
        return caught.exception

    async def _read_post_state(self, ctx, stocktake_id: int):
        async with self.Session() as db:
            session = await db.get(StocktakeSession, stocktake_id)
            work = await db.get(WorkSession, ctx.work_session_id)
            snapshot = await db.scalar(
                select(SessionInventorySnapshot).where(
                    SessionInventorySnapshot.company_id == self.company_id,
                    SessionInventorySnapshot.work_session_id == ctx.work_session_id,
                    SessionInventorySnapshot.product_variant_id == self.variant_id,
                    SessionInventorySnapshot.stock_status == "AVAILABLE",
                )
            )
            balance = await self._balance_total(db, ctx.custody_id)
            movements = await self._movement_count(db, stocktake_session_id=stocktake_id)
            return SimpleNamespace(
                session=session,
                work=work,
                snapshot=snapshot,
                balance=balance,
                movements=movements,
            )

    async def test_01_eod_canonical_exact_match_succeeds(self):
        ctx = await self._seed_ended_session(balance_quantity=5, seed_snapshot=True)
        before_movements = await self._movement_count(self.db, work_session_id=ctx.work_session_id)
        result = await self._run_eod(self.db, ctx, actual_quantity=5)
        self.assertFalse(result["requires_audit"])
        self.assertFalse(result["already_reconciled"])
        work = await self.db.get(WorkSession, ctx.work_session_id)
        snapshot = await self.db.scalar(
            select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id == self.company_id,
                SessionInventorySnapshot.work_session_id == ctx.work_session_id,
            )
        )
        self.assertIsNotNone(work.inventory_reconciled_at)
        self.assertEqual(int(work.inventory_reconciled_by), int(self.field.driver.id))
        self.assertEqual(Decimal(snapshot.ending_quantity), Decimal("5"))
        self.assertEqual(int(snapshot.settled_by), int(self.field.driver.id))
        self.assertIsNotNone(snapshot.settled_at)
        self.assertEqual(
            await self._movement_count(self.db, work_session_id=ctx.work_session_id),
            before_movements,
        )
        self.assertEqual(await self._stocktake_count(self.db, ctx.work_session_id), 0)

    async def test_02_eod_active_plus_historical_duplicate_fails_closed(self):
        ctx = await self._seed_ended_session()
        await self._add_history(ctx.vehicle_id, active=False, label="EODDUP")
        await self.db.commit()
        await self._assert_rejected_eod_safe(ctx)

    async def test_03_eod_missing_custody_fails_closed(self):
        ctx = await self._seed_ended_session()
        await self.db.execute(
            delete(InventoryLocation).where(
                InventoryLocation.company_id == self.company_id,
                InventoryLocation.id == ctx.custody_id,
            )
        )
        await self.db.commit()
        await self._assert_rejected_eod_safe(ctx)

    async def test_04_eod_single_inactive_custody_fails_closed(self):
        ctx = await self._seed_ended_session()
        custody = await self.db.get(InventoryLocation, ctx.custody_id)
        custody.is_active = False
        await self.db.commit()
        await self._assert_rejected_eod_safe(ctx)

    async def test_05_vehicle_recon_start_canonical_succeeds(self):
        ctx = await self._seed_ended_session()
        result = await self._start_recon(ctx)
        stocktake_id = int(result["session_id"])
        session = await self.db.get(StocktakeSession, stocktake_id)
        self.assertEqual(session.status, "COUNTING")
        self.assertEqual(session.stocktake_type, "VEHICLE_RECON")
        self.assertEqual(int(session.location_id), ctx.custody_id)
        self.assertEqual(int(session.related_work_session_id), ctx.work_session_id)
        locks = await self._count(
            InventoryLock,
            InventoryLock.company_id == self.company_id,
            InventoryLock.stocktake_session_id == stocktake_id,
            InventoryLock.released_at.is_(None),
        )
        self.assertEqual(locks, 1)

    async def test_06_vehicle_recon_start_ambiguous_rejects_without_artifacts(self):
        ctx = await self._seed_ended_session()
        await self._add_history(ctx.vehicle_id, active=False, label="STARTDUP")
        await self.db.commit()
        exc = await self._assert_no_partial_start(
            ctx,
            ctx.custody_id,
            lambda: self._start_recon(ctx),
        )
        self.assertEqual(exc.status_code, 409)

    async def test_07_vehicle_recon_start_wrong_warehouse_location_rejects_without_artifacts(self):
        ctx = await self._seed_ended_session()
        exc = await self._assert_no_partial_start(
            ctx,
            self.wh_b_id,
            lambda: self._start_recon(ctx, location_id=self.wh_b_id),
        )
        self.assertEqual(exc.status_code, 404)

    async def test_08_vehicle_recon_start_other_vehicle_location_rejects_without_artifacts(self):
        ctx = await self._seed_ended_session()
        _, other_custody_id = await self._create_vehicle()
        await self.db.commit()
        exc = await self._assert_no_partial_start(
            ctx,
            other_custody_id,
            lambda: self._start_recon(ctx, location_id=other_custody_id),
        )
        self.assertEqual(exc.status_code, 409)

    async def test_09_post_rejects_ambiguity_introduced_after_valid_start(self):
        ctx = await self._seed_ended_session(balance_quantity=5, seed_snapshot=True)
        opened = await self._start_recon(ctx)
        stocktake_id = int(opened["session_id"])
        counted = await self._submit_count(ctx, stocktake_id, actual_quantity=6)
        attempt_id = int(counted["attempt_id"])
        await self._add_history(ctx.vehicle_id, active=False, label="POSTDUP")
        await self.db.commit()

        before_balance = await self._balance_total(self.db, ctx.custody_id)
        before_movements = await self._movement_count(
            self.db,
            stocktake_session_id=stocktake_id,
        )
        before_snapshot = await self.db.scalar(
            select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id == self.company_id,
                SessionInventorySnapshot.work_session_id == ctx.work_session_id,
            )
        )
        self.assertIsNone(before_snapshot.ending_quantity)

        with self.assertRaises(HTTPException) as caught:
            await self._approve(stocktake_id, attempt_id)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertLess(caught.exception.status_code, 500)

        state = await self._read_post_state(ctx, stocktake_id)
        self.assertEqual(state.balance, before_balance)
        self.assertEqual(state.movements, before_movements)
        self.assertEqual(state.session.status, "PENDING_REVIEW")
        self.assertIsNone(state.session.posted_at)
        self.assertIsNone(state.session.approved_at)
        self.assertIsNone(state.work.inventory_reconciled_at)
        self.assertIsNone(state.work.inventory_reconciled_by)
        self.assertIsNotNone(state.snapshot)
        self.assertIsNone(state.snapshot.ending_quantity)
        self.assertIsNone(state.snapshot.settled_by)
        self.assertIsNone(state.snapshot.settled_at)

    async def test_10_seal_rejects_ambiguity_without_snapshot_or_session_partial_state(self):
        ctx = await self._seed_ended_session(balance_quantity=5, seed_snapshot=True)
        await self._add_history(ctx.vehicle_id, active=False, label="SEALDUP")
        await self.db.commit()
        before_balance = await self._balance_total(self.db, ctx.custody_id)
        before_movements = await self._movement_count(
            self.db,
            work_session_id=ctx.work_session_id,
        )

        with self.assertRaises(InventoryMutationError):
            await finalize_vehicle_inventory_reconciliation(
                self.db,
                company_id=self.company_id,
                work_session_id=ctx.work_session_id,
                vehicle_location_id=ctx.custody_id,
                settled_by=int(self.field.driver.id),
            )
        await self.db.rollback()

        work = await self.db.get(WorkSession, ctx.work_session_id)
        snapshot = await self.db.scalar(
            select(SessionInventorySnapshot).where(
                SessionInventorySnapshot.company_id == self.company_id,
                SessionInventorySnapshot.work_session_id == ctx.work_session_id,
            )
        )
        self.assertIsNone(work.inventory_reconciled_at)
        self.assertIsNone(work.inventory_reconciled_by)
        self.assertIsNone(snapshot.ending_quantity)
        self.assertIsNone(snapshot.settled_by)
        self.assertIsNone(snapshot.settled_at)
        self.assertEqual(await self._balance_total(self.db, ctx.custody_id), before_balance)
        self.assertEqual(
            await self._movement_count(self.db, work_session_id=ctx.work_session_id),
            before_movements,
        )

    async def _canonical_post_setup(self):
        ctx = await self._seed_ended_session(balance_quantity=5, seed_snapshot=True)
        opened = await self._start_recon(ctx)
        stocktake_id = int(opened["session_id"])
        counted = await self._submit_count(ctx, stocktake_id, actual_quantity=6)
        attempt_id = int(counted["attempt_id"])
        return ctx, stocktake_id, attempt_id

    async def test_11_canonical_post_and_seal_apply_exactly_one_surplus(self):
        ctx, stocktake_id, attempt_id = await self._canonical_post_setup()
        result = await self._approve(stocktake_id, attempt_id)
        self.assertEqual(result["status"], "POSTED")
        self.assertEqual(int(result["movement_count"]), 1)

        state = await self._read_post_state(ctx, stocktake_id)
        self.assertEqual(state.session.status, "POSTED")
        self.assertIsNotNone(state.session.posted_at)
        self.assertEqual(state.balance, Decimal("6"))
        self.assertEqual(state.movements, 1)
        self.assertIsNotNone(state.work.inventory_reconciled_at)
        self.assertEqual(
            int(state.work.inventory_reconciled_by),
            int(self.owner.operational_driver.id),
        )
        self.assertIsNotNone(state.snapshot)
        self.assertEqual(Decimal(state.snapshot.starting_quantity), Decimal("5"))
        self.assertEqual(Decimal(state.snapshot.ending_quantity), Decimal("6"))
        self.assertEqual(int(state.snapshot.settled_by), int(self.owner.operational_driver.id))
        self.assertIsNotNone(state.snapshot.settled_at)

        async with self.Session() as db:
            movement = await db.scalar(
                select(InventoryMovement).where(
                    InventoryMovement.company_id == self.company_id,
                    InventoryMovement.stocktake_session_id == stocktake_id,
                )
            )
            self.assertIsNotNone(movement)
            self.assertEqual(movement.reference_type, "DRIVER_SURPLUS")
            self.assertEqual(Decimal(movement.quantity), Decimal("1"))
            self.assertIsNone(movement.source_location_id)
            self.assertEqual(int(movement.destination_location_id), ctx.custody_id)
            active_locks = int(
                await db.scalar(
                    select(func.count()).select_from(InventoryLock).where(
                        InventoryLock.company_id == self.company_id,
                        InventoryLock.stocktake_session_id == stocktake_id,
                        InventoryLock.released_at.is_(None),
                    )
                )
                or 0
            )
            self.assertEqual(active_locks, 0)

    async def test_12_posted_replay_is_idempotent_and_creates_no_duplicate_effect(self):
        ctx, stocktake_id, attempt_id = await self._canonical_post_setup()
        await self._approve(stocktake_id, attempt_id)
        before = await self._read_post_state(ctx, stocktake_id)
        before_stamp = before.work.inventory_reconciled_at
        before_stocktakes = await self._stocktake_count(self.db, ctx.work_session_id)

        replay = await post_approved_stocktake_adjustments(
            self.db,
            company_id=self.company_id,
            stocktake_session_id=stocktake_id,
            stocktake_count_attempt_id=attempt_id,
            performed_by=int(self.owner.operational_driver.id),
        )
        await self.db.commit()
        self.assertEqual(len(replay), 1)

        after = await self._read_post_state(ctx, stocktake_id)
        self.assertEqual(after.balance, before.balance)
        self.assertEqual(after.movements, before.movements)
        self.assertEqual(after.work.inventory_reconciled_at, before_stamp)
        self.assertEqual(await self._stocktake_count(self.db, ctx.work_session_id), before_stocktakes)

    async def test_13_ordinary_warehouse_full_count_is_unaffected(self):
        batch_id = await self._seed_balance(self.wh_b_id, 5)
        await self.db.commit()
        started = await stocktake_api.start_unified_stocktake(
            UnifiedStocktakeStartRequest(
                location_id=self.wh_b_id,
                stocktake_type="FULL_COUNT",
            ),
            db=self.db,
            access=self.owner.access(self.db),
            legacy_actor=self.owner.operational_driver,
        )
        stocktake_id = int(started["session_id"])
        counted = await stocktake_api.submit_stocktake_count(
            stocktake_id,
            UnifiedStocktakeCountRequest(
                items=[
                    {
                        "product_variant_id": self.variant_id,
                        "batch_id": batch_id,
                        "stock_status": "AVAILABLE",
                        "actual_quantity": Decimal("5"),
                        "uom_id": self.uom_id,
                    }
                ]
            ),
            db=self.db,
            access=self.owner.access(self.db),
            legacy_actor=self.owner.operational_driver,
        )
        approved = await stocktake_api.approve_stocktake_session(
            stocktake_id,
            StocktakeApprovalRequest(
                count_attempt_id=int(counted["attempt_id"]),
                password="SyntheticOwner123",
            ),
            db=self.db,
            access=self.owner.access(self.db),
            legacy_actor=self.owner.operational_driver,
        )
        self.assertEqual(approved["status"], "POSTED")
        self.assertEqual(approved["movement_count"], 0)
        session = await self.db.get(StocktakeSession, stocktake_id)
        self.assertEqual(session.stocktake_type, "FULL_COUNT")
        self.assertIsNone(session.related_work_session_id)
        self.assertEqual(await self._balance_total(self.db, self.wh_b_id), Decimal("5"))
        vehicle_rows = await self._count(
            InventoryLocation,
            InventoryLocation.company_id == self.company_id,
            InventoryLocation.location_type == "VEHICLE",
        )
        self.assertEqual(vehicle_rows, 0)

    async def _concurrent_history_insert(self, ctx, barrier: PairBarrier, *, label: str) -> OperationOutcome:
        async with self.Session() as db:
            exc: BaseException | None = None
            try:
                await barrier.wait()
                await acquire_inventory_location_guard(
                    db,
                    self.company_id,
                    ctx.custody_id,
                    exclusive=True,
                )
                db.add(
                    InventoryLocation(
                        company_id=self.company_id,
                        name=f"Concurrent history {label} {uuid4().hex[:8]}",
                        code=f"CR-{label[:6]}-{uuid4().hex[:12]}",
                        location_type="VEHICLE",
                        vehicle_id=ctx.vehicle_id,
                        is_active=False,
                        version=1,
                    )
                )
                await db.flush()
                await db.commit()
            except BaseException as caught:
                exc = caught
                await db.rollback()
            return _classify(exc)

    def _assert_concurrency_outcomes(
        self,
        operational: OperationOutcome,
        ambiguity: OperationOutcome,
    ) -> None:
        forbidden = {"deadlock", "lock_timeout", "statement_timeout", "db_error", "error"}
        self.assertNotIn(operational.kind, forbidden, operational)
        self.assertNotIn(ambiguity.kind, forbidden, ambiguity)
        self.assertEqual(ambiguity.kind, "success", ambiguity)
        self.assertIn(operational.kind, {"success", "business_conflict", "domain_conflict"})
        if operational.kind != "success":
            if isinstance(operational.code, int):
                self.assertGreaterEqual(operational.code, 400)
                self.assertLess(operational.code, 500)
            self.assertLessEqual(ambiguity.completed_at, operational.completed_at)
        else:
            self.assertLessEqual(operational.completed_at, ambiguity.completed_at)

    async def test_14_concurrent_recon_post_vs_ambiguity_has_no_stale_custody_commit(self):
        ctx, stocktake_id, attempt_id = await self._canonical_post_setup()
        barrier = PairBarrier()
        vehicle_row_locks: list[str] = []

        def capture_vehicle_locks(conn, cursor, statement, parameters, context, executemany):
            normalized = " ".join(str(statement).lower().split())
            if re.search(r"\bfrom\s+vehicles\b", normalized) and "for update" in normalized:
                vehicle_row_locks.append(str(statement))

        event.listen(self.engine.sync_engine, "before_cursor_execute", capture_vehicle_locks)
        try:
            async def post_operation() -> OperationOutcome:
                async with self.Session() as db:
                    exc: BaseException | None = None
                    try:
                        await barrier.wait()
                        await self._approve(stocktake_id, attempt_id, db=db)
                    except BaseException as caught:
                        exc = caught
                        try:
                            await db.rollback()
                        except Exception:
                            pass
                    return _classify(exc)

            post_outcome, ambiguity_outcome = await asyncio.gather(
                post_operation(),
                self._concurrent_history_insert(ctx, barrier, label="POST"),
            )
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", capture_vehicle_locks)

        self._assert_concurrency_outcomes(post_outcome, ambiguity_outcome)
        self.assertFalse(vehicle_row_locks, f"reverse Vehicle row lock observed: {vehicle_row_locks[:1]}")

        state = await self._read_post_state(ctx, stocktake_id)
        async with self.Session() as db:
            custody_count = int(
                await db.scalar(
                    select(func.count()).select_from(InventoryLocation).where(
                        InventoryLocation.company_id == self.company_id,
                        InventoryLocation.vehicle_id == ctx.vehicle_id,
                        InventoryLocation.location_type == "VEHICLE",
                    )
                )
                or 0
            )
        self.assertEqual(custody_count, 2)
        if post_outcome.kind == "success":
            self.assertEqual(state.session.status, "POSTED")
            self.assertEqual(state.balance, Decimal("6"))
            self.assertEqual(state.movements, 1)
            self.assertIsNotNone(state.work.inventory_reconciled_at)
        else:
            self.assertEqual(state.session.status, "PENDING_REVIEW")
            self.assertEqual(state.balance, Decimal("5"))
            self.assertEqual(state.movements, 0)
            self.assertIsNone(state.work.inventory_reconciled_at)
            self.assertIsNone(state.snapshot.ending_quantity)
        print(
            "CONCURRENCY_EVIDENCE post_vs_ambiguity "
            f"post={post_outcome.kind}:{post_outcome.code} "
            f"ambiguity={ambiguity_outcome.kind}:{ambiguity_outcome.code}",
            flush=True,
        )

    async def test_15_concurrent_eod_vs_ambiguity_has_no_stale_custody_commit(self):
        ctx = await self._seed_ended_session(balance_quantity=5, seed_snapshot=True)
        barrier = PairBarrier()
        vehicle_row_locks: list[str] = []

        def capture_vehicle_locks(conn, cursor, statement, parameters, context, executemany):
            normalized = " ".join(str(statement).lower().split())
            if re.search(r"\bfrom\s+vehicles\b", normalized) and "for update" in normalized:
                vehicle_row_locks.append(str(statement))

        event.listen(self.engine.sync_engine, "before_cursor_execute", capture_vehicle_locks)
        try:
            async def eod_operation() -> OperationOutcome:
                async with self.Session() as db:
                    exc: BaseException | None = None
                    try:
                        await barrier.wait()
                        await self._run_eod(db, ctx, actual_quantity=5)
                    except BaseException as caught:
                        exc = caught
                        try:
                            await db.rollback()
                        except Exception:
                            pass
                    return _classify(exc)

            eod_outcome, ambiguity_outcome = await asyncio.gather(
                eod_operation(),
                self._concurrent_history_insert(ctx, barrier, label="EOD"),
            )
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", capture_vehicle_locks)

        self._assert_concurrency_outcomes(eod_outcome, ambiguity_outcome)
        self.assertFalse(vehicle_row_locks, f"reverse Vehicle row lock observed: {vehicle_row_locks[:1]}")

        async with self.Session() as db:
            work = await db.get(WorkSession, ctx.work_session_id)
            snapshot = await db.scalar(
                select(SessionInventorySnapshot).where(
                    SessionInventorySnapshot.company_id == self.company_id,
                    SessionInventorySnapshot.work_session_id == ctx.work_session_id,
                )
            )
            balance = await self._balance_total(db, ctx.custody_id)
            movements = await self._movement_count(db, work_session_id=ctx.work_session_id)
            stocktakes = await self._stocktake_count(db, ctx.work_session_id)
            custody_count = int(
                await db.scalar(
                    select(func.count()).select_from(InventoryLocation).where(
                        InventoryLocation.company_id == self.company_id,
                        InventoryLocation.vehicle_id == ctx.vehicle_id,
                        InventoryLocation.location_type == "VEHICLE",
                    )
                )
                or 0
            )
        self.assertEqual(custody_count, 2)
        self.assertEqual(balance, Decimal("5"))
        self.assertEqual(movements, 0)
        self.assertEqual(stocktakes, 0)
        if eod_outcome.kind == "success":
            self.assertIsNotNone(work.inventory_reconciled_at)
            self.assertEqual(Decimal(snapshot.ending_quantity), Decimal("5"))
        else:
            self.assertIsNone(work.inventory_reconciled_at)
            self.assertIsNone(work.inventory_reconciled_by)
            self.assertIsNone(snapshot.ending_quantity)
            self.assertIsNone(snapshot.settled_by)
            self.assertIsNone(snapshot.settled_at)
        print(
            "CONCURRENCY_EVIDENCE eod_vs_ambiguity "
            f"eod={eod_outcome.kind}:{eod_outcome.code} "
            f"ambiguity={ambiguity_outcome.kind}:{ambiguity_outcome.code}",
            flush=True,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
