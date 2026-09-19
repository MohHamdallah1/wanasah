from __future__ import annotations

import argparse
import asyncio
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import event, select, text


def find_backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        Path.cwd(),
        Path.cwd() / "wa_backend",
        here.parent,
        here.parent.parent,
        here.parent / "wa_backend",
    )
    for candidate in candidates:
        if (candidate / "main.py").is_file() and (candidate / "database.py").is_file():
            return candidate.resolve()
    raise RuntimeError(
        "لم أجد wa_backend. ضع الملف داخل wa_backend/scripts أو شغله من جذر المشروع."
    )


BACKEND_ROOT = find_backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from context import tenant_context  # noqa: E402
from database import AsyncSessionLocal, engine  # noqa: E402
from models import Driver  # noqa: E402
from api.warehouse import get_warehouse_inventory  # noqa: E402


SQL_SAMPLES: list[tuple[float, str]] = []


def normalize_sql(statement: str) -> str:
    return re.sub(r"\s+", " ", statement).strip()[:360]


def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._live_stock_profile_started = time.perf_counter()


def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    started = getattr(context, "_live_stock_profile_started", None)
    if started is None:
        return
    SQL_SAMPLES.append(
        ((time.perf_counter() - started) * 1000, normalize_sql(statement))
    )


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


async def request_once(
    db,
    driver: Driver,
    *,
    location_id: int,
    limit: int,
    search: str | None,
    only_alerts: bool,
) -> dict[str, Any]:
    SQL_SAMPLES.clear()
    started = time.perf_counter()

    payload = await get_warehouse_inventory(
        location_id=location_id,
        cursor=None,
        limit=limit,
        search=search,
        only_alerts=only_alerts,
        db=db,
        current_admin=driver,
    )

    total_ms = (time.perf_counter() - started) * 1000
    items = payload.get("items", [])

    return {
        "total_ms": total_ms,
        "sql_ms": sum(ms for ms, _ in SQL_SAMPLES),
        "sql_count": len(SQL_SAMPLES),
        "sql_samples": list(SQL_SAMPLES),
        "items": len(items),
        "has_more": payload.get("has_more"),
        "total": payload.get("total"),
        "alert_count": payload.get("alert_count"),
    }


async def benchmark_case(
    db,
    driver: Driver,
    *,
    location_id: int,
    limit: int,
    runs: int,
    warmup: int,
    search: str | None,
    only_alerts: bool,
) -> None:
    for _ in range(warmup):
        await request_once(
            db,
            driver,
            location_id=location_id,
            limit=limit,
            search=search,
            only_alerts=only_alerts,
        )

    results = []
    statement_totals: dict[str, list[float]] = defaultdict(list)

    for _ in range(runs):
        result = await request_once(
            db,
            driver,
            location_id=location_id,
            limit=limit,
            search=search,
            only_alerts=only_alerts,
        )
        results.append(result)
        for ms, statement in result["sql_samples"]:
            statement_totals[statement].append(ms)

    total_times = [r["total_ms"] for r in results]
    sql_times = [r["sql_ms"] for r in results]
    sql_counts = [r["sql_count"] for r in results]
    last = results[-1]

    print("\n" + "=" * 96)
    print(
        f"location={location_id} limit={limit} runs={runs} "
        f"items={last['items']} total={last['total']} "
        f"has_more={last['has_more']} alert_count={last['alert_count']}"
    )
    print(
        "ENDPOINT CORE ms: "
        f"min={min(total_times):.1f} "
        f"p50={statistics.median(total_times):.1f} "
        f"p95={percentile(total_times, 0.95):.1f} "
        f"max={max(total_times):.1f}"
    )
    print(
        "SQL ms:           "
        f"min={min(sql_times):.1f} "
        f"p50={statistics.median(sql_times):.1f} "
        f"p95={percentile(sql_times, 0.95):.1f} "
        f"max={max(sql_times):.1f}"
    )
    print(
        "SQL statements/request: "
        f"min={min(sql_counts)} "
        f"avg={statistics.mean(sql_counts):.1f} "
        f"max={max(sql_counts)}"
    )

    ranked = sorted(
        (
            (sum(times), max(times), len(times), statement)
            for statement, times in statement_totals.items()
        ),
        reverse=True,
    )[:12]

    print("\nأثقل SQL حسب مجموع الزمن:")
    for index, (total, max_ms, count, statement) in enumerate(ranked, 1):
        print(
            f"{index:02d}. total={total:.1f}ms "
            f"avg={total / count:.1f}ms "
            f"max={max_ms:.1f}ms executions={count}"
        )
        print(f"    {statement}")


async def async_main(args: argparse.Namespace) -> None:
    locations = [int(v) for v in args.locations.split(",") if v.strip()]
    limits = [int(v) for v in args.limits.split(",") if v.strip()]

    if not locations:
        raise RuntimeError("يجب تحديد مستودع واحد على الأقل.")
    if not limits or any(v < 1 or v > 200 for v in limits):
        raise RuntimeError("كل limit يجب أن يكون بين 1 و200.")
    if args.company_id <= 0 or args.driver_id <= 0:
        raise RuntimeError("company-id و driver-id يجب أن يكونا أكبر من صفر.")

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine.sync_engine, "after_cursor_execute", after_cursor_execute)

    token = tenant_context.set(args.company_id)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant', :c, false)"),
                {"c": str(args.company_id)},
            )

            driver = await db.scalar(
                select(Driver).where(
                    Driver.id == args.driver_id,
                    Driver.company_id == args.company_id,
                )
            )
            if driver is None:
                raise RuntimeError(
                    "لم أجد المستخدم داخل الشركة المحددة. تحقق من company-id و driver-id."
                )

            for location_id in locations:
                for limit in limits:
                    await benchmark_case(
                        db,
                        driver,
                        location_id=location_id,
                        limit=limit,
                        runs=args.runs,
                        warmup=args.warmup,
                        search=args.search,
                        only_alerts=args.only_alerts,
                    )
    finally:
        tenant_context.reset(token)
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine.sync_engine, "after_cursor_execute", after_cursor_execute)
        await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only profiler لمسار Live Stock نفسه مباشرةً داخل الباك إند، "
            "بدون JWT أو HTTP حتى نعزل زمن SQL والمنطق الحقيقي."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--driver-id", type=int, required=True)
    parser.add_argument("--locations", default="61,119")
    parser.add_argument("--limits", default="50,100,200")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--search", default=None)
    parser.add_argument("--only-alerts", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.runs < 1 or args.warmup < 0:
        raise SystemExit("--runs يجب أن يكون >= 1 و --warmup يجب أن يكون >= 0")
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
