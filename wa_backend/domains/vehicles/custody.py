from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryLocation, Vehicle

from .contracts import VehicleError
from .repository import (
    create_vehicle_custody,
    lock_canonical_custody,
    read_canonical_custody_location_id,
)


async def create_custody_for_vehicle(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle: Vehicle,
) -> InventoryLocation:
    location = create_vehicle_custody(
        db,
        company_id=company_id,
        vehicle=vehicle,
    )
    await db.flush()
    return location


async def lock_vehicle_custody(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
) -> InventoryLocation:
    return await lock_canonical_custody(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
    )


async def resolve_vehicle_custody_location_id(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    require_active: bool = True,
    expected_location_id: int | None = None,
) -> int:
    """Read the strict 1:1 mapping; callers retain their existing lock hierarchy."""
    location_id = await read_canonical_custody_location_id(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
        require_active=require_active,
    )
    if expected_location_id is not None and location_id != expected_location_id:
        raise VehicleError(
            "VEHICLE_CUSTODY_LOCATION_INCONSISTENT",
            "موقع عهدة السيارة تغير أثناء العملية؛ أعد المحاولة بعد تصحيح العهدة.",
            status_code=409,
        )
    return location_id


__all__ = [
    "create_custody_for_vehicle",
    "lock_vehicle_custody",
    "resolve_vehicle_custody_location_id",
]
