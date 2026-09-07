# RECONCILIATION_UNIFIED_VEHICLE_RECON
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from typing import List, Optional
import json
import logging

from database import get_db
from api.dependencies import get_current_driver
from models import (
    WorkSession,
    DispatchRoute,
    InventoryLocation,
    InventoryBalance,
    InventoryLock,
    StocktakeSession,
    ProductVariant,
    SystemAuditLog,
    Driver,
)
from services import (
    InventoryMutationError,
    acquire_inventory_location_guard,
    validate_vehicle_recon_work_session,
    open_vehicle_reconciliation_stocktake,
    finalize_vehicle_reconciliation_settlement,
)

router = APIRouter()
logger = logging.getLogger("wanasah_logger")
_DB_INT_MAX = 2_147_483_647
_MAX_RECON_COUNTS = 5000
_MAX_RECON_BALANCE_ROWS = 10000


class VehicleCountItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_variant_id: StrictInt = Field(gt=0, le=_DB_INT_MAX)
    actual_quantity: StrictInt = Field(ge=0, le=_DB_INT_MAX)


class VehicleReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counts: List[VehicleCountItem] = Field(..., max_length=_MAX_RECON_COUNTS)
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("notes يجب أن تكون نصاً.")
        value = value.strip()
        if "\x00" in value:
            raise ValueError("notes لا تقبل محرف NUL.")
        return value or None

    @model_validator(mode="after")
    def reject_duplicate_products(self):
        ids = [item.product_variant_id for item in self.counts]
        if len(ids) != len(set(ids)):
            raise ValueError("لا يجوز تكرار نفس الصنف في جرد السيارة؛ أرسل إجمالي الصنف مرة واحدة.")
        return self


@router.post("/driver/session/{session_id}/reconcile", status_code=200)
async def reconcile_driver_end_of_day(
    session_id: int,
    payload: VehicleReconciliationRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver),
):
    """
    تسوية عهدة نهاية اليوم بدون إجبار المندوب على Batch count عندما تكون الإجماليات مطابقة.

    - يقارن العد الفعلي التجميعي مع إجمالي on_hand (AVAILABLE + DAMAGED) للسيارة.
    - المطابقة التامة: يثبت Ending Snapshot ويغلق WorkSession مخزنياً.
    - وجود فرق: يفتح VEHICLE_RECON موجهاً فقط للأصناف المختلفة؛ لا يخمّن Batch الفرق.
    """
    company_id = int(current_driver.company_id)
    driver_id = int(current_driver.id)

    try:
        work_session = (
            await db.execute(
                select(WorkSession)
                .filter_by(
                    company_id=company_id,
                    id=session_id,
                    driver_id=driver_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if work_session is None:
            raise HTTPException(status_code=404, detail="جلسة العمل غير موجودة أو لا تخصك.")
        if work_session.end_time is None:
            raise HTTPException(status_code=409, detail="يجب إنهاء يوم العمل قبل تسوية عهدة السيارة.")

        # State-idempotency: retry بعد نجاح المطابقة لا يعيد أي حركة أو يفتح جرداً جديداً.
        if work_session.is_settled:
            await db.rollback()
            return {
                "message": "تمت تسوية عهدة هذه الجلسة مسبقاً.",
                "requires_audit": False,
                "already_settled": True,
            }

        route = (
            await db.execute(
                select(DispatchRoute)
                .filter_by(
                    company_id=company_id,
                    work_session_id=work_session.id,
                    driver_id=driver_id,
                )
                .order_by(DispatchRoute.id.desc())
                .limit(1)
                .with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if route is None or route.vehicle_id is None:
            raise HTTPException(status_code=409, detail="جلسة العمل لا ترتبط بسيارة صالحة للتسوية.")

        await validate_vehicle_recon_work_session(
            db,
            company_id=company_id,
            work_session_id=work_session.id,
            vehicle_id=int(route.vehicle_id),
        )

        vehicle_location = (
            await db.execute(
                select(InventoryLocation)
                .filter_by(
                    company_id=company_id,
                    vehicle_id=route.vehicle_id,
                    location_type="VEHICLE",
                    is_active=True,
                )
                .with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if vehicle_location is None:
            raise HTTPException(status_code=409, detail="السيارة لا تملك موقع مخزون VEHICLE فعالاً.")

        vehicle_location_id = int(vehicle_location.id)
        await acquire_inventory_location_guard(
            db,
            company_id,
            vehicle_location_id,
            exclusive=True,
        )

        # إذا سبق فتح VEHICLE_RECON لهذه الجلسة فلا ننشئ نسخة ثانية ولا نتجاوز المراجعة المفتوحة.
        existing_recon = (
            await db.execute(
                select(StocktakeSession)
                .filter(
                    StocktakeSession.company_id == company_id,
                    StocktakeSession.stocktake_type == "VEHICLE_RECON",
                    StocktakeSession.related_work_session_id == work_session.id,
                    StocktakeSession.status != "CANCELLED",
                )
                .order_by(StocktakeSession.id.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing_recon is not None:
            # SQLAlchemy expires ORM state on rollback. Capture primitive values first so
            # the idempotent replay never triggers implicit async I/O after rollback.
            existing_status = str(existing_recon.status)
            existing_reference = str(existing_recon.reference_number)
            existing_id = int(existing_recon.id)

            if existing_status == "POSTED":
                raise HTTPException(
                    status_code=409,
                    detail="VEHICLE_RECON بحالة POSTED لكن WorkSession غير مسواة؛ البيانات غير متسقة وتحتاج مراجعة.",
                )
            await db.rollback()
            return {
                "message": "يوجد VEHICLE_RECON مفتوح لهذه الجلسة؛ استخدم نفس جلسة المراجعة.",
                "requires_audit": True,
                "stocktake_reference": existing_reference,
                "stocktake_session_id": existing_id,
                "stocktake_status": existing_status,
            }

        conflicting_lock = (
            await db.execute(
                select(InventoryLock.id)
                .filter(
                    InventoryLock.company_id == company_id,
                    InventoryLock.location_id == vehicle_location_id,
                    InventoryLock.released_at.is_(None),
                )
                .order_by(InventoryLock.id.asc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if conflicting_lock is not None:
            raise HTTPException(status_code=409, detail="يوجد جرد/قفل مخزني فعال على السيارة؛ أكمله قبل التسوية.")

        submitted_ids = sorted({item.product_variant_id for item in payload.counts})
        if submitted_ids:
            valid_ids = set((
                await db.execute(
                    select(ProductVariant.id).filter(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(submitted_ids),
                    )
                )
            ).scalars().all())
            if valid_ids != set(submitted_ids):
                raise HTTPException(status_code=422, detail="أحد الأصناف المعدودة غير موجود أو لا يتبع شركتك.")

        balance_rows = (
            await db.execute(
                select(InventoryBalance)
                .filter(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id == vehicle_location_id,
                    InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),
                    or_(
                        InventoryBalance.on_hand_quantity > 0,
                        InventoryBalance.reserved_quantity > 0,
                    ),
                )
                .order_by(
                    InventoryBalance.product_variant_id.asc(),
                    InventoryBalance.batch_id.asc(),
                    InventoryBalance.stock_status.asc(),
                    InventoryBalance.id.asc(),
                )
                .limit(_MAX_RECON_BALANCE_ROWS + 1)
                .with_for_update()
            )
        ).scalars().all()
        if len(balance_rows) > _MAX_RECON_BALANCE_ROWS:
            raise HTTPException(status_code=409, detail="رصيد السيارة كبير جداً للتسوية التجميعية الآمنة.")

        expected_map = {}
        reserved_total = 0
        for balance in balance_rows:
            reserved_total += int(balance.reserved_quantity or 0)
            if balance.on_hand_quantity <= 0:
                continue
            product_variant_id = int(balance.product_variant_id)
            next_total = expected_map.get(product_variant_id, 0) + int(balance.on_hand_quantity or 0)
            if next_total > _DB_INT_MAX:
                raise HTTPException(status_code=409, detail="إجمالي أحد أصناف السيارة يتجاوز سعة INTEGER.")
            expected_map[product_variant_id] = next_total

        if reserved_total != 0:
            raise HTTPException(
                status_code=409,
                detail="يوجد مخزون محجوز على السيارة بعد إنهاء الجلسة؛ يجب تحرير الحجز قبل التسوية.",
            )

        actual_map = {item.product_variant_id: item.actual_quantity for item in payload.counts}
        missing_products = sorted(set(expected_map) - set(actual_map))
        if missing_products:
            raise HTTPException(
                status_code=422,
                detail=(
                    "محاولة العد ناقصة؛ الصنف غير المرسل لا يُعامل كصفر. "
                    f"الأصناف الناقصة: {missing_products[:20]}"
                ),
            )

        variances = []
        for product_variant_id in sorted(set(expected_map) | set(actual_map)):
            expected = int(expected_map.get(product_variant_id, 0))
            actual = int(actual_map.get(product_variant_id, 0))
            if expected != actual:
                variances.append({
                    "product_variant_id": product_variant_id,
                    "expected": expected,
                    "actual": actual,
                    "variance": actual - expected,
                })

        if not variances:
            await finalize_vehicle_reconciliation_settlement(
                db,
                company_id=company_id,
                work_session_id=work_session.id,
                vehicle_location_id=vehicle_location_id,
                settled_by=driver_id,
            )
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=driver_id,
                target_id=f"WorkSession_{work_session.id}",
                action_type="VEHICLE_RECON_MATCHED",
                old_value="is_settled=false",
                new_value=json.dumps({
                    "is_settled": True,
                    "product_count": len(expected_map),
                    "vehicle_location_id": vehicle_location_id,
                }, ensure_ascii=False),
            ))
            await db.commit()
            return {
                "message": "التسوية المخزنية مطابقة 100% وتم تثبيت عهدة نهاية الجلسة.",
                "requires_audit": False,
                "already_settled": False,
            }

        variance_product_ids = [row["product_variant_id"] for row in variances]
        audit_note = (
            f"تسوية عهدة جلسة ({work_session.id})؛ فرق تجميعي في الأصناف: "
            + ",".join(str(value) for value in variance_product_ids[:100])
        )
        if payload.notes:
            audit_note = f"{audit_note}. {payload.notes}"

        stocktake_session, created = await open_vehicle_reconciliation_stocktake(
            db,
            company_id=company_id,
            work_session_id=work_session.id,
            vehicle_location_id=vehicle_location_id,
            started_by=driver_id,
            product_variant_ids=variance_product_ids,
            notes=audit_note[:4000],
        )

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=driver_id,
            target_id=f"WorkSession_{work_session.id}",
            action_type="VEHICLE_RECON_VARIANCE_DETECTED",
            old_value="aggregate_count",
            new_value=json.dumps({
                "stocktake_session_id": stocktake_session.id,
                "stocktake_reference": stocktake_session.reference_number,
                "variance_count": len(variances),
                "variance_product_ids": variance_product_ids[:100],
            }, ensure_ascii=False),
        ))
        await db.commit()
        return {
            "message": "يوجد فرق في العهدة؛ تم فتح VEHICLE_RECON فقط للأصناف المختلفة وتجميد السيارة للمراجعة.",
            "requires_audit": True,
            "stocktake_reference": stocktake_session.reference_number,
            "stocktake_session_id": stocktake_session.id,
            "stocktake_status": stocktake_session.status,
            "variance_count": len(variances),
            "variance_product_ids": variance_product_ids,
            "created": created,
        }

    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("تعارض متزامن أثناء تسوية عهدة السيارة", exc_info=True)
        raise HTTPException(status_code=409, detail="حدث تعارض متزامن أثناء فتح/تثبيت التسوية؛ أعد المحاولة.") from exc
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ داخلي أثناء تسوية عهدة السيارة: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء معالجة التسوية.") from exc
