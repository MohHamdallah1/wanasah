from datetime import datetime, timezone
import base64
import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import (
    Branch,
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    InventoryTransferHeader,
    StocktakeSession,
    SystemAuditLog,
    TenantOperationalPolicy,
)
from schemas import (
    WarehouseLocationCreateRequest,
    WarehouseLocationCursorPage,
    WarehouseLocationMutationResponse,
    WarehouseLocationStateRequest,
    WarehouseLocationUpdateRequest,
    WarehouseSetupStatusResponse,
)

from services import (
    TRANSFER_DESTINATION_POLICY_CODE,
    InventoryMutationError,
    acquire_inventory_location_guard,
    begin_idempotent_operation,
    complete_idempotent_operation,
    inventory_business_error,
)
from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    rebuild_live_stock_warehouse,
    remove_live_stock_warehouse_projection,
)

# Staging-only dependency: remains sourced from the untouched monolith until
# _stable_request_hash is moved once to _shared.py in its dedicated stage.
from api.warehouse import _stable_request_hash

from ._shared import _escape_like


logger = logging.getLogger("wanasah_logger")
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


# ====================================================
# 0.9 إنشاء مستودع جديد مع idempotency والتدقيق وتحديث Live Stock
# ====================================================
@router.post(
    "/warehouse/locations",
    response_model=WarehouseLocationMutationResponse,
    status_code=201,
)
async def create_warehouse_location(
    payload: WarehouseLocationCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('location.create')

    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_LOCATION_CREATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        if payload.code == "TRANSIT-SYS":
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "SYSTEM_LOCATION_CODE_RESERVED",
                    "الكود TRANSIT-SYS محجوز لموقع العبور الداخلي للنظام.",
                ),
            )

        branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=payload.branch_id,
            require_active=True,
        )

        duplicate_id = (
            await db.execute(
                select(InventoryLocation.id).filter(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.code == payload.code,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if duplicate_id is not None:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "LOCATION_CODE_CONFLICT",
                    "كود الموقع مستخدم مسبقاً داخل شركتك.",
                ),
            )

        location = InventoryLocation(
            company_id=company_id,
            branch_id=payload.branch_id,
            name=payload.name,
            code=payload.code,
            location_type='WAREHOUSE',
            vehicle_id=None,
            system_role=None,
            is_system_managed=False,
            version=1,
            is_active=True,
        )
        db.add(location)
        await db.flush()

        await rebuild_live_stock_warehouse(
            db,
            company_id=company_id,
            warehouse_location_id=int(location.id),
        )

        branch_name = str(branch_row.name) if branch_row is not None else None
        location_payload = _warehouse_location_to_payload(
            location,
            branch_name=branch_name,
        )

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"InventoryLocation_{location.id}",
            action_type="WAREHOUSE_LOCATION_CREATED",
            old_value=None,
            new_value=json.dumps(location_payload, sort_keys=True, ensure_ascii=False),
        ))

        response_payload = {
            "message": "تم إنشاء المستودع بنجاح.",
            "location": location_payload,
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except LiveStockProjectionError as exc:
        await db.rollback()
        logger.error(
            "Live Stock projection lifecycle update failed: %s",
            str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="تعذر تحديث حالة المخزون الحي بأمان.",
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="تعذر إنشاء المستودع بسبب تعارض متزامن أو كود مكرر.",
        )
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في إنشاء المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء إنشاء المستودع.")


# ====================================================
# 0.10 تحديث بيانات المستودع مع قفل الصف والتحقق من الإصدار
# ====================================================
@router.patch(
    "/warehouse/locations/{location_id}",
    response_model=WarehouseLocationMutationResponse,
    status_code=200,
)
async def update_warehouse_location(
    location_id: int,
    payload: WarehouseLocationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('location.update', location_id)

    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload, context={"location_id": int(location_id)})
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_LOCATION_UPDATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        location = await _load_locked_warehouse_location(
            db,
            company_id=company_id,
            location_id=location_id,
        )
        if location.is_system_managed:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "SYSTEM_LOCATION_PROTECTED",
                    "لا يمكن تعديل موقع يديره النظام.",
                ),
            )
        if int(location.version) != int(payload.expected_version):
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "LOCATION_VERSION_CONFLICT",
                    "تغير المستودع منذ فتحه. حدّث البيانات ثم أعد المحاولة.",
                    context={"current_version": int(location.version)},
                ),
            )

        current_branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=location.branch_id,
            require_active=False,
        )
        old_payload = _warehouse_location_to_payload(
            location,
            branch_name=(str(current_branch_row.name) if current_branch_row is not None else None),
        )

        branch_row = current_branch_row
        if "branch_id" in payload.model_fields_set:
            branch_row = await _get_warehouse_branch(
                db,
                company_id=company_id,
                branch_id=payload.branch_id,
                require_active=True,
            )
            location.branch_id = payload.branch_id

        if "name" in payload.model_fields_set:
            location.name = payload.name

        if "code" in payload.model_fields_set:
            if payload.code == "TRANSIT-SYS":
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "SYSTEM_LOCATION_CODE_RESERVED",
                        "الكود TRANSIT-SYS محجوز لموقع العبور الداخلي للنظام.",
                    ),
                )
            duplicate_id = (
                await db.execute(
                    select(InventoryLocation.id).filter(
                        InventoryLocation.company_id == company_id,
                        InventoryLocation.code == payload.code,
                        InventoryLocation.id != location.id,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if duplicate_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "LOCATION_CODE_CONFLICT",
                        "كود الموقع مستخدم مسبقاً داخل شركتك.",
                    ),
                )
            location.code = payload.code

        location.version = int(location.version) + 1
        location.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.flush()

        new_payload = _warehouse_location_to_payload(
            location,
            branch_name=(str(branch_row.name) if branch_row is not None else None),
        )

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"InventoryLocation_{location.id}",
            action_type="WAREHOUSE_LOCATION_UPDATED",
            old_value=json.dumps(old_payload, sort_keys=True, ensure_ascii=False),
            new_value=json.dumps(new_payload, sort_keys=True, ensure_ascii=False),
        ))

        response_payload = {
            "message": "تم تحديث المستودع بنجاح.",
            "location": new_payload,
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="تعذر تحديث المستودع بسبب تعارض متزامن أو كود مكرر.")
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تحديث المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تحديث المستودع.")


# ====================================================
# 0.11 تفعيل المستودع مع حارس المخزون وإعادة بناء Live Stock
# ====================================================
@router.post(
    "/warehouse/locations/{location_id}/activate",
    response_model=WarehouseLocationMutationResponse,
    status_code=200,
)
async def activate_warehouse_location(
    location_id: int,
    payload: WarehouseLocationStateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('location.state', location_id)

    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload, context={"location_id": int(location_id)})
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_LOCATION_ACTIVATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        await acquire_inventory_location_guard(db, company_id, location_id, exclusive=True)
        location = await _load_locked_warehouse_location(
            db,
            company_id=company_id,
            location_id=location_id,
        )
        if location.is_system_managed:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "SYSTEM_LOCATION_PROTECTED",
                    "لا يمكن تغيير حالة موقع يديره النظام.",
                ),
            )
        if int(location.version) != int(payload.expected_version):
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "LOCATION_VERSION_CONFLICT",
                    "تغير المستودع منذ فتحه. حدّث البيانات ثم أعد المحاولة.",
                    context={"current_version": int(location.version)},
                ),
            )

        branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=location.branch_id,
            require_active=True,
        )

        activated_now = not bool(location.is_active)
        if activated_now:
            location.is_active = True
            location.version = int(location.version) + 1
            location.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"InventoryLocation_{location.id}",
                action_type="WAREHOUSE_LOCATION_ACTIVATED",
                old_value="inactive",
                new_value=payload.reason or "active",
            ))

        await db.flush()
        if activated_now:
            await rebuild_live_stock_warehouse(
                db,
                company_id=company_id,
                warehouse_location_id=int(location.id),
            )

        location_payload = _warehouse_location_to_payload(
            location,
            branch_name=(str(branch_row.name) if branch_row is not None else None),
        )
        response_payload = {
            "message": "تم تفعيل المستودع بنجاح.",
            "location": location_payload,
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except LiveStockProjectionError as exc:
        await db.rollback()
        logger.error(
            "Live Stock projection lifecycle update failed: %s",
            str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="تعذر تحديث حالة المخزون الحي بأمان.",
        )
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تفعيل المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تفعيل المستودع.")


# ====================================================
# 0.12 تعطيل المستودع بعد التحقق من جميع الموانع التشغيلية
# ====================================================
@router.post(
    "/warehouse/locations/{location_id}/deactivate",
    response_model=WarehouseLocationMutationResponse,
    status_code=200,
)
async def deactivate_warehouse_location(
    location_id: int,
    payload: WarehouseLocationStateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('location.state', location_id)

    company_id = current_admin.company_id
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="سبب تعطيل المستودع مطلوب للتدقيق.")

    try:
        request_hash = _stable_request_hash(payload, context={"location_id": int(location_id)})
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_LOCATION_DEACTIVATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        # Serializes deactivation against all inventory mutations using this location.
        await acquire_inventory_location_guard(db, company_id, location_id, exclusive=True)
        location = await _load_locked_warehouse_location(
            db,
            company_id=company_id,
            location_id=location_id,
        )
        if location.is_system_managed:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "SYSTEM_LOCATION_PROTECTED",
                    "لا يمكن تغيير حالة موقع يديره النظام.",
                ),
            )
        if int(location.version) != int(payload.expected_version):
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "LOCATION_VERSION_CONFLICT",
                    "تغير المستودع منذ فتحه. حدّث البيانات ثم أعد المحاولة.",
                    context={"current_version": int(location.version)},
                ),
            )

        branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=location.branch_id,
            require_active=False,
        )

        deactivated_now = bool(location.is_active)
        if deactivated_now:
            stock_row = (
                await db.execute(
                    select(
                        func.coalesce(func.sum(InventoryBalance.on_hand_quantity), 0),
                        func.coalesce(func.sum(InventoryBalance.reserved_quantity), 0),
                    ).filter(
                        InventoryBalance.company_id == company_id,
                        InventoryBalance.location_id == location.id,
                    )
                )
            ).one()
            on_hand_total = int(stock_row[0] or 0)
            reserved_total = int(stock_row[1] or 0)
            if on_hand_total > 0 or reserved_total > 0:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "LOCATION_DEACTIVATION_BLOCKED",
                        "لا يمكن تعطيل المستودع لأنه يحتوي رصيداً مخزنياً.",
                        context={
                            "blocker_type": "INVENTORY_BALANCE",
                            "on_hand_quantity": on_hand_total,
                            "reserved_quantity": reserved_total,
                        },
                    ),
                )

            transfer_ref = (
                await db.execute(
                    select(InventoryTransferHeader.reference_number).filter(
                        InventoryTransferHeader.company_id == company_id,
                        InventoryTransferHeader.status.not_in(
                            ['POSTED', 'REJECTED', 'CANCELLED']
                        ),
                        or_(
                            InventoryTransferHeader.source_location_id == location.id,
                            InventoryTransferHeader.destination_location_id == location.id,
                        ),
                    ).order_by(InventoryTransferHeader.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if transfer_ref is not None:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "LOCATION_DEACTIVATION_BLOCKED",
                        "لا يمكن تعطيل المستودع لوجود حوالة غير نهائية مرتبطة به.",
                        context={"blocker_type": "OPEN_TRANSFER", "reference_number": str(transfer_ref)},
                    ),
                )

            active_lock_id = (
                await db.execute(
                    select(InventoryLock.id).filter(
                        InventoryLock.company_id == company_id,
                        InventoryLock.location_id == location.id,
                        InventoryLock.released_at.is_(None),
                    ).order_by(InventoryLock.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if active_lock_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "LOCATION_DEACTIVATION_BLOCKED",
                        "لا يمكن تعطيل المستودع أثناء وجود قفل مخزني نشط عليه.",
                        context={"blocker_type": "INVENTORY_LOCK", "reference_id": int(active_lock_id)},
                    ),
                )

            active_stocktake = (
                await db.execute(
                    select(StocktakeSession.reference_number).filter(
                        StocktakeSession.company_id == company_id,
                        StocktakeSession.location_id == location.id,
                        StocktakeSession.status.in_(
                            ['DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED']
                        ),
                    ).order_by(StocktakeSession.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if active_stocktake is not None:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "LOCATION_DEACTIVATION_BLOCKED",
                        "لا يمكن تعطيل المستودع أثناء وجود جلسة جرد غير نهائية عليه.",
                        context={"blocker_type": "OPEN_STOCKTAKE", "reference_number": str(active_stocktake)},
                    ),
                )


            published_policy_ref = (
                await db.execute(
                    select(
                        TenantOperationalPolicy.id,
                        TenantOperationalPolicy.revision,
                    ).filter(
                        TenantOperationalPolicy.company_id == company_id,
                        TenantOperationalPolicy.policy_code
                        == TRANSFER_DESTINATION_POLICY_CODE,
                        TenantOperationalPolicy.status == "PUBLISHED",
                        TenantOperationalPolicy.effective_to.is_(None),
                        or_(
                            TenantOperationalPolicy.validated_payload[
                                "quarantine_location_id"
                            ].as_integer() == location.id,
                            TenantOperationalPolicy.validated_payload[
                                "disposal_location_id"
                            ].as_integer() == location.id,
                            TenantOperationalPolicy.validated_payload[
                                "vendor_return_staging_location_id"
                            ].as_integer() == location.id,
                        ),
                    ).limit(1)
                )
            ).first()
            if published_policy_ref is not None:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "LOCATION_DEACTIVATION_BLOCKED",
                        "لا يمكن تعطيل الموقع لأنه مرجع في سياسة تحويل منشورة.",
                        context={
                            "blocker_type": "PUBLISHED_OPERATIONAL_POLICY",
                            "policy_id": int(published_policy_ref.id),
                            "policy_revision": int(
                                published_policy_ref.revision
                            ),
                        },
                    ),
                )

            active_route_id = (
                await db.execute(
                    select(DispatchRoute.id).filter(
                        DispatchRoute.company_id == company_id,
                        DispatchRoute.source_location_id == location.id,
                        DispatchRoute.status.in_(['active', 'waiting', 'postponed']),
                    ).order_by(DispatchRoute.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if active_route_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "LOCATION_DEACTIVATION_BLOCKED",
                        "لا يمكن تعطيل المستودع لأنه مصدر لخط سير غير نهائي.",
                        context={"blocker_type": "OPEN_DISPATCH_ROUTE", "reference_id": int(active_route_id)},
                    ),
                )

            location.is_active = False
            location.version = int(location.version) + 1
            location.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"InventoryLocation_{location.id}",
                action_type="WAREHOUSE_LOCATION_DEACTIVATED",
                old_value="active",
                new_value=reason,
            ))

        await db.flush()
        if deactivated_now:
            await remove_live_stock_warehouse_projection(
                db,
                company_id=company_id,
                warehouse_location_id=int(location.id),
            )

        location_payload = _warehouse_location_to_payload(
            location,
            branch_name=(str(branch_row.name) if branch_row is not None else None),
        )
        response_payload = {
            "message": "تم تعطيل المستودع بنجاح.",
            "location": location_payload,
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except LiveStockProjectionError as exc:
        await db.rollback()
        logger.error(
            "Live Stock projection lifecycle update failed: %s",
            str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="تعذر تحديث حالة المخزون الحي بأمان.",
        )
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تعطيل المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تعطيل المستودع.")


