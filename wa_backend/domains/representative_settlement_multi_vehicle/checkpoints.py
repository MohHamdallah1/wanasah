"""Persist one immutable authenticated vehicle receipt and its exact lines."""
from sqlalchemy import func, select

from models import SessionInventorySnapshot, SystemAuditLog, utc_now

from .contracts import MAX_EPOCHS, MAX_LINES, CustodyRejected
from .models import VehicleCustodyCheckpoint, VehicleCustodyCheckpointEpoch, VehicleCustodyCheckpointLine
from .policy import command_hash, line_key


async def persist_checkpoint(db, *, access, actor_id, snapshot, command, actual, recon_id, final_watermark):
    vehicle = snapshot.responsibility
    checkpoint = VehicleCustodyCheckpoint(
        company_id=snapshot.company_id, work_session_id=snapshot.session_id,
        vehicle_id=vehicle.vehicle_id, vehicle_location_id=vehicle.location_id, mode=command.mode,
        destination_location_id=command.destination_location_id,
        signed_by_principal_id=access.subject.principal_id, request_id=str(command.request_id),
        payload_hash=command_hash(snapshot.session_id, vehicle.vehicle_id, command),
        snapshot_token=command.snapshot_token, context_digest=vehicle.context_digest,
        latest_epoch_id=snapshot.latest_epoch_id, latest_epoch_revision=snapshot.latest_epoch_revision,
        movement_watermark=snapshot.movement_watermark, final_movement_watermark=final_watermark,
        stocktake_session_id=recon_id,
        context_manifest={"period_ids": list(vehicle.period_ids), "epoch_ids": list(vehicle.epoch_ids)},
        notes=command.notes,
    )
    db.add(checkpoint)
    await db.flush()
    db.add_all([VehicleCustodyCheckpointEpoch(
        company_id=snapshot.company_id, work_session_id=snapshot.session_id,
        checkpoint_id=checkpoint.id, epoch_id=epoch_id,
    ) for epoch_id in vehicle.epoch_ids])
    db.add_all([VehicleCustodyCheckpointLine(
        company_id=snapshot.company_id, checkpoint_id=checkpoint.id,
        product_variant_id=row.variant_id, batch_id=row.batch_id, stock_status=row.stock_status,
        expected_quantity=row.quantity, actual_quantity=actual[line_key(snapshot, row)],
    ) for row in snapshot.rows])
    db.add(SystemAuditLog(
        company_id=snapshot.company_id, admin_id=actor_id, target_id=f"WorkSession_{snapshot.session_id}",
        action_type="VEHICLE_CUSTODY_COUNT_SEALED" if command.mode == "COUNT_IN_PLACE"
        else "VEHICLE_CUSTODY_PHYSICAL_HANDOFF",
        new_value=f"checkpoint={checkpoint.id};vehicle={vehicle.vehicle_id};request={command.request_id}",
    ))
    await db.flush()
    return checkpoint


async def seal_session_if_complete(db, *, work, vehicles, actor_id):
    """Freeze the day only after every vehicle has its own exact signed proof."""
    from .financial_readiness import require_complete_coverage
    receipts = (await db.scalars(select(VehicleCustodyCheckpoint).where(
        VehicleCustodyCheckpoint.company_id == work.company_id,
        VehicleCustodyCheckpoint.work_session_id == work.id,
    ).limit(MAX_EPOCHS + 1))).all()
    if len(receipts) < len(vehicles):
        if work.inventory_reconciled_at is not None:
            raise CustodyRejected("INCOMPLETE_INVENTORY_SEAL")
        return False
    links = (await db.execute(select(VehicleCustodyCheckpointEpoch.checkpoint_id,
                                     VehicleCustodyCheckpointEpoch.epoch_id).where(
        VehicleCustodyCheckpointEpoch.company_id == work.company_id,
        VehicleCustodyCheckpointEpoch.work_session_id == work.id,
    ).limit(MAX_EPOCHS + 1))).all()
    if len(links) > MAX_EPOCHS:
        raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
    by_receipt = {}
    for receipt_id, epoch_id in links:
        by_receipt.setdefault(receipt_id, set()).add(epoch_id)
    require_complete_coverage(vehicles, receipts, by_receipt)
    quantities = (await db.execute(select(
        VehicleCustodyCheckpoint.vehicle_location_id, VehicleCustodyCheckpointLine.product_variant_id,
        VehicleCustodyCheckpointLine.stock_status, func.sum(VehicleCustodyCheckpointLine.actual_quantity),
    ).join(VehicleCustodyCheckpointLine,
           (VehicleCustodyCheckpointLine.company_id == VehicleCustodyCheckpoint.company_id)
           & (VehicleCustodyCheckpointLine.checkpoint_id == VehicleCustodyCheckpoint.id)).where(
        VehicleCustodyCheckpoint.company_id == work.company_id,
        VehicleCustodyCheckpoint.work_session_id == work.id,
    ).group_by(VehicleCustodyCheckpoint.vehicle_location_id,
               VehicleCustodyCheckpointLine.product_variant_id,
               VehicleCustodyCheckpointLine.stock_status).limit(MAX_LINES * MAX_EPOCHS + 1))).all()
    expected = {(loc, variant, status): quantity for loc, variant, status, quantity in quantities}
    snapshots = (await db.scalars(select(SessionInventorySnapshot).where(
        SessionInventorySnapshot.company_id == work.company_id,
        SessionInventorySnapshot.work_session_id == work.id,
    ).limit(MAX_LINES * MAX_EPOCHS + 1))).all()
    if len(quantities) > MAX_LINES * MAX_EPOCHS or len(snapshots) > MAX_LINES * MAX_EPOCHS:
        raise CustodyRejected("SETTLEMENT_CUSTODY_TOO_LARGE")
    locations = {v.location_id for v in vehicles}
    seen = set()
    for row in snapshots:
        key = (row.location_id, row.product_variant_id, row.stock_status)
        if (row.location_id not in locations or key in seen or row.ending_quantity is None or row.settled_by is None
                or row.settled_at is None or row.ending_quantity != expected.get(key, 0)):
            raise CustodyRejected("INCOMPLETE_INVENTORY_SEAL")
        seen.add(key)
    if not set(expected) <= seen:
        raise CustodyRejected("INCOMPLETE_INVENTORY_SEAL")
    if work.inventory_reconciled_at is None:
        work.inventory_reconciled_at, work.inventory_reconciled_by = utc_now(), actor_id
    elif work.inventory_reconciled_by is None:
        raise CustodyRejected("INCOMPLETE_INVENTORY_SEAL")
    await db.flush()
    return True
