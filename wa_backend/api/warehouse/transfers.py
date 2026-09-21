from datetime import datetime, timezone
from decimal import Decimal
import base64
import hashlib
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select
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
)
from quantity import canonical_quantity
from product_lifecycle import WAREHOUSE_BALANCING, product_capability_predicate

from services import (
    InventoryMutationError,
    InventoryRuleError,
    apply_inventory_movement,
    begin_idempotent_operation,
    change_product_batch_disposition,
    complete_idempotent_operation,
    batch_sellability_predicate,
    get_company_local_date,
    inventory_business_error,
)

# Staging-only dependency: remains sourced from the untouched monolith until
# _stable_request_hash is moved once to _shared.py in its dedicated stage.
from api.warehouse import _stable_request_hash
from ._shared import (
    _decode_variant_cursor,
    _encode_variant_cursor,
    _escape_like,
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
