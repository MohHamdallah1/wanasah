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

class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(50), unique=True, nullable=False)
    setting_value = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200), nullable=True)

# ================= التوزيع الجغرافي (هرمي) =================
class Country(db.Model):
    __tablename__ = 'countries'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    governorates = db.relationship('Governorate', backref='country', lazy=True)

class Governorate(db.Model):
    __tablename__ = 'governorates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    country_id = db.Column(db.Integer, db.ForeignKey('countries.id'), nullable=False)
    zones = db.relationship('Zone', backref='governorate', lazy=True)

# ================= التوزيع الجغرافي والمناطق (Zones) =================
#   يمثل المناطق الجغرافية التي يتم تغطيتها في عمليات التوزيع.
# يحتوي على إعدادات الجدولة الشاملة (أسبوعي، مخصص، إلخ) 
# لتنظيم وترتيب مواعيد الزيارات الدورية لأسطول المندوبين.
class Zone(db.Model):
    __tablename__ = 'zones'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    governorate_id = db.Column(db.Integer, db.ForeignKey('governorates.id'), nullable=True)
    sequence_number = db.Column(db.Integer, nullable=True) # لترتيب خطوط السير
    
    # +++ حقول الجدولة الشاملة +++
    schedule_frequency = db.Column(db.String(50), nullable=True) # أسبوعي، شهري، مخصص
    visit_day = db.Column(db.String(20), nullable=True) # السبت، الأحد..
    start_date = db.Column(db.Date, nullable=True)
    custom_days = db.Column(db.Integer, nullable=True) # عدد الأيام للجدولة المخصصة
    
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    shops = db.relationship('Shop', backref='zone', lazy=True)

# ================= المستخدمين =================
class Driver(db.Model):
    __tablename__ = 'drivers'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    can_allow_debt = db.Column(db.Boolean, nullable=False, default=False)
    max_debt_limit = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

# ================= المنتجات (المرونة التامة) =================
class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    base_name = db.Column(db.String(150), nullable=False)
    brand = db.Column(db.String(100), nullable=True)
    category = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    variants = db.relationship('ProductVariant', backref='product', lazy=True)

class ProductVariant(db.Model):
    __tablename__ = 'product_variants'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_name = db.Column(db.String(200), nullable=False)
    flavor = db.Column(db.String(50), nullable=True)
    size = db.Column(db.String(50), nullable=True)
    sku = db.Column(db.String(100), nullable=True, unique=True)
    packs_per_carton = db.Column(db.Integer, nullable=False, default=50) # حجم الكرتونة خاص بكل منتج
    price_per_carton = db.Column(db.Numeric(10, 2), nullable=False)
    price_per_pack = db.Column(db.Numeric(10, 2), nullable=True) # سعر الحبة للفرط
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True) # +++ فهرس لتسريع جلب المنتجات المتاحة فقط
    default_max_samples_per_day = db.Column(db.Integer, nullable=False, default=0) # سقف العينات اليومي المسموح للمندوب


# ================= إدارة الأسطول والسيارات =================
class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    id = db.Column(db.Integer, primary_key=True)
    plate_number = db.Column(db.String(20), unique=True, nullable=False)
    vehicle_type = db.Column(db.String(50), nullable=True) # نوع الباص وسعته
    current_mileage = db.Column(db.Integer, nullable=False, default=0)
    next_oil_change = db.Column(db.Integer, nullable=True)
    license_expiry_date = db.Column(db.Date, nullable=True)
    maintenance_status = db.Column(db.String(50), nullable=False, default='Active') # Active, In_Maintenance
    is_active = db.Column(db.Boolean, nullable=False, default=True)

class VehicleLoad(db.Model):
    # مسودة الحمولة التي يجهزها أمين المستودع ليلاً
    __tablename__ = 'vehicle_loads'
    __table_args__ = (db.UniqueConstraint('vehicle_id', 'product_variant_id', name='uq_vehicle_variant_load'),) # +++ قيد الفرادة
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False, index=True) # +++ فهرس
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0) # الوحدة الأساسية فقط
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)) # +++ توحيد التواريخ

    # +++ الدرع المعماري: تعريف العلاقة لكي تعمل دوال الجلب السريعة (joinedload) +++
    product_variant = db.relationship('ProductVariant')

# ================= خطوط السير اليومية (التوزيع) =================
class DispatchRoute(db.Model):
    __tablename__ = 'dispatch_routes'
    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey('zones.id'), nullable=False, index=True) # +++ فهرس المنطقة
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=True, index=True) # +++ فهرس المندوب
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=True, index=True)
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=True, index=True)
    dispatch_date = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date(), index=True)
    status = db.Column(db.String(50), nullable=False, default='waiting', index=True) # +++ فهرس الحالة (مهم جداً للسرعة)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    zone = db.relationship('Zone')
    driver = db.relationship('Driver')
    vehicle = db.relationship('Vehicle')

# ================= الطلبات والنواقص (Shortages) =================
class ShortageRequest(db.Model):
    __tablename__ = 'shortage_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey('zones.id'), nullable=False, index=True)
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=True, index=True) 
    
    product_name = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), default='pending', index=True)
    wait_time = db.Column(db.String(50), default='الآن')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # العلاقات (Relationships)
    zone = db.relationship('Zone')
    shop = db.relationship('Shop')
    driver = db.relationship('Driver')
    
# ================= العروض والمحلات =================
class OfferRule(db.Model):
    __tablename__ = 'offer_rules'
    id = db.Column(db.Integer, primary_key=True)
    threshold_quantity = db.Column(db.Integer, nullable=False) # الكمية المطلوبة بالوحدة الأساسية
    offer_type = db.Column(db.String(50), nullable=False)
    bonus_quantity = db.Column(db.Integer, nullable=False, default=0) # البونص المجاني بالوحدة الأساسية
    discount_value = db.Column(db.Float, nullable=False, default=0.0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

class Shop(db.Model):
    __tablename__ = 'shops'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.Text, nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)
    zone_id = db.Column(db.Integer, db.ForeignKey('zones.id', ondelete='SET NULL'), nullable=True, index=True) # +++ حماية اليُتم والفهرسة
    current_balance = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    max_debt_limit = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    added_by_driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    notes = db.Column(db.Text, nullable=True)
    location_link = db.Column(db.String(500), nullable=True)
    sequence = db.Column(db.Integer, nullable=True, default=0) # رقم الترتيب داخل المنطقة
    is_archived = db.Column(db.Boolean, nullable=False, default=False) # سلة المحذوفات

    visits = db.relationship('Visit', backref='shop', lazy='select') # +++ التخلص من dynamic للسماح بالـ joinedload ومنع N+1

# ================= الجلسة والجرد المفصل =================
class WorkSession(db.Model):
    __tablename__ = 'work_sessions'
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False, index=True)
    start_time = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    end_time = db.Column(db.DateTime, nullable=True, index=True)
    session_date = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date(), index=True)
    start_latitude = db.Column(db.Float, nullable=True)
    start_longitude = db.Column(db.Float, nullable=True)
    
    # +++ الحقول الجديدة: الضوء الأخضر والاستراحة +++
    is_authorized_to_sell = db.Column(db.Boolean, nullable=False, default=False) 
    break_start_time = db.Column(db.DateTime, nullable=True)
    break_end_time = db.Column(db.DateTime, nullable=True)
    
    # +++ حقل الاعتماد الإداري للتسوية +++
    is_settled = db.Column(db.Boolean, nullable=False, default=False, index=True)
    # ++++++++++++++++++++++++++++++++++++++++++++++
    driver = db.relationship('Driver', backref=db.backref('work_sessions', lazy=True))
    inventory = db.relationship('SessionInventory', backref='work_session', lazy=True) # ربط الجلسة بالمخزونن

class SessionInventory(db.Model):
    __tablename__ = 'session_inventory'
    __table_args__ = (db.UniqueConstraint('work_session_id', 'product_variant_id', name='uq_session_variant_inv'),) # +++ قيد الفرادة للعهدة
    id = db.Column(db.Integer, primary_key=True)
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=False, index=True) # +++ فهرس
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=False, index=True) # +++ فهرس
    starting_quantity = db.Column(db.Integer, nullable=False, default=0)
    current_remaining_quantity = db.Column(db.Integer, nullable=False, default=0)
    product_variant = db.relationship('ProductVariant')


# ================= تفاصيل الفاتورة (سلة الزيارة) =================
# هذا الجدول يربط الزيارة الواحدة بعدة منتجات (كراتين وحبات) مع حفظ أسعار البيع اللحظية
class VisitItem(db.Model):
    __tablename__ = 'visit_items'
    id = db.Column(db.Integer, primary_key=True)
    # إضافة index=True لتسريع البحث عن محتويات زيارة معينة ومنع N+1
    visit_id = db.Column(db.Integer, db.ForeignKey('visits.id'), nullable=False, index=True)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False, index=True)   
    # الكمية المباعة بالوحدة الأساسية
    quantity = db.Column(db.Integer, nullable=False, default=0)  
    # +++ الدرج الجديد لحفظ حبات الفرط وعدم ضياعها +++
    packs_quantity = db.Column(db.Integer, nullable=False, default=0)
    # البونص بالوحدة الأساسية
    bonus_quantity = db.Column(db.Integer, nullable=False, default=0)
    # الأسعار وقت البيع للوحدة الأساسية
    price_per_unit_at_sale = db.Column(db.Numeric(10, 2), nullable=True)
    total_price = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    product_variant = db.relationship('ProductVariant')
    # العينات المجانية بالوحدة الأساسية
    sample_quantity = db.Column(db.Integer, nullable=False, default=0)

# ================= الزيارات =================
class Visit(db.Model):
    __tablename__ = 'visits'
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=True, index=True)
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=False, index=True)
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=True, index=True)
    visit_timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True) # +++ فهرس للتقارير الزمنية
    outcome = db.Column(db.String(50), nullable=True, default='Pending', index=True)
    amount_before_tax_and_discount = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    discount_applied = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    tax_percentage_applied = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    tax_amount = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    final_amount_due = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    cash_collected = db.Column(db.Numeric(10, 2), nullable=True, default=0.0)
    debt_paid = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    no_sale_reason = db.Column(db.String(200), nullable=True)
    shop_balance_before = db.Column(db.Numeric(10, 2), nullable=True)
    shop_balance_after = db.Column(db.Numeric(10, 2), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    sequence = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(50), nullable=False, default='Pending', index=True) # +++ فهرس لتسريع عمليات الفرز وحساب الإنجاز
    notes = db.Column(db.Text, nullable=True)
    tax_qr_code = db.Column(db.String(500), nullable=True)
    is_emergency = db.Column(db.Boolean, nullable=False, default=False) # لفرز الطلبات الطارئة بشاشة منفصلة
    
    work_session = db.relationship('WorkSession', backref=db.backref('visits', lazy='dynamic'))
    driver = db.relationship('Driver', backref=db.backref('visits', lazy='dynamic'))
    items = db.relationship('VisitItem', backref='visit', lazy='select', cascade="all, delete-orphan")


    # ================= المرتجعات والتوالف =================
class VisitReturn(db.Model):
    __tablename__ = 'visit_returns'
    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey('visits.id'), nullable=False, index=True)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False, index=True)
    
    # الكمية المستلمة كتالف بالوحدة الأساسية
    quantity = db.Column(db.Integer, nullable=False, default=0)
    
    # تصنيف التالف (مثال: 'Factory_Defect' للمصنع، 'Expired' للشركة)
    return_type = db.Column(db.String(50), nullable=False) 
    reason = db.Column(db.Text, nullable=True) # ملاحظات إضافية
    
    product_variant = db.relationship('ProductVariant')
    visit = db.relationship('Visit', backref=db.backref('returns', lazy='select', cascade="all, delete-orphan")) # +++ تم تغيير dynamic إلى select لدعم الـ joinedload ومنع الانهيار +++


# ================= سجل التدقيق للعمليات الجماعية (Audit Log) =================
# الهدف: توثيق كل عمليات استيراد المحلات الجماعية (من ملفات أو لصق).
# الفائدة: يحمي النظام بتسجيل (الموظف المسؤول، تاريخ الرفع، المنطقة، وعدد السجلات الناجحة أو الفاشلة) لتتبع الأخطاء ومنع التلاعب.
class ImportLog(db.Model):
    __tablename__ = 'import_logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False)
    zone_id = db.Column(db.Integer, db.ForeignKey('zones.id'), nullable=False)
    file_name = db.Column(db.String(255), nullable=True) # اسم ملف الإكسل أو "إدخال يدوي"
    total_records = db.Column(db.Integer, nullable=False, default=0)
    success_count = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(50), nullable=False) # 'Success', 'Failed'
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    admin = db.relationship('Driver')
    zone = db.relationship('Zone')



# ================= سجل حركات وتدقيق المخزون (Inventory Ledger) =================
# الهدف: توثيق العجز والزيادة وأي تسوية تتم على سيارة المندوب لحماية الجرد المالي.
class InventoryLedger(db.Model):
    __tablename__ = 'inventory_ledgers'
    id = db.Column(db.Integer, primary_key=True)
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=True)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=False)
    
    transaction_type = db.Column(db.String(50), nullable=False) # 'Deficit' (عجز), 'Surplus' (زيادة), 'Adjustment' (تعديل)
    expected_quantity = db.Column(db.Integer, nullable=False)   # الكمية التي كان يجب أن تكون في السيارة
    actual_quantity = db.Column(db.Integer, nullable=False)     # الكمية الفعلية التي جردها المحاسب
    difference = db.Column(db.Integer, nullable=False)          # الفارق (سالب للعجز، موجب للزيادة)
    
    admin_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False) # المحاسب/المشرف الذي قام بالتسوية
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes = db.Column(db.Text, nullable=True)

    product_variant = db.relationship('ProductVariant')
    driver = db.relationship('Driver', foreign_keys=[driver_id])
    admin = db.relationship('Driver', foreign_keys=[admin_id])


# ================= سجل النظام الشامل (System Audit Log) =================
# يسجل الحركات الحساسة (مثل التراجع عن إنهاء العمل) لمنع التلاعب
class SystemAuditLog(db.Model):
    __tablename__ = 'system_audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False, index=True)
    target_id = db.Column(db.String(100), nullable=False, index=True) # رقم الجلسة أو المندوب
    action_type = db.Column(db.String(100), nullable=False, index=True) # مثال: UNDO_END_WORK
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    admin = db.relationship('Driver', foreign_keys=[admin_id])

# ================= أرشيف الاستراحات (Work Break Log) =================
# يحل مشكلة ضياع الاستراحة الأولى إذا قام المندوب باستراحة ثانية
class WorkBreakLog(db.Model):
    __tablename__ = 'work_break_logs'
    id = db.Column(db.Integer, primary_key=True)
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=False, index=True)
    break_start = db.Column(db.DateTime, nullable=False)
    break_end = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True) # يحسب تلقائياً عند الإنهاء

    work_session = db.relationship('WorkSession', backref=db.backref('break_logs', lazy='dynamic'))

# =========================================
# جدول الحوالات المعلقة (تأكيد استلام منتصف اليوم)
# =========================================
class InventoryTransfer(db.Model):
    __tablename__ = 'inventory_transfers'
    
    id = db.Column(db.Integer, primary_key=True)
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id', ondelete='CASCADE'), nullable=False)
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id', ondelete='CASCADE'), nullable=False)
    
    quantity_packs = db.Column(db.Integer, nullable=False) # الكمية بالحبات (موجب للزيادة، سالب للسحب)
    status = db.Column(db.String(20), nullable=False, default='pending') # pending, accepted, rejected
    
    admin_id = db.Column(db.Integer, db.ForeignKey('drivers.id', ondelete='SET NULL'), nullable=True) # المسؤول الذي أرسل التعديل
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # العلاقات
    product_variant = db.relationship('ProductVariant')
    work_session = db.relationship('WorkSession', backref=db.backref('transfers', lazy='select', cascade="all, delete-orphan"))