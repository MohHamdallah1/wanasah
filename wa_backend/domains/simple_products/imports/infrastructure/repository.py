"""Persistence adapter for Product Import staging/job state.

This module owns direct ORM/SQLAlchemy access for Product Import jobs/rows and
the closely-related actor/barcode lookups required by the existing worker flow.
It intentionally does not own Product/Pricing/Tracking business rules.
"""
from __future__ import annotations

from collections.abc import Iterable
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
    ProductBarcode,
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
        await db.execute(
            insert(ProductImportRow),
            list(batch),
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


async def find_active_barcodes(
    db: AsyncSession,
    *,
    company_id: int,
    candidates: list[str],
) -> set[str]:
    if not candidates:
        return set()
    result = await db.execute(
        select(
            ProductBarcode.barcode
        ).where(
            ProductBarcode.company_id
            == int(company_id),
            ProductBarcode.barcode.in_(
                candidates
            ),
            ProductBarcode.is_active.is_(
                True
            ),
        )
    )
    return set(
        result.scalars().fetchmany(
            len(candidates)
        )
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
