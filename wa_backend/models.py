from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Numeric, Float, Text, ForeignKey, CheckConstraint, UniqueConstraint, Index, MetaData, text
from sqlalchemy.orm import relationship, declarative_base, backref
from datetime import datetime, timezone
from decimal import Decimal

convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

metadata = MetaData(naming_convention=convention)
Base = declarative_base(metadata=metadata)

# دالة مساعدة موحدة للوقت - المصدر الوحيد للحقيقة في كل الملف
# FIX ①: إزالة الـ timezone (offset-naive) لمنع كراش asyncpg مع جداول Postgres
def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# =================================================================================
# ① الإعدادات العامة للنظام
# =================================================================================
class SystemSetting(Base):
    __tablename__ = 'system_settings'
    id            = Column(Integer, primary_key=True)
    setting_key   = Column(String(50),  unique=True, nullable=False)
    setting_value = Column(String(100), nullable=False)
    description   = Column(String(200), nullable=True)


# =================================================================================
# ② التوزيع الجغرافي الهرمي: دولة → محافظة → منطقة
# الترتيب مهم: كل كلاس يعرَّف قبل من يشير إليه
# =================================================================================
class Country(Base):
    __tablename__ = 'countries'
    id   = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)

    governorates = relationship('Governorate', backref='country', lazy='raise')


class Governorate(Base):
    __tablename__ = 'governorates'
    __table_args__ = (
        UniqueConstraint('name', 'country_id', name='uq_governorate_name_per_country'),
    )
    id         = Column(Integer, primary_key=True)
    name       = Column(String(100), nullable=False)
    country_id = Column(Integer, ForeignKey('countries.id'), nullable=False)

    zones = relationship('Zone', backref='governorate', lazy='raise')


class Zone(Base):
    """
    المنطقة الجغرافية التي يغطيها المندوب.
    تحتوي على إعدادات الجدولة (أسبوعي، شهري، مخصص) لتنظيم
    مواعيد الزيارات الدورية.
    """
    __tablename__ = 'zones'
    __table_args__ = (
        UniqueConstraint('name', 'governorate_id', name='uq_zone_name_per_governorate'),
    )
    id              = Column(Integer, primary_key=True)
    name            = Column(String(100), nullable=False)
    governorate_id  = Column(Integer, ForeignKey('governorates.id', ondelete='SET NULL'), nullable=True)
    sequence_number = Column(Integer, nullable=True)   # ترتيب خطوط السير

    # حقول الجدولة
    schedule_frequency = Column(String(50),  nullable=True)  # weekly / monthly / custom
    visit_day          = Column(String(20),  nullable=True)  # Saturday / Sunday …
    start_date         = Column(Date,        nullable=True)
    custom_days        = Column(Integer,     nullable=True)  # عدد الأيام للجدولة المخصصة

    is_active = Column(Boolean, nullable=False, default=True)

    shops = relationship('Shop', backref='zone', lazy='raise')


# =================================================================================
# ③ المستخدمون (المندوبون والمسؤولون)
# ملاحظة معمارية: حالياً الأدوار داخل نفس الجدول (is_admin, can_allow_debt).
# هاد كافي للمرحلة الحالية، ولما نروح لـ SaaS نفصل جدول Roles مستقل.
# =================================================================================
class Driver(Base):
    __tablename__ = 'drivers'
    id            = Column(Integer, primary_key=True)
    username      = Column(String(80),  unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    full_name     = Column(String(120), nullable=False)
    phone_number  = Column(String(20),  nullable=True)
    is_active     = Column(Boolean,     nullable=False, default=True, server_default='true')
    is_admin      = Column(Boolean,     nullable=False, default=False, server_default='false')
    can_allow_debt  = Column(Boolean,       nullable=False, default=False, server_default='false')
    # +++ الدرع المحاسبي: حماية الدقة من تآكل الـ Float ومنع سقف الدين من الانقلاب لقيمة سالبة +++
    max_debt_limit  = Column(Numeric(12, 3), CheckConstraint('max_debt_limit >= 0', name='chk_driver_max_debt'), nullable=False, default=Decimal('0.000'), server_default='0.000')
    created_at      = Column(DateTime,      nullable=False, default=utc_now)  # FIX ①



# =================================================================================
# ④ المنتجات (Product → ProductVariant)
# =================================================================================
class Product(Base):
    __tablename__ = 'products'
    id         = Column(Integer, primary_key=True)
    base_name  = Column(String(150), nullable=False, unique=True)
    brand      = Column(String(100), nullable=True)
    category   = Column(String(100), nullable=True)
    created_at = Column(DateTime,   nullable=False, default=utc_now)  # FIX ①

    variants = relationship('ProductVariant', backref='product', lazy='raise')


class ProductVariant(Base):
    __tablename__ = 'product_variants'
    id         = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)

    variant_name    = Column(String(200), nullable=False)
    flavor          = Column(String(50),  nullable=True)
    size            = Column(String(50),  nullable=True)
    sku             = Column(String(100), nullable=True, unique=True)
    packs_per_carton = Column(Integer, CheckConstraint('packs_per_carton > 0', name='chk_packs_per_carton_positive'), nullable=False, default=50)
    price_per_carton = Column(Numeric(12, 3), nullable=False)
    price_per_pack   = Column(Numeric(12, 3), nullable=True)
    is_active        = Column(Boolean, nullable=False, default=True, server_default='true', index=True)
    default_max_samples_per_day = Column(Integer, nullable=False, default=0)


# =================================================================================
# ⑤ الأسطول والسيارات
# =================================================================================
class Vehicle(Base):
    __tablename__ = 'vehicles'
    id                 = Column(Integer, primary_key=True)
    plate_number       = Column(String(20), unique=True, nullable=False)
    vehicle_type       = Column(String(50), nullable=True)
    current_mileage    = Column(Integer,    nullable=False, default=0)
    next_oil_change    = Column(Integer,    nullable=True)
    license_expiry_date = Column(Date,      nullable=True)
    maintenance_status = Column(String(50), nullable=False, default='Active')  # Active | In_Maintenance
    is_active          = Column(Boolean,    nullable=False, default=True)


class VehicleLoad(Base):
    """
    مسودة الحمولة التي يجهزها أمين المستودع ليلاً.
    قيد الفرادة يمنع تكرار نفس المنتج على نفس السيارة.
    """
    __tablename__ = 'vehicle_loads'
    __table_args__ = (
        UniqueConstraint('vehicle_id', 'product_variant_id', name='uq_vehicle_variant_load'),
    )
    id                 = Column(Integer, primary_key=True)
    vehicle_id         = Column(Integer, ForeignKey('vehicles.id'),         nullable=False) # تم نسف الـ index المكرر لحماية الـ RAM
    product_variant_id = Column(Integer, ForeignKey('product_variants.id'), nullable=False)
    quantity           = Column(Integer, CheckConstraint('quantity >= 0', name='chk_vload_qty'), nullable=False, default=0)
    updated_at         = Column(DateTime, nullable=False, default=utc_now)  # FIX ①

    product_variant = relationship('ProductVariant', lazy='raise')


# =================================================================================
# ⑥ جلسات العمل والعهدة
# =================================================================================
class WorkSession(Base):
    __tablename__ = 'work_sessions'
    __table_args__ = (
        Index('ix_ws_driver_unsettled', 'driver_id', 'is_settled', 'end_time'),
    )
    id           = Column(Integer, primary_key=True)
    driver_id    = Column(Integer, ForeignKey('drivers.id'), nullable=False, index=True)
    start_time   = Column(DateTime, nullable=False, default=utc_now)           # FIX ①
    end_time     = Column(DateTime, nullable=True,  index=True)
    # +++ الكي الجراحي (Issue 3): توحيد الزمن (Naive UTC) لنسف تعارضات قاعدة البيانات +++
    session_date = Column(Date,     nullable=False, default=lambda: utc_now().date(), index=True)
    start_latitude  = Column(Numeric(10, 7), nullable=True)
    start_longitude = Column(Numeric(10, 7), nullable=True)

    is_authorized_to_sell = Column(Boolean,  nullable=False, default=False)
    break_start_time      = Column(DateTime, nullable=True)
    break_end_time        = Column(DateTime, nullable=True)
    is_settled            = Column(Boolean,  nullable=False, default=False, index=True)

    driver    = relationship('Driver', backref=backref('work_sessions', lazy='raise'))
    inventory = relationship('SessionInventory', backref='work_session', lazy='raise', cascade='all, delete-orphan')


class SessionInventory(Base):
    """
    العهدة الشخصية للمندوب خلال جلسة العمل.
    قيد الفرادة يمنع تكرار نفس المنتج في نفس الجلسة.
    """
    __tablename__ = 'session_inventory'
    __table_args__ = (
        UniqueConstraint('work_session_id', 'product_variant_id', name='uq_session_variant_inv'),
    )
    id                 = Column(Integer, primary_key=True)
    work_session_id    = Column(Integer, ForeignKey('work_sessions.id'),    nullable=False) # تمت إزالة الـ index المكرر بسبب الـ UniqueConstraint
    product_variant_id = Column(Integer, ForeignKey('product_variants.id'), nullable=False, index=True)
    
    # +++ النسف المعماري (حرج 3): فصل حمولة الصباح عن التعديلات لمنع تدمير تقارير الجرد +++
    starting_quantity          = Column(Integer, nullable=False, default=0)
    net_transfers              = Column(Integer, nullable=False, default=0) # موجب للحوالة المستلمة، سالب للحوالة المسحوبة
    current_remaining_quantity = Column(Integer, CheckConstraint('current_remaining_quantity >= 0', name='chk_positive_inventory'), nullable=False, default=0)

    product_variant = relationship('ProductVariant', lazy='raise')


# =================================================================================
# ⑦ المحلات
# =================================================================================
class Shop(Base):
    __tablename__ = 'shops'
    id             = Column(Integer, primary_key=True)
    name           = Column(String(150), nullable=False)
    address        = Column(Text,        nullable=True)
    latitude       = Column(Numeric(10, 7), nullable=True)
    longitude      = Column(Numeric(10, 7), nullable=True)
    phone_number   = Column(String(20),  nullable=True)
    contact_person = Column(String(100), nullable=True)
    zone_id        = Column(Integer, ForeignKey('zones.id', ondelete='SET NULL'),
                               nullable=True, index=True)
    # +++ النسف المعماري: حماية الـ Decimal، فرض server_default، وتطبيق سياسة (SET NULL) لحماية الداتابيز +++
    current_balance  = Column(Numeric(12, 3), CheckConstraint('current_balance >= 0', name='chk_positive_balance'), nullable=False, default=Decimal('0.000'), server_default='0.000')
    max_debt_limit   = Column(Numeric(12, 3), CheckConstraint('max_debt_limit >= 0', name='chk_positive_max_debt'), nullable=False, default=Decimal('0.000'), server_default='0.000')
    added_by_driver_id = Column(Integer, ForeignKey('drivers.id', ondelete='SET NULL'), nullable=True)
    is_active        = Column(Boolean,  nullable=False, default=True, server_default='true')
    created_at       = Column(DateTime, nullable=False, default=utc_now)  # FIX ①
    notes            = Column(Text,     nullable=True)
    location_link    = Column(String(500), nullable=True)
    # +++ إصلاح المنطق الترتيبي (Issue 5): المحل الجديد يأخذ 999 افتراضياً ليظهر بآخر خط السير +++
    sequence         = Column(Integer,  nullable=True, default=999, server_default='999')
    is_archived      = Column(Boolean,  nullable=False, default=False, server_default='false')

    visits = relationship('Visit', backref='shop', lazy='raise')


# =================================================================================
# ⑧ خطوط السير اليومية (الجدولة والتوزيع)
# =================================================================================
class DispatchRoute(Base):
    __tablename__ = 'dispatch_routes'
    # +++ النسف المعماري الشامل لثغرة الـ Race Condition (Partial Unique Indexes) +++
    __table_args__ = (
        # توحيد شمول 'postponed' لجميع الفهارس لمنع تخصيص مندوب لخط جديد بينما لديه خط مؤجل
        Index('uq_active_route_per_driver', 'driver_id', unique=True, postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
        Index('uq_active_route_per_vehicle', 'vehicle_id', unique=True, postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
        Index('uq_active_route_per_zone', 'zone_id', unique=True, postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
    )
    
    id              = Column(Integer, primary_key=True)
    zone_id         = Column(Integer, ForeignKey('zones.id'),         nullable=False, index=True)
    driver_id       = Column(Integer, ForeignKey('drivers.id'),       nullable=True,  index=True)
    vehicle_id      = Column(Integer, ForeignKey('vehicles.id'),      nullable=True,  index=True)
    work_session_id = Column(Integer, ForeignKey('work_sessions.id'), nullable=True,  index=True)
    # +++ الكي الجراحي (Issue 3): توحيد الزمن لنسف الانفصام الزمني +++
    dispatch_date   = Column(Date,    nullable=False, default=lambda: utc_now().date(), index=True)
    status          = Column(String(50), nullable=False, default='waiting', index=True)
    created_at      = Column(DateTime,   nullable=False, default=utc_now)  # FIX ①

    zone    = relationship('Zone')
    driver  = relationship('Driver')
    vehicle = relationship('Vehicle')


# =================================================================================
# ⑨ الزيارات وتفاصيلها
# =================================================================================
class Visit(Base):
    """
    الزيارة كحاوية: تضم مبيعات + توالف + عينات + تحصيل ديون.
    ملاحظة: الحقول المالية هنا (final_amount_due إلخ) هي القيم المُجمَّعة
    المحسوبة وقت الحفظ. مصدر الحقيقة الأول هو VisitItem.
    """
    __tablename__ = 'visits'
    __table_args__ = (
        Index('ix_visit_shop_timestamp', 'shop_id', 'visit_timestamp'),
        Index('ix_visit_session_outcome', 'work_session_id', 'outcome'),
    )
    id              = Column(Integer, primary_key=True)
    driver_id       = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=True,  index=True)
    shop_id         = Column(Integer, ForeignKey('shops.id'),        nullable=False, index=True)
    work_session_id = Column(Integer, ForeignKey('work_sessions.id'), nullable=True, index=True)
    visit_timestamp = Column(DateTime, nullable=False, default=utc_now, index=True)  # FIX ①

    outcome = Column(String(50), nullable=True, default='Pending', index=True)

    # +++ الدرع المحاسبي (Issue 2): تحويل جميع القيم المالية إلى Decimal لحماية دقة القروش وفرض server_default +++
    amount_before_tax_and_discount = Column(Numeric(12, 3), nullable=True, default=Decimal('0.000'), server_default='0.000')
    discount_applied               = Column(Numeric(12, 3), nullable=True, default=Decimal('0.000'), server_default='0.000')
    tax_percentage_applied         = Column(Numeric(12, 3), nullable=True, default=Decimal('0.000'), server_default='0.000')
    tax_amount                     = Column(Numeric(12, 3), nullable=True, default=Decimal('0.000'), server_default='0.000')
    final_amount_due               = Column(Numeric(12, 3), nullable=True, default=Decimal('0.000'), server_default='0.000')
    cash_collected                 = Column(Numeric(12, 3), CheckConstraint('cash_collected >= 0', name='chk_cash_collected_positive'), nullable=False, default=Decimal('0.000'), server_default='0.000')
    debt_paid                      = Column(Numeric(12, 3), CheckConstraint('debt_paid >= 0', name='chk_debt_paid_positive'), nullable=False, default=Decimal('0.000'), server_default='0.000')

    no_sale_reason    = Column(String(200), nullable=True)
    shop_balance_before = Column(Numeric(12, 3), nullable=True)
    shop_balance_after  = Column(Numeric(12, 3), nullable=True)
    latitude   = Column(Numeric(10, 7), nullable=True)
    longitude  = Column(Numeric(10, 7), nullable=True)
    sequence   = Column(Integer, nullable=True)
    status     = Column(String(50), nullable=False, default='Pending', index=True)
    notes      = Column(Text,    nullable=True)
    tax_qr_code   = Column(Text, nullable=True)
    is_emergency  = Column(Boolean, nullable=False, default=False)

    work_session = relationship('WorkSession', backref=backref('visits', lazy='raise'))
    driver       = relationship('Driver',      backref=backref('visits', lazy='raise'))
    items        = relationship('VisitItem',   backref='visit', lazy='raise',
                                   cascade='all, delete-orphan')


class VisitItem(Base):
    """
    تفاصيل الفاتورة - مصدر الحقيقة الأول للأرقام المالية.
    يحفظ أسعار البيع اللحظية لضمان دقة السجل حتى لو تغير السعر لاحقاً.
    """
    __tablename__ = 'visit_items'
    id                 = Column(Integer, primary_key=True)
    visit_id           = Column(Integer, ForeignKey('visits.id'),                        nullable=False, index=True)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False, index=True)

    # +++ الدرع الفولاذي للداتابيز: إغلاق ثغرة الأرقام السالبة من جذور الـ SQL +++
    # +++ فرض الصواب الجردي والمحاسبي على مستوى محرك قاعدة البيانات (server_default) +++
    quantity       = Column(Integer, CheckConstraint('quantity >= 0', name='chk_vitem_qty'), nullable=False, default=0, server_default='0')   # كراتين
    packs_quantity = Column(Integer, CheckConstraint('packs_quantity >= 0', name='chk_vitem_pqty'), nullable=False, default=0, server_default='0')   # حبات فرط
    bonus_quantity = Column(Integer, CheckConstraint('bonus_quantity >= 0', name='chk_vitem_bqty'), nullable=False, default=0, server_default='0')   # بونص كراتين
    sample_quantity = Column(Integer, CheckConstraint('sample_quantity >= 0', name='chk_vitem_sqty'), nullable=False, default=0, server_default='0')   # عينات مجانية
    sample_packs_quantity = Column(Integer, CheckConstraint('sample_packs_quantity >= 0', name='chk_vitem_spqty'), nullable=False, default=0, server_default='0')
    price_per_unit_at_sale = Column(Numeric(12, 3), nullable=False) # +++ إلزامي لحماية الفواتير +++
    total_price            = Column(Numeric(12, 3), nullable=False, default=Decimal('0.000'), server_default='0.000')
    sample_reason = Column(String(255), nullable=True)
    is_cancelled = Column(Boolean, nullable=False, default=False, server_default='false') # +++ لمنع طمس الأدلة وإغلاق ثغرة الـ NULL بالداتابيز +++

    product_variant = relationship('ProductVariant', lazy='raise')


class VisitReturn(Base):
    """
    المرتجعات والتوالف المستلمة خلال الزيارة.
    return_type: Factory_Defect | Expired | Damaged
    """
    __tablename__ = 'visit_returns'
    __table_args__ = (
        Index('ix_visit_return_composite', 'visit_id', 'product_variant_id'),
    )
    id                 = Column(Integer, primary_key=True)
    visit_id           = Column(Integer, ForeignKey('visits.id', ondelete='CASCADE'),    nullable=False, index=True)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False, index=True)

    # +++ حماية مخزون المرتجعات من الاختلاس العكسي +++
    quantity    = Column(Integer, CheckConstraint('quantity >= 0', name='chk_vret_qty'), nullable=False, default=0)
    packs_quantity = Column(Integer, CheckConstraint('packs_quantity >= 0', name='chk_vret_pqty'), nullable=False, default=0)
    return_type = Column(String(50), nullable=False)
    reason      = Column(Text,       nullable=True)
    is_cancelled = Column(Boolean, nullable=False, default=False, server_default='false') # +++ لمنع طمس الأدلة وإغلاق ثغرة الـ NULL بالداتابيز +++

    product_variant = relationship('ProductVariant', lazy='raise')
    visit = relationship('Visit', backref=backref('returns', lazy='raise',
                                                         cascade='all, delete-orphan'))


# =================================================================================
# ⑩ الطلبات والنواقص (Shortages)
# FIX ③: استبدال product_name النصي بـ product_variant_id FK
# السبب: الاسم النصي يُفقد سلامة البيانات لو تغير اسم المنتج
# التأثير على routes.py: أي endpoint يُنشئ ShortageRequest يرسل
#   product_variant_id (integer) بدل product_name (string)
# =================================================================================
class ShortageRequest(Base):
    __tablename__ = 'shortage_requests'
    id                 = Column(Integer, primary_key=True)
    zone_id            = Column(Integer, ForeignKey('zones.id'),            nullable=False, index=True)
    shop_id            = Column(Integer, ForeignKey('shops.id'),            nullable=False, index=True)
    driver_id          = Column(Integer, ForeignKey('drivers.id'),          nullable=True,  index=True)
    # FIX ③: product_variant_id بدل product_name النصي
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'),
                                   nullable=False, index=True)

    quantity   = Column(Integer, CheckConstraint('quantity > 0', name='chk_shortage_qty_positive'), nullable=False)
    status     = Column(String(50), nullable=False, default='pending', index=True)
    wait_time  = Column(String(50), nullable=True,  default='الآن')
    notes      = Column(Text,       nullable=True)   # بدل product_name - لو في ملاحظات إضافية
    created_at = Column(DateTime,   nullable=False,  default=utc_now)  # FIX ①

    zone            = relationship('Zone', lazy='raise')
    shop            = relationship('Shop', lazy='raise')
    driver          = relationship('Driver', lazy='raise')
    product_variant = relationship('ProductVariant', lazy='raise')  # FIX ③


# =================================================================================
# ⑪ العروض
# =================================================================================
class OfferRule(Base):
    __tablename__ = 'offer_rules'
    id                 = Column(Integer, primary_key=True)
    # +++ الكي الجراحي (G-01): ربط العرض بمنتج معين. (Null تعني عرض عام لجميع المنتجات) +++
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='CASCADE'), nullable=True, index=True)
    threshold_quantity = Column(Integer, nullable=False)
    offer_type         = Column(String(50), nullable=False)
    bonus_quantity     = Column(Integer,    nullable=False, default=0)
    # +++ حماية القروش من التآكل (Float vs Decimal) +++
    discount_value     = Column(Numeric(12, 3), nullable=False, default=Decimal('0.000'), server_default='0.000')
    is_active          = Column(Boolean,    nullable=False, default=True)


# =================================================================================
# ⑫ سجل الاستيراد الجماعي (Audit Log)
# =================================================================================
class ImportLog(Base):
    """
    يوثق عمليات استيراد المحلات الجماعية.
    يحفظ: المسؤول، التاريخ، المنطقة، عدد السجلات الناجحة والفاشلة.
    """
    __tablename__ = 'import_logs'
    id            = Column(Integer, primary_key=True)
    # +++ حماية الداتابيز من كراش الـ IntegrityError عند إلغاء حساب موظف +++
    admin_id      = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=False)
    zone_id       = Column(Integer, ForeignKey('zones.id'),   nullable=False)
    file_name     = Column(String(255), nullable=True)
    total_records = Column(Integer,     nullable=False, default=0)
    success_count = Column(Integer,     nullable=False, default=0)
    status        = Column(String(50),  nullable=False)  # Success | Failed | Partial
    created_at    = Column(DateTime,    nullable=False, default=utc_now)  # FIX ①

    admin = relationship('Driver', lazy='raise')
    zone  = relationship('Zone', lazy='raise')


# =================================================================================
# ⑬ سجل حركات المخزون (Inventory Ledger) - دفتر الأستاذ
# السجل المالي غير القابل للمسح
# =================================================================================
class InventoryLedger(Base):
    """
    يوثق العجز والزيادة وأي تسوية على سيارة المندوب.
    transaction_type: Deficit (عجز) | Surplus (زيادة) | Adjustment (تعديل)
    """
    __tablename__ = 'inventory_ledgers'
    # +++ الكي الجراحي (G-04): إجبار الداتابيز على حساب الفرق بدقة لمنع التلاعب المالي +++
    __table_args__ = (
        CheckConstraint('difference = actual_quantity - expected_quantity', name='chk_ledger_difference'),
    )
    id                 = Column(Integer, primary_key=True)
    work_session_id    = Column(Integer, ForeignKey('work_sessions.id'), nullable=True, index=True)
    driver_id          = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=False)
    vehicle_id         = Column(Integer, ForeignKey('vehicles.id'),      nullable=True)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id'), nullable=False)

    transaction_type  = Column(String(50), nullable=False)
    expected_quantity = Column(Integer,    nullable=False)
    actual_quantity   = Column(Integer,    nullable=False)
    difference        = Column(Integer,    nullable=False)  # سالب للعجز، موجب للزيادة

    # +++ حماية سجل الأستاذ (Issue 6): تقييد حذف الأدمن (RESTRICT) للحفاظ على الدفتر المالي من التلف +++
    admin_id  = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=utc_now)  # FIX ①
    notes     = Column(Text, nullable=True)

    product_variant = relationship('ProductVariant', lazy='raise')
    driver          = relationship('Driver', foreign_keys=[driver_id], lazy='raise')
    admin           = relationship('Driver', foreign_keys=[admin_id], lazy='raise')


# =================================================================================
# ⑭ سجل النظام الشامل (System Audit Log)
# يسجل الحركات الحساسة لمنع التلاعب
# =================================================================================
class SystemAuditLog(Base):
    __tablename__ = 'system_audit_logs'
    id          = Column(Integer, primary_key=True)
    # +++ تأمين بقاء سجل الرقابة حتى لو تم حذف حساب المدير (SET NULL بدلاً من الكراش) +++
    admin_id    = Column(Integer, ForeignKey('drivers.id', ondelete='SET NULL'), nullable=True, index=True)
    target_id   = Column(String(100), nullable=False, index=True)   # رقم الجلسة أو المندوب
    action_type = Column(String(100), nullable=False, index=True)   # UNDO_END_WORK إلخ
    old_value   = Column(Text, nullable=True)
    new_value   = Column(Text, nullable=True)
    timestamp   = Column(DateTime, nullable=False, default=utc_now)  # FIX ①

    admin = relationship('Driver', foreign_keys=[admin_id], lazy='raise')


# =================================================================================
# ⑮ أرشيف الاستراحات
# يحل مشكلة ضياع الاستراحة الأولى إذا قام المندوب باستراحة ثانية
# =================================================================================
class WorkBreakLog(Base):
    __tablename__ = 'work_break_logs'
    id              = Column(Integer, primary_key=True)
    work_session_id = Column(Integer, ForeignKey('work_sessions.id'), nullable=False, index=True)
    break_start     = Column(DateTime, nullable=False)
    break_end       = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)  # يُحسب تلقائياً عند الإنهاء

    work_session = relationship('WorkSession', backref=backref('break_logs', lazy='raise'))


# =================================================================================
# ⑯ الحوالات المعلقة (المصافحة - Handshake)
# عنق الزجاجة الذي يمنع دخول أي بضاعة للعهدة إلا بموافقة المندوب
# =================================================================================
class InventoryTransfer(Base):
    __tablename__ = 'inventory_transfers'
    __table_args__ = (
        Index('uq_pending_transfer', 'work_session_id', 'product_variant_id', unique=True, postgresql_where=text("status = 'pending'")),
    )
    id                 = Column(Integer, primary_key=True)
    work_session_id    = Column(Integer, ForeignKey('work_sessions.id',    ondelete='RESTRICT'), nullable=False)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False)

    quantity_packs = Column(Integer,    nullable=False)  # موجب للزيادة، سالب للسحب
    status         = Column(String(20), nullable=False, default='pending')  # pending | accepted | rejected

    admin_id   = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    notes = Column(String(255), nullable=True)

    product_variant = relationship('ProductVariant', lazy='raise')
    work_session    = relationship('WorkSession',
                                      backref=backref('transfers', lazy='raise',
                                                         cascade='all, delete-orphan'))


# =================================================================================
# ⑰ المستودع الرئيسي (Main Warehouse)
# يعتمد على الحبات (Packs) كأصغر وحدة قياس لمنع تضارب الفراطة.
# =================================================================================
class MainWarehouse(Base):
    __tablename__ = 'main_warehouse'
    # استخدام product_variant_id كـ Primary Key يمنع تكرار نفس المنتج في المستودع ويجعل الاستعلام O(1)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), primary_key=True)
    
    # الرصيد الفعلي المتاح للتحميل (الحبات)
    available_quantity_packs = Column(Integer, CheckConstraint('available_quantity_packs >= 0', name='chk_main_warehouse_positive'), nullable=False, default=0)
    
    # +++ معمارية In-Transit: الرصيد المحجوز للحوالات المعلقة لمنع إرساله لمندوب آخر +++
    reserved_quantity_packs = Column(Integer, CheckConstraint('reserved_quantity_packs >= 0', name='chk_reserved_warehouse_positive'), nullable=False, default=0)
    
    # +++ إشعارات العجز (Threshold Alerts): الحد الأدنى بالحبات +++
    min_threshold_packs = Column(Integer, nullable=False, default=0)
    
    last_updated = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now, index=True) # +++ فهرس التقارير الراكدة +++

    product_variant = relationship('ProductVariant', lazy='raise')


# =================================================================================
# ⑱ مقبرة التوالف (Damaged Goods Log)
# سجل دقيق لكل حبة تالفة تعود للمستودع مع توثيق (من أحضرها ومن أي محل).
# =================================================================================
class DamagedItemLog(Base):
    __tablename__ = 'damaged_items_log'
    id = Column(Integer, primary_key=True)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False)
    
    # +++ الدرع المحاسبي: منع التوالف السالبة +++
    quantity_packs = Column(Integer, CheckConstraint('quantity_packs >= 0', name='chk_damaged_positive'), nullable=False)
    damage_type    = Column(String(50), nullable=False) # Expired | Factory_Defect | Damaged
    
    # +++ التتبع الأمني (Traceability) +++
    source_driver_id = Column(Integer, ForeignKey('drivers.id', ondelete='SET NULL'), nullable=True)
    source_visit_id  = Column(Integer, ForeignKey('visits.id', ondelete='SET NULL'), nullable=True)
    receiving_admin_id = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=False)
    
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    product_variant = relationship('ProductVariant', lazy='raise')
    driver = relationship('Driver', foreign_keys=[source_driver_id], lazy='raise')
    admin = relationship('Driver', foreign_keys=[receiving_admin_id], lazy='raise')
    visit = relationship('Visit', lazy='raise')


# =================================================================================
# ⑲ دفتر أستاذ المستودع (Warehouse Ledger)
# السجل المالي للبضاعة - لا يمكن مسحه أو تعديله. يوثق الموردين وحركات التحميل.
# =================================================================================
class WarehouseLedger(Base):
    """
    أنواع الحركات (transaction_type):
    - INBOUND_SUPPLIER: استلام بضاعة من المورد.
    - DISPATCH_LOAD: تحميل سيارة مندوب.
    - DISPATCH_UNLOAD: تفريغ سيارة (أو مرتجع فراطة).
    - HANDSHAKE_RESERVE: حجز بضاعة لمصافحة معلقة.
    - HANDSHAKE_RELEASE: إعادة بضاعة محجوزة (رفض המندوب).
    - HANDSHAKE_COMMIT: تأكيد المصافحة (لا يغير الإجمالي لكن يصفر المحجوز).
    - AUDIT_ADJUSTMENT: تسوية جرد المستودع (عجز/زيادة).
    """
    __tablename__ = 'warehouse_ledger'
    __table_args__ = (
        Index('idx_ledger_variant_created', 'product_variant_id', 'created_at'),
        # +++ سحق الـ Magic String العربي واعتماد IS NOT NULL مع منع الفراغ +++
        Index('uq_ledger_supplier_ref', 'reference_id', 'product_variant_id', unique=True, postgresql_where=text("transaction_type = 'INBOUND_SUPPLIER' AND reference_id IS NOT NULL AND trim(reference_id) != ''")),
    )
    id = Column(Integer, primary_key=True)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False)
    
    transaction_type = Column(String(50), nullable=False, index=True)
    
    # تفاصيل الحركة بالحبات
    quantity_packs = Column(Integer, nullable=False)    
    # +++ لقطة الرصيد الفوري (Snapshot) قبل وبعد الحركة لضمان سلامة الدفاتر +++
    balance_before_packs = Column(Integer, nullable=False)
    balance_after_packs = Column(Integer, nullable=False)    
    admin_id = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=False)
    # رقم مرجعي (فاتورة مورد، رقم حوالة، رقم جلسة المندوب)
    reference_id = Column(String(100), nullable=True, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    product_variant = relationship('ProductVariant', lazy='raise')
    admin = relationship('Driver', foreign_keys=[admin_id], lazy='raise')

# =================================================================================
# ⑳ القائمة السوداء للتوكنز (Token Blacklist) - لإنهاء الجلسات (Logout)
# =================================================================================
class TokenBlacklist(Base):
    __tablename__ = 'token_blacklist'
    id = Column(Integer, primary_key=True)
    token = Column(String(500), unique=True, nullable=False)
    blacklisted_at = Column(DateTime, nullable=False, default=utc_now, index=True) # +++ فهرس لتسريع الحذف التلقائي +++


# =================================================================================
# ㉑ مفاتيح التجديد التلقائي (Refresh Tokens) - لضمان بقاء الجلسة نشطة
# =================================================================================
class RefreshToken(Base):
    __tablename__ = 'refresh_tokens'
    id = Column(Integer, primary_key=True)
    token = Column(String(500), unique=True, nullable=False)
    driver_id = Column(Integer, ForeignKey('drivers.id', ondelete='CASCADE'), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True) # +++ فهرس لتسريع تنظيف الداتابيز +++
    created_at = Column(DateTime, nullable=False, default=utc_now)
    is_revoked = Column(Boolean, nullable=False, default=False)
    
    driver = relationship('Driver', lazy='raise')