from pydantic import BaseModel, Field, ConfigDict, model_validator, AliasChoices, field_validator
from pydantic.functional_validators import BeforeValidator
from typing import Optional, List, Any, Literal, Annotated, Dict, Union
from datetime import datetime, timezone, date
from decimal import Decimal

# ==========================================
# 0. الدروع الفولاذية (دوال التطهير المساعدة - يجب أن تكون في الأعلى دائماً)
# ==========================================
def clean_finance_str(v) -> str:
    if v is None or str(v).strip() == "": 
        return "0.0"
    return str(v)

def safe_finance_float(v) -> float:
    if v is None: return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

def clean_null_string(v) -> str:
    return str(v) if v else ""

def clean_null_price(v) -> str: # +++ الدرع المالي للبيسة العُمانية: إرجاع نص للحفاظ على الـ Decimal في JSON +++
    if v is None or str(v).strip() == "": return "0.000"
    try:
        return str(Decimal(str(v)))
    except (Exception):
        return "0.000"

def clean_zero_packs(v) -> int:
    if v is None: return 1 # +++ العبث بالديفولت 50 يدمر المنتجات الفردية، 1 هو الآمن +++
    try:
        val = int(float(v))
        return val if val > 0 else 1
    except (ValueError, TypeError):
        return 1

def safe_decimal_input(v: Any) -> Decimal:
    if v is None or str(v).strip() == "": return Decimal('0.0')
    try: 
        dec = Decimal(str(v).strip())
        if not dec.is_finite(): raise ValueError("قيمة مالية غير صالحة (NaN/Infinity)")
        return dec
    except Exception: raise ValueError("قيمة مالية غير صالحة")

def safe_optional_decimal(v: Any) -> Optional[Decimal]:
    if v is None or str(v).strip() == "": return None
    try: 
        dec = Decimal(str(v).strip())
        if not dec.is_finite(): raise ValueError("قيمة مالية غير صالحة (NaN/Infinity)")
        return dec
    except Exception: raise ValueError("قيمة مالية غير صالحة")

def safe_int_input(v: Any) -> int:
    if v is None or str(v).strip() == "": return 999
    try: return int(float(str(v).strip()))
    except Exception: raise ValueError("قيمة رقمية غير صالحة")

# ==========================================
# 1. دروع الردود العامة (Generic Responses)
# ==========================================
class MessageResponse(BaseModel):
    message: str

# ==========================================
# 2. دروع المصادقة وتسجيل الدخول (Auth)
# ==========================================
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, description="اسم المستخدم")
    password: str = Field(..., min_length=4, description="كلمة المرور")

class LoginResponse(BaseModel):
    message: str
    token: str
    refresh_token: str
    driver_id: int
    driver_name: str
    is_admin: bool

# ==========================================
# 3. دروع العمليات المشتركة والمنتجات الفرعية (Shared)
# ==========================================
class ShopBase(BaseModel):
    name: str = Field(..., min_length=2, description="اسم المحل إجباري")
    phone_number: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_link: Optional[str] = None
    notes: Optional[str] = None

class ShopCreate(ShopBase):
    pass

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

class TransferResponseRequest(BaseModel):
    response: Literal['accepted', 'rejected'] = Field(..., description="رد المندوب")
    reason: Optional[str] = Field(None, description="سبب الرفض إن وجد")

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
class SessionStartRequest(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class BreakToggleRequest(BaseModel):
    action: Literal["start", "end"]

class BatchTransferItem(BaseModel):
    transfer_id: int
    status: Literal['accepted', 'rejected']

class BatchTransferResponseRequest(BaseModel):
    transfers: List[BatchTransferItem]

class PendingTransferItem(BaseModel):
    real_transfer_id: int
    product_name: str
    delta_cartons: int
    delta_packs: int

class PendingBatchResponse(BaseModel):
    transfer_id: str
    created_at: Optional[str]
    items: List[PendingTransferItem]

class AddShopRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=2, max_length=150)
    phone_number: str = Field(..., min_length=5, max_length=20)
    address: Optional[str] = Field(None, max_length=500)
    contact_person: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None
    location_link: Optional[str] = Field(None, max_length=500)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator('name', 'phone_number', 'address', 'contact_person', 'notes', 'location_link', mode='before')
    @classmethod
    def clean_strings(cls, v):
        if isinstance(v, str):
            cleaned = v.strip()
            return cleaned if cleaned else None
        return v

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
    returns: List[VisitReturnResponse] = []
    visit_timestamp: Optional[str] = None

    @field_validator('visit_timestamp', mode='before')
    @classmethod
    def format_time(cls, v):
        if isinstance(v, datetime): return v.replace(tzinfo=timezone.utc).isoformat()
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
class VisitItemInput(BaseModel):
    # +++ تم نسف كارثة النسخ واللصق التي كانت ستدمر الـ API +++
    product_variant_id: int
    quantity: int = Field(0, ge=0)
    packs_quantity: int = Field(0, ge=0)
    bonus_quantity: int = Field(0, ge=0)
    sample_quantity: int = Field(0, ge=0, validation_alias=AliasChoices('sample_quantity', 'sample_cartons'))
    sample_packs_quantity: int = Field(0, ge=0, validation_alias=AliasChoices('sample_packs_quantity', 'sample_packs'))
    sample_reason: Optional[str] = None

    @field_validator('quantity', 'packs_quantity', 'bonus_quantity', 'sample_quantity', 'sample_packs_quantity', mode='before')
    @classmethod
    def clean_empty_ints(cls, v: Any) -> int:
        if v == "" or v is None or str(v).strip() == "": return 0
        return int(v)

    # +++ الدرع الجنائي الشامل (Zero Trust): حماية العينات (كراتين وفراطة) من التهريب بدون سبب +++
    @model_validator(mode='after')
    def validate_samples_and_bonus(self) -> 'VisitItemInput':
        total_samples = self.sample_quantity + getattr(self, 'sample_packs_quantity', 0)
        if total_samples > 0 and not self.sample_reason:
            raise ValueError(f"مرفوض أمنياً: يجب تحديد سبب مقنع لصرف عينات للمنتج رقم {self.product_variant_id}")
        if total_samples == 0:
            self.sample_reason = None
        return self

class VisitReturnInput(BaseModel):
    product_variant_id: int
    quantity: int = Field(0, ge=0, validation_alias=AliasChoices('quantity', 'cartons'))
    packs_quantity: int = Field(0, ge=0, validation_alias=AliasChoices('packs_quantity', 'packs'))
    # +++ النسف المعماري لثغرة طباعة الأموال: إعدام حالة 'Sellable' تماماً لتطابق سياسة الشركة (لا استرجاع، استبدال تالف فقط) +++
    return_type: Literal['Expired', 'Damaged', 'Factory_Defect'] = Field('Damaged')
    reason: Optional[str] = None

    @field_validator('quantity', 'packs_quantity', mode='before')
    @classmethod
    def clean_empty_ints(cls, v: Any) -> int:
        if v == "" or v is None or str(v).strip() == "": return 0
        return int(v)

    @field_validator('return_type', mode='before')
    @classmethod
    def enforce_zero_trust(cls, v: Any) -> str:
        if v is None or str(v).strip() == "": return 'Damaged'
        return v

class VisitUpdateRequest(BaseModel):
    outcome: Literal['Sale', 'NoSale', 'Postponed']
    notes: Optional[str] = None
    is_emergency: bool = False
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    cash_collected: Decimal = Field(default=Decimal('0.00'), ge=0)
    debt_paid: Decimal = Field(default=Decimal('0.00'), ge=0)
    cart_items: List[VisitItemInput] = Field(default_factory=list)
    returns: List[VisitReturnInput] = Field(default_factory=list)

    @field_validator('cash_collected', 'debt_paid', mode='before')
    @classmethod
    def clean_empty_decimals(cls, v: Any) -> Decimal:
        if v == "" or v is None or str(v).strip() == "": return Decimal('0.00')
        try:
            dec = Decimal(str(v))
            if not dec.is_finite(): raise ValueError("قيمة غير صالحة")
            return dec
        except Exception:
            raise ValueError("قيمة غير صالحة")

    @model_validator(mode='after')
    def validate_visit_logic(self) -> 'VisitUpdateRequest':
        if self.outcome == 'Sale':
            total_items_qty = sum(i.quantity + i.packs_quantity + i.bonus_quantity + i.sample_quantity + i.sample_packs_quantity for i in self.cart_items)
            total_returns_qty = sum(r.quantity + r.packs_quantity for r in self.returns)
            has_real_activity = (total_items_qty > 0 or total_returns_qty > 0 or self.cash_collected > Decimal('0') or self.debt_paid > Decimal('0'))
            if not has_real_activity:
                raise ValueError("لا يمكن تسجيل 'بيع' بمنتجات صفرية بدون تحصيل مالي.")
        elif self.outcome == 'NoSale':
            # +++ الدرع المعماري لحل الـ 422: السماح بالـ NoSale بدون ملاحظات إذا كان المندوب قد أدخل عينات أو مرتجعات (لأنها تعتبر مبرراً بحد ذاتها) +++
            total_samples = sum(i.sample_quantity + getattr(i, 'sample_packs_quantity', 0) for i in self.cart_items)
            total_returns = sum(r.quantity + r.packs_quantity for r in self.returns)
            
            if total_samples == 0 and total_returns == 0:
                if not self.notes or not self.notes.strip():
                    raise ValueError("يجب كتابة سبب عدم البيع في الملاحظات.")
        elif self.outcome == 'Postponed':
            self.cash_collected = Decimal('0.00')
            self.debt_paid = Decimal('0.00')
            self.cart_items = []
            self.returns = []
        return self

# +++ سكيما الدالة القادمة (Active Session) +++
class ActiveSessionResponse(BaseModel):
    active_session_found: bool
    session_id: Optional[int] = None
    start_time: Optional[str] = None

# ==========================================
# 8. دروع لوحة التحكم والإدارة (Admin / Dispatch)
# ==========================================
class AuthorizeSessionRequest(BaseModel):
    # +++ النسف المعماري لفخ الـ 422: إعادة القيمة الافتراضية True للوفاء بعقد الواجهة القديم +++
    is_authorized: bool = Field(True, description="حالة الصلاحية المطلوبة (True للضوء الأخضر، False للإيقاف)")

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
class JardItemInput(BaseModel):
    product_id: int
    actual: int = Field(..., ge=0, description="الجرد الفعلي بالحبات")

    @field_validator('actual', mode='before')
    @classmethod
    def clean_empty_ints(cls, v: Any) -> int:
        if v == "" or v is None or str(v).strip() == "": return 0
        return int(v)

class SettleSessionRequest(BaseModel):
    actual_cash: Decimal = Field(default=Decimal('0.00'), ge=0)
    inventory_jard: List[JardItemInput] = Field(default_factory=list)
    notes: Annotated[str, BeforeValidator(clean_null_string)] = ""

    @field_validator('actual_cash', mode='before')
    @classmethod
    def clean_empty_decimals(cls, v: Any) -> Decimal:
        if v == "" or v is None or str(v).strip() == "": return Decimal('0.00')
        try:
            dec = Decimal(str(v))
            if not dec.is_finite(): raise ValueError("قيمة غير صالحة")
            return dec
        except Exception:
            raise ValueError("قيمة غير صالحة")

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

class DispatchRouteRequest(BaseModel):
    zone_id: int
    driver_id: int
    vehicle_id: int
    # استقبال الجرد كقاموس نصوص (للتوافق مع React) وسيتم تنظيفه داخلياً
    inventory: Optional[Dict[str, Any]] = Field(default_factory=dict)

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

class InventoryAdjustmentDelta(BaseModel):
    product_id: int
    delta_cartons: int

class AdjustRouteInventoryRequest(BaseModel):
    deltas: List[InventoryAdjustmentDelta] = Field(..., description="قائمة بالتعديلات المطلوبة")

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

class BulkUpdateShopItem(BaseModel):
    id: str # React يرسلها أحياناً كـ 's12'
    zoneId: Optional[str] = None
    sequence: Optional[Union[str, int]] = None
    archived: Optional[bool] = None

class AdminAddShopRequest(BaseModel):
    name: str
    owner: Optional[str] = ""
    phone: Optional[str] = ""
    mapLink: Optional[str] = ""
    zoneId: int
    # استقبال مرن جداً لحماية السيرفر من هجمات النصوص والفراغات
    latitude: Optional[Union[float, str]] = None
    longitude: Optional[Union[float, str]] = None
    # +++ سد ثغرة הـ Type Coercion: تحويل إجباري لـ Decimal قبل وصولها لـ SQLAlchemy +++
    initialDebt: Annotated[Decimal, BeforeValidator(safe_decimal_input)] = Decimal('0.0')
    maxDebtLimit: Annotated[Decimal, BeforeValidator(safe_decimal_input)] = Decimal('0.0')
    sequence: Annotated[int, BeforeValidator(safe_int_input)] = 999
    force_save: bool = False

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

class UpdateRouteStatusRequest(BaseModel):
    status: Optional[Literal['active', 'closed', 'waiting', 'postponed']] = None
    driverId: Optional[Union[int, str]] = None
    vehicleId: Optional[Union[int, str]] = None
    inventory: Optional[Dict[str, Any]] = None

class AddZoneRequest(BaseModel):
    name: str

class UpdateZoneRequest(BaseModel):
    name: Optional[str] = None
    frequency: Optional[str] = None
    visitDay: Optional[str] = None
    startDate: Optional[date] = None # Pydantic سيتكفل بتحويل 'YYYY-MM-DD' بأمان تام

class ArchivedZoneResponse(BaseModel):
    id: str
    name: str

class EditShopDetailsRequest(BaseModel):
    name: Optional[str] = None
    owner: Optional[str] = None
    phone: Optional[str] = None
    mapLink: Optional[str] = None
    zoneId: Optional[Union[int, str]] = None
    # +++ سد ثغرة الـ Pydantic Schizophrenia وتوحيد المخرجات لتطابق SQLAlchemy بسلاسة +++
    max_debt_limit: Annotated[Optional[Decimal], BeforeValidator(safe_optional_decimal)] = Field(default=None, validation_alias=AliasChoices('maxDebtLimit', 'max_debt_limit'))
    initial_debt: Annotated[Optional[Decimal], BeforeValidator(safe_optional_decimal)] = Field(default=None, validation_alias=AliasChoices('initialDebt', 'initial_debt'))

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

class CreateShortageItem(BaseModel):
    shopId: Union[int, str]
    zoneId: Union[int, str]
    productId: Optional[Union[int, str]] = None
    productName: Optional[str] = None
    driverId: Optional[Union[int, str]] = None
    quantity: int = Field(1, gt=0)

class BulkImportShopItem(BaseModel):
    name: Optional[str] = ""
    owner: Optional[str] = ""
    phone: Optional[str] = ""
    mapLink: Optional[str] = ""
    # +++ حماية ملفات الإكسيل من النصوص المكسورة +++
    initialDebt: Annotated[Decimal, BeforeValidator(safe_decimal_input)] = Decimal('0.0')
    sequence: Annotated[int, BeforeValidator(safe_int_input)] = 999

class BulkImportRequest(BaseModel):
    zoneId: int
    fileName: Optional[str] = "استيراد غير معروف"
    shops: List[BulkImportShopItem]

class InboundItemRequest(BaseModel):
    product_variant_id: int
    quantity_packs: int = Field(..., ge=0)

# ==========================================
# 9. دروع المستودع المركزي (Warehouse)
# ==========================================
class WarehouseInboundRequest(BaseModel):
    items: List[InboundItemRequest] = Field(..., description="قائمة الأصناف المستلمة")
    reference_id: Optional[str] = "بدون فاتورة"
    notes: Optional[str] = ""

class StocktakeItemRequest(BaseModel):
    product_variant_id: int
    actual_packs: int = Field(..., ge=0)

class WarehouseStocktakeRequest(BaseModel):
    items: List[StocktakeItemRequest] = Field(..., description="قائمة الأصناف المجرودة")
    notes: Optional[str] = "تسوية جرد يدوية"

class ToggleLockRequest(BaseModel):
    status: Literal['AUDIT_LOCK', 'ACTIVE']

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

class AddProductVariantRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True) # +++ درع الـ Alias لمنع كراش الـ Pydantic +++
    
    variant_name: str = Field(..., min_length=2, description="اسم المنتج")
    sku: Optional[str] = None
    # +++ حماية Pydantic V2: يجب أن يكون النوع Decimal صراحة لمنع فقدان الدقة +++
    price_per_carton: Decimal
    packs_per_carton: int = Field(..., gt=0, description="عدد الحبات في الكرتونة")
    price_per_pack: Optional[Decimal] = None
    min_threshold_packs: Optional[int] = Field(0, ge=0, description="الحد الأدنى لإنذار النواقص (بالحبات)")
    # +++ نسف الكارثة التشغيلية: استعادة سياسة العينات المفقودة مع Alias لامتصاص بيانات React +++
    default_max_samples_per_day: Optional[int] = Field(0, ge=0, alias="max_samples", description="الحد الأقصى للعينات المجانية يومياً")

    # +++ درع تنظيف الأسعار وحمايتها من الـ Decimal Crash و الـ NaN +++
    @field_validator('price_per_carton', 'price_per_pack', mode='before')
    @classmethod
    def clean_prices(cls, v: Any) -> Optional[Decimal]:
        if v == "" or v is None or str(v).strip() == "": return None
        try:
            dec = Decimal(str(v).strip())
            if not dec.is_finite(): raise ValueError("صيغة السعر غير صالحة.")
            return dec
        except Exception:
            raise ValueError("صيغة السعر غير صالحة.")

class AdjustWarehouseEntryRequest(BaseModel):
    password: str = Field(..., description="كلمة مرور المشرف للتأكيد")
    new_total_packs: int = Field(..., ge=0, description="الصافي الجديد المطلوب للكمية (بالحبات)")
    notes: Optional[str] = "تعديل خطأ إدخال"