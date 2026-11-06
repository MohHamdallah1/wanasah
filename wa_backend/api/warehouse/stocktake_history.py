"""Immutable, authorized terminal Stocktake archive; NO posting or mutation paths."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected
from domains.authorization.guards import require_stocktake
from domains.product_tracking import public_batch_number
from models import (
    Driver, InventoryLocation, ProductBatch, ProductVariant, StocktakeCountAttempt,
    StocktakeCountAttemptLine, StocktakeLine, StocktakeSession, SystemAuditLog, UOM,
)
from quantity import canonical_quantity

router = APIRouter()
TERMINAL = ("POSTED", "CANCELLED")
AUDIT_TYPES = ("STOCKTAKE_COUNT_SUBMITTED", "STOCKTAKE_CANCELLED", "STOCKTAKE_APPROVED_AND_POSTED",
               "STOCKTAKE_RECOUNT_AUTHORIZED", "STOCKTAKE_CANCEL_REJECTED")


def _cursor(value: int, scope: str) -> str:
    payload = {"v": 1, "id": value, "s": hashlib.sha256(scope.encode()).hexdigest()[:24]}
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")


def _decode(value: str, scope: str) -> int:
    try:
        data = json.loads(base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode()))
        if data.get("v") != 1 or data.get("s") != hashlib.sha256(scope.encode()).hexdigest()[:24]:
            raise ValueError
        if type(data.get("id")) is not int or data["id"] <= 0:
            raise ValueError
        return data["id"]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(400, "مؤشر سجل الجرد غير صالح لهذا النطاق.") from None


async def _location_access(access: BackofficeCapabilityAccess, location_id: int, code: str) -> None:
    try:
        await access.require(code, location_id)
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(403, "Authorization denied.") from None


async def _session(db: AsyncSession, access: BackofficeCapabilityAccess, session_id: int):
    # Security-sensitive expected and actual amounts are never visible with read/count alone.
    try:
        await require_stocktake(access, "stocktake.review", session_id)
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(403, "Authorization denied.") from None
    session = await db.scalar(select(StocktakeSession).where(
        StocktakeSession.company_id == access.company_id,
        StocktakeSession.id == session_id, StocktakeSession.status.in_(TERMINAL),
    ))
    if session is None:
        raise HTTPException(404, "سجل الجرد النهائي غير موجود.")
    location_type = await db.scalar(select(InventoryLocation.location_type).where(
        InventoryLocation.company_id == access.company_id,
        InventoryLocation.id == session.location_id,
    ))
    if location_type != "WAREHOUSE":
        raise HTTPException(404, "سجل الجرد النهائي غير موجود.")
    return session


def _iso(value):
    return value.isoformat() if value is not None else None


def _names(rows) -> dict[int, str]:
    return {int(row.id): row.full_name for row in rows}


@router.get("/warehouse/unified/stocktakes/history")
async def list_terminal_stocktakes(
    location_id: int = Query(..., ge=1),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _location_access(access, location_id, "stocktake.review")
    exists = await db.scalar(select(InventoryLocation.id).where(
        InventoryLocation.company_id == access.company_id,
        InventoryLocation.id == location_id, InventoryLocation.location_type == "WAREHOUSE",
    ))
    if exists is None:
        raise HTTPException(404, "المستودع غير موجود.")
    scope = f"{access.company_id}|{location_id}|stocktake-terminal-history"
    query = select(StocktakeSession, ProductVariant.name.label("scope_name")).outerjoin(
        ProductVariant, and_(ProductVariant.company_id == StocktakeSession.company_id,
                             ProductVariant.id == StocktakeSession.scope_product_variant_id)
    ).where(StocktakeSession.company_id == access.company_id,
            StocktakeSession.location_id == location_id,
            StocktakeSession.status.in_(TERMINAL))
    if cursor:
        query = query.where(StocktakeSession.id < _decode(cursor, scope))
    page_plus = (await db.execute(query.order_by(StocktakeSession.id.desc()).limit(limit + 1))).all()
    has_more = len(page_plus) > limit
    page = page_plus[:limit]
    ids = [int(row[0].id) for row in page]
    # Latest counter and number in one bulk query; never one query per session.
    attempts = (await db.execute(select(
        StocktakeCountAttempt.stocktake_session_id,
        StocktakeCountAttempt.attempt_number, StocktakeCountAttempt.counted_by,
        func.row_number().over(
            partition_by=StocktakeCountAttempt.stocktake_session_id,
            order_by=(StocktakeCountAttempt.attempt_number.desc(), StocktakeCountAttempt.id.desc()),
        ).label("rank"),
    ).where(StocktakeCountAttempt.company_id == access.company_id,
            StocktakeCountAttempt.stocktake_session_id.in_(ids)))).all() if ids else []
    latest = {int(x.stocktake_session_id): x for x in attempts if x.rank == 1}
    actor_ids = {int(v) for row, _ in page
                 for v in (row.started_by, row.approved_by, row.cancelled_by) if v is not None}
    actor_ids.update(int(x.counted_by) for x in latest.values())
    names = _names((await db.scalars(select(Driver).where(
        Driver.company_id == access.company_id, Driver.id.in_(actor_ids)
    ))).all()) if actor_ids else {}
    return {
        "items": [{
            "id": session.id, "reference_number": session.reference_number,
            "stocktake_type": session.stocktake_type, "status": session.status,
            "location_id": session.location_id, "scope_product_name": name,
            "scope_product_variant_id": session.scope_product_variant_id,
            "scope_batch_id": session.scope_batch_id,
            "started_by_name": names.get(session.started_by),
            "approved_by_name": names.get(session.approved_by),
            "cancelled_by_name": names.get(session.cancelled_by),
            "counted_by_name": names.get(latest[session.id].counted_by) if session.id in latest else None,
            "attempt_number": latest[session.id].attempt_number if session.id in latest else None,
            "cancelled_after_count": session.status == "CANCELLED" and session.id in latest,
            "cancellation_reason": session.cancellation_reason,
            "created_at": _iso(session.created_at),
            "finished_at": _iso(session.posted_at or session.cancelled_at),
        } for session, name in page],
        "has_more": has_more,
        "next_cursor": _cursor(page[-1][0].id, scope) if has_more and page else None,
    }


@router.get("/warehouse/unified/stocktake/{session_id}/history")
async def terminal_stocktake_details(
    session_id: int,
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    session = await _session(db, access, session_id)
    scope = f"{access.company_id}|{session.id}|terminal-attempts"
    query = select(StocktakeCountAttempt).where(
        StocktakeCountAttempt.company_id == access.company_id,
        StocktakeCountAttempt.stocktake_session_id == session.id,
    )
    if cursor:
        query = query.where(StocktakeCountAttempt.id < _decode(cursor, scope))
    rows = (await db.scalars(query.order_by(StocktakeCountAttempt.id.desc()).limit(limit + 1))).all()
    page = rows[:limit]
    actor_ids = {int(v) for v in (session.started_by, session.approved_by, session.cancelled_by) if v is not None}
    actor_ids.update(int(v) for attempt in page for v in (attempt.counted_by, attempt.authorized_by) if v is not None)
    audit = (await db.scalars(select(SystemAuditLog).where(
        SystemAuditLog.company_id == access.company_id,
        SystemAuditLog.target_id == f"Stocktake_{session.id}",
        SystemAuditLog.action_type.in_(AUDIT_TYPES),
    ).order_by(SystemAuditLog.id.desc()).limit(100))).all()
    actor_ids.update(int(a.admin_id) for a in audit if a.admin_id is not None)
    names = _names((await db.scalars(select(Driver).where(
        Driver.company_id == access.company_id, Driver.id.in_(actor_ids)
    ))).all()) if actor_ids else {}
    return {
        "session_id": session.id, "location_id": session.location_id,
        "reference_number": session.reference_number, "stocktake_type": session.stocktake_type,
        "status": session.status, "scope_product_variant_id": session.scope_product_variant_id,
        "scope_batch_id": session.scope_batch_id,
        "started_by_name": names.get(session.started_by), "approved_by_name": names.get(session.approved_by),
        "cancelled_by_name": names.get(session.cancelled_by),
        "created_at": _iso(session.created_at), "finished_at": _iso(session.posted_at or session.cancelled_at),
        "cancellation_reason": session.cancellation_reason, "notes": session.notes,
        "cancelled_after_count": session.status == "CANCELLED" and bool(page),
        "attempts": [{
            "id": a.id, "attempt_number": a.attempt_number,
            "counted_by_name": names.get(a.counted_by), "authorized_by_name": names.get(a.authorized_by),
            "recount_reason": a.recount_reason, "requires_independent_recount": a.requires_independent_recount,
            "submitted_at": _iso(a.submitted_at),
        } for a in page],
        "next_cursor": _cursor(page[-1].id, scope) if len(rows) > limit and page else None,
        "audit": [{
            "id": a.id, "action_type": a.action_type, "actor_name": names.get(a.admin_id),
            "at": _iso(a.timestamp), "old_value": a.old_value, "new_value": a.new_value,
        } for a in audit],
    }


@router.get("/warehouse/unified/stocktake/{session_id}/history/attempts/{attempt_id}/lines")
async def terminal_stocktake_attempt_lines(
    session_id: int,
    attempt_id: int,
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    session = await _session(db, access, session_id)
    attempt_exists = await db.scalar(select(StocktakeCountAttempt.id).where(
        StocktakeCountAttempt.company_id == access.company_id,
        StocktakeCountAttempt.stocktake_session_id == session.id, StocktakeCountAttempt.id == attempt_id,
    ))
    if attempt_exists is None:
        raise HTTPException(404, "محاولة العد غير موجودة.")
    scope = f"{access.company_id}|{session.id}|{attempt_id}|attempt-lines"
    query = select(
        StocktakeCountAttemptLine, StocktakeLine, ProductVariant.name,
        ProductVariant.base_uom_id, UOM.name, UOM.code,
        ProductBatch.batch_number,
    ).join(StocktakeLine, and_(
        StocktakeLine.company_id == StocktakeCountAttemptLine.company_id,
        StocktakeLine.stocktake_session_id == StocktakeCountAttemptLine.stocktake_session_id,
        StocktakeLine.id == StocktakeCountAttemptLine.stocktake_line_id,
    )).join(ProductVariant, and_(
        ProductVariant.company_id == StocktakeLine.company_id,
        ProductVariant.id == StocktakeLine.product_variant_id,
    )).join(UOM, UOM.id == ProductVariant.base_uom_id).join(ProductBatch, and_(
        ProductBatch.company_id == StocktakeLine.company_id,
        ProductBatch.product_variant_id == StocktakeLine.product_variant_id,
        ProductBatch.id == StocktakeLine.batch_id,
    )).where(
        StocktakeCountAttemptLine.company_id == access.company_id,
        StocktakeCountAttemptLine.stocktake_session_id == session.id,
        StocktakeCountAttemptLine.count_attempt_id == attempt_id,
    )
    if cursor:
        query = query.where(StocktakeCountAttemptLine.id > _decode(cursor, scope))
    rows = (await db.execute(query.order_by(StocktakeCountAttemptLine.id.asc()).limit(limit + 1))).all()
    page = rows[:limit]
    return {
        "items": [{
            "id": line.id, "product_name": product_name,
            "batch_id": original.batch_id, "batch_number": public_batch_number(batch_number),
            "stock_status": original.stock_status, "line_origin": original.line_origin,
            "base_uom_id": base_uom_id, "base_uom_name": uom_name, "base_uom_code": uom_code,
            "expected_quantity": canonical_quantity(line.expected_quantity),
            "actual_quantity": canonical_quantity(line.actual_quantity),
            "variance_quantity": canonical_quantity(line.variance_quantity),
        } for line, original, product_name, base_uom_id, uom_name, uom_code, batch_number in page],
        "next_cursor": _cursor(page[-1][0].id, scope) if len(rows) > limit and page else None,
    }
