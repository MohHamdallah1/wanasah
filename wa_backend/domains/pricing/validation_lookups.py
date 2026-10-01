"""Tenant-scoped, set-based ProductVariant/UOM lookup for Pricing.

Use one database snapshot for a bounded set of variants, without caching it
across draft and publish: either boundary may observe catalog updates made by
other transactions. Pricing, not its callers, retains validation authority.
"""
from __future__ import annotations

from typing import Literal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ProductUomConversion, ProductVariant


async def load_variant_uom_snapshot(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: list[int],
    stage: Literal["draft", "publish"],
) -> tuple[dict[int, tuple[int, str]], dict[int, set[int]]]:
    """Fetch operational state and allowed UOMs in one tenant-scoped SQL call.

    LEFT JOIN retains variants without any conversions, whose base UOM is
    nevertheless valid. Multiple conversion rows fold into a set, retaining
    the previous validation semantics. No row locking or authorization changes.
    """
    ids = sorted({int(variant_id) for variant_id in variant_ids})
    if not ids:
        return {}, {}
    label = (
        "pricing_draft_variant_uom"
        if stage == "draft"
        else "pricing_publish_variant_uom"
    )
    stmt = (
        select(
            ProductVariant.id.label("variant_id"),
            ProductVariant.base_uom_id,
            ProductVariant.lifecycle_status,
            ProductUomConversion.from_uom_id,
            ProductUomConversion.to_uom_id,
        )
        .select_from(ProductVariant)
        .outerjoin(
            ProductUomConversion,
            and_(
                ProductUomConversion.company_id == ProductVariant.company_id,
                ProductUomConversion.product_variant_id == ProductVariant.id,
            ),
        )
        .where(
            ProductVariant.company_id == int(company_id),
            ProductVariant.id.in_(ids),
        )
        .execution_options(wanasah_sql_trace_label=label)
    )

    variants: dict[int, tuple[int, str]] = {}
    mapped: dict[int, set[int]] = {}
    for row in (await db.execute(stmt)).all():
        variant_id = int(row.variant_id)
        base_uom_id = int(row.base_uom_id)
        variants[variant_id] = (base_uom_id, str(row.lifecycle_status))
        allowed = mapped.setdefault(variant_id, {base_uom_id})
        if row.from_uom_id is not None:
            allowed.add(int(row.from_uom_id))
            allowed.add(int(row.to_uom_id))
    return variants, mapped
