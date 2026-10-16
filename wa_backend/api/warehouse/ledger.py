import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
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
from domains.ledger import LedgerReadError, read_warehouse_ledger_page
from models import InventoryLocation
from schemas import (
    WarehouseLedgerCursorPage as BaseWarehouseLedgerCursorPage,
    WarehouseLedgerItem,
)


logger = logging.getLogger("wanasah_logger")
router = APIRouter()


class WarehouseLedgerEvidenceItem(WarehouseLedgerItem):
    reference_type: str = Field(..., min_length=1, max_length=50)
    movement_kind: str = Field(..., min_length=1, max_length=50)
    batch_id: Optional[int] = Field(None, gt=0)
    source_location_id: Optional[int] = Field(None, gt=0)
    source_location_name: Optional[str] = Field(None, max_length=200)
    destination_location_id: Optional[int] = Field(None, gt=0)
    destination_location_name: Optional[str] = Field(None, max_length=200)
    source_stock_status: Optional[str] = Field(None, max_length=30)
    destination_stock_status: Optional[str] = Field(None, max_length=30)


class WarehouseLedgerCursorPage(BaseWarehouseLedgerCursorPage):
    items: list[WarehouseLedgerEvidenceItem] = Field(..., max_length=200)


async def _require_ledger_access(
    access: BackofficeCapabilityAccess,
    *,
    location_id: int,
) -> None:
    exists = await access.db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == access.company_id,
            InventoryLocation.id == int(location_id),
            InventoryLocation.location_type == "WAREHOUSE",
        )
    )
    if exists is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "LEDGER_LOCATION_NOT_FOUND",
                "message": "The selected warehouse is unavailable.",
                "context": {},
            },
        )
    try:
        await access.require("ledger.read", int(location_id))
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "LEDGER_READ_FORBIDDEN",
                "message": "Ledger read is not allowed at the selected warehouse.",
                "context": {},
            },
        ) from None


@router.get(
    "/warehouse/ledger/cursor",
    response_model=WarehouseLedgerCursorPage,
    status_code=200,
)
async def get_warehouse_ledger_cursor(
    location_id: int = Query(..., gt=0),
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None, max_length=100),
    reference_type: Optional[str] = Query(default=None, max_length=50),
    reference_id: Optional[str] = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(
        get_current_backoffice_capability_access
    ),
):
    company_id = access.company_id
    await _require_ledger_access(access, location_id=location_id)
    try:
        return await read_warehouse_ledger_page(
            db,
            access=access,
            company_id=company_id,
            location_id=location_id,
            cursor=cursor,
            limit=limit,
            search=search,
            reference_type=reference_type,
            reference_id=reference_id,
        )
    except LedgerReadError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Ledger cursor read failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "LEDGER_READ_FAILED",
                "message": "Could not load the movement Ledger.",
                "context": {},
            },
        ) from exc
