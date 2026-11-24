"""Read-only #1077 projection of currently Pending signed urgent assignments.

The existing demand/Visit write contract is unchanged. An approved quantity is
neither delivery nor a reservation. One query snapshot preserves conservation.
"""
from sqlalchemy import and_, func, literal, literal_column, or_, select, true
from sqlalchemy.sql.selectable import CTE

from dispatch_access import route_filter, vehicle_filter
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from models import DispatchRoute, ShortageRequest, ShortageUrgentAssignment, Visit


def current_pending_visit_keys(company_id: int) -> CTE:
    """All tenant Pending Visit keys, bounded keyset batches, one snapshot."""
    # Read all live keys in ordered, index-friendly batches within one SQL
    # snapshot. A broad scan can choose a tenant-only historical index when
    # stats are stale; keyset batches keep the work on the live range.
    # The recursive cursor is strictly increasing; no final result cap.
    def key_batch(after=None):
        keys = select(Visit.id).where(
            Visit.company_id == company_id,
            Visit.status == literal_column("'Pending'"),
        )
        if after is not None:
            keys = keys.where(Visit.id > after).correlate(batches)
        return keys.order_by(Visit.id).limit(literal_column("32")).subquery()

    def collect(keys):
        return select(
            func.array_agg(keys.c.id).label("ids"),
            func.max(keys.c.id).label("last_id"),
        ).select_from(keys).having(func.count() > 0)

    batches = collect(key_batch()).cte("pending_visit_batches", recursive=True)
    following = collect(key_batch(batches.c.last_id)).lateral()
    batches = batches.union_all(
        select(following.c.ids, following.c.last_id)
        .select_from(batches).join(following, true()),
    )
    return select(
        func.unnest(batches.c.ids).label("id"),
        literal(company_id).label("company_id"),
    ).select_from(batches).cte("current_pending_visits").prefix_with("MATERIALIZED")


def pending_urgent_projection(
    access: BackofficeCapabilityAccess, visible: CTE, *, company_directory: bool,
):
    """Aggregate only the existing visible demand IDs and current Pending Visits.

    No assignment is omitted on a vehicle-scope failure: redact the entire
    projection instead of reporting a misleading partial sum.
    """
    pending = current_pending_visit_keys(access.company_id)
    assignment = ShortageUrgentAssignment
    # Visit-leading indexed range, not demand x Visit point probes. OFFSET 0
    # is an optimization fence (no truncation) against history-first flattening.
    # Do not filter by Shop/driver here: inconsistent evidence must redact.
    current = select(
        assignment.company_id, assignment.shortage_id, assignment.driver_id,
        assignment.vehicle_id, assignment.approved_base,
    ).where(
        assignment.company_id == pending.c.company_id,
        assignment.visit_id == pending.c.id,
    ).correlate(pending).offset(0).lateral("current_urgent_assignment")
    # Keep the Pending key scan narrow so the composite index covers it.
    # Fetch Visit evidence only for a matching live assignment, not for
    # unrelated Visits or terminal history. The composite key is unique.
    evidence = select(
        Visit.shop_id, Visit.driver_id.label("visit_driver_id"),
        Visit.is_emergency, Visit.work_session_id,
    ).where(
        Visit.company_id == current.c.company_id,
        Visit.id == pending.c.id,
    ).correlate(current, pending).limit(1).lateral("current_urgent_visit_evidence")
    # Freeze the live assignment set BEFORE joining visible demands. This
    # prevents planner join reordering from multiplying probes by demand count.
    live = select(
        current.c.company_id, current.c.shortage_id, current.c.driver_id,
        current.c.vehicle_id, current.c.approved_base,
        evidence.c.shop_id, evidence.c.visit_driver_id,
        evidence.c.is_emergency, evidence.c.work_session_id,
    ).select_from(pending).join(current, true()).join(evidence, true()).cte(
        "current_pending_assignments",
    ).prefix_with("MATERIALIZED")
    valid = and_(
        live.c.shop_id == visible.c.shop_id,
        live.c.visit_driver_id == live.c.driver_id,
        live.c.is_emergency.is_(True),
        or_(visible.c.driver_id.is_(None), visible.c.driver_id == live.c.driver_id),
        live.c.approved_base > 0,
        vehicle_filter(access, "dispatch.read", live.c.vehicle_id),
    )
    if not company_directory:
        valid = and_(valid, select(1).select_from(DispatchRoute).where(
            DispatchRoute.company_id == access.company_id,
            DispatchRoute.driver_id == live.c.driver_id,
            DispatchRoute.vehicle_id == live.c.vehicle_id,
            DispatchRoute.status == "active",
            or_(live.c.work_session_id.is_(None),
                DispatchRoute.work_session_id == live.c.work_session_id),
            route_filter(access, "dispatch.read"),
        ).exists())
    return select(
        live.c.shortage_id.label("shortage_id"),
        func.sum(live.c.approved_base).label("active_base"),
        func.bool_and(func.coalesce(valid, False)).label("evidence_allowed"),
    ).select_from(live).join(
        visible, and_(visible.c.company_id == live.c.company_id,
                      visible.c.id == live.c.shortage_id),
    ).where(
        visible.c.fulfillment_version == 1,
    ).group_by(live.c.shortage_id).subquery("pending_shortage_urgent")


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
