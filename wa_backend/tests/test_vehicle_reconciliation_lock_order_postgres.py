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
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import event, func, select, text
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
import services
from services import InventoryMutationError
from tests.canonical_actor_fixtures import seed_company_owner_fixture, seed_field_fixture


GATE_ENV = "WANASAH_VEHICLE_RECON_LOCK_ORDER_DB_GATE"
SCHEMA_PREFIX = "vehicle_recon_lock_order_"


@dataclass(frozen=True)
class Outcome:
    kind: str
    code: int | str | None
    detail: str


def _sqlstate(exc: BaseException | None) -> str | None:
    current = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        value = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if value:
            return str(value)
        orig = getattr(current, "orig", None)
        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        current = orig or cause or context
    return None


def _classify(exc: BaseException | None) -> Outcome:
    if exc is None:
        return Outcome("serialized_success", None, "success")
    state = _sqlstate(exc)
    if state == "40P01":
        return Outcome("postgresql_deadlock", state, str(exc))
    if state == "55P03":
        return Outcome("lock_timeout", state, str(exc))
    if state == "57014":
        return Outcome("statement_timeout", state, str(exc))
    if isinstance(exc, HTTPException):
        kind = "controlled_business_conflict" if 400 <= exc.status_code < 500 else "http_error"
        return Outcome(kind, exc.status_code, str(exc.detail))
    if isinstance(exc, InventoryMutationError):
        return Outcome("controlled_business_conflict", "InventoryMutationError", str(exc))
    if isinstance(exc, DBAPIError):
        return Outcome("db_error", state, str(exc))
    return Outcome("error", state, f"{type(exc).__name__}: {exc}")


class VehicleReconciliationLockOrderPostgres(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if os.environ.get(GATE_ENV) != "1":
            raise unittest.SkipTest(f"set {GATE_ENV}=1 to run the real PostgreSQL lock-order gate")
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
                    "statement_timeout": "12000",
                    "deadlock_timeout": "3000",
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
                    return int(
                        await conn.scalar(
                            text("SELECT count(*) FROM pg_namespace WHERE nspname LIKE :prefix"),
                            {"prefix": SCHEMA_PREFIX + "%"},
                        )
                        or 0
                    )
            finally:
                await admin.dispose()

        leftovers = asyncio.run(cleanup())
        print(f"DISPOSABLE_SCHEMA_CLEANUP={leftovers}", flush=True)
        if leftovers != 0:
            raise AssertionError(f"leftover lock-order schemas: {leftovers}")
        super().tearDownClass()

    async def asyncSetUp(self) -> None:
        self.engine = self._new_engine()
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.db = self.Session()
        suffix = uuid4().hex[:8]
        company = Company(
            name=f"Recon Lock Order {suffix}",
            company_code=f"RLO-{suffix}",
            timezone="UTC",
        )
        self.db.add(company)
        await self.db.flush()
        self.company_id = int(company.id)
        self.owner = await seed_company_owner_fixture(
            self.db, self.company_id, password="SyntheticOwner123"
        )
        self.field = await seed_field_fixture(
            self.db, self.company_id, password="SyntheticField123"
        )
        warehouse = InventoryLocation(
            company_id=self.company_id,
            name=f"Warehouse {suffix}",
            code=f"WH-{suffix}",
            location_type="WAREHOUSE",
            is_active=True,
        )
        self.db.add(warehouse)
        await self.db.flush()
        self.warehouse_id = int(warehouse.id)
        uom = UOM(name=f"Each {suffix}", code=f"E{suffix.upper()}")
        self.db.add(uom)
        await self.db.flush()
        product = Product(company_id=self.company_id, code=f"P-{suffix}", name=f"P {suffix}")
        self.db.add(product)
        await self.db.flush()
        variant = ProductVariant(
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
            packs_per_carton=10,
        )
        self.db.add(variant)
        await self.db.commit()
        self.variant_id = int(variant.id)
        self.uom_id = int(uom.id)
        self.vehicle_row_locks: list[str] = []

        def capture_vehicle_for_update(conn, cursor, statement, parameters, context, executemany):
            normalized = " ".join(str(statement).lower().split())
            if re.search(r"\bfrom\s+vehicles\b", normalized) and "for update" in normalized:
                self.vehicle_row_locks.append(str(statement))

        self._sql_listener = capture_vehicle_for_update
        event.listen(self.engine.sync_engine, "before_cursor_execute", self._sql_listener)

    async def asyncTearDown(self) -> None:
        event.remove(self.engine.sync_engine, "before_cursor_execute", self._sql_listener)
        try:
            await self.db.rollback()
        except Exception:
            pass
        await self.db.close()
        await self.engine.dispose()

    async def _create_vehicle(self) -> tuple[int, int]:
        payload = await create_vehicle(
            self.db,
            company_id=self.company_id,
            actor_id=self.owner.driver_id,
            command=CreateVehicleCommand(
                request_id=str(uuid4()),
                plate_number="RLO-" + uuid4().hex[:12],
                vehicle_type="Van",
                maintenance_status="Active",
            ),
        )
        vehicle_id = int(payload["id"])
        custody = await self.db.scalar(
            select(InventoryLocation).where(
                InventoryLocation.company_id == self.company_id,
                InventoryLocation.vehicle_id == vehicle_id,
                InventoryLocation.location_type == "VEHICLE",
            )
        )
        self.assertIsNotNone(custody)
        return vehicle_id, int(custody.id)

    async def _seed_balance(self, location_id: int, quantity: int = 5) -> int:
        batch = ProductBatch(
            company_id=self.company_id,
            product_variant_id=self.variant_id,
            batch_number="RLO-" + uuid4().hex[:16],
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

    async def _seed_context(self, *, balance: int = 5, snapshot: bool = True):
        vehicle_id, custody_id = await self._create_vehicle()
        zone = Zone(company_id=self.company_id, name="Zone " + uuid4().hex[:10])
        self.db.add(zone)
        await self.db.flush()
        ended = utc_now().replace(tzinfo=None)
        work = WorkSession(
            company_id=self.company_id,
            driver_id=int(self.field.driver.id),
            session_date=date.today(),
            start_time=ended - timedelta(hours=1),
            end_time=ended,
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
            source_location_id=self.warehouse_id,
            dispatch_date=date.today(),
            status="closed",
        )
        self.db.add(route)
        await self.db.flush()
        batch_id = await self._seed_balance(custody_id, balance)
        if snapshot:
            self.db.add(
                SessionInventorySnapshot(
                    company_id=self.company_id,
                    work_session_id=int(work.id),
                    location_id=custody_id,
                    product_variant_id=self.variant_id,
                    stock_status="AVAILABLE",
                    starting_quantity=Decimal(balance),
                )
            )
        await self.db.commit()
        return SimpleNamespace(
            vehicle_id=vehicle_id,
            custody_id=custody_id,
            work_session_id=int(work.id),
            batch_id=batch_id,
            field_context=self.field.context,
            field_driver=self.field.driver,
        )

    async def _start_recon(self, db: AsyncSession, ctx):
        return await stocktake_api.start_unified_stocktake(
            UnifiedStocktakeStartRequest(
                location_id=ctx.custody_id,
                stocktake_type="VEHICLE_RECON",
                related_work_session_id=ctx.work_session_id,
            ),
            db=db,
            access=self.owner.access(db),
            legacy_actor=self.owner.operational_driver,
        )

    async def _submit_count(self, db: AsyncSession, ctx, stocktake_id: int, actual: int):
        return await stocktake_api.submit_stocktake_count(
            stocktake_id,
            UnifiedStocktakeCountRequest(
                items=[{
                    "product_variant_id": self.variant_id,
                    "batch_id": ctx.batch_id,
                    "stock_status": "AVAILABLE",
                    "actual_quantity": Decimal(actual),
                    "uom_id": self.uom_id,
                }]
            ),
            db=db,
            access=self.owner.access(db),
            legacy_actor=self.owner.operational_driver,
        )

    async def _eod(self, db: AsyncSession, ctx):
        return await reconciliation_api.reconcile_driver_end_of_day(
            ctx.work_session_id,
            reconciliation_api.VehicleReconciliationRequest(
                counts=[{
                    "product_variant_id": self.variant_id,
                    "actual_quantity": Decimal("5"),
                }]
            ),
            db=db,
            field_context=ctx.field_context,
            legacy_actor=ctx.field_driver,
        )

    async def _approve(self, db: AsyncSession, stocktake_id: int, attempt_id: int):
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

    async def _prepare_pending_recon(self):
        ctx = await self._seed_context(balance=5, snapshot=True)
        started = await self._start_recon(self.db, ctx)
        stocktake_id = int(started["session_id"])
        counted = await self._submit_count(self.db, ctx, stocktake_id, actual=6)
        attempt_id = int(counted["attempt_id"])
        session = await self.db.get(StocktakeSession, stocktake_id)
        self.assertEqual(session.status, "PENDING_REVIEW")
        return ctx, stocktake_id, attempt_id

    async def _prepare_approved_recon(self):
        ctx, stocktake_id, attempt_id = await self._prepare_pending_recon()
        session = await self.db.get(StocktakeSession, stocktake_id)
        now = utc_now().replace(tzinfo=None)
        session.status = "APPROVED"
        session.approved_by = int(self.owner.operational_driver.id)
        session.approved_at = now
        session.updated_at = now
        await self.db.commit()
        return ctx, stocktake_id, attempt_id

    async def _backend_pid(self, db: AsyncSession) -> int:
        return int(await db.scalar(text("SELECT pg_backend_pid()")))

    async def _probe_work_session_lock(self, work_session_id: int) -> bool:
        async with self.Session() as probe:
            try:
                await probe.execute(
                    text(
                        "SELECT id FROM work_sessions "
                        "WHERE company_id=:company_id AND id=:work_session_id "
                        "FOR UPDATE NOWAIT"
                    ),
                    {"company_id": self.company_id, "work_session_id": work_session_id},
                )
                await probe.rollback()
                return False
            except DBAPIError as exc:
                state = _sqlstate(exc)
                await probe.rollback()
                if state != "55P03":
                    raise
                return True

    async def _probe_advisory_lock(self, location_id: int) -> bool:
        async with self.Session() as probe:
            acquired = bool(
                await probe.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:company_id, :location_id)"),
                    {"company_id": self.company_id, "location_id": location_id},
                )
            )
            await probe.rollback()
            return not acquired

    async def _blocking_graph(self, pid_a: int, pid_b: int) -> dict[int, list[int]]:
        async with self.Session() as monitor:
            rows = (
                await monitor.execute(
                    text(
                        "SELECT pid, pg_blocking_pids(pid) AS blockers "
                        "FROM (VALUES (CAST(:pid_a AS integer)), (CAST(:pid_b AS integer))) AS target(pid) "
                        "ORDER BY pid"
                    ),
                    {"pid_a": pid_a, "pid_b": pid_b},
                )
            ).all()
            return {int(row.pid): [int(v) for v in (row.blockers or [])] for row in rows}

    async def _wait_until_event_or_done(
        self,
        event: asyncio.Event,
        task: asyncio.Task[Outcome],
        *,
        label: str,
        timeout: float = 5.0,
    ) -> None:
        deadline = time.monotonic() + timeout
        while not event.is_set():
            if task.done():
                outcome = task.result()
                raise AssertionError(f"{label} finished before reaching guarded contention point: {outcome}")
            if time.monotonic() >= deadline:
                raise AssertionError(f"timed out waiting for {label} contention point")
            await asyncio.sleep(0.02)

    async def _wait_for_guard_or_work_session_block(
        self,
        *,
        guard_reached: asyncio.Event,
        waiter_pid: int,
        holder_pid: int,
        timeout: float = 5.0,
    ) -> tuple[str, dict[int, list[int]]]:
        deadline = time.monotonic() + timeout
        last: dict[int, list[int]] = {}
        while time.monotonic() < deadline:
            if guard_reached.is_set():
                return "guard_reached", await self._blocking_graph(waiter_pid, holder_pid)
            last = await self._blocking_graph(waiter_pid, holder_pid)
            if guard_reached.is_set():
                return "guard_reached", last
            if holder_pid in last.get(waiter_pid, []):
                return "blocked_before_guard", last
            await asyncio.sleep(0.02)
        raise AssertionError(
            "contention was not observed: waiter reached neither the location guard "
            f"nor a PostgreSQL block on the WorkSession holder; graph={last}"
        )

    async def _cancel_and_await(self, *tasks: asyncio.Task | None) -> None:
        existing = [task for task in tasks if task is not None]
        for task in existing:
            if not task.done():
                task.cancel()
        if existing:
            await asyncio.gather(*existing, return_exceptions=True)

    async def _rollback_quietly(self, *sessions: AsyncSession) -> None:
        for db in sessions:
            try:
                await db.rollback()
            except Exception:
                pass

    async def _lock_rows(self, pid_a: int, pid_b: int) -> list[str]:
        async with self.Session() as monitor:
            rows = (
                await monitor.execute(
                    text(
                        "SELECT pid, locktype, mode, granted, relation::regclass::text AS relation_name, "
                        "classid, objid, transactionid "
                        "FROM pg_locks WHERE pid IN (:pid_a, :pid_b) "
                        "AND (locktype IN ('advisory','transactionid','tuple') "
                        "OR relation = 'work_sessions'::regclass) "
                        "ORDER BY pid, locktype, granted DESC, mode"
                    ),
                    {"pid_a": pid_a, "pid_b": pid_b},
                )
            ).all()
            return [
                f"pid={r.pid} type={r.locktype} mode={r.mode} granted={r.granted} "
                f"rel={r.relation_name} classid={r.classid} objid={r.objid} xid={r.transactionid}"
                for r in rows
            ]

    async def _balance_total(self, location_id: int) -> Decimal:
        async with self.Session() as db:
            value = await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
                    InventoryBalance.company_id == self.company_id,
                    InventoryBalance.location_id == location_id,
                )
            )
            return Decimal(value or 0)

    async def _movement_count(self, *, stocktake_id: int | None = None) -> int:
        async with self.Session() as db:
            stmt = select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.company_id == self.company_id
            )
            if stocktake_id is not None:
                stmt = stmt.where(InventoryMovement.stocktake_session_id == stocktake_id)
            return int(await db.scalar(stmt) or 0)

    async def _custody_rows(self, ctx) -> list[tuple[int, bool]]:
        async with self.Session() as db:
            rows = (
                await db.execute(
                    select(InventoryLocation.id, InventoryLocation.is_active).where(
                        InventoryLocation.company_id == self.company_id,
                        InventoryLocation.vehicle_id == ctx.vehicle_id,
                        InventoryLocation.location_type == "VEHICLE",
                    ).order_by(InventoryLocation.id)
                )
            ).all()
            return [(int(row.id), bool(row.is_active)) for row in rows]

    async def _state(self, ctx, stocktake_id: int | None = None):
        async with self.Session() as db:
            work = await db.get(WorkSession, ctx.work_session_id)
            snapshot = await db.scalar(
                select(SessionInventorySnapshot).where(
                    SessionInventorySnapshot.company_id == self.company_id,
                    SessionInventorySnapshot.work_session_id == ctx.work_session_id,
                    SessionInventorySnapshot.product_variant_id == self.variant_id,
                )
            )
            sessions = (
                await db.execute(
                    select(StocktakeSession).where(
                        StocktakeSession.company_id == self.company_id,
                        StocktakeSession.stocktake_type == "VEHICLE_RECON",
                        StocktakeSession.related_work_session_id == ctx.work_session_id,
                    ).order_by(StocktakeSession.id)
                )
            ).scalars().all()
            balance = Decimal(
                await db.scalar(
                    select(func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0)).where(
                        InventoryBalance.company_id == self.company_id,
                        InventoryBalance.location_id == ctx.custody_id,
                    )
                )
                or 0
            )
            movements = int(
                await db.scalar(
                    select(func.count()).select_from(InventoryMovement).where(
                        InventoryMovement.company_id == self.company_id,
                        *(
                            [InventoryMovement.stocktake_session_id == stocktake_id]
                            if stocktake_id is not None
                            else []
                        ),
                    )
                )
                or 0
            )
            return SimpleNamespace(
                work=work,
                snapshot=snapshot,
                sessions=sessions,
                balance=balance,
                movements=movements,
            )

    async def _run_catching(self, operation) -> Outcome:
        exc: BaseException | None = None
        try:
            await operation()
        except BaseException as caught:
            exc = caught
        return _classify(exc)

    async def _race_eod_vs_start(self, ctx):
        b_guard_held = asyncio.Event()
        a_guard_reached = asyncio.Event()
        release = asyncio.Event()
        real_guard = services.acquire_inventory_location_guard

        async with self.Session() as db_a, self.Session() as db_b:
            pid_a = await self._backend_pid(db_a)
            pid_b = await self._backend_pid(db_b)
            task_a: asyncio.Task[Outcome] | None = None
            task_b: asyncio.Task[Outcome] | None = None
            contention_mode = "unobserved"
            graph: dict[int, list[int]] = {}
            lock_rows: list[str] = []

            async def eod_guard(db, company_id, location_id, *, exclusive=False):
                self.assertIs(db, db_a)
                a_guard_reached.set()
                return await real_guard(db, company_id, location_id, exclusive=exclusive)

            async def start_guard(db, company_id, location_id, *, exclusive=False):
                self.assertIs(db, db_b)
                result = await real_guard(db, company_id, location_id, exclusive=exclusive)
                b_guard_held.set()
                await release.wait()
                return result

            async def op_b():
                return await self._start_recon(db_b, ctx)

            async def op_a():
                return await self._eod(db_a, ctx)

            try:
                with patch.object(reconciliation_api, "acquire_inventory_location_guard", eod_guard), patch.object(
                    stocktake_api, "acquire_inventory_location_guard", start_guard
                ):
                    task_b = asyncio.create_task(self._run_catching(op_b))
                    await self._wait_until_event_or_done(
                        b_guard_held, task_b, label="VEHICLE_RECON start"
                    )
                    self.assertTrue(
                        await self._probe_advisory_lock(ctx.custody_id),
                        "start had not actually acquired the location advisory lock",
                    )

                    task_a = asyncio.create_task(self._run_catching(op_a))
                    contention_mode, graph = await self._wait_for_guard_or_work_session_block(
                        guard_reached=a_guard_reached,
                        waiter_pid=pid_a,
                        holder_pid=pid_b,
                    )
                    self.assertTrue(
                        await self._probe_work_session_lock(ctx.work_session_id),
                        "contention did not include a real WorkSession FOR UPDATE lock",
                    )
                    lock_rows = await self._lock_rows(pid_a, pid_b)
                    release.set()
                    outcome_a, outcome_b = await asyncio.gather(task_a, task_b)
            finally:
                release.set()
                await self._cancel_and_await(task_a, task_b)
                await self._rollback_quietly(db_a, db_b)

        return outcome_a, outcome_b, contention_mode, graph, lock_rows

    async def _race_eod_vs_approve(self, ctx, stocktake_id: int, attempt_id: int):
        b_guard_held = asyncio.Event()
        a_guard_reached = asyncio.Event()
        release = asyncio.Event()
        real_guard = services.acquire_inventory_location_guard

        async with self.Session() as db_a, self.Session() as db_b:
            pid_a = await self._backend_pid(db_a)
            pid_b = await self._backend_pid(db_b)
            task_a: asyncio.Task[Outcome] | None = None
            task_b: asyncio.Task[Outcome] | None = None
            contention_mode = "unobserved"
            graph: dict[int, list[int]] = {}
            lock_rows: list[str] = []

            async def eod_guard(db, company_id, location_id, *, exclusive=False):
                self.assertIs(db, db_a)
                a_guard_reached.set()
                return await real_guard(db, company_id, location_id, exclusive=exclusive)

            async def approve_guard(db, company_id, location_id, *, exclusive=False):
                self.assertIs(db, db_b)
                result = await real_guard(db, company_id, location_id, exclusive=exclusive)
                b_guard_held.set()
                await release.wait()
                return result

            async def op_a():
                return await self._eod(db_a, ctx)

            async def op_b():
                return await self._approve(db_b, stocktake_id, attempt_id)

            try:
                with patch.object(reconciliation_api, "acquire_inventory_location_guard", eod_guard), patch.object(
                    stocktake_api, "acquire_inventory_location_guard", approve_guard
                ):
                    task_b = asyncio.create_task(self._run_catching(op_b))
                    await self._wait_until_event_or_done(
                        b_guard_held, task_b, label="VEHICLE_RECON approval"
                    )
                    self.assertTrue(
                        await self._probe_advisory_lock(ctx.custody_id),
                        "approve had not actually acquired the location advisory lock",
                    )

                    task_a = asyncio.create_task(self._run_catching(op_a))
                    contention_mode, graph = await self._wait_for_guard_or_work_session_block(
                        guard_reached=a_guard_reached,
                        waiter_pid=pid_a,
                        holder_pid=pid_b,
                    )
                    self.assertTrue(
                        await self._probe_work_session_lock(ctx.work_session_id),
                        "contention did not include a real WorkSession FOR UPDATE lock",
                    )
                    lock_rows = await self._lock_rows(pid_a, pid_b)
                    release.set()
                    outcome_a, outcome_b = await asyncio.gather(task_a, task_b)
            finally:
                release.set()
                await self._cancel_and_await(task_a, task_b)
                await self._rollback_quietly(db_a, db_b)

        return outcome_a, outcome_b, contention_mode, graph, lock_rows

    async def _race_post_vs_start(self, ctx, stocktake_id: int, attempt_id: int):
        b_guard_held = asyncio.Event()
        a_guard_reached = asyncio.Event()
        release = asyncio.Event()
        real_guard = services.acquire_inventory_location_guard

        async with self.Session() as db_a, self.Session() as db_b:
            pid_a = await self._backend_pid(db_a)
            pid_b = await self._backend_pid(db_b)
            task_a: asyncio.Task[Outcome] | None = None
            task_b: asyncio.Task[Outcome] | None = None
            contention_mode = "unobserved"
            graph: dict[int, list[int]] = {}
            lock_rows: list[str] = []

            async def post_guard(db, company_id, location_id, *, exclusive=False):
                self.assertIs(db, db_a)
                a_guard_reached.set()
                return await real_guard(db, company_id, location_id, exclusive=exclusive)

            async def start_guard(db, company_id, location_id, *, exclusive=False):
                self.assertIs(db, db_b)
                result = await real_guard(db, company_id, location_id, exclusive=exclusive)
                b_guard_held.set()
                await release.wait()
                return result

            async def op_a():
                return await services.post_approved_stocktake_adjustments(
                    db_a,
                    company_id=self.company_id,
                    stocktake_session_id=stocktake_id,
                    stocktake_count_attempt_id=attempt_id,
                    performed_by=int(self.owner.operational_driver.id),
                )

            async def op_b():
                return await self._start_recon(db_b, ctx)

            try:
                with patch.object(services, "acquire_inventory_location_guard", post_guard), patch.object(
                    stocktake_api, "acquire_inventory_location_guard", start_guard
                ):
                    task_b = asyncio.create_task(self._run_catching(op_b))
                    await self._wait_until_event_or_done(
                        b_guard_held, task_b, label="VEHICLE_RECON start"
                    )
                    self.assertTrue(
                        await self._probe_advisory_lock(ctx.custody_id),
                        "start had not actually acquired the location advisory lock",
                    )

                    task_a = asyncio.create_task(self._run_catching(op_a))
                    contention_mode, graph = await self._wait_for_guard_or_work_session_block(
                        guard_reached=a_guard_reached,
                        waiter_pid=pid_a,
                        holder_pid=pid_b,
                    )
                    self.assertTrue(
                        await self._probe_work_session_lock(ctx.work_session_id),
                        "contention did not include a real WorkSession FOR UPDATE lock",
                    )
                    lock_rows = await self._lock_rows(pid_a, pid_b)
                    release.set()
                    outcome_a, outcome_b = await asyncio.gather(task_a, task_b)
                    if outcome_a.kind == "serialized_success":
                        await db_a.commit()
                    else:
                        await db_a.rollback()
            finally:
                release.set()
                await self._cancel_and_await(task_a, task_b)
                await self._rollback_quietly(db_a, db_b)

        return outcome_a, outcome_b, contention_mode, graph, lock_rows

    def _print_race(
        self,
        name: str,
        outcome_a: Outcome,
        outcome_b: Outcome,
        contention_mode: str,
        graph,
        lock_rows,
    ) -> None:
        print(
            f"RACE_OUTCOME {name} A={outcome_a.kind}:{outcome_a.code} "
            f"B={outcome_b.kind}:{outcome_b.code} mode={contention_mode}",
            flush=True,
        )
        print(f"WAIT_GRAPH_DIAGNOSTIC {name} {graph}", flush=True)
        for row in lock_rows:
            print(f"LOCK_ROW_DIAGNOSTIC {name} {row}", flush=True)

    def _assert_green_outcomes(self, *outcomes: Outcome) -> None:
        allowed_conflicts = {409, "InventoryMutationError"}
        for outcome in outcomes:
            if outcome.kind == "serialized_success":
                continue
            self.assertEqual(
                outcome.kind,
                "controlled_business_conflict",
                f"unexpected race outcome: {outcome}",
            )
            self.assertIn(
                outcome.code,
                allowed_conflicts,
                f"unexpected controlled conflict: {outcome}",
            )
        self.assertTrue(
            any(outcome.kind == "serialized_success" for outcome in outcomes),
            f"race made no committed forward progress: {outcomes}",
        )

    async def _assert_canonical_custody_unchanged(self, ctx) -> None:
        self.assertEqual(
            await self._custody_rows(ctx),
            [(ctx.custody_id, True)],
            "race left missing, stale, inactive, or ambiguous Vehicle custody",
        )

    async def test_01_eod_vs_vehicle_recon_start_has_no_abba(self):
        ctx = await self._seed_context(balance=5, snapshot=True)
        before_balance = await self._balance_total(ctx.custody_id)
        outcome_a, outcome_b, mode, graph, lock_rows = await self._race_eod_vs_start(ctx)
        self._print_race("eod_vs_start", outcome_a, outcome_b, mode, graph, lock_rows)

        state = await self._state(ctx)
        self.assertEqual(state.balance, before_balance)
        self.assertEqual(state.movements, 0)
        self.assertLessEqual(len(state.sessions), 1, "duplicate VEHICLE_RECON created")
        if state.sessions:
            self.assertEqual(state.sessions[0].status, "COUNTING")
            self.assertIsNone(state.work.inventory_reconciled_at)
            self.assertIsNone(state.work.inventory_reconciled_by)
            self.assertIsNone(state.snapshot.ending_quantity)
            self.assertIsNone(state.snapshot.settled_by)
            self.assertIsNone(state.snapshot.settled_at)
        else:
            self.assertIsNotNone(state.work.inventory_reconciled_at)
            self.assertIsNotNone(state.work.inventory_reconciled_by)
            self.assertEqual(Decimal(state.snapshot.ending_quantity), before_balance)
            self.assertIsNotNone(state.snapshot.settled_by)
            self.assertIsNotNone(state.snapshot.settled_at)
        await self._assert_canonical_custody_unchanged(ctx)
        self.assertFalse(
            self.vehicle_row_locks,
            f"reverse Vehicle row lock observed: {self.vehicle_row_locks[:1]}",
        )
        self._assert_green_outcomes(outcome_a, outcome_b)

    async def test_02_eod_vs_vehicle_recon_approve_has_no_abba(self):
        ctx, stocktake_id, attempt_id = await self._prepare_pending_recon()
        before_balance = await self._balance_total(ctx.custody_id)
        outcome_a, outcome_b, mode, graph, lock_rows = await self._race_eod_vs_approve(
            ctx, stocktake_id, attempt_id
        )
        self._print_race("eod_vs_approve", outcome_a, outcome_b, mode, graph, lock_rows)

        state = await self._state(ctx, stocktake_id)
        self.assertEqual(len(state.sessions), 1)
        session = state.sessions[0]
        self.assertNotEqual(
            session.status,
            "APPROVED",
            "approve race left a partial APPROVED state",
        )
        self.assertIn(session.status, {"PENDING_REVIEW", "POSTED"})
        if session.status == "POSTED":
            self.assertEqual(outcome_b.kind, "serialized_success")
            self.assertEqual(state.balance, Decimal("6"))
            self.assertEqual(state.movements, 1)
            self.assertIsNotNone(session.posted_at)
            self.assertIsNotNone(state.work.inventory_reconciled_at)
            self.assertIsNotNone(state.work.inventory_reconciled_by)
            self.assertEqual(Decimal(state.snapshot.ending_quantity), Decimal("6"))
        else:
            self.assertEqual(outcome_a.kind, "serialized_success")
            self.assertEqual(outcome_b.kind, "controlled_business_conflict")
            self.assertEqual(state.balance, before_balance)
            self.assertEqual(state.movements, 0)
            self.assertIsNone(session.posted_at)
            self.assertIsNotNone(state.work.inventory_reconciled_at)
            self.assertIsNotNone(state.work.inventory_reconciled_by)
            self.assertEqual(Decimal(state.snapshot.ending_quantity), before_balance)
        await self._assert_canonical_custody_unchanged(ctx)
        self.assertFalse(
            self.vehicle_row_locks,
            f"reverse Vehicle row lock observed: {self.vehicle_row_locks[:1]}",
        )
        self._assert_green_outcomes(outcome_a, outcome_b)

    async def test_03_post_vs_vehicle_recon_start_has_no_abba(self):
        ctx, stocktake_id, attempt_id = await self._prepare_approved_recon()
        before_balance = await self._balance_total(ctx.custody_id)
        outcome_a, outcome_b, mode, graph, lock_rows = await self._race_post_vs_start(
            ctx, stocktake_id, attempt_id
        )
        self._print_race("post_vs_start", outcome_a, outcome_b, mode, graph, lock_rows)

        state = await self._state(ctx, stocktake_id)
        self.assertEqual(len(state.sessions), 1, "start created a duplicate VEHICLE_RECON")
        session = state.sessions[0]
        self.assertIn(session.status, {"APPROVED", "POSTED"})
        if session.status == "POSTED":
            self.assertEqual(outcome_a.kind, "serialized_success")
            self.assertEqual(state.balance, Decimal("6"))
            self.assertEqual(state.movements, 1)
            self.assertIsNotNone(session.posted_at)
            self.assertIsNotNone(state.work.inventory_reconciled_at)
            self.assertIsNotNone(state.work.inventory_reconciled_by)
            self.assertEqual(Decimal(state.snapshot.ending_quantity), Decimal("6"))
        else:
            self.assertEqual(session.status, "APPROVED")
            self.assertEqual(state.balance, before_balance)
            self.assertEqual(state.movements, 0)
            self.assertIsNone(session.posted_at)
            self.assertIsNone(state.work.inventory_reconciled_at)
            self.assertIsNone(state.work.inventory_reconciled_by)
            self.assertIsNone(state.snapshot.ending_quantity)
        await self._assert_canonical_custody_unchanged(ctx)
        self.assertFalse(
            self.vehicle_row_locks,
            f"reverse Vehicle row lock observed: {self.vehicle_row_locks[:1]}",
        )
        self._assert_green_outcomes(outcome_a, outcome_b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
