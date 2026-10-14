from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.vehicles import (
    VehicleError,
    VehicleLifecycleCommand,
    deactivate_vehicle,
    reactivate_vehicle,
)
from models import Driver

from .schemas import VehicleLifecycleRequest


router = APIRouter()
_vehicle_manage = require_backoffice_capability("vehicle.manage")


def _http_error(exc: VehicleError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message, "context": exc.context},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "VEHICLE_NOT_FOUND",
            "message": "Vehicle was not found.",
            "context": {},
        },
    )


@router.post("/{vehicle_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_vehicle_endpoint(
    vehicle_id: int,
    payload: VehicleLifecycleRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_manage),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
) -> Response:
    if vehicle_id <= 0:
        raise _not_found()
    try:
        await deactivate_vehicle(
            db,
            company_id=access.company_id,
            actor_id=int(legacy_actor.id),
            vehicle_id=vehicle_id,
            command=VehicleLifecycleCommand(
                request_id=str(payload.request_id),
                expected_version=payload.expected_version,
            ),
        )
    except VehicleError as exc:
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{vehicle_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_vehicle_endpoint(
    vehicle_id: int,
    payload: VehicleLifecycleRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_manage),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
) -> Response:
    if vehicle_id <= 0:
        raise _not_found()
    try:
        await reactivate_vehicle(
            db,
            company_id=access.company_id,
            actor_id=int(legacy_actor.id),
            vehicle_id=vehicle_id,
            command=VehicleLifecycleCommand(
                request_id=str(payload.request_id),
                expected_version=payload.expected_version,
            ),
        )
    except VehicleError as exc:
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
