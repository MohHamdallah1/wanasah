from pydantic import BaseModel, Field, ConfigDict, model_validator, AliasChoices, field_validator
from pydantic.functional_validators import BeforeValidator
from typing import Optional, List, Any, Literal, Annotated, Dict, Union
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# ==========================================
# 0. Boundary primitives — fail closed, preserve DB precision, and reject lossy coercion.
# ==========================================
_DB_INT_MAX = 2_147_483_647
_MONEY_12_3_MAX = Decimal("999999999.999")
_MONEY_QUANT = Decimal("0.001")


class RequestModel(BaseModel):
    """Base for request DTOs: unknown client fields are contract violations."""
    model_config = ConfigDict(extra="forbid")


# تحويل أي قيمة مالية إلى Decimal محدود من NaN/Infinity مع دعم None عند الطلب.
def _finite_decimal(v: Any, *, allow_none: bool = False) -> Optional[Decimal]:
    if v is None or (isinstance(v, str) and not v.strip()):
        if allow_none:
            return None
        return Decimal("0.000")
    try:
        dec = Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("قيمة مالية غير صالحة") from exc
    if not dec.is_finite():
        raise ValueError("قيمة مالية غير صالحة (NaN/Infinity)")
    return dec


# تسلسل قيمة مالية صالحة إلى نص ثابت بثلاث منازل عشرية.
def clean_finance_str(v: Any) -> str:
    """Serialize a finite Numeric(12,3)-compatible value as a canonical 3-decimal string."""
    dec = _finite_decimal(v)
    if abs(dec) > _MONEY_12_3_MAX:
        raise ValueError("القيمة المالية تتجاوز سعة Numeric(12,3)")
    try:
        return format(dec.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP), "f")
    except InvalidOperation as exc:
        raise ValueError("قيمة مالية غير قابلة للتمثيل") from exc


# تحويل None إلى نص فارغ دون إسقاط القيم النصية الأخرى.
def clean_null_string(v: Any) -> str:
    return "" if v is None else str(v)


# تسلسل السعر إلى نص مالي ثابت مع رفض القيم الفاسدة أو السالبة.
def clean_null_price(v: Any) -> str:
    if v is None or (isinstance(v, str) and not v.strip()):
        return "0.000"
    dec = _finite_decimal(v)
    if dec < 0 or dec > _MONEY_12_3_MAX:
        raise ValueError("السعر خارج النطاق المالي المسموح")
    return format(dec.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP), "f")


# تحويل قيمة إلى INTEGER آمن دون قص الكسور أو قبول bool أو تجاوز سعة PostgreSQL.
def _strict_db_int(
    v: Any,
    *,
    minimum: int = 0,
    maximum: int = _DB_INT_MAX,
    empty_default: Optional[int] = None,
) -> int:
    if v is None or (isinstance(v, str) and not v.strip()):
        if empty_default is not None:
            return empty_default
        raise ValueError("قيمة رقمية مطلوبة")
    if isinstance(v, bool):
        raise ValueError("القيمة يجب أن تكون عدداً صحيحاً")
    try:
        dec = Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("قيمة رقمية غير صالحة") from exc
    if not dec.is_finite() or dec != dec.to_integral_value():
        raise ValueError("القيمة يجب أن تكون عدداً صحيحاً بدون كسور")
    if dec < minimum or dec > maximum:
        raise ValueError(f"القيمة خارج النطاق المسموح ({minimum}..{maximum})")
    return int(dec)


# تطبيع معرّف/كمية موجبة ضمن سعة INTEGER.
def positive_db_int_input(v: Any) -> int:
    return _strict_db_int(v, minimum=1)


# تطبيع كمية غير سالبة ضمن سعة INTEGER.
def nonnegative_db_int_input(v: Any) -> int:
    return _strict_db_int(v, minimum=0)


# تطبيع فرق موقّع ضمن سعة INTEGER.
def signed_db_int_input(v: Any) -> int:
    return _strict_db_int(v, minimum=-_DB_INT_MAX, maximum=_DB_INT_MAX)


# فرض invariant عدد الحبات في الكرتونة كموجب بدلاً من إخفاء فساد البيانات.
def clean_zero_packs(v: Any) -> int:
    # packs_per_carton is a model invariant; do not hide corrupt data by silently converting it to 1.
    return positive_db_int_input(v)


# تطبيع قيمة مالية اختيارية-المدخل إلى Numeric(12,3) دون تقريب صامت.
def safe_decimal_input(v: Any) -> Decimal:
    dec = _finite_decimal(v)
    if dec < 0 or dec > _MONEY_12_3_MAX:
        raise ValueError("القيمة المالية يجب أن تكون بين 0 و 999999999.999")
    try:
        quantized = dec.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("القيمة المالية غير قابلة للتمثيل بدقة 3 منازل") from exc
    if dec != quantized:
        raise ValueError("القيمة المالية لا يجوز أن تحتوي على أكثر من 3 منازل عشرية")
    return quantized



# تطبيع قيمة مالية اختيارية إلى Numeric(12,3) مع إبقاء None صريحاً.
def safe_optional_decimal(v: Any) -> Optional[Decimal]:
    dec = _finite_decimal(v, allow_none=True)
    if dec is None:
        return None
    if dec < 0 or dec > _MONEY_12_3_MAX:
        raise ValueError("القيمة المالية يجب أن تكون بين 0 و 999999999.999")
    try:
        quantized = dec.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("القيمة المالية غير قابلة للتمثيل بدقة 3 منازل") from exc
    if dec != quantized:
        raise ValueError("القيمة المالية لا يجوز أن تحتوي على أكثر من 3 منازل عشرية")
    return quantized



# رفض الفراغ/None للحقول المالية الإلزامية ثم تطبيق نفس حدود Numeric(12,3).
def required_money_input(v: Any) -> Decimal:
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ValueError("القيمة المالية مطلوبة")
    return safe_decimal_input(v)


# تطبيع sequence قديم مع الحفاظ على default=999 للفراغ فقط.
def safe_int_input(v: Any) -> int:
    # Preserve the legacy empty-sequence default, but never truncate fractional/huge values through float().
    return _strict_db_int(v, minimum=0, empty_default=999)


# تنظيف نص اختياري وتحويل الفراغ إلى None.
def _optional_text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("القيمة النصية يجب أن تكون نصاً")
    value = v.strip()
    if "\x00" in value:
        raise ValueError("القيمة النصية لا يجوز أن تحتوي على محرف NUL.")
    return value or None


# تنظيف نص إلزامي ورفض الفراغ أو الأنواع غير النصية.
def _required_text(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("القيمة النصية مطلوبة ويجب أن تكون نصاً")
    value = v.strip()
    if not value:
        raise ValueError("القيمة النصية لا يمكن أن تكون فارغة")
    if "\x00" in value:
        raise ValueError("القيمة النصية لا يجوز أن تحتوي على محرف NUL.")
    return value


# تطبيع خط العرض ورفض NaN/Infinity وخارج النطاق الجغرافي.
def _latitude_input(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        dec = Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("خط العرض غير صالح") from exc
    if not dec.is_finite() or dec < Decimal("-90") or dec > Decimal("90"):
        raise ValueError("خط العرض يجب أن يكون بين -90 و 90")
    return float(dec)


# تطبيع خط الطول ورفض NaN/Infinity وخارج النطاق الجغرافي.
def _longitude_input(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        dec = Decimal(str(v).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("خط الطول غير صالح") from exc
    if not dec.is_finite() or dec < Decimal("-180") or dec > Decimal("180"):
        raise ValueError("خط الطول يجب أن يكون بين -180 و 180")
    return float(dec)


# حماية حدود bcrypt مع إبقاء كلمة المرور نفسها دون strip أو تغيير.
def _bcrypt_password(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("كلمة المرور يجب أن تكون نصاً")
    if not v:
        raise ValueError("كلمة المرور مطلوبة")
    if len(v.encode("utf-8")) > 72:
        raise ValueError("كلمة المرور تتجاوز حد bcrypt البالغ 72 بايت")
    return v


# تطبيع معرّف اختياري موجب مع تحويل الفراغ إلى None.
def _normalize_optional_positive_id(v: Any) -> Optional[int]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return positive_db_int_input(v)


PositiveDbInt = Annotated[int, BeforeValidator(positive_db_int_input)]
NonNegativeDbInt = Annotated[int, BeforeValidator(nonnegative_db_int_input)]
SignedDbInt = Annotated[int, BeforeValidator(signed_db_int_input)]
OptionalPositiveDbInt = Annotated[Optional[int], BeforeValidator(_normalize_optional_positive_id)]
Latitude = Annotated[Optional[float], BeforeValidator(_latitude_input)]
Longitude = Annotated[Optional[float], BeforeValidator(_longitude_input)]
MoneyInput = Annotated[Decimal, BeforeValidator(safe_decimal_input)]
RequiredMoneyInput = Annotated[Decimal, BeforeValidator(required_money_input)]
OptionalMoneyInput = Annotated[Optional[Decimal], BeforeValidator(safe_optional_decimal)]

# ==========================================
# 1. دروع الردود العامة (Generic Responses)
# ==========================================
class MessageResponse(BaseModel):
    message: str

# ==========================================
# 2. دروع المصادقة وتسجيل الدخول (Auth)
# ==========================================
class LoginRequest(RequestModel):
    company_code: str = Field(..., min_length=2, max_length=50)
    username: str = Field(..., min_length=2, max_length=80, description="اسم المستخدم")
    password: str = Field(..., min_length=4, description="كلمة المرور")

    @field_validator("company_code", "username", mode="before")
    @classmethod
    def normalize_identity(cls, v: Any) -> str:
        return _required_text(v)

    @field_validator("password", mode="before")
    @classmethod
    def validate_password(cls, v: Any) -> str:
        return _bcrypt_password(v)


class LoginResponse(BaseModel):
    message: str
    token: str
    refresh_token: str
    driver_id: int
    driver_name: str
    is_admin: bool
    company_id: int # +++ زرع الهوية لحقنها في الموبايل والداشبورد +++
    company_code: str # +++ إجبارية لبناء ملف الـ SQLite الفيزيائي +++

# ==========================================
# 3. دروع العمليات المشتركة والمنتجات الفرعية (Shared)
# ==========================================
class ShopBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150, description="اسم المحل إجباري")
    phone_number: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=2000)
    latitude: Latitude = None
    longitude: Longitude = None
    location_link: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: Any) -> str:
        return _required_text(v)

    @field_validator("phone_number", "address", "location_link", "notes", mode="before")
    @classmethod
    def normalize_optional_strings(cls, v: Any) -> Optional[str]:
        return _optional_text(v)


class ShopCreate(ShopBase):
    model_config = ConfigDict(extra="forbid")

class ShopResponse(ShopBase):
    id: int
    zone_id: Optional[int]
    # +++ سد التسريب المالي: حماية أرصدة المحلات بـ String لضمان دقة القروش والبيسات +++
    current_balance: Annotated[str, BeforeValidator(clean_finance_str)] = "0.000"
    max_debt_limit: Annotated[str, BeforeValidator(clean_finance_str)] = "0.000"
    is_active: bool
    is_archived: bool
    sequence: Optional[int] = 999
    model_config = ConfigDict(from_attributes=True)

class TransferResponseRequest(RequestModel):
    response: Literal["accepted", "rejected"] = Field(..., description="رد المندوب")
    reason: Optional[str] = Field(None, max_length=1000, description="سبب الرفض إن وجد")

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    # الرفض قرار نهائي رقابي؛ يجب أن يحمل سبباً صريحاً ليتوافق مع سجل الحوالة النهائي.
    @model_validator(mode="after")
    def require_rejection_reason(self) -> "TransferResponseRequest":
        if self.response == "rejected" and not self.reason:
            raise ValueError("رفض الحوالة يتطلب سبباً واضحاً.")
        return self


class ProductVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    variant_name: str
    # +++ حماية التسريب المالي: استخدام الدالة النظيفة String +++
    price_per_carton: Annotated[str, BeforeValidator(clean_null_price)]
    packs_per_carton: Annotated[int, BeforeValidator(clean_zero_packs)]
    price_per_pack: Annotated[str, BeforeValidator(clean_null_price)]

# كائن مشترك يستخدم في أكثر من مكان (يجب تعريفه مبكراً)
class VisitProductMin(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    variant_name: str

class VisitShopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    address: Optional[str] = None
    phone_number: Optional[str] = None
    contact_person: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_link: Optional[str] = None
    zone_id: Optional[int] = None
    max_debt_limit: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    current_balance: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    sequence: Optional[int] = 999

# ==========================================
# 4. دروع تفاصيل الزيارة الفردية (Visit Details)
# ==========================================
class VisitDetailsShopResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_link: Optional[str] = None

class VisitDetailsItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_variant_id: int
    quantity: int
    packs_quantity: int
    bonus_quantity: int
    sample_quantity: int
    sample_packs_quantity: int = 0
    # +++ الدرع المالي الفولاذي: حماية السعر الإجمالي من التقريب الغبي +++
    total_price: Annotated[str, BeforeValidator(clean_finance_str)] = "0.000"
    variant_name: str = ""
    product_variant: Optional[VisitProductMin] = Field(None, exclude=True)

    @model_validator(mode='after')
    def populate_variant_name(self) -> 'VisitDetailsItemResponse':
        if self.product_variant:
            self.variant_name = self.product_variant.variant_name
        return self

class VisitDetailsReturnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_variant_id: int
    quantity: int
    packs_quantity: int
    return_type: str
    reason: Annotated[str, BeforeValidator(clean_null_string)] = ""

class VisitDetailsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    visit_id: int = Field(validation_alias="id")
    driver_id: Optional[int] = None
    outcome: Optional[str] = None
    status: str
    notes: Annotated[str, BeforeValidator(clean_null_string)] = ""
    no_sale_reason: Annotated[str, BeforeValidator(clean_null_string)] = ""
    cash_collected: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    debt_paid: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    shop: Optional[VisitDetailsShopResponse] = None
    cart_items: List[VisitDetailsItemResponse] = Field(default_factory=list, validation_alias="items")
    returns: List[VisitDetailsReturnResponse] = Field(default_factory=list)

# ==========================================
# 5. دروع عمليات الميدان والجلسات (Driver Operations)
# ==========================================
class SessionStartRequest(RequestModel):
    latitude: Latitude = None
    longitude: Longitude = None


class BreakToggleRequest(RequestModel):
    action: Literal["start", "end"]


class BatchTransferItem(RequestModel):
    transfer_id: PositiveDbInt
    status: Literal["accepted", "rejected"]
    reason: Optional[str] = Field(None, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    # كل رفض ضمن الرد الجماعي يجب أن يبقى قابلاً للتدقيق ولا يمر بلا سبب.
    @model_validator(mode="after")
    def require_rejection_reason(self) -> "BatchTransferItem":
        if self.status == "rejected" and not self.reason:
            raise ValueError("رفض الحوالة ضمن الدفعة يتطلب سبباً واضحاً.")
        return self


class BatchTransferResponseRequest(RequestModel):
    transfers: List[BatchTransferItem] = Field(..., min_length=1, max_length=200)

    @model_validator(mode="after")
    def reject_duplicate_transfers(self) -> "BatchTransferResponseRequest":
        ids = [item.transfer_id for item in self.transfers]
        if len(ids) != len(set(ids)):
            raise ValueError("لا يجوز إرسال نفس الحوالة أكثر من مرة في نفس الطلب.")
        return self


class PendingTransferItem(BaseModel):
    real_transfer_id: int
    product_name: str
    delta_cartons: int
    delta_packs: int

class PendingBatchResponse(BaseModel):
    transfer_id: str
    created_at: Optional[str]
    items: List[PendingTransferItem]

class AddShopRequest(RequestModel):
    name: str = Field(..., min_length=2, max_length=150)
    phone_number: str = Field(..., min_length=5, max_length=20)
    address: Optional[str] = Field(None, max_length=2000)
    contact_person: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=4000)
    location_link: Optional[str] = Field(None, max_length=500)
    latitude: Latitude = None
    longitude: Longitude = None

    @field_validator("name", "phone_number", mode="before")
    @classmethod
    def clean_required_strings(cls, v: Any) -> str:
        return _required_text(v)

    @field_validator("address", "contact_person", "notes", "location_link", mode="before")
    @classmethod
    def clean_optional_strings(cls, v: Any) -> Optional[str]:
        return _optional_text(v)


# ==========================================
# 6. دروع استعراض الزيارات للمندوب (Get Visits)
# ==========================================
class VisitItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_variant_id: int
    quantity: int
    packs_quantity: int
    bonus_quantity: int
    sample_quantity: int
    sample_packs_quantity: int
    sample_reason: Optional[str] = None
    # +++ الدرع المالي +++
    price_per_unit_at_sale: Annotated[str, BeforeValidator(clean_finance_str)] = "0.000"
    total_price: Annotated[str, BeforeValidator(clean_finance_str)] = "0.000"
    product_variant: Optional[VisitProductMin] = None
    is_cancelled: bool = Field(False, exclude=True)

class VisitReturnResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_variant_id: int
    quantity: int
    packs_quantity: int
    return_type: str
    reason: Optional[str] = None
    product_variant: Optional[VisitProductMin] = None
    is_cancelled: bool = Field(False, exclude=True)

class DriverVisitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    visit_id: int = Field(validation_alias="id")
    shop_id: int
    outcome: Optional[str] = None
    # يقرأ من خاصية الداتابيز (status) ويخرج في الـ JSON النهائي باسم (visit_status) لراحة الـ Flutter ومنع انهيار الـ Bloc
    status: str = Field(validation_alias="status", serialization_alias="visit_status")
    notes: Annotated[str, BeforeValidator(clean_null_string)] = ""
    is_emergency: bool
    no_sale_reason: Optional[str] = None
    tax_qr_code: Optional[str] = None
    cash_collected: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    debt_paid: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    shop_balance_before: Optional[Any] = Field(default=None, exclude=True)
    shop_name: str = ""
    shop_location_link: Optional[str] = None
    shop_latitude: Optional[float] = None
    shop_longitude: Optional[float] = None
    max_debt_limit: str = "0.0"
    shop_zone_id: Optional[int] = None
    allowed_zone_id: Optional[int] = None
    shop_balance: str = "0.0"
    visit_sequence: int = 999
    sequence: int = 999
    # +++ خط النقل: فتح المجال لمعلومات الاتصال بالمرور للموبايل +++
    shop_owner: Optional[str] = None
    shop_phone: Optional[str] = None
    shop: Optional[VisitShopResponse] = Field(default=None, exclude=True)
    cart_items: List[VisitItemResponse] = Field(default_factory=list, validation_alias="items")
    returns: List[VisitReturnResponse] = Field(default_factory=list)
    visit_timestamp: Optional[str] = None

    @field_validator('visit_timestamp', mode='before')
    @classmethod
    def format_time(cls, v):
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            else:
                v = v.astimezone(timezone.utc)
            return v.isoformat()
        return str(v) if v else None

    @field_validator('cart_items', 'returns', mode='after')
    @classmethod
    def filter_cancelled(cls, v):
        return [item for item in v if not getattr(item, 'is_cancelled', False)]

    @model_validator(mode='after')
    def compute_legacy_fields(self) -> 'DriverVisitResponse':
        if self.shop:
            self.shop_name = self.shop.name
            self.shop_location_link = self.shop.location_link
            self.shop_latitude = self.shop.latitude
            self.shop_longitude = self.shop.longitude
            self.shop_zone_id = self.shop.zone_id
            self.max_debt_limit = self.shop.max_debt_limit
            seq = self.shop.sequence if self.shop.sequence is not None else 999
            self.sequence = seq
            self.visit_sequence = seq
            if self.status == 'Completed' and self.shop_balance_before is not None:
                self.shop_balance = str(self.shop_balance_before)
            else:
                self.shop_balance = self.shop.current_balance

            # +++ تعبئة معلومات الاتصال من الكائن المخفي قبل إرسال الـ JSON +++
            self.shop_owner = self.shop.contact_person
            self.shop_phone = self.shop.phone_number
        return self

class InventoryDataResponse(BaseModel):
    id: int
    name: str
    price_per_carton: Annotated[str, BeforeValidator(clean_null_price)] = "0.000"
    price_per_pack: Annotated[str, BeforeValidator(clean_null_price)] = "0.000"
    packs_per_carton: int
    starting_cartons: int
    current_cartons: int
    current_packs: int

class PendingTransferMinResponse(BaseModel):
    transfer_id: int
    product_variant_id: int
    quantity_packs: int
    status: str
    created_at: Optional[str] = None

class GetVisitsContract(BaseModel):
    visits: List[DriverVisitResponse]
    inventory: List[InventoryDataResponse]
    pending_transfers: List[PendingTransferMinResponse] = Field(default_factory=list) # +++ إحياء الميزة الميتة +++

# ==========================================
# 7. دروع التحديث الميداني (Update Visit)
# ==========================================
class VisitItemInput(RequestModel):
    product_variant_id: PositiveDbInt
    quantity: NonNegativeDbInt = 0
    packs_quantity: NonNegativeDbInt = 0
    # العميل لا يحدد البونص؛ الخادم يحسبه من OfferRule. نبقي الحقل للتوافق لكن لا نسمح بقيمة غير صفرية.
    bonus_quantity: NonNegativeDbInt = 0
    sample_quantity: NonNegativeDbInt = Field(
        0, validation_alias=AliasChoices("sample_quantity", "sample_cartons")
    )
    sample_packs_quantity: NonNegativeDbInt = Field(
        0, validation_alias=AliasChoices("sample_packs_quantity", "sample_packs")
    )
    sample_reason: Optional[str] = Field(None, max_length=255)

    @field_validator("sample_reason", mode="before")
    @classmethod
    def normalize_sample_reason(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    @model_validator(mode="after")
    def validate_line(self) -> "VisitItemInput":
        if self.bonus_quantity != 0:
            raise ValueError("bonus_quantity محسوب من الخادم ولا يجوز للعميل إرساله بقيمة غير صفرية.")
        total_samples = self.sample_quantity + self.sample_packs_quantity
        if total_samples > 0 and not self.sample_reason:
            raise ValueError(
                f"يجب تحديد سبب صرف العينات للمنتج رقم {self.product_variant_id}."
            )
        if total_samples == 0:
            self.sample_reason = None
        if self.quantity + self.packs_quantity + total_samples == 0:
            raise ValueError("لا يجوز إرسال سطر منتج بكميات صفرية بالكامل.")
        return self


class VisitReturnInput(RequestModel):
    product_variant_id: PositiveDbInt
    quantity: NonNegativeDbInt = Field(
        0, validation_alias=AliasChoices("quantity", "cartons")
    )
    packs_quantity: NonNegativeDbInt = Field(
        0, validation_alias=AliasChoices("packs_quantity", "packs")
    )
    return_type: Literal["Expired", "Damaged", "Factory_Defect"] = "Damaged"
    reason: Optional[str] = Field(None, max_length=2000)

    @field_validator("return_type", mode="before")
    @classmethod
    def normalize_return_type(cls, v: Any) -> str:
        if v is None or (isinstance(v, str) and not v.strip()):
            return "Damaged"
        return str(v).strip()

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    @model_validator(mode="after")
    def require_nonzero_return(self) -> "VisitReturnInput":
        if self.quantity + self.packs_quantity == 0:
            raise ValueError("لا يجوز إرسال سطر مرتجع بكميات صفرية بالكامل.")
        return self


class VisitUpdateRequest(RequestModel):
    outcome: Literal["Sale", "NoSale", "Postponed"]
    notes: Optional[str] = Field(None, max_length=4000)
    is_emergency: bool = False
    latitude: Latitude = None
    longitude: Longitude = None
    cash_collected: MoneyInput = Decimal("0.000")
    debt_paid: MoneyInput = Decimal("0.000")
    cart_items: List[VisitItemInput] = Field(default_factory=list, max_length=500)
    returns: List[VisitReturnInput] = Field(default_factory=list, max_length=500)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    @model_validator(mode="after")
    def validate_visit_logic(self) -> "VisitUpdateRequest":
        cart_product_ids = [item.product_variant_id for item in self.cart_items]
        if len(cart_product_ids) != len(set(cart_product_ids)):
            raise ValueError(
                "لا يجوز تكرار نفس المنتج في سلة الزيارة؛ اجمع البيع والعينات في سطر واحد."
            )

        return_keys = [
            (item.product_variant_id, item.return_type)
            for item in self.returns
        ]
        if len(return_keys) != len(set(return_keys)):
            raise ValueError(
                "لا يجوز تكرار نفس المنتج ونوع المرتجع في أكثر من سطر."
            )

        has_real_sales = any(
            item.quantity > 0 or item.packs_quantity > 0
            for item in self.cart_items
        )
        total_samples = sum(
            item.sample_quantity + item.sample_packs_quantity
            for item in self.cart_items
        )
        total_returns = sum(
            item.quantity + item.packs_quantity
            for item in self.returns
        )

        if self.outcome in {"NoSale", "Postponed"} and self.notes and len(self.notes) > 200:
            raise ValueError(
                "سبب NoSale/Postponed لا يجوز أن يتجاوز 200 حرف لأنه يُحفظ في no_sale_reason."
            )

        if self.outcome == "Sale":
            if not has_real_sales:
                raise ValueError(
                    "حالة Sale تتطلب كمية بيع فعلية؛ العينات أو المرتجعات وحدها تسجل كـ NoSale."
                )
        elif self.outcome == "NoSale":
            if has_real_sales or self.cash_collected > Decimal("0"):
                raise ValueError(
                    "حالة NoSale لا تقبل مبيعات فعلية أو تحصيل كاش؛ "
                    "يسمح بالعينات/المرتجعات أو تحصيل ديون سابقة."
                )
            if total_samples == 0 and total_returns == 0 and not self.notes:
                raise ValueError("يجب كتابة سبب عدم البيع في الملاحظات.")
        else:  # Postponed
            if (
                self.cash_collected > Decimal("0")
                or self.debt_paid > Decimal("0")
                or self.cart_items
                or self.returns
            ):
                raise ValueError(
                    "الزيارة المؤجلة لا تقبل مبيعات أو عينات أو مرتجعات أو تحصيلاً مالياً."
                )
        return self


# +++ سكيما الدالة القادمة (Active Session) +++
class ActiveSessionResponse(BaseModel):
    active_session_found: bool
    session_id: Optional[int] = None
    start_time: Optional[str] = None

# ==========================================
# 8. دروع لوحة التحكم والإدارة (Admin / Dispatch)
# ==========================================
class AuthorizeSessionRequest(RequestModel):
    # القيمة الافتراضية True جزء من عقد الواجهة القديم؛ الحقول الزائدة تظل مرفوضة.
    is_authorized: bool = Field(
        True,
        description="حالة الصلاحية المطلوبة (True للضوء الأخضر، False للإيقاف)",
    )

class AdminInventoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    product_name: str
    # الكميات الإجمالية بالحبات (لتوافق العقد القديم)
    starting_quantity: int
    sold_quantity: int
    remaining_quantity: int
    packs_per_carton: int

    # +++ الدرع الرقابي: كميات مفصلة للمشرف (كراتين وحبات فرط) لنسف تآكل الكسور +++
    starting_cartons: int = 0
    starting_loose_packs: int = 0
    sold_cartons: int = 0
    sold_loose_packs: int = 0
    remaining_cartons: int = 0
    remaining_loose_packs: int = 0

class AdminSessionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    session_id: int
    driver_name: str
    start_time: Optional[str] = None
    is_authorized_to_sell: bool
    is_on_break: bool
    # +++ الكي الجراحي: السماح للباك-إند بتمرير رقم السيارة للداشبورد +++
    vehicle_label: Optional[str] = "بدون سيارة"

class AdminFinancials(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    expected_cash_in_hand: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    cash_from_sales: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    cash_from_debts: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"

# +++ الدرع المحاسبي: كلاس بيانات العينات للمحاسب +++
class AdminSampleItem(BaseModel):
    shop_name: str
    product_name: str
    sample_quantity_cartons: int
    sample_quantity_packs: int
    reason: Optional[str] = ""

class AdminVisitsInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    completed_total: int = 0
    successful_sales: int = 0
    pending_remaining: int = 0

class AdminSettlementInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    driver_name: str
    status: str
    financials: AdminFinancials
    visits: AdminVisitsInfo
    inventory: List[AdminInventoryItem] = Field(default_factory=list)

class AdminDashboardDriverResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    session: AdminSessionInfo
    settlement: AdminSettlementInfo

class SessionSettlementReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    driver_name: str
    session_date: Optional[str] = None
    status: str
    financials: AdminFinancials
    visits: AdminVisitsInfo
    inventory: List[AdminInventoryItem] = Field(default_factory=list)
    # +++ كشف العينات التفصيلي للمحاسب +++
    samples_given: List[AdminSampleItem] = Field(default_factory=list)

    @field_validator('session_date', mode='before')
    @classmethod
    def format_date(cls, v):
        # توحيد صيغة التاريخ لمنع انهيار الـ React
        if hasattr(v, 'isoformat'): return v.isoformat()
        return str(v) if v else None

# +++ دروع التسوية المالية (محكمة المندوب) +++
class JardItemInput(RequestModel):
    product_id: PositiveDbInt
    actual: NonNegativeDbInt = Field(..., description="الجرد الفعلي بالحبات")


class SettleSessionRequest(RequestModel):
    # مبلغ التسوية قرار محاسبي صريح؛ غيابه أو إرساله فارغاً لا يتحول إلى صفر بصمت.
    actual_cash: RequiredMoneyInput
    inventory_jard: List[JardItemInput] = Field(default_factory=list, max_length=5000)
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, v: Any) -> Optional[str]:
        return _optional_text(v)


class SettleSessionResponse(BaseModel):
    message: str
    cash_difference: Annotated[str, BeforeValidator(clean_finance_str)]
    is_settled: bool

class DispatchZoneResponse(BaseModel):
    id: str
    name: str
    visitDay: Optional[str] = ""
    startDate: Optional[str] = ""
    frequency: Optional[str] = ""
    scheduleStatus: str
    shopsCount: int

class DispatchDriverResponse(BaseModel):
    id: str
    name: str

class DispatchVehicleResponse(BaseModel):
    id: str
    label: str

class DispatchProductResponse(BaseModel):
    id: str
    name: str

class DispatchInitResponse(BaseModel):
    zones: List[DispatchZoneResponse]
    drivers: List[DispatchDriverResponse]
    vehicles: List[DispatchVehicleResponse]
    products: List[DispatchProductResponse]

class DispatchRouteRequest(RequestModel):
    zone_id: PositiveDbInt
    driver_id: PositiveDbInt
    vehicle_id: PositiveDbInt
    # Final model requires an explicit source warehouse; never infer "first active warehouse".
    source_location_id: PositiveDbInt
    # Legacy React wire shape is preserved, but keys/values are now validated and normalized.
    inventory: Dict[str, NonNegativeDbInt] = Field(default_factory=dict, max_length=5000)

    @field_validator("inventory", mode="before")
    @classmethod
    def validate_inventory_map(cls, v: Any) -> Dict[str, Any]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("inventory يجب أن يكون قاموس product_id -> target cartons.")
        out: Dict[str, Any] = {}
        for raw_key, raw_value in v.items():
            product_id = positive_db_int_input(raw_key)
            key = str(product_id)
            if key in out:
                raise ValueError("يوجد product_id مكرر في خطة التحميل.")
            out[key] = raw_value
        return out


class VehicleInventoryItemResponse(BaseModel):
    product_id: str
    product_name: str
    current_quantity: int
    current_loose_packs: int = 0

class RouteLiveInventoryItemResponse(BaseModel):
    product_id: str
    product_name: str
    current_cartons: int
    current_packs: int

class InventoryAdjustmentDelta(RequestModel):
    product_id: PositiveDbInt
    delta_cartons: SignedDbInt

    @model_validator(mode="after")
    def reject_zero_delta(self) -> "InventoryAdjustmentDelta":
        if self.delta_cartons == 0:
            raise ValueError("delta_cartons لا يجوز أن يكون صفراً.")
        return self


class AdjustRouteInventoryRequest(RequestModel):
    deltas: List[InventoryAdjustmentDelta] = Field(
        ..., min_length=1, max_length=5000, description="قائمة بالتعديلات المطلوبة"
    )

    @model_validator(mode="after")
    def reject_duplicate_products(self) -> "AdjustRouteInventoryRequest":
        ids = [item.product_id for item in self.deltas]
        if len(ids) != len(set(ids)):
            raise ValueError("لا يجوز تكرار نفس المنتج في تعديلات المسار.")
        return self


class RouteTransferResponse(BaseModel):
    transfer_id: int
    product_name: str
    delta_cartons: int
    delta_packs: int  # +++ إرجاع الفراطة المفقودة (بنفس اسم الفلاسك الأصلي) +++
    status: str
    created_at: Optional[str] = None
    batch_id: str

class DispatchShopResponse(BaseModel):
    id: str
    name: str
    owner: Optional[str] = ""
    phone: Optional[str] = ""
    mapLink: Optional[str] = ""
    zoneId: Optional[str] = ""
    initialDebt: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    maxDebtLimit: Annotated[str, BeforeValidator(clean_finance_str)] = "0.0"
    sequence: Optional[int] = 999
    archived: bool

class BulkUpdateShopItem(RequestModel):
    id: str  # React may send "s12"; normalize/validate without losing wire compatibility.
    zoneId: Optional[str] = None
    sequence: Optional[Union[str, int]] = None
    archived: Optional[bool] = None

    @field_validator("id", mode="before")
    @classmethod
    def validate_shop_id(cls, v: Any) -> str:
        value = _required_text(v)
        normalized = value[1:] if value.lower().startswith("s") else value
        return str(positive_db_int_input(normalized))

    @field_validator("zoneId", mode="before")
    @classmethod
    def validate_zone_id(cls, v: Any) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return str(positive_db_int_input(v))

    @field_validator("sequence", mode="before")
    @classmethod
    def validate_sequence(cls, v: Any) -> Optional[int]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return _strict_db_int(v, minimum=0)

    @model_validator(mode="after")
    def require_a_change(self) -> "BulkUpdateShopItem":
        if self.zoneId is None and self.sequence is None and self.archived is None:
            raise ValueError("يجب إرسال تغيير واحد على الأقل للمحل.")
        return self


class AdminAddShopRequest(RequestModel):
    name: str = Field(..., min_length=2, max_length=150)
    owner: Optional[str] = Field("", max_length=100)
    phone: Optional[str] = Field("", max_length=20)
    mapLink: Optional[str] = Field("", max_length=500)
    zoneId: PositiveDbInt
    latitude: Latitude = None
    longitude: Longitude = None
    initialDebt: MoneyInput = Decimal("0.000")
    maxDebtLimit: MoneyInput = Decimal("0.000")
    sequence: Annotated[int, BeforeValidator(safe_int_input)] = 999
    force_save: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: Any) -> str:
        return _required_text(v)

    @field_validator("owner", "phone", "mapLink", mode="before")
    @classmethod
    def normalize_optional_text(cls, v: Any) -> str:
        return _optional_text(v) or ""


class ActiveRouteResponse(BaseModel):
    id: str
    zoneId: str
    zoneName: str
    driverId: Optional[str] = ""
    driverName: Optional[str] = ""
    vehicleId: Optional[str] = ""
    shopsRemaining: int
    status: str
    sessionEnded: bool

class UpdateRouteStatusRequest(RequestModel):
    status: Optional[Literal["active", "closed", "waiting", "postponed"]] = None
    driverId: OptionalPositiveDbInt = None
    vehicleId: OptionalPositiveDbInt = None
    inventory: Optional[Dict[str, NonNegativeDbInt]] = Field(
        default=None, max_length=5000
    )

    @field_validator("inventory", mode="before")
    @classmethod
    def validate_inventory_map(cls, v: Any) -> Optional[Dict[str, Any]]:
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("inventory يجب أن يكون قاموساً.")
        out: Dict[str, Any] = {}
        for raw_key, raw_value in v.items():
            key = str(positive_db_int_input(raw_key))
            if key in out:
                raise ValueError("يوجد product_id مكرر في خطة التحميل.")
            out[key] = raw_value
        return out

    @model_validator(mode="after")
    def require_update(self) -> "UpdateRouteStatusRequest":
        if (
            self.status is None
            and self.driverId is None
            and self.vehicleId is None
            and not self.inventory
        ):
            raise ValueError("يجب إرسال تغيير فعلي واحد على الأقل لتحديث المسار.")
        return self


class AddZoneRequest(RequestModel):
    name: str = Field(..., min_length=2, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: Any) -> str:
        return _required_text(v)


class UpdateZoneRequest(RequestModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    frequency: Optional[Literal["weekly", "monthly", "custom"]] = None
    visitDay: Optional[str] = Field(None, max_length=20)
    startDate: Optional[date] = None

    @field_validator("name", "visitDay", mode="before")
    @classmethod
    def normalize_text(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    @model_validator(mode="after")
    def require_update(self) -> "UpdateZoneRequest":
        if (
            self.name is None
            and self.frequency is None
            and self.visitDay is None
            and self.startDate is None
        ):
            raise ValueError("يجب إرسال حقل واحد على الأقل لتحديث المنطقة.")
        return self


class ArchivedZoneResponse(BaseModel):
    id: str
    name: str

class EditShopDetailsRequest(RequestModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    owner: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    mapLink: Optional[str] = Field(None, max_length=500)
    zoneId: OptionalPositiveDbInt = None
    max_debt_limit: OptionalMoneyInput = Field(
        default=None,
        validation_alias=AliasChoices("maxDebtLimit", "max_debt_limit"),
    )
    initial_debt: OptionalMoneyInput = Field(
        default=None,
        validation_alias=AliasChoices("initialDebt", "initial_debt"),
    )

    @field_validator("name", "owner", "phone", "mapLink", mode="before")
    @classmethod
    def normalize_text(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    @model_validator(mode="after")
    def require_update(self) -> "EditShopDetailsRequest":
        if all(
            value is None
            for value in (
                self.name,
                self.owner,
                self.phone,
                self.mapLink,
                self.zoneId,
                self.max_debt_limit,
                self.initial_debt,
            )
        ):
            raise ValueError("يجب إرسال حقل واحد على الأقل لتعديل المحل.")
        return self


class ShortageResponseItem(BaseModel):
    id: str
    zoneId: str
    zoneName: str
    shopId: str
    shopName: str
    driverId: Optional[str] = ""
    driverName: Optional[str] = ""
    productName: str
    quantity: int
    status: str
    waitTime: Optional[str] = None
    createdAt: Optional[str] = None

class CreateShortageItem(RequestModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    shopId: PositiveDbInt
    zoneId: PositiveDbInt
    product_variant_id: PositiveDbInt = Field(..., alias="productId")
    productName: Optional[str] = Field(None, max_length=200)
    driverId: OptionalPositiveDbInt = None
    quantity: PositiveDbInt = 1

    @field_validator("productName", mode="before")
    @classmethod
    def normalize_product_name(cls, v: Any) -> Optional[str]:
        return _optional_text(v)


class BulkImportShopItem(RequestModel):
    name: str = Field(..., min_length=2, max_length=150)
    owner: Optional[str] = Field("", max_length=100)
    phone: Optional[str] = Field("", max_length=20)
    mapLink: Optional[str] = Field("", max_length=500)
    initialDebt: MoneyInput = Decimal("0.000")
    sequence: Annotated[int, BeforeValidator(safe_int_input)] = 999

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: Any) -> str:
        return _required_text(v)

    @field_validator("owner", "phone", "mapLink", mode="before")
    @classmethod
    def normalize_optional_text(cls, v: Any) -> str:
        return _optional_text(v) or ""


class BulkImportRequest(RequestModel):
    zoneId: PositiveDbInt
    fileName: Optional[str] = Field("استيراد غير معروف", max_length=255)
    shops: List[BulkImportShopItem] = Field(..., min_length=1, max_length=10000)

    @field_validator("fileName", mode="before")
    @classmethod
    def normalize_file_name(cls, v: Any) -> str:
        return _optional_text(v) or "استيراد غير معروف"


class InboundItemRequest(RequestModel):
    """Legacy inbound wire item kept only for compatibility; unified inbound uses InboundBatchItem."""
    product_variant_id: PositiveDbInt
    quantity_packs: NonNegativeDbInt

# ==========================================
# 9. دروع المستودع المركزي (Warehouse)
# ==========================================
class WarehouseInboundRequest(RequestModel):
    """Legacy inbound envelope; kept strict while batch-aware UpgradedInboundRequest is the target contract."""
    items: List[InboundItemRequest] = Field(
        ..., min_length=1, max_length=5000, description="قائمة الأصناف المستلمة"
    )
    reference_id: Optional[str] = Field("بدون فاتورة", max_length=100)
    notes: Optional[str] = Field("", max_length=4000)

    @field_validator("reference_id", "notes", mode="before")
    @classmethod
    def normalize_text(cls, v: Any) -> Optional[str]:
        return _optional_text(v)


class ToggleLockRequest(RequestModel):
    status: Literal["AUDIT_LOCK", "ACTIVE"]

class WarehouseAlertItem(BaseModel):
    product_variant_id: int
    product_name: str
    current_total_packs: int
    min_threshold_packs: int

class WarehouseInventoryItem(BaseModel):
    id: int
    name: str
    sku: Optional[str] = None
    packs_per_carton: int
    available_packs: int
    reserved_packs: int
    total_packs: int
    damaged_packs: int
    available_cartons: int
    available_loose_packs: int
    min_threshold: int

class WarehouseLedgerItem(BaseModel):
    id: int
    product_name: str
    packs_per_carton: int
    type: str
    quantity_packs: int
    balance_before: Optional[int] = None
    balance_after: Optional[int] = None
    admin_name: str
    reference: Optional[str] = None
    notes: Optional[str] = None
    date: str

class WarehouseStatusResponse(BaseModel):
    status: str

class SimpleProductVariantItem(BaseModel):
    id: int
    name: str
    packs_per_carton: int

class AddProductVariantRequest(RequestModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    variant_name: str = Field(..., min_length=2, max_length=200, description="اسم المنتج")
    sku: Optional[str] = Field(None, max_length=100)
    price_per_carton: RequiredMoneyInput
    packs_per_carton: PositiveDbInt = Field(..., description="عدد الحبات في الكرتونة")
    price_per_pack: OptionalMoneyInput = None
    min_threshold_packs: Optional[NonNegativeDbInt] = Field(
        0, description="الحد الأدنى لإنذار النواقص (بالحبات)"
    )
    default_max_samples_per_day: Optional[NonNegativeDbInt] = Field(
        0,
        alias="max_samples",
        description="الحد الأقصى للعينات المجانية يومياً",
    )

    @field_validator("variant_name", mode="before")
    @classmethod
    def normalize_name(cls, v: Any) -> str:
        return _required_text(v)

    @field_validator("sku", mode="before")
    @classmethod
    def normalize_sku(cls, v: Any) -> Optional[str]:
        return _optional_text(v)


class AdjustWarehouseEntryRequest(RequestModel):
    password: str = Field(..., description="كلمة مرور المشرف للتأكيد")
    new_total_packs: NonNegativeDbInt = Field(
        ..., description="الصافي الجديد المطلوب للكمية (بالحبات)"
    )
    notes: Optional[str] = Field("تعديل خطأ إدخال", max_length=2000)

    @field_validator("password", mode="before")
    @classmethod
    def validate_password(cls, v: Any) -> str:
        return _bcrypt_password(v)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, v: Any) -> Optional[str]:
        return _optional_text(v)


# =================================================================================
# [المرحلة 3 و 4 و 5] Pydantic Schemas (المحرك الموحد ودعم الدفعات)
# =================================================================================
class InboundBatchItem(RequestModel):
    product_variant_id: PositiveDbInt
    quantity_packs: PositiveDbInt
    batch_number: str = Field(..., min_length=1, max_length=100)
    production_date: Optional[date] = None
    expiry_date: date

    @field_validator("batch_number", mode="before")
    @classmethod
    def normalize_batch_number(cls, v: Any) -> str:
        return _required_text(v)

    @model_validator(mode="after")
    def validate_dates(self) -> "InboundBatchItem":
        if self.production_date is not None and self.production_date > self.expiry_date:
            raise ValueError("تاريخ الإنتاج لا يجوز أن يكون بعد تاريخ الصلاحية.")
        return self


class UpgradedInboundRequest(RequestModel):
    location_id: PositiveDbInt
    reference_id: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=4000)
    items: List[InboundBatchItem] = Field(..., min_length=1, max_length=5000)

    @field_validator("reference_id", "notes", mode="before")
    @classmethod
    def normalize_text(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    @model_validator(mode="after")
    def validate_duplicate_batch_metadata(self) -> "UpgradedInboundRequest":
        seen: Dict[tuple[int, str], tuple[Optional[date], date]] = {}
        for item in self.items:
            key = (item.product_variant_id, item.batch_number)
            metadata = (item.production_date, item.expiry_date)
            if key in seen:
                if seen[key] != metadata:
                    raise ValueError(
                        "نفس رقم الدفعة للصنف لا يجوز أن يظهر ببيانات إنتاج/صلاحية متعارضة."
                    )
                raise ValueError(
                    "لا يجوز تكرار نفس الصنف ورقم الدفعة في فاتورة الاستلام؛ اجمع الكمية في سطر واحد."
                )
            seen[key] = metadata
        return self


class UnifiedTransferItem(RequestModel):
    product_variant_id: PositiveDbInt
    quantity: PositiveDbInt
    is_fefo_override: bool = False
    override_batch_id: OptionalPositiveDbInt = None
    override_reason_id: OptionalPositiveDbInt = None

    @model_validator(mode="after")
    def validate_override_contract(self) -> "UnifiedTransferItem":
        if self.is_fefo_override:
            if self.override_batch_id is None or self.override_reason_id is None:
                raise ValueError(
                    "تجاوز FEFO يتطلب override_batch_id و override_reason_id."
                )
        elif self.override_batch_id is not None or self.override_reason_id is not None:
            raise ValueError(
                "override_batch_id/override_reason_id لا يسمح بهما بدون is_fefo_override=true."
            )
        return self


class UnifiedDispatchRequest(RequestModel):
    source_location_id: PositiveDbInt
    destination_location_id: PositiveDbInt
    items: List[UnifiedTransferItem] = Field(..., min_length=1, max_length=5000)
    notes: Optional[str] = Field("", max_length=4000)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, v: Any) -> str:
        return _optional_text(v) or ""

    @model_validator(mode="after")
    def validate_transfer_shape(self) -> "UnifiedDispatchRequest":
        if self.source_location_id == self.destination_location_id:
            raise ValueError("المصدر والوجهة يجب أن يكونا مختلفين.")

        seen = set()
        modes_by_product: Dict[int, set[bool]] = {}
        for item in self.items:
            key = (item.product_variant_id, item.override_batch_id)
            if key in seen:
                raise ValueError(
                    "لا يجوز تكرار نفس الصنف/الدفعة في طلب الحوالة؛ اجمع الكمية في سطر واحد."
                )
            seen.add(key)
            modes_by_product.setdefault(item.product_variant_id, set()).add(
                item.is_fefo_override
            )

        if any(len(modes) > 1 for modes in modes_by_product.values()):
            raise ValueError(
                "لا يجوز خلط FEFO التلقائي وتجاوز FEFO لنفس المنتج في حوالة واحدة."
            )
        return self


class UnifiedReceiveRequest(RequestModel):
    transfer_header_id: PositiveDbInt
    destination_location_id: PositiveDbInt



class UnifiedStocktakeStartRequest(RequestModel):
    location_id: PositiveDbInt
    stocktake_type: Literal["FULL_COUNT", "CYCLE_COUNT", "VEHICLE_RECON"]
    product_variant_id: OptionalPositiveDbInt = None
    batch_id: OptionalPositiveDbInt = None
    related_work_session_id: OptionalPositiveDbInt = None
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    @model_validator(mode="after")
    def validate_scope(self) -> "UnifiedStocktakeStartRequest":
        if self.stocktake_type == "CYCLE_COUNT":
            if self.product_variant_id is None:
                raise ValueError("CYCLE_COUNT يتطلب product_variant_id.")
            if self.related_work_session_id is not None:
                raise ValueError(
                    "related_work_session_id مخصص حصراً لـ VEHICLE_RECON."
                )
        elif self.stocktake_type == "VEHICLE_RECON":
            if self.product_variant_id is not None or self.batch_id is not None:
                raise ValueError(
                    "VEHICLE_RECON لا يقبل product_variant_id أو batch_id."
                )
            if self.related_work_session_id is None:
                raise ValueError(
                    "VEHICLE_RECON يجب أن يرتبط بجلسة العمل التي تتم تسويتها."
                )
        else:  # FULL_COUNT
            if self.product_variant_id is not None or self.batch_id is not None:
                raise ValueError(
                    "FULL_COUNT يجرد الموقع كاملاً ولا يقبل product_variant_id أو batch_id."
                )
            if self.related_work_session_id is not None:
                raise ValueError(
                    "related_work_session_id مخصص حصراً لـ VEHICLE_RECON."
                )

        if self.batch_id is not None and self.product_variant_id is None:
            raise ValueError("batch_id يتطلب product_variant_id.")
        return self


class StocktakeCountItem(RequestModel):
    product_variant_id: PositiveDbInt
    batch_id: PositiveDbInt
    stock_status: Literal["AVAILABLE", "DAMAGED"]
    actual_quantity: NonNegativeDbInt


class UnifiedStocktakeCountRequest(RequestModel):
    items: List[StocktakeCountItem] = Field(..., min_length=1, max_length=10000)
    notes: Optional[str] = Field(None, max_length=4000)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, v: Any) -> Optional[str]:
        return _optional_text(v)

    @model_validator(mode="after")
    def reject_duplicate_lines(self) -> "UnifiedStocktakeCountRequest":
        keys = [
            (item.product_variant_id, item.batch_id, item.stock_status)
            for item in self.items
        ]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "لا يجوز تكرار نفس الصنف/الدفعة/حالة المخزون في محاولة العد."
            )
        return self



class StocktakeRecountRequest(RequestModel):
    # يثبت أي محاولة راجعها المشرف قبل تفويض إعادة العد ويمنع Recount على نسخة أحدث بالخطأ.
    count_attempt_id: PositiveDbInt
    reason: str = Field(..., min_length=5, max_length=500)
    authorizer_username: str = Field(..., min_length=1, max_length=80)
    authorizer_password: str

    @field_validator("reason", "authorizer_username", mode="before")
    @classmethod
    def normalize_text(cls, v: Any) -> str:
        return _required_text(v)

    @field_validator("authorizer_password", mode="before")
    @classmethod
    def validate_password(cls, v: Any) -> str:
        return _bcrypt_password(v)



class StocktakeApprovalRequest(RequestModel):
    # Optimistic concurrency: الاعتماد يجب أن يخص محاولة العد التي شاهدها المشرف فعلياً.
    count_attempt_id: PositiveDbInt
    password: str
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("password", mode="before")
    @classmethod
    def validate_password(cls, v: Any) -> str:
        return _bcrypt_password(v)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, v: Any) -> Optional[str]:
        return _optional_text(v)



class StocktakeCancelRequest(RequestModel):
    password: str
    reason: str = Field(..., min_length=5, max_length=500)

    @field_validator("password", mode="before")
    @classmethod
    def validate_password(cls, v: Any) -> str:
        return _bcrypt_password(v)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, v: Any) -> str:
        return _required_text(v)
