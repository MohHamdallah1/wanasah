import os
from config import Config
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date
from sqlalchemy import select, func, and_, or_, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from models import (
    SystemSetting,
    OfferRule,
    Driver,
    Shop,
    WorkSession,
    Visit,
    VisitItem,
    VisitReturn,
    InventoryLock,
    InventoryLocation,
    InventoryBalance,
    InventoryMovement,
    InventoryMovementImpact,
    ProductBatch,
    StocktakeSession,
    StocktakeLine,
    StocktakeCountAttempt,
    StocktakeCountAttemptLine,
    utc_now,
)

from typing import Any, Type, Optional, List, Dict, Tuple


# حدود الأنواع الفعلية في PostgreSQL المستخدمة في models.py.
_DB_INT_MAX = 2_147_483_647
_DB_BIGINT_MAX = 9_223_372_036_854_775_807
_MONEY_12_3_MAX = Decimal("999999999.999")
_MONEY_QUANT = Decimal("0.001")
_PERCENT_MAX = Decimal("100")
_SQL_BULK_CHUNK_SIZE = 1000
_MAX_STOCKTAKE_POST_LINES = 10_000
_STOCKTAKE_ONLY_REFERENCE_TYPES = frozenset({"AUDIT_ADJUSTMENT", "DRIVER_SHORTAGE", "DRIVER_SURPLUS"})


# تحويل قيمة مالية إلى Decimal محدود وصالح قبل دخولها أي حساب محاسبي.
def _finite_decimal(
    value: Any,
    field_name: str,
    *,
    nonnegative: bool = True,
    maximum: Optional[Decimal] = None,
) -> Decimal:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} قيمة مالية غير صالحة.") from exc

    if not dec.is_finite():
        raise ValueError(f"{field_name} لا يقبل NaN أو Infinity.")
    if nonnegative and dec < 0:
        raise ValueError(f"{field_name} لا يمكن أن يكون سالباً.")
    if maximum is not None and dec > maximum:
        raise ValueError(f"{field_name} يتجاوز الحد الأقصى المسموح ({maximum}).")
    return dec


# تحويل قيمة مالية إلى Numeric(12,3) صالح قبل إرجاعها أو حفظها.
def _money_12_3(value: Any, field_name: str) -> Decimal:
    dec = _finite_decimal(
        value,
        field_name,
        nonnegative=True,
    )
    try:
        quantized = dec.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} لا يمكن تمثيله بدقة مالية صالحة.") from exc

    if quantized > _MONEY_12_3_MAX:
        raise ValueError(
            f"{field_name} يتجاوز سعة الحقل المالي Numeric(12,3)."
        )
    return quantized


# تحويل كمية/معرّف إلى عدد صحيح دون السماح بالكسور أو القيم المنطقية أو تجاوز INTEGER.
def _strict_int(
    value: Any,
    field_name: str,
    *,
    minimum: Optional[int] = 0,
    maximum: Optional[int] = _DB_INT_MAX,
) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً.")

    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً.") from exc

    if not dec.is_finite() or dec != dec.to_integral_value():
        raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً.")

    # افحص الحدود على Decimal قبل التحويل إلى int لمنع استهلاك ذاكرة ضخم
    # مع قيم مضغوطة مثل 1e100000000.
    if minimum is not None and dec < Decimal(minimum):
        raise ValueError(f"{field_name} يجب ألا يقل عن {minimum}.")
    if maximum is not None and dec > Decimal(maximum):
        raise ValueError(f"{field_name} يتجاوز الحد الأقصى المسموح ({maximum}).")

    try:
        result = int(dec)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field_name} يجب أن يكون عدداً صحيحاً صالحاً.") from exc

    return result


# تطبيع معرّف اختياري مع رفض الصفر والقيم السالبة والكسور وتجاوز INTEGER.
def _optional_positive_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    return _strict_int(
        value,
        field_name,
        minimum=1,
        maximum=_DB_INT_MAX,
    )


# تحويل قيمة إعداد حسب النوع المطلوب مع رفض NaN/Infinity ومعالجة boolean النصي بشكل صحيح.
def _coerce_setting_value(value: Any, value_type: Type) -> Any:
    if value_type is bool:
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("قيمة boolean غير صالحة.")

    converted = value_type(value)
    if isinstance(converted, Decimal) and not converted.is_finite():
        raise ValueError("قيمة Decimal غير محدودة.")
    if isinstance(converted, float):
        try:
            finite_float = Decimal(str(converted)).is_finite()
        except InvalidOperation:
            finite_float = False
        if not finite_float:
            raise ValueError("قيمة float غير محدودة.")
    return converted


# جلب إعداد خاص بالشركة حصراً ومنع أي قراءة عابرة بين الـTenants.
async def get_setting(
    db_session: AsyncSession,
    company_id: int,
    key: str,
    default_value: Any,
    value_type: Type = str,
    *,
    strict_conversion: bool = False,
) -> Any:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
    except ValueError as exc:
        raise ValueError("company_id إجباري وصالح لقراءة إعدادات الشركة.") from exc

    if not isinstance(key, str) or not key.strip() or "\x00" in key:
        raise ValueError("setting key غير صالح.")

    # الـDefault جزء من عقد النوع مثل القيمة المخزنة؛ لا نسمح بإرجاع نوع مختلف
    # فقط لأن السجل غير موجود أو يحمل قيمة تالفة.
    try:
        coerced_default = _coerce_setting_value(default_value, value_type)
    except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        raise ValueError(
            f"القيمة الافتراضية للإعداد ({key.strip()}) غير صالحة للنوع المطلوب."
        ) from exc

    stmt = select(SystemSetting.setting_value).filter_by(
        company_id=company_id,
        setting_key=key.strip(),
    )
    value = (await db_session.execute(stmt)).scalar_one_or_none()

    if value is None:
        return coerced_default

    try:
        return _coerce_setting_value(value, value_type)
    except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        if strict_conversion:
            raise ValueError(
                f"الإعداد ({key.strip()}) يحمل قيمة غير صالحة ولا يجوز استخدام Default بصمت."
            ) from exc
        return coerced_default

def calculate_invoice(
    cartons_qty: int,
    packs_qty: int,
    price_per_carton: Decimal,
    price_per_pack: Decimal,
    pre_fetched_tax: Decimal,
    active_offers: List[OfferRule],
    *,
    company_id: int,
    packs_per_carton: int = 1,
    variant_id: Optional[int] = None,
) -> Dict[str, Any]:
    """حساب الفاتورة المالي النقي مع عزل عروض الشركة ورفض أي إعداد مالي فاسد."""
    company_id = _strict_int(company_id, "company_id", minimum=1)
    variant_id = _optional_positive_int(variant_id, "variant_id")
    c_qty = _strict_int(cartons_qty, "cartons_qty", minimum=0)
    p_qty = _strict_int(packs_qty, "packs_qty", minimum=0)
    safe_ppc = _strict_int(packs_per_carton, "packs_per_carton", minimum=1)

    zero_result = {
        "base_amount": Decimal("0.000"),
        "discount_applied": Decimal("0.000"),
        "tax_amount": Decimal("0.000"),
        "final_amount": Decimal("0.000"),
        "bonus_units": 0,
    }
    if c_qty == 0 and p_qty == 0:
        return zero_result

    c_price = _money_12_3(
        price_per_carton or "0.0",
        "price_per_carton",
    )
    p_price = _money_12_3(
        price_per_pack or "0.0",
        "price_per_pack",
    )
    tax_pct = _finite_decimal(
        pre_fetched_tax,
        "tax_percentage",
        maximum=_PERCENT_MAX,
    ).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)

    # الكميات المدفوعة لا يجوز أن تمر بسعر صفري؛ العينات والبونص لهما مسارات مستقلة.
    if c_qty > 0 and c_price <= Decimal("0"):
        raise ValueError("price_per_carton يجب أن يكون أكبر من صفر عند بيع كراتين.")
    if p_qty > 0 and p_price <= Decimal("0"):
        raise ValueError("price_per_pack يجب أن يكون أكبر من صفر عند بيع حبات منفردة.")

    if active_offers is None:
        raise ValueError(
            "هندسة مرفوضة: يجب جلب العروض النشطة مسبقاً وتمريرها كقائمة."
        )

    # ثبّت المبلغ الأساسي على نفس Precision قاعدة البيانات قبل أي خصم/ضريبة.
    base_amount = _money_12_3(
        (Decimal(c_qty) * c_price) + (Decimal(p_qty) * p_price),
        "base_amount",
    )
    total_equivalent_cartons = c_qty + (p_qty // safe_ppc)

    relevant_offers = [
        offer
        for offer in active_offers
        if getattr(offer, "company_id", None) == company_id
        and (offer.product_variant_id is None or offer.product_variant_id == variant_id)
        and getattr(offer, "is_active", True)
    ]

    validated_offers = []
    for offer in relevant_offers:
        threshold = _strict_int(
            offer.threshold_quantity,
            f"offer[{getattr(offer, 'id', '?')}].threshold_quantity",
            minimum=1,
        )
        offer_type = str(offer.offer_type or "").strip()

        if offer_type not in {"free_items", "fixed_discount", "percentage_discount"}:
            raise ValueError(
                f"العرض رقم ({getattr(offer, 'id', '?')}) يحمل نوعاً غير صالح."
            )

        bonus_qty = _strict_int(
            offer.bonus_quantity or 0,
            f"offer[{getattr(offer, 'id', '?')}].bonus_quantity",
            minimum=0,
        )
        discount_cfg = _money_12_3(
            offer.discount_value or "0.0",
            f"offer[{getattr(offer, 'id', '?')}].discount_value",
        )

        if offer_type == "percentage_discount" and discount_cfg > Decimal("100"):
            raise ValueError(
                f"العرض رقم ({getattr(offer, 'id', '?')}) يحتوي نسبة خصم أكبر من 100%."
            )

        if threshold <= total_equivalent_cartons:
            validated_offers.append(
                (offer, threshold, bonus_qty, discount_cfg)
            )

    best_offer = None
    if validated_offers:
        max_threshold = max(row[1] for row in validated_offers)
        top_offers = [row for row in validated_offers if row[1] == max_threshold]
        if len(top_offers) > 1:
            offer_ids = ", ".join(str(getattr(row[0], "id", "?")) for row in top_offers)
            raise ValueError(
                f"تعارض إعدادات العروض: أكثر من عرض مؤهل بنفس الأولوية ({offer_ids})."
            )
        best_offer = top_offers[0]

    discount_value = Decimal("0.0")
    bonus_cartons = 0

    if best_offer:
        offer, threshold, bonus_qty, discount_cfg = best_offer
        multiplier = total_equivalent_cartons // threshold
        normalized_offer_type = str(offer.offer_type or "").strip()

        if normalized_offer_type == "free_items":
            bonus_cartons = multiplier * bonus_qty
            if bonus_cartons > _DB_INT_MAX:
                raise ValueError(
                    "كمية البونص الناتجة تتجاوز سعة INTEGER في قاعدة البيانات."
                )
        elif normalized_offer_type == "fixed_discount":
            discount_value = discount_cfg * Decimal(multiplier)
        else:
            discount_value = base_amount * (discount_cfg / Decimal("100"))

    # المحاسبة تُبنى على القيم التي ستُحفظ فعلياً (3 منازل) حتى يبقى:
    # final_amount == base_amount - discount_applied + tax_amount
    # حرفياً، بلا فروق فلس ناتجة عن التقريب المستقل.
    actual_discount_applied = _money_12_3(
        min(base_amount, discount_value),
        "discount_applied",
    )
    amount_after_discount = base_amount - actual_discount_applied
    tax_amount = _money_12_3(
        amount_after_discount * (tax_pct / Decimal("100")),
        "tax_amount",
    )
    final_amount = _money_12_3(
        amount_after_discount + tax_amount,
        "final_amount",
    )

    return {
        "base_amount": base_amount,
        "discount_applied": actual_discount_applied,
        "tax_amount": tax_amount,
        "final_amount": final_amount,
        "bonus_units": bonus_cartons,
    }

# التحقق من سقف الذمم داخل Tenant واحد مع قفل المحل ومنع أي قيم مالية غير محدودة.
async def check_debt_limits(
    db_session: AsyncSession,
    company_id: int,
    driver_id: int,
    shop_id: int,
    new_debt_amount: Decimal,
    pre_fetched_driver: Optional[Driver] = None,
) -> Tuple[bool, str]:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        driver_id = _strict_int(driver_id, "driver_id", minimum=1)
        shop_id = _strict_int(shop_id, "shop_id", minimum=1)
        new_debt = _money_12_3(
            new_debt_amount,
            "new_debt_amount",
        )
    except ValueError as exc:
        return False, str(exc)

    if new_debt == Decimal("0"):
        return True, ""

    # الـORM object الممرر مجرد hint للهوية، وليس مصدراً لصلاحية مالية قديمة.
    # نعيد قراءة صلاحية المندوب من DB كي لا تمر عملية بعد إلغاء can_allow_debt
    # أو تعطيل المستخدم في معاملة سبقت هذا الفحص.
    if pre_fetched_driver is not None and (
        pre_fetched_driver.id != driver_id
        or pre_fetched_driver.company_id != company_id
    ):
        return False, "المندوب غير صالح لهذه الشركة."

    stmt_driver = select(Driver).filter_by(
        id=driver_id,
        company_id=company_id,
        is_active=True,
        can_allow_debt=True,
    ).with_for_update(read=True)
    driver = (await db_session.execute(stmt_driver)).scalar_one_or_none()

    # لا نعتمد أي Shop pre-fetched في القرار المالي؛ يجب قفل الصف الحقيقي دائماً.
    stmt_shop = select(Shop).filter_by(
        id=shop_id,
        company_id=company_id,
    ).with_for_update()
    shop = (await db_session.execute(stmt_shop)).scalar_one_or_none()

    if not driver:
        return False, "المندوب غير موجود/غير فعال أو لم تعد لديه صلاحية إعطاء ذمم."
    if not shop:
        return False, "المحل غير موجود."
    if not getattr(shop, "is_active", False) or getattr(shop, "is_archived", False):
        return False, "المحل غير فعال أو مؤرشف ولا يمكن فتح ذمة جديدة له."
    # can_allow_debt جزء من استعلام DB أعلاه؛ غياب driver يعني أن الصلاحية
    # ألغيت أو أن الحساب لم يعد فعالاً.
    try:
        max_limit = _money_12_3(
            shop.max_debt_limit or "0.0",
            "shop.max_debt_limit",
        )
        current_bal = _money_12_3(
            shop.current_balance or "0.0",
            "shop.current_balance",
        )
    except ValueError as exc:
        return False, str(exc)

    if max_limit == Decimal("0"):
        return False, "هذا المحل غير مصرح له بفتح ذمم (السقف صفر)."

    if current_bal + new_debt > max_limit:
        return False, (
            f"مرفوض. سقف الذمة ({max_limit})، "
            f"والرصيد سيصبح ({current_bal + new_debt})."
        )

    return True, ""

class InventoryMutationError(Exception):
    pass


# إنشاء صف رصيد صفري عند الوجهة فقط؛ الرصيد الحي يبقى حصرياً في InventoryBalance.
async def _ensure_inventory_balance(
    db_session: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    product_variant_id: int,
    batch_id: int,
    stock_status: str,
) -> None:
    stmt = pg_insert(InventoryBalance).values(
        company_id=company_id,
        location_id=location_id,
        product_variant_id=product_variant_id,
        batch_id=batch_id,
        stock_status=stock_status,
        on_hand_quantity=0,
        reserved_quantity=0,
    ).on_conflict_do_nothing(
        index_elements=[
            "company_id",
            "location_id",
            "product_variant_id",
            "batch_id",
            "stock_status",
        ]
    )
    await db_session.execute(stmt)


# إنشاء أرصدة صفرية بالجملة على دفعات آمنة من حد معاملات PostgreSQL دون N+1 لكل سطر.
async def _bulk_ensure_inventory_balances(
    db_session: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    rows: List[Tuple[int, int, str]],
) -> None:
    if not rows:
        return

    unique_rows = sorted(set(rows))
    for offset in range(0, len(unique_rows), _SQL_BULK_CHUNK_SIZE):
        chunk = unique_rows[offset:offset + _SQL_BULK_CHUNK_SIZE]
        stmt = pg_insert(InventoryBalance).values([
            {
                "company_id": company_id,
                "location_id": location_id,
                "product_variant_id": product_variant_id,
                "batch_id": batch_id,
                "stock_status": stock_status,
                "on_hand_quantity": 0,
                "reserved_quantity": 0,
            }
            for product_variant_id, batch_id, stock_status in chunk
        ]).on_conflict_do_nothing(
            index_elements=[
                "company_id",
                "location_id",
                "product_variant_id",
                "batch_id",
                "stock_status",
            ]
        )
        await db_session.execute(stmt)


# تسجيل لقطة قبل/بعد للحركة دون إنشاء مصدر حقيقة موازٍ للرصيد.
def _add_inventory_movement_impact(
    db_session: AsyncSession,
    *,
    company_id: int,
    movement_id: int,
    balance: InventoryBalance,
    before_on_hand: int,
    before_reserved: int,
) -> None:
    after_on_hand = int(balance.on_hand_quantity or 0)
    after_reserved = int(balance.reserved_quantity or 0)

    if before_on_hand == after_on_hand and before_reserved == after_reserved:
        return

    db_session.add(InventoryMovementImpact(
        company_id=company_id,
        movement_id=movement_id,
        inventory_balance_id=balance.id,
        on_hand_before=before_on_hand,
        on_hand_after=after_on_hand,
        reserved_before=before_reserved,
        reserved_after=after_reserved,
    ))



# قفل Advisory مشترك للحركات وعزل حصري لبدء الجرد دون تسلسل الحركات الطبيعية داخل الموقع.
async def acquire_inventory_location_guard(
    db_session: AsyncSession,
    company_id: int,
    location_id: int,
    *,
    exclusive: bool = False,
) -> None:
    company_id = _strict_int(company_id, "company_id", minimum=1)
    location_id = _strict_int(location_id, "location_id", minimum=1)

    lock_fn = (
        func.pg_advisory_xact_lock
        if exclusive
        else func.pg_advisory_xact_lock_shared
    )
    await db_session.execute(select(lock_fn(company_id, location_id)))


# تطبيق حركة مخزون عامة واحدة؛ قواعد Workflow الخاصة بالجرد تبقى خارج المحرك منخفض المستوى.
async def apply_inventory_movement(
    db_session: AsyncSession,
    *,
    company_id: int,
    performed_by: int,
    product_variant_id: int,
    batch_id: int,
    quantity: int,
    movement_kind: str,
    reference_type: str,
    reference_id: str,
    idempotency_key: str,
    source_location_id: Optional[int] = None,
    destination_location_id: Optional[int] = None,
    source_stock_status: Optional[str] = None,
    destination_stock_status: Optional[str] = None,
    reservation_action: Optional[str] = None,
    work_session_id: Optional[int] = None,
    transfer_header_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> InventoryMovement:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        performed_by = _strict_int(performed_by, "performed_by", minimum=1)
        product_variant_id = _strict_int(
            product_variant_id, "product_variant_id", minimum=1
        )
        batch_id = _strict_int(batch_id, "batch_id", minimum=1)
        quantity = _strict_int(quantity, "quantity", minimum=1)
        source_location_id = _optional_positive_int(
            source_location_id, "source_location_id"
        )
        destination_location_id = _optional_positive_int(
            destination_location_id, "destination_location_id"
        )
        work_session_id = _optional_positive_int(
            work_session_id, "work_session_id"
        )
        transfer_header_id = _optional_positive_int(
            transfer_header_id, "transfer_header_id"
        )
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    movement_kind = str(movement_kind).strip().upper()
    if movement_kind not in {"PHYSICAL", "RESERVATION", "STATUS_CHANGE"}:
        raise InventoryMutationError("نوع حركة المخزون غير صالح.")

    reference_type = str(reference_type or "").strip()
    reference_id = str(reference_id or "").strip()
    idempotency_key = str(idempotency_key or "").strip()
    if notes is not None and not isinstance(notes, str):
        raise InventoryMutationError("notes يجب أن تكون نصاً أو None.")
    if any("\x00" in value for value in (reference_type, reference_id, idempotency_key)):
        raise InventoryMutationError("مرجع الحركة ومفتاح عدم التكرار لا يقبلان محرف NUL.")
    if notes is not None and "\x00" in notes:
        raise InventoryMutationError("notes لا تقبل محرف NUL.")
    if not reference_type or not reference_id or not idempotency_key:
        raise InventoryMutationError("مرجع الحركة ومفتاح عدم التكرار إلزاميان.")
    if len(reference_type) > 50 or len(reference_id) > 100 or len(idempotency_key) > 100:
        raise InventoryMutationError("مرجع الحركة أو مفتاح عدم التكرار أطول من الحد المسموح.")
    if reference_type in _STOCKTAKE_ONLY_REFERENCE_TYPES:
        raise InventoryMutationError(
            "مرجع حركة الجرد محجوز لخدمة ترحيل الجرد المعتمد ولا يجوز تمريره للمحرك العام."
        )

    if source_stock_status is not None:
        source_stock_status = str(source_stock_status).strip().upper()
    if destination_stock_status is not None:
        destination_stock_status = str(destination_stock_status).strip().upper()
    if reservation_action is not None:
        reservation_action = str(reservation_action).strip().upper()

    allowed_statuses = {"AVAILABLE", "DAMAGED"}
    if source_stock_status is not None and source_stock_status not in allowed_statuses:
        raise InventoryMutationError("حالة مخزون المصدر غير صالحة.")
    if destination_stock_status is not None and destination_stock_status not in allowed_statuses:
        raise InventoryMutationError("حالة مخزون الوجهة غير صالحة.")

    if (source_location_id is None) != (source_stock_status is None):
        raise InventoryMutationError("المصدر وحالته يجب أن يوجدا معاً أو يكونا فارغين معاً.")
    if (destination_location_id is None) != (destination_stock_status is None):
        raise InventoryMutationError("الوجهة وحالتها يجب أن يوجدا معاً أو يكونا فارغين معاً.")

    if movement_kind == "RESERVATION":
        if reservation_action not in {"RESERVE", "RELEASE"}:
            raise InventoryMutationError("حركة الحجز تتطلب RESERVE أو RELEASE.")
        if (
            source_location_id is None
            or destination_location_id != source_location_id
            or source_stock_status != "AVAILABLE"
            or destination_stock_status != "AVAILABLE"
        ):
            raise InventoryMutationError("شكل حركة الحجز غير صالح.")
    elif reservation_action is not None:
        raise InventoryMutationError("reservation_action مسموح فقط لحركة RESERVATION.")

    if movement_kind == "STATUS_CHANGE" and (
        source_location_id is None
        or destination_location_id != source_location_id
        or source_stock_status == destination_stock_status
    ):
        raise InventoryMutationError("شكل تغيير حالة المخزون غير صالح.")

    if movement_kind == "PHYSICAL":
        if source_location_id is None and destination_location_id is None:
            raise InventoryMutationError("الحركة الفيزيائية تحتاج مصدراً أو وجهة.")
        if (
            source_location_id is not None
            and destination_location_id is not None
            and source_location_id == destination_location_id
        ):
            raise InventoryMutationError("الحركة الفيزيائية بين نفس الموقع غير صالحة.")
        if (
            source_location_id is not None
            and destination_location_id is not None
            and source_stock_status != destination_stock_status
        ):
            raise InventoryMutationError(
                "الحركة PHYSICAL لا يجوز أن تغيّر حالة المخزون؛ استخدم STATUS_CHANGE."
            )

    advisory_key = f"inventory:{company_id}:{idempotency_key}"
    await db_session.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(advisory_key)))
    )

    existing = (
        await db_session.execute(
            select(InventoryMovement).filter_by(
                company_id=company_id,
                idempotency_key=idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        expected_existing = {
            "performed_by": performed_by,
            "source_location_id": source_location_id,
            "destination_location_id": destination_location_id,
            "source_stock_status": source_stock_status,
            "destination_stock_status": destination_stock_status,
            "product_variant_id": product_variant_id,
            "batch_id": batch_id,
            "movement_kind": movement_kind,
            "reservation_action": reservation_action,
            "quantity": quantity,
            "work_session_id": work_session_id,
            "transfer_header_id": transfer_header_id,
            "stocktake_session_id": None,
            "stocktake_count_attempt_id": None,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "notes": notes,
        }
        for field_name, expected_value in expected_existing.items():
            if getattr(existing, field_name) != expected_value:
                raise InventoryMutationError(
                    "مفتاح idempotency مستخدم مسبقاً لحركة مختلفة؛ تم رفض إعادة الاستخدام."
                )
        return existing

    location_ids = {
        int(location_id)
        for location_id in (source_location_id, destination_location_id)
        if location_id is not None
    }

    # ترتيب القفل: Advisory للمواقع ثم صفوف المواقع ثم الأقفال الجراحية ثم الأرصدة.
    for location_id in sorted(location_ids):
        await acquire_inventory_location_guard(
            db_session,
            company_id,
            location_id,
            exclusive=False,
        )

    if location_ids:
        stmt_locations = select(InventoryLocation.id).filter(
            InventoryLocation.company_id == company_id,
            InventoryLocation.id.in_(location_ids),
            InventoryLocation.is_active.is_(True),
        ).order_by(
            InventoryLocation.id.asc()
        ).with_for_update(read=True)
        existing_location_ids = set(
            (await db_session.execute(stmt_locations)).scalars().all()
        )
        if existing_location_ids != location_ids:
            raise InventoryMutationError("أحد مواقع المخزون غير موجود أو غير فعال.")

    batch_exists = (
        await db_session.execute(
            select(ProductBatch.id).filter_by(
                company_id=company_id,
                product_variant_id=product_variant_id,
                id=batch_id,
            )
        )
    ).scalar_one_or_none()
    if batch_exists is None:
        raise InventoryMutationError("الدفعة لا تنتمي للصنف أو الشركة المحددة.")

    try:
        for location_id in sorted(location_ids):
            await check_inventory_lock(
                db_session,
                company_id,
                location_id,
                product_variant_id,
                batch_id,
            )
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    source_key = (
        None
        if source_location_id is None
        else (int(source_location_id), source_stock_status)
    )
    destination_key = (
        None
        if destination_location_id is None
        else (int(destination_location_id), destination_stock_status)
    )

    if destination_key is not None and destination_key != source_key:
        await _ensure_inventory_balance(
            db_session,
            company_id=company_id,
            location_id=destination_key[0],
            product_variant_id=product_variant_id,
            batch_id=batch_id,
            stock_status=destination_key[1],
        )

    keys = sorted(
        {key for key in (source_key, destination_key) if key is not None},
        key=lambda x: (x[0], x[1]),
    )
    if not keys:
        raise InventoryMutationError("لا يوجد رصيد متأثر بالحركة.")

    predicates = [
        and_(
            InventoryBalance.location_id == location_id,
            InventoryBalance.stock_status == stock_status,
        )
        for location_id, stock_status in keys
    ]
    stmt_balances = select(InventoryBalance).filter(
        InventoryBalance.company_id == company_id,
        InventoryBalance.product_variant_id == product_variant_id,
        InventoryBalance.batch_id == batch_id,
        or_(*predicates),
    ).order_by(
        InventoryBalance.location_id.asc(),
        InventoryBalance.stock_status.asc(),
    ).with_for_update()

    balances = (await db_session.execute(stmt_balances)).scalars().all()
    balance_map = {(row.location_id, row.stock_status): row for row in balances}

    if source_key is not None and source_key not in balance_map:
        raise InventoryMutationError("رصيد المصدر غير موجود.")
    if destination_key is not None and destination_key not in balance_map:
        raise InventoryMutationError("تعذر إنشاء رصيد الوجهة.")

    # فحص دفاعي ثانٍ رخيص بعد Row Locks. يصبح غير لازم فقط بعد ترحيل كل منشئي الجرد إلى Exclusive Guard.
    try:
        for location_id in sorted(location_ids):
            await check_inventory_lock(
                db_session,
                company_id,
                location_id,
                product_variant_id,
                batch_id,
            )
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    before = {
        row.id: (int(row.on_hand_quantity or 0), int(row.reserved_quantity or 0))
        for row in balances
    }

    if movement_kind == "RESERVATION":
        balance = balance_map[source_key]
        on_hand = int(balance.on_hand_quantity or 0)
        reserved = int(balance.reserved_quantity or 0)
        if reservation_action == "RESERVE":
            if on_hand - reserved < quantity:
                raise InventoryMutationError("الرصيد المتاح لا يغطي كمية الحجز.")
            balance.reserved_quantity = reserved + quantity
        else:
            if reserved < quantity:
                raise InventoryMutationError("الرصيد المحجوز لا يغطي كمية التحرير.")
            balance.reserved_quantity = reserved - quantity
    else:
        source_balance = None
        destination_balance = None
        new_source_on_hand = None
        new_destination_on_hand = None

        if source_key is not None:
            source_balance = balance_map[source_key]
            source_on_hand = int(source_balance.on_hand_quantity or 0)
            source_reserved = int(source_balance.reserved_quantity or 0)
            if source_on_hand - source_reserved < quantity:
                raise InventoryMutationError("الرصيد الحر في المصدر لا يغطي الحركة.")
            new_source_on_hand = source_on_hand - quantity

        if destination_key is not None:
            destination_balance = balance_map[destination_key]
            destination_on_hand = int(destination_balance.on_hand_quantity or 0)
            new_destination_on_hand = destination_on_hand + quantity
            if new_destination_on_hand > _DB_INT_MAX:
                raise InventoryMutationError(
                    "الرصيد الناتج في الوجهة يتجاوز سعة INTEGER في قاعدة البيانات."
                )

        if source_balance is not None:
            source_balance.on_hand_quantity = new_source_on_hand
        if destination_balance is not None:
            destination_balance.on_hand_quantity = new_destination_on_hand

    movement = InventoryMovement(
        company_id=company_id,
        performed_by=performed_by,
        source_location_id=source_location_id,
        destination_location_id=destination_location_id,
        source_stock_status=source_stock_status,
        destination_stock_status=destination_stock_status,
        product_variant_id=product_variant_id,
        batch_id=batch_id,
        movement_kind=movement_kind,
        reservation_action=reservation_action,
        quantity=quantity,
        work_session_id=work_session_id,
        transfer_header_id=transfer_header_id,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        notes=notes,
    )
    db_session.add(movement)
    await db_session.flush()

    for balance in balances:
        before_on_hand, before_reserved = before[balance.id]
        _add_inventory_movement_impact(
            db_session,
            company_id=company_id,
            movement_id=movement.id,
            balance=balance,
            before_on_hand=before_on_hand,
            before_reserved=before_reserved,
        )

    return movement


# ترحيل فروقات جرد معتمد دفعة واحدة دون N+1، مع قفل الموقع والتحقق من آخر محاولة مرة واحدة.
async def post_approved_stocktake_adjustments(
    db_session: AsyncSession,
    *,
    company_id: int,
    stocktake_session_id: int,
    stocktake_count_attempt_id: int,
    performed_by: int,
) -> List[InventoryMovement]:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        stocktake_session_id = _strict_int(
            stocktake_session_id, "stocktake_session_id", minimum=1
        )
        stocktake_count_attempt_id = _strict_int(
            stocktake_count_attempt_id, "stocktake_count_attempt_id", minimum=1
        )
        performed_by = _strict_int(performed_by, "performed_by", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    actor_id = (
        await db_session.execute(
            select(Driver.id).filter_by(
                company_id=company_id,
                id=performed_by,
                is_active=True,
                is_admin=True,
            ).with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if actor_id is None:
        raise InventoryMutationError(
            "ترحيل الجرد يتطلب مشرفاً فعالاً من نفس الشركة."
        )

    probe = (
        await db_session.execute(
            select(StocktakeSession.location_id).filter_by(
                company_id=company_id,
                id=stocktake_session_id,
            )
        )
    ).scalar_one_or_none()
    if probe is None:
        raise InventoryMutationError("جلسة الجرد غير موجودة أو لا تتبع الشركة.")

    # الترحيل عملية حصرية على الموقع؛ يمنع أي حركة متزامنة أثناء تثبيت جميع الفروقات.
    await acquire_inventory_location_guard(
        db_session,
        company_id,
        int(probe),
        exclusive=True,
    )

    session = (
        await db_session.execute(
            select(StocktakeSession).filter_by(
                company_id=company_id,
                id=stocktake_session_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if session is None or session.location_id != probe:
        raise InventoryMutationError("جلسة الجرد تغيرت أو لم تعد صالحة للترحيل.")
    if session.status not in {"APPROVED", "POSTED"}:
        raise InventoryMutationError(
            f"ترحيل الجرد يتطلب حالة APPROVED؛ الحالة الحالية ({session.status})."
        )
    if session.approved_by is None or session.approved_at is None:
        raise InventoryMutationError("جلسة الجرد لا تحمل اعتماداً موثقاً صالحاً.")
    if session.stocktake_type == "VEHICLE_RECON":
        if session.related_work_session_id is None:
            raise InventoryMutationError(
                "VEHICLE_RECON يجب أن يرتبط بجلسة العمل التي تتم تسويتها."
            )
    elif session.related_work_session_id is not None:
        raise InventoryMutationError(
            "related_work_session_id غير مسموح لغير VEHICLE_RECON."
        )

    if session.stocktake_type not in {"FULL_COUNT", "CYCLE_COUNT", "VEHICLE_RECON"}:
        raise InventoryMutationError("نوع جلسة الجرد غير صالح.")

    location_row = (
        await db_session.execute(
            select(
                InventoryLocation.location_type,
                InventoryLocation.is_active,
            ).filter_by(
                company_id=company_id,
                id=session.location_id,
            ).with_for_update(read=True)
        )
    ).one_or_none()
    if location_row is None:
        raise InventoryMutationError("موقع جلسة الجرد غير موجود أو لا يتبع الشركة.")
    location_type, location_is_active = location_row
    expected_location_type = (
        "VEHICLE" if session.stocktake_type == "VEHICLE_RECON" else "WAREHOUSE"
    )
    if location_type != expected_location_type:
        raise InventoryMutationError(
            "نوع موقع جلسة الجرد لا يطابق نوع الجرد المعتمد."
        )
    if session.status == "APPROVED" and not location_is_active:
        raise InventoryMutationError(
            "لا يمكن ترحيل جرد جديد على موقع مخزون غير فعال."
        )

    latest_attempt = (
        await db_session.execute(
            select(StocktakeCountAttempt).filter_by(
                company_id=company_id,
                stocktake_session_id=session.id,
            ).order_by(
                StocktakeCountAttempt.attempt_number.desc(),
                StocktakeCountAttempt.id.desc(),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if latest_attempt is None:
        raise InventoryMutationError("لا توجد محاولة عد مثبتة لجلسة الجرد.")
    if latest_attempt.id != stocktake_count_attempt_id:
        raise InventoryMutationError(
            "المحاولة المطلوب ترحيلها ليست آخر محاولة عد مثبتة؛ أعد فتح المراجعة."
        )

    if latest_attempt.requires_independent_recount:
        if latest_attempt.recount_of_attempt_id is None:
            raise InventoryMutationError(
                "العجز المادي يتطلب إعادة عد مستقلة قبل الترحيل."
            )
        parent_attempt = (
            await db_session.execute(
                select(StocktakeCountAttempt).filter_by(
                    company_id=company_id,
                    stocktake_session_id=session.id,
                    id=latest_attempt.recount_of_attempt_id,
                )
            )
        ).scalar_one_or_none()
        if (
            parent_attempt is None
            or not parent_attempt.requires_independent_recount
            or parent_attempt.counted_by == latest_attempt.counted_by
        ):
            raise InventoryMutationError(
                "آخر محاولة لا تحقق شرط إعادة العد المستقلة للعجز المادي."
            )

    # تحميل Snapshot ومحاولة العد معاً يكشف أي سطر مفقود دون Query لكل صنف.
    stmt_lines = (
        select(StocktakeLine, StocktakeCountAttemptLine)
        .outerjoin(
            StocktakeCountAttemptLine,
            and_(
                StocktakeCountAttemptLine.company_id == StocktakeLine.company_id,
                StocktakeCountAttemptLine.stocktake_session_id
                == StocktakeLine.stocktake_session_id,
                StocktakeCountAttemptLine.stocktake_line_id == StocktakeLine.id,
                StocktakeCountAttemptLine.count_attempt_id == latest_attempt.id,
            ),
        )
        .filter(
            StocktakeLine.company_id == company_id,
            StocktakeLine.stocktake_session_id == session.id,
        )
        .order_by(
            StocktakeLine.product_variant_id.asc(),
            StocktakeLine.batch_id.asc(),
            StocktakeLine.stock_status.asc(),
            StocktakeLine.id.asc(),
        )
    )
    line_rows = (await db_session.execute(stmt_lines)).all()
    if not line_rows:
        raise InventoryMutationError("جلسة الجرد لا تحتوي على أسطر قابلة للترحيل.")
    if any(attempt_line is None for _, attempt_line in line_rows):
        raise InventoryMutationError(
            "آخر محاولة عد ناقصة ولا تغطي جميع أسطر Snapshot؛ تم رفض الترحيل."
        )
    if len(line_rows) > _MAX_STOCKTAKE_POST_LINES:
        raise InventoryMutationError(
            "جلسة الجرد تتجاوز الحد الآمن لعدد الأسطر في عملية ترحيل واحدة."
        )

    # لا نثق بسلامة منشئ Snapshot وحده؛ نطاق أسطر الجرد يجب أن يطابق رأس الجلسة حرفياً.
    if session.stocktake_type == "CYCLE_COUNT":
        if session.scope_product_variant_id is None:
            raise InventoryMutationError("CYCLE_COUNT بدون نطاق صنف صالح.")
        for stocktake_line, _ in line_rows:
            if stocktake_line.product_variant_id != session.scope_product_variant_id:
                raise InventoryMutationError(
                    "Snapshot الجرد الدوري يحتوي صنفاً خارج نطاق الجلسة."
                )
            if (
                session.scope_batch_id is not None
                and stocktake_line.batch_id != session.scope_batch_id
            ):
                raise InventoryMutationError(
                    "Snapshot الجرد الدوري يحتوي دفعة خارج نطاق الجلسة."
                )
    elif session.scope_product_variant_id is not None or session.scope_batch_id is not None:
        raise InventoryMutationError(
            "FULL_COUNT/VEHICLE_RECON لا يجوز أن يحملا نطاق صنف أو دفعة."
        )

    active_locks = (
        await db_session.execute(
            select(InventoryLock).filter(
                InventoryLock.company_id == company_id,
                InventoryLock.location_id == session.location_id,
                InventoryLock.released_at.is_(None),
            ).order_by(InventoryLock.id.asc()).with_for_update()
        )
    ).scalars().all()

    own_locks = [
        lock for lock in active_locks
        if lock.stocktake_session_id == session.id
    ]
    if session.status == "APPROVED":
        if session.stocktake_type in {"FULL_COUNT", "VEHICLE_RECON"}:
            own_scope_ok = any(
                lock.product_variant_id is None and lock.batch_id is None
                for lock in own_locks
            )
        elif session.scope_batch_id is None:
            own_scope_ok = any(
                lock.product_variant_id == session.scope_product_variant_id
                and lock.batch_id is None
                for lock in own_locks
            )
        else:
            own_scope_ok = any(
                lock.product_variant_id == session.scope_product_variant_id
                and lock.batch_id == session.scope_batch_id
                for lock in own_locks
            )
        if not own_scope_ok:
            raise InventoryMutationError(
                "قفل الجرد الفعال لا يطابق نطاق الجلسة المعتمدة."
            )

        for lock in active_locks:
            if lock.stocktake_session_id == session.id:
                continue
            if lock.product_variant_id is None:
                raise InventoryMutationError(
                    "يوجد قفل جرد شامل آخر متعارض على نفس الموقع."
                )
            if session.stocktake_type in {"FULL_COUNT", "VEHICLE_RECON"}:
                raise InventoryMutationError(
                    "يوجد قفل جرد آخر متعارض على نفس الموقع."
                )
            if lock.product_variant_id != session.scope_product_variant_id:
                continue
            if session.scope_batch_id is None or lock.batch_id in {
                None,
                session.scope_batch_id,
            }:
                raise InventoryMutationError(
                    "يوجد قفل جرد دوري متداخل مع نطاق الجلسة الحالية."
                )

    specs = []
    for stocktake_line, attempt_line in line_rows:
        if attempt_line.count_attempt_id != latest_attempt.id:
            raise InventoryMutationError("تم اكتشاف سطر عد مرتبط بمحاولة مختلفة.")
        variance = int(attempt_line.variance_quantity or 0)
        if variance != int(attempt_line.actual_quantity) - int(attempt_line.expected_quantity):
            raise InventoryMutationError("تم اكتشاف فرق جرد غير متسق حسابياً.")
        if variance == 0:
            continue

        stock_status = str(stocktake_line.stock_status or "").strip().upper()
        if stock_status not in {"AVAILABLE", "DAMAGED"}:
            raise InventoryMutationError("حالة مخزون غير صالحة في سطر الجرد.")

        if variance < 0:
            source_location_id = session.location_id
            destination_location_id = None
            source_stock_status = stock_status
            destination_stock_status = None
            reference_type = (
                "DRIVER_SHORTAGE"
                if session.stocktake_type == "VEHICLE_RECON"
                else "AUDIT_ADJUSTMENT"
            )
        else:
            source_location_id = None
            destination_location_id = session.location_id
            source_stock_status = None
            destination_stock_status = stock_status
            reference_type = (
                "DRIVER_SURPLUS"
                if session.stocktake_type == "VEHICLE_RECON"
                else "AUDIT_ADJUSTMENT"
            )

        specs.append({
            "attempt_line": attempt_line,
            "product_variant_id": stocktake_line.product_variant_id,
            "batch_id": stocktake_line.batch_id,
            "stock_status": stock_status,
            "variance": variance,
            "quantity": abs(variance),
            "source_location_id": source_location_id,
            "destination_location_id": destination_location_id,
            "source_stock_status": source_stock_status,
            "destination_stock_status": destination_stock_status,
            "reference_type": reference_type,
            "reference_id": session.reference_number,
            "idempotency_key": (
                f"AUDIT-{session.id}-{latest_attempt.id}-{attempt_line.id}"
            ),
            "work_session_id": (
                session.related_work_session_id
                if session.stocktake_type == "VEHICLE_RECON"
                else None
            ),
        })

    expected_idempotency_keys = {
        spec["idempotency_key"] for spec in specs
    }
    # اقرأ كل حركات المحاولة، لا الحركات ذات المفاتيح المتوقعة فقط، لكشف أي أثر زائد أو جزئي.
    existing_movements = (
        await db_session.execute(
            select(InventoryMovement).filter(
                InventoryMovement.company_id == company_id,
                InventoryMovement.stocktake_session_id == session.id,
                InventoryMovement.stocktake_count_attempt_id == latest_attempt.id,
            ).order_by(InventoryMovement.id.asc())
        )
    ).scalars().all()
    existing_map = {
        movement.idempotency_key: movement
        for movement in existing_movements
    }
    if len(existing_map) != len(existing_movements):
        raise InventoryMutationError(
            "تم اكتشاف مفاتيح idempotency مكررة في حركات الجرد؛ البيانات غير متسقة."
        )

    def validate_existing(spec: Dict[str, Any], movement: InventoryMovement) -> None:
        expected = {
            "performed_by": performed_by,
            "source_location_id": spec["source_location_id"],
            "destination_location_id": spec["destination_location_id"],
            "source_stock_status": spec["source_stock_status"],
            "destination_stock_status": spec["destination_stock_status"],
            "product_variant_id": spec["product_variant_id"],
            "batch_id": spec["batch_id"],
            "movement_kind": "PHYSICAL",
            "reservation_action": None,
            "quantity": spec["quantity"],
            "work_session_id": spec["work_session_id"],
            "transfer_header_id": None,
            "stocktake_session_id": session.id,
            "stocktake_count_attempt_id": latest_attempt.id,
            "reference_type": spec["reference_type"],
            "reference_id": spec["reference_id"],
        }
        for field_name, expected_value in expected.items():
            if getattr(movement, field_name) != expected_value:
                raise InventoryMutationError(
                    "سجل حركة جرد موجود يحمل نفس idempotency لكنه لا يطابق النتيجة المعتمدة."
                )

    if session.status == "POSTED":
        if session.posted_at is None:
            raise InventoryMutationError("جلسة POSTED بدون posted_at؛ البيانات غير متسقة.")
        if set(existing_map) != expected_idempotency_keys:
            raise InventoryMutationError(
                "جلسة POSTED لا تحتوي حصراً على مجموعة حركات الجرد المتوقعة."
            )
        ordered_existing = []
        for spec in specs:
            movement = existing_map.get(spec["idempotency_key"])
            if movement is None:
                raise InventoryMutationError("حركة جرد متوقعة مفقودة من جلسة POSTED.")
            validate_existing(spec, movement)
            ordered_existing.append(movement)
        return ordered_existing

    if existing_movements:
        raise InventoryMutationError(
            "تم العثور على حركات جرد سابقة بينما الجلسة ما زالت APPROVED؛ تم رفض الحالة الجزئية."
        )

    positive_rows = {
        (
            spec["product_variant_id"],
            spec["batch_id"],
            spec["stock_status"],
        )
        for spec in specs
        if spec["variance"] > 0
    }
    if positive_rows:
        await _bulk_ensure_inventory_balances(
            db_session,
            company_id=company_id,
            location_id=session.location_id,
            rows=list(positive_rows),
        )

    balance_keys = {
        (
            spec["product_variant_id"],
            spec["batch_id"],
            spec["stock_status"],
        )
        for spec in specs
    }
    balances = []
    if balance_keys:
        balances = (
            await db_session.execute(
                select(InventoryBalance).filter(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id == session.location_id,
                    tuple_(
                        InventoryBalance.product_variant_id,
                        InventoryBalance.batch_id,
                        InventoryBalance.stock_status,
                    ).in_(sorted(balance_keys)),
                ).order_by(
                    InventoryBalance.product_variant_id.asc(),
                    InventoryBalance.batch_id.asc(),
                    InventoryBalance.stock_status.asc(),
                ).with_for_update()
            )
        ).scalars().all()
    balance_map = {
        (row.product_variant_id, row.batch_id, row.stock_status): row
        for row in balances
    }
    if set(balance_map) != balance_keys:
        raise InventoryMutationError("تعذر امتلاك جميع أرصدة الجرد المطلوبة للترحيل.")

    # إعادة تحقق واحدة بعد Row Locks؛ ثابتة التكلفة ولا تتكرر لكل سطر.
    refreshed_locks = (
        await db_session.execute(
            select(InventoryLock).filter(
                InventoryLock.company_id == company_id,
                InventoryLock.location_id == session.location_id,
                InventoryLock.released_at.is_(None),
            ).order_by(InventoryLock.id.asc()).with_for_update()
        )
    ).scalars().all()
    if {lock.id for lock in refreshed_locks} != {lock.id for lock in active_locks}:
        raise InventoryMutationError(
            "تغيرت أقفال الجرد أثناء الترحيل؛ أعد المحاولة لضمان لقطة متسقة."
        )

    before_by_key = {}
    movements = []
    for spec in specs:
        key = (
            spec["product_variant_id"],
            spec["batch_id"],
            spec["stock_status"],
        )
        balance = balance_map[key]
        before_on_hand = int(balance.on_hand_quantity or 0)
        before_reserved = int(balance.reserved_quantity or 0)
        after_on_hand = before_on_hand + int(spec["variance"])
        if after_on_hand < 0:
            raise InventoryMutationError(
                "فرق الجرد سيجعل الرصيد الفعلي سالباً؛ تم رفض الترحيل."
            )
        if after_on_hand < before_reserved:
            raise InventoryMutationError(
                "فرق الجرد سيجعل الرصيد أقل من الكمية المحجوزة؛ حرر الحجوزات أولاً."
            )
        if after_on_hand > _DB_INT_MAX:
            raise InventoryMutationError(
                "الرصيد الناتج من فرق الجرد يتجاوز سعة INTEGER."
            )

        before_by_key[key] = (before_on_hand, before_reserved)
        balance.on_hand_quantity = after_on_hand
        movement = InventoryMovement(
            company_id=company_id,
            performed_by=performed_by,
            source_location_id=spec["source_location_id"],
            destination_location_id=spec["destination_location_id"],
            source_stock_status=spec["source_stock_status"],
            destination_stock_status=spec["destination_stock_status"],
            product_variant_id=spec["product_variant_id"],
            batch_id=spec["batch_id"],
            movement_kind="PHYSICAL",
            reservation_action=None,
            quantity=spec["quantity"],
            work_session_id=spec["work_session_id"],
            transfer_header_id=None,
            stocktake_session_id=session.id,
            stocktake_count_attempt_id=latest_attempt.id,
            reference_type=spec["reference_type"],
            reference_id=spec["reference_id"],
            idempotency_key=spec["idempotency_key"],
            notes="ترحيل فرق آخر محاولة عد معتمدة.",
        )
        db_session.add(movement)
        movements.append((spec, movement, balance))

    await db_session.flush()

    for spec, movement, balance in movements:
        key = (
            spec["product_variant_id"],
            spec["batch_id"],
            spec["stock_status"],
        )
        before_on_hand, before_reserved = before_by_key[key]
        _add_inventory_movement_impact(
            db_session,
            company_id=company_id,
            movement_id=movement.id,
            balance=balance,
            before_on_hand=before_on_hand,
            before_reserved=before_reserved,
        )

    now = utc_now()
    for lock in own_locks:
        lock.released_by = performed_by
        lock.released_at = now
        lock.release_reason = "STOCKTAKE_POSTED"

    session.status = "POSTED"
    session.posted_at = now
    session.updated_at = now

    return [movement for _, movement, _ in movements]


# تخصيص FEFO على الدفعات غير المقفلة؛ يجب استهلاك النتيجة في نفس المعاملة دون commit بين التخصيص والتنفيذ.
async def allocate_fefo_inventory(
    db_session: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    product_variant_id: int,
    quantity: int,
    as_of_date: date,
) -> List[Tuple[int, int]]:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        location_id = _strict_int(location_id, "location_id", minimum=1)
        product_variant_id = _strict_int(
            product_variant_id, "product_variant_id", minimum=1
        )
        quantity = _strict_int(quantity, "quantity", minimum=0)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    if type(as_of_date) is not date:
        raise InventoryMutationError(
            "as_of_date إجباري ويجب أن يكون تاريخ العمل المحلي للشركة."
        )
    if quantity == 0:
        return []

    await acquire_inventory_location_guard(
        db_session,
        company_id,
        location_id,
        exclusive=False,
    )

    location_exists = (
        await db_session.execute(
            select(InventoryLocation.id).filter_by(
                company_id=company_id,
                id=location_id,
                is_active=True,
            ).with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if location_exists is None:
        raise InventoryMutationError("موقع المخزون غير موجود أو غير فعال.")

    # يفحص القفل الشامل وقفل الصنف العام فقط؛ أقفال دفعات بعينها لا يجب أن توقف الصنف كله.
    await check_inventory_lock(
        db_session,
        company_id,
        location_id,
        product_variant_id,
    )

    # استبعاد الدفعات المقفلة جراحياً من FEFO بدلاً من إيقاف الصنف بكامله.
    locked_batches = select(InventoryLock.batch_id).filter(
        InventoryLock.company_id == company_id,
        InventoryLock.location_id == location_id,
        InventoryLock.product_variant_id == product_variant_id,
        InventoryLock.batch_id.is_not(None),
        InventoryLock.released_at.is_(None),
    )

    # نحدد مرشحي FEFO أولاً دون قفل، ثم نأخذ Share Lock على Metadata الدفعات
    # قبل قفل الأرصدة؛ هكذا لا يمكن Recall/تعديل صلاحية أن يتسابق مع التخصيص.
    candidate_batch_stmt = select(ProductBatch.id).join(
        InventoryBalance,
        and_(
            ProductBatch.company_id == InventoryBalance.company_id,
            ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
            ProductBatch.id == InventoryBalance.batch_id,
        ),
    ).filter(
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == location_id,
        InventoryBalance.product_variant_id == product_variant_id,
        InventoryBalance.stock_status == "AVAILABLE",
        InventoryBalance.on_hand_quantity > InventoryBalance.reserved_quantity,
        ProductBatch.is_active.is_(True),
        or_(
            ProductBatch.production_date.is_(None),
            ProductBatch.production_date <= as_of_date,
        ),
        ProductBatch.expiry_date >= as_of_date,
        ~InventoryBalance.batch_id.in_(locked_batches),
    ).order_by(
        ProductBatch.expiry_date.asc(),
        ProductBatch.id.asc(),
    )
    candidate_batch_ids = (
        await db_session.execute(candidate_batch_stmt)
    ).scalars().all()

    locked_batch_ids: List[int] = []
    if candidate_batch_ids:
        stmt_batch_metadata = select(ProductBatch.id).filter(
            ProductBatch.company_id == company_id,
            ProductBatch.product_variant_id == product_variant_id,
            ProductBatch.id.in_(candidate_batch_ids),
            ProductBatch.is_active.is_(True),
            or_(
                ProductBatch.production_date.is_(None),
                ProductBatch.production_date <= as_of_date,
            ),
            ProductBatch.expiry_date >= as_of_date,
        ).order_by(
            ProductBatch.expiry_date.asc(),
            ProductBatch.id.asc(),
        ).with_for_update(read=True)
        locked_batch_ids = (
            await db_session.execute(stmt_batch_metadata)
        ).scalars().all()

    if locked_batch_ids:
        stmt = select(InventoryBalance, ProductBatch).join(
            ProductBatch,
            and_(
                ProductBatch.company_id == InventoryBalance.company_id,
                ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
                ProductBatch.id == InventoryBalance.batch_id,
            ),
        ).filter(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
            InventoryBalance.product_variant_id == product_variant_id,
            InventoryBalance.stock_status == "AVAILABLE",
            InventoryBalance.on_hand_quantity > InventoryBalance.reserved_quantity,
            InventoryBalance.batch_id.in_(locked_batch_ids),
            ~InventoryBalance.batch_id.in_(locked_batches),
        ).order_by(
            ProductBatch.expiry_date.asc(),
            ProductBatch.id.asc(),
        ).with_for_update(of=InventoryBalance)
        rows = (await db_session.execute(stmt)).all()
    else:
        rows = []

    # بعد امتلاك Row Locks نعيد فحص الأقفال لمنع سباق جرد بدأ أثناء تنفيذ استعلام FEFO.
    await check_inventory_lock(
        db_session,
        company_id,
        location_id,
        product_variant_id,
    )
    if rows:
        selected_batch_ids = [batch.id for _, batch in rows]
        stmt_new_batch_locks = select(InventoryLock.batch_id).filter(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == location_id,
            InventoryLock.product_variant_id == product_variant_id,
            InventoryLock.batch_id.in_(selected_batch_ids),
            InventoryLock.released_at.is_(None),
        )
        newly_locked_batches = set(
            (await db_session.execute(stmt_new_batch_locks)).scalars().all()
        )
        if newly_locked_batches:
            raise InventoryMutationError(
                "بدأ جرد على إحدى دفعات FEFO أثناء التخصيص؛ أعد المحاولة بعد انتهاء الجرد."
            )

    remaining = quantity
    allocation: List[Tuple[int, int]] = []

    for balance, batch in rows:
        available = int(balance.on_hand_quantity or 0) - int(balance.reserved_quantity or 0)
        if available <= 0:
            continue

        take = min(available, remaining)
        allocation.append((batch.id, take))
        remaining -= take
        if remaining == 0:
            break

    if remaining > 0:
        raise InventoryMutationError(
            f"الرصيد المتاح غير المقفل وغير المنتهي لا يغطي الكمية المطلوبة. العجز: {remaining} حبة."
        )

    return allocation


# عكس حركة زيارة سابقة فقط؛ الحوالات والجرد والاستلامات تستخدم مساراتها الرقابية المخصصة.
async def reverse_inventory_movement(
    db_session: AsyncSession,
    *,
    original: InventoryMovement,
    performed_by: int,
    reference_type: str,
    reference_id: str,
    notes: Optional[str] = None,
) -> InventoryMovement:
    """يعكس حركة VISIT_* مرة واحدة فقط ويمنع تجاوز دورات الحياة المحكومة."""
    try:
        original_id = _strict_int(getattr(original, "id", None), "original.id", minimum=1)
        company_id = _strict_int(
            getattr(original, "company_id", None),
            "original.company_id",
            minimum=1,
        )
        performed_by = _strict_int(performed_by, "performed_by", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    reference_type = str(reference_type or "").strip()
    reference_id = str(reference_id or "").strip()
    if not reference_type or not reference_id:
        raise InventoryMutationError("مرجع الحركة العكسية إلزامي.")
    if "\x00" in reference_type or "\x00" in reference_id:
        raise InventoryMutationError("مرجع الحركة العكسية لا يقبل محرف NUL.")
    if len(reference_type) > 50 or len(reference_id) > 100:
        raise InventoryMutationError("مرجع الحركة العكسية أطول من الحد المسموح.")
    if notes is not None and not isinstance(notes, str):
        raise InventoryMutationError("notes يجب أن تكون نصاً أو None.")
    if notes is not None and "\x00" in notes:
        raise InventoryMutationError("notes لا تقبل محرف NUL.")

    # لا نثق بكائن ORM الممرر وحده؛ نقرأ الحركة الأصلية المقفلة من قاعدة البيانات.
    stmt_original = select(InventoryMovement).filter_by(
        company_id=company_id,
        id=original_id,
    ).with_for_update()
    persisted = (await db_session.execute(stmt_original)).scalar_one_or_none()
    if persisted is None:
        raise InventoryMutationError(
            "الحركة الأصلية غير موجودة أو لا تتبع الشركة المحددة."
        )

    # هذا المسار مخصص حصراً لإلغاء أثر زيارة قبل إعادة تحريرها.
    # الحوالات والجرد والاستلامات لها دورة حياة رقابية مستقلة ولا يجوز
    # تجاوزها عبر Reversal عام.
    if (
        persisted.transfer_header_id is not None
        or persisted.stocktake_session_id is not None
        or not str(persisted.reference_type or "").startswith("VISIT_")
        or persisted.reference_type == "VISIT_REVERSAL"
    ):
        raise InventoryMutationError(
            "هذه الحركة ليست حركة زيارة قابلة للعكس عبر هذا المسار."
        )

    reversal_key = f"REV-MOV-{company_id}-{persisted.id}"

    # نفس مفتاح العكس يأخذ Advisory Lock قبل فحص السجل لضمان Reversal واحد تحت التزامن.
    advisory_key = f"inventory:{company_id}:{reversal_key}"
    await db_session.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(advisory_key)))
    )

    existing = (
        await db_session.execute(
            select(InventoryMovement).filter_by(
                company_id=company_id,
                idempotency_key=reversal_key,
            )
        )
    ).scalar_one_or_none()

    if persisted.movement_kind == "RESERVATION":
        expected_reservation_action = (
            "RELEASE"
            if persisted.reservation_action == "RESERVE"
            else "RESERVE"
        )
    else:
        expected_reservation_action = None

    expected_inverse = {
        "source_location_id": (
            persisted.destination_location_id
            if persisted.movement_kind == "PHYSICAL"
            else persisted.source_location_id
        ),
        "destination_location_id": (
            persisted.source_location_id
            if persisted.movement_kind == "PHYSICAL"
            else persisted.destination_location_id
        ),
        "source_stock_status": (
            persisted.destination_stock_status
            if persisted.movement_kind in {"PHYSICAL", "STATUS_CHANGE"}
            else persisted.source_stock_status
        ),
        "destination_stock_status": (
            persisted.source_stock_status
            if persisted.movement_kind in {"PHYSICAL", "STATUS_CHANGE"}
            else persisted.destination_stock_status
        ),
        "product_variant_id": persisted.product_variant_id,
        "batch_id": persisted.batch_id,
        "movement_kind": persisted.movement_kind,
        "reservation_action": expected_reservation_action,
        "quantity": persisted.quantity,
        "work_session_id": persisted.work_session_id,
        "transfer_header_id": persisted.transfer_header_id,
        "stocktake_session_id": persisted.stocktake_session_id,
        "stocktake_count_attempt_id": persisted.stocktake_count_attempt_id,
    }

    if existing is not None:
        # نفس الحركة لا يجوز أن تُعكس مرتين بسياقين تجاريين مختلفين.
        if (
            existing.reference_type != reference_type
            or existing.reference_id != reference_id
        ):
            raise InventoryMutationError(
                "الحركة الأصلية عُكست مسبقاً بواسطة عملية مختلفة."
            )

        for field_name, expected_value in expected_inverse.items():
            if getattr(existing, field_name) != expected_value:
                raise InventoryMutationError(
                    "تم اكتشاف تعارض أو فساد في سجل الحركة العكسية الموجود."
                )
        return existing

    common = dict(
        db_session=db_session,
        company_id=company_id,
        performed_by=performed_by,
        product_variant_id=persisted.product_variant_id,
        batch_id=persisted.batch_id,
        quantity=persisted.quantity,
        work_session_id=persisted.work_session_id,
        transfer_header_id=persisted.transfer_header_id,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=reversal_key,
        notes=notes,
    )

    if persisted.movement_kind == "PHYSICAL":
        return await apply_inventory_movement(
            **common,
            movement_kind="PHYSICAL",
            source_location_id=persisted.destination_location_id,
            destination_location_id=persisted.source_location_id,
            source_stock_status=persisted.destination_stock_status,
            destination_stock_status=persisted.source_stock_status,
        )

    if persisted.movement_kind == "RESERVATION":
        return await apply_inventory_movement(
            **common,
            movement_kind="RESERVATION",
            reservation_action=expected_reservation_action,
            source_location_id=persisted.source_location_id,
            destination_location_id=persisted.destination_location_id,
            source_stock_status=persisted.source_stock_status,
            destination_stock_status=persisted.destination_stock_status,
        )

    if persisted.movement_kind == "STATUS_CHANGE":
        return await apply_inventory_movement(
            **common,
            movement_kind="STATUS_CHANGE",
            source_location_id=persisted.source_location_id,
            destination_location_id=persisted.destination_location_id,
            source_stock_status=persisted.destination_stock_status,
            destination_stock_status=persisted.source_stock_status,
        )

    raise InventoryMutationError("لا يمكن عكس نوع الحركة المحدد.")

def format_qty(total_packs: int, packs_per_carton: int) -> str:
    """تحويل الحبات إلى تمثيل كراتين/حبات دون السماح بكميات كسرية."""
    total = _strict_int(
        total_packs,
        "total_packs",
        minimum=-_DB_BIGINT_MAX,
        maximum=_DB_BIGINT_MAX,
    )
    ppc = _strict_int(packs_per_carton, "packs_per_carton", minimum=1)

    if ppc == 1:
        return f"{total} حبة"

    is_negative = total < 0
    abs_total = abs(total)
    cartons, packs = divmod(abs_total, ppc)

    parts = []
    if cartons > 0:
        parts.append(f"{cartons} كرتونة")
    if packs > 0:
        parts.append(f"{packs} حبة")

    result = " و ".join(parts) if parts else "0 حبة"
    return f"-{result}" if is_negative and result != "0 حبة" else result

class InventoryReversalError(Exception):
    """خطأ مخصص لالتقاط فشل استرجاع العهدة دون التسبب بـ 500 Crash"""
    pass


# عكس زيارة سابقة مالياً ومخزنياً تحت قفل هرمي وبالاعتماد على InventoryMovement فقط.
async def reverse_previous_visit_state(
    db_session: AsyncSession,
    visit: Visit,
    active_session: Optional[WorkSession],
    shop: Shop,
    admin_id: int,
) -> None:
    try:
        company_id = _strict_int(shop.company_id, "company_id", minimum=1)
        admin_id = _strict_int(admin_id, "admin_id", minimum=1)
        visit_id = _strict_int(visit.id, "visit_id", minimum=1)
        shop_id = _strict_int(shop.id, "shop_id", minimum=1)
    except ValueError as exc:
        raise InventoryReversalError(str(exc)) from exc

    # نعيد امتلاك الأقفال داخل الخدمة بنفس الترتيب الرسمي: session -> shop -> visit.
    locked_session = None
    if active_session is not None:
        stmt_session = select(WorkSession).filter_by(
            company_id=company_id,
            id=active_session.id,
        ).with_for_update()
        locked_session = (
            await db_session.execute(stmt_session)
        ).scalar_one_or_none()
        if locked_session is None:
            raise InventoryReversalError(
                "جلسة العمل غير موجودة أو لا تنتمي لنفس الشركة."
            )

    stmt_shop = select(Shop).filter_by(
        company_id=company_id,
        id=shop_id,
    ).with_for_update()
    locked_shop = (await db_session.execute(stmt_shop)).scalar_one_or_none()
    if locked_shop is None:
        raise InventoryReversalError(
            "المحل غير موجود أو لا ينتمي لنفس الشركة."
        )

    stmt_visit = select(Visit).filter_by(
        company_id=company_id,
        id=visit_id,
    ).with_for_update()
    locked_visit = (await db_session.execute(stmt_visit)).scalar_one_or_none()
    if locked_visit is None:
        raise InventoryReversalError(
            "الزيارة غير موجودة أو لا تنتمي لنفس الشركة."
        )

    if locked_visit.shop_id != locked_shop.id:
        raise InventoryReversalError(
            "مرفوض: الزيارة لا ترتبط بالمحل المحدد."
        )

    if locked_session is not None:
        if locked_visit.work_session_id != locked_session.id:
            raise InventoryReversalError(
                "مرفوض: الزيارة لا تنتمي لجلسة العمل التي يجري عكسها."
            )
        if locked_visit.driver_id != locked_session.driver_id:
            raise InventoryReversalError(
                "مرفوض: مندوب الزيارة لا يطابق مندوب جلسة العمل."
            )
        if locked_session.is_settled:
            raise InventoryReversalError(
                "مرفوض: لا يمكن عكس زيارة تابعة لجلسة تمت تسويتها واعتمادها."
            )
    elif locked_visit.work_session_id is not None:
        raise InventoryReversalError(
            "مرفوض: الزيارة مرتبطة بجلسة عمل ويجب تمرير الجلسة نفسها عند العكس."
        )

    if locked_visit.status != "Completed":
        raise InventoryReversalError(
            "لا يمكن عكس زيارة إلا إذا كانت حالتها Completed."
        )
    if locked_visit.outcome not in {"Sale", "NoSale"}:
        raise InventoryReversalError(
            "حالة الزيارة المكتملة غير قابلة للعكس بهذا المسار."
        )

    actor_exists = (
        await db_session.execute(
            select(Driver.id).filter_by(
                company_id=company_id,
                id=admin_id,
                is_active=True,
            )
        )
    ).scalar_one_or_none()
    if actor_exists is None:
        raise InventoryReversalError(
            "المستخدم المنفذ غير موجود أو غير فعال في هذه الشركة."
        )

    # نقفل تفاصيل الزيارة كي لا تتغير بالتوازي أثناء بناء القيد العكسي.
    stmt_items = select(VisitItem).filter_by(
        company_id=company_id,
        visit_id=locked_visit.id,
    ).order_by(VisitItem.id.asc()).with_for_update()
    visit_items = (await db_session.execute(stmt_items)).scalars().all()

    stmt_returns = select(VisitReturn).filter_by(
        company_id=company_id,
        visit_id=locked_visit.id,
    ).order_by(VisitReturn.id.asc()).with_for_update()
    visit_returns = (await db_session.execute(stmt_returns)).scalars().all()

    try:
        old_cash = _money_12_3(
            locked_visit.cash_collected or "0.0",
            "visit.cash_collected",
        )
        old_debt_paid = _money_12_3(
            locked_visit.debt_paid or "0.0",
            "visit.debt_paid",
        )
        current_bal = _money_12_3(
            locked_shop.current_balance or "0.0",
            "shop.current_balance",
        )
        final_amount_due = _money_12_3(
            locked_visit.final_amount_due or "0.0",
            "visit.final_amount_due",
        )
    except ValueError as exc:
        raise InventoryReversalError(str(exc)) from exc

    if old_cash > Decimal("0") or old_debt_paid > Decimal("0"):
        raise InventoryReversalError(
            f"مرفوض أمنياً ومحاسبياً: لا يمكن التراجع عن زيارة تم فيها تحصيل "
            f"كاش ({old_cash}) أو سداد ذمة ({old_debt_paid}). "
            "يجب إصدار قيد عكسي مالي مستقل."
        )

    net_visit_debt = final_amount_due - old_cash
    new_balance = current_bal - net_visit_debt + old_debt_paid
    if new_balance < Decimal("0"):
        raise InventoryReversalError(
            f"فشل التراجع: رصيد المحل الحالي ({current_bal}) "
            "لا يغطي أثر الزيارة السابقة."
        )

    active_items = (
        [
            item
            for item in visit_items
            if not getattr(item, "is_cancelled", False)
        ]
        if locked_visit.outcome in {"Sale", "NoSale"}
        else []
    )
    active_returns = [
        item
        for item in visit_returns
        if not getattr(item, "is_cancelled", False)
    ]

    # وجود سطر صفري لا يعني وجود أثر مخزني؛ الأثر الحقيقي هو أي كمية
    # مبيعات/بونص/عينات/مرتجع موجبة.
    has_inventory_effect = any(
        (item.quantity or 0) > 0
        or (item.packs_quantity or 0) > 0
        or (item.bonus_quantity or 0) > 0
        or (item.sample_quantity or 0) > 0
        or (item.sample_packs_quantity or 0) > 0
        for item in active_items
    ) or any(
        (item.quantity or 0) > 0
        or (item.packs_quantity or 0) > 0
        for item in active_returns
    )

    if locked_session is not None:
        stmt_movements = select(InventoryMovement).filter(
            InventoryMovement.company_id == company_id,
            InventoryMovement.work_session_id == locked_session.id,
            InventoryMovement.reference_id == str(locked_visit.id),
            InventoryMovement.reference_type.like(r"VISIT\_%", escape="\\"),
            InventoryMovement.reference_type != "VISIT_REVERSAL",
        ).order_by(
            InventoryMovement.created_at.desc(),
            InventoryMovement.id.desc(),
        )
        movements = (await db_session.execute(stmt_movements)).scalars().all()

        if has_inventory_effect and not movements:
            raise InventoryReversalError(
                "مرفوض: لا توجد حركات مخزون موحدة مرتبطة بهذه الزيارة؛ "
                "لن يتم تعديل الرصيد بالتخمين."
            )

        for movement in movements:
            try:
                await reverse_inventory_movement(
                    db_session,
                    original=movement,
                    performed_by=admin_id,
                    reference_type="VISIT_REVERSAL",
                    reference_id=str(locked_visit.id),
                    notes=(
                        f"عكس الزيارة {locked_visit.id} "
                        f"للمحل {locked_shop.name}"
                    ),
                )
            except InventoryMutationError as exc:
                raise InventoryReversalError(str(exc)) from exc
    elif has_inventory_effect:
        raise InventoryReversalError(
            "لا يمكن عكس أثر مخزني لزيارة بدون جلسة عمل مرتبطة."
        )

    for item in active_items:
        item.is_cancelled = True
    for ret in active_returns:
        ret.is_cancelled = True

    locked_shop.current_balance = new_balance
    locked_visit.amount_before_tax_and_discount = Decimal("0.0")
    locked_visit.discount_applied = Decimal("0.0")
    locked_visit.tax_percentage_applied = Decimal("0.0")
    locked_visit.tax_amount = Decimal("0.0")
    locked_visit.final_amount_due = Decimal("0.0")
    locked_visit.cash_collected = Decimal("0.0")
    locked_visit.debt_paid = Decimal("0.0")
    locked_visit.shop_balance_before = None
    locked_visit.shop_balance_after = None
    locked_visit.tax_qr_code = None
    locked_visit.no_sale_reason = None
    locked_visit.outcome = "Pending"
    locked_visit.status = "Pending"

# =================================================================================
# [المرحلة الثالثة] البند 5: Isolation Middleware (درع البنية التحتية للـ SaaS)
# =================================================================================

def get_tenant_cache_key(company_id: int, base_key: str) -> str:
    try:
        comp_id = _strict_int(company_id, "company_id", minimum=1)
    except ValueError as exc:
        raise ValueError("خطأ أمني: رمز الشركة غير صالح.") from exc

    if not isinstance(base_key, str) or not base_key.strip():
        raise ValueError("خطأ أمني: مفتاح الكاش غير صالح.")

    return f"tenant_{comp_id}:{base_key.strip()}"


def get_tenant_storage_path(company_id: int, filename: str) -> str:
    """
    Storage Isolation: يعيد مساراً داخل مجلد الشركة حصراً ويرفض أي مكوّن مسار
    أو symlink يخرج عن الجذر المخصص للـTenant.
    """
    try:
        comp_id = _strict_int(company_id, "company_id", minimum=1)
    except ValueError as exc:
        raise ValueError("خطأ أمني: رمز الشركة غير صالح.") from exc

    if not isinstance(filename, str):
        raise ValueError("خطأ أمني: اسم الملف غير صالح.")

    clean_name = filename.strip()
    if (
        not clean_name
        or clean_name in {".", ".."}
        or "\x00" in clean_name
        or "/" in clean_name
        or "\\" in clean_name
        or os.path.basename(clean_name) != clean_name
    ):
        raise ValueError("خطأ أمني: اسم الملف يجب أن يكون اسماً مجرداً دون مسار.")

    if len(clean_name.encode("utf-8")) > 255:
        raise ValueError("خطأ أمني: اسم الملف أطول من الحد الآمن لنظام الملفات.")

    base_path = getattr(Config, "STORAGE_BASE_PATH", "local_storage/")
    tenant_folder = os.path.realpath(
        os.path.join(base_path, f"company_{comp_id}")
    )
    target_path = os.path.realpath(os.path.join(tenant_folder, clean_name))

    try:
        common_root = os.path.commonpath([tenant_folder, target_path])
    except ValueError as exc:
        raise ValueError("خطأ أمني: مسار التخزين غير صالح.") from exc

    if common_root != tenant_folder:
        raise ValueError("خطأ أمني: مسار الملف يقع خارج نطاق الشركة.")

    return target_path


def enforce_tenant_background_job(company_id: int, **kwargs) -> dict:
    try:
        comp_id = _strict_int(company_id, "company_id", minimum=1)
    except ValueError as exc:
        raise ValueError(
            "خطأ أمني: لا يمكن إرسال مهمة خلفية بدون رمز شركة صالح."
        ) from exc

    kwargs["company_id"] = comp_id
    return kwargs

# فحص قفل مخزون فعال باستعلام واحد؛ تجاوز قفل الجرد متاح فقط داخل خدمة ترحيل الجرد المتخصصة.
async def check_inventory_lock(
    db_session: AsyncSession,
    company_id: int,
    location_id: int,
    variant_id: Optional[int] = None,
    batch_id: Optional[int] = None,
) -> None:
    company_id = _strict_int(company_id, "company_id", minimum=1)
    location_id = _strict_int(location_id, "location_id", minimum=1)
    variant_id = _optional_positive_int(variant_id, "variant_id")
    batch_id = _optional_positive_int(batch_id, "batch_id")

    if batch_id is not None and variant_id is None:
        raise ValueError("batch_id لا يمكن استخدامه بدون variant_id.")

    scope_filters = [
        and_(
            InventoryLock.product_variant_id.is_(None),
            InventoryLock.batch_id.is_(None),
        )
    ]
    if variant_id is not None:
        if batch_id is None:
            scope_filters.append(
                and_(
                    InventoryLock.product_variant_id == variant_id,
                    InventoryLock.batch_id.is_(None),
                )
            )
        else:
            scope_filters.append(
                and_(
                    InventoryLock.product_variant_id == variant_id,
                    or_(
                        InventoryLock.batch_id.is_(None),
                        InventoryLock.batch_id == batch_id,
                    ),
                )
            )

    stmt = select(InventoryLock.id).filter(
        InventoryLock.company_id == company_id,
        InventoryLock.location_id == location_id,
        InventoryLock.released_at.is_(None),
        or_(*scope_filters),
    ).limit(1)
    if (await db_session.execute(stmt)).first():
        if variant_id is None:
            raise ValueError(f"الموقع ({location_id}) تحت الجرد ومقفل بالكامل.")
        raise ValueError("الصنف/الدفعة مقفل جراحياً بسبب جرد نشط.")
