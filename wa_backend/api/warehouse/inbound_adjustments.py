from decimal import Decimal
import asyncio
import hashlib
import json
import logging

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess, require_inbound_adjustment
from models import (
    Driver,
    InventoryLocation,
    InventoryMovement,
    ProductVariant,
    SystemAuditLog,
)
from quantity import canonical_quantity
from schemas import AdjustWarehouseEntryRequest, MessageResponse
from services import InventoryMutationError, apply_inventory_movement


logger = logging.getLogger("wanasah_logger")
router = APIRouter()


# ====================================================
# 8. تعديل فاتورة توريد - Correction append-only على المحرك الموحد
# ====================================================
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




