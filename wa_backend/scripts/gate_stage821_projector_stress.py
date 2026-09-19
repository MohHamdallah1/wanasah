from __future__ import annotations

import argparse
import asyncio
import contextvars
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env", override=False)

from domains.live_stock_projection.service import (
    apply_live_stock_balance_impacts,
    refresh_live_stock_keys,
)

HOT_PRODUCT_CODE = "__PERF_LIVE_STOCK_SCALE__"
NOISE_COMPANY_PREFIX = "PERFNOISE-"

APP_URL = os.environ["DATABASE_URL"]
MIGRATION_URL = os.environ["DATABASE_URL_MIGRATION"]

# Aggregate production-equivalent DB budget:
# 4 workers × (8 steady + 2 overflow) = 40 maximum PostgreSQL connections.
STRESS_POOL_SIZE = int(os.environ.get("STAGE821_STRESS_POOL_SIZE", "32"))
STRESS_MAX_OVERFLOW = int(
    os.environ.get("STAGE821_STRESS_MAX_OVERFLOW", "8")
)
STRESS_DB_CONNECTION_CAP = STRESS_POOL_SIZE + STRESS_MAX_OVERFLOW
if STRESS_DB_CONNECTION_CAP != 40:
    raise RuntimeError(
        "Stage 8.2.1 hard stress gate requires an aggregate DB cap of 40 "
        f"connections; got {STRESS_DB_CONNECTION_CAP}."
    )

engine_app = create_async_engine(
    APP_URL,
    pool_size=STRESS_POOL_SIZE,
    max_overflow=STRESS_MAX_OVERFLOW,
    pool_timeout=3,
    pool_recycle=1800,
    pool_use_lifo=True,
    pool_pre_ping=True,
)
engine_su = create_async_engine(
    MIGRATION_URL,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
)
SessionApp = async_sessionmaker(
    engine_app, expire_on_commit=False, autobegin=False
)
SessionSU = async_sessionmaker(
    engine_su, expire_on_commit=False, autobegin=False
)


SQL_BUCKET: contextvars.ContextVar[list[tuple[str, float]] | None] = (
    contextvars.ContextVar("stage821_projector_sql_bucket", default=None)
)


def _sql_label(statement: str) -> str:
    normalized = " ".join(statement.lower().split())
    if "set_config('app.current_tenant'" in normalized:
        return "tenant"
    if "pg_advisory_xact_lock" in normalized:
        return "lock"
    if "inventory_live_stock_projection" in normalized:
        if normalized.startswith("update"):
            return "projection_update"
        if normalized.startswith("insert"):
            return "projection_insert"
        if normalized.startswith("delete"):
            return "projection_delete"
        return "projection_read"
    if "inventory_live_stock_warehouse_summaries" in normalized:
        return "summary"
    if "inventory_balances" in normalized:
        if normalized.startswith("update"):
            return "balance_update"
        return "facts"
    return normalized.split(" ", 1)[0] if normalized else "unknown"


def _before_cursor_execute(
    conn, cursor, statement, parameters, context, executemany
):
    bucket = SQL_BUCKET.get()
    if bucket is not None:
        context._stage821_sql_started = time.perf_counter()


def _after_cursor_execute(
    conn, cursor, statement, parameters, context, executemany
):
    bucket = SQL_BUCKET.get()
    started = getattr(context, "_stage821_sql_started", None)
    if bucket is not None and started is not None:
        bucket.append(
            (
                _sql_label(statement),
                (time.perf_counter() - started) * 1000,
            )
        )


event.listen(
    engine_app.sync_engine,
    "before_cursor_execute",
    _before_cursor_execute,
)
event.listen(
    engine_app.sync_engine,
    "after_cursor_execute",
    _after_cursor_execute,
)


@dataclass
class Metric:
    name: str
    values_ms: list[float]

    @property
    def p50(self) -> float:
        return percentile(self.values_ms, 0.50)

    @property
    def p95(self) -> float:
        return percentile(self.values_ms, 0.95)

    @property
    def p99(self) -> float:
        return percentile(self.values_ms, 0.99)

    @property
    def maximum(self) -> float:
        return max(self.values_ms) if self.values_ms else 0.0


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


async def set_tenant(session, company_id: int) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": str(company_id)},
    )


async def dataset_snapshot(
    company_id: int,
    location_id: int,
) -> dict[str, int]:
    async with SessionSU() as su:
        await su.begin()
        row = (
            await su.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM companies) AS companies,
                        (
                            SELECT count(*) FROM companies
                            WHERE company_code LIKE :noise_prefix
                        ) AS noise_companies,
                        (SELECT count(*) FROM product_variants) AS global_variants,
                        (
                            SELECT count(*)
                            FROM product_variants v
                            JOIN products p
                              ON p.company_id=v.company_id
                             AND p.id=v.product_id
                            WHERE v.company_id=:company_id
                              AND p.code=:hot_code
                        ) AS hot_variants,
                        (
                            SELECT count(*)
                            FROM inventory_balances b
                            JOIN product_variants v
                              ON v.company_id=b.company_id
                             AND v.id=b.product_variant_id
                            JOIN products p
                              ON p.company_id=v.company_id
                             AND p.id=v.product_id
                            WHERE b.company_id=:company_id
                              AND b.location_id=:location_id
                              AND p.code=:hot_code
                        ) AS hot_balances
                    """
                ),
                {
                    "company_id": company_id,
                    "location_id": location_id,
                    "hot_code": HOT_PRODUCT_CODE,
                    "noise_prefix": f"{NOISE_COMPANY_PREFIX}%",
                },
            )
        ).one()
        await su.rollback()
    return {
        "companies": int(row.companies),
        "noise_companies": int(row.noise_companies),
        "global_variants": int(row.global_variants),
        "hot_variants": int(row.hot_variants),
        "hot_balances": int(row.hot_balances),
    }


async def load_hot_rows(
    company_id: int,
    location_id: int,
    limit: int,
) -> list[tuple[int, int, int]]:
    async with SessionSU() as su:
        await su.begin()
        rows = (
            await su.execute(
                text(
                    """
                    SELECT DISTINCT ON (v.id)
                        v.id AS variant_id,
                        b.id AS balance_id,
                        b.on_hand_quantity
                    FROM product_variants v
                    JOIN products p
                      ON p.company_id=v.company_id
                     AND p.id=v.product_id
                    JOIN inventory_balances b
                      ON b.company_id=v.company_id
                     AND b.product_variant_id=v.id
                     AND b.location_id=:location_id
                     AND b.stock_status='AVAILABLE'
                    WHERE v.company_id=:company_id
                      AND p.code=:hot_code
                    ORDER BY v.id, b.id
                    LIMIT :limit
                    """
                ),
                {
                    "company_id": company_id,
                    "location_id": location_id,
                    "hot_code": HOT_PRODUCT_CODE,
                    "limit": limit,
                },
            )
        ).all()
        await su.rollback()
    return [
        (
            int(row.variant_id),
            int(row.balance_id),
            int(row.on_hand_quantity),
        )
        for row in rows
    ]


async def load_balance_impact_metadata(
    company_id: int,
    balance_ids: list[int],
) -> dict[int, dict[str, object]]:
    async with SessionSU() as su:
        await su.begin()
        rows = (
            await su.execute(
                text(
                    """
                    SELECT
                        b.id AS balance_id,
                        b.location_id,
                        l.location_type,
                        l.vehicle_id,
                        b.product_variant_id,
                        b.batch_id,
                        b.stock_status,
                        b.reserved_quantity,
                        v.name AS variant_name,
                        v.lifecycle_status,
                        v.operational_hold,
                        v.expiry_control_mode,
                        pb.is_active AS batch_is_active,
                        pb.disposition AS batch_disposition,
                        pb.production_date,
                        pb.expiry_date
                    FROM inventory_balances b
                    JOIN inventory_locations l
                      ON l.company_id=b.company_id
                     AND l.id=b.location_id
                    JOIN product_variants v
                      ON v.company_id=b.company_id
                     AND v.id=b.product_variant_id
                    JOIN product_batches pb
                      ON pb.company_id=b.company_id
                     AND pb.product_variant_id=b.product_variant_id
                     AND pb.id=b.batch_id
                    WHERE b.company_id=:company_id
                      AND b.id = ANY(CAST(:balance_ids AS integer[]))
                    """
                ),
                {
                    "company_id": company_id,
                    "balance_ids": balance_ids,
                },
            )
        ).mappings().all()
        await su.rollback()
    return {
        int(row["balance_id"]): dict(row)
        for row in rows
    }


async def _acquire_profiled_connection(session) -> None:
    started = time.perf_counter()
    await session.connection()
    bucket = SQL_BUCKET.get()
    if bucket is not None:
        bucket.append(
            ("pool_wait", (time.perf_counter() - started) * 1000)
        )


async def refresh_once(
    company_id: int,
    location_id: int,
    variant_ids: list[int],
) -> float:
    started = time.perf_counter()
    async with SessionApp() as app:
        await app.begin()
        await _acquire_profiled_connection(app)
        await set_tenant(app, company_id)
        await refresh_live_stock_keys(
            app,
            company_id=company_id,
            keys=[(location_id, variant_id) for variant_id in variant_ids],
        )
        await app.commit()
    return (time.perf_counter() - started) * 1000


async def profile_refresh_once(
    company_id: int,
    location_id: int,
    variant_ids: list[int],
) -> tuple[float, int, float, dict[str, int]]:
    bucket: list[tuple[str, float]] = []
    token = SQL_BUCKET.set(bucket)
    try:
        elapsed = await refresh_once(
            company_id,
            location_id,
            variant_ids,
        )
    finally:
        SQL_BUCKET.reset(token)

    labels: dict[str, int] = {}
    for label, _ms in bucket:
        labels[label] = labels.get(label, 0) + 1
    return (
        elapsed,
        len(bucket),
        sum(ms for _label, ms in bucket),
        labels,
    )


def _profile_operation(
    elapsed_ms: float,
    bucket: list[tuple[str, float]],
) -> tuple[dict[str, float], float]:
    per_label: dict[str, float] = {}
    for label, ms in bucket:
        per_label[label] = per_label.get(label, 0.0) + ms
    sql_ms = sum(per_label.values())
    return per_label, max(0.0, elapsed_ms - sql_ms)


def _print_concurrent_profile(
    name: str,
    profiles: list[tuple[dict[str, float], float]],
) -> None:
    labels = sorted(
        {
            label
            for per_label, _outside in profiles
            for label in per_label
        }
    )
    parts = []
    for label in labels:
        values = [
            per_label.get(label, 0.0)
            for per_label, _outside in profiles
        ]
        parts.append(
            f"{label}_p95={percentile(values, 0.95):.1f}ms"
        )
    outside = [outside for _per_label, outside in profiles]
    parts.append(
        f"outside_sql_p95={percentile(outside, 0.95):.1f}ms"
    )
    print(f"{name} " + " ".join(parts))


async def bulk_refresh_with_lock_count(
    company_id: int,
    location_id: int,
    variant_ids: list[int],
) -> tuple[float, int]:
    started = time.perf_counter()
    async with SessionApp() as app:
        await app.begin()
        await set_tenant(app, company_id)
        await refresh_live_stock_keys(
            app,
            company_id=company_id,
            keys=[(location_id, variant_id) for variant_id in variant_ids],
        )
        advisory_locks = int(
            (
                await app.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_locks
                        WHERE pid = pg_backend_pid()
                          AND locktype = 'advisory'
                        """
                    )
                )
            ).scalar_one()
        )
        await app.commit()
    return (time.perf_counter() - started) * 1000, advisory_locks


async def load_noise_mutation_samples(
    limit: int,
) -> list[dict[str, object]]:
    async with SessionSU() as su:
        await su.begin()
        rows = (
            await su.execute(
                text(
                    """
                    SELECT DISTINCT ON (c.id)
                        c.id AS company_id,
                        l.id AS location_id,
                        l.location_type,
                        l.vehicle_id,
                        v.id AS product_variant_id,
                        v.name AS variant_name,
                        v.lifecycle_status,
                        v.operational_hold,
                        v.expiry_control_mode,
                        b.id AS balance_id,
                        b.batch_id,
                        b.stock_status,
                        b.on_hand_quantity,
                        b.reserved_quantity,
                        pb.is_active AS batch_is_active,
                        pb.disposition AS batch_disposition,
                        pb.production_date,
                        pb.expiry_date
                    FROM companies c
                    JOIN inventory_locations l
                      ON l.company_id=c.id
                     AND l.code='PERF-WH'
                     AND l.location_type='WAREHOUSE'
                     AND l.is_active IS TRUE
                    JOIN product_variants v
                      ON v.company_id=c.id
                    JOIN inventory_balances b
                      ON b.company_id=c.id
                     AND b.location_id=l.id
                     AND b.product_variant_id=v.id
                     AND b.stock_status='AVAILABLE'
                    JOIN product_batches pb
                      ON pb.company_id=b.company_id
                     AND pb.product_variant_id=b.product_variant_id
                     AND pb.id=b.batch_id
                    WHERE c.company_code LIKE :prefix
                    ORDER BY c.id, v.id, b.id
                    LIMIT :limit
                    """
                ),
                {
                    "prefix": f"{NOISE_COMPANY_PREFIX}%",
                    "limit": limit,
                },
            )
        ).mappings().all()
        await su.rollback()
    return [dict(row) for row in rows]


def _impact_from_noise_sample(
    sample: dict[str, object],
    *,
    on_hand_before: int,
    on_hand_after: int,
) -> dict[str, object]:
    return {
        "inventory_balance_id": int(sample["balance_id"]),
        "location_id": int(sample["location_id"]),
        "location_type": str(sample["location_type"]),
        "vehicle_id": sample["vehicle_id"],
        "product_variant_id": int(sample["product_variant_id"]),
        "batch_id": int(sample["batch_id"]),
        "stock_status": str(sample["stock_status"]),
        "on_hand_before": on_hand_before,
        "on_hand_after": on_hand_after,
        "reserved_before": sample["reserved_quantity"],
        "reserved_after": sample["reserved_quantity"],
        "variant_name": str(sample["variant_name"]),
        "lifecycle_status": str(sample["lifecycle_status"]),
        "operational_hold": str(sample["operational_hold"]),
        "expiry_control_mode": str(sample["expiry_control_mode"]),
        "batch_is_active": bool(sample["batch_is_active"]),
        "batch_disposition": str(sample["batch_disposition"]),
        "production_date": sample["production_date"],
        "expiry_date": sample["expiry_date"],
    }


async def _cross_tenant_projection_mismatches(
    samples: list[dict[str, object]],
) -> int:
    if not samples:
        return 0
    company_ids = [int(sample["company_id"]) for sample in samples]
    location_ids = [int(sample["location_id"]) for sample in samples]
    variant_ids = [
        int(sample["product_variant_id"]) for sample in samples
    ]
    async with SessionSU() as su:
        await su.begin()
        mismatches = int(
            (
                await su.execute(
                    text(
                        """
                        WITH sample AS (
                            SELECT *
                            FROM unnest(
                                CAST(:company_ids AS integer[]),
                                CAST(:location_ids AS integer[]),
                                CAST(:variant_ids AS integer[])
                            ) AS s(
                                company_id,
                                location_id,
                                product_variant_id
                            )
                        ),
                        truth AS (
                            SELECT
                                s.company_id,
                                s.location_id,
                                s.product_variant_id,
                                COALESCE(
                                    SUM(b.on_hand_quantity)
                                        FILTER (
                                            WHERE b.stock_status='AVAILABLE'
                                        ),
                                    0
                                ) AS on_hand,
                                COALESCE(
                                    SUM(b.reserved_quantity)
                                        FILTER (
                                            WHERE b.stock_status='AVAILABLE'
                                        ),
                                    0
                                ) AS reserved
                            FROM sample s
                            LEFT JOIN inventory_balances b
                              ON b.company_id=s.company_id
                             AND b.location_id=s.location_id
                             AND b.product_variant_id=s.product_variant_id
                            GROUP BY
                                s.company_id,
                                s.location_id,
                                s.product_variant_id
                        )
                        SELECT count(*)
                        FROM truth t
                        LEFT JOIN inventory_live_stock_projection p
                          ON p.company_id=t.company_id
                         AND p.warehouse_location_id=t.location_id
                         AND p.product_variant_id=t.product_variant_id
                        WHERE p.product_variant_id IS NULL
                           OR p.warehouse_on_hand <> t.on_hand
                           OR p.warehouse_reserved <> t.reserved
                           OR p.warehouse_sellable_on_hand <> t.on_hand
                           OR p.warehouse_sellable_reserved <> t.reserved
                        """
                    ),
                    {
                        "company_ids": company_ids,
                        "location_ids": location_ids,
                        "variant_ids": variant_ids,
                    },
                )
            ).scalar_one()
        )
        await su.rollback()
    return mismatches


async def timed_cross_tenant_mutations(
    *,
    samples: list[dict[str, object]],
    concurrency: int,
    operations: int,
) -> tuple[Metric, float, list[str]]:
    if len(samples) < operations:
        raise RuntimeError(
            "Cross-tenant mutation samples must be unique per operation."
        )

    work = samples[:operations]
    warm_sem = asyncio.Semaphore(min(20, concurrency))

    async def warm(sample: dict[str, object]) -> None:
        async with warm_sem:
            await refresh_once(
                int(sample["company_id"]),
                int(sample["location_id"]),
                [int(sample["product_variant_id"])],
            )

    await asyncio.gather(*(warm(sample) for sample in work))

    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors: list[str] = []
    profiles: list[tuple[dict[str, float], float]] = []
    committed: list[dict[str, object]] = []

    async def mutate(sample: dict[str, object]) -> None:
        async with sem:
            bucket: list[tuple[str, float]] = []
            token = SQL_BUCKET.set(bucket)
            started = time.perf_counter()
            try:
                async with SessionApp() as app:
                    await app.begin()
                    await _acquire_profiled_connection(app)
                    company_id = int(sample["company_id"])
                    await set_tenant(app, company_id)
                    after = (
                        await app.execute(
                            text(
                                """
                                UPDATE inventory_balances
                                SET on_hand_quantity=on_hand_quantity + 1,
                                    last_updated=NOW()
                                WHERE company_id=:company_id
                                  AND id=:balance_id
                                RETURNING on_hand_quantity,
                                          reserved_quantity
                                """
                            ),
                            {
                                "company_id": company_id,
                                "balance_id": int(sample["balance_id"]),
                            },
                        )
                    ).one()
                    await apply_live_stock_balance_impacts(
                        app,
                        company_id=company_id,
                        impacts=[
                            _impact_from_noise_sample(
                                sample,
                                on_hand_before=(
                                    int(after.on_hand_quantity) - 1
                                ),
                                on_hand_after=int(after.on_hand_quantity),
                            )
                        ],
                    )
                    await app.commit()
                elapsed = (time.perf_counter() - started) * 1000
                latencies.append(elapsed)
                profiles.append(_profile_operation(elapsed, bucket))
                committed.append(sample)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}:{exc}")
            finally:
                SQL_BUCKET.reset(token)

    started = time.perf_counter()
    await asyncio.gather(*(mutate(sample) for sample in work))
    total_s = time.perf_counter() - started
    throughput = operations / total_s if total_s > 0 else 0.0
    _print_concurrent_profile(
        "CROSS_TENANT_MUTATION_SQL_PROFILE",
        profiles,
    )

    reaggregation_ops = sum(
        1 for per_label, _outside in profiles if "facts" in per_label
    )
    if reaggregation_ops:
        errors.append(
            f"CROSS_TENANT_HOT_PATH_REAGGREGATION:{reaggregation_ops}"
        )

    mismatch = await _cross_tenant_projection_mismatches(committed)
    if mismatch:
        errors.append(
            f"CROSS_TENANT_PROJECTION_MISMATCHES:{mismatch}"
        )

    restore_sem = asyncio.Semaphore(min(20, concurrency))

    async def restore(sample: dict[str, object]) -> None:
        async with restore_sem:
            async with SessionApp() as app:
                await app.begin()
                company_id = int(sample["company_id"])
                await set_tenant(app, company_id)
                original = int(sample["on_hand_quantity"])
                await app.execute(
                    text(
                        """
                        UPDATE inventory_balances
                        SET on_hand_quantity=:original,
                            last_updated=NOW()
                        WHERE company_id=:company_id
                          AND id=:balance_id
                        """
                    ),
                    {
                        "original": original,
                        "company_id": company_id,
                        "balance_id": int(sample["balance_id"]),
                    },
                )
                await apply_live_stock_balance_impacts(
                    app,
                    company_id=company_id,
                    impacts=[
                        _impact_from_noise_sample(
                            sample,
                            on_hand_before=original + 1,
                            on_hand_after=original,
                        )
                    ],
                )
                await app.commit()

    restore_results = await asyncio.gather(
        *(restore(sample) for sample in committed),
        return_exceptions=True,
    )
    restore_errors = [
        result
        for result in restore_results
        if isinstance(result, Exception)
    ]
    if restore_errors:
        errors.append(
            f"CROSS_TENANT_RESTORE_ERRORS:{len(restore_errors)}:"
            f"{restore_errors[0]}"
        )

    post_restore_mismatch = await _cross_tenant_projection_mismatches(
        committed
    )
    if post_restore_mismatch:
        errors.append(
            "CROSS_TENANT_POST_RESTORE_MISMATCHES:"
            f"{post_restore_mismatch}"
        )

    return (
        Metric("cross_tenant_mutation", latencies),
        throughput,
        errors,
    )


async def timed_parallel_refreshes(
    *,
    company_id: int,
    location_id: int,
    variant_ids: list[int],
    concurrency: int,
    operations: int,
) -> tuple[Metric, float, list[str]]:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors: list[str] = []
    profiles: list[tuple[dict[str, float], float]] = []

    async def one(index: int) -> None:
        async with sem:
            variant_id = variant_ids[index % len(variant_ids)]
            bucket: list[tuple[str, float]] = []
            token = SQL_BUCKET.set(bucket)
            try:
                elapsed = await refresh_once(
                    company_id,
                    location_id,
                    [variant_id],
                )
                latencies.append(elapsed)
                profiles.append(_profile_operation(elapsed, bucket))
            except Exception as exc:
                errors.append(f"{type(exc).__name__}:{exc}")
            finally:
                SQL_BUCKET.reset(token)

    started = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(operations)))
    total_s = time.perf_counter() - started
    throughput = operations / total_s if total_s > 0 else 0.0
    _print_concurrent_profile("PARALLEL_SQL_PROFILE", profiles)
    return Metric("parallel_refresh", latencies), throughput, errors


async def timed_mutation_pressure(
    *,
    company_id: int,
    location_id: int,
    rows: list[tuple[int, int, int]],
    impact_metadata: dict[int, dict[str, object]],
    concurrency: int,
    operations: int,
) -> tuple[Metric, float, list[str], dict[int, int]]:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors: list[str] = []
    profiles: list[tuple[dict[str, float], float]] = []
    touched_originals = {
        balance_id: original
        for _variant_id, balance_id, original in rows[:operations]
    }
    work = rows[:operations]

    async def one(item: tuple[int, int, int]) -> None:
        variant_id, balance_id, _original = item
        async with sem:
            started = time.perf_counter()
            bucket: list[tuple[str, float]] = []
            token = SQL_BUCKET.set(bucket)
            try:
                async with SessionApp() as app:
                    await app.begin()
                    await _acquire_profiled_connection(app)
                    await set_tenant(app, company_id)
                    after = (
                        await app.execute(
                            text(
                                """
                                UPDATE inventory_balances
                                SET on_hand_quantity=on_hand_quantity + 1,
                                    last_updated=NOW()
                                WHERE company_id=:company_id
                                  AND id=:balance_id
                                RETURNING on_hand_quantity,
                                          reserved_quantity
                                """
                            ),
                            {
                                "company_id": company_id,
                                "balance_id": balance_id,
                            },
                        )
                    ).one()
                    metadata = dict(impact_metadata[balance_id])
                    metadata.update(
                        {
                            "on_hand_before": int(after.on_hand_quantity) - 1,
                            "on_hand_after": after.on_hand_quantity,
                            "reserved_before": after.reserved_quantity,
                            "reserved_after": after.reserved_quantity,
                        }
                    )
                    await apply_live_stock_balance_impacts(
                        app,
                        company_id=company_id,
                        impacts=[metadata],
                    )
                    await app.commit()
                elapsed = (time.perf_counter() - started) * 1000
                latencies.append(elapsed)
                profiles.append(_profile_operation(elapsed, bucket))
            except Exception as exc:
                errors.append(f"{type(exc).__name__}:{exc}")
            finally:
                SQL_BUCKET.reset(token)

    started = time.perf_counter()
    await asyncio.gather(*(one(item) for item in work))
    total_s = time.perf_counter() - started
    throughput = len(work) / total_s if total_s > 0 else 0.0
    _print_concurrent_profile("MUTATION_SQL_PROFILE", profiles)
    reaggregation_ops = sum(
        1 for per_label, _outside in profiles if "facts" in per_label
    )
    if reaggregation_ops:
        errors.append(
            f"HOT_PATH_REAGGREGATION:{reaggregation_ops}"
        )
    return (
        Metric("mutation_pressure", latencies),
        throughput,
        errors,
        touched_originals,
    )


async def hot_key_contention(
    *,
    company_id: int,
    location_id: int,
    row: tuple[int, int, int],
    impact_metadata: dict[int, dict[str, object]],
    workers: int,
) -> tuple[Metric, list[str]]:
    variant_id, balance_id, original = row
    latencies: list[float] = []
    errors: list[str] = []

    async def one() -> None:
        started = time.perf_counter()
        try:
            async with SessionApp() as app:
                await app.begin()
                await _acquire_profiled_connection(app)
                await set_tenant(app, company_id)
                after = (
                    await app.execute(
                        text(
                            """
                            UPDATE inventory_balances
                            SET on_hand_quantity=on_hand_quantity + 1,
                                last_updated=NOW()
                            WHERE company_id=:company_id
                              AND id=:balance_id
                            RETURNING on_hand_quantity,
                                      reserved_quantity
                            """
                        ),
                        {
                            "company_id": company_id,
                            "balance_id": balance_id,
                        },
                    )
                ).one()
                metadata = dict(impact_metadata[balance_id])
                metadata.update(
                    {
                        "on_hand_before": int(after.on_hand_quantity) - 1,
                        "on_hand_after": after.on_hand_quantity,
                        "reserved_before": after.reserved_quantity,
                        "reserved_after": after.reserved_quantity,
                    }
                )
                await apply_live_stock_balance_impacts(
                    app,
                    company_id=company_id,
                    impacts=[metadata],
                )
                await app.commit()
            latencies.append((time.perf_counter() - started) * 1000)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}:{exc}")

    await asyncio.wait_for(
        asyncio.gather(*(one() for _ in range(workers))),
        timeout=30,
    )

    async with SessionApp() as app:
        await app.begin()
        await set_tenant(app, company_id)
        balance_truth = int(
            (
                await app.execute(
                    text(
                        """
                        SELECT on_hand_quantity
                        FROM inventory_balances
                        WHERE company_id=:company_id
                          AND id=:balance_id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "balance_id": balance_id,
                    },
                )
            ).scalar_one()
        )
        aggregate_truth = int(
            (
                await app.execute(
                    text(
                        """
                        SELECT COALESCE(SUM(on_hand_quantity), 0)
                        FROM inventory_balances
                        WHERE company_id=:company_id
                          AND location_id=:location_id
                          AND product_variant_id=:variant_id
                          AND stock_status='AVAILABLE'
                        """
                    ),
                    {
                        "company_id": company_id,
                        "location_id": location_id,
                        "variant_id": variant_id,
                    },
                )
            ).scalar_one()
        )
        projected = int(
            (
                await app.execute(
                    text(
                        """
                        SELECT warehouse_on_hand
                        FROM inventory_live_stock_projection
                        WHERE company_id=:company_id
                          AND warehouse_location_id=:location_id
                          AND product_variant_id=:variant_id
                        """
                    ),
                    {
                        "company_id": company_id,
                        "location_id": location_id,
                        "variant_id": variant_id,
                    },
                )
            ).scalar_one()
        )
        await app.rollback()
    if balance_truth != original + workers:
        errors.append(
            f"HOT_KEY_TRUTH_MISMATCH:{balance_truth}!={original + workers}"
        )
    if projected != aggregate_truth:
        errors.append(
            f"HOT_KEY_PROJECTION_MISMATCH:{projected}!={aggregate_truth}"
        )
    return Metric("hot_key_contention", latencies), errors


async def overlap_deadlock_pressure(
    *,
    company_id: int,
    location_id: int,
    first: int,
    second: int,
    workers: int,
) -> list[str]:
    errors: list[str] = []

    async def one(reverse: bool) -> None:
        ids = [second, first] if reverse else [first, second]
        try:
            async with SessionApp() as app:
                await app.begin()
                await set_tenant(app, company_id)
                await refresh_live_stock_keys(
                    app,
                    company_id=company_id,
                    keys=[(location_id, variant_id) for variant_id in ids],
                )
                await app.commit()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}:{exc}")

    await asyncio.wait_for(
        asyncio.gather(
            *(one(index % 2 == 1) for index in range(workers))
        ),
        timeout=30,
    )
    return errors


async def projection_truth_mismatches(
    *,
    company_id: int,
    location_id: int,
    variant_ids: list[int],
) -> int:
    async with SessionApp() as app:
        await app.begin()
        await set_tenant(app, company_id)
        mismatch = int(
            (
                await app.execute(
                    text(
                        """
                        WITH truth AS (
                            SELECT
                                product_variant_id,
                                COALESCE(
                                    SUM(on_hand_quantity)
                                        FILTER (
                                            WHERE stock_status='AVAILABLE'
                                        ),
                                    0
                                ) AS on_hand,
                                COALESCE(
                                    SUM(reserved_quantity)
                                        FILTER (
                                            WHERE stock_status='AVAILABLE'
                                        ),
                                    0
                                ) AS reserved
                            FROM inventory_balances
                            WHERE company_id=:company_id
                              AND location_id=:location_id
                              AND product_variant_id = ANY(:variant_ids)
                            GROUP BY product_variant_id
                        )
                        SELECT count(*)
                        FROM truth t
                        JOIN inventory_live_stock_projection p
                          ON p.company_id=:company_id
                         AND p.warehouse_location_id=:location_id
                         AND p.product_variant_id=t.product_variant_id
                        WHERE p.warehouse_on_hand <> t.on_hand
                           OR p.warehouse_reserved <> t.reserved
                        """
                    ),
                    {
                        "company_id": company_id,
                        "location_id": location_id,
                        "variant_ids": variant_ids,
                    },
                )
            ).scalar_one()
        )
        await app.rollback()
    return mismatch


async def summary_mismatch(
    *,
    company_id: int,
    location_id: int,
) -> bool:
    async with SessionApp() as app:
        await app.begin()
        await set_tenant(app, company_id)
        row = (
            await app.execute(
                text(
                    """
                    WITH actual AS (
                        SELECT
                            count(*) AS rows,
                            count(*) FILTER (WHERE is_low_stock) AS alerts,
                            count(*) FILTER (
                                WHERE lifecycle_status <> 'ACTIVE'
                                  AND (
                                      has_warehouse_presence
                                      OR has_vehicle_presence
                                  )
                            ) AS nonactive
                        FROM inventory_live_stock_projection
                        WHERE company_id=:company_id
                          AND warehouse_location_id=:location_id
                    )
                    SELECT
                        s.projected_row_count = a.rows
                        AND s.alert_count = a.alerts
                        AND s.nonactive_visible_count = a.nonactive AS ok
                    FROM inventory_live_stock_warehouse_summaries s
                    CROSS JOIN actual a
                    WHERE s.company_id=:company_id
                      AND s.warehouse_location_id=:location_id
                    """
                ),
                {
                    "company_id": company_id,
                    "location_id": location_id,
                },
            )
        ).scalar_one_or_none()
        await app.rollback()
    return bool(row)


async def restore_balances(
    *,
    company_id: int,
    location_id: int,
    originals: dict[int, tuple[int, int]],
) -> None:
    if not originals:
        return
    async with SessionSU() as su:
        await su.begin()
        await su.execute(
            text(
                """
                UPDATE inventory_balances
                SET on_hand_quantity=:quantity,
                    last_updated=NOW()
                WHERE company_id=:company_id
                  AND id=:balance_id
                """
            ),
            [
                {
                    "company_id": company_id,
                    "balance_id": balance_id,
                    "quantity": quantity,
                }
                for balance_id, (_variant_id, quantity) in originals.items()
            ],
        )
        await su.commit()

    variant_ids = sorted(
        {variant_id for variant_id, _quantity in originals.values()}
    )
    for offset in range(0, len(variant_ids), 1000):
        await refresh_once(
            company_id,
            location_id,
            variant_ids[offset:offset + 1000],
        )


def print_metric(metric: Metric) -> None:
    print(
        f"{metric.name}: samples={len(metric.values_ms)} "
        f"p50={metric.p50:.1f}ms p95={metric.p95:.1f}ms "
        f"p99={metric.p99:.1f}ms max={metric.maximum:.1f}ms"
    )


async def run(args: argparse.Namespace) -> None:
    failures: list[str] = []
    originals: dict[int, tuple[int, int]] = {}
    snapshot = await dataset_snapshot(args.company_id, args.location_id)
    print("DATASET=" + repr(snapshot))

    if snapshot["noise_companies"] < args.min_noise_companies:
        failures.append(
            f"NOISE_COMPANIES:{snapshot['noise_companies']}"
            f"<{args.min_noise_companies}"
        )
    if snapshot["hot_variants"] < args.min_hot_variants:
        failures.append(
            f"HOT_VARIANTS:{snapshot['hot_variants']}"
            f"<{args.min_hot_variants}"
        )
    if snapshot["global_variants"] < args.min_global_variants:
        failures.append(
            f"GLOBAL_VARIANTS:{snapshot['global_variants']}"
            f"<{args.min_global_variants}"
        )

    rows = await load_hot_rows(
        args.company_id,
        args.location_id,
        args.bulk_keys,
    )
    if len(rows) < args.bulk_keys:
        failures.append(
            f"HOT_ROWS:{len(rows)}<{args.bulk_keys}"
        )

    impact_metadata = await load_balance_impact_metadata(
        args.company_id,
        [balance_id for _variant_id, balance_id, _qty in rows],
    )
    if len(impact_metadata) != len(rows):
        failures.append(
            f"IMPACT_METADATA:{len(impact_metadata)}<{len(rows)}"
        )

    noise_samples = await load_noise_mutation_samples(
        args.parallel_ops
    )
    if len(noise_samples) < args.parallel_ops:
        failures.append(
            f"NOISE_MUTATION_SAMPLES:{len(noise_samples)}"
            f"<{args.parallel_ops}"
        )

    if failures:
        for failure in failures:
            print("FAIL: " + failure)
        print("STAGE821_PROJECTOR_STRESS_GATE=FAIL")
        raise SystemExit(1)

    variants = [variant_id for variant_id, _balance_id, _qty in rows]
    print(
        f"STRESS_CONFIG bulk_keys={args.bulk_keys} "
        f"concurrency={args.concurrency} "
        f"parallel_ops={args.parallel_ops} "
        f"mutation_ops={args.mutation_ops} "
        f"hot_key_workers={args.hot_key_workers} "
        f"db_connection_cap={STRESS_DB_CONNECTION_CAP}"
    )

    try:
        # Cold-ish 10k-key materialization / refresh.
        bulk_ms, bulk_advisory_locks = await bulk_refresh_with_lock_count(
            args.company_id,
            args.location_id,
            variants,
        )
        print(
            f"bulk_{len(variants)}={bulk_ms:.1f}ms "
            f"advisory_locks={bulk_advisory_locks}"
        )
        if bulk_ms > args.max_bulk_ms:
            failures.append(
                f"BULK_REFRESH:{bulk_ms:.1f}>{args.max_bulk_ms:.1f}"
            )
        if bulk_advisory_locks > args.max_bulk_advisory_locks:
            failures.append(
                f"BULK_ADVISORY_LOCKS:{bulk_advisory_locks}"
                f">{args.max_bulk_advisory_locks}"
            )

        # Warm the exact paths before collecting percentiles.
        for variant_id in variants[:10]:
            await refresh_once(
                args.company_id,
                args.location_id,
                [variant_id],
            )
        for offset in range(0, 300, 100):
            await refresh_once(
                args.company_id,
                args.location_id,
                variants[offset:offset + 100],
            )

        (
            single_profile_ms,
            single_sql_count,
            single_sql_ms,
            single_sql_labels,
        ) = await profile_refresh_once(
            args.company_id,
            args.location_id,
            [variants[0]],
        )
        (
            batch_profile_ms,
            batch_sql_count,
            batch_sql_ms,
            batch_sql_labels,
        ) = await profile_refresh_once(
            args.company_id,
            args.location_id,
            variants[:100],
        )
        print(
            "SQL_PROFILE_SINGLE "
            f"elapsed={single_profile_ms:.1f}ms "
            f"statements={single_sql_count} "
            f"sql_ms={single_sql_ms:.1f} "
            f"labels={single_sql_labels}"
        )
        print(
            "SQL_PROFILE_BATCH100 "
            f"elapsed={batch_profile_ms:.1f}ms "
            f"statements={batch_sql_count} "
            f"sql_ms={batch_sql_ms:.1f} "
            f"labels={batch_sql_labels}"
        )
        if single_sql_count > args.max_single_sql_statements:
            failures.append(
                f"SINGLE_SQL_STATEMENTS:{single_sql_count}"
                f">{args.max_single_sql_statements}"
            )
        if batch_sql_count > args.max_batch100_sql_statements:
            failures.append(
                f"BATCH100_SQL_STATEMENTS:{batch_sql_count}"
                f">{args.max_batch100_sql_statements}"
            )
        if batch_sql_count > single_sql_count + 1:
            failures.append(
                f"SQL_AMPLIFICATION:{single_sql_count}->{batch_sql_count}"
            )

        single = Metric(
            "single_key_refresh",
            [
                await refresh_once(
                    args.company_id,
                    args.location_id,
                    [variants[index % len(variants)]],
                )
                for index in range(args.single_runs)
            ],
        )
        print_metric(single)
        if single.p95 > args.max_single_p95:
            failures.append(
                f"SINGLE_P95:{single.p95:.1f}>{args.max_single_p95:.1f}"
            )

        batch100_values = []
        for index in range(args.batch_runs):
            start = (index * 100) % (len(variants) - 100)
            batch100_values.append(
                await refresh_once(
                    args.company_id,
                    args.location_id,
                    variants[start:start + 100],
                )
            )
        batch100 = Metric("batch_100_refresh", batch100_values)
        print_metric(batch100)
        if batch100.p95 > args.max_batch100_p95:
            failures.append(
                f"BATCH100_P95:{batch100.p95:.1f}"
                f">{args.max_batch100_p95:.1f}"
            )

        parallel, parallel_tps, parallel_errors = (
            await timed_cross_tenant_mutations(
                samples=noise_samples,
                concurrency=args.concurrency,
                operations=args.parallel_ops,
            )
        )
        print_metric(parallel)
        print(f"cross_tenant_mutation_throughput={parallel_tps:.1f}/s")
        if parallel_errors:
            failures.append(
                f"CROSS_TENANT_MUTATION_ERRORS:{len(parallel_errors)}:"
                + parallel_errors[0]
            )
        if parallel.p95 > args.max_parallel_p95:
            failures.append(
                f"CROSS_TENANT_P95:{parallel.p95:.1f}"
                f">{args.max_parallel_p95:.1f}"
            )
        if parallel_tps < args.min_parallel_tps:
            failures.append(
                f"CROSS_TENANT_TPS:{parallel_tps:.1f}"
                f"<{args.min_parallel_tps:.1f}"
            )

        mutation_rows = rows[:args.mutation_ops]
        for variant_id, balance_id, original in mutation_rows:
            originals[balance_id] = (variant_id, original)

        mutation, mutation_tps, mutation_errors, _ = (
            await timed_mutation_pressure(
                company_id=args.company_id,
                location_id=args.location_id,
                rows=mutation_rows,
                impact_metadata=impact_metadata,
                concurrency=args.concurrency,
                operations=args.mutation_ops,
            )
        )
        print_metric(mutation)
        print(f"mutation_throughput={mutation_tps:.1f}/s")
        if mutation_errors:
            failures.append(
                f"MUTATION_ERRORS:{len(mutation_errors)}:"
                + mutation_errors[0]
            )
        if mutation.p95 > args.max_mutation_p95:
            failures.append(
                f"MUTATION_P95:{mutation.p95:.1f}"
                f">{args.max_mutation_p95:.1f}"
            )
        if mutation_tps < args.min_mutation_tps:
            failures.append(
                f"MUTATION_TPS:{mutation_tps:.1f}"
                f"<{args.min_mutation_tps:.1f}"
            )

        hot_variant, hot_balance, hot_original = rows[-1]
        originals[hot_balance] = (hot_variant, hot_original)
        hot_metric, hot_errors = await hot_key_contention(
            company_id=args.company_id,
            location_id=args.location_id,
            row=(hot_variant, hot_balance, hot_original),
            impact_metadata=impact_metadata,
            workers=args.hot_key_workers,
        )
        print_metric(hot_metric)
        if hot_errors:
            failures.append(
                f"HOT_KEY_ERRORS:{len(hot_errors)}:{hot_errors[0]}"
            )
        if hot_metric.maximum > args.max_hot_key_max:
            failures.append(
                f"HOT_KEY_MAX:{hot_metric.maximum:.1f}"
                f">{args.max_hot_key_max:.1f}"
            )

        deadlock_errors = await overlap_deadlock_pressure(
            company_id=args.company_id,
            location_id=args.location_id,
            first=variants[0],
            second=variants[1],
            workers=args.deadlock_workers,
        )
        print(
            f"overlap_deadlock_workers={args.deadlock_workers} "
            f"errors={len(deadlock_errors)}"
        )
        if deadlock_errors:
            failures.append(
                f"DEADLOCK_PRESSURE_ERRORS:{len(deadlock_errors)}:"
                + deadlock_errors[0]
            )

        mismatch = await projection_truth_mismatches(
            company_id=args.company_id,
            location_id=args.location_id,
            variant_ids=variants[:args.correctness_samples],
        )
        print(f"projection_truth_mismatches={mismatch}")
        if mismatch:
            failures.append(f"PROJECTION_TRUTH_MISMATCHES:{mismatch}")

        summary_ok = await summary_mismatch(
            company_id=args.company_id,
            location_id=args.location_id,
        )
        print(f"summary_exact={summary_ok}")
        if not summary_ok:
            failures.append("SUMMARY_DRIFT")

    finally:
        try:
            await restore_balances(
                company_id=args.company_id,
                location_id=args.location_id,
                originals=originals,
            )
            post_restore_mismatch = await projection_truth_mismatches(
                company_id=args.company_id,
                location_id=args.location_id,
                variant_ids=[
                    variant_id
                    for variant_id, _quantity in originals.values()
                ],
            ) if originals else 0
            print(
                f"RESTORE_OK balances={len(originals)} "
                f"mismatches={post_restore_mismatch}"
            )
            if post_restore_mismatch:
                failures.append(
                    f"POST_RESTORE_PROJECTION_MISMATCHES:{post_restore_mismatch}"
                )
        finally:
            await engine_app.dispose()
            await engine_su.dispose()

    print("CHECKS=16")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print("FAIL: " + failure)
    if failures:
        print("STAGE821_PROJECTOR_STRESS_GATE=FAIL")
        raise SystemExit(1)
    print("STAGE821_PROJECTOR_STRESS_GATE=PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Hard Stage 8.2.1 projector stress gate. "
            "Requires the dedicated scale dataset; never benchmarks tiny data."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--location-id", type=int, required=True)

    parser.add_argument("--min-noise-companies", type=int, default=1000)
    parser.add_argument("--min-hot-variants", type=int, default=10000)
    parser.add_argument("--min-global-variants", type=int, default=100000)
    parser.add_argument("--bulk-keys", type=int, default=10000)

    parser.add_argument("--single-runs", type=int, default=100)
    parser.add_argument("--batch-runs", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--parallel-ops", type=int, default=512)
    parser.add_argument("--mutation-ops", type=int, default=256)
    parser.add_argument("--hot-key-workers", type=int, default=32)
    parser.add_argument("--deadlock-workers", type=int, default=64)
    parser.add_argument("--correctness-samples", type=int, default=500)

    parser.add_argument("--max-bulk-ms", type=float, default=8000.0)
    parser.add_argument("--max-bulk-advisory-locks", type=int, default=4)
    parser.add_argument("--max-single-sql-statements", type=int, default=6)
    parser.add_argument("--max-batch100-sql-statements", type=int, default=6)
    parser.add_argument("--max-single-p95", type=float, default=75.0)
    parser.add_argument("--max-batch100-p95", type=float, default=350.0)
    parser.add_argument("--max-parallel-p95", type=float, default=900.0)
    parser.add_argument("--min-parallel-tps", type=float, default=60.0)
    parser.add_argument("--max-mutation-p95", type=float, default=1200.0)
    parser.add_argument("--min-mutation-tps", type=float, default=35.0)
    parser.add_argument("--max-hot-key-max", type=float, default=6000.0)

    args = parser.parse_args()
    if not 1 <= args.concurrency <= 80:
        parser.error("--concurrency must be between 1 and 80")
    if args.bulk_keys != 10000:
        parser.error("--bulk-keys must remain 10000 for the hard gate")
    if args.min_noise_companies < 1000:
        parser.error("--min-noise-companies cannot be below 1000")
    if args.min_hot_variants < 10000:
        parser.error("--min-hot-variants cannot be below 10000")
    if args.min_global_variants < 100000:
        parser.error("--min-global-variants cannot be below 100000")
    if args.single_runs < 50 or args.batch_runs < 20:
        parser.error("percentile sample counts are too small")
    if args.parallel_ops < 256 or args.mutation_ops < 128:
        parser.error("stress operation counts are too small")
    if args.hot_key_workers < 16 or args.deadlock_workers < 32:
        parser.error("contention/deadlock worker counts are too small")
    if args.correctness_samples < 250:
        parser.error("--correctness-samples cannot be below 250")
    return args


if __name__ == "__main__":
    try:
        asyncio.run(run(parse_args()))
    except DBAPIError as exc:
        original = getattr(exc, "orig", exc)
        message = str(original).replace("\n", " ")
        if len(message) > 1200:
            message = message[:1200] + "...<truncated>"
        print(
            "STAGE821_PROJECTOR_STRESS_DB_ERROR="
            f"{type(original).__name__}: {message}"
        )
        print("STAGE821_PROJECTOR_STRESS_GATE=FAIL")
        raise SystemExit(1)
    except Exception as exc:
        message = str(exc).replace("\n", " ")
        if len(message) > 1200:
            message = message[:1200] + "...<truncated>"
        print(
            "STAGE821_PROJECTOR_STRESS_ERROR="
            f"{type(exc).__name__}: {message}"
        )
        print("STAGE821_PROJECTOR_STRESS_GATE=FAIL")
        raise SystemExit(1)
