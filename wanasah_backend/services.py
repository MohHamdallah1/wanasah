import math
from models import db, SystemSetting, OfferRule, Driver, Shop, WorkSession, SessionInventory, ProductVariant
from decimal import Decimal, ROUND_HALF_UP

def get_setting(key, default_value, value_type=str):
    """جلب الإعدادات العامة من قاعدة البيانات"""
    setting = SystemSetting.query.filter_by(setting_key=key).first()
    if not setting: return default_value
    try: return value_type(setting.setting_value)
    except ValueError: return default_value

def calculate_invoice(cartons_qty, packs_qty, price_per_carton, price_per_pack):
    """حساب الفاتورة المالي الصارم (يدعم الكراتين وحبات الفرط، ويرجع floats للواجهة)"""
    try:
        c_qty = int(cartons_qty)
        p_qty = int(packs_qty)
        if c_qty <= 0 and p_qty <= 0: return None
    except (ValueError, TypeError):
        return None

    # 1. تحضير المتغيرات المالية الدقيقة بالـ Decimal
    c_price = Decimal(str(price_per_carton or '0.0'))
    p_price = Decimal(str(price_per_pack or '0.0'))
    tax_pct = Decimal(str(get_setting('tax_percentage', '0.0')))
    TWO_PLACES = Decimal('0.01')

    # 2. الحسابات الأساسية (مجموع الكراتين + مجموع الفرط)
    base_amount = (Decimal(str(c_qty)) * c_price) + (Decimal(str(p_qty)) * p_price)
    discount_value = Decimal('0.0')
    bonus_cartons = 0

    # 3. محرك العروض المعقد (يطبق على كمية الكراتين)
    best_offer = OfferRule.query.filter(
        OfferRule.is_active == True,
        OfferRule.threshold_quantity <= c_qty
    ).order_by(OfferRule.threshold_quantity.desc()).first()

    if best_offer:
        if best_offer.offer_type == 'free_items':
            multiplier = c_qty // best_offer.threshold_quantity
            bonus_cartons = multiplier * best_offer.bonus_quantity
            
        elif best_offer.offer_type == 'fixed_discount':
            multiplier = c_qty // best_offer.threshold_quantity
            discount_value = Decimal(str(best_offer.discount_value)) * Decimal(str(multiplier))
            
        elif best_offer.offer_type == 'percentage_discount':
            discount_value = base_amount * (Decimal(str(best_offer.discount_value)) / Decimal('100'))

    # 4. حساب الصافي والضريبة
    amount_after_discount = base_amount - discount_value
    if amount_after_discount < Decimal('0.0'): amount_after_discount = Decimal('0.0')
    
    tax_amount = amount_after_discount * (tax_pct / Decimal('100'))
    final_amount = amount_after_discount + tax_amount

    # 5. إرجاع القاموس (Dictionary) بقيم float توافقاً مع JSON وفلاتر
    return {
        'base_amount': float(base_amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)),
        'discount_applied': float(discount_value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)),
        'tax_amount': float(tax_amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)),
        'final_amount': float(final_amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)),
        'bonus_units': bonus_cartons
    }

def check_debt_limits(driver_id, shop_id, new_debt_amount):
    """التحقق من سقف الذمم (استخدام Decimal حصراً لمنع أخطاء النوع)"""
    new_debt = Decimal(str(new_debt_amount))
    if new_debt <= Decimal('0'):
        return True, ""

    driver = db.session.get(Driver, driver_id)
    shop = db.session.get(Shop, shop_id)

    if not driver or not shop: return False, "المندوب أو المحل غير موجود."
    if not driver.can_allow_debt: return False, "غير مصرح لك بإعطاء ذمم للمحلات."

    max_limit = Decimal(str(shop.max_debt_limit or '0.0'))
    if max_limit <= Decimal('0'): return False, "هذا المحل غير مصرح له بفتح ذمم (السقف صفر)."

    current_bal = Decimal(str(shop.current_balance or '0.0'))
    expected_balance = current_bal + new_debt
    
    if expected_balance > max_limit:
        return False, f"مرفوض. سقف الذمة ({max_limit})، والرصيد سيصبح ({expected_balance})."

    return True, ""

def adjust_inventory(session_id, variant_id, net_quantity_change_in_packs):
    """
    تعديل الجرد بناءً على إجمالي عدد (الحبات/Packs).
    قاعدة معمارية: يُمنع استخدام db.session.commit() هنا للحفاظ على وحدة المعاملة (Atomicity).
    """
    if net_quantity_change_in_packs == 0:
        return True, ""

    # استخدام with_for_update() لعمل قفل حصري للصف (Row-level lock) لمنع أخطاء السباق الزمني
    inventory_record = SessionInventory.query.filter_by(
        work_session_id=session_id, 
        product_variant_id=variant_id
    ).with_for_update().first()

    if not inventory_record:
        if net_quantity_change_in_packs < 0:
            return False, "لا يوجد مخزون من هذا المنتج في سيارتك حالياً."
        inventory_record = SessionInventory(
            work_session_id=session_id, product_variant_id=variant_id,
            starting_quantity=0,
            current_remaining_quantity=0
        )
        db.session.add(inventory_record)

    final_quantity = inventory_record.current_remaining_quantity + net_quantity_change_in_packs

    if final_quantity < 0:
        return False, f"الكمية المطلوبة غير متوفرة. المتبقي لديك لا يغطي هذه العملية."

    inventory_record.current_remaining_quantity = final_quantity
    # لا يوجد Commit هنا! يتم الاعتماد على الـ Commit الرئيسي في مسار الفاتورة.
    return True, ""