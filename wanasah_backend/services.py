import math
from models import db, SystemSetting, OfferRule, Driver, Shop, WorkSession, SessionInventory, ProductVariant

def get_setting(key, default_value, value_type=str):
    """جلب الإعدادات العامة من قاعدة البيانات"""
    setting = SystemSetting.query.filter_by(setting_key=key).first()
    if not setting:
        return default_value
    try:
        return value_type(setting.setting_value)
    except ValueError:
        return default_value

def calculate_invoice(quantity, price_per_unit):
    """حساب تفاصيل الفاتورة الشاملة (بضاعة، خصومات، ضريبة، بونص مجاني)"""
    if quantity <= 0:
        return None

    tax_percentage = get_setting('tax_percentage', 0.0, float)
    base_amount = quantity * price_per_unit
    discount_value = 0.0
    bonus_units = 0

    best_offer = OfferRule.query.filter(
        OfferRule.is_active == True,
        OfferRule.threshold_quantity <= quantity
    ).order_by(OfferRule.threshold_quantity.desc()).first()

    if best_offer:
        num_tiers = quantity // best_offer.threshold_quantity
        if best_offer.offer_type == 'free_items':
            bonus_units = num_tiers * best_offer.bonus_quantity
        elif best_offer.offer_type == 'fixed_discount':
            discount_value = num_tiers * best_offer.discount_value
        elif best_offer.offer_type == 'percentage_discount':
            discount_value = base_amount * (best_offer.discount_value / 100.0)

    amount_after_discount = base_amount - discount_value
    if amount_after_discount < 0:
        amount_after_discount = 0.0
        
    tax_amount = amount_after_discount * (tax_percentage / 100.0)
    final_amount = amount_after_discount + tax_amount

    return {
        'base_amount': round(base_amount, 2),
        'discount_applied': round(discount_value, 2),
        'tax_percentage': tax_percentage,
        'tax_amount': round(tax_amount, 2),
        'final_amount': round(final_amount, 2),
        'bonus_units': bonus_units
    }

def check_debt_limits(driver_id, shop_id, new_debt_amount):
    """التحقق من صلاحيات المندوب وسقف ذمم المحل"""
    if new_debt_amount <= 0:
        return True, ""

    driver = db.session.get(Driver, driver_id)
    shop = db.session.get(Shop, shop_id)

    if not driver or not shop:
        return False, "المندوب أو المحل غير موجود."

    if not driver.can_allow_debt:
        return False, "غير مصرح لك بإعطاء ذمم للمحلات."

    if shop.max_debt_limit <= 0:
        return False, "هذا المحل غير مصرح له بفتح ذمم (السقف صفر)."

    expected_balance = shop.current_balance + new_debt_amount
    if expected_balance > shop.max_debt_limit:
        return False, f"مرفوض. سقف الذمة للمحل ({shop.max_debt_limit})، والرصيد سيصبح ({expected_balance})."

    return True, ""

def adjust_inventory(session_id, variant_id, net_quantity_change):
    """التعديل المباشر لجرد كل منتج على حدة في سيارة المندوب (وحدة واحدة)"""
    if net_quantity_change == 0:
        return True, ""

    # البحث عن سجل المنتج المحدد في سيارة المندوب
    inventory_record = SessionInventory.query.filter_by(
        work_session_id=session_id, 
        product_variant_id=variant_id
    ).first()

    if not inventory_record:
        # إذا لم يكن المنتج في سيارته أصلاً ويحاول البيع
        if net_quantity_change < 0:
            return False, "لا يوجد مخزون من هذا المنتج في سيارتك حالياً."
        # إذا كان يرجع بضاعة لم تكن معه، ننشئ سجل جديد
        inventory_record = SessionInventory(
            work_session_id=session_id, product_variant_id=variant_id,
            starting_quantity=0,
            current_remaining_quantity=0
        )
        db.session.add(inventory_record)

    # جلب خصائص المنتج
    variant = db.session.get(ProductVariant, variant_id)
    if not variant:
        return False, "بيانات المنتج غير متوفرة."

    final_quantity = inventory_record.current_remaining_quantity + net_quantity_change

    if final_quantity < 0:
        return False, f"المخزون المتوفر من ({variant.variant_name}) لا يكفي لهذه العملية."

    inventory_record.current_remaining_quantity = final_quantity
    
    return True, ""