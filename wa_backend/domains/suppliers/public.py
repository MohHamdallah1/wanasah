"""Public Supplier selection authority for business documents in other domains.

Holds a shared row lock until the caller commits, serializing selection against
rename/deactivation without serializing independent receipts from one supplier.
Replay must be reconciled before calling: completed evidence survives deactivation.
"""
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from .contracts import SupplierSnapshot
from .errors import SupplierError, fail


async def require_supplier_permission(
    access: BackofficeCapabilityAccess,
    permission="supplier.read",
):
    try:
        await access.require(permission)
    except BackofficeCapabilityAccessRejected:
        fail(
            403,
            "SUPPLIER_PERMISSION_DENIED",
            "Supplier permission is required.",
            permission=permission,
        )


async def select_active_supplier(
    db,
    *,
    access: BackofficeCapabilityAccess,
    supplier_id,
):
    await require_supplier_permission(access)
    from sqlalchemy import select
    from .models import Supplier
    row = await db.scalar(select(Supplier).where(
        Supplier.company_id == access.company_id, Supplier.id == supplier_id,
    ).with_for_update(read=True).execution_options(populate_existing=True))
    if row is None:
        fail(404, "SUPPLIER_NOT_FOUND", "Supplier is unavailable in this company.")
    if not row.is_active:
        fail(409, "SUPPLIER_INACTIVE", "Select an active supplier for this operation.")
    return SupplierSnapshot(row.id, row.name, row.code)


async def select_supplier_snapshot(
    db,
    *,
    access: BackofficeCapabilityAccess,
    supplier_id,
):
    """Resolve a historical Supplier identity for returns, even when inactive.

    Inactive suppliers cannot be selected for new inbound receipts, but stock
    already received from them must remain returnable to that same identity.
    """
    await require_supplier_permission(access)
    from sqlalchemy import select
    from .models import Supplier
    row = await db.scalar(select(Supplier).where(
        Supplier.company_id == access.company_id, Supplier.id == supplier_id,
    ).with_for_update(read=True).execution_options(populate_existing=True))
    if row is None:
        fail(404, "SUPPLIER_NOT_FOUND", "Supplier is unavailable in this company.")
    return SupplierSnapshot(row.id, row.name, row.code)
