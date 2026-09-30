"""Event-driven maintenance dispatch and tenant-scoped deadline reconciliation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import text

from domains.simple_products.imports.domain.retention import (
    DEFAULT_PRODUCT_IMPORT_RETENTION,
    TERMINAL_IMPORT_JOB_STATUSES,
)
from domains.simple_products.imports.infrastructure.queue_dsn import product_import_psycopg_dsn
from domains.simple_products.imports.infrastructure.repository import close_tenant_session, open_tenant_session


async def defer_due_candidates(task, *, kind: str, lock_prefix: str) -> dict[str, int]:
    """One control connection; at most ten indexed pages, never tenant discovery.

    Claim advancement and queue insertion commit together. A candidate remains
    durable while queued/running or after exhausted delivery retries. Legacy
    jobs without queueing_lock are included in the batched active-lock probe.
    """
    counts = {"companies_seen": 0, "deferred": 0, "skipped_active_or_idle": 0}
    cutoff = datetime.now(timezone.utc)
    async with await psycopg.AsyncConnection.connect(product_import_psycopg_dsn()) as conn:
        for _ in range(10):
            async with conn.transaction():
                cursor = await conn.execute(
                    "SELECT company_id, generation FROM public.product_import_claim_schedule(%s,%s,%s)",
                    (kind, cutoff, 1000),
                )
                candidates = await cursor.fetchall()
                if not candidates:
                    break
                locks = [lock_prefix + str(company_id) for company_id, _ in candidates]
                cursor = await conn.execute(
                    "SELECT lock FROM public.procrastinate_jobs WHERE lock = ANY(%s::text[]) "
                    "AND status IN ('todo','doing')", (locks,),
                )
                active = {row[0] for row in await cursor.fetchall()}
                counts["companies_seen"] += len(candidates)
                for (company_id, _generation), lock in zip(candidates, locks):
                    if lock in active:
                        counts["skipped_active_or_idle"] += 1
                        continue
                    try:
                        # Savepoint: a deduplication conflict must not abort the
                        # page transaction or discard other atomic submissions.
                        async with conn.transaction():
                            await task.configure(connection=conn, lock=lock, queueing_lock=lock).defer_async(
                                company_id=int(company_id),
                            )
                    except AlreadyEnqueued:
                        counts["skipped_active_or_idle"] += 1
                    else:
                        counts["deferred"] += 1
            if len(candidates) < 1000:
                break
    return counts


async def reconcile_candidate(company_id: int, *, kind: str) -> None:
    """After successful work, snapshot generation BEFORE reading next deadlines.

    Events or another completion after this snapshot invalidate the CAS. Global
    sequence generations prevent delete/reinsert ABA. No generation in the task
    payload is needed, so persisted company-only jobs use this same protocol.
    No business row lock is taken while holding a candidate row lock.
    """
    token, db = await open_tenant_session(company_id)
    try:
        parameters = {"company_id": int(company_id), "kind": kind}
        generation = await db.scalar(text(
            "SELECT generation FROM public.product_import_schedule_candidates "
            "WHERE company_id = :company_id AND task_kind = :kind"
        ), parameters)
        if generation is None:
            return
        now = datetime.now(timezone.utc)
        if kind == "capacity":
            relevant = await db.scalar(text("""
                SELECT EXISTS (
                    SELECT 1 FROM product_import_tenant_source_capacity
                    WHERE company_id = :company_id AND live_bytes <> 0
                ) OR EXISTS (
                    SELECT 1 FROM product_import_sources
                    WHERE company_id = :company_id AND deleted_at IS NULL
                ) OR EXISTS (
                    SELECT 1 FROM product_import_jobs WHERE company_id = :company_id
                    AND status IN ('QUEUED','PARSING','NEEDS_MAPPING','VALIDATING','IMPORTING','RETRYING')
                ) OR EXISTS (
                    SELECT 1 FROM product_import_admission_rejections WHERE company_id = :company_id
                    AND created_at >= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - interval '1 hour'
                )
            """), parameters)
            deadline = now + timedelta(minutes=5) if relevant else None
        elif kind == "retention":
            policy = DEFAULT_PRODUCT_IMPORT_RETENTION
            parameters.update(
                terminal_statuses=list(TERMINAL_IMPORT_JOB_STATUSES),
                source_window=policy.upload_bytes, detail_window=policy.full_row_detail,
                lineage_window=policy.compact_lineage,
            )
            deadline = await db.scalar(text("""
                SELECT min(d.deadline AT TIME ZONE 'UTC')
                FROM product_import_jobs j
                CROSS JOIN LATERAL (
                    SELECT j.finished_at + CAST(:source_window AS interval) AS deadline
                    WHERE j.source_payload IS NOT NULL OR
                        (j.source_id IS NOT NULL AND j.source_payload_cleared_at IS NULL)
                    UNION ALL SELECT j.finished_at + CAST(:detail_window AS interval) WHERE EXISTS (
                        SELECT 1 FROM product_import_rows r
                        WHERE r.company_id = :company_id AND r.job_id = j.id AND r.compacted_at IS NULL)
                    UNION ALL SELECT j.finished_at + CAST(:lineage_window AS interval) WHERE EXISTS (
                        SELECT 1 FROM product_import_rows r WHERE r.company_id = :company_id AND r.job_id = j.id)
                ) d
                WHERE j.company_id = :company_id AND j.finished_at IS NOT NULL
                  AND j.status = ANY(CAST(:terminal_statuses AS text[]))
            """), parameters)
        else:
            raise ValueError("Unknown Product Import candidate kind")
        await db.execute(text(
            "SELECT public.product_import_finish_schedule(:company_id, :kind, "
            "CAST(:generation AS bigint), CAST(:deadline AS timestamptz))"
        ), {**parameters, "generation": generation, "deadline": deadline})
        await db.commit()
    finally:
        await close_tenant_session(token, db)
