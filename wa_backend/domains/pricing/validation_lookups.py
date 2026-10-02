"""Tenant-scoped, set-based ProductVariant/UOM lookup for Pricing.

Use one database snapshot for a bounded set of variants, without caching it
across draft and publish: either boundary may observe catalog updates made by
other transactions. Pricing, not its callers, retains validation authority.
"""
from __future__ import annotations

from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import PriceBookEntry, ProductUomConversion, ProductVariant


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

async def load_initial_variant_uom_history_snapshot(
    db: AsyncSession,
    *,
    company_id: int,
    price_book_id: int,
    publication_id: int,
    variant_ids: list[int],
) -> tuple[
    dict[int, tuple[int, str]],
    dict[int, set[int]],
    bool,
]:
    """Fetch initial-price UOM state and prior-history proof in one SQL call.

    The EXISTS subquery excludes the in-flight publication so repeated 200-entry
    chunks can safely include another UOM for the same newly priced Variant.
    Any other PriceBookEntry in this PriceBook rejects the first-price fast path.
    """
    ids = sorted({int(variant_id) for variant_id in variant_ids})
    if not ids:
        return {}, {}, False

    history_exists = (
        select(PriceBookEntry.id)
        .where(
            PriceBookEntry.company_id == int(company_id),
            PriceBookEntry.price_book_id == int(price_book_id),
            PriceBookEntry.product_variant_id.in_(ids),
            PriceBookEntry.publication_id != int(publication_id),
        )
        .exists()
        .label("has_price_history")
    )
    stmt = (
        select(
            ProductVariant.id.label("variant_id"),
            ProductVariant.base_uom_id,
            ProductVariant.lifecycle_status,
            ProductUomConversion.from_uom_id,
            ProductUomConversion.to_uom_id,
            history_exists,
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
        .execution_options(
            wanasah_sql_trace_label="pricing_initial_variant_uom_history"
        )
    )

    variants: dict[int, tuple[int, str]] = {}
    mapped: dict[int, set[int]] = {}
    has_history = False
    for row in (await db.execute(stmt)).all():
        has_history = bool(row.has_price_history)
        variant_id = int(row.variant_id)
        base_uom_id = int(row.base_uom_id)
        variants[variant_id] = (base_uom_id, str(row.lifecycle_status))
        allowed = mapped.setdefault(variant_id, {base_uom_id})
        if row.from_uom_id is not None:
            allowed.add(int(row.from_uom_id))
            allowed.add(int(row.to_uom_id))
    return variants, mapped, has_history


async def load_locked_publication_validation_snapshot(
    db: AsyncSession,
    *,
    company_id: int,
    publication_id: int,
) -> tuple[
    list[PriceBookEntry],
    dict[int, tuple[int, str]],
    dict[int, set[int]],
]:
    """Lock draft price rows and fetch current Variant/UOM state in one SQL call.

    This preserves the old publish-time freshness boundary: no draft snapshot is
    reused. Only PriceBookEntry rows are locked; joined catalog rows retain the
    previous unlocked read semantics. LEFT JOINs preserve malformed/missing
    catalog references as validation failures instead of silently dropping an
    entry. Duplicate conversion rows are folded into the same UOM set.
    """
    stmt = (
        select(
            PriceBookEntry,
            ProductVariant.base_uom_id.label("variant_base_uom_id"),
            ProductVariant.lifecycle_status.label("variant_lifecycle_status"),
            ProductUomConversion.from_uom_id,
            ProductUomConversion.to_uom_id,
        )
        .select_from(PriceBookEntry)
        .outerjoin(
            ProductVariant,
            and_(
                ProductVariant.company_id == PriceBookEntry.company_id,
                ProductVariant.id == PriceBookEntry.product_variant_id,
            ),
        )
        .outerjoin(
            ProductUomConversion,
            and_(
                ProductUomConversion.company_id == PriceBookEntry.company_id,
                ProductUomConversion.product_variant_id
                == PriceBookEntry.product_variant_id,
            ),
        )
        .where(
            PriceBookEntry.company_id == int(company_id),
            PriceBookEntry.publication_id == int(publication_id),
        )
        .order_by(
            PriceBookEntry.product_variant_id,
            PriceBookEntry.uom_id,
            func.lower(PriceBookEntry.effectivity),
            PriceBookEntry.id,
        )
        .with_for_update(of=PriceBookEntry)
        .execution_options(
            wanasah_sql_trace_label="pricing_publish_entries_variant_uom"
        )
    )

    entries: list[PriceBookEntry] = []
    seen_entries: set[int] = set()
    variants: dict[int, tuple[int, str]] = {}
    mapped: dict[int, set[int]] = {}
    for row in (await db.execute(stmt)).all():
        entry = row[0]
        entry_id = int(entry.id)
        if entry_id not in seen_entries:
            seen_entries.add(entry_id)
            entries.append(entry)

        variant_id = int(entry.product_variant_id)
        if row.variant_base_uom_id is None:
            continue
        base_uom_id = int(row.variant_base_uom_id)
        variants[variant_id] = (
            base_uom_id,
            str(row.variant_lifecycle_status),
        )
        allowed = mapped.setdefault(variant_id, {base_uom_id})
        if row.from_uom_id is not None:
            allowed.add(int(row.from_uom_id))
            allowed.add(int(row.to_uom_id))
    return entries, variants, mapped

