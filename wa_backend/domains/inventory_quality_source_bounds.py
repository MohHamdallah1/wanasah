from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryBalance, InventoryLocation


QUALITY_WORKSPACE_SOURCE_LIMIT = 500


async def first_quality_source_limit_excess(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_id: int,
    batch_ids: Iterable[int],
    readable_location_filter: Any,
    max_sources: int = QUALITY_WORKSPACE_SOURCE_LIMIT,
) -> tuple[int, int] | None:
    """Return the first batch whose readable physical source count exceeds the UI bound.

    This is a set-based preflight. It runs before source details, reservation-owner
    evidence, or terminal-action discovery are materialized.
    """
    normalized_batch_ids = sorted({int(value) for value in batch_ids})
    if not normalized_batch_ids:
        return None

    source_count = func.count(func.distinct(InventoryLocation.id))
    row = (
        await db.execute(
            select(
                InventoryBalance.batch_id.label("batch_id"),
                source_count.label("source_count"),
            )
            .select_from(InventoryBalance)
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id == InventoryBalance.company_id,
                    InventoryLocation.id == InventoryBalance.location_id,
                ),
            )
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.product_variant_id == product_variant_id,
                InventoryBalance.batch_id.in_(normalized_batch_ids),
                InventoryBalance.on_hand_quantity > 0,
                InventoryLocation.is_active.is_(True),
                InventoryLocation.location_type.in_(["WAREHOUSE", "VEHICLE"]),
                readable_location_filter,
            )
            .group_by(InventoryBalance.batch_id)
            .having(source_count > int(max_sources))
            .order_by(InventoryBalance.batch_id.asc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return int(row.batch_id), int(row.source_count)
