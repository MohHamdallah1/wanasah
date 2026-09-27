"""Bounded tenant-scoped persistence for Product Import retention."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
    db: AsyncSession,
    *,
    company_id: int,
    cutoff: datetime,
    limit: int,
) -> list[UUID]:
    batch_limit = _bounded_limit(
        limit
    )
    result = await db.execute(
        text(
            f"""
            SELECT jobs.source_id
            FROM product_import_jobs AS jobs
            WHERE jobs.company_id = :company_id
              AND jobs.status IN ({_TERMINAL_STATUS_SQL})
              AND jobs.finished_at IS NOT NULL
              AND jobs.finished_at <= :cutoff
              AND jobs.source_id IS NOT NULL
              AND jobs.source_payload_cleared_at IS NULL
            ORDER BY
                jobs.finished_at ASC,
                jobs.id ASC
            LIMIT :batch_limit
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
    return [
        UUID(
            str(
                source_id
            )
        )
        for (
            source_id,
        )
        in result.fetchall()
    ]


async def mark_source_ids_cleared(
    db: AsyncSession,
    *,
    company_id: int,
    source_ids: list[UUID],
) -> int:
    if not source_ids:
        return 0
    result = await db.execute(
        text(
            """
            UPDATE product_import_jobs
            SET source_payload_cleared_at =
                    COALESCE(
                        source_payload_cleared_at,
                        CURRENT_TIMESTAMP
                    ),
                updated_at =
                    CURRENT_TIMESTAMP
            WHERE company_id = :company_id
              AND source_id = ANY(
                  CAST(:source_ids AS uuid[])
              )
              AND source_payload_cleared_at IS NULL
            """
        ),
        {
            "company_id":
                int(
                    company_id
                ),
            "source_ids": [
                str(
                    source_id
                )
                for source_id
                in source_ids
            ],
        },
    )
    return int(
        result.rowcount
        or 0
    )


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
            WITH candidates AS MATERIALIZED (
                SELECT rows.id
                FROM product_import_rows AS rows
                JOIN product_import_jobs AS jobs
                  ON jobs.company_id = rows.company_id
                 AND jobs.id = rows.job_id
                WHERE rows.company_id = :company_id
                  AND jobs.company_id = :company_id
                  AND jobs.status IN ({_TERMINAL_STATUS_SQL})
                  AND jobs.finished_at IS NOT NULL
                  AND jobs.finished_at <= :cutoff
                  AND rows.compacted_at IS NULL
                ORDER BY
                    jobs.finished_at ASC,
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
            WITH candidates AS MATERIALIZED (
                SELECT rows.id
                FROM product_import_rows AS rows
                JOIN product_import_jobs AS jobs
                  ON jobs.company_id = rows.company_id
                 AND jobs.id = rows.job_id
                WHERE rows.company_id = :company_id
                  AND jobs.company_id = :company_id
                  AND jobs.status IN ({_TERMINAL_STATUS_SQL})
                  AND jobs.finished_at IS NOT NULL
                  AND jobs.finished_at <= :cutoff
                ORDER BY
                    jobs.finished_at ASC,
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
