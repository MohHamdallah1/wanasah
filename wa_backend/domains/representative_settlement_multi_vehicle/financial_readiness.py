"""All-vehicle signed custody gate consumed before session financial posting.

This module never aggregates money or mutates balances. Existing session-owned
financial aggregation remains exactly once; no join to periods can multiply it.
The caller holds WorkSession FOR UPDATE and resolves replay before this gate.
"""
from sqlalchemy import func, or_, select, union_all

from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from models import InventoryLocation, InventoryLock, InventoryMovement, InventoryTransferHeader, Vehicle
from services import acquire_inventory_location_guard

from .application import require_capability
from .contracts import MAX_EPOCHS, CustodyRejected
from .models import VehicleCustodyCheckpoint, VehicleCustodyCheckpointEpoch
from .resolution import session_responsibilities


async def has_canonical_session_periods(db, *, company_id: int, session_id: int) -> bool:
    return await db.scalar(select(DispatchRouteExecutionPeriod.id).where(
        DispatchRouteExecutionPeriod.company_id == company_id,
        DispatchRouteExecutionPeriod.work_session_id == session_id,
        DispatchRouteExecutionPeriod.evidence_origin == "CANONICAL",
    ).limit(1)) is not None


def require_complete_coverage(vehicles, checkpoints, epoch_links):
    by_location = {c.vehicle_location_id: c for c in checkpoints}
    if len(by_location) != len(checkpoints) or set(by_location) != {v.location_id for v in vehicles}:
        raise CustodyRejected("ALL_VEHICLE_CUSTODY_CHECKPOINTS_REQUIRED")
    for vehicle in vehicles:
        checkpoint = by_location[vehicle.location_id]
        if (checkpoint.vehicle_id != vehicle.vehicle_id
                or checkpoint.context_digest != vehicle.context_digest
                or checkpoint.signed_by_principal_id is None or checkpoint.signed_at is None
                or checkpoint.mode not in ("COUNT_IN_PLACE", "PHYSICAL_HANDOFF")
                or set(checkpoint.context_manifest.get("period_ids", ())) != set(vehicle.period_ids)
                or set(checkpoint.context_manifest.get("epoch_ids", ())) != set(vehicle.epoch_ids)
                or set(epoch_links.get(checkpoint.id, ())) != set(vehicle.epoch_ids)):
            raise CustodyRejected("VEHICLE_CUSTODY_CHECKPOINT_STALE_OR_UNSIGNED")
    return by_location


def require_unchanged_or_signed_successor(*, vehicle, checkpoint, epochs, current_watermark):
    """Return a signed takeover time, or require unchanged physical evidence."""
    if (not epochs or len(epochs) > MAX_EPOCHS or epochs[0].id != checkpoint.latest_epoch_id
            or epochs[0].vehicle_location_id != vehicle.location_id):
        raise CustodyRejected("CUSTODY_CHANGED")
    if len(epochs) == 1:
        if current_watermark != checkpoint.final_movement_watermark:
            raise CustodyRejected("CUSTODY_CHECKPOINT_INVENTORY_STALE")
        return None
    previous = epochs[0]
    for successor in epochs[1:]:
        if (previous.ended_at is None or previous.ended_at < checkpoint.signed_at
                or successor.started_at != previous.ended_at
                or successor.context_revision != previous.context_revision + 1
                or successor.state != "ACCEPTED" or successor.accepted_by_principal_id is None
                or successor.vehicle_location_id != vehicle.location_id
                or not successor.request_id or not successor.payload_hash):
            raise CustodyRejected("CUSTODY_SUCCESSOR_ACCEPTANCE_REQUIRED")
        previous = successor
    return epochs[1].started_at


async def require_financial_custody_ready(db, *, access, session_id: int):
    await require_capability(access, "settlement.execute")
    from .activation import require_m04_schema
    await require_m04_schema(db)
    work, vehicles = await session_responsibilities(
        db, company_id=access.company_id, session_id=session_id, lock_session=True,
    )
    if work.is_settled:
        raise CustodyRejected("FINANCIAL_SETTLEMENT_ALREADY_CLOSED")
    location_ids = [v.location_id for v in vehicles]
    authorized = (await db.scalars(select(InventoryLocation.id).where(
        InventoryLocation.company_id == access.company_id,
        InventoryLocation.id.in_(location_ids), access.location_filter("inventory.read"),
    ))).all()
    if set(authorized) != set(location_ids):
        raise CustodyRejected("AUTHORIZATION_DENIED", status=403)
    locked = (await db.scalars(select(Vehicle.id).where(
        Vehicle.company_id == access.company_id,
        Vehicle.id.in_([v.vehicle_id for v in vehicles]),
    ).order_by(Vehicle.id).with_for_update())).all()
    if len(locked) != len(vehicles):
        raise CustodyRejected("CUSTODY_CHANGED")
    _, rechecked = await session_responsibilities(
        db, company_id=access.company_id, session_id=session_id, lock=True,
    )
    if vehicles != rechecked:
        raise CustodyRejected("CUSTODY_CHANGED")
    for location_id in sorted(v.location_id for v in vehicles):
        await acquire_inventory_location_guard(db, access.company_id, location_id, exclusive=True)
    checkpoints = (await db.scalars(select(VehicleCustodyCheckpoint).where(
        VehicleCustodyCheckpoint.company_id == access.company_id,
        VehicleCustodyCheckpoint.work_session_id == session_id,
    ).limit(MAX_EPOCHS + 1))).all()
    links = (await db.execute(select(
        VehicleCustodyCheckpointEpoch.checkpoint_id, VehicleCustodyCheckpointEpoch.epoch_id,
    ).where(VehicleCustodyCheckpointEpoch.company_id == access.company_id,
            VehicleCustodyCheckpointEpoch.work_session_id == session_id).limit(MAX_EPOCHS + 1))).all()
    if len(links) > MAX_EPOCHS:
        raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
    epoch_links = {}
    for checkpoint_id, epoch_id in links:
        epoch_links.setdefault(checkpoint_id, set()).add(epoch_id)
    by_location = require_complete_coverage(vehicles, checkpoints, epoch_links)
    # Read all current watermarks and successor epochs in sets, not one query
    # per car. The session remains bounded by MAX_EPOCHS; future history uses a
    # separate bounded budget and fails closed if human review is needed.
    epoch_rows = (await db.scalars(select(VehicleCustodyEpoch).where(
        VehicleCustodyEpoch.company_id == access.company_id,
        VehicleCustodyEpoch.vehicle_id.in_([v.vehicle_id for v in vehicles]),
        or_(*[(VehicleCustodyEpoch.vehicle_id == c.vehicle_id)
              & (VehicleCustodyEpoch.context_revision >= c.latest_epoch_revision) for c in checkpoints]),
    ).order_by(VehicleCustodyEpoch.vehicle_id, VehicleCustodyEpoch.context_revision).limit(1025))).all()
    if len(epoch_rows) > 1024:
        raise CustodyRejected("CUSTODY_SUCCESSOR_ACCEPTANCE_REQUIRED")
    history = {}
    for epoch in epoch_rows:
        history.setdefault(epoch.vehicle_id, []).append(epoch)
    source = select(InventoryMovement.source_location_id.label("location_id"),
                    InventoryMovement.id.label("movement_id")).where(
        InventoryMovement.company_id == access.company_id,
        InventoryMovement.source_location_id.in_(location_ids))
    destination = select(InventoryMovement.destination_location_id.label("location_id"),
                         InventoryMovement.id.label("movement_id")).where(
        InventoryMovement.company_id == access.company_id,
        InventoryMovement.destination_location_id.in_(location_ids))
    all_endpoints = union_all(source, destination).subquery()
    watermarks = dict((await db.execute(select(
        all_endpoints.c.location_id, func.max(all_endpoints.c.movement_id),
    ).group_by(all_endpoints.c.location_id))).all())
    uncounted_predicates = []
    lock_predicates, transfer_predicates = [], []
    for vehicle in vehicles:
        checkpoint = by_location[vehicle.location_id]
        takeover = require_unchanged_or_signed_successor(
            vehicle=vehicle, checkpoint=checkpoint, epochs=history.get(vehicle.vehicle_id, []),
            current_watermark=int(watermarks.get(vehicle.location_id, 0)),
        )
        lock_scope = InventoryLock.location_id == vehicle.location_id
        transfer_scope = or_(InventoryTransferHeader.source_location_id == vehicle.location_id,
                             InventoryTransferHeader.destination_location_id == vehicle.location_id)
        if takeover is not None:
            # Later work belongs to its new signed custodian, not to old S1.
            lock_scope = lock_scope & (InventoryLock.created_at <= takeover)
            transfer_scope = transfer_scope & (InventoryTransferHeader.created_at <= takeover)
        lock_predicates.append(lock_scope)
        transfer_predicates.append(transfer_scope)
        if takeover is not None:
            uncounted_predicates.append(
                (InventoryMovement.id > checkpoint.final_movement_watermark)
                & (InventoryMovement.created_at <= takeover)
                & or_(InventoryMovement.source_location_id == vehicle.location_id,
                      InventoryMovement.destination_location_id == vehicle.location_id))
    if uncounted_predicates:
        uncounted = await db.scalar(select(InventoryMovement.id).where(
            InventoryMovement.company_id == access.company_id,
            or_(*uncounted_predicates),
        ).limit(1))
        if uncounted is not None:
            raise CustodyRejected("CUSTODY_CHECKPOINT_INVENTORY_STALE")
    outstanding = await db.scalar(select(InventoryLock.id).where(
        InventoryLock.company_id == access.company_id, InventoryLock.released_at.is_(None),
        or_(*lock_predicates),
    ).limit(1))
    transfer = await db.scalar(select(InventoryTransferHeader.id).where(
        InventoryTransferHeader.company_id == access.company_id,
        InventoryTransferHeader.status.in_(("DRAFT", "PENDING", "IN_TRANSIT")),
        or_(*transfer_predicates),
    ).limit(1))
    if outstanding is not None or transfer is not None:
        raise CustodyRejected("CUSTODY_RECONCILIATION_OR_TRANSFER_PENDING")
    return work, tuple(checkpoints)
