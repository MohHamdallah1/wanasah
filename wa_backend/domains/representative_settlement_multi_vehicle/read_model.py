"""Authorized, coherent count sheets from session execution/custody evidence."""
from sqlalchemy import select

from models import Vehicle
from services import acquire_inventory_location_guard

from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected

from .contracts import CustodyRejected
from .resolution import session_responsibilities
from .snapshots import load_vehicle_snapshot, present_snapshot


async def read_vehicle_count_sheet(db, *, access, session_id: int, vehicle_id: int) -> dict:
    company_id = access.company_id
    try:
        await access.require("settlement.read")
        work, vehicles = await session_responsibilities(
            db, company_id=company_id, session_id=session_id, lock_session=True,
        )
        if work.is_settled:
            # Never display tomorrow's live balances as yesterday's signed count.
            raise CustodyRejected("FINANCIAL_SETTLEMENT_ALREADY_CLOSED")
        vehicle = next((v for v in vehicles if v.vehicle_id == vehicle_id), None)
        if vehicle is None:
            raise CustodyRejected("SESSION_VEHICLE_NOT_FOUND", status=404)
        await access.require("inventory.read", vehicle.location_id)
        locked = (await db.execute(select(Vehicle.id, Vehicle.plate_number).where(
            Vehicle.company_id == company_id, Vehicle.id.in_([v.vehicle_id for v in vehicles]),
        ).order_by(Vehicle.id).with_for_update())).all()
        found = next((row for row in locked if row.id == vehicle_id), None)
        if found is None or len(locked) != len(vehicles):
            raise CustodyRejected("SESSION_VEHICLE_NOT_FOUND", status=404)
        _, rechecked = await session_responsibilities(
            db, company_id=company_id, session_id=session_id, lock=True,
        )
        if vehicles != rechecked:
            raise CustodyRejected("CUSTODY_CHANGED")
        await acquire_inventory_location_guard(db, company_id, vehicle.location_id, exclusive=True)
        snapshot = await load_vehicle_snapshot(
            db, company_id=company_id, session_id=session_id, responsibility=vehicle,
        )
        return {"work_session_id": work.id, "vehicle_plate": found.plate_number,
                **present_snapshot(snapshot)}
    except BackofficeCapabilityAccessRejected:
        raise CustodyRejected("AUTHORIZATION_DENIED", status=403) from None
