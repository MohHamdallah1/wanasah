from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from datetime import datetime, date, timezone
import bcrypt

convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

metadata = MetaData(naming_convention=convention)
db = SQLAlchemy(metadata=metadata)

# دالة مساعدة موحدة للوقت - المصدر الوحيد للحقيقة في كل الملف
# FIX ①: بدل تكرار lambda في كل جدول، دالة واحدة تضمن التوحيد
def utc_now():
    return datetime.now(timezone.utc)


# =================================================================================
# ① الإعدادات العامة للنظام
# =================================================================================
class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    id            = db.Column(db.Integer, primary_key=True)
    setting_key   = db.Column(db.String(50),  unique=True, nullable=False)
    setting_value = db.Column(db.String(100), nullable=False)
    description   = db.Column(db.String(200), nullable=True)


# =================================================================================
# ② التوزيع الجغرافي الهرمي: دولة → محافظة → منطقة
# الترتيب مهم: كل كلاس يعرَّف قبل من يشير إليه
# =================================================================================
class Country(db.Model):
    __tablename__ = 'countries'
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

    governorates = db.relationship('Governorate', backref='country', lazy=True)


class Governorate(db.Model):
    __tablename__ = 'governorates'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    country_id = db.Column(db.Integer, db.ForeignKey('countries.id'), nullable=False)

    zones = db.relationship('Zone', backref='governorate', lazy=True)


class Zone(db.Model):
    """
    المنطقة الجغرافية التي يغطيها المندوب.
    تحتوي على إعدادات الجدولة (أسبوعي، شهري، مخصص) لتنظيم
    مواعيد الزيارات الدورية.
    """
    __tablename__ = 'zones'
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(100), nullable=False)
    governorate_id  = db.Column(db.Integer, db.ForeignKey('governorates.id'), nullable=True)
    sequence_number = db.Column(db.Integer, nullable=True)   # ترتيب خطوط السير

    # حقول الجدولة
    schedule_frequency = db.Column(db.String(50),  nullable=True)  # weekly / monthly / custom
    visit_day          = db.Column(db.String(20),  nullable=True)  # Saturday / Sunday …
    start_date         = db.Column(db.Date,        nullable=True)
    custom_days        = db.Column(db.Integer,     nullable=True)  # عدد الأيام للجدولة المخصصة

    is_active = db.Column(db.Boolean, nullable=False, default=True)

    shops = db.relationship('Shop', backref='zone', lazy=True)


# =================================================================================
# ③ المستخدمون (المندوبون والمسؤولون)
# ملاحظة معمارية: حالياً الأدوار داخل نفس الجدول (is_admin, can_allow_debt).
# هاد كافي للمرحلة الحالية، ولما نروح لـ SaaS نفصل جدول Roles مستقل.
# =================================================================================
class Driver(db.Model):
    __tablename__ = 'drivers'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    full_name     = db.Column(db.String(120), nullable=False)
    phone_number  = db.Column(db.String(20),  nullable=True)
    is_active     = db.Column(db.Boolean,     nullable=False, default=True)
    is_admin      = db.Column(db.Boolean,     nullable=False, default=False)
    can_allow_debt  = db.Column(db.Boolean,       nullable=False, default=False)
    max_debt_limit  = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    created_at      = db.Column(db.DateTime,      nullable=False, default=utc_now)  # FIX ①

    def set_password(self, password: str):
        self.password_hash = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(
            password.encode('utf-8'),
            self.password_hash.encode('utf-8')
        )


# =================================================================================
# ④ المنتجات (Product → ProductVariant)
# =================================================================================
class Product(db.Model):
    __tablename__ = 'products'
    id         = db.Column(db.Integer, primary_key=True)
    base_name  = db.Column(db.String(150), nullable=False)
    brand      = db.Column(db.String(100), nullable=True)
    category   = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime,   nullable=False, default=utc_now)  # FIX ①

    variants = db.relationship('ProductVariant', backref='product', lazy=True)


class ProductVariant(db.Model):
    __tablename__ = 'product_variants'
    id         = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    variant_name    = db.Column(db.String(200), nullable=False)
    flavor          = db.Column(db.String(50),  nullable=True)
    size            = db.Column(db.String(50),  nullable=True)
    sku             = db.Column(db.String(100), nullable=True, unique=True)
    packs_per_carton = db.Column(db.Integer,       nullable=False, default=50)
    price_per_carton = db.Column(db.Numeric(10, 2), nullable=False)
    price_per_pack   = db.Column(db.Numeric(10, 2), nullable=True)
    is_active        = db.Column(db.Boolean, nullable=False, default=True, index=True)
    default_max_samples_per_day = db.Column(db.Integer, nullable=False, default=0)


# =================================================================================
# ⑤ الأسطول والسيارات
# =================================================================================
class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    id                 = db.Column(db.Integer, primary_key=True)
    plate_number       = db.Column(db.String(20), unique=True, nullable=False)
    vehicle_type       = db.Column(db.String(50), nullable=True)
    current_mileage    = db.Column(db.Integer,    nullable=False, default=0)
    next_oil_change    = db.Column(db.Integer,    nullable=True)
    license_expiry_date = db.Column(db.Date,      nullable=True)
    maintenance_status = db.Column(db.String(50), nullable=False, default='Active')  # Active | In_Maintenance
    is_active          = db.Column(db.Boolean,    nullable=False, default=True)


class VehicleLoad(db.Model):
    """
    مسودة الحمولة التي يجهزها أمين المستودع ليلاً.
    قيد الفرادة يمنع تكرار نفس المنتج على نفس السيارة.
    """
    __tablename__ = 'vehicle_loads'
    __table_args__ = (
        db.UniqueConstraint('vehicle_id', 'product_variant_id', name='uq_vehicle_variant_load'),
    )
    id                 = db.Column(db.Integer, primary_key=True)
    vehicle_id         = db.Column(db.Integer, db.ForeignKey('vehicles.id'),         nullable=False, index=True)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=False)
    quantity           = db.Column(db.Integer,  nullable=False, default=0)
    updated_at         = db.Column(db.DateTime, nullable=False, default=utc_now)  # FIX ①

    product_variant = db.relationship('ProductVariant')


# =================================================================================
# ⑥ جلسات العمل والعهدة
# مُعرَّفة قبل DispatchRoute لأن DispatchRoute يشير إليها
# FIX ②: حل مشكلة الترتيب - WorkSession كانت بعد DispatchRoute
# =================================================================================
class WorkSession(db.Model):
    __tablename__ = 'work_sessions'
    id           = db.Column(db.Integer, primary_key=True)
    driver_id    = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False, index=True)
    start_time   = db.Column(db.DateTime, nullable=False, default=utc_now)           # FIX ①
    end_time     = db.Column(db.DateTime, nullable=True,  index=True)
    session_date = db.Column(db.Date,     nullable=False,
                             default=lambda: datetime.now(timezone.utc).date(), index=True)
    start_latitude  = db.Column(db.Float, nullable=True)
    start_longitude = db.Column(db.Float, nullable=True)

    is_authorized_to_sell = db.Column(db.Boolean,  nullable=False, default=False)
    break_start_time      = db.Column(db.DateTime, nullable=True)
    break_end_time        = db.Column(db.DateTime, nullable=True)
    is_settled            = db.Column(db.Boolean,  nullable=False, default=False, index=True)

    driver    = db.relationship('Driver', backref=db.backref('work_sessions', lazy=True))
    inventory = db.relationship('SessionInventory', backref='work_session', lazy=True)


class SessionInventory(db.Model):
    """
    العهدة الشخصية للمندوب خلال جلسة العمل.
    قيد الفرادة يمنع تكرار نفس المنتج في نفس الجلسة.
    """
    __tablename__ = 'session_inventory'
    __table_args__ = (
        db.UniqueConstraint('work_session_id', 'product_variant_id', name='uq_session_variant_inv'),
    )
    id                 = db.Column(db.Integer, primary_key=True)
    work_session_id    = db.Column(db.Integer, db.ForeignKey('work_sessions.id'),    nullable=False, index=True)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=False, index=True)
    starting_quantity           = db.Column(db.Integer, nullable=False, default=0)
    current_remaining_quantity = db.Column(db.Integer, db.CheckConstraint('current_remaining_quantity >= 0', name='chk_positive_inventory'), nullable=False, default=0)

    product_variant = db.relationship('ProductVariant')


# =================================================================================
# ⑦ المحلات
# =================================================================================
class Shop(db.Model):
    __tablename__ = 'shops'
    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(150), nullable=False)
    address        = db.Column(db.Text,        nullable=True)
    latitude       = db.Column(db.Float,       nullable=True)
    longitude      = db.Column(db.Float,       nullable=True)
    phone_number   = db.Column(db.String(20),  nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)
    zone_id        = db.Column(db.Integer, db.ForeignKey('zones.id', ondelete='SET NULL'),
                               nullable=True, index=True)
    current_balance  = db.Column(db.Numeric(10, 2), db.CheckConstraint('current_balance >= 0', name='chk_positive_balance'), nullable=False, default=0.0)
    max_debt_limit   = db.Column(db.Numeric(10, 2), db.CheckConstraint('max_debt_limit >= 0', name='chk_positive_max_debt'), nullable=False, default=0.0)
    added_by_driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=True)
    is_active        = db.Column(db.Boolean,  nullable=False, default=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=utc_now)  # FIX ①
    notes            = db.Column(db.Text,     nullable=True)
    location_link    = db.Column(db.String(500), nullable=True)
    sequence         = db.Column(db.Integer,  nullable=True, default=0)
    is_archived      = db.Column(db.Boolean,  nullable=False, default=False)

    visits = db.relationship('Visit', backref='shop', lazy='select')


# =================================================================================
# ⑧ خطوط السير اليومية (الجدولة والتوزيع)
# مُعرَّفة بعد WorkSession لأنها تشير إليها
# =================================================================================
class DispatchRoute(db.Model):
    __tablename__ = 'dispatch_routes'
    id              = db.Column(db.Integer, primary_key=True)
    zone_id         = db.Column(db.Integer, db.ForeignKey('zones.id'),         nullable=False, index=True)
    driver_id       = db.Column(db.Integer, db.ForeignKey('drivers.id'),       nullable=True,  index=True)
    vehicle_id      = db.Column(db.Integer, db.ForeignKey('vehicles.id'),      nullable=True,  index=True)
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=True,  index=True)
    dispatch_date   = db.Column(db.Date,    nullable=False,
                                default=lambda: datetime.now(timezone.utc).date(), index=True)
    status          = db.Column(db.String(50), nullable=False, default='waiting', index=True)
    created_at      = db.Column(db.DateTime,   nullable=False, default=utc_now)  # FIX ①

    zone    = db.relationship('Zone')
    driver  = db.relationship('Driver')
    vehicle = db.relationship('Vehicle')


# =================================================================================
# ⑨ الزيارات وتفاصيلها
# =================================================================================
class Visit(db.Model):
    """
    الزيارة كحاوية: تضم مبيعات + توالف + عينات + تحصيل ديون.
    ملاحظة: الحقول المالية هنا (final_amount_due إلخ) هي القيم المُجمَّعة
    المحسوبة وقت الحفظ. مصدر الحقيقة الأول هو VisitItem.
    """
    __tablename__ = 'visits'
    id              = db.Column(db.Integer, primary_key=True)
    driver_id       = db.Column(db.Integer, db.ForeignKey('drivers.id'),      nullable=True,  index=True)
    shop_id         = db.Column(db.Integer, db.ForeignKey('shops.id'),        nullable=False, index=True)
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=True, index=True)
    visit_timestamp = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)  # FIX ①

    outcome = db.Column(db.String(50), nullable=True, default='Pending', index=True)

    # الحقول المالية - مُجمَّعة من VisitItem عند الحفظ
    amount_before_tax_and_discount = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    discount_applied               = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    tax_percentage_applied         = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    tax_amount                     = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    final_amount_due               = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    cash_collected                 = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    debt_paid                      = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)

    no_sale_reason    = db.Column(db.String(200), nullable=True)
    shop_balance_before = db.Column(db.Numeric(10, 2), nullable=True)
    shop_balance_after  = db.Column(db.Numeric(10, 2), nullable=True)
    latitude   = db.Column(db.Float,   nullable=True)
    longitude  = db.Column(db.Float,   nullable=True)
    sequence   = db.Column(db.Integer, nullable=True)
    status     = db.Column(db.String(50), nullable=False, default='Pending', index=True)
    notes      = db.Column(db.Text,    nullable=True)
    tax_qr_code   = db.Column(db.String(500), nullable=True)
    is_emergency  = db.Column(db.Boolean, nullable=False, default=False)

    work_session = db.relationship('WorkSession', backref=db.backref('visits', lazy='select'))
    driver       = db.relationship('Driver',      backref=db.backref('visits', lazy='select'))
    items        = db.relationship('VisitItem',   backref='visit', lazy='select',
                                   cascade='all, delete-orphan')


class VisitItem(db.Model):
    """
    تفاصيل الفاتورة - مصدر الحقيقة الأول للأرقام المالية.
    يحفظ أسعار البيع اللحظية لضمان دقة السجل حتى لو تغير السعر لاحقاً.
    """
    __tablename__ = 'visit_items'
    id                 = db.Column(db.Integer, primary_key=True)
    visit_id           = db.Column(db.Integer, db.ForeignKey('visits.id'),                        nullable=False, index=True)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False, index=True)

    quantity       = db.Column(db.Integer,       nullable=False, default=0)   # كراتين
    packs_quantity = db.Column(db.Integer,       nullable=False, default=0)   # حبات فرط
    bonus_quantity = db.Column(db.Integer,       nullable=False, default=0)   # بونص كراتين
    sample_quantity = db.Column(db.Integer,      nullable=False, default=0)   # عينات مجانية
    price_per_unit_at_sale = db.Column(db.Numeric(10, 2), nullable=True)
    total_price            = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)

    product_variant = db.relationship('ProductVariant')


class VisitReturn(db.Model):
    """
    المرتجعات والتوالف المستلمة خلال الزيارة.
    return_type: Factory_Defect | Expired | Damaged
    """
    __tablename__ = 'visit_returns'
    id                 = db.Column(db.Integer, primary_key=True)
    visit_id           = db.Column(db.Integer, db.ForeignKey('visits.id'),                        nullable=False, index=True)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False, index=True)

    quantity    = db.Column(db.Integer,    nullable=False, default=0)
    return_type = db.Column(db.String(50), nullable=False)
    reason      = db.Column(db.Text,       nullable=True)

    product_variant = db.relationship('ProductVariant')
    visit = db.relationship('Visit', backref=db.backref('returns', lazy='select',
                                                         cascade='all, delete-orphan'))


# =================================================================================
# ⑩ الطلبات والنواقص (Shortages)
# FIX ③: استبدال product_name النصي بـ product_variant_id FK
# السبب: الاسم النصي يُفقد سلامة البيانات لو تغير اسم المنتج
# التأثير على routes.py: أي endpoint يُنشئ ShortageRequest يرسل
#   product_variant_id (integer) بدل product_name (string)
# =================================================================================
class ShortageRequest(db.Model):
    __tablename__ = 'shortage_requests'
    id                 = db.Column(db.Integer, primary_key=True)
    zone_id            = db.Column(db.Integer, db.ForeignKey('zones.id'),            nullable=False, index=True)
    shop_id            = db.Column(db.Integer, db.ForeignKey('shops.id'),            nullable=False, index=True)
    driver_id          = db.Column(db.Integer, db.ForeignKey('drivers.id'),          nullable=True,  index=True)
    # FIX ③: product_variant_id بدل product_name النصي
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id', ondelete='RESTRICT'),
                                   nullable=False, index=True)

    quantity   = db.Column(db.Integer,    nullable=False)
    status     = db.Column(db.String(50), nullable=False, default='pending', index=True)
    wait_time  = db.Column(db.String(50), nullable=True,  default='الآن')
    notes      = db.Column(db.Text,       nullable=True)   # بدل product_name - لو في ملاحظات إضافية
    created_at = db.Column(db.DateTime,   nullable=False,  default=utc_now)  # FIX ①

    zone            = db.relationship('Zone')
    shop            = db.relationship('Shop')
    driver          = db.relationship('Driver')
    product_variant = db.relationship('ProductVariant')  # FIX ③


# =================================================================================
# ⑪ العروض
# =================================================================================
class OfferRule(db.Model):
    __tablename__ = 'offer_rules'
    id                 = db.Column(db.Integer, primary_key=True)
    threshold_quantity = db.Column(db.Integer, nullable=False)
    offer_type         = db.Column(db.String(50), nullable=False)
    bonus_quantity     = db.Column(db.Integer,    nullable=False, default=0)
    discount_value     = db.Column(db.Float,      nullable=False, default=0.0)
    is_active          = db.Column(db.Boolean,    nullable=False, default=True)


# =================================================================================
# ⑫ سجل الاستيراد الجماعي (Audit Log)
# =================================================================================
class ImportLog(db.Model):
    """
    يوثق عمليات استيراد المحلات الجماعية.
    يحفظ: المسؤول، التاريخ، المنطقة، عدد السجلات الناجحة والفاشلة.
    """
    __tablename__ = 'import_logs'
    id            = db.Column(db.Integer, primary_key=True)
    admin_id      = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False)
    zone_id       = db.Column(db.Integer, db.ForeignKey('zones.id'),   nullable=False)
    file_name     = db.Column(db.String(255), nullable=True)
    total_records = db.Column(db.Integer,     nullable=False, default=0)
    success_count = db.Column(db.Integer,     nullable=False, default=0)
    status        = db.Column(db.String(50),  nullable=False)  # Success | Failed | Partial
    created_at    = db.Column(db.DateTime,    nullable=False, default=utc_now)  # FIX ①

    admin = db.relationship('Driver')
    zone  = db.relationship('Zone')


# =================================================================================
# ⑬ سجل حركات المخزون (Inventory Ledger) - دفتر الأستاذ
# السجل المالي غير القابل للمسح
# =================================================================================
class InventoryLedger(db.Model):
    """
    يوثق العجز والزيادة وأي تسوية على سيارة المندوب.
    transaction_type: Deficit (عجز) | Surplus (زيادة) | Adjustment (تعديل)
    """
    __tablename__ = 'inventory_ledgers'
    id                 = db.Column(db.Integer, primary_key=True)
    work_session_id    = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=True)
    driver_id          = db.Column(db.Integer, db.ForeignKey('drivers.id'),       nullable=False)
    vehicle_id         = db.Column(db.Integer, db.ForeignKey('vehicles.id'),      nullable=True)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=False)

    transaction_type  = db.Column(db.String(50), nullable=False)
    expected_quantity = db.Column(db.Integer,    nullable=False)
    actual_quantity   = db.Column(db.Integer,    nullable=False)
    difference        = db.Column(db.Integer,    nullable=False)  # سالب للعجز، موجب للزيادة

    admin_id  = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=utc_now)  # FIX ①
    notes     = db.Column(db.Text, nullable=True)

    product_variant = db.relationship('ProductVariant')
    driver          = db.relationship('Driver', foreign_keys=[driver_id])
    admin           = db.relationship('Driver', foreign_keys=[admin_id])


# =================================================================================
# ⑭ سجل النظام الشامل (System Audit Log)
# يسجل الحركات الحساسة لمنع التلاعب
# =================================================================================
class SystemAuditLog(db.Model):
    __tablename__ = 'system_audit_logs'
    id          = db.Column(db.Integer, primary_key=True)
    admin_id    = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False, index=True)
    target_id   = db.Column(db.String(100), nullable=False, index=True)   # رقم الجلسة أو المندوب
    action_type = db.Column(db.String(100), nullable=False, index=True)   # UNDO_END_WORK إلخ
    old_value   = db.Column(db.Text, nullable=True)
    new_value   = db.Column(db.Text, nullable=True)
    timestamp   = db.Column(db.DateTime, nullable=False, default=utc_now)  # FIX ①

    admin = db.relationship('Driver', foreign_keys=[admin_id])


# =================================================================================
# ⑮ أرشيف الاستراحات
# يحل مشكلة ضياع الاستراحة الأولى إذا قام المندوب باستراحة ثانية
# =================================================================================
class WorkBreakLog(db.Model):
    __tablename__ = 'work_break_logs'
    id              = db.Column(db.Integer, primary_key=True)
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=False, index=True)
    break_start     = db.Column(db.DateTime, nullable=False)
    break_end       = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True)  # يُحسب تلقائياً عند الإنهاء

    work_session = db.relationship('WorkSession', backref=db.backref('break_logs', lazy='select'))


# =================================================================================
# ⑯ الحوالات المعلقة (المصافحة - Handshake)
# عنق الزجاجة الذي يمنع دخول أي بضاعة للعهدة إلا بموافقة المندوب
# =================================================================================
class InventoryTransfer(db.Model):
    __tablename__ = 'inventory_transfers'
    id                 = db.Column(db.Integer, primary_key=True)
    work_session_id    = db.Column(db.Integer, db.ForeignKey('work_sessions.id',    ondelete='CASCADE'), nullable=False)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id', ondelete='CASCADE'), nullable=False)

    quantity_packs = db.Column(db.Integer,    nullable=False)  # موجب للزيادة، سالب للسحب
    status         = db.Column(db.String(20), nullable=False, default='pending')  # pending | accepted | rejected

    admin_id   = db.Column(db.Integer, db.ForeignKey('drivers.id', ondelete='SET NULL'), nullable=True)
    # FIX ④: إزالة .replace(tzinfo=None) - كان يُنشئ naive datetime مخالف لبقية الجداول
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    product_variant = db.relationship('ProductVariant')
    work_session    = db.relationship('WorkSession',
                                      backref=db.backref('transfers', lazy='select',
                                                         cascade='all, delete-orphan'))