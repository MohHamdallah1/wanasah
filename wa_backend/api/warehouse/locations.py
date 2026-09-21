from datetime import datetime, timezone
import base64
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import Branch, Driver, InventoryLocation
from schemas import WarehouseLocationCursorPage, WarehouseSetupStatusResponse

from ._shared import _escape_like


router = APIRouter()


# ====================================================
# 0.1 إنشاء بصمة نطاق Cursor لقائمة المستودعات
# ====================================================
def _warehouse_location_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


# ====================================================
# 0.2 ترميز Cursor لقائمة المستودعات وربطه بنطاق الاستعلام
# ====================================================
def _encode_warehouse_location_cursor(
    location_id: int,
    *,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "warehouse-location",
            "scope": _warehouse_location_cursor_scope_hash(scope),
            "id": int(location_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# ====================================================
# 0.3 فك Cursor لقائمة المستودعات والتحقق من نطاقه
# ====================================================
def _decode_warehouse_location_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "warehouse-location"
            or payload.get("scope")
            != _warehouse_location_cursor_scope_hash(expected_scope)
        ):
            raise ValueError

        location_id = payload.get("id")
        if type(location_id) is not int or location_id <= 0:
            raise ValueError

        return location_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor المستودعات غير صالح أو لا يطابق نطاق البحث الحالي.",
        ) from exc


# ====================================================
# 0.4 تحويل كيان المستودع إلى عقد الاستجابة الموحد
# ====================================================
def _warehouse_location_to_payload(
    location: InventoryLocation,
    *,
    branch_name: Optional[str] = None,
) -> dict:
    def _as_iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat()

    return {
        "id": int(location.id),
        "name": str(location.name),
        "code": str(location.code),
        "branch_id": (
            int(location.branch_id)
            if location.branch_id is not None
            else None
        ),
        "branch_name": branch_name,
        "is_active": bool(location.is_active),
        "version": int(location.version),
        "created_at": _as_iso(location.created_at),
        "updated_at": _as_iso(location.updated_at),
    }


# ====================================================
# 0.5 تحميل الفرع المرتبط بالمستودع والتحقق من ملكيته وحالته
# ====================================================
async def _get_warehouse_branch(
    db: AsyncSession,
    *,
    company_id: int,
    branch_id: Optional[int],
    require_active: bool,
):
    if branch_id is None:
        return None

    row = (
        await db.execute(
            select(
                Branch.id,
                Branch.name,
                Branch.is_active,
            ).filter(
                Branch.company_id == company_id,
                Branch.id == branch_id,
            )
        )
    ).one_or_none()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="الفرع المحدد غير موجود أو لا يتبع شركتك.",
        )

    if require_active and not bool(row.is_active):
        raise HTTPException(
            status_code=409,
            detail="لا يمكن ربط المستودع بفرع غير فعال.",
        )

    return row


# ====================================================
# 0.6 تحميل المستودع بقفل صف للتعديلات المتزامنة
# ====================================================
async def _load_locked_warehouse_location(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
) -> InventoryLocation:
    location = (
        await db.execute(
            select(InventoryLocation).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
                InventoryLocation.location_type == 'WAREHOUSE',
            ).with_for_update()
        )
    ).scalar_one_or_none()

    if location is None:
        raise HTTPException(
            status_code=404,
            detail="المستودع غير موجود أو لا يتبع شركتك.",
        )
    return location


# ====================================================
# 0.7 جلب حالة جاهزية إعداد المستودعات
# ====================================================
@router.get(
    "/warehouse/setup-status",
    response_model=WarehouseSetupStatusResponse,
    status_code=200,
)
async def get_warehouse_setup_status(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('location.read', any_location=True)
    company_id = current_admin.company_id

    active_scope = (
        InventoryLocation.company_id == company_id,
        InventoryLocation.location_type == 'WAREHOUSE',
        InventoryLocation.is_active.is_(True),
    )
    active_count = int((await db.execute(
        select(func.count(InventoryLocation.id)).filter(*active_scope)
    )).scalar_one())
    accessible_count = int((await db.execute(
        select(func.count(InventoryLocation.id)).filter(
            *active_scope,
            access.location_filter('location.read'),
        )
    )).scalar_one())
    can_create = bool(await db.scalar(select(access.allows('location.create'))))
    return {
        "warehouse_ready": active_count > 0,
        "active_warehouse_count": active_count,
        "accessible_warehouse_count": accessible_count,
        "can_create": can_create,
    }


# ====================================================
# 0.8 جلب وإدارة قائمة المستودعات باستخدام Cursor
# ====================================================
@router.get(
    "/warehouse/locations",
    response_model=WarehouseLocationCursorPage,
    status_code=200,
)
@router.get(
    "/warehouse/locations/manage",
    response_model=WarehouseLocationCursorPage,
    status_code=200,
)
async def manage_warehouse_locations(
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    include_inactive: bool = Query(default=False),
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('location.read', any_location=True)

    company_id = current_admin.company_id
    clean_search = (search or "").strip().lower()

    scope = (
        f"warehouse-locations|{company_id}|"
        f"{1 if include_inactive else 0}|{clean_search}"
    )

    stmt = (
        select(
            InventoryLocation,
            Branch.name.label("branch_name"),
        )
        .outerjoin(
            Branch,
            and_(
                Branch.company_id == InventoryLocation.company_id,
                Branch.id == InventoryLocation.branch_id,
            ),
        )
        .filter(
            InventoryLocation.company_id == company_id,
            access.location_filter('location.read'),
            InventoryLocation.location_type == 'WAREHOUSE',
        )
    )

    if not include_inactive:
        stmt = stmt.filter(InventoryLocation.is_active.is_(True))

    if clean_search:
        pattern = f"%{_escape_like(clean_search)}%"
        stmt = stmt.filter(
            or_(
                func.lower(InventoryLocation.name).like(pattern, escape="\\"),
                func.lower(InventoryLocation.code).like(pattern, escape="\\"),
            )
        )

    total = None
    if cursor is None:
        count_stmt = select(func.count()).select_from(
            stmt.with_only_columns(
                InventoryLocation.id,
                maintain_column_froms=True,
            ).order_by(None).subquery()
        )
        total = int((await db.execute(count_stmt)).scalar_one())

    if cursor is not None:
        cursor_id = _decode_warehouse_location_cursor(
            cursor,
            expected_scope=scope,
        )
        stmt = stmt.filter(InventoryLocation.id > cursor_id)

    rows = (
        await db.execute(
            stmt.order_by(InventoryLocation.id.asc()).limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        _warehouse_location_to_payload(
            location,
            branch_name=branch_name,
        )
        for location, branch_name in rows
    ]

    next_cursor = None
    if has_more and rows:
        next_cursor = _encode_warehouse_location_cursor(
            int(rows[-1][0].id),
            scope=scope,
        )

    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


