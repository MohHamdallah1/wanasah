"""#1067: shortage allocation only from signed, frozen FIELD sale evidence.

A matching SKU is NEVER enough: a manager-created tenant-scoped
ShortageUrgentAssignment binds a specific Visit to a specific demand and
an approved upper bound. No sale matching an unrelated Visit can consume demand.
"""
from __future__ import annotations

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    ShortageRequest, ShortageUrgentAssignment, ShortageDeliveryEvent, Visit,
)


def _positive_base(value: object, field: str) -> int:
    number = Decimal(str(value))
    if not number.is_finite() or number != number.to_integral_value() or number <= 0:
        raise ValueError(f"{field} must be a positive integral canonical base quantity")
    result = int(number)
    if result > 2_147_483_647:
        raise ValueError(f"{field} exceeds supported shortage quantity")
    return result


async def apply_signed_shortage_sale(
    db: AsyncSession, *, company_id: int, visit: Visit,
    sale_quantities: dict[int, Decimal], request_id: str,
) -> list[dict]:
    """Call ONLY after frozen SalesVisitRevision + posted Visit sale movements.

    Caller owns the visit/Shop transaction and its original FIELD UUID.
    The same transaction commits the append-only delivery evidence.
    """
    if not sale_quantities:
        return []
    if visit.current_sales_revision_id is None:
        raise RuntimeError("Shortage delivery requires a frozen sale revision")
    rows = (await db.execute(
        select(ShortageUrgentAssignment)
        .where(
            ShortageUrgentAssignment.company_id == company_id,
            ShortageUrgentAssignment.visit_id == visit.id,
        )
        # Approved assignment rows are immutable; the demand row below is
        # the quantity serialization point. Do not take assignment row locks
        # ahead of the demand (manager promotion locks demand first).
        .order_by(ShortageUrgentAssignment.id.asc())
    )).scalars().all()
    if not rows:
        return []
    shortage_ids = sorted({int(a.shortage_id) for a in rows})
    demands = (await db.execute(
        select(ShortageRequest)
        .where(ShortageRequest.company_id == company_id, ShortageRequest.id.in_(shortage_ids))
        .order_by(ShortageRequest.id.asc())
        .with_for_update()
    )).scalars().all()
    demand_map = {int(s.id): s for s in demands}
    remaining_sales = {
        int(pid): _positive_base(qty, f"sale[{pid}]")
        for pid, qty in sale_quantities.items() if Decimal(str(qty)) > 0
    }
    recorded = []
    for assignment in rows:
        shortage = demand_map.get(int(assignment.shortage_id))
        if (
            shortage is None or shortage.fulfillment_version != 1
            or shortage.fulfilled_base is None or shortage.company_id != company_id
            or shortage.shop_id != visit.shop_id
            or assignment.driver_id != visit.driver_id
        ):
            raise RuntimeError("Signed shortage assignment/demand provenance mismatch")
        product_id = int(shortage.product_variant_id)
        offered = remaining_sales.get(product_id, 0)
        if not offered:
            continue
        already = (await db.execute(
            select(ShortageDeliveryEvent)
            .where(
                ShortageDeliveryEvent.company_id == company_id,
                ShortageDeliveryEvent.assignment_id == assignment.id,
                ShortageDeliveryEvent.event_type == "DELIVERY",
            ).order_by(ShortageDeliveryEvent.id.asc())
        )).scalars().all()
        reversed_ids = set((await db.scalars(
            select(ShortageDeliveryEvent.reverses_event_id).where(
                ShortageDeliveryEvent.company_id == company_id,
                ShortageDeliveryEvent.assignment_id == assignment.id,
                ShortageDeliveryEvent.event_type == "REVERSAL",
            )
        )).all())
        active = sum(int(e.quantity_delta) for e in already if e.id not in reversed_ids)
        room_in_assignment = int(assignment.approved_base) - active
        room_in_demand = int(shortage.quantity) - int(shortage.fulfilled_base)
        if room_in_assignment < 0 or room_in_demand < 0:
            raise RuntimeError("Shortage quantity authority corrupted")
        credited = min(offered, room_in_assignment, room_in_demand)
        if credited <= 0:
            continue
        db.add(ShortageDeliveryEvent(
            company_id=company_id,
            assignment_id=int(assignment.id),
            visit_id=int(visit.id),
            sales_revision_id=int(visit.current_sales_revision_id),
            event_type="DELIVERY",
            quantity_delta=credited,
            request_id=str(request_id),
        ))
        shortage.fulfilled_base = int(shortage.fulfilled_base) + credited
        shortage.status = "fulfilled" if shortage.fulfilled_base == shortage.quantity else "pending"
        if shortage.status == "fulfilled":
            shortage.fulfilled_by_visit_id = int(visit.id)
            from models import utc_now
            shortage.fulfilled_at = utc_now()
        else:
            shortage.fulfilled_by_visit_id = None
            shortage.fulfilled_at = None
        remaining_sales[product_id] = offered - credited
        recorded.append({
            "shortage_id": int(shortage.id),
            "assignment_id": int(assignment.id),
            "credited_base": credited,
            "outstanding_base": int(shortage.quantity) - int(shortage.fulfilled_base),
        })
    return recorded


async def reverse_signed_shortage_sale(
    db: AsyncSession, *, company_id: int, visit_id: int, request_id: str,
) -> list[dict]:
    """Append exact compensating deltas on a FIELD correction, without deleting history.

    Caller has locked original Visit and Shop and has reversed the sale's
    financial/inventory revision inside the same transaction.
    """
    delivered = (await db.execute(
        select(ShortageDeliveryEvent)
        .where(
            ShortageDeliveryEvent.company_id == company_id,
            ShortageDeliveryEvent.visit_id == visit_id,
            ShortageDeliveryEvent.event_type == "DELIVERY",
        ).order_by(ShortageDeliveryEvent.id.asc())
    )).scalars().all()
    if not delivered:
        return []
    # Historical delivery and assignment rows are immutable. Lock mutable
    # demands FIRST (same ordering as manager promotion and FIELD delivery)
    # so a correction cannot deadlock a concurrent urgent authorization.
    assignments = (await db.execute(
        select(ShortageUrgentAssignment)
        .where(
            ShortageUrgentAssignment.company_id == company_id,
            ShortageUrgentAssignment.id.in_({int(e.assignment_id) for e in delivered}),
        ).order_by(ShortageUrgentAssignment.id.asc())
    )).scalars().all()
    assignment_map = {int(a.id): a for a in assignments}
    shortages = (await db.execute(
        select(ShortageRequest)
        .where(
            ShortageRequest.company_id == company_id,
            ShortageRequest.id.in_({int(a.shortage_id) for a in assignments}),
        ).order_by(ShortageRequest.id.asc())
        .with_for_update()
    )).scalars().all()
    shortage_map = {int(s.id): s for s in shortages}
    already_reversed = set((await db.scalars(
        select(ShortageDeliveryEvent.reverses_event_id).where(
            ShortageDeliveryEvent.company_id == company_id,
            ShortageDeliveryEvent.visit_id == visit_id,
            ShortageDeliveryEvent.event_type == "REVERSAL",
        )
    )).all())
    changed = []
    for event in delivered:
        if event.id in already_reversed:
            continue
        assignment = assignment_map.get(int(event.assignment_id))
        shortage = shortage_map.get(int(assignment.shortage_id)) if assignment else None
        if shortage is None or shortage.fulfillment_version != 1:
            raise RuntimeError("Missing tenant shortage correction provenance")
        qty = int(event.quantity_delta)
        if not isinstance(shortage.fulfilled_base, int) or shortage.fulfilled_base < qty:
            raise RuntimeError("Cannot reverse more than committed shortage delivery")
        db.add(ShortageDeliveryEvent(
            company_id=company_id,
            assignment_id=int(event.assignment_id),
            visit_id=int(visit_id),
            sales_revision_id=int(event.sales_revision_id),
            event_type="REVERSAL",
            quantity_delta=-qty,
            reverses_event_id=int(event.id),
            request_id=str(request_id),
        ))
        shortage.fulfilled_base -= qty
        shortage.status = "pending"
        shortage.fulfilled_at = None
        shortage.fulfilled_by_visit_id = None
        changed.append({"shortage_id": int(shortage.id), "reversed_base": qty})
    return changed
