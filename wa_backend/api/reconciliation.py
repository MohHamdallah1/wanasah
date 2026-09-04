from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel
import uuid

from database import get_db
from api.dependencies import get_current_driver
from models import (WorkSession, SessionInventory, StocktakeSession, 
                    StocktakeLine, InventoryLock, InventoryLocation, Driver)

router = APIRouter()

# =================================================================================
# [المرحلة السابعة] Pydantic Schemas لتسوية المناديب
# =================================================================================
class VehicleCountItem(BaseModel):
    product_variant_id: int
    actual_quantity: int # الكمية التي عدّها المندوب بيده داخل السيارة

class VehicleReconciliationRequest(BaseModel):
    counts: List[VehicleCountItem]
    notes: Optional[str] = None

# =================================================================================
# محرك التسوية (End of Day Reconciliation)
# =================================================================================
@router.post("/driver/session/{session_id}/reconcile", status_code=200)
async def reconcile_driver_end_of_day(
    session_id: int,
    payload: VehicleReconciliationRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver) 
):
    company_id = current_driver.company_id

    try:
        stmt_session = select(WorkSession).with_for_update().filter_by(
            id=session_id, company_id=company_id, driver_id=current_driver.id
        )
        work_session = (await db.execute(stmt_session)).scalar_one_or_none()

        if not work_session:
            raise ValueError("جلسة العمل غير موجودة.")
        if work_session.is_settled:
            raise ValueError("مرفوض: هذه الجلسة مغلقة مالياً ومخزنياً وتمت تسويتها مسبقاً.")

        stmt_inventory = select(SessionInventory).filter_by(work_session_id=session_id)
        session_inv = (await db.execute(stmt_inventory)).scalars().all()
        
        expected_balances = {inv.product_variant_id: inv.current_remaining_quantity for inv in session_inv}

        # (P2-2 Fixed): حماية من القائمة الفارغة للتهرب من التسوية
        if expected_balances and not payload.counts:
            raise ValueError("مرفوض أمنياً: لا يمكن تسليم جرد فارغ بينما توجد بضاعة مسجلة في عهدتك.")

        actual_counts = {}
        for item in payload.counts:
            if item.actual_quantity < 0: raise ValueError("مرفوض: لا يمكن إدخال كميات سالبة في الجرد.")
            actual_counts[item.product_variant_id] = actual_counts.get(item.product_variant_id, 0) + item.actual_quantity

        variances = []
        for v_id, expected_qty in expected_balances.items():
            actual_qty = actual_counts.get(v_id, 0)
            if expected_qty != actual_qty:
                variances.append({"product_variant_id": v_id, "expected": expected_qty, "actual": actual_qty, "variance": actual_qty - expected_qty})
        
        for v_id, actual_qty in actual_counts.items():
            if v_id not in expected_balances and actual_qty > 0:
                variances.append({"product_variant_id": v_id, "expected": 0, "actual": actual_qty, "variance": actual_qty})

        if not variances:
            # (P1-2 Fixed): لا نغلق الجلسة `is_settled=True` هنا، نتركها للمحاسب لاستلام النقد!
            await db.commit()
            return {"message": "التسوية المخزنية مطابقة 100%. الرجاء التوجه للمحاسب لتسليم النقد وإغلاق الجلسة.", "requires_audit": False}
        
        # (P2-1 Fixed): جلب الموقع الفعال المربوط بالسيارة النشطة
        stmt_loc = select(InventoryLocation).filter_by(
            company_id=company_id, driver_id=current_driver.id, location_type='VEHICLE', is_active=True
        )
        vehicle_loc = (await db.execute(stmt_loc)).scalars().first()
        if not vehicle_loc:
            raise ValueError("خطأ هندسي: لا يوجد موقع (Location) فعال لسيارتك في النظام الموحد.")

        # (P1-1 Fixed): منع التضارب مع جلسات المراجعة أو الإعادة (RECOUNT_REQUIRED)
        stmt_active_recon = select(StocktakeSession.id).filter(
            StocktakeSession.company_id == company_id,
            StocktakeSession.location_id == vehicle_loc.id,
            StocktakeSession.status.in_(['PENDING_REVIEW', 'RECOUNT_REQUIRED'])
        )
        if (await db.execute(stmt_active_recon)).first():
            raise ValueError("يوجد جلسة تسوية قيد المراجعة أو الإعادة حالياً. لا يمكن فتح جلسة جديدة.")

        ref_num = f"V-REC-{uuid.uuid4().hex[:8].upper()}"
        stocktake_session = StocktakeSession(
            company_id=company_id, location_id=vehicle_loc.id,
            reference_number=ref_num, stocktake_type='VEHICLE_RECON',
            status='PENDING_REVIEW', 
            started_by=current_driver.id, counted_by=current_driver.id, 
            notes=f"تسوية إجبارية لنهاية اليوم - جلسة عمل ({session_id}). {payload.notes or ''}"
        )
        db.add(stocktake_session)
        await db.flush()

        for diff in variances:
            st_line = StocktakeLine(
                company_id=company_id, stocktake_session_id=stocktake_session.id,
                product_variant_id=diff['product_variant_id'], batch_id=None,
                expected_quantity=diff['expected'], actual_quantity=diff['actual'],
                variance_quantity=diff['variance']
            )
            db.add(st_line)

        lock = InventoryLock(
            company_id=company_id, stocktake_session_id=stocktake_session.id,
            location_id=vehicle_loc.id, created_by=current_driver.id
        )
        db.add(lock)
        
        await db.commit()
        return {
            "message": "يوجد فروقات في العهدة! تم تجميد مبيعات السيارة وفتح جلسة تسوية للمراجعة.", 
            "requires_audit": True,
            "stocktake_reference": ref_num
        }

    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء معالجة التسوية.")