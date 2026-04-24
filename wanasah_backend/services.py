import math
from models import db, SystemSetting, OfferRule, Driver, Shop, WorkSession, SessionInventory, ProductVariant
from decimal import Decimal, ROUND_HALF_UP

def get_setting(key, default_value, value_type=str):
    """جلب الإعدادات العامة من قاعدة البيانات"""
    setting = SystemSetting.query.filter_by(setting_key=key).first()
    if not setting: return default_value
    try: return value_type(setting.setting_value)
    except ValueError: return default_value

def calculate_invoice(cartons_qty, packs_qty, price_per_carton, price_per_pack, pre_fetched_tax=None, active_offers=None):
    """حساب الفاتورة المالي الصارم (يدعم الـ Fallback لمنع الانهيار)"""
    try:
        c_qty = int(cartons_qty)
        p_qty = int(packs_qty)
        if c_qty <= 0 and p_qty <= 0: return None
    except (ValueError, TypeError):
        return None

    c_price = Decimal(str(price_per_carton or '0.0'))
    p_price = Decimal(str(price_per_pack or '0.0'))
    tax_pct = Decimal(str(pre_fetched_tax)) if pre_fetched_tax is not None else Decimal(str(get_setting('tax_percentage', '0.0')))
    TWO_PLACES = Decimal('0.01')

    base_amount = (Decimal(str(c_qty)) * c_price) + (Decimal(str(p_qty)) * p_price)
    discount_value = Decimal('0.0')
    bonus_cartons = 0

    # +++ النسف المعماري الذكي (Logic Fallback) +++
    best_offer = None
    if active_offers is not None:
        valid_offers = [o for o in active_offers if o.threshold_quantity <= c_qty]
        if valid_offers:
            best_offer = sorted(valid_offers, key=lambda x: x.threshold_quantity, reverse=True)[0]
    else:
        # Fallback للداتابيز إذا نسينا التمرير من الـ Route
        best_offer = OfferRule.query.filter(OfferRule.is_active == True, OfferRule.threshold_quantity <= c_qty).order_by(OfferRule.threshold_quantity.desc()).first()

    if best_offer and best_offer.threshold_quantity > 0:
        multiplier = c_qty // best_offer.threshold_quantity
        if best_offer.offer_type == 'free_items':
            bonus_cartons = multiplier * best_offer.bonus_quantity
        elif best_offer.offer_type == 'fixed_discount':
            discount_value = Decimal(str(best_offer.discount_value)) * Decimal(str(multiplier))
        elif best_offer.offer_type == 'percentage_discount':
            # +++ إيقاف النزيف المالي: الخصم يُطبق فقط على الكمية المشمولة بالعرض (المضاعفات) وليس على كامل الفاتورة +++
            discounted_cartons = multiplier * best_offer.threshold_quantity
            discounted_amount = Decimal(str(discounted_cartons)) * c_price
            discount_value = discounted_amount * (Decimal(str(best_offer.discount_value)) / Decimal('100'))

    amount_after_discount = max(Decimal('0.0'), base_amount - discount_value)
    tax_amount = amount_after_discount * (tax_pct / Decimal('100'))
    final_amount = amount_after_discount + tax_amount

    return {
        'base_amount': float(base_amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)),
        'discount_applied': float(discount_value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)),
        'tax_amount': float(tax_amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)),
        'final_amount': float(final_amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)),
        'bonus_units': bonus_cartons
    }

def check_debt_limits(driver_id, shop_id, new_debt_amount, pre_fetched_driver=None, pre_fetched_shop=None):
    """التحقق من سقف الذمم (استقبال الكائنات المجلوبة مسبقاً لنسف الزهايمر)"""
    new_debt = Decimal(str(new_debt_amount))
    if new_debt <= Decimal('0'): return True, ""

    # +++ استخدام المجلوب مسبقاً أو الذهاب للداتابيز كـ Fallback +++
    driver = pre_fetched_driver or db.session.get(Driver, driver_id)
    shop = pre_fetched_shop or db.session.get(Shop, shop_id)

    if not driver or not shop: return False, "المندوب أو المحل غير موجود."
    if not getattr(driver, 'can_allow_debt', False): return False, "غير مصرح لك بإعطاء ذمم للمحلات."

    max_limit = Decimal(str(shop.max_debt_limit or '0.0'))
    if max_limit <= Decimal('0'): return False, "هذا المحل غير مصرح له بفتح ذمم (السقف صفر)."

    current_bal = Decimal(str(shop.current_balance or '0.0'))
    if current_bal + new_debt > max_limit:
        return False, f"مرفوض. سقف الذمة ({max_limit})، والرصيد سيصبح ({current_bal + new_debt})."

    return True, ""

def adjust_inventory(session_id, variant_id, net_quantity_change_in_packs, pre_locked_inventory_record=None):
    """تعديل الجرد مع حماية الـ Deadlock باستخدام السجل المقفل مسبقاً"""
    if net_quantity_change_in_packs == 0: return True, ""

    # +++ استخدام السجل المقفل جماعياً من الـ Route أو قفله منفرداً كـ Fallback +++
    inventory_record = pre_locked_inventory_record
    if not inventory_record:
        inventory_record = SessionInventory.query.filter_by(
            work_session_id=session_id, product_variant_id=variant_id
        ).with_for_update().first()

    if not inventory_record:
        if net_quantity_change_in_packs < 0: return False, "لا يوجد مخزون في سيارتك."
        inventory_record = SessionInventory(work_session_id=session_id, product_variant_id=variant_id, starting_quantity=0, current_remaining_quantity=0)
        db.session.add(inventory_record)

    if inventory_record.current_remaining_quantity + net_quantity_change_in_packs < 0:
        return False, "الكمية المتبقية لا تغطي العملية."

    inventory_record.current_remaining_quantity += net_quantity_change_in_packs
    return True, ""