"""Read-only #1077 projection of currently Pending signed urgent assignments.

The existing demand/Visit write contract is unchanged. An approved quantity is
neither delivery nor a reservation. One query snapshot preserves conservation.
"""
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.sql.selectable import CTE

from dispatch_access import route_filter, vehicle_filter
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from models import DispatchRoute, ShortageRequest, ShortageUrgentAssignment, Visit


def pending_urgent_projection(
    access: BackofficeCapabilityAccess, visible: CTE, *, company_directory: bool,
):
    """Aggregate only the existing visible demand IDs and current Pending Visits.

    No assignment is omitted on a vehicle-scope failure: redact the entire
    projection instead of reporting a misleading partial sum.
    """
    # Start from the live Visit set, not every assignment in a demand's
    # historical ledger. The existing unique (company, shortage, visit)
    # index supports exact point lookups; LIMIT 1 expresses that uniqueness
    # and prevents a history-first join plan.
    pending = select(
        Visit.id, Visit.company_id, Visit.shop_id, Visit.driver_id,
        Visit.work_session_id, Visit.is_emergency,
    ).where(
        Visit.company_id == access.company_id,
        Visit.status == "Pending",
    ).cte("current_pending_visits").prefix_with("MATERIALIZED")
    assignment = ShortageUrgentAssignment
    current = select(
        assignment.shortage_id, assignment.driver_id, assignment.vehicle_id,
        assignment.approved_base,
    ).where(
        assignment.company_id == visible.c.company_id,
        assignment.shortage_id == visible.c.id,
        assignment.visit_id == pending.c.id,
    ).correlate(visible, pending).limit(1).lateral("current_urgent_assignment")
    valid = and_(
        pending.c.shop_id == visible.c.shop_id,
        pending.c.driver_id == current.c.driver_id,
        pending.c.is_emergency.is_(True),
        or_(visible.c.driver_id.is_(None), visible.c.driver_id == current.c.driver_id),
        current.c.approved_base > 0,
        vehicle_filter(access, "dispatch.read", current.c.vehicle_id),
    )
    if not company_directory:
        valid = and_(valid, select(1).select_from(DispatchRoute).where(
            DispatchRoute.company_id == access.company_id,
            DispatchRoute.driver_id == current.c.driver_id,
            DispatchRoute.vehicle_id == current.c.vehicle_id,
            DispatchRoute.status == "active",
            or_(pending.c.work_session_id.is_(None),
                DispatchRoute.work_session_id == pending.c.work_session_id),
            route_filter(access, "dispatch.read"),
        ).exists())
    return select(
        current.c.shortage_id.label("shortage_id"),
        func.sum(current.c.approved_base).label("active_base"),
        func.bool_and(func.coalesce(valid, False)).label("evidence_allowed"),
    ).select_from(visible).join(
        pending, pending.c.company_id == visible.c.company_id,
    ).join(current, true()).where(
        visible.c.fulfillment_version == 1,
    ).group_by(current.c.shortage_id).subquery("pending_shortage_urgent")


def project_urgent_quantities(
    demand: ShortageRequest, active_base: int | None, evidence_allowed: bool | None,
) -> dict[str, int | None]:
    unknown = {"activeUrgentBase": None, "unassignedBase": None}
    if (
        demand.fulfillment_version != 1 or demand.status != "pending"
        or demand.fulfilled_base is None
        or not 0 <= demand.fulfilled_base < demand.quantity
        or evidence_allowed is False
        or (active_base is None) != (evidence_allowed is None)
    ):
        return unknown
    outstanding = demand.quantity - demand.fulfilled_base
    active = 0 if active_base is None else int(active_base)
    if not 0 <= active <= outstanding:
        return unknown
    return {"activeUrgentBase": active, "unassignedBase": outstanding - active}
