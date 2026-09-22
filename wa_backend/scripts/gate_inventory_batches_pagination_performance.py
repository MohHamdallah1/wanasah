from __future__ import annotations

import argparse
import ast
import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event


def find_backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        Path.cwd() / "wa_backend",
        here.parent.parent / "wa_backend",
        here.parent.parent,
        here.parent,
    )
    for candidate in candidates:
        if (
            (candidate / "main.py").is_file()
            and (candidate / "database.py").is_file()
        ):
            return candidate.resolve()
    raise RuntimeError("wa_backend not found.")


BACKEND_ROOT = find_backend_root()
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import api.warehouse.live_stock as live_stock  # noqa: E402
from context import tenant_context  # noqa: E402
from database import engine  # noqa: E402
from models import InventoryBalance, ProductBatch  # noqa: E402
from scripts.gate_inventory_batches_roundtrip import (  # noqa: E402
    SQL_BUCKET,
    after_cursor_execute,
    before_cursor_execute,
    percentile,
    prepare_session,
    resolve_driver_id,
    resolve_target,
)

BASELINE_COMMIT = "4de5cb918e5b41891eda8f0d39fad02b2499d5d8"


def load_baseline_endpoint():
    source = subprocess.check_output(
        [
            "git",
            "show",
            f"{BASELINE_COMMIT}:wa_backend/api/warehouse/live_stock.py",
        ],
        cwd=REPO_ROOT,
        encoding="utf-8",
    )
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "get_warehouse_inventory_batches"
    )
    function.decorator_list = []
    function.name = "baseline_get_warehouse_inventory_batches"

    namespace = dict(vars(live_stock))
    exec(
        compile(
            ast.fix_missing_locations(
                ast.Module(body=[function], type_ignores=[])
            ),
            "baseline_inventory_batches",
            "exec",
        ),
        namespace,
    )
    return namespace["baseline_get_warehouse_inventory_batches"]


BASELINE_ENDPOINT = load_baseline_endpoint()


@dataclass(frozen=True)
class PerfSample:
    elapsed_ms: float
    sql_ms: float
    sql_count: int
    row_count: int
    has_more: bool | None


async def measure_call(
    endpoint,
    *,
    db,
    driver,
    location_id: int,
    product_variant_id: int,
    paginated: bool,
) -> PerfSample:
    bucket: list[tuple[str, float]] = []
    token = SQL_BUCKET.set(bucket)
    try:
        started = time.perf_counter()
        if paginated:
            payload = await endpoint(
                product_variant_id=product_variant_id,
                location_id=location_id,
                cursor=None,
                limit=100,
                db=db,
                current_admin=driver,
            )
        else:
            payload = await endpoint(
                product_variant_id=product_variant_id,
                location_id=location_id,
                db=db,
                current_admin=driver,
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
    finally:
        SQL_BUCKET.reset(token)

    batches = payload.get("batches")
    if not isinstance(batches, list):
        raise RuntimeError("Benchmark endpoint lost batches response.")

    return PerfSample(
        elapsed_ms=elapsed_ms,
        sql_ms=sum(duration for _label, duration in bucket),
        sql_count=len(bucket),
        row_count=len(batches),
        has_more=payload.get("has_more"),
    )


async def benchmark_pair(
    *,
    db,
    driver,
    location_id: int,
    product_variant_id: int,
    runs: int,
    warmup: int,
) -> tuple[list[PerfSample], list[PerfSample]]:
    for _ in range(warmup):
        await measure_call(
            BASELINE_ENDPOINT,
            db=db,
            driver=driver,
            location_id=location_id,
            product_variant_id=product_variant_id,
            paginated=False,
        )
        await measure_call(
            live_stock.get_warehouse_inventory_batches,
            db=db,
            driver=driver,
            location_id=location_id,
            product_variant_id=product_variant_id,
            paginated=True,
        )

    baseline_samples: list[PerfSample] = []
    current_samples: list[PerfSample] = []

    for index in range(runs):
        order = (
            ("baseline", "current")
            if index % 2 == 0
            else ("current", "baseline")
        )
        for name in order:
            if name == "baseline":
                baseline_samples.append(
                    await measure_call(
                        BASELINE_ENDPOINT,
                        db=db,
                        driver=driver,
                        location_id=location_id,
                        product_variant_id=product_variant_id,
                        paginated=False,
                    )
                )
            else:
                current_samples.append(
                    await measure_call(
                        live_stock.get_warehouse_inventory_batches,
                        db=db,
                        driver=driver,
                        location_id=location_id,
                        product_variant_id=product_variant_id,
                        paginated=True,
                    )
                )

    return baseline_samples, current_samples


def print_summary(
    label: str,
    baseline: list[PerfSample],
    current: list[PerfSample],
) -> None:
    def metrics(samples: list[PerfSample]) -> str:
        elapsed = [sample.elapsed_ms for sample in samples]
        sql_ms = [sample.sql_ms for sample in samples]
        sql_counts = [sample.sql_count for sample in samples]
        row_counts = [sample.row_count for sample in samples]
        return (
            f"rows={min(row_counts)}..{max(row_counts)} "
            f"sql={min(sql_counts)}..{max(sql_counts)} "
            f"p50={percentile(elapsed, 0.50):.2f}ms "
            f"p95={percentile(elapsed, 0.95):.2f}ms "
            f"sql_p95={percentile(sql_ms, 0.95):.2f}ms"
        )

    print(f"{label}_BASELINE {metrics(baseline)}")
    print(f"{label}_PAGINATED {metrics(current)}")


async def add_scale_fixture(
    *,
    db,
    company_id: int,
    location_id: int,
    product_variant_id: int,
    count: int,
) -> None:
    prefix = f"perf-page-{uuid4().hex[:12]}"
    base_expiry = date(2035, 1, 1)
    batches: list[ProductBatch] = []

    for index in range(count):
        batch = ProductBatch(
            company_id=company_id,
            product_variant_id=product_variant_id,
            batch_number=f"{prefix}-{index:04d}",
            production_date=None,
            expiry_date=(
                None
                if index >= count - 2
                else base_expiry + timedelta(days=index)
            ),
            disposition="RELEASED",
        )
        db.add(batch)
        batches.append(batch)

    await db.flush()

    db.add_all(
        [
            InventoryBalance(
                company_id=company_id,
                location_id=location_id,
                product_variant_id=product_variant_id,
                batch_id=int(batch.id),
                stock_status="AVAILABLE",
                on_hand_quantity=1,
                reserved_quantity=0,
            )
            for batch in batches
        ]
    )
    await db.flush()


async def async_main(args: argparse.Namespace) -> None:
    driver_id = await resolve_driver_id(args.company_id, args.driver_id)
    location_id, product_variant_id = await resolve_target(
        args.company_id,
        args.location_id,
        args.product_variant_id,
    )

    db, driver, tenant_token = await prepare_session(
        args.company_id,
        driver_id,
    )
    try:
        print(
            "TARGET "
            f"company_id={args.company_id} "
            f"driver_id={driver_id} "
            f"location_id={location_id} "
            f"product_variant_id={product_variant_id} "
            f"fixture_batches={args.fixture_batches}"
        )

        small_baseline, small_current = await benchmark_pair(
            db=db,
            driver=driver,
            location_id=location_id,
            product_variant_id=product_variant_id,
            runs=args.runs,
            warmup=args.warmup,
        )
        print_summary("SMALL", small_baseline, small_current)

        small_baseline_rows = {
            sample.row_count for sample in small_baseline
        }
        if len(small_baseline_rows) != 1:
            raise RuntimeError(
                "Stable baseline row count changed during small benchmark."
            )
        pre_fixture_rows = next(iter(small_baseline_rows))

        await add_scale_fixture(
            db=db,
            company_id=args.company_id,
            location_id=location_id,
            product_variant_id=product_variant_id,
            count=args.fixture_batches,
        )

        scale_baseline, scale_current = await benchmark_pair(
            db=db,
            driver=driver,
            location_id=location_id,
            product_variant_id=product_variant_id,
            runs=args.runs,
            warmup=args.warmup,
        )
        print_summary("SCALE", scale_baseline, scale_current)

        expected_scale_rows = pre_fixture_rows + args.fixture_batches
        scale_baseline_rows = {
            sample.row_count for sample in scale_baseline
        }
        if scale_baseline_rows != {expected_scale_rows}:
            raise RuntimeError(
                "Scale fixture cardinality mismatch: "
                f"expected={expected_scale_rows} "
                f"observed={sorted(scale_baseline_rows)} "
                f"fixture_batches={args.fixture_batches}"
            )
        print(
            "SCALE_FIXTURE "
            f"before={pre_fixture_rows} "
            f"added={args.fixture_batches} "
            f"expected={expected_scale_rows} "
            f"observed={expected_scale_rows}"
        )

        if not all(
            sample.sql_count == 5
            for sample in small_current + scale_current
        ):
            raise RuntimeError(
                "Paginated endpoint no longer holds the five-query bounded budget."
            )
        if not all(
            sample.row_count <= 100
            for sample in scale_current
        ):
            raise RuntimeError(
                "Paginated endpoint exceeded the requested page size."
            )
        if not all(
            sample.has_more is True
            for sample in scale_current
        ):
            raise RuntimeError(
                "Scale first page did not expose continuation."
            )

        print(
            "INVENTORY_BATCHES_PAGINATION_PERF=PASS "
            "fixtures_rolled_back=true"
        )
    finally:
        await db.rollback()
        tenant_context.reset(tenant_token)
        await db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "A/B benchmark the stable unbounded batch endpoint against "
            "the bounded keyset implementation in the same DB session."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--driver-id", type=int)
    parser.add_argument("--location-id", type=int)
    parser.add_argument("--product-variant-id", type=int)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--fixture-batches", type=int, default=205)
    args = parser.parse_args()

    if args.company_id <= 0:
        parser.error("--company-id must be positive")
    if args.runs < 10:
        parser.error("--runs must be >= 10")
    if args.warmup < 1:
        parser.error("--warmup must be >= 1")
    if args.fixture_batches < 200:
        parser.error("--fixture-batches must be >= 200")
    return args


async def _run() -> None:
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        before_cursor_execute,
    )
    event.listen(
        engine.sync_engine,
        "after_cursor_execute",
        after_cursor_execute,
    )
    try:
        await async_main(parse_args())
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )
        event.remove(
            engine.sync_engine,
            "after_cursor_execute",
            after_cursor_execute,
        )
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
