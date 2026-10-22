from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from database import get_db
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from models import InventoryLocation
from schemas import WarehouseStatusResponse

from ._shared import _active_full_warehouse_audit_lock


router = APIRouter()


async def _require_status_access(
    access: BackofficeCapabilityAccess,
    location_id: int,
) -> None:
    try:
        await access.require(('location.read', 'dispatch.read'), location_id)
    except BackofficeCapabilityAccessRejected:
        exists = await access.db.scalar(
            select(InventoryLocation.id).where(
                InventoryLocation.company_id == access.company_id,
                InventoryLocation.id == location_id,
            )
        )
        if exists is None:
            raise HTTPException(404, 'الموقع غير موجود أو غير متاح.') from None
        raise HTTPException(
            403,
            'لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.',
        ) from None


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

    active_lock = await _active_full_warehouse_audit_lock(
        db,
        company_id=int(access.company_id),
        location_id=location_id,
    )

    if active_lock is None:
        return {
            "status": "ACTIVE",
            "stocktake_session_id": None,
            "stocktake_reference": None,
            "stocktake_status": None,
        }

    return {
        "status": "AUDIT_LOCK",
        "stocktake_session_id": active_lock.stocktake_session_id,
        "stocktake_reference": active_lock.stocktake_reference,
        "stocktake_status": active_lock.stocktake_status,
    }

