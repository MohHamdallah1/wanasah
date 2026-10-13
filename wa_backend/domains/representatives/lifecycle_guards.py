from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    DispatchRoute,
    InventoryTransferHeader,
    StocktakeSession,
    WorkSession,
)

from .contracts import RepresentativeError


_CURRENT_ROUTE_STATUSES = ("active", "waiting", "postponed")
_OPEN_VEHICLE_RECON_STATUSES = (
    "DRAFT",
    "COUNTING",
    "PENDING_REVIEW",
    "RECOUNT_REQUIRED",
    "APPROVED",
)


def _blocked(blocker: str) -> RepresentativeError:
    return RepresentativeError(
        "REPRESENTATIVE_DEACTIVATION_BLOCKED",
        "Representative cannot be deactivated while operational work remains open.",
        status_code=409,
        context={"blocker": blocker},
    )


async def _first_locked_id(db: AsyncSession, statement) -> int | None:
    result = await db.execute(statement)
    value = result.scalars().first()
    return int(value) if value is not None else None


async def assert_representative_deactivation_safe(
    db: AsyncSession,
    *,
    company_id: int,
    legacy_driver_id: int,
) -> None:
    """Enforce only the source-proven operational deactivation blockers."""
    open_work_session = await _first_locked_id(
        db,
        select(WorkSession.id)
        .where(
            WorkSession.company_id == company_id,
            WorkSession.driver_id == legacy_driver_id,
            WorkSession.end_time.is_(None),
        )
        .order_by(WorkSession.id)
        .limit(1)
        .with_for_update(),
    )
    if open_work_session is not None:
        raise _blocked("OPEN_WORK_SESSION")

    current_route = await _first_locked_id(
        db,
        select(DispatchRoute.id)
        .where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.driver_id == legacy_driver_id,
            DispatchRoute.status.in_(_CURRENT_ROUTE_STATUSES),
        )
        .order_by(DispatchRoute.id)
        .limit(1)
        .with_for_update(),
    )
    if current_route is not None:
        raise _blocked("CURRENT_DISPATCH_ROUTE")

    pending_handshake = await _first_locked_id(
        db,
        select(InventoryTransferHeader.id)
        .where(
            InventoryTransferHeader.company_id == company_id,
            InventoryTransferHeader.workflow_type == "HANDSHAKE",
            InventoryTransferHeader.status == "PENDING",
            InventoryTransferHeader.expected_receiver_id == legacy_driver_id,
        )
        .order_by(InventoryTransferHeader.id)
        .limit(1)
        .with_for_update(),
    )
    if pending_handshake is not None:
        raise _blocked("PENDING_HANDSHAKE_TRANSFER")

    unreconciled_ended_session = await _first_locked_id(
        db,
        select(WorkSession.id)
        .where(
            WorkSession.company_id == company_id,
            WorkSession.driver_id == legacy_driver_id,
            WorkSession.end_time.is_not(None),
            WorkSession.inventory_reconciled_at.is_(None),
        )
        .order_by(WorkSession.id)
        .limit(1)
        .with_for_update(),
    )
    if unreconciled_ended_session is not None:
        raise _blocked("UNRECONCILED_WORK_SESSION")

    unresolved_vehicle_recon = await _first_locked_id(
        db,
        select(StocktakeSession.id)
        .join(
            WorkSession,
            and_(
                WorkSession.company_id == StocktakeSession.company_id,
                WorkSession.id == StocktakeSession.related_work_session_id,
            ),
        )
        .where(
            StocktakeSession.company_id == company_id,
            StocktakeSession.stocktake_type == "VEHICLE_RECON",
            StocktakeSession.status.in_(_OPEN_VEHICLE_RECON_STATUSES),
            WorkSession.company_id == company_id,
            WorkSession.driver_id == legacy_driver_id,
        )
        .order_by(StocktakeSession.id)
        .limit(1)
        .with_for_update(of=StocktakeSession),
    )
    if unresolved_vehicle_recon is not None:
        raise _blocked("UNRESOLVED_VEHICLE_RECON")


__all__ = ["assert_representative_deactivation_safe"]
