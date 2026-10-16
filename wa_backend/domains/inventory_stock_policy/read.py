from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    InventoryLocation,
    InventoryStockPolicy,
    ProductLocation,
    ProductVariant,
)


@dataclass(frozen=True)
class EffectiveShelfLifePolicy:
    """Read-only V1 explanation of the exact product/location shelf-life rule."""

    location_id: int
    product_variant_id: int
    minimum_remaining_shelf_life_days: int
    requirement_applies: bool
    source: str


class InventoryStockPolicyReadNotFound(LookupError):
    """The requested warehouse/product assignment is outside the tenant read scope."""


async def read_effective_shelf_life_policy(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    product_variant_id: int,
) -> EffectiveShelfLifePolicy:
    """Return the exact policy consumed by sellability, without creating a write authority.

    Checkpoint 6 freezes V1 shelf-life management as read-only explainability: there is
    no dedicated canonical shelf-life write capability or write contract. Missing or
    inactive exact policy rows therefore mean an effective requirement of zero days,
    matching the existing sellability coalesce. This helper never evaluates batch
    sellability; `domains.inventory_rules.batch_sellability_predicate` remains that
    single authority.
    """

    warehouse_id = await db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == int(company_id),
            InventoryLocation.id == int(location_id),
            InventoryLocation.location_type == "WAREHOUSE",
            InventoryLocation.is_active.is_(True),
        )
    )
    if warehouse_id is None:
        raise InventoryStockPolicyReadNotFound

    assignment_id = await db.scalar(
        select(ProductLocation.id)
        .join(
            ProductVariant,
            and_(
                ProductVariant.company_id == ProductLocation.company_id,
                ProductVariant.id == ProductLocation.product_variant_id,
            ),
        )
        .where(
            ProductLocation.company_id == int(company_id),
            ProductLocation.location_id == int(location_id),
            ProductLocation.product_variant_id == int(product_variant_id),
            ProductVariant.company_id == int(company_id),
        )
    )
    if assignment_id is None:
        raise InventoryStockPolicyReadNotFound

    policy = (
        await db.execute(
            select(
                InventoryStockPolicy.id,
                InventoryStockPolicy.minimum_remaining_shelf_life_days,
            ).where(
                InventoryStockPolicy.company_id == int(company_id),
                InventoryStockPolicy.location_id == int(location_id),
                InventoryStockPolicy.product_variant_id == int(product_variant_id),
                InventoryStockPolicy.is_active.is_(True),
            )
        )
    ).one_or_none()

    minimum_days = (
        int(policy.minimum_remaining_shelf_life_days or 0)
        if policy is not None
        else 0
    )
    if minimum_days < 0:
        raise RuntimeError("Inventory shelf-life policy cannot be negative.")

    return EffectiveShelfLifePolicy(
        location_id=int(location_id),
        product_variant_id=int(product_variant_id),
        minimum_remaining_shelf_life_days=minimum_days,
        requirement_applies=minimum_days > 0,
        source="EXACT_ACTIVE_POLICY" if policy is not None else "NO_ACTIVE_POLICY",
    )
