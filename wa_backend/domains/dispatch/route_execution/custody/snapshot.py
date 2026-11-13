"""Bounded tenant-scoped physical vehicle evidence; never mutates inventory."""
from __future__ import annotations
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    DispatchRoute, InventoryBalance, InventoryLocation, InventoryMovement,
    Vehicle, WorkSession,
)
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.vehicles.eligibility import vehicle_is_operational
from domains.vehicles.repository import read_canonical_custody_location_id
from domains.vehicles.contracts import VehicleError
from services import acquire_inventory_location_guard

from .proofs import CustodyRejected, digest

MAX_STOCK_LINES = 10000

@dataclass(frozen=True)
class CustodyState:
    location_id: int
    epoch: VehicleCustodyEpoch | None
    stock_snapshot: str
    stocked: bool
    lines: list[dict]

    @property
    def revision(self) -> int:
        return int(self.epoch.context_revision) if self.epoch else 0


async def read_vehicle_state(
    db: AsyncSession, company_id: int, vehicle_id: int, *,
    lock: bool = False,
) -> CustodyState:
    # Lock Vehicle first (like Dispatch lifecycle), then the canonical
    # inventory location. Every stock writer also takes the location guard.
    try:
        location_id = await read_canonical_custody_location_id(
            db, company_id=company_id, vehicle_id=vehicle_id, require_active=True,
        )
    except VehicleError as exc:
        # Never turn an invalid, inactive, or ambiguous custody location into
        # an unhandled 500; the caller receives a tenant-safe recovery code.
        raise CustodyRejected(exc.code, exc.status_code) from exc
    vehicle_query = select(Vehicle).where(
        Vehicle.company_id == company_id, Vehicle.id == vehicle_id,
    )
    if lock:
        vehicle_query = vehicle_query.with_for_update()
    vehicle = await db.scalar(vehicle_query)
    if vehicle is None or not vehicle_is_operational(vehicle):
        raise CustodyRejected("CUSTODY_VEHICLE_NOT_OPERATIONAL")
    if lock:
        # Match Dispatch launch/lifecycle's vehicle-before-inventory order;
        # stock writers share the location guard, preventing snapshot drift.
        await acquire_inventory_location_guard(
            db, company_id, location_id, exclusive=True,
        )
    location = await db.scalar(select(InventoryLocation).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.id == location_id,
        InventoryLocation.vehicle_id == vehicle_id,
        InventoryLocation.location_type == "VEHICLE",
        InventoryLocation.is_active.is_(True),
    ))
    if location is None:
        raise CustodyRejected("CUSTODY_LOCATION_CHANGED")

    epoch_query = select(VehicleCustodyEpoch).where(
        VehicleCustodyEpoch.company_id == company_id,
        VehicleCustodyEpoch.vehicle_id == vehicle_id,
        VehicleCustodyEpoch.ended_at.is_(None),
    )
    if lock:
        epoch_query = epoch_query.with_for_update()
    epochs = (await db.scalars(epoch_query)).all()
    if len(epochs) > 1:
        raise CustodyRejected("CUSTODY_EPOCH_AMBIGUOUS")
    epoch = epochs[0] if epochs else None
    if epoch is not None and int(epoch.vehicle_location_id) != location_id:
        raise CustodyRejected("CUSTODY_EPOCH_LOCATION_MISMATCH")

    # Snapshot covers every batch/variant/status and reservation, including
    # inventory zero rows, and the location's movement watermark.
    statement = select(
        InventoryBalance.product_variant_id,
        InventoryBalance.batch_id, InventoryBalance.stock_status,
        InventoryBalance.on_hand_quantity, InventoryBalance.reserved_quantity,
        InventoryBalance.last_updated,
    ).where(
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == location_id,
    ).order_by(
        InventoryBalance.product_variant_id, InventoryBalance.batch_id,
        InventoryBalance.stock_status,
    ).limit(MAX_STOCK_LINES + 1)
    if lock:
        statement = statement.with_for_update()
    stock = (await db.execute(statement)).all()
    if len(stock) > MAX_STOCK_LINES:
        raise CustodyRejected("CUSTODY_SNAPSHOT_WINDOW_EXCEEDED")
    lines = [dict(
        variant_id=int(row[0]), batch_id=int(row[1]), status=str(row[2]),
        on_hand=str(row[3]), reserved=str(row[4]),
        last_updated=str(row[5]),
    ) for row in stock]
    moves = await db.execute(select(
        func.coalesce(func.count(InventoryMovement.id), 0),
        func.coalesce(func.max(InventoryMovement.id), 0),
    ).where(
        InventoryMovement.company_id == company_id,
        or_(InventoryMovement.source_location_id == location_id,
            InventoryMovement.destination_location_id == location_id),
    ))
    movement_count, last_movement_id = moves.one()
    fingerprint = digest({
        "company_id": company_id, "vehicle_id": vehicle_id,
        "location_id": location_id, "lines": lines,
        "movement_count": int(movement_count),
        "last_movement_id": int(last_movement_id),
    })
    return CustodyState(
        location_id=location_id, epoch=epoch,
        stock_snapshot=fingerprint,
        stocked=any(row[3] > 0 for row in stock), lines=lines,
    )


async def require_quiescent_vehicle(
    db: AsyncSession, company_id: int, vehicle_id: int,
) -> None:
    live_route = await db.scalar(select(DispatchRoute.id).where(
        DispatchRoute.company_id == company_id,
        DispatchRoute.vehicle_id == vehicle_id,
        # Both legacy and M02/other revisions must hold the vehicle.
        # An inconsistent missing period is not permission to reassign.
        DispatchRoute.status.in_(("active", "waiting")),
    ).limit(1))
    live_period = await db.scalar(select(DispatchRouteExecutionPeriod.id).where(
        DispatchRouteExecutionPeriod.company_id == company_id,
        DispatchRouteExecutionPeriod.vehicle_id == vehicle_id,
        DispatchRouteExecutionPeriod.ended_at.is_(None),
        DispatchRouteExecutionPeriod.state.in_(("PLANNED", "ACTIVE")),
    ).limit(1))
    if live_route is not None or live_period is not None:
        raise CustodyRejected("CUSTODY_LIVE_ROUTE_MUST_SETTLE_FIRST")
    unresolved = await db.scalar(
        select(WorkSession.id).join(
            DispatchRouteExecutionPeriod,
            (DispatchRouteExecutionPeriod.company_id == WorkSession.company_id)
            & (DispatchRouteExecutionPeriod.work_session_id == WorkSession.id),
        ).where(
            WorkSession.company_id == company_id,
            DispatchRouteExecutionPeriod.vehicle_id == vehicle_id,
            or_(WorkSession.end_time.is_(None),
                WorkSession.is_settled.is_(False),
                WorkSession.inventory_reconciled_at.is_(None)),
        ).limit(1)
    )
    if unresolved is not None:
        raise CustodyRejected("CUSTODY_PREVIOUS_SESSION_UNSETTLED")
    # An M01 legacy epoch can point at an original WorkSession without an M03
    # execution period. The missing join must NOT allow custody to bypass
    # that session's unfinished financial/inventory settlement.
    from_existing_epoch = await db.scalar(
        select(WorkSession.id).join(
            VehicleCustodyEpoch,
            (VehicleCustodyEpoch.company_id == WorkSession.company_id)
            & (VehicleCustodyEpoch.related_session_id == WorkSession.id),
        ).where(
            WorkSession.company_id == company_id,
            VehicleCustodyEpoch.vehicle_id == vehicle_id,
            or_(WorkSession.end_time.is_(None),
                WorkSession.is_settled.is_(False),
                WorkSession.inventory_reconciled_at.is_(None)),
        ).limit(1)
    )
    if from_existing_epoch is not None:
        raise CustodyRejected("CUSTODY_PREVIOUS_SESSION_UNSETTLED")
    # Old postponed/closed route rows can retain a WorkSession association
    # even where no M03 period and no M01 related_session were backfilled.
    # Outstanding settlement still prevents assuming responsibility is free.
    from_legacy_route = await db.scalar(
        select(WorkSession.id).join(
            DispatchRoute,
            (DispatchRoute.company_id == WorkSession.company_id)
            & (DispatchRoute.work_session_id == WorkSession.id),
        ).where(
            WorkSession.company_id == company_id,
            DispatchRoute.vehicle_id == vehicle_id,
            or_(WorkSession.end_time.is_(None),
                WorkSession.is_settled.is_(False),
                WorkSession.inventory_reconciled_at.is_(None)),
        ).limit(1)
    )
    if from_legacy_route is not None:
        raise CustodyRejected("CUSTODY_PREVIOUS_SESSION_UNSETTLED")
