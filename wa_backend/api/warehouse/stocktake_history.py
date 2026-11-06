"""Immutable, authorized, bounded terminal Stocktake history reads.

No active session may enter this router. Count quantities become readable only
after a terminal state AND an explicit stocktake.review location capability.
No inventory/attempt/audit mutation is performed by any GET.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from database import get_db
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.product_tracking import public_batch_number
from models import (
    Driver, InventoryLocation, InventoryMovement, ProductBatch, ProductVariant,
    StocktakeCountAttempt, StocktakeCountAttemptLine, StocktakeLine,
    StocktakeSession, SystemAuditLog, UOM,
)
from quantity import canonical_quantity

router = APIRouter()
_TERMINAL = ("POSTED", "CANCELLED")
_AUDIT_ACTIONS = (
    "STOCKTAKE_COUNT_SUBMITTED", "STOCKTAKE_RECOUNT_AUTHORIZED",
    "STOCKTAKE_CANCELLED", "STOCKTAKE_APPROVED_AND_POSTED",
    "STOCKTAKE_APPROVAL_REJECTED", "STOCKTAKE_CANCEL_REJECTED",
)
_MAX_PAGE = 100


def _time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + ("Z" if value.tzinfo is None else "")


def _cursor(value: int, scope: str, *, finished: datetime | None = None) -> str:
    payload = {"v": 1, "id": value, "s": hashlib.sha256(scope.encode()).hexdigest()[:24]}
    if finished is not None:
        payload["t"] = finished.isoformat()
    return base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")


def _decode(cursor: str, scope: str, *, with_time: bool = False):
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (type(data) is not dict or data.get("v") != 1
            or type(data.get("id")) is not int or data["id"] < 1
            or data.get("s") != hashlib.sha256(scope.encode()).hexdigest()[:24]):
            raise ValueError()
        if with_time:
            finished = datetime.fromisoformat(data["t"])
            if finished.tzinfo is not None:
                raise ValueError()
            return finished, data["id"]
        if "t" in data:
            raise ValueError()
        return data["id"]
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid stocktake history cursor.") from None


async def _require(access: BackofficeCapabilityAccess, code: str, location_id: int):
    try:
        await access.require(code, location_id)
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(status_code=403, detail="Authorization denied.") from None


async def _warehouse(db: AsyncSession, company_id: int, location_id: int):
    present = await db.scalar(select(InventoryLocation.id).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.id == location_id,
        InventoryLocation.location_type == "WAREHOUSE",
    ))
    if present is None:
        raise HTTPException(status_code=404, detail="Warehouse not found.")


async def _session(db: AsyncSession, access: BackofficeCapabilityAccess,
                   session_id: int, location_id: int):
    # Never use client-provided session metadata to establish authorization.
    session = await db.scalar(select(StocktakeSession).where(
        StocktakeSession.company_id == access.company_id,
        StocktakeSession.id == session_id,
        StocktakeSession.location_id == location_id,
        StocktakeSession.stocktake_type.in_(("FULL_COUNT", "CYCLE_COUNT")),
        StocktakeSession.status.in_(_TERMINAL),
    ))
    if session is None:
        raise HTTPException(status_code=404, detail="Terminal stocktake not found.")
    await _require(access, "stocktake.review", int(session.location_id))
    return session


def _latest_attempt_id(company_id: int):
    return (
        select(StocktakeCountAttempt.id)
        .where(
            StocktakeCountAttempt.company_id == company_id,
            StocktakeCountAttempt.stocktake_session_id == StocktakeSession.id,
        )
        .order_by(StocktakeCountAttempt.attempt_number.desc(),
                  StocktakeCountAttempt.id.desc())
        .limit(1).correlate(StocktakeSession).scalar_subquery()
    )


def _finish_expr():
    return func.coalesce(StocktakeSession.posted_at, StocktakeSession.cancelled_at)


@router.get("/warehouse/unified/stocktakes/history")
async def list_stocktake_history(
    location_id: int = Query(..., ge=1),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=_MAX_PAGE),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _require(access, "stocktake.read", location_id)
    await _warehouse(db, access.company_id, location_id)
    company_id = int(access.company_id)
    started, approved, cancelled, counter = (
        aliased(Driver) for _ in range(4)
    )
    recent = aliased(StocktakeCountAttempt)
    finished = _finish_expr()
    scope = f"{company_id}|{location_id}|terminal-v1"
    stmt = (
        select(
            StocktakeSession, ProductVariant.name.label("product_name"),
            ProductBatch.batch_number.label("scope_batch_number"),
            started.full_name.label("started_name"),
            approved.full_name.label("approved_name"),
            cancelled.full_name.label("cancelled_name"),
            counter.full_name.label("counter_name"),
            recent.attempt_number.label("attempt_number"),
        )
        .outerjoin(ProductVariant, and_(
            ProductVariant.company_id == StocktakeSession.company_id,
            ProductVariant.id == StocktakeSession.scope_product_variant_id,
        ))
        .outerjoin(ProductBatch, and_(
            ProductBatch.company_id == StocktakeSession.company_id,
            ProductBatch.product_variant_id == StocktakeSession.scope_product_variant_id,
            ProductBatch.id == StocktakeSession.scope_batch_id,
        ))
        .join(started, and_(started.company_id == company_id,
                            started.id == StocktakeSession.started_by))
        .outerjoin(approved, and_(approved.company_id == company_id,
                                  approved.id == StocktakeSession.approved_by))
        .outerjoin(cancelled, and_(cancelled.company_id == company_id,
                                   cancelled.id == StocktakeSession.cancelled_by))
        .outerjoin(recent, and_(recent.company_id == company_id,
                                recent.id == _latest_attempt_id()))
        .outerjoin(counter, and_(counter.company_id == company_id,
                                  counter.id == recent.counted_by))
        .where(
            StocktakeSession.company_id == company_id,
            StocktakeSession.location_id == location_id,
            StocktakeSession.stocktake_type.in_(("FULL_COUNT", "CYCLE_COUNT")),
            StocktakeSession.status.in_(_TERMINAL),
        )
    )
    if cursor:
        ended, previous_id = _decode(cursor, scope, with_time=True)
        stmt = stmt.where(or_(finished < ended,
                             and_(finished == ended, StocktakeSession.id < previous_id)))
    rows = (await db.execute(stmt.order_by(
        finished.desc(), StocktakeSession.id.desc(),
    ).limit(limit + 1))).all()
    items = []
    for s, product_name, batch_number, starter, approver, canceller, counted, attempt_no in rows[:limit]:
        items.append({
            "id": s.id, "reference_number": s.reference_number,
            "status": s.status, "stocktake_type": s.stocktake_type,
            "location_id": s.location_id, "scope_product_variant_id": s.scope_product_variant_id,
            "scope_product_name": product_name,
            "scope_batch_id": s.scope_batch_id,
            "scope_batch_number": public_batch_number(batch_number),
            "created_at": _time(s.created_at),
            "finished_at": _time(s.posted_at or s.cancelled_at),
            "started_by_name": starter,
            "counted_by_name": counted, "attempt_number": attempt_no,
            "approved_by_name": approver, "cancelled_by_name": canceller,
            "cancellation_reason": s.cancellation_reason,
            "cancelled_after_count": attempt_no is not None and s.status == "CANCELLED",
        })
    last = rows[limit - 1][0] if len(rows) > limit else None
    return {
        "items": items, "has_more": last is not None,
        "next_cursor": _cursor(last.id, scope, finished=last.posted_at or last.cancelled_at) if last else None,
    }


async def _attempt_page(db, company_id: int, session_id: int,
                        cursor: str | None, limit: int):
    scope = f"{company_id}|{session_id}|attempts"
    stmt = select(
        StocktakeCountAttempt, Driver.full_name,
    ).join(Driver, and_(
        Driver.company_id == company_id,
        Driver.id == StocktakeCountAttempt.counted_by,
    )).where(
        StocktakeCountAttempt.company_id == company_id,
        StocktakeCountAttempt.stocktake_session_id == session_id,
    )
    if cursor:
        stmt = stmt.where(StocktakeCountAttempt.id < _decode(cursor, scope))
    rows = (await db.execute(stmt.order_by(
        StocktakeCountAttempt.id.desc()).limit(limit + 1))).all()
    items = [{
        "id": a.id, "attempt_number": a.attempt_number,
        "counted_by": a.counted_by, "counted_by_name": name,
        "submitted_at": _time(a.submitted_at),
        "authorized_by": a.authorized_by,
        "recount_of_attempt_id": a.recount_of_attempt_id,
        "recount_reason": a.recount_reason,
        "requires_independent_recount": a.requires_independent_recount,
    } for a, name in rows[:limit]]
    last = rows[limit - 1][0].id if len(rows) > limit else None
    return {"items": items, "has_more": last is not None,
            "next_cursor": _cursor(last, scope) if last else None}


async def _audit_page(db, company_id: int, session_id: int,
                      cursor: str | None, limit: int):
    scope = f"{company_id}|{session_id}|audit"
    stmt = select(SystemAuditLog, Driver.full_name).outerjoin(
        Driver, and_(Driver.company_id == company_id,
                     Driver.id == SystemAuditLog.admin_id),
    ).where(
        SystemAuditLog.company_id == company_id,
        SystemAuditLog.target_id == f"Stocktake_{session_id}",
        SystemAuditLog.action_type.in_(_AUDIT_ACTIONS),
    )
    if cursor:
        stmt = stmt.where(SystemAuditLog.id < _decode(cursor, scope))
    rows = (await db.execute(stmt.order_by(
        SystemAuditLog.id.desc()).limit(limit + 1))).all()
    items = []
    for event, name in rows[:limit]:
        # Audit payloads may evolve; expose only a known whitelist, never an
        # arbitrary JSON dump of a future field (or a stored credential).
        detail = {}
        if event.action_type in _AUDIT_ACTIONS:
            try:
                raw = json.loads(event.new_value or "{}")
                if isinstance(raw, dict):
                    detail = {key: raw[key] for key in (
                        "status", "reason", "attempt_number", "attempt_id",
                        "line_count", "movement_count", "released_lock_count",
                        "requires_independent_recount",
                    ) if key in raw}
            except (ValueError, TypeError):
                pass
        items.append({
            "id": event.id, "action_type": event.action_type,
            "actor_name": name, "timestamp": _time(event.timestamp),
            "details": detail,
        })
    last = rows[limit - 1][0].id if len(rows) > limit else None
    return {"items": items, "has_more": last is not None,
            "next_cursor": _cursor(last, scope) if last else None}


@router.get("/warehouse/unified/stocktakes/history/{session_id}")
async def get_stocktake_history_detail(
    session_id: int,
    location_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    session = await _session(db, access, session_id, location_id)
    company_id = int(access.company_id)
    product_name = None
    batch_number = None
    if session.scope_product_variant_id:
        product_name = await db.scalar(select(ProductVariant.name).where(
            ProductVariant.company_id == company_id,
            ProductVariant.id == session.scope_product_variant_id,
        ))
    if session.scope_batch_id:
        batch_number = await db.scalar(select(ProductBatch.batch_number).where(
            ProductBatch.company_id == company_id,
            ProductBatch.product_variant_id == session.scope_product_variant_id,
            ProductBatch.id == session.scope_batch_id,
        ))
    attempts = await _attempt_page(db, company_id, session.id, None, 50)
    audit = await _audit_page(db, company_id, session.id, None, 50)
    # This is a read of canonical, already-posted physical ledger evidence,
    # never an inference from cancellation or from a projected balance.
    adjustment_count = await db.scalar(select(func.count()).select_from(
        InventoryMovement).where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.stocktake_session_id == session.id,
            InventoryMovement.reference_type == "AUDIT_ADJUSTMENT",
        ))
    return {
        "session": {
            "id": session.id, "reference_number": session.reference_number,
            "status": session.status, "stocktake_type": session.stocktake_type,
            "location_id": session.location_id,
            "scope_product_name": product_name,
            "scope_batch_number": public_batch_number(batch_number),
            "created_at": _time(session.created_at),
            "finished_at": _time(session.posted_at or session.cancelled_at),
            "snapshot_cutoff_at": _time(session.snapshot_cutoff_at),
            "started_by": session.started_by, "approved_by": session.approved_by,
            "cancelled_by": session.cancelled_by,
            "approved_at": _time(session.approved_at), "cancelled_at": _time(session.cancelled_at),
            "cancellation_reason": session.cancellation_reason,
            "notes": session.notes,
            "cancelled_after_count": session.status == "CANCELLED" and bool(attempts["items"]),
            "adjustment_movement_count": adjustment_count or 0,
        },
        "attempts": attempts, "audit": audit,
    }


@router.get("/warehouse/unified/stocktakes/history/{session_id}/attempts")
async def get_stocktake_history_attempts(
    session_id: int,
    location_id: int = Query(..., ge=1),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=_MAX_PAGE),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _session(db, access, session_id, location_id)
    return await _attempt_page(db, access.company_id, session_id, cursor, limit)


@router.get("/warehouse/unified/stocktakes/history/{session_id}/audit")
async def get_stocktake_history_audit(
    session_id: int,
    location_id: int = Query(..., ge=1),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=_MAX_PAGE),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _session(db, access, session_id, location_id)
    return await _audit_page(db, access.company_id, session_id, cursor, limit)


@router.get("/warehouse/unified/stocktakes/history/{session_id}/attempts/{attempt_id}/lines")
async def get_stocktake_history_attempt_lines(
    session_id: int,
    attempt_id: int,
    location_id: int = Query(..., ge=1),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=100, ge=1, le=_MAX_PAGE),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _session(db, access, session_id, location_id)
    company_id = access.company_id
    attempt_exists = await db.scalar(select(StocktakeCountAttempt.id).where(
        StocktakeCountAttempt.company_id == company_id,
        StocktakeCountAttempt.stocktake_session_id == session_id,
        StocktakeCountAttempt.id == attempt_id,
    ))
    if attempt_exists is None:
        raise HTTPException(status_code=404, detail="Count attempt not found.")
    scope = f"{company_id}|{session_id}|{attempt_id}|lines"
    stmt = (select(
        StocktakeCountAttemptLine, StocktakeLine,
        ProductVariant.name, ProductVariant.base_uom_id,
        UOM.code, UOM.name, ProductBatch.batch_number, ProductBatch.expiry_date,
    ).join(StocktakeLine, and_(
        StocktakeLine.company_id == StocktakeCountAttemptLine.company_id,
        StocktakeLine.stocktake_session_id == StocktakeCountAttemptLine.stocktake_session_id,
        StocktakeLine.id == StocktakeCountAttemptLine.stocktake_line_id,
    )).join(ProductVariant, and_(
        ProductVariant.company_id == StocktakeLine.company_id,
        ProductVariant.id == StocktakeLine.product_variant_id,
    )).join(UOM, UOM.id == ProductVariant.base_uom_id)
    .join(ProductBatch, and_(
        ProductBatch.company_id == StocktakeLine.company_id,
        ProductBatch.product_variant_id == StocktakeLine.product_variant_id,
        ProductBatch.id == StocktakeLine.batch_id,
    )).where(
        StocktakeCountAttemptLine.company_id == company_id,
        StocktakeCountAttemptLine.stocktake_session_id == session_id,
        StocktakeCountAttemptLine.count_attempt_id == attempt_id,
    ))
    if cursor:
        stmt = stmt.where(StocktakeCountAttemptLine.id > _decode(cursor, scope))
    rows = (await db.execute(stmt.order_by(
        StocktakeCountAttemptLine.id.asc()).limit(limit + 1))).all()
    items = [{
        "id": line.id, "stocktake_line_id": snapshot.id,
        "product_variant_id": snapshot.product_variant_id,
        "product_name": name, "batch_id": snapshot.batch_id,
        "batch_number": public_batch_number(batch_number),
        "expiry_date": _time(expiry_date) if isinstance(expiry_date, datetime) else (
            expiry_date.isoformat() if expiry_date else None
        ),
        "stock_status": snapshot.stock_status, "line_origin": snapshot.line_origin,
        "base_uom_id": base_id, "base_uom_code": base_code, "base_uom_name": base_name,
        "expected_quantity": canonical_quantity(line.expected_quantity),
        "actual_quantity": canonical_quantity(line.actual_quantity),
        "variance_quantity": canonical_quantity(line.variance_quantity),
        "notes": line.notes,
    } for line, snapshot, name, base_id, base_code, base_name, batch_number, expiry_date in rows[:limit]]
    last = rows[limit - 1][0].id if len(rows) > limit else None
    return {"items": items, "has_more": last is not None,
            "next_cursor": _cursor(last, scope) if last else None}
