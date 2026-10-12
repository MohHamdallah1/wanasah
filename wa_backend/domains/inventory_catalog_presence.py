from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from inventory_access import InventoryAccess
from models import Driver, InventoryBalance, InventoryLocation


class InventoryCatalogPresenceForbidden(RuntimeError):
    """The caller cannot read every selected physical warehouse."""


def _resolve_catalog_presence_access(
    db: AsyncSession,
    *,
    access: BackofficeCapabilityAccess | None,
    actor: Driver | None,
    company_id: int | None,
):
    if access is not None:
        if actor is not None:
            raise ValueError("Use canonical access or a legacy actor, not both.")
        tenant_company_id = int(access.company_id)
        if company_id is not None and int(company_id) != tenant_company_id:
            raise ValueError("Canonical access company does not match the requested tenant.")
        return tenant_company_id, access

    if actor is None or company_id is None:
        raise ValueError("Canonical access or the legacy actor/company pair is required.")
    return int(company_id), InventoryAccess(db, actor)


async def variant_ids_present_in_all_warehouses(
    db: AsyncSession,
    *,
    warehouse_ids: Sequence[int],
    access: BackofficeCapabilityAccess | None = None,
    actor: Driver | None = None,
    company_id: int | None = None,
):
    """Return a permission-scoped set query for physical warehouse presence.

    This is a read contract for Catalog surfaces. Inventory remains authoritative
    for locations, balances and exact-location access. The returned query matches
    variants with positive physical on-hand in every selected warehouse; it does
    not expose quantities, hidden locations, or Inventory mutation authority.

    Canonical Backoffice callers pass ``access``. The legacy actor/company pair is
    retained temporarily for callers that have not completed their auth cutover.
    """
    normalized_ids = tuple(sorted({int(value) for value in warehouse_ids}))
    if not normalized_ids:
        raise ValueError("warehouse_ids cannot be empty")

    tenant_company_id, permission_access = _resolve_catalog_presence_access(
        db,
        access=access,
        actor=actor,
        company_id=company_id,
    )
    readable_ids = set(
        int(value)
        for value in (
            await db.scalars(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == tenant_company_id,
                    InventoryLocation.id.in_(normalized_ids),
                    InventoryLocation.location_type == "WAREHOUSE",
                    InventoryLocation.is_active.is_(True),
                    permission_access.location_filter(
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
            InventoryBalance.company_id == tenant_company_id,
            InventoryBalance.location_id.in_(normalized_ids),
            InventoryBalance.on_hand_quantity > 0,
            InventoryLocation.is_active.is_(True),
            InventoryLocation.location_type == "WAREHOUSE",
            permission_access.location_filter(
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
