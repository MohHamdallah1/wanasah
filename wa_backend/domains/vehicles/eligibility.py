from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Vehicle

from .contracts import CURRENT_ROUTE_STATUSES


OPERATIONAL_MAINTENANCE_STATUS = "Active"


def vehicle_operational_predicate(model=Vehicle):
    """SQL predicate for Vehicles eligible for new/live operational use."""
    return and_(
        model.is_active.is_(True),
        model.maintenance_status == OPERATIONAL_MAINTENANCE_STATUS,
    )


def vehicle_is_operational(vehicle: Vehicle | None) -> bool:
    """Return whether a loaded Vehicle is eligible for operational use."""
    return bool(
        vehicle is not None
        and vehicle.is_active
        and vehicle.maintenance_status == OPERATIONAL_MAINTENANCE_STATUS
    )


def route_requires_operational_vehicle(
    *,
    target_status: str,
    vehicle_changed: bool = False,
    inventory_mutation: bool = False,
) -> bool:
    """Whether a Dispatch route mutation is entering/altering operational Vehicle use."""
    return bool(
        vehicle_changed
        or target_status in CURRENT_ROUTE_STATUSES
        or inventory_mutation
    )


async def read_vehicle_operational_state(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
) -> Vehicle | None:
    """Plain tenant-scoped state read for callers already serialized by another guard.

    This intentionally does not take a Vehicle row lock. Callers such as Driver
    session start and Dispatch route-load adjustment hold the VEHICLE inventory
    location guard first, preserving the frozen lock hierarchy and avoiding a
    Route -> Vehicle row-lock inversion.
    """
    return await db.scalar(
        select(Vehicle).where(
            Vehicle.company_id == int(company_id),
            Vehicle.id == int(vehicle_id),
        )
    )


__all__ = [
    "OPERATIONAL_MAINTENANCE_STATUS",
    "read_vehicle_operational_state",
    "route_requires_operational_vehicle",
    "vehicle_is_operational",
    "vehicle_operational_predicate",
]
