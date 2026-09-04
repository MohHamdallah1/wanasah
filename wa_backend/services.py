import os
from config import Config
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.dialects.postgresql import insert
from models import SystemSetting, OfferRule, Driver, Shop, WorkSession, SessionInventory, ProductVariant, InventoryLedger, MainWarehouse, WarehouseLedger, InventoryLock
from typing import Any, Type, Optional, List, Dict, Tuple

async def get_setting(db_session: AsyncSession, key: str, default_value: Any, value_type: Type = str) -> Any:
    """جلب الإعدادات العامة مع حماية الـ 500 Crash من الـ Decimal InvalidOperation"""
    stmt = select(SystemSetting).filter_by(setting_key=key)
    result = await db_session.execute(stmt)
    setting = result.scalar_one_or_none()
    
    if not setting: return default_value
    try: 
        return value_type(setting.setting_value)
    except Exception: # +++ الدرع الفولاذي: التقاط جميع الانفجارات التحويلية +++
        return default_value

def calculate_invoice( # +++  لتلوث الـ Event Loop: تحويلها لدالة رياضية صريحة +++
    cartons_qty: int, 
    packs_qty: int, 
    price_per_carton: Decimal, 
    price_per_pack: Decimal, 
    pre_fetched_tax: Optional[Decimal] = None, 
    active_offers: Optional[List[OfferRule]] = None,
    packs_per_carton: int = 1,
    variant_id: Optional[int] = None # +++ إضافة معرّف المنتج لفلترة العروض +++
) -> Dict[str, Any]:
    """حساب الفاتورة المالي النقي (محصن ضد كراش العينات المجانية)"""
    _ZERO_RESULT = {'base_amount': Decimal('0.000'), 'discount_applied': Decimal('0.000'), 'tax_amount': Decimal('0.000'), 'final_amount': Decimal('0.000'), 'bonus_units': 0}
    
    try:
        c_qty = int(cartons_qty)
        p_qty = int(packs_qty)
        # +++   استخدام 'or' لمنع تمرير أي قيم سالبة منفردة +++
        if c_qty < 0 or p_qty < 0 or (c_qty == 0 and p_qty == 0): 
            return _ZERO_RESULT
    except (ValueError, TypeError):
        return _ZERO_RESULT

    c_price = Decimal(str(price_per_carton or '0.0'))
    p_price = Decimal(str(price_per_pack or '0.0'))
    
    # +++  لقنبلة הـ N+1 (Pure Function Enforcement) +++
    if pre_fetched_tax is None:
        raise ValueError("هندسة مرفوضة: يجب جلب الضريبة مسبقاً وتمريرها للدالة الرياضية لمنع استنزاف قاعدة البيانات.")
    tax_pct = Decimal(str(pre_fetched_tax))
        
    # +++ الدرع العُماني: 3 خانات عشرية لمنع التهرب الضريبي +++
    THREE_PLACES = Decimal('0.001')

    base_amount = (Decimal(str(c_qty)) * c_price) + (Decimal(str(p_qty)) * p_price)
    discount_value = Decimal('0.0')
    bonus_cartons = 0

    # +++ دمج الكميات (كراتين + حبات) لمعرفة الحجم الحقيقي للمبيعات ومنع ضياع العروض +++
    safe_ppc = packs_per_carton if packs_per_carton > 0 else 1
    total_equivalent_cartons = c_qty + (p_qty // safe_ppc)

    best_offer = None
    if active_offers is None:
        raise ValueError("هندسة مرفوضة: يجب جلب العروض النشطة مسبقاً وتمريرها كقائمة لمنع استنزاف قاعدة البيانات (N+1).")
        
    # +++   فلترة العروض المرتبطة بهذا المنتج فقط (أو العروض العامة)، والتأكد من نشاطها +++
    valid_offers = [
        o for o in active_offers 
        if (o.product_variant_id is None or o.product_variant_id == variant_id) 
        and getattr(o, 'is_active', True)
        and o.threshold_quantity <= total_equivalent_cartons
    ]
    if valid_offers:
        best_offer = sorted(valid_offers, key=lambda x: x.threshold_quantity, reverse=True)[0]

    if best_offer and best_offer.threshold_quantity > 0:
        multiplier = total_equivalent_cartons // best_offer.threshold_quantity
        if best_offer.offer_type == 'free_items':
            bonus_cartons = multiplier * best_offer.bonus_quantity
        elif best_offer.offer_type == 'fixed_discount':
            discount_value = Decimal(str(best_offer.discount_value)) * Decimal(str(multiplier))
        elif best_offer.offer_type == 'percentage_discount':
            # +++  الخصم يُحسب على كامل المبلغ الأساسي +++
            discount_value = base_amount * (Decimal(str(best_offer.discount_value)) / Decimal('100'))

    # +++ الدرع المحاسبي: الخصم المطبق لا يمكن أن يتجاوز قيمة الفاتورة لمنع تشويه تقارير الأرباح والخسائر +++
    actual_discount_applied = min(base_amount, discount_value)
    amount_after_discount = base_amount - actual_discount_applied
    
    tax_amount = amount_after_discount * (tax_pct / Decimal('100'))
    final_amount = amount_after_discount + tax_amount

    # +++ نسف تسريب الدقة (The Float Leak): إرجاع Decimal نقي للعمليات المحاسبية +++
    return {
        'base_amount': base_amount.quantize(THREE_PLACES, rounding=ROUND_HALF_UP),
        'discount_applied': actual_discount_applied.quantize(THREE_PLACES, rounding=ROUND_HALF_UP),
        'tax_amount': tax_amount.quantize(THREE_PLACES, rounding=ROUND_HALF_UP),
        'final_amount': final_amount.quantize(THREE_PLACES, rounding=ROUND_HALF_UP),
        'bonus_units': bonus_cartons
    }

async def check_debt_limits(
    db_session: AsyncSession, 
    driver_id: int, 
    shop_id: int, 
    new_debt_amount: Decimal, 
    pre_fetched_driver: Optional[Driver] = None, 
    pre_fetched_shop: Optional[Shop] = None
) -> Tuple[bool, str]:
    """التحقق من سقف الذمم (محصن ضد الـ Phantom Reads والـ Race Conditions)"""
    new_debt = Decimal(str(new_debt_amount))
    if new_debt <= Decimal('0'): return True, ""

    driver = pre_fetched_driver or await db_session.get(Driver, driver_id)
    
    # +++  لقنبلة الـ Race Condition (Phantom Read Lock) +++
    # تم إعدام الاعتماد على pre_fetched_shop لأنه يكسر الـ with_for_update() ويسمح بتجاوز السقف المالي
    stmt = select(Shop).with_for_update().filter_by(id=shop_id)
    shop = (await db_session.execute(stmt)).scalar_one_or_none()

    if not driver or not shop: return False, "المندوب أو المحل غير موجود."
    if not getattr(driver, 'can_allow_debt', False): return False, "غير مصرح لك بإعطاء ذمم للمحلات."

    max_limit = Decimal(str(shop.max_debt_limit or '0.0'))
    if max_limit <= Decimal('0'): return False, "هذا المحل غير مصرح له بفتح ذمم (السقف صفر)."

    current_bal = Decimal(str(shop.current_balance or '0.0'))
    if current_bal + new_debt > max_limit:
        return False, f"مرفوض. سقف الذمة ({max_limit})، والرصيد سيصبح ({current_bal + new_debt})."

    return True, ""

async def adjust_inventory(
    db_session: AsyncSession, 
    session_id: int, 
    variant_id: int, 
    net_quantity_change_in_packs: int, 
    admin_id: int, 
    transaction_type: str, 
    notes: str, 
    vehicle_id: Optional[int] = None, 
    pre_locked_inventory_record: Optional[SessionInventory] = None,
    pre_locked_warehouse_record: Optional[MainWarehouse] = None # +++ توحيد الـ Warehouse Logic +++
) -> Tuple[bool, str]:
    """تعديل الجرد الفولاذي الشامل (Single Source of Truth) - يربط العهدة والمستودع معاً"""
    if net_quantity_change_in_packs == 0: return True, ""

    # 1. تحديث المستودع (إجباري لمنع تسرب المخزون أو خلق بضاعة من العدم)
    wh_record = pre_locked_warehouse_record
    if not wh_record:
        # إذا لم يمرر المبرمج المستودع، نقوم نحن بجلبه وقفله قسرياً لحماية الجرد
        stmt = select(MainWarehouse).with_for_update().filter_by(product_variant_id=variant_id)
        wh_record = (await db_session.execute(stmt)).scalar_one_or_none()
        if not wh_record:
            return False, "فشل: الصنف غير موجود في المستودع الرئيسي."

    old_wh_balance = wh_record.available_quantity_packs or 0
    
    # إذا كنا نضيف للمندوب (يعني نسحب من المستودع)
    if net_quantity_change_in_packs > 0:
        if (wh_record.available_quantity_packs or 0) < net_quantity_change_in_packs:
            return False, f"فشل: رصيد المستودع لا يغطي صرف {net_quantity_change_in_packs} حبة."
        wh_record.available_quantity_packs = (wh_record.available_quantity_packs or 0) - net_quantity_change_in_packs
    else:
        # إذا كنا نسحب من المندوب (يعني نرجع للمستودع)
        wh_record.available_quantity_packs += abs(net_quantity_change_in_packs)
        
    db_session.add(WarehouseLedger(
        product_variant_id=variant_id, 
        transaction_type=transaction_type + '_WH',
        quantity_packs=abs(net_quantity_change_in_packs),
        balance_before_packs=old_wh_balance,
        balance_after_packs=wh_record.available_quantity_packs,
        admin_id=admin_id, reference_id=f"SESS_{session_id}", notes=notes
    ))

    # 2. تحديث عهدة المندوب
    if not pre_locked_inventory_record:
        insert_stmt = insert(SessionInventory).values(
            work_session_id=session_id, product_variant_id=variant_id,
            starting_quantity=0, net_transfers=0, current_remaining_quantity=0
        ).on_conflict_do_nothing(index_elements=['work_session_id', 'product_variant_id'])
        await db_session.execute(insert_stmt)

        stmt = select(SessionInventory).filter_by(
            work_session_id=session_id, product_variant_id=variant_id
        ).with_for_update()
        inventory_record = (await db_session.execute(stmt)).scalar_one()
    else:
        inventory_record = pre_locked_inventory_record

    expected_qty = inventory_record.current_remaining_quantity
    if expected_qty + net_quantity_change_in_packs < 0:
        return False, "الكمية المتبقية في العهدة لا تغطي عملية السحب."

    inventory_record.current_remaining_quantity += net_quantity_change_in_packs
    inventory_record.net_transfers = (inventory_record.net_transfers or 0) + net_quantity_change_in_packs
    
    db_session.add(InventoryLedger(
        work_session_id=session_id, vehicle_id=vehicle_id, product_variant_id=variant_id,
        transaction_type=transaction_type, expected_quantity=expected_qty,
        actual_quantity=inventory_record.current_remaining_quantity, difference=net_quantity_change_in_packs,
        admin_id=admin_id, notes=notes
    ))
    return True, ""


def format_qty(total_packs: int, packs_per_carton: int) -> str:
    """دالة التصفيح المحاسبي: تحويل الحبات لنص بشري (كراتين وحبات) مع الحفاظ على الإشارة السالبة"""
    if not packs_per_carton or packs_per_carton <= 1:
        return f"{total_packs} حبة"
    
    is_negative = int(total_packs) < 0
    abs_total = abs(int(total_packs))
    cartons, packs = divmod(abs_total, packs_per_carton)
    
    parts = []
    if cartons > 0:
        parts.append(f"{cartons} كرتونة")
    if packs > 0:
        parts.append(f"{packs} حبة")
    
    res = " و ".join(parts) if parts else "0 حبة"
    return f"-{res}" if is_negative and res != "0 حبة" else res


class InventoryReversalError(Exception):
    """خطأ مخصص لالتقاط فشل استرجاع العهدة دون التسبب بـ 500 Crash"""
    pass

async def reverse_previous_visit_state(
    db_session: AsyncSession, 
    visit: Any, 
    active_session: Optional[WorkSession], 
    shop: Shop,
    admin_id: int, # +++ الدرع الجنائي: توثيق من قام بالتراجع حقاً لمنع التزوير في الدفاتر +++
    vehicle_id: Optional[int] = None 
) -> None:
    """
    خدمة التراجع المستقلة (Reversal Service - Elite Version)
    محصنة ضد N+1، Lazy Loading، و Decimal TypeErrors.
    """
    # ==========================================
    # 0. الفحص المالي الاستباقي (Pre-Flight Financial Check)
    # نسف ثغرة الفساد المحاسبي: الفحص قبل أي تعديل على الداتابيز
    # ==========================================
    old_cash = Decimal(str(visit.cash_collected or '0.0'))
    old_debt_paid = Decimal(str(visit.debt_paid or '0.0'))
    
    if old_cash > Decimal('0') or old_debt_paid > Decimal('0'):
        raise InventoryReversalError(
            f"مرفوض أمنياً ومحاسبياً: لا يمكن التراجع عن زيارة تم فيها تحصيل كاش ({old_cash}) أو سداد ذمة ({old_debt_paid}). "
            "يجب إصدار 'قيد عكسي' (Credit Note) للحفاظ على التسلسل المالي ومنع الاختلاس."
        )

    current_bal = Decimal(str(shop.current_balance or '0.0'))
    net_visit_debt = Decimal(str(visit.final_amount_due or '0.0')) - old_cash
    
    new_balance = current_bal - net_visit_debt + old_debt_paid
    
    if new_balance < Decimal('0'):
        raise InventoryReversalError(f"فشل التراجع: رصيد المحل الحالي ({current_bal}) لا يغطي الديون المسجلة بالزيارة. التراجع سيجعل الرصيد بالسالب (المحل سدد ذمته لاحقاً)!")

    # ==========================================
    # 1. الدرع المعماري الشامل (Mega-Lock & IO Optimization)
    # نسف الـ Cross-Query Deadlock عن طريق دمج الاستعلامات
    # ==========================================
    item_variant_ids = [i.product_variant_id for i in visit.items if not getattr(i, 'is_cancelled', False)] if visit.outcome in ['Sale', 'NoSale'] else []
    ret_variant_ids = [r.product_variant_id for r in visit.returns if not getattr(r, 'is_cancelled', False)]
    
    # دمج الـ IDs وإزالة التكرار لعمل قفل واحد هرمي يمنع الـ Deadlock تماماً
    all_variant_ids = list(set(item_variant_ids + ret_variant_ids))
    
    locked_inv = {}
    bulk_variants = {}
    
    if active_session and all_variant_ids:
        # قفل موحد ومرتب تصاعدياً (The Ultimate Deadlock Shield)
        stmt_inv = select(SessionInventory).with_for_update().filter(
            SessionInventory.work_session_id == active_session.id,
            SessionInventory.product_variant_id.in_(all_variant_ids)
        ).order_by(SessionInventory.product_variant_id.asc())
        locked_inv = {inv.product_variant_id: inv for inv in (await db_session.execute(stmt_inv)).scalars().all()}

        # جلب تفاصيل المنتجات بضربة واحدة لتقليل הـ I/O بنسبة 50%
        stmt_vars = select(ProductVariant).filter(ProductVariant.id.in_(all_variant_ids))
        bulk_variants = {v.id: v for v in (await db_session.execute(stmt_vars)).scalars().all()}

    # ==========================================
    # 2. التراجع المستودعي للمبيعات والعينات
    # ==========================================
    if visit.outcome in ['Sale', 'NoSale']:
        for item in visit.items:
            if getattr(item, 'is_cancelled', False): continue
            
            variant = bulk_variants.get(item.product_variant_id)
            safe_packs = variant.packs_per_carton if variant and variant.packs_per_carton else 1
            
            # +++   حماية السيرفر من الانفجار بسبب الـ NoneType في حقول البونص والعينات +++
            safe_bonus = item.bonus_quantity or 0
            safe_sample = item.sample_quantity or 0
            # +++ الدرع الفولاذي (إصلاح البوت): استخدام or 0 لسحق الـ None العائد من قاعدة البيانات +++
            packs_to_return = ((item.quantity + safe_bonus + safe_sample) * safe_packs) + (getattr(item, 'packs_quantity', 0) or 0) + (getattr(item, 'sample_packs_quantity', 0) or 0)
            
            if active_session:
                inv_record = locked_inv.get(item.product_variant_id)
                expected_qty = inv_record.current_remaining_quantity if inv_record else 0
                
                if inv_record:
                    inv_record.current_remaining_quantity += packs_to_return
                else:
                    # +++ الدرع الرقابي: جرد الصباح صفر إجباري لكي لا نطمس الفروقات عن عين المحاسب +++
                    inv_record = SessionInventory(work_session_id=active_session.id, product_variant_id=item.product_variant_id, starting_quantity=0, net_transfers=0, current_remaining_quantity=packs_to_return)
                    db_session.add(inv_record)
                    locked_inv[item.product_variant_id] = inv_record 
                    
                db_session.add(InventoryLedger(
                    work_session_id=active_session.id, driver_id=visit.driver_id,
                    vehicle_id=vehicle_id, 
                    product_variant_id=item.product_variant_id, transaction_type='Adjustment (Reversal)',
                    expected_quantity=expected_qty, actual_quantity=expected_qty + packs_to_return,
                    difference=packs_to_return, admin_id=admin_id, notes=f"إلغاء بيع سابق للمحل: {shop.name}"
                ))
            
            # +++ سحق كارثة الإزاحة: محاذاة صارمة داخل حلقة for +++
            item.is_cancelled = True 

    # ==========================================
    # 3. التراجع المستودعي للمرتجعات (إعادة ضبط العهدة بدقة)
    # ==========================================
    for ret in visit.returns:
        if getattr(ret, 'is_cancelled', False): continue 
        
        if active_session:
            ret_variant = bulk_variants.get(ret.product_variant_id)
            safe_packs = ret_variant.packs_per_carton if ret_variant and ret_variant.packs_per_carton else 1
            # +++ الدرع الفولاذي (إصلاح البوت): استخدام or 0 لسحق الـ None العائد من قاعدة البيانات +++
            total_ret_packs = (ret.quantity * safe_packs) + (getattr(ret, 'packs_quantity', 0) or 0)
            
            inv_record = locked_inv.get(ret.product_variant_id)
            if not inv_record:
                # +++ الدرع الرقابي: جرد الصباح صفر إجباري لكي لا نطمس الفروقات عن عين المحاسب +++
                inv_record = SessionInventory(work_session_id=active_session.id, product_variant_id=ret.product_variant_id, starting_quantity=0, net_transfers=0, current_remaining_quantity=0)
                db_session.add(inv_record)
                locked_inv[ret.product_variant_id] = inv_record

            expected_qty = inv_record.current_remaining_quantity
            is_sellable = ret.return_type not in ['Expired', 'Damaged', 'Factory_Defect']

            if is_sellable:
                # مرتجع صالح: تم إضافته لعهدة المندوب أثناء الزيارة، فعند التراجع نسحبه منه
                if inv_record.current_remaining_quantity < total_ret_packs:
                    raise InventoryReversalError(f"لا يمكن التراجع! المندوب قام ببيع جزء من هذا المرتجع ولا يملك رصيداً كافياً لإعادته. المطلوب: {total_ret_packs}، المتاح: {inv_record.current_remaining_quantity}")

                inv_record.current_remaining_quantity -= total_ret_packs
                diff = -total_ret_packs
                note_text = "عكس مرتجع صالح: سحب من عهدة المندوب"
            else:
                # مرتجع تالف (استبدال 1:1): تم سحب بضاعة صالحة من المندوب أثناء الزيارة، فعند التراجع نعيدها لعهدته
                inv_record.current_remaining_quantity += total_ret_packs
                diff = total_ret_packs
                note_text = "عكس استبدال توالف: إعادة البضاعة الصالحة لعهدة المندوب"

            db_session.add(InventoryLedger(
                work_session_id=active_session.id, driver_id=visit.driver_id,
                vehicle_id=vehicle_id, 
                product_variant_id=ret.product_variant_id, transaction_type='Adjustment (Reversal Return)',
                expected_quantity=expected_qty, 
                actual_quantity=inv_record.current_remaining_quantity,
                difference=diff, 
                admin_id=admin_id, 
                notes=f"{note_text} للمحل: {shop.name}"
            ))
        ret.is_cancelled = True

    # ==========================================
    # 4. التراجع المالي الشامل
    # ==========================================
    # تطبيق التعديلات المالية التي تم فحصها مسبقاً في بداية الدالة
    shop.current_balance = new_balance

    # تصفير العدادات المالية للزيارة بشكل آمن محاسبياً
    visit.amount_before_tax_and_discount = Decimal('0.0')
    visit.discount_applied = Decimal('0.0')
    visit.tax_amount = Decimal('0.0')
    visit.final_amount_due = Decimal('0.0')
    visit.cash_collected = Decimal('0.0')
    visit.debt_paid = Decimal('0.0')
    visit.shop_balance_before = None
    visit.shop_balance_after = None
    visit.tax_qr_code = None

    # إرجاع لحالة الانتظار
    visit.outcome = 'Pending'
    visit.status = 'Pending'

# =================================================================================
# [المرحلة الثالثة] البند 5: Isolation Middleware (درع البنية التحتية للـ SaaS)
# =================================================================================

def get_tenant_cache_key(company_id: int, base_key: str) -> str:
    if not company_id:
        raise ValueError("خطأ أمني: لا يمكن الوصول للكاش بدون company_id")
    return f"tenant_{int(company_id)}:{base_key}"

def get_tenant_storage_path(company_id: int, filename: str) -> str:
    """
    (Storage Isolation): يوجه الملفات لمسار آمن ومحصن ضد هجمات (Path Traversal).
    ملاحظة: إنشاء المجلد (os.makedirs) يجب أن يتم في مسار الـ Upload النهائي (Async) وليس هنا لمنع خنق السيرفر.
    """
    try:
        comp_id = int(company_id)
    except (ValueError, TypeError):
        raise ValueError("خطأ أمني: رمز الشركة غير صالح.")
        
    if not filename or not isinstance(filename, str):
        raise ValueError("خطأ أمني: اسم الملف غير صالح.")

    # الدرع الأول: سحق أي مسار خبيث (../ أو /absolute/) واستخراج اسم الملف النقي
    safe_filename = os.path.basename(filename)
    if not safe_filename or safe_filename == '.' or safe_filename == '..':
        raise ValueError("خطأ أمني: محاولة اختراق مسار الملف.")
    
    base_path = getattr(Config, 'STORAGE_BASE_PATH', 'local_storage/')
    tenant_folder = os.path.join(base_path, f"company_{comp_id}")
    target_path = os.path.join(tenant_folder, safe_filename)
    
    # الدرع الثاني (Defense-in-Depth): التأكد النهائي أن المسار الناتج يقع حصراً داخل مجلد الشركة
    if not os.path.abspath(target_path).startswith(os.path.abspath(tenant_folder) + os.sep):
        raise ValueError("خطأ أمني: مسار الملف يقع خارج النطاق المسموح للشركة.")
        
    return target_path
    
def enforce_tenant_background_job(company_id: int, **kwargs) -> dict:
    try:
        comp_id = int(company_id)
    except (ValueError, TypeError):
        raise ValueError("خطأ أمني: لا يمكن إرسال مهمة خلفية بدون رمز شركة صالح.")
    
    kwargs['company_id'] = comp_id
    return kwargs

async def check_inventory_lock(db_session: AsyncSession, company_id: int, location_id: int, variant_id: Optional[int] = None, batch_id: Optional[int] = None):
    """
    (P0 Fixed): حارس الأقفال الجراحية المركزي.
    يُسقط أي عملية (في النظام القديم أو الجديد) إذا كان الموقع/الصنف تحت الجرد.
    """
    stmt_full = select(InventoryLock.id).filter_by(
        company_id=company_id, location_id=location_id, product_variant_id=None, released_at=None
    )
    if (await db_session.execute(stmt_full)).first():
        raise ValueError(f"الموقع ({location_id}) تحت الجرد الشامل ومقفل بالكامل.")
        
    if variant_id:
        from sqlalchemy import or_
        stmt_partial = select(InventoryLock.id).filter(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == location_id,
            InventoryLock.product_variant_id == variant_id,
            InventoryLock.released_at.is_(None)
        )
        if batch_id:
            stmt_partial = stmt_partial.filter(or_(InventoryLock.batch_id == batch_id, InventoryLock.batch_id.is_(None)))
            
        if (await db_session.execute(stmt_partial)).first():
            raise ValueError(f"الصنف/الدفعة مقفل جراحياً بسبب جرد دوري نشط.")