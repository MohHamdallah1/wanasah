"""M02 database-backed lifecycle transition on M01's verified period/epoch schema.

All M01 imports are deliberately local until #940 is merged. Never use the
legacy route's last driver/vehicle as the *current* physical custody authority.
This module does NOT import inventory mutation services or write stock.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    DispatchRoute, DomainAuditEvent, InventoryLocation, RouteCommercialContext,
    WorkSession, Zone,
)
from domains.dispatch_representatives import has_canonical_field_identity
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.vehicles.eligibility import vehicle_is_operational

from .intent import RouteLifecycleIntent, lifecycle_request_hash
from .policy import LifecycleConflict, LifecycleDecision, RouteLifecycleState
from .resource_locks import LockedRouteResources, lock_route_resources


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class M01RouteLifecycleStore:
    """One-use, one-DB-transaction adapter. Caller commits via usecase only.

    Tenant, auth and dynamic assignment are separate checks; RLS is an
    additional DB boundary, never an alternative to access.require().
    """

    def __init__(self, *, actor_principal_id: int):
        if type(actor_principal_id) is not int or actor_principal_id <= 0:
            raise ValueError("Canonical Backoffice principal id required")
        self.actor_principal_id = actor_principal_id
        self.resources: LockedRouteResources | None = None
        self.period = None
        self.target_rep_id: int | None = None
        self.target_session: WorkSession | None = None
        self.vehicle_location_id: int | None = None
        self.custody = None

    async def lock_authorized_state(
        self, db: AsyncSession, *, company_id: int, route_id: int,
        intent: RouteLifecycleIntent,
    ) -> RouteLifecycleState:
        # M01 schema is required: importing a missing table fails loudly rather
        # than allowing an unsafe non-epoch legacy fallback.
        from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
        from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch

        # Pre-read only for global lock order, NOT authorization. PAUSE must
        # lock the CURRENT period's real representative and vehicle, rather
        # than historic DispatchRoute.driver_id/vehicle_id after A->B.
        # All four identifiers are rechecked after acquiring row locks.
        maybe_periods = (await db.execute(
            select(DispatchRouteExecutionPeriod.id,
                   DispatchRouteExecutionPeriod.work_session_id,
                   DispatchRouteExecutionPeriod.driver_id,
                   DispatchRouteExecutionPeriod.vehicle_id).where(
                DispatchRouteExecutionPeriod.company_id == company_id,
                DispatchRouteExecutionPeriod.route_id == route_id,
                DispatchRouteExecutionPeriod.ended_at.is_(None),
                DispatchRouteExecutionPeriod.state.in_(("PLANNED", "ACTIVE")),
            ).order_by(DispatchRouteExecutionPeriod.id.asc())
        )).all()
        if len(maybe_periods) > 1:
            raise LifecycleConflict("MULTIPLE_LIVE_PERIODS")
        pre_current = maybe_periods[0] if (
            maybe_periods and (intent.action == "PAUSE" or intent.action == "RESUME")
        ) else None
        resources = await lock_route_resources(
            db, company_id=company_id, route_id=route_id,
            target_driver_id=(int(pre_current.driver_id) if pre_current is not None
                              else intent.target_driver_id),
            target_vehicle_id=(int(pre_current.vehicle_id) if pre_current is not None
                               else intent.target_vehicle_id),
            additional_session_ids=tuple(sorted(
                int(row.work_session_id) for row in maybe_periods
                if row.work_session_id is not None
            )),
        )
        self.resources = resources
        route = resources.route
        current = (
            await db.execute(
                select(DispatchRouteExecutionPeriod).where(
                    DispatchRouteExecutionPeriod.company_id == company_id,
                    DispatchRouteExecutionPeriod.route_id == route_id,
                    DispatchRouteExecutionPeriod.ended_at.is_(None),
                    DispatchRouteExecutionPeriod.state.in_(("PLANNED", "ACTIVE")),
                ).order_by(DispatchRouteExecutionPeriod.id.asc()).with_for_update()
            )
        ).scalars().all()
        if len(current) > 1:
            raise LifecycleConflict("MULTIPLE_LIVE_PERIODS")
        self.period = current[0] if current else None
        if (intent.action == "PAUSE" or (intent.action == "RESUME" and route.status == "waiting")) and (
            pre_current is None or self.period is None or
            int(self.period.id) != int(pre_current.id) or
            self.period.driver_id != pre_current.driver_id or
            self.period.vehicle_id != pre_current.vehicle_id or
            self.period.work_session_id != pre_current.work_session_id
        ):
            raise LifecycleConflict("ROUTE_PAUSE_PERIOD_CHANGED_CONCURRENTLY")
        if self.period is not None and (
            self.period.context_revision != route.assignment_context_revision
            or self.period.state not in ("PLANNED", "ACTIVE")
            or self.period.work_session_id not in (None, *resources.sessions.keys())
        ):
            raise LifecycleConflict("CURRENT_PERIOD_REVISION_MISMATCH")
        if self.period is not None:
            # The legacy route's S1 may be long settled while a new period is
            # PLANNED or bound to another active S2. Never fence the new
            # assignment using the historical route.work_session_id.
            current_session = (
                resources.sessions.get(int(self.period.work_session_id))
                if self.period.work_session_id is not None else None
            )
            if self.period.work_session_id is not None and (
                current_session is None
                or current_session.driver_id != self.period.driver_id
            ):
                raise LifecycleConflict("CURRENT_PERIOD_SESSION_MISMATCH")
        else:
            current_session = resources.session

        # Legacy rev 1 still has route driver+vehicle as the available
        # pre-M01 assignment, but can be POSTPONED with no fabricated
        # historical period or custody. After revision 1, only canonical
        # period epochs are allowed to resume/postpone.
        legacy_live = (
            self.period is None
            and route.assignment_context_revision == 1
            and route.status in ("active", "waiting")
            and route.driver_id is not None
            and route.vehicle_id is not None
        )

        self.target_rep_id = None
        self.target_session = None
        self.vehicle_location_id = None
        self.custody = None
        if intent.action == "PAUSE":
            # A signed period must retain the SAME genuine accepted M01 vehicle
            # custody. An already-historic or reassigned epoch cannot be cloned.
            if self.period is None or (
                self.period.field_representative_id is None or
                self.period.vehicle_location_id is None or
                self.period.request_id is None or self.period.payload_hash is None
            ):
                raise LifecycleConflict("ROUTE_PAUSE_SIGNED_PROOF_MISSING")
            epochs = (await db.execute(
                select(VehicleCustodyEpoch).where(
                    VehicleCustodyEpoch.company_id == company_id,
                    VehicleCustodyEpoch.vehicle_id == self.period.vehicle_id,
                    VehicleCustodyEpoch.ended_at.is_(None),
                ).order_by(VehicleCustodyEpoch.id.asc()).with_for_update()
            )).scalars().all()
            if len(epochs) != 1:
                raise LifecycleConflict("ROUTE_PAUSE_CUSTODY_UNVERIFIED")
            custody = epochs[0]
            if (
                custody.state != "ACCEPTED" or
                custody.custodian_kind != "FIELD_REPRESENTATIVE" or
                custody.vehicle_location_id != self.period.vehicle_location_id or
                custody.field_representative_id != self.period.field_representative_id or
                custody.accepted_by_principal_id is None or
                custody.request_id is None or custody.payload_hash is None
            ):
                raise LifecycleConflict("ROUTE_PAUSE_CUSTODY_CHANGED")
        if intent.action == "RESUME":
            driver_id = intent.target_driver_id
            vehicle_id = intent.target_vehicle_id
            if driver_id not in resources.canonical_field_driver_ids:
                raise LifecycleConflict("TARGET_REPRESENTATIVE_IDENTITY_REQUIRED")
            driver = resources.drivers.get(driver_id)
            vehicle = resources.vehicles.get(vehicle_id)
            if driver is None or not driver.is_active:
                raise LifecycleConflict("TARGET_REPRESENTATIVE_INACTIVE")
            if not vehicle_is_operational(vehicle):
                raise LifecycleConflict("TARGET_VEHICLE_INACTIVE")

            # Legacy Driver is merely an operational locator; field profile
            # and principal are resolved from the exact tenant bridge.
            row = (
                await db.execute(
                    select(
                        IdentityLegacyDriverMap.field_representative_id,
                        IdentityLegacyDriverMap.field_principal_id,
                    ).where(
                        IdentityLegacyDriverMap.company_id == company_id,
                        IdentityLegacyDriverMap.legacy_driver_id == driver_id,
                        has_canonical_field_identity(
                            company_id=company_id, legacy_driver_id=driver_id,
                        ),
                    )
                )
            ).one_or_none()
            if row is None or row.field_representative_id is None:
                raise LifecycleConflict("TARGET_FIELD_IDENTITY_UNVERIFIED")
            self.target_rep_id = int(row.field_representative_id)
            field_principal_id = int(row.field_principal_id)

            # A valid identity mapping alone does not grant operational
            # capability. Reuse the persisted FIELD role engine, including
            # role-revoke/auth_revision checks, before admitting an assignment.
            from domains.auth_sessions.context import FieldRequestContext
            from domains.authorization.field_access import (
                FieldCapabilityAccess, FieldCapabilityAccessRejected,
            )
            from domains.identity.models import CompanyPrincipal
            principal = await db.scalar(
                select(CompanyPrincipal).where(
                    CompanyPrincipal.company_id == company_id,
                    CompanyPrincipal.id == field_principal_id,
                    CompanyPrincipal.is_active.is_(True),
                )
            )
            if principal is None:
                raise LifecycleConflict("TARGET_FIELD_PRINCIPAL_INACTIVE")
            try:
                await FieldCapabilityAccess(
                    db,
                    FieldRequestContext(
                        principal_id=field_principal_id,
                        company_id=company_id,
                        representative_id=self.target_rep_id,
                        auth_revision=int(principal.auth_revision),
                    ),
                ).require_all(("work_session.execute", "visit.execute"))
            except FieldCapabilityAccessRejected as exc:
                raise LifecycleConflict("TARGET_FIELD_CAPABILITY_MISSING") from exc

            # Vehicle location is physical truth; never select arbitrary
            # active or historical duplicate locations for the same car.
            locations = (
                await db.execute(
                    select(InventoryLocation).where(
                        InventoryLocation.company_id == company_id,
                        InventoryLocation.vehicle_id == vehicle_id,
                        InventoryLocation.location_type == "VEHICLE",
                    ).order_by(InventoryLocation.id.asc()).with_for_update()
                )
            ).scalars().all()
            if len(locations) != 1 or not locations[0].is_active:
                raise LifecycleConflict("VEHICLE_LOCATION_NOT_UNIQUE_AND_ACTIVE")
            self.vehicle_location_id = int(locations[0].id)

            epochs = (
                await db.execute(
                    select(VehicleCustodyEpoch).where(
                        VehicleCustodyEpoch.company_id == company_id,
                        VehicleCustodyEpoch.vehicle_id == vehicle_id,
                        VehicleCustodyEpoch.ended_at.is_(None),
                    ).order_by(VehicleCustodyEpoch.id.asc()).with_for_update()
                )
            ).scalars().all()
            if len(epochs) > 1:
                raise LifecycleConflict("CURRENT_CUSTODY_NOT_UNIQUE")
            self.custody = epochs[0] if epochs else None
            if self.custody is not None and self.custody.vehicle_location_id != self.vehicle_location_id:
                raise LifecycleConflict("CUSTODY_LOCATION_MISMATCH")
            self.target_session = resources.target_session
            if self.target_session is not None:
                if self.target_session.is_settled:
                    raise LifecycleConflict("TARGET_SESSION_SETTLED")
                if self.target_session.end_time is not None:
                    raise LifecycleConflict("TARGET_SESSION_ENDED")

            custody_matches = bool(
                self.custody is not None
                and self.custody.state == "ACCEPTED"
                and self.custody.custodian_kind == "FIELD_REPRESENTATIVE"
                and self.custody.custodian_principal_id == field_principal_id
                and self.custody.field_representative_id == self.target_rep_id
                and self.custody.accepted_by_principal_id is not None
                and self.custody.request_id is not None
                and self.custody.payload_hash is not None
            )
        else:
            custody_matches = False

        bound_session = current_session
        if self.period is not None:
            live_driver_id = self.period.driver_id
            live_vehicle_id = self.period.vehicle_id
        else:
            live_driver_id = route.driver_id if legacy_live else None
            live_vehicle_id = route.vehicle_id if legacy_live else None
        return RouteLifecycleState(
            route_id=route_id, company_id=company_id, zone_id=int(route.zone_id),
            status=str(route.status), context_revision=int(route.assignment_context_revision),
            open_period_id=int(self.period.id) if self.period is not None else None,
            active_driver_id=live_driver_id, active_vehicle_id=live_vehicle_id,
            work_session_id=int(route.work_session_id) if route.work_session_id is not None else None,
            work_session_settled=bool(bound_session and bound_session.is_settled),
            target_vehicle_custody_revision=(
                int(self.custody.context_revision) if self.custody is not None else None
            ),
            target_vehicle_custody_accepted=bool(self.custody and self.custody.state == "ACCEPTED"),
            target_vehicle_custody_matches_target=custody_matches,
            legacy_live_without_period=legacy_live,
            zone_active=bool(resources.zone.is_active),
        )

    async def assert_live_resource_guards(
        self, db: AsyncSession, *, state: RouteLifecycleState,
        decision: LifecycleDecision,
    ) -> None:
        from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
        if self.resources is None:
            raise RuntimeError("Lifecycle DB resources not locked")
        if not decision.zone_reserved:
            return
        zone_conflict = await db.scalar(
            select(DispatchRoute.id).where(
                DispatchRoute.company_id == state.company_id,
                DispatchRoute.id != state.route_id,
                DispatchRoute.zone_id == state.zone_id,
                DispatchRoute.status.in_(("active", "waiting", "postponed")),
            ).limit(1)
        )
        if zone_conflict is not None:
            raise LifecycleConflict("ZONE_RESERVED_BY_OTHER_ROUTE")
        if not decision.live_assets_reserved:
            return

        driver_id = decision.open_period_driver_id
        vehicle_id = decision.open_period_vehicle_id
        # Both legacy routes (no canonical period) and new period-backed
        # routes are protected. Destination Driver/Vehicle rows are already
        # FOR UPDATE locked, matching the old route-launch lock order.
        legacy = await db.scalar(
            select(DispatchRoute.id).where(
                DispatchRoute.company_id == state.company_id,
                DispatchRoute.id != state.route_id,
                DispatchRoute.status.in_(("active", "waiting")),
                DispatchRoute.assignment_context_revision == 1,
                or_(DispatchRoute.driver_id == driver_id,
                    DispatchRoute.vehicle_id == vehicle_id),
            ).limit(1)
        )
        if legacy is not None:
            raise LifecycleConflict("LIVE_LEGACY_ASSIGNMENT_CONFLICT")
        canonical = await db.scalar(
            select(DispatchRouteExecutionPeriod.id).where(
                DispatchRouteExecutionPeriod.company_id == state.company_id,
                DispatchRouteExecutionPeriod.ended_at.is_(None),
                DispatchRouteExecutionPeriod.state.in_(("PLANNED", "ACTIVE")),
                or_(DispatchRouteExecutionPeriod.driver_id == driver_id,
                    DispatchRouteExecutionPeriod.vehicle_id == vehicle_id),
                # A PAUSE closes/replaces THIS precise period with the same
                # signed assets; it does not conflict with its own source.
                *([DispatchRouteExecutionPeriod.id != state.open_period_id]
                  if decision.end_period_id is not None else []),
            ).limit(1)
        )
        if canonical is not None:
            raise LifecycleConflict("LIVE_PERIOD_ASSIGNMENT_CONFLICT")

    async def persist_transition(
        self, db: AsyncSession, *, state: RouteLifecycleState,
        decision: LifecycleDecision, intent: RouteLifecycleIntent, actor_id: int,
    ) -> None:
        from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
        from services import get_company_local_date
        if self.resources is None or self.resources.route.id != decision.route_id:
            raise RuntimeError("Lifecycle transition requires locked same-route state")
        route = self.resources.route
        if route.assignment_context_revision != state.context_revision:
            raise LifecycleConflict("ROUTE_CONTEXT_REVISION_STALE")
        now = _utc_naive()

        if decision.end_period_id is not None:
            if self.period is None or self.period.id != decision.end_period_id:
                raise LifecycleConflict("ROUTE_PERIOD_STALE")
            if self.period.ended_at is not None:
                raise LifecycleConflict("ROUTE_PERIOD_ALREADY_CLOSED")
            self.period.ended_at = now
            self.period.ended_by_principal_id = self.actor_principal_id
            self.period.state = "CLOSED"
            self.period.reason = intent.action

        if decision.open_period_driver_id is not None:
            if intent.action == "PAUSE" or (
                intent.action == "RESUME" and state.status == "waiting"
            ):
                if self.period is None or decision.end_period_id != self.period.id:
                    raise LifecycleConflict("ROUTE_PAUSE_PERIOD_STALE")
                if (not self.period.field_representative_id or
                    not self.period.vehicle_location_id or
                    not self.period.commercial_context_id or
                    not self.period.request_id or not self.period.payload_hash or
                    self.period.driver_id != decision.open_period_driver_id or
                    self.period.vehicle_id != decision.open_period_vehicle_id):
                    raise LifecycleConflict("ROUTE_PAUSE_SIGNED_PROOF_MISSING")
                if intent.action == "RESUME":
                    # The client supplies exact signed current custody, not an
                    # old legacy route car. No reassignment during UNPAUSE.
                    if (self.target_rep_id != self.period.field_representative_id or
                        self.vehicle_location_id != self.period.vehicle_location_id or
                        self.custody is None or self.custody.state != "ACCEPTED"):
                        raise LifecycleConflict("PAUSED_ROUTE_CUSTODY_CHANGED")
                    current_session = (
                        self.resources.sessions.get(int(self.period.work_session_id))
                        if self.period.work_session_id is not None else None
                    )
                    if current_session and current_session.end_time is not None:
                        raise LifecycleConflict("PAUSED_SESSION_ALREADY_ENDED")
                # No custody transfer, new WorkSession, or implicit stock move.
                # A new signed period is essential: historical Visit foreign
                # keys reference the prior (period_id, context_revision), so
                # mutating that revision would corrupt signed visit evidence.
                new_driver = int(self.period.driver_id)
                new_rep = int(self.period.field_representative_id)
                new_vehicle = int(self.period.vehicle_id)
                new_location = int(self.period.vehicle_location_id)
                new_session = self.period.work_session_id
                new_commercial = int(self.period.commercial_context_id)
                new_state = "ACTIVE" if new_session is not None else "PLANNED"
                # Flush CLOSED before INSERT so unique live-driver/vehicle
                # period guards never see two live periods in our own txn.
                await db.flush()
                db.add(DispatchRouteExecutionPeriod(
                    company_id=state.company_id, route_id=state.route_id,
                    work_session_id=new_session,
                    driver_id=new_driver, field_representative_id=new_rep,
                    vehicle_id=new_vehicle, vehicle_location_id=new_location,
                    commercial_context_id=new_commercial, state=new_state,
                    context_revision=decision.next_context_revision,
                    started_at=now, started_by_principal_id=self.actor_principal_id,
                    request_id=str(intent.request_id),
                    payload_hash=lifecycle_request_hash(state.route_id, intent),
                    reason=intent.action,
                ))
            else:
                if self.target_rep_id is None or self.vehicle_location_id is None:
                    raise LifecycleConflict("DESTINATION_AUTHORITY_UNVERIFIED")
                from models import RouteCommercialContext
                commercial = await db.scalar(
                    select(RouteCommercialContext.id).where(
                        RouteCommercialContext.company_id == state.company_id,
                        RouteCommercialContext.dispatch_route_id == state.route_id,
                    )
                )
                if commercial is None:
                    raise LifecycleConflict("COMMERCIAL_CONTEXT_NOT_PUBLISHED")
                db.add(DispatchRouteExecutionPeriod(
                    company_id=state.company_id, route_id=state.route_id,
                    work_session_id=(
                        int(self.target_session.id) if self.target_session else None
                    ),
                    driver_id=decision.open_period_driver_id,
                    field_representative_id=self.target_rep_id,
                    vehicle_id=decision.open_period_vehicle_id,
                    vehicle_location_id=self.vehicle_location_id,
                    commercial_context_id=int(commercial),
                    state="ACTIVE" if self.target_session else "PLANNED",
                    context_revision=decision.next_context_revision,
                    started_at=now, started_by_principal_id=self.actor_principal_id,
                    request_id=str(intent.request_id),
                    payload_hash=lifecycle_request_hash(state.route_id, intent),
                    reason="RESUME",
                ))

        # Keep legacy route's work_session_id/driver/vehicle as READ-ONLY
        # historical link when a session is bound: its composite tenant FK
        # prevents rewriting driver_id to another person's session. The new
        # period is the CURRENT assignment truth. M03/05 will consume that.
        if (intent.action == "RESUME" and self.resources.session is None
                and decision.open_period_driver_id is not None):
            route.driver_id = decision.open_period_driver_id
            route.vehicle_id = decision.open_period_vehicle_id
            # Old vehicle load plans are NOT stock: a separate explicit
            # load-plan read/reconciliation will be required by M05.
            route.adjustment_context_revision += 1

        route.status = decision.status
        route.assignment_context_revision = decision.next_context_revision
        if decision.schedule_zone_next:
            zone = self.resources.zone
            company_date = await get_company_local_date(db, state.company_id)
            if zone.start_date is not None and zone.interval_days is not None:
                from datetime import timedelta
                zone.start_date = company_date + timedelta(days=int(zone.interval_days))

        db.add(DomainAuditEvent(
            company_id=state.company_id,
            event_type=f"DISPATCH_ROUTE_{intent.action}",
            entity_type="DISPATCH_ROUTE",
            entity_id=str(state.route_id),
            actor_user_id=None,
            actor_context={
                "backoffice_principal_id": self.actor_principal_id,
                "request_id": str(intent.request_id),
                "from_revision": state.context_revision,
                "to_revision": decision.next_context_revision,
                "period_closed": decision.end_period_id,
                "assignment_driver_id": decision.open_period_driver_id,
                "assignment_vehicle_id": decision.open_period_vehicle_id,
            },
            reason_code="M02_ROUTE_LIFECYCLE",
            request_id=intent.request_id,
            before_snapshot={
                "status": state.status,
                "assignment_context_revision": state.context_revision,
                "live_period_id": state.open_period_id,
            },
            after_snapshot={
                "status": decision.status,
                "assignment_context_revision": decision.next_context_revision,
                "zone_reserved": decision.zone_reserved,
                "live_assets_reserved": decision.live_assets_reserved,
            },
            schema_version=1,
        ))
