"""Bounded, session-authorized catalogue reads for blind DISCOVERED stocktake lines.

These reads never create a ProductBatch, StocktakeLine, balance or movement.
The canonical count/approval commands remain the only mutation authority.
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from domains.authorization.guards import require_stocktake
from domains.product_tracking import public_batch_number
from models import Driver, ProductBatch, ProductVariant, StocktakeCountAttempt, StocktakeSession, UOM
from quantity import canonical_quantity

from ._shared import _escape_like

router = APIRouter()
_MAX_DISCOVERY_BATCH_IDS = 100


def _cursor(value: int, scope: str) -> str:
    payload = {"v": 1, "id": value, "s": hashlib.sha256(scope.encode()).hexdigest()[:24]}
    return base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).decode().rstrip("=")


def _decode_cursor(value: str, scope: str) -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode()))
        assert payload["v"] == 1
        assert type(payload["id"]) is int and payload["id"] > 0
        assert payload["s"] == hashlib.sha256(scope.encode()).hexdigest()[:24]
        return payload["id"]
    except (ValueError, TypeError, KeyError, AssertionError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Cursor نطاق الجرد المكتشف غير صالح.") from None


@router.get("/warehouse/unified/stocktake/{session_id}/discovery-options")
async def stocktake_discovery_options(
    session_id: int,
    product_variant_id: Optional[int] = Query(default=None, ge=1),
    batch_ids: Optional[str] = Query(default=None, max_length=1100),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
    actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    try:
        await require_stocktake(access, "stocktake.count", session_id)
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(status_code=403, detail="Authorization denied.") from None

    company_id = access.company_id
    session = (await db.execute(
        select(
            StocktakeSession.stocktake_type, StocktakeSession.status,
            StocktakeSession.scope_product_variant_id, StocktakeSession.scope_batch_id,
            StocktakeSession.pending_independent_recount_required,
        ).where(StocktakeSession.company_id == company_id, StocktakeSession.id == session_id)
    )).one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="جلسة الجرد غير موجودة.")
    if session.stocktake_type not in {"FULL_COUNT", "CYCLE_COUNT", "VEHICLE_RECON"} or session.status not in {
        "COUNTING", "RECOUNT_REQUIRED"
    }:
        raise HTTPException(status_code=409, detail="لا يمكن إضافة أسطر مكتشفة في حالة الجرد الحالية.")
    if session.status == "RECOUNT_REQUIRED" and session.pending_independent_recount_required:
        prior_counter = (await db.execute(
            select(StocktakeCountAttempt.counted_by).where(
                StocktakeCountAttempt.company_id == company_id,
                StocktakeCountAttempt.stocktake_session_id == session_id,
            ).order_by(StocktakeCountAttempt.attempt_number.desc()).limit(1)
        )).scalar_one_or_none()
        if prior_counter == actor.id:
            raise HTTPException(status_code=403, detail="إعادة العد المستقلة تتطلب مستخدماً آخر.")

    clean = search.strip() if search else ""
    if batch_ids is not None:
        if product_variant_id is not None or cursor is not None or clean:
            raise HTTPException(status_code=400, detail="نطاق التحقق من التشغيلات غير صالح.")
        ids_raw = batch_ids.split(",")
        if len(ids_raw) > _MAX_DISCOVERY_BATCH_IDS or any(
            not item.isascii() or not item.isdecimal() or int(item) <= 0 for item in ids_raw
        ):
            raise HTTPException(status_code=400, detail="عدد أو هوية تشغيلات الجرد غير صالحة.")
        ids = sorted({int(item) for item in ids_raw})
        if not ids:
            raise HTTPException(status_code=400, detail="لم تحدد تشغيلات للتحقق.")
    else:
        ids = None

    variant_cols = (
        ProductVariant.id.label("product_variant_id"), ProductVariant.name.label("product_name"),
        ProductVariant.sku, ProductVariant.base_uom_id, ProductVariant.quantity_scale,
        ProductVariant.quantity_step, UOM.code.label("base_uom_code"), UOM.name.label("base_uom_name"),
    )
    if product_variant_id is None and ids is None:
        if session.stocktake_type == "CYCLE_COUNT":
            # The session, not the operator's query, restricts cycle-count products.
            scope_variant = session.scope_product_variant_id
        else:
            scope_variant = None
        filters = [
            ProductVariant.company_id == company_id,
            ProductVariant.lifecycle_status.in_(["ACTIVE", "RETIRING"]),
            exists(select(ProductBatch.id).where(
                ProductBatch.company_id == company_id,
                ProductBatch.product_variant_id == ProductVariant.id,
            )),
        ]
        if scope_variant is not None:
            filters.append(ProductVariant.id == scope_variant)
        if clean:
            pattern = f"%{_escape_like(clean)}%"
            filters.append(or_(
                ProductVariant.name.ilike(pattern, escape="\\"),
                ProductVariant.sku.ilike(pattern, escape="\\"),
            ))
        scope = f"{company_id}|{session_id}|products|{clean}"
        if cursor is not None:
            filters.append(ProductVariant.id < _decode_cursor(cursor, scope))
        rows = (await db.execute(
            select(*variant_cols).join(UOM, UOM.id == ProductVariant.base_uom_id)
            .where(*filters).order_by(ProductVariant.id.desc()).limit(limit + 1)
        )).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        return {
            "items": [{
                "id": r.product_variant_id, "name": r.product_name, "sku": r.sku,
                "base_uom_id": r.base_uom_id, "base_uom_code": r.base_uom_code,
                "base_uom_name": r.base_uom_name, "quantity_scale": r.quantity_scale,
                "quantity_step": canonical_quantity(r.quantity_step),
            } for r in page],
            "next_cursor": _cursor(page[-1].product_variant_id, scope) if has_more and page else None,
            "has_more": has_more, "total": None,
        }

    filters = [
        ProductBatch.company_id == company_id,
        ProductVariant.company_id == company_id,
        ProductVariant.lifecycle_status.in_(["ACTIVE", "RETIRING"]),
    ]
    if session.stocktake_type == "CYCLE_COUNT":
        filters.append(ProductBatch.product_variant_id == session.scope_product_variant_id)
        if session.scope_batch_id is not None:
            filters.append(ProductBatch.id == session.scope_batch_id)
    if ids is not None:
        filters.append(ProductBatch.id.in_(ids))
    else:
        if product_variant_id is None:
            raise HTTPException(status_code=400, detail="الصنف مطلوب لاختيار التشغيلة.")
        filters.append(ProductBatch.product_variant_id == product_variant_id)
        if clean:
            filters.append(ProductBatch.batch_number.ilike(
                f"%{_escape_like(clean)}%", escape="\\",
            ))
        scope = f"{company_id}|{session_id}|batches|{product_variant_id}|{clean}"
        if cursor is not None:
            filters.append(ProductBatch.id < _decode_cursor(cursor, scope))
    rows = (await db.execute(
        select(
            ProductBatch.id, ProductBatch.product_variant_id, ProductBatch.batch_number,
            ProductBatch.production_date, ProductBatch.expiry_date, ProductBatch.is_active,
            ProductBatch.disposition, *variant_cols[1:],
        ).join(ProductVariant, and_(
            ProductVariant.company_id == ProductBatch.company_id,
            ProductVariant.id == ProductBatch.product_variant_id,
        )).join(UOM, UOM.id == ProductVariant.base_uom_id)
        .where(*filters).order_by(ProductBatch.id.desc())
        .limit((_MAX_DISCOVERY_BATCH_IDS if ids is not None else limit) + (0 if ids is not None else 1))
    )).all()
    has_more = ids is None and len(rows) > limit
    page = rows[:limit] if ids is None else rows
    return {
        "items": [{
            "id": r.id, "product_variant_id": r.product_variant_id,
            "batch_number": public_batch_number(r.batch_number),
            "production_date": r.production_date, "expiry_date": r.expiry_date,
            "is_active": r.is_active, "disposition": r.disposition,
            "product_name": r.product_name, "sku": r.sku,
            "base_uom_id": r.base_uom_id, "base_uom_code": r.base_uom_code,
            "base_uom_name": r.base_uom_name, "quantity_scale": r.quantity_scale,
            "quantity_step": canonical_quantity(r.quantity_step),
        } for r in page],
        "next_cursor": _cursor(page[-1].id, scope) if has_more and page else None,
        "has_more": has_more, "total": None,
    }
