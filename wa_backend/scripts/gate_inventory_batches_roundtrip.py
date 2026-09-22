from __future__ import annotations

import argparse
import asyncio
import contextvars
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
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
        if (
            (candidate / "main.py").is_file()
            and (candidate / "database.py").is_file()
        ):
            return candidate.resolve()
    raise RuntimeError(
        "wa_backend not found. Run from repository root or place this file "
        "in wa_backend/scripts/."
    )


BACKEND_ROOT = find_backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.warehouse.live_stock import get_warehouse_inventory_batches  # noqa: E402
from context import tenant_context  # noqa: E402
from database import AsyncSessionLocal, engine  # noqa: E402
from models import Driver, InventoryBalance, InventoryLocation, ProductVariant  # noqa: E402


SQL_BUCKET: contextvars.ContextVar[list[tuple[str, float]] | None] = (
    contextvars.ContextVar(
        "inventory_batches_roundtrip_sql_bucket",
        default=None,
    )
)


def _sql_label(statement: str) -> str:
    normalized = " ".join(statement.lower().split())

    if "inventory_cost_events" in normalized:
        if "count(" in normalized:
            return "purchase_count"
        return "latest_purchase"

    if (
        "inventory_balances" in normalized
        and "product_batches" in normalized
    ):
        return "batch_aggregate"

    if "current_timestamp at time zone" in normalized:
        return "company_local_date"

    if "product_variants" in normalized:
        return "variant"

    if "companies" in normalized:
        return "company"

    if "inventory_locations" in normalized:
        if (
            "user_location_access" in normalized
            or "role_permissions" in normalized
        ):
            return "location_access"
        return "location"

    if (
        "user_location_access" in normalized
        or "role_permissions" in normalized
        or "permissions" in normalized
    ):
        return "access"

    if normalized.startswith("select true"):
        return "access"

    return normalized.split(" ", 1)[0] if normalized else "unknown"


def before_cursor_execute(
    conn,
    cursor,
    statement,
    parameters,
    context,
    executemany,
):
    bucket = SQL_BUCKET.get()
    if bucket is None:
        return
    context._inventory_batches_roundtrip_started = time.perf_counter()
    context._inventory_batches_roundtrip_label = _sql_label(statement)


def after_cursor_execute(
    conn,
    cursor,
    statement,
    parameters,
    context,
    executemany,
):
    bucket = SQL_BUCKET.get()
    started = getattr(
        context,
        "_inventory_batches_roundtrip_started",
        None,
    )
    if bucket is None or started is None:
        return
    bucket.append(
        (
            getattr(
                context,
                "_inventory_batches_roundtrip_label",
                "unknown",
            ),
            (time.perf_counter() - started) * 1000,
        )
    )


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


@dataclass(frozen=True)
class Sample:
    elapsed_ms: float
    sql_ms: float
    sql_labels: tuple[str, ...]

    @property
    def sql_count(self) -> int:
        return len(self.sql_labels)


async def _set_tenant(db, company_id: int) -> None:
    await db.execute(
        text("SELECT set_config('app.current_tenant', :company_id, false)"),
        {"company_id": str(company_id)},
    )


async def resolve_driver_id(
    company_id: int,
    requested_driver_id: int | None,
) -> int:
    token = tenant_context.set(company_id)
    try:
        async with AsyncSessionLocal() as db:
            await _set_tenant(db, company_id)
            stmt = select(Driver.id).where(
                Driver.company_id == company_id,
                Driver.is_active.is_(True),
            )
            if requested_driver_id is not None:
                driver_id = await db.scalar(
                    stmt.where(Driver.id == requested_driver_id)
                )
                if driver_id is None:
                    raise RuntimeError(
                        "Requested active driver was not found in the company."
                    )
                return int(driver_id)

            driver_id = await db.scalar(
                stmt.order_by(Driver.is_admin.desc(), Driver.id.asc()).limit(1)
            )
            if driver_id is None:
                raise RuntimeError(
                    "No active driver is available for the benchmark company."
                )
            return int(driver_id)
    finally:
        tenant_context.reset(token)


async def resolve_target(
    company_id: int,
    location_id: int | None,
    product_variant_id: int | None,
) -> tuple[int, int]:
    token = tenant_context.set(company_id)
    try:
        async with AsyncSessionLocal() as db:
            await _set_tenant(db, company_id)

            resolved_location_id = location_id
            if resolved_location_id is None:
                resolved_location_id = await db.scalar(
                    select(InventoryLocation.id)
                    .join(
                        InventoryBalance,
                        InventoryBalance.location_id
                        == InventoryLocation.id,
                    )
                    .where(
                        InventoryLocation.company_id == company_id,
                        InventoryLocation.location_type == "WAREHOUSE",
                        InventoryLocation.is_active.is_(True),
                        InventoryBalance.company_id == company_id,
                        InventoryBalance.batch_id.isnot(None),
                        InventoryBalance.on_hand_quantity > 0,
                    )
                    .group_by(InventoryLocation.id)
                    .order_by(
                        func.count(
                            func.distinct(InventoryBalance.batch_id)
                        ).desc(),
                        InventoryLocation.id.asc(),
                    )
                    .limit(1)
                )
            if resolved_location_id is None:
                raise RuntimeError(
                    "No active warehouse with positive batched stock was found."
                )
            resolved_location_id = int(resolved_location_id)

            if product_variant_id is not None:
                variant_id = await db.scalar(
                    select(ProductVariant.id).where(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id == product_variant_id,
                    )
                )
                if variant_id is None:
                    raise RuntimeError(
                        "Requested product variant was not found in the company."
                    )
                return resolved_location_id, int(variant_id)

            variant_id = await db.scalar(
                select(InventoryBalance.product_variant_id)
                .where(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id == resolved_location_id,
                    InventoryBalance.batch_id.isnot(None),
                    InventoryBalance.on_hand_quantity > 0,
                )
                .group_by(InventoryBalance.product_variant_id)
                .order_by(
                    func.count(
                        func.distinct(InventoryBalance.batch_id)
                    ).desc(),
                    InventoryBalance.product_variant_id.asc(),
                )
                .limit(1)
            )
            if variant_id is None:
                raise RuntimeError(
                    "No product variant with positive batched stock was found "
                    "in the selected warehouse."
                )
            return resolved_location_id, int(variant_id)
    finally:
        tenant_context.reset(token)


async def prepare_session(company_id: int, driver_id: int):
    db = AsyncSessionLocal()
    token = tenant_context.set(company_id)
    try:
        await _set_tenant(db, company_id)
        driver = await db.scalar(
            select(Driver).where(
                Driver.company_id == company_id,
                Driver.id == driver_id,
                Driver.is_active.is_(True),
            )
        )
        if driver is None:
            raise RuntimeError("Benchmark driver is no longer available.")
        return db, driver, token
    except Exception:
        tenant_context.reset(token)
        await db.close()
        raise


def validate_payload(
    payload: dict[str, Any],
    *,
    location_id: int,
    product_variant_id: int,
) -> None:
    if payload.get("location_id") != location_id:
        raise RuntimeError("Batch response location scope changed.")
    if payload.get("product_variant_id") != product_variant_id:
        raise RuntimeError("Batch response product scope changed.")

    currency_code = payload.get("currency_code")
    if not isinstance(currency_code, str) or not currency_code.strip():
        raise RuntimeError("Batch response currency contract changed.")

    batches = payload.get("batches")
    if not isinstance(batches, list):
        raise RuntimeError("Batch response batches contract changed.")
    if not batches:
        raise RuntimeError(
            "Selected benchmark product produced no batch rows."
        )

    required = {
        "batch_id",
        "batch_number",
        "production_date",
        "expiry_date",
        "disposition",
        "days_to_expiry",
        "on_hand_quantity",
        "reserved_quantity",
        "available_for_sale_quantity",
        "unavailable_quantity",
        "restricted_quantity",
        "quarantined_quantity",
        "blocked_quantity",
        "recalled_quantity",
        "damaged_quantity",
        "disposal_pending_quantity",
        "latest_purchase_cost",
        "latest_purchase_uom_code",
        "latest_purchase_date",
        "purchase_event_count",
    }
    for batch in batches:
        if not isinstance(batch, dict):
            raise RuntimeError("Batch response item is no longer an object.")
        missing = required - set(batch)
        if missing:
            raise RuntimeError(
                "Batch response item lost fields: "
                + ", ".join(sorted(missing))
            )
        if int(batch["purchase_event_count"]) < 0:
            raise RuntimeError(
                "Batch purchase_event_count became negative."
            )


async def timed_endpoint_call(
    *,
    company_id: int,
    driver_id: int,
    location_id: int,
    product_variant_id: int,
) -> tuple[Sample, dict[str, Any]]:
    db, driver, tenant_token = await prepare_session(
        company_id,
        driver_id,
    )
    bucket: list[tuple[str, float]] = []
    sql_token = SQL_BUCKET.set(bucket)
    try:
        started = time.perf_counter()
        payload = await get_warehouse_inventory_batches(
            product_variant_id=product_variant_id,
            location_id=location_id,
            db=db,
            current_admin=driver,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        validate_payload(
            payload,
            location_id=location_id,
            product_variant_id=product_variant_id,
        )
        return (
            Sample(
                elapsed_ms=elapsed_ms,
                sql_ms=sum(duration for _label, duration in bucket),
                sql_labels=tuple(label for label, _duration in bucket),
            ),
            payload,
        )
    finally:
        SQL_BUCKET.reset(sql_token)
        tenant_context.reset(tenant_token)
        await db.close()


async def assert_missing_variant_404(
    *,
    company_id: int,
    driver_id: int,
    location_id: int,
) -> None:
    token = tenant_context.set(company_id)
    try:
        async with AsyncSessionLocal() as db:
            await _set_tenant(db, company_id)
            max_variant_id = await db.scalar(
                select(func.max(ProductVariant.id)).where(
                    ProductVariant.company_id == company_id
                )
            )
    finally:
        tenant_context.reset(token)

    missing_variant_id = int(max_variant_id or 0) + 1
    if missing_variant_id <= 0:
        raise RuntimeError("Could not derive a missing variant id.")

    db, driver, tenant_token = await prepare_session(
        company_id,
        driver_id,
    )
    try:
        try:
            await get_warehouse_inventory_batches(
                product_variant_id=missing_variant_id,
                location_id=location_id,
                db=db,
                current_admin=driver,
            )
        except HTTPException as exc:
            if exc.status_code != 404:
                raise RuntimeError(
                    "Missing product variant no longer returns 404."
                ) from exc
        else:
            raise RuntimeError(
                "Missing product variant unexpectedly succeeded."
            )
    finally:
        tenant_context.reset(tenant_token)
        await db.close()


async def async_main(args: argparse.Namespace) -> None:
    driver_id = await resolve_driver_id(
        args.company_id,
        args.driver_id,
    )
    location_id, product_variant_id = await resolve_target(
        args.company_id,
        args.location_id,
        args.product_variant_id,
    )

    print(
        "TARGET "
        f"company_id={args.company_id} "
        f"driver_id={driver_id} "
        f"location_id={location_id} "
        f"product_variant_id={product_variant_id}"
    )

    for _ in range(args.warmup):
        await timed_endpoint_call(
            company_id=args.company_id,
            driver_id=driver_id,
            location_id=location_id,
            product_variant_id=product_variant_id,
        )

    samples: list[Sample] = []
    last_payload: dict[str, Any] | None = None
    for _ in range(args.runs):
        sample, last_payload = await timed_endpoint_call(
            company_id=args.company_id,
            driver_id=driver_id,
            location_id=location_id,
            product_variant_id=product_variant_id,
        )
        samples.append(sample)

    await assert_missing_variant_404(
        company_id=args.company_id,
        driver_id=driver_id,
        location_id=location_id,
    )

    counts = [sample.sql_count for sample in samples]
    latencies = [sample.elapsed_ms for sample in samples]
    sql_times = [sample.sql_ms for sample in samples]
    sequences = {sample.sql_labels for sample in samples}

    failures: list[str] = []
    if min(counts) != max(counts):
        failures.append(
            "SQL_STATEMENT_COUNT_NOT_STABLE:"
            f"{min(counts)}..{max(counts)}"
        )
    if max(counts) > args.max_sql_statements:
        failures.append(
            "SQL_STATEMENT_BUDGET:"
            f"{max(counts)}>{args.max_sql_statements}"
        )
    if len(sequences) != 1:
        failures.append("SQL_SEQUENCE_NOT_STABLE")

    sequence = next(iter(sequences)) if len(sequences) == 1 else ()
    print(
        "BASELINE "
        f"runs={args.runs} "
        f"warmup={args.warmup} "
        f"batches={len((last_payload or {}).get('batches', []))} "
        f"sql_statements={min(counts)}..{max(counts)} "
        f"p50={percentile(latencies, 0.50):.2f}ms "
        f"p95={percentile(latencies, 0.95):.2f}ms "
        f"max={max(latencies):.2f}ms "
        f"sql_p95={percentile(sql_times, 0.95):.2f}ms"
    )
    print("SQL_SEQUENCE=" + " -> ".join(sequence))
    print("CHECKS=4")
    print(f"FAILURES={len(failures)}")

    if failures:
        for failure in failures:
            print("FAIL: " + failure)
        print("INVENTORY_BATCHES_ROUNDTRIP_GATE=FAIL")
        raise SystemExit(1)

    print("INVENTORY_BATCHES_ROUNDTRIP_GATE=PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure and gate get_warehouse_inventory_batches DB round-trips "
            "without changing endpoint semantics."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--driver-id", type=int)
    parser.add_argument("--location-id", type=int)
    parser.add_argument("--product-variant-id", type=int)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--max-sql-statements", type=int, default=10)

    args = parser.parse_args()
    if args.company_id <= 0:
        parser.error("--company-id must be positive")
    if args.driver_id is not None and args.driver_id <= 0:
        parser.error("--driver-id must be positive")
    if args.location_id is not None and args.location_id <= 0:
        parser.error("--location-id must be positive")
    if (
        args.product_variant_id is not None
        and args.product_variant_id <= 0
    ):
        parser.error("--product-variant-id must be positive")
    if args.runs < 10:
        parser.error("--runs must be >= 10 for a useful p95")
    if args.warmup < 1:
        parser.error("--warmup must be >= 1")
    if args.max_sql_statements < 1:
        parser.error("--max-sql-statements must be >= 1")
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
