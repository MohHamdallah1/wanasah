from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import Driver, InventoryLocation, InventoryLock
from schemas import WarehouseStatusResponse


router = APIRouter()


@router.get("/warehouse/status", response_model=WarehouseStatusResponse, status_code=200)
async def get_warehouse_status(
    location_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await access.require(('location.read', 'dispatch.read'), location_id)

    stmt_location = select(InventoryLocation.id).filter_by(
        id=location_id,
        company_id=current_admin.company_id,
        location_type='WAREHOUSE',
        is_active=True
    )
    location_exists = (await db.execute(stmt_location)).scalar_one_or_none()

    if location_exists is None:
        raise HTTPException(
            status_code=404,
            detail="المستودع غير موجود أو لا يتبع شركتك."
        )

    stmt_lock = select(InventoryLock.id).filter(
        InventoryLock.company_id == current_admin.company_id,
        InventoryLock.location_id == location_id,
        InventoryLock.product_variant_id.is_(None),
        InventoryLock.batch_id.is_(None),
        InventoryLock.released_at.is_(None)
    ).limit(1)

    active_lock = (await db.execute(stmt_lock)).scalar_one_or_none()

    return {
        "status": "AUDIT_LOCK" if active_lock is not None else "ACTIVE"
    }


