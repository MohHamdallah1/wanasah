from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.inventory_vehicle_load import (
    mutate_vehicle_load,
    vehicle_load_snapshot,
    vehicle_load_source_inventory,
    vehicle_load_warehouses,
)
from domains.vehicles import VehicleError
from models import Driver

from .load_schemas import (
    VehicleLoadMutationRequest,
    VehicleLoadMutationResponse,
    VehicleLoadSnapshotResponse,
    VehicleLoadSourcePage,
    VehicleLoadWarehousePage,
)


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


@router.get(
    "/{vehicle_id}/load",
    response_model=VehicleLoadSnapshotResponse,
    status_code=200,
)
async def read_vehicle_load(
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_read),
):
    if vehicle_id <= 0:
        raise _not_found()
    try:
        return await vehicle_load_snapshot(
            db,
            access=access,
            vehicle_id=vehicle_id,
        )
    except VehicleError as exc:
        raise _http_error(exc) from None


@router.get(
    "/{vehicle_id}/load/warehouses",
    response_model=VehicleLoadWarehousePage,
    status_code=200,
)
async def read_vehicle_load_warehouses(
    vehicle_id: int,
    direction: Literal["ADD", "UNLOAD"] = Query(...),
    search: str | None = Query(default=None, min_length=2, max_length=100),
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_read),
):
    if vehicle_id <= 0:
        raise _not_found()
    try:
        return await vehicle_load_warehouses(
            db,
            access=access,
            vehicle_id=vehicle_id,
            direction=direction,
            search=search,
            cursor=cursor,
            limit=limit,
        )
    except VehicleError as exc:
        raise _http_error(exc) from None


@router.get(
    "/{vehicle_id}/load/source-inventory",
    response_model=VehicleLoadSourcePage,
    status_code=200,
)
async def read_vehicle_load_source_inventory(
    vehicle_id: int,
    warehouse_id: int = Query(..., ge=1),
    search: str | None = Query(default=None, min_length=2, max_length=100),
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_read),
):
    if vehicle_id <= 0:
        raise _not_found()
    try:
        return await vehicle_load_source_inventory(
            db,
            access=access,
            vehicle_id=vehicle_id,
            warehouse_id=warehouse_id,
            search=search,
            cursor=cursor,
            limit=limit,
        )
    except VehicleError as exc:
        raise _http_error(exc) from None


@router.post(
    "/{vehicle_id}/load/add",
    response_model=VehicleLoadMutationResponse,
    status_code=200,
)
async def add_vehicle_load(
    vehicle_id: int,
    payload: VehicleLoadMutationRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_read),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    if vehicle_id <= 0:
        raise _not_found()
    try:
        return await mutate_vehicle_load(
            db,
            access=access,
            actor_id=int(legacy_actor.id),
            vehicle_id=vehicle_id,
            warehouse_id=payload.warehouse_id,
            direction="ADD",
            request_id=payload.request_id,
            items=[
                {
                    "product_variant_id": item.product_variant_id,
                    "quantity": item.quantity,
                    "stock_status": item.stock_status,
                }
                for item in payload.items
            ],
        )
    except VehicleError as exc:
        await db.rollback()
        raise _http_error(exc) from None


@router.post(
    "/{vehicle_id}/load/unload",
    response_model=VehicleLoadMutationResponse,
    status_code=200,
)
async def unload_vehicle_load(
    vehicle_id: int,
    payload: VehicleLoadMutationRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_vehicle_read),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    if vehicle_id <= 0:
        raise _not_found()
    try:
        return await mutate_vehicle_load(
            db,
            access=access,
            actor_id=int(legacy_actor.id),
            vehicle_id=vehicle_id,
            warehouse_id=payload.warehouse_id,
            direction="UNLOAD",
            request_id=payload.request_id,
            items=[
                {
                    "product_variant_id": item.product_variant_id,
                    "quantity": item.quantity,
                    "stock_status": item.stock_status,
                }
                for item in payload.items
            ],
        )
    except VehicleError as exc:
        await db.rollback()
        raise _http_error(exc) from None


__all__ = ["router"]
