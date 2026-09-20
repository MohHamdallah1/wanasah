from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import contextvars
import http.client
import json
import math
import os
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

def find_backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        Path.cwd() / "wa_backend",
        here.parent.parent / "wa_backend",
        here.parent.parent,
        here.parent,
    )
    for candidate in candidates:
        if (candidate / "main.py").is_file() and (candidate / "database.py").is_file():
            return candidate.resolve()
    raise RuntimeError(
        "wa_backend not found. Run from repository root or place this file in wa_backend/scripts/."
    )

BACKEND_ROOT = find_backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from context import tenant_context  # noqa: E402
import database as database_runtime  # noqa: E402
from database import AsyncSessionLocal, engine  # noqa: E402
from models import Company, Driver, InventoryBalance, InventoryStockPolicy, ProductVariant  # noqa: E402
from api.auth import create_access_token  # noqa: E402
from api.warehouse import (  # noqa: E402
    get_warehouse_inventory,
    get_warehouse_inventory_alert_summary,
    get_warehouse_inventory_summary,
)
from domains.live_stock_projection.service import rebuild_live_stock_company
from main import app  # noqa: E402

# ASGITransport runs in one Python process, so the normal per-worker pool
# (5 steady + 0 overflow) would expose only 1/4 of the measured production
# DB budget. This aggregate benchmark pool models 4 workers × 5 = 20 without
# weakening request concurrency or latency thresholds.
HTTP_BENCH_POOL_SIZE = 20
HTTP_BENCH_MAX_OVERFLOW = 0
HTTP_BENCH_DB_CAP = HTTP_BENCH_POOL_SIZE + HTTP_BENCH_MAX_OVERFLOW
if HTTP_BENCH_DB_CAP != 20:
    raise RuntimeError("Live Stock HTTP benchmark DB cap must remain 20.")

# Match the Stage 8.2.1 production topology exactly: four workers with
# five steady connections each and no overflow.  Using 4+1 here is not
# equivalent because QueuePool overflow connections are transient and are not
# prewarmed by the application lifespan, which distorts the HTTP tail latency
# that this gate is supposed to measure.
REAL_HTTP_WORKERS = 4
REAL_HTTP_POOL_SIZE = 5
REAL_HTTP_MAX_OVERFLOW = 0
REAL_HTTP_DB_CAP = (
    REAL_HTTP_WORKERS
    * (REAL_HTTP_POOL_SIZE + REAL_HTTP_MAX_OVERFLOW)
)
if (
    REAL_HTTP_WORKERS != 4
    or REAL_HTTP_POOL_SIZE != 5
    or REAL_HTTP_MAX_OVERFLOW != 0
    or REAL_HTTP_DB_CAP != 20
):
    raise RuntimeError(
        "Real Uvicorn HTTP benchmark must match production topology: "
        "4 workers x (pool_size=5 + max_overflow=0) = 20 connections."
    )

http_bench_engine = create_async_engine(
    database_runtime.DATABASE_URL,
    pool_size=HTTP_BENCH_POOL_SIZE,
    max_overflow=HTTP_BENCH_MAX_OVERFLOW,
    pool_timeout=3,
    pool_recycle=1800,
    pool_use_lifo=True,
    pool_pre_ping=True,
)
event.listen(
    http_bench_engine.sync_engine,
    "checkout",
    database_runtime.on_checkout,
)
POOL_WAIT_BUCKET: contextvars.ContextVar[list[float] | None] = (
    contextvars.ContextVar(
        "live_stock_http_pool_wait_bucket",
        default=None,
    )
)


class ProfiledHttpBenchSession(AsyncSession):
    async def connection(self, *args, **kwargs):
        started = time.perf_counter()
        connection = await super().connection(*args, **kwargs)
        bucket = POOL_WAIT_BUCKET.get()
        if bucket is not None:
            bucket.append(
                (time.perf_counter() - started) * 1000
            )
        return connection


HttpBenchSession = async_sessionmaker(
    http_bench_engine,
    class_=ProfiledHttpBenchSession,
    expire_on_commit=False,
)

migration_url = os.environ.get("DATABASE_URL_MIGRATION")
if not migration_url:
    raise RuntimeError(
        "DATABASE_URL_MIGRATION is required for global scale counts."
    )
global_count_engine = create_async_engine(
    migration_url,
    pool_size=1,
    max_overflow=1,
    pool_pre_ping=True,
)
GlobalCountSession = async_sessionmaker(
    global_count_engine,
    expire_on_commit=False,
)


async def http_benchmark_get_db():
    # Match production get_db: yielding AsyncSession must not eagerly checkout
    # a PostgreSQL connection before get_current_driver decodes the JWT and
    # establishes tenant_context.
    async with HttpBenchSession() as session:
        yield session


SQL_BUCKET: contextvars.ContextVar[list[tuple[str, float]] | None] = contextvars.ContextVar(
    "live_stock_scale_sql_bucket",
    default=None,
)

def _sql_label(statement: str) -> str:
    normalized = " ".join(statement.lower().split())
    if "set_config('app.current_tenant'" in normalized:
        return "tenant"
    if "token_blacklist" in normalized:
        return "auth_blacklist"
    if " from drivers " in normalized:
        return "driver"
    if "user_location_access" in normalized or "role_permissions" in normalized:
        return "access"
    if (
        "inventory_live_stock_company_summaries" in normalized
        and "inventory_live_stock_warehouse_summaries" in normalized
    ):
        return "readiness_summary"
    if (
        "inventory_cost_states" in normalized
        and "inventory_live_stock_projection" in normalized
    ):
        return "details"
    if "product_uom_conversions" in normalized:
        return "display_uom"
    if "inventory_cost_events" in normalized:
        return "latest_purchase"
    if (
        "inventory_live_stock_projection" in normalized
        and "next_transition_date" in normalized
    ):
        return "readiness_due"
    if "inventory_live_stock_projection" in normalized:
        return "candidate"
    if "inventory_locations" in normalized:
        return "location"
    if "permissions" in normalized:
        return "access"
    return normalized.split(" ", 1)[0] if normalized else "unknown"


def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    bucket = SQL_BUCKET.get()
    if bucket is not None:
        context._live_stock_scale_started = time.perf_counter()
        context._live_stock_scale_label = _sql_label(statement)

def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    bucket = SQL_BUCKET.get()
    started = getattr(context, "_live_stock_scale_started", None)
    if bucket is not None and started is not None:
        bucket.append(
            (
                getattr(context, "_live_stock_scale_label", "unknown"),
                (time.perf_counter() - started) * 1000,
            )
        )

def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * p
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    weight = pos - low
    return ordered[low] * (1 - weight) + ordered[high] * weight

@dataclass
class Sample:
    ms: float
    sql_ms: float
    sql_count: int
    items: int | None = None
    total: int | None = None
    sql_by_label: dict[str, float] | None = None

@dataclass
class Stats:
    name: str
    p50: float
    p95: float
    p99: float
    maximum: float
    sql_p95: float
    statements_min: int
    statements_max: int
    samples: int
    sql_label_p95: dict[str, float]

def summarize(name: str, rows: list[Sample]) -> Stats:
    times = [r.ms for r in rows]
    sql = [r.sql_ms for r in rows]
    counts = [r.sql_count for r in rows]
    labels = sorted(
        {
            label
            for row in rows
            for label in (row.sql_by_label or {})
        }
    )
    label_p95 = {
        label: percentile(
            [
                (row.sql_by_label or {}).get(label, 0.0)
                for row in rows
            ],
            0.95,
        )
        for label in labels
    }
    return Stats(
        name=name,
        p50=percentile(times, 0.50),
        p95=percentile(times, 0.95),
        p99=percentile(times, 0.99),
        maximum=max(times),
        sql_p95=percentile(sql, 0.95),
        statements_min=min(counts),
        statements_max=max(counts),
        samples=len(rows),
        sql_label_p95=label_p95,
    )

async def load_driver(db, company_id: int, driver_id: int) -> Driver:
    driver = await db.scalar(
        select(Driver).where(
            Driver.id == driver_id,
            Driver.company_id == company_id,
            Driver.is_active.is_(True),
        )
    )
    if driver is None:
        raise RuntimeError("Active benchmark driver not found.")
    return driver

async def prepare_session(company_id: int, driver_id: int):
    db = AsyncSessionLocal()
    token = tenant_context.set(company_id)
    try:
        await db.execute(
            text("SELECT set_config('app.current_tenant', :c, false)"),
            {"c": str(company_id)},
        )
        driver = await load_driver(db, company_id, driver_id)
        return db, driver, token
    except Exception:
        tenant_context.reset(token)
        await db.close()
        raise

async def timed_core(call: Callable[[Any, Driver], Awaitable[dict[str, Any]]], company_id: int, driver_id: int) -> Sample:
    db, driver, tenant_token = await prepare_session(company_id, driver_id)
    sql_bucket: list[tuple[str, float]] = []
    sql_token = SQL_BUCKET.set(sql_bucket)
    try:
        started = time.perf_counter()
        payload = await call(db, driver)
        elapsed = (time.perf_counter() - started) * 1000
        items = payload.get("items")
        sql_by_label: dict[str, float] = {}
        for label, sql_ms in sql_bucket:
            sql_by_label[label] = sql_by_label.get(label, 0.0) + sql_ms
        return Sample(
            ms=elapsed,
            sql_ms=sum(sql_ms for _label, sql_ms in sql_bucket),
            sql_count=len(sql_bucket),
            items=len(items) if isinstance(items, list) else None,
            total=payload.get("total") if isinstance(payload.get("total"), int) else None,
            sql_by_label=sql_by_label,
        )
    finally:
        SQL_BUCKET.reset(sql_token)
        tenant_context.reset(tenant_token)
        await db.close()

async def benchmark(
    name: str,
    call: Callable[[Any, Driver], Awaitable[dict[str, Any]]],
    *,
    company_id: int,
    driver_id: int,
    runs: int,
    warmup: int,
) -> tuple[Stats, list[Sample]]:
    for _ in range(warmup):
        await timed_core(call, company_id, driver_id)
    rows = [
        await timed_core(call, company_id, driver_id)
        for _ in range(runs)
    ]
    return summarize(name, rows), rows

async def main_page_call(location_id: int, limit: int):
    async def _call(db, driver):
        return await get_warehouse_inventory(
            location_id=location_id,
            cursor=None,
            limit=limit,
            search=None,
            only_alerts=False,
            db=db,
            current_admin=driver,
        )
    return _call

async def alert_summary_call(location_id: int):
    async def _call(db, driver):
        return await get_warehouse_inventory_alert_summary(
            location_id=location_id,
            db=db,
            current_admin=driver,
        )
    return _call

async def inventory_summary_call(location_id: int):
    async def _call(db, driver):
        return await get_warehouse_inventory_summary(
            location_id=location_id,
            db=db,
            current_admin=driver,
        )
    return _call


async def only_alerts_call(location_id: int, limit: int):
    async def _call(db, driver):
        return await get_warehouse_inventory(
            location_id=location_id,
            cursor=None,
            limit=limit,
            search=None,
            only_alerts=True,
            db=db,
            current_admin=driver,
        )
    return _call

async def search_call(location_id: int, limit: int, search_term: str):
    async def _call(db, driver):
        return await get_warehouse_inventory(
            location_id=location_id,
            cursor=None,
            limit=limit,
            search=search_term,
            only_alerts=False,
            db=db,
            current_admin=driver,
        )
    return _call

async def second_page_call(location_id: int, limit: int, company_id: int, driver_id: int):
    async def _call(db, driver):
        first = await get_warehouse_inventory(
            location_id=location_id,
            cursor=None,
            limit=limit,
            search=None,
            only_alerts=False,
            db=db,
            current_admin=driver,
        )
        cursor = first.get("next_cursor")
        if not cursor:
            raise RuntimeError("Dataset is too small to benchmark cursor page 2.")
        # Do not count the first page in the SQL/latency sample.
        bucket = SQL_BUCKET.get()
        if bucket is not None:
            bucket.clear()
        started = time.perf_counter()
        second = await get_warehouse_inventory(
            location_id=location_id,
            cursor=cursor,
            limit=limit,
            search=None,
            only_alerts=False,
            db=db,
            current_admin=driver,
        )
        second["_inner_ms_override"] = (time.perf_counter() - started) * 1000
        return second

    async def _wrapped(db, driver):
        return await _call(db, driver)
    return _wrapped

async def prepare_projection(company_id: int) -> float:
    token = tenant_context.set(company_id)
    started = time.perf_counter()
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant', :c, false)"),
                {"c": str(company_id)},
            )
            await rebuild_live_stock_company(
                db,
                company_id=company_id,
                batch_size=10000,
            )
            await db.commit()
    finally:
        tenant_context.reset(token)
    return (time.perf_counter() - started) * 1000


async def resolve_driver_id(company_id: int, requested: int | None) -> int:
    token = tenant_context.set(company_id)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant', :c, false)"),
                {"c": str(company_id)},
            )
            if requested is not None:
                value = await db.scalar(
                    select(Driver.id).where(
                        Driver.company_id == company_id,
                        Driver.id == requested,
                        Driver.is_active.is_(True),
                    )
                )
                if value is None:
                    raise RuntimeError("Requested active benchmark driver not found.")
                return int(value)

            value = await db.scalar(
                select(Driver.id)
                .where(
                    Driver.company_id == company_id,
                    Driver.is_active.is_(True),
                    Driver.is_admin.is_(True),
                )
                .order_by(Driver.id.asc())
                .limit(1)
            )
            if value is None:
                raise RuntimeError(
                    "No active company admin exists for the benchmark; "
                    "pass --driver-id explicitly."
                )
            return int(value)
    finally:
        tenant_context.reset(token)


async def verify_projection_read_schema() -> None:
    required_indexes = {
        "ix_live_stock_projection_warehouse_transition",
        "ix_product_variant_live_active_seek",
        "ix_inventory_cost_event_purchase_latest",
        "ix_product_uom_conversion_display_seek",
    }
    async with AsyncSessionLocal() as db:
        existing = set(
            (
                await db.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND indexname = ANY(:index_names)
                        """
                    ),
                    {"index_names": sorted(required_indexes)},
                )
            ).scalars().all()
        )
        if db.in_transaction():
            await db.rollback()
    missing = sorted(required_indexes - existing)
    if missing:
        raise RuntimeError(
            "Live Stock read-path indexes are missing: "
            + ", ".join(missing)
            + ". Run Alembic upgrade head before benchmarking."
        )


async def dataset_snapshot(company_id: int, location_id: int) -> dict[str, int]:
    token = tenant_context.set(company_id)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant', :c, false)"),
                {"c": str(company_id)},
            )
            variants = int(
                await db.scalar(
                    select(func.count()).select_from(ProductVariant).where(
                        ProductVariant.company_id == company_id
                    )
                ) or 0
            )
            balances = int(
                await db.scalar(
                    select(func.count()).select_from(InventoryBalance).where(
                        InventoryBalance.company_id == company_id,
                        InventoryBalance.location_id == location_id,
                    )
                ) or 0
            )
            policies = int(
                await db.scalar(
                    select(func.count()).select_from(InventoryStockPolicy).where(
                        InventoryStockPolicy.company_id == company_id,
                        InventoryStockPolicy.location_id == location_id,
                    )
                ) or 0
            )
            company_snapshot = {
                "company_variants": variants,
                "location_balances": balances,
                "location_policies": policies,
            }

        async with GlobalCountSession() as global_db:
            global_variants = int(
                (
                    await global_db.scalar(
                        select(func.count()).select_from(ProductVariant)
                    )
                )
                or 0
            )
            companies = int(
                (
                    await global_db.scalar(
                        select(func.count()).select_from(Company)
                    )
                )
                or 0
            )

        return {
            **company_snapshot,
            "global_variants": global_variants,
            "companies": companies,
        }
    finally:
        tenant_context.reset(token)

async def create_benchmark_token(
    *,
    company_id: int,
    driver_id: int,
) -> str:
    token_ctx = tenant_context.set(company_id)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant', :c, false)"),
                {"c": str(company_id)},
            )
            driver = await load_driver(db, company_id, driver_id)
            return create_access_token(
                {
                    "sub": str(driver.id),
                    "is_admin": bool(driver.is_admin),
                    "username": driver.username,
                },
                company_id=company_id,
                role_name="Admin" if driver.is_admin else "Inventory",
            )
    finally:
        tenant_context.reset(token_ctx)


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_real_uvicorn() -> tuple[subprocess.Popen, int, str]:
    port = _free_local_port()
    env = os.environ.copy()
    env.update(
        {
            "WEB_CONCURRENCY": str(REAL_HTTP_WORKERS),
            "DB_APP_CONNECTION_BUDGET": str(REAL_HTTP_DB_CAP),
            "DB_POOL_SIZE": str(REAL_HTTP_POOL_SIZE),
            "DB_MAX_OVERFLOW": str(REAL_HTTP_MAX_OVERFLOW),
            "DB_POOL_TIMEOUT": "3",
            "DB_POOL_RECYCLE": "1800",
        }
    )

    log_file = tempfile.NamedTemporaryFile(
        prefix="wanasah-live-stock-uvicorn-",
        suffix=".log",
        delete=False,
    )
    log_path = log_file.name
    log_file.close()
    log_stream = open(log_path, "w", encoding="utf-8")

    kwargs: dict[str, Any] = {
        "cwd": str(BACKEND_ROOT),
        "env": env,
        "stdout": log_stream,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "scripts.stage823_benchmark_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            str(REAL_HTTP_WORKERS),
            "--log-level",
            "warning",
        ],
        **kwargs,
    )
    log_stream.close()
    return process, port, log_path


def _read_benchmark_log(log_path: str, limit: int = 6000) -> str:
    try:
        value = Path(log_path).read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""
    return value[-limit:]


def _stop_real_uvicorn(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                [
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


async def _wait_for_real_uvicorn(
    *,
    process: subprocess.Popen,
    base_url: str,
    log_path: str,
) -> None:
    """Wait until every real Uvicorn worker has completed lifespan startup."""
    deadline = time.monotonic() + 45.0
    seen_pids: set[int] = set()

    async def probe_once() -> int | None:
        limits = httpx.Limits(
            max_connections=1,
            max_keepalive_connections=0,
        )
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=2.0,
                limits=limits,
                headers={"Connection": "close"},
                trust_env=False,
            ) as client:
                response = await client.get(
                    "/__live_stock_benchmark_readiness__"
                )
                if response.status_code != 200:
                    return None
                payload = response.json()
                pid = payload.get("pid")
                return pid if type(pid) is int and pid > 0 else None
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "Uvicorn benchmark server exited before readiness.\n"
                + _read_benchmark_log(log_path)
            )

        batch = await asyncio.gather(
            *(probe_once() for _ in range(REAL_HTTP_WORKERS * 4))
        )
        seen_pids.update(pid for pid in batch if pid is not None)
        if len(seen_pids) >= REAL_HTTP_WORKERS:
            print(
                "HTTP_WORKERS_READY="
                + json.dumps(
                    {
                        "workers_expected": REAL_HTTP_WORKERS,
                        "workers_seen": len(seen_pids),
                        "pids": sorted(seen_pids),
                    },
                    sort_keys=True,
                )
            )
            return
        await asyncio.sleep(0.2)

    log_tail = _read_benchmark_log(log_path)
    raise RuntimeError(
        "Not all Uvicorn benchmark workers became ready in time. "
        f"seen={sorted(seen_pids)} expected={REAL_HTTP_WORKERS} "
        f"pid={process.pid} poll={process.poll()} log={log_path}\n"
        + (log_tail or "<benchmark log is empty>")
    )


def _real_uvicorn_http_load_stdlib(
    *,
    port: int,
    token: str,
    location_id: int,
    concurrency: int,
    requests: int,
) -> dict[str, Any]:
    """Generate real HTTP load without HTTPX's Windows asyncio transport cost.

    The server under test is unchanged.  This client uses one persistent
    stdlib HTTP connection per worker thread so the gate measures the Uvicorn
    application path instead of HTTPX/Proactor loopback overhead on Windows.
    """
    latencies: list[float] = []
    statuses: list[int] = []
    route_latencies: dict[str, list[float]] = {
        "cursor": [],
        "alerts": [],
    }
    timeout_count = 0
    transport_error_count = 0
    error_samples: list[str] = []

    work: list[list[int]] = [[] for _ in range(concurrency)]
    for index in range(requests):
        work[index % concurrency].append(index)

    def worker(indices: list[int]) -> dict[str, Any]:
        local_latencies: list[float] = []
        local_statuses: list[int] = []
        local_route_latencies: dict[str, list[float]] = {
            "cursor": [],
            "alerts": [],
        }
        local_timeouts = 0
        local_transport_errors = 0
        local_error_samples: list[str] = []

        connection = http.client.HTTPConnection(
            "127.0.0.1",
            port,
            timeout=30.0,
        )
        headers = {"Authorization": f"Bearer {token}"}
        try:
            for index in indices:
                is_alert = index % 5 == 0
                route_name = "alerts" if is_alert else "cursor"
                request_path = (
                    f"/warehouse/inventory/alerts/summary"
                    f"?location_id={location_id}"
                    if is_alert
                    else (
                        f"/warehouse/inventory/cursor"
                        f"?location_id={location_id}&limit=50"
                    )
                )
                started = time.perf_counter()
                try:
                    connection.request(
                        "GET",
                        request_path,
                        headers=headers,
                    )
                    response = connection.getresponse()
                    response.read()
                    local_statuses.append(response.status)
                except TimeoutError as exc:
                    local_timeouts += 1
                    local_statuses.append(0)
                    if len(local_error_samples) < 3:
                        local_error_samples.append(
                            f"{route_name}:timeout:{type(exc).__name__}"
                        )
                    try:
                        connection.close()
                    except Exception:
                        pass
                    connection = http.client.HTTPConnection(
                        "127.0.0.1",
                        port,
                        timeout=30.0,
                    )
                except OSError as exc:
                    local_transport_errors += 1
                    local_statuses.append(0)
                    if len(local_error_samples) < 3:
                        local_error_samples.append(
                            f"{route_name}:transport:{type(exc).__name__}"
                        )
                    try:
                        connection.close()
                    except Exception:
                        pass
                    connection = http.client.HTTPConnection(
                        "127.0.0.1",
                        port,
                        timeout=30.0,
                    )
                finally:
                    elapsed_ms = (
                        time.perf_counter() - started
                    ) * 1000
                    local_latencies.append(elapsed_ms)
                    local_route_latencies[route_name].append(
                        elapsed_ms
                    )
        finally:
            connection.close()

        return {
            "latencies": local_latencies,
            "statuses": local_statuses,
            "routes": local_route_latencies,
            "timeouts": local_timeouts,
            "transport_errors": local_transport_errors,
            "error_samples": local_error_samples,
        }

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=concurrency
    ) as executor:
        results = list(executor.map(worker, work))

    for result in results:
        latencies.extend(result["latencies"])
        statuses.extend(result["statuses"])
        route_latencies["cursor"].extend(
            result["routes"]["cursor"]
        )
        route_latencies["alerts"].extend(
            result["routes"]["alerts"]
        )
        timeout_count += result["timeouts"]
        transport_error_count += result["transport_errors"]
        if len(error_samples) < 10:
            remaining = 10 - len(error_samples)
            error_samples.extend(
                result["error_samples"][:remaining]
            )

    http_status_errors = sum(
        1 for status in statuses if status not in {0, 200}
    )
    total_errors = (
        http_status_errors
        + timeout_count
        + transport_error_count
    )
    return {
        "client": "stdlib_threads",
        "requests": requests,
        "completed_responses": sum(
            1 for status in statuses if status != 0
        ),
        "concurrency": concurrency,
        "workers": REAL_HTTP_WORKERS,
        "db_connection_cap": REAL_HTTP_DB_CAP,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "max_ms": max(latencies),
        "cursor_p95_ms": percentile(
            route_latencies["cursor"],
            0.95,
        ),
        "alerts_p95_ms": percentile(
            route_latencies["alerts"],
            0.95,
        ),
        "http_status_errors": http_status_errors,
        "timeouts": timeout_count,
        "transport_errors": transport_error_count,
        "error_samples": error_samples,
        "uvicorn_log_tail": "",
        "errors": total_errors,
    }


async def real_uvicorn_http_load(
    *,
    token: str,
    location_id: int,
    concurrency: int,
    requests: int,
) -> dict[str, Any]:
    process, port, log_path = _start_real_uvicorn()
    base_url = f"http://127.0.0.1:{port}"
    try:
        await _wait_for_real_uvicorn(
            process=process,
            base_url=base_url,
            log_path=log_path,
        )

        if os.name == "nt":
            load = await asyncio.to_thread(
                _real_uvicorn_http_load_stdlib,
                port=port,
                token=token,
                location_id=location_id,
                concurrency=concurrency,
                requests=requests,
            )
        else:
            headers = {"Authorization": f"Bearer {token}"}
            sem = asyncio.Semaphore(concurrency)
            latencies: list[float] = []
            statuses: list[int] = []
            timeout_count = 0
            transport_error_count = 0
            error_samples: list[str] = []
            route_latencies: dict[str, list[float]] = {
                "cursor": [],
                "alerts": [],
            }

            async with httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=30.0,
            ) as client:
                async def one(index: int) -> None:
                    nonlocal timeout_count, transport_error_count
                    async with sem:
                        is_alert = index % 5 == 0
                        route_name = "alerts" if is_alert else "cursor"
                        request_path = (
                            f"/warehouse/inventory/alerts/summary"
                            f"?location_id={location_id}"
                            if is_alert
                            else (
                                f"/warehouse/inventory/cursor"
                                f"?location_id={location_id}&limit=50"
                            )
                        )
                        started = time.perf_counter()
                        try:
                            response = await client.get(request_path)
                            statuses.append(response.status_code)
                        except httpx.TimeoutException as exc:
                            timeout_count += 1
                            statuses.append(0)
                            if len(error_samples) < 10:
                                error_samples.append(
                                    f"{route_name}:timeout:{type(exc).__name__}"
                                )
                        except httpx.HTTPError as exc:
                            transport_error_count += 1
                            statuses.append(0)
                            if len(error_samples) < 10:
                                error_samples.append(
                                    f"{route_name}:http_error:{type(exc).__name__}"
                                )
                        finally:
                            elapsed_ms = (
                                time.perf_counter() - started
                            ) * 1000
                            latencies.append(elapsed_ms)
                            route_latencies[route_name].append(elapsed_ms)

                await asyncio.gather(
                    *(one(i) for i in range(requests))
                )

            http_status_errors = sum(
                1 for status in statuses if status not in {0, 200}
            )
            total_errors = (
                http_status_errors
                + timeout_count
                + transport_error_count
            )
            load = {
                "client": "httpx_async",
                "requests": requests,
                "completed_responses": sum(
                    1 for status in statuses if status != 0
                ),
                "concurrency": concurrency,
                "workers": REAL_HTTP_WORKERS,
                "db_connection_cap": REAL_HTTP_DB_CAP,
                "p50_ms": percentile(latencies, 0.50),
                "p95_ms": percentile(latencies, 0.95),
                "p99_ms": percentile(latencies, 0.99),
                "max_ms": max(latencies),
                "cursor_p95_ms": percentile(
                    route_latencies["cursor"],
                    0.95,
                ),
                "alerts_p95_ms": percentile(
                    route_latencies["alerts"],
                    0.95,
                ),
                "http_status_errors": http_status_errors,
                "timeouts": timeout_count,
                "transport_errors": transport_error_count,
                "error_samples": error_samples,
                "uvicorn_log_tail": "",
                "errors": total_errors,
            }

        if load["errors"]:
            load["uvicorn_log_tail"] = _read_benchmark_log(
                log_path
            )
        return load
    finally:
        _stop_real_uvicorn(process)
        try:
            Path(log_path).unlink(missing_ok=True)
        except OSError:
            pass


async def http_load(
    *,
    company_id: int,
    driver_id: int,
    location_id: int,
    concurrency: int,
    requests: int,
) -> dict[str, Any]:
    token = await create_benchmark_token(
        company_id=company_id,
        driver_id=driver_id,
    )

    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"}
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: list[int] = []
    sql_totals: list[float] = []
    sql_counts: list[int] = []
    sql_profiles: list[dict[str, float]] = []
    route_latencies: dict[str, list[float]] = {
        "cursor": [],
        "alerts": [],
    }
    outside_sql_ms: list[float] = []
    pool_wait_ms: list[float] = []

    previous_override = app.dependency_overrides.get(
        database_runtime.get_db
    )
    app.dependency_overrides[
        database_runtime.get_db
    ] = http_benchmark_get_db

    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://wanasah-perf.local",
            headers=headers,
            timeout=30.0,
        ) as client:
            async def one(index: int):
                async with sem:
                    is_alert = index % 5 == 0
                    route_name = "alerts" if is_alert else "cursor"
                    path = (
                        f"/warehouse/inventory/alerts/summary?location_id={location_id}"
                        if is_alert
                        else f"/warehouse/inventory/cursor?location_id={location_id}&limit=50"
                    )
                    bucket: list[tuple[str, float]] = []
                    request_pool_wait: list[float] = []
                    sql_token = SQL_BUCKET.set(bucket)
                    pool_token = POOL_WAIT_BUCKET.set(
                        request_pool_wait
                    )
                    request_started = time.perf_counter()
                    try:
                        started = request_started
                        response = await client.get(path)
                        elapsed_ms = (
                            time.perf_counter() - started
                        ) * 1000
                        latencies.append(elapsed_ms)
                        route_latencies[route_name].append(elapsed_ms)
                        statuses.append(response.status_code)
                        profile: dict[str, float] = {}
                        for label, sql_ms in bucket:
                            profile[label] = (
                                profile.get(label, 0.0) + sql_ms
                            )
                        profile["pool_wait"] = sum(
                            request_pool_wait
                        )
                        pool_wait_ms.append(
                            sum(request_pool_wait)
                        )
                        sql_profiles.append(profile)
                        sql_total = sum(
                            ms for _label, ms in bucket
                        )
                        sql_totals.append(sql_total)
                        outside_sql_ms.append(
                            max(
                                0.0,
                                elapsed_ms
                                - sql_total
                                - sum(request_pool_wait),
                            )
                        )
                        sql_counts.append(len(bucket))
                    finally:
                        POOL_WAIT_BUCKET.reset(pool_token)
                        SQL_BUCKET.reset(sql_token)

            await asyncio.gather(
                *(one(i) for i in range(requests))
            )
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(
                database_runtime.get_db,
                None,
            )
        else:
            app.dependency_overrides[
                database_runtime.get_db
            ] = previous_override

    labels = sorted(
        {
            label
            for profile in sql_profiles
            for label in profile
        }
    )
    label_p95 = {
        label: percentile(
            [profile.get(label, 0.0) for profile in sql_profiles],
            0.95,
        )
        for label in labels
    }
    return {
        "requests": requests,
        "concurrency": concurrency,
        "db_connection_cap": HTTP_BENCH_DB_CAP,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "max_ms": max(latencies),
        "sql_p95_ms": percentile(sql_totals, 0.95),
        "sql_statements_min": min(sql_counts),
        "sql_statements_max": max(sql_counts),
        "sql_label_p95": label_p95,
        "pool_wait_p95_ms": percentile(
            pool_wait_ms,
            0.95,
        ),
        "outside_sql_p95_ms": percentile(
            outside_sql_ms,
            0.95,
        ),
        "cursor_p95_ms": percentile(
            route_latencies["cursor"],
            0.95,
        ),
        "alerts_p95_ms": percentile(
            route_latencies["alerts"],
            0.95,
        ),
        "errors": sum(1 for status in statuses if status != 200),
    }


def print_stats(stats: Stats) -> None:
    labels = " ".join(
        f"{label}_p95={value:.1f}ms"
        for label, value in sorted(stats.sql_label_p95.items())
        if value > 0
    )
    print(
        f"{stats.name}: p50={stats.p50:.1f}ms "
        f"p95={stats.p95:.1f}ms p99={stats.p99:.1f}ms "
        f"max={stats.maximum:.1f}ms sql_p95={stats.sql_p95:.1f}ms "
        f"sql_statements={stats.statements_min}..{stats.statements_max} "
        f"samples={stats.samples}"
        + (f" {labels}" if labels else "")
    )

async def async_main(args: argparse.Namespace) -> None:
    await verify_projection_read_schema()
    driver_id = await resolve_driver_id(args.company_id, args.driver_id)
    snapshot = await dataset_snapshot(args.company_id, args.location_id)
    print("DATASET=" + json.dumps(snapshot, sort_keys=True))
    rebuild_ms = await prepare_projection(args.company_id)
    print(f"PROJECTION_PREPARE={rebuild_ms:.1f}ms driver_id={driver_id}")

    failures: list[str] = []
    if snapshot["company_variants"] < args.min_company_variants:
        failures.append(
            f"INSUFFICIENT_COMPANY_VARIANTS:{snapshot['company_variants']}<{args.min_company_variants}"
        )
    if snapshot["global_variants"] < args.min_global_variants:
        failures.append(
            f"INSUFFICIENT_GLOBAL_VARIANTS:{snapshot['global_variants']}<{args.min_global_variants}"
        )
    if snapshot["companies"] < args.min_companies:
        failures.append(
            f"INSUFFICIENT_COMPANIES:{snapshot['companies']}<{args.min_companies}"
        )

    scenarios: list[tuple[str, Callable[[Any, Driver], Awaitable[dict[str, Any]]], float]] = []
    scenarios.append(("live_50", await main_page_call(args.location_id, 50), args.max_live_p95))
    scenarios.append(("live_200", await main_page_call(args.location_id, 200), args.max_live_p95))
    scenarios.append(("summary", await inventory_summary_call(args.location_id), args.max_summary_p95))
    scenarios.append(("alerts_summary", await alert_summary_call(args.location_id), args.max_alert_p95))
    scenarios.append(("only_alerts_50", await only_alerts_call(args.location_id, 50), args.max_alert_p95))
    scenarios.append(("search_50", await search_call(args.location_id, 50, args.search), args.max_search_p95))
    scenarios.append(("cursor_page_2", await second_page_call(args.location_id, 50, args.company_id, driver_id), args.max_live_p95))

    stats_by_name: dict[str, Stats] = {}
    for name, call, threshold in scenarios:
        stats, _ = await benchmark(
            name,
            call,
            company_id=args.company_id,
            driver_id=driver_id,
            runs=args.runs,
            warmup=args.warmup,
        )
        stats_by_name[name] = stats
        print_stats(stats)
        if stats.p95 > threshold:
            failures.append(f"{name}:P95:{stats.p95:.1f}>{threshold:.1f}")
        if stats.statements_min != stats.statements_max:
            failures.append(
                f"{name}:SQL_STATEMENT_COUNT_NOT_STABLE:{stats.statements_min}..{stats.statements_max}"
            )

    # N+1/query amplification guard: page size must not increase SQL statement count.
    if (
        stats_by_name["live_50"].statements_max
        != stats_by_name["live_200"].statements_max
    ):
        failures.append(
            "N_PLUS_ONE_GUARD:live_50_and_live_200_statement_counts_differ"
        )

    prewarm_started = time.perf_counter()
    await database_runtime.warm_async_engine_pool(
        http_bench_engine,
        connections=HTTP_BENCH_POOL_SIZE,
    )
    prewarm_ms = (time.perf_counter() - prewarm_started) * 1000
    print(
        f"HTTP_POOL_PREWARM={prewarm_ms:.1f}ms "
        f"steady_connections={HTTP_BENCH_POOL_SIZE} "
        f"max_overflow={HTTP_BENCH_MAX_OVERFLOW}"
    )

    # Keep the in-process ASGI run as a SQL diagnostic only. It deliberately
    # uses one Python process, so it must not be treated as a 4-worker latency
    # verdict.
    asgi_diagnostic = await http_load(
        company_id=args.company_id,
        driver_id=driver_id,
        location_id=args.location_id,
        concurrency=min(args.concurrency, 5),
        requests=min(args.requests, 25),
    )
    print(
        "ASGI_HTTP_DIAGNOSTIC="
        + json.dumps(asgi_diagnostic, sort_keys=True)
    )
    print(
        "ASGI_HTTP_PROFILE "
        f"cursor_p95={asgi_diagnostic['cursor_p95_ms']:.1f}ms "
        f"alerts_p95={asgi_diagnostic['alerts_p95_ms']:.1f}ms "
        f"pool_wait_p95={asgi_diagnostic['pool_wait_p95_ms']:.1f}ms "
        f"sql_p95={asgi_diagnostic['sql_p95_ms']:.1f}ms "
        f"outside_sql_p95={asgi_diagnostic['outside_sql_p95_ms']:.1f}ms "
        f"labels={asgi_diagnostic['sql_label_p95']}"
    )
    if asgi_diagnostic["errors"]:
        failures.append(
            f"ASGI_HTTP_DIAGNOSTIC_ERRORS:{asgi_diagnostic['errors']}"
        )

    token = await create_benchmark_token(
        company_id=args.company_id,
        driver_id=driver_id,
    )

    # Release every parent-process DB connection before starting the four real
    # Uvicorn workers. Otherwise the benchmark itself would exceed the intended
    # 20-connection application budget.
    await engine.dispose()
    await http_bench_engine.dispose()
    await global_count_engine.dispose()

    load = await real_uvicorn_http_load(
        token=token,
        location_id=args.location_id,
        concurrency=args.concurrency,
        requests=args.requests,
    )
    print("HTTP_LOAD=" + json.dumps(load, sort_keys=True))
    print(
        "HTTP_LOAD_PROFILE "
        f"workers={load['workers']} "
        f"client={load['client']} "
        f"cursor_p95={load['cursor_p95_ms']:.1f}ms "
        f"alerts_p95={load['alerts_p95_ms']:.1f}ms "
        f"overall_p95={load['p95_ms']:.1f}ms "
        f"timeouts={load['timeouts']} "
        f"transport_errors={load['transport_errors']}"
    )
    if load["uvicorn_log_tail"]:
        print("HTTP_UVICORN_LOG_TAIL_BEGIN")
        print(load["uvicorn_log_tail"])
        print("HTTP_UVICORN_LOG_TAIL_END")
    if load["errors"]:
        failures.append(f"HTTP_LOAD_ERRORS:{load['errors']}")
    if load["p95_ms"] > args.max_http_p95:
        failures.append(
            f"HTTP_LOAD_P95:{load['p95_ms']:.1f}>{args.max_http_p95:.1f}"
        )

    print(f"CHECKS={3 + len(scenarios) * 2 + 3}")
    print(f"FAILURES={len(failures)}")
    if failures:
        for failure in failures:
            print("FAIL: " + failure)
        print("LIVE_STOCK_SCALE_GATE=FAIL")
        raise SystemExit(1)

    print("LIVE_STOCK_SCALE_GATE=PASS")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Production-oriented Live Stock performance gate: scale, alerts, "
            "search, cursor, N+1 guard and concurrent ASGI load."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--driver-id", type=int)
    parser.add_argument("--location-id", type=int, required=True)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--search", default="PERF Live Product 0001")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--requests", type=int, default=100)

    parser.add_argument("--min-company-variants", type=int, default=10000)
    parser.add_argument("--min-global-variants", type=int, default=100000)
    parser.add_argument("--min-companies", type=int, default=50)

    parser.add_argument("--max-live-p95", type=float, default=150.0)
    parser.add_argument("--max-summary-p95", type=float, default=75.0)
    parser.add_argument("--max-alert-p95", type=float, default=75.0)
    parser.add_argument("--max-search-p95", type=float, default=250.0)
    parser.add_argument("--max-http-p95", type=float, default=500.0)

    args = parser.parse_args()
    if args.runs < 10:
        parser.error("--runs must be >= 10 for a meaningful p95/p99")
    if args.warmup < 1:
        parser.error("--warmup must be >= 1")
    if not 1 <= args.concurrency <= 100:
        parser.error("--concurrency must be between 1 and 100")
    if args.requests < args.concurrency:
        parser.error("--requests must be >= --concurrency")
    return args

async def _dispose_benchmark_engines() -> None:
    await engine.dispose()
    await http_bench_engine.dispose()
    await global_count_engine.dispose()


async def _run() -> None:
    for tracked_engine in (engine, http_bench_engine):
        event.listen(
            tracked_engine.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )
        event.listen(
            tracked_engine.sync_engine,
            "after_cursor_execute",
            after_cursor_execute,
        )
    try:
        await async_main(parse_args())
    finally:
        for tracked_engine in (engine, http_bench_engine):
            event.remove(
                tracked_engine.sync_engine,
                "before_cursor_execute",
                before_cursor_execute,
            )
            event.remove(
                tracked_engine.sync_engine,
                "after_cursor_execute",
                after_cursor_execute,
            )
        await _dispose_benchmark_engines()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
