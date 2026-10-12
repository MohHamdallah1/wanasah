from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from models import InventoryLocation, InventoryLock
from schemas import WarehouseStatusResponse


router = APIRouter()


async def _require_status_access(
    access: BackofficeCapabilityAccess,
    location_id: int,
) -> None:
    exists = await access.db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == access.company_id,
            InventoryLocation.id == location_id,
        )
    )
    if exists is None:
        raise HTTPException(404, 'الموقع غير موجود أو غير متاح.')
    allowed = await access.db.scalar(
        select(access.allows(('location.read', 'dispatch.read'), location_id))
    )
    if not bool(allowed):
        raise HTTPException(403, 'لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.')


# =================================================================================
# 5. جلب حالة قفل المستودع
# =================================================================================
# جلب حالة قفل مستودع محدد اعتماداً على الأقفال الفعلية للمحرك الموحد.
@router.get("/warehouse/status", response_model=WarehouseStatusResponse, status_code=200)
async def get_warehouse_status(
    location_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _require_status_access(access, location_id)

    stmt_location = select(InventoryLocation.id).filter_by(
        id=location_id,
        company_id=access.company_id,
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
        InventoryLock.company_id == access.company_id,
        InventoryLock.location_id == location_id,
        InventoryLock.product_variant_id.is_(None),
        InventoryLock.batch_id.is_(None),
        InventoryLock.released_at.is_(None)
    ).limit(1)

    active_lock = (await db.execute(stmt_lock)).scalar_one_or_none()

    return {
        "status": "AUDIT_LOCK" if active_lock is not None else "ACTIVE"
    }

