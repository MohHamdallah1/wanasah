from datetime import timezone
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from typing import List
from database import get_db
from api.dependencies import get_current_driver, get_current_admin
from sqlalchemy.orm import joinedload
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
import bcrypt 
import logging
logger = logging.getLogger("wanasah_logger")

from models import (Driver, Product, MainWarehouse, WarehouseLedger, ProductVariant, SystemSetting,
DamagedItemLog, VehicleLoad, SessionInventory, WorkSession, InventoryTransfer, DispatchRoute, Vehicle, SystemAuditLog)

from schemas import (WarehouseInboundRequest, WarehouseStocktakeRequest, ToggleLockRequest, WarehouseAlertItem,
WarehouseInventoryItem, WarehouseLedgerItem, WarehouseStatusResponse, SimpleProductVariantItem,
AddProductVariantRequest, AdjustWarehouseEntryRequest )


router = APIRouter()

# =================================================================================
# دوال مساعدة للمستودع (Helper Functions)
# =================================================================================
async def check_warehouse_lock(db: AsyncSession) -> bool:
    """درع أمني: التحقق من أن المستودع ليس مقفلاً بسبب عملية جرد بصيغة Async"""
    stmt = select(SystemSetting).filter_by(setting_key='warehouse_status')
    lock_setting = (await db.execute(stmt)).scalar_one_or_none()
    if lock_setting and lock_setting.setting_value == 'AUDIT_LOCK':
        return True
    return False

# =================================================================================
# 1. استلام بضاعة من المورد (Inbound) - البنك المركزي
# =================================================================================
@router.post("/warehouse/inbound", status_code=201)
async def warehouse_inbound(
    payload: WarehouseInboundRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
    # +++ فحص قفل الجرد +++
    if await check_warehouse_lock(db):
        raise HTTPException(status_code=403, detail="مرفوض: المستودع مقفل حالياً بسبب عملية جرد.")

    if not payload.items:
        raise HTTPException(status_code=400, detail="يجب إرسال أصناف للاستلام.")

    reference_id = payload.reference_id
    notes = payload.notes

    # +++ الدرع المالي: منع تكرار أرقام فواتير الموردين لمنع دبلجة البضاعة (مطابق للفلاسك 100%) +++
    if reference_id and reference_id.strip() and reference_id != "بدون فاتورة":
        # CS-WH-01: Advisory lock to close TOCTOU window on same invoice number
        normalized_ref = reference_id.strip().lower()
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(normalized_ref))))
        # البحث بشكل صارم مع تجاهل المسافات وحالة الأحرف
        stmt_ref = select(WarehouseLedger.id).filter(
            WarehouseLedger.transaction_type.in_(['INBOUND_SUPPLIER', 'INBOUND_CORRECTION']), 
            func.lower(func.trim(WarehouseLedger.reference_id)) == normalized_ref
        )
        existing_ref = (await db.execute(stmt_ref)).first()
        
        if existing_ref:
            raise HTTPException(status_code=409, detail=f"مرفوض: رقم الفاتورة '{reference_id}' مسجل مسبقاً في النظام. يرجى التحقق لمنع تكرار إدخال البضاعة.")

    try:
        # +++ درع التجميع (Payload Aggregation): حماية الداتابيز من تكرار نفس الصنف في فاتورة المورد +++
        aggregated_items = {}
        for item in payload.items:
            if item.quantity_packs <= 0: continue
            aggregated_items[item.product_variant_id] = aggregated_items.get(item.product_variant_id, 0) + item.quantity_packs

        var_ids = list(aggregated_items.keys())
        if not var_ids:
            return {"message": "لا توجد كميات صالحة للإدخال."}
        
        # +++ الدرع الفولاذي: التحقق من وجود المنتجات أولاً لمنع انهيار السيرفر بسبب الـ ForeignKeyViolation +++
        stmt_variants = select(ProductVariant.id).filter(ProductVariant.id.in_(var_ids))
        valid_var_ids = set((await db.execute(stmt_variants)).scalars().all())

        # +++ قفل الأصناف (Row-Level Lock) مرتبة تصاعدياً لنسف الـ Deadlock +++
        stmt_wh = select(MainWarehouse).with_for_update().filter(MainWarehouse.product_variant_id.in_(list(valid_var_ids))).order_by(MainWarehouse.product_variant_id.asc())
        bulk_warehouse = {w.product_variant_id: w for w in (await db.execute(stmt_wh)).scalars().all()}

        for p_id, added_packs in aggregated_items.items():
            if p_id not in valid_var_ids:
                continue # تجاهل المنتجات الوهمية

            wh_record = bulk_warehouse.get(p_id)
            old_balance = wh_record.available_quantity_packs or 0 if wh_record else 0
            if wh_record:
                wh_record.available_quantity_packs += added_packs
            else:
                wh_record = MainWarehouse(product_variant_id=p_id, available_quantity_packs=added_packs, reserved_quantity_packs=0)
                db.add(wh_record)
                await db.flush() # +++ تحديث الذاكرة فوراً للحصول على الرصيد الجديد بأمان +++
                bulk_warehouse[p_id] = wh_record # تحديث الـ Map الداخلي

            # توثيق الحركة في الليدجر (الدفتر غير القابل للمسح)
            db.add(WarehouseLedger(
                product_variant_id=p_id, 
                transaction_type='INBOUND_SUPPLIER',
                quantity_packs=added_packs,
                balance_before_packs=old_balance,
                balance_after_packs=wh_record.available_quantity_packs,
                admin_id=current_admin.id, 
                reference_id=reference_id, 
                notes=notes
            ))

        await db.commit()
        return {"message": "تم إدخال البضاعة للمستودع وتوثيقها بنجاح"}
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
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
            aggregated_items[item.product_variant_id] = aggregated_items.get(item.product_variant_id, 0) + item.actual_packs

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

        for p_id, actual_packs in aggregated_items.items():
            if p_id not in valid_var_ids:
                continue 

            variant = variants_map[p_id]
            wh_record = bulk_warehouse.get(p_id)
            
            if not wh_record:
                wh_record = MainWarehouse(product_variant_id=p_id, available_quantity_packs=0, reserved_quantity_packs=0)
                db.add(wh_record)
                await db.flush() 

            # +++ 3. النسف المعماري للكارثة (العودة للواقع الميداني) +++
            # الجرد الملموس يُقارن بـ (المتاح) فقط. البضاعة المحجوزة موجودة في سيارات المناديب بالشارع وليست على الرف.
            expected_packs = wh_record.available_quantity_packs
            difference = actual_packs - expected_packs

            if difference != 0:
                # تحديث المتاح الفعلي مباشرة (الواقع يفرض نفسه)
                wh_record.available_quantity_packs = actual_packs
                
                db.add(WarehouseLedger(
                    product_variant_id=p_id, 
                    transaction_type='AUDIT_ADJUSTMENT',
                    # +++ سحق لغم القيمة المطلقة (abs): إرسال العجز والزيادة بإشارتها الحقيقية (+/-) +++
                    quantity_packs=difference, 
                    balance_before_packs=expected_packs,  # <--- هذا السطر اللي رح يمنع الكراش
                    balance_after_packs=actual_packs,
                    admin_id=current_admin.id, 
                    reference_id="STOCKTAKE_OP", 
                    notes=f"الرصيد المتوقع بالرف: {expected_packs}، الفعلي المجرود: {actual_packs}. الفرق: {'+' if difference>0 else ''}{difference}. {payload.notes}"
                ))

        # +++ 4. فتح المستودع تلقائياً بعد إنهاء الجرد بـ Upsert فولاذي لمنع الـ Race Condition (IntegrityError) +++
        insert_stmt = insert(SystemSetting).values(
            setting_key='warehouse_status', 
            setting_value='ACTIVE'
        ).on_conflict_do_update(
            index_elements=['setting_key'],
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
        # +++ نسف ثغرة الـ UniqueViolation باستخدام Upsert معماري فولاذي +++
        insert_stmt = insert(SystemSetting).values(
            setting_key='warehouse_status', 
            setting_value=new_status
        ).on_conflict_do_update(
            index_elements=['setting_key'],
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
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    # +++ النسف المعماري (تحديث اللوجستيات): الإنذار يُبنى على (المتاح للبيع) فقط! +++
    # البضاعة المحجوزة (Reserved) تعتبر بحكم المُباعة ولا يعتمد عليها لتلبية طلبات الغد.
    stmt = select(MainWarehouse, ProductVariant).join(
        ProductVariant, MainWarehouse.product_variant_id == ProductVariant.id
    ).filter(
        # +++ سحق إنذارات الزومبي: تجاهل المنتجات الموقوفة تماماً حتى لو كان رصيدها صفراً +++
        ProductVariant.is_active == True,
        MainWarehouse.available_quantity_packs <= MainWarehouse.min_threshold_packs,
        MainWarehouse.min_threshold_packs > 0 
    )
    
    alerts = (await db.execute(stmt)).all()

    result = []
    for wh, variant in alerts:
        result.append({
            "product_variant_id": variant.id,
            "product_name": variant.variant_name,
            # نرسل المتاح كونه الرقم الذي تسبب بالإنذار
            "current_total_packs": wh.available_quantity_packs, 
            "min_threshold_packs": wh.min_threshold_packs
        })

    return result

# =================================================================================
# 5. جلب حالة المستودع بالكامل (الرصيد الحي، التوالف، المناديب، السيارات)
# =================================================================================
@router.get("/warehouse/inventory", response_model=List[WarehouseInventoryItem], status_code=200)
async def get_warehouse_inventory(
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    

    try:
        # +++ 1. Subquery للتوالف (Damaged) +++
        damaged_subq = select(
            DamagedItemLog.product_variant_id,
            func.sum(DamagedItemLog.quantity_packs).label('total_damaged')
        ).group_by(DamagedItemLog.product_variant_id).subquery()

        # +++ 2. Subquery لحمولات السيارات النائمة حصراً (نسف ثغرة الدبلجة وأشباح السيارات) +++
        # جلب أرقام السيارات النشطة حالياً في الشارع لاستبعادها
        # +++ النسف المعماري لكارثة الأصول الوهمية: إضافة 'postponed' لأن السيارة تظل محملة وخارج المستودع +++
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
            MainWarehouse, 
            damaged_subq.c.total_damaged, 
            vehicle_load_subq.c.total_vehicle_cartons, 
            session_inv_subq.c.total_session_packs,
            pending_pulls_subq.c.total_pulls
        ).outerjoin(MainWarehouse, ProductVariant.id == MainWarehouse.product_variant_id)\
         .outerjoin(damaged_subq, ProductVariant.id == damaged_subq.c.product_variant_id)\
         .outerjoin(vehicle_load_subq, ProductVariant.id == vehicle_load_subq.c.product_variant_id)\
         .outerjoin(session_inv_subq, ProductVariant.id == session_inv_subq.c.product_variant_id)\
         .outerjoin(pending_pulls_subq, ProductVariant.id == pending_pulls_subq.c.product_variant_id)\
         .filter(
             or_(
                 ProductVariant.is_active == True,
                 MainWarehouse.available_quantity_packs > 0,
                 MainWarehouse.reserved_quantity_packs > 0,
                 vehicle_load_subq.c.total_vehicle_cartons > 0,
                 session_inv_subq.c.total_session_packs > 0,
                 damaged_subq.c.total_damaged > 0
             )
         )

        # جلب النتائج بضربة واحدة (O(1))
        all_inventory_rows = (await db.execute(stmt)).all()

        result = []
        for row in all_inventory_rows:
            variant = row.ProductVariant
            wh = row.MainWarehouse
            total_damaged = row.total_damaged
            veh_cartons = row.total_vehicle_cartons
            sess_packs = row.total_session_packs
            pending_pulls = row.total_pulls

            # +++ حماية Pydantic من الـ Decimal Division Crash (تغليف بـ int إجباري) +++
            avail = int(wh.available_quantity_packs) if wh and wh.available_quantity_packs else 0
            res = int(wh.reserved_quantity_packs) if wh and wh.reserved_quantity_packs else 0
            damaged = int(total_damaged) if total_damaged else 0
            ppc = int(variant.packs_per_carton) if variant.packs_per_carton else 1
            
            # عرض السحوبات المعلقة للمشرف כאילו هي قيد النقل (Virtual Reserved)
            virtual_res = res + abs(int(pending_pulls or 0))
            
            # تجميع الأصول الحقيقية للشركة
            veh_packs_total = int(veh_cartons or 0) * ppc
            sess_packs_total = int(sess_packs or 0)
            
            # إجمالي الأصول = متاح بالمستودع + محجوز (قيد النقل) + سيارات نائمة + مناديب بالشارع
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
                "min_threshold": int(wh.min_threshold_packs) if wh and wh.min_threshold_packs else 0
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
    skip: int = 0, # +++ البداية (Pagination) +++
    limit: int = 500, # +++ عدد السجلات للـ Page الواحدة +++
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin)
):
    
    
    try:
        # +++ النسف المعماري لـ N+1 مع Pagination حقيقي يحمي الذاكرة ولا يعمي المحاسب +++
        safe_limit = min(limit, 1000) # +++ الدرع الفولاذي: حماية الـ RAM من الانفجار بحد أقصى إجباري +++
        stmt = select(WarehouseLedger).options(
            joinedload(WarehouseLedger.product_variant), 
            joinedload(WarehouseLedger.admin)
        ).order_by(WarehouseLedger.created_at.desc()).offset(skip).limit(safe_limit)
        
        logs = (await db.execute(stmt)).scalars().all()
        
        result = []
        for log in logs:
            variant = log.product_variant
            admin = log.admin
            ppc = int(variant.packs_per_carton) if variant and variant.packs_per_carton else 1
            
            # +++ الدرع المحاسبي: حساب الرصيد السابق بناءً على نوع الحركة (لأن الإشارات تتغير حسب نوع السحب والإضافة) +++
            # CS-WH-05 / warehouse.md Finding #7: Explicit whitelist instead of catch-all else
            DECREASE_TYPES = {'DISPATCH_LOAD', 'HANDSHAKE_RESERVE'}
            NEUTRAL_TYPES = {'HANDSHAKE_COMMIT'}
            INCREASE_TYPES = {
                'INBOUND_SUPPLIER', 'INBOUND_CORRECTION', 'AUDIT_ADJUSTMENT',
                'DISPATCH_UNLOAD', 'DISPATCH_UNLOAD_FALLBACK', 'VEHICLE_ROLLOVER',
                'END_DAY_CLEARANCE'
            }
            if log.transaction_type in DECREASE_TYPES:
                bal_before = log.balance_after_packs + log.quantity_packs
            elif log.transaction_type in NEUTRAL_TYPES:
                bal_before = log.balance_after_packs
            elif log.transaction_type in INCREASE_TYPES:
                bal_before = log.balance_after_packs - log.quantity_packs
            else:
                bal_before = None
                logger.warning(f"Unknown ledger transaction_type '{log.transaction_type}' (entry id={log.id}) — balance_before could not be safely reconstructed.")

            result.append({
                "id": log.id,
                "product_name": variant.variant_name if variant else "غير معروف",
                "packs_per_carton": ppc,
                "type": log.transaction_type,
                "quantity_packs": log.quantity_packs,
                "balance_before": bal_before,
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
    
    
    stmt = select(SystemSetting).filter_by(setting_key='warehouse_status')
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
        # 1. التزويد الآلي للمنتج الأب (Base Product Auto-Provisioning)
        stmt_product = select(Product).limit(1)
        base_product = (await db.execute(stmt_product)).scalars().first()
        if not base_product:
            base_product = Product(base_name="General Category")
            db.add(base_product)
            await db.flush()

        # إنشاء المنتج الجديد
        new_variant = ProductVariant(
            product_id=base_product.id,
            variant_name=payload.variant_name.strip(),
            sku=payload.sku.strip() if payload.sku else None,
            price_per_carton=payload.price_per_carton,
            packs_per_carton=payload.packs_per_carton,
            price_per_pack=payload.price_per_pack,
            default_max_samples_per_day=payload.default_max_samples_per_day,
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
            min_threshold_packs=payload.min_threshold_packs
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
        # +++ درع إضافي: توثيق محاولة التلاعب في حال كانت كلمة السر خاطئة +++
        audit = SystemAuditLog(
            admin_id=current_admin.id, target_id=f"Ledger_{entry_id}",
            action_type='UNAUTHORIZED_ADJUSTMENT', old_value='Wrong Password', new_value='Rejected'
        )
        db.add(audit)
        await db.commit()
        raise HTTPException(status_code=403, detail="كلمة المرور غير صحيحة. تم رفض العملية وتوثيق المحاولة.")

    try:
        # 2. جلب الحركة الأصلية 
        original_entry = await db.get(WarehouseLedger, entry_id)
        if not original_entry:
            raise HTTPException(status_code=404, detail="الحركة غير موجودة.")
            
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
        if ref_id and ref_id.strip() and ref_id != "بدون فاتورة":
            stmt_sum = select(func.sum(WarehouseLedger.quantity_packs)).filter(
                WarehouseLedger.reference_id == ref_id,
                WarehouseLedger.product_variant_id == original_entry.product_variant_id,
                WarehouseLedger.transaction_type.in_(['INBOUND_SUPPLIER', 'INBOUND_CORRECTION'])
            )
            current_invoice_total_packs = (await db.execute(stmt_sum)).scalar() or 0
        else:
            current_invoice_total_packs = original_entry.quantity_packs

        delta = int(payload.new_total_packs) - int(current_invoice_total_packs)

        if delta == 0:
            return {"message": "لا يوجد تغيير في الكمية. الصافي الحالي مطابق لما أدخلته."}

        # 4. جلب المنتج وقفله للتحديث (Row-level lock) بترتيب هرمي لمنع الـ Deadlock
        stmt_variant = select(ProductVariant).with_for_update().filter_by(id=original_entry.product_variant_id)
        variant = (await db.execute(stmt_variant)).scalar_one_or_none()
        if not variant:
            await db.rollback() # +++ الدرع الفولاذي: تحرير القفل لإنقاذ السيرفر +++
            raise HTTPException(status_code=404, detail="المنتج غير موجود.")

        # 5. تحديث الرصيد الحالي للمستودع (منع الرصيد السالب)
        if wh_record.available_quantity_packs + delta < 0:
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"فشل التعديل: الكمية المخصومة ({abs(delta)}) أكبر من المتوفر بالمستودع ({wh_record.available_quantity_packs}).")

        old_balance = wh_record.available_quantity_packs or 0  # <--- حفظ الرصيد القديم
        wh_record.available_quantity_packs += delta

        # 6. تسجيل الحركة العكسية (Inbound Correction) لضبط الدفاتر بنفس رقم المرجع
        adjustment_entry = WarehouseLedger(
            product_variant_id=variant.id,
            quantity_packs=delta,
            balance_before_packs=old_balance,  # <--- إضافة الحقل
            balance_after_packs=wh_record.available_quantity_packs,
            transaction_type='INBOUND_CORRECTION',
            admin_id=current_admin.id,
            reference_id=original_entry.reference_id,
            notes=f"تعديل لفاتورة المورد: {payload.notes}"
        )
        
        db.add(adjustment_entry)
        await db.commit()
        
        return {"message": f"تم تسجيل التعديل بنجاح. الفرق المحاسبي: {'+' if delta>0 else ''}{delta} حبة."}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"خطأ في العملية: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء معالجة التعديل.")