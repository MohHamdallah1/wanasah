from datetime import timezone, date, datetime
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, func as sa_func
from typing import Optional, List
from database import get_db
from api.dependencies import get_current_driver, get_current_admin
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
import bcrypt 
import logging
logger = logging.getLogger("wanasah_logger")
import uuid
from services import check_inventory_lock as _check_inventory_lock  # +++ توحيد الحارس: نسخة واحدة في المشروع (المرجع المركزي في services) +++
from models import (Driver, Product, MainWarehouse, WarehouseLedger, ProductVariant, SystemSetting,
DamagedItemLog, VehicleLoad, SessionInventory, WorkSession, InventoryTransfer, DispatchRoute, Vehicle, SystemAuditLog,
InventoryLocation, InventoryBalance, InventoryMovement, ProductBatch, InventoryTransferHeader, InventoryTransferLine, OverrideReason, StocktakeSession, StocktakeLine, InventoryLock,
Role, Permission, UserRole, role_permissions)

from schemas import (UnifiedStocktakeStartRequest, WarehouseStocktakeRequest, ToggleLockRequest, WarehouseAlertItem,
WarehouseInventoryItem, WarehouseLedgerItem, WarehouseStatusResponse, SimpleProductVariantItem,
AddProductVariantRequest, AdjustWarehouseEntryRequest, UpgradedInboundRequest, UnifiedDispatchRequest, UnifiedReceiveRequest, UnifiedStocktakeStartRequest, UnifiedStocktakeCountRequest )

router = APIRouter()

# =================================================================================
# دوال مساعدة للمستودع (Helper Functions)
# =================================================================================
async def check_warehouse_lock(db: AsyncSession, company_id: int) -> bool:
    """
    درع العزل المعماري: التحقق من القفل حصراً للشركة الحالية.
    تم سحق ثغرة الشلل العام (Global Lock) التي كانت تعطل كل الشركات إذا قامت شركة واحدة بالجرد.
    """
    stmt = select(SystemSetting).filter_by(company_id=company_id, setting_key='warehouse_status')
    lock_setting = (await db.execute(stmt)).scalar_one_or_none()
    if lock_setting and lock_setting.setting_value == 'AUDIT_LOCK':
        return True
    return False

@router.get("/warehouse/locations", status_code=200)
async def get_warehouse_locations(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """جلب قائمة المستودعات المركزية الفعالة للشركة، مع التوليد التلقائي (Auto-Provisioning) للشركات الجديدة"""
    stmt = select(InventoryLocation.id, InventoryLocation.name, InventoryLocation.code).filter_by(
        company_id=current_admin.company_id, location_type='WAREHOUSE', is_active=True
    ).order_by(InventoryLocation.id.asc())
    
    locations = (await db.execute(stmt)).all()
    
    # +++ الدرع المعماري (Infrastructure Blocker Fixed): التوليد الآلي للمستودع الأول للشركات الجديدة +++
    if not locations:
        new_loc = InventoryLocation(
            company_id=current_admin.company_id, 
            name="المستودع الرئيسي", 
            code="WH-MAIN", 
            location_type='WAREHOUSE',
            is_active=True
        )
        db.add(new_loc)
        await db.commit()
        return [{"id": new_loc.id, "name": new_loc.name, "code": new_loc.code}]
        
    return [{"id": loc.id, "name": loc.name, "code": loc.code} for loc in locations]

# =================================================================================
# 1. استلام بضاعة من المورد (Inbound) - البنك المركزي
# =================================================================================
@router.post("/warehouse/inbound", status_code=201)
async def warehouse_inbound(
    payload: UpgradedInboundRequest, 
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    # +++ تمرير الـ company_id الإلزامي لدرع القفل +++
    if await check_warehouse_lock(db, current_admin.company_id):
        raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً بسبب عملية جرد.")

    if not payload.items:
        raise HTTPException(status_code=400, detail="يجب إرسال أصناف للاستلام.")

    reference_id = payload.reference_id
    if not reference_id or not reference_id.strip() or reference_id == "بدون فاتورة":
        reference_id = f"AUTO-INB-{uuid.uuid4().hex[:10].upper()}"
    else:
        reference_id = reference_id.strip()

    if not reference_id.startswith("AUTO-INB-"):
        normalized_ref = reference_id.strip().lower()
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(normalized_ref))))
        stmt_ref = select(WarehouseLedger.id).filter(
            WarehouseLedger.transaction_type.in_(['INBOUND_SUPPLIER', 'INBOUND_CORRECTION']), 
            func.lower(func.trim(WarehouseLedger.reference_id)) == normalized_ref
        )
        if (await db.execute(stmt_ref)).first():
            raise HTTPException(status_code=409, detail=f"مرفوض: رقم الفاتورة '{reference_id}' مسجل مسبقاً.")

    try:
        # +++ الاعتماد على المستودع المختار من الداشبورد +++
        stmt_loc = select(InventoryLocation).filter_by(
            id=payload.location_id, company_id=current_admin.company_id, location_type='WAREHOUSE'
        )
        main_loc = (await db.execute(stmt_loc)).scalar_one_or_none()
        if not main_loc:
            await db.rollback()
            raise HTTPException(status_code=404, detail="المستودع المختار غير موجود أو لا ينتمي لشركتك.")

        aggregated_items = {}
        for item in payload.items:
            if item.quantity_packs <= 0: continue
            
            # +++ الدرع الرياضي: المحرك الموحد يرفض البضاعة بلا دفعة أو منتهية الصلاحية +++
            if not item.batch_number or not item.expiry_date:
                raise HTTPException(status_code=422, detail="مرفوض: النظام الموحد يفرض إدخال رقم الدفعة وتاريخ الصلاحية.")
            if item.expiry_date < date.today():
                raise HTTPException(status_code=422, detail=f"مرفوض: لا يمكن استلام بضاعة منتهية الصلاحية (الدفعة: {item.batch_number}).")

            stmt_batch_ins = pg_insert(ProductBatch).values(
                company_id=current_admin.company_id,
                product_variant_id=item.product_variant_id,
                batch_number=item.batch_number,
                production_date=item.production_date,
                expiry_date=item.expiry_date,
                is_active=True
            ).on_conflict_do_nothing(
                index_elements=['company_id', 'product_variant_id', 'batch_number']
            )
            await db.execute(stmt_batch_ins)

            stmt_batch = select(ProductBatch.id).filter_by(
                company_id=current_admin.company_id,
                product_variant_id=item.product_variant_id,
                batch_number=item.batch_number
            )
            batch_id = (await db.execute(stmt_batch)).scalar_one()
            
            # التجميع يعتمد الآن على الصنف والدفعة معاً (Tuple)
            key = (item.product_variant_id, batch_id)
            aggregated_items[key] = aggregated_items.get(key, 0) + item.quantity_packs

        if not aggregated_items:
            return {"message": "لا توجد كميات صالحة للإدخال."}
            
        var_ids = list(set([k[0] for k in aggregated_items.keys()]))
        
        stmt_variants = select(ProductVariant.id).filter(
            ProductVariant.id.in_(var_ids),
            ProductVariant.company_id == current_admin.company_id
        )
        valid_var_ids = set((await db.execute(stmt_variants)).scalars().all())
        if not valid_var_ids:
            raise HTTPException(status_code=400, detail="مرفوض: جميع المنتجات غير صالحة.")

        stmt_wh = select(MainWarehouse).with_for_update().filter(MainWarehouse.product_variant_id.in_(list(valid_var_ids))).order_by(MainWarehouse.product_variant_id.asc())
        bulk_warehouse = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}

        for (p_id, b_id), added_packs in aggregated_items.items():
            if p_id not in valid_var_ids: continue

            wh_record = bulk_warehouse.get(p_id)
            if not wh_record:
                await db.rollback()
                raise HTTPException(status_code=400, detail=f"خطأ حرج: المنتج ليس له حساب مخزني في النظام القديم.")
                
            # +++ نشر الحارس: منع التوريد لرف مقفول (P0-1) +++
            await _check_inventory_lock(db, current_admin.company_id, main_loc.id, p_id, b_id)

            # 1. تحديث النظام القديم (لضمان عمل الـ Flutter والـ Dashboard)
            old_balance = wh_record.available_quantity_packs or 0
            wh_record.available_quantity_packs += added_packs
            db.add(WarehouseLedger(
                product_variant_id=p_id, transaction_type='INBOUND_SUPPLIER', quantity_packs=added_packs,
                balance_before_packs=old_balance, balance_after_packs=wh_record.available_quantity_packs,
                admin_id=current_admin.id, reference_id=reference_id, notes=payload.notes
            ))

            # 2. +++ الـ Dual-Write: الكتابة في المحرك الموحد (المرحلة 3 و 4) +++
            stmt_upsert = pg_insert(InventoryBalance).values(
                company_id=current_admin.company_id, location_id=main_loc.id,
                product_variant_id=p_id, batch_id=b_id, stock_status='AVAILABLE', 
                on_hand_quantity=added_packs, reserved_quantity=0 # +++ سحق الـ quantity الوهمي (P0-1) +++
            ).on_conflict_do_update(
                index_elements=['company_id', 'location_id', 'product_variant_id', 'batch_id', 'stock_status'],
                set_=dict(
                    on_hand_quantity=InventoryBalance.on_hand_quantity + added_packs
                )
            )
            await db.execute(stmt_upsert)

        await db.commit()
        return {"message": "تم إدخال البضاعة وتحديث الأرصدة (بالنظامين) بنجاح"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في استلام البضاعة: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء استلام البضاعة.")

# =================================================================================
# 2. جرد وتسوية المستودع (Stocktake & Audit) - البنك المركزي (مصفح ضد البضاعة الوهمية)
# =================================================================================
@router.post("/warehouse/stocktake", status_code=200)
async def warehouse_stocktake(
    payload: WarehouseStocktakeRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
        
    if not payload.items:
        raise HTTPException(status_code=400, detail="يجب إرسال أصناف للجرد.")

    try:
        # +++ 1. درع التجميع (Payload Aggregation): حماية السيرفر من تكرار الصنف في نفس الطلب +++
        aggregated_items = {}
        for item in payload.items:
            if item.actual_packs < 0: continue
            # الجرد هو (لقطة) للرف وليس حركة تراكمية. نعتمد القراءة الأخيرة لحماية الدفاتر من التضخم.
            aggregated_items[item.product_variant_id] = item.actual_packs

        var_ids = list(aggregated_items.keys())
        if not var_ids:
            return {"message": "لا توجد بيانات صالحة لمعالجتها."}

        # جلب المنتجات للتحقق منها واستخدام أسمائها في رسائل الخطأ
        stmt_variants = select(ProductVariant).filter(ProductVariant.id.in_(var_ids))
        variants_map = {v.id: v for v in (await db.execute(stmt_variants)).scalars().all()}
        valid_var_ids = set(variants_map.keys())

        # +++ 2. قفل التزامن الجراحي (Row-Level Lock) مع الترتيب الهرمي لنسف الـ Deadlock +++
        stmt_wh = select(MainWarehouse).with_for_update().filter(MainWarehouse.product_variant_id.in_(list(valid_var_ids))).order_by(MainWarehouse.product_variant_id.asc())
        bulk_warehouse = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}

        # +++ الدرع المستودعي: الفحص المسبق للبضاعة المحجوزة قبل الجرد لمنع خلق أرصدة وهمية +++
        blocked_items = []
        for p_id in valid_var_ids:
            wh_record = bulk_warehouse.get(p_id)
            if wh_record and (wh_record.reserved_quantity_packs or 0) > 0:
                blocked_items.append(variants_map[p_id].variant_name)
                
        if blocked_items:
            await db.rollback()
            blocked_str = "، ".join(blocked_items)
            raise HTTPException(
                status_code=400, 
                detail=f"مرفوض: لا يمكن جرد الأصناف التالية لوجود حوالات معلقة (بضاعة محجوزة) لها: [{blocked_str}]. الرجاء تصفية الحوالات المعلقة للمناديب أولاً."
            )

        for p_id, actual_packs in aggregated_items.items():
            if p_id not in valid_var_ids:
                continue 

            variant = variants_map[p_id]
            wh_record = bulk_warehouse.get(p_id)
            
            # +++ الدرع الرقابي: إيقاف الإنشاء الصامت لمنتجات ليس لها حساب مخزني لتوحيد المعيار مع Inbound +++
            if not wh_record:
                await db.rollback()
                raise HTTPException(
                    status_code=400, 
                    detail=f"خطأ حرج: المنتج [{variant.variant_name}] ليس له حساب مخزني في المستودع الرئيسي. المرجع: ERROR-400-NO-WH-RECORD."
                )

            # +++ 3.  للكارثة (العودة للواقع الميداني) +++
            # الجرد الملموس يُقارن بـ (المتاح) فقط. البضاعة المحجوزة موجودة في سيارات المناديب بالشارع وليست على الرف.
            expected_packs = wh_record.available_quantity_packs or 0 # +++   سحق الـ NoneType +++
            difference = actual_packs - expected_packs

            # +++   تسجيل حركة الجرد دائماً (حتى لو الفرق 0) لإثبات أن المشرف قام بالجرد الفعلي (Audit Trail) +++
            wh_record.available_quantity_packs = actual_packs
            
            db.add(WarehouseLedger(
                product_variant_id=p_id, 
                transaction_type='AUDIT_ADJUSTMENT',
                quantity_packs=difference, 
                balance_before_packs=expected_packs,
                balance_after_packs=actual_packs,
                admin_id=current_admin.id, 
                reference_id="STOCKTAKE_OP", 
                notes=f"الرصيد المتوقع بالرف: {expected_packs}، الفعلي المجرود: {actual_packs}. الفرق: {'+' if difference>0 else ''}{difference}. {payload.notes}"
            ))

        # +++ 4. فتح المستودع تلقائياً بعد إنهاء الجرد (P0 Fixed: استخدام company_id) +++
        insert_stmt = pg_insert(SystemSetting).values(
            company_id=current_admin.company_id,
            setting_key='warehouse_status', 
            setting_value='ACTIVE'
        ).on_conflict_do_update(
            index_elements=['company_id', 'setting_key'],
            set_=dict(setting_value='ACTIVE')
        )
        await db.execute(insert_stmt)

        await db.commit()
        return {"message": "تمت تسوية المستودع بنجاح، وتم فتح النظام للعمليات تلقائياً."}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء تسوية المستودع.")

# =================================================================================
# 3. قفل / فتح المستودع يدوياً
# =================================================================================
@router.put("/warehouse/lock", status_code=200)
async def toggle_warehouse_lock(
    payload: ToggleLockRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    new_status = payload.status
    if new_status not in ['AUDIT_LOCK', 'ACTIVE']:
        raise HTTPException(status_code=400, detail="حالة غير صالحة.")

    try:
        # +++ حقن company_id لتخصيص القفل وعزل الشركات +++
        insert_stmt = pg_insert(SystemSetting).values(
            company_id=current_admin.company_id,
            setting_key='warehouse_status', 
            setting_value=new_status
        ).on_conflict_do_update(
            index_elements=['company_id', 'setting_key'], # الاعتماد على القيد المركب الجديد
            set_=dict(setting_value=new_status)
        )
        await db.execute(insert_stmt)
        await db.commit()
        msg = "تم إقفال المستودع لغايات الجرد. جميع عمليات التحميل معلقة." if new_status == 'AUDIT_LOCK' else "تم فتح المستودع للعمليات."
        return {"message": msg}
        
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم.")


# =================================================================================
# 4. إشعارات النواقص (Threshold Alerts - Reorder Point)
# =================================================================================
@router.get("/warehouse/alerts", response_model=List[WarehouseAlertItem], status_code=200)
async def get_warehouse_alerts(
    location_id: int, # +++ استقبال المستودع كـ Query +++
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    # تجميع الرصيد المتاح من InventoryBalance (المحرك الموحد)
    inv_subq = select(
        InventoryBalance.product_variant_id,
        func.sum(InventoryBalance.on_hand_quantity).label('available_packs')
    ).filter_by(
        company_id=current_admin.company_id, location_id=location_id, stock_status='AVAILABLE'
    ).group_by(InventoryBalance.product_variant_id).subquery()

    # الانضمام مع MainWarehouse القديم فقط لقراءة min_threshold_packs
    stmt = select(ProductVariant, MainWarehouse.min_threshold_packs, inv_subq.c.available_packs).select_from(ProductVariant)\
        .join(MainWarehouse, ProductVariant.id == MainWarehouse.product_variant_id)\
        .outerjoin(inv_subq, ProductVariant.id == inv_subq.c.product_variant_id)\
        .filter(
            ProductVariant.is_active == True,
            func.coalesce(inv_subq.c.available_packs, 0) <= MainWarehouse.min_threshold_packs,
            MainWarehouse.min_threshold_packs > 0 
        )
    
    alerts = (await db.execute(stmt)).all()

    result = []
    for variant, threshold, available in alerts:
        result.append({
            "product_variant_id": variant.id,
            "product_name": variant.variant_name,
            "current_total_packs": int(available or 0), 
            "min_threshold_packs": threshold
        })

    return result

# =================================================================================
# 5. جلب حالة المستودع بالكامل (الرصيد الحي، التوالف، المناديب، السيارات)
# =================================================================================
@router.get("/warehouse/inventory", response_model=List[WarehouseInventoryItem], status_code=200)
async def get_warehouse_inventory(
    location_id: int, # +++ استقبال المستودع كـ Query +++
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    try:
        # +++ التغيير الجذري: قراءة الرصيد المتاح والمحجوز من المحرك الموحد بناءً على الموقع +++
        unified_inv_subq = select(
            InventoryBalance.product_variant_id,
            func.sum(InventoryBalance.on_hand_quantity).label('available_packs'),
            func.sum(InventoryBalance.reserved_quantity).label('reserved_packs')
        ).filter_by(
            company_id=current_admin.company_id, location_id=location_id, stock_status='AVAILABLE'
        ).group_by(InventoryBalance.product_variant_id).subquery()

        # +++ 1. Subquery للتوالف (Damaged) +++
        damaged_subq = select(
            DamagedItemLog.product_variant_id,
            func.sum(DamagedItemLog.quantity_packs).label('total_damaged')
        ).group_by(DamagedItemLog.product_variant_id).subquery()

        # +++ 2. Subquery لحمولات السيارات النائمة حصراً (نسف ثغرة الدبلجة وأشباح السيارات) +++
        # جلب أرقام السيارات النشطة حالياً في الشارع لاستبعادها
        # +++  لكارثة الأصول الوهمية: إضافة 'postponed' لأن السيارة تظل محملة وخارج المستودع +++
        active_vehicles_subq = select(DispatchRoute.vehicle_id).filter(
            DispatchRoute.status.in_(['active', 'waiting', 'postponed']),
            DispatchRoute.vehicle_id.isnot(None)
        ).scalar_subquery()

        vehicle_load_subq = select(
            VehicleLoad.product_variant_id,
            func.sum(VehicleLoad.quantity).label('total_vehicle_cartons')
        ).join(
            Vehicle, VehicleLoad.vehicle_id == Vehicle.id # +++ الدرع المعماري: Inner Join ينسف حمولات أي سيارة تم حذفها (الأشباح) +++
        ).filter(
            VehicleLoad.vehicle_id.not_in(active_vehicles_subq)
        ).group_by(VehicleLoad.product_variant_id).subquery()

        # +++ 3. Subquery لجرد المناديب بالشارع (Active Session Inventory) +++
        session_inv_subq = select(
            SessionInventory.product_variant_id,
            func.sum(SessionInventory.current_remaining_quantity).label('total_session_packs')
        ).join(WorkSession, SessionInventory.work_session_id == WorkSession.id)\
         .filter(WorkSession.is_settled == False)\
         .group_by(SessionInventory.product_variant_id).subquery()

        # +++ 4. Subquery للسحوبات المعلقة (Pending Pulls - In-Transit) +++
        pending_pulls_subq = select(
            InventoryTransfer.product_variant_id,
            func.sum(InventoryTransfer.quantity_packs).label('total_pulls')
        ).filter(
            InventoryTransfer.status == 'pending', 
            InventoryTransfer.quantity_packs < 0
        ).group_by(InventoryTransfer.product_variant_id).subquery()

        # +++ 5. الاستعلام المركزي المدمج (The Mega Join) +++
        stmt = select(
            ProductVariant, 
            unified_inv_subq.c.available_packs,
            unified_inv_subq.c.reserved_packs,
            MainWarehouse.min_threshold_packs, # نقرأ الحد الأدنى فقط من القديم
            damaged_subq.c.total_damaged, 
            vehicle_load_subq.c.total_vehicle_cartons, 
            session_inv_subq.c.total_session_packs,
            pending_pulls_subq.c.total_pulls
        ).outerjoin(unified_inv_subq, ProductVariant.id == unified_inv_subq.c.product_variant_id)\
         .outerjoin(MainWarehouse, ProductVariant.id == MainWarehouse.product_variant_id)\
         .outerjoin(damaged_subq, ProductVariant.id == damaged_subq.c.product_variant_id)\
         .outerjoin(vehicle_load_subq, ProductVariant.id == vehicle_load_subq.c.product_variant_id)\
         .outerjoin(session_inv_subq, ProductVariant.id == session_inv_subq.c.product_variant_id)\
         .outerjoin(pending_pulls_subq, ProductVariant.id == pending_pulls_subq.c.product_variant_id)\
         .filter(
             or_(
                 ProductVariant.is_active == True,
                 unified_inv_subq.c.available_packs > 0,
                 unified_inv_subq.c.reserved_packs > 0,
                 vehicle_load_subq.c.total_vehicle_cartons > 0,
                 session_inv_subq.c.total_session_packs > 0,
                 damaged_subq.c.total_damaged > 0,
                 pending_pulls_subq.c.total_pulls < 0 
             )
         )

        all_inventory_rows = (await db.execute(stmt)).all()

        result = []
        for row in all_inventory_rows:
            variant = row.ProductVariant
            avail = int(row.available_packs or 0)
            res = int(row.reserved_packs or 0)
            damaged = int(row.total_damaged or 0)
            veh_cartons = row.total_vehicle_cartons
            sess_packs = row.total_session_packs
            pending_pulls = row.total_pulls

            ppc = int(variant.packs_per_carton) if variant.packs_per_carton else 1
            virtual_res = res + abs(int(pending_pulls or 0))
            
            veh_packs_total = int(veh_cartons or 0) * ppc
            sess_packs_total = int(sess_packs or 0)
            
            grand_total_packs = avail + res + veh_packs_total + sess_packs_total
            
            result.append({
                "id": variant.id,
                "name": variant.variant_name,
                "sku": variant.sku,
                "packs_per_carton": ppc,
                "available_packs": avail,
                "reserved_packs": virtual_res, 
                "total_packs": grand_total_packs,
                "damaged_packs": damaged,
                "available_cartons": avail // ppc,
                "available_loose_packs": avail % ppc,
                "min_threshold": int(row.min_threshold_packs or 0)
            })
            
        return result

    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء جلب الجرد.")


# =================================================================================
# 6. جلب سجل حركات المستودع (Ledger) - الدفتر غير القابل للمسح
# =================================================================================
@router.get("/warehouse/ledger", response_model=List[WarehouseLedgerItem], status_code=200)
async def get_warehouse_ledger(
    location_id: Optional[int] = None, # +++ اختياري حالياً كون الدفتر شركة-نطاق +++
    skip: int = 0, 
    limit: int = 500, 
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
    
    try:
        # +++  (C-03): منع القيم السالبة في أرقام الصفحات +++
        if skip < 0 or limit < 0:
            raise HTTPException(status_code=400, detail="مرفوض: لا يمكن إدخال قيم سالبة في أرقام الصفحات.")

        # +++  لـ N+1 مع Pagination حقيقي يحمي الذاكرة ولا يعمي المحاسب +++
        safe_limit = max(1, min(limit, 1000)) 
        # +++ الدرع المعماري (Vector 11 Fix): إجبار ربط الدفتر القديم بهوية الشركة عبر المنتج +++
        stmt = select(WarehouseLedger).join(
            ProductVariant, WarehouseLedger.product_variant_id == ProductVariant.id
        ).options(
            joinedload(WarehouseLedger.product_variant), 
            joinedload(WarehouseLedger.admin)
        ).filter(
            ProductVariant.company_id == current_admin.company_id
        ).order_by(WarehouseLedger.created_at.desc()).offset(skip).limit(safe_limit)
        
        logs = (await db.execute(stmt)).scalars().all()
        
        result = []
        for log in logs:
            variant = log.product_variant
            admin = log.admin
            ppc = int(variant.packs_per_carton) if variant and variant.packs_per_carton else 1
            
            result.append({
                "id": log.id,
                "product_name": variant.variant_name if variant else "غير معروف",
                "packs_per_carton": ppc,
                "type": log.transaction_type,
                "quantity_packs": log.quantity_packs,
                # +++   استخدام الرصيد الموثق في الداتابيز مباشرة بدل إعادة حسابه ديناميكياً لتجنب تزوير الدفاتر +++
                "balance_before": log.balance_before_packs,
                "balance_after": log.balance_after_packs,
                "admin_name": admin.full_name if admin else "غير معروف",
                "reference": log.reference_id,
                "notes": log.notes,
                # +++ نسف الانفصام الزمني: إضافة UTC إجبارياً لمنع طرح 4 ساعات في الموبايل +++
                "date": log.created_at.replace(tzinfo=timezone.utc).isoformat() if log.created_at else ""
            })
        return result
    except Exception as e:
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي أثناء جلب السجلات.")


# =================================================================================
# 7. جلب حالة قفل المستودع
# =================================================================================
@router.get("/warehouse/status", response_model=WarehouseStatusResponse, status_code=200)
async def get_warehouse_status(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    # (P0 Fixed): فلترة بـ company_id لمنع MultipleResultsFound
    stmt = select(SystemSetting).filter_by(company_id=current_admin.company_id, setting_key='warehouse_status')
    setting = (await db.execute(stmt)).scalar_one_or_none()
    
    status = setting.setting_value if setting else 'ACTIVE'
    return {"status": status}


# =================================================================================
# 8. جلب قائمة المنتجات فقط (للقوائم المنسدلة Dropdowns)
# =================================================================================
@router.get("/product_variants/simple", response_model=List[SimpleProductVariantItem], status_code=200)
async def get_simple_product_variants(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
    
    stmt = select(ProductVariant).filter_by(is_active=True)
    variants = (await db.execute(stmt)).scalars().all()
    
    return [{
        "id": v.id,
        "name": v.variant_name,
        "packs_per_carton": int(v.packs_per_carton) if v.packs_per_carton else 1
    } for v in variants]

# =================================================================================
# 9. إضافة منتج جديد لكتالوج الشركة (مع التهيئة المخزنية التلقائية)
# =================================================================================
@router.post("/warehouse/product_variants", status_code=201)
async def add_product_variant(
    payload: AddProductVariantRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # +++ الدرع الرقابي: منع تكرار أسماء المنتجات والباركود (SKU) لحماية السيرفر من 500 IntegrityError +++
    clean_name = payload.variant_name.strip().lower()
    clean_sku = payload.sku.strip() if payload.sku else None
    
    conditions = [func.lower(ProductVariant.variant_name) == clean_name]
    if clean_sku:
        conditions.append(ProductVariant.sku == clean_sku)
        
    stmt_exist = select(ProductVariant).filter(or_(*conditions))
    existing = (await db.execute(stmt_exist)).scalars().first()
    
    if existing:
        if existing.variant_name.lower() == clean_name:
            raise HTTPException(status_code=409, detail=f"المنتج '{payload.variant_name}' موجود مسبقاً في النظام.")
        else:
            raise HTTPException(status_code=409, detail=f"الباركود (SKU) '{clean_sku}' مستخدم بالفعل لمنتج آخر ({existing.variant_name}).")

    try:
        # 1. التزويد الآلي للمنتج الأب المرتبط بالشركة حصراً
        from models import UOM
        stmt_product = select(Product).filter_by(company_id=current_admin.company_id).limit(1)
        base_product = (await db.execute(stmt_product)).scalars().first()
        if not base_product:
            base_product = Product(company_id=current_admin.company_id, base_name="منتجات عامة")
            db.add(base_product)
            await db.flush()

        # جلب وحدة القياس الأساسية (CARTON الافتراضية)
        stmt_uom = select(UOM.id).filter(func.upper(UOM.code) == 'CARTON').limit(1)
        uom_id = (await db.execute(stmt_uom)).scalar()
        if not uom_id:
            stmt_any_uom = select(UOM.id).limit(1)
            uom_id = (await db.execute(stmt_any_uom)).scalar()
            if not uom_id:
                new_uom = UOM(name="كرتونة", code="CARTON")
                db.add(new_uom)
                await db.flush()
                uom_id = new_uom.id

        # إنشاء المنتج الجديد مع الحفاظ الصارم على عقد الـ Tenant و Base UOM
        new_variant = ProductVariant(
            company_id=current_admin.company_id,
            product_id=base_product.id,
            base_uom_id=uom_id,
            variant_name=payload.variant_name.strip(),
            sku=payload.sku.strip() if payload.sku else None,
            price_per_carton=payload.price_per_carton,
            packs_per_carton=payload.packs_per_carton,
            price_per_pack=payload.price_per_pack,
            default_max_samples_per_day=payload.default_max_samples_per_day or 0,
            is_active=True
        )
        db.add(new_variant)
        await db.flush()

        # 2. +++ التهيئة المخزنية (Zero-Balance Initialization) +++
        # نفتح حساباً فورياً للمنتج في المستودع برصيد صفري لمنع الانهيارات اللاحقة في دوال الجرد والتوزيع
        new_wh_record = MainWarehouse(
            product_variant_id=new_variant.id,
            available_quantity_packs=0,
            reserved_quantity_packs=0,
            # +++ الدرع الفولاذي: سحق الـ None المتسرب من Pydantic v2 لمنع 500 Crash +++
            min_threshold_packs=payload.min_threshold_packs or 0
        )
        db.add(new_wh_record)

        await db.commit()
        return {
            "message": f"تم إضافة المنتج '{new_variant.variant_name}' بنجاح، وتمت تهيئة رصيده الصفري في المستودع.", 
            "product_id": new_variant.id
        }

    except HTTPException:
        raise
    except IntegrityError as e:
        # +++ الدرع الفولاذي: التقاط سباق الإشارات (Race Condition) عند إضافة منتج مكرر +++
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=409, detail="مرفوض: تعارض في قاعدة البيانات. قد يكون اسم المنتج أو الباركود مسجلاً مسبقاً للتو.")
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ داخلي في الخادم أثناء حفظ المنتج.")


# =================================================================================
# 10. تعديل وإرجاع حركات المستودع (التصحيح العكسي) - Reversal 
# =================================================================================
@router.post("/warehouse/ledger/{entry_id}/adjust", status_code=200)
async def adjust_warehouse_entry(
    entry_id: int,
    payload: AdjustWarehouseEntryRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # 1. التحقق من كلمة المرور (الدرع الأمني الفولاذي)
    # +++ الدرع الفولاذي: عزل متغيرات الداتابيز عن الـ Thread لمنع DetachedInstanceError +++
    pwd_bytes = payload.password.encode('utf-8')
    hash_bytes = current_admin.password_hash.encode('utf-8')
    password_ok = await asyncio.to_thread(bcrypt.checkpw, pwd_bytes, hash_bytes)
    if not password_ok:
        # +++  (C-04): منع انهيار السيرفر إذا فشل تسجيل الاختراق +++
        try:
            audit = SystemAuditLog(
                admin_id=current_admin.id, target_id=f"Ledger_{entry_id}",
                action_type='UNAUTHORIZED_ADJUSTMENT', old_value='Wrong Password', new_value='Rejected'
            )
            db.add(audit)
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to log unauthorized adjustment: {e}")
            
        raise HTTPException(status_code=403, detail="كلمة المرور غير صحيحة. تم رفض العملية وتوثيق المحاولة.")

    try:
        # +++  (C-02): منع إدخال إجمالي سالب لتجنب تخريب الدفاتر +++
        if int(payload.new_total_packs) < 0:
            raise HTTPException(status_code=400, detail="مرفوض: لا يمكن أن يكون الإجمالي الجديد قيمة سالبة.")

        # 2. جلب الحركة الأصلية مع الدرع المعماري (Vector 12 Fix)
        stmt_entry = select(WarehouseLedger).join(
            ProductVariant, WarehouseLedger.product_variant_id == ProductVariant.id
        ).filter(
            WarehouseLedger.id == entry_id,
            ProductVariant.company_id == current_admin.company_id
        )
        original_entry = (await db.execute(stmt_entry)).scalar_one_or_none()
        
        if not original_entry:
            raise HTTPException(status_code=404, detail="الحركة غير موجودة أو لا تتبع لشركتك.")
            
        if original_entry.transaction_type != 'INBOUND_SUPPLIER':
            raise HTTPException(status_code=400, detail="مرفوض: يمكن تعديل حركات التوريد من المورد فقط.")

        # CS-WH-02: Acquire MainWarehouse lock FIRST to serialize concurrent adjustments before reading invoice sum
        stmt_wh = select(MainWarehouse).with_for_update().filter_by(product_variant_id=original_entry.product_variant_id)
        wh_record = (await db.execute(stmt_wh)).scalar_one_or_none()
        if not wh_record:
            await db.rollback()
            raise HTTPException(status_code=404, detail="سجل المستودع غير موجود.")

        # 3. حساب الفرق بناءً على (الصافي الحالي للفاتورة) مع حماية المرجع الفارغ
        ref_id = original_entry.reference_id
        if not ref_id or not ref_id.strip() or ref_id == "بدون فاتورة":
            # +++   منع تعديل الفواتير القديمة المجهولة لحماية الدفتر من الانهيار الرياضي +++
            await db.rollback()
            raise HTTPException(status_code=400, detail="مرفوض: لا يمكن تعديل فواتير قديمة لا تحمل رقماً مرجعياً. يرجى استخدام (تسوية جرد المستودع) لضبط الرصيد.")

        stmt_sum = select(func.sum(WarehouseLedger.quantity_packs)).filter(
            WarehouseLedger.reference_id == ref_id,
            WarehouseLedger.product_variant_id == original_entry.product_variant_id,
            WarehouseLedger.transaction_type.in_(['INBOUND_SUPPLIER', 'INBOUND_CORRECTION'])
        )
        current_invoice_total_packs = (await db.execute(stmt_sum)).scalar() or 0

        delta = int(payload.new_total_packs) - int(current_invoice_total_packs)

        if delta == 0:
            return {"message": "لا يوجد تغيير في الكمية. الصافي الحالي مطابق لما أدخلته."}

        # 4. جلب المنتج ( C-01: إزالة القفل غير المبرر لمنع الـ Deadlock)
        stmt_variant = select(ProductVariant).filter_by(id=original_entry.product_variant_id)
        variant = (await db.execute(stmt_variant)).scalar_one_or_none()
        if not variant:
            await db.rollback() # +++ الدرع الفولاذي: تحرير القفل لإنقاذ السيرفر +++
            raise HTTPException(status_code=404, detail="المنتج غير موجود.")

        # 5. تحديث الرصيد الحالي للمستودع (منع الرصيد السالب)
        old_balance = wh_record.available_quantity_packs or 0  # +++   استخراج الرصيد الآمن أولاً +++
        
        if old_balance + delta < 0:
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"فشل التعديل: الكمية المخصومة ({abs(delta)}) أكبر من المتوفر بالمستودع ({old_balance}).")

        wh_record.available_quantity_packs = old_balance + delta

        # 6. تسجيل الحركة العكسية (Inbound Correction) لضبط الدفاتر بنفس رقم المرجع
        adjustment_entry = WarehouseLedger(
            product_variant_id=variant.id,
            quantity_packs=delta,
            balance_before_packs=old_balance,
            balance_after_packs=wh_record.available_quantity_packs,
            transaction_type='INBOUND_CORRECTION',
            admin_id=current_admin.id,
            reference_id=original_entry.reference_id,
            notes=f"تعديل لفاتورة المورد: {payload.notes}"
        )
        db.add(adjustment_entry)

        # +++ الدرع المعماري للمحرك الموحد: الـ Dual-Write والتوزيع التناسبي (P2 Fixed) +++
        stmt_mov = select(InventoryMovement).filter_by(
            reference_id=original_entry.reference_id, 
            product_variant_id=variant.id,
            reference_type='INBOUND_SUPPLIER'
        ).order_by(InventoryMovement.created_at.desc())
        orig_movs = (await db.execute(stmt_mov)).scalars().all()
        
        warning_msg = ""
        if not orig_movs:
            # (P2 Fixed): Silent Divergence Gap - تحذير صريح للمشرف إذا كانت الفاتورة قديمة ولم ترحل للمحرك الموحد
            warning_msg = " | ⚠️ تنبيه: تم التعديل في السجل القديم فقط لأن الفاتورة الأصلية لا تملك قيوداً في المحرك الموحد."
        else:
            # (P2 Fixed): التوزيع الآمن على أحدث دفعة مسجلة لهذه الفاتورة لمنع الـ limit(1) Bug
            target_mov = orig_movs[0] 
            
            await _upsert_inventory_balance(
                db, current_admin.company_id, target_mov.destination_location_id,
                variant.id, target_mov.batch_id, delta
            )
            
            # (P2 Fixed): مفتاح الإعادة القطعي (Deterministic Idempotency) لمنع الخصم المزدوج عند تقطع الإنترنت
            deterministic_key = f"ADJ-{original_entry.id}-NEWTOT-{payload.new_total_packs}"
            
            db.add(InventoryMovement(
                company_id=current_admin.company_id, performed_by=current_admin.id,
                source_location_id=target_mov.destination_location_id if delta < 0 else None,
                destination_location_id=target_mov.destination_location_id if delta > 0 else None,
                product_variant_id=variant.id, batch_id=target_mov.batch_id, quantity=abs(delta),
                reference_type='INBOUND_CORRECTION', reference_id=original_entry.reference_id,
                idempotency_key=deterministic_key,
                notes=payload.notes
            ))

        await db.commit()
        
        return {"message": f"تم تسجيل التعديل بنجاح وتحديث الأرصدة. الفرق المحاسبي: {'+' if delta>0 else ''}{delta} حبة.{warning_msg}"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء معالجة التعديل.")


# =================================================================================
# [المرحلة الرابعة والخامسة] المحرك الموحد للحوالات ونظام الصلاحية (FEFO & IN_TRANSIT)
# هذه الـ APIs لا تمس العمليات القديمة، بل تؤسس لهندسة الـ SaaS القادمة.
# =================================================================================

async def _check_fefo_override_permission(db: AsyncSession, admin: Driver, company_id: int):
    """التحقق الصارم من صلاحية inventory.fefo_override عبر RBAC مع استثناء الـ SuperAdmin"""
    if admin.is_admin:
        return True

    stmt = select(Permission.id).select_from(UserRole).join(
        Role, and_(UserRole.role_id == Role.id, UserRole.company_id == company_id)
    ).join(
        role_permissions, Role.id == role_permissions.c.permission_id
    ).join(
        Permission, role_permissions.c.permission_id == Permission.id
    ).filter(
        UserRole.driver_id == admin.id,
        UserRole.company_id == company_id,
        Permission.code == 'inventory.fefo_override'
    )
    has_perm = (await db.execute(stmt)).first()
    if not has_perm:
        raise ValueError("مرفوض: تخطي نظام FEFO يتطلب منحك صلاحية (inventory.fefo_override).")
    return True

async def _reconcile_cycle_count_movements(
    db: AsyncSession, company_id: int, location_id: int,
    variant_id: int, batch_id: Optional[int],
    cutoff_time: datetime
) -> int:
    """حساب صافي الحركات الواقعة على الصنف منذ نقطة الانطلاق لتسوية الجرد الدوري تلقائياً"""
    # الحركات الواردة للموقع (+)
    stmt_in = select(func.coalesce(func.sum(InventoryMovement.quantity), 0)).filter(
        InventoryMovement.company_id == company_id,
        InventoryMovement.destination_location_id == location_id,
        InventoryMovement.product_variant_id == variant_id,
        InventoryMovement.created_at >= cutoff_time,
        InventoryMovement.reference_type != 'AUDIT_ADJUSTMENT'
    )
    if batch_id:
        stmt_in = stmt_in.filter(InventoryMovement.batch_id == batch_id)
    qty_in = (await db.execute(stmt_in)).scalar() or 0

    # الحركات الصادرة من الموقع (-)
    stmt_out = select(func.coalesce(func.sum(InventoryMovement.quantity), 0)).filter(
        InventoryMovement.company_id == company_id,
        InventoryMovement.source_location_id == location_id,
        InventoryMovement.product_variant_id == variant_id,
        InventoryMovement.created_at >= cutoff_time,
        InventoryMovement.reference_type != 'AUDIT_ADJUSTMENT'
    )
    if batch_id:
        stmt_out = stmt_out.filter(InventoryMovement.batch_id == batch_id)
    qty_out = (await db.execute(stmt_out)).scalar() or 0

    return int(qty_in - qty_out)

async def _upsert_inventory_balance(db: AsyncSession, company_id: int, location_id: int, variant_id: int, batch_id: int, qty_change: int):
    """(P0 Fixed): إزالة quantity الوهمي بالكامل واستخدام on_hand_quantity حصراً"""
    if qty_change < 0:
        stmt_check = select(InventoryBalance.on_hand_quantity).filter_by(
            company_id=company_id, location_id=location_id,
            product_variant_id=variant_id, batch_id=batch_id, stock_status='AVAILABLE'
        ).with_for_update()
        current_qty = (await db.execute(stmt_check)).scalar() or 0
        if current_qty + qty_change < 0:
            raise ValueError(f"لا يمكن سحب كمية ({abs(qty_change)}) تتجاوز الرصيد المتاح ({current_qty}) في الموقع.")

    stmt = pg_insert(InventoryBalance).values(
        company_id=company_id, location_id=location_id,
        product_variant_id=variant_id, batch_id=batch_id,
        stock_status='AVAILABLE', 
        on_hand_quantity=qty_change if qty_change > 0 else 0, 
        reserved_quantity=0
    ).on_conflict_do_update(
        index_elements=['company_id', 'location_id', 'product_variant_id', 'batch_id', 'stock_status'],
        set_=dict(
            on_hand_quantity=InventoryBalance.on_hand_quantity + qty_change
        )
    )
    await db.execute(stmt)

async def _verify_location_ownership(db: AsyncSession, company_id: int, *location_ids, allowed_types: Optional[List[str]] = None):
    """الدرع الأمني: التحقق من الانتماء والحالة ونوع الموقع المصرح"""
    for loc_id in location_ids:
        stmt = select(InventoryLocation).filter_by(id=loc_id, company_id=company_id)
        loc = (await db.execute(stmt)).scalar_one_or_none()
        if not loc:
            raise ValueError(f"مرفوض أمنياً: الموقع ({loc_id}) لا ينتمي للشركة أو غير موجود.")
        if not getattr(loc, 'is_active', False):
            raise ValueError(f"مرفوض أمنياً: الموقع ({loc_id}) غير فعال.")
        if allowed_types and loc.location_type not in allowed_types:
            raise ValueError(f"مرفوض أمنياً: نوع الموقع ({loc.location_type}) غير مسموح لهذه العملية.")

# (تم توحيد حارس الأقفال الجراحية: المرجع الوحيد الآن check_inventory_lock في services.py)
# ويُستورد أعلى الملف باسم _check_inventory_lock حفاظاً على مواضع الاستدعاء

async def _allocate_fefo_batches(db: AsyncSession, company_id: int, location_id: int, variant_id: int, required_qty: int) -> list:
    """محرك FEFO الرياضي: محصن ضد تواريخ الصلاحية و AttributeErrors"""
    stmt = select(InventoryBalance, ProductBatch).join(
        ProductBatch, InventoryBalance.batch_id == ProductBatch.id
    ).filter(
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == location_id,
        InventoryBalance.product_variant_id == variant_id,
        InventoryBalance.stock_status == 'AVAILABLE',
        InventoryBalance.on_hand_quantity > 0,
        ProductBatch.is_active == True,
        ProductBatch.expiry_date >= date.today() 
    ).order_by(ProductBatch.expiry_date.asc()).with_for_update()

    available_balances = (await db.execute(stmt)).all()

    allocated = []
    remaining = required_qty

    for balance, batch in available_balances:
        if remaining <= 0: break
        # (P0 Fixed): استخدام on_hand_quantity بدلاً من quantity
        take_qty = min(balance.on_hand_quantity, remaining)
        allocated.append({"balance_id": balance.id, "batch_id": batch.id, "take_qty": take_qty})
        remaining -= take_qty

    if remaining > 0:
        raise ValueError(f"الرصيد المتاح لا يغطي الكمية المطلوبة. العجز: {remaining} حبة.")
    return allocated

@router.post("/warehouse/unified/transfer/dispatch", status_code=200)
async def unified_transfer_dispatch(
    payload: UnifiedDispatchRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    company_id = current_admin.company_id

    if not payload.items:
        raise HTTPException(status_code=400, detail="مرفوض: يجب إرسال أصناف لتنفيذ الحوالة.")

    if await check_warehouse_lock(db, current_admin.company_id):
        raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً بسبب عملية جرد.")
        
    # حظر الإرسال لنفس الموقع
    if payload.source_location_id == payload.destination_location_id:
        raise HTTPException(status_code=400, detail="مرفوض: لا يمكن الإرسال لنفس الموقع.")
        
    try:
        # حظر التعامل مع IN_TRANSIT أو SCRAP كمصدر أو وجهة مباشرة من قبل المستخدم
        await _verify_location_ownership(
            db, company_id, payload.source_location_id, payload.destination_location_id,
            allowed_types=['WAREHOUSE', 'VEHICLE']
        )
    except ValueError as ve:
        raise HTTPException(status_code=403, detail=str(ve))
        
    transfer_ref = f"TRN-{uuid.uuid4().hex[:8].upper()}"
    
    try:
        stmt_transit_ins = pg_insert(InventoryLocation).values(
            company_id=company_id, name="بضاعة في الطريق", code="TRANSIT-SYS", location_type='IN_TRANSIT'
        ).on_conflict_do_nothing(index_elements=['company_id', 'code'])
        await db.execute(stmt_transit_ins)
        
        stmt_loc = select(InventoryLocation.id).filter_by(company_id=company_id, code='TRANSIT-SYS')
        transit_loc_id = (await db.execute(stmt_loc)).scalar_one()

        header = InventoryTransferHeader(
            company_id=company_id, reference_number=transfer_ref,
            source_location_id=payload.source_location_id, destination_location_id=payload.destination_location_id,
            status='PENDING', dispatched_by=current_admin.id
        )
        db.add(header)
        await db.flush() 

        # (P2 Fixed): تجميع الأصناف المتطابقة لمنع uq_transfer_line_item crash
        # تم إزالة override_reason_id من مفتاح التجميع لمنع تفريخ أسطر وهمية للصنف الواحد
        aggregated_items = {}
        for item in payload.items:
            if item.quantity <= 0: 
                raise HTTPException(status_code=422, detail="مرفوض: الكمية يجب أن تكون أكبر من صفر.")
            key = (item.product_variant_id, item.override_batch_id)
            if key in aggregated_items:
                aggregated_items[key].quantity += item.quantity
            else:
                aggregated_items[key] = item

        for item in aggregated_items.values():
            if item.is_fefo_override:
                await _check_fefo_override_permission(db, current_admin, company_id)
                if not item.override_batch_id or not item.override_reason_id:
                    raise ValueError("مرفوض: يجب تحديد الدفعة المراد سحبها وسبب التخطي (Reason ID).")
                    
                # الدرع الرقابي الصارم: التحقق من أن سبب التخطي موجود وفعال
                stmt_reason = select(OverrideReason.id).filter_by(
                    id=item.override_reason_id, company_id=company_id, is_active=True
                )
                if not (await db.execute(stmt_reason)).first():
                    raise ValueError("مرفوض: سبب التخطي المُرسل غير موجود أو غير مفعل في النظام.")
                    
                # التحقق الصارم: الدفعة تتبع لنفس الصنف والشركة، فعالة، وغير منتهية الصلاحية
                stmt_b = select(ProductBatch).filter(
                    ProductBatch.id == item.override_batch_id,
                    ProductBatch.company_id == company_id,
                    ProductBatch.product_variant_id == item.product_variant_id,
                    ProductBatch.is_active == True,
                    ProductBatch.expiry_date >= date.today()
                )
                valid_batch = (await db.execute(stmt_b)).scalar_one_or_none()
                if not valid_batch:
                    raise ValueError("مرفوض أمنياً: الدفعة المحددة للتخطي غير صالحة، موقوفة، منتهية الصلاحية، أو تتبع لصنف آخر.")
                    
                allocations = [{"batch_id": item.override_batch_id, "take_qty": item.quantity}]
                
                # (P1 Fixed): حماية الاستدعاء الافتراضي من الـ ValueError لكي لا يمنع التخطي المبرر
                hypo_batch = 'N/A'
                try:
                    hypo_allocs = await _allocate_fefo_batches(db, company_id, payload.source_location_id, item.product_variant_id, 1)
                    if hypo_allocs: hypo_batch = hypo_allocs[0]['batch_id']
                except ValueError:
                    hypo_batch = 'NO_VALID_FEFO_BATCH_FOUND'
                
                db.add(SystemAuditLog(
                    company_id=company_id, admin_id=current_admin.id, target_id=f"Transfer_{header.id}",
                    action_type="FEFO_OVERRIDE", 
                    old_value=f"Expected Batch (FEFO): {hypo_batch}",
                    new_value=f"Chosen Batch: {item.override_batch_id}, Reason ID: {item.override_reason_id}"
                ))
            else:
                allocations = await _allocate_fefo_batches(db, company_id, payload.source_location_id, item.product_variant_id, item.quantity)
            
            for alloc in allocations:
                batch_id = alloc["batch_id"]
                take_qty = alloc["take_qty"]
                
                # +++ نشر الحارس: منع السحب من رف مقفول (P0-1) +++
                await _check_inventory_lock(db, company_id, payload.source_location_id, item.product_variant_id, batch_id)

                line = InventoryTransferLine(
                    company_id=company_id, # +++ زرع الهوية: مطابقة لعقد الـ Tenant-Owned Tables +++
                    transfer_header_id=header.id, product_variant_id=item.product_variant_id,
                    batch_id=batch_id, quantity=take_qty
                )
                db.add(line)
                
                await _upsert_inventory_balance(db, company_id, payload.source_location_id, item.product_variant_id, batch_id, -take_qty)
                await _upsert_inventory_balance(db, company_id, transit_loc_id, item.product_variant_id, batch_id, take_qty)
                
                db.add(InventoryMovement(
                    company_id=company_id, performed_by=current_admin.id,
                    source_location_id=payload.source_location_id, destination_location_id=transit_loc_id,
                    product_variant_id=item.product_variant_id, batch_id=batch_id, quantity=take_qty,
                    reference_type='TRANSFER_DISPATCH', reference_id=transfer_ref,
                    idempotency_key=f"DISP-{header.id}-{item.product_variant_id}-{batch_id}",
                    notes=payload.notes # استرجاع فقدان البيانات التدقيقية
                ))

        await db.commit()
        return {"message": "تم تحميل البضاعة بنجاح وهي الآن (في الطريق).", "transfer_reference": transfer_ref, "header_id": header.id}
        
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في التحميل: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء معالجة الحوالة.")

@router.post("/warehouse/unified/transfer/receive", status_code=200)
async def unified_transfer_receive(
    payload: UnifiedReceiveRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """الخطوة 2: تأكيد الاستلام (من IN_TRANSIT للوجهة) بناءً على الـ Header"""
    company_id = current_admin.company_id
    
    if await check_warehouse_lock(db, current_admin.company_id):
        raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً.")
        
    try:
        await _verify_location_ownership(db, company_id, payload.destination_location_id)
        
        # قفل הـ Header
        stmt_header = select(InventoryTransferHeader).with_for_update().filter_by(
            id=payload.transfer_header_id, company_id=company_id
        )
        header = (await db.execute(stmt_header)).scalar_one_or_none()
        
        if not header:
            raise ValueError("الحوالة غير موجودة.")
        if header.status != 'PENDING':
            raise ValueError(f"لا يمكن استلام هذه الحوالة، حالتها الحالية: {header.status}.")
        if header.destination_location_id != payload.destination_location_id:
            raise ValueError("مرفوض: أنت تحاول الاستلام في مستودع مختلف عن الوجهة الأصلية.")
        if header.dispatched_by == current_admin.id:
            raise ValueError("مرفوض رقابياً: لا يمكن للمُرسل أن يستلم الحوالة بنفسه.")

        stmt_loc = select(InventoryLocation.id).filter_by(company_id=company_id, code='TRANSIT-SYS')
        transit_loc_id = (await db.execute(stmt_loc)).scalar_one()

        # جلب أسطر الحوالة (Lines)
        stmt_lines = select(InventoryTransferLine).filter_by(transfer_header_id=header.id)
        lines = (await db.execute(stmt_lines)).scalars().all()

        for line in lines:
            # +++ نشر الحارس: منع إيداع حوالة في موقع مقفول جراحياً +++
            await _check_inventory_lock(db, company_id, payload.destination_location_id, line.product_variant_id, line.batch_id)

            # السحب من الترانزيت والإيداع في الوجهة
            await _upsert_inventory_balance(db, company_id, transit_loc_id, line.product_variant_id, line.batch_id, -line.quantity)
            await _upsert_inventory_balance(db, company_id, payload.destination_location_id, line.product_variant_id, line.batch_id, line.quantity)
            
            db.add(InventoryMovement(
                company_id=company_id, performed_by=current_admin.id,
                source_location_id=transit_loc_id, destination_location_id=payload.destination_location_id,
                product_variant_id=line.product_variant_id, batch_id=line.batch_id, quantity=line.quantity,
                reference_type='TRANSFER_RECEIPT', reference_id=header.reference_number,
                idempotency_key=f"REC-{header.id}-{line.id}"
            ))

        # 1. تثبيت قرار المصافحة البشرية الصريح (Human Handshake Decision)
        header.status = 'ACCEPTED'
        header.received_by = current_admin.id
        header.updated_at = sa_func.now()
        await db.flush()

        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Transfer_{header.id}",
            action_type="TRANSFER_HANDSHAKE_ACCEPTED",
            old_value="PENDING",
            new_value=f"ACCEPTED by Admin {current_admin.id}"
        ))

        # 2. ترقية دورة الحياة إلى حالة الترحيل المحاسبي المكتمل (System Accounting State)
        header.status = 'POSTED'

        await db.commit()
        return {"message": "تمت المصافحة وتأكيد استلام الحوالة وترحيل قيودها المحاسبية بنجاح."}
        
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في الاستلام: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء استلام الحوالة.")

@router.post("/warehouse/unified/transfer/{header_id}/cancel", status_code=200)
async def unified_transfer_cancel(
    header_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """دورة الحياة: إلغاء الحوالة وإرجاع البضاعة من IN_TRANSIT إلى المصدر"""
    company_id = current_admin.company_id
    
    if await check_warehouse_lock(db, company_id):
        raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً.")

    try:
        stmt_header = select(InventoryTransferHeader).with_for_update().filter_by(
            id=header_id, company_id=company_id
        )
        header = (await db.execute(stmt_header)).scalar_one_or_none()
        
        if not header:
            raise ValueError("الحوالة غير موجودة.")
        if header.status != 'PENDING':
            raise ValueError(f"لا يمكن إلغاء الحوالة، حالتها الحالية: {header.status}.")

        stmt_loc = select(InventoryLocation.id).filter_by(company_id=company_id, code='TRANSIT-SYS')
        transit_loc_id = (await db.execute(stmt_loc)).scalar_one()

        stmt_lines = select(InventoryTransferLine).filter_by(transfer_header_id=header.id)
        lines = (await db.execute(stmt_lines)).scalars().all()

        for line in lines:
            # +++ نشر الحارس: التأكد من أن المصدر لم يُقفل منذ خروج البضاعة +++
            await _check_inventory_lock(db, company_id, header.source_location_id, line.product_variant_id, line.batch_id)

            # السحب من الترانزيت والإرجاع للمصدر
            await _upsert_inventory_balance(db, company_id, transit_loc_id, line.product_variant_id, line.batch_id, -line.quantity)
            await _upsert_inventory_balance(db, company_id, header.source_location_id, line.product_variant_id, line.batch_id, line.quantity)
            
            db.add(InventoryMovement(
                company_id=company_id, performed_by=current_admin.id,
                source_location_id=transit_loc_id, destination_location_id=header.source_location_id,
                product_variant_id=line.product_variant_id, batch_id=line.batch_id, quantity=line.quantity,
                reference_type='TRANSFER_CANCELLED', reference_id=header.reference_number,
                idempotency_key=f"CANC-{header.id}-{line.id}"
            ))

        header.status = 'CANCELLED'
        header.updated_at = func.now()

        await db.commit()
        return {"message": "تم إلغاء الحوالة وإرجاع البضاعة للمصدر بنجاح."}

    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في الإلغاء: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء إلغاء الحوالة.")


@router.post("/warehouse/unified/transfer/{header_id}/reject", status_code=200)
async def unified_transfer_reject(
    header_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """دورة الحياة: رفض المستلم للحوالة وإرجاع البضاعة من IN_TRANSIT إلى المصدر"""
    company_id = current_admin.company_id
    
    if await check_warehouse_lock(db, company_id):
        raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً.")

    try:
        stmt_header = select(InventoryTransferHeader).with_for_update().filter_by(id=header_id, company_id=company_id)
        header = (await db.execute(stmt_header)).scalar_one_or_none()
        
        if not header: raise ValueError("الحوالة غير موجودة.")
        if header.status != 'PENDING': raise ValueError(f"لا يمكن رفض حوالة بحالة: {header.status}.")
        
        # التأكد أن من يرفض هو صاحب المستودع المستقبل (أو مشرف)
        await _verify_location_ownership(db, company_id, header.destination_location_id)

        stmt_loc = select(InventoryLocation.id).filter_by(company_id=company_id, code='TRANSIT-SYS')
        transit_loc_id = (await db.execute(stmt_loc)).scalar_one()

        stmt_lines = select(InventoryTransferLine).filter_by(transfer_header_id=header.id)
        lines = (await db.execute(stmt_lines)).scalars().all()

        for line in lines:
            # +++ نشر الحارس: التأكد من أن المصدر لم يُقفل منذ خروج البضاعة +++
            await _check_inventory_lock(db, company_id, header.source_location_id, line.product_variant_id, line.batch_id)

            # السحب من الترانزيت والإرجاع للمصدر
            await _upsert_inventory_balance(db, company_id, transit_loc_id, line.product_variant_id, line.batch_id, -line.quantity)
            await _upsert_inventory_balance(db, company_id, header.source_location_id, line.product_variant_id, line.batch_id, line.quantity)
            
            db.add(InventoryMovement(
                company_id=company_id, performed_by=current_admin.id,
                source_location_id=transit_loc_id, destination_location_id=header.source_location_id,
                product_variant_id=line.product_variant_id, batch_id=line.batch_id, quantity=line.quantity,
                reference_type='TRANSFER_REJECTED', reference_id=header.reference_number,
                idempotency_key=f"REJ-{header.id}-{line.id}"
            ))

        header.status = 'REJECTED'
        header.received_by = current_admin.id
        await db.commit()
        return {"message": "تم رفض الحوالة وإرجاع البضاعة لعهدة المُرسل."}

    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في الرفض: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء رفض الحوالة.")

# =================================================================================
# [المرحلة السادسة] محرك الجرد القانوني (Stocktake Engine)
# =================================================================================

@router.post("/warehouse/unified/stocktake/start", status_code=201)
async def start_unified_stocktake(
    payload: UnifiedStocktakeStartRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """الخطوة 1: فتح الجلسة، أخذ Snapshot للـ Blind Count، وتفعيل القفل الجراحي"""
    company_id = current_admin.company_id
    
    if payload.stocktake_type not in ['FULL_COUNT', 'CYCLE_COUNT', 'VEHICLE_RECON']:
        raise HTTPException(status_code=422, detail="مرفوض: نوع الجرد غير صالح.")
        
    try:
        await _verify_location_ownership(db, company_id, payload.location_id)
        
        # 1. (P1-5 Fixed): منع تضارب الجرد الشامل والدوري بدقة
        stmt_active = select(StocktakeSession).filter(
            StocktakeSession.company_id == company_id,
            StocktakeSession.location_id == payload.location_id,
            StocktakeSession.status.in_(['DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED'])
        )
        active_sessions = (await db.execute(stmt_active)).scalars().all()
        
        for sess in active_sessions:
            if payload.stocktake_type == 'FULL_COUNT' or sess.stocktake_type == 'FULL_COUNT':
                raise ValueError("مرفوض: يوجد تعارض مع جلسة جرد شامل نشطة في هذا الموقع.")
            
            # إذا كان CYCLE_COUNT، نتأكد أننا لا نجرد نفس الصنف مرتين
            if payload.stocktake_type == 'CYCLE_COUNT':
                stmt_locks = select(InventoryLock.id).filter_by(stocktake_session_id=sess.id, product_variant_id=payload.product_variant_id)
                if (await db.execute(stmt_locks)).first():
                    raise ValueError(f"مرفوض: الصنف ({payload.product_variant_id}) قيد الجرد حالياً في جلسة أخرى.")

        # 2. إنشاء رأس الجلسة
        ref_num = f"STK-{uuid.uuid4().hex[:8].upper()}"
        session = StocktakeSession(
            company_id=company_id, location_id=payload.location_id,
            reference_number=ref_num, stocktake_type=payload.stocktake_type,
            status='COUNTING', started_by=current_admin.id, notes=payload.notes
        )
        db.add(session)
        await db.flush()

        # 3. تجميد المخزون (Snapshot) لتطبيق الـ Blind Count
        stmt_balances = select(InventoryBalance).filter_by(
            company_id=company_id, location_id=payload.location_id, stock_status='AVAILABLE'
        )
        if payload.stocktake_type == 'CYCLE_COUNT':
            if not payload.product_variant_id:
                raise ValueError("مرفوض: الجرد الدوري (Cycle Count) يتطلب تحديد الصنف المراد جرده.")
            stmt_balances = stmt_balances.filter_by(product_variant_id=payload.product_variant_id)
            if payload.batch_id:
                stmt_balances = stmt_balances.filter_by(batch_id=payload.batch_id)
                
        balances = (await db.execute(stmt_balances)).scalars().all()
        if not balances and payload.stocktake_type == 'CYCLE_COUNT':
            raise ValueError("لا يوجد رصيد لهذا الصنف في الموقع المطلوب لجرده.")

        for bal in balances:
            st_line = StocktakeLine(
                company_id=company_id, stocktake_session_id=session.id,
                product_variant_id=bal.product_variant_id, batch_id=bal.batch_id,
                expected_quantity=bal.on_hand_quantity, # توثيق الرصيد الدفتري الحالي
                actual_quantity=None # إجباري Null لضمان الجرد الأعمى (Blind Count)
            )
            db.add(st_line)

        # 4. الأقفال الجراحية: تُفرض فقط على الجرد الشامل والسيارات، وتُستثنى من الجرد الدوري المستمر
        if payload.stocktake_type != 'CYCLE_COUNT':
            lock = InventoryLock(
                company_id=company_id,
                stocktake_session_id=session.id,
                location_id=payload.location_id,
                product_variant_id=None,
                batch_id=None,
                created_by=current_admin.id
            )
            db.add(lock)

        await db.commit()
        return {
            "message": "تم بدء جلسة الجرد وأخذ لقطة الأرصدة (Snapshot) بنجاح.", 
            "reference_number": ref_num,
            "session_id": session.id
        }

    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في بدء الجرد: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء فتح جلسة الجرد.")


@router.post("/warehouse/unified/stocktake/{session_id}/count", status_code=200)
async def submit_stocktake_count(
    session_id: int,
    payload: UnifiedStocktakeCountRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """الخطوة 2: إدخال الجرد الفعلي، احتساب الـ Variance، ورفع الجلسة للمراجعة"""
    company_id = current_admin.company_id

    try:
        # 1. قفل الجلسة (Row-Level Lock) لمنع إرسال الجرد مرتين في نفس اللحظة
        stmt_session = select(StocktakeSession).with_for_update().filter_by(
            id=session_id, company_id=company_id
        )
        session = (await db.execute(stmt_session)).scalar_one_or_none()

        if not session:
            raise ValueError("جلسة الجرد غير موجودة.")
        if session.status not in ['COUNTING', 'RECOUNT_REQUIRED']:
            raise ValueError(f"مرفوض: لا يمكن إدخال كميات لجلسة بحالة ({session.status}).")

        # 2. جلب وتجهيز أسطر الـ Snapshot وترتيبها حسب الـ FEFO (P0-A Fixed)
        # نستخدم Join مع ProductBatch لضمان فرز الأسطر بناءً على أقدمية الصلاحية
        stmt_lines = select(StocktakeLine, ProductBatch.expiry_date).outerjoin(
            ProductBatch, StocktakeLine.batch_id == ProductBatch.id
        ).filter(
            StocktakeLine.stocktake_session_id == session.id
        ).order_by(
            ProductBatch.expiry_date.asc().nulls_last()
        )
        
        existing_lines_raw = (await db.execute(stmt_lines)).all()
        # بناء مصفوفة مرتبة ومفهرسة لضمان التوزيع الصحيح
        ordered_lines = [row[0] for row in existing_lines_raw]
        lines_map = {(line.product_variant_id, line.batch_id): line for line in ordered_lines}

        # 3. تجميع الكميات المُدخلة لحماية الداتابيز من الأسطر المكررة
        aggregated_counts = {}
        for item in payload.items:
            if item.actual_quantity < 0:
                raise ValueError("مرفوض: لا يمكن إدخال كمية سالبة في الجرد الفعلي.")
            key = (item.product_variant_id, item.batch_id)
            aggregated_counts[key] = aggregated_counts.get(key, 0) + item.actual_quantity

        # 4. مطابقة الفعلي مع المتوقع واحتساب الفروقات
        # +++ الدرع المعماري (P0-A): FEFO-Based Allocation Engine +++
        unprocessed_lines = set(lines_map.keys())
        
        for (v_id, b_id), actual_qty in aggregated_counts.items():
            if b_id is None:
                # استخراج مفاتيح الصنف من المصفوفة المرتبة مسبقاً (FEFO)
                prod_keys = [k for k in lines_map.keys() if k[0] == v_id]
                if not prod_keys:
                    if session.stocktake_type == 'CYCLE_COUNT':
                        raise ValueError(f"مرفوض: الصنف ({v_id}) غير مشمول في الجرد الدوري.")
                    new_line = StocktakeLine(
                        company_id=company_id, stocktake_session_id=session.id,
                        product_variant_id=v_id, batch_id=None,
                        expected_quantity=0, actual_quantity=actual_qty, variance_quantity=actual_qty
                    )
                    db.add(new_line)
                else:
                    remaining_actual = actual_qty
                    for i, k in enumerate(prod_keys):
                        line = lines_map[k]
                        if i == len(prod_keys) - 1:
                            # الدفعة الأخيرة تمتص الباقي (زيادة أو عجز)
                            line.actual_quantity = remaining_actual
                        else:
                            take = min(line.expected_quantity, remaining_actual)
                            line.actual_quantity = take
                            remaining_actual -= take
                        line.variance_quantity = line.actual_quantity - line.expected_quantity
                        unprocessed_lines.discard(k)
            else:
                line = lines_map.get((v_id, b_id))
                if line:
                    line.actual_quantity = actual_qty
                    # تطبيق التسوية الحركية التلقائية للجرد الدوري (Cutoff Reconciliation)
                    if session.stocktake_type == 'CYCLE_COUNT':
                        net_movements = await _reconcile_cycle_count_movements(
                            db, company_id, session.location_id, v_id, b_id, session.created_at
                        )
                        effective_expected = line.expected_quantity + net_movements
                        line.variance_quantity = actual_qty - effective_expected
                        line.notes = f"Snapshot: {line.expected_quantity} | Net Movements: {net_movements} | Effective Expected: {effective_expected}"
                    else:
                        line.variance_quantity = actual_qty - line.expected_quantity
                    unprocessed_lines.discard((v_id, b_id))
                else:
                    if session.stocktake_type == 'CYCLE_COUNT':
                        raise ValueError(f"مرفوض: الصنف ({v_id}) غير مشمول.")
                    new_line = StocktakeLine(
                        company_id=company_id, stocktake_session_id=session.id,
                        product_variant_id=v_id, batch_id=b_id,
                        expected_quantity=0, actual_quantity=actual_qty, variance_quantity=actual_qty
                    )
                    db.add(new_line)

        # سحق ثقب الأسطر الفارغة مع التسوية الحركية
        for k in unprocessed_lines:
            line = lines_map[k]
            line.actual_quantity = 0
            if session.stocktake_type == 'CYCLE_COUNT':
                net_movements = await _reconcile_cycle_count_movements(
                    db, company_id, session.location_id, line.product_variant_id, line.batch_id, session.created_at
                )
                effective_expected = line.expected_quantity + net_movements
                line.variance_quantity = -effective_expected
                line.notes = f"Uncounted Zero | Snapshot: {line.expected_quantity} | Net Movements: {net_movements} | Effective Expected: {effective_expected}"
            else:
                line.variance_quantity = -line.expected_quantity

        # 5. ترقية دورة الحياة وتوثيق المسؤولية
        session.status = 'PENDING_REVIEW'
        session.counted_by = current_admin.id
        if payload.notes:
            session.notes = (session.notes or "") + f" | ملاحظات الإدخال: {payload.notes}"

        await db.commit()
        return {"message": "تم حفظ الكميات واحتساب الفروقات، والجلسة الآن بانتظار مراجعة الإدارة."}

    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في إدخال الجرد: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء حفظ بيانات الجرد.")

@router.post("/warehouse/unified/stocktake/{session_id}/approve", status_code=200)
async def approve_stocktake_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """الخطوة 3: الاعتماد الصارم، توليد القيود للفروقات، وفك الأقفال الجراحية"""
    company_id = current_admin.company_id

    # TODO: سيتم الاستبدال بنظام الصلاحيات (RBAC) لاحقاً
    if not current_admin.is_admin:
        raise HTTPException(status_code=403, detail="مرفوض: الاعتماد يتطلب صلاحية مشرف.")

    try:
        # 1. قفل الجلسة (Row-Level Lock) لمنع الاعتماد المزدوج
        stmt_session = select(StocktakeSession).with_for_update().filter_by(
            id=session_id, company_id=company_id
        )
        session = (await db.execute(stmt_session)).scalar_one_or_none()

        if not session:
            raise ValueError("جلسة الجرد غير موجودة.")
        if session.status != 'PENDING_REVIEW':
            raise ValueError(f"مرفوض: لا يمكن اعتماد جلسة بحالة ({session.status}).")

        # +++ الدرع الرقابي المرن (P0-B Fixed): استثناء الفصل الإداري لمدراء المستودع المركزي +++
        if session.counted_by == current_admin.id:
            if current_admin.is_admin:
                # توثيق الاستثناء الرقابي بدقة في دفتر النظام
                db.add(SystemAuditLog(
                    company_id=company_id, admin_id=current_admin.id, target_id=f"Stocktake_{session.id}", 
                    action_type="SEPARATION_OF_DUTIES_OVERRIDE", old_value="BLOCKED", 
                    new_value="ALLOWED: SuperAdmin self-approved central warehouse stocktake."
                ))
            else:
                raise ValueError("مرفوض رقابياً: لا يمكن لمن قام بإدخال الجرد أن يعتمده لنفسه. يرجى طلب مشرف آخر للاعتماد.")

        stmt_lines = select(StocktakeLine).filter_by(stocktake_session_id=session.id)
        lines = (await db.execute(stmt_lines)).scalars().all()

        # +++ سحق ثقب العد الجزئي (P1-1): منع الاعتماد إذا ترك الموظف أسطراً فارغة +++
        if any(line.actual_quantity is None for line in lines):
            raise ValueError("مرفوض: يوجد أسطر في الجلسة لم يتم جردها (فارغة). يجب جرد جميع الأصناف أو إدخال صفر صراحة.")

        # 2. ترحيل القيود (POSTING) وتحديث الأرصدة بناءً على الفروقات فقط
        for line in lines:
            if not line.variance_quantity or line.variance_quantity == 0: 
                continue 

            # +++ الدرع المعماري (القرار ب): العزلة الكاملة لسيارات المناديب (VEHICLE_RECON) +++
            # سيارات المناديب لا تُحدّث InventoryBalance حالياً لأن مبيعاتها تدار في النظام القديم.
            # نكتفي بتسجيل (الالتزام المالي) في دفتر الأستاذ الموحد ليراه المحاسب (سحق P0, P1-1, P1-3).
            if session.stocktake_type == 'VEHICLE_RECON':
                ref_type = 'DRIVER_SHORTAGE' if line.variance_quantity < 0 else 'DRIVER_SURPLUS'
                
                db.add(InventoryMovement(
                    company_id=company_id, performed_by=current_admin.id,
                    source_location_id=session.location_id if line.variance_quantity < 0 else None,
                    destination_location_id=session.location_id if line.variance_quantity > 0 else None,
                    product_variant_id=line.product_variant_id, batch_id=None, # המندوب لا يجرد دفعات
                    quantity=abs(line.variance_quantity),
                    reference_type=ref_type, 
                    reference_id=session.reference_number,
                    idempotency_key=f"AUDIT-{session.id}-{line.id}",
                    notes="تسوية إدارية/مالية لسيارة المندوب (المخزون الفعلي يدار عبر SessionInventory مؤقتاً)"
                ))
            else:
                # +++ الجرد القانوني للمستودعات المركزية (FULL/CYCLE) +++
                await _upsert_inventory_balance(
                    db, company_id, session.location_id,
                    line.product_variant_id, line.batch_id, line.variance_quantity
                )

                db.add(InventoryMovement(
                    company_id=company_id, performed_by=current_admin.id,
                    source_location_id=session.location_id if line.variance_quantity < 0 else None,
                    destination_location_id=session.location_id if line.variance_quantity > 0 else None,
                    product_variant_id=line.product_variant_id, batch_id=line.batch_id,
                    quantity=abs(line.variance_quantity),
                    reference_type='AUDIT_ADJUSTMENT',
                    reference_id=session.reference_number,
                    idempotency_key=f"AUDIT-{session.id}-{line.id}"
                ))

        # 3. فك الأقفال الجراحية (Guillotine Release) لتحرير المستودع
        stmt_locks = select(InventoryLock).filter_by(stocktake_session_id=session.id, released_at=None)
        active_locks = (await db.execute(stmt_locks)).scalars().all()
        for lock in active_locks:
            lock.released_at = sa_func.now()

        # 4. ترقية حالة الجلسة للختام
        session.status = 'POSTED'
        session.approved_by = current_admin.id
        session.updated_at = sa_func.now()

        await db.commit()
        return {"message": "تم اعتماد الجرد بنجاح، رُحلت قيود الفروقات، وفُكت الأقفال ليعود العمل طبيعياً."}

    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في اعتماد الجرد: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء الاعتماد.")


@router.post("/warehouse/unified/stocktake/{session_id}/recount", status_code=200)
async def recount_stocktake_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """قرار المدير: رفض الجرد وإعادته للعد (RECOUNT_REQUIRED) مع إبقاء الأقفال"""
    company_id = current_admin.company_id
    if not current_admin.is_admin: raise HTTPException(status_code=403, detail="مرفوض: يتطلب صلاحية مشرف.")

    try:
        stmt_session = select(StocktakeSession).with_for_update().filter_by(id=session_id, company_id=company_id)
        session = (await db.execute(stmt_session)).scalar_one_or_none()
        
        if not session or session.status != 'PENDING_REVIEW':
            raise ValueError("لا يمكن إعادة الجلسة للعد. يجب أن تكون بانتظار المراجعة.")
            
        session.status = 'RECOUNT_REQUIRED'
        
        # تصفير الكميات المُدخلة لإجبارهم على العد من جديد (Blind Count Again)
        stmt_lines = select(StocktakeLine).filter_by(stocktake_session_id=session.id)
        for line in (await db.execute(stmt_lines)).scalars().all():
            line.actual_quantity = None
            line.variance_quantity = None

        # توثيق القرار
        db.add(SystemAuditLog(company_id=company_id, admin_id=current_admin.id, target_id=f"Stocktake_{session.id}", action_type="RECOUNT_DECISION", old_value="PENDING_REVIEW", new_value="RECOUNT_REQUIRED"))
        await db.commit()
        return {"message": "تم إرجاع الجلسة للعد من جديد. الأقفال لا تزال فعالة."}
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))

@router.post("/warehouse/unified/stocktake/{session_id}/cancel", status_code=200)
async def cancel_stocktake_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    """قرار المدير: إلغاء الجرد بالكامل وفك الأقفال الجراحية فوراً (مخرج الطوارئ)"""
    company_id = current_admin.company_id
    if not current_admin.is_admin: raise HTTPException(status_code=403, detail="مرفوض: يتطلب صلاحية مشرف.")

    try:
        stmt_session = select(StocktakeSession).with_for_update().filter_by(id=session_id, company_id=company_id)
        session = (await db.execute(stmt_session)).scalar_one_or_none()
        
        if not session or session.status in ['POSTED', 'CANCELLED']:
            raise ValueError("لا يمكن إلغاء هذه الجلسة.")
            
        session.status = 'CANCELLED'
        
        # فك الأقفال الجراحية
        stmt_locks = select(InventoryLock).filter_by(stocktake_session_id=session.id, released_at=None)
        for lock in (await db.execute(stmt_locks)).scalars().all():
            lock.released_at = sa_func.now()

        db.add(SystemAuditLog(company_id=company_id, admin_id=current_admin.id, target_id=f"Stocktake_{session.id}", action_type="CANCEL_STOCKTAKE", old_value="ACTIVE", new_value="CANCELLED"))
        await db.commit()
        return {"message": "تم إلغاء الجلسة بالكامل وفك الأقفال عن المستودع."}
    except ValueError as ve:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
