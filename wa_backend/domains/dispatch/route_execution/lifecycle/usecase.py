"""M02 transaction orchestration; M01 owns period/custody persistence.

The store implementation is deliberately a *strict required* capability.
Until M01 is merged and the actual tenant-safe model/index contract is known,
this use case is not exposed as an unsafe legacy command. There is no fallback
to mutating DispatchRoute driver/vehicle or InventoryBalance.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from services import begin_idempotent_operation, complete_idempotent_operation

from .intent import RouteLifecycleIntent, lifecycle_request_hash
from .policy import LifecycleDecision, RouteLifecycleState, decide_lifecycle

OPERATION = "DISPATCH_ROUTE_LIFECYCLE_M02"


class LifecycleStore(Protocol):
    async def lock_authorized_state(
        self, db: AsyncSession, *, company_id: int, route_id: int,
        intent: RouteLifecycleIntent,
    ) -> RouteLifecycleState:
        """Lock canonical route/session/zone/driver/vehicle/M01 periods/epochs.

        Revalidate tenant FKs + dynamic FIELD assignment + custody + current
        read/execute location grants. Acquire locks in documented sorted order.
        An uncertain historical 'needs_review' identity MUST fail closed.
        """
        ...

    async def assert_live_resource_guards(
        self, db: AsyncSession, *, state: RouteLifecycleState,
        decision: LifecycleDecision,
    ) -> None:
        """Check and reserve zone+live driver/vehicle via actual DB partial guards.

        Postpone retains zone reservation but makes driver/vehicle assignable.
        Resume must be denied on a conflicting live period or wrong custodian.
        """
        ...

    async def persist_transition(
        self, db: AsyncSession, *, state: RouteLifecycleState,
        decision: LifecycleDecision, intent: RouteLifecycleIntent, actor_id: int,
    ) -> None:
        """CAS route revision; close/create period; audit; preserve completed visits.

        No InventoryBalance, InventoryMovement, physical custody or financial
        value changes are permitted as a side effect.
        """
        ...


async def execute_route_lifecycle(
    db: AsyncSession, *, company_id: int, route_id: int, actor_id: int,
    intent: RouteLifecycleIntent, store: LifecycleStore,
    authorize_route: Callable[[int], Awaitable[None]],
    authorize_vehicle: Callable[[int], Awaitable[None]],
) -> dict[str, Any]:
    """One ACID intent, including its durable, exact-payload replay receipt.

    Replays must re-check *current* route and destination-vehicle authority.
    Postpone and close have no target car; they cannot silently hand custody to
    any other driver. A 409 from M01 store/partial indexes is never softened.
    """
    if company_id <= 0 or route_id <= 0 or actor_id <= 0:
        raise ValueError("Invalid company/route/actor identity")
    await authorize_route(route_id)
    if intent.action == "RESUME":
        assert intent.target_vehicle_id is not None
        await authorize_vehicle(intent.target_vehicle_id)
    record, original = await begin_idempotent_operation(
        db, company_id=company_id, actor_id=actor_id,
        operation=OPERATION, request_id=str(intent.request_id),
        request_hash=lifecycle_request_hash(route_id, intent),
    )
    if original is not None:
        if (
            original.get("request_id") != str(intent.request_id)
            or original.get("route_id") != route_id
            or original.get("state") != "COMMITTED"
            or original.get("action") != intent.action
            or type(original.get("context_revision")) is not int
        ):
            raise RuntimeError("Corrupt lifecycle idempotency receipt")
        await db.rollback()  # release UUID lock; replay has no side effects
        return original

    try:
        state = await store.lock_authorized_state(
            db, company_id=company_id, route_id=route_id, intent=intent,
        )
        if state.company_id != company_id or state.route_id != route_id:
            raise RuntimeError("Lifecycle store returned an inconsistent tenant or route")
        decision = decide_lifecycle(state, intent)
        await store.assert_live_resource_guards(db, state=state, decision=decision)
        await store.persist_transition(
            db, state=state, decision=decision, intent=intent, actor_id=actor_id,
        )
        # Force PG unique/tenant FK/CAS violations in the SAME atomic commit
        # as the immutable idempotency receipt.
        await db.flush()
        response = {
            "state": "COMMITTED",
            "request_id": str(intent.request_id),
            "route_id": route_id,
            "action": intent.action,
            "status": decision.status,
            "context_revision": decision.next_context_revision,
            "zone_reserved": decision.zone_reserved,
            "live_assets_reserved": decision.live_assets_reserved,
        }
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except BaseException:
        await db.rollback()
        raise
