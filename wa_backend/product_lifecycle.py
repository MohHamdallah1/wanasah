"""Central product lifecycle capabilities, guards, blockers and domain evidence."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import DomainAuditEvent, ProductVariant, TransactionalOutbox, utc_now


STRUCTURE_EDIT = "STRUCTURE_EDIT"
METADATA_EDIT = "METADATA_EDIT"
INBOUND_NEW = "INBOUND_NEW"
INBOUND_COMPLETE = "INBOUND_COMPLETE"
REPLENISHMENT_NEW = "REPLENISHMENT_NEW"
ROUTE_LOAD_NEW = "ROUTE_LOAD_NEW"
ROUTE_SALE_OPEN = "ROUTE_SALE_OPEN"
WAREHOUSE_BALANCING = "WAREHOUSE_BALANCING"
ROUTE_RETURN = "ROUTE_RETURN"
STOCKTAKE = "STOCKTAKE"
RECONCILIATION = "RECONCILIATION"
RETURN_DISPOSAL = "RETURN_DISPOSAL"
HISTORY = "HISTORY"

_LIFECYCLE_CAPABILITIES = {
    "DRAFT": frozenset({STRUCTURE_EDIT, METADATA_EDIT, HISTORY}),
    "ACTIVE": frozenset({
        METADATA_EDIT, INBOUND_NEW, INBOUND_COMPLETE, REPLENISHMENT_NEW,
        ROUTE_LOAD_NEW, ROUTE_SALE_OPEN, WAREHOUSE_BALANCING, ROUTE_RETURN,
        STOCKTAKE, RECONCILIATION, RETURN_DISPOSAL, HISTORY,
    }),
    "RETIRING": frozenset({
        METADATA_EDIT, INBOUND_COMPLETE, ROUTE_SALE_OPEN, ROUTE_RETURN,
        STOCKTAKE, RECONCILIATION, RETURN_DISPOSAL, HISTORY,
    }),
    "ARCHIVED": frozenset({HISTORY}),
}

_HOLD_BLOCKS = {
    "NONE": frozenset(),
    "SALES_HOLD": frozenset({ROUTE_SALE_OPEN, ROUTE_LOAD_NEW, REPLENISHMENT_NEW}),
    "RECALL": frozenset({INBOUND_NEW, REPLENISHMENT_NEW, ROUTE_LOAD_NEW, ROUTE_SALE_OPEN, WAREHOUSE_BALANCING}),
}

_STARTED_DOCUMENT_OPERATIONS = frozenset({
    INBOUND_COMPLETE, ROUTE_RETURN, STOCKTAKE, RECONCILIATION, RETURN_DISPOSAL,
})

PRODUCT_LOCATION_FLAG_KEYS = frozenset({"inbound_enabled", "outbound_enabled"})
DEFAULT_PRODUCT_LOCATION_FLAGS = {"inbound_enabled": True, "outbound_enabled": True}


@dataclass(frozen=True)
class CapabilityDecision:
    allowed: bool
    code: str


class ProductLifecycleTransitionError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def apply_variant_publish_transition(
    row: ProductVariant,
    now: datetime,
) -> tuple[str, str]:
    if row.lifecycle_status != "DRAFT" or row.operational_hold != "NONE":
        raise ProductLifecycleTransitionError(
            "PRODUCT_PUBLISH_TRANSITION_INVALID",
            "النشر مسموح لمسودة غير موقوفة فقط.",
        )
    if (
        not str(row.sku or "").strip()
        or not str(row.name or "").strip()
        or row.base_uom_id is None
    ):
        raise ProductLifecycleTransitionError(
            "PRODUCT_PUBLISH_READINESS_FAILED",
            "هوية الصنف ووحدة الأساس غير مكتملة.",
        )
    if (
        row.lot_control_mode not in {"NONE", "OPTIONAL", "REQUIRED"}
        or row.expiry_control_mode not in {"NONE", "OPTIONAL", "REQUIRED"}
    ):
        raise ProductLifecycleTransitionError(
            "PRODUCT_PUBLISH_READINESS_FAILED",
            "سياسة الدفعة أو الصلاحية غير صالحة.",
        )
    row.lifecycle_status = "ACTIVE"
    row.published_at = now
    return (
        "ProductPublished",
        "تم نشر الصنف وأصبحت بنيته ثابتة.",
    )


def evaluate_product_capability(
    lifecycle_status: str,
    operational_hold: str,
    operation: str,
    *,
    document_started: bool = False,
) -> CapabilityDecision:
    lifecycle = str(lifecycle_status).upper()
    hold = str(operational_hold).upper()
    if lifecycle not in _LIFECYCLE_CAPABILITIES or hold not in _HOLD_BLOCKS:
        return CapabilityDecision(False, "PRODUCT_STATE_INVALID")
    if document_started and operation in _STARTED_DOCUMENT_OPERATIONS and lifecycle != "DRAFT":
        return CapabilityDecision(True, "IN_FLIGHT_TERMINAL_PATH")
    if operation not in _LIFECYCLE_CAPABILITIES[lifecycle]:
        return CapabilityDecision(False, f"PRODUCT_{lifecycle}_{operation}_BLOCKED")
    if operation in _HOLD_BLOCKS[hold]:
        return CapabilityDecision(False, f"PRODUCT_{hold}_{operation}_BLOCKED")
    return CapabilityDecision(True, "ALLOWED")


def product_capability_predicate(model: Any, operation: str):
    """SQL equivalent of the matrix for lists that start a new operation."""
    lifecycle_states = [
        lifecycle
        for lifecycle, capabilities in _LIFECYCLE_CAPABILITIES.items()
        if operation in capabilities
    ]
    blocked_holds = [
        hold for hold, operations in _HOLD_BLOCKS.items() if operation in operations
    ]
    predicates = [model.lifecycle_status.in_(lifecycle_states)]
    if blocked_holds:
        predicates.append(model.operational_hold.not_in(blocked_holds))
    return and_(*predicates)


def validate_product_location_flags(value: Any) -> dict[str, bool]:
    if not isinstance(value, dict) or set(value) != PRODUCT_LOCATION_FLAG_KEYS:
        raise ValueError("operational_flags must contain inbound_enabled and outbound_enabled only")
    if any(type(value[key]) is not bool for key in PRODUCT_LOCATION_FLAG_KEYS):
        raise ValueError("Product location flags must be booleans")
    return {key: value[key] for key in sorted(PRODUCT_LOCATION_FLAG_KEYS)}


def product_location_allows(flags: Any, operation: str) -> bool:
    try:
        normalized = validate_product_location_flags(flags)
    except ValueError:
        return False
    if operation == INBOUND_NEW:
        return normalized["inbound_enabled"]
    if operation in {ROUTE_LOAD_NEW, WAREHOUSE_BALANCING, REPLENISHMENT_NEW}:
        return normalized["outbound_enabled"]
    return True


async def acquire_product_lifecycle_guards(
    db: AsyncSession,
    company_id: int,
    variant_ids: Iterable[int],
    *,
    exclusive: bool,
) -> None:
    function = func.pg_advisory_xact_lock if exclusive else func.pg_advisory_xact_lock_shared
    for variant_id in sorted({int(value) for value in variant_ids}):
        key = f"product-lifecycle:{int(company_id)}:{variant_id}"
        await db.execute(select(function(func.hashtextextended(key, 0))))


def variant_snapshot(row: ProductVariant) -> dict[str, Any]:
    return {
        "id": row.id,
        "product_id": row.product_id,
        "sku": row.sku,
        "name": row.name,
        "lifecycle_status": row.lifecycle_status,
        "operational_hold": row.operational_hold,
        "lifecycle_revision": row.lifecycle_revision,
        "version": row.version,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "retired_at": row.retired_at.isoformat() if row.retired_at else None,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
    }


def record_domain_event(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    request_id: UUID,
    event_type: str,
    entity_type: str,
    entity_id: int,
    reason: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    emit_outbox: bool = True,
) -> None:
    now = utc_now()
    db.add(DomainAuditEvent(
        company_id=company_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        actor_user_id=actor_id,
        actor_context={"actor_type": "Driver", "source": "admin_api"},
        reason_code=event_type,
        reason_text=reason,
        request_id=request_id,
        before_snapshot=before,
        after_snapshot=after,
        schema_version=1,
        occurred_at=now,
    ))
    if emit_outbox:
        db.add(TransactionalOutbox(
            company_id=company_id,
            event_type=event_type,
            aggregate_type=entity_type,
            aggregate_id=str(entity_id),
            payload={
                "event_type": event_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "company_id": company_id,
                "request_id": str(request_id),
                "before": before,
                "after": after,
                "occurred_at": now.isoformat(),
            },
            schema_version=1,
            idempotency_key=f"{event_type}:{entity_type}:{entity_id}:{request_id}",
            status="PENDING",
            attempts=0,
            available_at=now,
        ))


async def archive_blockers(db: AsyncSession, company_id: int, variant_id: int) -> list[dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT blocker_code, total, first_id
        FROM (
            SELECT 'INVENTORY_BALANCE' blocker_code, count(*) total, min(id) first_id
            FROM inventory_balances
            WHERE company_id=:company_id AND product_variant_id=:variant_id
              AND (on_hand_quantity <> 0 OR reserved_quantity <> 0)
            UNION ALL
            SELECT 'PRODUCT_LOCATION', count(*), min(id)
            FROM product_locations
            WHERE company_id=:company_id AND product_variant_id=:variant_id
            UNION ALL
            SELECT 'STOCK_POLICY', count(*), min(id)
            FROM inventory_stock_policies
            WHERE company_id=:company_id AND product_variant_id=:variant_id AND is_active IS TRUE
            UNION ALL
            SELECT 'OPEN_TRANSFER', count(*), min(h.id)
            FROM inventory_transfer_lines l
            JOIN inventory_transfer_headers h ON h.company_id=l.company_id AND h.id=l.transfer_header_id
            WHERE l.company_id=:company_id AND l.product_variant_id=:variant_id
              AND h.status IN ('DRAFT','PENDING','IN_TRANSIT','ACCEPTED')
            UNION ALL
            SELECT 'ACTIVE_ROUTE_LOAD', count(*), min(r.id)
            FROM dispatch_load_plan_lines l
            JOIN dispatch_routes r ON r.company_id=l.company_id AND r.id=l.dispatch_route_id
            WHERE l.company_id=:company_id AND l.product_variant_id=:variant_id
              AND r.status IN ('active','waiting','postponed')
            UNION ALL
            SELECT 'OPEN_STOCKTAKE', count(*), min(s.id)
            FROM stocktake_lines l
            JOIN stocktake_sessions s ON s.company_id=l.company_id AND s.id=l.stocktake_session_id
            WHERE l.company_id=:company_id AND l.product_variant_id=:variant_id
              AND s.status IN ('DRAFT','COUNTING','PENDING_REVIEW','RECOUNT_REQUIRED','APPROVED')
            UNION ALL
            SELECT 'ACTIVE_INVENTORY_LOCK', count(*), min(id)
            FROM inventory_locks
            WHERE company_id=:company_id AND product_variant_id=:variant_id AND released_at IS NULL
            UNION ALL
            SELECT 'OPEN_CUSTODY', count(*), min(s.id)
            FROM session_inventory_snapshots s
            JOIN work_sessions w ON w.company_id=s.company_id AND w.id=s.work_session_id
            WHERE s.company_id=:company_id AND s.product_variant_id=:variant_id
              AND (w.end_time IS NULL OR w.inventory_reconciled_at IS NULL OR w.is_settled IS FALSE)
            UNION ALL
            SELECT 'OPEN_SHORTAGE', count(*), min(id)
            FROM shortage_requests
            WHERE company_id=:company_id AND product_variant_id=:variant_id AND status='pending'
            UNION ALL
            SELECT 'ACTIVE_OFFER', count(*), min(id)
            FROM offer_rules
            WHERE company_id=:company_id AND product_variant_id=:variant_id AND is_active IS TRUE
        ) blockers
        WHERE total > 0
        ORDER BY blocker_code
    """), {"company_id": company_id, "variant_id": variant_id})).all()
    return [
        {"code": str(code), "count": int(total), "sample_id": int(first_id) if first_id is not None else None}
        for code, total, first_id in rows
    ]


async def product_location_delete_blockers(
    db: AsyncSession,
    company_id: int,
    location_id: int,
    variant_id: int,
) -> list[dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT blocker_code, total, first_id
        FROM (
            SELECT 'STOCK_POLICY' blocker_code, count(*) total, min(id) first_id
            FROM inventory_stock_policies
            WHERE company_id=:company_id AND location_id=:location_id AND product_variant_id=:variant_id
            UNION ALL
            SELECT 'INVENTORY_BALANCE', count(*), min(id)
            FROM inventory_balances
            WHERE company_id=:company_id AND location_id=:location_id AND product_variant_id=:variant_id
            UNION ALL
            SELECT 'INVENTORY_MOVEMENT', count(*), min(id)
            FROM inventory_movements
            WHERE company_id=:company_id AND product_variant_id=:variant_id
              AND (source_location_id=:location_id OR destination_location_id=:location_id)
            UNION ALL
            SELECT 'TRANSFER_REFERENCE', count(*), min(h.id)
            FROM inventory_transfer_lines l
            JOIN inventory_transfer_headers h ON h.company_id=l.company_id AND h.id=l.transfer_header_id
            WHERE l.company_id=:company_id AND l.product_variant_id=:variant_id
              AND (h.source_location_id=:location_id OR h.destination_location_id=:location_id)
            UNION ALL
            SELECT 'STOCKTAKE_REFERENCE', count(*), min(s.id)
            FROM stocktake_lines l
            JOIN stocktake_sessions s ON s.company_id=l.company_id AND s.id=l.stocktake_session_id
            WHERE l.company_id=:company_id AND l.product_variant_id=:variant_id AND s.location_id=:location_id
        ) blockers
        WHERE total > 0
        ORDER BY blocker_code
    """), {"company_id": company_id, "location_id": location_id, "variant_id": variant_id})).all()
    return [
        {"code": str(code), "count": int(total), "sample_id": int(first_id) if first_id is not None else None}
        for code, total, first_id in rows
    ]
