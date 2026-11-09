"""HTTP adapter for the atomic Dispatch shortages group command (#849)."""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Driver
from ws_manager import dispatch_manager
from services import OperationIdempotencyError
from domains.dispatch_shortages_group import (
    GroupShortageMutation, ShortageGroupRejected, replace_shortage_group,
)
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected,
)
from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver

router = APIRouter()
logger = logging.getLogger("wanasah_logger")
_shortage_read = require_backoffice_capability("shortage.read")


@router.put("/dispatch/shortages/group", status_code=200)
async def replace_shortages_group(
    payload: GroupShortageMutation,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_shortage_read),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    """Thin transport adapter: action-specific capability gates and one domain command."""
    # Reading the group never implies authority to cancel or create shortages.
    try:
        await access.require("shortage.cancel")
        if payload.items:
            await access.require("shortage.create")
    except BackofficeCapabilityAccessRejected:
        await db.rollback()
        raise HTTPException(status_code=403, detail={
            "code": "SHORTAGE_GROUP_PERMISSION_DENIED",
            "message": "لا تملك الصلاحيات المطلوبة لتعديل هذه النواقص.",
        }) from None

    try:
        result, mutated = await replace_shortage_group(
            db, company_id=access.company_id, actor_id=int(legacy_actor.id),
            command=payload,
        )
        if mutated:
            asyncio.create_task(dispatch_manager.broadcast(
                {
                    "event": "SHORTAGE_DELETED" if not payload.items else "SHORTAGE_ADDED",
                    "message": result["message"],
                },
                company_id=access.company_id,
            ))
        return result
    except ShortageGroupRejected as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail={
            "code": exc.code, "message": exc.message,
        }) from exc
    except OperationIdempotencyError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={
            "code": exc.code, "message": str(exc),
        }) from exc
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("Atomic shortage group database conflict", exc_info=True)
        raise HTTPException(status_code=409, detail={
            "code": "SHORTAGE_GROUP_CONCURRENT_CONFLICT",
            "message": "حصل تعارض متزامن، حدّث القائمة وأعد المحاولة.",
        }) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("Atomic shortage group failed")
        raise HTTPException(status_code=500, detail={
            "code": "SHORTAGE_GROUP_FAILED",
            "message": "تعذر حفظ مجموعة النواقص.",
        }) from exc
