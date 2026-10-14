"""Canonical Backoffice authorization helpers for Dispatch route and vehicle scope."""

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import aliased

from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from models import DispatchRoute, InventoryLocation, Vehicle


_AUTHORIZATION_REJECTION_DETAIL = "Authorization denied."
_VEHICLE_NOT_AVAILABLE_DETAIL = "موقع السيارة غير موجود أو غير متاح."


def _authorization_rejected() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_AUTHORIZATION_REJECTION_DETAIL,
    )


def _vehicle_not_available() -> HTTPException:
    return HTTPException(status_code=404, detail=_VEHICLE_NOT_AVAILABLE_DETAIL)


async def require_any_location(
    access: BackofficeCapabilityAccess,
    code: str,
) -> None:
    """Require at least one authorized location without weakening canonical Owner rules."""
    try:
        await access.require(code, any_location=True)
    except BackofficeCapabilityAccessRejected:
        raise _authorization_rejected() from None


async def require_location(
    access: BackofficeCapabilityAccess,
    code: str,
    location_id: int,
) -> None:
    """Require a concrete tenant-owned location with opaque authorization failure."""
    try:
        await access.require(code, int(location_id))
    except (BackofficeCapabilityAccessRejected, TypeError, ValueError):
        raise _authorization_rejected() from None


def _strict_vehicle_custody_count(company_id, vehicle_column):
    history = aliased(InventoryLocation)
    return (
        select(func.count(history.id))
        .where(
            history.company_id == company_id,
            history.vehicle_id == vehicle_column,
            history.location_type == "VEHICLE",
        )
        .correlate_except(history)
        .scalar_subquery()
    )


def vehicle_filter(
    access: BackofficeCapabilityAccess,
    code: str,
    vehicle_column=Vehicle.id,
):
    """Filter by strict active custody plus the existing Dispatch location capability."""
    return (
        select(1)
        .select_from(InventoryLocation)
        .where(
            InventoryLocation.company_id == access.company_id,
            InventoryLocation.vehicle_id == vehicle_column,
            InventoryLocation.location_type == "VEHICLE",
            InventoryLocation.is_active.is_(True),
            _strict_vehicle_custody_count(access.company_id, vehicle_column) == 1,
            access.allows(code, InventoryLocation.id),
        )
        .exists()
    )


async def require_vehicle(
    access: BackofficeCapabilityAccess,
    code: str,
    vehicle_id: int,
) -> None:
    vehicle_exists = await access.db.scalar(
        select(Vehicle.id).where(
            Vehicle.company_id == access.company_id,
            Vehicle.id == vehicle_id,
        )
    )
    if vehicle_exists is None:
        raise _vehicle_not_available()

    location_id = await access.db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == access.company_id,
            InventoryLocation.vehicle_id == vehicle_id,
            InventoryLocation.location_type == "VEHICLE",
            InventoryLocation.is_active.is_(True),
            _strict_vehicle_custody_count(access.company_id, vehicle_id) == 1,
        )
    )
    if location_id is None:
        raise _vehicle_not_available()

    await require_location(access, code, int(location_id))


def route_filter(access: BackofficeCapabilityAccess, code: str):
    """Filter routes by tenant-valid source warehouse and vehicle scope."""
    source_location_filter = (
        select(1)
        .select_from(InventoryLocation)
        .where(
            InventoryLocation.company_id == access.company_id,
            InventoryLocation.id == DispatchRoute.source_location_id,
            InventoryLocation.location_type == "WAREHOUSE",
            InventoryLocation.is_active.is_(True),
            access.allows(code, InventoryLocation.id),
        )
        .exists()
    )
    return and_(
        source_location_filter,
        vehicle_filter(access, code, DispatchRoute.vehicle_id),
    )


async def require_route(
    access: BackofficeCapabilityAccess,
    code: str,
    route_id: int,
) -> None:
    row = (
        await access.db.execute(
            select(
                DispatchRoute.source_location_id,
                DispatchRoute.vehicle_id,
            ).where(
                DispatchRoute.company_id == access.company_id,
                DispatchRoute.id == route_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="خط السير غير موجود.")

    source_location_id, vehicle_id = row
    if source_location_id is None or vehicle_id is None:
        raise _authorization_rejected()

    valid_source_location_id = await access.db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == access.company_id,
            InventoryLocation.id == int(source_location_id),
            InventoryLocation.location_type == "WAREHOUSE",
            InventoryLocation.is_active.is_(True),
        )
    )
    if valid_source_location_id is None:
        raise _authorization_rejected()

    await require_location(access, code, int(source_location_id))
    await require_vehicle(access, code, int(vehicle_id))


__all__ = [
    "require_any_location",
    "require_location",
    "require_route",
    "require_vehicle",
    "route_filter",
    "vehicle_filter",
]
