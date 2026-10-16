import asyncio
import logging
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)
from database import get_db
from domains.authorization import require_inbound_adjustment
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.ledger import (
    LedgerAdjustmentError,
    apply_inbound_adjustment,
    load_inbound_adjustment_state,
)
from models import Driver, SystemAuditLog
from quantity import canonical_quantity
from schemas import AdjustWarehouseEntryRequest, MessageResponse
from services import InventoryMutationError


logger = logging.getLogger("wanasah_logger")
router = APIRouter()


class LedgerAdjustmentStateResponse(BaseModel):
    entry_id: int = Field(..., gt=0)
    reference: str = Field(..., min_length=1, max_length=100)
    product_variant_id: int = Field(..., gt=0)
    batch_id: Optional[int] = Field(None, gt=0)
    warehouse_location_id: int = Field(..., gt=0)
    current_total_quantity: str
    base_uom_id: int = Field(..., gt=0)
    base_uom_code: str = Field(..., min_length=1, max_length=20)


async def _require_inbound_adjustment_access(
    access: BackofficeCapabilityAccess,
    entry_id: int,
) -> None:
    try:
        await require_inbound_adjustment(access, entry_id)
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "LEDGER_ADJUST_FORBIDDEN",
                "message": "Ledger adjustment is not allowed at the authoritative inbound warehouse.",
                "context": {},
            },
        ) from None


def _http_error(exc: LedgerAdjustmentError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get(
    "/warehouse/ledger/{entry_id}/adjustment-state",
    response_model=LedgerAdjustmentStateResponse,
    status_code=200,
)
async def get_warehouse_entry_adjustment_state(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(
        get_current_backoffice_capability_access
    ),
):
    await _require_inbound_adjustment_access(access, entry_id)
    try:
        state = await load_inbound_adjustment_state(
            db,
            company_id=access.company_id,
            entry_id=entry_id,
            lock=False,
        )
        return state.response()
    except LedgerAdjustmentError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/warehouse/ledger/{entry_id}/adjust",
    response_model=MessageResponse,
    status_code=200,
)
async def adjust_warehouse_entry(
    entry_id: int,
    payload: AdjustWarehouseEntryRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(
        get_current_backoffice_capability_access
    ),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    await _require_inbound_adjustment_access(access, entry_id)
    company_id = access.company_id

    password_ok = await asyncio.to_thread(
        bcrypt.checkpw,
        payload.password.encode("utf-8"),
        legacy_actor.password_hash.encode("utf-8"),
    )
    if not password_ok:
        try:
            db.add(
                SystemAuditLog(
                    company_id=company_id,
                    admin_id=legacy_actor.id,
                    target_id=f"InventoryMovement_{entry_id}",
                    action_type="UNAUTHORIZED_ADJUSTMENT",
                    old_value="Wrong Password",
                    new_value="Rejected",
                )
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error(
                "Failed to audit rejected Ledger adjustment: %s",
                exc,
                exc_info=True,
            )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "LEDGER_ADJUSTMENT_PASSWORD_INVALID",
                "message": "The confirmation password is incorrect.",
                "context": {},
            },
        )

    try:
        state, delta, correction_id = await apply_inbound_adjustment(
            db,
            company_id=company_id,
            entry_id=entry_id,
            actor_id=int(legacy_actor.id),
            new_total_quantity=payload.new_total_quantity,
            uom_id=payload.uom_id,
            notes=payload.notes,
        )
        await db.commit()

        if correction_id is None:
            return {"message": "No correction was needed; the authoritative inbound total already matches."}
        return {
            "message": (
                "Recorded an append-only inbound correction successfully. "
                f"Delta: {canonical_quantity(delta)} {state.base_uom_code}."
            )
        }
    except LedgerAdjustmentError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LEDGER_ADJUSTMENT_INVENTORY_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning(
            "Concurrent Ledger adjustment conflict: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LEDGER_ADJUSTMENT_CONCURRENT_CONFLICT",
                "message": "A concurrent correction conflict occurred; no partial correction was saved.",
                "context": {},
            },
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("Ledger inbound adjustment failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "LEDGER_ADJUSTMENT_FAILED",
                "message": "Could not process the inbound correction.",
                "context": {},
            },
        ) from exc
