"""Public Supplier selection authority for business documents in other domains.

Holds a shared row lock until the caller commits, serializing selection against
rename/deactivation without serializing independent receipts from one supplier.
Replay must be reconciled before calling: completed evidence survives deactivation.
"""
from inventory_access import InventoryAccess
from .contracts import SupplierSnapshot
from .errors import SupplierError, fail


async def require_supplier_permission(db, actor, permission="supplier.read"):
    if not actor.company_id or actor.company_id <= 0 or not actor.is_active:
        fail(403, "SUPPLIER_COMPANY_REQUIRED", "An active company session is required.")
    try:
        await InventoryAccess(db, actor).require(permission)
    except Exception as exc:
        from fastapi import HTTPException
        if isinstance(exc, HTTPException) and exc.status_code == 403:
            fail(403, "SUPPLIER_PERMISSION_DENIED", "Supplier permission is required.", permission=permission)
        raise


async def select_active_supplier(db, *, actor, supplier_id):
    await require_supplier_permission(db, actor)
    from sqlalchemy import select
    from .models import Supplier
    row = await db.scalar(select(Supplier).where(
        Supplier.company_id == actor.company_id, Supplier.id == supplier_id,
    ).with_for_update(read=True).execution_options(populate_existing=True))
    if row is None:
        fail(404, "SUPPLIER_NOT_FOUND", "Supplier is unavailable in this company.")
    if not row.is_active:
        fail(409, "SUPPLIER_INACTIVE", "Select an active supplier for this operation.")
    return SupplierSnapshot(row.id, row.name, row.code)

async def select_supplier_snapshot(db, *, actor, supplier_id):
    """Resolve a historical Supplier identity for returns, even when inactive.

    Inactive suppliers cannot be selected for new inbound receipts, but stock
    already received from them must remain returnable to that same identity.
    """
    await require_supplier_permission(db, actor)
    from sqlalchemy import select
    from .models import Supplier
    row = await db.scalar(select(Supplier).where(
        Supplier.company_id == actor.company_id, Supplier.id == supplier_id,
    ).with_for_update(read=True).execution_options(populate_existing=True))
    if row is None:
        fail(404, "SUPPLIER_NOT_FOUND", "Supplier is unavailable in this company.")
    return SupplierSnapshot(row.id, row.name, row.code)
