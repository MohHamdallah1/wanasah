from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, update, or_, and_, delete
from sqlalchemy.orm import joinedload, contains_eager, selectinload
from sqlalchemy.exc import IntegrityError
from database import get_db
from typing import List
from api.dependencies import get_current_driver
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from services import reverse_previous_visit_state, InventoryReversalError, get_setting, calculate_invoice, check_debt_limits
import logging
logger = logging.getLogger("wanasah_logger")

from models import (Driver, WorkSession, DispatchRoute, VehicleLoad, SessionInventory, Visit, InventoryTransfer,
WorkBreakLog, VisitItem, Shop, ProductVariant, VisitReturn, OfferRule, InventoryLedger, Zone,
WarehouseLedger, MainWarehouse, ShortageRequest, SystemAuditLog)

from schemas import (SessionStartRequest, BreakToggleRequest, TransferResponseRequest,
BatchTransferResponseRequest, PendingBatchResponse, AddShopRequest, ProductVariantResponse,
GetVisitsContract, VisitDetailsResponse, ActiveSessionResponse, VisitUpdateRequest)

router = APIRouter(tags=["Driver Operations"])
# =========================================
# 1. بدء جلسة العمل (مربوطة بالتوزيع والجرد)
# =========================================
@router.post("/driver/{driver_id}/sessions/start", status_code=201)
async def start_work_session(
    driver_id: int, 
    payload: SessionStartRequest, 
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # 1. الدرع الأمني (IDOR): منع المندوب من بدء جلسة لغيره
    if current_driver.id != driver_id:
         raise HTTPException(status_code=403, detail="مرفوض: غير مصرح لك.")

    # 2. الحماية من تراكم العهدة (Unsettled Session Check)
    # +++ النسف المعماري: استثناء الجلسة النشطة حالياً لكي لا تتضارب مع فحص الجلسة النشطة وتظهر رسالة خاطئة للمندوب +++
    stmt_unsettled = select(WorkSession).filter(
        WorkSession.driver_id == driver_id, 
        WorkSession.is_settled == False,
        WorkSession.end_time.is_not(None) 
    ).order_by(WorkSession.id.desc()).limit(1)
    
    unsettled_session = (await db.execute(stmt_unsettled)).scalars().first()
    if unsettled_session:
        raise HTTPException(
            status_code=400, 
            detail="لا يمكنك بدء يوم عمل جديد. لديك عهدة سابقة معلقة لم يتم تسويتها من قبل الإدارة."
        )

    # 3. منع بدء العمل بدون خط سير (حماية التوزيع)
    # +++ قفل خط السير لمنع المدير من سحبه أثناء بدء المندوب للعمل (Race Condition Shield) +++
    stmt_route = select(DispatchRoute).filter_by(driver_id=driver_id, status='active').with_for_update()
    active_route = (await db.execute(stmt_route)).scalars().first()
    if not active_route:
        raise HTTPException(
            status_code=400, # +++ تحويله لـ 400 لكي يظهر للمندوب الإشعار الصحيح +++ 
            detail="لا يوجد لديك خط سير مخصص اليوم. الرجاء مراجعة مدير التوزيع."
        )

    try:
        # +++ قفل التزامن الفولاذي (Row-Level Lock) لمنع الدبل كليك +++
        stmt_lock = select(Driver).filter_by(id=driver_id).with_for_update()
        await db.execute(stmt_lock)

        # 4. التحقق من عدم وجود جلسة نشطة (لم تنتهِ بعد)
        stmt_existing = select(WorkSession).filter_by(driver_id=driver_id, end_time=None)
        existing_session = (await db.execute(stmt_existing)).scalar_one_or_none()
        if existing_session:
            await db.rollback() # +++ الإغلاق اليدوي للقفل +++
            raise HTTPException(status_code=409, detail="لديك جلسة عمل نشطة بالفعل لم يتم إنهاؤها.")

        # 5. إنشاء الجلسة الجديدة
        new_session = WorkSession(
            driver_id=driver_id,
            start_time=datetime.now(timezone.utc).replace(tzinfo=None),
            start_latitude=payload.latitude,
            start_longitude=payload.longitude,
            is_authorized_to_sell=False # يبدأ بالضوء الأحمر
        )
        db.add(new_session)
        await db.flush() # للحصول على new_session.id لاستخدامه في الخطوات التالية

        # 6. +++ ربط خط السير ونقل حمولة السيارة للعهدة (مصافحة الصباح) +++
        active_route.work_session_id = new_session.id
        
        # جلب حمولة السيارة مع تفاصيل المنتجات (Eager Loading لنسف N+1)
        stmt_loads = select(VehicleLoad).options(joinedload(VehicleLoad.product_variant)).filter_by(vehicle_id=active_route.vehicle_id).with_for_update()
        vehicle_loads = (await db.execute(stmt_loads)).scalars().all()
        
        for load in vehicle_loads:
            variant = load.product_variant
            packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton else 1
            total_packs = load.quantity * packs_per_carton
            
            inventory_item = SessionInventory(
                work_session_id=new_session.id,
                product_variant_id=load.product_variant_id,
                starting_quantity=total_packs,
                current_remaining_quantity=total_packs
            )
            db.add(inventory_item)
            
        # 7. +++ النسف المعماري (Bulk Update): حصر التحديث بمنطقة خط السير والطوارئ فقط لحماية دفاتر الجلسة من التلوث بمحلات خارج المنطقة +++
        stmt_bulk_visits = (
            update(Visit)
            .where(
                and_(
                    Visit.driver_id == driver_id,
                    Visit.status == 'Pending',
                    or_(
                        Visit.shop_id.in_(select(Shop.id).where(Shop.zone_id == active_route.zone_id)),
                        Visit.is_emergency == True
                    )
                )
            )
            .values(work_session_id=new_session.id)
        )
        await db.execute(stmt_bulk_visits)

        await db.commit()
        return {
            "message": "تم بدء الجلسة بنجاح، وتم استلام جرد السيارة.", 
            "session_id": new_session.id
        }

    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء بدء الجلسة.")

# =========================================
# 2. إنهاء جلسة العمل
# =========================================
@router.put("/driver/{driver_id}/sessions/end", status_code=200)
async def end_work_session(
    driver_id: int, 
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # 1. +++ الدرع الفولاذي (IDOR Fix): منع أي مندوب من إنهاء جلسة مندوب آخر +++
    if current_driver.id != driver_id:
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: لا يمكنك إنهاء جلسة زميلك.")

    # 2. البحث عن الجلسة النشطة مع القفل لمنع التسوية المتزامنة
    # +++ الدرع الفولاذي ضد كراش الـ MultipleResultsFound +++
    stmt_session = select(WorkSession).filter_by(driver_id=driver_id, end_time=None).order_by(WorkSession.id.desc()).limit(1).with_for_update()
    active_session = (await db.execute(stmt_session)).scalars().first()
    
    if not active_session:
        raise HTTPException(status_code=404, detail="No active session")

    # 3. +++ حرس الحدود (Backend): حماية الاستراحة من جذور السيرفر +++
    if active_session.break_start_time and not active_session.break_end_time:
        raise HTTPException(
            status_code=400, 
            detail="مرفوض أمنياً: أنت الآن في وقت الاستراحة. يجب إنهاء الاستراحة أولاً قبل إنهاء يوم العمل."
        )

    # 4. +++ الدرع الحديدي: منع إنهاء العمل إذا كان هناك مصافحات معلقة +++
    stmt_pending = select(InventoryTransfer).filter_by(work_session_id=active_session.id, status='pending')
    pending_transfers = (await db.execute(stmt_pending)).scalars().first()
    
    if pending_transfers:
        raise HTTPException(
            status_code=400, 
            detail="لا يمكنك إنهاء العمل! لديك حوالات معلقة من الإدارة (مصافحة) يجب الموافقة عليها أو رفضها أولاً."
        )

    try:
        active_session.end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        return {"message": "تم إنهاء الجلسة بنجاح."}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء إنهاء الجلسة.")

# =========================================
# 3. تسجيل وقت الاستراحة
# =========================================

@router.put("/driver/{driver_id}/sessions/break", status_code=200)
async def toggle_break(
    driver_id: int,
    payload: BreakToggleRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # 1. الدرع الأمني: التحقق من الهوية (IDOR)
    if current_driver.id != driver_id:
         raise HTTPException(status_code=403, detail="مرفوض: غير مصرح لك بالوصول.")

    try:
        # 2. قفل التزامن الفولاذي (Row-Level Lock) لمنع كارثة الـ Double Click
        # نستخدم with_for_update لضمان أن طلباً واحداً فقط يعالج الجلسة حالياً
        # +++ الدرع المفقود: حماية limit(1) لمنع כراش MultipleResultsFound +++
        stmt_session = select(WorkSession).filter_by(driver_id=driver_id, end_time=None).order_by(WorkSession.id.desc()).limit(1).with_for_update()
        active_session = (await db.execute(stmt_session)).scalars().first()
        
        if not active_session:
            raise HTTPException(status_code=404, detail="لا توجد جلسة عمل نشطة حالياً.")

        action = payload.action

        if action == 'start':
            if active_session.break_start_time and not active_session.break_end_time:
                 await db.rollback() # +++ الإغلاق اليدوي للقفل +++
                 raise HTTPException(status_code=400, detail="الاستراحة بدأت بالفعل.")
            
            active_session.break_start_time = datetime.now(timezone.utc).replace(tzinfo=None)
            active_session.break_end_time = None 
            msg = "تم بدء الاستراحة بنجاح."
            
        elif action == 'end':
            if not active_session.break_start_time or active_session.break_end_time:
                 await db.rollback() # +++ الإغلاق اليدوي للقفل +++
                 raise HTTPException(status_code=400, detail="لا يوجد استراحة نشطة لإنهائها.")
            
            end_t = datetime.now(timezone.utc).replace(tzinfo=None)
            break_start = active_session.break_start_time
            
            # كلا الوقتين الآن Naive (بدون Timezone)، يمكن الطرح بأمان تام بدون كراش
            duration = int((end_t - break_start).total_seconds() / 60) if break_start else 0
            
            # توثيق الحركة في جدول الاستراحات
            break_log = WorkBreakLog(
                work_session_id=active_session.id,
                break_start=active_session.break_start_time,
                break_end=end_t,
                duration_minutes=duration
            )
            db.add(break_log)
            
            # تصفير الحقول للسماح باستراحة جديدة
            active_session.break_start_time = None
            active_session.break_end_time = None
            msg = "تم إنهاء الاستراحة وتوثيق مدتها بنجاح."
        
        await db.commit()
        return {"message": msg}

    except HTTPException:
        # إعادة رفع أخطاء HTTPException كما هي
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء تسجيل الاستراحة.")

# =========================================
# 4. تحديث نتيجة الزيارة (Update Visit) - النسخة الفولاذية المعدلة
# =========================================
@router.put("/visits/{visit_id}", status_code=200)
async def update_visit(
    visit_id: int,
    payload: VisitUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # 1. +++ جلب الزيارة وقفلها مع فحص درع التسوية +++
    stmt_visit = select(Visit).options(
        selectinload(Visit.shop),
        selectinload(Visit.work_session), # جلب الجلسة لفحص التسوية
        selectinload(Visit.items).selectinload(VisitItem.product_variant),
        selectinload(Visit.returns)
    ).with_for_update().filter_by(id=visit_id)
    visit = (await db.execute(stmt_visit)).scalar_one_or_none()
    
    if not visit:
        raise HTTPException(status_code=404, detail="الزيارة غير موجودة")
        
    # +++ الدرع المحاسبي: منع تعديل الزيارات المسواة ماليًا +++
    if visit.work_session and visit.work_session.is_settled:
        await db.rollback()
        raise HTTPException(status_code=403, detail="مرفوض: لا يمكن تعديل زيارة تم تسويتها ماليًا واعتمادها من الإدارة.")

    if visit.driver_id != current_driver.id:
        await db.rollback()
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: لا تملك صلاحية التعديل على هذه الزيارة.")

    # 2. قفل سجل المحل
    stmt_shop = select(Shop).with_for_update().filter_by(id=visit.shop_id)
    shop = (await db.execute(stmt_shop)).scalar_one_or_none()
    visit.shop = shop 

    # 3. جلب الجلسة النشطة الحالية للمندوب
    # جلب الجلسة بدون قفل (حماية السيرفر من اختناق الـ Read-Only Lock)
    stmt_session = select(WorkSession).filter_by(driver_id=current_driver.id, end_time=None)
    active_session = (await db.execute(stmt_session)).scalars().first() # +++ سحق الـ 500 Crash +++

    if not active_session:
        await db.rollback()
        raise HTTPException(status_code=403, detail="لا يمكنك تنفيذ العملية. الرجاء بدء يوم العمل أولاً.")

    # 4. حماية الـ Ghost Sale
    stmt_route = select(DispatchRoute).filter_by(work_session_id=active_session.id, status='active')
    current_route = (await db.execute(stmt_route)).scalars().first() # +++ سحق الـ 500 Crash +++
    
    if not current_route:
        await db.rollback()
        raise HTTPException(status_code=403, detail="تم سحب خط السير أو إيقافه من قبل الإدارة. لا يمكنك إتمام العملية.")

    # 5. +++ حماية معمارية: فحص الطوارئ (Payload + DB) +++
    stmt_shortage = select(ShortageRequest).filter_by(shop_id=shop.id, status='pending')
    has_active_shortage = (await db.execute(stmt_shortage)).first() is not None
    
    # تصحيح الثغرة: نتحقق من الحقل القادم في الـ payload أيضاً
    is_emergency_request = payload.is_emergency or visit.is_emergency
    
    if shop.zone_id != current_route.zone_id and not (is_emergency_request or has_active_shortage):
        await db.rollback()
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: لا يمكنك البيع لمحل خارج منطقة عملك المخصصة إلا بتصريح طلب عاجل.")

    # 6. حماية الاستراحة والضوء الأخضر والمصافحة
    if active_session.break_start_time and not active_session.break_end_time:
        await db.rollback()
        raise HTTPException(status_code=403, detail="أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل.")

    if not active_session.is_authorized_to_sell:
        await db.rollback()
        raise HTTPException(status_code=403, detail="غير مصرح لك بإجراء عمليات بيع حالياً. بانتظار تفعيل خط السير من الإدارة.")

    stmt_transfer = select(InventoryTransfer).filter_by(work_session_id=active_session.id, status='pending')
    if (await db.execute(stmt_transfer)).first():
        await db.rollback()
        raise HTTPException(status_code=403, detail="مرفوض: لديك حوالة معلقة من الإدارة (مصافحة). يرجى تأكيدها أو رفضها أولاً.")

    # 7. نظام الارتجاع الشامل
    try:
        if visit.status == 'Completed':
            # +++ حقن رقم السيارة لدفتر الأستاذ +++
            await reverse_previous_visit_state(
                db, visit, active_session, shop,
                admin_id=current_driver.id,
                vehicle_id=current_route.vehicle_id if current_route else None,
            )
    except InventoryReversalError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    
    # ------------------ (بداية القسم الثاني: المعالجة المالية والمستودعية) ------------------
    # 1. +++ الدرع المالي الفولاذي: تحويل مدخلات الموبايل (Float) إلى Decimal صريح لمنع TypeError عند الطرح +++
    debt_paid_input = Decimal(str(payload.debt_paid or '0.0'))
    original_shop_balance = Decimal(str(shop.current_balance or '0.0'))
    cash_collected = Decimal(str(payload.cash_collected or '0.0'))

    # +++ سحق ثغرة السالب (The Negative Exploit): منع المندوب من إرسال قيم سالبة لاختلاس الدفاتر +++
    if debt_paid_input < Decimal('0') or cash_collected < Decimal('0'):
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض أمنياً: لا يمكن إدخال قيم مالية سالبة في التحصيل أو النقد.")

    # 2. اللوجيك المحاسبي لتحصيل الذمم
    if debt_paid_input > Decimal('0'):
        if original_shop_balance <= Decimal('0'):
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"مرفوض: المحل رصيده دائن أو مُصفر ({original_shop_balance}). لا توجد ذمم.")
        if debt_paid_input > original_shop_balance:
             await db.rollback()
             raise HTTPException(status_code=400, detail=f"مرفوض: التحصيل ({debt_paid_input}) أكبر من ذمة المحل ({original_shop_balance}).")

    # 3. تحديث البيانات الأساسية للزيارة
    if visit.status == 'Pending':
        visit.visit_timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
        
    visit.outcome = payload.outcome 
    # +++ النسف المعماري لفخ الحالة: المؤجل يبقى "Pending" لكي لا يختفي من قائمة المندوب +++
    visit.status = 'Completed' if payload.outcome in ['Sale', 'NoSale'] else 'Pending'
    
    visit.notes = payload.notes
    # +++ سحق ثغرة הـ Falsy Zero: الصفر إحداثي حقيقي ولا يجب تجاهله +++
    visit.latitude = payload.latitude if payload.latitude is not None else visit.latitude
    visit.longitude = payload.longitude if payload.longitude is not None else visit.longitude
    visit.shop_balance_before = original_shop_balance
    # +++ حماية قرار الإدارة: دمج حالة الطوارئ لمنع الموبايل من طمسها بالـ Default False +++
    visit.is_emergency = payload.is_emergency or visit.is_emergency
    visit.work_session_id = active_session.id

    # +++ الدرع الفولاذي ضد سرقة التأجيل (Postponed Theft Shield) +++
    # المندوب الخبيث قد يرسل تأجيلاً مع سلة مبيعات ليخصم البضاعة من عهدته دون محاسبة!
    if payload.outcome == 'Postponed' and (payload.cart_items or payload.returns or payload.debt_paid > 0):
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض أمنياً: لا يمكن تسجيل مبيعات أو مرتجعات أو تحصيل ذمم لزيارة حالتها (مؤجلة).")

    # +++ الدرع الفولاذي (تحديث بيزنس أبو علي): NoSale تعني لا يوجد مبيعات حقيقية. يُسمح بالمرتجعات والعينات فقط +++
    has_real_sales = any(i.quantity > 0 or i.packs_quantity > 0 for i in payload.cart_items) if payload.cart_items else False
    if payload.outcome == 'NoSale' and (has_real_sales or cash_collected > Decimal('0')):
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض أمنياً: لا يمكن تسجيل مبيعات حقيقية أو كاش نقدي لحالة (لا يوجد بيع). يسمح بالمرتجعات والعينات فقط، أو تحصيل ديون سابقة.")
    # +++ الدرع الجنائي O(1): فحص السقف اليومي للعينات ومنع تجاوز الحد المسموح به +++
    sample_items = [i for i in payload.cart_items if i.sample_quantity > 0 or getattr(i, 'sample_packs_quantity', 0) > 0]
    if sample_items:
        sample_pids = [i.product_variant_id for i in sample_items]
        
        # 1. جلب ما صرفه المندوب اليوم من هذه الأصناف
        today_start = datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time())
        stmt_past = select(VisitItem.product_variant_id, func.sum(VisitItem.sample_quantity * ProductVariant.packs_per_carton + getattr(VisitItem, 'sample_packs_quantity', 0))).join(Visit).join(ProductVariant).filter(
            Visit.driver_id == current_driver.id,
            Visit.visit_timestamp >= today_start,
            Visit.status == 'Completed',
            VisitItem.product_variant_id.in_(sample_pids)
        ).group_by(VisitItem.product_variant_id)
        
        past_samples_map = {row[0]: int(row[1] or 0) for row in (await db.execute(stmt_past)).all()}
        
        # 2. جلب السقوف المسموحة
        stmt_limits = select(ProductVariant).filter(ProductVariant.id.in_(sample_pids))
        limits_map = {v.id: v for v in (await db.execute(stmt_limits)).scalars().all()}
        
        for item in sample_items:
            var = limits_map.get(item.product_variant_id)
            if not var: continue
            
            ppc = var.packs_per_carton or 1
            requested_packs = (item.sample_quantity * ppc) + getattr(item, 'sample_packs_quantity', 0)
            past_packs = past_samples_map.get(item.product_variant_id, 0)
            
            # نفترض أن الحد الأقصى بالكراتين، نحوله لحبات (حسب البيزنس المتفق عليه)
            max_allowed_packs = (getattr(var, 'default_max_samples_per_day', 0) or 0) * ppc 
            
            # +++ النسف المعماري 1: إذا كان السقف 0 (بسبب عدم جاهزية الداشبورد)، نعتبره مفتوحاً مؤقتاً +++
            if max_allowed_packs > 0:
                if (past_packs + requested_packs) > max_allowed_packs:
                    # +++ النسف المعماري 2: بناء الرسالة قبل الـ rollback لمنع كراش الـ MissingGreenlet +++
                    max_cartons = max_allowed_packs // ppc
                    error_msg = f"مرفوض أمنياً: تجاوزت الحد المسموح من العينات لمنتج ({var.variant_name}). المسموح لك باليوم: {max_cartons} كرتونة."
                    await db.rollback()
                    raise HTTPException(status_code=400, detail=error_msg)


    # +++ حماية التلاعب بالسلة (Duplicate Items Check): منع المندوب من إرسال نفس الصنف مرتين لتجاوز العروض أو تكرار الفواتير +++
    cart_pids = [i.product_variant_id for i in payload.cart_items]
    ret_pids = [r.product_variant_id for r in payload.returns]
    if len(cart_pids) != len(set(cart_pids)) or len(ret_pids) != len(set(ret_pids)):
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض أمنياً: السلة أو المرتجعات تحتوي على أصناف مكررة. يرجى دمج الكميات لنفس الصنف.")

    # +++ الدرع الجنائي الشامل (Negative Print & Ghost Sale Shield) +++
    if payload.outcome == 'Sale' and not payload.cart_items:
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض أمنياً: لا يمكن تسجيل حالة (بيع) دون وجود منتجات فعلية في السلة.")
        
    for item in payload.cart_items:
        if item.quantity < 0 or item.packs_quantity < 0 or item.bonus_quantity < 0 or item.sample_quantity < 0 or item.sample_packs_quantity < 0:
            await db.rollback()
            raise HTTPException(status_code=400, detail="مرفوض أمنياً: تم رصد كميات سالبة في سلة المبيعات. محاولة تلاعب بالعهدة.")
            
    for item in payload.cart_items:
        if item.quantity < 0 or item.packs_quantity < 0 or item.bonus_quantity < 0 or item.sample_quantity < 0 or item.sample_packs_quantity < 0:
            await db.rollback()
            raise HTTPException(status_code=400, detail="مرفوض أمنياً: تم رصد كميات سالبة في سلة المبيعات. محاولة تلاعب بالعهدة.")

    # 4. +++ النسف المعماري لـ N+1: جلب كل المنتجات والعهدة دفعة واحدة للذاكرة +++
    all_var_ids = list(set(cart_pids + ret_pids))
    
    variants_map = {}
    inv_map = {}
    
    if all_var_ids:
        # جلب تفاصيل المنتجات
        stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(all_var_ids))
        variants_map = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}
        
        # جلب وقفل سجلات العهدة (ترتيب إجباري بالـ ID لمنع الـ Deadlock المتصالب)
        stmt_inv = select(SessionInventory).with_for_update().filter(
            SessionInventory.work_session_id == active_session.id,
            SessionInventory.product_variant_id.in_(all_var_ids)
        ).order_by(SessionInventory.product_variant_id.asc())
        inv_records = (await db.execute(stmt_inv)).scalars().all()
        inv_map = {inv.product_variant_id: inv for inv in inv_records}

    # 5. +++ حماية الذاكرة (Memory Desync Trap): مسح طفيليات الحفظ من الـ RAM مباشرة +++
    # تعديل الكائنات المحملة في الذاكرة لضمان تزامنها تلقائياً مع الداتابيز عند الـ Commit
    for existing_item in visit.items:
        if not getattr(existing_item, 'is_cancelled', False):
            existing_item.is_cancelled = True
            
    for existing_return in visit.returns:
        if not getattr(existing_return, 'is_cancelled', False):
            existing_return.is_cancelled = True

    # 6. معالجة سلة المبيعات (Cart Items)
    total_final_amount = Decimal('0.0')
    total_base_amount = Decimal('0.0')
    total_discount = Decimal('0.0')
    total_tax = Decimal('0.0')
    
    # جلب الإعدادات والعروض مرة واحدة لتقليل الضغط
    current_tax_pct = await get_setting(db, 'tax_percentage', '0.0')
    stmt_offers = select(OfferRule).filter_by(is_active=True).order_by(OfferRule.threshold_quantity.desc())
    active_offers = (await db.execute(stmt_offers)).scalars().all()

    for item in payload.cart_items:
        variant = variants_map.get(item.product_variant_id)
        if not variant:
            await db.rollback()
            raise HTTPException(status_code=404, detail=f"المنتج رقم {item.product_variant_id} غير موجود في النظام.")
            
        # +++ الدرع التجاري: منع بيع المنتجات الموقوفة أو المسحوبة من السوق (Recalled) +++
        if not variant.is_active:
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"مرفوض: المنتج ({variant.variant_name}) مسحوب من السوق أو موقوف حالياً ولا يمكن بيعه.")
        
        # حساب الفاتورة (Async Service) - مع تمرير سعة الكرتونة لتطبيق العروض بدقة
        invoice = calculate_invoice(item.quantity, item.packs_quantity, variant.price_per_carton, variant.price_per_pack, current_tax_pct, active_offers, packs_per_carton=variant.packs_per_carton or 1)
        
        # +++ الدرع المحاسبي: السقف الإجباري للبونص لمنع المندوب من اختلاس بضاعة تحت مسمى "عروض" +++
        final_bonus_cartons = invoice['bonus_units']

        # حماية العهدة: خصم (مبيعات + بونص نهائي + عينات)
        safe_ppc = variant.packs_per_carton or 1
        total_packs_to_deduct = (item.quantity * safe_ppc) + item.packs_quantity + \
                                (final_bonus_cartons * safe_ppc) + \
                                (item.sample_quantity * safe_ppc) + item.sample_packs_quantity
        
        inv_record = inv_map.get(item.product_variant_id)
        if not inv_record or inv_record.current_remaining_quantity < total_packs_to_deduct:
            await db.rollback()
            raise HTTPException(status_code=409, detail=f"مخزونك لا يكفي من {variant.variant_name}. المتبقي: {inv_record.current_remaining_quantity if inv_record else 0}")

        # الخصم الفعلي
        expected_qty = inv_record.current_remaining_quantity
        inv_record.current_remaining_quantity -= total_packs_to_deduct
        
        # توثيق البيع في دفتر الأستاذ
        db.add(InventoryLedger(
            work_session_id=active_session.id, driver_id=visit.driver_id,
            vehicle_id=current_route.vehicle_id if current_route else None, product_variant_id=item.product_variant_id,
            transaction_type='Sale', expected_quantity=expected_qty,
            actual_quantity=inv_record.current_remaining_quantity,
            difference=-total_packs_to_deduct, admin_id=visit.driver_id,
            notes=f"بيع للمحل: {shop.name}", timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
        ))

        # +++ الدرع الديناميكي: حماية السيرفر من الانفجار إذا كان عمود كسور العينات غير موجود بقاعدة البيانات +++
        visit_item_data = {
            "visit_id": visit.id, 
            "product_variant_id": item.product_variant_id,
            "quantity": item.quantity, 
            "packs_quantity": item.packs_quantity,
            "bonus_quantity": final_bonus_cartons, 
            "sample_quantity": item.sample_quantity,
            "sample_reason": item.sample_reason,
            "price_per_unit_at_sale": variant.price_per_carton, 
            "total_price": Decimal(str(invoice['final_amount']))
        }
        
        if hasattr(VisitItem, 'sample_packs_quantity'):
            visit_item_data["sample_packs_quantity"] = getattr(item, 'sample_packs_quantity', 0)
            
        db.add(VisitItem(**visit_item_data))

        total_final_amount += Decimal(str(invoice['final_amount']))
        total_base_amount += Decimal(str(invoice['base_amount']))
        total_discount += Decimal(str(invoice['discount_applied']))
        total_tax += Decimal(str(invoice['tax_amount']))
    
    # 7. +++ معالجة المرتجعات (Returns): حماية العهدة والرقابة المحاسبية +++
    for ret in payload.returns:
        variant = variants_map.get(ret.product_variant_id)
        if not variant:
            await db.rollback()
            raise HTTPException(status_code=404, detail=f"المنتج المرتجع رقم {ret.product_variant_id} غير موجود.")
        
        safe_ppc = variant.packs_per_carton or 1
        total_ret_packs = (ret.quantity * safe_ppc) + ret.packs_quantity
        
        inv_record = inv_map.get(ret.product_variant_id)
        
        # +++ الحماية من القيم المعدومة (TypeError Shield) +++
        expected_qty = (inv_record.current_remaining_quantity or 0) if inv_record else 0
        
        # +++ الدرع الأمني (Zero Trust - No Implicit Trust): الاعتماد على القائمة البيضاء (Whitelist) فقط +++
        # إذا أرسل التطبيق المهكر نوعاً وهمياً، سيتم رفض إدخاله للعهدة وعزله كتالف لمنع التلاعب بالمخزون.
        is_sellable = ret.return_type in ['Good', 'Resellable']
        
        if is_sellable:
            if not inv_record:
                # إنشاء سجل عهدة جديد إذا استلم المندوب صنفاً لم يكن معه صباحاً
                inv_record = SessionInventory(
                    work_session_id=active_session.id, 
                    product_variant_id=ret.product_variant_id, 
                    starting_quantity=0, 
                    current_remaining_quantity=0
                )
                db.add(inv_record)
                await db.flush() # +++ تأكيد الحفظ في الجلسة لمنع تضارب الأقفال +++
                inv_map[ret.product_variant_id] = inv_record # تحديث الذاكرة
            
            # تحديث الكمية بأمان
            inv_record.current_remaining_quantity = (inv_record.current_remaining_quantity or 0) + total_ret_packs
            
        # +++ النسف المعماري لنظام الاستبدال 1:1 (Exchange Logic) +++
        if not is_sellable:
            # إذا كان تالفاً فهذا يعني أنه "استبدال". نسحب بضاعة صالحة من المندوب ونعطيها للمحل.
            if not inv_record or inv_record.current_remaining_quantity < total_ret_packs:
                await db.rollback()
                raise HTTPException(status_code=400, detail=f"مرفوض: مخزونك الصالح من ({variant.variant_name}) لا يكفي للقيام باستبدال التوالف. المطلوب للتبديل: {total_ret_packs} حبة.")

            inv_record.current_remaining_quantity -= total_ret_packs

            # توثيق السحب الصالح (استبدال)
            db.add(InventoryLedger(
                work_session_id=active_session.id, driver_id=visit.driver_id,
                vehicle_id=current_route.vehicle_id if current_route else None,
                product_variant_id=ret.product_variant_id, transaction_type='Exchange (Deduction)',
                expected_quantity=expected_qty,
                actual_quantity=inv_record.current_remaining_quantity,
                difference=-total_ret_packs,
                admin_id=visit.driver_id,
                notes=f"استبدال 1:1 للمحل: {shop.name} | تم سحب بضاعة صالحة مقابل استلام ({ret.return_type})",
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
            ))

        # +++ الدرع الرقابي: توثيق دخول المرتجع/التالف لسيارة المندوب +++
        ret_reason_text = f" | السبب: {ret.reason}" if ret.reason else ""
        db.add(InventoryLedger(
            work_session_id=active_session.id, driver_id=visit.driver_id,
            vehicle_id=current_route.vehicle_id if current_route else None, 
            product_variant_id=ret.product_variant_id, transaction_type='Return (Addition)',
            expected_quantity=expected_qty, 
            actual_quantity=expected_qty + (total_ret_packs if is_sellable else 0),
            difference=(total_ret_packs if is_sellable else 0), 
            admin_id=visit.driver_id, 
            notes=f"مرتجع {ret.return_type} للمحل: {shop.name}{ret_reason_text}",
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
        ))
        
        db.add(VisitReturn(
            visit_id=visit.id, product_variant_id=ret.product_variant_id,
            quantity=ret.quantity, packs_quantity=ret.packs_quantity,
            return_type=ret.return_type, reason=ret.reason
        ))
    
    # ------------------ (بداية القسم الثالث: المحرك المالي وتصفية الديون) ------------------
    # 1. +++ الدرع المالي لمنع السرقة: منع تحصيل كاش يتجاوز قيمة الفاتورة +++
    if payload.outcome == 'Sale':
        if cash_collected > total_final_amount:
            await db.rollback()
            raise HTTPException(
                status_code=400, 
                detail=f"مرفوض: النقد المحصل ({cash_collected}) لا يمكن أن يتجاوز قيمة الفاتورة ({total_final_amount}). لسداد الديون السابقة استخدم حقل التحصيل المخصص."
            )

        new_debt = total_final_amount - cash_collected
        
        # +++ فحص سقف الدين (Async Service) +++
        if new_debt > Decimal('0'):
            is_allowed, msg = await check_debt_limits(db, visit.driver_id, shop.id, new_debt, pre_fetched_driver=current_driver, pre_fetched_shop=shop)
            if not is_allowed:
                await db.rollback()
                raise HTTPException(status_code=403, detail=msg)
    else:
        # تصفير العدادات إذا لم تكن عملية بيع
        new_debt = Decimal('0.0')
        total_final_amount = Decimal('0.0')
        total_base_amount = Decimal('0.0')
        total_discount = Decimal('0.0')
        total_tax = Decimal('0.0')

    # 2. حفظ العدادات المالية للزيارة
    visit.amount_before_tax_and_discount = total_base_amount
    visit.discount_applied = total_discount
    visit.tax_amount = total_tax
    visit.final_amount_due = total_final_amount
    visit.cash_collected = cash_collected if payload.outcome == 'Sale' else Decimal('0.0')
    visit.debt_paid = debt_paid_input if payload.outcome != 'Postponed' else Decimal('0.0')

    # 3. +++ تنظيف التناقض المنطقي (Data Sanitization) +++
    if payload.outcome == 'NoSale':
        visit.no_sale_reason = payload.notes
    elif payload.outcome == 'Sale':
        visit.no_sale_reason = None
    elif payload.outcome == 'Postponed':
        visit.no_sale_reason = payload.notes

    # 4. المعالجة المحاسبية الشاملة لرصيد المحل
    # Fix: driver.md Finding #1 — Outdent accounting block to execute for ALL non-postponed outcomes
    if payload.outcome != 'Postponed':
        new_balance = original_shop_balance + new_debt - debt_paid_input
        
        # +++ النسف المعماري (Hard Fail): منع إخفاء العجز المحاسبي بصمت +++
        if new_balance < Decimal('0'):
            await db.rollback()
            raise HTTPException(
                status_code=400, 
                detail=f"مرفوض محاسبياً: التحصيل أكبر من إجمالي الدين. الرصيد سيصبح بالسالب ({new_balance})."
            )
            
        shop.current_balance = new_balance
        visit.shop_balance_after = new_balance

        # دفتر الأستاذ لتحصيل الديون (Audit Trail)
        if debt_paid_input > Decimal('0'):
            db.add(SystemAuditLog(
                admin_id=visit.driver_id,
                target_id=f"Shop_{shop.id}_Visit_{visit.id}",
                action_type="DEBT_COLLECTION",
                old_value=f"Balance: {original_shop_balance}",
                new_value=f"Collected: {debt_paid_input} | New Balance: {new_balance}"
            ))
    else:
        # إذا كانت الزيارة مؤجلة، الرصيد لا يتأثر
        visit.shop_balance_after = original_shop_balance

    # 5. +++ إغلاق الطوارئ وفرز المحلات بدقة (النسف المعماري للزومبي) +++
    if payload.outcome in ['Sale', 'NoSale']:
        if has_active_shortage: # المتغير من القسم الأول
            stmt_close_shortage = update(ShortageRequest).where(
                ShortageRequest.shop_id == shop.id, ShortageRequest.status == 'pending'
            ).values(status='fulfilled')
            await db.execute(stmt_close_shortage)

        # إذا كان المحل الطارئ في نفس منطقة المندوب، نسحب عنه ختم الطوارئ 
        # ونمسح الزيارات (Pending) المكررة لمنع ظهوره مرتين في الموبايل
        if current_route and shop.zone_id == current_route.zone_id:
            visit.is_emergency = False
            
            stmt_del_dups = delete(Visit).where(
                Visit.shop_id == shop.id,
                Visit.driver_id == active_session.driver_id,
                Visit.status == 'Pending',
                Visit.id != visit.id
            )
            await db.execute(stmt_del_dups)

    # 6. +++ الختم النهائي للعملية +++
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء حفظ الزيارة.")

    return {
        "message": "Visit updated successfully",
        # +++ الدرع المالي للواجهة: إرسال الرقم كنص (String) لمنع فقدان القروش في الـ Frontend +++
        "new_balance": str(shop.current_balance or '0.0') 
    }
    # ------------------ (نهاية الدالة الأسطورية) ------------------


# =========================================
# 5. جلب بيانات الداشبورد للمندوب (النسخة الأصلية الكاملة)
# =========================================
@router.get("/driver/{driver_id}/dashboard", status_code=200)
async def get_driver_dashboard(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    if current_driver.id != driver_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # 1. +++ توحيد رؤية الـ Dashboard مع الميدان: قراءة كل الحالات النشطة لمنع عمى الشاشة +++
    stmt_route = select(DispatchRoute).filter(
        DispatchRoute.driver_id == driver_id, 
        DispatchRoute.status.in_(['active', 'waiting', 'postponed'])
    )
    active_route = (await db.execute(stmt_route)).scalars().first()
    
    # 2. جلب أحدث جلسة معلقة بأمان
    stmt_session = select(WorkSession).filter_by(driver_id=driver_id, is_settled=False).order_by(WorkSession.id.desc())
    active_session = (await db.execute(stmt_session)).scalars().first()

    assigned_region = "غير محددة"
    inventory_list = []

    # 3. اللوجيك الأصلي: إذا تم إطلاق خط سير، أرسل المنطقة والحمولة
    if active_route:
        zone = await db.get(Zone, active_route.zone_id)
        if zone:
            assigned_region = zone.name

        # جلب الحمولة من السيارة إذا لم تبدأ الجلسة بعد
        if not active_session:
            stmt_vloads = select(VehicleLoad, ProductVariant).join(
                ProductVariant, VehicleLoad.product_variant_id == ProductVariant.id
            ).filter(VehicleLoad.vehicle_id == active_route.vehicle_id)
            
            vehicle_loads = (await db.execute(stmt_vloads)).all()
            
            for load, variant in vehicle_loads:
                inventory_list.append({
                    "product_id": variant.id,
                    "product_name": variant.variant_name,
                    "starting_cartons": load.quantity,
                    "remaining_cartons": load.quantity,
                    "remaining_packs": 0 
                })

    # 4. إذا بدأت الجلسة الفعلية، نعتمد على جرد الجلسة
    if active_session:
        stmt_sinvs = select(SessionInventory).options(joinedload(SessionInventory.product_variant)).filter_by(work_session_id=active_session.id).order_by(SessionInventory.product_variant_id.asc())
        inventories = (await db.execute(stmt_sinvs)).scalars().all()
        
        inventory_list = [] 
        for inv in inventories:
            variant = inv.product_variant
            packs = variant.packs_per_carton if variant and variant.packs_per_carton and variant.packs_per_carton > 0 else 1
            
            # +++ الدرع المعماري للواجهة: دمج المصافحات (net_transfers) لكي لا يرى المندوب رصيداً حالياً أكبر من رصيد البداية +++
            total_received = inv.starting_quantity + (inv.net_transfers or 0)
            
            inventory_list.append({
                "product_id": variant.id,
                "product_name": variant.variant_name,
                "starting_cartons": total_received // packs,
                "remaining_cartons": inv.current_remaining_quantity // packs,
                "remaining_packs": inv.current_remaining_quantity % packs
            })

    # 5. حساب الماليات والزيارات
    total_sales_cash = Decimal('0.0')
    total_debt_paid = Decimal('0.0')
    debt_payments_count = 0
    total_completed = 0
    sales_in_completed = 0
    total_pending = 0

    if active_session:
        stmt_stats = select(
            func.count(Visit.id).label('total_visits'),
            func.sum(Visit.cash_collected).label('total_cash'),
            func.sum(Visit.debt_paid).label('total_debt')
        ).filter(Visit.work_session_id == active_session.id, Visit.status == 'Completed')
        stats = (await db.execute(stmt_stats)).first()

        if stats:
            total_completed = stats.total_visits or 0
            # +++ تطهير الـ Float: الاحتفاظ بالقيم كـ Decimal نقي لمنع تآكل القروش +++
            total_sales_cash = Decimal(str(stats.total_cash or '0.0'))
            total_debt_paid = Decimal(str(stats.total_debt or '0.0'))
        
        stmt_debt_count = select(func.count(Visit.id)).filter(Visit.work_session_id == active_session.id, Visit.status == 'Completed', Visit.debt_paid > 0)
        debt_payments_count = (await db.execute(stmt_debt_count)).scalar() or 0
        
        # +++ الدرع المحاسبي: المبيعات الحقيقية تشمل المبيعات النقدية و(مبيعات الذمم)، لذلك نعتمد على Outcome +++
        stmt_sales_count = select(func.count(Visit.id)).filter(Visit.work_session_id == active_session.id, Visit.outcome == 'Sale')
        sales_in_completed = (await db.execute(stmt_sales_count)).scalar() or 0

        if active_route:
            stmt_pending = select(func.count(Visit.id)).join(Shop).filter(
                Visit.driver_id == driver_id,
                Visit.status == 'Pending',
                Shop.is_archived == False,
                or_(
                    Shop.zone_id == active_route.zone_id,
                    Visit.is_emergency == True
                )
            )
            total_pending = (await db.execute(stmt_pending)).scalar() or 0
        else:
            total_pending = 0

    elif active_route:
        # +++ تصحيح الخطأ الموروث: استثناء المحلات مؤرشفة حتى لو لم تبدأ الجلسة +++
        stmt_pending = select(func.count(Visit.id)).join(Shop).filter(
            Visit.driver_id == driver_id, 
            Visit.status == 'Pending',
            Shop.zone_id == active_route.zone_id,
            Shop.is_archived == False
        )
        total_pending = (await db.execute(stmt_pending)).scalar() or 0

    response_data = {
        "driver_name": current_driver.full_name,
        "assigned_region": assigned_region,
        "active_session": {
            "session_id": active_session.id,
            # +++ النسف المعماري لانفصام الزمن: إضافة الـ UTC Timezone إجبارياً لكي لا يقرأه Flutter كـ Local Time +++
            "start_time": active_session.start_time.replace(tzinfo=timezone.utc).isoformat() if active_session.start_time else None,
            "is_authorized_to_sell": active_session.is_authorized_to_sell,
            "break_start_time": active_session.break_start_time.replace(tzinfo=timezone.utc).isoformat() if active_session.break_start_time else None,
            "break_end_time": active_session.break_end_time.replace(tzinfo=timezone.utc).isoformat() if active_session.break_end_time else None,
            "inventory": inventory_list
        } if active_session else None,
        "financials": {
            # إرسال الأموال كنصوص دقيقة لتطبيق الموبايل
            "total_sales_cash": str(total_sales_cash),
            "total_debt_paid": str(total_debt_paid),
            "debt_payments_count": debt_payments_count,
            "total_cash_overall": str(total_sales_cash + total_debt_paid)
        },
        "counts": {
            "total_pending": total_pending,
            "total_completed": total_completed,
            "sales_in_completed": sales_in_completed
        }
    }
    
    if not active_session and active_route:
        response_data['active_session'] = {
            "session_id": None,
            "start_time": None,
            "is_authorized_to_sell": False,
            "inventory": inventory_list
        }

    return response_data

# =========================================
# 6. تأكيد استلام/رفض حوالة منتصف اليوم (المصافحة - Zero Trust)
# =========================================
@router.put("/driver/transfers/{transfer_id}/respond", status_code=200)
async def respond_to_transfer(
    transfer_id: int,
    payload: TransferResponseRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # 1. جلب الحوالة وقفل السطر مع شحن تفاصيل الجلسة والمنتج معاً بصدمة واحدة (Eager Loading)
    stmt_transfer = select(InventoryTransfer).options(
        joinedload(InventoryTransfer.work_session),
        joinedload(InventoryTransfer.product_variant) # +++ الدرع الفولاذي لمنع الـ Lazy Loading Crash وسحق الـ N+1 +++
    ).filter_by(id=transfer_id).with_for_update(of=InventoryTransfer) # +++ درع الـ Deadlock: قفل جدول الحوالات فقط +++
    transfer = (await db.execute(stmt_transfer)).scalar_one_or_none()
    
    if not transfer:
        await db.rollback() # إغلاق القفل قبل الخروج
        raise HTTPException(status_code=404, detail="الحوالة المطلوبة غير موجودة.")
        
    if transfer.work_session.driver_id != current_driver.id:
        await db.rollback()
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: هذه الحوالة لا تخصك.")
        
    if transfer.status != 'pending':
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"هذه الحوالة تمت معالجتها مسبقاً بحالة: {transfer.status}")

    try:
        transfer.status = payload.response
        
        # جلب بيانات خط السير والمنتج (بدون قفل حالياً)
        stmt_route = select(DispatchRoute).filter_by(work_session_id=transfer.work_session_id)
        route = (await db.execute(stmt_route)).scalars().first()
        
        # +++ سحق الاستعلام المكرر: قراءة المنتج مباشرة من الـ RAM بعد شحنه استباقياً وتوفير Query كاملة +++
        variant = transfer.product_variant
        packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton else 1

        # +++ النسف المعماري الشامل للـ Deadlock: توحيد الأقفال مع dispatch.py (السيارة -> المستودع -> العهدة) +++
        v_load = None
        if route:
            # 1. قفل حمولة السيارة أولاً
            stmt_vload = select(VehicleLoad).filter_by(
                vehicle_id=route.vehicle_id, product_variant_id=transfer.product_variant_id
            ).with_for_update()
            v_load = (await db.execute(stmt_vload)).scalars().first()

        # 2. قفل المستودع المركزي ثانياً
        stmt_wh = select(MainWarehouse).filter_by(product_variant_id=transfer.product_variant_id).with_for_update()
        wh_record = (await db.execute(stmt_wh)).scalars().first()
        if not wh_record:
            wh_record = MainWarehouse(product_variant_id=transfer.product_variant_id, available_quantity_packs=0, reserved_quantity_packs=0)
            db.add(wh_record)
            await db.flush()

        # 3. قفل عهدة المندوب ثالثاً
        stmt_sess_inv = select(SessionInventory).filter_by(
            work_session_id=transfer.work_session_id, product_variant_id=transfer.product_variant_id
        ).with_for_update()
        sess_inv = (await db.execute(stmt_sess_inv)).scalars().first()
        
        expected_qty = (sess_inv.current_remaining_quantity or 0) if sess_inv else 0

        if payload.response == 'accepted':
            # +++ درع الأصناف النشطة لمنع استلام منتجات معطلة +++
            if transfer.quantity_packs > 0 and variant and not variant.is_active:
                await db.rollback() # +++ الدرع الفولاذي: تحرير الأقفال لمنع الشلل +++
                raise HTTPException(status_code=400, detail=f"مرفوض: لا يمكنك استلام حمولة جديدة من المنتج ({variant.variant_name}) لأنه موقوف حالياً.")

            # +++ الدرع الفولاذي: منع الرصيد السالب عند سحب بضاعة من المندوب +++
            if transfer.quantity_packs < 0:
                if not sess_inv or (sess_inv.current_remaining_quantity + transfer.quantity_packs < 0):
                    await db.rollback() # +++ الدرع الفولاذي: تحرير الأقفال لمنع الشلل +++
                    raise HTTPException(
                        status_code=400, 
                        detail=f"فشل التأكيد: رصيدك من {variant.variant_name if variant else 'هذا الصنف'} لا يكفي للسحب. المتاح: {expected_qty}"
                    )

            if transfer.quantity_packs > 0:
                wh_record.reserved_quantity_packs = max(0, wh_record.reserved_quantity_packs - transfer.quantity_packs)
                db.add(WarehouseLedger(
                    product_variant_id=transfer.product_variant_id, transaction_type='HANDSHAKE_COMMIT',
                    quantity_packs=transfer.quantity_packs, balance_after_packs=wh_record.available_quantity_packs,
                    admin_id=transfer.admin_id, reference_id=f"TRANS_{transfer.id}", 
                    notes=f"موافقة المندوب: تحرير المحجوز للعهدة الفردية. (المحجوز المتبقي: {wh_record.reserved_quantity_packs})"
                ))
            else:
                wh_record.available_quantity_packs += abs(transfer.quantity_packs)
                db.add(WarehouseLedger(
                    product_variant_id=transfer.product_variant_id, transaction_type='HANDSHAKE_COMMIT_PULL',
                    quantity_packs=abs(transfer.quantity_packs), balance_after_packs=wh_record.available_quantity_packs,
                    admin_id=transfer.admin_id, reference_id=f"TRANS_{transfer.id}", 
                    notes=f"موافقة المندوب: استرجاع بضاعة مسحوبة للمستودع الفردي المتاح. (المحجوز الحالي: {wh_record.reserved_quantity_packs})"
                ))

            # أ. تحديث عهدة المندوب الحية (بالحبات)
            if sess_inv:
                sess_inv.current_remaining_quantity += transfer.quantity_packs
                sess_inv.net_transfers = (sess_inv.net_transfers or 0) + transfer.quantity_packs
            else:
                sess_inv = SessionInventory(
                    work_session_id=transfer.work_session_id, 
                    product_variant_id=transfer.product_variant_id, 
                    starting_quantity=0, 
                    net_transfers=transfer.quantity_packs, 
                    current_remaining_quantity=transfer.quantity_packs
                )
                db.add(sess_inv)
                
            await db.flush() 
                
            audit_notes = "موافقة المندوب الرقمية (مصافحة)"
                
            # ب. تحديث حمولة السيارة (VehicleLoad) - مع سحق ثغرة السحب المخفي
            if route:
                # السيارة مقفلة مسبقاً في الأعلى لمنع הـ Cross-Module Deadlock
                
                # +++ الدرع المحاسبي (Anti-Theft): استخدام الرياضيات المطلقة لمنع ثغرة بايثون في القسمة السالبة التي تؤدي لاختلاس المخزون +++
                sign = -1 if transfer.quantity_packs < 0 else 1
                abs_packs = abs(transfer.quantity_packs)
                delta_cartons = (abs_packs // packs_per_carton) * sign
                remaining_packs = (abs_packs % packs_per_carton) * sign
                
                if v_load:
                    if v_load.quantity + delta_cartons < 0:
                        await db.rollback() # +++ الدرع الفولاذي: تحرير الأقفال لمنع الشلل +++
                        raise HTTPException(status_code=400, detail="فشل: حمولة السيارة المسجلة لا تكفي للسحب.")
                    v_load.quantity += delta_cartons
                else:
                    if delta_cartons < 0:
                        await db.rollback() # +++ الدرع الفولاذي: تحرير الأقفال لمنع الشلل +++
                        raise HTTPException(status_code=400, detail="فشل محاسبي: لا يمكن سحب كراتين لمنتج غير مسجل بحمولة السيارة أصلاً.")
                    elif delta_cartons > 0:
                        db.add(VehicleLoad(
                            vehicle_id=route.vehicle_id, 
                            product_variant_id=transfer.product_variant_id, 
                            quantity=delta_cartons
                        ))
                        
                # توثيق الكسور المحاسبية المتماثلة في الدفتر
                if remaining_packs > 0:
                    audit_notes += f" | كسور: تم إضافة {remaining_packs} حبة حية للعهدة ولم تزد كراتين السيارة."
                elif remaining_packs < 0:
                    audit_notes += f" | كسور: تم سحب {abs(remaining_packs)} حبة حية من العهدة ولم تنقص كراتين السيارة."

            # ج. توثيق الحركة في دفتر الأستاذ (InventoryLedger)
            trans_type = 'تأكيد استلام حمولة' if transfer.quantity_packs > 0 else 'تأكيد سحب حمولة'
            db.add(InventoryLedger(
                work_session_id=transfer.work_session_id, 
                driver_id=current_driver.id, 
                vehicle_id=route.vehicle_id if route else None,
                product_variant_id=transfer.product_variant_id, 
                transaction_type=trans_type,
                expected_quantity=expected_qty, 
                actual_quantity=expected_qty + transfer.quantity_packs,
                difference=transfer.quantity_packs, 
                admin_id=transfer.admin_id, 
                notes=audit_notes
            ))

        elif payload.response == 'rejected':
            # +++ مزامنة الرفض الفردي: تحرير المحجوز وإعادته للمتاح في المستودع المركزي فوراً +++
            if transfer.quantity_packs > 0:
                wh_record.reserved_quantity_packs = max(0, wh_record.reserved_quantity_packs - transfer.quantity_packs)
                wh_record.available_quantity_packs += transfer.quantity_packs
                db.add(WarehouseLedger(
                    product_variant_id=transfer.product_variant_id, transaction_type='HANDSHAKE_RELEASE',
                    quantity_packs=transfer.quantity_packs, balance_after_packs=wh_record.available_quantity_packs,
                    admin_id=transfer.admin_id, reference_id=f"TRANS_{transfer.id}", 
                    notes=f"رفض المندوب الفردي: إرجاع المحجوز للمتاح. (المحجوز المتبقي: {wh_record.reserved_quantity_packs})"
                ))

            trans_type = 'تعارض: رفض استلام حمولة' if transfer.quantity_packs > 0 else 'تعارض: رفض سحب حمولة'
            db.add(InventoryLedger(
                work_session_id=transfer.work_session_id, 
                driver_id=current_driver.id, 
                vehicle_id=route.vehicle_id if route else None,
                product_variant_id=transfer.product_variant_id, 
                transaction_type=trans_type,
                expected_quantity=expected_qty, 
                actual_quantity=expected_qty, 
                difference=0, 
                admin_id=transfer.admin_id, 
                notes=f"سجل النظام تعارضاً: المندوب رفض طلب {'الاستلام' if transfer.quantity_packs > 0 else 'السحب'}."
            ))

        await db.commit()
        return {"message": f"تم تسجيل الرد ({payload.response}) بنجاح."}

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=409, 
            detail="فشل العملية: لا يمكن إتمام المعاملة لأن الرصيد سيصبح بالسالب في المستودع أو السيارة."
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء معالجة الحوالة.")

# =========================================
# 7 معالجة الحوالات بالجملة (Batch Response) - نسف الـ HTTP N+1
# =========================================
@router.put("/driver/transfers/batch_respond", status_code=200)
async def batch_respond_to_transfers(
    payload: BatchTransferResponseRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # +++ إبطال ثغرة DDoS: وضع سقف للدفعة لحماية الرام والداتابيز +++
    if not payload.transfers:
        raise HTTPException(status_code=400, detail="بيانات الطلب غير مكتملة.")
    if len(payload.transfers) > 100:
        raise HTTPException(status_code=413, detail="الدفعة كبيرة جداً. الحد الأقصى 100 حوالة في الطلب الواحد.")

    transfer_ids = [t.transfer_id for t in payload.transfers]
    status_map = {t.transfer_id: t.status for t in payload.transfers}

    try:
        # 1. درع IDOR
        stmt_transfers = select(InventoryTransfer).join(WorkSession).filter(
            InventoryTransfer.id.in_(transfer_ids),
            InventoryTransfer.status == 'pending',
            WorkSession.driver_id == current_driver.id
        ).with_for_update(of=InventoryTransfer).order_by(InventoryTransfer.id.asc()) # +++ درع الـ Deadlock: قفل الحوالات فقط +++
        
        transfers = (await db.execute(stmt_transfers)).scalars().all()

        if not transfers:
            await db.rollback()
            raise HTTPException(status_code=404, detail="لا يوجد حوالات صالحة للمعالجة أو لا تخصك.")

        # 2. +++ النسف المعماري (Multi-Session Bug): استخراج كل الجلسات والمنتجات بدقة +++
        var_ids = list(set([t.product_variant_id for t in transfers]))
        session_ids = list(set([t.work_session_id for t in transfers]))

        # جلب المنتجات (بدون is_active للسماح بتصفية المنتجات الموقوفة)
        stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(var_ids))
        variants_map = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}

        # +++ توفير הـ CPU: إنشاء خريطة التعبئة مرة واحدة خارج اللوب +++
        var_packs_map = {v.id: (v.packs_per_carton if v.packs_per_carton else 1) for v in variants_map.values()}

        # جلب خطوط السير وتحديد السيارات
        stmt_routes = select(DispatchRoute).filter(DispatchRoute.work_session_id.in_(session_ids))
        routes = (await db.execute(stmt_routes)).scalars().all()
        route_map = {r.work_session_id: r for r in routes}
        vehicle_ids = list(set([r.vehicle_id for r in routes if r.vehicle_id]))

        # 1. جلب وقفل سيارات الشركة أولاً (لمطابقة معمارية dispatch.py ونسف הـ Deadlock)
        v_load_map = {}
        if vehicle_ids:
            stmt_vloads = select(VehicleLoad).filter(
                VehicleLoad.vehicle_id.in_(vehicle_ids), 
                VehicleLoad.product_variant_id.in_(var_ids)
            ).with_for_update().order_by(VehicleLoad.vehicle_id.asc(), VehicleLoad.product_variant_id.asc())
            v_loads = (await db.execute(stmt_vloads)).scalars().all()
            v_load_map = {(vl.vehicle_id, vl.product_variant_id): vl for vl in v_loads}

        # 2. جلب وقفل المستودع المركزي ثانياً
        stmt_wh = select(MainWarehouse).filter(
            MainWarehouse.product_variant_id.in_(var_ids)
        ).with_for_update().order_by(MainWarehouse.product_variant_id.asc())
        bulk_warehouse = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}

        for v_id in var_ids:
            if v_id not in bulk_warehouse:
                new_wh = MainWarehouse(product_variant_id=v_id, available_quantity_packs=0, reserved_quantity_packs=0)
                db.add(new_wh)
                bulk_warehouse[v_id] = new_wh
        await db.flush()

        # 3. جلب وقفل عهدة المندوب ثالثاً
        stmt_sess_inv = select(SessionInventory).filter(
            SessionInventory.work_session_id.in_(session_ids), 
            SessionInventory.product_variant_id.in_(var_ids)
        ).with_for_update().order_by(SessionInventory.work_session_id.asc(), SessionInventory.product_variant_id.asc())
        sess_invs = (await db.execute(stmt_sess_inv)).scalars().all()
        sess_inv_map = {(si.work_session_id, si.product_variant_id): si for si in sess_invs}

        # 3. آلة الزمن (Execution Loop)
        for transfer in transfers:
            current_response = status_map.get(transfer.id)
            if current_response not in ['accepted', 'rejected']: continue
            
            transfer.status = current_response
            p_id = transfer.product_variant_id
            w_session_id = transfer.work_session_id
            
            variant = variants_map.get(p_id)
            sess_inv = sess_inv_map.get((w_session_id, p_id))
            expected_qty = sess_inv.current_remaining_quantity if sess_inv else 0
            route = route_map.get(w_session_id)
            
            wh_record = bulk_warehouse.get(p_id)
            if not wh_record:
                wh_record = MainWarehouse(product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
                db.add(wh_record)
                bulk_warehouse[p_id] = wh_record

            if current_response == 'accepted':
                # +++ درع الأصناف النشطة: المندوب يمكنه إرجاع (Pull) صنف موقوف، لكن لا يمكنه استلام (Push) صنف جديد موقوف +++
                if transfer.quantity_packs > 0 and variant and not variant.is_active:
                    await db.rollback()
                    raise HTTPException(status_code=400, detail=f"مرفوض: لا يمكنك استلام حمولة جديدة من المنتج ({variant.variant_name}) لأنه موقوف حالياً.")
                # +++ منع الرصيد السالب عند السحب +++
                if transfer.quantity_packs < 0 and (not sess_inv or sess_inv.current_remaining_quantity + transfer.quantity_packs < 0):
                    await db.rollback()
                    raise HTTPException(status_code=400, detail=f"فشل: رصيدك من {variant.variant_name if variant else p_id} لا يكفي للسحب.")

                # أ. المعالجة المحاسبية للمستودع المركزي
                if transfer.quantity_packs > 0:
                    wh_record.reserved_quantity_packs = max(0, wh_record.reserved_quantity_packs - transfer.quantity_packs)
                    db.add(WarehouseLedger(
                        product_variant_id=p_id, transaction_type='HANDSHAKE_COMMIT',
                        quantity_packs=transfer.quantity_packs, balance_after_packs=wh_record.available_quantity_packs,
                        admin_id=transfer.admin_id, reference_id=f"TRANS_{transfer.id}", 
                        notes=f"موافقة المندوب: تحرير المحجوز للعهدة. (المحجوز المتبقي: {wh_record.reserved_quantity_packs})"
                    ))
                else:
                    wh_record.available_quantity_packs += abs(transfer.quantity_packs)
                    db.add(WarehouseLedger(
                        product_variant_id=p_id, transaction_type='HANDSHAKE_COMMIT_PULL',
                        quantity_packs=abs(transfer.quantity_packs), balance_after_packs=wh_record.available_quantity_packs,
                        admin_id=transfer.admin_id, reference_id=f"TRANS_{transfer.id}", 
                        notes=f"موافقة المندوب: استرجاع بضاعة للمستودع المتاح. (المحجوز الحالي: {wh_record.reserved_quantity_packs})"
                    ))

                # ب. تحديث عهدة المندوب الحية
                if sess_inv:
                    sess_inv.current_remaining_quantity += transfer.quantity_packs
                    sess_inv.net_transfers = (sess_inv.net_transfers or 0) + transfer.quantity_packs
                else:
                    sess_inv = SessionInventory(
                        work_session_id=w_session_id, product_variant_id=p_id, 
                        starting_quantity=0, net_transfers=transfer.quantity_packs, 
                        current_remaining_quantity=transfer.quantity_packs
                    )
                    db.add(sess_inv)
                    sess_inv_map[(w_session_id, p_id)] = sess_inv
                    
                # ج. تحديث السيارة (القسمة الآمنة ومعالجة ثغرات السحب والكسور العكسية)
                audit_notes = f"معالجة مصافحة جماعية - رقم الحوالة: {transfer.id}"
                if route and route.vehicle_id:
                    safe_packs = var_packs_map.get(p_id, 1) 
                    # +++ الدرع المحاسبي (Anti-Theft): حماية قسمة الأرقام السالبة لمنع اختلاس الكسرات +++
                    sign = -1 if transfer.quantity_packs < 0 else 1
                    abs_packs = abs(transfer.quantity_packs)
                    delta_cartons = (abs_packs // safe_packs) * sign
                    remaining_packs = (abs_packs % safe_packs) * sign
                    
                    v_load = v_load_map.get((route.vehicle_id, p_id))
                    if v_load: 
                        if v_load.quantity + delta_cartons < 0:
                            await db.rollback()
                            raise HTTPException(status_code=400, detail=f"فشل: حمولة السيارة المسجلة من المنتج ({variant.variant_name if variant else p_id}) لا تكفي للسحب.")
                        v_load.quantity += delta_cartons
                    else:
                        # +++ إصلاح ثغرة السحب المخفي: منع سحب كميات لمنتج غير مدرج أصلاً بالسيارة +++
                        if delta_cartons < 0:
                            await db.rollback()
                            raise HTTPException(status_code=400, detail=f"فشل محاسبي: لا يمكن سحب كراتين لمنتج غير مسجل بحمولة السيارة أصلاً.")
                        elif delta_cartons > 0: 
                            new_v_load = VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=p_id, quantity=delta_cartons)
                            db.add(new_v_load)
                            v_load_map[(route.vehicle_id, p_id)] = new_v_load
                        
                    # +++ تصحيح لغة التدقيق المحاسبي للكسور السلبية والموجبة بدقة +++
                    if remaining_packs > 0:
                        audit_notes += f" | كسور: تم إضافة {remaining_packs} حبة حية للعهدة ولم تزد كراتين السيارة."
                    elif remaining_packs < 0:
                        audit_notes += f" | كسور: تم سحب {abs(remaining_packs)} حبة حية من العهدة ولم تنقص كراتين السيارة."

            elif current_response == 'rejected':
                audit_notes = f"رفض مصافحة جماعية - رقم الحوالة: {transfer.id}"
                if transfer.quantity_packs > 0:
                    wh_record.reserved_quantity_packs = max(0, wh_record.reserved_quantity_packs - transfer.quantity_packs)
                    wh_record.available_quantity_packs += transfer.quantity_packs
                    db.add(WarehouseLedger(
                        product_variant_id=p_id, transaction_type='HANDSHAKE_RELEASE',
                        quantity_packs=transfer.quantity_packs, balance_after_packs=wh_record.available_quantity_packs,
                        admin_id=transfer.admin_id, reference_id=f"TRANS_{transfer.id}", 
                        notes=f"رفض المندوب: إرجاع المحجوز للمتاح. (المحجوز المتبقي: {wh_record.reserved_quantity_packs})" # +++ توثيق المحجوز +++
                    ))

            # توثيق حركة المندوب
            db.add(InventoryLedger(
                work_session_id=w_session_id, driver_id=current_driver.id, vehicle_id=route.vehicle_id if route else None,
                product_variant_id=p_id, transaction_type=f"Batch {current_response.capitalize()}",
                expected_quantity=expected_qty, actual_quantity=expected_qty + (transfer.quantity_packs if current_response == 'accepted' else 0),
                difference=transfer.quantity_packs if current_response == 'accepted' else 0, admin_id=transfer.admin_id,
                notes=audit_notes
            ))

        await db.commit()
        return {"message": f"تمت معالجة {len(transfers)} حوالة بنجاح."}

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=409, detail="فشل العملية: تعارض في قاعدة البيانات.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي في المعالجة الجماعية.")

# =========================================
# 8. التحقق من وجود حوالات معلقة (للمندوب - Polling)
# =========================================
@router.get("/driver/{driver_id}/transfers/pending", response_model=List[PendingBatchResponse], status_code=200)
async def get_pending_transfers(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # 1. الدرع الأمني (IDOR)
    if current_driver.id != driver_id:
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: لا يمكنك استعراض حوالات غيرك.")

    # 2. جلب الجلسة النشطة
    stmt_session = select(WorkSession).filter_by(driver_id=driver_id, end_time=None)
    active_session = (await db.execute(stmt_session)).scalars().first()

    if not active_session:
        return []

    # 3. نسف الـ N+1 الشرس بجلب الحوالات والمنتجات بضربة واحدة 
    stmt_transfers = select(InventoryTransfer).options(
        joinedload(InventoryTransfer.product_variant)
    ).filter_by(
        work_session_id=active_session.id,
        status='pending'
    ).order_by(InventoryTransfer.created_at.asc())
    
    pending_transfers = (await db.execute(stmt_transfers)).scalars().all()

    batches = {}
    for t in pending_transfers:
        # الحفاظ على عقد الموبايل الأصلي (Legacy Contract) لمنع انهيار الـ Bloc
        batch_id = t.notes if (t.notes and "BATCH_" in t.notes) else f"SINGLE_{t.id}"

        if batch_id not in batches:
            # +++ تأمين الوقت (Timezone Shield): تحويل الوقت لـ Aware ISO صريح لمنع تضارب الساعات +++
            formatted_date = t.created_at.replace(tzinfo=timezone.utc).isoformat() if t.created_at else None
            
            batches[batch_id] = {
                "transfer_id": batch_id,
                "created_at": formatted_date,
                "items": []
            }

        variant = t.product_variant
        safe_packs = variant.packs_per_carton if variant and variant.packs_per_carton else 1
        
        # الحساب المتماثل للأرقام المحاسبية: كلاهما يحمل نفس الإشارة منعاً لانفصام البيانات بالواجهة
        sign = -1 if t.quantity_packs < 0 else 1
        abs_packs = abs(t.quantity_packs)
        delta_cartons = (abs_packs // safe_packs) * sign
        delta_packs = (abs_packs % safe_packs) * sign

        batches[batch_id]["items"].append({
            "real_transfer_id": t.id,
            "product_name": variant.variant_name if variant else "غير معروف",
            "delta_cartons": delta_cartons,
            "delta_packs": delta_packs
        })

    return list(batches.values())


# =========================================
# 9. إضافة محل جديد (من الميدان)
# =========================================
@router.post("/shops", status_code=201)
async def add_new_shop(
    payload: AddShopRequest,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # 1. الدرع الأمني (IDOR) - سحب الـ ID مباشرة من التوكن
    driver_id = current_driver.id

    # 2. جلب الجلسة النشطة
    stmt_session = select(WorkSession).filter_by(driver_id=driver_id, end_time=None)
    active_session = (await db.execute(stmt_session)).scalars().first()
    
    if not active_session:
        raise HTTPException(status_code=403, detail="مرفوض: الرجاء بدء يوم العمل أولاً.")

    # 3. جلب خط السير النشط لمنع كارثة "المحل الشبح"
    stmt_route = select(DispatchRoute).filter_by(work_session_id=active_session.id, status='active')
    active_route = (await db.execute(stmt_route)).scalars().first()
    
    if not active_route:
        raise HTTPException(status_code=403, detail="مرفوض: لا يوجد لديك خط سير نشط لربط المحل الجديد به.")
        
    # 4. حماية الاستراحة والصلاحية
    if active_session.break_start_time and not active_session.break_end_time:
        raise HTTPException(status_code=403, detail="أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل.")
        
    if not active_session.is_authorized_to_sell:
        raise HTTPException(status_code=403, detail="مرفوض: غير مصرح لك بإضافة محلات حالياً. بانتظار تفعيل خط السير من الإدارة.")

    # 5. +++ الدرع الجغرافي: سحق ثغرة نصف الإحداثي وعنصرية خط الاستواء +++
    has_coords = payload.latitude is not None and payload.longitude is not None
    # +++ سحق ثغرة المسافات الفارغة (Whitespace Bypass) التي تخدع دالة bool() وتصنع محلات بلا خرائط +++
    has_link = bool(str(payload.location_link or "").strip())

    if not (has_coords or has_link):
        raise HTTPException(status_code=400, detail="فشل الحفظ: يجب توفير الموقع الجغرافي كاملاً (خط الطول والعرض معاً) أو رابط الخريطة.")

    # 6. درع التكرار وإجبارية الهاتف (حسب قرار الإدارة لضبط الذمم)
    clean_phone = str(payload.phone_number or "").strip()
    if not clean_phone:
        raise HTTPException(status_code=400, detail="مرفوض: رقم الهاتف إجباري لضمان التواصل مع المحل وتوثيق الذمم.")
        
    stmt_dup = select(Shop).filter_by(phone_number=clean_phone)
    existing_shop = (await db.execute(stmt_dup)).scalars().first()
    if existing_shop:
        raise HTTPException(status_code=409, detail=f"فشل الحفظ: رقم الهاتف مسجل مسبقاً للمحل ({existing_shop.name}).")

    try:
        # Pydantic قام بالتنظيف المسبق للـ Whitespaces، نعين القيم مباشرة
        new_shop = Shop(
            name=payload.name,
            address=payload.address,
            phone_number=payload.phone_number,
            contact_person=payload.contact_person,
            notes=payload.notes,
            location_link=payload.location_link,
            latitude=payload.latitude,
            longitude=payload.longitude,
            zone_id=active_route.zone_id, 
            added_by_driver_id=driver_id,
            sequence=999,
            # +++ الدرع المالي: تهيئة الأرصدة كـ Decimal نقي لمنع 500 Crash في الزيارات +++
            current_balance=Decimal('0.0'),
            max_debt_limit=Decimal('0.0') 
        )
        db.add(new_shop)
        await db.flush() # دفع البيانات للحصول على ID المحل

        # +++ نسف ثغرة الزيارة اليتيمة وإضافة الترتيب +++
        new_visit = Visit(
            driver_id=driver_id,
            shop_id=new_shop.id,
            work_session_id=active_session.id, # ربط الزيارة بالجلسة الحالية
            status='Pending',
            sequence=new_shop.sequence, # ربط الترتيب لتظهر في المكان الصحيح بالموبايل
            visit_timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        db.add(new_visit)
        
        await db.commit()
        return {"message": "Shop added successfully", "shop": {"id": new_shop.id, "name": new_shop.name}}
        
    except IntegrityError as e:
        # +++ الدرع الفولاذي: التقاط الـ IntegrityError ورمي 409 Conflict محترم للمندوب +++
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=409, detail="فشل الحفظ: تعارض في البيانات. قد يكون رقم الهاتف مسجلاً مسبقاً.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء إضافة المحل.")


# =========================================
# 10. قائمة المنتجات والأسعار (Product Catalog - Legacy URL Match)
# =========================================
@router.get("/product_variants", response_model=List[ProductVariantResponse], status_code=200)
async def get_products(
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver) # حماية الرابط بالتوكن الأصلي دون المساس بالـ URLContract
    ):
        # +++ النسف المعماري النخبة لـ N+1 ومحرقة الـ CPU: استعلام مباشر وإرجاع الكائنات فوراً +++
        # لا توجد حلقات تكرارية (No Python Loops)، الداتا تُسلم مباشرة لمحرك Pydantic ليقوم بالـ Serialization بسرعة الصاروخ
        stmt = select(ProductVariant).filter_by(is_active=True).order_by(ProductVariant.id.asc())
        result = await db.execute(stmt)
        return result.scalars().all()


# =========================================
# 11. استعراض زيارات اليوم والجرد (عمارة الـ Contains Eager الفولاذية)
# =========================================
@router.get("/driver/{driver_id}/visits", response_model=GetVisitsContract, status_code=200)
async def get_driver_visits(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    if current_driver.id != driver_id:
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: غير مصرح لك.")

    # 1. جلب الجلسة وخط السير
    stmt_session = select(WorkSession).filter_by(driver_id=driver_id, is_settled=False).order_by(WorkSession.id.desc())
    active_session = (await db.execute(stmt_session)).scalars().first()

    stmt_route = select(DispatchRoute).filter(
        DispatchRoute.driver_id == driver_id, 
        DispatchRoute.status.in_(['active', 'waiting', 'postponed'])
    )
    active_route = (await db.execute(stmt_route)).scalars().first()

    if not active_route:
        return {"visits": [], "inventory": []}

    # 2. بناء شرط الجلب الميداني العزل التام
    session_id_val = active_session.id if active_session else -1
    # +++ نسف فخ اختفاء الطوارئ (إبداع المالك): طلبات الطوارئ لا تموت بالوقت، بل تبقى حية طالما أنها Pending +++
    condition = or_(
        and_(Visit.status == 'Pending', Shop.zone_id == active_route.zone_id),
        Visit.work_session_id == session_id_val,
        and_(Visit.is_emergency == True, Visit.status == 'Pending')
    )

    # 3. +++ نسف قنبلة التزامن العكسي للموبايل: عزل الأصناف الملغاة لمنع تضخم الفواتير في قاعدة بيانات الموبايل (SQLite) +++
    stmt_visits = select(Visit).join(Shop).options(
        contains_eager(Visit.shop), 
        selectinload(Visit.items.and_(VisitItem.is_cancelled == False)).joinedload(VisitItem.product_variant),
        selectinload(Visit.returns.and_(VisitReturn.is_cancelled == False)).joinedload(VisitReturn.product_variant)
    ).filter(
        Visit.driver_id == driver_id,
        Shop.is_archived == False,
        condition
    ).order_by(Shop.sequence.asc().nulls_last(), Visit.id.asc())

    visits = (await db.execute(stmt_visits)).scalars().all()

    # +++ الكي الجراحي: حقن الـ allowed_zone_id في كائنات SQLAlchemy للوفاء بعقد الـ Flutter +++
    route_zone_id = active_route.zone_id if active_route else None
    for v in visits:
        v.allowed_zone_id = route_zone_id

    # 4. إعادة بناء جرد الأوفلاين للموبايل
    inventory_data = []
    if active_session:
        stmt_inv = select(SessionInventory).options(joinedload(SessionInventory.product_variant)).filter_by(work_session_id=active_session.id)
        inventories = (await db.execute(stmt_inv)).scalars().all()
        for inv in inventories:
            variant = inv.product_variant
            packs = variant.packs_per_carton if variant and variant.packs_per_carton and variant.packs_per_carton > 0 else 1
            # +++ تصحيح جرد الأوفلاين: دمج الحوالات المعلقة لكي لا ينكسر الـ Progress Bar في تطبيق الـ Flutter +++
            total_received = inv.starting_quantity + (inv.net_transfers or 0)
            inventory_data.append({
                "id": variant.id,
                "name": variant.variant_name,
                # +++ الدرع المالي للـ SaaS: إرسال الأسعار كنصوص لمنع تآكل العملات في الـ JSON +++
                "price_per_carton": str(variant.price_per_carton or '0.0'),
                "price_per_pack": str(variant.price_per_pack or '0.0'),
                "packs_per_carton": packs,
                "starting_cartons": total_received // packs,
                "current_cartons": inv.current_remaining_quantity // packs,
                "current_packs": inv.current_remaining_quantity % packs
            })
    else:
        stmt_loads = select(VehicleLoad, ProductVariant).join(
            ProductVariant, VehicleLoad.product_variant_id == ProductVariant.id
        ).filter(VehicleLoad.vehicle_id == active_route.vehicle_id)
        vehicle_loads = (await db.execute(stmt_loads)).all()
        for load, variant in vehicle_loads:
            packs = variant.packs_per_carton if variant and variant.packs_per_carton and variant.packs_per_carton > 0 else 1
            inventory_data.append({
                "id": variant.id,
                "name": variant.variant_name,
                # +++ الدرع المالي للـ SaaS: إرسال الأسعار كنصوص (String) +++
                "price_per_carton": str(variant.price_per_carton or '0.0'),
                "price_per_pack": str(variant.price_per_pack or '0.0'),
                "packs_per_carton": packs,
                "starting_cartons": load.quantity,
                "current_cartons": load.quantity,
                "current_packs": 0
            })

    # 5. +++ جلب الحوالات المعلقة (CS-WH-04) لكي يرى المندوب البضاعة المحجوزة بالميدان +++
    pending_transfers_data = []
    if active_session:
        stmt_pending_transfers = select(InventoryTransfer).filter_by(
            work_session_id=active_session.id, status='pending'
        )
        pending_transfers_db = (await db.execute(stmt_pending_transfers)).scalars().all()
        for t in pending_transfers_db:
            pending_transfers_data.append({
                "transfer_id": t.id,
                "product_variant_id": t.product_variant_id,
                "quantity_packs": t.quantity_packs,
                "status": t.status,
                "created_at": t.created_at.replace(tzinfo=timezone.utc).isoformat() if t.created_at else None
            })

    # 6. تسليم الخريطة النظيفة للعقد المقدس مع الموبايل
    return {
        "visits": visits,
        "inventory": inventory_data,
        "pending_transfers": pending_transfers_data
    }


# =========================================
# 12. جلب تفاصيل الزيارة المكتملة (مطابقة العقد الأصيل)
# =========================================
@router.get("/visits/{visit_id}", response_model=VisitDetailsResponse, status_code=200)
async def get_visit_details(
    visit_id: int,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # +++ التطهير الأدائي المطلق: سحق الأصناف الملغاة داخل الـ SQL +++
    stmt = select(Visit).options(
        joinedload(Visit.shop),
        selectinload(Visit.items.and_(VisitItem.is_cancelled == False)).joinedload(VisitItem.product_variant),
        selectinload(Visit.returns.and_(VisitReturn.is_cancelled == False)) # شحن المرتجعات السليمة فقط
    ).filter_by(id=visit_id)
    
    visit = (await db.execute(stmt)).scalar_one_or_none()
    
    if not visit:
        raise HTTPException(status_code=404, detail="عذراً، الزيارة المطلوبة غير موجودة.")
    
    # +++ الدرع الأمني المصفح: المندوب يرى فواتيره فقط، والأدمن يرى كل شيء للرقابة المحاسبية والجرد +++
    if not current_driver.is_admin and visit.driver_id != current_driver.id:
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: غير مصرح لك بالاطلاع على فواتير المناديب الآخرين.")
        
    return visit


# =========================================
# 13. التحقق من وجود جلسة نشطة للمندوب (عند فتح التطبيق)
# =========================================
@router.get("/driver/{driver_id}/sessions/active", response_model=ActiveSessionResponse, status_code=200)
async def get_active_session(
    driver_id: int,
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver)
):
    # +++ الدرع الفولاذي: منع المندوب من التجسس على جلسات المناديب الآخرين +++
    if current_driver.id != driver_id:
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: وصول غير مصرح به.")
        
    # 2. البحث عن الجلسة النشطة (مع حماية הـ limit)
    # +++ الدرع الفولاذي ضد كراش الـ MultipleResultsFound (بدون أقفال لأنه GET Request للقراءة فقط) +++
    stmt_session = select(WorkSession).filter_by(driver_id=driver_id, end_time=None).order_by(WorkSession.id.desc()).limit(1)
    active_session = (await db.execute(stmt_session)).scalars().first()
    
    if active_session:
        return {
            "active_session_found": True, 
            "session_id": active_session.id, 
            # تحويل الوقت لـ ISO مع تأمين المنطقة الزمنية
            "start_time": active_session.start_time.replace(tzinfo=timezone.utc).isoformat() if active_session.start_time else None
        }
        
    return {"active_session_found": False}