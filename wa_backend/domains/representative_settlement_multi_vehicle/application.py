"""M04 count transaction. Inventory/variance effects use an explicit owner port.

No transport is enabled until ordered schema and the canonical Vehicle Recon
multi-location authority are integrated. The application never commits a
fictional receipt, silently corrects variance, or closes financial settlement.
"""
from __future__ import annotations

from typing import Protocol

from sqlalchemy import select

from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from models import SystemAuditLog, Vehicle
from services import (
    acquire_inventory_location_guard, begin_idempotent_operation,
    complete_idempotent_operation,
)

from .contracts import CustodyRejected, VehicleCountCommand
from .models import (
    VehicleCustodyCheckpoint, VehicleCustodyCheckpointEpoch, VehicleCustodyCheckpointLine,
)
from .policy import command_hash, line_key, validate_count
from .resolution import session_responsibilities
from .snapshots import load_vehicle_snapshot, movement_watermark


class InventoryCustodyAuthority(Protocol):
    """Implemented at canonical Inventory boundary after shared-seam approval.

    All methods participate in the caller's transaction (never commit). Review
    must verify exact same-vehicle VEHICLE_RECON + approved independent recount
    evidence, rather than accepting an arbitrary POSTED stocktake.
    """
    async def require_clear_or_reviewed(self, db, *, work, snapshot) -> int | None: ...

    async def submit_variance(self, db, *, work, snapshot, actual, actor_id, notes) -> dict: ...

    async def physical_handoff(self, db, *, work, snapshot, destination_id, actor_id,
                               request_id) -> int: ...


async def require_capability(access, code, location_id=None):
    try:
        await access.require(code, location_id)
    except BackofficeCapabilityAccessRejected:
        raise CustodyRejected("AUTHORIZATION_DENIED", status=403) from None


async def record_vehicle_count(db, *, access, actor_id: int, session_id: int,
                               vehicle_id: int, command: VehicleCountCommand,
                               inventory: InventoryCustodyAuthority) -> dict:
    """Authorize replay, then serialize count against lifecycle/load/settlement.

    Lock order follows M02: idempotency -> WorkSession -> sorted Vehicle ->
    custody epochs -> sorted Inventory location guards. Caller maps errors;
    this use case commits the receipt and durable response together.
    """
    company_id = access.company_id
    try:
        await require_capability(access, "settlement.execute")
        _, vehicles = await session_responsibilities(
            db, company_id=company_id, session_id=session_id,
        )
        vehicle = next((v for v in vehicles if v.vehicle_id == vehicle_id), None)
        if vehicle is None:
            raise CustodyRejected("SESSION_VEHICLE_NOT_FOUND", status=404)
        await require_capability(access, "inventory.read", vehicle.location_id)
        await require_capability(access, "stocktake.count", vehicle.location_id)
        if command.mode == "PHYSICAL_HANDOFF":
            await require_capability(access, "transfer.send", vehicle.location_id)
            await require_capability(access, "transfer.destination", command.destination_location_id)
        record, replay = await begin_idempotent_operation(
            db, company_id=company_id, actor_id=actor_id,
            operation="REP_MULTI_VEHICLE_CUSTODY_COUNT", request_id=str(command.request_id),
            request_hash=command_hash(session_id, vehicle_id, command),
        )
        if replay is not None:
            await db.rollback()
            return replay
        work, locked_vehicles = await session_responsibilities(
            db, company_id=company_id, session_id=session_id, lock_session=True,
        )
        if work.is_settled:
            raise CustodyRejected("FINANCIAL_SETTLEMENT_ALREADY_CLOSED")
        if vehicles != locked_vehicles:
            raise CustodyRejected("CUSTODY_CHANGED")
        locked_ids = (await db.scalars(select(Vehicle.id).where(
            Vehicle.company_id == company_id, Vehicle.id.in_([v.vehicle_id for v in vehicles]),
        ).order_by(Vehicle.id).with_for_update())).all()
        if len(locked_ids) != len(vehicles):
            raise CustodyRejected("SESSION_VEHICLE_NOT_FOUND", status=404)
        # Lock epochs only after Vehicle, in the same order as lifecycle writers.
        _, rechecked = await session_responsibilities(
            db, company_id=company_id, session_id=session_id, lock=True,
        )
        if vehicles != rechecked:
            raise CustodyRejected("CUSTODY_CHANGED")
        locations = {vehicle.location_id}
        if command.destination_location_id is not None:
            locations.add(command.destination_location_id)
        for location_id in sorted(locations):
            await acquire_inventory_location_guard(db, company_id, location_id, exclusive=True)
        existing = await db.scalar(select(VehicleCustodyCheckpoint.id).where(
            VehicleCustodyCheckpoint.company_id == company_id,
            VehicleCustodyCheckpoint.work_session_id == session_id,
            VehicleCustodyCheckpoint.vehicle_location_id == vehicle.location_id,
        ))
        if existing is not None:
            raise CustodyRejected("VEHICLE_CUSTODY_ALREADY_COUNTED")
        snapshot = await load_vehicle_snapshot(
            db, company_id=company_id, session_id=session_id, responsibility=vehicle,
        )
        actual = validate_count(snapshot, command)
        recon_id = await inventory.require_clear_or_reviewed(db, work=work, snapshot=snapshot)
        mismatch = any(actual[line_key(snapshot, row)] != row.quantity for row in snapshot.rows)
        if mismatch:
            if recon_id is not None:
                raise CustodyRejected("SEALED_CUSTODY_COUNT_MISMATCH")
            await require_capability(access, "stocktake.start", vehicle.location_id)
            response = await inventory.submit_variance(
                db, work=work, snapshot=snapshot, actual=actual, actor_id=actor_id, notes=command.notes,
            )
            # Inventory owns all corrections; neither a checkpoint nor receipt
            # may exist while independent review remains outstanding.
            response = {**response, "financial_ready": False, "movement_count": 0}
        else:
            moved = 0
            if command.mode == "PHYSICAL_HANDOFF":
                moved = await inventory.physical_handoff(
                    db, work=work, snapshot=snapshot,
                    destination_id=command.destination_location_id,
                    actor_id=actor_id, request_id=str(command.request_id),
                )
            final_watermark = await movement_watermark(
                db, company_id=company_id, location_id=vehicle.location_id,
            )
            checkpoint = VehicleCustodyCheckpoint(
                company_id=company_id, work_session_id=session_id, vehicle_id=vehicle_id,
                vehicle_location_id=vehicle.location_id, mode=command.mode,
                destination_location_id=command.destination_location_id,
                signed_by_principal_id=access.subject.principal_id,
                request_id=str(command.request_id), payload_hash=command_hash(session_id, vehicle_id, command),
                snapshot_token=command.snapshot_token, context_digest=vehicle.context_digest,
                latest_epoch_id=snapshot.latest_epoch_id,
                latest_epoch_revision=snapshot.latest_epoch_revision,
                movement_watermark=snapshot.movement_watermark,
                final_movement_watermark=final_watermark, stocktake_session_id=recon_id,
                context_manifest={"period_ids": list(vehicle.period_ids), "epoch_ids": list(vehicle.epoch_ids)},
                notes=command.notes,
            )
            db.add(checkpoint)
            await db.flush()
            db.add_all([VehicleCustodyCheckpointEpoch(
                company_id=company_id, work_session_id=session_id,
                checkpoint_id=checkpoint.id, epoch_id=epoch_id,
            ) for epoch_id in vehicle.epoch_ids])
            db.add_all([VehicleCustodyCheckpointLine(
                company_id=company_id, checkpoint_id=checkpoint.id,
                product_variant_id=row.variant_id, batch_id=row.batch_id,
                stock_status=row.stock_status, expected_quantity=row.quantity,
                actual_quantity=actual[line_key(snapshot, row)],
            ) for row in snapshot.rows])
            # A dedicated event: COUNT_IN_PLACE never claims warehouse receipt.
            db.add(SystemAuditLog(
                company_id=company_id, admin_id=actor_id,
                target_id=f"WorkSession_{session_id}",
                action_type="VEHICLE_CUSTODY_COUNT_SEALED" if command.mode == "COUNT_IN_PLACE"
                else "VEHICLE_CUSTODY_PHYSICAL_HANDOFF",
                new_value=f"checkpoint={checkpoint.id};vehicle={vehicle_id};request={command.request_id}",
            ))
            response = {
                "status": "VEHICLE_CUSTODY_SEALED", "mode": command.mode,
                "vehicle_id": vehicle_id, "checkpoint_id": checkpoint.id,
                "review_required": False, "movement_count": moved,
                # Final readiness is a separate all-vehicle authoritative gate.
                "financial_ready": False,
            }
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except Exception:
        await db.rollback()
        raise
