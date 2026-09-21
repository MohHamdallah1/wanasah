import asyncio
import base64
import bcrypt
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from inventory_access import InventoryAccess
from models import Driver, InventoryLock, StocktakeSession, SystemSetting


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

