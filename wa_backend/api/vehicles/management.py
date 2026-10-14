from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.vehicles import (
    CreateVehicleCommand,
    UpdateVehicleCommand,
    VehicleError,
    create_vehicle,
    update_vehicle,
)
from models import Driver

from .schemas import VehicleCreateRequest, VehicleResponse, VehicleUpdateRequest


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


@router.post("", response_model=VehicleResponse, status_code=201)
async def create_vehicle_endpoint(
    payload: VehicleCreateRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_manage),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    try:
        return await create_vehicle(
            db,
            company_id=access.company_id,
            actor_id=int(legacy_actor.id),
            command=CreateVehicleCommand(
                request_id=str(payload.request_id),
                plate_number=payload.plate_number,
                vehicle_type=payload.vehicle_type,
                current_mileage=payload.current_mileage,
                next_oil_change=payload.next_oil_change,
                license_expiry_date=payload.license_expiry_date,
                maintenance_status=payload.maintenance_status,
            ),
        )
    except VehicleError as exc:
        raise _http_error(exc) from None


@router.patch("/{vehicle_id}", response_model=VehicleResponse, status_code=200)
async def update_vehicle_endpoint(
    vehicle_id: int,
    payload: VehicleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_manage),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    if vehicle_id <= 0:
        raise _not_found()
    fields = payload.model_dump(
        exclude={"request_id", "expected_version"},
        exclude_unset=True,
    )
    try:
        return await update_vehicle(
            db,
            company_id=access.company_id,
            actor_id=int(legacy_actor.id),
            vehicle_id=vehicle_id,
            command=UpdateVehicleCommand(
                request_id=str(payload.request_id),
                expected_version=payload.expected_version,
                fields=fields,
            ),
        )
    except VehicleError as exc:
        raise _http_error(exc) from None


__all__ = ["router"]
