"""Read-only canonical optional outer counting UOM, never inventory authority.

Caller first authorizes the stocktake/session and bounds the returned page.
Only variant specifications *on that authorized page* may be looked up here.
A conflicting conversion graph suppresses its own variant's outer UOM.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.uom_authority import (
    UomAuthorityError,
    build_variant_uom_authority,
)
from models import ProductUomConversion, UOM
from quantity import QUANTITY_MAX


# (base_uom_id, quantity_scale, quantity_step) come from the authorized read.
CountVariantSpec = tuple[int, int, Decimal]
MAX_COUNT_VARIANTS = 10_000


async def read_count_outer_uoms(
    db: AsyncSession,
    *,
    company_id: int,
    variants: Mapping[int, CountVariantSpec],
) -> dict[int, dict[str, int | str]]:
    """Return optional exact base-per-outer factors for a bounded page.

    One tenant-filtered conversion query, one UOM lookup at most, no N+1.
    No legacy packs_per_carton, quantity conversion via float or money reads.
    """
    if not variants:
        return {}
    ids = sorted({int(variant_id) for variant_id in variants})
    if (
        len(ids) > MAX_COUNT_VARIANTS
        or company_id <= 0
        or any(variant_id <= 0 for variant_id in ids)
    ):
        raise ValueError("Stocktake outer UOM read requires a bounded authorized page.")

    conversions = (await db.scalars(
        select(ProductUomConversion).where(
            ProductUomConversion.company_id == company_id,
            ProductUomConversion.product_variant_id.in_(ids),
        ).order_by(
            ProductUomConversion.product_variant_id,
            ProductUomConversion.id,
        )
    )).all()

    by_variant: dict[int, list[ProductUomConversion]] = defaultdict(list)
    for conversion in conversions:
        by_variant[int(conversion.product_variant_id)].append(conversion)

    winners: dict[int, tuple[int, Fraction]] = {}
    for variant_id in ids:
        if not by_variant[variant_id]:
            continue
        base_uom_id, scale, step = variants[variant_id]
        variant = SimpleNamespace(
            id=variant_id, base_uom_id=base_uom_id,
            quantity_scale=scale, quantity_step=step,
        )
        try:
            authority = build_variant_uom_authority(
                variant, by_variant[variant_id],
            )
            candidate = authority.largest_display_uom()
            if candidate is None:
                continue
            uom_id, factor = candidate
            # Whole base quantity, exactly representable by NUMERIC(20,6).
            if factor.denominator != 1 or not (1 < factor.numerator <= QUANTITY_MAX):
                continue
            # Positive steps and product scale are canonical variant constraints.
            if Decimal(factor.numerator) % authority.quantity_step != 0:
                continue
            winners[variant_id] = (uom_id, factor)
        except (UomAuthorityError, ValueError, ArithmeticError):
            # One damaged or conflicting graph cannot leak an arbitrary unit.
            continue

    if not winners:
        return {}
    uom_ids = sorted({unit for unit, _ in winners.values()})
    names = {
        int(row.id): row
        for row in (await db.scalars(
            select(UOM).where(UOM.id.in_(uom_ids))
        )).all()
    }
    return {
        variant_id: {
            "count_outer_uom_id": unit,
            "count_outer_uom_name": names[unit].name,
            "count_outer_uom_code": names[unit].code,
            "count_outer_factor_numerator": factor.numerator,
            "count_outer_factor_denominator": factor.denominator,
        }
        for variant_id, (unit, factor) in winners.items()
        if unit in names and names[unit].code and names[unit].name
    }
