from datetime import timezone, date, datetime
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, update, tuple_, case
from typing import Optional, List
from database import get_db
from api.dependencies import get_current_admin
from sqlalchemy.exc import IntegrityError
import bcrypt 
import logging
logger = logging.getLogger("wanasah_logger")
import uuid
import hashlib
import json
import base64
from services import (
    check_inventory_lock as _check_inventory_lock,
    acquire_inventory_location_guard,
    apply_inventory_movement,
    apply_inventory_movements_batch,
    post_approved_stocktake_adjustments,
    allocate_fefo_inventory_batch,
    get_company_local_date,
    validate_vehicle_recon_work_session,
    begin_idempotent_operation,
    complete_idempotent_operation,
    InventoryMutationError,
)
from models import (Driver, Product, ProductVariant, Branch,
DispatchRoute, SystemAuditLog,
InventoryLocation, InventoryStockPolicy, InventoryBalance, InventoryMovement, InventoryMovementImpact, ProductBatch,
InventoryTransferHeader, InventoryTransferLine, OverrideReason, SystemSetting,
StocktakeSession, StocktakeLine, StocktakeCountAttempt, StocktakeCountAttemptLine, InventoryLock)

from schemas import (UnifiedStocktakeStartRequest,
WarehouseInventoryItem, WarehouseInventoryCursorPage, WarehouseLedgerItem, WarehouseLedgerCursorPage,
WarehouseStatusResponse, WarehouseLocationCreateRequest, WarehouseLocationUpdateRequest,
WarehouseLocationStateRequest, WarehouseLocationCursorPage, WarehouseLocationMutationResponse,
SimpleProductVariantItem, SimpleProductVariantCursorPage, ProductVariantResolveRequest,
AddProductVariantRequest, AdjustWarehouseEntryRequest, UpgradedInboundRequest, UnifiedDispatchRequest, UnifiedReceiveRequest,
UnifiedTransferDecisionRequest, WarehouseTransferCursorPage, WarehouseTransferDetail,
UnifiedTransferLocationItem, UnifiedTransferSourceInventoryCursorPage,
UnifiedTransferOverrideOptionsResponse,
StocktakeActiveSessionCursorPage,
StocktakeCycleBatchCursorPage,
UnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest )

router = APIRouter()


# إنشاء بصمة ثابتة للطلب مع اعتبار ترتيب items غير مؤثر منطقياً.
def _stable_request_hash(
    payload,
    *,
    context: Optional[dict] = None,
) -> str:
    body = payload.model_dump(mode="json", exclude={"request_id"})

    items = body.get("items")
    if isinstance(items, list):
        body["items"] = sorted(
            items,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )

    if context:
        body["_context"] = dict(context)

    canonical = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ledger_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _encode_ledger_cursor(
    created_at: datetime,
    movement_id: int,
    *,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 2,
            "kind": "warehouse-ledger",
            "scope": _ledger_cursor_scope_hash(scope),
            "created_at": created_at.isoformat(),
            "id": int(movement_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_ledger_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> tuple[datetime, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 2
            or payload.get("kind") != "warehouse-ledger"
            or payload.get("scope")
            != _ledger_cursor_scope_hash(expected_scope)
        ):
            raise ValueError

        movement_id = payload.get("id")
        if type(movement_id) is not int or movement_id <= 0:
            raise ValueError

        created_at = datetime.fromisoformat(str(payload.get("created_at")))
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)

        return created_at, movement_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor سجل الحركات غير صالح أو لا يطابق نطاق البحث الحالي.",
        ) from exc


def _escape_like(value: str) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )

def _warehouse_location_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


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


def _transfer_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _encode_transfer_cursor(
    created_at: datetime,
    transfer_id: int,
    *,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "warehouse-transfer",
            "scope": _transfer_cursor_scope_hash(scope),
            "created_at": created_at.isoformat(),
            "id": int(transfer_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_transfer_cursor(
    cursor: str,
    *,
    expected_scope: str,
) -> tuple[datetime, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "warehouse-transfer"
            or payload.get("scope")
            != _transfer_cursor_scope_hash(expected_scope)
        ):
            raise ValueError

        transfer_id = payload.get("id")
        if type(transfer_id) is not int or transfer_id <= 0:
            raise ValueError

        created_at = datetime.fromisoformat(str(payload.get("created_at")))
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)

        return created_at, transfer_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor الحوالات غير صالح أو لا يطابق نطاق البحث الحالي.",
        ) from exc


def _variant_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _encode_variant_cursor(
    *,
    kind: str,
    variant_name: str,
    variant_id: int,
    scope: str,
) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": kind,
            "scope": _variant_cursor_scope_hash(scope),
            "name": variant_name,
            "id": int(variant_id),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_variant_cursor(
    cursor: str,
    *,
    expected_kind: str,
    expected_scope: str,
) -> tuple[str, int]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))

        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != expected_kind
            or payload.get("scope")
            != _variant_cursor_scope_hash(expected_scope)
        ):
            raise ValueError

        variant_name = payload.get("name")
        variant_id = payload.get("id")

        if (
            not isinstance(variant_name, str)
            or not variant_name
            or len(variant_name) > 200
            or type(variant_id) is not int
            or variant_id <= 0
        ):
            raise ValueError

        return variant_name, variant_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor الصفحة غير صالح أو لا يطابق معايير الاستعلام الحالي.",
        ) from exc





def _stocktake_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


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
async def _verify_stocktake_admin_credentials(
    db: AsyncSession,
    company_id: int,
    username: str,
    password: str
) -> Optional[Driver]:
    stmt = select(Driver).filter_by(
        company_id=company_id,
        username=username.strip(),
        is_active=True,
        is_admin=True
    )
    admin = (await db.execute(stmt)).scalar_one_or_none()

    if not admin:
        return None

    password_ok = await asyncio.to_thread(
        bcrypt.checkpw,
        password.encode('utf-8'),
        admin.password_hash.encode('utf-8')
    )
    return admin if password_ok else None


# تحديد ما إذا كان العجز يتطلب إعادة عد مستقلة؛ الوضع الافتراضي الآمن يعتبر أي عجز مادياً حتى تضبط الشركة حدودها.
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
# =================================================================================
@router.get("/warehouse/locations", status_code=200)
async def get_warehouse_locations(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """جلب المستودعات الفعالة مع Auto-Provision آمن للشركات الجديدة فقط."""
    company_id = current_admin.company_id

    stmt_active = select(
        InventoryLocation.id,
        InventoryLocation.name,
        InventoryLocation.code
    ).filter_by(
        company_id=company_id,
        location_type='WAREHOUSE',
        is_active=True
    ).order_by(
        InventoryLocation.id.asc()
    )

    locations = (await db.execute(stmt_active)).all()
    if locations:
        return [
            {"id": loc.id, "name": loc.name, "code": loc.code}
            for loc in locations
        ]

    # لا نعيد تفعيل مستودع متوقف بصمت. Auto-Provision مخصص فقط لشركة
    # لا تملك أي WAREHOUSE أصلاً.
    stmt_any = select(InventoryLocation.id).filter_by(
        company_id=company_id,
        location_type='WAREHOUSE'
    ).limit(1)
    if (await db.execute(stmt_any)).scalar_one_or_none() is not None:
        return []

    try:
        # ON CONFLICT يحمي أول دخول متزامن لشركة جديدة بدون IntegrityError/500.
        stmt_insert = pg_insert(InventoryLocation).values(
            company_id=company_id,
            name="المستودع الرئيسي",
            code="WH-MAIN",
            location_type='WAREHOUSE',
            is_active=True
        ).on_conflict_do_nothing(
            index_elements=['company_id', 'code']
        )
        await db.execute(stmt_insert)

        locations = (await db.execute(stmt_active)).all()
        await db.commit()

        return [
            {"id": loc.id, "name": loc.name, "code": loc.code}
            for loc in locations
        ]

    except Exception as e:
        await db.rollback()
        logger.error(
            f"خطأ في Auto-Provision للمستودع: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ داخلي أثناء تجهيز مستودعات الشركة."
        )


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
        "created_at": _as_iso(location.created_at),
        "updated_at": _as_iso(location.updated_at),
    }


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


@router.get(
    "/warehouse/locations/manage",
    response_model=WarehouseLocationCursorPage,
    status_code=200,
)
async def manage_warehouse_locations(
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    include_inactive: bool = Query(default=True),
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
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


@router.post(
    "/warehouse/locations",
    response_model=WarehouseLocationMutationResponse,
    status_code=201,
)
async def create_warehouse_location(
    payload: WarehouseLocationCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
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
                detail="الكود TRANSIT-SYS محجوز لموقع العبور الداخلي للنظام.",
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
                detail="كود الموقع مستخدم مسبقاً داخل شركتك.",
            )

        location = InventoryLocation(
            company_id=company_id,
            branch_id=payload.branch_id,
            name=payload.name,
            code=payload.code,
            location_type='WAREHOUSE',
            vehicle_id=None,
            is_active=True,
        )
        db.add(location)
        await db.flush()

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


@router.patch(
    "/warehouse/locations/{location_id}",
    response_model=WarehouseLocationMutationResponse,
    status_code=200,
)
async def update_warehouse_location(
    location_id: int,
    payload: WarehouseLocationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
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
                    detail="الكود TRANSIT-SYS محجوز لموقع العبور الداخلي للنظام.",
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
                raise HTTPException(status_code=409, detail="كود الموقع مستخدم مسبقاً داخل شركتك.")
            location.code = payload.code

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


@router.post(
    "/warehouse/locations/{location_id}/activate",
    response_model=WarehouseLocationMutationResponse,
    status_code=200,
)
async def activate_warehouse_location(
    location_id: int,
    payload: WarehouseLocationStateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
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

        branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=location.branch_id,
            require_active=True,
        )

        if not location.is_active:
            location.is_active = True
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
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تفعيل المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تفعيل المستودع.")


@router.post(
    "/warehouse/locations/{location_id}/deactivate",
    response_model=WarehouseLocationMutationResponse,
    status_code=200,
)
async def deactivate_warehouse_location(
    location_id: int,
    payload: WarehouseLocationStateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
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

        branch_row = await _get_warehouse_branch(
            db,
            company_id=company_id,
            branch_id=location.branch_id,
            require_active=False,
        )

        if location.is_active:
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
                    detail=(
                        "لا يمكن تعطيل المستودع لأنه يحتوي مخزوناً فعلياً "
                        f"(on_hand={on_hand_total}, reserved={reserved_total})."
                    ),
                )

            transit_ref = (
                await db.execute(
                    select(InventoryTransferHeader.reference_number).filter(
                        InventoryTransferHeader.company_id == company_id,
                        InventoryTransferHeader.workflow_type == 'TRANSIT',
                        InventoryTransferHeader.status == 'IN_TRANSIT',
                        or_(
                            InventoryTransferHeader.source_location_id == location.id,
                            InventoryTransferHeader.destination_location_id == location.id,
                        ),
                    ).order_by(InventoryTransferHeader.id.asc()).limit(1)
                )
            ).scalar_one_or_none()
            if transit_ref is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"لا يمكن تعطيل المستودع لوجود حوالة IN_TRANSIT مرتبطة به ({transit_ref}).",
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
                    detail="لا يمكن تعطيل المستودع أثناء وجود جرد/قفل مخزني نشط عليه.",
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
                    detail="لا يمكن تعطيل المستودع لأنه مصدر لخط سير تشغيلي غير مغلق.",
                )

            location.is_active = False
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
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تعطيل المستودع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تعطيل المستودع.")


# =================================================================================
# 1. استلام بضاعة من المورد (Inbound) - المحرك الموحد
# =================================================================================
@router.post("/warehouse/inbound", status_code=201)
async def warehouse_inbound(
    payload: UpgradedInboundRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_INBOUND",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        if not payload.items:
            raise HTTPException(status_code=400, detail="يجب إرسال أصناف للاستلام.")

        reference_id = payload.reference_id
        if not reference_id or not reference_id.strip() or reference_id == "بدون فاتورة":
            reference_id = f"AUTO-INB-{payload.request_id.hex.upper()}"
        else:
            reference_id = reference_id.strip()
        normalized_ref = reference_id.strip().lower()

        if not reference_id.startswith("AUTO-INB-"):
            await db.execute(
                select(func.pg_advisory_xact_lock(
                    company_id,
                    func.hashtext(f"inbound-ref:{normalized_ref}")
                ))
            )
            duplicate_ref = (
                await db.execute(
                    select(InventoryMovement.id).filter(
                        InventoryMovement.company_id == company_id,
                        InventoryMovement.reference_type == 'INBOUND_SUPPLIER',
                        func.lower(func.trim(InventoryMovement.reference_id)) == normalized_ref
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if duplicate_ref is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"مرفوض: رقم الفاتورة '{reference_id}' مسجل مسبقاً."
                )

        main_loc = (
            await db.execute(
                select(InventoryLocation).filter_by(
                    id=payload.location_id,
                    company_id=company_id,
                    location_type='WAREHOUSE',
                    is_active=True
                )
            )
        ).scalar_one_or_none()
        if main_loc is None:
            raise HTTPException(
                status_code=404,
                detail="المستودع المختار غير موجود أو غير فعال أو لا ينتمي لشركتك."
            )

        requested_var_ids = {item.product_variant_id for item in payload.items}
        valid_var_ids = set(
            (
                await db.execute(
                    select(ProductVariant.id).filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(requested_var_ids),
                        ProductVariant.is_active.is_(True)
                    )
                )
            ).scalars().all()
        )
        if valid_var_ids != requested_var_ids:
            raise HTTPException(
                status_code=400,
                detail="يوجد صنف غير صالح أو غير فعال أو لا يتبع شركتك ضمن فاتورة الاستلام."
            )

        as_of_date = await get_company_local_date(db, company_id)
        requested_batches = {}
        for item in payload.items:
            if item.quantity_packs <= 0:
                continue
            if not item.batch_number or not item.expiry_date:
                raise HTTPException(
                    status_code=422,
                    detail="مرفوض: النظام الموحد يفرض إدخال رقم الدفعة وتاريخ الصلاحية."
                )
            if item.expiry_date < as_of_date:
                raise HTTPException(
                    status_code=422,
                    detail=f"مرفوض: لا يمكن استلام بضاعة منتهية الصلاحية (الدفعة: {item.batch_number})."
                )

            if item.production_date is not None and item.production_date > as_of_date:
                raise HTTPException(
                    status_code=422,
                    detail=f"مرفوض: تاريخ إنتاج الدفعة ({item.batch_number}) يقع في المستقبل."
                )

            if item.production_date is not None and item.production_date > item.expiry_date:
                raise HTTPException(
                    status_code=422,
                    detail=f"مرفوض: تاريخ إنتاج الدفعة ({item.batch_number}) بعد تاريخ صلاحيتها."
                )

            key = (int(item.product_variant_id), str(item.batch_number))
            metadata = (item.production_date, item.expiry_date)
            existing_metadata = requested_batches.get(key)
            if existing_metadata is not None and existing_metadata != metadata:
                raise HTTPException(
                    status_code=409,
                    detail=f"الدفعة ({item.batch_number}) مكررة ببيانات إنتاج/صلاحية متعارضة داخل الطلب."
                )
            requested_batches[key] = metadata

        if not requested_batches:
            raise HTTPException(status_code=400, detail="لا توجد كميات صالحة للإدخال.")

        await db.execute(
            pg_insert(ProductBatch).values([
                {
                    "company_id": company_id,
                    "product_variant_id": product_variant_id,
                    "batch_number": batch_number,
                    "production_date": requested_batches[(product_variant_id, batch_number)][0],
                    "expiry_date": requested_batches[(product_variant_id, batch_number)][1],
                    "is_active": True,
                }
                for product_variant_id, batch_number in sorted(requested_batches)
            ]).on_conflict_do_nothing(
                index_elements=['company_id', 'product_variant_id', 'batch_number']
            )
        )

        batch_rows = (
            await db.execute(
                select(ProductBatch).filter(
                    ProductBatch.company_id == company_id,
                    tuple_(ProductBatch.product_variant_id, ProductBatch.batch_number).in_(
                        sorted(requested_batches)
                    )
                )
            )
        ).scalars().all()
        batch_map = {
            (row.product_variant_id, row.batch_number): row
            for row in batch_rows
        }
        if set(batch_map) != set(requested_batches):
            raise HTTPException(status_code=409, detail="تعذر تثبيت جميع دفعات فاتورة الاستلام.")

        for key, (production_date, expiry_date) in requested_batches.items():
            batch = batch_map[key]

            if not batch.is_active:
                raise HTTPException(
                    status_code=409,
                    detail=f"الدفعة ({batch.batch_number}) متوقفة إدارياً ولا يمكن إدخال رصيد AVAILABLE عليها."
                )

            if batch.expiry_date < as_of_date:
                raise HTTPException(
                    status_code=409,
                    detail=f"الدفعة ({batch.batch_number}) منتهية الصلاحية ولا يمكن إدخال رصيد AVAILABLE عليها."
                )

            if batch.production_date is not None and batch.production_date > as_of_date:
                raise HTTPException(
                    status_code=409,
                    detail=f"الدفعة ({batch.batch_number}) تحمل تاريخ إنتاج مستقبلي وغير صالحة للإدخال."
                )

            if batch.expiry_date != expiry_date:
                raise HTTPException(
                    status_code=409,
                    detail=f"الدفعة ({batch.batch_number}) موجودة مسبقاً بتاريخ صلاحية مختلف."
                )

            if (
                batch.production_date is not None
                and production_date is not None
                and batch.production_date != production_date
            ):
                raise HTTPException(
                    status_code=409,
                    detail=f"الدفعة ({batch.batch_number}) موجودة مسبقاً بتاريخ إنتاج مختلف."
                )

        aggregated_items: dict[tuple[int, int], int] = {}
        for item in payload.items:
            if item.quantity_packs <= 0:
                continue
            batch = batch_map[(int(item.product_variant_id), str(item.batch_number))]
            key = (int(item.product_variant_id), int(batch.id))
            aggregated_items[key] = aggregated_items.get(key, 0) + int(item.quantity_packs)

        movement_specs = []
        for (product_variant_id, batch_id), added_packs in sorted(aggregated_items.items()):
            movement_raw_key = (
                f"{company_id}|{normalized_ref}|{main_loc.id}|{product_variant_id}|{batch_id}"
            )
            movement_specs.append({
                "product_variant_id": product_variant_id,
                "batch_id": batch_id,
                "quantity": added_packs,
                "movement_kind": 'PHYSICAL',
                "reference_type": 'INBOUND_SUPPLIER',
                "reference_id": reference_id,
                "idempotency_key": "INB-" + hashlib.sha256(movement_raw_key.encode("utf-8")).hexdigest(),
                "source_location_id": None,
                "destination_location_id": main_loc.id,
                "source_stock_status": None,
                "destination_stock_status": 'AVAILABLE',
                "notes": payload.notes,
            })

        await apply_inventory_movements_batch(
            db,
            company_id=company_id,
            performed_by=current_admin.id,
            movements=movement_specs,
        )

        response_payload = {
            "message": "تم إدخال البضاعة وتحديث المخزون بنجاح"
        }
        complete_idempotent_operation(
            idempotency_record,
            response_payload,
        )
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except IntegrityError as e:
        await db.rollback()
        logger.warning(f"تعارض متزامن أثناء استلام البضاعة: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail="حدث تعارض متزامن أثناء الاستلام. لم يتم حفظ أي جزء من العملية."
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في استلام البضاعة: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ داخلي في الخادم أثناء استلام البضاعة."
        )


# =================================================================================
# 2. إشعارات النواقص (Threshold Alerts - Reorder Point)
# =================================================================================
# Legacy unbounded /warehouse/alerts removed; alert metadata now comes from inventory cursor.


# =================================================================================
# 3. جلب حالة المستودع بالكامل من المحرك الموحد
# =================================================================================
@router.get(
    "/warehouse/inventory/cursor",
    response_model=WarehouseInventoryCursorPage,
    status_code=200,
)
async def get_warehouse_inventory(
    location_id: int,
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    only_alerts: bool = False,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    try:
        stmt_location = select(InventoryLocation.id).filter_by(
            id=location_id,
            company_id=company_id,
            location_type='WAREHOUSE',
            is_active=True,
        )
        if (await db.execute(stmt_location)).scalar_one_or_none() is None:
            raise HTTPException(
                status_code=404,
                detail="المستودع غير موجود أو لا يتبع شركتك.",
            )

        as_of_date = await get_company_local_date(db, company_id)

        clean_search = (search or "").strip().lower()
        if clean_search and len(clean_search) < 2:
            raise HTTPException(
                status_code=400,
                detail="البحث في المخزون يتطلب حرفين على الأقل.",
            )

        search_condition = None
        if clean_search:
            like_pattern = f"%{_escape_like(clean_search)}%"
            search_condition = or_(
                func.lower(ProductVariant.variant_name).like(
                    like_pattern,
                    escape="\\",
                ),
                func.lower(
                    func.coalesce(ProductVariant.sku, "")
                ).like(
                    like_pattern,
                    escape="\\",
                ),
            )

        # الرصيد الفيزيائي في المستودع يجعل الصنف مرئياً حتى لو تم تعطيله،
        # لأن إخفاء صنف متوقف وله بضاعة فعلية يخرق معنى الجرد الحي.
        warehouse_stock_exists = (
            select(InventoryBalance.id)
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id == ProductVariant.id,
                InventoryBalance.on_hand_quantity > 0,
            )
            .correlate(ProductVariant)
            .exists()
        )

        latest_source_for_candidate_vehicle = (
            select(DispatchRoute.source_location_id)
            .filter(
                DispatchRoute.company_id == company_id,
                DispatchRoute.vehicle_id == InventoryLocation.vehicle_id,
            )
            .order_by(DispatchRoute.id.desc())
            .limit(1)
            .correlate(InventoryLocation)
            .scalar_subquery()
        )

        vehicle_stock_exists = (
            select(InventoryBalance.id)
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id
                    == InventoryBalance.company_id,
                    InventoryLocation.id
                    == InventoryBalance.location_id,
                ),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.product_variant_id == ProductVariant.id,
                InventoryBalance.stock_status == 'AVAILABLE',
                InventoryBalance.on_hand_quantity > 0,
                InventoryLocation.company_id == company_id,
                InventoryLocation.location_type == 'VEHICLE',
                InventoryLocation.is_active.is_(True),
                InventoryLocation.vehicle_id.isnot(None),
                latest_source_for_candidate_vehicle == location_id,
            )
            .correlate(ProductVariant)
            .exists()
        )

        visible_condition = or_(
            ProductVariant.is_active.is_(True),
            warehouse_stock_exists,
            vehicle_stock_exists,
        )

        batch_is_sellable = and_(
            ProductBatch.is_active.is_(True),
            or_(
                ProductBatch.production_date.is_(None),
                ProductBatch.production_date <= as_of_date,
            ),
            ProductBatch.expiry_date >= as_of_date,
        )

        alert_inventory_subq = None
        if only_alerts or cursor is None:
            alert_inventory_subq = (
                select(
                    InventoryBalance.product_variant_id,
                    func.sum(
                        InventoryBalance.on_hand_quantity
                    ).label("alert_on_hand"),
                    func.sum(
                        InventoryBalance.reserved_quantity
                    ).label("alert_reserved"),
                )
                .join(
                    ProductBatch,
                    and_(
                        ProductBatch.company_id
                        == InventoryBalance.company_id,
                        ProductBatch.product_variant_id
                        == InventoryBalance.product_variant_id,
                        ProductBatch.id == InventoryBalance.batch_id,
                    ),
                )
                .filter(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id == location_id,
                    InventoryBalance.stock_status == 'AVAILABLE',
                    batch_is_sellable,
                )
                .group_by(InventoryBalance.product_variant_id)
                .subquery()
            )

        def _build_alert_variants_stmt():
            if alert_inventory_subq is None:
                raise RuntimeError(
                    "Alert inventory subquery was not initialized."
                )

            free_expression = (
                func.coalesce(alert_inventory_subq.c.alert_on_hand, 0)
                - func.coalesce(alert_inventory_subq.c.alert_reserved, 0)
            )

            return (
                select(
                    ProductVariant.id,
                    ProductVariant.variant_name,
                )
                .join(
                    InventoryStockPolicy,
                    and_(
                        InventoryStockPolicy.company_id
                        == ProductVariant.company_id,
                        InventoryStockPolicy.product_variant_id
                        == ProductVariant.id,
                        InventoryStockPolicy.location_id == location_id,
                        InventoryStockPolicy.is_active.is_(True),
                    ),
                )
                .outerjoin(
                    alert_inventory_subq,
                    alert_inventory_subq.c.product_variant_id
                    == ProductVariant.id,
                )
                .filter(
                    ProductVariant.company_id == company_id,
                    ProductVariant.is_active.is_(True),
                    InventoryStockPolicy.minimum_quantity > 0,
                    free_expression
                    <= InventoryStockPolicy.minimum_quantity,
                )
            )

        if only_alerts:
            candidate_stmt = _build_alert_variants_stmt()
        else:
            candidate_stmt = select(
                ProductVariant.id,
                ProductVariant.variant_name,
            ).filter(
                ProductVariant.company_id == company_id,
                visible_condition,
            )

        if search_condition is not None:
            candidate_stmt = candidate_stmt.filter(search_condition)

        total = None
        if cursor is None:
            count_source = (
                candidate_stmt
                .order_by(None)
                .subquery()
            )
            total = int(
                (
                    await db.execute(
                        select(func.count()).select_from(count_source)
                    )
                ).scalar_one()
            )

        scope = (
            f"inventory|{company_id}|{location_id}|"
            f"{clean_search}|{int(only_alerts)}"
        )
        if cursor is not None:
            cursor_name, cursor_id = _decode_variant_cursor(
                cursor,
                expected_kind="warehouse-inventory",
                expected_scope=scope,
            )
            candidate_stmt = candidate_stmt.filter(
                or_(
                    ProductVariant.variant_name > cursor_name,
                    and_(
                        ProductVariant.variant_name == cursor_name,
                        ProductVariant.id > cursor_id,
                    ),
                )
            )

        candidate_rows = (
            await db.execute(
                candidate_stmt
                .order_by(
                    ProductVariant.variant_name.asc(),
                    ProductVariant.id.asc(),
                )
                .limit(limit + 1)
            )
        ).all()

        has_more = len(candidate_rows) > limit
        page_candidates = candidate_rows[:limit]
        page_variant_ids = [int(row.id) for row in page_candidates]

        alert_count = None
        alert_samples: list[str] = []
        if cursor is None and not clean_search and not only_alerts:
            alert_stmt = _build_alert_variants_stmt().order_by(
                ProductVariant.variant_name.asc(),
                ProductVariant.id.asc(),
            )

            alert_count = int(
                (
                    await db.execute(
                        select(func.count()).select_from(
                            alert_stmt.order_by(None).subquery()
                        )
                    )
                ).scalar_one()
            )

            if alert_count > 0:
                alert_samples = list(
                    (
                        await db.execute(
                            alert_stmt.with_only_columns(
                                ProductVariant.variant_name
                            ).limit(3)
                        )
                    ).scalars().all()
                )

        if not page_variant_ids:
            return {
                "items": [],
                "next_cursor": None,
                "has_more": False,
                "total": total,
                "alert_count": alert_count,
                "alert_samples": alert_samples,
            }

        warehouse_available_subq = (
            select(
                InventoryBalance.product_variant_id,
                func.sum(
                    InventoryBalance.on_hand_quantity
                ).label('warehouse_on_hand'),
                func.sum(
                    InventoryBalance.reserved_quantity
                ).label('warehouse_reserved'),
                func.sum(
                    case(
                        (
                            batch_is_sellable,
                            InventoryBalance.on_hand_quantity,
                        ),
                        else_=0,
                    )
                ).label('warehouse_sellable_on_hand'),
                func.sum(
                    case(
                        (
                            batch_is_sellable,
                            InventoryBalance.reserved_quantity,
                        ),
                        else_=0,
                    )
                ).label('warehouse_sellable_reserved'),
            )
            .join(
                ProductBatch,
                and_(
                    ProductBatch.company_id
                    == InventoryBalance.company_id,
                    ProductBatch.product_variant_id
                    == InventoryBalance.product_variant_id,
                    ProductBatch.id == InventoryBalance.batch_id,
                ),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.stock_status == 'AVAILABLE',
                InventoryBalance.product_variant_id.in_(
                    page_variant_ids
                ),
            )
            .group_by(InventoryBalance.product_variant_id)
            .subquery()
        )

        warehouse_damaged_subq = (
            select(
                InventoryBalance.product_variant_id,
                func.sum(
                    InventoryBalance.on_hand_quantity
                ).label('damaged_packs'),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.stock_status == 'DAMAGED',
                InventoryBalance.product_variant_id.in_(
                    page_variant_ids
                ),
            )
            .group_by(InventoryBalance.product_variant_id)
            .subquery()
        )

        latest_source_for_vehicle = (
            select(DispatchRoute.source_location_id)
            .filter(
                DispatchRoute.company_id == company_id,
                DispatchRoute.vehicle_id == InventoryLocation.vehicle_id,
            )
            .order_by(DispatchRoute.id.desc())
            .limit(1)
            .correlate(InventoryLocation)
            .scalar_subquery()
        )

        vehicle_inventory_subq = (
            select(
                InventoryBalance.product_variant_id,
                func.sum(
                    InventoryBalance.on_hand_quantity
                ).label('vehicle_packs'),
            )
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id
                    == InventoryBalance.company_id,
                    InventoryLocation.id
                    == InventoryBalance.location_id,
                ),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.stock_status == 'AVAILABLE',
                InventoryBalance.product_variant_id.in_(
                    page_variant_ids
                ),
                InventoryLocation.company_id == company_id,
                InventoryLocation.location_type == 'VEHICLE',
                InventoryLocation.is_active.is_(True),
                InventoryLocation.vehicle_id.isnot(None),
                latest_source_for_vehicle == location_id,
            )
            .group_by(InventoryBalance.product_variant_id)
            .subquery()
        )

        policy_subq = (
            select(
                InventoryStockPolicy.product_variant_id,
                InventoryStockPolicy.minimum_quantity,
            )
            .filter(
                InventoryStockPolicy.company_id == company_id,
                InventoryStockPolicy.location_id == location_id,
                InventoryStockPolicy.is_active.is_(True),
                InventoryStockPolicy.product_variant_id.in_(
                    page_variant_ids
                ),
            )
            .subquery()
        )

        stmt = (
            select(
                ProductVariant,
                warehouse_available_subq.c.warehouse_on_hand,
                warehouse_available_subq.c.warehouse_reserved,
                warehouse_available_subq.c.warehouse_sellable_on_hand,
                warehouse_available_subq.c.warehouse_sellable_reserved,
                warehouse_damaged_subq.c.damaged_packs,
                vehicle_inventory_subq.c.vehicle_packs,
                policy_subq.c.minimum_quantity,
            )
            .outerjoin(
                warehouse_available_subq,
                warehouse_available_subq.c.product_variant_id
                == ProductVariant.id,
            )
            .outerjoin(
                warehouse_damaged_subq,
                warehouse_damaged_subq.c.product_variant_id
                == ProductVariant.id,
            )
            .outerjoin(
                vehicle_inventory_subq,
                vehicle_inventory_subq.c.product_variant_id
                == ProductVariant.id,
            )
            .outerjoin(
                policy_subq,
                policy_subq.c.product_variant_id
                == ProductVariant.id,
            )
            .filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(page_variant_ids),
            )
            .order_by(
                ProductVariant.variant_name.asc(),
                ProductVariant.id.asc(),
            )
        )

        rows = (await db.execute(stmt)).all()

        result = []
        for (
            variant,
            warehouse_on_hand,
            warehouse_reserved,
            warehouse_sellable_on_hand,
            warehouse_sellable_reserved,
            damaged_packs,
            vehicle_packs,
            minimum_quantity,
        ) in rows:
            on_hand = int(warehouse_on_hand or 0)
            reserved = int(warehouse_reserved or 0)

            sellable_on_hand = (
                int(warehouse_sellable_on_hand or 0)
                if variant.is_active
                else 0
            )
            sellable_reserved = (
                int(warehouse_sellable_reserved or 0)
                if variant.is_active
                else 0
            )

            free_packs = sellable_on_hand - sellable_reserved
            blocked_packs = on_hand - sellable_on_hand
            vehicle_total = int(vehicle_packs or 0)
            damaged = int(damaged_packs or 0)

            if free_packs < 0:
                raise RuntimeError(
                    f"Inventory invariant violated for "
                    f"product_variant_id={variant.id}: "
                    "sellable reserved quantity exceeds sellable on-hand."
                )
            if blocked_packs < 0:
                raise RuntimeError(
                    f"Inventory invariant violated for "
                    f"product_variant_id={variant.id}: "
                    "sellable stock exceeds physical AVAILABLE stock."
                )

            ppc = int(variant.packs_per_carton or 1)
            total_physical_available = on_hand + vehicle_total

            result.append({
                "id": variant.id,
                "name": variant.variant_name,
                "sku": variant.sku,
                "packs_per_carton": ppc,
                "available_packs": free_packs,
                "reserved_packs": reserved,
                "blocked_packs": blocked_packs,
                "total_packs": total_physical_available,
                "damaged_packs": damaged,
                "available_cartons": free_packs // ppc,
                "available_loose_packs": free_packs % ppc,
                "min_threshold": int(minimum_quantity or 0),
            })

        if len(result) != len(page_variant_ids):
            raise RuntimeError(
                "Inventory page identity invariant violated."
            )

        next_cursor = None
        if has_more:
            last_candidate = page_candidates[-1]
            next_cursor = _encode_variant_cursor(
                kind="warehouse-inventory",
                variant_name=str(last_candidate.variant_name),
                variant_id=int(last_candidate.id),
                scope=scope,
            )

        return {
            "items": result,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total": total,
            "alert_count": alert_count,
            "alert_samples": alert_samples,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"خطأ في Cursor المخزون الحي: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ داخلي أثناء جلب صفحة المخزون.",
        )


# =================================================================================
# 4. جلب سجل حركات المستودع (Ledger) - InventoryMovement هو المصدر الوحيد
# =================================================================================
# Legacy list ledger endpoint removed after Dashboard cursor migration.
# Cursor API لسجل الحركات؛ الـCursor مربوط بالـTenant والفلاتر الحالية.
@router.get(
    "/warehouse/ledger/cursor",
    response_model=WarehouseLedgerCursorPage,
    status_code=200,
)
async def get_warehouse_ledger_cursor(
    location_id: Optional[int] = None,
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    reference_type: Optional[str] = Query(default=None, max_length=50),
    reference_id: Optional[str] = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    clean_search = (search or "").strip().lower()
    clean_type = (reference_type or "").strip()
    clean_reference = (reference_id or "").strip()

    if clean_search and len(clean_search) < 2:
        raise HTTPException(
            status_code=400,
            detail="البحث في السجل يتطلب حرفين على الأقل.",
        )

    ledger_scope = (
        f"ledger|{company_id}|{location_id or 0}|"
        f"{clean_search}|{clean_type}|{clean_reference}"
    )

    try:
        if location_id is not None:
            stmt_location = select(InventoryLocation.id).filter_by(
                id=location_id,
                company_id=company_id,
                location_type='WAREHOUSE',
            )
            if (await db.execute(stmt_location)).scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=404,
                    detail="المستودع غير موجود أو لا يتبع شركتك.",
                )

        stmt = select(
            InventoryMovement,
            ProductVariant.variant_name,
            ProductVariant.packs_per_carton,
            Driver.full_name,
        ).join(
            ProductVariant,
            and_(
                ProductVariant.company_id == InventoryMovement.company_id,
                ProductVariant.id == InventoryMovement.product_variant_id,
            ),
        ).join(
            Driver,
            and_(
                Driver.company_id == InventoryMovement.company_id,
                Driver.id == InventoryMovement.performed_by,
            ),
        ).filter(
            InventoryMovement.company_id == company_id,
        )

        if location_id is not None:
            stmt = stmt.filter(
                or_(
                    InventoryMovement.source_location_id == location_id,
                    InventoryMovement.destination_location_id == location_id,
                )
            )

        if clean_type:
            stmt = stmt.filter(
                InventoryMovement.reference_type == clean_type,
            )

        if clean_reference:
            stmt = stmt.filter(
                InventoryMovement.reference_id == clean_reference
            )

        if clean_search:
            like_pattern = f"%{_escape_like(clean_search)}%"
            stmt = stmt.filter(
                or_(
                    func.lower(ProductVariant.variant_name).like(
                        like_pattern, escape="\\"
                    ),
                    func.lower(InventoryMovement.reference_id).like(
                        like_pattern, escape="\\"
                    ),
                    func.lower(Driver.full_name).like(
                        like_pattern, escape="\\"
                    ),
                    func.lower(
                        func.coalesce(InventoryMovement.notes, "")
                    ).like(
                        like_pattern, escape="\\"
                    ),
                )
            )

        total = None
        if cursor is None:
            count_stmt = select(func.count()).select_from(
                stmt.with_only_columns(
                    InventoryMovement.id,
                    maintain_column_froms=True,
                ).order_by(None).subquery()
            )
            total = int((await db.execute(count_stmt)).scalar_one())

        if cursor is not None:
            cursor_created_at, cursor_id = _decode_ledger_cursor(
                cursor,
                expected_scope=ledger_scope,
            )
            stmt = stmt.filter(
                or_(
                    InventoryMovement.created_at < cursor_created_at,
                    and_(
                        InventoryMovement.created_at == cursor_created_at,
                        InventoryMovement.id < cursor_id,
                    ),
                )
            )

        stmt = stmt.order_by(
            InventoryMovement.created_at.desc(),
            InventoryMovement.id.desc(),
        ).limit(limit + 1)

        rows = (await db.execute(stmt)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]

        available_types: list[str] = []
        if cursor is None and reference_id is None:
            type_stmt = select(
                InventoryMovement.reference_type
            ).filter(
                InventoryMovement.company_id == company_id,
            )

            if location_id is not None:
                type_stmt = type_stmt.filter(
                    or_(
                        InventoryMovement.source_location_id == location_id,
                        InventoryMovement.destination_location_id == location_id,
                    )
                )

            available_types = list(
                (
                    await db.execute(
                        type_stmt.distinct().order_by(
                            InventoryMovement.reference_type.asc()
                        )
                    )
                ).scalars().all()
            )

        if not rows:
            return {
                "items": [],
                "next_cursor": None,
                "has_more": False,
                "total": total,
                "available_types": available_types,
            }

        movement_ids = [row[0].id for row in rows]

        stmt_impacts = select(
            InventoryMovementImpact,
            InventoryBalance,
        ).join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id
                == InventoryMovementImpact.company_id,
                InventoryBalance.id
                == InventoryMovementImpact.inventory_balance_id,
            ),
        ).filter(
            InventoryMovementImpact.company_id == company_id,
            InventoryMovementImpact.movement_id.in_(movement_ids),
            InventoryBalance.company_id == company_id,
        )

        if location_id is not None:
            stmt_impacts = stmt_impacts.filter(
                InventoryBalance.location_id == location_id
            )

        impacts_by_movement: dict[
            int,
            list[tuple[InventoryMovementImpact, InventoryBalance]],
        ] = {}

        for impact, balance in (await db.execute(stmt_impacts)).all():
            impacts_by_movement.setdefault(
                impact.movement_id,
                [],
            ).append((impact, balance))

        result = []

        for movement, product_name, packs_per_carton, admin_name in rows:
            candidates = impacts_by_movement.get(movement.id, [])
            chosen = None

            def _find_impact(target_location_id, target_status):
                if target_location_id is None or target_status is None:
                    return None
                for impact_row, balance_row in candidates:
                    if (
                        balance_row.location_id == target_location_id
                        and balance_row.stock_status == target_status
                    ):
                        return impact_row, balance_row
                return None

            if movement.movement_kind == 'STATUS_CHANGE':
                chosen = _find_impact(
                    movement.source_location_id,
                    'AVAILABLE',
                )
            elif location_id is not None:
                if movement.source_location_id == location_id:
                    chosen = _find_impact(
                        location_id,
                        movement.source_stock_status,
                    )
                if (
                    chosen is None
                    and movement.destination_location_id == location_id
                ):
                    chosen = _find_impact(
                        location_id,
                        movement.destination_stock_status,
                    )
            else:
                chosen = _find_impact(
                    movement.source_location_id,
                    movement.source_stock_status,
                )
                if chosen is None:
                    chosen = _find_impact(
                        movement.destination_location_id,
                        movement.destination_stock_status,
                    )

            balance_before = None
            balance_after = None
            quantity_packs = None

            if chosen is not None:
                impact, _balance = chosen

                if movement.movement_kind == 'RESERVATION':
                    balance_before = (
                        int(impact.on_hand_before)
                        - int(impact.reserved_before)
                    )
                    balance_after = (
                        int(impact.on_hand_after)
                        - int(impact.reserved_after)
                    )
                else:
                    balance_before = int(impact.on_hand_before)
                    balance_after = int(impact.on_hand_after)

                quantity_packs = balance_after - balance_before

            if quantity_packs is None:
                quantity = int(movement.quantity)

                if movement.movement_kind == 'RESERVATION':
                    quantity_packs = (
                        -quantity
                        if movement.reservation_action == 'RESERVE'
                        else quantity
                    )
                elif movement.movement_kind == 'STATUS_CHANGE':
                    quantity_packs = (
                        -quantity
                        if movement.source_stock_status == 'AVAILABLE'
                        else quantity
                    )
                elif location_id is not None:
                    quantity_packs = (
                        -quantity
                        if movement.source_location_id == location_id
                        else quantity
                    )
                else:
                    quantity_packs = (
                        -quantity
                        if movement.source_location_id is not None
                        else quantity
                    )

            created_at = movement.created_at
            if created_at is not None:
                if created_at.tzinfo is None:
                    response_created_at = created_at.replace(
                        tzinfo=timezone.utc
                    )
                else:
                    response_created_at = created_at.astimezone(
                        timezone.utc
                    )
            else:
                response_created_at = None

            result.append({
                "id": movement.id,
                "product_variant_id": movement.product_variant_id,
                "product_name": product_name,
                "packs_per_carton": int(packs_per_carton or 1),
                "type": movement.reference_type,
                "quantity_packs": int(quantity_packs),
                "balance_before": balance_before,
                "balance_after": balance_after,
                "admin_name": admin_name or "غير معروف",
                "reference": movement.reference_id,
                "notes": movement.notes,
                "date": (
                    response_created_at.isoformat()
                    if response_created_at
                    else ""
                ),
            })

        next_cursor = None
        if has_more and rows:
            last_movement = rows[-1][0]
            if last_movement.created_at is None:
                raise RuntimeError(
                    "Ledger invariant violated: movement without created_at."
                )
            next_cursor = _encode_ledger_cursor(
                last_movement.created_at,
                last_movement.id,
                scope=ledger_scope,
            )

        return {
            "items": result,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total": total,
            "available_types": available_types,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"خطأ في Cursor سجل المستودع: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ داخلي أثناء جلب صفحة سجل الحركات.",
        )


# =================================================================================
# 5. جلب حالة قفل المستودع
# =================================================================================
# جلب حالة قفل مستودع محدد اعتماداً على الأقفال الفعلية للمحرك الموحد.
@router.get("/warehouse/status", response_model=WarehouseStatusResponse, status_code=200)
async def get_warehouse_status(
    location_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    stmt_location = select(InventoryLocation.id).filter_by(
        id=location_id,
        company_id=current_admin.company_id,
        location_type='WAREHOUSE',
        is_active=True
    )
    location_exists = (await db.execute(stmt_location)).scalar_one_or_none()

    if location_exists is None:
        raise HTTPException(
            status_code=404,
            detail="المستودع غير موجود أو لا يتبع شركتك."
        )

    stmt_lock = select(InventoryLock.id).filter(
        InventoryLock.company_id == current_admin.company_id,
        InventoryLock.location_id == location_id,
        InventoryLock.product_variant_id.is_(None),
        InventoryLock.batch_id.is_(None),
        InventoryLock.released_at.is_(None)
    ).limit(1)

    active_lock = (await db.execute(stmt_lock)).scalar_one_or_none()

    return {
        "status": "AUDIT_LOCK" if active_lock is not None else "ACTIVE"
    }


# =================================================================================
# 6. جلب قائمة المنتجات فقط (للقوائم المنسدلة Dropdowns)
# =================================================================================
@router.get(
    "/product_variants/simple/cursor",
    response_model=SimpleProductVariantCursorPage,
    status_code=200,
)
async def get_simple_product_variants(
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    clean_search = (search or "").strip().lower()

    if clean_search and len(clean_search) < 2:
        raise HTTPException(
            status_code=400,
            detail="البحث في كتالوج المنتجات يتطلب حرفين على الأقل.",
        )

    stmt = select(
        ProductVariant.id,
        ProductVariant.variant_name,
        ProductVariant.sku,
        ProductVariant.packs_per_carton,
    ).filter(
        ProductVariant.company_id == company_id,
        ProductVariant.is_active.is_(True),
    )

    if clean_search:
        like_pattern = f"%{_escape_like(clean_search)}%"
        stmt = stmt.filter(
            or_(
                func.lower(ProductVariant.variant_name).like(
                    like_pattern,
                    escape="\\",
                ),
                func.lower(
                    func.coalesce(ProductVariant.sku, "")
                ).like(
                    like_pattern,
                    escape="\\",
                ),
            )
        )

    total = None
    if cursor is None:
        total = int(
            (
                await db.execute(
                    select(func.count()).select_from(
                        stmt.with_only_columns(
                            ProductVariant.id,
                            maintain_column_froms=True,
                        ).order_by(None).subquery()
                    )
                )
            ).scalar_one()
        )

    scope = f"catalog|{company_id}|{clean_search}"
    if cursor is not None:
        cursor_name, cursor_id = _decode_variant_cursor(
            cursor,
            expected_kind="product-catalog",
            expected_scope=scope,
        )
        stmt = stmt.filter(
            or_(
                ProductVariant.variant_name > cursor_name,
                and_(
                    ProductVariant.variant_name == cursor_name,
                    ProductVariant.id > cursor_id,
                ),
            )
        )

    rows = (
        await db.execute(
            stmt.order_by(
                ProductVariant.variant_name.asc(),
                ProductVariant.id.asc(),
            ).limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor = None
    if has_more and page_rows:
        last_row = page_rows[-1]
        next_cursor = _encode_variant_cursor(
            kind="product-catalog",
            variant_name=str(last_row.variant_name),
            variant_id=int(last_row.id),
            scope=scope,
        )

    return {
        "items": [
            {
                "id": int(row.id),
                "name": row.variant_name,
                "sku": row.sku,
                "packs_per_carton": int(
                    row.packs_per_carton or 1
                ),
            }
            for row in page_rows
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


@router.post(
    "/product_variants/simple/resolve",
    response_model=List[SimpleProductVariantItem],
    status_code=200,
)
async def resolve_simple_product_variants(
    payload: ProductVariantResolveRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    requested_ids = sorted(set(int(value) for value in payload.ids))

    rows = (
        await db.execute(
            select(
                ProductVariant.id,
                ProductVariant.variant_name,
                ProductVariant.sku,
                ProductVariant.packs_per_carton,
            )
            .filter(
                ProductVariant.company_id == company_id,
                ProductVariant.is_active.is_(True),
                ProductVariant.id.in_(requested_ids),
            )
            .order_by(
                ProductVariant.variant_name.asc(),
                ProductVariant.id.asc(),
            )
        )
    ).all()

    return [
        {
            "id": int(row.id),
            "name": row.variant_name,
            "sku": row.sku,
            "packs_per_carton": int(row.packs_per_carton or 1),
        }
        for row in rows
    ]


# =================================================================================
# 7. إضافة منتج جديد لكتالوج الشركة - Tenant/Concurrency Safe
# =================================================================================
@router.post("/warehouse/product_variants", status_code=201)
async def add_product_variant(
    payload: AddProductVariantRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    clean_name = payload.variant_name.strip()
    normalized_name = clean_name.lower()
    clean_sku = payload.sku.strip() if payload.sku else None

    try:
        # نفس الاسم أو SKU داخل الشركة يجب أن يتسلسل قبل فحص التكرار.
        # ترتيب المفاتيح يمنع Deadlock لو طلبان يشتركان في أكثر من قيمة.
        lock_tokens = [
            f"product-name:{normalized_name}"
        ]
        if clean_sku:
            lock_tokens.append(
                f"product-sku:{clean_sku}"
            )

        for token in sorted(lock_tokens):
            await db.execute(
                select(
                    func.pg_advisory_xact_lock(
                        company_id,
                        func.hashtext(token)
                    )
                )
            )

        duplicate_conditions = [
            func.lower(ProductVariant.variant_name) == normalized_name
        ]
        if clean_sku:
            duplicate_conditions.append(
                ProductVariant.sku == clean_sku
            )

        stmt_exist = select(ProductVariant).filter(
            ProductVariant.company_id == company_id,
            or_(*duplicate_conditions)
        )
        existing = (
            await db.execute(stmt_exist)
        ).scalars().first()

        if existing:
            if existing.variant_name.lower() == normalized_name:
                raise HTTPException(
                    status_code=409,
                    detail=f"المنتج '{payload.variant_name}' موجود مسبقاً في شركتك."
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"الباركود (SKU) '{clean_sku}' مستخدم بالفعل "
                    f"لمنتج آخر في شركتك ({existing.variant_name})."
                )
            )

        from models import UOM

        # Bootstrap للـ Parent باستخدام UPSERT، لذلك منتجان مختلفان
        # يُضافان معاً لأول مرة بدون أن يتصادما على "منتجات عامة".
        stmt_parent_insert = pg_insert(Product).values(
            company_id=company_id,
            base_name="منتجات عامة"
        ).on_conflict_do_nothing(
            index_elements=['company_id', 'base_name']
        )
        await db.execute(stmt_parent_insert)

        stmt_product = select(Product).filter_by(
            company_id=company_id,
            base_name="منتجات عامة"
        )
        base_product = (
            await db.execute(stmt_product)
        ).scalar_one_or_none()

        if base_product is None:
            raise HTTPException(
                status_code=409,
                detail="تعذر تجهيز الكتالوج الأساسي للشركة."
            )

        # UOM جدول سيادي مشترك. Bootstrap آمن حتى لو أول شركتين
        # بدأتا بإضافة المنتجات في نفس اللحظة.
        stmt_uom = select(UOM.id).filter(
            func.upper(UOM.code) == 'CARTON'
        ).limit(1)

        uom_id = (
            await db.execute(stmt_uom)
        ).scalar_one_or_none()

        if uom_id is None:
            stmt_uom_insert = pg_insert(UOM).values(
                name="كرتونة",
                code="CARTON"
            ).on_conflict_do_nothing()

            await db.execute(stmt_uom_insert)

            uom_id = (
                await db.execute(stmt_uom)
            ).scalar_one_or_none()

        if uom_id is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "تعذر تجهيز وحدة القياس CARTON. "
                    "يوجد تعارض في بيانات وحدات القياس السيادية ويجب تصحيحه إدارياً."
                )
            )

        new_variant = ProductVariant(
            company_id=company_id,
            product_id=base_product.id,
            base_uom_id=uom_id,
            variant_name=clean_name,
            sku=clean_sku,
            price_per_carton=payload.price_per_carton,
            packs_per_carton=payload.packs_per_carton,
            price_per_pack=payload.price_per_pack,
            default_max_samples_per_day=(
                payload.default_max_samples_per_day or 0
            ),
            is_active=True
        )
        db.add(new_variant)
        await db.flush()

        stmt_warehouses = select(
            InventoryLocation.id
        ).filter_by(
            company_id=company_id,
            location_type='WAREHOUSE',
            is_active=True
        ).order_by(
            InventoryLocation.id.asc()
        )
        warehouse_ids = (
            await db.execute(stmt_warehouses)
        ).scalars().all()

        minimum_quantity = int(
            payload.min_threshold_packs or 0
        )

        if not warehouse_ids:
            # Auto-Provision آمن للشركة الجديدة فقط. إذا WH-MAIN موجود
            # لكنه متوقف فلن نعيد تفعيله بصمت.
            stmt_any_warehouse = select(
                InventoryLocation.id
            ).filter_by(
                company_id=company_id,
                location_type='WAREHOUSE'
            ).limit(1)

            any_warehouse = (
                await db.execute(stmt_any_warehouse)
            ).scalar_one_or_none()

            if any_warehouse is None:
                stmt_provision = pg_insert(
                    InventoryLocation
                ).values(
                    company_id=company_id,
                    name="المستودع الرئيسي",
                    code="WH-MAIN",
                    location_type='WAREHOUSE',
                    is_active=True
                ).on_conflict_do_nothing(
                    index_elements=['company_id', 'code']
                )
                await db.execute(stmt_provision)

                warehouse_ids = (
                    await db.execute(stmt_warehouses)
                ).scalars().all()

        if not warehouse_ids:
            raise HTTPException(
                status_code=409,
                detail=(
                    "لا يوجد مستودع فعال يمكن ربط سياسة حد النقص به. "
                    "فعّل مستودعاً أولاً ثم أعد إضافة المنتج."
                )
            )

        for warehouse_id in warehouse_ids:
            db.add(InventoryStockPolicy(
                company_id=company_id,
                location_id=warehouse_id,
                product_variant_id=new_variant.id,
                minimum_quantity=minimum_quantity,
                target_quantity=None,
                is_active=True
            ))

        await db.commit()

        return {
            "message": f"تم إضافة المنتج '{new_variant.variant_name}' بنجاح.",
            "product_id": new_variant.id
        }

    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.warning(
            f"تعارض متزامن أثناء إضافة المنتج: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "مرفوض: حدث تعارض متزامن أثناء إضافة المنتج. "
                "تحقق من الاسم أو SKU ثم أعد المحاولة."
            )
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"خطأ في حفظ المنتج: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ داخلي في الخادم أثناء حفظ المنتج."
        )


# =================================================================================
# 8. تعديل فاتورة توريد - Correction append-only على المحرك الموحد
# =================================================================================
@router.post("/warehouse/ledger/{entry_id}/adjust", status_code=200)
async def adjust_warehouse_entry(
    entry_id: int,
    payload: AdjustWarehouseEntryRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id

    password_ok = await asyncio.to_thread(
        bcrypt.checkpw,
        payload.password.encode('utf-8'),
        current_admin.password_hash.encode('utf-8')
    )

    if not password_ok:
        try:
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"InventoryMovement_{entry_id}",
                action_type='UNAUTHORIZED_ADJUSTMENT',
                old_value='Wrong Password',
                new_value='Rejected'
            ))
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(
                f"Failed to log unauthorized adjustment: {e}",
                exc_info=True
            )

        raise HTTPException(
            status_code=403,
            detail="كلمة المرور غير صحيحة. تم رفض العملية وتوثيق المحاولة."
        )

    try:
        new_total_packs = int(payload.new_total_packs)
        if new_total_packs < 0:
            raise HTTPException(
                status_code=400,
                detail="مرفوض: لا يمكن أن يكون الإجمالي الجديد قيمة سالبة."
            )

        stmt_original = select(InventoryMovement).filter(
            InventoryMovement.company_id == company_id,
            InventoryMovement.id == entry_id,
            InventoryMovement.reference_type == 'INBOUND_SUPPLIER'
        )
        original = (
            await db.execute(stmt_original)
        ).scalar_one_or_none()

        if original is None:
            raise HTTPException(
                status_code=404,
                detail="حركة التوريد غير موجودة أو لا تتبع لشركتك."
            )

        if (
            original.movement_kind != 'PHYSICAL'
            or original.source_location_id is not None
            or original.destination_location_id is None
            or original.destination_stock_status != 'AVAILABLE'
        ):
            raise HTTPException(
                status_code=409,
                detail="الحركة المحددة ليست حركة توريد مورد صالحة للتعديل."
            )

        ref_id = (original.reference_id or "").strip()
        if not ref_id or ref_id == "بدون فاتورة":
            raise HTTPException(
                status_code=400,
                detail=(
                    "مرفوض: لا يمكن تعديل حركة توريد لا تحمل مرجعاً صالحاً."
                )
            )

        normalized_ref = ref_id.lower()

        # تسلسل كل تعديلات نفس فاتورة/صنف داخل نفس الشركة.
        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    company_id,
                    func.hashtext(
                        f"inbound-adjust:{original.product_variant_id}:{normalized_ref}"
                    )
                )
            )
        )

        # أعد القراءة بعد القفل حتى لا نعتمد على حالة سبقت انتظار عملية منافسة.
        original = (
            await db.execute(stmt_original)
        ).scalar_one_or_none()
        if original is None:
            raise HTTPException(
                status_code=404,
                detail="حركة التوريد لم تعد متاحة."
            )

        stmt_supplier_movements = select(
            InventoryMovement
        ).filter(
            InventoryMovement.company_id == company_id,
            InventoryMovement.product_variant_id == original.product_variant_id,
            InventoryMovement.reference_type == 'INBOUND_SUPPLIER',
            func.lower(func.trim(InventoryMovement.reference_id)) == normalized_ref
        ).order_by(
            InventoryMovement.id.asc()
        )

        supplier_movements = (
            await db.execute(stmt_supplier_movements)
        ).scalars().all()

        if not supplier_movements:
            raise HTTPException(
                status_code=409,
                detail="تعذر العثور على قيود التوريد الأصلية لهذه الفاتورة."
            )

        batch_ids = {
            movement.batch_id
            for movement in supplier_movements
        }
        destination_ids = {
            movement.destination_location_id
            for movement in supplier_movements
        }

        if len(batch_ids) != 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "هذه الفاتورة تحتوي أكثر من Batch لنفس الصنف. "
                    "تم رفض التعديل الإجمالي لمنع الخصم من دفعة خاطئة؛ "
                    "التصحيح يجب أن يكون على مستوى الدفعة."
                )
            )

        if len(destination_ids) != 1 or None in destination_ids:
            raise HTTPException(
                status_code=409,
                detail="قيود التوريد الأصلية تحمل أكثر من وجهة أو وجهة غير صالحة."
            )

        batch_id = next(iter(batch_ids))
        warehouse_location_id = next(iter(destination_ids))

        stmt_location = select(InventoryLocation.id).filter_by(
            company_id=company_id,
            id=warehouse_location_id,
            location_type='WAREHOUSE'
        )
        if (await db.execute(stmt_location)).scalar_one_or_none() is None:
            raise HTTPException(
                status_code=409,
                detail="مستودع فاتورة التوريد غير موجود أو لا يتبع شركتك."
            )

        stmt_invoice_movements = select(
            InventoryMovement
        ).filter(
            InventoryMovement.company_id == company_id,
            InventoryMovement.product_variant_id == original.product_variant_id,
            InventoryMovement.batch_id == batch_id,
            InventoryMovement.reference_type.in_([
                'INBOUND_SUPPLIER',
                'INBOUND_CORRECTION'
            ]),
            func.lower(func.trim(InventoryMovement.reference_id)) == normalized_ref
        ).order_by(
            InventoryMovement.id.asc()
        )

        invoice_movements = (
            await db.execute(stmt_invoice_movements)
        ).scalars().all()

        current_total_packs = 0

        for movement in invoice_movements:
            quantity = int(movement.quantity)

            if movement.reference_type == 'INBOUND_SUPPLIER':
                if (
                    movement.source_location_id is not None
                    or movement.destination_location_id != warehouse_location_id
                    or movement.destination_stock_status != 'AVAILABLE'
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="تم اكتشاف قيد توريد غير متسق؛ أوقف التعديل وراجع السجل."
                    )
                current_total_packs += quantity
                continue

            is_positive_correction = (
                movement.source_location_id is None
                and movement.destination_location_id == warehouse_location_id
                and movement.destination_stock_status == 'AVAILABLE'
            )
            is_negative_correction = (
                movement.source_location_id == warehouse_location_id
                and movement.destination_location_id is None
                and movement.source_stock_status == 'AVAILABLE'
            )

            if is_positive_correction:
                current_total_packs += quantity
            elif is_negative_correction:
                current_total_packs -= quantity
            else:
                raise HTTPException(
                    status_code=409,
                    detail="تم اكتشاف قيد تصحيح غير متسق؛ أوقف التعديل وراجع السجل."
                )

        if current_total_packs < 0:
            raise HTTPException(
                status_code=409,
                detail="الصافي التاريخي للفاتورة أصبح سالباً؛ تم رفض أي تعديل إضافي."
            )

        delta = new_total_packs - current_total_packs

        if delta == 0:
            await db.commit()
            return {
                "message": "لا يوجد تغيير في الكمية. الصافي الحالي مطابق لما أدخلته."
            }

        idempotency_raw = (
            f"{company_id}|{normalized_ref}|{original.product_variant_id}|"
            f"{batch_id}|{current_total_packs}|{new_total_packs}"
        )
        idempotency_key = (
            "ADJ-"
            + hashlib.sha256(
                idempotency_raw.encode("utf-8")
            ).hexdigest()
        )

        correction_notes = (
            f"تصحيح فاتورة مورد: {payload.notes}"
            if payload.notes
            else "تصحيح فاتورة مورد"
        )

        correction_movement = await apply_inventory_movement(
            db,
            company_id=company_id,
            performed_by=current_admin.id,
            product_variant_id=original.product_variant_id,
            batch_id=batch_id,
            quantity=abs(delta),
            movement_kind='PHYSICAL',
            reference_type='INBOUND_CORRECTION',
            reference_id=ref_id,
            idempotency_key=idempotency_key,
            source_location_id=(
                warehouse_location_id
                if delta < 0
                else None
            ),
            destination_location_id=(
                warehouse_location_id
                if delta > 0
                else None
            ),
            source_stock_status=(
                'AVAILABLE'
                if delta < 0
                else None
            ),
            destination_stock_status=(
                'AVAILABLE'
                if delta > 0
                else None
            ),
            notes=correction_notes
        )

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"InventoryMovement_{correction_movement.id}",
            action_type='INBOUND_ADJUSTMENT',
            old_value=json.dumps(
                {
                    "reference": ref_id,
                    "product_variant_id": original.product_variant_id,
                    "batch_id": batch_id,
                    "total_packs": current_total_packs
                },
                ensure_ascii=False
            ),
            new_value=json.dumps(
                {
                    "total_packs": new_total_packs,
                    "delta": delta
                },
                ensure_ascii=False
            )
        ))

        await db.commit()

        return {
            "message": (
                "تم تسجيل التصحيح كحركة مستقلة وتحديث الرصيد بنجاح. "
                f"الفرق: {'+' if delta > 0 else ''}{delta} حبة."
            )
        }

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as e:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=str(e)
        )
    except IntegrityError as e:
        await db.rollback()
        logger.warning(
            f"تعارض متزامن في تعديل فاتورة التوريد: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=409,
            detail="حدث تعارض متزامن أثناء التعديل. لم يتم حفظ تصحيح جزئي."
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"خطأ في تعديل فاتورة التوريد: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء معالجة التعديل."
        )


# =================================================================================
# [المرحلة الرابعة والخامسة] المحرك الموحد للحوالات ونظام الصلاحية (FEFO & IN_TRANSIT)
# =================================================================================

async def _verify_location_ownership(
    db: AsyncSession,
    company_id: int,
    *location_ids,
    allowed_types: Optional[List[str]] = None
):
    """التحقق من الانتماء والحالة ونوع الموقع دون كشف بيانات Tenant آخر."""
    unique_ids = sorted({int(loc_id) for loc_id in location_ids})

    stmt = select(
        InventoryLocation.id,
        InventoryLocation.location_type,
        InventoryLocation.is_active
    ).filter(
        InventoryLocation.company_id == company_id,
        InventoryLocation.id.in_(unique_ids)
    )
    rows = (await db.execute(stmt)).all()
    found = {
        row.id: (row.location_type, bool(row.is_active))
        for row in rows
    }

    if set(found) != set(unique_ids):
        raise ValueError("مرفوض أمنياً: أحد المواقع غير موجود أو لا ينتمي للشركة.")

    for loc_id in unique_ids:
        location_type, is_active = found[loc_id]
        if not is_active:
            raise ValueError(f"مرفوض أمنياً: الموقع ({loc_id}) غير فعال.")
        if allowed_types and location_type not in allowed_types:
            raise ValueError(
                f"مرفوض أمنياً: نوع الموقع ({location_type}) غير مسموح لهذه العملية."
            )


async def _acquire_shared_inventory_guards(
    db: AsyncSession,
    company_id: int,
    *location_ids: int
) -> None:
    """ترتيب حراس المواقع قبل أي Row Lock لمنع دورات Deadlock."""
    for location_id in sorted({int(x) for x in location_ids}):
        await acquire_inventory_location_guard(
            db,
            company_id,
            location_id,
            exclusive=False
        )


@router.get(
    "/warehouse/unified/transfer/locations",
    response_model=List[UnifiedTransferLocationItem],
    status_code=200,
)
async def list_unified_transfer_locations(
    search: Optional[str] = Query(
        default=None,
        min_length=2,
        max_length=100,
    ),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    clean_search = (search or "").strip().lower()

    stmt = (
        select(
            InventoryLocation.id,
            InventoryLocation.name,
            InventoryLocation.code,
            InventoryLocation.location_type,
            InventoryLocation.vehicle_id,
        )
        .filter(
            InventoryLocation.company_id == company_id,
            InventoryLocation.is_active.is_(True),
            InventoryLocation.location_type.in_(
                ['WAREHOUSE', 'VEHICLE']
            ),
        )
    )

    if clean_search:
        pattern = f"%{_escape_like(clean_search)}%"
        stmt = stmt.filter(
            or_(
                func.lower(InventoryLocation.name).like(
                    pattern,
                    escape="\\",
                ),
                func.lower(InventoryLocation.code).like(
                    pattern,
                    escape="\\",
                ),
            )
        )

    rows = (
        await db.execute(
            stmt.order_by(
                case(
                    (InventoryLocation.location_type == 'WAREHOUSE', 0),
                    else_=1,
                ),
                InventoryLocation.name.asc(),
                InventoryLocation.id.asc(),
            ).limit(limit)
        )
    ).all()

    return [
        {
            "id": int(row.id),
            "name": str(row.name),
            "code": str(row.code),
            "location_type": str(row.location_type),
            "vehicle_id": (
                int(row.vehicle_id)
                if row.vehicle_id is not None
                else None
            ),
        }
        for row in rows
    ]


@router.get(
    "/warehouse/unified/transfer/source-inventory",
    response_model=UnifiedTransferSourceInventoryCursorPage,
    status_code=200,
)
async def get_unified_transfer_source_inventory(
    location_id: int = Query(..., ge=1),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    clean_search = (search or "").strip().lower()

    location = (
        await db.execute(
            select(
                InventoryLocation.id,
                InventoryLocation.location_type,
            ).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
                InventoryLocation.is_active.is_(True),
                InventoryLocation.location_type.in_(
                    ['WAREHOUSE', 'VEHICLE']
                ),
            )
        )
    ).one_or_none()

    if location is None:
        raise HTTPException(
            status_code=404,
            detail="مصدر الحوالة غير موجود أو غير فعال أو لا يتبع شركتك.",
        )

    as_of_date = await get_company_local_date(db, company_id)

    sellable_batch = and_(
        ProductBatch.company_id == InventoryBalance.company_id,
        ProductBatch.product_variant_id
        == InventoryBalance.product_variant_id,
        ProductBatch.id == InventoryBalance.batch_id,
        ProductBatch.is_active.is_(True),
        or_(
            ProductBatch.production_date.is_(None),
            ProductBatch.production_date <= as_of_date,
        ),
        ProductBatch.expiry_date >= as_of_date,
    )

    active_lock_exists = (
        select(InventoryLock.id)
        .filter(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == location_id,
            InventoryLock.released_at.is_(None),
            or_(
                and_(
                    InventoryLock.product_variant_id.is_(None),
                    InventoryLock.batch_id.is_(None),
                ),
                and_(
                    InventoryLock.product_variant_id
                    == InventoryBalance.product_variant_id,
                    or_(
                        InventoryLock.batch_id.is_(None),
                        InventoryLock.batch_id
                        == InventoryBalance.batch_id,
                    ),
                ),
            ),
        )
        .correlate(InventoryBalance)
        .exists()
    )

    available_expression = func.sum(
        InventoryBalance.on_hand_quantity
        - InventoryBalance.reserved_quantity
    )

    stmt = (
        select(
            ProductVariant.id,
            ProductVariant.variant_name,
            ProductVariant.sku,
            ProductVariant.packs_per_carton,
            available_expression.label("available_packs"),
        )
        .join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id
                == ProductVariant.company_id,
                InventoryBalance.product_variant_id
                == ProductVariant.id,
            ),
        )
        .join(
            ProductBatch,
            sellable_batch,
        )
        .filter(
            ProductVariant.company_id == company_id,
            ProductVariant.is_active.is_(True),
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
            InventoryBalance.stock_status == 'AVAILABLE',
            ~active_lock_exists,
        )
        .group_by(
            ProductVariant.id,
            ProductVariant.variant_name,
            ProductVariant.sku,
            ProductVariant.packs_per_carton,
        )
        .having(available_expression > 0)
    )

    if clean_search:
        pattern = f"%{_escape_like(clean_search)}%"
        stmt = stmt.filter(
            or_(
                func.lower(ProductVariant.variant_name).like(
                    pattern,
                    escape="\\",
                ),
                func.lower(
                    func.coalesce(ProductVariant.sku, "")
                ).like(
                    pattern,
                    escape="\\",
                ),
            )
        )

    scope = (
        f"transfer-source|{company_id}|{location_id}|{clean_search}"
    )

    total = None
    if cursor is None:
        total = int(
            (
                await db.execute(
                    select(func.count()).select_from(
                        stmt.order_by(None).subquery()
                    )
                )
            ).scalar_one()
        )

    if cursor is not None:
        cursor_name, cursor_id = _decode_variant_cursor(
            cursor,
            expected_kind="transfer-source-inventory",
            expected_scope=scope,
        )
        stmt = stmt.filter(
            or_(
                ProductVariant.variant_name > cursor_name,
                and_(
                    ProductVariant.variant_name == cursor_name,
                    ProductVariant.id > cursor_id,
                ),
            )
        )

    rows = (
        await db.execute(
            stmt.order_by(
                ProductVariant.variant_name.asc(),
                ProductVariant.id.asc(),
            ).limit(limit + 1)
        )
    ).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor = None
    if has_more and page_rows:
        last_row = page_rows[-1]
        next_cursor = _encode_variant_cursor(
            kind="transfer-source-inventory",
            variant_name=str(last_row.variant_name),
            variant_id=int(last_row.id),
            scope=scope,
        )

    return {
        "items": [
            {
                "id": int(row.id),
                "name": str(row.variant_name),
                "sku": row.sku,
                "packs_per_carton": int(
                    row.packs_per_carton or 1
                ),
                "available_packs": int(
                    row.available_packs or 0
                ),
            }
            for row in page_rows
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


@router.get(
    "/warehouse/unified/transfer/override-options",
    response_model=UnifiedTransferOverrideOptionsResponse,
    status_code=200,
)
async def get_unified_transfer_override_options(
    location_id: int = Query(..., ge=1),
    product_variant_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    location_exists = (
        await db.execute(
            select(InventoryLocation.id).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
                InventoryLocation.is_active.is_(True),
                InventoryLocation.location_type.in_(
                    ['WAREHOUSE', 'VEHICLE']
                ),
            )
        )
    ).scalar_one_or_none()

    if location_exists is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "مصدر الحوالة غير موجود أو غير فعال "
                "أو لا يتبع شركتك."
            ),
        )

    product_exists = (
        await db.execute(
            select(ProductVariant.id).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id == product_variant_id,
                ProductVariant.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()

    if product_exists is None:
        raise HTTPException(
            status_code=404,
            detail="الصنف غير موجود أو غير فعال أو لا يتبع شركتك.",
        )

    as_of_date = await get_company_local_date(db, company_id)

    active_lock_exists = (
        select(InventoryLock.id)
        .filter(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == location_id,
            InventoryLock.released_at.is_(None),
            or_(
                and_(
                    InventoryLock.product_variant_id.is_(None),
                    InventoryLock.batch_id.is_(None),
                ),
                and_(
                    InventoryLock.product_variant_id
                    == InventoryBalance.product_variant_id,
                    or_(
                        InventoryLock.batch_id.is_(None),
                        InventoryLock.batch_id
                        == InventoryBalance.batch_id,
                    ),
                ),
            ),
        )
        .correlate(InventoryBalance)
        .exists()
    )

    available_expression = func.sum(
        InventoryBalance.on_hand_quantity
        - InventoryBalance.reserved_quantity
    )

    batch_rows = (
        await db.execute(
            select(
                ProductBatch.id,
                ProductBatch.batch_number,
                ProductBatch.production_date,
                ProductBatch.expiry_date,
                available_expression.label("available_packs"),
            )
            .join(
                InventoryBalance,
                and_(
                    InventoryBalance.company_id
                    == ProductBatch.company_id,
                    InventoryBalance.product_variant_id
                    == ProductBatch.product_variant_id,
                    InventoryBalance.batch_id == ProductBatch.id,
                ),
            )
            .filter(
                ProductBatch.company_id == company_id,
                ProductBatch.product_variant_id
                == product_variant_id,
                ProductBatch.is_active.is_(True),
                or_(
                    ProductBatch.production_date.is_(None),
                    ProductBatch.production_date <= as_of_date,
                ),
                ProductBatch.expiry_date >= as_of_date,
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id
                == product_variant_id,
                InventoryBalance.stock_status == 'AVAILABLE',
                ~active_lock_exists,
            )
            .group_by(
                ProductBatch.id,
                ProductBatch.batch_number,
                ProductBatch.production_date,
                ProductBatch.expiry_date,
            )
            .having(available_expression > 0)
            .order_by(
                ProductBatch.expiry_date.asc(),
                ProductBatch.id.asc(),
            )
        )
    ).all()

    reason_rows = (
        await db.execute(
            select(
                OverrideReason.id,
                OverrideReason.code,
                OverrideReason.description,
            )
            .filter(
                OverrideReason.company_id == company_id,
                OverrideReason.is_active.is_(True),
            )
            .order_by(
                OverrideReason.code.asc(),
                OverrideReason.id.asc(),
            )
        )
    ).all()

    fefo_batch_id = int(batch_rows[0].id) if batch_rows else None

    return {
        "location_id": int(location_id),
        "product_variant_id": int(product_variant_id),
        "fefo_batch_id": fefo_batch_id,
        "batches": [
            {
                "id": int(row.id),
                "batch_number": str(row.batch_number),
                "production_date": row.production_date,
                "expiry_date": row.expiry_date,
                "available_packs": int(row.available_packs or 0),
                "is_fefo_head": (
                    fefo_batch_id is not None
                    and int(row.id) == fefo_batch_id
                ),
            }
            for row in batch_rows
        ],
        "reasons": [
            {
                "id": int(row.id),
                "code": str(row.code),
                "description": str(row.description),
            }
            for row in reason_rows
        ],
    }


_TRANSFER_QUERY_STATUSES = frozenset({
    'DRAFT',
    'PENDING',
    'IN_TRANSIT',
    'ACCEPTED',
    'REJECTED',
    'POSTED',
    'CANCELLED',
})


async def _serialize_transfer_headers(
    db: AsyncSession,
    *,
    company_id: int,
    headers: list[InventoryTransferHeader],
) -> list[dict]:
    if not headers:
        return []

    header_ids = [int(header.id) for header in headers]
    location_ids = sorted({
        int(location_id)
        for header in headers
        for location_id in (
            header.source_location_id,
            header.destination_location_id,
        )
    })
    actor_ids = sorted({
        int(actor_id)
        for header in headers
        for actor_id in (
            header.dispatched_by,
            header.received_by,
            header.cancelled_by,
        )
        if actor_id is not None
    })

    location_map = {
        int(row.id): str(row.name)
        for row in (
            await db.execute(
                select(
                    InventoryLocation.id,
                    InventoryLocation.name,
                ).filter(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.id.in_(location_ids),
                )
            )
        ).all()
    }
    if set(location_map) != set(location_ids):
        raise RuntimeError(
            "Transfer invariant violated: source/destination location missing."
        )

    actor_map = {}
    if actor_ids:
        actor_map = {
            int(row.id): str(row.full_name)
            for row in (
                await db.execute(
                    select(
                        Driver.id,
                        Driver.full_name,
                    ).filter(
                        Driver.company_id == company_id,
                        Driver.id.in_(actor_ids),
                    )
                )
            ).all()
        }
        if set(actor_map) != set(actor_ids):
            raise RuntimeError(
                "Transfer invariant violated: referenced actor missing."
            )

    aggregates = {
        int(header_id): (int(line_count), int(total_quantity or 0))
        for header_id, line_count, total_quantity in (
            await db.execute(
                select(
                    InventoryTransferLine.transfer_header_id,
                    func.count(InventoryTransferLine.id),
                    func.sum(InventoryTransferLine.quantity),
                ).filter(
                    InventoryTransferLine.company_id == company_id,
                    InventoryTransferLine.transfer_header_id.in_(header_ids),
                ).group_by(
                    InventoryTransferLine.transfer_header_id,
                )
            )
        ).all()
    }

    result = []
    for header in headers:
        line_count, total_quantity = aggregates.get(
            int(header.id),
            (0, 0),
        )
        result.append({
            "id": int(header.id),
            "reference_number": str(header.reference_number),
            "source_location_id": int(header.source_location_id),
            "source_location_name": location_map[int(header.source_location_id)],
            "destination_location_id": int(header.destination_location_id),
            "destination_location_name": location_map[int(header.destination_location_id)],
            "status": str(header.status),
            "dispatched_by": int(header.dispatched_by),
            "dispatched_by_name": actor_map[int(header.dispatched_by)],
            "received_by": (
                int(header.received_by)
                if header.received_by is not None
                else None
            ),
            "received_by_name": (
                actor_map[int(header.received_by)]
                if header.received_by is not None
                else None
            ),
            "cancelled_by": (
                int(header.cancelled_by)
                if header.cancelled_by is not None
                else None
            ),
            "cancelled_by_name": (
                actor_map[int(header.cancelled_by)]
                if header.cancelled_by is not None
                else None
            ),
            "line_count": line_count,
            "total_quantity": total_quantity,
            "notes": header.notes,
            "decision_reason": header.decision_reason,
            "created_at": header.created_at,
            "updated_at": header.updated_at,
            "accepted_at": header.accepted_at,
            "rejected_at": header.rejected_at,
            "cancelled_at": header.cancelled_at,
            "posted_at": header.posted_at,
        })

    return result


@router.get(
    "/warehouse/unified/transfers",
    response_model=WarehouseTransferCursorPage,
    status_code=200,
)
async def list_unified_transfers(
    status: Optional[str] = Query(default=None, max_length=50),
    location_id: Optional[int] = Query(default=None, ge=1),
    direction: str = Query(default="all", max_length=20),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    normalized_status = (status or "").strip().upper()
    normalized_direction = (direction or "all").strip().lower()
    normalized_search = (search or "").strip().lower()

    if normalized_status and normalized_status not in _TRANSFER_QUERY_STATUSES:
        raise HTTPException(
            status_code=422,
            detail="حالة الحوالة المطلوبة غير صالحة.",
        )
    if normalized_direction not in {"all", "source", "destination"}:
        raise HTTPException(
            status_code=422,
            detail="direction يجب أن يكون all/source/destination.",
        )

    if location_id is not None:
        location_exists = (
            await db.execute(
                select(InventoryLocation.id).filter(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.id == location_id,
                    InventoryLocation.location_type.in_(['WAREHOUSE', 'VEHICLE']),
                )
            )
        ).scalar_one_or_none()
        if location_exists is None:
            raise HTTPException(
                status_code=404,
                detail="الموقع غير موجود أو لا يتبع شركتك.",
            )

    scope = (
        f"transfers|{company_id}|{normalized_status}|"
        f"{location_id or 0}|{normalized_direction}|{normalized_search}"
    )

    stmt = select(InventoryTransferHeader).filter(
        InventoryTransferHeader.company_id == company_id,
        InventoryTransferHeader.workflow_type == 'TRANSIT',
    )

    if normalized_status:
        stmt = stmt.filter(
            InventoryTransferHeader.status == normalized_status,
        )

    if location_id is not None:
        if normalized_direction == "source":
            stmt = stmt.filter(
                InventoryTransferHeader.source_location_id == location_id,
            )
        elif normalized_direction == "destination":
            stmt = stmt.filter(
                InventoryTransferHeader.destination_location_id == location_id,
            )
        else:
            stmt = stmt.filter(
                or_(
                    InventoryTransferHeader.source_location_id == location_id,
                    InventoryTransferHeader.destination_location_id == location_id,
                )
            )

    if normalized_search:
        pattern = f"%{_escape_like(normalized_search)}%"
        stmt = stmt.filter(
            func.lower(InventoryTransferHeader.reference_number).like(
                pattern,
                escape="\\",
            )
        )

    total = None
    if cursor is None:
        count_stmt = select(func.count()).select_from(
            stmt.with_only_columns(
                InventoryTransferHeader.id,
                maintain_column_froms=True,
            ).order_by(None).subquery()
        )
        total = int((await db.execute(count_stmt)).scalar_one())

    if cursor is not None:
        cursor_created_at, cursor_id = _decode_transfer_cursor(
            cursor,
            expected_scope=scope,
        )
        stmt = stmt.filter(
            or_(
                InventoryTransferHeader.created_at < cursor_created_at,
                and_(
                    InventoryTransferHeader.created_at == cursor_created_at,
                    InventoryTransferHeader.id < cursor_id,
                ),
            )
        )

    rows = (
        await db.execute(
            stmt.order_by(
                InventoryTransferHeader.created_at.desc(),
                InventoryTransferHeader.id.desc(),
            ).limit(limit + 1)
        )
    ).scalars().all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = await _serialize_transfer_headers(
        db,
        company_id=company_id,
        headers=rows,
    )

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_transfer_cursor(
            last.created_at,
            last.id,
            scope=scope,
        )

    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


@router.get(
    "/warehouse/unified/transfers/{header_id}",
    response_model=WarehouseTransferDetail,
    status_code=200,
)
async def get_unified_transfer_detail(
    header_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    header = (
        await db.execute(
            select(InventoryTransferHeader).filter(
                InventoryTransferHeader.company_id == company_id,
                InventoryTransferHeader.id == header_id,
                InventoryTransferHeader.workflow_type == 'TRANSIT',
            )
        )
    ).scalar_one_or_none()

    if header is None:
        raise HTTPException(
            status_code=404,
            detail="الحوالة غير موجودة أو لا تتبع شركتك.",
        )

    serialized = await _serialize_transfer_headers(
        db,
        company_id=company_id,
        headers=[header],
    )

    line_rows = (
        await db.execute(
            select(
                InventoryTransferLine,
                ProductVariant.variant_name,
                ProductBatch.batch_number,
                ProductBatch.expiry_date,
            ).join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == InventoryTransferLine.company_id,
                    ProductVariant.id == InventoryTransferLine.product_variant_id,
                ),
            ).join(
                ProductBatch,
                and_(
                    ProductBatch.company_id == InventoryTransferLine.company_id,
                    ProductBatch.product_variant_id
                    == InventoryTransferLine.product_variant_id,
                    ProductBatch.id == InventoryTransferLine.batch_id,
                ),
            ).filter(
                InventoryTransferLine.company_id == company_id,
                InventoryTransferLine.transfer_header_id == header.id,
            ).order_by(
                InventoryTransferLine.product_variant_id.asc(),
                InventoryTransferLine.batch_id.asc(),
                InventoryTransferLine.id.asc(),
            )
        )
    ).all()

    lines = [
        {
            "id": int(line.id),
            "product_variant_id": int(line.product_variant_id),
            "product_name": str(product_name),
            "batch_id": int(line.batch_id),
            "batch_number": str(batch_number),
            "expiry_date": expiry_date,
            "quantity": int(line.quantity),
            "fefo_override_reason_id": (
                int(line.fefo_override_reason_id)
                if line.fefo_override_reason_id is not None
                else None
            ),
            "fefo_overridden_by": (
                int(line.fefo_overridden_by)
                if line.fefo_overridden_by is not None
                else None
            ),
            "fefo_override_note": line.fefo_override_note,
        }
        for line, product_name, batch_number, expiry_date in line_rows
    ]

    if not lines:
        raise RuntimeError(
            "Transfer invariant violated: transit transfer has no lines."
        )

    return {
        "transfer": serialized[0],
        "lines": lines,
    }


@router.post("/warehouse/unified/transfer/dispatch", status_code=200)
async def unified_transfer_dispatch(
    payload: UnifiedDispatchRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_TRANSFER_DISPATCH",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        await _verify_location_ownership(
            db,
            company_id,
            payload.source_location_id,
            payload.destination_location_id,
            allowed_types=['WAREHOUSE', 'VEHICLE']
        )

        requested_variant_ids = {item.product_variant_id for item in payload.items}
        valid_variant_ids = set(
            (
                await db.execute(
                    select(ProductVariant.id).filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(requested_variant_ids),
                        ProductVariant.is_active.is_(True)
                    )
                )
            ).scalars().all()
        )
        if valid_variant_ids != requested_variant_ids:
            raise HTTPException(
                status_code=400,
                detail="يوجد صنف غير صالح أو غير فعال أو لا يتبع شركتك ضمن الحوالة."
            )

        await db.execute(
            pg_insert(InventoryLocation).values(
                company_id=company_id,
                name="بضاعة في الطريق",
                code="TRANSIT-SYS",
                location_type='IN_TRANSIT',
                is_active=True
            ).on_conflict_do_nothing(index_elements=['company_id', 'code'])
        )
        transit_location_id = (
            await db.execute(
                select(InventoryLocation.id).filter_by(
                    company_id=company_id,
                    code='TRANSIT-SYS',
                    location_type='IN_TRANSIT',
                    is_active=True
                )
            )
        ).scalar_one_or_none()
        if transit_location_id is None:
            raise HTTPException(status_code=409, detail="تعذر تجهيز موقع IN_TRANSIT الخاص بالشركة.")

        await _acquire_shared_inventory_guards(
            db,
            company_id,
            payload.source_location_id,
            transit_location_id
        )

        ordered_items = sorted(
            payload.items,
            key=lambda item: (int(item.product_variant_id), int(item.override_batch_id or 0))
        )

        override_items = [item for item in ordered_items if item.is_fefo_override]
        normal_items = [item for item in ordered_items if not item.is_fefo_override]

        as_of_date = await get_company_local_date(db, company_id)

        reason_map = {}
        override_batch_pairs = set()
        if override_items:
            reason_ids = {int(item.override_reason_id) for item in override_items}
            reason_map = {
                row.id: row.description
                for row in (
                    await db.execute(
                        select(OverrideReason.id, OverrideReason.description).filter(
                            OverrideReason.company_id == company_id,
                            OverrideReason.id.in_(reason_ids),
                            OverrideReason.is_active.is_(True),
                        )
                    )
                ).all()
            }
            if set(reason_map) != reason_ids:
                raise HTTPException(status_code=400, detail="أحد أسباب تجاوز FEFO غير موجود أو غير فعال في شركتك.")

            override_batch_pairs = {
                (int(item.product_variant_id), int(item.override_batch_id))
                for item in override_items
            }
            valid_override_pairs = set(
                (
                    await db.execute(
                        select(ProductBatch.product_variant_id, ProductBatch.id).filter(
                            ProductBatch.company_id == company_id,
                            tuple_(ProductBatch.product_variant_id, ProductBatch.id).in_(sorted(override_batch_pairs)),
                            ProductBatch.is_active.is_(True),
                            or_(
                                ProductBatch.production_date.is_(None),
                                ProductBatch.production_date <= as_of_date,
                            ),
                            ProductBatch.expiry_date >= as_of_date,
                        )
                    )
                ).all()
            )
            if valid_override_pairs != override_batch_pairs:
                raise HTTPException(
                    status_code=400,
                    detail="إحدى دفعات تجاوز FEFO غير صالحة أو منتهية أو لا تتبع الصنف/الشركة."
                )

        normal_allocations = {}
        if normal_items:
            normal_allocations = await allocate_fefo_inventory_batch(
                db,
                company_id=company_id,
                location_id=payload.source_location_id,
                requests={int(item.product_variant_id): int(item.quantity) for item in normal_items},
                as_of_date=as_of_date,
                require_full=True,
            )

        override_expected = {}
        if override_items:
            override_expected = await allocate_fefo_inventory_batch(
                db,
                company_id=company_id,
                location_id=payload.source_location_id,
                requests={int(item.product_variant_id): 1 for item in override_items},
                as_of_date=as_of_date,
                require_full=False,
            )

        transfer_ref = f"TRN-{uuid.uuid4().hex.upper()}"
        header = InventoryTransferHeader(
            company_id=company_id,
            reference_number=transfer_ref,
            source_location_id=payload.source_location_id,
            destination_location_id=payload.destination_location_id,
            transit_location_id=transit_location_id,
            workflow_type='TRANSIT',
            status='IN_TRANSIT',
            dispatched_by=current_admin.id,
            notes=payload.notes or None
        )
        db.add(header)
        await db.flush()

        transfer_lines = []
        movement_specs = []
        for item in ordered_items:
            if item.is_fefo_override:
                allocations = [(int(item.override_batch_id), int(item.quantity))]
                expected_rows = override_expected.get(int(item.product_variant_id), [])
                expected_batch_id = expected_rows[0][0] if expected_rows else None
                override_reason_id = int(item.override_reason_id)
                override_actor_id = current_admin.id
                override_note = str(reason_map[override_reason_id] or "")[:255]
                db.add(SystemAuditLog(
                    company_id=company_id,
                    admin_id=current_admin.id,
                    target_id=f"Transfer_{header.id}",
                    action_type="FEFO_OVERRIDE",
                    old_value=(
                        f"Expected FEFO Batch: {expected_batch_id}"
                        if expected_batch_id is not None
                        else "Expected FEFO Batch: unavailable"
                    ),
                    new_value=f"Chosen Batch: {item.override_batch_id}, Reason ID: {item.override_reason_id}"
                ))
            else:
                allocations = normal_allocations.get(int(item.product_variant_id), [])
                override_reason_id = None
                override_actor_id = None
                override_note = None

            for batch_id, take_qty in allocations:
                transfer_lines.append(InventoryTransferLine(
                    company_id=company_id,
                    transfer_header_id=header.id,
                    product_variant_id=item.product_variant_id,
                    batch_id=batch_id,
                    quantity=take_qty,
                    fefo_override_reason_id=override_reason_id,
                    fefo_overridden_by=override_actor_id,
                    fefo_override_note=override_note
                ))
                movement_specs.append({
                    "product_variant_id": item.product_variant_id,
                    "batch_id": batch_id,
                    "quantity": take_qty,
                    "movement_kind": 'PHYSICAL',
                    "reference_type": 'TRANSFER_DISPATCH',
                    "reference_id": transfer_ref,
                    "idempotency_key": f"TRN-DISP-{header.id}-{item.product_variant_id}-{batch_id}",
                    "source_location_id": payload.source_location_id,
                    "destination_location_id": transit_location_id,
                    "source_stock_status": 'AVAILABLE',
                    "destination_stock_status": 'AVAILABLE',
                    "transfer_header_id": header.id,
                    "notes": payload.notes or None,
                })

        if not movement_specs:
            raise HTTPException(status_code=409, detail="الحوالة لم تنتج أي حركة مخزون صالحة.")

        db.add_all(transfer_lines)
        await apply_inventory_movements_batch(
            db,
            company_id=company_id,
            performed_by=current_admin.id,
            movements=movement_specs,
        )

        response_payload = {
            "message": "تم تحميل البضاعة بنجاح وهي الآن في الطريق.",
            "transfer_reference": transfer_ref,
            "header_id": header.id,
        }
        complete_idempotent_operation(
            idempotency_record,
            response_payload,
        )
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(e))
    except IntegrityError as e:
        await db.rollback()
        logger.warning(f"تعارض متزامن أثناء إنشاء الحوالة: {str(e)}", exc_info=True)
        raise HTTPException(status_code=409, detail="حدث تعارض متزامن أثناء إنشاء الحوالة. لم يتم حفظ أي جزء منها.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في إنشاء الحوالة: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء معالجة الحوالة.")


async def _load_locked_in_transit_transfer(
    db: AsyncSession,
    company_id: int,
    header_id: int,
    *,
    action_label: str
) -> InventoryTransferHeader:
    """تحميل حوالة TRANSIT لنفس الشركة وقفلها قبل تنفيذ قرار نهائي."""
    header = (
        await db.execute(
            select(InventoryTransferHeader).filter_by(
                id=header_id,
                company_id=company_id
            ).with_for_update()
        )
    ).scalar_one_or_none()

    if header is None:
        raise HTTPException(
            status_code=404,
            detail="الحوالة غير موجودة أو لا تتبع شركتك."
        )

    if header.workflow_type != 'TRANSIT' or header.status != 'IN_TRANSIT':
        raise HTTPException(
            status_code=409,
            detail=f"لا يمكن {action_label} الحوالة بحالتها الحالية ({header.status})."
        )

    if header.transit_location_id is None:
        raise HTTPException(
            status_code=409,
            detail="الحوالة لا تحمل موقع IN_TRANSIT صالحاً."
        )

    return header


def _validate_transfer_decision_reason(
    decision_reason: str,
    *,
    action_label: str
) -> str:
    reason = decision_reason.strip()
    if not reason or len(reason) > 2000:
        raise HTTPException(
            status_code=422,
            detail=f"سبب {action_label} مطلوب ويجب ألا يتجاوز 2000 حرف."
        )
    return reason


async def _move_transfer_lines_from_transit(
    db: AsyncSession,
    *,
    company_id: int,
    header: InventoryTransferHeader,
    performed_by: int,
    destination_location_id: int,
    reference_type: str,
    idempotency_prefix: str,
    notes: Optional[str]
) -> None:
    """ترحيل جميع أسطر حوالة واحدة من IN_TRANSIT إلى موقع نهائي بترتيب ثابت."""
    transit_location_id = int(header.transit_location_id)

    await _verify_location_ownership(
        db,
        company_id,
        transit_location_id,
        allowed_types=['IN_TRANSIT']
    )
    await _verify_location_ownership(
        db,
        company_id,
        destination_location_id,
        allowed_types=['WAREHOUSE', 'VEHICLE']
    )

    await _acquire_shared_inventory_guards(
        db,
        company_id,
        transit_location_id,
        destination_location_id
    )

    lines = (
        await db.execute(
            select(InventoryTransferLine).filter_by(
                company_id=company_id,
                transfer_header_id=header.id
            ).order_by(
                InventoryTransferLine.product_variant_id.asc(),
                InventoryTransferLine.batch_id.asc(),
                InventoryTransferLine.id.asc()
            )
        )
    ).scalars().all()

    if not lines:
        raise HTTPException(
            status_code=409,
            detail="الحوالة لا تحتوي على أسطر مخزون صالحة."
        )

    movement_specs = [
        {
            "product_variant_id": line.product_variant_id,
            "batch_id": line.batch_id,
            "quantity": line.quantity,
            "movement_kind": 'PHYSICAL',
            "reference_type": reference_type,
            "reference_id": header.reference_number,
            "idempotency_key": f"{idempotency_prefix}-{header.id}-{line.id}",
            "source_location_id": transit_location_id,
            "destination_location_id": destination_location_id,
            "source_stock_status": 'AVAILABLE',
            "destination_stock_status": 'AVAILABLE',
            "transfer_header_id": header.id,
            "notes": notes,
        }
        for line in lines
    ]
    await apply_inventory_movements_batch(
        db,
        company_id=company_id,
        performed_by=performed_by,
        movements=movement_specs,
    )


@router.post("/warehouse/unified/transfer/receive", status_code=200)
async def unified_transfer_receive(
    payload: UnifiedReceiveRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_TRANSFER_RECEIVE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        header = await _load_locked_in_transit_transfer(
            db,
            company_id,
            payload.transfer_header_id,
            action_label="استلام"
        )

        if header.destination_location_id != payload.destination_location_id:
            raise HTTPException(
                status_code=409,
                detail="الوجهة المرسلة لا تطابق الوجهة الأصلية للحوالة."
            )

        if header.dispatched_by == current_admin.id:
            raise HTTPException(
                status_code=403,
                detail="مرفوض رقابياً: لا يمكن للمُرسل تأكيد استلام نفس الحوالة."
            )

        await _move_transfer_lines_from_transit(
            db,
            company_id=company_id,
            header=header,
            performed_by=current_admin.id,
            destination_location_id=payload.destination_location_id,
            reference_type='TRANSFER_RECEIPT',
            idempotency_prefix='TRN-REC',
            notes=header.notes
        )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        header.received_by = current_admin.id
        header.accepted_at = now_utc
        header.posted_at = now_utc
        header.updated_at = now_utc
        header.status = 'POSTED'

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Transfer_{header.id}",
            action_type="TRANSFER_RECEIVED",
            old_value="IN_TRANSIT",
            new_value=f"POSTED by Admin {current_admin.id}"
        ))

        response_payload = {
            "message": "تم تأكيد الاستلام وترحيل الحوالة بنجاح.",
            "header_id": int(header.id),
            "transfer_reference": str(header.reference_number),
            "status": "POSTED",
        }
        complete_idempotent_operation(
            idempotency_record,
            response_payload,
        )
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(e))
    except IntegrityError as e:
        await db.rollback()
        logger.warning(
            f"تعارض متزامن أثناء استلام الحوالة: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=409,
            detail="حدث تعارض متزامن أثناء الاستلام. لم يتم حفظ عملية جزئية."
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"خطأ في استلام الحوالة: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء استلام الحوالة."
        )


@router.post("/warehouse/unified/transfer/{header_id}/cancel", status_code=200)
async def unified_transfer_cancel(
    header_id: int,
    payload: UnifiedTransferDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    reason = _validate_transfer_decision_reason(
        payload.decision_reason,
        action_label="الإلغاء"
    )

    try:
        request_hash = _stable_request_hash(
            payload,
            context={"transfer_header_id": int(header_id)},
        )
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_TRANSFER_CANCEL",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        header = await _load_locked_in_transit_transfer(
            db,
            company_id,
            header_id,
            action_label="إلغاء"
        )

        await _move_transfer_lines_from_transit(
            db,
            company_id=company_id,
            header=header,
            performed_by=current_admin.id,
            destination_location_id=header.source_location_id,
            reference_type='TRANSFER_CANCELLED',
            idempotency_prefix='TRN-CANC',
            notes=reason
        )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        header.status = 'CANCELLED'
        header.cancelled_by = current_admin.id
        header.cancelled_at = now_utc
        header.decision_reason = reason
        header.updated_at = now_utc

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Transfer_{header.id}",
            action_type="TRANSFER_CANCELLED",
            old_value="IN_TRANSIT",
            new_value=reason
        ))

        response_payload = {
            "message": "تم إلغاء الحوالة وإرجاع البضاعة للمصدر بنجاح.",
            "header_id": int(header.id),
            "transfer_reference": str(header.reference_number),
            "status": "CANCELLED",
        }
        complete_idempotent_operation(
            idempotency_record,
            response_payload,
        )
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(e))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="حدث تعارض متزامن أثناء إلغاء الحوالة. لم يتم حفظ عملية جزئية."
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"خطأ في إلغاء الحوالة: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء إلغاء الحوالة."
        )


@router.post("/warehouse/unified/transfer/{header_id}/reject", status_code=200)
async def unified_transfer_reject(
    header_id: int,
    payload: UnifiedTransferDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id
    reason = _validate_transfer_decision_reason(
        payload.decision_reason,
        action_label="الرفض"
    )

    try:
        request_hash = _stable_request_hash(
            payload,
            context={"transfer_header_id": int(header_id)},
        )
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="WAREHOUSE_TRANSFER_REJECT",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        header = await _load_locked_in_transit_transfer(
            db,
            company_id,
            header_id,
            action_label="رفض"
        )

        if header.dispatched_by == current_admin.id:
            raise HTTPException(
                status_code=403,
                detail="مرفوض رقابياً: لا يمكن للمُرسل رفض نفس الحوالة بصفته مستلماً."
            )

        await _verify_location_ownership(
            db,
            company_id,
            header.destination_location_id,
            allowed_types=['WAREHOUSE', 'VEHICLE']
        )

        await _move_transfer_lines_from_transit(
            db,
            company_id=company_id,
            header=header,
            performed_by=current_admin.id,
            destination_location_id=header.source_location_id,
            reference_type='TRANSFER_REJECTED',
            idempotency_prefix='TRN-REJ',
            notes=reason
        )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        header.status = 'REJECTED'
        header.received_by = current_admin.id
        header.rejected_at = now_utc
        header.decision_reason = reason
        header.updated_at = now_utc

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Transfer_{header.id}",
            action_type="TRANSFER_REJECTED",
            old_value="IN_TRANSIT",
            new_value=reason
        ))

        response_payload = {
            "message": "تم رفض الحوالة وإرجاع البضاعة لعهدة المصدر.",
            "header_id": int(header.id),
            "transfer_reference": str(header.reference_number),
            "status": "REJECTED",
        }
        complete_idempotent_operation(
            idempotency_record,
            response_payload,
        )
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(e))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="حدث تعارض متزامن أثناء رفض الحوالة. لم يتم حفظ عملية جزئية."
        )
    except Exception as e:
        await db.rollback()
        logger.error(
            f"خطأ في رفض الحوالة: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء رفض الحوالة."
        )


# =================================================================================
# [المرحلة السادسة] محرك الجرد القانوني (Stocktake Engine)
# =================================================================================

_STOCKTAKE_ACTIVE_STATUSES = ('DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED')
_MAX_STOCKTAKE_LINES = 10_000


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


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


async def _probe_stocktake_location_id(db: AsyncSession, company_id: int, session_id: int) -> int:
    location_id = (
        await db.execute(
            select(StocktakeSession.location_id).filter_by(id=session_id, company_id=company_id)
        )
    ).scalar_one_or_none()
    if location_id is None:
        raise HTTPException(status_code=404, detail="جلسة الجرد غير موجودة أو لا تتبع شركتك.")
    return int(location_id)


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


def _stocktake_cycle_batch_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


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
    current_admin: Driver = Depends(get_current_admin),
):
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
        InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),
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


_ACTIVE_STOCKTAKE_STATUSES = frozenset({
    "DRAFT",
    "COUNTING",
    "PENDING_REVIEW",
    "RECOUNT_REQUIRED",
    "APPROVED",
})


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
    current_admin: Driver = Depends(get_current_admin),
):
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
            ProductVariant.variant_name.label("scope_product_name"),
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


@router.post("/warehouse/unified/stocktake/start", status_code=201)
async def start_unified_stocktake(
    payload: UnifiedStocktakeStartRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    """فتح الجلسة وأخذ Snapshot ثابت وإنشاء Lock مطابق للنطاق."""
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
            InventoryBalance.stock_status.in_(['AVAILABLE', 'DAMAGED']),
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
                expected_quantity=int(balance.on_hand_quantity),
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
@router.get("/warehouse/unified/stocktake/{session_id}/count-sheet", status_code=200)
async def get_stocktake_count_sheet(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
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
                ProductVariant.variant_name,
                ProductVariant.packs_per_carton,
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
                ProductVariant.variant_name.asc(),
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
        "packs_per_carton": int(packs_per_carton or 1),
        "batch_number": batch_number,
        "expiry_date": expiry_date.isoformat(),
    } for line, product_name, packs_per_carton, batch_number, expiry_date in rows]


@router.post("/warehouse/unified/stocktake/{session_id}/count", status_code=200)
async def submit_stocktake_count(
    session_id: int,
    payload: UnifiedStocktakeCountRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    """Attempt immutable + DISCOVERED lines معروفة في ProductBatch."""
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

        submitted_map = {
            (item.product_variant_id, item.batch_id, item.stock_status): int(item.actual_quantity)
            for item in payload.items
        }
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
                        ProductVariant.is_active,
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
                    variant_is_active,
                )
                for (
                    batch_id,
                    product_variant_id,
                    production_date,
                    expiry_date,
                    batch_is_active,
                    variant_is_active,
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
                    variant_is_active,
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
                    if not batch_is_active or not variant_is_active:
                        raise HTTPException(
                            status_code=422,
                            detail="DISCOVERED بحالة AVAILABLE يتطلب صنفاً ودفعة فعالين.",
                        )

                    if expiry_date < as_of_date:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                "الدفعة المنتهية لا يجوز تسجيلها DISCOVERED "
                                "بحالة AVAILABLE؛ استخدم DAMAGED."
                            ),
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
            expected_quantity = int(line.expected_quantity)
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
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في تثبيت الجرد: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تثبيت محاولة الجرد.")


@router.get("/warehouse/unified/stocktake/{session_id}/review", status_code=200)
async def get_stocktake_review(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
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
                ProductVariant.variant_name,
                ProductVariant.packs_per_carton,
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
                ProductVariant.variant_name.asc(),
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
            "packs_per_carton": int(packs_per_carton or 1),
            "batch_number": batch_number,
            "expiry_date": expiry_date.isoformat(),
            "expected_quantity": attempt_line.expected_quantity,
            "actual_quantity": attempt_line.actual_quantity,
            "variance_quantity": attempt_line.variance_quantity,
            "notes": attempt_line.notes,
        } for attempt_line, stocktake_line, product_name, packs_per_carton, batch_number, expiry_date in rows],
    }


@router.post("/warehouse/unified/stocktake/{session_id}/approve", status_code=200)
async def approve_stocktake_session(
    session_id: int,
    payload: StocktakeApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    """Optimistic approval ثم posting حصراً عبر post_approved_stocktake_adjustments."""
    company_id = current_admin.company_id
    if not current_admin.is_admin:
        raise HTTPException(status_code=403, detail="اعتماد الجرد يتطلب صلاحية مشرف.")

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


@router.post("/warehouse/unified/stocktake/{session_id}/recount", status_code=200)
async def recount_stocktake_session(
    session_id: int,
    payload: StocktakeRecountRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    """تفويض Recount مرتبط بمحاولة العد التي شاهدها المشرف."""
    company_id = current_admin.company_id
    if not current_admin.is_admin:
        raise HTTPException(status_code=403, detail="تفويض إعادة العد يتطلب صلاحية مشرف.")

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


@router.post("/warehouse/unified/stocktake/{session_id}/cancel", status_code=200)
async def cancel_stocktake_session(
    session_id: int,
    payload: StocktakeCancelRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    """إلغاء موثق مع تحرير كامل Metadata للقفل."""
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
