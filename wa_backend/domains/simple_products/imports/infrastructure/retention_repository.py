"""Bounded tenant-scoped persistence for Product Import retention."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

import psycopg

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from domains.simple_products.imports.application.source_store import (
    ProductImportSourceIntegrityError, TransactionalSourceStore,
)
from domains.simple_products.imports.infrastructure.queue_dsn import product_import_psycopg_dsn


_TERMINAL_STATUS_SQL = (
    "'VALIDATION_FAILED',"
    "'COMPLETED',"
    "'COMPLETED_WITH_ERRORS',"
    "'FAILED'"
)


def _bounded_limit(
    limit: int,
) -> int:
    if (
        isinstance(
            limit,
            bool,
        )
        or not isinstance(
            limit,
            int,
        )
        or limit <= 0
        or limit > 5_000
    ):
        raise ValueError(
            "Retention batch limit must be between 1 and 5000."
        )
    return int(
        limit
    )


async def fetch_expired_source_ids(
    connection: psycopg.AsyncConnection,
    *, company_id: int, cutoff: datetime, limit: int,
) -> list[UUID]:
    """Lock eligible jobs before SourceStore; caller must retain this transaction."""
    cursor = await connection.execute(
        f"""
        SELECT jobs.source_id
        FROM product_import_jobs AS jobs
        WHERE jobs.company_id = %s
          AND jobs.status IN ({_TERMINAL_STATUS_SQL})
          AND jobs.finished_at IS NOT NULL AND jobs.finished_at <= %s
          AND jobs.source_id IS NOT NULL AND jobs.source_payload_cleared_at IS NULL
        ORDER BY jobs.finished_at, jobs.id
        LIMIT %s
        FOR UPDATE OF jobs SKIP LOCKED
        """,
        (int(company_id), cutoff, _bounded_limit(limit)),
    )
    return [UUID(str(row[0])) for row in await cursor.fetchall()]


async def mark_source_ids_cleared(
    connection: psycopg.AsyncConnection,
    *, company_id: int, source_ids: list[UUID], cutoff: datetime,
) -> int:
    if not source_ids:
        return 0
    result = await connection.execute(
        f"""
        UPDATE product_import_jobs
        SET source_payload_cleared_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE company_id = %s AND source_id = ANY(%s::uuid[])
          AND source_payload_cleared_at IS NULL
          AND status IN ({_TERMINAL_STATUS_SQL})
          AND finished_at IS NOT NULL AND finished_at <= %s
        """,
        (int(company_id), source_ids, cutoff),
    )
    return int(result.rowcount or 0)


async def clear_expired_stored_sources(
    *, company_id: int, cutoff: datetime, limit: int,
    source_store: TransactionalSourceStore,
) -> int:
    # Same lock order as Retry/Correction: job -> source (ordered id) ->
    # tenant capacity -> global capacity. No connection/commit gap in cleanup.
    async with await psycopg.AsyncConnection.connect(product_import_psycopg_dsn()) as connection:
        async with connection.transaction():
            await connection.execute("SELECT set_config('app.current_tenant', %s, true)",
                                     (str(int(company_id)),))
            source_ids = await fetch_expired_source_ids(
                connection, company_id=company_id, cutoff=cutoff, limit=limit,
            )
            if not source_ids:
                return 0
            await source_store.delete_source_bytes_batch_on_connection(
                connection=connection, company_id=company_id, source_ids=source_ids,
            )
            marked = await mark_source_ids_cleared(
                connection, company_id=company_id, source_ids=source_ids, cutoff=cutoff,
            )
            if marked != len(source_ids):
                raise ProductImportSourceIntegrityError("Locked retention source eligibility changed.")
            return marked


async def clear_expired_source_payloads(
    db: AsyncSession,
    *,
    company_id: int,
    cutoff: datetime,
    limit: int,
) -> int:
    batch_limit = _bounded_limit(
        limit
    )
    result = await db.execute(
        text(
            f"""
            WITH candidates AS MATERIALIZED (
                SELECT jobs.id
                FROM product_import_jobs AS jobs
                WHERE jobs.company_id = :company_id
                  AND jobs.status IN ({_TERMINAL_STATUS_SQL})
                  AND jobs.finished_at IS NOT NULL
                  AND jobs.finished_at <= :cutoff
                  AND jobs.source_payload IS NOT NULL
                ORDER BY
                    jobs.finished_at ASC,
                    jobs.id ASC
                LIMIT :batch_limit
                FOR UPDATE SKIP LOCKED
            ),
            cleared AS (
                UPDATE product_import_jobs AS jobs
                SET source_payload = NULL,
                    source_payload_cleared_at =
                        COALESCE(
                            jobs.source_payload_cleared_at,
                            CURRENT_TIMESTAMP
                        ),
                    updated_at = CURRENT_TIMESTAMP
                FROM candidates
                WHERE jobs.company_id = :company_id
                  AND jobs.id = candidates.id
                RETURNING jobs.id
            )
            SELECT count(*)::bigint
            FROM cleared
            """
        ),
        {
            "company_id":
                int(
                    company_id
                ),
            "cutoff":
                cutoff,
            "batch_limit":
                batch_limit,
        },
    )
    return int(
        result.scalar_one()
        or 0
    )


async def compact_expired_row_details(
    db: AsyncSession,
    *,
    company_id: int,
    cutoff: datetime,
    limit: int,
) -> tuple[int, int]:
    batch_limit = _bounded_limit(
        limit
    )
    result = await db.execute(
        text(
            f"""
            WITH eligible_jobs AS MATERIALIZED (
                SELECT jobs.id
                FROM product_import_jobs AS jobs
                WHERE jobs.company_id = :company_id
                  AND jobs.status IN ({_TERMINAL_STATUS_SQL})
                  AND jobs.finished_at IS NOT NULL AND jobs.finished_at <= :cutoff
                  AND EXISTS (
                      SELECT 1 FROM product_import_rows AS r
                      WHERE r.company_id = :company_id AND r.job_id = jobs.id
                      AND r.compacted_at IS NULL
                  )
                ORDER BY jobs.finished_at, jobs.id
                LIMIT :batch_limit
                FOR UPDATE OF jobs SKIP LOCKED
            ), candidates AS MATERIALIZED (
                SELECT rows.id
                FROM product_import_rows AS rows
                JOIN eligible_jobs AS jobs ON jobs.id = rows.job_id
                WHERE rows.company_id = :company_id
                  AND rows.compacted_at IS NULL
                ORDER BY
                    rows.job_id ASC,
                    rows.id ASC
                LIMIT :batch_limit
                FOR UPDATE OF rows SKIP LOCKED
            ),
            compacted AS (
                UPDATE product_import_rows AS rows
                SET raw_data = '{{}}'::jsonb,
                    normalized_data = '{{}}'::jsonb,
                    error_message = NULL,
                    compacted_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    version = rows.version + 1
                FROM candidates
                WHERE rows.company_id = :company_id
                  AND rows.id = candidates.id
                RETURNING
                    rows.company_id,
                    rows.job_id,
                    rows.row_number
            ),
            removed_barcodes AS (
                DELETE FROM product_import_row_barcodes AS barcodes
                USING compacted
                WHERE barcodes.company_id =
                        compacted.company_id
                  AND barcodes.job_id =
                        compacted.job_id
                  AND barcodes.row_number =
                        compacted.row_number
                RETURNING 1
            )
            SELECT
                (
                    SELECT count(*)::bigint
                    FROM compacted
                ) AS compacted_rows,
                (
                    SELECT count(*)::bigint
                    FROM removed_barcodes
                ) AS removed_barcodes
            """
        ),
        {
            "company_id":
                int(
                    company_id
                ),
            "cutoff":
                cutoff,
            "batch_limit":
                batch_limit,
        },
    )
    row = result.one()
    return (
        int(
            row[
                0
            ]
            or 0
        ),
        int(
            row[
                1
            ]
            or 0
        ),
    )


async def delete_expired_row_lineage(
    db: AsyncSession,
    *,
    company_id: int,
    cutoff: datetime,
    limit: int,
) -> int:
    batch_limit = _bounded_limit(
        limit
    )
    result = await db.execute(
        text(
            f"""
            WITH eligible_jobs AS MATERIALIZED (
                SELECT jobs.id
                FROM product_import_jobs AS jobs
                WHERE jobs.company_id = :company_id
                  AND jobs.status IN ({_TERMINAL_STATUS_SQL})
                  AND jobs.finished_at IS NOT NULL AND jobs.finished_at <= :cutoff
                  AND EXISTS (
                      SELECT 1 FROM product_import_rows AS r
                      WHERE r.company_id = :company_id AND r.job_id = jobs.id
                  )
                ORDER BY jobs.finished_at, jobs.id
                LIMIT :batch_limit
                FOR UPDATE OF jobs SKIP LOCKED
            ), candidates AS MATERIALIZED (
                SELECT rows.id
                FROM product_import_rows AS rows
                JOIN eligible_jobs AS jobs ON jobs.id = rows.job_id
                WHERE rows.company_id = :company_id
                ORDER BY
                    rows.job_id ASC,
                    rows.id ASC
                LIMIT :batch_limit
                FOR UPDATE OF rows SKIP LOCKED
            ),
            deleted AS (
                DELETE FROM product_import_rows AS rows
                USING candidates
                WHERE rows.company_id = :company_id
                  AND rows.id = candidates.id
                RETURNING rows.id
            )
            SELECT count(*)::bigint
            FROM deleted
            """
        ),
        {
            "company_id":
                int(
                    company_id
                ),
            "cutoff":
                cutoff,
            "batch_limit":
                batch_limit,
        },
    )
    return int(
        result.scalar_one()
        or 0
    )
