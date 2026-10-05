from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from models import DomainAuditEvent


class ProductStatusReasonSource(Protocol):
    id: int
    lifecycle_revision: int
    operational_hold: str


_LIFECYCLE_EVENT_TYPES = (
    "ProductPublished",
    "ProductRetired",
    "ProductRestored",
    "ProductArchived",
    "ProductSalesHoldPlaced",
    "ProductSalesHoldReleased",
    "ProductRecallIssued",
    "ProductRecallCancelled",
    "ProductRecallClosed",
)


async def load_current_product_status_reasons(
    db: AsyncSession,
    *,
    company_id: int,
    variants: Sequence[ProductStatusReasonSource],
) -> dict[int, str | None]:
    """Return the audited reason for each variant's current lifecycle revision.

    This is read-only presentation evidence. ProductVariant remains the state authority;
    DomainAuditEvent only supplies the human reason recorded for that exact transition.
    """
    if type(company_id) is not int or company_id <= 0:
        raise ValueError("company_id must be a positive integer")
    if len(variants) > 200:
        raise ValueError("status reason scope exceeds one product page")

    result: dict[int, str | None] = {}
    revision_targets: list[tuple[str, int]] = []
    for variant in variants:
        variant_id = int(variant.id)
        revision = int(variant.lifecycle_revision)
        if variant_id <= 0 or revision <= 0:
            raise ValueError("invalid product lifecycle reason scope")
        result[variant_id] = None
        revision_targets.append((str(variant_id), revision))

    if not revision_targets:
        return result

    revision_expr = DomainAuditEvent.after_snapshot[
        "lifecycle_revision"
    ].as_integer()
    rows = (
        await db.execute(
            select(
                DomainAuditEvent.entity_id,
                DomainAuditEvent.reason_text,
                DomainAuditEvent.id,
            )
            .where(
                DomainAuditEvent.company_id == company_id,
                DomainAuditEvent.entity_type == "ProductVariant",
                DomainAuditEvent.event_type.in_(_LIFECYCLE_EVENT_TYPES),
                tuple_(
                    DomainAuditEvent.entity_id,
                    revision_expr,
                ).in_(revision_targets),
            )
            .order_by(
                DomainAuditEvent.entity_id.asc(),
                DomainAuditEvent.id.desc(),
            )
        )
    ).all()

    seen: set[int] = set()
    for entity_id, reason_text, _event_id in rows:
        try:
            variant_id = int(entity_id)
        except (TypeError, ValueError):
            continue
        if variant_id in seen or variant_id not in result:
            continue
        seen.add(variant_id)
        clean = reason_text.strip() if isinstance(reason_text, str) else ""
        result[variant_id] = clean or None

    return result
