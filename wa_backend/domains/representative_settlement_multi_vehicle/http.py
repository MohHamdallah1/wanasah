"""Vehicle-specific transport. Schema gate precedes all new writer imports."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError

from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.pricing.core import PricingError
from services import InventoryMutationError

from .activation import require_m04_schema
from .contracts import CustodyRejected, VehicleCountCommand

logger = logging.getLogger("wanasah_logger")


async def command_response(db, operation):
    try:
        await require_m04_schema(db)
        return await operation()
    except CustodyRejected as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "context": exc.context}) from None
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={
            "code": getattr(exc, "code", "CUSTODY_INVENTORY_CONFLICT"), "context": {},
        }) from None
    except PricingError as exc:
        await db.rollback()
        if 400 <= exc.status_code < 500:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from None
        logger.exception("M04 pricing authority failed")
        raise HTTPException(status_code=500, detail={"code": "CUSTODY_COMMAND_FAILED"}) from None
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "CUSTODY_CONCURRENT_CONFLICT"}) from None
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        logger.exception("M04 vehicle custody command failed")
        raise HTTPException(status_code=500, detail={"code": "CUSTODY_COMMAND_FAILED"}) from None


def build_command_router(*, variance_writer):
    router = APIRouter()
    execute = require_backoffice_capability("settlement.execute")

    @router.post("/admin/sessions/{session_id}/inventory-custody/vehicles/{vehicle_id}/count")
    async def count_vehicle(session_id: int, vehicle_id: int, payload: VehicleCountCommand,
                            db=Depends(get_db), access=Depends(execute),
                            actor=Depends(get_current_backoffice_legacy_driver)):
        async def run():
            from .application import record_vehicle_count
            from .inventory_adapter import CanonicalInventoryCustody
            return await record_vehicle_count(
                db, access=access, actor_id=int(actor.id), session_id=session_id, vehicle_id=vehicle_id,
                command=payload, inventory=CanonicalInventoryCustody(variance_writer),
            )
        return await command_response(db, run)

    from .variance_http import build_variance_router
    router.include_router(build_variance_router())
    return router
