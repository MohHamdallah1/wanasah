from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryBalance, InventoryLocation, ProductBatch, ProductVariant, UOM
from quantity import canonical_quantity


QUALITY_BATCH_SOURCE_PREVIEW_LIMIT = 6
QUALITY_PRODUCT_LOCATION_PREVIEW_LIMIT = 8


async def read_variant_inventory_issue_summary(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_id: int,
    readable_location_filter: Any,
    preview_limit: int = QUALITY_PRODUCT_LOCATION_PREVIEW_LIMIT,
) -> dict[str, Any]:
    """Return an exact set-based physical-stock summary plus a bounded location preview."""
    aggregate = (
        await db.execute(
            select(
                func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0).label("on_hand"),
                func.coalesce(func.sum(InventoryBalance.reserved_quantity), 0).label("reserved"),
                func.count(func.distinct(InventoryBalance.batch_id)).label("batch_count"),
                func.count(func.distinct(InventoryLocation.id)).label("source_count"),
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
                InventoryBalance.on_hand_quantity > 0,
                InventoryLocation.is_active.is_(True),
                InventoryLocation.location_type.in_(["WAREHOUSE", "VEHICLE"]),
                readable_location_filter,
            )
        )
    ).one()

    location_rows = (
        await db.execute(
            select(
                InventoryLocation.id.label("location_id"),
                InventoryLocation.name.label("location_name"),
                InventoryLocation.location_type,
                func.sum(InventoryBalance.on_hand_quantity).label("on_hand"),
                func.sum(InventoryBalance.reserved_quantity).label("reserved"),
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
                InventoryBalance.on_hand_quantity > 0,
                InventoryLocation.is_active.is_(True),
                InventoryLocation.location_type.in_(["WAREHOUSE", "VEHICLE"]),
                readable_location_filter,
            )
            .group_by(
                InventoryLocation.id,
                InventoryLocation.name,
                InventoryLocation.location_type,
            )
            .order_by(InventoryLocation.location_type.asc(), InventoryLocation.name.asc(), InventoryLocation.id.asc())
            .limit(int(preview_limit) + 1)
        )
    ).all()

    preview_rows = location_rows[:preview_limit]
    return {
        "total_on_hand_quantity": canonical_quantity(Decimal(aggregate.on_hand or 0)),
        "total_reserved_quantity": canonical_quantity(Decimal(aggregate.reserved or 0)),
        "batch_count": int(aggregate.batch_count or 0),
        "source_count": int(aggregate.source_count or 0),
        "locations_preview": [
            {
                "location_id": int(row.location_id),
                "location_name": str(row.location_name),
                "location_type": str(row.location_type).upper(),
                "on_hand_quantity": canonical_quantity(Decimal(row.on_hand or 0)),
                "reserved_quantity": canonical_quantity(Decimal(row.reserved or 0)),
            }
            for row in preview_rows
        ],
        "locations_truncated": len(location_rows) > preview_limit,
    }


async def read_quality_batch_candidates(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_id: int,
    readable_location_filter: Any,
    cursor: int | None,
    limit: int,
    source_preview_limit: int = QUALITY_BATCH_SOURCE_PREVIEW_LIMIT,
) -> dict[str, Any] | None:
    """List one product's physical batches across every readable warehouse/vehicle."""
    variant = (
        await db.execute(
            select(ProductVariant.id, ProductVariant.base_uom_id, UOM.code.label("base_uom_code"))
            .join(UOM, UOM.id == ProductVariant.base_uom_id)
            .where(
                ProductVariant.company_id == company_id,
                ProductVariant.id == product_variant_id,
            )
        )
    ).one_or_none()
    if variant is None:
        return None

    source_count = func.count(func.distinct(InventoryLocation.id))
    query = (
        select(
            ProductBatch.id.label("batch_id"),
            ProductBatch.batch_number,
            ProductBatch.production_date,
            ProductBatch.expiry_date,
            ProductBatch.disposition,
            ProductBatch.disposition_reason,
            func.sum(InventoryBalance.on_hand_quantity).label("on_hand"),
            func.sum(InventoryBalance.reserved_quantity).label("reserved"),
            source_count.label("source_count"),
        )
        .select_from(InventoryBalance)
        .join(
            ProductBatch,
            and_(
                ProductBatch.company_id == InventoryBalance.company_id,
                ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
                ProductBatch.id == InventoryBalance.batch_id,
            ),
        )
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
            InventoryBalance.on_hand_quantity > 0,
            InventoryLocation.is_active.is_(True),
            InventoryLocation.location_type.in_(["WAREHOUSE", "VEHICLE"]),
            readable_location_filter,
        )
        .group_by(
            ProductBatch.id,
            ProductBatch.batch_number,
            ProductBatch.production_date,
            ProductBatch.expiry_date,
            ProductBatch.disposition,
            ProductBatch.disposition_reason,
        )
    )
    if cursor is not None:
        query = query.where(ProductBatch.id > int(cursor))

    rows = (
        await db.execute(
            query.order_by(ProductBatch.id.asc()).limit(int(limit) + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    batch_ids = [int(row.batch_id) for row in page_rows]
    source_rows = []
    if batch_ids:
        grouped_sources = (
            select(
                InventoryBalance.batch_id.label("batch_id"),
                InventoryLocation.id.label("location_id"),
                InventoryLocation.name.label("location_name"),
                InventoryLocation.location_type.label("location_type"),
                func.sum(InventoryBalance.on_hand_quantity).label("on_hand"),
                func.sum(InventoryBalance.reserved_quantity).label("reserved"),
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
                InventoryBalance.batch_id.in_(batch_ids),
                InventoryBalance.on_hand_quantity > 0,
                InventoryLocation.is_active.is_(True),
                InventoryLocation.location_type.in_(["WAREHOUSE", "VEHICLE"]),
                readable_location_filter,
            )
            .group_by(
                InventoryBalance.batch_id,
                InventoryLocation.id,
                InventoryLocation.name,
                InventoryLocation.location_type,
            )
            .subquery("quality_batch_sources")
        )
        ranked_sources = (
            select(
                grouped_sources.c.batch_id,
                grouped_sources.c.location_id,
                grouped_sources.c.location_name,
                grouped_sources.c.location_type,
                grouped_sources.c.on_hand,
                grouped_sources.c.reserved,
                func.row_number()
                .over(
                    partition_by=grouped_sources.c.batch_id,
                    order_by=(
                        grouped_sources.c.location_type.asc(),
                        grouped_sources.c.location_name.asc(),
                        grouped_sources.c.location_id.asc(),
                    ),
                )
                .label("source_rank"),
            )
            .subquery("ranked_quality_batch_sources")
        )
        source_rows = (
            await db.execute(
                select(
                    ranked_sources.c.batch_id,
                    ranked_sources.c.location_id,
                    ranked_sources.c.location_name,
                    ranked_sources.c.location_type,
                    ranked_sources.c.on_hand,
                    ranked_sources.c.reserved,
                )
                .where(ranked_sources.c.source_rank <= int(source_preview_limit))
                .order_by(
                    ranked_sources.c.batch_id.asc(),
                    ranked_sources.c.source_rank.asc(),
                )
            )
        ).all()

    previews: dict[int, list[dict[str, Any]]] = {batch_id: [] for batch_id in batch_ids}
    for row in source_rows:
        bucket = previews[int(row.batch_id)]
        bucket.append({
            "location_id": int(row.location_id),
            "location_name": str(row.location_name),
            "location_type": str(row.location_type).upper(),
            "on_hand_quantity": canonical_quantity(Decimal(row.on_hand or 0)),
            "reserved_quantity": canonical_quantity(Decimal(row.reserved or 0)),
        })

    items = []
    for row in page_rows:
        batch_id = int(row.batch_id)
        items.append({
            "batch_id": batch_id,
            "batch_number": str(row.batch_number),
            "production_date": row.production_date,
            "expiry_date": row.expiry_date,
            "disposition": str(row.disposition),
            "disposition_reason": str(row.disposition_reason) if row.disposition_reason is not None else None,
            "total_on_hand_quantity": canonical_quantity(Decimal(row.on_hand or 0)),
            "total_reserved_quantity": canonical_quantity(Decimal(row.reserved or 0)),
            "source_count": int(row.source_count or 0),
            "sources_preview": previews[batch_id],
            "sources_truncated": int(row.source_count or 0) > len(previews[batch_id]),
        })

    return {
        "product_variant_id": int(variant.id),
        "base_uom_id": int(variant.base_uom_id),
        "base_uom_code": str(variant.base_uom_code),
        "items": items,
        "next_cursor": int(page_rows[-1].batch_id) if has_more and page_rows else None,
        "has_more": has_more,
    }
