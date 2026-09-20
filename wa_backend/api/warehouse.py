from datetime import timezone, date, datetime
from decimal import Decimal
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Integer, and_, any_, bindparam, case, func, or_, select, tuple_, union, update
from typing import Optional, List
from database import get_db
from api.dependencies import get_current_driver
from inventory_access import (InventoryAccess, require_stocktake, require_transfer,
                              transfer_filter, require_inbound_adjustment)
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
    acquire_inventory_location_guards,
    ensure_system_transit_location,
    inventory_business_error,
    warehouse_setup_required_detail,
    TRANSFER_DESTINATION_POLICY_CODE,
    SPECIAL_TRANSFER_PURPOSES,
    SPECIAL_TRANSFER_PERMISSION,
    resolve_special_transfer_direction_context,
    validate_special_transfer_source_items_locked,
    validate_special_transfer_policy_snapshot,
    resolve_special_transfer_terminal_statuses,
    resolve_retiring_warehouse_balancing_override_context,
    save_transfer_destination_policy_draft,
    publish_transfer_destination_policy,
    get_transfer_destination_policy_state,
    apply_inventory_movement,
    apply_inventory_movements_batch,
    post_approved_stocktake_adjustments,
    allocate_fefo_inventory_batch,
    batch_sellability_predicate,
    resolve_inflight_transfer_destination_statuses,
    get_company_local_date,
    validate_vehicle_recon_work_session,
    begin_idempotent_operation,
    complete_idempotent_operation,
    InventoryMutationError,
    InventoryRuleError,
    change_product_batch_disposition,
)
from models import (Company, Driver, Product, ProductVariant, ProductLocation, ProductUomConversion, Branch,
DispatchRoute, SystemAuditLog,
InventoryLocation, TenantOperationalPolicy, InventoryStockPolicy, InventoryBalance, InventoryMovement, InventoryMovementImpact, ProductBatch,
InventoryLiveStockCompanySummary, InventoryLiveStockWarehouseSummary, InventoryLiveStockProjection,
InventoryCostEvent, InventoryCostState,
InventoryTransferHeader, InventoryTransferLine, OverrideReason, SystemSetting,
WorkSession, StocktakeSession, StocktakeLine, StocktakeCountAttempt, StocktakeCountAttemptLine, InventoryLock)
from models import UOM
from quantity import QuantityError, canonical_quantity, validate_variant_quantity
from domains.inventory_costing.service import (
    CostingError,
    activate_costing_for_first_receipt,
    build_purchase_cost_input,
    cost_policy_payload,
    set_cost_policy,
)
from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    assert_live_stock_projection_ready,
    rebuild_live_stock_warehouse,
    remove_live_stock_warehouse_projection,
)

from product_lifecycle import (
    DEFAULT_PRODUCT_LOCATION_FLAGS,
    INBOUND_NEW,
    REPLENISHMENT_NEW,
    WAREHOUSE_BALANCING,
    acquire_product_lifecycle_guards,
    evaluate_product_capability,
    product_capability_predicate,
    product_location_allows,
    record_domain_event,
)

from schemas import (UnifiedStocktakeStartRequest,
WarehouseInventoryItem, WarehouseInventoryCursorPage, WarehouseInventoryAlertSummaryResponse, WarehouseInventorySummaryResponse, WarehouseInventoryBatchDetailResponse, WarehouseLedgerItem, WarehouseLedgerCursorPage,
WarehouseStatusResponse, WarehouseLocationCreateRequest, WarehouseLocationUpdateRequest,
WarehouseLocationStateRequest, WarehouseLocationCursorPage, WarehouseLocationMutationResponse,
WarehouseSetupStatusResponse,
MessageResponse, AdjustWarehouseEntryRequest, UpgradedInboundRequest, InboundOptionsRequest, InventoryCostPolicyUpdateRequest, UnifiedDispatchRequest, UnifiedReceiveRequest,
UnifiedTransferDecisionRequest, WarehouseTransferCursorPage, WarehouseTransferDetail,
UnifiedTransferLocationItem, UnifiedTransferSourceInventoryCursorPage,
UnifiedTransferOverrideOptionsResponse,
StocktakeActiveSessionCursorPage,
StocktakeCycleBatchCursorPage,
StocktakeSessionContextResponse,
VehicleReconCandidateCursorPage,
UnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest,
BatchDispositionChangeRequest, BatchDispositionMutationResponse,
InventoryStatusChangeRequest, InventoryStatusChangeResponse,
TransferDestinationPolicySaveRequest, TransferDestinationPolicyPublishRequest,
TransferDestinationPolicyMutationResponse, TransferDestinationPolicyStateResponse,
SpecialTransferDispatchRequest, SpecialTransferDispatchResponse )

router = APIRouter()

# PATCH: STAGE4C_SYNCHRONOUS_BATCH_ELIGIBILITY

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


# =================================================================================
# 1. استلام بضاعة من المورد (Inbound) - المحرك الموحد
# =================================================================================
async def _require_active_warehouse_setup(
    db: AsyncSession,
    company_id: int,
) -> None:
    active_id = (
        await db.execute(
            select(InventoryLocation.id).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.location_type == 'WAREHOUSE',
                InventoryLocation.is_active.is_(True),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if active_id is None:
        raise HTTPException(status_code=409, detail=warehouse_setup_required_detail())


async def _resolve_inbound_uom_options(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: list[int],
) -> tuple[dict[int, int], dict[tuple[int, int], Decimal], dict[int, UOM]]:
    ids = sorted({int(value) for value in variant_ids})
    if not ids:
        return {}, {}, {}

    variant_rows = (
        await db.execute(
            select(ProductVariant.id, ProductVariant.base_uom_id).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(ids),
                ProductVariant.lifecycle_status == "ACTIVE",
            )
        )
    ).all()
    base_by_variant = {
        int(row.id): int(row.base_uom_id)
        for row in variant_rows
    }
    if set(base_by_variant) != set(ids):
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INBOUND_VARIANT_UNAVAILABLE",
                "One or more products are not active or do not belong to the company.",
            ),
        )

    conversion_rows = (
        await db.execute(
            select(ProductUomConversion).filter(
                ProductUomConversion.company_id == company_id,
                ProductUomConversion.product_variant_id.in_(ids),
            )
        )
    ).scalars().all()

    factors: dict[tuple[int, int], Decimal] = {
        (variant_id, base_uom_id): Decimal("1")
        for variant_id, base_uom_id in base_by_variant.items()
    }
    uom_ids = set(base_by_variant.values())
    for conversion in conversion_rows:
        variant_id = int(conversion.product_variant_id)
        base_uom_id = base_by_variant[variant_id]
        numerator = Decimal(conversion.numerator)
        denominator = Decimal(conversion.denominator)
        if numerator <= 0 or denominator <= 0:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "INBOUND_UOM_CONVERSION_INVALID",
                    "A product unit conversion is invalid.",
                    context={"product_variant_id": variant_id},
                ),
            )

        candidate_uom_id = None
        factor = None
        if int(conversion.to_uom_id) == base_uom_id:
            candidate_uom_id = int(conversion.from_uom_id)
            factor = numerator / denominator
        elif int(conversion.from_uom_id) == base_uom_id:
            candidate_uom_id = int(conversion.to_uom_id)
            factor = denominator / numerator
        if candidate_uom_id is None or factor is None:
            continue

        key = (variant_id, candidate_uom_id)
        existing = factors.get(key)
        if existing is not None and existing != factor:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "INBOUND_UOM_CONVERSION_CONFLICT",
                    "Conflicting direct unit conversions were found for a product.",
                    context={
                        "product_variant_id": variant_id,
                        "uom_id": candidate_uom_id,
                    },
                ),
            )
        factors[key] = factor
        uom_ids.add(candidate_uom_id)

    uoms = list(
        (
            await db.scalars(
                select(UOM).where(UOM.id.in_(sorted(uom_ids))).order_by(UOM.id.asc())
            )
        ).all()
    )
    uom_map = {int(row.id): row for row in uoms}
    if set(uom_map) != uom_ids:
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INBOUND_UOM_REFERENCE_MISSING",
                "A unit reference required by the product is missing.",
            ),
        )
    return base_by_variant, factors, uom_map


async def _ensure_first_inbound_product_locations(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    variant_ids,
    actor_id: int,
    request_id: uuid.UUID,
) -> set[int]:
    """Create only missing product/location assignments for the selected inbound warehouse.

    The caller must already have validated exact-warehouse inbound permission and
    company-scoped product lifecycle eligibility. Existing assignments are never
    overwritten, so explicit inbound/outbound flags remain authoritative.
    """
    normalized_ids = sorted({int(value) for value in variant_ids})
    if not normalized_ids:
        return set()

    rows = [
        {
            "company_id": int(company_id),
            "location_id": int(location_id),
            "product_variant_id": int(variant_id),
            "operational_flags": dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
            "created_by": int(actor_id),
        }
        for variant_id in normalized_ids
    ]
    created_rows = list(
        (
            await db.execute(
                pg_insert(ProductLocation)
                .values(rows)
                .on_conflict_do_nothing(
                    constraint="uq_product_location_assignment"
                )
                .returning(
                    ProductLocation.id,
                    ProductLocation.product_variant_id,
                )
            )
        ).all()
    )

    for product_location_id, product_variant_id in created_rows:
        snapshot = {
            "id": int(product_location_id),
            "company_id": int(company_id),
            "location_id": int(location_id),
            "product_variant_id": int(product_variant_id),
            "operational_flags": dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
            "version": 1,
            "created_by": int(actor_id),
        }
        record_domain_event(
            db,
            company_id=int(company_id),
            actor_id=int(actor_id),
            request_id=request_id,
            event_type="ProductLocationAssigned",
            entity_type="ProductLocation",
            entity_id=int(product_location_id),
            reason="AUTO_FIRST_INBOUND",
            before=None,
            after=snapshot,
        )

    return {
        int(product_variant_id)
        for _, product_variant_id in created_rows
    }


async def _load_inventory_display_uoms(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: list[int] | set[int],
) -> dict[int, dict]:
    ids = sorted({int(value) for value in variant_ids})
    if not ids:
        return {}

    rows = (
        await db.execute(
            select(ProductUomConversion, UOM)
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == ProductUomConversion.company_id,
                    ProductVariant.id == ProductUomConversion.product_variant_id,
                ),
            )
            .join(UOM, UOM.id == ProductUomConversion.from_uom_id)
            .filter(
                ProductUomConversion.company_id == int(company_id),
                _warehouse_array_membership(
                    ProductUomConversion.product_variant_id,
                    ids,
                    "inventory_display_uom_variant_ids",
                ),
                ProductUomConversion.to_uom_id == ProductVariant.base_uom_id,
            )
            .order_by(
                ProductUomConversion.product_variant_id.asc(),
                ProductUomConversion.id.asc(),
            )
        )
    ).all()

    candidates: dict[int, list[dict]] = {}
    for conversion, uom in rows:
        numerator = Decimal(conversion.numerator)
        denominator = Decimal(conversion.denominator)
        if numerator <= 0 or denominator <= 0:
            raise RuntimeError("Invalid product UOM conversion.")
        factor = numerator / denominator
        if factor <= 1:
            continue
        candidates.setdefault(int(conversion.product_variant_id), []).append({
            "uom_id": int(uom.id),
            "uom_code": str(uom.code),
            "uom_name": str(uom.name),
            "factor_to_base": factor,
        })

    # Never guess between multiple commercial units.  One exact direct conversion
    # is safe to use as the default display; otherwise the caller falls back to base.
    return {
        variant_id: rows[0]
        for variant_id, rows in candidates.items()
        if len(rows) == 1
    }


async def _ledger_product_location_snapshots(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    product_variant_ids: list[int] | set[int],
    movement_ids: list[int],
) -> dict[int, tuple[Decimal, Decimal]]:
    variant_ids = sorted({int(value) for value in product_variant_ids})
    page_movement_ids = sorted({int(value) for value in movement_ids})
    if not variant_ids or not page_movement_ids:
        return {}

    movement_delta_subq = (
        select(
            InventoryMovement.id.label("movement_id"),
            InventoryMovement.product_variant_id.label("product_variant_id"),
            InventoryMovement.created_at.label("created_at"),
            func.sum(
                InventoryMovementImpact.on_hand_after
                - InventoryMovementImpact.on_hand_before
            ).label("location_delta"),
        )
        .join(
            InventoryMovementImpact,
            and_(
                InventoryMovementImpact.company_id == InventoryMovement.company_id,
                InventoryMovementImpact.movement_id == InventoryMovement.id,
            ),
        )
        .join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id == InventoryMovementImpact.company_id,
                InventoryBalance.id == InventoryMovementImpact.inventory_balance_id,
            ),
        )
        .filter(
            InventoryMovement.company_id == int(company_id),
            InventoryMovement.product_variant_id.in_(variant_ids),
            InventoryMovementImpact.company_id == int(company_id),
            InventoryBalance.company_id == int(company_id),
            InventoryBalance.location_id == int(location_id),
        )
        .group_by(
            InventoryMovement.id,
            InventoryMovement.product_variant_id,
            InventoryMovement.created_at,
        )
        .subquery()
    )

    history_subq = (
        select(
            movement_delta_subq.c.movement_id,
            movement_delta_subq.c.product_variant_id,
            movement_delta_subq.c.location_delta,
            func.sum(movement_delta_subq.c.location_delta)
            .over(
                partition_by=movement_delta_subq.c.product_variant_id,
                order_by=(
                    movement_delta_subq.c.created_at.asc(),
                    movement_delta_subq.c.movement_id.asc(),
                ),
                rows=(None, 0),
            )
            .label("cumulative_delta"),
            func.sum(movement_delta_subq.c.location_delta)
            .over(partition_by=movement_delta_subq.c.product_variant_id)
            .label("total_delta"),
        )
        .subquery()
    )

    current_balance_subq = (
        select(
            InventoryBalance.product_variant_id.label("product_variant_id"),
            func.sum(InventoryBalance.on_hand_quantity).label("current_total"),
        )
        .filter(
            InventoryBalance.company_id == int(company_id),
            InventoryBalance.location_id == int(location_id),
            InventoryBalance.product_variant_id.in_(variant_ids),
        )
        .group_by(InventoryBalance.product_variant_id)
        .subquery()
    )

    snapshot_rows = (
        await db.execute(
            select(
                history_subq.c.movement_id,
                history_subq.c.location_delta,
                history_subq.c.cumulative_delta,
                history_subq.c.total_delta,
                func.coalesce(current_balance_subq.c.current_total, 0).label(
                    "current_total"
                ),
            )
            .outerjoin(
                current_balance_subq,
                current_balance_subq.c.product_variant_id
                == history_subq.c.product_variant_id,
            )
            .filter(history_subq.c.movement_id.in_(page_movement_ids))
        )
    ).all()

    result: dict[int, tuple[Decimal, Decimal]] = {}
    for row in snapshot_rows:
        delta = Decimal(row.location_delta or 0)
        cumulative = Decimal(row.cumulative_delta or 0)
        total_delta = Decimal(row.total_delta or 0)
        current_total = Decimal(row.current_total or 0)
        opening_total = current_total - total_delta
        after = opening_total + cumulative
        before = after - delta
        if before < 0 or after < 0:
            raise RuntimeError(
                "Ledger product/location balance reconstruction became negative."
            )
        result[int(row.movement_id)] = (before, after)
    return result


@router.post("/warehouse/inbound/options", status_code=200)
async def warehouse_inbound_options(
    payload: InboundOptionsRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('inbound.create', any_location=True)
    company_id = current_admin.company_id

    base_by_variant, factors, uom_map = await _resolve_inbound_uom_options(
        db,
        company_id=company_id,
        variant_ids=payload.ids,
    )
    company = await db.scalar(
        select(Company).where(Company.id == company_id)
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company was not found.")

    items = []
    for variant_id in sorted(base_by_variant):
        base_uom_id = base_by_variant[variant_id]
        option_rows = []
        for (candidate_variant_id, uom_id), factor in sorted(factors.items()):
            if candidate_variant_id != variant_id:
                continue
            uom = uom_map[uom_id]
            option_rows.append({
                "id": int(uom.id),
                "code": str(uom.code),
                "name": str(uom.name),
                "factor_to_base": canonical_quantity(factor),
            })
        option_rows.sort(
            key=lambda row: (
                0 if int(row["id"]) == base_uom_id else 1,
                str(row["code"]),
                int(row["id"]),
            )
        )
        items.append({
            "product_variant_id": variant_id,
            "base_uom_id": base_uom_id,
            "uoms": option_rows,
        })

    return {
        "currency_code": str(company.currency_code).upper(),
        "items": items,
    }


@router.get("/warehouse/costing-policy", status_code=200)
async def warehouse_costing_policy(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('inbound.create', any_location=True)
    can_change = bool(
        await db.scalar(select(access.allows('inventory.costing.manage')))
    )
    try:
        return await cost_policy_payload(
            db,
            company_id=current_admin.company_id,
            can_change=can_change,
        )
    except CostingError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc


@router.put("/warehouse/costing-policy", status_code=200)
async def update_warehouse_costing_policy(
    payload: InventoryCostPolicyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('inventory.costing.manage')
    company_id = current_admin.company_id
    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="INVENTORY_COST_POLICY_UPDATE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        await set_cost_policy(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            method=payload.method,
            expected_version=payload.expected_version,
        )
        response_payload = await cost_policy_payload(
            db,
            company_id=company_id,
            can_change=True,
        )
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload
    except CostingError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/warehouse/inbound", response_model=MessageResponse, status_code=201)
async def warehouse_inbound(
    payload: UpgradedInboundRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await access.require('inbound.create', any_location=True)

    company_id = current_admin.company_id
    await _require_active_warehouse_setup(db, company_id)
    await access.require('inbound.create', payload.location_id)

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
            raise HTTPException(status_code=400, detail="No inbound items were supplied.")

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
                    detail=inventory_business_error(
                        "INBOUND_REFERENCE_DUPLICATE",
                        "The supplier reference was already posted.",
                        context={"reference_id": reference_id},
                    ),
                )

        main_loc = (
            await db.execute(
                select(InventoryLocation).filter_by(
                    id=payload.location_id,
                    company_id=company_id,
                    location_type='WAREHOUSE',
                    is_system_managed=False,
                    is_active=True
                )
            )
        ).scalar_one_or_none()
        if main_loc is None:
            raise HTTPException(
                status_code=404,
                detail=inventory_business_error(
                    "INBOUND_WAREHOUSE_UNAVAILABLE",
                    "The selected warehouse is unavailable.",
                ),
            )

        requested_var_ids = {item.product_variant_id for item in payload.items}
        await acquire_product_lifecycle_guards(
            db, company_id, requested_var_ids, exclusive=False,
        )
        variant_rows = (
            await db.execute(
                select(
                    ProductVariant.id,
                    ProductVariant.base_uom_id,
                    ProductVariant.quantity_scale,
                    ProductVariant.quantity_step,
                    ProductVariant.expiry_control_mode,
                    ProductVariant.lifecycle_status,
                    ProductVariant.operational_hold,
                    ProductLocation.operational_flags,
                ).outerjoin(
                    ProductLocation,
                    and_(
                        ProductLocation.company_id == ProductVariant.company_id,
                        ProductLocation.product_variant_id == ProductVariant.id,
                        ProductLocation.location_id == payload.location_id,
                    ),
                ).filter(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(requested_var_ids),
                )
            )
        ).all()
        found_variant_ids = {int(row.id) for row in variant_rows}
        if found_variant_ids != requested_var_ids:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "INBOUND_VARIANT_UNAVAILABLE",
                    "One or more products are unavailable for inbound.",
                    context={
                        "missing_product_variant_ids": sorted(
                            requested_var_ids - found_variant_ids
                        ),
                    },
                ),
            )

        missing_location_variant_ids = sorted(
            int(row.id)
            for row in variant_rows
            if row.operational_flags is None
        )
        if missing_location_variant_ids:
            await _ensure_first_inbound_product_locations(
                db,
                company_id=company_id,
                location_id=payload.location_id,
                variant_ids=missing_location_variant_ids,
                actor_id=current_admin.id,
                request_id=payload.request_id,
            )

        variant_rules = {}
        for row in variant_rows:
            decision = evaluate_product_capability(
                row.lifecycle_status,
                row.operational_hold,
                INBOUND_NEW,
            )
            if not decision.allowed:
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        decision.code,
                        "The product state does not allow inbound stock.",
                        context={"product_variant_id": int(row.id)},
                    ),
                )
            if (
                row.operational_flags is not None
                and not product_location_allows(
                    row.operational_flags,
                    INBOUND_NEW,
                )
            ):
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "PRODUCT_LOCATION_INBOUND_DISABLED",
                        "Inbound is disabled for this product at the selected warehouse.",
                        context={
                            "product_variant_id": int(row.id),
                            "location_id": payload.location_id,
                        },
                    ),
                )
            variant_rules[int(row.id)] = {
                "base_uom_id": int(row.base_uom_id),
                "quantity_scale": int(row.quantity_scale),
                "quantity_step": row.quantity_step,
                "expiry_control_mode": str(row.expiry_control_mode),
            }

        _, uom_factors, _ = await _resolve_inbound_uom_options(
            db,
            company_id=company_id,
            variant_ids=sorted(requested_var_ids),
        )
        as_of_date = await get_company_local_date(db, company_id)
        requested_batches: dict[
            tuple[int, str],
            tuple[Optional[date], Optional[date]],
        ] = {}
        inbound_lines: list[dict] = []
        seen_batch_uoms: set[tuple[int, str, int]] = set()

        for item in payload.items:
            batch_key = (int(item.product_variant_id), str(item.batch_number))
            metadata = (item.production_date, item.expiry_date)
            if batch_key in requested_batches and requested_batches[batch_key] != metadata:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_BATCH_METADATA_CONFLICT",
                        "The same product batch cannot carry conflicting dates in one receipt.",
                        context={
                            "product_variant_id": int(item.product_variant_id),
                            "batch_number": str(item.batch_number),
                        },
                    ),
                )

            line_key = (
                int(item.product_variant_id),
                str(item.batch_number),
                int(item.uom_id),
            )
            if line_key in seen_batch_uoms:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_DUPLICATE_BATCH_UOM_LINE",
                        "The same product, batch and purchasing unit may appear only once per receipt.",
                        context={
                            "product_variant_id": int(item.product_variant_id),
                            "batch_number": str(item.batch_number),
                            "uom_id": int(item.uom_id),
                        },
                    ),
                )
            seen_batch_uoms.add(line_key)

            factor = uom_factors.get(
                (int(item.product_variant_id), int(item.uom_id))
            )
            if factor is None:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_UOM_UNSUPPORTED",
                        "The selected purchasing unit has no direct exact conversion to the base unit.",
                        context={
                            "product_variant_id": int(item.product_variant_id),
                            "uom_id": int(item.uom_id),
                        },
                    ),
                )
            raw_base_quantity = Decimal(item.quantity) * Decimal(factor)
            try:
                base_quantity = validate_variant_quantity(
                    raw_base_quantity,
                    quantity_scale=variant_rules[item.product_variant_id]["quantity_scale"],
                    quantity_step=variant_rules[item.product_variant_id]["quantity_step"],
                    field_name="quantity",
                )
            except QuantityError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_QUANTITY_CONVERSION_INVALID",
                        "The purchased quantity cannot be represented exactly in the product base unit.",
                        context={"product_variant_id": int(item.product_variant_id)},
                    ),
                ) from exc

            expiry_mode = variant_rules[item.product_variant_id]["expiry_control_mode"]
            if expiry_mode == 'REQUIRED' and item.expiry_date is None:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_EXPIRY_REQUIRED",
                        "Expiry date is required for this product.",
                        context={"product_variant_id": int(item.product_variant_id)},
                    ),
                )
            if expiry_mode == 'NONE' and item.expiry_date is not None:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_EXPIRY_NOT_ALLOWED",
                        "This product does not use expiry tracking.",
                        context={"product_variant_id": int(item.product_variant_id)},
                    ),
                )
            if item.expiry_date is not None and item.expiry_date < as_of_date:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_BATCH_EXPIRED",
                        "Expired stock cannot be received as available inventory.",
                        context={"batch_number": str(item.batch_number)},
                    ),
                )
            if item.production_date is not None and item.production_date > as_of_date:
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_PRODUCTION_DATE_FUTURE",
                        "Production date cannot be in the future.",
                        context={"batch_number": str(item.batch_number)},
                    ),
                )
            if (
                item.production_date is not None
                and item.expiry_date is not None
                and item.production_date > item.expiry_date
            ):
                raise HTTPException(
                    status_code=422,
                    detail=inventory_business_error(
                        "INBOUND_BATCH_DATES_INVALID",
                        "Production date cannot be after expiry date.",
                        context={"batch_number": str(item.batch_number)},
                    ),
                )

            if batch_key not in requested_batches:
                requested_batches[batch_key] = metadata
            inbound_lines.append({
                "batch_key": batch_key,
                "uom_id": int(item.uom_id),
                "base_quantity": base_quantity,
                "cost_input": build_purchase_cost_input(
                    input_uom_id=int(item.uom_id),
                    input_quantity=Decimal(item.quantity),
                    input_unit_cost=Decimal(item.unit_cost),
                    base_quantity=base_quantity,
                ),
            })

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
            (int(row.product_variant_id), str(row.batch_number)): row
            for row in batch_rows
        }
        if set(batch_map) != set(requested_batches):
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "INBOUND_BATCH_PERSISTENCE_CONFLICT",
                    "Not all inbound batches could be established.",
                ),
            )

        for key, (production_date, expiry_date) in requested_batches.items():
            batch = batch_map[key]
            if not batch.is_active or batch.disposition != 'RELEASED':
                raise HTTPException(
                    status_code=409,
                    detail=inventory_business_error(
                        "INBOUND_BATCH_UNAVAILABLE",
                        "The batch is not released for available inventory.",
                        context={"batch_number": str(batch.batch_number)},
                    ),
                )
            expiry_mode = variant_rules[int(batch.product_variant_id)]["expiry_control_mode"]
            if expiry_mode == 'REQUIRED' and batch.expiry_date is None:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_EXPIRY_REQUIRED", "The existing batch is missing its required expiry date.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if expiry_mode == 'NONE' and batch.expiry_date is not None:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_EXPIRY_NOT_ALLOWED", "The existing batch has expiry data for a non-expiry product.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if batch.expiry_date is not None and batch.expiry_date < as_of_date:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_BATCH_EXPIRED", "The existing batch is expired.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if batch.production_date is not None and batch.production_date > as_of_date:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_PRODUCTION_DATE_FUTURE", "The existing batch has a future production date.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if batch.expiry_date != expiry_date:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_BATCH_METADATA_CONFLICT", "The batch already exists with a different expiry date.",
                    context={"batch_number": str(batch.batch_number)},
                ))
            if batch.production_date is not None and production_date is not None and batch.production_date != production_date:
                raise HTTPException(status_code=409, detail=inventory_business_error(
                    "INBOUND_BATCH_METADATA_CONFLICT", "The batch already exists with a different production date.",
                    context={"batch_number": str(batch.batch_number)},
                ))

        # Policy activation is serialized and happens before the first physical receipt.
        await activate_costing_for_first_receipt(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
        )

        movement_specs = []
        for line in sorted(
            inbound_lines,
            key=lambda value: (
                value["batch_key"][0],
                value["batch_key"][1],
                value["uom_id"],
            ),
        ):
            batch_key = line["batch_key"]
            product_variant_id, batch_number = batch_key
            batch = batch_map[batch_key]
            movement_raw_key = (
                f"{company_id}|{normalized_ref}|{main_loc.id}|"
                f"{product_variant_id}|{batch.id}|{line['uom_id']}"
            )
            movement_specs.append({
                "product_variant_id": product_variant_id,
                "batch_id": int(batch.id),
                "quantity": line["base_quantity"],
                "movement_kind": 'PHYSICAL',
                "reference_type": 'INBOUND_SUPPLIER',
                "reference_id": reference_id,
                "idempotency_key": (
                    "INB-"
                    + hashlib.sha256(movement_raw_key.encode("utf-8")).hexdigest()
                ),
                "source_location_id": None,
                "destination_location_id": main_loc.id,
                "source_stock_status": None,
                "destination_stock_status": 'AVAILABLE',
                "inventory_cost_input": line["cost_input"],
                "notes": payload.notes,
            })

        await apply_inventory_movements_batch(
            db,
            company_id=company_id,
            performed_by=current_admin.id,
            movements=movement_specs,
        )

        response_payload = {"message": "INBOUND_POSTED"}
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except HTTPException:
        await db.rollback()
        raise
    except CostingError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning(
            f"Concurrent conflict during supplier inbound: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INBOUND_CONCURRENT_CONFLICT",
                "A concurrent inbound conflict occurred. Nothing was committed.",
            ),
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(
            f"Unexpected supplier inbound failure: {str(exc)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=inventory_business_error(
                "INBOUND_INTERNAL_ERROR",
                "Supplier inbound could not be completed.",
            ),
        ) from exc


# =================================================================================
# 2. إشعارات النواقص (Threshold Alerts - Reorder Point)
# =================================================================================
# Legacy unbounded /warehouse/alerts removed; alert metadata now comes from inventory cursor.


# =================================================================================
# 3. جلب حالة المستودع بالكامل من المحرك الموحد
# =================================================================================
def _warehouse_array_membership(column, values, bind_name: str):
    normalized = sorted({int(value) for value in values})
    if not normalized:
        raise ValueError("Warehouse array membership requires values.")
    return column == any_(
        bindparam(
            bind_name,
            value=normalized,
            type_=ARRAY(Integer),
        )
    )


async def _require_live_stock_read_model_ready(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
) -> None:
    try:
        await assert_live_stock_projection_ready(
            db,
            company_id=company_id,
            warehouse_location_id=location_id,
        )
    except LiveStockProjectionError as exc:
        if "active warehouse" in str(exc):
            exists = await db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.id == location_id,
                    InventoryLocation.location_type == "WAREHOUSE",
                    InventoryLocation.is_active.is_(True),
                )
            )
            if exists is None:
                raise HTTPException(
                    status_code=404,
                    detail="المستودع غير موجود أو لا يتبع شركتك.",
                ) from exc
        raise HTTPException(
            status_code=503,
            detail=inventory_business_error(
                "LIVE_STOCK_PROJECTION_NOT_READY",
                "الرصيد الحي قيد التحديث. أعد المحاولة بعد لحظات.",
            ),
        ) from exc


def _readable_vehicle_locations_subquery(
    *,
    company_id: int,
    access: InventoryAccess,
):
    return (
        select(InventoryLocation.id, InventoryLocation.vehicle_id)
        .where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.location_type == "VEHICLE",
            InventoryLocation.is_active.is_(True),
            InventoryLocation.vehicle_id.isnot(None),
            access.location_filter("inventory.read"),
        )
        .subquery("readable_vehicle_locations")
    )


def _latest_readable_vehicle_sources_subquery(
    *,
    company_id: int,
    readable_vehicle_locations,
):
    return (
        select(DispatchRoute.vehicle_id, DispatchRoute.source_location_id)
        .where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.vehicle_id.in_(
                select(readable_vehicle_locations.c.vehicle_id)
            ),
        )
        .distinct(DispatchRoute.vehicle_id)
        .order_by(DispatchRoute.vehicle_id, DispatchRoute.id.desc())
        .subquery("latest_readable_vehicle_sources")
    )


async def _require_live_stock_warehouse_read(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    access: InventoryAccess,
    actor: Driver,
) -> bool:
    """Validate inventory.read authority for the selected warehouse.

    Company admins need no separate location SQL on the success path because
    the readiness query already joins the active warehouse. Restricted actors
    keep explicit location + permission checks to preserve authorization.
    """
    if bool(actor.is_admin):
        return True

    location_exists = await db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.id == location_id,
            InventoryLocation.location_type == "WAREHOUSE",
            InventoryLocation.is_active.is_(True),
        )
    )
    if location_exists is None:
        raise HTTPException(
            status_code=404,
            detail="المستودع غير موجود أو لا يتبع شركتك.",
        )

    permission_row = (
        await db.execute(
            select(
                access.allows(
                    "inventory.read",
                    location_id,
                ).label("location_allowed"),
                access.allows(
                    "inventory.read",
                ).label("company_wide_allowed"),
            )
        )
    ).one()
    if not bool(permission_row.location_allowed):
        raise HTTPException(
            status_code=403,
            detail="لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.",
        )
    return bool(permission_row.company_wide_allowed)


def _build_visible_inventory_stmt(
    *, company_id: int, location_id: int, access: InventoryAccess,
    company_wide_inventory_read: bool,
    candidate_filters=(), limit: Optional[int] = None,
):
    """Exact Live Stock visibility with projection-backed warehouse presence.

    Active variants are always visible. Non-active variants are visible when
    warehouse stock exists in the projection or when stock exists on a vehicle
    the current actor is allowed to read and whose latest route belongs to the
    selected warehouse.
    """
    candidate_filters = [
        ProductVariant.company_id == company_id,
        *candidate_filters,
    ]
    ordering = (
        (ProductVariant.name, ProductVariant.id)
        if limit is not None
        else ()
    )
    if company_wide_inventory_read:
        return (
            select(
                ProductVariant.id,
                ProductVariant.name.label("variant_name"),
            )
            .outerjoin(
                InventoryLiveStockProjection,
                and_(
                    InventoryLiveStockProjection.company_id
                    == ProductVariant.company_id,
                    InventoryLiveStockProjection.product_variant_id
                    == ProductVariant.id,
                    InventoryLiveStockProjection.warehouse_location_id
                    == location_id,
                ),
            )
            .where(
                *candidate_filters,
                or_(
                    ProductVariant.lifecycle_status == "ACTIVE",
                    InventoryLiveStockProjection.has_warehouse_presence.is_(
                        True
                    ),
                    InventoryLiveStockProjection.has_vehicle_presence.is_(
                        True
                    ),
                ),
            )
            .order_by(*ordering)
            .limit(limit + 1 if limit is not None else None)
        )


    active_candidates = (
        select(
            ProductVariant.id,
            ProductVariant.name.label("variant_name"),
        )
        .where(
            *candidate_filters,
            ProductVariant.lifecycle_status == "ACTIVE",
        )
        .order_by(*ordering)
        .limit(limit + 1 if limit is not None else None)
    )

    warehouse_candidates = (
        select(
            ProductVariant.id,
            ProductVariant.name.label("variant_name"),
        )
        .join(
            InventoryLiveStockProjection,
            and_(
                InventoryLiveStockProjection.company_id
                == ProductVariant.company_id,
                InventoryLiveStockProjection.product_variant_id
                == ProductVariant.id,
                InventoryLiveStockProjection.warehouse_location_id
                == location_id,
            ),
        )
        .where(
            *candidate_filters,
            ProductVariant.lifecycle_status.is_distinct_from("ACTIVE"),
            InventoryLiveStockProjection.has_warehouse_presence.is_(True),
        )
        .order_by(*ordering)
        .limit(limit + 1 if limit is not None else None)
    )

    readable_vehicle_locations = _readable_vehicle_locations_subquery(
        company_id=company_id,
        access=access,
    )
    latest_vehicle_sources = _latest_readable_vehicle_sources_subquery(
        company_id=company_id,
        readable_vehicle_locations=readable_vehicle_locations,
    )
    vehicle_candidates = (
        select(
            ProductVariant.id,
            ProductVariant.name.label("variant_name"),
        )
        .join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id == company_id,
                InventoryBalance.product_variant_id == ProductVariant.id,
                InventoryBalance.stock_status != "DAMAGED",
                InventoryBalance.on_hand_quantity > 0,
            ),
        )
        .join(
            readable_vehicle_locations,
            readable_vehicle_locations.c.id
            == InventoryBalance.location_id,
        )
        .join(
            latest_vehicle_sources,
            and_(
                latest_vehicle_sources.c.vehicle_id
                == readable_vehicle_locations.c.vehicle_id,
                latest_vehicle_sources.c.source_location_id == location_id,
            ),
        )
        .where(
            *candidate_filters,
            ProductVariant.lifecycle_status.is_distinct_from("ACTIVE"),
        )
        .distinct()
        .order_by(*ordering)
        .limit(limit + 1 if limit is not None else None)
    )

    visible_candidates = union(
        active_candidates,
        warehouse_candidates,
        vehicle_candidates,
    ).subquery("visible_inventory_candidates")
    return (
        select(
            visible_candidates.c.id,
            visible_candidates.c.variant_name,
        )
        .order_by(
            *((visible_candidates.c.variant_name, visible_candidates.c.id)
              if limit is not None else ())
        )
        .limit(limit + 1 if limit is not None else None)
    )


def _build_inventory_alert_variants_stmt(
    *,
    company_id: int,
    location_id: int,
    variant_filters=(),
):
    return (
        select(
            ProductVariant.id,
            ProductVariant.name.label("variant_name"),
        )
        .join(
            InventoryLiveStockProjection,
            and_(
                InventoryLiveStockProjection.company_id
                == ProductVariant.company_id,
                InventoryLiveStockProjection.product_variant_id
                == ProductVariant.id,
                InventoryLiveStockProjection.warehouse_location_id
                == location_id,
            ),
        )
        .where(
            ProductVariant.company_id == company_id,
            InventoryLiveStockProjection.is_low_stock.is_(True),
            *variant_filters,
        )
    )


@router.get(
    "/warehouse/inventory/alerts/summary",
    response_model=WarehouseInventoryAlertSummaryResponse,
    status_code=200,
)
async def get_warehouse_inventory_alert_summary(
    location_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    company_id = current_admin.company_id
    await _require_live_stock_warehouse_read(
        db,
        company_id=company_id,
        location_id=location_id,
        access=access,
        actor=current_admin,
    )

    await _require_live_stock_read_model_ready(
        db,
        company_id=company_id,
        location_id=location_id,
    )
    alert_count = int(
        (
            await db.scalar(
                select(
                    InventoryLiveStockWarehouseSummary.alert_count
                ).where(
                    InventoryLiveStockWarehouseSummary.company_id
                    == company_id,
                    InventoryLiveStockWarehouseSummary.warehouse_location_id
                    == location_id,
                )
            )
        )
        or 0
    )
    return {"alert_count": alert_count}


@router.get("/warehouse/inventory/summary", response_model=WarehouseInventorySummaryResponse)
async def get_warehouse_inventory_summary(
    location_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    company_id = current_admin.company_id
    company_wide_inventory_read = (
        await _require_live_stock_warehouse_read(
            db,
            company_id=company_id,
            location_id=location_id,
            access=access,
            actor=current_admin,
        )
    )

    await _require_live_stock_read_model_ready(
        db,
        company_id=company_id,
        location_id=location_id,
    )

    summary_row = (
        await db.execute(
            select(
                InventoryLiveStockCompanySummary.active_variant_count,
                InventoryLiveStockWarehouseSummary.alert_count,
                InventoryLiveStockWarehouseSummary.nonactive_visible_count,
            )
            .join(
                InventoryLiveStockWarehouseSummary,
                InventoryLiveStockWarehouseSummary.company_id
                == InventoryLiveStockCompanySummary.company_id,
            )
            .where(
                InventoryLiveStockCompanySummary.company_id == company_id,
                InventoryLiveStockWarehouseSummary.warehouse_location_id
                == location_id,
            )
        )
    ).one()
    active_count = int(summary_row.active_variant_count)
    alert_count = int(summary_row.alert_count)

    if company_wide_inventory_read:
        return {
            "stock_total": (
                active_count
                + int(summary_row.nonactive_visible_count)
            ),
            "alert_count": alert_count,
        }

    # Restricted actors must not inherit vehicle presence from vehicles they
    # cannot read. Warehouse presence is projection-backed; vehicle-only
    # visibility remains permission-aware and the UNION removes overlap.
    warehouse_nonactive = (
        select(InventoryLiveStockProjection.product_variant_id.label("id"))
        .join(
            ProductVariant,
            and_(
                ProductVariant.company_id
                == InventoryLiveStockProjection.company_id,
                ProductVariant.id
                == InventoryLiveStockProjection.product_variant_id,
            ),
        )
        .where(
            InventoryLiveStockProjection.company_id == company_id,
            InventoryLiveStockProjection.warehouse_location_id
            == location_id,
            ProductVariant.lifecycle_status.is_distinct_from("ACTIVE"),
            InventoryLiveStockProjection.has_warehouse_presence.is_(True),
        )
    )

    readable_vehicle_locations = _readable_vehicle_locations_subquery(
        company_id=company_id,
        access=access,
    )
    latest_vehicle_sources = _latest_readable_vehicle_sources_subquery(
        company_id=company_id,
        readable_vehicle_locations=readable_vehicle_locations,
    )
    readable_vehicle_nonactive = (
        select(InventoryBalance.product_variant_id.label("id"))
        .join(
            ProductVariant,
            and_(
                ProductVariant.company_id == InventoryBalance.company_id,
                ProductVariant.id == InventoryBalance.product_variant_id,
            ),
        )
        .join(
            readable_vehicle_locations,
            readable_vehicle_locations.c.id == InventoryBalance.location_id,
        )
        .join(
            latest_vehicle_sources,
            and_(
                latest_vehicle_sources.c.vehicle_id
                == readable_vehicle_locations.c.vehicle_id,
                latest_vehicle_sources.c.source_location_id == location_id,
            ),
        )
        .where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.stock_status != "DAMAGED",
            InventoryBalance.on_hand_quantity > 0,
            ProductVariant.lifecycle_status.is_distinct_from("ACTIVE"),
        )
        .distinct()
    )
    nonactive_visible = union(
        warehouse_nonactive,
        readable_vehicle_nonactive,
    ).subquery("restricted_nonactive_visible")
    nonactive_count = int(
        (
            await db.scalar(
                select(func.count()).select_from(nonactive_visible)
            )
        )
        or 0
    )

    return {
        "stock_total": active_count + nonactive_count,
        "alert_count": alert_count,
    }


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
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    company_id = current_admin.company_id

    try:
        company_wide_inventory_read = (
            await _require_live_stock_warehouse_read(
                db,
                company_id=company_id,
                location_id=location_id,
                access=access,
                actor=current_admin,
            )
        )

        await _require_live_stock_read_model_ready(
            db,
            company_id=company_id,
            location_id=location_id,
        )

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
                func.lower(ProductVariant.name).like(
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

        scope = (
            f"inventory|{company_id}|{location_id}|"
            f"{clean_search}|{int(only_alerts)}"
        )
        candidate_filters = []
        if search_condition is not None:
            candidate_filters.append(search_condition)
        if cursor is not None:
            cursor_name, cursor_id = _decode_variant_cursor(
                cursor,
                expected_kind="warehouse-inventory",
                expected_scope=scope,
            )
            candidate_filters.append(
                tuple_(ProductVariant.name, ProductVariant.id)
                > tuple_(cursor_name, cursor_id)
            )

        if only_alerts:
            # Search and seek are part of the policy-driven source query so the
            # database never materializes the full alert population first.
            alerts = _build_inventory_alert_variants_stmt(
                company_id=company_id,
                location_id=location_id,
                variant_filters=candidate_filters,
            ).cte("scoped_alerts").prefix_with("MATERIALIZED")
            candidate_stmt = (
                select(alerts.c.id, alerts.c.variant_name)
                .order_by(alerts.c.variant_name, alerts.c.id)
                .limit(limit + 1)
            )
        else:
            candidate_stmt = _build_visible_inventory_stmt(
                company_id=company_id,
                location_id=location_id,
                access=access,
                company_wide_inventory_read=company_wide_inventory_read,
                candidate_filters=candidate_filters,
                limit=limit,
            )

        # Compatibility fields remain nullable; no exact totals on list reads.
        total = None
        candidate_rows = (await db.execute(candidate_stmt)).all()

        has_more = len(candidate_rows) > limit
        page_candidates = candidate_rows[:limit]
        page_variant_ids = [int(row.id) for row in page_candidates]

        alert_count = None
        alert_samples: list[str] = []

        if not page_variant_ids:
            return {
                "items": [],
                "next_cursor": None,
                "has_more": False,
                "total": total,
                "alert_count": alert_count,
                "alert_samples": alert_samples,
            }

        vehicles: dict[int, Decimal] = {}
        if not company_wide_inventory_read:
            readable_vehicle_locations = _readable_vehicle_locations_subquery(
                company_id=company_id,
                access=access,
            )
            latest_vehicle_sources = _latest_readable_vehicle_sources_subquery(
                company_id=company_id,
                readable_vehicle_locations=readable_vehicle_locations,
            )
            vehicle_inventory_stmt = (
                select(
                    InventoryBalance.product_variant_id,
                    func.sum(
                        InventoryBalance.on_hand_quantity
                    ).label("vehicle_packs"),
                )
                .join(
                    readable_vehicle_locations,
                    readable_vehicle_locations.c.id
                    == InventoryBalance.location_id,
                )
                .join(
                    latest_vehicle_sources,
                    and_(
                        latest_vehicle_sources.c.vehicle_id
                        == readable_vehicle_locations.c.vehicle_id,
                        latest_vehicle_sources.c.source_location_id
                        == location_id,
                    ),
                )
                .where(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.stock_status != "DAMAGED",
                    _warehouse_array_membership(
                        InventoryBalance.product_variant_id,
                        page_variant_ids,
                        "inventory_vehicle_page_variant_ids",
                    ),
                    InventoryBalance.on_hand_quantity > 0,
                )
                .group_by(InventoryBalance.product_variant_id)
            )
            vehicles = {
                int(row.product_variant_id): Decimal(
                    row.vehicle_packs or 0
                )
                for row in (
                    await db.execute(vehicle_inventory_stmt)
                ).all()
            }

        latest_purchase_page = (
            select(
                InventoryCostEvent.product_variant_id.label(
                    "product_variant_id"
                ),
                InventoryCostEvent.input_unit_cost.label(
                    "input_unit_cost"
                ),
                UOM.code.label("input_uom_code"),
                InventoryCostEvent.created_at.label("created_at"),
            )
            .join(
                UOM,
                UOM.id == InventoryCostEvent.input_uom_id,
            )
            .where(
                InventoryCostEvent.company_id == company_id,
                _warehouse_array_membership(
                    InventoryCostEvent.product_variant_id,
                    page_variant_ids,
                    "inventory_purchase_page_variant_ids",
                ),
                InventoryCostEvent.event_type == "PURCHASE_IN",
            )
            .distinct(InventoryCostEvent.product_variant_id)
            .order_by(
                InventoryCostEvent.product_variant_id,
                InventoryCostEvent.created_at.desc(),
                InventoryCostEvent.id.desc(),
            )
            .subquery("latest_purchase_page")
        )

        stmt = (
            select(
                ProductVariant,
                UOM,
                InventoryLiveStockProjection,
                InventoryCostState.average_unit_cost.label(
                    "average_unit_cost"
                ),
                Company.currency_code.label("currency_code"),
                latest_purchase_page.c.input_unit_cost.label(
                    "last_purchase_cost"
                ),
                latest_purchase_page.c.input_uom_code.label(
                    "last_purchase_uom_code"
                ),
                latest_purchase_page.c.created_at.label(
                    "last_purchase_created_at"
                ),
            )
            .join(UOM, UOM.id == ProductVariant.base_uom_id)
            .join(Company, Company.id == ProductVariant.company_id)
            .outerjoin(
                InventoryLiveStockProjection,
                and_(
                    InventoryLiveStockProjection.company_id
                    == ProductVariant.company_id,
                    InventoryLiveStockProjection.product_variant_id
                    == ProductVariant.id,
                    InventoryLiveStockProjection.warehouse_location_id
                    == location_id,
                ),
            )
            .outerjoin(
                InventoryCostState,
                and_(
                    InventoryCostState.company_id
                    == ProductVariant.company_id,
                    InventoryCostState.product_variant_id
                    == ProductVariant.id,
                ),
            )
            .outerjoin(
                latest_purchase_page,
                latest_purchase_page.c.product_variant_id
                == ProductVariant.id,
            )
            .where(
                ProductVariant.company_id == company_id,
                _warehouse_array_membership(
                    ProductVariant.id,
                    page_variant_ids,
                    "inventory_detail_page_variant_ids",
                ),
            )
            .order_by(ProductVariant.name, ProductVariant.id)
        )
        rows = [
            (
                variant,
                uom,
                projection,
                average_unit_cost,
                currency_code,
                last_purchase_cost,
                last_purchase_uom_code,
                last_purchase_created_at,
                (
                    Decimal(projection.vehicle_packs or 0)
                    if company_wide_inventory_read
                    and projection is not None
                    else vehicles.get(int(variant.id), Decimal("0"))
                ),
            )
            for (
                variant,
                uom,
                projection,
                average_unit_cost,
                currency_code,
                last_purchase_cost,
                last_purchase_uom_code,
                last_purchase_created_at,
            ) in (await db.execute(stmt)).all()
        ]

        display_uoms = await _load_inventory_display_uoms(
            db,
            company_id=company_id,
            variant_ids=page_variant_ids,
        )

        result = []
        for (
            variant,
            base_uom,
            projection,
            average_unit_cost,
            currency_code,
            last_purchase_cost_raw,
            last_purchase_uom_code_raw,
            last_purchase_created_at,
            vehicle_total,
        ) in rows:
            on_hand = Decimal(
                projection.warehouse_on_hand
                if projection is not None
                else 0
            )
            reserved = Decimal(
                projection.warehouse_reserved
                if projection is not None
                else 0
            )
            projected_sellable_on_hand = Decimal(
                projection.warehouse_sellable_on_hand
                if projection is not None
                else 0
            )
            projected_sellable_reserved = Decimal(
                projection.warehouse_sellable_reserved
                if projection is not None
                else 0
            )

            sellable_on_hand = (
                projected_sellable_on_hand
                if variant.lifecycle_status == "ACTIVE"
                and variant.operational_hold == "NONE"
                else Decimal("0")
            )
            sellable_reserved = (
                projected_sellable_reserved
                if variant.lifecycle_status == "ACTIVE"
                and variant.operational_hold == "NONE"
                else Decimal("0")
            )

            free_quantity = sellable_on_hand - sellable_reserved
            explicit_blocked = Decimal(
                projection.blocked_status_packs
                if projection is not None
                else 0
            )
            blocked_quantity = (
                on_hand - sellable_on_hand
            ) + explicit_blocked
            recalled = Decimal(
                projection.recalled_packs
                if projection is not None
                else 0
            )
            vehicle_total = Decimal(vehicle_total or 0)
            damaged = Decimal(
                projection.damaged_packs
                if projection is not None
                else 0
            )
            minimum_quantity = Decimal(
                projection.minimum_quantity
                if projection is not None
                else 0
            )

            warehouse_on_hand_total = on_hand + explicit_blocked + damaged
            unavailable_quantity = (
                warehouse_on_hand_total - reserved - free_quantity
            )

            if free_quantity < 0:
                raise RuntimeError(
                    f"Inventory invariant violated for "
                    f"product_variant_id={variant.id}: "
                    "sellable reserved quantity exceeds sellable on-hand."
                )
            if blocked_quantity < 0:
                raise RuntimeError(
                    f"Inventory invariant violated for "
                    f"product_variant_id={variant.id}: "
                    "sellable stock exceeds physical AVAILABLE stock."
                )
            if unavailable_quantity < 0:
                raise RuntimeError(
                    f"Inventory business partition violated for "
                    f"product_variant_id={variant.id}: "
                    "on-hand is smaller than reserved plus sellable stock."
                )

            total_physical_available = on_hand + explicit_blocked + vehicle_total

            display = display_uoms.get(int(variant.id))
            if display is None:
                display_uom_id = int(base_uom.id)
                display_uom_code = str(base_uom.code)
                display_uom_name = str(base_uom.name)
                display_factor = Decimal("1")
            else:
                display_uom_id = int(display["uom_id"])
                display_uom_code = str(display["uom_code"])
                display_uom_name = str(display["uom_name"])
                display_factor = Decimal(display["factor_to_base"])

            has_location_inventory = (
                warehouse_on_hand_total > 0 or vehicle_total > 0
            )

            average_cost_display = None
            if has_location_inventory and average_unit_cost is not None:
                average_cost_display = (
                    Decimal(average_unit_cost) * display_factor
                ).quantize(Decimal("0.000001"))

            last_purchase_cost = None
            last_purchase_uom_code = None
            last_purchase_date = None
            if (
                has_location_inventory
                and last_purchase_cost_raw is not None
            ):
                last_purchase_cost = Decimal(last_purchase_cost_raw)
                last_purchase_uom_code = str(
                    last_purchase_uom_code_raw
                )
                last_purchase_date = (
                    last_purchase_created_at.date()
                    if last_purchase_created_at is not None
                    else None
                )

            if not currency_code:
                raise RuntimeError("Company currency is unavailable.")

            result.append({
                "id": variant.id,
                "name": variant.variant_name,
                "sku": variant.sku,
                "base_uom_id": variant.base_uom_id,
                "base_uom_code": base_uom.code,
                "base_uom_name": base_uom.name,
                "display_uom_id": display_uom_id,
                "display_uom_code": display_uom_code,
                "display_uom_name": display_uom_name,
                "display_factor_to_base": canonical_quantity(display_factor),
                "currency_code": str(currency_code).upper(),
                "average_cost_display": (
                    format(average_cost_display, "f")
                    if average_cost_display is not None
                    else None
                ),
                "last_purchase_cost": (
                    format(last_purchase_cost, "f")
                    if last_purchase_cost is not None
                    else None
                ),
                "last_purchase_uom_code":
                    last_purchase_uom_code,
                "last_purchase_date":
                    last_purchase_date,
                "quantity_scale": variant.quantity_scale,
                "quantity_step": canonical_quantity(variant.quantity_step),

                "on_hand_quantity": canonical_quantity(warehouse_on_hand_total),
                "reserved_quantity": canonical_quantity(reserved),
                "available_for_sale_quantity": canonical_quantity(free_quantity),
                "unavailable_quantity": canonical_quantity(unavailable_quantity),
                "vehicle_quantity": canonical_quantity(vehicle_total),
                "recalled_quantity": canonical_quantity(recalled),

                "available_quantity": canonical_quantity(free_quantity),
                "blocked_quantity": canonical_quantity(blocked_quantity),
                "total_quantity": canonical_quantity(total_physical_available),
                "damaged_quantity": canonical_quantity(damaged),
                "minimum_quantity": canonical_quantity(minimum_quantity or 0),
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


@router.get(
    "/warehouse/inventory/{product_variant_id}/batches",
    response_model=WarehouseInventoryBatchDetailResponse,
    status_code=200,
)
async def get_warehouse_inventory_batches(
    product_variant_id: int,
    location_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.read", location_id)

    company_id = current_admin.company_id

    try:
        location_exists = await db.scalar(
            select(InventoryLocation.id).filter(
                InventoryLocation.id == location_id,
                InventoryLocation.company_id == company_id,
                InventoryLocation.location_type == "WAREHOUSE",
                InventoryLocation.is_active.is_(True),
            )
        )
        if location_exists is None:
            raise HTTPException(
                status_code=404,
                detail=inventory_business_error(
                    "LIVE_STOCK_LOCATION_NOT_FOUND",
                    "The selected warehouse is unavailable.",
                ),
            )

        variant_exists = await db.scalar(
            select(ProductVariant.id).filter(
                ProductVariant.id == product_variant_id,
                ProductVariant.company_id == company_id,
            )
        )
        if variant_exists is None:
            raise HTTPException(
                status_code=404,
                detail=inventory_business_error(
                    "LIVE_STOCK_PRODUCT_NOT_FOUND",
                    "The selected product is unavailable.",
                ),
            )

        as_of_date = await get_company_local_date(db, company_id)

        batch_is_sellable = batch_sellability_predicate(
            as_of_date,
            expiry_control_mode=ProductVariant.expiry_control_mode,
            minimum_remaining_shelf_life_days=(
                InventoryStockPolicy.minimum_remaining_shelf_life_days
            ),
        )

        batch_stmt = (
            select(
                ProductBatch.id.label("batch_id"),
                ProductBatch.batch_number,
                ProductBatch.production_date,
                ProductBatch.expiry_date,
                ProductBatch.disposition,
                func.sum(
                    InventoryBalance.on_hand_quantity
                ).label("on_hand_total"),
                func.sum(
                    InventoryBalance.reserved_quantity
                ).label("reserved_total"),
                func.sum(
                    case(
                        (
                            and_(
                                InventoryBalance.stock_status == "AVAILABLE",
                                batch_is_sellable,
                            ),
                            InventoryBalance.on_hand_quantity,
                        ),
                        else_=0,
                    )
                ).label("sellable_on_hand"),
                func.sum(
                    case(
                        (
                            and_(
                                InventoryBalance.stock_status == "AVAILABLE",
                                batch_is_sellable,
                            ),
                            InventoryBalance.reserved_quantity,
                        ),
                        else_=0,
                    )
                ).label("sellable_reserved"),
                func.sum(
                    case(
                        (
                            InventoryBalance.stock_status == "QUARANTINED",
                            InventoryBalance.on_hand_quantity,
                        ),
                        else_=0,
                    )
                ).label("quarantined_quantity"),
                func.sum(
                    case(
                        (
                            InventoryBalance.stock_status == "BLOCKED",
                            InventoryBalance.on_hand_quantity,
                        ),
                        else_=0,
                    )
                ).label("blocked_quantity"),
                func.sum(
                    case(
                        (
                            InventoryBalance.stock_status == "RECALLED",
                            InventoryBalance.on_hand_quantity,
                        ),
                        else_=0,
                    )
                ).label("recalled_quantity"),
                func.sum(
                    case(
                        (
                            InventoryBalance.stock_status == "DAMAGED",
                            InventoryBalance.on_hand_quantity,
                        ),
                        else_=0,
                    )
                ).label("damaged_quantity"),
                func.sum(
                    case(
                        (
                            InventoryBalance.stock_status
                            == "DISPOSAL_PENDING",
                            InventoryBalance.on_hand_quantity,
                        ),
                        else_=0,
                    )
                ).label("disposal_pending_quantity"),
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
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id
                    == InventoryBalance.company_id,
                    ProductVariant.id
                    == InventoryBalance.product_variant_id,
                ),
            )
            .outerjoin(
                InventoryStockPolicy,
                and_(
                    InventoryStockPolicy.company_id
                    == InventoryBalance.company_id,
                    InventoryStockPolicy.location_id == location_id,
                    InventoryStockPolicy.product_variant_id
                    == InventoryBalance.product_variant_id,
                    InventoryStockPolicy.is_active.is_(True),
                ),
            )
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id
                == product_variant_id,
                InventoryBalance.on_hand_quantity > 0,
            )
            .group_by(
                ProductBatch.id,
                ProductBatch.batch_number,
                ProductBatch.production_date,
                ProductBatch.expiry_date,
                ProductBatch.disposition,
            )
            .order_by(
                ProductBatch.expiry_date.asc().nulls_last(),
                ProductBatch.id.asc(),
            )
        )

        batch_rows = (await db.execute(batch_stmt)).all()
        batch_ids = [int(row.batch_id) for row in batch_rows]

        latest_purchase_by_batch = {}
        purchase_count_by_batch = {}

        if batch_ids:
            latest_purchase_rows = (
                await db.execute(
                    select(
                        InventoryCostEvent.batch_id.label("batch_id"),
                        InventoryCostEvent.input_unit_cost.label(
                            "input_unit_cost"
                        ),
                        UOM.code.label("input_uom_code"),
                        InventoryCostEvent.created_at.label(
                            "created_at"
                        ),
                    )
                    .join(
                        UOM,
                        UOM.id == InventoryCostEvent.input_uom_id,
                    )
                    .filter(
                        InventoryCostEvent.company_id == company_id,
                        InventoryCostEvent.product_variant_id
                        == product_variant_id,
                        InventoryCostEvent.batch_id.in_(batch_ids),
                        InventoryCostEvent.event_type == "PURCHASE_IN",
                    )
                    .distinct(InventoryCostEvent.batch_id)
                    .order_by(
                        InventoryCostEvent.batch_id,
                        InventoryCostEvent.created_at.desc(),
                        InventoryCostEvent.id.desc(),
                    )
                )
            ).all()
            latest_purchase_by_batch = {
                int(row.batch_id): row
                for row in latest_purchase_rows
            }

            purchase_count_rows = (
                await db.execute(
                    select(
                        InventoryCostEvent.batch_id.label("batch_id"),
                        func.count(InventoryCostEvent.id).label(
                            "event_count"
                        ),
                    )
                    .filter(
                        InventoryCostEvent.company_id == company_id,
                        InventoryCostEvent.product_variant_id
                        == product_variant_id,
                        InventoryCostEvent.batch_id.in_(batch_ids),
                        InventoryCostEvent.event_type == "PURCHASE_IN",
                    )
                    .group_by(InventoryCostEvent.batch_id)
                )
            ).all()
            purchase_count_by_batch = {
                int(row.batch_id): int(row.event_count)
                for row in purchase_count_rows
            }

        currency_code = await db.scalar(
            select(Company.currency_code).where(
                Company.id == company_id
            )
        )
        if not currency_code:
            raise RuntimeError(
                "Company currency is unavailable."
            )

        batches = []
        for row in batch_rows:
            on_hand_total = Decimal(row.on_hand_total or 0)
            reserved_total = Decimal(row.reserved_total or 0)
            sellable_on_hand = Decimal(
                row.sellable_on_hand or 0
            )
            sellable_reserved = Decimal(
                row.sellable_reserved or 0
            )

            available_for_sale = (
                sellable_on_hand - sellable_reserved
            )
            unavailable = (
                on_hand_total
                - reserved_total
                - available_for_sale
            )

            if available_for_sale < 0 or unavailable < 0:
                raise RuntimeError(
                    "Inventory batch partition invariant failed "
                    f"for product_variant_id={product_variant_id}, "
                    f"batch_id={row.batch_id}."
                )

            quarantined = Decimal(
                row.quarantined_quantity or 0
            )
            blocked = Decimal(row.blocked_quantity or 0)
            recalled = Decimal(row.recalled_quantity or 0)
            damaged = Decimal(row.damaged_quantity or 0)
            disposal_pending = Decimal(
                row.disposal_pending_quantity or 0
            )

            explicit_unavailable = (
                quarantined
                + blocked
                + recalled
                + damaged
                + disposal_pending
            )
            restricted = unavailable - explicit_unavailable
            if restricted < 0:
                raise RuntimeError(
                    "Inventory batch unavailable breakdown "
                    f"exceeded the partition for batch_id={row.batch_id}."
                )

            latest_purchase = latest_purchase_by_batch.get(
                int(row.batch_id)
            )
            latest_purchase_cost = None
            latest_purchase_uom_code = None
            latest_purchase_date = None
            if latest_purchase is not None:
                latest_purchase_cost = Decimal(
                    latest_purchase.input_unit_cost
                )
                latest_purchase_uom_code = str(
                    latest_purchase.input_uom_code
                )
                latest_purchase_date = (
                    latest_purchase.created_at.date()
                )

            batches.append(
                {
                    "batch_id": int(row.batch_id),
                    "batch_number": str(row.batch_number),
                    "production_date": row.production_date,
                    "expiry_date": row.expiry_date,
                    "disposition": str(row.disposition),
                    "days_to_expiry": (
                        (row.expiry_date - as_of_date).days
                        if row.expiry_date is not None
                        else None
                    ),
                    "on_hand_quantity": canonical_quantity(
                        on_hand_total
                    ),
                    "reserved_quantity": canonical_quantity(
                        reserved_total
                    ),
                    "available_for_sale_quantity":
                        canonical_quantity(
                            available_for_sale
                        ),
                    "unavailable_quantity":
                        canonical_quantity(unavailable),
                    "restricted_quantity":
                        canonical_quantity(restricted),
                    "quarantined_quantity":
                        canonical_quantity(quarantined),
                    "blocked_quantity":
                        canonical_quantity(blocked),
                    "recalled_quantity":
                        canonical_quantity(recalled),
                    "damaged_quantity":
                        canonical_quantity(damaged),
                    "disposal_pending_quantity":
                        canonical_quantity(disposal_pending),
                    "latest_purchase_cost": (
                        format(
                            latest_purchase_cost,
                            "f",
                        )
                        if latest_purchase_cost is not None
                        else None
                    ),
                    "latest_purchase_uom_code":
                        latest_purchase_uom_code,
                    "latest_purchase_date":
                        latest_purchase_date,
                    "purchase_event_count":
                        purchase_count_by_batch.get(
                            int(row.batch_id),
                            0,
                        ),
                }
            )

        return {
            "location_id": location_id,
            "product_variant_id": product_variant_id,
            "currency_code": str(currency_code).upper(),
            "batches": batches,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to load live-stock batch details "
            f"for company_id={company_id}, "
            f"location_id={location_id}, "
            f"product_variant_id={product_variant_id}: {exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=inventory_business_error(
                "LIVE_STOCK_BATCH_DETAILS_FAILED",
                "Live-stock batch details could not be loaded.",
            ),
        ) from exc


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
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('ledger.read', location_id, any_location=location_id is None)

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
            ProductVariant.name,
            UOM,
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
            Driver.full_name,
        ).join(
            ProductVariant,
            and_(
                ProductVariant.company_id == InventoryMovement.company_id,
                ProductVariant.id == InventoryMovement.product_variant_id,
            ),
        ).join(UOM, UOM.id == ProductVariant.base_uom_id).join(
            Driver,
            and_(
                Driver.company_id == InventoryMovement.company_id,
                Driver.id == InventoryMovement.performed_by,
            ),
        ).filter(
            InventoryMovement.company_id == company_id,
            or_(access.allows('ledger.read', InventoryMovement.source_location_id),
                access.allows('ledger.read', InventoryMovement.destination_location_id)),
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
                    func.lower(ProductVariant.name).like(
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
            or_(access.allows('ledger.read', InventoryMovement.source_location_id),
                access.allows('ledger.read', InventoryMovement.destination_location_id)),
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
        page_variant_ids = sorted({int(row[0].product_variant_id) for row in rows})

        aggregate_snapshots = (
            await _ledger_product_location_snapshots(
                db,
                company_id=company_id,
                location_id=location_id,
                product_variant_ids=page_variant_ids,
                movement_ids=movement_ids,
            )
            if location_id is not None
            else {}
        )
        display_uoms = await _load_inventory_display_uoms(
            db,
            company_id=company_id,
            variant_ids=page_variant_ids,
        )

        batch_ids = sorted({
            int(row[0].batch_id)
            for row in rows
            if row[0].batch_id is not None
        })
        batch_number_by_id: dict[int, str] = {}
        if batch_ids:
            batch_number_by_id = {
                int(batch_id): str(batch_number)
                for batch_id, batch_number in (
                    await db.execute(
                        select(ProductBatch.id, ProductBatch.batch_number).filter(
                            ProductBatch.company_id == company_id,
                            ProductBatch.id.in_(batch_ids),
                        )
                    )
                ).all()
            }

        cost_events = list(
            (
                await db.scalars(
                    select(InventoryCostEvent).filter(
                        InventoryCostEvent.company_id == company_id,
                        InventoryCostEvent.inventory_movement_id.in_(movement_ids),
                    )
                )
            ).all()
        )
        cost_event_by_movement = {
            int(event.inventory_movement_id): event for event in cost_events
        }
        cost_uom_ids = sorted({
            int(event.input_uom_id)
            for event in cost_events
            if event.input_uom_id is not None
        })
        cost_uom_by_id: dict[int, UOM] = {}
        if cost_uom_ids:
            cost_uom_by_id = {
                int(row.id): row
                for row in (
                    await db.scalars(select(UOM).where(UOM.id.in_(cost_uom_ids)))
                ).all()
            }
        ledger_currency_code = await db.scalar(
            select(Company.currency_code).where(Company.id == company_id)
        )
        if not ledger_currency_code:
            raise RuntimeError("Company currency is unavailable.")

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
            access.allows('ledger.read', InventoryBalance.location_id),
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

        for movement, product_name, base_uom, quantity_scale, quantity_step, admin_name in rows:
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
                        Decimal(impact.on_hand_before)
                        - Decimal(impact.reserved_before)
                    )
                    balance_after = (
                        Decimal(impact.on_hand_after)
                        - Decimal(impact.reserved_after)
                    )
                else:
                    balance_before = Decimal(impact.on_hand_before)
                    balance_after = Decimal(impact.on_hand_after)

                quantity_packs = balance_after - balance_before

            if quantity_packs is None:
                quantity = Decimal(movement.quantity)

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

            aggregate_snapshot = aggregate_snapshots.get(int(movement.id))
            total_balance_before = (
                aggregate_snapshot[0] if aggregate_snapshot is not None else None
            )
            total_balance_after = (
                aggregate_snapshot[1] if aggregate_snapshot is not None else None
            )

            display = display_uoms.get(int(movement.product_variant_id))
            if display is None:
                display_uom_id = int(base_uom.id)
                display_uom_code = str(base_uom.code)
                display_uom_name = str(base_uom.name)
                display_factor = Decimal("1")
            else:
                display_uom_id = int(display["uom_id"])
                display_uom_code = str(display["uom_code"])
                display_uom_name = str(display["uom_name"])
                display_factor = Decimal(display["factor_to_base"])

            cost_event = cost_event_by_movement.get(int(movement.id))
            input_uom = (
                cost_uom_by_id.get(int(cost_event.input_uom_id))
                if cost_event is not None and cost_event.input_uom_id is not None
                else None
            )
            average_cost_after = None
            average_cost_uom_code = None
            average_cost_uom_name = None
            if cost_event is not None:
                cost_quantity_after = Decimal(cost_event.quantity_after)
                cost_value_after = Decimal(cost_event.value_after)
                average_base_after = (
                    Decimal("0")
                    if cost_quantity_after == 0
                    else cost_value_after / cost_quantity_after
                )
                if (
                    cost_event.input_quantity is not None
                    and Decimal(cost_event.input_quantity) > 0
                    and input_uom is not None
                ):
                    event_factor = (
                        Decimal(movement.quantity)
                        / Decimal(cost_event.input_quantity)
                    )
                    average_cost_after = average_base_after * event_factor
                    average_cost_uom_code = str(input_uom.code)
                    average_cost_uom_name = str(input_uom.name)
                else:
                    average_cost_after = average_base_after * display_factor
                    average_cost_uom_code = display_uom_code
                    average_cost_uom_name = display_uom_name
                average_cost_after = average_cost_after.quantize(
                    Decimal("0.000001")
                )

            result.append({
                "id": movement.id,
                "product_variant_id": movement.product_variant_id,
                "product_name": product_name,
                "base_uom_id": base_uom.id,
                "base_uom_code": base_uom.code,
                "quantity_scale": int(quantity_scale),
                "quantity_step": canonical_quantity(quantity_step),
                "type": movement.reference_type,
                "quantity": canonical_quantity(quantity_packs),
                "balance_before": total_balance_before,
                "balance_after": total_balance_after,
                "balance_scope": (
                    "PRODUCT_LOCATION"
                    if aggregate_snapshot is not None
                    else None
                ),
                "batch_number": (
                    batch_number_by_id.get(int(movement.batch_id))
                    if movement.batch_id is not None
                    else None
                ),
                "display_uom_id": display_uom_id,
                "display_uom_code": display_uom_code,
                "display_uom_name": display_uom_name,
                "display_factor_to_base": canonical_quantity(display_factor),
                "currency_code": str(ledger_currency_code).upper(),
                "cost_method": (
                    str(cost_event.method) if cost_event is not None else None
                ),
                "input_quantity": (
                    canonical_quantity(cost_event.input_quantity)
                    if cost_event is not None
                    and cost_event.input_quantity is not None
                    else None
                ),
                "input_uom_code": (
                    str(input_uom.code) if input_uom is not None else None
                ),
                "input_uom_name": (
                    str(input_uom.name) if input_uom is not None else None
                ),
                "input_unit_cost": (
                    format(
                        Decimal(cost_event.input_unit_cost).quantize(
                            Decimal("0.000001")
                        ),
                        "f",
                    )
                    if cost_event is not None
                    and cost_event.input_unit_cost is not None
                    else None
                ),
                "total_cost": (
                    format(
                        Decimal(cost_event.total_cost).quantize(
                            Decimal("0.000001")
                        ),
                        "f",
                    )
                    if cost_event is not None
                    else None
                ),
                "average_cost_after": (
                    format(average_cost_after, "f")
                    if average_cost_after is not None
                    else None
                ),
                "average_cost_uom_code": average_cost_uom_code,
                "average_cost_uom_name": average_cost_uom_name,
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
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await access.require(('location.read', 'dispatch.read'), location_id)

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


# Catalog ownership moved to api/catalog.py; operational consumers use /catalog/variants.

# =================================================================================
# 8. تعديل فاتورة توريد - Correction append-only على المحرك الموحد
# =================================================================================
@router.post(
    "/warehouse/ledger/{entry_id}/adjust",
    response_model=MessageResponse,
    status_code=200,
)
async def adjust_warehouse_entry(
    entry_id: int,
    payload: AdjustWarehouseEntryRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await require_inbound_adjustment(access, entry_id)

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
        new_total_quantity = payload.new_total_quantity
        if new_total_quantity < 0:
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

        variant_uom_id = await db.scalar(
            select(ProductVariant.base_uom_id).where(
                ProductVariant.company_id == company_id,
                ProductVariant.id == original.product_variant_id,
            )
        )
        if variant_uom_id is None or int(variant_uom_id) != payload.uom_id:
            raise HTTPException(
                status_code=422,
                detail={"code": "UOM_MISMATCH", "message": "التصحيح يجب أن يستخدم وحدة أساس الصنف.", "context": {"expected_uom_id": variant_uom_id}},
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

        current_total_quantity = Decimal("0")

        for movement in invoice_movements:
            quantity = Decimal(movement.quantity)

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
                current_total_quantity += quantity
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
                current_total_quantity += quantity
            elif is_negative_correction:
                current_total_quantity -= quantity
            else:
                raise HTTPException(
                    status_code=409,
                    detail="تم اكتشاف قيد تصحيح غير متسق؛ أوقف التعديل وراجع السجل."
                )

        if current_total_quantity < 0:
            raise HTTPException(
                status_code=409,
                detail="الصافي التاريخي للفاتورة أصبح سالباً؛ تم رفض أي تعديل إضافي."
            )

        delta = new_total_quantity - current_total_quantity

        if delta == 0:
            await db.commit()
            return {
                "message": "لا يوجد تغيير في الكمية. الصافي الحالي مطابق لما أدخلته."
            }

        idempotency_raw = (
            f"{company_id}|{normalized_ref}|{original.product_variant_id}|"
            f"{batch_id}|{canonical_quantity(current_total_quantity)}|{canonical_quantity(new_total_quantity)}"
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
                    "total_quantity": canonical_quantity(current_total_quantity),
                    "uom_id": payload.uom_id,
                },
                ensure_ascii=False
            ),
            new_value=json.dumps(
                {
                    "total_quantity": canonical_quantity(new_total_quantity),
                    "delta": canonical_quantity(delta),
                    "uom_id": payload.uom_id,
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




# STAGE4E2A_TRANSFER_POLICY_GUARD
_TRANSFER_POLICY_VALIDATION_CODES = frozenset({
    "TRANSFER_POLICY_PAYLOAD_INVALID",
    "TRANSFER_POLICY_LOCATION_INVALID",
    "TRANSFER_POLICY_LOCATION_TYPE_INVALID",
})


def _transfer_policy_to_payload(policy: Optional[TenantOperationalPolicy]):
    if policy is None:
        return None
    return {
        "id": int(policy.id),
        "policy_code": str(policy.policy_code),
        "schema_version": int(policy.schema_version),
        "revision": int(policy.revision),
        "validated_payload": dict(policy.validated_payload or {}),
        "status": str(policy.status),
        "effective_from": (
            policy.effective_from.isoformat()
            if policy.effective_from is not None
            else None
        ),
        "effective_to": (
            policy.effective_to.isoformat()
            if policy.effective_to is not None
            else None
        ),
        "approved_by": (
            int(policy.approved_by)
            if policy.approved_by is not None
            else None
        ),
        "approved_at": (
            policy.approved_at.isoformat()
            if policy.approved_at is not None
            else None
        ),
        "created_by": int(policy.created_by),
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


async def _require_transfer_policy_location_access(
    access: InventoryAccess,
    validated_payload: dict,
) -> None:
    location_ids = sorted({
        int(validated_payload["quarantine_location_id"]),
        int(validated_payload["disposal_location_id"]),
        int(validated_payload["vendor_return_staging_location_id"]),
    })
    for location_id in location_ids:
        # Policy administration itself is company-scoped; referenced locations
        # must still be visible to the actor through the normal location ACL.
        await access.require(
            "location.read",
            location_id,
        )


@router.get(
    "/warehouse/operational-policy/transfer-destinations",
    response_model=TransferDestinationPolicyStateResponse,
    status_code=200,
)
async def get_transfer_destination_policy(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.transfer_policy.manage", any_location=True)

    try:
        draft, published = await get_transfer_destination_policy_state(
            db,
            company_id=current_admin.company_id,
        )
        return {
            "draft": _transfer_policy_to_payload(draft),
            "published": _transfer_policy_to_payload(published),
        }
    except InventoryMutationError as exc:
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_READ_FAILED",
                str(exc),
            ),
        ) from exc


@router.put(
    "/warehouse/operational-policy/transfer-destinations/draft",
    response_model=TransferDestinationPolicyMutationResponse,
    status_code=200,
)
async def save_transfer_destination_policy(
    payload: TransferDestinationPolicySaveRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.transfer_policy.manage", any_location=True)
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(payload)
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="TRANSFER_DESTINATION_POLICY_DRAFT_SAVE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        policy = await save_transfer_destination_policy_draft(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            request_id=payload.request_id,
            expected_revision=payload.expected_revision,
            payload=payload.payload.model_dump(mode="python"),
        )
        await _require_transfer_policy_location_access(
            access,
            dict(policy.validated_payload),
        )

        response = {
            "message": "تم حفظ Draft سياسة وجهات التحويل بعد التحقق الصارم من المواقع.",
            "policy": _transfer_policy_to_payload(policy),
        }
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response

    except InventoryRuleError as exc:
        await db.rollback()
        status_code = (
            400
            if exc.code in _TRANSFER_POLICY_VALIDATION_CODES
            else 409
        )
        raise HTTPException(
            status_code=status_code,
            detail=exc.as_detail(),
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_SAVE_REJECTED",
                str(exc),
            ),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_CONFLICT",
                "حدث تعارض متزامن أثناء حفظ السياسة.",
            ),
        ) from exc


@router.post(
    "/warehouse/operational-policy/transfer-destinations/{policy_id}/publish",
    response_model=TransferDestinationPolicyMutationResponse,
    status_code=200,
)
async def publish_transfer_destination_policy_endpoint(
    policy_id: int,
    payload: TransferDestinationPolicyPublishRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.transfer_policy.manage", any_location=True)
    company_id = current_admin.company_id

    try:
        request_hash = _stable_request_hash(
            payload,
            context={"policy_id": int(policy_id)},
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="TRANSFER_DESTINATION_POLICY_PUBLISH",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        policy = await publish_transfer_destination_policy(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            policy_id=policy_id,
            expected_revision=payload.expected_revision,
            request_id=payload.request_id,
        )
        await _require_transfer_policy_location_access(
            access,
            dict(policy.validated_payload),
        )

        response = {
            "message": "تم نشر سياسة وجهات التحويل بعد إعادة التحقق من المواقع.",
            "policy": _transfer_policy_to_payload(policy),
        }
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response

    except InventoryRuleError as exc:
        await db.rollback()
        if exc.code in _TRANSFER_POLICY_VALIDATION_CODES:
            status_code = 400
        elif exc.code == "TRANSFER_POLICY_DRAFT_NOT_FOUND":
            status_code = 404
        else:
            status_code = 409
        raise HTTPException(
            status_code=status_code,
            detail=exc.as_detail(),
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_PUBLISH_REJECTED",
                str(exc),
            ),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_POLICY_CONFLICT",
                "حدث تعارض متزامن أثناء نشر السياسة.",
            ),
        ) from exc


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



# PATCH: STAGE4D_BATCH_DISPOSITION_PORTION_STATUS

@router.post(
    "/warehouse/batches/{batch_id}/disposition",
    response_model=BatchDispositionMutationResponse,
    status_code=200,
)
async def change_batch_disposition(
    batch_id: int,
    payload: BatchDispositionChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("batch.disposition")

    if batch_id <= 0:
        raise HTTPException(
            status_code=422,
            detail=inventory_business_error(
                "BATCH_ID_INVALID",
                "batch_id يجب أن يكون موجباً.",
                context={"batch_id": batch_id},
            ),
        )

    company_id = current_admin.company_id
    try:
        request_hash = _stable_request_hash(
            payload,
            context={"batch_id": int(batch_id)},
        )
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="BATCH_DISPOSITION_CHANGE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        batch = await change_product_batch_disposition(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            batch_id=batch_id,
            expected_revision=payload.expected_revision,
            target_disposition=payload.disposition,
            reason=payload.reason,
            request_id=payload.request_id,
        )

        response_payload = {
            "message": "تم تحديث disposition للدفعة دون تغيير Bucket الرصيد تلقائياً.",
            "batch_id": int(batch.id),
            "product_variant_id": int(batch.product_variant_id),
            "batch_number": str(batch.batch_number),
            "disposition": str(batch.disposition),
            "disposition_reason": batch.disposition_reason,
            "disposition_revision": int(batch.disposition_revision),
            "updated_at": batch.updated_at.isoformat(),
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except InventoryRuleError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "BATCH_DISPOSITION_REJECTED",
                str(exc),
                context={"batch_id": batch_id},
            ),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض أثناء تغيير disposition للدفعة", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "BATCH_DISPOSITION_CONFLICT",
                "حدث تعارض متزامن أثناء تغيير حالة الدفعة؛ أعد المحاولة.",
                context={"batch_id": batch_id},
            ),
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("خطأ داخلي أثناء تغيير disposition للدفعة", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء تحديث حالة الدفعة.",
        ) from exc


@router.post(
    "/warehouse/inventory/status-change",
    response_model=InventoryStatusChangeResponse,
    status_code=200,
)
async def change_inventory_status(
    payload: InventoryStatusChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require("inventory.status_change", payload.location_id)

    company_id = current_admin.company_id
    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="INVENTORY_STATUS_CHANGE",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        base_uom_id = (
            await db.execute(
                select(ProductVariant.base_uom_id).filter(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id == payload.product_variant_id,
                )
            )
        ).scalar_one_or_none()
        if base_uom_id is None:
            raise HTTPException(
                status_code=404,
                detail=inventory_business_error(
                    "PRODUCT_NOT_FOUND",
                    "الصنف غير موجود أو لا يتبع الشركة.",
                    context={
                        "product_variant_id": int(payload.product_variant_id),
                    },
                ),
            )
        if int(base_uom_id) != int(payload.uom_id):
            raise HTTPException(
                status_code=422,
                detail=inventory_business_error(
                    "UOM_MISMATCH",
                    "تغيير حالة المخزون يجب أن يستخدم وحدة أساس الصنف.",
                    context={
                        "product_variant_id": int(payload.product_variant_id),
                        "expected_uom_id": int(base_uom_id),
                    },
                ),
            )

        movement = await apply_inventory_movement(
            db,
            company_id=company_id,
            performed_by=current_admin.id,
            product_variant_id=payload.product_variant_id,
            batch_id=payload.batch_id,
            quantity=payload.quantity,
            movement_kind="STATUS_CHANGE",
            reference_type="STATUS_RECLASSIFICATION",
            reference_id=str(payload.request_id),
            idempotency_key=f"STATUS-{payload.request_id}",
            source_location_id=payload.location_id,
            destination_location_id=payload.location_id,
            source_stock_status=payload.source_status,
            destination_stock_status=payload.destination_status,
            notes=payload.reason,
        )

        response_payload = {
            "message": "تم تغيير Bucket الرصيد عبر Unified Inventory Movement Engine.",
            "movement_id": int(movement.id),
            "source_status": str(movement.source_stock_status),
            "destination_status": str(movement.destination_stock_status),
        }
        complete_idempotent_operation(idempotency_record, response_payload)
        await db.commit()
        return response_payload

    except InventoryRuleError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INVENTORY_STATUS_CHANGE_REJECTED",
                str(exc),
                context={
                    "location_id": int(payload.location_id),
                    "product_variant_id": int(payload.product_variant_id),
                    "batch_id": int(payload.batch_id),
                },
            ),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض أثناء تغيير Bucket المخزون", exc_info=True)
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "INVENTORY_STATUS_CHANGE_CONFLICT",
                "حدث تعارض متزامن أثناء تغيير حالة الرصيد؛ أعد المحاولة.",
                context={
                    "location_id": int(payload.location_id),
                    "product_variant_id": int(payload.product_variant_id),
                    "batch_id": int(payload.batch_id),
                },
            ),
        ) from exc
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("خطأ داخلي أثناء تغيير Bucket المخزون", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="خطأ داخلي أثناء تغيير حالة الرصيد.",
        ) from exc


@router.get(
    "/warehouse/unified/transfer/locations",
    response_model=List[UnifiedTransferLocationItem],
    status_code=200,
)
async def list_unified_transfer_locations(
    purpose: Optional[str] = Query(default=None, pattern='^(source|destination)$'),
    search: Optional[str] = Query(
        default=None,
        min_length=2,
        max_length=100,
    ),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require(('transfer.read', 'transfer.send', 'transfer.destination'), any_location=True)

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
            access.location_filter('transfer.send' if purpose == 'source' else
                'transfer.destination' if purpose == 'destination' else
                ('transfer.read', 'transfer.send', 'transfer.destination')),
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
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('transfer.send', location_id)

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

    sellable_batch_join = and_(
        ProductBatch.company_id == InventoryBalance.company_id,
        ProductBatch.product_variant_id
        == InventoryBalance.product_variant_id,
        ProductBatch.id == InventoryBalance.batch_id,
    )
    sellable_batch = batch_sellability_predicate(
        as_of_date,
        expiry_control_mode=ProductVariant.expiry_control_mode,
        minimum_remaining_shelf_life_days=(
            InventoryStockPolicy.minimum_remaining_shelf_life_days
        ),
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
            ProductVariant.name,
            ProductVariant.sku,
            ProductVariant.base_uom_id,
            UOM.code.label("base_uom_code"),
            UOM.name.label("base_uom_name"),
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
            available_expression.label("available_quantity"),
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
            sellable_batch_join,
        )
        .join(UOM, UOM.id == ProductVariant.base_uom_id)
        .join(
            ProductLocation,
            and_(
                ProductLocation.company_id == ProductVariant.company_id,
                ProductLocation.product_variant_id == ProductVariant.id,
                ProductLocation.location_id == location_id,
            ),
        )
        .outerjoin(
            InventoryStockPolicy,
            and_(
                InventoryStockPolicy.company_id
                == ProductVariant.company_id,
                InventoryStockPolicy.location_id == location_id,
                InventoryStockPolicy.product_variant_id
                == ProductVariant.id,
                InventoryStockPolicy.is_active.is_(True),
            ),
        )
        .filter(
            ProductVariant.company_id == company_id,
            product_capability_predicate(ProductVariant, WAREHOUSE_BALANCING),
            sellable_batch,
            ProductLocation.operational_flags['outbound_enabled'].as_boolean().is_(True),
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
            InventoryBalance.stock_status == 'AVAILABLE',
            ~active_lock_exists,
        )
        .group_by(
            ProductVariant.id,
            ProductVariant.name,
            ProductVariant.sku,
            ProductVariant.base_uom_id,
            UOM.code,
            UOM.name,
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
        )
        .having(available_expression > 0)
    )

    if clean_search:
        pattern = f"%{_escape_like(clean_search)}%"
        stmt = stmt.filter(
            or_(
                func.lower(ProductVariant.name).like(
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
                ProductVariant.name > cursor_name,
                and_(
                    ProductVariant.name == cursor_name,
                    ProductVariant.id > cursor_id,
                ),
            )
        )

    rows = (
        await db.execute(
            stmt.order_by(
                ProductVariant.name.asc(),
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
            variant_name=str(last_row.name),
            variant_id=int(last_row.id),
            scope=scope,
        )

    return {
        "items": [
            {
                "id": int(row.id),
                "name": str(row.name),
                "sku": row.sku,
                "base_uom_id": int(row.base_uom_id),
                "base_uom_code": str(row.base_uom_code),
                "base_uom_name": str(row.base_uom_name),
                "quantity_scale": int(row.quantity_scale),
                "quantity_step": canonical_quantity(row.quantity_step),
                "available_quantity": canonical_quantity(row.available_quantity or 0),
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
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('inventory.fefo_override', location_id)

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
            select(ProductVariant.id).join(
                ProductLocation,
                and_(
                    ProductLocation.company_id == ProductVariant.company_id,
                    ProductLocation.product_variant_id == ProductVariant.id,
                    ProductLocation.location_id == location_id,
                ),
            ).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id == product_variant_id,
                product_capability_predicate(ProductVariant, WAREHOUSE_BALANCING),
                ProductLocation.operational_flags['outbound_enabled'].as_boolean().is_(True),
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
                available_expression.label("available_quantity"),
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
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == ProductBatch.company_id,
                    ProductVariant.id == ProductBatch.product_variant_id,
                ),
            )
            .outerjoin(
                InventoryStockPolicy,
                and_(
                    InventoryStockPolicy.company_id == ProductBatch.company_id,
                    InventoryStockPolicy.location_id == location_id,
                    InventoryStockPolicy.product_variant_id
                    == ProductBatch.product_variant_id,
                    InventoryStockPolicy.is_active.is_(True),
                ),
            )
            .filter(
                ProductBatch.company_id == company_id,
                ProductBatch.product_variant_id
                == product_variant_id,
                batch_sellability_predicate(
                    as_of_date,
                    expiry_control_mode=ProductVariant.expiry_control_mode,
                    minimum_remaining_shelf_life_days=(
                        InventoryStockPolicy.minimum_remaining_shelf_life_days
                    ),
                ),
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
                ProductBatch.expiry_date.asc().nulls_last(),
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
                "available_quantity": canonical_quantity(row.available_quantity or 0),
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
        int(header_id): (int(line_count), Decimal(total_quantity or 0))
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
            (0, Decimal("0")),
        )
        result.append({
            "id": int(header.id),
            "reference_number": str(header.reference_number),
            "source_location_id": int(header.source_location_id),
            "source_location_name": location_map[int(header.source_location_id)],
            "destination_location_id": int(header.destination_location_id),
            "destination_location_name": location_map[int(header.destination_location_id)],
            "transfer_purpose": str(header.transfer_purpose),
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
            "total_quantity": canonical_quantity(total_quantity),
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
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await access.require('transfer.read', location_id, any_location=location_id is None)

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
                    InventoryLocation.location_type.in_(
                        ['WAREHOUSE', 'VEHICLE', 'SCRAP']
                    ),
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
        transfer_filter(access),
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
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    await require_transfer(access, 'transfer.read', header_id)

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
                ProductVariant.name,
                ProductVariant.base_uom_id,
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
            "quantity": canonical_quantity(line.quantity),
            "uom_id": int(base_uom_id),
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
        for line, product_name, base_uom_id, batch_number, expiry_date in line_rows
    ]

    if not lines:
        raise RuntimeError(
            "Transfer invariant violated: transit transfer has no lines."
        )

    return {
        "transfer": serialized[0],
        "lines": lines,
    }


# STAGE4E2B2_SPECIAL_TRANSFER_EXECUTION
@router.post(
    "/warehouse/unified/transfer/special/dispatch",
    response_model=SpecialTransferDispatchResponse,
    status_code=200,
)
async def special_transfer_dispatch(
    payload: SpecialTransferDispatchRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    company_id = current_admin.company_id
    purpose = str(payload.transfer_purpose).upper()
    permission_code = SPECIAL_TRANSFER_PERMISSION.get(purpose)
    if permission_code is None:
        raise HTTPException(
            status_code=422,
            detail=inventory_business_error(
                "SPECIAL_TRANSFER_PURPOSE_INVALID",
                "غرض التحويل الخاص غير صالح.",
                context={"transfer_purpose": purpose},
            ),
        )

    access = InventoryAccess(db, current_admin)
    await access.require(permission_code)
    await access.require("transfer.send", payload.source_location_id)

    try:
        request_hash = _stable_request_hash(payload)
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="SPECIAL_TRANSFER_DISPATCH",
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        requested_variant_ids = sorted({
            int(item.product_variant_id)
            for item in payload.items
        })
        await acquire_product_lifecycle_guards(
            db,
            company_id,
            requested_variant_ids,
            exclusive=False,
        )

        transit_location = await ensure_system_transit_location(
            db,
            company_id,
        )
        transit_location_id = int(transit_location.id)

        direction = await resolve_special_transfer_direction_context(
            db,
            company_id=company_id,
            source_location_id=payload.source_location_id,
            transfer_purpose=purpose,
            additional_location_ids=[transit_location_id],
        )

        destination_location_id = int(
            direction["destination_location_id"]
        )
        await access.require(
            "transfer.destination",
            destination_location_id,
        )

        as_of_date = await get_company_local_date(db, company_id)
        source_lines = await validate_special_transfer_source_items_locked(
            db,
            company_id=company_id,
            source_location_id=payload.source_location_id,
            transfer_purpose=purpose,
            items=list(payload.items),
            as_of_date=as_of_date,
        )

        transfer_ref = f"SPTR-{uuid.uuid4().hex.upper()}"
        header = InventoryTransferHeader(
            company_id=company_id,
            reference_number=transfer_ref,
            source_location_id=payload.source_location_id,
            destination_location_id=destination_location_id,
            transit_location_id=transit_location_id,
            workflow_type="TRANSIT",
            status="IN_TRANSIT",
            transfer_purpose=purpose,
            commercial_context={
                "schema_version": 1,
                "commercial_context_id": None,
                "tenant_policy_code": TRANSFER_DESTINATION_POLICY_CODE,
                "tenant_policy_id": int(direction["tenant_policy_id"]),
                "tenant_policy_revision": int(
                    direction["tenant_policy_revision"]
                ),
                "source_location_type": str(
                    direction["source_location_type"]
                ),
                "destination_location_type": str(
                    direction["destination_location_type"]
                ),
                "transfer_purpose": purpose,
            },
            tenant_policy_id=int(direction["tenant_policy_id"]),
            tenant_policy_revision=int(
                direction["tenant_policy_revision"]
            ),
            dispatched_by=current_admin.id,
            notes=payload.notes,
        )
        db.add(header)
        await db.flush()

        transfer_lines = []
        movement_specs = []
        for line_no, line in enumerate(source_lines, start=1):
            transfer_lines.append(
                InventoryTransferLine(
                    company_id=company_id,
                    transfer_header_id=header.id,
                    product_variant_id=line["product_variant_id"],
                    batch_id=line["batch_id"],
                    quantity=line["quantity"],
                    source_stock_status=line["source_stock_status"],
                    lifecycle_revision_snapshot=(
                        line["lifecycle_revision_snapshot"]
                    ),
                    lifecycle_status_snapshot=(
                        line["lifecycle_status_snapshot"]
                    ),
                    operational_hold_snapshot=(
                        line["operational_hold_snapshot"]
                    ),
                    fefo_override_reason_id=None,
                    fefo_overridden_by=None,
                    fefo_override_note=None,
                )
            )
            movement_specs.append({
                "product_variant_id": line["product_variant_id"],
                "batch_id": line["batch_id"],
                "quantity": line["quantity"],
                "movement_kind": "PHYSICAL",
                "reference_type": "SPECIAL_TRANSFER_DISPATCH",
                "reference_id": transfer_ref,
                "idempotency_key": (
                    f"SPTR-DISP-{header.id}-{line_no}"
                ),
                "source_location_id": payload.source_location_id,
                "destination_location_id": transit_location_id,
                "source_stock_status": line["source_stock_status"],
                "destination_stock_status": line["source_stock_status"],
                "transfer_header_id": header.id,
                "notes": payload.notes,
            })

        if not movement_specs:
            raise InventoryMutationError(
                "التحويل الخاص لم ينتج أي حركة مخزون."
            )

        db.add_all(transfer_lines)
        await apply_inventory_movements_batch(
            db,
            company_id=company_id,
            performed_by=current_admin.id,
            movements=movement_specs,
        )

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Transfer_{header.id}",
            action_type="SPECIAL_TRANSFER_DISPATCHED",
            old_value=None,
            new_value=(
                f"purpose={purpose}; "
                f"policy={direction['tenant_policy_id']}:"
                f"{direction['tenant_policy_revision']}; "
                f"source={payload.source_location_id}; "
                f"destination={destination_location_id}"
            ),
        ))

        response_payload = {
            "message": "تم إنشاء التحويل الخاص ونقل المخزون إلى IN_TRANSIT.",
            "transfer_reference": transfer_ref,
            "header_id": int(header.id),
            "transfer_purpose": purpose,
            "source_location_id": int(payload.source_location_id),
            "destination_location_id": destination_location_id,
            "tenant_policy_id": int(direction["tenant_policy_id"]),
            "tenant_policy_revision": int(
                direction["tenant_policy_revision"]
            ),
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
    except InventoryRuleError as exc:
        await db.rollback()
        status_code = (
            422
            if exc.code == "SPECIAL_TRANSFER_UOM_MISMATCH"
            else 409
        )
        raise HTTPException(
            status_code=status_code,
            detail=exc.as_detail(),
        ) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "SPECIAL_TRANSFER_REJECTED",
                str(exc),
                context={"transfer_purpose": purpose},
            ),
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning(
            "تعارض متزامن أثناء إنشاء التحويل الخاص",
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "SPECIAL_TRANSFER_CONFLICT",
                "حدث تعارض متزامن؛ لم يتم حفظ أي جزء من التحويل.",
                context={"transfer_purpose": purpose},
            ),
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.error(
            "خطأ داخلي أثناء إنشاء التحويل الخاص",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=inventory_business_error(
                "SPECIAL_TRANSFER_INTERNAL_ERROR",
                "خطأ داخلي أثناء إنشاء التحويل الخاص.",
            ),
        ) from exc

# Stage 4E generic TRANSIT endpoint owns only REPLENISHMENT and
# WAREHOUSE_BALANCING. Special purposes use the dedicated policy-bound command.
_GENERIC_TRANSFER_PURPOSE_CAPABILITY = {
    "REPLENISHMENT": REPLENISHMENT_NEW,
    "WAREHOUSE_BALANCING": WAREHOUSE_BALANCING,
}


@router.post("/warehouse/unified/transfer/dispatch", status_code=200)
async def unified_transfer_dispatch(
    payload: UnifiedDispatchRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await access.require('transfer.send', payload.source_location_id)
    await access.require('transfer.destination', payload.destination_location_id)
    if any(item.is_fefo_override for item in payload.items):
        await access.require('inventory.fefo_override', payload.source_location_id)

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
        await acquire_product_lifecycle_guards(
            db, company_id, requested_variant_ids, exclusive=False,
        )
        location_types = dict((await db.execute(
            select(InventoryLocation.id, InventoryLocation.location_type).where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id.in_([payload.source_location_id, payload.destination_location_id]),
            )
        )).all())

        transfer_purpose = str(payload.transfer_purpose).upper()
        lifecycle_capability = _GENERIC_TRANSFER_PURPOSE_CAPABILITY.get(
            transfer_purpose
        )
        if lifecycle_capability is None:
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "TRANSFER_PURPOSE_WORKFLOW_REQUIRED",
                    "غرض الحوالة المطلوب يحتاج Workflow واتجاهاً مخصصاً ولا يجوز تمريره عبر الحوالة العامة.",
                    context={"transfer_purpose": transfer_purpose},
                ),
            )

        source_type = location_types.get(payload.source_location_id)
        destination_type = location_types.get(payload.destination_location_id)
        if source_type != "WAREHOUSE" or destination_type != "WAREHOUSE":
            raise HTTPException(
                status_code=409,
                detail=inventory_business_error(
                    "TRANSFER_DIRECTION_BLOCKED",
                    "REPLENISHMENT/WAREHOUSE_BALANCING في المسار العام يتطلبان WAREHOUSE -> WAREHOUSE.",
                    context={
                        "transfer_purpose": transfer_purpose,
                        "source_location_type": source_type,
                        "destination_location_type": destination_type,
                    },
                ),
            )

        variant_uom_rows = (
            await db.execute(
                select(
                    ProductVariant.id,
                    ProductVariant.base_uom_id,
                    ProductVariant.lifecycle_status,
                    ProductVariant.operational_hold,
                    ProductVariant.lifecycle_revision,
                ).filter(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(requested_variant_ids),
                )
            )
        ).all()
        variant_uoms = {}
        variant_context = {}
        retiring_balancing_variant_ids = []

        for row in variant_uom_rows:
            lifecycle_status = str(row.lifecycle_status or "").upper()
            operational_hold = str(row.operational_hold or "").upper()

            retiring_balancing_candidate = (
                transfer_purpose == "WAREHOUSE_BALANCING"
                and lifecycle_status == "RETIRING"
            )

            if retiring_balancing_candidate:
                # This is the single owner-approved RETIRING exception.
                # RECALL remains a hard safety block.
                if operational_hold == "RECALL":
                    raise HTTPException(
                        status_code=409,
                        detail=inventory_business_error(
                            "PRODUCT_RECALL_WAREHOUSE_BALANCING_BLOCKED",
                            "الصنف المستدعى لا يقبل WAREHOUSE_BALANCING جديداً.",
                            context={
                                "product_variant_id": int(row.id),
                                "transfer_purpose": transfer_purpose,
                            },
                        ),
                    )
                retiring_balancing_variant_ids.append(int(row.id))
            else:
                decision = evaluate_product_capability(
                    lifecycle_status,
                    operational_hold,
                    lifecycle_capability,
                )
                if not decision.allowed:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": decision.code,
                            "message": "حالة الصنف لا تسمح بالحوالة المطلوبة.",
                            "context": {
                                "product_variant_id": int(row.id),
                                "transfer_purpose": transfer_purpose,
                            },
                        },
                    )

            variant_uoms[int(row.id)] = int(row.base_uom_id)
            variant_context[int(row.id)] = row

        if set(variant_uoms) != requested_variant_ids:
            raise HTTPException(
                status_code=400,
                detail="يوجد صنف غير صالح أو غير فعال أو لا يتبع شركتك ضمن الحوالة."
            )

        retiring_balancing_policy = None
        if retiring_balancing_variant_ids:
            await access.require("transfer.warehouse_balancing_override")
            try:
                retiring_balancing_policy = (
                    await resolve_retiring_warehouse_balancing_override_context(
                        db,
                        company_id=company_id,
                    )
                )
            except InventoryRuleError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=exc.as_detail(),
                ) from exc

        assignment_rows = (await db.execute(
            select(
                ProductLocation.location_id,
                ProductLocation.product_variant_id,
                ProductLocation.operational_flags,
            ).where(
                ProductLocation.company_id == company_id,
                ProductLocation.product_variant_id.in_(requested_variant_ids),
                ProductLocation.location_id.in_([payload.source_location_id, payload.destination_location_id]),
            )
        )).all()
        assignments = {
            (int(row.location_id), int(row.product_variant_id)): row.operational_flags
            for row in assignment_rows
        }
        missing_source = sorted(
            variant_id for variant_id in requested_variant_ids
            if not product_location_allows(
                assignments.get((payload.source_location_id, variant_id)),
                lifecycle_capability,
            )
        )
        missing_destination = sorted(
            variant_id for variant_id in requested_variant_ids
            if location_types.get(payload.destination_location_id) == 'WAREHOUSE'
            and not product_location_allows(
                assignments.get((payload.destination_location_id, variant_id)),
                INBOUND_NEW,
            )
        )
        if missing_source or missing_destination:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PRODUCT_LOCATION_REQUIRED",
                    "message": "الحوالة تتطلب ربطاً تشغيلياً صريحاً للصنف بالموقع.",
                    "context": {
                        "source_location_id": payload.source_location_id,
                        "destination_location_id": payload.destination_location_id,
                        "source_product_variant_ids": missing_source,
                        "destination_product_variant_ids": missing_destination,
                    },
                },
            )
        for item in payload.items:
            if item.uom_id != variant_uoms[item.product_variant_id]:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "UOM_MISMATCH", "message": "كمية الحوالة يجب أن تستخدم وحدة أساس الصنف.", "context": {"product_variant_id": item.product_variant_id, "expected_uom_id": variant_uoms[item.product_variant_id]}},
                )

        transit_location = await ensure_system_transit_location(db, company_id)
        transit_location_id = int(transit_location.id)

        await acquire_inventory_location_guards(
            db,
            company_id,
            [payload.source_location_id, payload.destination_location_id, transit_location_id],
        )
        await _verify_location_ownership(
            db,
            company_id,
            payload.source_location_id,
            payload.destination_location_id,
            allowed_types=['WAREHOUSE', 'VEHICLE'],
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
                        select(
                            ProductBatch.product_variant_id,
                            ProductBatch.id,
                        )
                        .join(
                            ProductVariant,
                            and_(
                                ProductVariant.company_id
                                == ProductBatch.company_id,
                                ProductVariant.id
                                == ProductBatch.product_variant_id,
                            ),
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
                        .outerjoin(
                            InventoryStockPolicy,
                            and_(
                                InventoryStockPolicy.company_id
                                == ProductBatch.company_id,
                                InventoryStockPolicy.location_id
                                == payload.source_location_id,
                                InventoryStockPolicy.product_variant_id
                                == ProductBatch.product_variant_id,
                                InventoryStockPolicy.is_active.is_(True),
                            ),
                        )
                        .filter(
                            ProductBatch.company_id == company_id,
                            tuple_(
                                ProductBatch.product_variant_id,
                                ProductBatch.id,
                            ).in_(sorted(override_batch_pairs)),
                            batch_sellability_predicate(
                                as_of_date,
                                expiry_control_mode=(
                                    ProductVariant.expiry_control_mode
                                ),
                                minimum_remaining_shelf_life_days=(
                                    InventoryStockPolicy.minimum_remaining_shelf_life_days
                                ),
                            ),
                            InventoryBalance.company_id == company_id,
                            InventoryBalance.location_id
                            == payload.source_location_id,
                            InventoryBalance.stock_status == "AVAILABLE",
                            InventoryBalance.on_hand_quantity
                            > InventoryBalance.reserved_quantity,
                        )
                        .order_by(
                            ProductBatch.product_variant_id.asc(),
                            ProductBatch.id.asc(),
                        )
                        .with_for_update(
                            read=True,
                            of=ProductBatch,
                        )
                    )
                ).all()
            )
            if valid_override_pairs != override_batch_pairs:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "إحدى دفعات تجاوز FEFO غير مؤهلة للبيع/التحميل "
                        "بسبب disposition/expiry/shelf-life أو لا تتبع الصنف/الشركة."
                    )
                )

        normal_allocations = {}
        if normal_items:
            normal_allocations = await allocate_fefo_inventory_batch(
                db,
                company_id=company_id,
                location_id=payload.source_location_id,
                requests={int(item.product_variant_id): item.quantity for item in normal_items},
                as_of_date=as_of_date,
                require_full=True,
            )

        override_expected = {}
        if override_items:
            override_expected = await allocate_fefo_inventory_batch(
                db,
                company_id=company_id,
                location_id=payload.source_location_id,
                requests={int(item.product_variant_id): item.quantity for item in override_items},
                as_of_date=as_of_date,
                require_full=False,
            )

        transfer_ref = f"TRN-{uuid.uuid4().hex.upper()}"
        balancing_policy_id = (
            int(retiring_balancing_policy["tenant_policy_id"])
            if retiring_balancing_policy is not None
            else None
        )
        balancing_policy_revision = (
            int(retiring_balancing_policy["tenant_policy_revision"])
            if retiring_balancing_policy is not None
            else None
        )

        header = InventoryTransferHeader(
            company_id=company_id,
            reference_number=transfer_ref,
            source_location_id=payload.source_location_id,
            destination_location_id=payload.destination_location_id,
            transit_location_id=transit_location_id,
            workflow_type='TRANSIT',
            status='IN_TRANSIT',
            transfer_purpose=transfer_purpose,
            commercial_context={
                "schema_version": 1,
                "commercial_context_id": None,
                "tenant_policy_code": (
                    TRANSFER_DESTINATION_POLICY_CODE
                    if retiring_balancing_policy is not None
                    else None
                ),
                "tenant_policy_id": balancing_policy_id,
                "tenant_policy_revision": balancing_policy_revision,
                "retiring_warehouse_balancing_override": (
                    retiring_balancing_policy is not None
                ),
                "retiring_product_variant_ids": (
                    sorted(retiring_balancing_variant_ids)
                    if retiring_balancing_policy is not None
                    else []
                ),
                "source_location_type": source_type,
                "destination_location_type": destination_type,
                "transfer_purpose": transfer_purpose,
            },
            tenant_policy_id=balancing_policy_id,
            tenant_policy_revision=balancing_policy_revision,
            dispatched_by=current_admin.id,
            notes=payload.notes or None
        )
        db.add(header)
        await db.flush()

        if retiring_balancing_policy is not None:
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"Transfer_{header.id}",
                action_type="RETIRING_WAREHOUSE_BALANCING_OVERRIDE",
                old_value=None,
                new_value=json.dumps(
                    {
                        "transfer_purpose": transfer_purpose,
                        "tenant_policy_id": balancing_policy_id,
                        "tenant_policy_revision": balancing_policy_revision,
                        "product_variant_ids": sorted(
                            retiring_balancing_variant_ids
                        ),
                        "source_location_id": int(
                            payload.source_location_id
                        ),
                        "destination_location_id": int(
                            payload.destination_location_id
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ))

        transfer_lines = []
        movement_specs = []
        for item in ordered_items:
            if item.is_fefo_override:
                allocations = [(int(item.override_batch_id), item.quantity)]
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
                variant_state = variant_context[int(item.product_variant_id)]
                transfer_lines.append(InventoryTransferLine(
                    company_id=company_id,
                    transfer_header_id=header.id,
                    product_variant_id=item.product_variant_id,
                    batch_id=batch_id,
                    quantity=take_qty,
                    source_stock_status="AVAILABLE",
                    lifecycle_revision_snapshot=int(variant_state.lifecycle_revision),
                    lifecycle_status_snapshot=str(variant_state.lifecycle_status),
                    operational_hold_snapshot=str(variant_state.operational_hold),
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
            "transfer_purpose": transfer_purpose,
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

    if str(header.transfer_purpose).upper() in SPECIAL_TRANSFER_PURPOSES:
        await validate_special_transfer_policy_snapshot(
            db,
            company_id=company_id,
            header=header,
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
    notes: Optional[str],
    terminal_action: str,
) -> dict[int, str]:
    """Complete an already-valid TRANSIT document into a current safe terminal bucket."""
    transit_location_id = int(header.transit_location_id)
    transfer_purpose = str(header.transfer_purpose).upper()
    is_special = transfer_purpose in SPECIAL_TRANSFER_PURPOSES
    normalized_terminal_action = str(terminal_action or "").strip().upper()

    if normalized_terminal_action not in {"RECEIVE", "RETURN_TO_SOURCE"}:
        raise HTTPException(
            status_code=409,
            detail=inventory_business_error(
                "TRANSFER_TERMINAL_ACTION_INVALID",
                "نوع قرار إنهاء الحوالة غير صالح.",
            ),
        )

    if is_special and normalized_terminal_action == "RECEIVE":
        destination_allowed_types = (
            ["WAREHOUSE", "SCRAP"]
            if transfer_purpose == "DISPOSAL"
            else ["WAREHOUSE"]
        )
    else:
        destination_allowed_types = ["WAREHOUSE", "VEHICLE"]

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
        allowed_types=destination_allowed_types,
    )

    # Lock order: idempotency -> product lifecycle -> locations -> rows/balances.
    variant_ids = sorted(set(
        (
            await db.execute(
                select(InventoryTransferLine.product_variant_id).filter_by(
                    company_id=company_id,
                    transfer_header_id=header.id,
                )
            )
        ).scalars().all()
    ))
    if not variant_ids:
        raise HTTPException(
            status_code=409,
            detail="الحوالة لا تحتوي على أسطر مخزون صالحة.",
        )

    await acquire_product_lifecycle_guards(
        db,
        company_id,
        variant_ids,
        exclusive=False,
    )

    await acquire_inventory_location_guards(
        db,
        company_id,
        [transit_location_id, destination_location_id],
    )
    await _verify_location_ownership(
        db,
        company_id,
        transit_location_id,
        allowed_types=['IN_TRANSIT'],
    )
    await _verify_location_ownership(
        db,
        company_id,
        destination_location_id,
        allowed_types=destination_allowed_types,
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
            ).with_for_update()
        )
    ).scalars().all()

    if not lines:
        raise HTTPException(
            status_code=409,
            detail="الحوالة لا تحتوي على أسطر مخزون صالحة."
        )

    if is_special:
        terminal_statuses = await resolve_special_transfer_terminal_statuses(
            db,
            company_id=company_id,
            destination_location_id=destination_location_id,
            transfer_purpose=transfer_purpose,
            terminal_action=normalized_terminal_action,
            lines=lines,
        )
    else:
        terminal_statuses = await resolve_inflight_transfer_destination_statuses(
            db,
            company_id=company_id,
            destination_location_id=destination_location_id,
            transfer_purpose=transfer_purpose,
            lines=lines,
        )

    movement_specs = []
    for line in lines:
        source_status = str(line.source_stock_status).upper()
        final_status = terminal_statuses[int(line.id)]

        # PHYSICAL preserves portion status by DB invariant.  Any safety downgrade
        # is a second explicit STATUS_CHANGE through the same Unified Engine.
        movement_specs.append({
            "product_variant_id": line.product_variant_id,
            "batch_id": line.batch_id,
            "quantity": line.quantity,
            "movement_kind": 'PHYSICAL',
            "reference_type": reference_type,
            "reference_id": header.reference_number,
            "idempotency_key": f"{idempotency_prefix}-{header.id}-{line.id}",
            "source_location_id": transit_location_id,
            "destination_location_id": destination_location_id,
            "source_stock_status": source_status,
            "destination_stock_status": source_status,
            "transfer_header_id": header.id,
            "notes": notes,
        })
        if final_status != source_status:
            movement_specs.append({
                "product_variant_id": line.product_variant_id,
                "batch_id": line.batch_id,
                "quantity": line.quantity,
                "movement_kind": 'STATUS_CHANGE',
                "reference_type": (
                    "SPECIAL_TRANSFER_TERMINAL_STATUS"
                    if is_special
                    else "TRANSFER_TERMINAL_STATUS"
                ),
                "reference_id": header.reference_number,
                "idempotency_key": (
                    f"{idempotency_prefix}-STATUS-{header.id}-{line.id}"
                ),
                "source_location_id": destination_location_id,
                "destination_location_id": destination_location_id,
                "source_stock_status": source_status,
                "destination_stock_status": final_status,
                "transfer_header_id": header.id,
                "notes": (
                    f"Safe terminal status for {header.transfer_purpose}: "
                    f"{source_status}->{final_status}"
                ),
            })

    await apply_inventory_movements_batch(
        db,
        company_id=company_id,
        performed_by=performed_by,
        movements=movement_specs,
    )
    return terminal_statuses


@router.post("/warehouse/unified/transfer/receive", status_code=200)
async def unified_transfer_receive(
    payload: UnifiedReceiveRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await require_transfer(access, 'transfer.receive', payload.transfer_header_id, 'destination')

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

        special_permission = SPECIAL_TRANSFER_PERMISSION.get(
            str(header.transfer_purpose).upper()
        )
        if special_permission is not None:
            await access.require(special_permission)

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
            notes=header.notes,
            terminal_action="RECEIVE",
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
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await require_transfer(access, 'transfer.cancel', header_id, 'source')

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

        special_permission = SPECIAL_TRANSFER_PERMISSION.get(
            str(header.transfer_purpose).upper()
        )
        if special_permission is not None:
            await access.require(special_permission)

        await _move_transfer_lines_from_transit(
            db,
            company_id=company_id,
            header=header,
            performed_by=current_admin.id,
            destination_location_id=header.source_location_id,
            reference_type='TRANSFER_CANCELLED',
            idempotency_prefix='TRN-CANC',
            notes=reason,
            terminal_action="RETURN_TO_SOURCE",
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
    current_admin: Driver = Depends(get_current_driver)
):
    access = InventoryAccess(db, current_admin)
    await require_transfer(access, 'transfer.reject', header_id, 'destination')

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

        special_permission = SPECIAL_TRANSFER_PERMISSION.get(
            str(header.transfer_purpose).upper()
        )
        if special_permission is not None:
            await access.require(special_permission)

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
            notes=reason,
            terminal_action="RETURN_TO_SOURCE",
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


def _vehicle_recon_candidate_cursor_scope_hash(
    scope: str,
) -> str:
    return hashlib.sha256(
        scope.encode("utf-8")
    ).hexdigest()[:24]


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
