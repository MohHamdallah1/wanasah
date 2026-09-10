"""Resolve dispatch authority from stored route endpoints, never client names."""
from fastapi import HTTPException
from sqlalchemy import select, and_, true
from models import DispatchRoute, InventoryLocation


def vehicle_filter(access, code, vehicle_column):
    if access.actor.is_admin:
        return true()
    return select(1).select_from(InventoryLocation).where(
        InventoryLocation.company_id == access.company_id,
        InventoryLocation.vehicle_id == vehicle_column,
        InventoryLocation.location_type == 'VEHICLE',
        InventoryLocation.is_active.is_(True),
        access.allows(code, InventoryLocation.id),
    ).exists()


def route_filter(access, code):
    if access.actor.is_admin:
        return true()
    return and_(access.allows(code, DispatchRoute.source_location_id),
                vehicle_filter(access, code, DispatchRoute.vehicle_id))


async def require_vehicle(access, code, vehicle_id):
    if access.actor.is_admin:
        return
    location_id = await access.db.scalar(select(InventoryLocation.id).where(
        InventoryLocation.company_id == access.company_id,
        InventoryLocation.vehicle_id == vehicle_id,
        InventoryLocation.location_type == 'VEHICLE', InventoryLocation.is_active.is_(True)))
    if location_id is None:
        raise HTTPException(404, 'موقع السيارة غير موجود أو غير متاح.')
    await access.require(code, location_id)


async def require_route(access, code, route_id):
    row = (await access.db.execute(select(DispatchRoute.source_location_id, DispatchRoute.vehicle_id).where(
        DispatchRoute.company_id == access.company_id, DispatchRoute.id == route_id))).one_or_none()
    if row is None:
        raise HTTPException(404, 'المسار غير موجود أو غير متاح.')
    # Historic admin routes retain their existing handler validation and messages.
    if access.actor.is_admin:
        return
    if row.source_location_id is None or row.vehicle_id is None:
        raise HTTPException(403, 'لا يمكن تفويض مسار لا يحمل مواقع صريحة.')
    await access.require(code, row.source_location_id)
    await require_vehicle(access, code, row.vehicle_id)
