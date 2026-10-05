from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_access import InventoryAccess
from models import Driver, InventoryBalance, InventoryLocation


class InventoryCatalogPresenceForbidden(RuntimeError):
    """The caller cannot read every selected physical warehouse."""


async def variant_ids_present_in_all_warehouses(
    db: AsyncSession,
    *,
    actor: Driver,
    company_id: int,
    warehouse_ids: Sequence[int],
):
    """Return a permission-scoped set query for physical warehouse presence.

    This is a read contract for Catalog surfaces. Inventory remains authoritative
    for locations, balances and exact-location access. The returned query matches
    variants with positive physical on-hand in every selected warehouse; it does
    not expose quantities, hidden locations, or Inventory mutation authority.
    """
    normalized_ids = tuple(sorted({int(value) for value in warehouse_ids}))
    if not normalized_ids:
        raise ValueError("warehouse_ids cannot be empty")

    access = InventoryAccess(db, actor)
    readable_ids = set(
        int(value)
        for value in (
            await db.scalars(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.id.in_(normalized_ids),
                    InventoryLocation.location_type == "WAREHOUSE",
                    InventoryLocation.is_active.is_(True),
                    access.location_filter(
                        "inventory.read",
                        InventoryLocation.id,
                    ),
                )
            )
        ).all()
    )
    if readable_ids != set(normalized_ids):
        raise InventoryCatalogPresenceForbidden

    return (
        select(InventoryBalance.product_variant_id)
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
            InventoryBalance.location_id.in_(normalized_ids),
            InventoryBalance.on_hand_quantity > 0,
            InventoryLocation.is_active.is_(True),
            InventoryLocation.location_type == "WAREHOUSE",
            access.location_filter(
                "inventory.read",
                InventoryLocation.id,
            ),
        )
        .group_by(InventoryBalance.product_variant_id)
        .having(
            func.count(func.distinct(InventoryBalance.location_id))
            == len(normalized_ids)
        )
    )
