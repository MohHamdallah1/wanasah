import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ws_manager import dispatch_manager
from sqlalchemy.future import select
from sqlalchemy import delete, func, or_, and_, case, nullslast, update, cast, Float
from database import get_db
from api.dependencies import get_current_driver, get_current_admin
from datetime import timedelta, datetime, timezone
from sqlalchemy.orm import joinedload
from decimal import Decimal
from typing import List 
from fastapi.responses import JSONResponse
import re
from collections import Counter
import logging
logger = logging.getLogger("wanasah_logger")

from models import ( Driver, WorkSession, SystemAuditLog, DamagedItemLog, MainWarehouse, InventoryLedger,
VehicleLoad, VisitReturn, ProductVariant, DispatchRoute, WarehouseLedger,Zone, Vehicle, Shop,Visit,
 SessionInventory, ShortageRequest, SystemSetting, InventoryTransfer, Country, Governorate, ImportLog, VisitItem)

from schemas import ( MessageResponse, AuthorizeSessionRequest, AdminDashboardDriverResponse,
SessionSettlementReportResponse, SettleSessionRequest, SettleSessionResponse, DispatchInitResponse,
DispatchRouteRequest, VehicleInventoryItemResponse, RouteLiveInventoryItemResponse, AdjustRouteInventoryRequest,
RouteTransferResponse, DispatchShopResponse, BulkUpdateShopItem, AdminAddShopRequest, ActiveRouteResponse,
UpdateRouteStatusRequest, AddZoneRequest, ArchivedZoneResponse, EditShopDetailsRequest, ShortageResponseItem,
CreateShortageItem, BulkImportRequest, UpdateZoneRequest)



# إنشاء روتر خاص بمسارات الإدارة (بتاج منفصل لتنظيم Swagger)
router = APIRouter(tags=["Admin & Dispatch Operations"])

# =========================================
# 1. إعطاء أو سحب "الضوء الأخضر" (تفعيل صلاحية البيع)
# =========================================
@router.put("/admin/sessions/{session_id}/authorize", response_model=MessageResponse, status_code=200)
async def authorize_session(
    session_id: int,
    # +++ الدرع الفولاذي: تهيئة كائن Pydantic كقيمة افتراضية صريحة للوفاء بعقود الـ React القديمة ومنع الـ 422 والـ 500 +++
    payload: AuthorizeSessionRequest = AuthorizeSessionRequest(),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):

    # 1. جلب الجلسة مع قفل التزامن (Row-Level Lock)
    stmt = select(WorkSession).filter_by(id=session_id).with_for_update()
    session = (await db.execute(stmt)).scalar_one_or_none()

    if not session:
        await db.rollback() # +++ سحق ثغرة تسريب الاتصالات (Connection Leak) +++
        raise HTTPException(status_code=404, detail="الجلسة المطلوبة غير موجودة.")

    # 2. درع الزومبي (حظر المساس بالجلسات الميتة أو المسواة)
    if session.end_time or session.is_settled:
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض: لا يمكن تعديل صلاحيات جلسة مغلقة أو تمت تسويتها ماليًا.")

    # 3. +++ الدرع الرقابي (Conflict of Interest): منع المشرف من إعطاء الصلاحية لنفسه +++
    if session.driver_id == current_admin.id:
        await db.rollback()
        raise HTTPException(status_code=403, detail="مرفوض رقابياً: لا يمكنك منح صلاحية البيع لجلسة تخصك (تضارب مصالح).")

    try:
        if session.is_authorized_to_sell != payload.is_authorized:
            old_val = session.is_authorized_to_sell
            session.is_authorized_to_sell = payload.is_authorized
            
            # 4. الدرع السيادي (Audit Trail): توثيق الحركة إجبارياً
            audit_log = SystemAuditLog(
                admin_id=current_admin.id,
                target_id=f"Session_{session.id}_Driver_{session.driver_id}",
                action_type="AUTHORIZATION_TOGGLE",
                old_value=f"is_authorized: {old_val}",
                new_value=f"is_authorized: {payload.is_authorized}"
            )
            db.add(audit_log)
            
        await db.commit()
        return {"message": "تم تحديث صلاحية البيع وتوثيق العملية بنجاح."}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء التحديث.")

# =========================================
# 2. جلب ملخص كل الجلسات النشطة اليوم (شاشة غرفة العمليات - O(1) Architecture)
# =========================================
@router.get("/admin/sessions/today", response_model=List[AdminDashboardDriverResponse], status_code=200)
async def get_admin_dashboard_data(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):

    today_date = datetime.now(timezone.utc).date()
    # +++ النسف المعماري للانفصام الزمني (Timezone Drift): تجهيز الحدود الزمنية النقية لمنع الـ Full Table Scan +++
    today_start = datetime.combine(today_date, datetime.min.time())
    today_end = today_start + timedelta(days=1)
    limit_date_start = today_start - timedelta(days=14)
    
    # 1. جلب الجلسات الحية (Sargable Query لرفع سرعة الداتابيز x100)
    stmt_sessions = select(WorkSession).options(joinedload(WorkSession.driver)).filter(
        or_(
            and_(WorkSession.start_time >= today_start, WorkSession.start_time < today_end),
            and_(WorkSession.is_settled == False, WorkSession.start_time >= limit_date_start)
        )
    )
    sessions = (await db.execute(stmt_sessions)).scalars().all()
    
    if not sessions:
        return []

    session_ids = [s.id for s in sessions]
    driver_ids = [s.driver_id for s in sessions]
    
    # 2. +++ النسف المحاسبي (SQL Conditional Aggregation): فصل الزيارات عن المبيعات الناجحة +++
    stmt_stats = select(
        Visit.work_session_id,
        func.count(Visit.id).label('total_visits'),
        func.sum(case((Visit.outcome == 'Sale', 1), else_=0)).label('successful_sales'), # +++ صائد المبيعات الحقيقية +++
        func.sum(Visit.cash_collected).label('total_cash'),
        func.sum(Visit.debt_paid).label('total_debt')
    ).filter(
        Visit.work_session_id.in_(session_ids), 
        Visit.status == 'Completed'
    ).group_by(Visit.work_session_id)
    
    stats_map = {r.work_session_id: r for r in (await db.execute(stmt_stats)).all()}
        
    # 3. جلب أعداد الزيارات المعلقة
    stmt_pending = select(
        Visit.driver_id, 
        func.count(Visit.id)
    ).filter(
        Visit.driver_id.in_(driver_ids), 
        Visit.status == 'Pending',
        or_(Visit.work_session_id.in_(session_ids), func.date(Visit.visit_timestamp) == today_date)
    ).group_by(Visit.driver_id)
    
    pending_map = {r.driver_id: r[1] for r in (await db.execute(stmt_pending)).all()}
        
    # 4. جلب العهدة
    stmt_inv = select(SessionInventory).options(joinedload(SessionInventory.product_variant)).filter(
        SessionInventory.work_session_id.in_(session_ids)
    )
    inv_map = {}
    for inv in (await db.execute(stmt_inv)).scalars().all():
        inv_map.setdefault(inv.work_session_id, []).append(inv)

    # 5. التجميع الصاروخي بالذاكرة
    drivers_data = []
    for session in sessions:
        driver = session.driver
        if not driver or not driver.is_active or driver.is_admin:
            continue
            
        is_on_break = bool(session.break_start_time and not session.break_end_time)
        stats = stats_map.get(session.id)

        completed_total = stats.total_visits if stats else 0
        # +++ حقن المبيعات الناجحة الحقيقية +++
        successful_sales_count = stats.successful_sales if stats else 0 
        
        cash_from_sales = Decimal(str(stats.total_cash or '0.0')) if (stats and stats.total_cash) else Decimal('0.0')
        cash_from_debts = Decimal(str(stats.total_debt or '0.0')) if (stats and stats.total_debt) else Decimal('0.0')
        expected_cash_in_hand = cash_from_sales + cash_from_debts
        
        pending_remaining = pending_map.get(session.driver_id, 0)
        
        inventories = inv_map.get(session.id, [])
        inv_list = []
        for inv in inventories:
            variant = inv.product_variant
            packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton > 0 else 1
            total_received = inv.starting_quantity + getattr(inv, 'net_transfers', 0)
            sold_qty = total_received - inv.current_remaining_quantity
            rem_qty = inv.current_remaining_quantity
            
            # +++ تفكيك العهدة (كراتين وحبات) لراحة المشرف +++
            inv_list.append({
                "product_id": inv.product_variant_id,
                "product_name": variant.variant_name if variant else "غير معروف",
                "starting_quantity": total_received, 
                "sold_quantity": sold_qty, 
                "remaining_quantity": rem_qty, 
                "packs_per_carton": packs_per_carton,
                "starting_cartons": total_received // packs_per_carton,
                "starting_loose_packs": total_received % packs_per_carton,
                "sold_cartons": sold_qty // packs_per_carton,
                "sold_loose_packs": sold_qty % packs_per_carton,
                "remaining_cartons": rem_qty // packs_per_carton,
                "remaining_loose_packs": rem_qty % packs_per_carton
            })
        
        if session.is_settled:
            status_str = "تمت التسوية"
        elif session.end_time:
            status_str = "مغلقة بانتظار التسوية"
        elif is_on_break:
            status_str = "استراحة"
        else:
            status_str = "في الطريق"

        # تم حذف كود (استبعاد الجلسات الميتة) من هنا لأن استعلام الـ SQL في الأعلى لم يجلبها من الأساس بفضل الـ or_!
        
        drivers_data.append({
            "session": {
                "session_id": session.id,
                "driver_name": driver.full_name,
                "start_time": session.start_time.replace(tzinfo=timezone.utc).isoformat() if session.start_time else None,
                "is_authorized_to_sell": session.is_authorized_to_sell,
                "is_on_break": is_on_break
            },
            "settlement": {
                "driver_name": driver.full_name,
                "status": status_str,
                "financials": {
                    "expected_cash_in_hand": str(expected_cash_in_hand),
                    "cash_from_sales": str(cash_from_sales),
                    "cash_from_debts": str(cash_from_debts)
                },
                "visits": {
                    "completed_total": completed_total,
                    "successful_sales": successful_sales_count, # +++ تم ربطها بالرقم الحقيقي المفلتر في الداتابيز +++
                    "pending_remaining": pending_remaining
                },
                "inventory": inv_list
            }
        })
        
    def get_status_rank(d):
        s = d['settlement']['status']
        if s == "في الطريق": return 1
        if s == "استراحة": return 2
        if s == "مغلقة بانتظار التسوية": return 3
        return 4
        
    drivers_data.sort(key=get_status_rank)
    
    return drivers_data


# =========================================
# 3. تقرير التسوية اليومية وجرد السيارة للمحاسب (محكمة المندوب - O(1) & Deadlock Free)
# =========================================
@router.get("/admin/sessions/{session_id}/settlement_report", response_model=SessionSettlementReportResponse, status_code=200)
async def get_session_settlement_report(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # 1. جلب الجلسة والمندوب (GET آمن وبدون أقفال مدمرة للـ Concurrency)
    stmt_session = select(WorkSession).options(joinedload(WorkSession.driver)).filter_by(id=session_id)
    session = (await db.execute(stmt_session)).scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="الجلسة غير موجودة")

    # 2. تجميع الماليات والمبيعات المكتملة بضربة SQL واحدة
    stmt_stats = select(
        func.count(Visit.id).label('total_visits'),
        func.sum(case((Visit.outcome == 'Sale', 1), else_=0)).label('sales_count'), # صائد المبيعات الناجحة
        func.sum(Visit.cash_collected).label('total_cash'),
        func.sum(Visit.debt_paid).label('total_debt')
    ).filter(
        Visit.work_session_id == session_id, 
        Visit.status == 'Completed'
    )
    stats = (await db.execute(stmt_stats)).first()

    # 3. +++ النسف المعماري لفضيحة الشبح: ربط الـ Pending גلسة اليوم حصراً وليس بتاريخ المندوب +++
    stmt_pending = select(func.count(Visit.id)).filter(
        Visit.work_session_id == session_id, 
        Visit.status == 'Pending'
    )
    pending_count = (await db.execute(stmt_pending)).scalar() or 0

    # 4. جلب الجرد التفصيلي للعهدة
    stmt_inv = select(SessionInventory).options(
        joinedload(SessionInventory.product_variant)
    ).filter_by(work_session_id=session.id)
    inventories = (await db.execute(stmt_inv)).scalars().all()
    
    # 5. بناء التقرير المالي
    completed_total = stats.total_visits if stats else 0
    successful_sales = int(stats.sales_count or 0) if stats else 0
    cash_from_sales = Decimal(str(stats.total_cash or '0.0')) if stats else Decimal('0.0')
    cash_from_debts = Decimal(str(stats.total_debt or '0.0')) if stats else Decimal('0.0')
    expected_cash_in_hand = cash_from_sales + cash_from_debts

    # 6. تفكيك العهدة (كراتين وحبات) لراحة نظر المحاسب
    inv_list = []
    for inv in inventories:
        variant = inv.product_variant
        packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton > 0 else 1
        
        total_received = inv.starting_quantity + getattr(inv, 'net_transfers', 0)
        remaining = inv.current_remaining_quantity
        sold_qty = total_received - remaining
        
        inv_list.append({
            "product_id": inv.product_variant_id,
            "product_name": variant.variant_name if variant else "غير معروف",
            "starting_quantity": total_received,
            "sold_quantity": sold_qty,
            "remaining_quantity": remaining,
            "packs_per_carton": packs_per_carton,
            "starting_cartons": total_received // packs_per_carton,
            "starting_loose_packs": total_received % packs_per_carton,
            "sold_cartons": sold_qty // packs_per_carton,
            "sold_loose_packs": sold_qty % packs_per_carton,
            "remaining_cartons": remaining // packs_per_carton,
            "remaining_loose_packs": remaining % packs_per_carton
        })
    # +++ الدرع المحاسبي: جلب جدول العينات التفصيلي (O(1)) لكشف التلاعب +++
    stmt_samples = select(VisitItem, Shop.name.label('shop_name'), ProductVariant.variant_name).join(
        Visit, Visit.id == VisitItem.visit_id
    ).join(
        Shop, Shop.id == Visit.shop_id
    ).join(
        ProductVariant, ProductVariant.id == VisitItem.product_variant_id
    ).filter(
        Visit.work_session_id == session_id,
        or_(VisitItem.sample_quantity > 0, VisitItem.sample_packs_quantity > 0)
    )
    samples_raw = (await db.execute(stmt_samples)).all()
    
    samples_list = []
    for item, s_name, p_name in samples_raw:
        samples_list.append({
            "shop_name": s_name,
            "product_name": p_name,
            "sample_quantity_cartons": item.sample_quantity,
            "sample_quantity_packs": getattr(item, 'sample_packs_quantity', 0),
            "reason": item.sample_reason or "بدون سبب"
        })

    # 7. تحديد حالة الجلسة بوضوح للمحاسب
    status_str = "نشطة الآن في الميدان"
    if session.is_settled:
        status_str = "تمت التسوية (مغلقة نهائياً)"
    elif session.end_time:
        status_str = "مغلقة بانتظار المحاسبة"

    # +++ النسف المعماري لألغام التواريخ والـ AttributeError +++
    if getattr(session, 'session_date', None):
        final_date = session.session_date.isoformat()
    elif session.start_time:
        final_date = session.start_time.date().isoformat()
    else:
        final_date = datetime.now(timezone.utc).date().isoformat()

    return {
        "driver_name": session.driver.full_name if session.driver else "غير معروف",
        "session_date": final_date,
        "status": status_str,
        "financials": {
            "expected_cash_in_hand": str(expected_cash_in_hand),
            "cash_from_sales": str(cash_from_sales),
            "cash_from_debts": str(cash_from_debts)
        },
        "visits": {
            "completed_total": completed_total,
            "successful_sales": successful_sales,
            "pending_remaining": pending_count
        },
        "inventory": inv_list,
        "samples_given": samples_list # +++ الجدول أصبح متاحاً للـ React Dashboard +++
    }


# =========================================
# 4. اعتماد التسوية اليومية واستلام الجرد الفعلي (محكمة المندوب الفولاذية)
# =========================================
@router.put("/admin/sessions/{session_id}/settle", response_model=SettleSessionResponse, status_code=200)
async def settle_session(
    session_id: int,
    payload: SettleSessionRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):

    stmt_session = select(WorkSession).with_for_update().filter_by(id=session_id)
    session = (await db.execute(stmt_session)).scalar_one_or_none()

    if not session:
        await db.rollback()
        raise HTTPException(status_code=404, detail="الجلسة غير موجودة")

    if session.is_settled:
        await db.rollback()
        raise HTTPException(status_code=400, detail="تم اعتماد تسوية هذه الجلسة مسبقاً.")

    if not session.end_time:
        await db.rollback()
        raise HTTPException(status_code=400, detail="لا يمكن تسوية الجلسة لأن المندوب لم يُنهِ العمل.")

    try:
        # 1. الحسابات المالية
        stmt_stats = select(
            func.sum(Visit.cash_collected).label('total_cash'),
            func.sum(Visit.debt_paid).label('total_debt')
        ).filter(Visit.work_session_id == session.id, Visit.status == 'Completed')
        stats = (await db.execute(stmt_stats)).first()

        expected_cash_dec = Decimal(str(stats.total_cash or '0')) + Decimal(str(stats.total_debt or '0'))
        actual_cash_dec = payload.actual_cash
        cash_difference_dec = actual_cash_dec - expected_cash_dec

        # تم نقل فحص البضاعة للأسفل بعد تعريف المتغيرات لمنع الـ NameError

        if cash_difference_dec != Decimal('0.0'):
            db.add(SystemAuditLog(
                admin_id=current_admin.id,
                target_id=f"Session_{session.id}",
                action_type="SETTLEMENT_CASH_DISCREPANCY",
                old_value=f"Expected: {expected_cash_dec}",
                new_value=f"Actual: {actual_cash_dec} | مبرر المشرف: {payload.notes}"
            ))

        # 2. تحضير البيانات
        jard_map = {}
        for item in payload.inventory_jard:
            pid = item.product_id
            jard_map[pid] = jard_map.get(pid, 0) + item.actual

        stmt_route = select(DispatchRoute).with_for_update().filter_by(work_session_id=session.id)
        route = (await db.execute(stmt_route)).scalar_one_or_none()

        stmt_damaged = select(VisitReturn).join(Visit).filter(
            Visit.work_session_id == session.id,
            VisitReturn.return_type.in_(['Expired', 'Damaged', 'Factory_Defect']),
            VisitReturn.is_cancelled == False
        )
        damaged_returns = (await db.execute(stmt_damaged)).scalars().all()

        # جلب مبدئي لأصناف العهدة لتحديد قائمة المنتجات بدون قفل متسرع يسبب Deadlock
        stmt_inv_keys = select(SessionInventory.product_variant_id).filter_by(work_session_id=session.id)
        inv_pids = (await db.execute(stmt_inv_keys)).scalars().all()

        all_involved_pids = list(set(
            list(inv_pids) + 
            list(jard_map.keys()) + 
            [r.product_variant_id for r in damaged_returns]
        ))
        all_involved_pids.sort()

        bulk_variants = {}
        bulk_wh_records = {}
        bulk_inv_records = {}
        damaged_by_product = {}

        if all_involved_pids:
            stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(all_involved_pids))
            bulk_variants = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}

            # 1. الترتيب الإجباري للـ Deadlock: قفل وتفريغ السيارة أولاً
            if route and route.vehicle_id:
                await db.execute(delete(VehicleLoad).where(VehicleLoad.vehicle_id == route.vehicle_id))

            # 2. قفل المستودع ثانياً
            stmt_wh = select(MainWarehouse).with_for_update().filter(
                MainWarehouse.product_variant_id.in_(all_involved_pids)
            ).order_by(MainWarehouse.product_variant_id.asc())
            bulk_wh_records = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}
            
            # 3. قفل عهدة الجلسة ثالثاً (الآن نحن آمنون تماماً)
            stmt_inv = select(SessionInventory).with_for_update().filter(
                SessionInventory.work_session_id == session.id,
                SessionInventory.product_variant_id.in_(all_involved_pids)
            )
            all_session_inv = (await db.execute(stmt_inv)).scalars().all()
            bulk_inv_records = {inv.product_variant_id: inv for inv in all_session_inv}

        for ret in damaged_returns:
                var = bulk_variants.get(ret.product_variant_id)
                if not var: continue
                ppc = var.packs_per_carton or 1
                ret_packs = (ret.quantity * ppc) + getattr(ret, 'packs_quantity', 0)
                if ret_packs > 0:
                    damaged_by_product[ret.product_variant_id] = damaged_by_product.get(ret.product_variant_id, 0) + ret_packs
                    db.add(DamagedItemLog(
                        product_variant_id=ret.product_variant_id,
                        quantity_packs=ret_packs,
                        damage_type=ret.return_type,
                        source_driver_id=session.driver_id,
                        source_visit_id=ret.visit_id,
                        receiving_admin_id=current_admin.id,
                        notes=ret.reason or "فرز تلقائي نهاية اليوم"
                    ))

        # +++ الدرع الرقابي الفولاذي (التصحيح المعماري للـ NameError): يجب فحص الجرد هنا بعد جلب وتحضير كافة البيانات +++
        has_inventory_difference = any(
            jard_map.get(pid, (bulk_inv_records.get(pid).current_remaining_quantity if bulk_inv_records.get(pid) else 0) + damaged_by_product.get(pid, 0)) != 
            ((bulk_inv_records.get(pid).current_remaining_quantity if bulk_inv_records.get(pid) else 0) + damaged_by_product.get(pid, 0))
            for pid in all_involved_pids
        )
        
        if (cash_difference_dec != Decimal('0.0') or has_inventory_difference) and not payload.notes:
            await db.rollback()
            raise HTTPException(
                status_code=400, 
                detail=f"يوجد فرق في الجرد المالي ({cash_difference_dec}) أو جرد البضاعة. يرجى كتابة تبرير صريح (ملاحظات) لاعتماد التسوية المحاسبية."
            )

        # 3. الحلقة الرئيسية (المعدلة معمارياً لنسف الفائض الوهمي وتلويث العهدة)
        for prod_id in all_involved_pids:
            inv_record = bulk_inv_records.get(prod_id)
            # المتوقع السليم فقط
            expected_sellable_qty = inv_record.current_remaining_quantity if inv_record else 0
            damaged_packs = damaged_by_product.get(prod_id, 0)
            
            # +++ الدرع المحاسبي 1: المتوقع الملموس = السليم + التوالف الموثقة +++
            expected_total_physical = expected_sellable_qty + damaged_packs
            
            # المشرف يدخل الملموس الفعلي، نقارنه بالملموس المتوقع
            actual_qty = jard_map.get(prod_id, expected_total_physical)
            difference = actual_qty - expected_total_physical

            if difference != 0:
                t_type = 'Surplus' if difference > 0 else 'Deficit'
                db.add(InventoryLedger(
                    work_session_id=session.id,
                    driver_id=session.driver_id,
                    vehicle_id=route.vehicle_id if route else None,
                    product_variant_id=prod_id,
                    transaction_type=t_type,
                    expected_quantity=expected_total_physical,
                    actual_quantity=actual_qty,
                    difference=difference,
                    admin_id=current_admin.id,
                    notes=f"تسوية الجرد. المتوقع الملموس: {expected_total_physical} (منها {damaged_packs} توالف)، الفعلي الملموس: {actual_qty}"
                ))

                variant_name = bulk_variants.get(prod_id).variant_name if bulk_variants.get(prod_id) else f"ID:{prod_id}"
                db.add(SystemAuditLog(
                    admin_id=current_admin.id,
                    target_id=f"Session_{session.id}_Prod_{prod_id}",
                    action_type="INVENTORY_DISCREPANCY",
                    old_value=f"Expected Physical: {expected_total_physical}",
                    new_value=f"Actual: {actual_qty} | {'زيادة' if difference > 0 else 'عجز'} ({abs(difference)} حبة) للصنف: {variant_name}"
                ))

            # ==========================================================
            # معالجة السيارة، المستودع، وقيود الإغلاق (Armored Version)
            # ==========================================================
            # الكمية الصالحة المتبقية بعد عزل التوالف من الجرد الملموس
            sellable_qty = actual_qty - damaged_packs

            # +++ الدرع المحاسبي 2: تجميد اللقطة التاريخية (Snapshot) لإنقاذ تقارير المحاسبة +++
            if inv_record:
                inv_record.current_remaining_quantity = actual_qty
            else:
                db.add(SessionInventory(
                    work_session_id=session.id,
                    product_variant_id=prod_id,
                    starting_quantity=0,
                    current_remaining_quantity=actual_qty
                ))

            if sellable_qty < 0:
                variant_name = bulk_variants.get(prod_id).variant_name if bulk_variants.get(prod_id) else f"ID:{prod_id}"
                db.add(InventoryLedger(
                    work_session_id=session.id, driver_id=session.driver_id, vehicle_id=route.vehicle_id if route else None,
                    product_variant_id=prod_id, transaction_type='AUDIT_DISCREPANCY', expected_quantity=actual_qty,
                    actual_quantity=damaged_packs, difference=abs(sellable_qty), admin_id=current_admin.id,
                    notes=f"تحذير: كمية التوالف أكبر من العهدة الفعلية للصنف: {variant_name}"
                ))
                sellable_qty = 0

            # +++ التعديل الجراحي 1: قيد الإغلاق يكتب دائماً لتوثيق تصفير عهدة اليوم +++
            db.add(InventoryLedger(
                work_session_id=session.id, driver_id=session.driver_id, vehicle_id=route.vehicle_id if route else None,
                product_variant_id=prod_id, transaction_type='END_DAY_CLEARANCE', expected_quantity=sellable_qty,
                actual_quantity=0, difference=-sellable_qty, admin_id=current_admin.id,
                notes=f"إغلاق عهدة الجلسة. الرصيد الصافي المتبقي قبل الفرز: {sellable_qty} حبة."
            ))

            if sellable_qty > 0:
                variant = bulk_variants.get(prod_id)
                ppc = variant.packs_per_carton if variant and variant.packs_per_carton else 1
                actual_cartons = sellable_qty // ppc
                loose_packs = sellable_qty % ppc

                if route and route.vehicle_id:
                    # 1. إرجاع الفراطة للمستودع
                    if loose_packs > 0:
                        db.add(InventoryLedger(
                            work_session_id=session.id, driver_id=session.driver_id, vehicle_id=route.vehicle_id,
                            product_variant_id=prod_id, transaction_type='Warehouse Return', expected_quantity=loose_packs,
                            actual_quantity=0, difference=-loose_packs, admin_id=current_admin.id,
                            notes="تصفير الفراطة الصالحة وإعادتها للمستودع"
                        ))

                        wh_record = bulk_wh_records.get(prod_id)
                        if not wh_record: # +++ حماية الأصناف الشبحية +++
                            wh_record = MainWarehouse(product_variant_id=prod_id, available_quantity_packs=0, reserved_quantity_packs=0)
                            db.add(wh_record)
                            bulk_wh_records[prod_id] = wh_record

                        wh_record.available_quantity_packs += loose_packs

                        db.add(WarehouseLedger(
                            product_variant_id=prod_id, transaction_type='DISPATCH_UNLOAD', quantity_packs=loose_packs,
                            balance_after_packs=wh_record.available_quantity_packs, admin_id=current_admin.id,
                            reference_id=f"SESS_{session.id}_END", notes="إرجاع فراطة صالحة من تسوية المندوب"
                        ))

                    # 2. إبقاء الكراتين في السيارة وتوثيقها
                    if actual_cartons > 0:
                        db.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=prod_id, quantity=actual_cartons))
                        
                        # +++ التعديل الجراحي 2: توثيق حركة التدوير للكراتين +++
                        db.add(InventoryLedger(
                            work_session_id=session.id, driver_id=session.driver_id, vehicle_id=route.vehicle_id,
                            product_variant_id=prod_id, transaction_type='VEHICLE_ROLLOVER', expected_quantity=actual_cartons * ppc,
                            actual_quantity=actual_cartons * ppc, difference=0, admin_id=current_admin.id,
                            notes=f"تدوير لليوم التالي: إبقاء {actual_cartons} كرتونة سليمة في السيارة."
                        ))
                else:
                    # +++ التعديل الجراحي 3: الثقب الأسود (Null Safety) - إرجاع إجباري للمستودع في حال غياب السيارة +++
                    wh_record = bulk_wh_records.get(prod_id)
                    if not wh_record:
                        wh_record = MainWarehouse(product_variant_id=prod_id, available_quantity_packs=0, reserved_quantity_packs=0)
                        db.add(wh_record)
                        bulk_wh_records[prod_id] = wh_record
                    
                    wh_record.available_quantity_packs += sellable_qty
                    
                    db.add(WarehouseLedger(
                        product_variant_id=prod_id, transaction_type='DISPATCH_UNLOAD_FALLBACK', quantity_packs=sellable_qty,
                        balance_after_packs=wh_record.available_quantity_packs, admin_id=current_admin.id,
                        reference_id=f"SESS_{session.id}_END", notes="إرجاع كامل العهدة للمستودع (إجراء طوارئ لعدم ارتباط جلسة بسيارة)."
                    ))
                    
                    db.add(InventoryLedger(
                        work_session_id=session.id, driver_id=session.driver_id, vehicle_id=None,
                        product_variant_id=prod_id, transaction_type='Warehouse Return', expected_quantity=sellable_qty,
                        actual_quantity=0, difference=-sellable_qty, admin_id=current_admin.id,
                        notes="تفريغ إجباري لكامل الرصيد الصالح للمستودع المركزي."
                    ))

        # 4. إغلاق الجلسة
        session.is_settled = True
        if route:
            route.work_session_id = None

        await db.commit()
        return {
            "message": "تم اعتماد التسوية بنجاح",
            "cash_difference": str(cash_difference_dec),
            "is_settled": True
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء اعتماد التسوية.")


# =========================================
# 5. تهيئة شاشة التوزيع (Dispatch Init)
# =========================================
@router.get("/dispatch/init", response_model=DispatchInitResponse, status_code=200)
async def dispatch_init(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):

    # 1. جلب الكيانات الأساسية بضربات متوازية
    stmt_zones = select(Zone).filter_by(is_active=True)
    zones = (await db.execute(stmt_zones)).scalars().all()

    stmt_drivers = select(Driver).filter_by(is_active=True, is_admin=False)
    drivers = (await db.execute(stmt_drivers)).scalars().all()

    stmt_vehicles = select(Vehicle).filter_by(is_active=True)
    vehicles = (await db.execute(stmt_vehicles)).scalars().all()

    stmt_products = select(ProductVariant).filter_by(is_active=True)
    products = (await db.execute(stmt_products)).scalars().all()

    # 2. +++ الحل السحري لمشكلة N+1 (O(1)): استعلام واحد يجلب عدد المحلات لكل المناطق +++
    stmt_shop_counts = select(Shop.zone_id, func.count(Shop.id)).filter(
        Shop.is_archived == False, 
        Shop.is_active == True
    ).group_by(Shop.zone_id)
    
    shop_counts = (await db.execute(stmt_shop_counts)).all()
    # تحويل النتيجة لقاموس (Dictionary) لسرعة البحث
    shop_count_map = {row.zone_id: row[1] for row in shop_counts if row.zone_id}

    today = datetime.now(timezone.utc).date()
    zones_data = []
    
    for z in zones:
        # استخدام الذاكرة المسبقة (O(1)) بدلاً من استعلام مهدر داخل الحلقة
        shops_count = shop_count_map.get(z.id, 0)
        
        # تحديد حالة الجدولة للترتيب واللون الأحمر (مطابق لمنطقك)
        schedule_status = "null"
        if z.start_date:
            if z.start_date < today: 
                schedule_status = "overdue"
            elif z.start_date == today: 
                schedule_status = "today"
            else: 
                schedule_status = "upcoming"

        zones_data.append({
            "id": str(z.id), 
            "name": z.name,
            "visitDay": z.visit_day or "غير محدد",
            "startDate": z.start_date.isoformat() if z.start_date else "",
            "frequency": z.schedule_frequency or "أسبوعي",
            "scheduleStatus": schedule_status,
            "shopsCount": shops_count
        })

    # تسليم العقد للواجهة كما في الفلاسك تماماً
    return {
        "zones": zones_data,
        "drivers": [{"id": str(d.id), "name": d.full_name} for d in drivers],
        "vehicles": [{"id": str(v.id), "label": f"{v.vehicle_type} - {v.plate_number}"} for v in vehicles],
        "products": [{"id": str(p.id), "name": p.variant_name} for p in products]
    }


# =========================================
# 6. إطلاق خط سير جديد وحفظ الحمولة (The Dispatch Engine - Optimized & Zero Trust)
# =========================================
@router.post("/dispatch/route", status_code=201)
async def dispatch_route(
    payload: DispatchRouteRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):

    stmt_wh_lock = select(SystemSetting).filter_by(setting_key='warehouse_status')
    lock_setting = (await db.execute(stmt_wh_lock)).scalar_one_or_none()
    if lock_setting and lock_setting.setting_value == 'AUDIT_LOCK':
        raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً لغايات الجرد (Stocktake). يرجى فتح المستودع أولاً.")

    stmt_driver_lock = select(Driver).with_for_update().filter_by(id=payload.driver_id)
    driver_lock = (await db.execute(stmt_driver_lock)).scalar_one_or_none()
    if not driver_lock:
        raise HTTPException(status_code=404, detail="المندوب غير موجود.")

    stmt_zone_check = select(DispatchRoute).filter(DispatchRoute.status.in_(['active', 'waiting', 'postponed']), DispatchRoute.zone_id == payload.zone_id)
    if (await db.execute(stmt_zone_check)).first():
        await db.rollback()
        raise HTTPException(status_code=409, detail="⚠️ المنطقة المحددة قيد العمل أو مؤجلة مسبقاً. الرجاء إغلاقها أو تحويلها أولاً.")
    
    stmt_driver_check = select(DispatchRoute).filter(DispatchRoute.status.in_(['active', 'waiting']), DispatchRoute.driver_id == payload.driver_id)
    if (await db.execute(stmt_driver_check)).first():
        await db.rollback()
        raise HTTPException(status_code=409, detail="⚠️ المندوب المختار لديه خط سير نشط أو قيد الانتظار حالياً.")
        
    stmt_veh_check = select(DispatchRoute).filter(DispatchRoute.status.in_(['active', 'waiting']), DispatchRoute.vehicle_id == payload.vehicle_id)
    if (await db.execute(stmt_veh_check)).first():
        await db.rollback()
        raise HTTPException(status_code=409, detail="⚠️ السيارة المحددة مستخدمة في خط سير نشط أو قيد الانتظار حالياً.")

    try:
        new_route = DispatchRoute(zone_id=payload.zone_id, driver_id=payload.driver_id, vehicle_id=payload.vehicle_id, status='active')
        db.add(new_route)

        stmt_session = select(WorkSession).with_for_update().filter_by(driver_id=payload.driver_id, end_time=None)
        active_session = (await db.execute(stmt_session)).scalar_one_or_none()
        
        if payload.inventory is not None:
            clean_inventory = {}
            for p, q in payload.inventory.items():
                if str(q).strip() != '':
                    try:
                        clean_inventory[int(str(p).strip())] = int(str(q).strip())
                    except ValueError:
                        continue
            
            prod_ids = list(clean_inventory.keys())
            
            # +++ الدرع الفولاذي ضد الـ Deadlock: قفل السيارة (VehicleLoad) أولاً ليتطابق مع معمارية driver.py +++
            stmt_vloads = select(VehicleLoad).with_for_update().filter_by(vehicle_id=payload.vehicle_id)
            current_v_loads = (await db.execute(stmt_vloads)).scalars().all()
            current_load_map = {vl.product_variant_id: vl for vl in current_v_loads}
            
            all_involved_pids = list(set(prod_ids + list(current_load_map.keys()))) if not active_session else prod_ids
            all_involved_pids.sort() # HIERARCHY LOCK ORDERING
            
            variants_map = {}
            bulk_warehouse = {}
            
            if all_involved_pids:
                stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(all_involved_pids))
                variants_map = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}
                
                # قفل المستودع ثانياً (الترتيب الذهبي لمنع الـ Race Condition)
                stmt_wh = select(MainWarehouse).with_for_update().filter(MainWarehouse.product_variant_id.in_(all_involved_pids)).order_by(MainWarehouse.product_variant_id.asc())
                bulk_warehouse = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}
            
            if not active_session:
                # 🔴 حالة الصباح (Morning Load) - مطابقة للفلاسك 100%
                target_driver = await db.get(Driver, payload.driver_id)
                target_vehicle = await db.get(Vehicle, payload.vehicle_id)
                d_name = target_driver.full_name if target_driver else "غير معروف"
                v_plate = target_vehicle.plate_number if target_vehicle else "غير معروف"

                for p_id in all_involved_pids:
                    variant = variants_map.get(p_id)
                    if not variant: 
                        await db.rollback()
                        raise HTTPException(status_code=404, detail=f"مرفوض: المنتج رقم ({p_id}) غير موجود في النظام.")
                    packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
                    
                    new_cartons = clean_inventory.get(p_id, 0)
                    new_packs = new_cartons * packs_per_carton
                    
                    current_v_load = current_load_map.get(p_id)
                    current_packs = (current_v_load.quantity * packs_per_carton) if current_v_load else 0
                    
                    delta_packs = new_packs - current_packs
                    if delta_packs == 0: continue
                        
                    wh_record = bulk_warehouse.get(p_id)
                    if not wh_record:
                        wh_record = MainWarehouse(product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
                        db.add(wh_record)
                        
                    if delta_packs > 0: 
                        if wh_record.available_quantity_packs < delta_packs:
                            # +++ النسف المعماري (MissingGreenlet Shield): بناء الخطأ قبل الـ rollback لمنع الـ Async Crash +++
                            req_c, req_p = divmod(delta_packs, packs_per_carton)
                            av_c, av_p = divmod(wh_record.available_quantity_packs, packs_per_carton)
                            req_str = f"{req_c} كرتونة" + (f" و {req_p} حبة" if req_p else "") if req_c else f"{req_p} حبة"
                            av_str = f"{av_c} كرتونة" + (f" و {av_p} حبة" if av_p else "") if av_c else f"{av_p} حبة"
                            error_msg = f"مرفوض: رصيد المستودع من ({variant.variant_name}) لا يكفي. المطلوب: {req_str} | المتاح: {av_str}."
                            await db.rollback()
                            raise HTTPException(status_code=400, detail=error_msg)
                        
                        wh_record.available_quantity_packs -= delta_packs
                        trans_type = 'DISPATCH_LOAD'
                        d_c, d_p = divmod(delta_packs, packs_per_carton)
                        amt_str = f"{d_c} كرتونة" + (f" و {d_p} حبة" if d_p else "") if d_c else f"{d_p} حبة"
                        notes_text = f"تحميل سيارة المندوب {d_name} (لوحة: {v_plate}). سحب ({amt_str}) من المستودع."
                        
                    else: 
                        wh_record.available_quantity_packs += abs(delta_packs)
                        trans_type = 'DISPATCH_UNLOAD'
                        d_c, d_p = divmod(abs(delta_packs), packs_per_carton)
                        amt_str = f"{d_c} كرتونة" + (f" و {d_p} حبة" if d_p else "") if d_c else f"{d_p} حبة"
                        notes_text = f"إعادة بضاعة للمستودع من سيارة {d_name} (لوحة: {v_plate}). تم إرجاع ({amt_str})."
                        
                    if current_v_load:
                        if new_cartons == 0: 
                            db.delete(current_v_load) # الحذف الآمن في الذاكرة (Sync)
                        else: 
                            current_v_load.quantity = new_cartons
                    elif new_cartons > 0:
                        db.add(VehicleLoad(vehicle_id=payload.vehicle_id, product_variant_id=p_id, quantity=new_cartons))
                        
                    db.add(WarehouseLedger(
                        product_variant_id=p_id, transaction_type=trans_type,
                        quantity_packs=abs(delta_packs), balance_after_packs=wh_record.available_quantity_packs,
                        admin_id=current_admin.id, reference_id=f"VEH_{payload.vehicle_id}_MORN", notes=notes_text
                    ))

            else:
                # 🔴 حالة منتصف اليوم (Mid-day Handshake): المندوب نشط (نظام المصافحة)
                # +++ قفل العهدة لمنع فقدان التحديثات (Lost Update Shield) أثناء المصافحة +++
                stmt_sinvs = select(SessionInventory).with_for_update().filter(SessionInventory.work_session_id == active_session.id, SessionInventory.product_variant_id.in_(all_involved_pids))
                bulk_sinvs = {si.product_variant_id: si for si in (await db.execute(stmt_sinvs)).scalars().all()} if all_involved_pids else {}
                
                stmt_pending = select(InventoryTransfer.product_variant_id, func.sum(InventoryTransfer.quantity_packs)).filter(
                    InventoryTransfer.work_session_id == active_session.id,
                    InventoryTransfer.product_variant_id.in_(all_involved_pids),
                    InventoryTransfer.status == 'pending'
                ).group_by(InventoryTransfer.product_variant_id)
                
                pending_transfers_map = {v_id: total for v_id, total in (await db.execute(stmt_pending)).all()} if all_involved_pids else {}
                # +++ توحيد الزمن المعماري وطرد مكتبة time بالكامل +++
                batch_timestamp = str(int(datetime.now(timezone.utc).timestamp()))

                for p_id in all_involved_pids:
                    new_actual_qty_cartons = clean_inventory.get(p_id, 0)
                    variant = variants_map.get(p_id)
                    if not variant: 
                        await db.rollback()
                        raise HTTPException(status_code=404, detail=f"مرفوض: المنتج رقم ({p_id}) غير موجود في النظام.")
                    packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
                    new_actual_qty_packs = new_actual_qty_cartons * packs_per_carton

                    sess_inv = bulk_sinvs.get(p_id)
                    current_live_packs = sess_inv.current_remaining_quantity if sess_inv else 0
                    existing_pending_packs = pending_transfers_map.get(p_id, 0)
                    
                    delta_packs = new_actual_qty_packs - (current_live_packs + existing_pending_packs)
                    
                    # +++ درع الميدان: فحص رصيد المندوب قبل السحب (طلب البوت المفيد الوحيد هنا) +++
                    if delta_packs < 0:
                        if current_live_packs + delta_packs < 0:
                            await db.rollback()
                            raise HTTPException(status_code=400, detail=f"مرفوض: رصيد المندوب الحالي من ({variant.variant_name}) لا يكفي لتسجيل هذا السحب.")
                        # (نقطة هامة: لا نعدل المستودع هنا! التعديل يتم عند موافقة المندوب كما في فلاسك)
                    
                    # +++ النسف المعماري (The Double-Load Exploit): لا نعدل VehicleLoad هنا إطلاقاً! التعديل يتم فقط بعد موافقة المندوب في respond_to_transfer لمنع تدبيل البضاعة مرتين في قاعدة البيانات +++
                    if delta_packs == 0: continue 

                    wh_record = bulk_warehouse.get(p_id)
                    if not wh_record:
                        wh_record = MainWarehouse(product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
                        db.add(wh_record)

                    if delta_packs > 0: 
                        if wh_record.available_quantity_packs < delta_packs:
                            error_msg = f"مرفوض: رصيد المستودع من ({variant.variant_name}) لا يكفي. المتاح {wh_record.available_quantity_packs} حبة."
                            await db.rollback()
                            raise HTTPException(status_code=400, detail=error_msg)
                        wh_record.available_quantity_packs -= delta_packs
                        wh_record.reserved_quantity_packs += delta_packs
                        
                        db.add(WarehouseLedger(
                            product_variant_id=p_id, transaction_type='HANDSHAKE_RESERVE',
                            quantity_packs=delta_packs, balance_after_packs=wh_record.available_quantity_packs,
                            admin_id=current_admin.id, reference_id=f"BATCH_{batch_timestamp}", notes=f"حجز بضاعة منتصف اليوم (قيد النقل). ({delta_packs} حبة)."
                        ))

                    new_transfer = InventoryTransfer(
                        work_session_id=active_session.id,
                        product_variant_id=p_id,
                        quantity_packs=delta_packs,
                        status='pending',
                        admin_id=current_admin.id,
                        notes=f"BATCH_{batch_timestamp}"
                    )
                    db.add(new_transfer)

        # ========================================================
        # 🔴 بناء المحلات والزيارات (الأيتام والطوارئ)
        # ========================================================
        stmt_shops = select(Shop).filter_by(zone_id=payload.zone_id, is_active=True, is_archived=False)
        shops_in_zone = (await db.execute(stmt_shops)).scalars().all()
        shop_ids = [s.id for s in shops_in_zone]
        
        # +++ النسف المعماري الحقيقي: إبقاء الـ Timezone ليتطابق مع الداتابيز ومنع كراش Offset-Naive +++
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        if shop_ids:
            # 1. تبني الأيتام (عبر تحديث قاعدة البيانات مباشرة لمنع انفجار الـ RAM و N+1 Updates)
            update_vals = {'driver_id': payload.driver_id}
            if active_session:
                update_vals['work_session_id'] = active_session.id
            
            stmt_adopt_orphans = update(Visit).where(
                Visit.shop_id.in_(shop_ids), 
                Visit.status == 'Pending', 
                Visit.driver_id.is_(None)
            ).values(**update_vals)
            await db.execute(stmt_adopt_orphans)
            
            # 2. جلب وتحديث زيارات المندوب (Sargable Optimization)
            stmt_existing = select(Visit).filter(
                Visit.driver_id == payload.driver_id,
                Visit.shop_id.in_(shop_ids),
                or_(
                    Visit.status == 'Pending', 
                    and_(Visit.visit_timestamp >= today_start, Visit.visit_timestamp < today_end)
                )
            )
            existing_visits = (await db.execute(stmt_existing)).scalars().all()
            existing_visits_map = {v.shop_id: v for v in existing_visits}
            visited_shop_ids = set(existing_visits_map.keys())

            # 3. جلب الطوارئ
            stmt_shortages = select(ShortageRequest.shop_id).filter(ShortageRequest.shop_id.in_(shop_ids), ShortageRequest.status == 'pending')
            shortage_shop_ids = set((await db.execute(stmt_shortages)).scalars().all())

            for shop in shops_in_zone:
                is_emerg = shop.id in shortage_shop_ids
                if shop.id not in visited_shop_ids:
                    new_visit = Visit(
                        driver_id=payload.driver_id, shop_id=shop.id, status='Pending', 
                        sequence=shop.sequence, is_emergency=is_emerg
                    )
                    # ربط الجلسة للزيارة الجديدة
                    if active_session:
                        new_visit.work_session_id = active_session.id
                    db.add(new_visit)
                else:
                    visit_to_update = existing_visits_map.get(shop.id)
                    if visit_to_update and is_emerg:
                         visit_to_update.is_emergency = True

        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast({"event": "ROUTE_DISPATCHED", "message": "تم إطلاق خط سير جديد"}))
        return {"message": "تم إطلاق خط السير بنجاح"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي في الخادم أثناء إطلاق خط السير.")


# =========================================
# 7. جلب الحمولة الافتتاحية للسيارة (للإدارة والمستودع) - (متطابقة مع Flask 100%)
# =========================================
@router.get("/dispatch/inventory/{vehicle_id}", response_model=List[VehicleInventoryItemResponse], status_code=200)
async def get_vehicle_inventory(
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):

    # 1. النسف المعماري لسيارة الأشباح (نفس منطق الفلاسك)
    # +++ نسف ثغرة  ـ MultipleResultsFound بوضع Limit 1 مطابق للفلاسك +++
    stmt_unsettled = select(WorkSession).join(
        DispatchRoute, DispatchRoute.work_session_id == WorkSession.id
    ).filter(
        DispatchRoute.vehicle_id == vehicle_id,
        WorkSession.is_settled == False
    ).order_by(WorkSession.id.desc()).limit(1)
    
    unsettled_session = (await db.execute(stmt_unsettled)).scalars().first()

    inventory_map = {}
    is_live = False

    # 2. جلب الجرد (حسب حالة السيارة)
    if unsettled_session:
        is_live = True
        # السيارة "عهدة في الشارع": نقرأ من جرد الجلسة المرتبطة بها حصراً (بالحبات)
        stmt_sess_inv = select(SessionInventory).filter_by(work_session_id=unsettled_session.id)
        sess_invs = (await db.execute(stmt_sess_inv)).scalars().all()
        for inv in sess_invs:
            inventory_map[inv.product_variant_id] = inv.current_remaining_quantity
    else:
        # السيارة "نائمة في المستودع": نقرأ حمولة السيارة المعتمدة ونحولها لحبات فوراً لتوحيد المعمارية
        stmt_loads = select(VehicleLoad).options(joinedload(VehicleLoad.product_variant)).filter_by(vehicle_id=vehicle_id)
        loads = (await db.execute(stmt_loads)).scalars().all()
        for l in loads:
            v_packs = l.product_variant.packs_per_carton if l.product_variant and l.product_variant.packs_per_carton else 1
            # +++ استعادة البزنس لوجيك الأصيل: قراءة الكراتين فقط لأن حمولة المستودع الصباحية لا تحتوي فراطة +++
            inventory_map[l.product_variant_id] = l.quantity * v_packs

    # 3. +++ سحق المخزون الشبح: دمج البيانات مع المنتجات النشطة، أو الموقوفة التي لا يزال لها رصيد بالسيارة +++
    valid_pids = list(inventory_map.keys())
    active_or_loaded_cond = or_(ProductVariant.is_active == True, ProductVariant.id.in_(valid_pids)) if valid_pids else ProductVariant.is_active == True
    stmt_variants = select(ProductVariant).filter(active_or_loaded_cond)
    variants = (await db.execute(stmt_variants)).scalars().all()
    
    result = []
    for v in variants:
        total_packs = inventory_map.get(v.id, 0)
        packs = v.packs_per_carton if v.packs_per_carton and v.packs_per_carton > 0 else 1
        
        # +++ المعمارية الموحدة (Unified Logic): الحساب الآن يتم دائماً على أساس الحبات لمنع ضياع الكسور +++
        current_quantity = total_packs // packs if total_packs > 0 else 0
        current_loose_packs = total_packs % packs if total_packs > 0 else 0

        result.append({
            "product_id": str(v.id), # مطابقة الـ Frontend
            "product_name": v.variant_name,
            "current_quantity": current_quantity,
            "current_loose_packs": current_loose_packs # +++ حماية الفراطة من التبخر +++
        })

    return result


# =========================================
# 8. جلب الجرد اللحظي (الحي) لسيارة المندوب بالشارع (In-Van)
# =========================================
@router.get("/dispatch/route/{route_id}/live_inventory", response_model=List[RouteLiveInventoryItemResponse], status_code=200)
async def get_route_live_inventory(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):

    route = await db.get(DispatchRoute, route_id)
    if not route or not route.driver_id:
        raise HTTPException(status_code=404, detail="خط السير غير موجود أو غير مرتبط بمندوب.")

    # +++ النسف المعماري لـ 500 Crash: استخدام Limit(1) بدلاً من scalar_one_or_none +++
    stmt_session = select(WorkSession).filter_by(
        driver_id=route.driver_id, 
        is_settled=False
    ).order_by(WorkSession.id.desc()).limit(1)
    
    active_session = (await db.execute(stmt_session)).scalars().first()

    # خريطة الجرد لتخزين إجمالي الحبات (O(1)) بدلاً من الكلاس الوهمي DummyInv
    inventory_packs_map = {}
    pending_withdrawals_map = {}
    
    if active_session:
        # المندوب بالشارع: نقرأ عهدته الحية
        stmt_inv = select(SessionInventory).filter_by(work_session_id=active_session.id)
        inventories = (await db.execute(stmt_inv)).scalars().all()
        inventory_packs_map = {inv.product_variant_id: inv.current_remaining_quantity for inv in inventories}
        
        # تصحيح خيانة العرض: جلب السحوبات المعلقة (السالبة) وعزلها
        stmt_pending = select(
            InventoryTransfer.product_variant_id, 
            func.sum(InventoryTransfer.quantity_packs)
        ).filter(
            InventoryTransfer.work_session_id == active_session.id,
            InventoryTransfer.status == 'pending',
            InventoryTransfer.quantity_packs < 0
        ).group_by(InventoryTransfer.product_variant_id)
        
        pending_transfers = (await db.execute(stmt_pending)).all()
        # +++ الدرع الفولاذي: حماية السيرفر من None والـ Decimal القادمة من func.sum +++
        pending_withdrawals_map = {v_id: int(total or 0) for v_id, total in pending_transfers if v_id}
    else:
        # المندوب نائم: نقرأ حمولة السيارة ونحولها فوراً إلى حبات نقية في الذاكرة
        stmt_loads = select(VehicleLoad).filter_by(vehicle_id=route.vehicle_id)
        loads = (await db.execute(stmt_loads)).scalars().all()
        
        if loads:
            load_pids = [l.product_variant_id for l in loads]
            stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(load_pids))
            variants_for_load = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}
            
            for l in loads:
                variant = variants_for_load.get(l.product_variant_id)
                packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton else 1
                # +++ التجميع التراكمي: حماية من أي تكرار تاريخي (Glitch) في الداتابيز +++
                inventory_packs_map[l.product_variant_id] = inventory_packs_map.get(l.product_variant_id, 0) + (l.quantity * packs_per_carton)

    # +++ سحق المخزون الشبح +++
    valid_pids = list(set(list(inventory_packs_map.keys()) + list(pending_withdrawals_map.keys())))
    active_or_loaded_cond = or_(ProductVariant.is_active == True, ProductVariant.id.in_(valid_pids)) if valid_pids else ProductVariant.is_active == True
    stmt_all_variants = select(ProductVariant).filter(active_or_loaded_cond)
    variants = (await db.execute(stmt_all_variants)).scalars().all()
    
    result = []
    for v in variants:
        total_live_packs = inventory_packs_map.get(v.id, 0)
        packs_per_carton = v.packs_per_carton if v.packs_per_carton and v.packs_per_carton > 0 else 1
        
        # pending_packs قيمتها سالبة أصلاً، جمعها يعني طرحها فعلياً لمعرفة المتاح الصافي
        pending_packs = pending_withdrawals_map.get(v.id, 0)
        actual_remaining_packs = total_live_packs + pending_packs 
        
        current_cartons = actual_remaining_packs // packs_per_carton if actual_remaining_packs > 0 else 0
        current_packs = actual_remaining_packs % packs_per_carton if actual_remaining_packs > 0 else 0
        
        result.append({
            "product_id": str(v.id),
            "product_name": v.variant_name,
            "current_cartons": current_cartons,
            "current_packs": current_packs
        })

    return result


# +++ دالة مساعدة (مطابقة للفلاسك) لتحويل الحبات إلى نصوص بشرية في الليدجر +++
def format_qty_py(total_packs: int, packs_per_carton: int) -> str:
    if not packs_per_carton or packs_per_carton <= 1:
        return f"{total_packs} حبة"
    abs_total = abs(int(total_packs))
    cartons, packs = divmod(abs_total, packs_per_carton)
    parts = []
    if cartons > 0: parts.append(f"{cartons} كرتونة")
    if packs > 0: parts.append(f"{packs} حبة")
    return " و ".join(parts) if parts else "0 حبة"


# =========================================
# 9. تعديل الحمولة اللحظي (بالزيادة والنقصان) مع توثيق الحركة (In-Van Adjustment)
# =========================================
@router.put("/dispatch/route/{route_id}/adjust_inventory", status_code=200)
async def adjust_route_inventory(
    route_id: int,
    payload: AdjustRouteInventoryRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
        # 1. الدرع الفولاذي: منع سحب بضاعة للسيارات أثناء جرد المستودع
    stmt_wh_lock = select(SystemSetting).filter_by(setting_key='warehouse_status')
    lock_setting = (await db.execute(stmt_wh_lock)).scalar_one_or_none()
    if lock_setting and lock_setting.setting_value == 'AUDIT_LOCK':
        raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً لغايات الجرد (Stocktake). يرجى فتح المستودع أولاً.")

    # +++ قفل خط السير لمنع بدء عمل متزامن أثناء التعديل +++
    stmt_route_lock = select(DispatchRoute).with_for_update().filter_by(id=route_id)
    route = (await db.execute(stmt_route_lock)).scalar_one_or_none()
    if not route or not route.driver_id:
        await db.rollback() # +++ الدرع الفولاذي: إنقاذ السيرفر من شلل الأقفال +++
        raise HTTPException(status_code=404, detail="خط السير غير موجود أو غير مرتبط بمندوب.")

    # 2. الدرع المعماري: تحديد وقفل الجلسة فوراً لمنع (TOCTOU Race Condition)
    stmt_unsettled = select(WorkSession).with_for_update().filter_by(driver_id=route.driver_id, is_settled=False).order_by(WorkSession.id.desc()).limit(1)
    unsettled_session = (await db.execute(stmt_unsettled)).scalars().first()
    
    if unsettled_session and unsettled_session.end_time:
        await db.rollback() # +++ إنقاذ السيرفر من شلل الأقفال +++
        raise HTTPException(status_code=403, detail="مرفوض: لا يمكن تعديل الجرد لأن المندوب أنهى عمله وبانتظار التسوية المالية. قم باعتماد التسوية أولاً أو تراجع عن إنهاء العمل.")

    active_session = unsettled_session if (unsettled_session and not unsettled_session.end_time) else None
    
    if not payload.deltas:
        raise HTTPException(status_code=400, detail="لم يتم إرسال أي تعديلات.")

    try:
        # 3. (تم نقل قفل التزامن للجلسة إلى بداية الدالة لسد ثغرة سباق الإشارات)

        # 4. تجميع الطلبات المتكررة (Aggregation) لنسف ثغرة التجزئة
        aggregated_deltas = {}
        for item in payload.deltas:
            aggregated_deltas[item.product_id] = aggregated_deltas.get(item.product_id, 0) + item.delta_cartons

        prod_ids = list(aggregated_deltas.keys())
        prod_ids.sort() # +++ النسف المعماري للـ Deadlock: الترتيب إجباري قبل قفل المستودع +++

        # 5. جلب الداتا كـ O(1) Batch Fetch
        stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(prod_ids))
        variants_map = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}
        
        # +++ الدرع الفولاذي: قفل حمولة السيارة لمنع المشرفين من التعديل المزدوج في نفس الثانية +++
        stmt_vloads = select(VehicleLoad).with_for_update().filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(prod_ids))
        bulk_vloads = {vl.product_variant_id: vl for vl in (await db.execute(stmt_vloads)).scalars().all()}
        
        # قفل المستودع بالترتيب التصاعدي لمنع التقاطع
        stmt_wh = select(MainWarehouse).with_for_update().filter(MainWarehouse.product_variant_id.in_(prod_ids)).order_by(MainWarehouse.product_variant_id.asc())
        bulk_wh_records = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}

        bulk_sinvs = {}
        pending_withdrawals_map = {}
        
        if active_session:
            stmt_sinv = select(SessionInventory).with_for_update().filter(SessionInventory.work_session_id == active_session.id, SessionInventory.product_variant_id.in_(prod_ids))
            bulk_sinvs = {si.product_variant_id: si for si in (await db.execute(stmt_sinv)).scalars().all()}
            
            # جلب الحوالات السالبة المعلقة وتأمينها من None و TypeError
            stmt_pending = select(
                InventoryTransfer.product_variant_id, 
                func.sum(InventoryTransfer.quantity_packs)
            ).filter(
                InventoryTransfer.work_session_id == active_session.id,
                InventoryTransfer.product_variant_id.in_(prod_ids),
                InventoryTransfer.status == 'pending',
                InventoryTransfer.quantity_packs < 0
            ).group_by(InventoryTransfer.product_variant_id)
            
            pending_transfers = (await db.execute(stmt_pending)).all()
            pending_withdrawals_map = {v_id: int(total or 0) for v_id, total in pending_transfers if v_id}

        # ========================================================
        # 6. مرحلة التحقق الصارم المسبق (Validation Phase)
        # ========================================================
        for p_id, delta_cartons in aggregated_deltas.items():
            if delta_cartons == 0: continue
            variant = variants_map.get(p_id)
            if not variant: 
                await db.rollback()
                raise HTTPException(status_code=404, detail=f"مرفوض: المنتج رقم ({p_id}) غير موجود في النظام.")

            if active_session:
                safe_packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
                delta_packs = delta_cartons * safe_packs_per_carton
                
                sess_inv = bulk_sinvs.get(p_id)
                current_packs = sess_inv.current_remaining_quantity if sess_inv else 0
                
                # pending_withdrawals قيمتها سالبة أصلاً
                pending_withdrawals = pending_withdrawals_map.get(p_id, 0)
                available_packs = current_packs + pending_withdrawals 
                
                if available_packs + delta_packs < 0:
                    await db.rollback()
                    max_withdraw_cartons = available_packs // safe_packs_per_carton
                    raise HTTPException(status_code=400, detail=f"عذراً، المتاح فعلياً من ({variant.variant_name}) للسحب هو {max_withdraw_cartons} كرتونة فقط (بعد خصم الحوالات المعلقة).")
            else:
                v_load = bulk_vloads.get(p_id)
                current_cartons = v_load.quantity if v_load else 0
                if current_cartons + delta_cartons < 0:
                    await db.rollback()
                    raise HTTPException(status_code=400, detail=f"عذراً، حمولة السيارة المبدئية من ({variant.variant_name}) لا تكفي لهذا السحب.")

        # ========================================================
        # 7. مرحلة التنفيذ الموحدة (Zero Trust Model)
        # ========================================================
        batch_timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        
        for p_id, delta_cartons in aggregated_deltas.items():
            if delta_cartons == 0: continue
            variant = variants_map.get(p_id)
            if not variant: 
                await db.rollback()
                raise HTTPException(status_code=404, detail=f"مرفوض: المنتج رقم ({p_id}) غير موجود في النظام.")

            wh_record = bulk_wh_records.get(p_id)
            if not wh_record:
                wh_record = MainWarehouse(product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
                db.add(wh_record)
                bulk_wh_records[p_id] = wh_record
                
            safe_packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
            delta_packs = delta_cartons * safe_packs_per_carton

            if active_session:
                # 🔴 المندوب بالشارع: النقل للمحجوز (In-Transit) أو إصدار طلب سحب
                if delta_packs > 0:
                    if wh_record.available_quantity_packs < delta_packs:
                        await db.rollback()
                        raise HTTPException(status_code=400, detail=f"مرفوض: رصيد المستودع من ({variant.variant_name}) لا يكفي لإرسال ({delta_packs}) حبة.")
                    
                    wh_record.available_quantity_packs -= delta_packs
                    wh_record.reserved_quantity_packs += delta_packs
                    
                    db.add(WarehouseLedger(
                        product_variant_id=p_id, transaction_type='HANDSHAKE_RESERVE',
                        quantity_packs=delta_packs, balance_after_packs=wh_record.available_quantity_packs,
                        admin_id=current_admin.id, reference_id="MANUAL_ADJUST", 
                        notes=f"تعديل حمولة لمندوب نشط (حجز البضاعة). ({format_qty_py(delta_packs, safe_packs_per_carton)})"
                    ))
                
                # إصدار الحوالة للمندوب
                new_transfer = InventoryTransfer(
                    work_session_id=active_session.id,
                    product_variant_id=p_id,
                    quantity_packs=delta_packs,
                    status='pending',
                    admin_id=current_admin.id,
                    notes=f"BATCH_{batch_timestamp}" 
                )
                db.add(new_transfer)
                
            else:
                # 🔴 المندوب نائم: تعديل VehicleLoad المباشر وسحب/إرجاع للمستودع فوراً
                if delta_packs > 0:
                    if wh_record.available_quantity_packs < delta_packs:
                        await db.rollback()
                        raise HTTPException(status_code=400, detail=f"مرفوض: رصيد المستودع من ({variant.variant_name}) لا يكفي لتزويد السيارة بـ ({delta_packs}) حبة.")
                    wh_record.available_quantity_packs -= delta_packs
                    trans_type = 'DISPATCH_LOAD'
                    w_notes = f"تعديل حمولة سيارة قبل العمل. سحب ({format_qty_py(delta_packs, safe_packs_per_carton)})."
                else:
                    wh_record.available_quantity_packs += abs(delta_packs)
                    trans_type = 'DISPATCH_UNLOAD'
                    w_notes = f"تعديل حمولة سيارة قبل العمل. إعادة {abs(delta_packs)} حبة."
                
                db.add(WarehouseLedger(
                    product_variant_id=p_id, transaction_type=trans_type,
                    quantity_packs=abs(delta_packs), balance_after_packs=wh_record.available_quantity_packs,
                    admin_id=current_admin.id, reference_id="MANUAL_ADJUST", notes=w_notes
                ))

                v_load = bulk_vloads.get(p_id)
                if v_load: 
                    v_load.quantity += delta_cartons
                    # +++ سحق ثغرة الأشباح: مسح السجل نهائياً إذا تم تصفير حمولة الصنف +++
                    if v_load.quantity <= 0:
                        db.delete(v_load) # الحذف الآمن في الذاكرة (Sync)
                elif delta_cartons > 0: 
                    db.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=p_id, quantity=delta_cartons))

        # 8. الدرع الرقابي: توثيق العملية الحساسة لحماية السيرفر
        audit_details = " | ".join([
            f"صنف {p_id} (الفرق: {'+' if delta_cartons > 0 else ''}{delta_cartons} كرتونة)" 
            for p_id, delta_cartons in aggregated_deltas.items() if delta_cartons != 0
        ])
        
        # حماية الداتابيز من انفجار الـ VARCHAR
        if len(audit_details) > 250:
            audit_details = audit_details[:247] + "..."
        
        db.add(SystemAuditLog(
            admin_id=current_admin.id,
            target_id=f"Route_{route.id}_Driver_{route.driver_id}",
            action_type="MANUAL_INVENTORY_ADJUSTMENT",
            old_value="تعديل مباشر على حمولة السيارة / العهدة",
            new_value=audit_details
        ))

        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast({"event": "INVENTORY_ADJUSTED", "message": "تم تعديل حمولة سيارة"}))
        
        msg = "تم تحديث حمولة السيارة."
        if active_session:
            msg += " تم إرسال الحوالة للمندوب، بانتظار تأكيده للاستلام لتحديث عهدته المالية."
            
        return {"message": msg}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي في الخادم أثناء تعديل الحمولة.")

# =========================================
# 10. مراقبة حالة الحوالات المعلقة والمرفوضة (للمسؤول) - O(1) Architecture
# =========================================
@router.get("/dispatch/route/{route_id}/transfers", response_model=List[RouteTransferResponse], status_code=200)
async def get_route_transfers(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):

    route = await db.get(DispatchRoute, route_id)
    if not route or not route.driver_id:
        return []

    # +++ النسف المعماري (حرج 4): إبقاء الحوالات مرئية للإدارة حتى بعد إنهاء العمل وقبل التسوية +++
    # +++ درع الحماية: استخدام limit(1) لسحق كراش MultipleResultsFound +++
    stmt_session = select(WorkSession).filter_by(
        driver_id=route.driver_id, 
        is_settled=False
    ).order_by(WorkSession.id.desc()).limit(1)
    
    active_session = (await db.execute(stmt_session)).scalars().first()
    if not active_session:
        return []

    # +++ جلب جميع الحوالات لهذه الجلسة مع المنتجات بضربة واحدة O(1) (Eager Loading) +++
    stmt_transfers = select(InventoryTransfer).options(
        joinedload(InventoryTransfer.product_variant)
    ).filter_by(
        work_session_id=active_session.id
    ).order_by(InventoryTransfer.created_at.desc())
    
    transfers = (await db.execute(stmt_transfers)).scalars().all()

    result = []
    for t in transfers:
        variant = t.product_variant
        packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton else 1
        
        # +++ استعادة المنطق المحاسبي الأصلي للفلاسك بالملي (الكراتين والحبات) +++
        abs_qty = abs(t.quantity_packs)
        sign = -1 if t.quantity_packs < 0 else 1
        delta_cartons = (abs_qty // packs_per_carton) * sign
        delta_packs = (abs_qty % packs_per_carton) * sign

        # +++ جلب معرّف الدفعة لتمكين الـ React من دمج الحوالات في الشاشة +++
        batch_id = t.notes if (t.notes and "BATCH_" in t.notes) else f"SINGLE_{t.id}"

        result.append({
            "transfer_id": t.id,
            "product_name": variant.variant_name if variant else "غير معروف",
            "delta_cartons": delta_cartons,
            "delta_packs": delta_packs, # +++ سحق ثغرة تآكل الفراطة +++
            "status": t.status, 
            "created_at": t.created_at.isoformat() if t.created_at else None, # +++ سحق لغم  ـ Timezone +++
            "batch_id": batch_id 
        })

    return result


# =========================================
# 11. استرجاع المحلات (شاشة التوزيع - Pagination Limit)
# =========================================
@router.get("/dispatch/shops", response_model=List[DispatchShopResponse], status_code=200)
async def get_dispatch_shops(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
    # تحذير هندسي: تم إزالة  ـ limit(2000) الكارثي لأن يسبب اختلاف المحلات (Data Truncation)
    # ملاحظة: يجب تطبيق Pagination 진ية لاحقاً، ولكن حالياً نجلب المحلات النشطة لoids كوارث التوزيع
    stmt = select(Shop).filter(Shop.is_active == True, Shop.is_archived == False).order_by(nullslast(Shop.sequence.asc()), Shop.id.asc())
    shops = (await db.execute(stmt)).scalars().all()
    
    result = []
    for s in shops:
        result.append({
            "id": str(s.id),
            "name": s.name,
            "owner": s.contact_person.strip() if s.contact_person else "", # +++ تنظيف المالك +++
            "phone": s.phone_number or "",
            "mapLink": s.location_link or "",
            "zoneId": str(s.zone_id) if s.zone_id else "",
            "initialDebt": float(s.current_balance or 0.0),
            "maxDebtLimit": float(s.max_debt_limit or 0.0),
            "sequence": s.sequence if s.sequence is not None else 999, # +++ حماية Pydantic من كراش الـ None +++
            "archived": getattr(s, 'is_archived', False)
        })

    return result


# =========================================
# 12. التحديث الجماعي للمحلات (نقل، ترتيب، أرشفة، استعادة)
# =========================================
@router.put("/dispatch/shops/bulk_update", status_code=200)
async def bulk_update_shops(
    payload: List[BulkUpdateShopItem],
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
        
    try:
        # 1. تنظيف الـ IDs من حرف s القادم من React (مطابق للفلاسك)
        shop_ids = [str(item.id).replace('s', '') for item in payload if item.id]
        if not shop_ids:
            return {"message": "لا توجد بيانات للتحديث"}

        # 2. جلب المحلات من الداتابيز دفعة واحدة O(1)
        stmt_shops = select(Shop).filter(Shop.id.in_([int(i) for i in shop_ids if i.isdigit()]))
        bulk_shops = {str(sh.id): sh for sh in (await db.execute(stmt_shops)).scalars().all()}
        
        # 3. جلب المناطق للتحقق من سلامة استعادة المحلات المؤرشفة (Restore Shield)
        zone_ids_to_check = set()
        for s in payload:
            if s.archived is False:
                clean_id = s.id.replace('s', '')
                z_id = s.zoneId
                if not z_id and clean_id in bulk_shops:
                    z_id = str(bulk_shops[clean_id].zone_id)
                if z_id and z_id.isdigit():
                    zone_ids_to_check.add(int(z_id))
                    
        bulk_zones = {}
        if zone_ids_to_check:
            stmt_zones = select(Zone).filter(Zone.id.in_(list(zone_ids_to_check)))
            bulk_zones = {z.id: z for z in (await db.execute(stmt_zones)).scalars().all()}

        archived_shop_ids = []
        
        # 4. التحديث الجراحي بالذاكرة
        for s_data in payload:
            clean_id = s_data.id.replace('s', '')
            shop = bulk_shops.get(clean_id)
            
            if shop:
                # حماية الاستعادة (منع استعادة محل لمنطقة ميتة)
                if s_data.archived is False:
                    raw_zone = s_data.zoneId if s_data.zoneId is not None else str(shop.zone_id)
                    z_id = int(raw_zone) if (raw_zone and raw_zone.isdigit()) else None
                    zone_exists = bulk_zones.get(z_id)
                    
                    if not zone_exists or not getattr(zone_exists, 'is_active', True):
                        await db.rollback()
                        raise HTTPException(status_code=400, detail=f"لا يمكن استعادة المحل '{shop.name}' لأن منطقته مؤرشفة. يرجى نقله لمنطقة نشطة أولاً.")

                # تحديث الترتيب مع حماية الفراغات (Empty Strings)
                if s_data.sequence is not None:
                    raw_seq = str(s_data.sequence).strip()
                    shop.sequence = int(raw_seq) if raw_seq.isdigit() else 999
                    
                # تحديث حالة الأرشيف
                if s_data.archived is not None:
                    shop.is_archived = s_data.archived
                    if s_data.archived is True:
                        archived_shop_ids.append(int(shop.id))
                        
                # تحديث النقل الجغرافي (Zone)
                if s_data.zoneId is not None and str(s_data.zoneId).isdigit():
                    shop.zone_id = int(s_data.zoneId)
                    
        # 5. الكي الجراحي: إلغاء الزيارات المعلقة للمحلات التي تم أرشفتها للتو (Cascade Cancel)
        if archived_shop_ids:
            stmt_cancel = update(Visit).where(
                Visit.shop_id.in_(archived_shop_ids), 
                Visit.status == 'Pending'
            ).values(status='Cancelled')
            await db.execute(stmt_cancel)
            
        await db.commit()
        return {"message": "تم تحديث المحلات بنجاح"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء التحديث الجماعي.")


# =========================================
# 13. إضافة محل جديد من لوحة التحكم (مع كاشف التكرار الذكي)
# =========================================
@router.post("/dispatch/shops", status_code=201)
async def admin_add_shop(
    payload: AdminAddShopRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    name = payload.name.strip()
    phone = payload.phone.strip() if payload.phone else ""
    map_link = payload.mapLink.strip() if payload.mapLink else ""
    zone_id = payload.zoneId
    
    # +++ حماية  ـ 500 Crash بمعالجة منفصلة للإحداثيات لمنع ضياع السليم منها +++
    lat, lng = None, None
    try:
        # +++ سحق لغم الصفر الجغرافي: 0.0 يعتبر Falsy في بايثون، يجب فحصه كـ is not None +++
        if payload.latitude is not None and str(payload.latitude).strip().lower() not in ['', 'none']:
            lat = float(str(payload.latitude).strip())
    except ValueError: pass
    
    try:
        if payload.longitude is not None and str(payload.longitude).strip().lower() not in ['', 'none']:
            lng = float(str(payload.longitude).strip())
    except ValueError: pass

    if not name: 
        raise HTTPException(status_code=400, detail="مرفوض: اسم المحل إجباري")
    if not zone_id: 
        raise HTTPException(status_code=400, detail="مرفوض: المنطقة إجبارية لإنشاء المحل")

    # ========================================================
    # 1. الفحص الذكي المركب (Duplicate Detection Shield) - مطابق للفلاسك 100%
    # ========================================================
    duplicate_shop = None

    # الفحص الأول: رقم الهاتف
    if phone:
        stmt = select(Shop).options(joinedload(Shop.zone)).filter(Shop.phone_number == phone)
        duplicate_shop = (await db.execute(stmt)).scalars().first()

    # الفحص الثاني: التطابق بالاسم ورابط الموقع
    if not duplicate_shop and name and map_link:
        stmt = select(Shop).options(joinedload(Shop.zone)).filter(Shop.name == name, Shop.location_link == map_link)
        duplicate_shop = (await db.execute(stmt)).scalars().first()

    # الفحص الثالث: الرادار الجغرافي (الإحداثيات)
    if not duplicate_shop and lat is not None and lng is not None:
        stmt = select(Shop).options(joinedload(Shop.zone)).filter(
            Shop.name == name,
            Shop.latitude.isnot(None), 
            Shop.longitude.isnot(None),
            # +++ رياضيات الـ GPS الآمنة في SQLAlchemy +++
            func.abs(cast(Shop.latitude, Float) - lat) < 0.0001,
            func.abs(cast(Shop.longitude, Float) - lng) < 0.0001
        )
        duplicate_shop = (await db.execute(stmt)).scalars().first()

    # في حال اكتشاف تكرار ولم يتم طلب الحفظ الإجباري
    if duplicate_shop and not payload.force_save:
        zone_name = duplicate_shop.zone.name if duplicate_shop.zone else "بدون منطقة"
        is_arch_msg = " (مؤرشف)" if getattr(duplicate_shop, 'is_archived', False) else ""
        
        # نرجع 409 مع بيانات المحل المكرر ليتمكن الفرونت إند من عرضها للمشرف
        return JSONResponse(status_code=409, content={
            "message": "تنبيه: يوجد محل مسجل مسبقاً بمعلومات مطابقة.",
            "is_duplicate": True,
            "existing_shop": {
                "id": str(duplicate_shop.id),
                "name": duplicate_shop.name,
                "owner": duplicate_shop.contact_person or "غير مسجل",
                "phone": duplicate_shop.phone_number,
                "mapLink": duplicate_shop.location_link,
                "zone_name": zone_name + is_arch_msg
            }
        })

    # ========================================================
    # 2. التطهير المحاسبي ونسف الفراغات للحفظ النهائي
    # ========================================================
    try:
        try:
            raw_initial_debt = str(payload.initialDebt).strip()
            safe_initial_debt = Decimal(raw_initial_debt) if raw_initial_debt not in ['', 'None'] else Decimal('0.0')
        except Exception:
            safe_initial_debt = Decimal('0.0')
            
        try:
            raw_max_limit = str(payload.maxDebtLimit).strip()
            safe_max_limit = Decimal(raw_max_limit) if raw_max_limit not in ['', 'None'] else Decimal('0.0')
        except Exception:
            safe_max_limit = Decimal('0.0')
            
        # تنظيف الترتيب (Sequence)
        raw_seq = str(payload.sequence).strip()
        safe_sequence = int(raw_seq) if raw_seq.isdigit() else 999

        new_shop = Shop(
            name=name,
            contact_person=payload.owner.strip() if payload.owner else "",
            phone_number=phone,
            location_link=map_link,
            latitude=lat,
            longitude=lng,
            zone_id=zone_id,
            # حماية الداتابيز من الأرصدة الافتتاحية السالبة
            current_balance=max(Decimal('0.0'), safe_initial_debt),
            max_debt_limit=safe_max_limit,
            added_by_driver_id=current_admin.id,
            sequence=safe_sequence
        )
        db.add(new_shop)
        # +++ الدرع الفولاذي (O(1)): سحب الـ ID قبل الـ Commit لمنع כراش MissingGreenlet بدون استعلام إضافي +++
        await db.flush() 
        shop_id = new_shop.id 
        
        await db.commit()
        return {"message": "تم إضافة المحل بنجاح", "shop_id": str(shop_id)}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء إضافة المحل.")


# =========================================
# 14. استرجاع خطوط السير النشطة والمؤجلة (غرفة مراقبة المدير)
# =========================================
@router.get("/dispatch/active_routes", response_model=List[ActiveRouteResponse], status_code=200)
async def get_active_routes(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
        
    stmt_routes = select(DispatchRoute).filter(DispatchRoute.status.in_(['active', 'waiting', 'postponed']))
    routes = (await db.execute(stmt_routes)).scalars().all()
    
    # +++ تدمير N+1 باستخدام القواميس (Dictionaries) مع تنظيف التكرار عبر Set لحماية السيرفر +++
    zone_ids = list({r.zone_id for r in routes if r.zone_id})
    driver_ids = list({r.driver_id for r in routes if r.driver_id})
    session_ids = list({r.work_session_id for r in routes if r.work_session_id})
    
    zones_map = {}
    if zone_ids:
        stmt_zones = select(Zone.id, Zone.name).filter(Zone.id.in_(zone_ids))
        zones_map = {z_id: z_name for z_id, z_name in (await db.execute(stmt_zones)).all()}

    drivers_map = {}
    if driver_ids:
        stmt_drivers = select(Driver.id, Driver.full_name).filter(Driver.id.in_(driver_ids))
        drivers_map = {d_id: d_name for d_id, d_name in (await db.execute(stmt_drivers)).all()}

    pending_visits_map = {}
    session_ended_map = {} 
    
    if driver_ids:
        # +++ النسف المعماري لـ "كمين الصفر": نعد المحلات المعلقة بضربة واحدة للداتابيز (O(1)) +++
        active_zone_ids = list({r.zone_id for r in routes if r.status == 'active' and r.zone_id})
        
        if active_zone_ids:
            # +++ Clean Code (Labeling) لتأمين البيانات وحماية الـ Indexing +++
            stmt_pending = select(Visit.driver_id, func.count(Visit.id).label('pending_count')).join(
                Shop, Visit.shop_id == Shop.id
            ).filter(
                Visit.driver_id.in_(driver_ids),
                Visit.status == 'Pending',
                or_(Shop.zone_id.in_(active_zone_ids), Visit.is_emergency == True)
            ).group_by(Visit.driver_id)
            
            pending_counts = (await db.execute(stmt_pending)).all()
            # +++ استخدام الأسماء الصريحة بناءً على اقتراح البوت +++
            pending_visits_map = {row.driver_id: row.pending_count for row in pending_counts}
        
        # +++ جلب حالات نهاية الجلسة O(1) +++
        if session_ids:
            stmt_sessions = select(WorkSession.id, WorkSession.end_time).filter(WorkSession.id.in_(session_ids))
            sessions_info = (await db.execute(stmt_sessions)).all()
            session_ended_map = {s_id: (end_t is not None) for s_id, end_t in sessions_info}
    
    # +++ حساب المحلات (المتبقية فقط) في المنطقة التي ليس لها مندوب +++
    # نعد فقط الزيارات المحررة (الأيتام) التي لم تنجز بعد
    stmt_shop_counts = select(Shop.zone_id, func.count(Visit.id)).join(
        Visit, Shop.id == Visit.shop_id
    ).filter(
        Shop.is_active == True,
        Shop.is_archived == False,
        Visit.status == 'Pending',
        Visit.driver_id.is_(None) # استخدام is_(None) للآمان في SQLAlchemy
    ).group_by(Shop.zone_id)
    
    shop_counts = (await db.execute(stmt_shop_counts)).all()
    zone_shops_map = {z_id: count for z_id, count in shop_counts}

    res = []
    for r in routes:
        # اللوجيك الأصلي: إذا كان الخط نشطاً والمندوب موجوداً، احسب الزيارات المعلقة للمندوب.
        # أما إذا كان موقوفاً أو بدون مندوب، فالمحلات المتبقية هي كل محلات المنطقة.
        if r.status == 'active' and r.driver_id:
            shops_remaining = pending_visits_map.get(r.driver_id, 0)
        else:
            shops_remaining = zone_shops_map.get(r.zone_id, 0)
            
        session_ended = session_ended_map.get(r.work_session_id, False) if r.work_session_id else False
            
        res.append({
            "id": str(r.id),
            "zoneId": str(r.zone_id) if r.zone_id else "",
            "zoneName": zones_map.get(r.zone_id, "منطقة محذوفة"),
            "driverId": str(r.driver_id) if r.driver_id else "",
            "driverName": drivers_map.get(r.driver_id, "بدون مندوب") if r.driver_id else "بدون مندوب",
            "vehicleId": str(r.vehicle_id) if r.vehicle_id else "",
            "shopsRemaining": shops_remaining,
            "status": r.status,
            "sessionEnded": session_ended 
        })
        
    return res


# =========================================
# 15. تغيير حالة خط السير (تبديل مندوب، تغيير حالة، تعديل حمولة) - (Zero Trust & No Phantoms)
# =========================================
@router.put("/dispatch/route/{route_id}/status", status_code=200)
async def update_route_status(
    route_id: int,
    payload: UpdateRouteStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # +++ الدرع الاستباقي (Fail-Fast): سد ثغرة الجرد في أول سطر لمنع اختناق السيرفر ونسف مشاكل المحرر +++
    if payload.inventory is not None:
        audit_check = (await db.execute(select(SystemSetting).filter_by(setting_key='warehouse_status'))).scalar_one_or_none()
        if audit_check and audit_check.setting_value == 'AUDIT_LOCK':
            raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً لغايات الجرد (Stocktake). يرجى فتح المستودع أولاً.")
            
    # +++ قفل خط السير لمنع التضارب أثناء التبديل أو الإغلاق +++
    stmt_route_lock = select(DispatchRoute).with_for_update().filter_by(id=route_id)
    route = (await db.execute(stmt_route_lock)).scalar_one_or_none()
    if not route:
        await db.rollback() # +++ الدرع الفولاذي: نسف ثغرة تسريب الأقفال (Lock Leak) +++
        raise HTTPException(status_code=404, detail="خط السير غير موجود")

    new_status = payload.status
    new_driver_id = int(payload.driverId) if payload.driverId and str(payload.driverId).isdigit() else None
    new_vehicle_id = int(payload.vehicleId) if payload.vehicleId and str(payload.vehicleId).isdigit() else None
    
    # ========================================================
    # 1. الدرع المعماري الصارم: التحقق من التضارب
    # ========================================================
    target_driver_id = new_driver_id or route.driver_id
    is_activating = (new_status == 'active') or (not new_status and route.status == 'active')
    
    if is_activating:
        if target_driver_id:
            stmt_dup_driver = select(DispatchRoute).filter(DispatchRoute.driver_id == target_driver_id, DispatchRoute.status == 'active', DispatchRoute.id != route.id)
            if (await db.execute(stmt_dup_driver)).first(): 
                raise HTTPException(status_code=400, detail="مرفوض: المندوب لديه خط سير نشط حالياً.")
        
        target_veh = new_vehicle_id or route.vehicle_id
        if target_veh:
            stmt_dup_veh = select(DispatchRoute).filter(DispatchRoute.vehicle_id == target_veh, DispatchRoute.status == 'active', DispatchRoute.id != route.id)
            if (await db.execute(stmt_dup_veh)).first(): 
                raise HTTPException(status_code=400, detail="مرفوض: هذه السيارة مستخدمة في خط سير نشط آخر.")

        stmt_dup_zone = select(DispatchRoute).filter(DispatchRoute.zone_id == route.zone_id, DispatchRoute.status == 'active', DispatchRoute.id != route.id)
        if (await db.execute(stmt_dup_zone)).first(): 
            raise HTTPException(status_code=400, detail="مرفوض: هذه المنطقة قيد العمل حالياً مع مندوب آخر.")

    try:
        # ========================================================
        # 2. تحديث الحالة (والجدولة التلقائية)
        # ========================================================
        if new_status: 
            route.status = new_status
            if new_status == 'closed':
                zone = await db.get(Zone, route.zone_id)
                if zone and zone.start_date and zone.schedule_frequency:
                    freq = str(zone.schedule_frequency)
                    days_to_add = 7
                    if freq == 'أسبوعي': days_to_add = 7
                    elif freq == 'نصف شهري': days_to_add = 14
                    else:
                        numbers = re.findall(r'\d+', freq)
                        if numbers: days_to_add = int(numbers[0])
                    zone.start_date = zone.start_date + timedelta(days=days_to_add)

            if new_status in ['closed', 'waiting', 'postponed'] and route.driver_id:
                # +++ الدرع الجغرافي: حصر مسح الزيارات المعلقة بمنطقة خط السير فقط لمنع مسح طوارئ المناطق الأخرى +++
                stmt_zone_shops = select(Shop.id).filter(Shop.zone_id == route.zone_id).scalar_subquery()
                stmt_zombies = update(Visit).where(
                    Visit.driver_id == route.driver_id, 
                    Visit.status == 'Pending',
                    Visit.shop_id.in_(stmt_zone_shops)
                ).values(driver_id=None, work_session_id=None, is_emergency=False)
                await db.execute(stmt_zombies)

        # ========================================================
        # 3. تبديل المندوب (حماية الفراطة، ودرع الـ Null Driver)
        # ========================================================
        if new_driver_id: 
            if new_driver_id != route.driver_id:
                # +++ لغم الـ Null Driver (الكي الجراحي): لا ننظف إلا إذا كان هناك مندوب قديم فعلاً +++
                if route.driver_id:
                    # +++ قفل الجلسة القديمة لمنع تضارب الإنهاء أثناء التبديل +++
                    stmt_old_sess = select(WorkSession).with_for_update().filter_by(driver_id=route.driver_id, end_time=None).limit(1)
                    old_active_session = (await db.execute(stmt_old_sess)).scalars().first()
                    
                    if old_active_session:
                        stmt_live_invs = select(SessionInventory).filter_by(work_session_id=old_active_session.id)
                        live_invs = (await db.execute(stmt_live_invs)).scalars().all()
                        
                        if live_invs:
                            var_ids = [inv.product_variant_id for inv in live_invs]
                            stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(var_ids))
                            variants = (await db.execute(stmt_vars)).scalars().all()
                            var_map = {v.id: (v.packs_per_carton if v.packs_per_carton else 1) for v in variants}
                            
                            stmt_vloads = select(VehicleLoad).with_for_update().filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(var_ids))
                            v_loads = (await db.execute(stmt_vloads)).scalars().all()
                            v_load_map = {vl.product_variant_id: vl for vl in v_loads}
                            
                            # +++ قفل المستودع لحماية الفراطة المرتجعة +++
                            stmt_wh = select(MainWarehouse).with_for_update().filter(MainWarehouse.product_variant_id.in_(var_ids)).order_by(MainWarehouse.product_variant_id.asc())
                            bulk_wh_records = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}
                            
                            for live_inv in live_invs:
                                safe_packs = var_map.get(live_inv.product_variant_id, 1)
                                actual_cartons = live_inv.current_remaining_quantity // safe_packs
                                loose_packs = live_inv.current_remaining_quantity % safe_packs # +++ سحق ثغرة تآكل الفراطة +++
                                
                                # +++ إعادة الفراطة الصريحة للمستودع وتوثيقها +++
                                if loose_packs > 0:
                                    wh_rec = bulk_wh_records.get(live_inv.product_variant_id)
                                    if not wh_rec:
                                        wh_rec = MainWarehouse(product_variant_id=live_inv.product_variant_id, available_quantity_packs=0, reserved_quantity_packs=0)
                                        db.add(wh_rec)
                                        bulk_wh_records[live_inv.product_variant_id] = wh_rec
                                        
                                    wh_rec.available_quantity_packs += loose_packs
                                    db.add(WarehouseLedger(
                                        product_variant_id=live_inv.product_variant_id, transaction_type='DISPATCH_UNLOAD',
                                        quantity_packs=loose_packs, balance_after_packs=wh_rec.available_quantity_packs,
                                        admin_id=current_admin.id, reference_id=f"SWITCH_{route.id}", notes="إرجاع فراطة صالحة للمستودع عند تبديل المندوب"
                                    ))

                                v_load = v_load_map.get(live_inv.product_variant_id)
                                # +++ سحق ثغرة الأشباح (Phantom Record) +++
                                if actual_cartons <= 0:
                                    if v_load: db.delete(v_load) 
                                else:
                                    if v_load: v_load.quantity = actual_cartons
                                    else: db.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=live_inv.product_variant_id, quantity=actual_cartons))
                                
                        old_active_session.end_time = datetime.now(timezone.utc)
                        
                        stmt_rej_transfers = update(InventoryTransfer).where(
                            InventoryTransfer.work_session_id == old_active_session.id, 
                            InventoryTransfer.status == 'pending'
                        ).values(status='rejected')
                        await db.execute(stmt_rej_transfers)

                    stmt_zone_shops = select(Shop.id).filter(Shop.zone_id == route.zone_id).scalar_subquery()
                    stmt_trans_visits = update(Visit).where(
                        Visit.driver_id == route.driver_id,
                        Visit.status == 'Pending',
                        Visit.shop_id.in_(stmt_zone_shops)
                    ).values(driver_id=new_driver_id, work_session_id=None)
                    await db.execute(stmt_trans_visits)
                    
            route.driver_id = new_driver_id
            route.work_session_id = None
            
        if new_vehicle_id: route.vehicle_id = new_vehicle_id
        
        # ========================================================
        # 4. تحديث الحمولة الجراحي (Guard & Zero Trust)
        # ========================================================
        if payload.inventory is not None and route.vehicle_id:
            # +++ الدرع الفولاذي: قفل الجلسة بضربة واحدة من البداية لمنع إنهاء العمل أثناء التعديل +++
            stmt_active_sess = select(WorkSession).with_for_update().filter_by(driver_id=route.driver_id, end_time=None).limit(1) if route.driver_id else None
            active_session = (await db.execute(stmt_active_sess)).scalars().first() if stmt_active_sess is not None else None
            
            if not active_session:
                # +++ النسف المعماري لكارثة تبخر المستودع (Warehouse Evaporation): حساب الفروقات بدقة وإرجاعها/سحبها من المستودع المركزي قبل تعديل السيارة لمنع ضياع البضاعة +++
                prod_ids_to_check = [int(p) for p, q in payload.inventory.items() if str(q).strip() != '']
                # +++ قفل VehicleLoad أولاً لمنع Deadlock متصالب مع ترتيب أقفال باقي الدوال +++
                stmt_existing_vl = select(VehicleLoad).with_for_update().filter_by(vehicle_id=route.vehicle_id)
                existing_vloads = (await db.execute(stmt_existing_vl)).scalars().all()
                existing_vl_map = {vl.product_variant_id: vl for vl in existing_vloads}
                
                all_pids = list(set(prod_ids_to_check + list(existing_vl_map.keys())))
                if all_pids:
                    stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(all_pids))
                    v_map = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}
                    
                    stmt_wh_lock = select(MainWarehouse).with_for_update().filter(MainWarehouse.product_variant_id.in_(all_pids)).order_by(MainWarehouse.product_variant_id.asc())
                    bulk_wh = {w.product_variant_id: w for w in (await db.execute(stmt_wh_lock)).scalars().all()}
                    
                    for p_id in all_pids:
                        variant = v_map.get(p_id)
                        if not variant: 
                            await db.rollback()
                            raise HTTPException(status_code=404, detail=f"مرفوض: المنتج رقم ({p_id}) غير موجود في النظام.")
                        ppc = variant.packs_per_carton if variant.packs_per_carton else 1
                        
                        raw_qty = payload.inventory.get(str(p_id), payload.inventory.get(p_id, 0))
                        clean_str = str(raw_qty).strip() if raw_qty is not None else ''
                        # Fix: dispatch.md Finding #1 — Reject negative cartons before delta to prevent phantom stock fabrication
                        new_cartons = int(clean_str) if (clean_str.isdigit() or (clean_str.startswith('-') and clean_str[1:].isdigit())) else 0
                        if new_cartons < 0:
                            await db.rollback()
                            raise HTTPException(status_code=400, detail=f"مرفوض أمنياً: لا يمكن إدخال كمية سالبة ({new_cartons}) للمنتج {variant.variant_name}.")
                        new_packs = new_cartons * ppc
                        
                        curr_load = existing_vl_map.get(p_id)
                        curr_packs = (curr_load.quantity * ppc) if curr_load else 0
                        delta_packs = new_packs - curr_packs
                        
                        if delta_packs == 0: continue
                        
                        wh_rec = bulk_wh.get(p_id)
                        if not wh_rec:
                            wh_rec = MainWarehouse(product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
                            db.add(wh_rec)
                            
                        if delta_packs > 0:
                            if wh_rec.available_quantity_packs < delta_packs:
                                await db.rollback()
                                raise HTTPException(status_code=400, detail=f"مرفوض: المستودع لا يملك ({delta_packs}) حبة متاحة من {variant.variant_name}.")
                            wh_rec.available_quantity_packs -= delta_packs
                            db.add(WarehouseLedger(product_variant_id=p_id, transaction_type='DISPATCH_LOAD', quantity_packs=delta_packs, balance_after_packs=wh_rec.available_quantity_packs, admin_id=current_admin.id, reference_id=f"VEH_EDIT_{route.id}", notes="تعديل حمولة سيارة قبل الدوام: سحب من المستودع"))
                        else:
                            wh_rec.available_quantity_packs += abs(delta_packs)
                            db.add(WarehouseLedger(product_variant_id=p_id, transaction_type='DISPATCH_UNLOAD', quantity_packs=abs(delta_packs), balance_after_packs=wh_rec.available_quantity_packs, admin_id=current_admin.id, reference_id=f"VEH_EDIT_{route.id}", notes="تعديل حمولة سيارة قبل الدوام: إعادة للمستودع"))
                            
                        if curr_load:
                            if new_cartons <= 0: db.delete(curr_load)
                            else: curr_load.quantity = new_cartons
                        elif new_cartons > 0:
                            db.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=p_id, quantity=new_cartons))
            else:
                admin_user_id = current_admin.id
                prod_ids_to_update = [int(p) for p, q in payload.inventory.items() if str(q).strip() != '']
                
                bulk_vloads = {}
                bulk_sinvs = {}
                pending_transfers_map = {}

                if prod_ids_to_update:
                    # +++ إعادة فرض الحماية المستودعية (Mid-day Handshake Guard) +++
                    stmt_wh_lock = select(MainWarehouse).with_for_update().filter(MainWarehouse.product_variant_id.in_(prod_ids_to_update)).order_by(MainWarehouse.product_variant_id.asc())
                    bulk_wh_records = {w.product_variant_id: w for w in (await db.execute(stmt_wh_lock)).scalars().all()}

                    stmt_vl = select(VehicleLoad).filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(prod_ids_to_update))
                    bulk_vloads = {vl.product_variant_id: vl for vl in (await db.execute(stmt_vl)).scalars().all()}

                    stmt_sinv = select(SessionInventory).with_for_update().filter(SessionInventory.work_session_id == active_session.id, SessionInventory.product_variant_id.in_(prod_ids_to_update))
                    bulk_sinvs = {si.product_variant_id: si for si in (await db.execute(stmt_sinv)).scalars().all()}

                    stmt_pending = select(InventoryTransfer.product_variant_id, func.sum(InventoryTransfer.quantity_packs)).filter(
                        InventoryTransfer.work_session_id == active_session.id,
                        InventoryTransfer.product_variant_id.in_(prod_ids_to_update),
                        InventoryTransfer.status == 'pending'
                    ).group_by(InventoryTransfer.product_variant_id)
                    
                    pending_transfers_query = (await db.execute(stmt_pending)).all()
                    pending_transfers_map = {v_id: int(total or 0) for v_id, total in pending_transfers_query if v_id}

                    stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(prod_ids_to_update))
                    variants_map = {v.id: v for v in (await db.execute(stmt_vars)).scalars().all()}
                    batch_timestamp = str(int(datetime.now(timezone.utc).timestamp()))
                    
                    for prod_id, new_qty_str in payload.inventory.items():
                        clean_qty_str = str(new_qty_str).strip()
                        if clean_qty_str == '': continue
                        try:
                            new_actual_qty_cartons = int(clean_qty_str)
                            p_id = int(prod_id)
                        except ValueError:
                            continue
                            
                        variant = variants_map.get(p_id)
                        if not variant: 
                            await db.rollback()
                            raise HTTPException(status_code=404, detail=f"مرفوض: المنتج رقم ({p_id}) غير موجود في النظام.")
                            
                        safe_packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
                        new_actual_qty_packs = new_actual_qty_cartons * safe_packs_per_carton
                            
                        # +++ النسف المعماري لثغرة التدبيل: ترك VehicleLoad دون مساس. الاعتماد الكلي على المصافحة (InventoryTransfer) لتعديل حمولة السيارة بشكل متزامن وآمن +++
                        sess_inv = bulk_sinvs.get(p_id)
                        current_live_packs = sess_inv.current_remaining_quantity if sess_inv else 0
                        existing_pending_packs = pending_transfers_map.get(p_id, 0)
                        
                        difference_in_packs = new_actual_qty_packs - (current_live_packs + existing_pending_packs)
                        
                        if difference_in_packs != 0:
                            wh_record = bulk_wh_records.get(p_id)
                            if not wh_record:
                                wh_record = MainWarehouse(product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
                                db.add(wh_record)
                                bulk_wh_records[p_id] = wh_record
                                
                            # +++ الدرع المستودعي: حجز البضاعة في حال الزيادة +++
                            if difference_in_packs > 0:
                                if wh_record.available_quantity_packs < difference_in_packs:
                                    await db.rollback()
                                    raise HTTPException(status_code=400, detail=f"مرفوض: رصيد المستودع من ({variant.variant_name}) لا يكفي لتسجيل هذا التعديل.")
                                    
                                wh_record.available_quantity_packs -= difference_in_packs
                                wh_record.reserved_quantity_packs += difference_in_packs
                                db.add(WarehouseLedger(
                                    product_variant_id=p_id, transaction_type='HANDSHAKE_RESERVE',
                                    quantity_packs=difference_in_packs, balance_after_packs=wh_record.available_quantity_packs,
                                    admin_id=admin_user_id, reference_id=f"BATCH_{batch_timestamp}", notes="حجز بضاعة لتعديل خط سير نشط."
                                ))
                                
                            # إصدار الحوالة للمندوب
                            new_transfer = InventoryTransfer(
                                work_session_id=active_session.id,
                                product_variant_id=p_id,
                                quantity_packs=difference_in_packs,
                                status='pending',
                                admin_id=admin_user_id,
                                notes=f"BATCH_{batch_timestamp}"
                            )
                            db.add(new_transfer)

        # ========================================================
        # 5. التوليد الذكي (أشباح الشاشة وربط الجلسة)
        # ========================================================
        if route.status == 'active' and route.driver_id:
            today = datetime.now(timezone.utc).date()
            
            stmt_shops_zone = select(Shop).filter_by(zone_id=route.zone_id, is_active=True, is_archived=False)
            shops_in_zone = (await db.execute(stmt_shops_zone)).scalars().all()
            shop_ids = [s.id for s in shops_in_zone]
            
            if shop_ids:
                # +++ الكي الجراحي: جلب جلسة المندوب الجديد لربطها بالأيتام فوراً +++
                stmt_new_sess = select(WorkSession).filter_by(driver_id=route.driver_id, end_time=None).limit(1)
                new_active_sess = (await db.execute(stmt_new_sess)).scalars().first()
                
                # التبني المباشر (Direct Update) لسحق استهلاك الذاكرة
                update_vals = {'driver_id': route.driver_id}
                if new_active_sess:
                    update_vals['work_session_id'] = new_active_sess.id
                    
                stmt_adopt_orphans = update(Visit).where(
                    Visit.shop_id.in_(shop_ids), 
                    Visit.status == 'Pending', 
                    Visit.driver_id.is_(None)
                ).values(**update_vals)
                await db.execute(stmt_adopt_orphans)
                
                # +++ النسف المعماري الحقيقي: منع كراش Offset-Naive +++
                today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                today_end = today_start + timedelta(days=1)
                
                stmt_existing = select(Visit).filter(
                    Visit.driver_id == route.driver_id,
                    Visit.shop_id.in_(shop_ids),
                    or_(Visit.status == 'Pending', and_(Visit.visit_timestamp >= today_start, Visit.visit_timestamp < today_end))
                )
                existing_visits = (await db.execute(stmt_existing)).scalars().all()
                existing_visits_map = {v.shop_id: v for v in existing_visits}
                visited_shop_ids = set(existing_visits_map.keys())
                
                stmt_pending_shortages = select(ShortageRequest.shop_id).filter(ShortageRequest.shop_id.in_(shop_ids), ShortageRequest.status == 'pending')
                shortage_shop_ids = set((await db.execute(stmt_pending_shortages)).scalars().all())
                
                for shop in shops_in_zone:
                    is_emerg = shop.id in shortage_shop_ids
                    if shop.id not in visited_shop_ids:
                        db.add(Visit(
                            driver_id=route.driver_id, 
                            shop_id=shop.id, 
                            status='Pending', 
                            sequence=shop.sequence,
                            is_emergency=is_emerg,
                            work_session_id=new_active_sess.id if new_active_sess else None # +++ سحق أشباح الشاشة للزيارات الجديدة +++
                        ))
                    else:
                        visit_to_update = existing_visits_map.get(shop.id)
                        if visit_to_update and is_emerg:
                             visit_to_update.is_emergency = True
 
        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast({"event": "ROUTE_STATUS_UPDATED", "message": "تم تحديث حالة خط السير"}))
        return {"message": "تم تحديث خط السير بنجاح"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء تحديث خط السير.")


# =========================================
# 16. تراجع عن إنهاء العمل (Admin Override - Split Brain Protection)
# =========================================
@router.put("/dispatch/session/{session_id}/undo_end_work", status_code=200)
async def undo_end_work(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
        # +++ قفل التزامن الفولاذي: قفل الجلسة لمنع أي مشرفين من التعديل عليها بنفس اللحظة +++
    stmt_session = select(WorkSession).with_for_update().filter_by(id=session_id)
    session = (await db.execute(stmt_session)).scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="الجلسة غير موجودة.")

    if session.is_settled:
        raise HTTPException(status_code=400, detail="لا يمكن التراجع، تم اعتماد التسوية لهذه الجلسة مسبقاً.")
        
    if not session.end_time:
         raise HTTPException(status_code=400, detail="الجلسة نشطة بالفعل.")

    # ========================================================
    # 1. قفل الدماغ المنقسم (Split-Brain Shield)
    # ========================================================
    # أ. هل بدأ  מندوب جلسة جديدة؟
    stmt_active_now = select(WorkSession).filter(
        WorkSession.driver_id == session.driver_id, 
        WorkSession.end_time.is_(None)
    )
    if (await db.execute(stmt_active_now)).first():
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض: المندوب لديه جلسة عمل نشطة حالياً. يجب إغلاقها قبل التراجع.")

    # ب. هل تم تعيين خط سير جديد للمندوب؟
    stmt_route_now = select(DispatchRoute).filter(
        DispatchRoute.driver_id == session.driver_id, 
        DispatchRoute.status == 'active',
        # +++ الدرع الفولاذي (NULL Safe): استخدام is_distinct_from لمنع تجاهل خطوط السير الجديدة +++
        DispatchRoute.work_session_id.is_distinct_from(session.id) 
    )
    if (await db.execute(stmt_route_now)).first():
        await db.rollback()
        raise HTTPException(status_code=400, detail="مرفوض: المندوب لديه خط سير جديد نشط حالياً. يجب إغلاقه قبل التراجع.")

    # ========================================================
    # 2. حماية الـ Audit Trail (حد أقصى للتراجع)
    # ========================================================
    stmt_undo_count = select(func.count(SystemAuditLog.id)).filter(
        SystemAuditLog.target_id == str(session.id), 
        SystemAuditLog.action_type == 'UNDO_END_WORK'
    )
    undo_count = (await db.execute(stmt_undo_count)).scalar() or 0
    
    if undo_count >= 3:
        await db.rollback()
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: تم استنفاد الحد الأقصى (3 مرات) لإعادة فتح هذه الجلسة. لا يمكن التراجع عن الإنهاء مجدداً.")

    try:
        # ========================================================
        # 3. التنفيذ الجراحي (Undo Action)
        # ========================================================
        old_end_time = session.end_time.isoformat()
        
        # أ. إعادة إحياء الجلسة
        session.end_time = None
        
        # ب. إعادة إحياء خط السير (الدرع الفولاذي) - مع القفل لمنع تضارب التبديل
        stmt_route = select(DispatchRoute).with_for_update().filter_by(work_session_id=session.id)
        route = (await db.execute(stmt_route)).scalar_one_or_none()
        
        if route:
            # إذا كان الخط لا يزال بعهدة المندوب، نعيد تفعيله
            if route.driver_id == session.driver_id:
                route.status = 'active'
            else:
                # إذا تم سحب الخط منه أثناء الإغلاق، نفك الارتباط المكسور
                route.work_session_id = None
                
        # ج. توثيق الحركة الحساسة
        audit_log = SystemAuditLog(
            admin_id=current_admin.id,
            target_id=str(session.id),
            action_type='UNDO_END_WORK',
            old_value=f"end_time: {old_end_time}",
            new_value="end_time: NULL (Session Reopened)"
        )
        db.add(audit_log)
        
        await db.commit()
        return {"message": "تم التراجع عن إنهاء العمل بنجاح. يمكن للمندوب متابعة عمله الآن."}

    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء التراجع عن إنهاء العمل.")


# =========================================
# 17. إدارة المناطق (إضافة منطقة جديدة)
# =========================================
@router.post("/dispatch/zones", status_code=201)
async def add_zone(
    payload: AddZoneRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="اسم المنطقة مطلوب")

    # الفحص الصارم لوجود المنطقة (نشطة أو مؤرشفة)
    stmt_existing = select(Zone).filter_by(name=name)
    existing_zone = (await db.execute(stmt_existing)).scalars().first()
    
    if existing_zone:
        if not getattr(existing_zone, 'is_active', True):
            raise HTTPException(status_code=409, detail="هذه المنطقة موجودة مسبقاً في (أرشيف المناطق). يرجى استعادتها بدلاً من إنشائها من جديد.")
        raise HTTPException(status_code=409, detail="المنطقة موجودة ونشطة مسبقاً")

    try:
        # +++ المعالجة الذكية لحقل المحافظة الإجباري (Auto-Provisioning) O(1) +++
        stmt_gov = select(Governorate).limit(1)
        gov = (await db.execute(stmt_gov)).scalars().first()
        
        if not gov:
            stmt_country = select(Country).limit(1)
            country = (await db.execute(stmt_country)).scalars().first()
            if not country:
                country = Country(name="الأردن")
                db.add(country)
                await db.flush() # +++ توليد الـ ID للبلد +++
                
            gov = Governorate(name="العاصمة", country_id=country.id)
            db.add(gov)
            await db.flush() # +++ توليد الـ ID للمحافظة +++

        new_zone = Zone(name=name, governorate_id=gov.id)
        db.add(new_zone)
        await db.flush() # +++ استخراج الـ ID للمنطقة بأمان قبل الـ Commit +++
        zone_id = new_zone.id
        
        await db.commit()
        return {"message": "تم إضافة المنطقة بنجاح", "zone_id": str(zone_id)}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء إضافة المنطقة.")


# =========================================
# 18. أرشفة المنطقة (مع حماية  ـ Rug-Pull ونسف الـ N+1)
# =========================================
@router.delete("/dispatch/zones/{zone_id}", status_code=200)
async def archive_zone(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    zone = await db.get(Zone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="المنطقة غير موجودة")

    # +++ الدرع المعماري (Rug-Pull Shield): منع سحب منطقة يعمل بها مندوب بالشارع +++
    stmt_active_routes = select(func.count(DispatchRoute.id)).filter(
        DispatchRoute.zone_id == zone_id, 
        DispatchRoute.status.in_(['active', 'waiting'])
    )
    active_routes_count = (await db.execute(stmt_active_routes)).scalar() or 0

    if active_routes_count > 0:
        raise HTTPException(status_code=400, detail=f"مرفوض: يوجد خط سير نشط أو قيد الانتظار يعمل في منطقة ({zone.name}). يجب إغلاق خط السير أولاً.")

    try:
        # +++ النسف المعماري لجريمة الـ N+1 (Cascade Archive O(1)) +++
        # تحديث آلاف المحلات بضربة واحدة في قاعدة البيانات بدون تحميلها في الذاكرة
        stmt_archive_shops = update(Shop).where(Shop.zone_id == zone_id).values(is_archived=True)
        await db.execute(stmt_archive_shops)
        
        # +++ الدرع المحاسبي الإضافي (الذي نسيته في الفلاسك): إلغاء أي زيارات معلقة لهذه المحلات المؤرشفة +++
        stmt_shop_ids = select(Shop.id).filter_by(zone_id=zone_id).scalar_subquery()
        stmt_cancel_visits = update(Visit).where(
            Visit.shop_id.in_(stmt_shop_ids), 
            Visit.status == 'Pending'
        ).values(status='Cancelled')
        await db.execute(stmt_cancel_visits)

        # أرشفة المنطقة نفسها
        zone.is_active = False
        
        await db.commit()
        return {"message": f"تم أرشفة المنطقة ({zone.name}) وجميع المحلات التابعة لها بنجاح"}

    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء أرشفة المنطقة.")


# =========================================
# 19. تعديل بيانات المنطقة (جدولة، اسم، أيام)
# =========================================
@router.put("/dispatch/zones/{zone_id}", status_code=200)
async def update_zone(
    zone_id: int,
    payload: UpdateZoneRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # +++ قفل التزامن (Row-Level Lock) لمنع التضارب أثناء التعديل +++
    stmt_zone = select(Zone).with_for_update().filter_by(id=zone_id)
    zone = (await db.execute(stmt_zone)).scalar_one_or_none()
    
    if not zone:
        raise HTTPException(status_code=404, detail="المنطقة غير موجودة")

    new_name = payload.name.strip() if payload.name else None

    try:
        if new_name:
            stmt_exist = select(Zone).filter(Zone.name == new_name, Zone.id != zone_id)
            if (await db.execute(stmt_exist)).first():
                raise HTTPException(status_code=409, detail="يوجد منطقة أخرى بنفس الاسم")
            zone.name = new_name
            
        if payload.frequency:
            zone.schedule_frequency = payload.frequency
        if payload.visitDay:
            zone.visit_day = payload.visitDay
        if payload.startDate:
            # +++ Pydantic تكفل بتحويل التاريخ وحمايتنا من قنابل  ـ strptime +++
            zone.start_date = payload.startDate 
            
        await db.commit()
        return {"message": "تم التعديل بنجاح"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء تعديل المنطقة.")


# =========================================
# 20. جلب المناطق المؤرشفة
# =========================================
@router.get("/dispatch/zones/archived", response_model=List[ArchivedZoneResponse], status_code=200)
async def get_archived_zones(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # جلب المناطق الميتة فقط بـ O(1)
    stmt = select(Zone).filter_by(is_active=False)
    zones = (await db.execute(stmt)).scalars().all()
    
    return [{"id": str(z.id), "name": z.name} for z in zones]


# =========================================
# 21. استعادة المنطقة المؤرشفة
# =========================================
@router.put("/dispatch/zones/{zone_id}/restore", status_code=200)
async def restore_zone(
    zone_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    zone = await db.get(Zone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="المنطقة غير موجودة")

    # +++ درع إضافي: التحقق لكي لا نرهق الداتابيز بعملية Commit وهمية إذا كانت المنطقة نشطة أصلاً +++
    if getattr(zone, 'is_active', False):
        return {"message": "المنطقة نشطة بالفعل"}

    try:
        zone.is_active = True
        await db.commit()
        return {"message": "تم استعادة المنطقة بنجاح"}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء استعادة المنطقة.")


# =========================================
# 22. تعديل بيانات محل موجود (الرصيد الحي، السقف، المنطقة)
# =========================================
@router.put("/dispatch/shops/{shop_id}", status_code=200)
async def edit_shop_details(
    shop_id: str,
    payload: EditShopDetailsRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
        
    # 1. تنظيف المعرف القادم من React وحمايته من  ـ 500 Crash
    clean_id_str = str(shop_id).replace('s', '')
    if not clean_id_str.isdigit():
        raise HTTPException(status_code=400, detail="معرف المحل غير صالح.")
    clean_id = int(clean_id_str)

    # 2. الدرع المحاسبي: قفل المحل لمنع مسح مبيعات المندوب التي تحدث في نفس اللحظة (Row-Level Lock)
    stmt_shop = select(Shop).with_for_update().filter_by(id=clean_id)
    shop = (await db.execute(stmt_shop)).scalar_one_or_none()
    
    if not shop:
        raise HTTPException(status_code=404, detail="المحل غير موجود")
        
    new_phone = payload.phone.strip() if payload.phone else ""
    
    # 3. فحص تكرار رقم الهاتف لمحل آخر لمنع التضارب
    if new_phone and new_phone != shop.phone_number:
        stmt_dup_phone = select(Shop).filter_by(phone_number=new_phone)
        if (await db.execute(stmt_dup_phone)).first():
            await db.rollback()
            raise HTTPException(status_code=409, detail="رقم الهاتف مستخدم لمحل آخر")
            
    try:
        # 4. التحديث الجراحي للبيانات الأساسية (نحتفظ بالقديم إذا لم يتم إرسال جديد)
        if payload.name is not None:
            shop.name = payload.name
        if payload.owner is not None:
            shop.contact_person = payload.owner
            
        # حماية الهاتف من المسح العشوائي
        shop.phone_number = new_phone if new_phone else shop.phone_number
        
        if payload.mapLink is not None:
            shop.location_link = payload.mapLink
            
        if payload.zoneId is not None:
            zone_str = str(payload.zoneId).strip()
            if zone_str.isdigit():
                shop.zone_id = int(zone_str)
        
        # 5. الكي الجراحي: تحديث الأموال بـ Decimal نقي ومحمي من الفراغات (ونسف لغم الـ Falsy Zero)
        val_limit = payload.maxDebtLimit if payload.maxDebtLimit is not None else payload.max_debt_limit
        if val_limit is not None:
            raw_limit = str(val_limit).strip()
            if raw_limit:  # "0" أو "0.0" كنص تعتبر True في بايثون، فستمر بنجاح!
                try:
                    shop.max_debt_limit = Decimal(raw_limit)
                except Exception:
                    pass 
                
        val_debt = payload.initialDebt if payload.initialDebt is not None else payload.initial_debt
        if val_debt is not None:
            raw_debt = str(val_debt).strip()
            if raw_debt:
                try:
                    shop.current_balance = Decimal(raw_debt)
                except Exception:
                    pass
        
        await db.commit()
        return {"message": "تم التعديل بنجاح"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء تعديل المحل.")


# =========================================
# 23. جلب الطلبات العاجلة (شاشة النواقص) - GET
# =========================================
@router.get("/dispatch/shortages", response_model=List[ShortageResponseItem], status_code=200)
async def get_shortages(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # +++ التدمير الحقيقي لـ N+1 (O(1) Fetch) مع الدرع المفقود +++
    stmt = select(ShortageRequest).options(
        joinedload(ShortageRequest.zone),
        joinedload(ShortageRequest.shop),
        joinedload(ShortageRequest.driver),
        joinedload(ShortageRequest.product_variant)
    ).filter_by(status='pending').order_by(ShortageRequest.created_at.asc())
    
    shortages = (await db.execute(stmt)).scalars().all()
    
    result = [{
        "id": str(s.id),
        "zoneId": str(s.zone_id) if s.zone_id else "",
        "zoneName": s.zone.name if s.zone else "",
        "shopId": str(s.shop_id) if s.shop_id else "",
        "shopName": s.shop.name if s.shop else "",
        "driverId": str(s.driver_id) if s.driver_id else "",
        "driverName": s.driver.full_name if s.driver else "",
        "productName": s.product_variant.variant_name if s.product_variant else "غير معروف",
        "quantity": s.quantity,
        "status": s.status,
        "waitTime": s.wait_time,
        # +++ نسف لغم الـ Timezone الأخير في السيستم: توحيد توقيت الطوارئ مع جرينتش لمنع كراش الموبايل +++
        "createdAt": s.created_at.replace(tzinfo=timezone.utc).isoformat() if s.created_at else None
    } for s in shortages]
    
    return result


# =========================================
# 24. إضافة طلبات عاجلة (تبني ودمج الزيارات) - POST
# =========================================
@router.post("/dispatch/shortages", status_code=201)
async def add_shortages(
    payload: List[CreateShortageItem],
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    if not payload:
        raise HTTPException(status_code=400, detail="لا توجد بيانات لإضافتها.")

    try:
        # +++ 1. تحضير الذاكرة (Memory Maps) لنسف  ـ N+1 +++
        shop_ids = list({int(str(item.shopId).strip()) for item in payload if str(item.shopId).strip().isdigit()})
        
        stmt_shops = select(Shop).filter(Shop.id.in_(shop_ids))
        bulk_shops = {sh.id: sh for sh in (await db.execute(stmt_shops)).scalars().all()}
        
        # +++ النسف المعماري الحقيقي: منع كراش Offset-Naive +++
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # جلب زيارات اليوم (المعلقة أو المكتملة) لوسمها بالطوارئ
        # +++ قفل الزيارة لمنع المندوب من إنهائها أثناء وسمها بالطوارئ +++
        stmt_visits = select(Visit).with_for_update().filter(
            Visit.shop_id.in_(shop_ids),
            or_(
                Visit.status == 'Pending',
                and_(Visit.visit_timestamp >= today_start, Visit.visit_timestamp < today_end)
            )
        ).order_by(Visit.id.asc())
        recent_visits = (await db.execute(stmt_visits)).scalars().all()
        bulk_visits = {v.shop_id: v for v in recent_visits} 
        
        # حماية الطلبات العاجلة المتعددة (جلب الطلبات القديمة)
        stmt_existing_reqs = select(ShortageRequest).options(joinedload(ShortageRequest.shop)).filter(
            ShortageRequest.shop_id.in_(shop_ids), 
            ShortageRequest.status == 'pending'
        )
        existing_requests_map = {req.shop_id: req for req in (await db.execute(stmt_existing_reqs)).scalars().all()}

        # +++ سحق اصطدام الأسماء: الاعتماد على الـ ID أولاً، ثم الاسم كخيار بديل +++
        product_ids = list({int(str(item.productId).strip()) for item in payload if str(item.productId).strip().isdigit()})
        product_names = list({str(item.productName).strip() for item in payload if item.productName and not str(item.productId).strip().isdigit()})
        
        stmt_vars = select(ProductVariant).filter(or_(ProductVariant.id.in_(product_ids), ProductVariant.variant_name.in_(product_names)))
        fetched_variants = (await db.execute(stmt_vars)).scalars().all()
        bulk_variants_map_id = {v.id: v for v in fetched_variants}
        bulk_variants_map_name = {v.variant_name: v for v in fetched_variants}

        # درع لمنع إرسال نفس المنتج مرتين بالخطأ في نفس الـ Payload
        payload_tracker = set()

        # +++ 2. المعالجة الجراحية +++
        for item in payload:
            shop_id_str = str(item.shopId).strip()
            if not shop_id_str.isdigit(): continue
            shop_id = int(shop_id_str)
            
            # الرفض إذا كان هناك طلب قديم معلق لهذا المحل
            if shop_id in existing_requests_map:
                req = existing_requests_map[shop_id]
                shop_name = req.shop.name if req.shop else str(shop_id)
                await db.rollback()
                raise HTTPException(status_code=409, detail=f"مرفوض: يوجد طلب عاجل قيد الانتظار للمحل ({shop_name}). يرجى تعديله أو حذفه أولاً.")

            prod_id_str = str(item.productId).strip()
            prod_name = str(item.productName).strip()
            variant = None
            
            if prod_id_str.isdigit(): variant = bulk_variants_map_id.get(int(prod_id_str))
            if not variant and prod_name: variant = bulk_variants_map_name.get(prod_name)
            
            if not variant:
                await db.rollback()
                raise HTTPException(status_code=404, detail=f"المنتج '{prod_name or prod_id_str}' غير موجود في النظام.")
                
            tracker_key = f"{shop_id}_{variant.id}"
            if tracker_key in payload_tracker: continue 
            payload_tracker.add(tracker_key)

            zone_id_str = str(item.zoneId).strip()
            if not zone_id_str.isdigit():
                await db.rollback()
                raise HTTPException(status_code=400, detail="مرفوض: المنطقة إجبارية للطلب العاجل.")
            zone_id = int(zone_id_str)

            driver_id_str = str(item.driverId).strip() if item.driverId else ""
            driver_id = int(driver_id_str) if driver_id_str.isdigit() else None

            # أ. إنشاء الطلب
            new_shortage = ShortageRequest(
                zone_id=zone_id,
                shop_id=shop_id,
                driver_id=driver_id,
                product_variant_id=variant.id, 
                quantity=item.quantity or 1
            )
            db.add(new_shortage)
            
            # ب. دمج الزيارة والتفويض (التبني) - (معمارية حماية الأموال المكتملة)
            if driver_id:
                existing_visit = bulk_visits.get(shop_id)
                if existing_visit:
                    if existing_visit.driver_id == driver_id:
                        # نفس المندوب: نكتفي بختم الطوارئ
                        existing_visit.is_emergency = True
                        # +++ درع الزومبي: إحياء الزيارة إذا كان المندوب قد ألغاها صباحاً +++
                        if existing_visit.status == 'Cancelled':
                            existing_visit.status = 'Pending'
                    else:
                        # مندوب مختلف: هنا الخطر!
                        if existing_visit.status == 'Completed':
                            # +++ درع الفساد المالي: يمنع سرقة زيارة مكتملة، بل ننشئ زيارة جديدة للمندوب الجديد +++
                            shop_record = bulk_shops.get(shop_id)
                            new_visit = Visit(
                                driver_id=driver_id,
                                shop_id=shop_id,
                                status='Pending',
                                sequence=shop_record.sequence if shop_record else 999,
                                is_emergency=True
                            )
                            db.add(new_visit)
                            # نحدث الذاكرة لتشير للزيارة الجديدة في حال تكرر المحل في نفس الطلب
                            bulk_visits[shop_id] = new_visit
                        else:
                            # الزيارة معلقة (Pending) أو ملغاة (Cancelled): يمكن نقلها بأمان
                            existing_visit.is_emergency = True
                            existing_visit.driver_id = driver_id
                            existing_visit.work_session_id = None
                            existing_visit.status = 'Pending' # +++ إحياء الزيارة للمندوب الجديد +++
                else:
                    shop_record = bulk_shops.get(shop_id)
                    new_visit = Visit(
                        driver_id=driver_id,
                        shop_id=shop_id,
                        status='Pending',
                        sequence=shop_record.sequence if shop_record else 999,
                        is_emergency=True
                    )
                    db.add(new_visit)
                    bulk_visits[shop_id] = new_visit 
                    
        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast({"event": "SHORTAGE_ADDED", "message": "تم إضافة نواقص جديدة"}))
        return {"message": "تم تسجيل الطلبات بنجاح"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء حفظ الطلبات.")


# =========================================
# 25. حذف الطلب العاجل (وعملية تنظيف الأشباح) - DELETE
# =========================================
@router.delete("/dispatch/shortages/{shortage_id}", status_code=200)
async def delete_shortage(
    shortage_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    shortage = await db.get(ShortageRequest, shortage_id)
    if not shortage:
        return {"message": "الطلب غير موجود أصلاً."}

    try:
        shop_id = shortage.shop_id
        await db.delete(shortage)
        await db.flush() # +++ تحديث الذاكرة فوراً قبل فحص المتبقي +++
        
        # +++ التزامن المعماري: سحب ختم (عاجل) إذا لم يتبقَ أي طلبات أخرى +++
        stmt_rem = select(func.count(ShortageRequest.id)).filter_by(shop_id=shop_id, status='pending')
        remaining = (await db.execute(stmt_rem)).scalar() or 0
        
        if remaining == 0:
            stmt_visit = select(Visit).filter_by(shop_id=shop_id, status='Pending').limit(1)
            target_visit = (await db.execute(stmt_visit)).scalars().first()
            
            if target_visit:
                target_visit.is_emergency = False
                
                # +++ نسف الشبح: إذا كان المحل خارج منطقة المندوب (أضيف للطوارئ فقط)، نسحبه منه لكي لا يعلق الشبح في تطبيقه +++
                if target_visit.driver_id:
                    stmt_route = select(DispatchRoute).filter_by(driver_id=target_visit.driver_id, status='active').limit(1)
                    route = (await db.execute(stmt_route)).scalars().first()
                    shop = await db.get(Shop, shop_id)
                    
                    if route and shop and shop.zone_id != route.zone_id:
                        target_visit.driver_id = None
                        target_visit.work_session_id = None
        
        await db.commit()
        asyncio.create_task(dispatch_manager.broadcast({"event": "SHORTAGE_DELETED", "message": "تم معالجة نواقص"}))
        return {"message": "تم حذف الطلب وتنظيف الميدان بنجاح"}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء حذف الطلب.")


# =========================================
# 26. الاستيراد الآمن للمحلات بالجملة (Bulk Import O(1) & Memory Safe)
# =========================================
@router.post("/dispatch/shops/bulk_import", status_code=201)
async def bulk_import_shops(
    payload: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    zone_id = payload.zoneId
    shops_list = payload.shops
    file_name = payload.fileName

    if not zone_id or not shops_list:
        raise HTTPException(status_code=400, detail="المنطقة وقائمة المحلات مطلوبة")

    log_id = None
    try:
        # ========================================================
        # 1. توثيق العملية مبدئياً وحجز ID للـ Log
        # ========================================================
        import_log = ImportLog(
            admin_id=current_admin.id, 
            zone_id=zone_id, 
            file_name=file_name, 
            total_records=len(shops_list), 
            status='Processing'
        )
        db.add(import_log)
        await db.flush() # +++ الدرع الفولاذي: سحب الـ ID من الداتابيز قبل إغلاق الجلسة لمنع الانفجار +++
        log_id = import_log.id
        await db.commit()

        # ========================================================
        # 2. تحضير القوائم الفريدة (Sets) للسرعة
        # ========================================================
        incoming_names = list({s.name.strip().lower() for s in shops_list if s.name and s.name.strip()})
        # +++ درع الإكسيل: إزالة الـ .0 من الهواتف قبل بناء فهارس البحث +++
        incoming_phones = list({(str(s.phone).strip()[:-2] if str(s.phone).strip().endswith('.0') else str(s.phone).strip()) for s in shops_list if s.phone and str(s.phone).strip()})
        incoming_links = list({s.mapLink.strip().lower() for s in shops_list if s.mapLink and s.mapLink.strip()})

        all_existing_shops_raw = []
        CHUNK_SIZE = 500 # التوازن المثالي لمنع انفجار الـ RAM و Timeout الداتابيز

        # ========================================================
        # 3. هندسة الطلب الموحد (Chunked Bulk Fetch O(1))
        # ========================================================
        max_len = max(len(incoming_names), len(incoming_phones), len(incoming_links))
        for i in range(0, max_len, CHUNK_SIZE):
            name_chunk = incoming_names[i:i + CHUNK_SIZE]
            phone_chunk = incoming_phones[i:i + CHUNK_SIZE]
            link_chunk = incoming_links[i:i + CHUNK_SIZE]

            filters = []
            if name_chunk: filters.append(func.lower(Shop.name).in_(name_chunk))
            if phone_chunk: filters.append(Shop.phone_number.in_(phone_chunk))
            if link_chunk: filters.append(func.lower(Shop.location_link).in_(link_chunk))

            if filters:
                # جلب الحقول المطلوبة فقط (Tuples) لنسف الـ Memory Bloat
                stmt = select(Shop.id, Shop.name, Shop.phone_number, Shop.location_link).filter(
                    Shop.is_archived == False, 
                    or_(*filters)
                )
                results = (await db.execute(stmt)).all()
                all_existing_shops_raw.extend(results)

        # إزالة التكرار من النتائج
        all_existing_shops = list({res[0]: res for res in all_existing_shops_raw}.values())

        # ========================================================
        # 4. بناء الـ Hash Maps للمقارنة الفورية O(1)
        # ========================================================
        name_idx, phone_idx, link_idx = {}, {}, {}
        for ext_id, ext_name, ext_phone, ext_link in all_existing_shops:
            n = (ext_name or '').strip().lower()
            p = str(ext_phone or '').strip()
            l = (ext_link or '').strip().lower()
            if n: name_idx.setdefault(n, []).append(ext_id)
            if p: phone_idx.setdefault(p, []).append(ext_id)
            if l: link_idx.setdefault(l, []).append(ext_id)

        new_shops = []
        ignored_count = 0

        # ========================================================
        # 5. المعالجة النهائية والحماية من التكرار الداخلي (Intra-Excel)
        # ========================================================
        for s in shops_list:
            s_name = (s.name or '').strip().lower()
            s_phone = str(s.phone or '').strip()
            if s_phone.endswith('.0'): s_phone = s_phone[:-2] # +++ تنظيف الهاتف قبل الإدخال +++
            s_link = (s.mapLink or '').strip().lower()

            candidate_ids = []
            if s_name in name_idx: candidate_ids.extend(name_idx[s_name])
            if s_phone in phone_idx: candidate_ids.extend(phone_idx[s_phone])
            if s_link in link_idx: candidate_ids.extend(link_idx[s_link])
            
            # درع منع التكرار القاطع
            is_phone_duplicate = bool(s_phone and s_phone in phone_idx)
            is_duplicate = is_phone_duplicate or any(count >= 2 for count in Counter(candidate_ids).values())
            
            if is_duplicate:
                ignored_count += 1
                continue

            # +++ حماية  ـ Decimal من انهيار البيانات (Empty Strings or Chars) +++
            try:
                raw_debt = str(s.initialDebt or '0.0').strip()
                safe_debt = Decimal(raw_debt) if raw_debt else Decimal('0.0')
            except Exception:
                safe_debt = Decimal('0.0')

            try:
                raw_seq = str(s.sequence or '999').strip()
                # +++ هندسة البايثون: تحويل النص لـ float لامتصاص (1.0) ثم لـ int لجعله رقماً صحيحاً (1) +++
                safe_seq = int(float(raw_seq)) 
            except Exception:
                safe_seq = 999

            new_shop = Shop(
                name=(s.name or '').strip(),
                contact_person=(s.owner or '').strip(),
                phone_number=s_phone,
                location_link=(s.mapLink or '').strip(),
                zone_id=zone_id,
                current_balance=max(Decimal('0.0'), safe_debt),
                added_by_driver_id=current_admin.id,
                sequence=safe_seq
            )
            new_shops.append(new_shop)
            
            # +++ تحديث الذاكرة فوراً لمنع التكرار داخل الإكسيل نفسه (Self-Healing) +++
            temp_id = f"temp_{len(new_shops)}"
            if s_name: name_idx.setdefault(s_name, []).append(temp_id)
            if s_phone: phone_idx.setdefault(s_phone, []).append(temp_id)
            if s_link: link_idx.setdefault(s_link, []).append(temp_id)

        # إضافة كل المحلات دفعة واحدة للـ DB
        db.add_all(new_shops)
        
        # جلب الـ Log لتحديثه
        stmt_log = select(ImportLog).filter_by(id=log_id)
        current_log = (await db.execute(stmt_log)).scalar_one_or_none()
        if current_log:
            current_log.success_count = len(new_shops)
            current_log.status = 'Success'
            
        await db.commit()
        
        return {"message": f"تم رفع {len(new_shops)} محل بنجاح، وتجاهل {ignored_count} مكرر."}

    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        
        # +++ المعالجة الانفصالية للطوارئ: تحديث حالة الـ Log بمعاملة جديدة +++
        if log_id:
            try:
                stmt_fail = update(ImportLog).where(ImportLog.id == log_id).values(status='Failed')
                await db.execute(stmt_fail)
                await db.commit()
            except Exception:
                await db.rollback()

        raise HTTPException(status_code=500, detail="فشل في رفع البيانات، تم إلغاء العملية بالكامل لحماية قاعدة البيانات.")
