import asyncio
import base64
import bcrypt
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess, require_stocktake
from services import (
    InventoryMutationError,
    acquire_inventory_location_guard,
    get_company_local_date,
    post_approved_stocktake_adjustments,
    validate_vehicle_recon_work_session,
)
from quantity import QuantityError, canonical_quantity, validate_variant_quantity
from schemas import StocktakeActiveSessionCursorPage, StocktakeApprovalRequest, StocktakeCancelRequest, StocktakeCycleBatchCursorPage, StocktakeRecountRequest, StocktakeSessionContextResponse, UnifiedStocktakeCountRequest, UnifiedStocktakeStartRequest, VehicleReconCandidateCursorPage

from models import (
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    ProductBatch,
    ProductVariant,
    StocktakeCountAttempt,
    StocktakeCountAttemptLine,
    StocktakeLine,
    StocktakeSession,
    SystemAuditLog,
    SystemSetting,
    UOM,
    WorkSession,
)


from ._shared import _escape_like


logger = logging.getLogger("wanasah_logger")
router = APIRouter()


# ====================================================
# 11. الجرد الموحد (Stocktake)
# ====================================================
# ====================================================
# 11.1 إنشاء بصمة نطاق Cursor لجلسات الجرد
# ====================================================
def _stocktake_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


# ====================================================
# 11.2 ترميز Cursor لجلسات الجرد النشطة
# ====================================================
def _encode_stocktake_cursor(
    session_id: int,
    *,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "stocktake-active-session",
            "scope": _stocktake_cursor_scope_hash(scope),
            "id": int(session_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# ====================================================
# 11.3 فك Cursor جلسات الجرد والتحقق من نطاقه
# ====================================================
def _decode_stocktake_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(
            (cursor + padding).encode("ascii")
        )
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "stocktake-active-session"
            or payload.get("scope")
            != _stocktake_cursor_scope_hash(expected_scope)
        ):
            raise ValueError

        session_id = payload.get("id")
        if type(session_id) is not int or session_id <= 0:
            raise ValueError

        return session_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cursor جلسات الجرد غير صالح "
                "أو لا يطابق الموقع الحالي."
            ),
        ) from exc


# التحقق من بيانات مشرف مخول داخل نفس الشركة دون كشف سبب فشل المصادقة.
# ====================================================
# 11.4 التحقق من بيانات مشرف مخول لإعادة العد
# ====================================================
async def _verify_stocktake_admin_credentials(
    db: AsyncSession,
    company_id: int,
    username: str,
    password: str,
    location_id: int,
) -> Optional[Driver]:
    stmt = select(Driver).filter_by(
        company_id=company_id,
        username=username.strip(),
        is_active=True,
    )
    admin = (await db.execute(stmt)).scalar_one_or_none()

    if not admin:
        return None

    password_ok = await asyncio.to_thread(
        bcrypt.checkpw,
        password.encode('utf-8'),
        admin.password_hash.encode('utf-8')
    )
    if not password_ok:
        return None
    try:
        await InventoryAccess(db, admin).require('stocktake.recount', location_id)
    except HTTPException:
        return None
    return admin


# تحديد ما إذا كان العجز يتطلب إعادة عد مستقلة؛ الوضع الافتراضي الآمن يعتبر أي عجز مادياً حتى تضبط الشركة حدودها.
# ====================================================
# 11.5 تحديد ما إذا كان العجز يتطلب إعادة عد مستقلة
# ====================================================
async def _requires_independent_stocktake_recount(
    db: AsyncSession,
    company_id: int,
    line_values: list[tuple[int, int]]
) -> bool:
    shortages = [
        (expected_qty, abs(variance_qty))
        for expected_qty, variance_qty in line_values
        if variance_qty < 0
    ]

    if not shortages:
        return False

    stmt_settings = select(
        SystemSetting.setting_key,
        SystemSetting.setting_value
    ).filter(
        SystemSetting.company_id == company_id,
        SystemSetting.setting_key.in_([
            'stocktake_material_shortage_packs',
            'stocktake_material_shortage_percent'
        ])
    )
    settings = {
        key: value
        for key, value in (await db.execute(stmt_settings)).all()
    }

    packs_threshold = None
    percent_threshold = None

    try:
        if settings.get('stocktake_material_shortage_packs') is not None:
            packs_threshold = max(
                0,
                int(settings['stocktake_material_shortage_packs'])
            )
    except (TypeError, ValueError):
        packs_threshold = None

    try:
        if settings.get('stocktake_material_shortage_percent') is not None:
            percent_threshold = max(
                0.0,
                float(settings['stocktake_material_shortage_percent'])
            )
    except (TypeError, ValueError):
        percent_threshold = None

    # Secure-by-default: إذا لم تضبط الشركة سياسة بعد، أي عجز يتطلب عدّاً مستقلاً.
    if packs_threshold is None and percent_threshold is None:
        return True

    for expected_qty, shortage_qty in shortages:
        shortage_percent = (
            (shortage_qty / expected_qty) * 100
            if expected_qty > 0
            else 100.0
        )

        packs_hit = (
            packs_threshold is not None
            and shortage_qty >= packs_threshold
        )
        percent_hit = (
            percent_threshold is not None
            and shortage_percent >= percent_threshold
        )

        if packs_hit or percent_hit:
            return True

    return False


# =================================================================================
# دوال مساعدة للمستودع (Helper Functions)

# [المرحلة السادسة] محرك الجرد القانوني (Stocktake Engine)
# =================================================================================

_STOCKTAKE_ACTIVE_STATUSES = ('DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED')
_MAX_STOCKTAKE_LINES = 10_000


# ====================================================
# 11.6 إنشاء توقيت UTC naive موحد للجرد
# ====================================================
def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ====================================================
# 11.7 تحويل التوقيت إلى ISO UTC
# ====================================================
def _iso_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


# ====================================================
# 11.8 بناء شرط تداخل جلسات الجرد
# ====================================================
def _stocktake_session_overlap_predicate(
    stocktake_type: str,
    product_variant_id: Optional[int],
    batch_id: Optional[int],
):
    if stocktake_type in {'FULL_COUNT', 'VEHICLE_RECON'}:
        return None
    if batch_id is None:
        return or_(
            StocktakeSession.stocktake_type.in_(['FULL_COUNT', 'VEHICLE_RECON']),
            and_(
                StocktakeSession.stocktake_type == 'CYCLE_COUNT',
                StocktakeSession.scope_product_variant_id == product_variant_id,
            ),
        )
    return or_(
        StocktakeSession.stocktake_type.in_(['FULL_COUNT', 'VEHICLE_RECON']),
        and_(
            StocktakeSession.stocktake_type == 'CYCLE_COUNT',
            StocktakeSession.scope_product_variant_id == product_variant_id,
            or_(
                StocktakeSession.scope_batch_id.is_(None),
                StocktakeSession.scope_batch_id == batch_id,
            ),
        ),
    )


# ====================================================
# 11.9 بناء شرط تداخل أقفال المخزون
# ====================================================
def _inventory_lock_overlap_predicate(
    stocktake_type: str,
    product_variant_id: Optional[int],
    batch_id: Optional[int],
):
    if stocktake_type in {'FULL_COUNT', 'VEHICLE_RECON'}:
        return None
    if batch_id is None:
        return or_(
            InventoryLock.product_variant_id.is_(None),
            InventoryLock.product_variant_id == product_variant_id,
        )
    return or_(
        InventoryLock.product_variant_id.is_(None),
        and_(
            InventoryLock.product_variant_id == product_variant_id,
            or_(
                InventoryLock.batch_id.is_(None),
                InventoryLock.batch_id == batch_id,
            ),
        ),
    )


# ====================================================
# 11.10 تحميل جلسة الجرد والتحقق من انتمائها للشركة
# ====================================================
async def _load_stocktake_session(
    db: AsyncSession,
    company_id: int,
    session_id: int,
    *,
    for_update: bool = False,
) -> StocktakeSession:
    stmt = select(StocktakeSession).filter_by(id=session_id, company_id=company_id)
    if for_update:
        stmt = stmt.with_for_update()
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="جلسة الجرد غير موجودة أو لا تتبع شركتك.")
    return session


# ====================================================
# 11.11 جلب موقع جلسة الجرد بسرعة للتحقق من الصلاحيات
# ====================================================
async def _probe_stocktake_location_id(db: AsyncSession, company_id: int, session_id: int) -> int:
    location_id = (
        await db.execute(
            select(StocktakeSession.location_id).filter_by(id=session_id, company_id=company_id)
        )
    ).scalar_one_or_none()
    if location_id is None:
        raise HTTPException(status_code=404, detail="جلسة الجرد غير موجودة أو لا تتبع شركتك.")
    return int(location_id)


# ====================================================
# 11.12 تحميل أحدث محاولة عد لجلسة الجرد
# ====================================================
async def _latest_stocktake_attempt(
    db: AsyncSession,
    company_id: int,
    session_id: int,
) -> Optional[StocktakeCountAttempt]:
    return (
        await db.execute(
            select(StocktakeCountAttempt)
            .filter_by(company_id=company_id, stocktake_session_id=session_id)
            .order_by(StocktakeCountAttempt.attempt_number.desc(), StocktakeCountAttempt.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# ====================================================
# 11.13 إنشاء بصمة نطاق Cursor لدفعات الجرد الدوري
# ====================================================
def _stocktake_cycle_batch_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


# ====================================================
# 11.14 ترميز Cursor لدفعات الجرد الدوري
# ====================================================
def _encode_stocktake_cycle_batch_cursor(batch_id: int, *, scope: str) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "stocktake-cycle-batch",
            "scope": _stocktake_cycle_batch_cursor_scope_hash(scope),
            "id": int(batch_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# ====================================================
# 11.15 فك Cursor دفعات الجرد الدوري والتحقق من نطاقه
# ====================================================
def _decode_stocktake_cycle_batch_cursor(cursor: str, *, expected_scope: str) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "stocktake-cycle-batch"
            or payload.get("scope")
            != _stocktake_cycle_batch_cursor_scope_hash(expected_scope)
        ):
            raise ValueError
        batch_id = payload.get("id")
        if type(batch_id) is not int or batch_id <= 0:
            raise ValueError
        return batch_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor دفعات الجرد الدوري غير صالح أو لا يطابق النطاق الحالي.",
        ) from exc


# ====================================================
# 11.16 جلب دفعات الصنف المتاحة للجرد الدوري باستخدام Cursor
# ====================================================
@router.get(
    "/warehouse/unified/stocktake/cycle-batches",
    response_model=StocktakeCycleBatchCursorPage,
    status_code=200,
)
async def list_stocktake_cycle_batches(
    location_id: int = Query(..., ge=1),
    product_variant_id: int = Query(..., ge=1),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('stocktake.start', location_id)

    company_id = current_admin.company_id

    location_exists = (
        await db.execute(
            select(InventoryLocation.id).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
                InventoryLocation.is_active.is_(True),
                InventoryLocation.location_type.in_(["WAREHOUSE", "VEHICLE"]),
            )
        )
    ).scalar_one_or_none()
    if location_exists is None:
        raise HTTPException(
            status_code=404,
            detail="موقع الجرد غير موجود أو غير فعال أو لا يتبع شركتك.",
        )

    variant_exists = (
        await db.execute(
            select(ProductVariant.id).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id == product_variant_id,
            )
        )
    ).scalar_one_or_none()
    if variant_exists is None:
        raise HTTPException(
            status_code=404,
            detail="الصنف غير موجود أو لا يتبع شركتك.",
        )

    clean_search = search.strip() if search else ""
    scope = f"{company_id}|{location_id}|{product_variant_id}|{clean_search}"
    stocked_batch_ids = select(InventoryBalance.batch_id).filter(
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == location_id,
        InventoryBalance.product_variant_id == product_variant_id,
        InventoryBalance.batch_id.is_not(None),
        InventoryBalance.on_hand_quantity > 0,
    ).distinct()

    filters = [
        ProductBatch.company_id == company_id,
        ProductBatch.product_variant_id == product_variant_id,
        ProductBatch.id.in_(stocked_batch_ids),
    ]
    if clean_search:
        escaped = _escape_like(clean_search)
        filters.append(
            ProductBatch.batch_number.ilike(f"%{escaped}%", escape="\\")
        )

    total = None
    if cursor is None:
        total = int(
            (
                await db.execute(
                    select(func.count(ProductBatch.id)).filter(*filters)
                )
            ).scalar_one()
        )

    stmt = select(
        ProductBatch.id,
        ProductBatch.product_variant_id,
        ProductBatch.batch_number,
        ProductBatch.production_date,
        ProductBatch.expiry_date,
        ProductBatch.is_active,
    ).filter(*filters)

    if cursor is not None:
        cursor_id = _decode_stocktake_cycle_batch_cursor(
            cursor,
            expected_scope=scope,
        )
        stmt = stmt.filter(ProductBatch.id < cursor_id)

    rows = (
        await db.execute(
            stmt.order_by(ProductBatch.id.desc()).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        next_cursor = _encode_stocktake_cycle_batch_cursor(
            int(page_rows[-1].id),
            scope=scope,
        )

    return {
        "items": [
            {
                "id": int(row.id),
                "product_variant_id": int(row.product_variant_id),
                "batch_number": str(row.batch_number),
                "production_date": row.production_date,
                "expiry_date": row.expiry_date,
                "is_active": bool(row.is_active),
            }
            for row in page_rows
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


# ====================================================
# 11.17 إنشاء بصمة نطاق Cursor لمرشحي تسوية السيارات
# ====================================================
def _vehicle_recon_candidate_cursor_scope_hash(
    scope: str,
) -> str:
    return hashlib.sha256(
        scope.encode("utf-8")
    ).hexdigest()[:24]


# ====================================================
# 11.18 ترميز Cursor لمرشحي تسوية السيارات
# ====================================================
def _encode_vehicle_recon_candidate_cursor(
    work_session_id: int,
    *,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind":
                "stocktake-vehicle-recon-candidate",
            "scope":
                _vehicle_recon_candidate_cursor_scope_hash(
                    scope
                ),
            "id": int(work_session_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(
        raw
    ).decode("ascii").rstrip("=")


# ====================================================
# 11.19 فك Cursor مرشحي تسوية السيارات والتحقق من نطاقه
# ====================================================
def _decode_vehicle_recon_candidate_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(
            (cursor + padding).encode("ascii")
        )
        payload = json.loads(
            raw.decode("utf-8")
        )

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind")
            != "stocktake-vehicle-recon-candidate"
            or payload.get("scope")
            != _vehicle_recon_candidate_cursor_scope_hash(
                expected_scope
            )
        ):
            raise ValueError

        work_session_id = payload.get("id")
        if (
            type(work_session_id) is not int
            or work_session_id <= 0
        ):
            raise ValueError

        return work_session_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cursor جلسات تسوية السيارات "
                "غير صالح أو لا يطابق المستودع الحالي."
            ),
        ) from exc


# ====================================================
# 11.20 جلب جلسات العمل المرشحة لتسوية مخزون السيارات
# ====================================================
@router.get(
    "/warehouse/unified/stocktake/vehicle-recon-candidates",
    response_model=VehicleReconCandidateCursorPage,
    status_code=200,
)
async def list_vehicle_recon_candidates(
    source_location_id: int = Query(
        ...,
        ge=1,
    ),
    search: Optional[str] = Query(
        default=None,
        min_length=2,
        max_length=100,
    ),
    cursor: Optional[str] = Query(
        default=None,
        max_length=1024,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(
        get_current_driver
    ),
):
    access = InventoryAccess(db, current_admin)
    await access.require('location.read', source_location_id)
    await access.require('stocktake.start', any_location=True)

    company_id = current_admin.company_id

    source_exists = (
        await db.execute(
            select(InventoryLocation.id).filter(
                InventoryLocation.company_id
                == company_id,
                InventoryLocation.id
                == source_location_id,
                InventoryLocation.location_type
                == "WAREHOUSE",
                InventoryLocation.is_active.is_(
                    True
                ),
            )
        )
    ).scalar_one_or_none()

    if source_exists is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "المستودع المصدر غير موجود "
                "أو غير فعال أو لا يتبع شركتك."
            ),
        )

    clean_search = (
        search.strip()
        if search
        else ""
    )
    scope = (
        f"{company_id}|"
        f"{source_location_id}|"
        f"{clean_search}"
    )

    base_filters = [
        access.location_filter('stocktake.start'),
        WorkSession.company_id == company_id,
        WorkSession.end_time.is_not(None),
        WorkSession.is_settled.is_(False),
        WorkSession.inventory_reconciled_at
        .is_(None),
    ]

    if clean_search:
        escaped = _escape_like(clean_search)
        pattern = f"%{escaped}%"
        base_filters.append(
            or_(
                Driver.full_name.ilike(
                    pattern,
                    escape="\\",
                ),
                InventoryLocation.name.ilike(
                    pattern,
                    escape="\\",
                ),
                InventoryLocation.code.ilike(
                    pattern,
                    escape="\\",
                ),
            )
        )

    def _candidate_query_columns():
        return (
            WorkSession.id.label(
                "work_session_id"
            ),
            WorkSession.driver_id,
            Driver.full_name.label(
                "driver_name"
            ),
            WorkSession.session_date,
            WorkSession.end_time,
            DispatchRoute.vehicle_id,
            InventoryLocation.id.label(
                "vehicle_location_id"
            ),
            InventoryLocation.name.label(
                "vehicle_location_name"
            ),
            InventoryLocation.code.label(
                "vehicle_location_code"
            ),
        )

    def _candidate_joins(stmt):
        return (
            stmt
            .join(
                DispatchRoute,
                and_(
                    DispatchRoute.company_id
                    == WorkSession.company_id,
                    DispatchRoute.work_session_id
                    == WorkSession.id,
                    DispatchRoute.driver_id
                    == WorkSession.driver_id,
                    DispatchRoute.source_location_id
                    == source_location_id,
                    DispatchRoute.vehicle_id
                    .is_not(None),
                ),
            )
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id
                    == WorkSession.company_id,
                    InventoryLocation.vehicle_id
                    == DispatchRoute.vehicle_id,
                    InventoryLocation.location_type
                    == "VEHICLE",
                    InventoryLocation.is_active
                    .is_(True),
                ),
            )
            .join(
                Driver,
                and_(
                    Driver.company_id
                    == WorkSession.company_id,
                    Driver.id
                    == WorkSession.driver_id,
                ),
            )
        )

    total = None
    if cursor is None:
        count_stmt = _candidate_joins(
            select(
                func.count(
                    WorkSession.id
                )
            ).select_from(WorkSession)
        ).filter(*base_filters)

        total = int(
            (
                await db.execute(
                    count_stmt
                )
            ).scalar_one()
        )

    stmt = _candidate_joins(
        select(
            *_candidate_query_columns()
        ).select_from(WorkSession)
    ).filter(*base_filters)

    if cursor is not None:
        cursor_id = (
            _decode_vehicle_recon_candidate_cursor(
                cursor,
                expected_scope=scope,
            )
        )
        stmt = stmt.filter(
            WorkSession.id < cursor_id
        )

    rows = (
        await db.execute(
            stmt.order_by(
                WorkSession.id.desc()
            ).limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor = None
    if has_more and page_rows:
        next_cursor = (
            _encode_vehicle_recon_candidate_cursor(
                int(
                    page_rows[-1]
                    .work_session_id
                ),
                scope=scope,
            )
        )

    work_session_ids = [
        int(row.work_session_id)
        for row in page_rows
    ]
    existing_by_work_session = {}

    if work_session_ids:
        existing_rows = (
            await db.execute(
                select(
                    StocktakeSession
                    .related_work_session_id,
                    StocktakeSession.id,
                    StocktakeSession
                    .reference_number,
                    StocktakeSession.status,
                )
                .filter(
                    StocktakeSession.company_id
                    == company_id,
                    StocktakeSession.stocktake_type
                    == "VEHICLE_RECON",
                    StocktakeSession
                    .related_work_session_id
                    .in_(work_session_ids),
                    StocktakeSession.status
                    != "CANCELLED",
                )
                .order_by(
                    StocktakeSession
                    .related_work_session_id
                    .asc(),
                    StocktakeSession.id.desc(),
                )
            )
        ).all()

        for existing in existing_rows:
            work_session_id = int(
                existing.related_work_session_id
            )
            if (
                work_session_id
                not in existing_by_work_session
            ):
                existing_by_work_session[
                    work_session_id
                ] = existing

    items = []
    for row in page_rows:
        work_session_id = int(
            row.work_session_id
        )
        existing = (
            existing_by_work_session.get(
                work_session_id
            )
        )

        items.append(
            {
                "work_session_id":
                    work_session_id,
                "driver_id":
                    int(row.driver_id),
                "driver_name":
                    str(row.driver_name),
                "session_date":
                    row.session_date,
                "end_time":
                    row.end_time,
                "vehicle_id":
                    int(row.vehicle_id),
                "vehicle_location_id":
                    int(
                        row.vehicle_location_id
                    ),
                "vehicle_location_name":
                    str(
                        row
                        .vehicle_location_name
                    ),
                "vehicle_location_code":
                    str(
                        row
                        .vehicle_location_code
                    ),
                "existing_stocktake_session_id":
                    (
                        int(existing.id)
                        if existing is not None
                        else None
                    ),
                "existing_stocktake_reference":
                    (
                        str(
                            existing
                            .reference_number
                        )
                        if existing is not None
                        else None
                    ),
                "existing_stocktake_status":
                    (
                        str(existing.status)
                        if existing is not None
                        else None
                    ),
            }
        )

    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


# ====================================================
# 11.21 حالات جلسات الجرد النشطة والاستعلام عنها
# ====================================================
_ACTIVE_STOCKTAKE_STATUSES = frozenset({
    "DRAFT",
    "COUNTING",
    "PENDING_REVIEW",
    "RECOUNT_REQUIRED",
    "APPROVED",
})


# ====================================================
# 11.21 جلب جلسات الجرد النشطة للموقع باستخدام Cursor
# ====================================================
@router.get(
    "/warehouse/unified/stocktakes/active",
    response_model=StocktakeActiveSessionCursorPage,
    status_code=200,
)
async def list_active_stocktake_sessions(
    location_id: int = Query(..., ge=1),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('stocktake.read', location_id)

    company_id = current_admin.company_id

    location_exists = (
        await db.execute(
            select(InventoryLocation.id).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
                InventoryLocation.is_active.is_(True),
                InventoryLocation.location_type.in_(["WAREHOUSE", "VEHICLE"]),
            )
        )
    ).scalar_one_or_none()

    if location_exists is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "موقع الجرد غير موجود أو غير فعال "
                "أو لا يتبع شركتك."
            ),
        )

    scope = f"{company_id}|{location_id}|active"

    base_filters = (
        StocktakeSession.company_id == company_id,
        StocktakeSession.location_id == location_id,
        StocktakeSession.status.in_(_ACTIVE_STOCKTAKE_STATUSES),
    )

    stmt = (
        select(
            StocktakeSession.id,
            StocktakeSession.reference_number,
            StocktakeSession.stocktake_type,
            StocktakeSession.status,
            StocktakeSession.location_id,
            StocktakeSession.scope_product_variant_id,
            ProductVariant.name.label("scope_product_name"),
            StocktakeSession.scope_batch_id,
            ProductBatch.batch_number.label("scope_batch_number"),
            StocktakeSession.related_work_session_id,
            StocktakeSession.started_by,
            Driver.full_name.label("started_by_name"),
            StocktakeSession.pending_independent_recount_required,
            StocktakeSession.snapshot_cutoff_at,
            StocktakeSession.created_at,
            StocktakeSession.updated_at,
        )
        .outerjoin(
            ProductVariant,
            and_(
                ProductVariant.company_id == StocktakeSession.company_id,
                ProductVariant.id == StocktakeSession.scope_product_variant_id,
            ),
        )
        .outerjoin(
            ProductBatch,
            and_(
                ProductBatch.company_id == StocktakeSession.company_id,
                ProductBatch.product_variant_id
                == StocktakeSession.scope_product_variant_id,
                ProductBatch.id == StocktakeSession.scope_batch_id,
            ),
        )
        .join(
            Driver,
            and_(
                Driver.company_id == StocktakeSession.company_id,
                Driver.id == StocktakeSession.started_by,
            ),
        )
        .filter(*base_filters)
    )

    total = None
    if cursor is None:
        total = int(
            (
                await db.execute(
                    select(func.count(StocktakeSession.id))
                    .filter(*base_filters)
                )
            ).scalar_one()
        )

    if cursor is not None:
        cursor_id = _decode_stocktake_cursor(
            cursor,
            expected_scope=scope,
        )
        stmt = stmt.filter(StocktakeSession.id < cursor_id)

    rows = (
        await db.execute(
            stmt.order_by(StocktakeSession.id.desc())
            .limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor = None
    if has_more and page_rows:
        next_cursor = _encode_stocktake_cursor(
            int(page_rows[-1].id),
            scope=scope,
        )

    return {
        "items": [
            {
                "id": int(row.id),
                "reference_number": str(row.reference_number),
                "stocktake_type": str(row.stocktake_type),
                "status": str(row.status),
                "location_id": int(row.location_id),
                "scope_product_variant_id": (
                    int(row.scope_product_variant_id)
                    if row.scope_product_variant_id is not None
                    else None
                ),
                "scope_product_name": row.scope_product_name,
                "scope_batch_id": (
                    int(row.scope_batch_id)
                    if row.scope_batch_id is not None
                    else None
                ),
                "scope_batch_number": row.scope_batch_number,
                "related_work_session_id": (
                    int(row.related_work_session_id)
                    if row.related_work_session_id is not None
                    else None
                ),
                "started_by": int(row.started_by),
                "started_by_name": str(row.started_by_name),
                "pending_independent_recount_required": bool(
                    row.pending_independent_recount_required
                ),
                "snapshot_cutoff_at": row.snapshot_cutoff_at,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in page_rows
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


# ====================================================
# 11.22 جلب سياق جلسة الجرد والتحقق من ارتباطها بالمستودع
# ====================================================
@router.get(
    "/warehouse/unified/stocktake/{session_id}/context",
    response_model=StocktakeSessionContextResponse,
    status_code=200,
)
async def get_stocktake_session_context(
    session_id: int,
    anchor_location_id: int = Query(
        ...,
        ge=1,
    ),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(
        get_current_driver
    ),
):
    access = InventoryAccess(db, current_admin)
    await access.require('location.read', anchor_location_id)
    await require_stocktake(access, 'stocktake.read', session_id)

    company_id = current_admin.company_id

    anchor_exists = (
        await db.execute(
            select(InventoryLocation.id).filter(
                InventoryLocation.company_id
                == company_id,
                InventoryLocation.id
                == anchor_location_id,
                InventoryLocation.location_type
                == "WAREHOUSE",
                InventoryLocation.is_active.is_(
                    True
                ),
            )
        )
    ).scalar_one_or_none()

    if anchor_exists is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "مستودع سياق الجرد غير موجود "
                "أو غير فعال أو لا يتبع شركتك."
            ),
        )

    session = (
        await db.execute(
            select(
                StocktakeSession.id,
                StocktakeSession.stocktake_type,
                StocktakeSession.status,
                StocktakeSession.location_id,
                StocktakeSession.related_work_session_id,
            ).filter(
                StocktakeSession.company_id
                == company_id,
                StocktakeSession.id
                == session_id,
            )
        )
    ).one_or_none()

    if session is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "جلسة الجرد غير موجودة "
                "أو لا تتبع شركتك."
            ),
        )

    stocktake_type = str(
        session.stocktake_type
    )
    actual_location_id = int(
        session.location_id
    )
    related_work_session_id = (
        int(
            session
            .related_work_session_id
        )
        if session
        .related_work_session_id
        is not None
        else None
    )

    if stocktake_type in {
        "FULL_COUNT",
        "CYCLE_COUNT",
    }:
        if (
            actual_location_id
            != anchor_location_id
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "جلسة الجرد لا تتبع "
                    "المستودع المحدد."
                ),
            )
    elif stocktake_type == "VEHICLE_RECON":
        if related_work_session_id is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "VEHICLE_RECON بلا "
                    "related_work_session_id صالح."
                ),
            )

        vehicle_id = (
            await db.execute(
                select(
                    InventoryLocation.vehicle_id
                ).filter(
                    InventoryLocation.company_id
                    == company_id,
                    InventoryLocation.id
                    == actual_location_id,
                    InventoryLocation.location_type
                    == "VEHICLE",
                    InventoryLocation.is_active
                    .is_(True),
                )
            )
        ).scalar_one_or_none()

        if vehicle_id is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "موقع VEHICLE_RECON "
                    "ليس موقع سيارة فعالاً."
                ),
            )

        route_source = (
            await db.execute(
                select(
                    DispatchRoute
                    .source_location_id
                )
                .filter(
                    DispatchRoute.company_id
                    == company_id,
                    DispatchRoute.work_session_id
                    == related_work_session_id,
                    DispatchRoute.vehicle_id
                    == vehicle_id,
                    DispatchRoute
                    .source_location_id
                    == anchor_location_id,
                )
                .order_by(
                    DispatchRoute.id.desc()
                )
                .limit(1)
            )
        ).scalar_one_or_none()

        if route_source is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "جلسة السيارة لا ترتبط "
                    "بالمستودع المحدد."
                ),
            )
    else:
        raise HTTPException(
            status_code=409,
            detail="نوع جلسة الجرد غير مدعوم.",
        )

    return {
        "session_id": int(session.id),
        "stocktake_type":
            stocktake_type,
        "status":
            str(session.status),
        "location_id":
            actual_location_id,
        "related_work_session_id":
            related_work_session_id,
        "source_location_id":
            int(anchor_location_id),
    }


# ====================================================
# 11.23 بدء جلسة الجرد وأخذ Snapshot مقفل للنطاق
# ====================================================
@router.post("/warehouse/unified/stocktake/start", status_code=201)
async def start_unified_stocktake(
    payload: UnifiedStocktakeStartRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    """فتح الجلسة وأخذ Snapshot ثابت وإنشاء Lock مطابق للنطاق."""
    access = InventoryAccess(db, current_admin)
    await access.require('stocktake.start', payload.location_id)

    company_id = current_admin.company_id

    try:
        expected_location_type = 'VEHICLE' if payload.stocktake_type == 'VEHICLE_RECON' else 'WAREHOUSE'
        location = (
            await db.execute(
                select(InventoryLocation).filter_by(
                    id=payload.location_id,
                    company_id=company_id,
                    location_type=expected_location_type,
                    is_active=True,
                )
            )
        ).scalar_one_or_none()
        if location is None:
            raise HTTPException(status_code=404, detail="الموقع غير موجود أو غير فعال أو لا يتبع شركتك.")

        if payload.product_variant_id is not None:
            variant_id = (
                await db.execute(
                    select(ProductVariant.id).filter_by(
                        id=payload.product_variant_id,
                        company_id=company_id,
                    )
                )
            ).scalar_one_or_none()
            if variant_id is None:
                raise HTTPException(status_code=404, detail="الصنف المحدد غير موجود أو لا يتبع شركتك.")

        if payload.batch_id is not None:
            batch_id = (
                await db.execute(
                    select(ProductBatch.id).filter_by(
                        id=payload.batch_id,
                        company_id=company_id,
                        product_variant_id=payload.product_variant_id,
                    )
                )
            ).scalar_one_or_none()
            if batch_id is None:
                raise HTTPException(status_code=404, detail="الدفعة المحددة غير موجودة أو لا تتبع الصنف والشركة.")

        # ترتيب القفل ثابت: موقع المخزون أولاً، ثم WorkSession.
        # هذا يطابق posting ويمنع سباق Start/Approve مع التسوية.
        await acquire_inventory_location_guard(
            db,
            company_id,
            payload.location_id,
            exclusive=True,
        )

        if payload.stocktake_type == 'VEHICLE_RECON':
            if location.vehicle_id is None:
                raise HTTPException(
                    status_code=409,
                    detail="موقع السيارة لا يحمل vehicle_id صالحاً.",
                )

            try:
                await validate_vehicle_recon_work_session(
                    db,
                    company_id=company_id,
                    work_session_id=payload.related_work_session_id,
                    vehicle_id=location.vehicle_id,
                )
            except InventoryMutationError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=str(exc),
                ) from exc

            existing_recon_id = (
                await db.execute(
                    select(StocktakeSession.id).filter(
                        StocktakeSession.company_id == company_id,
                        StocktakeSession.stocktake_type == 'VEHICLE_RECON',
                        StocktakeSession.related_work_session_id
                        == payload.related_work_session_id,
                        StocktakeSession.status != 'CANCELLED',
                    )
                    .order_by(StocktakeSession.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if existing_recon_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "جلسة العمل مرتبطة مسبقاً بـ VEHICLE_RECON غير ملغى؛ "
                        "لا يمكن إنشاء تسوية مخزون ثانية لنفس الجلسة."
                    ),
                )

        session_overlap = _stocktake_session_overlap_predicate(
            payload.stocktake_type,
            payload.product_variant_id,
            payload.batch_id,
        )
        stmt_session_overlap = select(StocktakeSession.id).filter(
            StocktakeSession.company_id == company_id,
            StocktakeSession.location_id == payload.location_id,
            StocktakeSession.status.in_(_STOCKTAKE_ACTIVE_STATUSES),
        )
        if session_overlap is not None:
            stmt_session_overlap = stmt_session_overlap.filter(session_overlap)
        conflicting_session_id = (
            await db.execute(
                stmt_session_overlap.order_by(StocktakeSession.id.asc()).limit(1).with_for_update()
            )
        ).scalar_one_or_none()
        if conflicting_session_id is not None:
            raise HTTPException(
                status_code=409,
                detail="يوجد جرد نشط يتداخل مع نفس الموقع/الصنف/الدفعة.",
            )

        lock_overlap = _inventory_lock_overlap_predicate(
            payload.stocktake_type,
            payload.product_variant_id,
            payload.batch_id,
        )
        stmt_lock_overlap = select(InventoryLock.id).filter(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == payload.location_id,
            InventoryLock.released_at.is_(None),
        )
        if lock_overlap is not None:
            stmt_lock_overlap = stmt_lock_overlap.filter(lock_overlap)
        conflicting_lock_id = (
            await db.execute(
                stmt_lock_overlap.order_by(InventoryLock.id.asc()).limit(1).with_for_update()
            )
        ).scalar_one_or_none()
        if conflicting_lock_id is not None:
            raise HTTPException(status_code=409, detail="يوجد قفل جرد فعال يتداخل مع النطاق المطلوب.")

        reference_number = f"STK-{uuid.uuid4().hex[:12].upper()}"
        session = StocktakeSession(
            company_id=company_id,
            location_id=payload.location_id,
            reference_number=reference_number,
            stocktake_type=payload.stocktake_type,
            status='DRAFT',
            scope_product_variant_id=payload.product_variant_id if payload.stocktake_type == 'CYCLE_COUNT' else None,
            scope_batch_id=payload.batch_id if payload.stocktake_type == 'CYCLE_COUNT' else None,
            related_work_session_id=payload.related_work_session_id if payload.stocktake_type == 'VEHICLE_RECON' else None,
            started_by=current_admin.id,
            notes=payload.notes,
        )
        db.add(session)
        await db.flush()

        db.add(InventoryLock(
            company_id=company_id,
            stocktake_session_id=session.id,
            location_id=payload.location_id,
            product_variant_id=payload.product_variant_id if payload.stocktake_type == 'CYCLE_COUNT' else None,
            batch_id=payload.batch_id if payload.stocktake_type == 'CYCLE_COUNT' else None,
            created_by=current_admin.id,
        ))
        await db.flush()

        stmt_balances = select(InventoryBalance).filter(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == payload.location_id,
            InventoryBalance.on_hand_quantity > 0,
        )
        if payload.stocktake_type == 'CYCLE_COUNT':
            stmt_balances = stmt_balances.filter(
                InventoryBalance.product_variant_id == payload.product_variant_id
            )
            if payload.batch_id is not None:
                stmt_balances = stmt_balances.filter(InventoryBalance.batch_id == payload.batch_id)

        balances = (
            await db.execute(
                stmt_balances
                .order_by(
                    InventoryBalance.product_variant_id.asc(),
                    InventoryBalance.batch_id.asc(),
                    InventoryBalance.stock_status.asc(),
                    InventoryBalance.id.asc(),
                )
                .limit(_MAX_STOCKTAKE_LINES + 1)
                .with_for_update()
            )
        ).scalars().all()
        if len(balances) > _MAX_STOCKTAKE_LINES:
            raise HTTPException(
                status_code=409,
                detail="نطاق الجرد يتجاوز 10000 سطر؛ استخدم CYCLE_COUNT أصغر.",
            )

        for balance in balances:
            db.add(StocktakeLine(
                company_id=company_id,
                stocktake_session_id=session.id,
                product_variant_id=balance.product_variant_id,
                batch_id=balance.batch_id,
                stock_status=balance.stock_status,
                line_origin='SNAPSHOT',
                expected_quantity=Decimal(balance.on_hand_quantity),
            ))

        cutoff = _utc_naive_now()
        session.snapshot_cutoff_at = cutoff
        session.status = 'COUNTING'
        session.updated_at = cutoff
        await db.commit()

        return {
            "message": "تم بدء جلسة الجرد وأخذ Snapshot مقفل بنجاح.",
            "reference_number": reference_number,
            "session_id": session.id,
            "stocktake_type": session.stocktake_type,
            "snapshot_lines": len(balances),
        }

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.warning(f"تعارض متزامن أثناء بدء الجرد: {e}", exc_info=True)
        raise HTTPException(status_code=409, detail="حدث تعارض متزامن أثناء فتح الجرد؛ لم تُحفظ جلسة جزئية.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في بدء الجرد: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء فتح جلسة الجرد.")


# Blind Count: لا يتم إرجاع expected_quantity.


# ====================================================
# 11.24 جلب ورقة العد العمياء لجلسة الجرد
# ====================================================
@router.get("/warehouse/unified/stocktake/{session_id}/count-sheet", status_code=200)
async def get_stocktake_count_sheet(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await require_stocktake(access, 'stocktake.count', session_id)

    company_id = current_admin.company_id
    session = await _load_stocktake_session(db, company_id, session_id)

    if session.status not in {'COUNTING', 'RECOUNT_REQUIRED'}:
        raise HTTPException(status_code=409, detail=f"لا يمكن فتح ورقة العد بحالة ({session.status}).")

    if session.status == 'RECOUNT_REQUIRED' and session.pending_independent_recount_required:
        previous_attempt = await _latest_stocktake_attempt(db, company_id, session.id)
        if previous_attempt is not None and previous_attempt.counted_by == current_admin.id:
            raise HTTPException(status_code=403, detail="إعادة العد المستقلة يجب أن ينفذها مستخدم آخر.")

    rows = (
        await db.execute(
            select(
                StocktakeLine,
                ProductVariant.name,
                ProductVariant.base_uom_id,
                ProductVariant.quantity_scale,
                ProductVariant.quantity_step,
                UOM.code,
                UOM.name,
                ProductBatch.batch_number,
                ProductBatch.expiry_date,
            )
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == StocktakeLine.company_id,
                    ProductVariant.id == StocktakeLine.product_variant_id,
                ),
            )
            .join(
                UOM,
                UOM.id == ProductVariant.base_uom_id,
            )
            .join(
                ProductBatch,
                and_(
                    ProductBatch.company_id == StocktakeLine.company_id,
                    ProductBatch.product_variant_id == StocktakeLine.product_variant_id,
                    ProductBatch.id == StocktakeLine.batch_id,
                ),
            )
            .filter(
                StocktakeLine.company_id == company_id,
                StocktakeLine.stocktake_session_id == session.id,
            )
            .order_by(
                ProductVariant.name.asc(),
                ProductBatch.expiry_date.asc(),
                ProductBatch.id.asc(),
                StocktakeLine.stock_status.asc(),
            )
        )
    ).all()

    return [{
        "stocktake_line_id": line.id,
        "product_variant_id": line.product_variant_id,
        "batch_id": line.batch_id,
        "stock_status": line.stock_status,
        "line_origin": line.line_origin,
        "product_name": product_name,
        "base_uom_id": base_uom_id,
        "base_uom_code": base_uom_code,
        "base_uom_name": base_uom_name,
        "quantity_scale": quantity_scale,
        "quantity_step": canonical_quantity(quantity_step),
        "batch_number": batch_number,
        "expiry_date": expiry_date.isoformat(),
    } for (
        line, product_name, base_uom_id, quantity_scale, quantity_step,
        base_uom_code, base_uom_name, batch_number, expiry_date,
    ) in rows]


# ====================================================
# 11.25 تثبيت محاولة العد ومعالجة الفروقات والأسطر المكتشفة
# ====================================================
@router.post("/warehouse/unified/stocktake/{session_id}/count", status_code=200)
async def submit_stocktake_count(
    session_id: int,
    payload: UnifiedStocktakeCountRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    """Attempt immutable + DISCOVERED lines معروفة في ProductBatch."""
    access = InventoryAccess(db, current_admin)
    await require_stocktake(access, 'stocktake.count', session_id)

    company_id = current_admin.company_id

    try:
        session = await _load_stocktake_session(db, company_id, session_id, for_update=True)
        if session.status not in {'COUNTING', 'RECOUNT_REQUIRED'}:
            raise HTTPException(status_code=409, detail=f"لا يمكن تثبيت عد بحالة ({session.status}).")

        previous_attempt = await _latest_stocktake_attempt(db, company_id, session.id)
        if session.status == 'COUNTING' and previous_attempt is not None:
            raise HTTPException(status_code=409, detail="توجد محاولة سابقة؛ Attempt جديد يتطلب Recount موثقاً.")

        if session.status == 'RECOUNT_REQUIRED':
            if session.pending_recount_authorized_by is None or not session.pending_recount_reason:
                raise HTTPException(status_code=409, detail="إعادة العد لا تحمل تفويضاً موثقاً.")
            if previous_attempt is None:
                raise HTTPException(status_code=409, detail="RECOUNT_REQUIRED بدون محاولة سابقة.")
            if session.pending_independent_recount_required and previous_attempt.counted_by == current_admin.id:
                raise HTTPException(status_code=403, detail="إعادة العد المستقلة يجب أن ينفذها مستخدم آخر.")

        existing_lines = (
            await db.execute(
                select(StocktakeLine)
                .filter_by(company_id=company_id, stocktake_session_id=session.id)
                .order_by(
                    StocktakeLine.product_variant_id.asc(),
                    StocktakeLine.batch_id.asc(),
                    StocktakeLine.stock_status.asc(),
                    StocktakeLine.id.asc(),
                )
            )
        ).scalars().all()
        line_map = {
            (line.product_variant_id, line.batch_id, line.stock_status): line
            for line in existing_lines
        }
        if len(line_map) != len(existing_lines):
            raise HTTPException(status_code=409, detail="جلسة الجرد تحتوي أسطر Snapshot مكررة.")

        submitted_variant_ids = {item.product_variant_id for item in payload.items}
        variant_rows = (
            await db.execute(
                select(
                    ProductVariant.id,
                    ProductVariant.base_uom_id,
                    ProductVariant.quantity_scale,
                    ProductVariant.quantity_step,
                ).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(submitted_variant_ids),
                )
            )
        ).all()
        variant_rules = {
            row.id: (row.base_uom_id, row.quantity_scale, row.quantity_step)
            for row in variant_rows
        }
        if set(variant_rules) != submitted_variant_ids:
            raise HTTPException(status_code=422, detail="محاولة العد تحتوي صنفاً غير معروف أو لا يتبع شركتك.")

        submitted_map = {}
        for item in payload.items:
            base_uom_id, quantity_scale, quantity_step = variant_rules[item.product_variant_id]
            if item.uom_id != base_uom_id:
                raise HTTPException(
                    status_code=422,
                    detail="كمية العد يجب أن ترسل بوحدة الأساس الخاصة بالصنف.",
                )
            submitted_map[(item.product_variant_id, item.batch_id, item.stock_status)] = (
                validate_variant_quantity(
                    item.actual_quantity,
                    quantity_scale=quantity_scale,
                    quantity_step=quantity_step,
                    field_name="actual_quantity",
                    allow_zero=True,
                )
            )
        missing_keys = set(line_map) - set(submitted_map)
        if missing_keys:
            raise HTTPException(
                status_code=422,
                detail=f"يوجد {len(missing_keys)} سطر لم يتم عده؛ السطر غير المرسل لا يُعامل كصفر.",
            )

        discovered_keys = set(submitted_map) - set(line_map)
        if discovered_keys:
            zero_discovered = [
                key
                for key in discovered_keys
                if submitted_map[key] <= 0
            ]
            if zero_discovered:
                raise HTTPException(
                    status_code=422,
                    detail="DISCOVERED جديد يجب أن يحمل كمية فعلية أكبر من صفر.",
                )

            as_of_date = await get_company_local_date(db, company_id)

            batch_rows = (
                await db.execute(
                    select(
                        ProductBatch.id,
                        ProductBatch.product_variant_id,
                        ProductBatch.production_date,
                        ProductBatch.expiry_date,
                        ProductBatch.is_active,
                        ProductVariant.lifecycle_status.in_(['ACTIVE', 'RETIRING']).label("variant_is_countable"),
                    )
                    .join(
                        ProductVariant,
                        and_(
                            ProductVariant.company_id == ProductBatch.company_id,
                            ProductVariant.id == ProductBatch.product_variant_id,
                        ),
                    )
                    .filter(
                        ProductBatch.company_id == company_id,
                        ProductBatch.id.in_({
                            batch_id
                            for _, batch_id, _ in discovered_keys
                        }),
                    )
                )
            ).all()

            batch_map = {
                (product_variant_id, batch_id): (
                    production_date,
                    expiry_date,
                    batch_is_active,
                    variant_is_countable,
                )
                for (
                    batch_id,
                    product_variant_id,
                    production_date,
                    expiry_date,
                    batch_is_active,
                    variant_is_countable,
                ) in batch_rows
            }

            for product_variant_id, batch_id, stock_status in sorted(discovered_keys):
                batch_meta = batch_map.get(
                    (product_variant_id, batch_id)
                )

                if batch_meta is None:
                    raise HTTPException(
                        status_code=422,
                        detail="DISCOVERED صنف/دفعة غير معروف أو لا يتبع شركتك.",
                    )

                (
                    production_date,
                    expiry_date,
                    batch_is_active,
                    variant_is_countable,
                ) = batch_meta

                if (
                    production_date is not None
                    and production_date > as_of_date
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="DISCOVERED يشير إلى دفعة بتاريخ إنتاج مستقبلي وغير صالح.",
                    )

                if stock_status == 'AVAILABLE':
                    if not batch_is_active or not variant_is_countable:
                        raise HTTPException(
                            status_code=422,
                            detail="DISCOVERED بحالة AVAILABLE يتطلب صنفاً ودفعة فعالين.",
                        )

                if session.stocktake_type == 'CYCLE_COUNT':
                    if product_variant_id != session.scope_product_variant_id:
                        raise HTTPException(
                            status_code=422,
                            detail="DISCOVERED خارج نطاق صنف CYCLE_COUNT.",
                        )

                    if (
                        session.scope_batch_id is not None
                        and batch_id != session.scope_batch_id
                    ):
                        raise HTTPException(
                            status_code=422,
                            detail="DISCOVERED خارج نطاق دفعة CYCLE_COUNT.",
                        )

                line = StocktakeLine(
                    company_id=company_id,
                    stocktake_session_id=session.id,
                    product_variant_id=product_variant_id,
                    batch_id=batch_id,
                    stock_status=stock_status,
                    line_origin='DISCOVERED',
                    expected_quantity=0,
                    discovered_by=current_admin.id,
                    discovered_at=_utc_naive_now(),
                    notes="تم اكتشافه أثناء العد الفعلي.",
                )
                db.add(line)
                line_map[
                    (product_variant_id, batch_id, stock_status)
                ] = line

            await db.flush()

        all_lines = sorted(
            line_map.values(),
            key=lambda line: (line.product_variant_id, line.batch_id, line.stock_status, line.id),
        )
        if len(all_lines) > _MAX_STOCKTAKE_LINES:
            raise HTTPException(status_code=422, detail="محاولة العد تتجاوز الحد الآمن البالغ 10000 سطر.")

        attempt_number = previous_attempt.attempt_number + 1 if previous_attempt is not None else 1
        is_recount = session.status == 'RECOUNT_REQUIRED'
        attempt = StocktakeCountAttempt(
            company_id=company_id,
            stocktake_session_id=session.id,
            attempt_number=attempt_number,
            recount_of_attempt_id=previous_attempt.id if is_recount else None,
            counted_by=current_admin.id,
            authorized_by=session.pending_recount_authorized_by if is_recount else None,
            recount_reason=session.pending_recount_reason if is_recount else None,
        )
        db.add(attempt)
        await db.flush()

        attempt_line_values = []
        for line in all_lines:
            key = (line.product_variant_id, line.batch_id, line.stock_status)
            expected_quantity = Decimal(line.expected_quantity)
            actual_quantity = submitted_map[key]
            variance_quantity = actual_quantity - expected_quantity
            db.add(StocktakeCountAttemptLine(
                company_id=company_id,
                stocktake_session_id=session.id,
                count_attempt_id=attempt.id,
                stocktake_line_id=line.id,
                expected_quantity=expected_quantity,
                actual_quantity=actual_quantity,
                variance_quantity=variance_quantity,
            ))
            attempt_line_values.append((expected_quantity, variance_quantity))

        requires_independent = await _requires_independent_stocktake_recount(
            db, company_id, attempt_line_values
        )
        attempt.requires_independent_recount = requires_independent

        session.status = 'PENDING_REVIEW'
        session.pending_recount_authorized_by = None
        session.pending_recount_reason = None
        session.pending_independent_recount_required = False
        session.updated_at = _utc_naive_now()
        if payload.notes:
            session.notes = f"{session.notes or ''} | Attempt #{attempt_number}: {payload.notes}".strip(" |")

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Stocktake_{session.id}",
            action_type="STOCKTAKE_COUNT_SUBMITTED",
            old_value=f"previous_attempt={previous_attempt.id if previous_attempt else None}",
            new_value=json.dumps({
                "attempt_id": attempt.id,
                "attempt_number": attempt_number,
                "counted_by": current_admin.id,
                "recount_of_attempt_id": attempt.recount_of_attempt_id,
                "requires_independent_recount": requires_independent,
                "line_count": len(all_lines),
            }, ensure_ascii=False),
        ))
        await db.commit()

        return {
            "message": "تم تثبيت محاولة العد بنجاح.",
            "attempt_id": attempt.id,
            "attempt_number": attempt_number,
            "requires_independent_recount": requires_independent,
            "status": "PENDING_REVIEW",
        }

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.warning(f"تعارض متزامن أثناء تثبيت الجرد: {e}", exc_info=True)
        raise HTTPException(status_code=409, detail="حدث تعارض متزامن أثناء تثبيت العد؛ لم يُحفظ Attempt جزئي.")
    except QuantityError as e:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في تثبيت الجرد: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تثبيت محاولة الجرد.")


# ====================================================
# 11.26 مراجعة أحدث محاولة عد وسجل المحاولات وفروقات الجرد
# ====================================================
@router.get("/warehouse/unified/stocktake/{session_id}/review", status_code=200)
async def get_stocktake_review(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await require_stocktake(access, 'stocktake.review', session_id)

    company_id = current_admin.company_id
    if not current_admin.is_admin:
        raise HTTPException(status_code=403, detail="مراجعة الجرد تتطلب صلاحية مشرف.")

    session = await _load_stocktake_session(db, company_id, session_id)
    if session.status != 'PENDING_REVIEW':
        raise HTTPException(status_code=409, detail=f"الجلسة ليست بانتظار المراجعة؛ حالتها ({session.status}).")

    attempts = (
        await db.execute(
            select(StocktakeCountAttempt)
            .filter_by(company_id=company_id, stocktake_session_id=session.id)
            .order_by(StocktakeCountAttempt.attempt_number.asc(), StocktakeCountAttempt.id.asc())
        )
    ).scalars().all()
    if not attempts:
        raise HTTPException(status_code=409, detail="لا توجد محاولة عد مثبتة لهذه الجلسة.")

    latest_attempt = attempts[-1]
    attempts_by_id = {attempt.id: attempt for attempt in attempts}
    parent_attempt = attempts_by_id.get(latest_attempt.recount_of_attempt_id)
    independent_recount_satisfied = (
        not latest_attempt.requires_independent_recount
        or (
            parent_attempt is not None
            and parent_attempt.requires_independent_recount
            and parent_attempt.counted_by != latest_attempt.counted_by
            and parent_attempt.attempt_number == latest_attempt.attempt_number - 1
        )
    )

    user_ids = {
        user_id
        for attempt in attempts
        for user_id in (attempt.counted_by, attempt.authorized_by)
        if user_id is not None
    }
    users_map = {}
    if user_ids:
        users_map = {
            user_id: full_name
            for user_id, full_name in (
                await db.execute(
                    select(Driver.id, Driver.full_name).filter(
                        Driver.company_id == company_id,
                        Driver.id.in_(user_ids),
                    )
                )
            ).all()
        }

    rows = (
        await db.execute(
            select(
                StocktakeCountAttemptLine,
                StocktakeLine,
                ProductVariant.name,
                ProductVariant.base_uom_id,
                ProductVariant.quantity_scale,
                ProductVariant.quantity_step,
                UOM.code,
                UOM.name,
                ProductBatch.batch_number,
                ProductBatch.expiry_date,
            )
            .join(
                StocktakeLine,
                and_(
                    StocktakeLine.company_id == StocktakeCountAttemptLine.company_id,
                    StocktakeLine.stocktake_session_id == StocktakeCountAttemptLine.stocktake_session_id,
                    StocktakeLine.id == StocktakeCountAttemptLine.stocktake_line_id,
                ),
            )
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == StocktakeLine.company_id,
                    ProductVariant.id == StocktakeLine.product_variant_id,
                ),
            )
            .join(
                UOM,
                UOM.id == ProductVariant.base_uom_id,
            )
            .join(
                ProductBatch,
                and_(
                    ProductBatch.company_id == StocktakeLine.company_id,
                    ProductBatch.product_variant_id == StocktakeLine.product_variant_id,
                    ProductBatch.id == StocktakeLine.batch_id,
                ),
            )
            .filter(
                StocktakeCountAttemptLine.company_id == company_id,
                StocktakeCountAttemptLine.stocktake_session_id == session.id,
                StocktakeCountAttemptLine.count_attempt_id == latest_attempt.id,
            )
            .order_by(
                ProductVariant.name.asc(),
                ProductBatch.expiry_date.asc(),
                ProductBatch.id.asc(),
                StocktakeLine.stock_status.asc(),
            )
        )
    ).all()

    return {
        "session_id": session.id,
        "reference_number": session.reference_number,
        "stocktake_type": session.stocktake_type,
        "status": session.status,
        "location_id": session.location_id,
        "scope_product_variant_id": session.scope_product_variant_id,
        "scope_batch_id": session.scope_batch_id,
        "related_work_session_id": session.related_work_session_id,
        "snapshot_cutoff_at": _iso_utc(session.snapshot_cutoff_at),
        "independent_recount_satisfied": independent_recount_satisfied,
        "latest_attempt": {
            "id": latest_attempt.id,
            "attempt_number": latest_attempt.attempt_number,
            "counted_by": latest_attempt.counted_by,
            "counted_by_name": users_map.get(latest_attempt.counted_by, "غير معروف"),
            "authorized_by": latest_attempt.authorized_by,
            "authorized_by_name": users_map.get(latest_attempt.authorized_by) if latest_attempt.authorized_by else None,
            "recount_of_attempt_id": latest_attempt.recount_of_attempt_id,
            "recount_reason": latest_attempt.recount_reason,
            "requires_independent_recount": latest_attempt.requires_independent_recount,
            "submitted_at": _iso_utc(latest_attempt.submitted_at),
        },
        "attempt_history": [{
            "id": attempt.id,
            "attempt_number": attempt.attempt_number,
            "counted_by": attempt.counted_by,
            "counted_by_name": users_map.get(attempt.counted_by, "غير معروف"),
            "authorized_by": attempt.authorized_by,
            "authorized_by_name": users_map.get(attempt.authorized_by) if attempt.authorized_by else None,
            "recount_of_attempt_id": attempt.recount_of_attempt_id,
            "recount_reason": attempt.recount_reason,
            "requires_independent_recount": attempt.requires_independent_recount,
            "submitted_at": _iso_utc(attempt.submitted_at),
        } for attempt in attempts],
        "lines": [{
            "attempt_line_id": attempt_line.id,
            "stocktake_line_id": stocktake_line.id,
            "product_variant_id": stocktake_line.product_variant_id,
            "batch_id": stocktake_line.batch_id,
            "stock_status": stocktake_line.stock_status,
            "line_origin": stocktake_line.line_origin,
            "product_name": product_name,
            "base_uom_id": base_uom_id,
            "base_uom_code": base_uom_code,
            "base_uom_name": base_uom_name,
            "quantity_scale": quantity_scale,
            "quantity_step": canonical_quantity(quantity_step),
            "batch_number": batch_number,
            "expiry_date": expiry_date.isoformat(),
            "expected_quantity": canonical_quantity(attempt_line.expected_quantity),
            "actual_quantity": canonical_quantity(attempt_line.actual_quantity),
            "variance_quantity": canonical_quantity(attempt_line.variance_quantity),
            "notes": attempt_line.notes,
        } for (
            attempt_line, stocktake_line, product_name, base_uom_id,
            quantity_scale, quantity_step, base_uom_code, base_uom_name,
            batch_number, expiry_date,
        ) in rows],
    }


# ====================================================
# 11.27 اعتماد الجرد وترحيل الفروقات عبر محرك المخزون الموحد
# ====================================================
@router.post("/warehouse/unified/stocktake/{session_id}/approve", status_code=200)
async def approve_stocktake_session(
    session_id: int,
    payload: StocktakeApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    """Optimistic approval ثم posting حصراً عبر post_approved_stocktake_adjustments."""
    access = InventoryAccess(db, current_admin)
    await require_stocktake(access, 'stocktake.approve', session_id)

    company_id = current_admin.company_id

    password_ok = await asyncio.to_thread(
        bcrypt.checkpw,
        payload.password.encode('utf-8'),
        current_admin.password_hash.encode('utf-8'),
    )
    if not password_ok:
        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Stocktake_{session_id}",
            action_type="STOCKTAKE_APPROVAL_REJECTED",
            old_value="PENDING_REVIEW",
            new_value="Wrong password",
        ))
        await db.commit()
        raise HTTPException(status_code=403, detail="كلمة المرور غير صحيحة؛ تم رفض الاعتماد وتوثيق المحاولة.")

    try:
        location_id = await _probe_stocktake_location_id(db, company_id, session_id)
        await acquire_inventory_location_guard(db, company_id, location_id, exclusive=True)

        session = await _load_stocktake_session(db, company_id, session_id, for_update=True)
        if session.status != 'PENDING_REVIEW':
            raise HTTPException(status_code=409, detail=f"لا يمكن اعتماد جلسة بحالة ({session.status}).")

        latest_attempt = await _latest_stocktake_attempt(db, company_id, session.id)
        if latest_attempt is None:
            raise HTTPException(status_code=409, detail="لا توجد محاولة عد مثبتة لاعتمادها.")
        if latest_attempt.id != payload.count_attempt_id:
            raise HTTPException(
                status_code=409,
                detail="محاولة العد التي راجعتها لم تعد الأحدث؛ أعد فتح شاشة المراجعة.",
            )

        approved_at = _utc_naive_now()
        session.status = 'APPROVED'
        session.approved_by = current_admin.id
        session.approved_at = approved_at
        session.updated_at = approved_at
        if payload.notes:
            session.notes = f"{session.notes or ''} | Approval: {payload.notes}".strip(" |")
        await db.flush()

        movements = await post_approved_stocktake_adjustments(
            db,
            company_id=company_id,
            stocktake_session_id=session.id,
            stocktake_count_attempt_id=latest_attempt.id,
            performed_by=current_admin.id,
        )

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Stocktake_{session.id}",
            action_type="STOCKTAKE_APPROVED_AND_POSTED",
            old_value=json.dumps({
                "status": "PENDING_REVIEW",
                "attempt_id": latest_attempt.id,
                "attempt_number": latest_attempt.attempt_number,
            }, ensure_ascii=False),
            new_value=json.dumps({
                "status": "POSTED",
                "approved_by": current_admin.id,
                "movement_count": len(movements),
            }, ensure_ascii=False),
        ))
        await db.commit()

        return {
            "message": "تم اعتماد الجرد وترحيل الفروقات وفك الأقفال بنجاح.",
            "attempt_id": latest_attempt.id,
            "attempt_number": latest_attempt.attempt_number,
            "movement_count": len(movements),
            "status": "POSTED",
        }

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except IntegrityError as e:
        await db.rollback()
        logger.warning(f"تعارض متزامن أثناء اعتماد الجرد: {e}", exc_info=True)
        raise HTTPException(status_code=409, detail="حدث تعارض متزامن أثناء الاعتماد؛ لم تُحفظ حالة جزئية.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في اعتماد الجرد: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء اعتماد الجرد.")


# ====================================================
# 11.28 تفويض إعادة العد مع حفظ المحاولة السابقة
# ====================================================
@router.post("/warehouse/unified/stocktake/{session_id}/recount", status_code=200)
async def recount_stocktake_session(
    session_id: int,
    payload: StocktakeRecountRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    """تفويض Recount مرتبط بمحاولة العد التي شاهدها المشرف."""
    access = InventoryAccess(db, current_admin)
    await require_stocktake(access, 'stocktake.recount', session_id)

    company_id = current_admin.company_id

    try:
        session = await _load_stocktake_session(db, company_id, session_id, for_update=True)
        if session.status != 'PENDING_REVIEW':
            raise HTTPException(status_code=409, detail="لا يمكن طلب إعادة العد إلا لجلسة بانتظار المراجعة.")

        latest_attempt = await _latest_stocktake_attempt(db, company_id, session.id)
        if latest_attempt is None:
            raise HTTPException(status_code=409, detail="لا توجد محاولة عد مثبتة لإعادة عدها.")
        if latest_attempt.id != payload.count_attempt_id:
            raise HTTPException(status_code=409, detail="محاولة العد التي راجعتها لم تعد الأحدث؛ أعد فتح المراجعة.")

        authorizer = await _verify_stocktake_admin_credentials(
            db,
            company_id,
            payload.authorizer_username,
            payload.authorizer_password,
            session.location_id,
        )
        if authorizer is None:
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"Stocktake_{session.id}",
                action_type="STOCKTAKE_RECOUNT_AUTH_REJECTED",
                old_value=f"attempt={latest_attempt.id}",
                new_value="Invalid authorizer credentials",
            ))
            await db.commit()
            raise HTTPException(status_code=403, detail="بيانات المستخدم المخول غير صحيحة؛ تم رفض العملية وتوثيقها.")

        if latest_attempt.requires_independent_recount and authorizer.id == latest_attempt.counted_by:
            raise HTTPException(
                status_code=409,
                detail="العجز المادي يتطلب تفويض مستخدم مخول آخر غير منفذ العد الحالي.",
            )

        session.status = 'RECOUNT_REQUIRED'
        session.pending_recount_authorized_by = authorizer.id
        session.pending_recount_reason = payload.reason
        session.pending_independent_recount_required = latest_attempt.requires_independent_recount
        session.updated_at = _utc_naive_now()

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Stocktake_{session.id}",
            action_type="STOCKTAKE_RECOUNT_AUTHORIZED",
            old_value=json.dumps({
                "status": "PENDING_REVIEW",
                "attempt_id": latest_attempt.id,
                "attempt_number": latest_attempt.attempt_number,
                "counted_by": latest_attempt.counted_by,
                "requires_independent_recount": latest_attempt.requires_independent_recount,
            }, ensure_ascii=False),
            new_value=json.dumps({
                "status": "RECOUNT_REQUIRED",
                "authorized_by": authorizer.id,
                "reason": payload.reason,
                "independent_required": latest_attempt.requires_independent_recount,
            }, ensure_ascii=False),
        ))
        await db.commit()

        return {
            "message": "تم تفويض إعادة العد مع حفظ المحاولة السابقة كاملة.",
            "previous_attempt_id": latest_attempt.id,
            "previous_attempt_number": latest_attempt.attempt_number,
            "requires_independent_counter": latest_attempt.requires_independent_recount,
            "status": "RECOUNT_REQUIRED",
        }

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.warning(f"تعارض متزامن أثناء تفويض Recount: {e}", exc_info=True)
        raise HTTPException(status_code=409, detail="حدث تعارض متزامن أثناء تفويض إعادة العد.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في تفويض إعادة العد: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تفويض إعادة العد.")


# ====================================================
# 11.29 إلغاء جلسة الجرد وتحرير الأقفال مع حفظ سجل التدقيق
# ====================================================
@router.post("/warehouse/unified/stocktake/{session_id}/cancel", status_code=200)
async def cancel_stocktake_session(
    session_id: int,
    payload: StocktakeCancelRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    """إلغاء موثق مع تحرير كامل Metadata للقفل."""
    access = InventoryAccess(db, current_admin)
    await require_stocktake(access, 'stocktake.cancel', session_id)

    company_id = current_admin.company_id
    if not current_admin.is_admin:
        raise HTTPException(status_code=403, detail="إلغاء الجرد يتطلب صلاحية مشرف.")

    password_ok = await asyncio.to_thread(
        bcrypt.checkpw,
        payload.password.encode('utf-8'),
        current_admin.password_hash.encode('utf-8'),
    )
    if not password_ok:
        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Stocktake_{session_id}",
            action_type="STOCKTAKE_CANCEL_REJECTED",
            old_value="ACTIVE_STOCKTAKE",
            new_value="Wrong password",
        ))
        await db.commit()
        raise HTTPException(status_code=403, detail="كلمة المرور غير صحيحة؛ تم رفض الإلغاء وتوثيق المحاولة.")

    try:
        location_id = await _probe_stocktake_location_id(db, company_id, session_id)
        await acquire_inventory_location_guard(db, company_id, location_id, exclusive=True)

        session = await _load_stocktake_session(db, company_id, session_id, for_update=True)
        if session.status in {'POSTED', 'CANCELLED'}:
            raise HTTPException(status_code=409, detail=f"لا يمكن إلغاء جلسة بحالة ({session.status}).")

        previous_status = session.status
        now = _utc_naive_now()
        release_result = await db.execute(
            update(InventoryLock).where(
                InventoryLock.company_id == company_id,
                InventoryLock.stocktake_session_id == session.id,
                InventoryLock.released_at.is_(None),
            ).values(
                released_by=current_admin.id,
                released_at=now,
                release_reason="STOCKTAKE_CANCELLED",
            )
        )
        released_lock_count = int(release_result.rowcount or 0)

        session.status = 'CANCELLED'
        session.cancelled_by = current_admin.id
        session.cancelled_at = now
        session.cancellation_reason = payload.reason
        session.pending_recount_authorized_by = None
        session.pending_recount_reason = None
        session.pending_independent_recount_required = False
        session.updated_at = now

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Stocktake_{session.id}",
            action_type="STOCKTAKE_CANCELLED",
            old_value=previous_status,
            new_value=json.dumps({
                "status": "CANCELLED",
                "reason": payload.reason,
                "released_lock_count": released_lock_count,
            }, ensure_ascii=False),
        ))
        await db.commit()

        return {
            "message": "تم إلغاء جلسة الجرد وفك الأقفال مع حفظ سجل التدقيق.",
            "released_lock_count": released_lock_count,
            "status": "CANCELLED",
        }

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.warning(f"تعارض متزامن أثناء إلغاء الجرد: {e}", exc_info=True)
        raise HTTPException(status_code=409, detail="حدث تعارض متزامن أثناء إلغاء الجرد.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في إلغاء الجرد: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء إلغاء الجرد.")

