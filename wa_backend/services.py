import os
from config import Config
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import UUID, uuid4
from sqlalchemy import select, func, and_, or_, tuple_, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from models import (
    SystemSetting,
    Company,
    OfferRule,
    ProductVariant,
    Driver,
    Shop,
    ShortageRequest,
    WorkSession,
    SessionInventorySnapshot,
    DispatchRoute,
    Visit,
    VisitItem,
    VisitReturn,
    InventoryLock,
    InventoryLocation,
    InventoryStockPolicy,
    InventoryBalance,
    InventoryMovement,
    InventoryMovementImpact,
    ProductBatch,
    OperationIdempotency,
    StocktakeSession,
    StocktakeLine,
    StocktakeCountAttempt,
    StocktakeCountAttemptLine,
    utc_now,
)

from typing import Any, Type, Optional, List, Dict, Tuple
from quantity import QUANTITY_MAX, QuantityError, parse_quantity, validate_variant_quantity
from product_lifecycle import acquire_product_lifecycle_guards, record_domain_event


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


def _quantity_decimal(
    value: Any,
    field_name: str = "quantity",
    *,
    allow_zero: bool = True,
    allow_negative: bool = False,
) -> Decimal:
    try:
        return parse_quantity(
            value,
            field_name,
            allow_zero=allow_zero,
            allow_negative=allow_negative,
        )
    except QuantityError as exc:
        raise InventoryMutationError(str(exc)) from exc


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

    stmt_driver = select(Driver).execution_options(populate_existing=True).filter_by(
        id=driver_id,
        company_id=company_id,
        is_active=True,
        can_allow_debt=True,
    ).with_for_update(read=True)
    driver = (await db_session.execute(stmt_driver)).scalar_one_or_none()

    # لا نعتمد أي Shop pre-fetched في القرار المالي؛ يجب قفل الصف الحقيقي دائماً.
    stmt_shop = select(Shop).execution_options(populate_existing=True).filter_by(
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



# PATCH: STAGE4D_BATCH_DISPOSITION_PORTION_STATUS

_INVENTORY_STOCK_STATUSES = frozenset({
    "AVAILABLE",
    "QUARANTINED",
    "BLOCKED",
    "RECALLED",
    "DAMAGED",
    "DISPOSAL_PENDING",
})

# STAGE4D1_HARDENING
# Stage 4D.1: keep the generic same-location reclassification command narrow.
# Transfer-purpose operations (return / recall-return / quarantine transfer /
# disposal) are NOT represented here; Stage 4E owns those directional workflows.
# This command supports only local safety escalation plus explicit quarantine release.
_PORTION_STATUS_TRANSITIONS = {
    "AVAILABLE": frozenset({"QUARANTINED", "BLOCKED", "RECALLED"}),
    "QUARANTINED": frozenset({"AVAILABLE", "BLOCKED", "RECALLED"}),
    "BLOCKED": frozenset({"RECALLED"}),
    "RECALLED": frozenset(),
    "DAMAGED": frozenset(),
    "DISPOSAL_PENDING": frozenset(),
}

_BATCH_DISPOSITIONS = frozenset({
    "RELEASED", "QUARANTINED", "BLOCKED", "RECALLED",
})

# Explicit Batch disposition commands only.
# QUARANTINED -> RELEASED is the documented Test/Release path.
# RECALLED is terminal here; return/quarantine/disposal of recalled physical stock
# belongs to Stage 4E transfer-purpose workflows, not a generic disposition patch.
_BATCH_DISPOSITION_TRANSITIONS = {
    "RELEASED": frozenset({"QUARANTINED", "BLOCKED", "RECALLED"}),
    "QUARANTINED": frozenset({"RELEASED", "BLOCKED", "RECALLED"}),
    "BLOCKED": frozenset({"RECALLED"}),
    "RECALLED": frozenset(),
}


class InventoryRuleError(InventoryMutationError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.code = str(code)
        self.context = dict(context or {})
        super().__init__(message)

    def as_detail(self) -> Dict[str, Any]:
        return inventory_business_error(
            self.code,
            str(self),
            context=self.context,
        )


async def change_product_batch_disposition(
    db_session: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    batch_id: int,
    expected_revision: int,
    target_disposition: str,
    reason: str,
    request_id: UUID,
) -> ProductBatch:
    """Batch-wide safety overlay; never rewrites portion stock_status implicitly."""
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        actor_id = _strict_int(actor_id, "actor_id", minimum=1)
        batch_id = _strict_int(batch_id, "batch_id", minimum=1)
        expected_revision = _strict_int(
            expected_revision,
            "expected_revision",
            minimum=1,
        )
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    target = str(target_disposition or "").strip().upper()
    if target not in _BATCH_DISPOSITIONS:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_INVALID",
            "حالة الدفعة المطلوبة غير صالحة.",
            context={"batch_id": batch_id, "target_disposition": target},
        )

    if not isinstance(reason, str):
        raise InventoryMutationError("سبب تغيير حالة الدفعة يجب أن يكون نصاً.")
    reason = reason.strip()
    if not reason or "\x00" in reason or len(reason) > 2000:
        raise InventoryMutationError(
            "سبب تغيير حالة الدفعة مطلوب ويجب ألا يتجاوز 2000 حرف."
        )
    if not isinstance(request_id, UUID):
        raise InventoryMutationError("request_id يجب أن يكون UUID صالحاً.")

    # قراءة الهوية فقط قبل الحارس؛ القرار نفسه يعاد تحت shared lifecycle guard
    # ثم Row Lock على ProductBatch، وهو نفس الصف الذي تقفله FEFO في Stage 4C.
    variant_id = (
        await db_session.execute(
            select(ProductBatch.product_variant_id).filter(
                ProductBatch.company_id == company_id,
                ProductBatch.id == batch_id,
            )
        )
    ).scalar_one_or_none()
    if variant_id is None:
        raise InventoryRuleError(
            "BATCH_NOT_FOUND",
            "الدفعة غير موجودة أو لا تتبع الشركة.",
            context={"batch_id": batch_id},
        )
    variant_id = int(variant_id)

    await acquire_product_lifecycle_guards(
        db_session,
        company_id,
        [variant_id],
        exclusive=False,
    )

    batch = (
        await db_session.execute(
            select(ProductBatch)
            .execution_options(populate_existing=True)
            .filter(
                ProductBatch.company_id == company_id,
                ProductBatch.id == batch_id,
                ProductBatch.product_variant_id == variant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if batch is None:
        raise InventoryRuleError(
            "BATCH_NOT_FOUND",
            "الدفعة تغيرت أو لم تعد متاحة داخل الشركة.",
            context={"batch_id": batch_id},
        )

    variant_state = (
        await db_session.execute(
            select(
                ProductVariant.lifecycle_status,
                ProductVariant.operational_hold,
            ).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id == variant_id,
            )
        )
    ).one_or_none()
    if variant_state is None:
        raise InventoryMutationError("الصنف المرتبط بالدفعة غير موجود داخل الشركة.")

    if not bool(batch.is_active):
        raise InventoryRuleError(
            "BATCH_INACTIVE",
            "الدفعة متوقفة إدارياً ولا تقبل تغيير disposition جديداً.",
            context={"batch_id": batch_id},
        )

    current_revision = int(batch.disposition_revision)
    if current_revision != expected_revision:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_REVISION_CONFLICT",
            "تغيرت حالة الدفعة منذ فتحها. حدّث البيانات ثم أعد المحاولة.",
            context={
                "batch_id": batch_id,
                "expected_revision": expected_revision,
                "current_revision": current_revision,
            },
        )

    current = str(batch.disposition or "").strip().upper()
    if current not in _BATCH_DISPOSITIONS:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_INVALID",
            "الدفعة تحمل disposition غير معروف.",
            context={"batch_id": batch_id, "current_disposition": current},
        )
    if current == target:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_NO_CHANGE",
            "الدفعة موجودة بالفعل بالحالة المطلوبة.",
            context={"batch_id": batch_id, "disposition": current},
        )
    if target not in _BATCH_DISPOSITION_TRANSITIONS[current]:
        raise InventoryRuleError(
            "BATCH_DISPOSITION_TRANSITION_BLOCKED",
            "انتقال disposition المطلوب غير مسموح حسب مصفوفة Stage 4.",
            context={
                "batch_id": batch_id,
                "from": current,
                "to": target,
            },
        )

    lifecycle_status = str(variant_state.lifecycle_status or "").upper()
    operational_hold = str(variant_state.operational_hold or "").upper()
    if lifecycle_status in {"DRAFT", "ARCHIVED"}:
        raise InventoryRuleError(
            "PRODUCT_NOT_OPERATIONAL",
            "حالة الصنف لا تسمح بأمر disposition تشغيلي جديد.",
            context={
                "product_variant_id": variant_id,
                "lifecycle_status": lifecycle_status,
            },
        )
    if target == "RELEASED" and operational_hold != "NONE":
        hold_code = (
            "PRODUCT_RECALLED"
            if operational_hold == "RECALL"
            else "PRODUCT_SALES_HOLD"
        )
        raise InventoryRuleError(
            hold_code,
            "لا يمكن تحرير الدفعة إلى RELEASED أثناء وجود Hold تشغيلي على الصنف.",
            context={
                "product_variant_id": variant_id,
                "batch_id": batch_id,
                "operational_hold": operational_hold,
            },
        )

    before = {
        "id": int(batch.id),
        "product_variant_id": variant_id,
        "disposition": current,
        "disposition_reason": batch.disposition_reason,
        "disposition_revision": current_revision,
    }

    batch.disposition = target
    batch.disposition_reason = reason
    batch.disposition_revision = current_revision + 1
    batch.updated_at = utc_now()

    after = {
        "id": int(batch.id),
        "product_variant_id": variant_id,
        "disposition": target,
        "disposition_reason": reason,
        "disposition_revision": current_revision + 1,
    }

    record_domain_event(
        db_session,
        company_id=company_id,
        actor_id=actor_id,
        request_id=request_id,
        event_type="BatchDispositionChanged",
        entity_type="ProductBatch",
        entity_id=batch_id,
        reason=reason,
        before=before,
        after=after,
        emit_outbox=True,
    )
    await db_session.flush()
    return batch



def inventory_business_error(
    code: str,
    message: str,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "context": dict(context or {}),
    }


def warehouse_setup_required_detail() -> Dict[str, Any]:
    return inventory_business_error(
        "WAREHOUSE_SETUP_REQUIRED",
        "يجب إنشاء مستودع فعال قبل تنفيذ هذه العملية.",
    )


# PATCH: STAGE4C_SYNCHRONOUS_BATCH_ELIGIBILITY
def batch_sellability_predicate(
    as_of_date: date,
    *,
    expiry_control_mode,
    minimum_remaining_shelf_life_days=None,
):
    """SQL predicate موحد لصلاحية Batch للبيع/التحميل/الحوالة العادية."""
    if type(as_of_date) is not date:
        raise ValueError("as_of_date يجب أن يكون date صريحاً.")

    min_days = (
        func.coalesce(minimum_remaining_shelf_life_days, 0)
        if minimum_remaining_shelf_life_days is not None
        else 0
    )
    expiry_meets_policy = and_(
        ProductBatch.expiry_date.is_not(None),
        (ProductBatch.expiry_date - as_of_date) >= min_days,
    )
    no_expiry_allowed = and_(
        ProductBatch.expiry_date.is_(None),
        min_days == 0,
    )

    return and_(
        ProductBatch.is_active.is_(True),
        ProductBatch.disposition == "RELEASED",
        or_(
            ProductBatch.production_date.is_(None),
            ProductBatch.production_date <= as_of_date,
        ),
        or_(
            and_(
                expiry_control_mode == "NONE",
                no_expiry_allowed,
            ),
            and_(
                expiry_control_mode == "OPTIONAL",
                or_(no_expiry_allowed, expiry_meets_policy),
            ),
            and_(
                expiry_control_mode == "REQUIRED",
                expiry_meets_policy,
            ),
        ),
    )


def _batch_metadata_is_sellable(
    *,
    as_of_date: date,
    expiry_control_mode: str,
    production_date: Optional[date],
    expiry_date: Optional[date],
    minimum_remaining_shelf_life_days: int,
) -> bool:
    """نفس عقد SQL أعلاه لصفوف Metadata المقفلة داخل FEFO."""
    if type(as_of_date) is not date:
        raise InventoryMutationError("as_of_date يجب أن يكون date صريحاً.")

    mode = str(expiry_control_mode or "").strip().upper()
    if mode not in {"NONE", "OPTIONAL", "REQUIRED"}:
        raise InventoryMutationError("expiry_control_mode غير صالح للصنف.")

    try:
        min_days = _strict_int(
            minimum_remaining_shelf_life_days,
            "minimum_remaining_shelf_life_days",
            minimum=0,
        )
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    if production_date is not None and production_date > as_of_date:
        return False

    # لا يمكن إثبات Minimum Shelf Life موجب بدون expiry_date؛ نفشل مغلقاً.
    if mode == "NONE":
        return expiry_date is None and min_days == 0

    if expiry_date is None:
        return mode == "OPTIONAL" and min_days == 0

    return expiry_date >= as_of_date + timedelta(days=min_days)


# تثبيت أن VEHICLE_RECON مرتبط بجلسة عمل منتهية وغير مسواة وبنفس السيارة داخل Tenant واحد.
async def validate_vehicle_recon_work_session(
    db_session: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
    vehicle_id: int,
) -> WorkSession:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        work_session_id = _strict_int(
            work_session_id, "work_session_id", minimum=1
        )
        vehicle_id = _strict_int(vehicle_id, "vehicle_id", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    work_session = (
        await db_session.execute(
            select(WorkSession)
            .execution_options(populate_existing=True)
            .filter_by(
                company_id=company_id,
                id=work_session_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if work_session is None:
        raise InventoryMutationError(
            "جلسة العمل غير موجودة أو لا تتبع الشركة."
        )

    if work_session.end_time is None:
        raise InventoryMutationError(
            "لا يمكن بدء أو ترحيل VEHICLE_RECON قبل إنهاء جلسة العمل."
        )

    if work_session.is_settled:
        raise InventoryMutationError(
            "جلسة العمل تمت تسويتها مالياً مسبقاً ولا تقبل VEHICLE_RECON جديداً."
        )

    if work_session.inventory_reconciled_at is not None:
        raise InventoryMutationError(
            "عهدة مخزون جلسة العمل تمت مطابقتها مسبقاً ولا تقبل VEHICLE_RECON جديداً."
        )

    route_id = (
        await db_session.execute(
            select(DispatchRoute.id).filter(
                DispatchRoute.company_id == company_id,
                DispatchRoute.work_session_id == work_session.id,
                DispatchRoute.driver_id == work_session.driver_id,
                DispatchRoute.vehicle_id == vehicle_id,
            )
            .order_by(DispatchRoute.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if route_id is None:
        raise InventoryMutationError(
            "جلسة العمل المحددة لا ترتبط بهذه السيارة داخل الشركة."
        )

    return work_session


# حجز request_id للعملية داخل Tenant واحد وإرجاع النتيجة السابقة عند retry مطابق.
async def begin_idempotent_operation(
    db_session: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    operation: str,
    request_id: str,
    request_hash: str,
) -> Tuple[OperationIdempotency, Optional[Dict[str, Any]]]:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        actor_id = _strict_int(actor_id, "actor_id", minimum=1)
        canonical_request_id = str(UUID(str(request_id)))
    except (ValueError, TypeError) as exc:
        raise InventoryMutationError("بيانات idempotency غير صالحة.") from exc

    operation = str(operation).strip()
    if not operation or len(operation) > 80:
        raise InventoryMutationError("operation غير صالح لـ idempotency.")

    request_hash = str(request_hash).strip().lower()
    if (
        len(request_hash) != 64
        or any(ch not in "0123456789abcdef" for ch in request_hash)
    ):
        raise InventoryMutationError("request_hash غير صالح لـ idempotency.")

    await db_session.execute(
        select(
            func.pg_advisory_xact_lock(
                company_id,
                func.hashtext(
                    f"op-idempotency:{operation}:{canonical_request_id}"
                ),
            )
        )
    )

    existing = (
        await db_session.execute(
            select(OperationIdempotency)
            .execution_options(populate_existing=True)
            .filter_by(
                company_id=company_id,
                operation=operation,
                request_id=canonical_request_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.created_by != actor_id:
            raise InventoryMutationError(
                "request_id مستخدم مسبقاً بواسطة مستخدم آخر داخل الشركة."
            )

        if existing.request_hash != request_hash:
            raise InventoryMutationError(
                "request_id مستخدم مسبقاً لطلب مختلف؛ استخدم request_id جديداً."
            )

        if existing.completed_at is None or existing.response_json is None:
            raise RuntimeError(
                "Idempotency invariant violated: committed request is incomplete."
            )

        if not isinstance(existing.response_json, dict):
            raise RuntimeError(
                "Idempotency invariant violated: stored response is not an object."
            )

        return existing, dict(existing.response_json)

    record = OperationIdempotency(
        company_id=company_id,
        operation=operation,
        request_id=canonical_request_id,
        request_hash=request_hash,
        created_by=actor_id,
    )
    db_session.add(record)
    await db_session.flush()
    return record, None


# تثبيت نتيجة العملية داخل نفس معاملة البيانات قبل commit.
def complete_idempotent_operation(
    record: OperationIdempotency,
    response_payload: Dict[str, Any],
) -> None:
    if record.completed_at is not None or record.response_json is not None:
        raise RuntimeError("Idempotency record already completed.")
    if not isinstance(response_payload, dict):
        raise TypeError("response_payload يجب أن يكون dict.")

    record.response_json = dict(response_payload)
    record.completed_at = utc_now()


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
    before_on_hand: Decimal,
    before_reserved: Decimal,
) -> None:
    after_on_hand = _quantity_decimal(balance.on_hand_quantity or 0)
    after_reserved = _quantity_decimal(balance.reserved_quantity or 0)

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
async def get_company_local_date(
    db_session: AsyncSession,
    company_id: int,
) -> date:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    timezone_name = (
        await db_session.execute(
            select(Company.timezone).filter_by(id=company_id)
        )
    ).scalar_one_or_none()
    if not timezone_name:
        raise InventoryMutationError("الشركة غير موجودة أو لا تحمل منطقة زمنية صالحة.")

    try:
        local_date = (
            await db_session.execute(
                text("SELECT (CURRENT_TIMESTAMP AT TIME ZONE :timezone_name)::date"),
                {"timezone_name": str(timezone_name).strip()},
            )
        ).scalar_one()
    except Exception as exc:
        raise InventoryMutationError(
            f"المنطقة الزمنية للشركة غير صالحة: {timezone_name}"
        ) from exc

    if type(local_date) is not date:
        raise InventoryMutationError("تعذر حساب تاريخ العمل المحلي للشركة.")
    return local_date


async def get_company_operational_day_utc_bounds(
    db_session: AsyncSession,
    company_id: int,
    operational_date: Optional[date] = None,
) -> Tuple[datetime, datetime]:
    """تحويل يوم الشركة المحلي إلى الفترة UTC نصف المفتوحة [start_utc, end_utc)."""
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    timezone_name = (
        await db_session.execute(
            select(Company.timezone).filter(Company.id == company_id)
        )
    ).scalar_one_or_none()
    if not timezone_name:
        raise InventoryMutationError("الشركة غير موجودة أو لا تحمل منطقة زمنية صالحة.")

    if operational_date is None:
        operational_date = await get_company_local_date(db_session, company_id)
    if type(operational_date) is not date:
        raise InventoryMutationError("operational_date يجب أن يكون date صريحاً.")

    try:
        company_zone = ZoneInfo(str(timezone_name).strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InventoryMutationError(
            f"المنطقة الزمنية للشركة غير صالحة: {timezone_name}"
        ) from exc

    local_start = datetime.combine(operational_date, time.min, tzinfo=company_zone)
    next_local_start = datetime.combine(
        operational_date + timedelta(days=1),
        time.min,
        tzinfo=company_zone,
    )
    start_utc = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = next_local_start.astimezone(timezone.utc).replace(tzinfo=None)
    if not start_utc < end_utc:
        raise InventoryMutationError("حدود يوم العمل UTC غير صالحة.")
    return start_utc, end_utc


def _normalize_inventory_movement_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise InventoryMutationError("كل حركة في الدفعة يجب أن تكون dict.")

    try:
        normalized = {
            "product_variant_id": _strict_int(
                spec.get("product_variant_id"), "product_variant_id", minimum=1
            ),
            "batch_id": _strict_int(spec.get("batch_id"), "batch_id", minimum=1),
            "quantity": _quantity_decimal(spec.get("quantity"), "quantity", allow_zero=False),
            "source_location_id": _optional_positive_int(
                spec.get("source_location_id"), "source_location_id"
            ),
            "destination_location_id": _optional_positive_int(
                spec.get("destination_location_id"), "destination_location_id"
            ),
            "work_session_id": _optional_positive_int(
                spec.get("work_session_id"), "work_session_id"
            ),
            "transfer_header_id": _optional_positive_int(
                spec.get("transfer_header_id"), "transfer_header_id"
            ),
            "stocktake_session_id": _optional_positive_int(
                spec.get("stocktake_session_id"), "stocktake_session_id"
            ),
            "stocktake_count_attempt_id": _optional_positive_int(
                spec.get("stocktake_count_attempt_id"),
                "stocktake_count_attempt_id",
            ),
        }
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    movement_kind = str(spec.get("movement_kind") or "").strip().upper()
    if movement_kind not in {"PHYSICAL", "RESERVATION", "STATUS_CHANGE"}:
        raise InventoryMutationError("نوع حركة المخزون غير صالح.")

    reference_type = str(spec.get("reference_type") or "").strip().upper()
    reference_id = str(spec.get("reference_id") or "").strip()
    idempotency_key = str(spec.get("idempotency_key") or "").strip()
    notes = spec.get("notes")

    if notes is not None and not isinstance(notes, str):
        raise InventoryMutationError("notes يجب أن تكون نصاً أو None.")
    if any("\x00" in value for value in (reference_type, reference_id, idempotency_key)):
        raise InventoryMutationError("مرجع الحركة ومفتاح عدم التكرار لا يقبلان محرف NUL.")
    if notes is not None and "\x00" in notes:
        raise InventoryMutationError("notes لا تقبل محرف NUL.")
    if not reference_type or not reference_id or not idempotency_key:
        raise InventoryMutationError("مرجع الحركة ومفتاح عدم التكرار إلزاميان.")
    if (
        len(reference_type) > 50
        or len(reference_id) > 100
        or len(idempotency_key) > 100
    ):
        raise InventoryMutationError(
            "مرجع الحركة أو مفتاح عدم التكرار أطول من الحد المسموح."
        )
    raw_snapshot = spec.get("financial_unit_price_snapshot")
    if raw_snapshot is None:
        financial_unit_price_snapshot = None
    else:
        try:
            financial_unit_price_snapshot = _money_12_3(
                raw_snapshot,
                "financial_unit_price_snapshot",
            )
        except ValueError as exc:
            raise InventoryMutationError(str(exc)) from exc

    stocktake_session_id = normalized["stocktake_session_id"]
    stocktake_count_attempt_id = normalized["stocktake_count_attempt_id"]
    is_stocktake_reference = reference_type in _STOCKTAKE_ONLY_REFERENCE_TYPES

    if is_stocktake_reference:
        if movement_kind != "PHYSICAL":
            raise InventoryMutationError("حركة ترحيل الجرد يجب أن تكون PHYSICAL حصراً.")
        if stocktake_session_id is None or stocktake_count_attempt_id is None:
            raise InventoryMutationError(
                "حركة الجرد تتطلب stocktake_session_id وstocktake_count_attempt_id."
            )
        if reference_type in {"DRIVER_SHORTAGE", "DRIVER_SURPLUS"} and normalized["work_session_id"] is None:
            raise InventoryMutationError("حركة عهدة المندوب تتطلب work_session_id.")
        if reference_type == "DRIVER_SHORTAGE":
            if financial_unit_price_snapshot is None:
                raise InventoryMutationError(
                    "DRIVER_SHORTAGE يتطلب سعراً مالياً مثبتاً لحظة الترحيل."
                )
            total_value = financial_unit_price_snapshot * normalized["quantity"]
            if not total_value.is_finite() or total_value > _MONEY_12_3_MAX:
                raise InventoryMutationError("قيمة DRIVER_SHORTAGE تتجاوز السعة المالية.")
        elif financial_unit_price_snapshot is not None:
            raise InventoryMutationError(
                "السعر المالي المثبت مسموح فقط لـ DRIVER_SHORTAGE."
            )
    else:
        if stocktake_session_id is not None or stocktake_count_attempt_id is not None:
            raise InventoryMutationError(
                "هوية جلسة الجرد غير مسموحة لحركة غير جردية."
            )
        if financial_unit_price_snapshot is not None:
            raise InventoryMutationError(
                "السعر المالي المثبت غير مسموح لحركة غير DRIVER_SHORTAGE."
            )

    source_stock_status = spec.get("source_stock_status")
    destination_stock_status = spec.get("destination_stock_status")
    reservation_action = spec.get("reservation_action")
    if source_stock_status is not None:
        source_stock_status = str(source_stock_status).strip().upper()
    if destination_stock_status is not None:
        destination_stock_status = str(destination_stock_status).strip().upper()
    if reservation_action is not None:
        reservation_action = str(reservation_action).strip().upper()

    allowed_statuses = _INVENTORY_STOCK_STATUSES
    if source_stock_status is not None and source_stock_status not in allowed_statuses:
        raise InventoryMutationError("حالة مخزون المصدر غير صالحة.")
    if destination_stock_status is not None and destination_stock_status not in allowed_statuses:
        raise InventoryMutationError("حالة مخزون الوجهة غير صالحة.")

    source_location_id = normalized["source_location_id"]
    destination_location_id = normalized["destination_location_id"]
    if (source_location_id is None) != (source_stock_status is None):
        raise InventoryMutationError(
            "المصدر وحالته يجب أن يوجدا معاً أو يكونا فارغين معاً."
        )
    if (destination_location_id is None) != (destination_stock_status is None):
        raise InventoryMutationError(
            "الوجهة وحالتها يجب أن يوجدا معاً أو يكونا فارغين معاً."
        )

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
        raise InventoryMutationError(
            "reservation_action مسموح فقط لحركة RESERVATION."
        )

    if movement_kind == "STATUS_CHANGE":
        if (
            source_location_id is None
            or destination_location_id != source_location_id
            or source_stock_status == destination_stock_status
        ):
            raise InventoryMutationError("شكل تغيير حالة المخزون غير صالح.")
        allowed_destinations = _PORTION_STATUS_TRANSITIONS.get(
            source_stock_status,
            frozenset(),
        )
        if destination_stock_status not in allowed_destinations:
            raise InventoryRuleError(
                "STOCK_STATUS_TRANSITION_BLOCKED",
                "انتقال حالة الرصيد المطلوب غير مسموح حسب مصفوفة Stage 4.",
                context={
                    "from": source_stock_status,
                    "to": destination_stock_status,
                },
            )

    if movement_kind == "PHYSICAL":
        if source_location_id is None and destination_location_id is None:
            raise InventoryMutationError("الحركة الفيزيائية تحتاج مصدراً أو وجهة.")
        if (
            source_location_id is not None
            and destination_location_id is not None
            and source_location_id == destination_location_id
        ):
            raise InventoryMutationError(
                "الحركة الفيزيائية بين نفس الموقع غير صالحة."
            )
        if (
            source_location_id is not None
            and destination_location_id is not None
            and source_stock_status != destination_stock_status
        ):
            raise InventoryMutationError(
                "الحركة PHYSICAL لا يجوز أن تغيّر حالة المخزون؛ استخدم STATUS_CHANGE."
            )

    normalized.update({
        "movement_kind": movement_kind,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "idempotency_key": idempotency_key,
        "source_stock_status": source_stock_status,
        "destination_stock_status": destination_stock_status,
        "reservation_action": reservation_action,
        "financial_unit_price_snapshot": financial_unit_price_snapshot,
        "notes": notes,
    })
    return normalized

def _movement_matches_existing(
    movement: InventoryMovement,
    spec: Dict[str, Any],
    performed_by: int,
) -> bool:
    expected = {
        "performed_by": performed_by,
        "source_location_id": spec["source_location_id"],
        "destination_location_id": spec["destination_location_id"],
        "source_stock_status": spec["source_stock_status"],
        "destination_stock_status": spec["destination_stock_status"],
        "product_variant_id": spec["product_variant_id"],
        "batch_id": spec["batch_id"],
        "movement_kind": spec["movement_kind"],
        "reservation_action": spec["reservation_action"],
        "quantity": spec["quantity"],
        "work_session_id": spec["work_session_id"],
        "transfer_header_id": spec["transfer_header_id"],
        "stocktake_session_id": spec["stocktake_session_id"],
        "stocktake_count_attempt_id": spec["stocktake_count_attempt_id"],
        "financial_unit_price_snapshot": spec["financial_unit_price_snapshot"],
        "reference_type": spec["reference_type"],
        "reference_id": spec["reference_id"],
        "notes": spec["notes"],
    }
    return all(getattr(movement, field) == value for field, value in expected.items())

async def _acquire_idempotency_guards_batch(
    db_session: AsyncSession,
    company_id: int,
    idempotency_keys: List[str],
) -> None:
    if not idempotency_keys:
        return

    # نفس مفتاح المحرك الفردي القديم حرفياً، حتى تكون الحماية متوافقة
    # أثناء rolling deployment ولا يوجد مساران لقفل idempotency.
    await db_session.execute(
        text(
            """
            SELECT pg_advisory_xact_lock(
                hashtext('inventory:' || CAST(:company_id AS text) || ':' || idempotency_key)
            )
            FROM unnest(CAST(:idempotency_keys AS text[])) AS t(idempotency_key)
            ORDER BY idempotency_key
            """
        ),
        {
            "company_id": str(company_id),
            "idempotency_keys": sorted(idempotency_keys),
        },
    )

def _inventory_lock_conflicts_with_spec(
    lock: InventoryLock,
    spec: Dict[str, Any],
) -> bool:
    # جلسة الجرد المالكة للقفل وحدها تستطيع ترحيل فروقاتها عبر المحرك.
    own_stocktake_id = spec.get("stocktake_session_id")
    if own_stocktake_id is not None and lock.stocktake_session_id == own_stocktake_id:
        return False

    endpoints = {
        loc_id
        for loc_id in (spec["source_location_id"], spec["destination_location_id"])
        if loc_id is not None
    }
    if lock.location_id not in endpoints:
        return False
    if lock.product_variant_id is None:
        return True
    if lock.product_variant_id != spec["product_variant_id"]:
        return False
    return lock.batch_id is None or lock.batch_id == spec["batch_id"]

async def acquire_inventory_location_guards(
    db_session: AsyncSession,
    company_id: int,
    location_ids: List[int],
) -> None:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        normalized_ids = sorted({
            _strict_int(location_id, "location_id", minimum=1)
            for location_id in location_ids
        })
    except (TypeError, ValueError) as exc:
        raise InventoryMutationError(str(exc)) from exc

    if not normalized_ids:
        return
    if len(normalized_ids) > 10_000:
        raise InventoryMutationError("عدد حراس المواقع يتجاوز الحد الآمن البالغ 10000 موقع.")

    await db_session.execute(
        text(
            """
            SELECT pg_advisory_xact_lock_shared(CAST(:company_id AS integer), location_id)
            FROM unnest(CAST(:location_ids AS integer[])) AS t(location_id)
            ORDER BY location_id
            """
        ),
        {"company_id": company_id, "location_ids": normalized_ids},
    )


_SYSTEM_TRANSIT_PROVISION_GUARD = -2147483648


async def ensure_system_transit_location(
    db_session: AsyncSession,
    company_id: int,
) -> InventoryLocation:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    await db_session.execute(
        select(func.pg_advisory_xact_lock(company_id, _SYSTEM_TRANSIT_PROVISION_GUARD))
    )
    location = (
        await db_session.execute(
            select(InventoryLocation)
            .filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.system_role == "TRANSIT",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if location is not None:
        if not (
            location.is_system_managed
            and location.location_type == "IN_TRANSIT"
            and location.is_active
            and location.branch_id is None
            and location.vehicle_id is None
        ):
            raise InventoryMutationError(
                "موقع العبور النظامي للشركة موجود بحالة غير صالحة ويجب إصلاحه إدارياً."
            )
        return location

    reserved_code_owner = (
        await db_session.execute(
            select(InventoryLocation.id).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.code == "TRANSIT-SYS",
            ).limit(1)
        )
    ).scalar_one_or_none()
    if reserved_code_owner is not None:
        raise InventoryMutationError(
            "الكود TRANSIT-SYS مستخدم في موقع لا يحمل هوية العبور النظامية."
        )

    location = InventoryLocation(
        company_id=company_id,
        branch_id=None,
        name="بضاعة في الطريق",
        code="TRANSIT-SYS",
        location_type="IN_TRANSIT",
        vehicle_id=None,
        system_role="TRANSIT",
        is_system_managed=True,
        version=1,
        is_active=True,
    )
    db_session.add(location)
    await db_session.flush()
    return location

async def apply_inventory_movements_batch(
    db_session: AsyncSession,
    *,
    company_id: int,
    performed_by: int,
    movements: List[Dict[str, Any]],
) -> List[InventoryMovement]:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        performed_by = _strict_int(performed_by, "performed_by", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    if not isinstance(movements, list) or not movements:
        raise InventoryMutationError(
            "دفعة الحركات يجب أن تحتوي حركة واحدة على الأقل."
        )
    if len(movements) > 10_000:
        raise InventoryMutationError(
            "دفعة الحركات تتجاوز الحد الآمن البالغ 10000 حركة."
        )

    specs = [_normalize_inventory_movement_spec(spec) for spec in movements]
    idempotency_keys = [spec["idempotency_key"] for spec in specs]
    if len(idempotency_keys) != len(set(idempotency_keys)):
        raise InventoryMutationError(
            "مفتاح idempotency مكرر داخل دفعة الحركات نفسها."
        )

    await _acquire_idempotency_guards_batch(
        db_session,
        company_id,
        idempotency_keys,
    )

    existing_rows = (
        await db_session.execute(
            select(InventoryMovement)
            .execution_options(populate_existing=True)
            .filter(
                InventoryMovement.company_id == company_id,
                InventoryMovement.idempotency_key.in_(idempotency_keys),
            )
        )
    ).scalars().all()
    existing_map = {row.idempotency_key: row for row in existing_rows}
    if len(existing_map) != len(existing_rows):
        raise InventoryMutationError(
            "تم اكتشاف مفاتيح idempotency مكررة في سجل الحركات."
        )

    results_by_key: Dict[str, InventoryMovement] = {}
    new_specs: List[Dict[str, Any]] = []

    for spec in specs:
        existing = existing_map.get(spec["idempotency_key"])
        if existing is None:
            new_specs.append(spec)
            continue
        if not _movement_matches_existing(existing, spec, performed_by):
            raise InventoryMutationError(
                "مفتاح idempotency مستخدم مسبقاً لحركة مختلفة؛ تم رفض إعادة الاستخدام."
            )
        results_by_key[spec["idempotency_key"]] = existing

    if not new_specs:
        return [
            results_by_key[spec["idempotency_key"]]
            for spec in specs
        ]

    location_ids = sorted({
        int(location_id)
        for spec in new_specs
        for location_id in (
            spec["source_location_id"],
            spec["destination_location_id"],
        )
        if location_id is not None
    })
    product_variant_ids = sorted({
        spec["product_variant_id"]
        for spec in new_specs
    })

    # Lifecycle mutations use the exclusive form of the same guard. Taking the
    # shared guard here closes the archive-vs-new-movement race without blocking
    # independent products.
    await acquire_product_lifecycle_guards(
        db_session,
        company_id,
        product_variant_ids,
        exclusive=False,
    )

    variant_rows = (
        await db_session.execute(
            select(
                ProductVariant.id,
                ProductVariant.quantity_scale,
                ProductVariant.quantity_step,
                ProductVariant.lifecycle_status,
                ProductVariant.operational_hold,
                ProductVariant.expiry_control_mode,
            ).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(product_variant_ids),
            )
        )
    ).all()
    variant_rules = {
        int(row.id): (
            int(row.quantity_scale),
            row.quantity_step,
            row.lifecycle_status,
            row.operational_hold,
            row.expiry_control_mode,
        )
        for row in variant_rows
    }
    if set(variant_rules) != set(product_variant_ids):
        raise InventoryMutationError("أحد أصناف الحركة غير موجود داخل الشركة.")
    try:
        for spec in new_specs:
            scale, step, lifecycle_status, _operational_hold, _expiry_mode = variant_rules[spec["product_variant_id"]]
            if lifecycle_status in {"DRAFT", "ARCHIVED"}:
                raise InventoryMutationError(
                    f"الصنف ({spec['product_variant_id']}) بحالة {lifecycle_status} ولا يقبل حركة مخزون جديدة."
                )
            spec["quantity"] = validate_variant_quantity(
                spec["quantity"],
                quantity_scale=scale,
                quantity_step=step,
                field_name="quantity",
            )
    except QuantityError as exc:
        raise InventoryMutationError(str(exc)) from exc

    # ترتيب القفل ثابت: idempotency -> product lifecycle -> locations -> rows -> balances.
    await acquire_inventory_location_guards(
        db_session,
        company_id,
        location_ids,
    )

    if location_ids:
        existing_location_ids = set(
            (
                await db_session.execute(
                    select(InventoryLocation.id).filter(
                        InventoryLocation.company_id == company_id,
                        InventoryLocation.id.in_(location_ids),
                        InventoryLocation.is_active.is_(True),
                    ).order_by(
                        InventoryLocation.id.asc()
                    ).with_for_update(read=True)
                )
            ).scalars().all()
        )
        if existing_location_ids != set(location_ids):
            raise InventoryMutationError(
                "أحد مواقع المخزون غير موجود أو غير فعال."
            )

    batch_keys = sorted({
        (spec["product_variant_id"], spec["batch_id"])
        for spec in new_specs
    })
    locked_batches = (
        await db_session.execute(
            select(ProductBatch)
            .execution_options(populate_existing=True)
            .filter(
                ProductBatch.company_id == company_id,
                tuple_(
                    ProductBatch.product_variant_id,
                    ProductBatch.id,
                ).in_(batch_keys),
            )
            .order_by(
                ProductBatch.product_variant_id.asc(),
                ProductBatch.id.asc(),
            )
            .with_for_update()
        )
    ).scalars().all()
    batch_map = {
        (int(batch.product_variant_id), int(batch.id)): batch
        for batch in locked_batches
    }
    if set(batch_map) != set(batch_keys):
        raise InventoryMutationError(
            "إحدى الدفعات لا تنتمي للصنف أو الشركة المحددة."
        )

    # تحرير Portion إلى AVAILABLE قرار correctness لحظي، وليس مجرد تغيير Label.
    # يتم بعد location guards وتحت Row Lock على ProductBatch كي لا يسبق Recall/Expiry race.
    release_specs = [
        spec
        for spec in new_specs
        if spec["movement_kind"] == "STATUS_CHANGE"
        and spec["destination_stock_status"] == "AVAILABLE"
    ]
    if release_specs:
        as_of_date = await get_company_local_date(db_session, company_id)
        policy_keys = sorted({
            (int(spec["destination_location_id"]), int(spec["product_variant_id"]))
            for spec in release_specs
        })
        policy_rows = (
            await db_session.execute(
                select(
                    InventoryStockPolicy.location_id,
                    InventoryStockPolicy.product_variant_id,
                    InventoryStockPolicy.minimum_remaining_shelf_life_days,
                ).filter(
                    InventoryStockPolicy.company_id == company_id,
                    InventoryStockPolicy.is_active.is_(True),
                    tuple_(
                        InventoryStockPolicy.location_id,
                        InventoryStockPolicy.product_variant_id,
                    ).in_(policy_keys),
                )
            )
        ).all()
        min_shelf_life = {
            (int(row.location_id), int(row.product_variant_id)):
                int(row.minimum_remaining_shelf_life_days or 0)
            for row in policy_rows
        }

        for spec in release_specs:
            variant_id = int(spec["product_variant_id"])
            location_id = int(spec["destination_location_id"])
            batch = batch_map[(variant_id, int(spec["batch_id"]))]
            (
                _scale,
                _step,
                _lifecycle_status,
                operational_hold,
                expiry_control_mode,
            ) = variant_rules[variant_id]

            normalized_hold = str(operational_hold or "").upper()
            if normalized_hold != "NONE":
                hold_code = (
                    "PRODUCT_RECALLED"
                    if normalized_hold == "RECALL"
                    else "PRODUCT_SALES_HOLD"
                )
                raise InventoryRuleError(
                    hold_code,
                    "لا يمكن تحرير الرصيد إلى AVAILABLE أثناء وجود Hold تشغيلي على الصنف.",
                    context={
                        "product_variant_id": variant_id,
                        "batch_id": int(batch.id),
                        "operational_hold": normalized_hold,
                    },
                )
            if not bool(batch.is_active):
                raise InventoryRuleError(
                    "BATCH_NOT_ELIGIBLE",
                    "الدفعة متوقفة إدارياً ولا يمكن تحرير رصيدها إلى AVAILABLE.",
                    context={"batch_id": int(batch.id)},
                )
            if str(batch.disposition or "").upper() != "RELEASED":
                raise InventoryRuleError(
                    "BATCH_NOT_RELEASED",
                    "الدفعة ليست RELEASED ولا يمكن تحرير رصيدها إلى AVAILABLE.",
                    context={
                        "batch_id": int(batch.id),
                        "disposition": str(batch.disposition),
                    },
                )
            if (
                batch.production_date is not None
                and batch.production_date > as_of_date
            ):
                raise InventoryRuleError(
                    "BATCH_NOT_ELIGIBLE",
                    "تاريخ إنتاج الدفعة يقع في المستقبل.",
                    context={"batch_id": int(batch.id)},
                )
            if batch.expiry_date is not None and batch.expiry_date < as_of_date:
                raise InventoryRuleError(
                    "BATCH_EXPIRED",
                    "الدفعة منتهية الصلاحية ولا يمكن تحريرها إلى AVAILABLE.",
                    context={
                        "batch_id": int(batch.id),
                        "expiry_date": batch.expiry_date.isoformat(),
                    },
                )

            minimum_days = min_shelf_life.get((location_id, variant_id), 0)
            if not _batch_metadata_is_sellable(
                as_of_date=as_of_date,
                expiry_control_mode=str(expiry_control_mode),
                production_date=batch.production_date,
                expiry_date=batch.expiry_date,
                minimum_remaining_shelf_life_days=minimum_days,
            ):
                raise InventoryRuleError(
                    "SHELF_LIFE_POLICY_BLOCKED",
                    "الدفعة لا تحقق سياسة الصلاحية/العمر المتبقي للموقع.",
                    context={
                        "location_id": location_id,
                        "product_variant_id": variant_id,
                        "batch_id": int(batch.id),
                        "minimum_remaining_shelf_life_days": minimum_days,
                    },
                )

    async def _relevant_active_locks():
        if not location_ids:
            return []
        return (
            await db_session.execute(
                select(InventoryLock).filter(
                    InventoryLock.company_id == company_id,
                    InventoryLock.location_id.in_(location_ids),
                    InventoryLock.released_at.is_(None),
                    or_(
                        InventoryLock.product_variant_id.is_(None),
                        InventoryLock.product_variant_id.in_(product_variant_ids),
                    ),
                ).order_by(
                    InventoryLock.location_id.asc(),
                    InventoryLock.product_variant_id.asc().nulls_first(),
                    InventoryLock.batch_id.asc().nulls_first(),
                    InventoryLock.id.asc(),
                )
            )
        ).scalars().all()

    active_locks = await _relevant_active_locks()
    for spec in new_specs:
        if any(
            _inventory_lock_conflicts_with_spec(lock, spec)
            for lock in active_locks
        ):
            raise InventoryMutationError(
                "الصنف/الدفعة مقفل جراحياً بسبب جرد نشط."
            )

    source_keys = {
        (
            spec["source_location_id"],
            spec["product_variant_id"],
            spec["batch_id"],
            spec["source_stock_status"],
        )
        for spec in new_specs
        if spec["source_location_id"] is not None
    }
    destination_keys = {
        (
            spec["destination_location_id"],
            spec["product_variant_id"],
            spec["batch_id"],
            spec["destination_stock_status"],
        )
        for spec in new_specs
        if spec["destination_location_id"] is not None
    }

    # UPSERT الوجهات بشكل chunked، وبعدد استعلامات يعتمد على عدد المواقع/chunks
    # لا على عدد الحركات.
    destination_rows_by_location: Dict[int, List[Tuple[int, int, str]]] = {}
    for (
        location_id,
        product_variant_id,
        batch_id,
        stock_status,
    ) in sorted(destination_keys):
        destination_rows_by_location.setdefault(
            int(location_id),
            [],
        ).append((
            int(product_variant_id),
            int(batch_id),
            str(stock_status),
        ))

    for location_id in sorted(destination_rows_by_location):
        await _bulk_ensure_inventory_balances(
            db_session,
            company_id=company_id,
            location_id=location_id,
            rows=destination_rows_by_location[location_id],
        )

    all_balance_keys = sorted(source_keys | destination_keys)
    balances = []
    if all_balance_keys:
        balances = (
            await db_session.execute(
                select(InventoryBalance)
                .execution_options(populate_existing=True)
                .filter(
                    InventoryBalance.company_id == company_id,
                    tuple_(
                        InventoryBalance.location_id,
                        InventoryBalance.product_variant_id,
                        InventoryBalance.batch_id,
                        InventoryBalance.stock_status,
                    ).in_(all_balance_keys),
                ).order_by(
                    InventoryBalance.location_id.asc(),
                    InventoryBalance.product_variant_id.asc(),
                    InventoryBalance.batch_id.asc(),
                    InventoryBalance.stock_status.asc(),
                ).with_for_update()
            )
        ).scalars().all()

    balance_map = {
        (
            row.location_id,
            row.product_variant_id,
            row.batch_id,
            row.stock_status,
        ): row
        for row in balances
    }
    if any(key not in balance_map for key in source_keys):
        raise InventoryMutationError(
            "رصيد مصدر مطلوب للحركة غير موجود."
        )
    if any(key not in balance_map for key in destination_keys):
        raise InventoryMutationError(
            "تعذر إنشاء أحد أرصدة الوجهة."
        )

    # دفاع ثانٍ بعد امتلاك Row Locks. حارس الموقع يمنع منشئ الجرد الجديد
    # الصحيح من السباق، وهذا الفحص يحمي أيضاً من أي منشئ Legacy لم يُهجّر بعد.
    refreshed_locks = await _relevant_active_locks()
    for spec in new_specs:
        if any(
            _inventory_lock_conflicts_with_spec(lock, spec)
            for lock in refreshed_locks
        ):
            raise InventoryMutationError(
                "بدأ جرد متعارض أثناء تنفيذ دفعة المخزون؛ أعد المحاولة."
            )

    movement_records: List[InventoryMovement] = []
    impact_snapshots = []

    # نحاكي الحركات بالترتيب داخل الذاكرة بعد امتلاك جميع Row Locks؛
    # لذلك حركتان على نفس الرصيد ترى الثانية نتيجة الأولى داخل نفس Transaction.
    for spec in new_specs:
        source_key = None
        if spec["source_location_id"] is not None:
            source_key = (
                spec["source_location_id"],
                spec["product_variant_id"],
                spec["batch_id"],
                spec["source_stock_status"],
            )

        destination_key = None
        if spec["destination_location_id"] is not None:
            destination_key = (
                spec["destination_location_id"],
                spec["product_variant_id"],
                spec["batch_id"],
                spec["destination_stock_status"],
            )

        touched = []

        if spec["movement_kind"] == "RESERVATION":
            balance = balance_map[source_key]
            before_on_hand = _quantity_decimal(balance.on_hand_quantity or 0)
            before_reserved = _quantity_decimal(balance.reserved_quantity or 0)

            if spec["reservation_action"] == "RESERVE":
                if before_on_hand - before_reserved < spec["quantity"]:
                    raise InventoryMutationError(
                        "الرصيد المتاح لا يغطي كمية الحجز."
                    )
                balance.reserved_quantity = (
                    before_reserved + spec["quantity"]
                )
            else:
                if before_reserved < spec["quantity"]:
                    raise InventoryMutationError(
                        "الرصيد المحجوز لا يغطي كمية التحرير."
                    )
                balance.reserved_quantity = (
                    before_reserved - spec["quantity"]
                )

            touched.append((
                balance,
                before_on_hand,
                before_reserved,
                _quantity_decimal(balance.on_hand_quantity or 0),
                _quantity_decimal(balance.reserved_quantity or 0),
            ))

        else:
            if source_key is not None:
                source_balance = balance_map[source_key]
                before_on_hand = _quantity_decimal(
                    source_balance.on_hand_quantity or 0
                )
                before_reserved = _quantity_decimal(
                    source_balance.reserved_quantity or 0
                )
                if (
                    before_on_hand - before_reserved
                    < spec["quantity"]
                ):
                    raise InventoryMutationError(
                        "الرصيد الحر في المصدر لا يغطي الحركة."
                    )

                after_on_hand = (
                    before_on_hand - spec["quantity"]
                )
                source_balance.on_hand_quantity = after_on_hand
                touched.append((
                    source_balance,
                    before_on_hand,
                    before_reserved,
                    after_on_hand,
                    before_reserved,
                ))

            if destination_key is not None:
                destination_balance = balance_map[destination_key]
                before_on_hand = _quantity_decimal(
                    destination_balance.on_hand_quantity or 0
                )
                before_reserved = _quantity_decimal(
                    destination_balance.reserved_quantity or 0
                )
                after_on_hand = (
                    before_on_hand + spec["quantity"]
                )
                if after_on_hand > QUANTITY_MAX:
                    raise InventoryMutationError(
                        "الرصيد الناتج في الوجهة يتجاوز سعة NUMERIC(20,6)."
                    )

                destination_balance.on_hand_quantity = after_on_hand
                touched.append((
                    destination_balance,
                    before_on_hand,
                    before_reserved,
                    after_on_hand,
                    before_reserved,
                ))

        movement = InventoryMovement(
            company_id=company_id,
            performed_by=performed_by,
            source_location_id=spec["source_location_id"],
            destination_location_id=spec["destination_location_id"],
            source_stock_status=spec["source_stock_status"],
            destination_stock_status=spec["destination_stock_status"],
            product_variant_id=spec["product_variant_id"],
            batch_id=spec["batch_id"],
            movement_kind=spec["movement_kind"],
            reservation_action=spec["reservation_action"],
            quantity=spec["quantity"],
            work_session_id=spec["work_session_id"],
            transfer_header_id=spec["transfer_header_id"],
            stocktake_session_id=spec["stocktake_session_id"],
            stocktake_count_attempt_id=spec["stocktake_count_attempt_id"],
            financial_unit_price_snapshot=spec["financial_unit_price_snapshot"],
            reference_type=spec["reference_type"],
            reference_id=spec["reference_id"],
            idempotency_key=spec["idempotency_key"],
            notes=spec["notes"],
        )
        db_session.add(movement)
        movement_records.append(movement)
        impact_snapshots.append((movement, touched))

    # Flush واحد للحركات والأرصدة بدلاً من Flush لكل حركة.
    await db_session.flush()

    for movement, touched in impact_snapshots:
        for (
            balance,
            before_on_hand,
            before_reserved,
            after_on_hand,
            after_reserved,
        ) in touched:
            db_session.add(InventoryMovementImpact(
                company_id=company_id,
                movement_id=movement.id,
                inventory_balance_id=balance.id,
                on_hand_before=before_on_hand,
                on_hand_after=after_on_hand,
                reserved_before=before_reserved,
                reserved_after=after_reserved,
            ))
        results_by_key[movement.idempotency_key] = movement

    return [
        results_by_key[spec["idempotency_key"]]
        for spec in specs
    ]

async def apply_inventory_movement(
    db_session: AsyncSession,
    *,
    company_id: int,
    performed_by: int,
    product_variant_id: int,
    batch_id: int,
    quantity: Decimal,
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
    result = await apply_inventory_movements_batch(
        db_session,
        company_id=company_id,
        performed_by=performed_by,
        movements=[{
            "product_variant_id": product_variant_id,
            "batch_id": batch_id,
            "quantity": quantity,
            "movement_kind": movement_kind,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "idempotency_key": idempotency_key,
            "source_location_id": source_location_id,
            "destination_location_id": destination_location_id,
            "source_stock_status": source_stock_status,
            "destination_stock_status": destination_stock_status,
            "reservation_action": reservation_action,
            "work_session_id": work_session_id,
            "transfer_header_id": transfer_header_id,
            "notes": notes,
        }],
    )
    return result[0]


# فتح VEHICLE_RECON موجّه فقط للأصناف التي فشل عدّها التجميعي.
# يبقى InventoryLock على السيارة كاملة لأن الجلسة منتهية، لكن العد التفصيلي لا يرهق المشرف بأصناف مطابقة.
async def open_vehicle_reconciliation_stocktake(
    db_session: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
    vehicle_location_id: int,
    started_by: int,
    product_variant_ids: List[int],
    notes: Optional[str] = None,
) -> Tuple[StocktakeSession, bool]:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        work_session_id = _strict_int(work_session_id, "work_session_id", minimum=1)
        vehicle_location_id = _strict_int(vehicle_location_id, "vehicle_location_id", minimum=1)
        started_by = _strict_int(started_by, "started_by", minimum=1)
        normalized_variant_ids = sorted({
            _strict_int(value, "product_variant_id", minimum=1)
            for value in product_variant_ids
        })
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    if not normalized_variant_ids:
        raise InventoryMutationError("VEHICLE_RECON الموجّه يتطلب صنفاً واحداً على الأقل.")
    if len(normalized_variant_ids) > 5000:
        raise InventoryMutationError("عدد أصناف VEHICLE_RECON يتجاوز الحد الآمن.")

    if notes is not None:
        if not isinstance(notes, str):
            raise InventoryMutationError("notes يجب أن تكون نصاً أو None.")
        notes = notes.strip() or None
        if notes is not None and ("\x00" in notes or len(notes) > 4000):
            raise InventoryMutationError("notes غير صالحة أو تتجاوز 4000 حرف.")

    actor = (
        await db_session.execute(
            select(Driver.id, Driver.is_admin).filter_by(
                company_id=company_id,
                id=started_by,
                is_active=True,
            ).with_for_update(read=True)
        )
    ).one_or_none()
    if actor is None:
        raise InventoryMutationError("منشئ التسوية غير موجود/غير فعال أو خارج الشركة.")

    location = (
        await db_session.execute(
            select(InventoryLocation).filter_by(
                company_id=company_id,
                id=vehicle_location_id,
                location_type="VEHICLE",
                is_active=True,
            ).with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if location is None or location.vehicle_id is None:
        raise InventoryMutationError("موقع السيارة غير موجود أو غير فعال أو لا يحمل vehicle_id صالحاً.")

    work_session = await validate_vehicle_recon_work_session(
        db_session,
        company_id=company_id,
        work_session_id=work_session_id,
        vehicle_id=int(location.vehicle_id),
    )
    if started_by != work_session.driver_id and not bool(actor.is_admin):
        raise InventoryMutationError("لا يجوز لمندوب آخر فتح تسوية عهدة هذه الجلسة.")

    valid_variant_ids = set((
        await db_session.execute(
            select(ProductVariant.id).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(normalized_variant_ids),
            )
        )
    ).scalars().all())
    if valid_variant_ids != set(normalized_variant_ids):
        raise InventoryMutationError("أحد أصناف فرق العهدة غير موجود أو لا يتبع الشركة.")

    await acquire_inventory_location_guard(
        db_session,
        company_id,
        vehicle_location_id,
        exclusive=True,
    )

    existing = (
        await db_session.execute(
            select(StocktakeSession)
            .filter(
                StocktakeSession.company_id == company_id,
                StocktakeSession.stocktake_type == "VEHICLE_RECON",
                StocktakeSession.related_work_session_id == work_session_id,
                StocktakeSession.status != "CANCELLED",
            )
            .order_by(StocktakeSession.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    conflicting_session_id = (
        await db_session.execute(
            select(StocktakeSession.id)
            .filter(
                StocktakeSession.company_id == company_id,
                StocktakeSession.location_id == vehicle_location_id,
                StocktakeSession.status.in_([
                    "DRAFT", "COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED", "APPROVED"
                ]),
            )
            .order_by(StocktakeSession.id.asc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if conflicting_session_id is not None:
        raise InventoryMutationError("يوجد جرد نشط على السيارة؛ لا يمكن فتح تسوية موازية.")

    conflicting_lock_id = (
        await db_session.execute(
            select(InventoryLock.id)
            .filter(
                InventoryLock.company_id == company_id,
                InventoryLock.location_id == vehicle_location_id,
                InventoryLock.released_at.is_(None),
            )
            .order_by(InventoryLock.id.asc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if conflicting_lock_id is not None:
        raise InventoryMutationError("يوجد قفل جرد فعال على السيارة؛ لا يمكن فتح تسوية جديدة.")

    reference_number = f"VREC-{uuid4().hex[:12].upper()}"
    session = StocktakeSession(
        company_id=company_id,
        location_id=vehicle_location_id,
        reference_number=reference_number,
        stocktake_type="VEHICLE_RECON",
        status="DRAFT",
        related_work_session_id=work_session_id,
        started_by=started_by,
        notes=notes,
    )
    db_session.add(session)
    await db_session.flush()

    db_session.add(InventoryLock(
        company_id=company_id,
        stocktake_session_id=session.id,
        location_id=vehicle_location_id,
        product_variant_id=None,
        batch_id=None,
        created_by=started_by,
    ))
    await db_session.flush()

    balances = (
        await db_session.execute(
            select(InventoryBalance)
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == vehicle_location_id,
                InventoryBalance.product_variant_id.in_(normalized_variant_ids),
                InventoryBalance.on_hand_quantity > 0,
            )
            .order_by(
                InventoryBalance.product_variant_id.asc(),
                InventoryBalance.batch_id.asc(),
                InventoryBalance.stock_status.asc(),
                InventoryBalance.id.asc(),
            )
            .limit(_MAX_STOCKTAKE_POST_LINES + 1)
            .with_for_update()
        )
    ).scalars().all()
    if len(balances) > _MAX_STOCKTAKE_POST_LINES:
        raise InventoryMutationError("VEHICLE_RECON يتجاوز الحد الآمن لأسطر الجرد.")

    for balance in balances:
        db_session.add(StocktakeLine(
            company_id=company_id,
            stocktake_session_id=session.id,
            product_variant_id=balance.product_variant_id,
            batch_id=balance.batch_id,
            stock_status=balance.stock_status,
            line_origin="SNAPSHOT",
            expected_quantity=_quantity_decimal(balance.on_hand_quantity),
        ))

    cutoff = utc_now()
    session.snapshot_cutoff_at = cutoff
    session.status = "COUNTING"
    session.updated_at = cutoff
    await db_session.flush()
    return session, True


# تثبيت عهدة نهاية الجلسة من الرصيد الحي بعد المطابقة/ترحيل VEHICLE_RECON.
# هذه الدالة لا تخمّن Batch ولا تغيّر InventoryBalance ولا تنفذ التسوية المالية؛
# فقط تجمّد Ending Snapshot وتختم inventory_reconciled_* على WorkSession.
async def finalize_vehicle_inventory_reconciliation(
    db_session: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
    vehicle_location_id: int,
    settled_by: int,
) -> WorkSession:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        work_session_id = _strict_int(work_session_id, "work_session_id", minimum=1)
        vehicle_location_id = _strict_int(vehicle_location_id, "vehicle_location_id", minimum=1)
        settled_by = _strict_int(settled_by, "settled_by", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    actor = (
        await db_session.execute(
            select(Driver.id, Driver.is_admin).filter_by(
                company_id=company_id,
                id=settled_by,
                is_active=True,
            ).with_for_update(read=True)
        )
    ).one_or_none()
    if actor is None:
        raise InventoryMutationError("منفذ التسوية غير موجود/غير فعال أو خارج الشركة.")

    work_session = (
        await db_session.execute(
            select(WorkSession)
            .execution_options(populate_existing=True)
            .filter_by(company_id=company_id, id=work_session_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if work_session is None:
        raise InventoryMutationError("جلسة العمل غير موجودة أو لا تتبع الشركة.")
    if work_session.end_time is None:
        raise InventoryMutationError("لا يمكن تسوية عهدة جلسة عمل لم تنتهِ بعد.")
    if settled_by != work_session.driver_id and not bool(actor.is_admin):
        raise InventoryMutationError("تثبيت عهدة الجلسة مسموح لصاحب الجلسة أو لمشرف فعال من نفس الشركة فقط.")

    # ترتيب الأقفال الرسمي لـ VEHICLE_RECON: WorkSession -> inventory-location guard.
    await acquire_inventory_location_guard(
        db_session,
        company_id,
        vehicle_location_id,
        exclusive=True,
    )

    location = (
        await db_session.execute(
            select(InventoryLocation).filter_by(
                company_id=company_id,
                id=vehicle_location_id,
                location_type="VEHICLE",
                is_active=True,
            ).with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if location is None or location.vehicle_id is None:
        raise InventoryMutationError("موقع السيارة غير موجود أو غير فعال أو لا يحمل vehicle_id صالحاً.")

    route_id = (
        await db_session.execute(
            select(DispatchRoute.id).filter(
                DispatchRoute.company_id == company_id,
                DispatchRoute.work_session_id == work_session.id,
                DispatchRoute.driver_id == work_session.driver_id,
                DispatchRoute.vehicle_id == location.vehicle_id,
            ).order_by(DispatchRoute.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if route_id is None:
        raise InventoryMutationError("جلسة العمل لا ترتبط بموقع السيارة المحدد داخل الشركة.")

    snapshots = (
        await db_session.execute(
            select(SessionInventorySnapshot)
            .execution_options(populate_existing=True)
            .filter_by(company_id=company_id, work_session_id=work_session.id)
            .order_by(
                SessionInventorySnapshot.product_variant_id.asc(),
                SessionInventorySnapshot.stock_status.asc(),
                SessionInventorySnapshot.id.asc(),
            )
            .with_for_update()
        )
    ).scalars().all()

    if any(int(row.location_id) != vehicle_location_id for row in snapshots):
        raise InventoryMutationError("لقطة جلسة المندوب مرتبطة بموقع سيارة مختلف؛ تم رفض التسوية.")

    if work_session.is_settled and work_session.inventory_reconciled_at is None:
        raise InventoryMutationError(
            "جلسة مسواة مالياً بدون ختم تسوية مخزنية؛ البيانات غير متسقة."
        )

    if work_session.inventory_reconciled_at is not None:
        if work_session.inventory_reconciled_by is None:
            raise InventoryMutationError("ختم التسوية المخزنية ناقص هوية المنفذ.")
        if any(
            row.ending_quantity is None
            or row.settled_by is None
            or row.settled_at is None
            for row in snapshots
        ):
            raise InventoryMutationError("جلسة مخزون معلّمة كمطابقة لكن Ending Snapshot ناقص.")
        return work_session

    if work_session.inventory_reconciled_by is not None:
        raise InventoryMutationError("تم اكتشاف ختم تسوية مخزنية جزئي على WorkSession.")

    if any(
        row.ending_quantity is not None
        or row.settled_by is not None
        or row.settled_at is not None
        for row in snapshots
    ):
        raise InventoryMutationError("تم اكتشاف تسوية مخزنية جزئية في SessionInventorySnapshot.")

    final_rows = (
        await db_session.execute(
            select(InventoryBalance)
            .filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == vehicle_location_id,
                or_(
                    InventoryBalance.on_hand_quantity > 0,
                    InventoryBalance.reserved_quantity > 0,
                ),
            )
            .order_by(
                InventoryBalance.product_variant_id.asc(),
                InventoryBalance.batch_id.asc(),
                InventoryBalance.stock_status.asc(),
                InventoryBalance.id.asc(),
            )
            .limit(_MAX_STOCKTAKE_POST_LINES + 1)
            .with_for_update()
        )
    ).scalars().all()
    if len(final_rows) > _MAX_STOCKTAKE_POST_LINES:
        raise InventoryMutationError("رصيد السيارة يتجاوز الحد الآمن لتثبيت Ending Snapshot.")
    if any(_quantity_decimal(row.reserved_quantity or 0) != 0 for row in final_rows):
        raise InventoryMutationError(
            "لا يمكن ختم عهدة السيارة بوجود مخزون محجوز؛ يجب تحرير جميع الحجوزات أولاً."
        )

    final_map: Dict[Tuple[int, str], Decimal] = {}
    for balance in final_rows:
        key = (int(balance.product_variant_id), str(balance.stock_status))
        next_value = final_map.get(key, Decimal("0")) + _quantity_decimal(balance.on_hand_quantity or 0)
        if next_value < 0 or next_value > QUANTITY_MAX:
            raise InventoryMutationError("إجمالي عهدة نهاية الجلسة يتجاوز سعة NUMERIC(20,6).")
        final_map[key] = next_value

    snapshot_map: Dict[Tuple[int, str], SessionInventorySnapshot] = {}
    for row in snapshots:
        key = (int(row.product_variant_id), str(row.stock_status))
        if key in snapshot_map:
            raise InventoryMutationError("لقطة الجلسة تحتوي صنف/حالة مكررة.")
        snapshot_map[key] = row

    settled_at = utc_now()
    for key in sorted(set(snapshot_map) | set(final_map)):
        ending_quantity = final_map.get(key, Decimal("0"))
        row = snapshot_map.get(key)
        if row is None:
            product_variant_id, stock_status = key
            row = SessionInventorySnapshot(
                company_id=company_id,
                work_session_id=work_session.id,
                location_id=vehicle_location_id,
                product_variant_id=product_variant_id,
                stock_status=stock_status,
                starting_quantity=Decimal("0"),
            )
            db_session.add(row)
        row.ending_quantity = ending_quantity
        row.settled_by = settled_by
        row.settled_at = settled_at

    work_session.inventory_reconciled_at = settled_at
    work_session.inventory_reconciled_by = settled_by
    # is_settled يبقى False هنا عمداً: هذا حق التسوية المالية لدى المحاسب فقط.
    await db_session.flush()
    return work_session


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
            select(
                StocktakeSession.location_id,
                StocktakeSession.stocktake_type,
                StocktakeSession.related_work_session_id,
            ).filter_by(
                company_id=company_id,
                id=stocktake_session_id,
            )
        )
    ).one_or_none()
    if probe is None:
        raise InventoryMutationError("جلسة الجرد غير موجودة أو لا تتبع الشركة.")

    probe_location_id, probe_type, probe_work_session_id = probe
    # VEHICLE_RECON يلتزم ترتيب أقفال موحد: WorkSession -> inventory-location guard.
    if probe_type == "VEHICLE_RECON":
        if probe_work_session_id is None:
            raise InventoryMutationError("VEHICLE_RECON بدون WorkSession مرتبط.")
        locked_probe_session = (
            await db_session.execute(
                select(WorkSession.id).filter_by(
                    company_id=company_id,
                    id=probe_work_session_id,
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if locked_probe_session is None:
            raise InventoryMutationError("جلسة العمل المرتبطة بـ VEHICLE_RECON غير موجودة أو خارج الشركة.")

    # الترحيل عملية حصرية على الموقع؛ يمنع أي حركة متزامنة أثناء تثبيت جميع الفروقات.
    await acquire_inventory_location_guard(
        db_session,
        company_id,
        int(probe_location_id),
        exclusive=True,
    )

    session = (
        await db_session.execute(
            select(StocktakeSession).execution_options(populate_existing=True).filter_by(
                company_id=company_id,
                id=stocktake_session_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if (
        session is None
        or session.location_id != probe_location_id
        or session.stocktake_type != probe_type
        or session.related_work_session_id != probe_work_session_id
    ):
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
                InventoryLocation.vehicle_id,
            ).filter_by(
                company_id=company_id,
                id=session.location_id,
            ).with_for_update(read=True)
        )
    ).one_or_none()
    if location_row is None:
        raise InventoryMutationError("موقع جلسة الجرد غير موجود أو لا يتبع الشركة.")
    location_type, location_is_active, location_vehicle_id = location_row
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

    # POSTED replay يبقى idempotent حتى لو تمت التسوية المالية لاحقاً.
    if (
        session.stocktake_type == "VEHICLE_RECON"
        and session.status == "APPROVED"
    ):
        if location_vehicle_id is None:
            raise InventoryMutationError(
                "موقع VEHICLE_RECON لا يحمل vehicle_id صالحاً."
            )
        await validate_vehicle_recon_work_session(
            db_session,
            company_id=company_id,
            work_session_id=session.related_work_session_id,
            vehicle_id=location_vehicle_id,
        )

    latest_attempt = (
        await db_session.execute(
            select(StocktakeCountAttempt).execution_options(populate_existing=True).filter_by(
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

    if (
        latest_attempt.submitted_at is None
        or session.snapshot_cutoff_at is None
        or latest_attempt.submitted_at < session.snapshot_cutoff_at
        or latest_attempt.submitted_at > session.approved_at
    ):
        raise InventoryMutationError("توقيت آخر محاولة عد لا يطابق اللقطة والاعتماد.")

    parent_attempt = None
    if latest_attempt.recount_of_attempt_id is not None:
        parent_attempt = (
            await db_session.execute(
                select(StocktakeCountAttempt).execution_options(populate_existing=True).filter_by(
                    company_id=company_id,
                    stocktake_session_id=session.id,
                    id=latest_attempt.recount_of_attempt_id,
                )
            )
        ).scalar_one_or_none()
        if (
            parent_attempt is None
            or parent_attempt.attempt_number != latest_attempt.attempt_number - 1
            or parent_attempt.submitted_at > latest_attempt.submitted_at
        ):
            raise InventoryMutationError("سلسلة إعادة العد لا ترتبط بالمحاولة السابقة مباشرة.")
        if (
            parent_attempt.requires_independent_recount
            and parent_attempt.counted_by == latest_attempt.counted_by
        ):
            raise InventoryMutationError("إعادة العد الإلزامية يجب أن ينفذها مستخدم مستقل.")
    if latest_attempt.requires_independent_recount and (
        parent_attempt is None or not parent_attempt.requires_independent_recount
    ):
        raise InventoryMutationError("العجز المادي يتطلب إعادة عد مستقلة قبل الترحيل.")

    # تحميل Snapshot ومحاولة العد معاً يكشف أي سطر مفقود دون Query لكل صنف.
    stmt_lines = (
        select(StocktakeLine, StocktakeCountAttemptLine).execution_options(populate_existing=True)
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
        .limit(_MAX_STOCKTAKE_POST_LINES + 1)
    )
    line_rows = (await db_session.execute(stmt_lines)).all()
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

    own_locks = (
        await db_session.execute(
            select(InventoryLock)
            .execution_options(populate_existing=True)
            .filter(
                InventoryLock.company_id == company_id,
                InventoryLock.stocktake_session_id == session.id,
                InventoryLock.location_id == session.location_id,
                InventoryLock.released_at.is_(None),
            ).order_by(
                InventoryLock.id.asc()
            ).with_for_update()
        )
    ).scalars().all()

    conflict_scope = None
    if session.status == "APPROVED":
        if session.stocktake_type in {"FULL_COUNT", "VEHICLE_RECON"}:
            own_scope_ok = any(
                lock.product_variant_id is None
                and lock.batch_id is None
                for lock in own_locks
            )
        elif session.scope_batch_id is None:
            own_scope_ok = any(
                lock.product_variant_id
                == session.scope_product_variant_id
                and lock.batch_id is None
                for lock in own_locks
            )
            conflict_scope = or_(
                InventoryLock.product_variant_id.is_(None),
                InventoryLock.product_variant_id
                == session.scope_product_variant_id,
            )
        else:
            own_scope_ok = any(
                lock.product_variant_id
                == session.scope_product_variant_id
                and lock.batch_id == session.scope_batch_id
                for lock in own_locks
            )
            conflict_scope = or_(
                InventoryLock.product_variant_id.is_(None),
                and_(
                    InventoryLock.product_variant_id
                    == session.scope_product_variant_id,
                    or_(
                        InventoryLock.batch_id.is_(None),
                        InventoryLock.batch_id
                        == session.scope_batch_id,
                    ),
                ),
            )

        if not own_scope_ok:
            raise InventoryMutationError(
                "قفل الجرد الفعال لا يطابق نطاق الجلسة المعتمدة."
            )

        stmt_conflict = select(InventoryLock.id).filter(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == session.location_id,
            InventoryLock.stocktake_session_id != session.id,
            InventoryLock.released_at.is_(None),
        )
        if conflict_scope is not None:
            stmt_conflict = stmt_conflict.filter(
                conflict_scope
            )

        conflicting_lock_id = (
            await db_session.execute(
                stmt_conflict
                .order_by(InventoryLock.id.asc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()

        if conflicting_lock_id is not None:
            raise InventoryMutationError(
                "يوجد قفل جرد آخر متعارض مع نطاق الجلسة الحالية."
            )

    specs = []
    expected_by_key = {}
    for stocktake_line, attempt_line in line_rows:
        if (
            stocktake_line.company_id != company_id
            or stocktake_line.stocktake_session_id != session.id
            or attempt_line.company_id != company_id
            or attempt_line.stocktake_session_id != session.id
            or attempt_line.stocktake_line_id != stocktake_line.id
            or attempt_line.count_attempt_id != latest_attempt.id
        ):
            raise InventoryMutationError("هوية سطر العد لا تطابق لقطة الجرد والمحاولة.")
        stock_status = stocktake_line.stock_status
        if stock_status not in _INVENTORY_STOCK_STATUSES:
            raise InventoryMutationError("حالة مخزون غير صالحة في سطر الجرد.")
        key = (stocktake_line.product_variant_id, stocktake_line.batch_id, stock_status)
        if key in expected_by_key:
            raise InventoryMutationError("لقطة الجرد تحتوي هوية صنف/دفعة/حالة مكررة.")
        if attempt_line.expected_quantity != stocktake_line.expected_quantity:
            raise InventoryMutationError("الكمية المتوقعة في العد تختلف عن لقطة الجرد المقفلة.")
        expected_by_key[key] = stocktake_line.expected_quantity
        variance = attempt_line.variance_quantity
        if variance != attempt_line.actual_quantity - attempt_line.expected_quantity:
            raise InventoryMutationError("تم اكتشاف فرق جرد غير متسق حسابياً.")
        if variance == 0:
            continue

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
            select(InventoryMovement).execution_options(populate_existing=True).filter(
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

        snap = movement.financial_unit_price_snapshot
        if spec["reference_type"] == "DRIVER_SHORTAGE":
            if snap is None:
                raise InventoryMutationError(
                    "حركة DRIVER_SHORTAGE تاريخية بلا سعر مالي مثبت؛ البيانات غير مكتملة."
                )
            snap_dec = Decimal(str(snap))
            total_value = snap_dec * spec["quantity"]
            if (
                not snap_dec.is_finite()
                or snap_dec < 0
                or snap_dec > _MONEY_12_3_MAX
                or not total_value.is_finite()
                or total_value > _MONEY_12_3_MAX
            ):
                raise InventoryMutationError("قيمة DRIVER_SHORTAGE التاريخية خارج النطاق المالي.")
        elif snap is not None:
            raise InventoryMutationError(
                "حركة جرد غير DRIVER_SHORTAGE تحمل سعراً مالياً لا يخصها."
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
        if session.stocktake_type == "VEHICLE_RECON":
            recon_state = (
                await db_session.execute(
                    select(
                        WorkSession.inventory_reconciled_at,
                        WorkSession.inventory_reconciled_by,
                    ).filter_by(
                        company_id=company_id,
                        id=session.related_work_session_id,
                    )
                )
            ).one_or_none()
            if (
                recon_state is None
                or recon_state.inventory_reconciled_at is None
                or recon_state.inventory_reconciled_by is None
            ):
                raise InventoryMutationError(
                    "VEHICLE_RECON بحالة POSTED لكن WorkSession بلا ختم تسوية مخزنية مكتمل."
                )
            incomplete_snapshot_id = (
                await db_session.execute(
                    select(SessionInventorySnapshot.id)
                    .filter(
                        SessionInventorySnapshot.company_id == company_id,
                        SessionInventorySnapshot.work_session_id == session.related_work_session_id,
                        or_(
                            SessionInventorySnapshot.ending_quantity.is_(None),
                            SessionInventorySnapshot.settled_by.is_(None),
                            SessionInventorySnapshot.settled_at.is_(None),
                        ),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if incomplete_snapshot_id is not None:
                raise InventoryMutationError(
                    "VEHICLE_RECON بحالة POSTED لكن Ending Snapshot غير مكتمل."
                )
        return ordered_existing

    if existing_movements:
        raise InventoryMutationError(
            "تم العثور على حركات جرد سابقة بينما الجلسة ما زالت APPROVED؛ تم رفض الحالة الجزئية."
        )

    # اقرأ نطاق الجرد الفعلي مرة واحدة.
    # VEHICLE_RECON قد يكون كاملاً (من warehouse) أو موجهاً فقط لأصناف ظهر بها فرق تجميعي.
    stmt_balances = select(InventoryBalance).execution_options(populate_existing=True).filter(
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == session.location_id,
    )
    if session.stocktake_type == "CYCLE_COUNT":
        stmt_balances = stmt_balances.filter(
            InventoryBalance.product_variant_id == session.scope_product_variant_id,
        )
        if session.scope_batch_id is not None:
            stmt_balances = stmt_balances.filter(
                InventoryBalance.batch_id == session.scope_batch_id,
            )
    elif session.stocktake_type == "VEHICLE_RECON":
        recon_variant_ids = sorted({
            int(stocktake_line.product_variant_id)
            for stocktake_line, _ in line_rows
        })
        if recon_variant_ids:
            stmt_balances = stmt_balances.filter(
                InventoryBalance.product_variant_id.in_(recon_variant_ids)
            )
        else:
            # جلسة موجّهة بلا Snapshot لا تفحص أصنافاً غير مكتشفة؛ أي DISCOVERED يضيف سطره قبل الاعتماد.
            stmt_balances = stmt_balances.filter(InventoryBalance.id == -1)
    # تجاهل الأرصدة الصفرية التاريخية خارج اللقطة، وحدّ حجم النتيجة قبل تحميلها في الذاكرة.
    stmt_balances = stmt_balances.filter(or_(
        InventoryBalance.on_hand_quantity > 0,
        tuple_(
            InventoryBalance.product_variant_id,
            InventoryBalance.batch_id,
            InventoryBalance.stock_status,
        ).in_(sorted(expected_by_key)),
    ))
    balances = (await db_session.execute(stmt_balances.order_by(
        InventoryBalance.product_variant_id.asc(),
        InventoryBalance.batch_id.asc(),
        InventoryBalance.stock_status.asc(),
    ).limit(_MAX_STOCKTAKE_POST_LINES + 1).with_for_update())).scalars().all()
    if len(balances) > _MAX_STOCKTAKE_POST_LINES:
        raise InventoryMutationError("الأرصدة الفعلية تتجاوز نطاق لقطة الجرد المسموح.")
    balance_map = {
        (row.product_variant_id, row.batch_id, row.stock_status): row
        for row in balances
    }
    for key, balance in balance_map.items():
        if key not in expected_by_key and balance.on_hand_quantity != 0:
            raise InventoryMutationError("يوجد رصيد فعلي خارج أسطر لقطة الجرد؛ تم رفض الترحيل.")
    for key, expected_quantity in expected_by_key.items():
        balance = balance_map.get(key)
        current_quantity = balance.on_hand_quantity if balance is not None else 0
        if current_quantity != expected_quantity:
            raise InventoryMutationError("الرصيد الحي تغيّر عن لقطة الجرد المقفلة؛ تم رفض الترحيل.")

    # إعادة تحقق bounded بعد Row Locks؛ لا نحمل كل أقفال الموقع إلى الذاكرة.
    if session.status == "APPROVED":
        stmt_conflict_recheck = select(InventoryLock.id).filter(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == session.location_id,
            InventoryLock.stocktake_session_id != session.id,
            InventoryLock.released_at.is_(None),
        )
        if conflict_scope is not None:
            stmt_conflict_recheck = stmt_conflict_recheck.filter(
                conflict_scope
            )

        if (
            await db_session.execute(
                stmt_conflict_recheck.limit(1)
            )
        ).scalar_one_or_none() is not None:
            raise InventoryMutationError(
                "ظهر قفل جرد متعارض أثناء الترحيل؛ أعد المحاولة لضمان لقطة متسقة."
            )

    # تثبيت سعر العجز في لحظة اعتماد/ترحيل VEHICLE_RECON؛ لا نقرأ السعر الحي لاحقاً أبداً.
    shortage_variant_ids = sorted({
        int(spec["product_variant_id"])
        for spec in specs
        if spec["reference_type"] == "DRIVER_SHORTAGE"
    })
    shortage_unit_prices = {}
    if shortage_variant_ids:
        price_rows = (
            await db_session.execute(
                select(
                    ProductVariant.id,
                    ProductVariant.price_per_pack,
                )
                .filter(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(shortage_variant_ids),
                )
                .order_by(ProductVariant.id.asc())
                .with_for_update(read=True)
            )
        ).all()
        if {int(row.id) for row in price_rows} != set(shortage_variant_ids):
            raise InventoryMutationError("أحد أصناف عجز المندوب مفقود داخل الشركة.")

        for row in price_rows:
            # Preserve the existing accounting rule exactly: DRIVER_SHORTAGE is valued by price_per_pack.
            # We only freeze that value here; we do not invent a new carton-price fallback.
            unit_price = _money_12_3(row.price_per_pack or "0.000", "price_per_pack")
            if not unit_price.is_finite() or unit_price < 0 or unit_price > _MONEY_12_3_MAX:
                raise InventoryMutationError("سعر عجز المندوب غير صالح للتثبيت المالي.")
            shortage_unit_prices[int(row.id)] = unit_price

        for spec in specs:
            if spec["reference_type"] != "DRIVER_SHORTAGE":
                spec["financial_unit_price_snapshot"] = None
                continue
            unit_price = shortage_unit_prices[int(spec["product_variant_id"])]
            total_value = unit_price * spec["quantity"]
            if not total_value.is_finite() or total_value > _MONEY_12_3_MAX:
                raise InventoryMutationError(
                    "قيمة عجز المندوب الناتجة تتجاوز السعة المالية Numeric(12,3)."
                )
            spec["financial_unit_price_snapshot"] = unit_price
    else:
        for spec in specs:
            spec["financial_unit_price_snapshot"] = None

    movement_specs = []
    for spec in specs:
        movement_specs.append({
            "product_variant_id": spec["product_variant_id"],
            "batch_id": spec["batch_id"],
            "quantity": spec["quantity"],
            "movement_kind": "PHYSICAL",
            "reference_type": spec["reference_type"],
            "reference_id": spec["reference_id"],
            "idempotency_key": spec["idempotency_key"],
            "source_location_id": spec["source_location_id"],
            "destination_location_id": spec["destination_location_id"],
            "source_stock_status": spec["source_stock_status"],
            "destination_stock_status": spec["destination_stock_status"],
            "reservation_action": None,
            "work_session_id": spec["work_session_id"],
            "transfer_header_id": None,
            "stocktake_session_id": session.id,
            "stocktake_count_attempt_id": latest_attempt.id,
            "financial_unit_price_snapshot": spec.get("financial_unit_price_snapshot"),
            "notes": "ترحيل فرق آخر محاولة عد معتمدة.",
        })

    applied_movements = []
    if movement_specs:
        applied_movements = await apply_inventory_movements_batch(
            db_session,
            company_id=company_id,
            performed_by=performed_by,
            movements=movement_specs,
        )
        if len(applied_movements) != len(movement_specs):
            raise InventoryMutationError(
                "المحرك الموحد لم يعد جميع حركات فروقات الجرد المتوقعة."
            )

    now = utc_now()
    await db_session.execute(
        update(InventoryLock).where(
            InventoryLock.company_id == company_id,
            InventoryLock.stocktake_session_id == session.id,
            InventoryLock.released_at.is_(None),
        ).values(
            released_by=performed_by,
            released_at=now,
            release_reason="STOCKTAKE_POSTED",
        )
    )

    session.status = "POSTED"
    session.posted_at = now
    session.updated_at = now

    # VEHICLE_RECON لا يكتمل مخزنياً قبل تثبيت Ending Snapshot وختم inventory_reconciled_*.
    # التسوية المالية (WorkSession.is_settled) لا تتم هنا.
    if session.stocktake_type == "VEHICLE_RECON":
        await finalize_vehicle_inventory_reconciliation(
            db_session,
            company_id=company_id,
            work_session_id=session.related_work_session_id,
            vehicle_location_id=session.location_id,
            settled_by=performed_by,
        )

    return applied_movements


# تخصيص FEFO على الدفعات غير المقفلة؛ يجب استهلاك النتيجة في نفس المعاملة دون commit بين التخصيص والتنفيذ.

async def allocate_fefo_inventory_batch(
    db_session: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    requests: Dict[int, Decimal],
    as_of_date: date,
    require_full: bool = True,
) -> Dict[int, List[Tuple[int, Decimal]]]:
    try:
        company_id = _strict_int(company_id, "company_id", minimum=1)
        location_id = _strict_int(location_id, "location_id", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    if type(as_of_date) is not date:
        raise InventoryMutationError(
            "as_of_date إجباري ويجب أن يكون تاريخ العمل المحلي للشركة."
        )
    if not isinstance(requests, dict) or not requests:
        return {}
    if len(requests) > 5000:
        raise InventoryMutationError(
            "دفعة FEFO تتجاوز الحد الآمن البالغ 5000 صنف."
        )

    normalized_requests: Dict[int, Decimal] = {}
    try:
        for raw_variant_id, raw_quantity in requests.items():
            variant_id = _strict_int(
                raw_variant_id,
                "product_variant_id",
                minimum=1,
            )
            quantity = _quantity_decimal(raw_quantity, "quantity", allow_zero=True)
            if variant_id in normalized_requests:
                raise ValueError(
                    "product_variant_id مكرر داخل طلب FEFO الدفعي."
                )
            normalized_requests[variant_id] = quantity
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc

    requested_all = sorted(normalized_requests)
    positive_requests = {
        variant_id: quantity
        for variant_id, quantity in normalized_requests.items()
        if quantity > 0
    }
    if not positive_requests:
        return {variant_id: [] for variant_id in requested_all}

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
        raise InventoryMutationError(
            "موقع المخزون غير موجود أو غير فعال."
        )

    requested_variant_ids = sorted(positive_requests)

    quantity_rule_rows = (
        await db_session.execute(
            select(
                ProductVariant.id,
                ProductVariant.quantity_scale,
                ProductVariant.quantity_step,
                ProductVariant.expiry_control_mode,
            ).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id.in_(requested_variant_ids),
            )
        )
    ).all()

    quantity_rules = {
        int(row.id): (
            int(row.quantity_scale),
            row.quantity_step,
            str(row.expiry_control_mode),
        )
        for row in quantity_rule_rows
    }

    if set(quantity_rules) != set(requested_variant_ids):
        raise InventoryMutationError(
            "أحد أصناف طلب FEFO غير موجود داخل الشركة."
        )

    shelf_life_rows = (
        await db_session.execute(
            select(
                InventoryStockPolicy.product_variant_id,
                InventoryStockPolicy.minimum_remaining_shelf_life_days,
            ).filter(
                InventoryStockPolicy.company_id == company_id,
                InventoryStockPolicy.location_id == location_id,
                InventoryStockPolicy.product_variant_id.in_(
                    requested_variant_ids
                ),
                InventoryStockPolicy.is_active.is_(True),
            ).order_by(
                InventoryStockPolicy.product_variant_id.asc()
            ).with_for_update(read=True)
        )
    ).all()

    minimum_shelf_life_by_variant = {
        int(row.product_variant_id):
            int(row.minimum_remaining_shelf_life_days or 0)
        for row in shelf_life_rows
    }
    try:
        positive_requests = {
            variant_id: validate_variant_quantity(
                quantity,
                quantity_scale=quantity_rules[variant_id][0],
                quantity_step=quantity_rules[variant_id][1],
                field_name="quantity",
            )
            for variant_id, quantity in positive_requests.items()
        }
    except QuantityError as exc:
        raise InventoryMutationError(str(exc)) from exc

    active_locks = (
        await db_session.execute(
            select(
                InventoryLock.product_variant_id,
                InventoryLock.batch_id,
            ).filter(
                InventoryLock.company_id == company_id,
                InventoryLock.location_id == location_id,
                InventoryLock.released_at.is_(None),
                or_(
                    InventoryLock.product_variant_id.is_(None),
                    InventoryLock.product_variant_id.in_(
                        requested_variant_ids
                    ),
                ),
            )
        )
    ).all()

    if any(
        product_variant_id is None
        for product_variant_id, _ in active_locks
    ):
        raise InventoryMutationError(
            f"الموقع ({location_id}) تحت الجرد ومقفل بالكامل."
        )

    product_locked = {
        int(product_variant_id)
        for product_variant_id, batch_id in active_locks
        if product_variant_id is not None and batch_id is None
    }
    blocked_products = sorted(
        product_locked & set(requested_variant_ids)
    )
    if blocked_products:
        raise InventoryMutationError(
            f"أصناف FEFO مقفلة بجرد نشط: {blocked_products[:10]}"
        )

    locked_batch_keys = {
        (int(product_variant_id), int(batch_id))
        for product_variant_id, batch_id in active_locks
        if product_variant_id is not None and batch_id is not None
    }

    candidate_pairs = (
        await db_session.execute(
            select(
                InventoryBalance.product_variant_id,
                InventoryBalance.batch_id,
            ).join(
                ProductBatch,
                and_(
                    ProductBatch.company_id
                    == InventoryBalance.company_id,
                    ProductBatch.product_variant_id
                    == InventoryBalance.product_variant_id,
                    ProductBatch.id
                    == InventoryBalance.batch_id,
                ),
            ).filter(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id.in_(
                    requested_variant_ids
                ),
                InventoryBalance.stock_status == "AVAILABLE",
                InventoryBalance.on_hand_quantity
                > InventoryBalance.reserved_quantity,
                ProductBatch.is_active.is_(True),
                ProductBatch.disposition == "RELEASED",
                or_(
                    ProductBatch.production_date.is_(None),
                    ProductBatch.production_date <= as_of_date,
                ),
                or_(
                    ProductBatch.expiry_date.is_(None),
                    ProductBatch.expiry_date >= as_of_date,
                ),
            ).order_by(
                InventoryBalance.product_variant_id.asc(),
                ProductBatch.expiry_date.asc().nulls_last(),
                ProductBatch.id.asc(),
            )
        )
    ).all()

    candidate_pairs = [
        (int(variant_id), int(batch_id))
        for variant_id, batch_id in candidate_pairs
        if (int(variant_id), int(batch_id))
        not in locked_batch_keys
    ]

    if not candidate_pairs:
        if require_full:
            first_variant = requested_variant_ids[0]
            raise InventoryMutationError(
                f"لا يوجد رصيد FEFO صالح للصنف ({first_variant})."
            )
        return {
            variant_id: []
            for variant_id in requested_all
        }

    # نقفل Metadata ثم الأرصدة على chunks ثابتة لتجنب حد parameters
    # في PostgreSQL عندما يكون لكل صنف عدد كبير من الدفعات.
    metadata_pairs = set()
    metadata_dates: Dict[
        Tuple[int, int],
        Tuple[Optional[date], Optional[date]],
    ] = {}

    for offset in range(
        0,
        len(candidate_pairs),
        _SQL_BULK_CHUNK_SIZE,
    ):
        chunk = candidate_pairs[
            offset:offset + _SQL_BULK_CHUNK_SIZE
        ]
        rows = (
            await db_session.execute(
                select(
                    ProductBatch.product_variant_id,
                    ProductBatch.id,
                    ProductBatch.production_date,
                    ProductBatch.expiry_date,
                ).filter(
                    ProductBatch.company_id == company_id,
                    tuple_(
                        ProductBatch.product_variant_id,
                        ProductBatch.id,
                    ).in_(chunk),
                    ProductBatch.is_active.is_(True),
                    ProductBatch.disposition == "RELEASED",
                    or_(
                        ProductBatch.production_date.is_(None),
                        ProductBatch.production_date <= as_of_date,
                    ),
                    or_(
                        ProductBatch.expiry_date.is_(None),
                        ProductBatch.expiry_date >= as_of_date,
                    ),
                ).order_by(
                    ProductBatch.product_variant_id.asc(),
                    ProductBatch.expiry_date.asc().nulls_last(),
                    ProductBatch.id.asc(),
                ).with_for_update(read=True)
            )
        ).all()

        for variant_id, batch_id, production_date, expiry_date in rows:
            key = (int(variant_id), int(batch_id))
            metadata_pairs.add(key)
            metadata_dates[key] = (production_date, expiry_date)

    valid_candidate_pairs = []
    for pair in candidate_pairs:
        if pair not in metadata_pairs:
            continue

        variant_id = pair[0]
        production_date, expiry_date = metadata_dates[pair]
        expiry_control_mode = quantity_rules[variant_id][2]
        min_days = minimum_shelf_life_by_variant.get(variant_id, 0)

        if _batch_metadata_is_sellable(
            as_of_date=as_of_date,
            expiry_control_mode=expiry_control_mode,
            production_date=production_date,
            expiry_date=expiry_date,
            minimum_remaining_shelf_life_days=min_days,
        ):
            valid_candidate_pairs.append(pair)
    candidate_pairs = valid_candidate_pairs

    balance_rows = []
    for offset in range(
        0,
        len(candidate_pairs),
        _SQL_BULK_CHUNK_SIZE,
    ):
        chunk = candidate_pairs[
            offset:offset + _SQL_BULK_CHUNK_SIZE
        ]
        balance_rows.extend(
            (
                await db_session.execute(
                    select(InventoryBalance)
                    .execution_options(populate_existing=True)
                    .filter(
                        InventoryBalance.company_id == company_id,
                        InventoryBalance.location_id == location_id,
                        InventoryBalance.stock_status == "AVAILABLE",
                        InventoryBalance.on_hand_quantity
                        > InventoryBalance.reserved_quantity,
                        tuple_(
                            InventoryBalance.product_variant_id,
                            InventoryBalance.batch_id,
                        ).in_(chunk),
                    ).order_by(
                        InventoryBalance.product_variant_id.asc(),
                        InventoryBalance.batch_id.asc(),
                    ).with_for_update()
                )
            ).scalars().all()
        )

    # ترتيب FEFO النهائي يعتمد على Metadata المقفلة، لا على ترتيب chunks.
    balance_rows.sort(
        key=lambda balance: (
            int(balance.product_variant_id),
            metadata_dates[
                (
                    int(balance.product_variant_id),
                    int(balance.batch_id),
                )
            ][1] is None,
            metadata_dates[
                (
                    int(balance.product_variant_id),
                    int(balance.batch_id),
                )
            ][1] or date.max,
            int(balance.batch_id),
        )
    )

    # فحص دفاعي بعد Row Locks؛ حارس الموقع يمنع المنشئ الصحيح من السباق،
    # والفحص يلتقط أي Legacy creator حتى تتم هجرته.
    refreshed_locks = (
        await db_session.execute(
            select(
                InventoryLock.product_variant_id,
                InventoryLock.batch_id,
            ).filter(
                InventoryLock.company_id == company_id,
                InventoryLock.location_id == location_id,
                InventoryLock.released_at.is_(None),
                or_(
                    InventoryLock.product_variant_id.is_(None),
                    InventoryLock.product_variant_id.in_(
                        requested_variant_ids
                    ),
                ),
            )
        )
    ).all()

    if any(
        product_variant_id is None
        for product_variant_id, _ in refreshed_locks
    ):
        raise InventoryMutationError(
            "بدأ جرد شامل أثناء تخصيص FEFO؛ أعد المحاولة."
        )

    refreshed_product_locks = {
        int(product_variant_id)
        for product_variant_id, batch_id in refreshed_locks
        if product_variant_id is not None and batch_id is None
    }
    if refreshed_product_locks & set(requested_variant_ids):
        raise InventoryMutationError(
            "بدأ جرد صنف أثناء تخصيص FEFO؛ أعد المحاولة."
        )

    refreshed_batch_locks = {
        (int(product_variant_id), int(batch_id))
        for product_variant_id, batch_id in refreshed_locks
        if product_variant_id is not None and batch_id is not None
    }
    selected_pairs = {
        (
            int(balance.product_variant_id),
            int(balance.batch_id),
        )
        for balance in balance_rows
    }
    if refreshed_batch_locks & selected_pairs:
        raise InventoryMutationError(
            "بدأ جرد دفعة أثناء تخصيص FEFO؛ أعد المحاولة."
        )

    allocations: Dict[int, List[Tuple[int, Decimal]]] = {
        variant_id: []
        for variant_id in requested_all
    }
    remaining = dict(positive_requests)

    for balance in balance_rows:
        variant_id = int(balance.product_variant_id)
        needed = remaining.get(variant_id, 0)
        if needed <= 0:
            continue

        available = (
            _quantity_decimal(balance.on_hand_quantity or 0)
            - _quantity_decimal(balance.reserved_quantity or 0)
        )
        if available <= 0:
            continue

        take = min(available, needed)
        allocations[variant_id].append((
            int(balance.batch_id),
            take,
        ))
        remaining[variant_id] -= take

    shortages = {
        variant_id: qty
        for variant_id, qty in remaining.items()
        if qty > 0
    }
    if shortages and require_full:
        first_variant = sorted(shortages)[0]
        raise InventoryMutationError(
            f"الرصيد FEFO المؤهل وغير المقفل لا يغطي الصنف ({first_variant}). "
            f"العجز: {shortages[first_variant]} حبة."
        )

    return allocations

async def allocate_fefo_inventory(
    db_session: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    product_variant_id: int,
    quantity: Decimal,
    as_of_date: date,
) -> List[Tuple[int, Decimal]]:
    result = await allocate_fefo_inventory_batch(
        db_session,
        company_id=company_id,
        location_id=location_id,
        requests={product_variant_id: quantity},
        as_of_date=as_of_date,
        require_full=True,
    )
    try:
        normalized_variant_id = _strict_int(product_variant_id, "product_variant_id", minimum=1)
    except ValueError as exc:
        raise InventoryMutationError(str(exc)) from exc
    return result.get(normalized_variant_id, [])


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
    if reference_type != "VISIT_REVERSAL":
        raise InventoryMutationError("عكس الزيارة يجب أن يحمل مرجع VISIT_REVERSAL حصراً.")
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
    stmt_original = select(InventoryMovement).execution_options(populate_existing=True).filter_by(
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
            select(InventoryMovement).execution_options(populate_existing=True).filter_by(
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
        "performed_by": performed_by,
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
        stmt_session = select(WorkSession).execution_options(populate_existing=True).filter_by(
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

    stmt_shop = select(Shop).execution_options(populate_existing=True).filter_by(
        company_id=company_id,
        id=shop_id,
    ).with_for_update()
    locked_shop = (await db_session.execute(stmt_shop)).scalar_one_or_none()
    if locked_shop is None:
        raise InventoryReversalError(
            "المحل غير موجود أو لا ينتمي لنفس الشركة."
        )

    stmt_visit = select(Visit).execution_options(populate_existing=True).filter_by(
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
        if locked_session.inventory_reconciled_at is not None:
            raise InventoryReversalError(
                "مرفوض: لا يمكن عكس زيارة بعد ختم التسوية المخزنية لجلسة العمل."
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
    stmt_items = select(VisitItem).execution_options(populate_existing=True).filter_by(
        company_id=company_id,
        visit_id=locked_visit.id,
    ).order_by(VisitItem.id.asc()).with_for_update()
    visit_items = (await db_session.execute(stmt_items)).scalars().all()

    stmt_returns = select(VisitReturn).execution_options(populate_existing=True).filter_by(
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
        stmt_movements = select(InventoryMovement).execution_options(populate_existing=True).filter(
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

    await db_session.execute(
        update(ShortageRequest)
        .where(
            ShortageRequest.company_id == company_id,
            ShortageRequest.fulfilled_by_visit_id == locked_visit.id,
            ShortageRequest.status == "fulfilled",
        )
        .values(
            status="pending",
            fulfilled_by_visit_id=None,
            fulfilled_at=None,
        )
    )

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
    storage_root = os.path.realpath(base_path)
    tenant_folder = os.path.join(storage_root, f"company_{comp_id}")
    # مجلد الشركة نفسه لا يجوز أن يكون رابطاً يعيد توجيهها إلى شركة أخرى أو خارج الجذر.
    if os.path.normcase(os.path.realpath(tenant_folder)) != os.path.normcase(tenant_folder):
        raise ValueError("خطأ أمني: مجلد الشركة يعيد التوجيه إلى مسار غير مسموح.")
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
