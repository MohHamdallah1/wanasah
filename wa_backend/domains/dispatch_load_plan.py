"""Exact route-plan reconciliation shared by Dispatch and FIELD transfer outcomes."""
from decimal import Decimal
from sqlalchemy import and_, func, or_, select
from models import DispatchRoute, DispatchLoadPlanLine, InventoryBalance, InventoryTransferHeader, InventoryTransferLine
from domains.vehicles import resolve_vehicle_custody_location_id
from services import InventoryMutationError


async def lock_session_load_plan(db, *, company_id: int, work_session_id: int):
    # Acquire before the session/location mutation locks. No route row is locked
    # here: terminal decisions may release custody after a route becomes inactive.
    key = f"dispatch-load-plan:{company_id}:{work_session_id}"
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def lock_route_adjustment_context(db, *, company_id, route_id):
    session_id = await db.scalar(select(DispatchRoute.work_session_id).where(
        DispatchRoute.company_id == company_id, DispatchRoute.id == route_id,
    ))
    if session_id is not None:
        await lock_session_load_plan(db, company_id=company_id, work_session_id=session_id)
    return session_id


async def pending_handshake_base_net(db, *, company_id, work_session_id, driver_id, vehicle_location_id):
    rows = (await db.execute(
        select(InventoryTransferHeader.source_location_id, InventoryTransferHeader.destination_location_id,
               InventoryTransferLine.product_variant_id, func.sum(InventoryTransferLine.quantity))
        .join(InventoryTransferLine, and_(
            InventoryTransferLine.company_id == InventoryTransferHeader.company_id,
            InventoryTransferLine.transfer_header_id == InventoryTransferHeader.id))
        .where(InventoryTransferHeader.company_id == company_id,
               InventoryTransferHeader.work_session_id == work_session_id,
               InventoryTransferHeader.workflow_type == "HANDSHAKE",
               InventoryTransferHeader.status == "PENDING",
               InventoryTransferHeader.expected_receiver_id == driver_id,
               InventoryTransferLine.company_id == company_id,
               or_(InventoryTransferHeader.source_location_id == vehicle_location_id,
                   InventoryTransferHeader.destination_location_id == vehicle_location_id))
        .group_by(InventoryTransferHeader.source_location_id, InventoryTransferHeader.destination_location_id,
                  InventoryTransferLine.product_variant_id)
    )).all()
    result = {}
    for src, dst, pid, quantity in rows:
        signed = Decimal(quantity or 0) * (1 if int(dst) == vehicle_location_id else -1)
        result[int(pid)] = result.get(int(pid), Decimal(0)) + signed
    return result


async def synchronize_session_load_plans(db, *, company_id, work_session_id, actor_id):
    """After terminal status is flushed: physical custody + remaining pending net.

    The caller holds lock_session_load_plan before touching transfer evidence.
    This function never moves stock and never converts already-base line quantities.
    """
    await db.flush()
    routes = (await db.scalars(select(DispatchRoute).where(
        DispatchRoute.company_id == company_id, DispatchRoute.work_session_id == work_session_id,
        DispatchRoute.vehicle_id.is_not(None),
    ).order_by(DispatchRoute.id))).all()
    for route in routes:
        location_id = await resolve_vehicle_custody_location_id(
            db, company_id=company_id, vehicle_id=route.vehicle_id, require_active=False,
        )
        rows = (await db.execute(select(
            InventoryBalance.product_variant_id, func.sum(InventoryBalance.on_hand_quantity),
        ).where(InventoryBalance.company_id == company_id, InventoryBalance.location_id == location_id)
          .group_by(InventoryBalance.product_variant_id))).all()
        physical = {int(pid): Decimal(quantity or 0) for pid, quantity in rows}
        pending = await pending_handshake_base_net(
            db, company_id=company_id, work_session_id=work_session_id,
            driver_id=route.driver_id, vehicle_location_id=location_id,
        )
        lines = (await db.scalars(select(DispatchLoadPlanLine).where(
            DispatchLoadPlanLine.company_id == company_id, DispatchLoadPlanLine.dispatch_route_id == route.id,
        ).order_by(DispatchLoadPlanLine.product_variant_id).with_for_update())).all()
        existing = {int(line.product_variant_id): line for line in lines}
        for pid in sorted(set(physical) | set(pending) | set(existing)):
            target = physical.get(pid, Decimal(0)) + pending.get(pid, Decimal(0))
            if target < 0:
                raise InventoryMutationError("Remaining pending handshakes exceed physical vehicle custody.")
            line = existing.get(pid)
            if not target:
                if line is not None:
                    await db.delete(line)
            elif line is None:
                db.add(DispatchLoadPlanLine(company_id=company_id, dispatch_route_id=route.id,
                    product_variant_id=pid, target_quantity_packs=target, updated_by=actor_id))
            else:
                line.target_quantity_packs = target
                line.updated_by = actor_id
