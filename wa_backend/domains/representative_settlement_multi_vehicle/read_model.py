"""Authorized, coherent count sheets from session execution/custody evidence."""
from sqlalchemy import select

from models import InventoryLocation, StocktakeSession, Vehicle
from services import acquire_inventory_location_guard

from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected

from .contracts import MAX_EPOCHS, CustodyRejected
from .models import VehicleCustodyCheckpoint, VehicleCustodyCheckpointEpoch
from .activation import require_m04_schema
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


async def read_session_vehicle_membership(db, *, access, session_id: int) -> dict:
    """Bounded signed S1 vehicle+checkpoint status list for M05.

    Not a financial-settlement permission or physical stock read. One missing
    vehicle location grant denies the entire list so partial visibility cannot
    be misrepresented to an operator as a complete session. S2's future period
    is intentionally not joined; only the exact CLOSED S1 evidence is read.
    """
    from .application import require_capability

    await require_capability(access, "settlement.read")
    await require_m04_schema(db)
    work, vehicles = await session_responsibilities(
        db, company_id=access.company_id, session_id=session_id,
    )
    if len(vehicles) == 0 or len(vehicles) > MAX_EPOCHS:
        raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
    locations = {v.location_id for v in vehicles}
    if len(locations) != len(vehicles):
        raise CustodyRejected("VEHICLE_LOCATION_EVIDENCE_AMBIGUOUS")
    authorized_locations = set((await db.scalars(select(InventoryLocation.id).where(
        InventoryLocation.company_id == access.company_id,
        InventoryLocation.id.in_(locations),
        InventoryLocation.location_type == "VEHICLE",
        access.location_filter("inventory.read", InventoryLocation.id),
    ))).all())
    if authorized_locations != locations:
        raise CustodyRejected("AUTHORIZATION_DENIED", status=403)

    car_ids = {v.vehicle_id for v in vehicles}
    plates = dict((await db.execute(select(Vehicle.id, Vehicle.plate_number).where(
        Vehicle.company_id == access.company_id, Vehicle.id.in_(car_ids),
    ))).all())
    if set(plates) != car_ids:
        raise CustodyRejected("SESSION_VEHICLE_NOT_FOUND", status=404)

    checkpoints = (await db.scalars(select(VehicleCustodyCheckpoint).where(
        VehicleCustodyCheckpoint.company_id == access.company_id,
        VehicleCustodyCheckpoint.work_session_id == session_id,
    ).order_by(VehicleCustodyCheckpoint.id).limit(MAX_EPOCHS + 1))).all()
    if len(checkpoints) > MAX_EPOCHS:
        raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
    signed_by_location = {}
    for checkpoint in checkpoints:
        location_id = int(checkpoint.vehicle_location_id)
        if location_id not in locations or location_id in signed_by_location:
            raise CustodyRejected("VEHICLE_CUSTODY_CHECKPOINT_STALE_OR_UNSIGNED")
        signed_by_location[location_id] = checkpoint

    epoch_links = (await db.execute(select(
        VehicleCustodyCheckpointEpoch.checkpoint_id,
        VehicleCustodyCheckpointEpoch.epoch_id,
    ).where(
        VehicleCustodyCheckpointEpoch.company_id == access.company_id,
        VehicleCustodyCheckpointEpoch.work_session_id == session_id,
    ).limit(MAX_EPOCHS + 1))).all()
    if len(epoch_links) > MAX_EPOCHS:
        raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
    linked_epochs = {}
    for checkpoint_id, epoch_id in epoch_links:
        linked_epochs.setdefault(int(checkpoint_id), set()).add(int(epoch_id))

    reviews = (await db.execute(select(
        StocktakeSession.location_id, StocktakeSession.id,
        StocktakeSession.status,
    ).where(
        StocktakeSession.company_id == access.company_id,
        StocktakeSession.related_work_session_id == session_id,
        StocktakeSession.stocktake_type == "VEHICLE_RECON",
        StocktakeSession.location_id.in_(locations),
    ).order_by(StocktakeSession.location_id, StocktakeSession.id)
     .limit(MAX_EPOCHS + 1))).all()
    if len(reviews) > MAX_EPOCHS:
        raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
    recon_by_location = {}
    for loc, recon_id, status in reviews:
        if int(loc) in recon_by_location:
            raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
        recon_by_location[int(loc)] = (int(recon_id), str(status))

    result = []
    for vehicle in vehicles:
        checkpoint = signed_by_location.get(vehicle.location_id)
        recon = recon_by_location.get(vehicle.location_id)
        if checkpoint is not None:
            manifest = checkpoint.context_manifest
            if (not isinstance(manifest, dict)
                    or checkpoint.vehicle_id != vehicle.vehicle_id
                    or checkpoint.context_digest != vehicle.context_digest
                    or checkpoint.signed_at is None or checkpoint.signed_by_principal_id is None
                    or checkpoint.mode not in ("COUNT_IN_PLACE", "PHYSICAL_HANDOFF")
                    or set(manifest.get("period_ids", ())) != set(vehicle.period_ids)
                    or set(manifest.get("epoch_ids", ())) != set(vehicle.epoch_ids)
                    or linked_epochs.get(int(checkpoint.id), set()) != set(vehicle.epoch_ids)
                    or checkpoint.stocktake_session_id != (recon[0] if recon else None)
                    or (recon is not None and recon[1] != "POSTED")):
                raise CustodyRejected("VEHICLE_CUSTODY_CHECKPOINT_STALE_OR_UNSIGNED")
            status = "COUNT_SIGNED"
        elif recon is not None:
            status = "REVIEW_REQUIRED" if recon[1] != "POSTED" else "RECOUNT_AND_SIGN_REQUIRED"
        else:
            status = "NOT_COUNTED"
        result.append({
            "vehicle_id": vehicle.vehicle_id,
            "vehicle_location_id": vehicle.location_id,
            "plate_number": plates[vehicle.vehicle_id],
            "period_ids": list(vehicle.period_ids),
            "custody_epoch_ids": list(vehicle.epoch_ids),
            "checkpoint_status": status,
            "checkpoint_id": int(checkpoint.id) if checkpoint else None,
            "checkpoint_mode": checkpoint.mode if checkpoint else None,
        })
    return {
        "work_session_id": int(work.id),
        "work_session_ended": work.end_time is not None,
        "financially_settled": bool(work.is_settled),
        "all_vehicle_counts_signed": all(v["checkpoint_status"] == "COUNT_SIGNED" for v in result),
        # Not financial-ready: the actual settlement writer must separately
        # verify immutable movement watermarks, epoch successors and locks.
        "vehicles": result,
    }
