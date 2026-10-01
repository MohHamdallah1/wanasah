"""Bounded failed-row projection; raw source/metadata never leave persistence."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Text, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import JSONB

from domains.simple_products.imports.domain.inline_correction import (
    MAX_INLINE_CORRECTION_ROWS, MAX_INLINE_ROW_VALUES_BYTES,
)
from models import ProductImportRow


async def fetch_correction_rows_page(
    db: AsyncSession,
    *,
    company_id: int,
    job_id: UUID,
    fields: dict[str, str],
    after_row: int,
    limit: int,
) -> list[Any]:
    if not 1 <= limit <= MAX_INLINE_CORRECTION_ROWS or after_row < 0:
        raise ValueError("Invalid correction page bounds.")
    arguments = [
        value
        for field, header in fields.items()
        for value in (field, ProductImportRow.raw_data[header])
    ]
    projected = func.jsonb_build_object(*arguments, type_=JSONB)
    # Cap bytes in SQL before transferring any cell values to Python.
    values = case(
        (
            (ProductImportRow.compacted_at.is_(None))
            & (func.octet_length(cast(projected, Text)) <= MAX_INLINE_ROW_VALUES_BYTES),
            projected,
        ),
        else_=None,
    ).label("values")
    result = await db.execute(
        select(
            ProductImportRow.row_identity, ProductImportRow.row_number,
            ProductImportRow.version, ProductImportRow.status,
            ProductImportRow.error_code, ProductImportRow.compacted_at, values,
        )
        .where(
            ProductImportRow.company_id == int(company_id),
            ProductImportRow.job_id == job_id,
            ProductImportRow.status.in_(("INVALID", "IMPORT_FAILED")),
            ProductImportRow.row_number > after_row,
        )
        .order_by(ProductImportRow.row_number.asc())
        .limit(limit + 1)
    )
    return list(result.all())
