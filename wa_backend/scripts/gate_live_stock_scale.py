from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import event, func, select, text

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

SQL_BUCKET: contextvars.ContextVar[list[float] | None] = contextvars.ContextVar(
    "live_stock_scale_sql_bucket",
    default=None,
)

def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    bucket = SQL_BUCKET.get()
    if bucket is not None:
        context._live_stock_scale_started = time.perf_counter()

def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    bucket = SQL_BUCKET.get()
    started = getattr(context, "_live_stock_scale_started", None)
    if bucket is not None and started is not None:
        bucket.append((time.perf_counter() - started) * 1000)

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

def summarize(name: str, rows: list[Sample]) -> Stats:
    times = [r.ms for r in rows]
    sql = [r.sql_ms for r in rows]
    counts = [r.sql_count for r in rows]
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
    sql_bucket: list[float] = []
    sql_token = SQL_BUCKET.set(sql_bucket)
    try:
        started = time.perf_counter()
        payload = await call(db, driver)
        elapsed = (time.perf_counter() - started) * 1000
        items = payload.get("items")
        return Sample(
            ms=elapsed,
            sql_ms=sum(sql_bucket),
            sql_count=len(sql_bucket),
            items=len(items) if isinstance(items, list) else None,
            total=payload.get("total") if isinstance(payload.get("total"), int) else None,
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
            global_variants = int(
                await db.scalar(select(func.count()).select_from(ProductVariant)) or 0
            )
            companies = int(
                await db.scalar(select(func.count()).select_from(Company)) or 0
            )
            return {
                "company_variants": variants,
                "location_balances": balances,
                "location_policies": policies,
                "global_variants": global_variants,
                "companies": companies,
            }
    finally:
        tenant_context.reset(token)

async def http_load(
    *,
    company_id: int,
    driver_id: int,
    location_id: int,
    concurrency: int,
    requests: int,
) -> dict[str, Any]:
    token_ctx = tenant_context.set(company_id)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant', :c, false)"),
                {"c": str(company_id)},
            )
            driver = await load_driver(db, company_id, driver_id)
            token = create_access_token(
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

    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"}
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: list[int] = []

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://wanasah-perf.local",
        headers=headers,
        timeout=30.0,
    ) as client:
        async def one(index: int):
            async with sem:
                path = (
                    f"/warehouse/inventory/alerts/summary?location_id={location_id}"
                    if index % 5 == 0
                    else f"/warehouse/inventory/cursor?location_id={location_id}&limit=50"
                )
                started = time.perf_counter()
                response = await client.get(path)
                latencies.append((time.perf_counter() - started) * 1000)
                statuses.append(response.status_code)

        await asyncio.gather(*(one(i) for i in range(requests)))

    return {
        "requests": requests,
        "concurrency": concurrency,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "max_ms": max(latencies),
        "errors": sum(1 for status in statuses if status != 200),
    }

def print_stats(stats: Stats) -> None:
    print(
        f"{stats.name}: p50={stats.p50:.1f}ms "
        f"p95={stats.p95:.1f}ms p99={stats.p99:.1f}ms "
        f"max={stats.maximum:.1f}ms sql_p95={stats.sql_p95:.1f}ms "
        f"sql_statements={stats.statements_min}..{stats.statements_max} "
        f"samples={stats.samples}"
    )

async def async_main(args: argparse.Namespace) -> None:
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
    scenarios.append(("cursor_page_2", await second_page_call(args.location_id, 50, args.company_id, args.driver_id), args.max_live_p95))

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

    load = await http_load(
        company_id=args.company_id,
        driver_id=driver_id,
        location_id=args.location_id,
        concurrency=args.concurrency,
        requests=args.requests,
    )
    print("HTTP_LOAD=" + json.dumps(load, sort_keys=True))
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

def main() -> None:
    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine.sync_engine, "after_cursor_execute", after_cursor_execute)
    try:
        asyncio.run(async_main(parse_args()))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine.sync_engine, "after_cursor_execute", after_cursor_execute)

if __name__ == "__main__":
    main()
