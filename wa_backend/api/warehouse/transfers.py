from datetime import datetime, timezone
import base64
import hashlib
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import Driver, InventoryLocation, ProductVariant
from schemas import (
    BatchDispositionChangeRequest,
    BatchDispositionMutationResponse,
    InventoryStatusChangeRequest,
    InventoryStatusChangeResponse,
)
from services import (
    InventoryMutationError,
    InventoryRuleError,
    apply_inventory_movement,
    begin_idempotent_operation,
    change_product_batch_disposition,
    complete_idempotent_operation,
    inventory_business_error,
)

# Staging-only dependency: remains sourced from the untouched monolith until
# _stable_request_hash is moved once to _shared.py in its dedicated stage.
from api.warehouse import _stable_request_hash


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


