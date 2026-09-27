"""Tenant-scoped Product Import lineage reads."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    ProductImportJob,
    ProductImportRow,
)


MAX_LINEAGE_PAGE = 200


async def fetch_import_lineage_page(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    after_row_number: int,
    limit: int,
) -> tuple[
    ProductImportJob | None,
    list[ProductImportRow],
    bool,
]:
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
        or limit > MAX_LINEAGE_PAGE
    ):
        raise ValueError(
            "Lineage limit must be between 1 and 200."
        )
    if int(
        after_row_number
    ) < 0:
        raise ValueError(
            "after_row_number must be non-negative."
        )

    job = await db.scalar(
        select(
            ProductImportJob
        ).where(
            ProductImportJob.company_id
            == int(
                company_id
            ),
            ProductImportJob.id
            == job_id,
        )
    )
    if job is None:
        return (
            None,
            [],
            False,
        )

    query_limit = int(
        limit
    ) + 1
    result = await db.execute(
        select(
            ProductImportRow
        )
        .where(
            ProductImportRow.company_id
            == int(
                company_id
            ),
            ProductImportRow.job_id
            == job_id,
            ProductImportRow.row_number
            > int(
                after_row_number
            ),
        )
        .order_by(
            ProductImportRow.row_number.asc()
        )
        .limit(
            query_limit
        )
    )
    rows = list(
        result.scalars().fetchmany(
            query_limit
        )
    )
    has_more = (
        len(
            rows
        )
        > int(
            limit
        )
    )
    if has_more:
        rows = rows[
            : int(
                limit
            )
        ]

    return (
        job,
        rows,
        has_more,
    )
