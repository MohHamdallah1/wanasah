"""Pure M02 atomic transition invariants, independent of M01 ORM naming.

The database adapter MUST lock and verify the actual M01 period/custody epochs,
tenant FKs, capability+scope and live resource uniqueness before using a plan.
This code never edits a Visit, commercial evidence or physical InventoryBalance.
"""
from __future__ import annotations

from dataclasses import dataclass

from .intent import RouteLifecycleIntent


class LifecycleConflict(ValueError):
    """Fail-closed business conflict; the HTTP adapter maps this to 409."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RouteLifecycleState:
    route_id: int
    company_id: int
    zone_id: int
    status: str
    context_revision: int
    # Current operational period, NEVER the last historic completed period.
    open_period_id: int | None
    active_driver_id: int | None
    active_vehicle_id: int | None
    # A historical WorkSession is not proof that a live period is open.
    work_session_id: int | None
    work_session_settled: bool
    # Current vehicle epoch for the requested destination, not source.
    target_vehicle_custody_revision: int | None
    target_vehicle_custody_accepted: bool
    # M01 canonical FieldRepresentative owner/accepted handoff must match
    # the requested representative. A vehicle epoch held by somebody ELSE
    # is NOT permission to assign its loaded physical location to this actor.
    target_vehicle_custody_matches_target: bool = False
    zone_active: bool = True


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    route_id: int
    company_id: int
    zone_id: int
    old_status: str
    status: str
    next_context_revision: int
    # M01 period commands are executed transactionally with the route row.
    end_period_id: int | None
    open_period_driver_id: int | None
    open_period_vehicle_id: int | None
    zone_reserved: bool
    live_assets_reserved: bool
    # The zone's future date is advanced by its authoritative local calendar.
    # Scheduling a later visit creates a SEPARATE route ID; never recycle this.
    schedule_zone_next: bool = False

    @property
    def inventory_movements(self) -> tuple[()]:
        """Route status/assignment must NEVER write stock or attribute stock."""
        return ()


def decide_lifecycle(
    state: RouteLifecycleState,
    intent: RouteLifecycleIntent,
) -> LifecycleDecision:
    if state.context_revision < 1 or state.context_revision != intent.expected_context_revision:
        raise LifecycleConflict("ROUTE_CONTEXT_REVISION_STALE")
    if state.status not in {"active", "waiting", "postponed", "closed"}:
        raise LifecycleConflict("ROUTE_STATUS_INVALID")
    if state.context_revision >= 2**63 - 1:
        raise LifecycleConflict("ROUTE_CONTEXT_REVISION_EXHAUSTED")

    if intent.action == "POSTPONE":
        if state.work_session_settled:
            raise LifecycleConflict("SESSION_ALREADY_SETTLED")
        if state.status not in {"active", "waiting"}:
            raise LifecycleConflict("ROUTE_NOT_LIVE")
        if state.open_period_id is None:
            raise LifecycleConflict("ROUTE_LIVE_PERIOD_MISSING")
        if intent.expected_period_id != state.open_period_id:
            raise LifecycleConflict("ROUTE_PERIOD_STALE")
        if state.active_driver_id is None or state.active_vehicle_id is None:
            raise LifecycleConflict("ROUTE_LIVE_ASSIGNMENT_MISSING")
        # Closing a live period releases operational route assignment only.
        # Vehicle physical custody remains independently owned by M01 epochs.
        return LifecycleDecision(
            route_id=state.route_id, company_id=state.company_id,
            zone_id=state.zone_id, old_status=state.status, status="postponed",
            next_context_revision=state.context_revision + 1,
            end_period_id=state.open_period_id,
            open_period_driver_id=None, open_period_vehicle_id=None,
            zone_reserved=True, live_assets_reserved=False,
        )

    if intent.action == "RESUME":
        if state.status != "postponed":
            raise LifecycleConflict("ROUTE_NOT_POSTPONED")
        # A route postponed yesterday may resume under a NEW period/day, even
        # when its historical legacy WorkSession has been financially settled.
        # M01 must verify the target period/session rather than reusing S1.
        if state.open_period_id is not None:
            raise LifecycleConflict("ROUTE_ALREADY_HAS_LIVE_PERIOD")
        if intent.expected_period_id is not None:
            # A historical period is not an open period and must not be
            # silently accepted as a target for assignment.
            raise LifecycleConflict("ROUTE_PERIOD_STALE")
        if not state.zone_active:
            raise LifecycleConflict("ZONE_ARCHIVED")
        if state.target_vehicle_custody_revision is None:
            raise LifecycleConflict("VEHICLE_CUSTODY_UNVERIFIED")
        if intent.expected_vehicle_custody_revision != state.target_vehicle_custody_revision:
            raise LifecycleConflict("VEHICLE_CUSTODY_REVISION_STALE")
        if not state.target_vehicle_custody_accepted:
            # Approval from real custody is mandatory even for an empty car.
            raise LifecycleConflict("VEHICLE_CUSTODY_ACCEPTANCE_REQUIRED")
        if not state.target_vehicle_custody_matches_target:
            raise LifecycleConflict("VEHICLE_CUSTODIAN_MISMATCH")
        return LifecycleDecision(
            route_id=state.route_id, company_id=state.company_id,
            zone_id=state.zone_id, old_status=state.status, status="active",
            next_context_revision=state.context_revision + 1,
            end_period_id=None,
            open_period_driver_id=intent.target_driver_id,
            open_period_vehicle_id=intent.target_vehicle_id,
            zone_reserved=True, live_assets_reserved=True,
        )

    if intent.action == "CLOSE":
        if state.open_period_id is not None and state.work_session_settled:
            raise LifecycleConflict("SESSION_ALREADY_SETTLED")
        if state.status == "closed":
            # Identical retry is resolved by the durable operation receipt,
            # not by unversioned state-idempotence which hides changed intent.
            raise LifecycleConflict("ROUTE_ALREADY_CLOSED")
        if state.open_period_id is not None:
            if intent.expected_period_id != state.open_period_id:
                raise LifecycleConflict("ROUTE_PERIOD_STALE")
        elif intent.expected_period_id is not None:
            raise LifecycleConflict("ROUTE_PERIOD_STALE")
        return LifecycleDecision(
            route_id=state.route_id, company_id=state.company_id,
            zone_id=state.zone_id, old_status=state.status, status="closed",
            next_context_revision=state.context_revision + 1,
            end_period_id=state.open_period_id,
            open_period_driver_id=None, open_period_vehicle_id=None,
            zone_reserved=False, live_assets_reserved=False,
            schedule_zone_next=True,
        )
    raise LifecycleConflict("ROUTE_ACTION_UNSUPPORTED")
