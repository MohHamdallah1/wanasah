from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models import InventoryLocation, Vehicle

from .repository import create_vehicle_custody, lock_canonical_custody


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


__all__ = ["create_custody_for_vehicle", "lock_vehicle_custody"]
