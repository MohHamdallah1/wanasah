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

def calculate_invoice(quantity, price_per_carton):
    """حساب تفاصيل الفاتورة الشاملة (بضاعة، خصومات، ضريبة، بونص مجاني)"""
    if quantity <= 0:
        return None

    tax_percentage = get_setting('tax_percentage', 0.0, float)
    base_amount = quantity * price_per_carton
    discount_value = 0.0
    bonus_cartons = 0
    bonus_packs = 0

    best_offer = OfferRule.query.filter(
        OfferRule.is_active == True,
        OfferRule.threshold_cartons <= quantity
    ).order_by(OfferRule.threshold_cartons.desc()).first()

    if best_offer:
        num_tiers = quantity // best_offer.threshold_cartons
        if best_offer.offer_type == 'free_items':
            bonus_cartons = num_tiers * best_offer.bonus_cartons
            bonus_packs = num_tiers * best_offer.bonus_packs
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
        'bonus_cartons': bonus_cartons,
        'bonus_packs': bonus_packs
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

def adjust_inventory(session_id, variant_id, net_cartons_change, net_packs_change):
    """التعديل الذكي لجرد كل منتج على حدة في سيارة المندوب"""
    if net_cartons_change == 0 and net_packs_change == 0:
        return True, ""

    # البحث عن سجل المنتج المحدد في سيارة المندوب
    inventory_record = SessionInventory.query.filter_by(
        work_session_id=session_id, 
        product_variant_id=variant_id
    ).first()

    if not inventory_record:
        # إذا لم يكن المنتج في سيارته أصلاً ويحاول البيع
        if net_cartons_change < 0 or net_packs_change < 0:
            return False, "لا يوجد مخزون من هذا المنتج في سيارتك حالياً."
        # إذا كان يرجع بضاعة لم تكن معه، ننشئ سجل جديد
        inventory_record = SessionInventory(
            work_session_id=session_id, product_variant_id=variant_id,
            starting_cartons=0, starting_packs=0,
            current_remaining_cartons=0, current_remaining_packs=0
        )
        db.session.add(inventory_record)

    # جلب خصائص المنتج (مثل حجم الكرتونة)
    variant = db.session.get(ProductVariant, variant_id)
    if not variant:
        return False, "بيانات المنتج غير متوفرة."

    packs_per_carton = variant.packs_per_carton
    current_cartons = inventory_record.current_remaining_cartons
    current_packs = inventory_record.current_remaining_packs

    packs_after_change = current_packs + net_packs_change
    cartons_to_adjust = 0

    if packs_after_change < 0:
        packs_needed = abs(packs_after_change)
        cartons_to_open = math.ceil(packs_needed / packs_per_carton)
        cartons_to_adjust -= cartons_to_open
        packs_after_change = (cartons_to_open * packs_per_carton) - packs_needed
    elif packs_after_change >= packs_per_carton:
        cartons_to_pack = packs_after_change // packs_per_carton
        cartons_to_adjust += cartons_to_pack
        packs_after_change = packs_after_change % packs_per_carton

    final_cartons = current_cartons + net_cartons_change + cartons_to_adjust

    if final_cartons < 0:
        return False, f"المخزون المتوفر من ({variant.variant_name}) لا يكفي لهذه العملية."

    inventory_record.current_remaining_cartons = final_cartons
    inventory_record.current_remaining_packs = packs_after_change
    
    return True, ""