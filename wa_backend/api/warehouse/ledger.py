import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel, Field
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
from domains.ledger.operation_read import read_operation_groups, read_operation_movements
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
    source_location_type: Optional[str] = Field(None, max_length=20)
    destination_location_id: Optional[int] = Field(None, gt=0)
    destination_location_name: Optional[str] = Field(None, max_length=200)
    destination_location_type: Optional[str] = Field(None, max_length=20)
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


# Read-only operation projection for the same authorized selected warehouse.
# These routes do not mutate or replace the canonical movement Ledger.
class LedgerOperationStocktakeHistory(BaseModel):
    session_id: int = Field(..., gt=0)
    warehouse_location_id: int = Field(..., gt=0)
    reference: str = Field(..., max_length=100)


class LedgerOperationSummary(BaseModel):
    group_key: str = Field(..., max_length=1024)
    group_kind: Literal["TRANSFER", "STOCKTAKE", "RECEIPT", "MOVEMENT"]
    operation_type: str = Field(..., max_length=50)
    reference: str = Field(..., max_length=100)
    latest_at: str = Field(..., max_length=64)
    latest_movement_id: int = Field(..., gt=0)
    source_location_name: Optional[str] = Field(None, max_length=200)
    destination_location_name: Optional[str] = Field(None, max_length=200)
    latest_actor_name: Optional[str] = Field(None, max_length=120)
    stage_types: list[str]
    movement_kinds: list[str]
    movement_count: int = Field(..., ge=1)
    product_variant_count: int = Field(..., ge=1)
    batch_count: int = Field(..., ge=0)
    expandable: bool
    count_meaning: Literal["POSTED_VARIANCE_MOVEMENTS", "AUTHORIZED_IMMUTABLE_MOVEMENTS"]
    stocktake_history: Optional[LedgerOperationStocktakeHistory] = None


class LedgerOperationPage(BaseModel):
    items: list[LedgerOperationSummary] = Field(..., max_length=200)
    next_cursor: Optional[str] = Field(None, max_length=512)
    has_more: bool
    snapshot_max_movement_id: Optional[int] = Field(None, gt=0)
    type_filter_semantics: Literal["MATCH_ANY_CHILD_SHOW_ALL_AUTHORIZED"]


class LedgerOperationMovementItem(WarehouseLedgerEvidenceItem):
    matches_filter: bool


class LedgerOperationMovementPage(BaseModel):
    group_key: str = Field(..., max_length=1024)
    items: list[LedgerOperationMovementItem] = Field(..., max_length=200)
    next_cursor: Optional[str] = Field(None, max_length=512)
    has_more: bool


def _operation_http_error(exc: LedgerReadError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get(
    "/warehouse/ledger/operations/cursor",
    response_model=LedgerOperationPage,
    status_code=200,
)
async def get_warehouse_ledger_operations(
    location_id: int = Query(..., gt=0),
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None, max_length=100),
    reference_type: Optional[str] = Query(None, max_length=50),
    reference_id: Optional[str] = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _require_ledger_access(access, location_id=location_id)
    try:
        return await read_operation_groups(
            db, access=access, company_id=access.company_id,
            location_id=location_id, cursor=cursor, limit=limit,
            search=search, movement_type=reference_type, reference_id=reference_id,
        )
    except LedgerReadError as exc:
        raise _operation_http_error(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Ledger operation summary failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={
            "code": "LEDGER_OPERATION_READ_FAILED",
            "message": "Could not load authorized Ledger operations.", "context": {},
        }) from exc


@router.get(
    "/warehouse/ledger/operations/{group_key}/movements/cursor",
    response_model=LedgerOperationMovementPage,
    status_code=200,
)
async def get_warehouse_ledger_operation_movements(
    group_key: str = Path(..., min_length=1, max_length=1024),
    location_id: int = Query(..., gt=0),
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None, max_length=100),
    reference_type: Optional[str] = Query(None, max_length=50),
    reference_id: Optional[str] = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _require_ledger_access(access, location_id=location_id)
    try:
        return await read_operation_movements(
            db, access=access, company_id=access.company_id, location_id=location_id,
            group_token=group_key, cursor=cursor, limit=limit,
            search=search, movement_type=reference_type, reference_id=reference_id,
        )
    except LedgerReadError as exc:
        raise _operation_http_error(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Ledger operation detail failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={
            "code": "LEDGER_OPERATION_DETAIL_FAILED",
            "message": "Could not load authorized operation movements.", "context": {},
        }) from exc
