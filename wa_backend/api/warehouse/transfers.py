from datetime import datetime, timezone
from decimal import Decimal
import base64
import hashlib
import json
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess, require_transfer, transfer_filter
from models import (
    Driver,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    InventoryStockPolicy,
    InventoryTransferHeader,
    InventoryTransferLine,
    OverrideReason,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    SystemAuditLog,
    UOM,
)
from schemas import (
    BatchDispositionChangeRequest,
    BatchDispositionMutationResponse,
    InventoryStatusChangeRequest,
    InventoryStatusChangeResponse,
    UnifiedTransferLocationItem,
    UnifiedTransferOverrideOptionsResponse,
    UnifiedTransferSourceInventoryCursorPage,
    WarehouseTransferCursorPage,
    WarehouseTransferDetail,
    SpecialTransferDispatchRequest,
    SpecialTransferDispatchResponse,
    UnifiedDispatchRequest,
    UnifiedReceiveRequest,
    UnifiedTransferDecisionRequest,
)
from quantity import canonical_quantity
from product_lifecycle import (
    INBOUND_NEW,
    REPLENISHMENT_NEW,
    WAREHOUSE_BALANCING,
    acquire_product_lifecycle_guards,
    evaluate_product_capability,
    product_capability_predicate,
    product_location_allows,
)

from services import (
    InventoryMutationError,
    InventoryRuleError,
    SPECIAL_TRANSFER_PERMISSION,
    SPECIAL_TRANSFER_PURPOSES,
    TRANSFER_DESTINATION_POLICY_CODE,
    acquire_inventory_location_guards,
    allocate_fefo_inventory_batch,
    apply_inventory_movement,
    apply_inventory_movements_batch,
    begin_idempotent_operation,
    change_product_batch_disposition,
    complete_idempotent_operation,
    batch_sellability_predicate,
    ensure_system_transit_location,
    get_company_local_date,
    inventory_business_error,
    resolve_inflight_transfer_destination_statuses,
    resolve_retiring_warehouse_balancing_override_context,
    resolve_special_transfer_direction_context,
    resolve_special_transfer_terminal_statuses,
    validate_special_transfer_policy_snapshot,
    validate_special_transfer_source_items_locked,
)


from ._shared import (
    _decode_variant_cursor,
    _encode_variant_cursor,
    _escape_like,
    _stable_request_hash,
)


logger = logging.getLogger("wanasah_logger")
router = APIRouter()


# ====================================================
# 10. المحرك الموحد للحوالات وحركات الحالة المرتبطة
# ====================================================
# ====================================================
# 10.1 إنشاء بصمة نطاق Cursor لقائمة الحوالات
# ====================================================
def _transfer_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


# ====================================================
# 10.2 ترميز Cursor الحوالات وربطه بنطاق الاستعلام
# ====================================================
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


# ====================================================
# 10.3 فك Cursor الحوالات والتحقق من نطاقه
# ====================================================
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



# ====================================================
# 10.4 التحقق من ملكية المواقع وحالتها ونوعها ضمن الشركة
# ====================================================
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

# ====================================================
# 10.5 تغيير disposition للدفعة دون تغيير Bucket المخزون تلقائياً
# ====================================================
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


# ====================================================
# 10.6 تغيير Bucket حالة المخزون عبر محرك الحركات الموحد
# ====================================================
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


# ====================================================
# 10.7 جلب المواقع المتاحة كمصدر أو وجهة للحوالات
# ====================================================
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


# ====================================================
# 10.8 جلب مخزون المصدر المتاح للحوالات باستخدام Cursor
# ====================================================
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


# ====================================================
# 10.9 جلب خيارات تجاوز FEFO والأسباب المسموحة للحوالة
# ====================================================
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



# ====================================================
# 10.10-10.12 استعلامات الحوالات وتهيئة الاستجابة
# ====================================================
_TRANSFER_QUERY_STATUSES = frozenset({
    'DRAFT',
    'PENDING',
    'IN_TRANSIT',
    'ACCEPTED',
    'REJECTED',
    'POSTED',
    'CANCELLED',
})


# ====================================================
# 10.10 تحويل رؤوس الحوالات إلى عقد الاستجابة مع الأسماء والمجاميع
# ====================================================
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


# ====================================================
# 10.11 جلب قائمة الحوالات الموحدة باستخدام Cursor والفلاتر
# ====================================================
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


# ====================================================
# 10.12 جلب تفاصيل حوالة موحدة مع أسطرها
# ====================================================
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

# ====================================================
# 10.13 إنشاء تحويل خاص مرتبط بسياسة الوجهات ونقل المخزون إلى IN_TRANSIT
# ====================================================
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


# ====================================================
# 10.14 سياسة أغراض الحوالة العامة وتنفيذ Dispatch
# ====================================================
_GENERIC_TRANSFER_PURPOSE_CAPABILITY = {
    "REPLENISHMENT": REPLENISHMENT_NEW,
    "WAREHOUSE_BALANCING": WAREHOUSE_BALANCING,
}


# ====================================================
# 10.14 إنشاء حوالة عامة REPLENISHMENT/WAREHOUSE_BALANCING ونقلها إلى IN_TRANSIT
# ====================================================
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


# ====================================================
# 10.15 تحميل حوالة IN_TRANSIT وقفلها قبل القرار النهائي
# ====================================================
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


# ====================================================
# 10.16 التحقق من سبب قرار الحوالة النهائي
# ====================================================
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


# ====================================================
# 10.17 نقل أسطر الحوالة من IN_TRANSIT إلى الوجهة النهائية الآمنة
# ====================================================
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


# ====================================================
# 10.18 استلام الحوالة وترحيلها إلى POSTED
# ====================================================
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


# ====================================================
# 10.19 إلغاء الحوالة وإرجاع المخزون من IN_TRANSIT إلى المصدر
# ====================================================
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


# ====================================================
# 10.20 رفض الحوالة وإرجاع المخزون من IN_TRANSIT إلى المصدر
# ====================================================
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

