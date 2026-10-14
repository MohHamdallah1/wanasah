from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import require_backoffice_capability
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.vehicles import VehicleError, get_vehicle, list_vehicles, vehicle_payload

from .schemas import VehicleCursorPage, VehicleResponse


router = APIRouter()
_vehicle_read = require_backoffice_capability("vehicle.read")


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


@router.get("", response_model=VehicleCursorPage, status_code=200)
async def read_vehicles(
    search: str | None = Query(default=None, min_length=2, max_length=100),
    active: bool | None = Query(default=None),
    maintenance_status: Literal["Active", "In_Maintenance"] | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_read),
):
    try:
        page = await list_vehicles(
            db,
            company_id=access.company_id,
            search=search,
            active=active,
            maintenance_status=maintenance_status,
            cursor=cursor,
            limit=limit,
            scope_tag="company-v1",
        )
    except VehicleError as exc:
        raise _http_error(exc) from None
    return {
        "items": [vehicle_payload(item) for item in page.items],
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }


@router.get("/{vehicle_id}", response_model=VehicleResponse, status_code=200)
async def read_vehicle_detail(
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_read),
):
    if vehicle_id <= 0:
        raise _not_found()
    try:
        return vehicle_payload(
            await get_vehicle(
                db,
                company_id=access.company_id,
                vehicle_id=vehicle_id,
            )
        )
    except VehicleError as exc:
        raise _http_error(exc) from None


__all__ = ["router"]
