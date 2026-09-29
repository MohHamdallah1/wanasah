"""Persistence adapter for Product Import staging/job state.

This module owns direct ORM/SQLAlchemy access for Product Import jobs/rows and
the closely-related actor/barcode lookups required by the existing worker flow.
It intentionally does not own Product/Pricing/Tracking business rules.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from database import AsyncSessionLocal
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.infrastructure.parsers import (
    ParsedRow,
)
from models import (
    Driver,
    ProductImportJob,
    ProductImportRow,
)


async def open_tenant_session(
    company_id: int,
):
    token = tenant_context.set(
        int(company_id)
    )
    db = AsyncSessionLocal()
    try:
        await db.execute(
            text(
                "SELECT set_config("
                "'app.current_tenant', :c, false)"
            ),
            {
                "c": str(
                    int(company_id)
                )
            },
        )
        return token, db
    except Exception:
        await db.close()
        tenant_context.reset(token)
        raise


async def close_tenant_session(
    token,
    db: AsyncSession,
) -> None:
    try:
        await db.close()
    finally:
        tenant_context.reset(token)


async def load_job(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    for_update: bool = False,
) -> ProductImportJob | None:
    statement = select(
        ProductImportJob
    ).where(
        ProductImportJob.company_id
        == int(company_id),
        ProductImportJob.id
        == job_id,
    )
    if for_update:
        statement = (
            statement.with_for_update()
        )
    return await db.scalar(
        statement
    )


async def mark_job_source_cleared(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> None:
    job = await load_job(
        db,
        company_id=company_id,
        job_id=job_id,
        for_update=True,
    )
    if job is None:
        raise ProductImportTerminalError(
            "Product import job was not found."
        )
    if (
        job.source_payload_cleared_at
        is None
    ):
        job.source_payload_cleared_at = (
            func.now()
        )
        await db.flush()


async def delete_job_rows(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    status: str | None = None,
) -> None:
    statement = delete(
        ProductImportRow
    ).where(
        ProductImportRow.company_id
        == int(company_id),
        ProductImportRow.job_id
        == job_id,
    )
    if status is not None:
        statement = statement.where(
            ProductImportRow.status
            == status,
        )
    await db.execute(statement)


async def insert_staged_rows(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    rows: Iterable[ParsedRow],
    batch_size: int,
    max_rows: int,
) -> int:
    if batch_size <= 0:
        raise ValueError(
            "batch_size must be positive."
        )
    if max_rows <= 0:
        raise ValueError(
            "max_rows must be positive."
        )

    batch: list[
        dict[str, Any]
    ] = []
    total_rows = 0

    async def flush() -> None:
        if not batch:
            return
        # A single explicit multi-VALUES statement avoids asyncpg
        # executemany stalls on Windows during large staging jobs.
        # Keep the bounded batch and stage-count reconciliation.
        await db.execute(
            insert(ProductImportRow).values(
                list(batch)
            ),
        )
        batch.clear()

    for parsed in rows:
        total_rows += 1
        if total_rows > max_rows:
            raise ProductImportTerminalError(
                f"The import exceeds the {max_rows:,}-row safety limit."
            )

        batch.append(
            {
                "company_id": int(
                    company_id
                ),
                "job_id": job_id,
                "row_number": int(
                    parsed.row_number
                ),
                "raw_data": dict(
                    parsed.raw
                ),
                "normalized_data": {},
                "status": "STAGED",
                "version": 1,
            }
        )
        if (
            len(batch)
            >= batch_size
        ):
            await flush()

    if total_rows == 0:
        raise ProductImportTerminalError(
            "The file contains no product rows."
        )

    await flush()
    return total_rows


async def fetch_validation_batch(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    after_row_number: int,
    limit: int,
) -> list[ProductImportRow]:
    if limit <= 0:
        raise ValueError(
            "limit must be positive."
        )

    result = await db.execute(
        select(
            ProductImportRow
        )
        .where(
            ProductImportRow.company_id
            == int(company_id),
            ProductImportRow.job_id
            == job_id,
            ProductImportRow.status
            == "STAGED",
            ProductImportRow.row_number
            > int(
                after_row_number
            ),
        )
        .order_by(
            ProductImportRow.row_number.asc()
        )
        .limit(
            int(limit)
        )
        .with_for_update()
    )
    return list(
        result.scalars().fetchmany(
            int(limit)
        )
    )


async def count_validation_outcomes(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> tuple[int, int, int]:
    row = (
        await db.execute(
            select(
                func.count(
                    ProductImportRow.id
                ).filter(
                    ProductImportRow.status
                    == "VALID"
                ),
                func.count(
                    ProductImportRow.id
                ).filter(
                    ProductImportRow.status
                    == "INVALID"
                ),
                func.count(
                    ProductImportRow.id
                ).filter(
                    ProductImportRow.status
                    == "STAGED"
                ),
            ).where(
                ProductImportRow.company_id
                == int(company_id),
                ProductImportRow.job_id
                == job_id,
            )
        )
    ).one()

    return (
        int(
            row[0]
            or 0
        ),
        int(
            row[1]
            or 0
        ),
        int(
            row[2]
            or 0
        ),
    )


async def list_job_rows(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    status: str | None = None,
    limit: int,
    for_update_skip_locked: bool = False,
) -> list[ProductImportRow]:
    if limit <= 0:
        raise ValueError(
            "limit must be positive."
        )

    statement = (
        select(ProductImportRow)
        .where(
            ProductImportRow.company_id
            == int(company_id),
            ProductImportRow.job_id
            == job_id,
        )
        .order_by(
            ProductImportRow.row_number.asc()
        )
    )
    if status is not None:
        statement = statement.where(
            ProductImportRow.status
            == status,
        )
    statement = statement.limit(
        int(limit)
    )
    if for_update_skip_locked:
        statement = (
            statement.with_for_update(
                skip_locked=True
            )
        )
    result = await db.execute(
        statement
    )
    return list(
        result.scalars().fetchmany(
            int(limit)
        )
    )


async def fetch_failed_rows_batch(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    after_row_number: int,
    limit: int,
) -> list[ProductImportRow]:
    if limit <= 0:
        raise ValueError(
            "limit must be positive."
        )

    result = await db.execute(
        select(
            ProductImportRow
        )
        .where(
            ProductImportRow.company_id
            == int(company_id),
            ProductImportRow.job_id
            == job_id,
            ProductImportRow.status.in_(
                (
                    "INVALID",
                    "IMPORT_FAILED",
                )
            ),
            ProductImportRow.row_number
            > int(
                after_row_number
            ),
        )
        .order_by(
            ProductImportRow.row_number.asc()
        )
        .limit(
            int(limit)
        )
    )
    return list(
        result.scalars().fetchmany(
            int(limit)
        )
    )


async def rebuild_job_barcode_staging(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> int:
    await db.execute(
        text(
            """
            DELETE FROM product_import_row_barcodes
            WHERE company_id = :company_id
              AND job_id = :job_id
            """
        ),
        {
            "company_id": int(company_id),
            "job_id": job_id,
        },
    )

    result = await db.execute(
        text(
            """
            INSERT INTO product_import_row_barcodes (
                company_id,
                job_id,
                row_number,
                barcode
            )
            SELECT DISTINCT
                rows.company_id,
                rows.job_id,
                rows.row_number,
                candidate.barcode
            FROM product_import_rows AS rows
            CROSS JOIN LATERAL (
                VALUES
                    (
                        NULLIF(
                            rows.normalized_data->>'unit_barcode',
                            ''
                        )
                    ),
                    (
                        NULLIF(
                            rows.normalized_data->>'package_barcode',
                            ''
                        )
                    )
            ) AS candidate(barcode)
            WHERE rows.company_id = :company_id
              AND rows.job_id = :job_id
              AND rows.status = 'VALID'
              AND candidate.barcode IS NOT NULL
            """
        ),
        {
            "company_id": int(company_id),
            "job_id": job_id,
        },
    )
    return int(
        result.rowcount
        or 0
    )


async def invalidate_internal_duplicate_barcodes(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> int:
    result = await db.execute(
        text(
            """
            -- A single ordered barcode scan avoids a quadratic join when
            -- newly populated staging tables have stale planner estimates.
            WITH barcode_occurrences AS MATERIALIZED (
                SELECT
                    row_number,
                    COUNT(*) OVER (
                        PARTITION BY barcode
                    ) AS occurrences
                FROM product_import_row_barcodes
                WHERE company_id = :company_id
                  AND job_id = :job_id
            ),
            bad_rows AS (
                SELECT DISTINCT row_number
                FROM barcode_occurrences
                WHERE occurrences > 1
            )
            UPDATE product_import_rows AS rows
            SET status = 'INVALID',
                error_code = 'IMPORT_BARCODE_DUPLICATE',
                error_message = 'Barcode appears on more than one import row.',
                version = rows.version + 1,
                updated_at = CURRENT_TIMESTAMP
            FROM bad_rows
            WHERE rows.company_id = :company_id
              AND rows.job_id = :job_id
              AND rows.row_number = bad_rows.row_number
              AND rows.status = 'VALID'
            """
        ),
        {
            "company_id": int(company_id),
            "job_id": job_id,
        },
    )
    return int(
        result.rowcount
        or 0
    )


async def invalidate_external_barcode_conflicts(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> int:
    result = await db.execute(
        text(
            """
            -- A correlated EXISTS is a logical semi-join. Unlike LATERAL
            -- with LIMIT 1 OFFSET 0, it lets PostgreSQL use the tenant/
            -- active-barcode unique index and choose a set-based join.
            -- No cross-tenant read, no materialized row-level result leakage.
            WITH bad_rows AS (
                SELECT DISTINCT staged.row_number
                FROM product_import_row_barcodes AS staged
                WHERE staged.company_id = :company_id
                  AND staged.job_id = :job_id
                  AND EXISTS (
                      SELECT 1
                      FROM product_barcodes AS existing
                      WHERE existing.company_id = staged.company_id
                        AND existing.barcode = staged.barcode
                        AND existing.is_active IS TRUE
                  )
            )
            UPDATE product_import_rows AS rows
            SET status = 'INVALID',
                error_code = 'IMPORT_BARCODE_CONFLICT',
                error_message = 'Barcode is already active.',
                version = rows.version + 1,
                updated_at = CURRENT_TIMESTAMP
            FROM bad_rows
            WHERE rows.company_id = :company_id
              AND rows.job_id = :job_id
              AND rows.row_number = bad_rows.row_number
              AND rows.status = 'VALID'
            """
        ),
        {
            "company_id": int(company_id),
            "job_id": job_id,
        },
    )
    return int(
        result.rowcount
        or 0
    )


async def load_active_actor(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
) -> Driver | None:
    return await db.scalar(
        select(Driver).where(
            Driver.company_id
            == int(company_id),
            Driver.id
            == int(actor_id),
            Driver.is_active.is_(True),
        )
    )


@dataclass(frozen=True, slots=True)
class ProductImportProgress:
    total_rows: int
    imported_rows: int
    invalid_rows: int
    import_failed_rows: int
    pending_rows: int


async def count_job_progress(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> ProductImportProgress:
    row = (
        await db.execute(
            select(
                func.count(
                    ProductImportRow.id
                ),
                func.count(
                    ProductImportRow.id
                ).filter(
                    ProductImportRow.status
                    == "IMPORTED"
                ),
                func.count(
                    ProductImportRow.id
                ).filter(
                    ProductImportRow.status
                    == "INVALID"
                ),
                func.count(
                    ProductImportRow.id
                ).filter(
                    ProductImportRow.status
                    == "IMPORT_FAILED"
                ),
                func.count(
                    ProductImportRow.id
                ).filter(
                    ProductImportRow.status.in_(
                        (
                            "STAGED",
                            "VALID",
                        )
                    )
                ),
            ).where(
                ProductImportRow.company_id
                == int(company_id),
                ProductImportRow.job_id
                == job_id,
            )
        )
    ).one()

    return ProductImportProgress(
        total_rows=int(
            row[0]
            or 0
        ),
        imported_rows=int(
            row[1]
            or 0
        ),
        invalid_rows=int(
            row[2]
            or 0
        ),
        import_failed_rows=int(
            row[3]
            or 0
        ),
        pending_rows=int(
            row[4]
            or 0
        ),
    )


async def count_job_statuses(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
) -> dict[str, int]:
    rows = (
        await db.execute(
            select(
                ProductImportRow.status,
                func.count(
                    ProductImportRow.id
                ),
            )
            .where(
                ProductImportRow.company_id
                == int(
                    company_id
                ),
                ProductImportRow.job_id
                == job_id,
            )
            .group_by(
                ProductImportRow.status
            )
        )
    ).all()
    return {
        str(
            status
        ): int(
            count
            or 0
        )
        for status, count in rows
    }


async def job_has_rows(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    status: str,
) -> bool:
    value = await db.scalar(
        select(
            ProductImportRow.id
        )
        .where(
            ProductImportRow.company_id
            == int(
                company_id
            ),
            ProductImportRow.job_id
            == job_id,
            ProductImportRow.status
            == str(
                status
            ),
        )
        .order_by(
            ProductImportRow.row_number.asc()
        )
        .limit(
            1
        )
    )
    return (
        value
        is not None
    )


async def count_job_rows(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    status: str,
) -> int:
    value = await db.scalar(
        select(
            func.count(
                ProductImportRow.id
            )
        ).where(
            ProductImportRow.company_id
            == int(company_id),
            ProductImportRow.job_id
            == job_id,
            ProductImportRow.status
            == status,
        )
    )
    return int(value or 0)
