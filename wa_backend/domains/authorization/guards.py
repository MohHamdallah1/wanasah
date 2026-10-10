"""Workflow-facing authorization guards built on the canonical access engine."""

from fastapi import HTTPException
from sqlalchemy import or_, select

from models import InventoryMovement, InventoryTransferHeader, StocktakeSession

from .capabilities import PERMISSIONS
from .inventory_access import InventoryAccess


async def inventory_actor(current_driver, db):
    access = InventoryAccess(db, current_driver)
    await access.require(PERMISSIONS, any_location=True)
    return current_driver


async def require_stocktake(access, code, session_id):
    location_id = await access.db.scalar(select(StocktakeSession.location_id).where(
        StocktakeSession.company_id == access.company_id, StocktakeSession.id == session_id))
    if location_id is None:
        raise HTTPException(404, 'جلسة الجرد غير موجودة أو غير متاحة.')
    await access.require(code, location_id)


def transfer_filter(access, code='transfer.read'):
    return or_(access.allows(code, InventoryTransferHeader.source_location_id),
               access.allows(code, InventoryTransferHeader.destination_location_id))


async def require_transfer(access, code, header_id, side=None):
    # Only server-stored endpoints determine the authority, including replay.
    row = (await access.db.execute(select(
        InventoryTransferHeader.source_location_id, InventoryTransferHeader.destination_location_id,
    ).where(InventoryTransferHeader.company_id == access.company_id,
            InventoryTransferHeader.id == header_id))).one_or_none()
    if row is None:
        raise HTTPException(404, 'الحوالة غير موجودة أو غير متاحة.')
    if side is not None:
        await access.require(code, row[0 if side == 'source' else 1])
    elif not await access.db.scalar(select(or_(access.allows(code, row[0]), access.allows(code, row[1])))):
        raise HTTPException(403, 'لا تملك صلاحية عرض هذه الحوالة.')


async def require_inbound_adjustment(access, entry_id):
    location_id = await access.db.scalar(select(InventoryMovement.destination_location_id).where(
        InventoryMovement.company_id == access.company_id, InventoryMovement.id == entry_id,
        InventoryMovement.reference_type == 'INBOUND_SUPPLIER'))
    if location_id is None:
        raise HTTPException(404, 'حركة التوريد غير موجودة أو غير متاحة.')
    await access.require('ledger.adjust', location_id)


__all__ = [
    "inventory_actor",
    "require_inbound_adjustment",
    "require_stocktake",
    "require_transfer",
    "transfer_filter",
]
