from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Numeric, Float, Text, ForeignKey, CheckConstraint, UniqueConstraint, Index, MetaData, text, Table, ForeignKeyConstraint
from sqlalchemy.orm import relationship, declarative_base, backref
from datetime import datetime, timezone
from decimal import Decimal
import bcrypt

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
# 0. الكيانات السيادية للمنصة (System-Owned Tables) - لا تتبع لأي شركة[cite: 9]
# =================================================================================
class PlatformAdmin(Base):
    """آلهة المنصة (God Mode): حساب منفصل لإدارة الشركات والاشتراكات[cite: 9]"""
    __tablename__ = 'platform_admins'
    id            = Column(Integer, primary_key=True)
    username      = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime, nullable=False, default=utc_now)

class UOM(Base):
    """وحدات القياس العالمية (Pack, Box, Pallet)[cite: 9]"""
    __tablename__ = 'uom'
    id   = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    code = Column(String(20), nullable=False, unique=True)

class LoginAttempt(Base):
    """سجل محاولات الدخول (نظام حماية Brute-Force السيادي)"""
    __tablename__ = 'login_attempts'
    id = Column(Integer, primary_key=True)
    ip_address = Column(String(50), nullable=False, index=True)
    username_attempted = Column(String(80), nullable=True)
    company_code_attempted = Column(String(50), nullable=True)
    is_successful = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    
# =================================================================================
# 0.1 كيانات الـ SaaS الأساسية (Tenant-Owned Core)[cite: 9]
# =================================================================================
class Company(Base):
    """الكيان المستأجر (Tenant): السور الفولاذي الذي يعزل البيانات[cite: 9]"""
    __tablename__ = 'companies'
    __table_args__ = (CheckConstraint("subscription_status IN ('active', 'suspended', 'expired', 'trial')", name='company_sub_status'),)
    id                  = Column(Integer, primary_key=True)
    name                = Column(String(150), nullable=False)
    company_code        = Column(String(50), unique=True, nullable=False, index=True)
    is_active           = Column(Boolean, nullable=False, default=True)
    subscription_status = Column(String(50), nullable=False, default='active')
    currency_code       = Column(String(10), nullable=False, default='JOD')
    timezone            = Column(String(50), nullable=False, default='Asia/Amman')
    created_at          = Column(DateTime, nullable=False, default=utc_now)

class Branch(Base):
    """التقسيم الإداري لفروع الشركة[cite: 9]"""
    __tablename__ = 'branches'
    __table_args__ = (
        UniqueConstraint('company_id', 'branch_code', name='uq_company_branch_code'),
        UniqueConstraint('company_id', 'id', name='uq_branches_company_id'), # +++ Parent Guard +++
    )
    id         = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    name       = Column(String(150), nullable=False)
    branch_code= Column(String(50), nullable=False)
    is_active  = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    company = relationship('Company', backref='branches', lazy='raise')

# =================================================================================
# 0.2 نظام الصلاحيات الديناميكي (RBAC)[cite: 9]
# =================================================================================
class Role(Base):
    __tablename__ = 'roles'
    __table_args__ = (
        UniqueConstraint('company_id', 'name', name='uq_company_role_name'),
        UniqueConstraint('company_id', 'id', name='uq_roles_company_id'), # +++ Parent Guard +++
    )
    id         = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    name       = Column(String(100), nullable=False)
    is_system_role = Column(Boolean, nullable=False, default=False)

class Permission(Base):
    __tablename__ = 'permissions'
    id   = Column(Integer, primary_key=True)
    code = Column(String(100), unique=True, nullable=False)

role_permissions = Table('role_permissions', Base.metadata,
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)


class UserRole(Base):
    """ربط المستخدم بالدور الخاص به[cite: 9]"""
    __tablename__ = 'user_roles'
    __table_args__ = (
        UniqueConstraint('company_id', 'driver_id', 'role_id', name='uq_user_role_tenant'),
        ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['company_id', 'role_id'], ['roles.company_id', 'roles.id'], ondelete='CASCADE'),
    )
    id         = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True) # +++ تمت إضافته (Blocker 2) +++
    driver_id  = Column(Integer, nullable=False, index=True)
    role_id    = Column(Integer, nullable=False, index=True)

class UserLocationAccess(Base):
    """من يرى أو ينقل من أي مستودع بدقة"""
    __tablename__ = 'user_location_access'
    __table_args__ = (
        UniqueConstraint('company_id', 'driver_id', 'location_id', 'role_id', name='uq_user_loc_access_tenant'),
        ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['company_id', 'role_id'], ['roles.company_id', 'roles.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['company_id', 'location_id'], ['inventory_locations.company_id', 'inventory_locations.id'], ondelete='CASCADE'),
    )
    id          = Column(Integer, primary_key=True)
    company_id  = Column(Integer, nullable=False, index=True)
    driver_id   = Column(Integer, nullable=False, index=True)
    location_id = Column(Integer, nullable=False, index=True)
    role_id     = Column(Integer, nullable=False, index=True)


# =================================================================================
# ① الإعدادات العامة للنظام
# =================================================================================
class SystemSetting(Base):
    __tablename__ = 'system_settings'
    __table_args__ = (UniqueConstraint('company_id', 'setting_key', name='uq_company_setting_key'),) # +++ تحويل الـ Unique Constraint[cite: 9] +++
    id            = Column(Integer, primary_key=True)
    company_id    = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True) # +++ زرع الهوية[cite: 9] +++
    setting_key   = Column(String(50), nullable=False)
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
        UniqueConstraint('company_id', 'name', 'governorate_id', name='uq_company_zone_gov'),
        Index('idx_uq_zone_company_name_null_gov', 'company_id', 'name', unique=True, postgresql_where=text("governorate_id IS NULL")),
        UniqueConstraint('company_id', 'id', name='uq_zones_company_id'), # +++ Parent Guard +++
    )
    id              = Column(Integer, primary_key=True)
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
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
# =================================================================================
class Driver(Base):
    __tablename__ = 'drivers'
    __table_args__ = (
        UniqueConstraint('company_id', 'username', name='uq_company_username'),
        UniqueConstraint('company_id', 'id', name='uq_drivers_company_id'), # +++ Parent Guard +++
    )
    id            = Column(Integer, primary_key=True)
    company_id    = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True) # +++ زرع الهوية[cite: 9] +++
    username      = Column(String(80), nullable=False)
    password_hash = Column(String(128), nullable=False)
    full_name     = Column(String(120), nullable=False)
    phone_number  = Column(String(20),  nullable=True)
    is_active     = Column(Boolean,     nullable=False, default=True, server_default='true')
    is_admin      = Column(Boolean,     nullable=False, default=False, server_default='false')
    can_allow_debt  = Column(Boolean,       nullable=False, default=False, server_default='false')
    # +++ الدرع المحاسبي: حماية الدقة من تآكل الـ Float ومنع سقف الدين من الانقلاب لقيمة سالبة +++
    max_debt_limit  = Column(Numeric(12, 3), CheckConstraint('max_debt_limit >= 0', name='chk_driver_max_debt'), nullable=False, default=Decimal('0.000'), server_default='0.000')
    created_at      = Column(DateTime,      nullable=False, default=utc_now)  # FIX ①

    def set_password(self, raw_password: str):
        """تشفير كلمة المرور بناءً على آلية bcrypt المستخدمة في نظام المصادقة"""
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(raw_password.encode('utf-8'), salt).decode('utf-8')



# =================================================================================
# ④ المنتجات (Product → ProductVariant)
# =================================================================================
class Product(Base):
    __tablename__ = 'products'
    __table_args__ = (
        UniqueConstraint('company_id', 'base_name', name='uq_company_base_name'),
        UniqueConstraint('company_id', 'id', name='uq_products_company_id'), # +++ Parent Guard +++
    )
    id         = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True) # +++ زرع الهوية[cite: 9] +++
    base_name  = Column(String(150), nullable=False)
    brand      = Column(String(100), nullable=True)
    category   = Column(String(100), nullable=True)
    created_at = Column(DateTime,   nullable=False, default=utc_now)  # FIX ①

    variants = relationship('ProductVariant', backref='product', lazy='raise')


class UOMConversion(Base):
    """معاملات التحويل بين الوحدات لكل منتج[cite: 9]"""
    __tablename__ = 'uom_conversions'
    __table_args__ = (UniqueConstraint('company_id', 'product_variant_id', 'from_uom_id', 'to_uom_id', name='uq_uom_conversion'),)
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='CASCADE'), nullable=False)
    from_uom_id = Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False)
    to_uom_id   = Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False)
    conversion_factor = Column(Numeric(10, 4), CheckConstraint('conversion_factor > 0', name='chk_positive_conversion'), nullable=False)

class ProductVariant(Base):
    __tablename__ = 'product_variants'
    __table_args__ = (
        UniqueConstraint('company_id', 'sku', name='uq_company_sku'),
        UniqueConstraint('company_id', 'id', name='uq_product_variants_company_id'), # +++ Parent Guard +++
    )
    id         = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True) # +++ زرع الهوية[cite: 9] +++
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    base_uom_id= Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False) # +++ NOT NULL الإلزامي +++

    variant_name    = Column(String(200), nullable=False)
    flavor          = Column(String(50),  nullable=True)
    size            = Column(String(50),  nullable=True)
    sku             = Column(String(100), nullable=True)
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
    __table_args__ = (
        UniqueConstraint('company_id', 'plate_number', name='uq_company_plate_number'),
        UniqueConstraint('company_id', 'id', name='uq_vehicles_company_id'), # +++ Parent Guard +++
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    plate_number       = Column(String(20), nullable=False)
    vehicle_type       = Column(String(50), nullable=True)
    current_mileage    = Column(Integer,    nullable=False, default=0)
    next_oil_change    = Column(Integer,    nullable=True)
    license_expiry_date = Column(Date,      nullable=True)
    maintenance_status = Column(String(50), nullable=False, default='Active')  # Active | In_Maintenance
    is_active          = Column(Boolean,    nullable=False, default=True)


# =================================================================================
# ⑥ جلسات العمل (المحرك الموحد: العهدة أصبحت تدار عبر InventoryBalance لموقع السيارة)
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
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    vehicle_id         = Column(Integer, ForeignKey('vehicles.id'),         nullable=False) # تم نسف الـ index المكرر لحماية الـ RAM
    product_variant_id = Column(Integer, ForeignKey('product_variants.id'), nullable=False)
    quantity           = Column(Integer, CheckConstraint('quantity >= 0', name='chk_vload_qty'), nullable=False, default=0)
    updated_at         = Column(DateTime, nullable=False, default=utc_now)  # FIX ①

    product_variant = relationship('ProductVariant', lazy='raise')

# =================================================================================
class WorkSession(Base):
    __tablename__ = 'work_sessions'
    __table_args__ = (
        Index('ix_ws_driver_unsettled', 'driver_id', 'is_settled', 'end_time'),
        Index('uq_active_session_per_driver', 'company_id', 'driver_id', unique=True, postgresql_where=text("end_time IS NULL")),
        UniqueConstraint('company_id', 'id', name='uq_work_sessions_company_id'),
    )
    id           = Column(Integer, primary_key=True)
    company_id   = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    driver_id    = Column(Integer, ForeignKey('drivers.id'), nullable=False, index=True)
    start_time   = Column(DateTime, nullable=False, default=utc_now)
    end_time     = Column(DateTime, nullable=True,  index=True)
    session_date = Column(Date,     nullable=False, default=lambda: utc_now().date(), index=True)
    start_latitude  = Column(Numeric(10, 7), nullable=True)
    start_longitude = Column(Numeric(10, 7), nullable=True)

    is_authorized_to_sell = Column(Boolean,  nullable=False, default=False)
    break_start_time      = Column(DateTime, nullable=True)
    break_end_time        = Column(DateTime, nullable=True)
    is_settled            = Column(Boolean,  nullable=False, default=False, index=True)

    driver = relationship('Driver', backref=backref('work_sessions', lazy='raise'))


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
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    work_session_id    = Column(Integer, ForeignKey('work_sessions.id'),    nullable=False) # تمت إزالة الـ index المكرر بسبب الـ UniqueConstraint
    product_variant_id = Column(Integer, ForeignKey('product_variants.id'), nullable=False, index=True)
    
    # +++  (حرج 3): فصل حمولة الصباح عن التعديلات لمنع تدمير تقارير الجرد +++
    starting_quantity          = Column(Integer, nullable=False, default=0)
    net_transfers              = Column(Integer, nullable=False, default=0) # موجب للحوالة المستلمة، سالب للحوالة المسحوبة
    current_remaining_quantity = Column(Integer, CheckConstraint('current_remaining_quantity >= 0', name='chk_positive_inventory'), nullable=False, default=0)

    product_variant = relationship('ProductVariant', lazy='raise')

# =================================================================================
# ⑦ المحلات
# =================================================================================
class Shop(Base):
    __tablename__ = 'shops'
    __table_args__ = (UniqueConstraint('company_id', 'id', name='uq_shops_company_id'),) # +++ Parent Guard +++
    id             = Column(Integer, primary_key=True)
    company_id     = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    name           = Column(String(150), nullable=False)
    address        = Column(Text,        nullable=True)
    latitude       = Column(Numeric(10, 7), nullable=True)
    longitude      = Column(Numeric(10, 7), nullable=True)
    phone_number   = Column(String(20),  nullable=True)
    contact_person = Column(String(100), nullable=True)
    zone_id        = Column(Integer, ForeignKey('zones.id', ondelete='SET NULL'),
                               nullable=True, index=True)
    # +++  حماية الـ Decimal، فرض server_default، وتطبيق سياسة (SET NULL) لحماية الداتابيز +++
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
    __table_args__ = (
        # +++ الدرع الفولاذي: دمج company_id مع الفهارس الجزئية لمنع اختلاط الخطوط بين الشركات +++
        Index('uq_active_route_per_driver', 'company_id', 'driver_id', unique=True, postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
        Index('uq_active_route_per_vehicle', 'company_id', 'vehicle_id', unique=True, postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
        Index('uq_active_route_per_zone', 'company_id', 'zone_id', unique=True, postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
    )
    
    id              = Column(Integer, primary_key=True)
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    zone_id         = Column(Integer, ForeignKey('zones.id'),         nullable=False, index=True)
    driver_id       = Column(Integer, ForeignKey('drivers.id'),       nullable=True,  index=True)
    vehicle_id      = Column(Integer, ForeignKey('vehicles.id'),      nullable=True,  index=True)
    work_session_id = Column(Integer, ForeignKey('work_sessions.id'), nullable=True,  index=True)
    # +++  (Issue 3): توحيد الزمن لنسف الانفصام الزمني +++
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
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
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
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
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
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
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
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
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
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    # +++  (G-01): ربط العرض بمنتج معين. (Null تعني عرض عام لجميع المنتجات) +++
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
    company_id    = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
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
# (تمت إزالة InventoryLedger: استُبدل بدفتر الأستاذ الموحد InventoryMovement)


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
    # +++  (G-04): إجبار الداتابيز على حساب الفرق بدقة لمنع التلاعب المالي +++
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
    company_id  = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    # +++ سجل رقابي غير قابل لتغيير هوية الفاعل: المستخدمون الذين لهم سجل يُعطّلون ولا يُحذفون. +++
    admin_id    = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=True, index=True)
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
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    work_session_id = Column(Integer, ForeignKey('work_sessions.id'), nullable=False, index=True)
    break_start     = Column(DateTime, nullable=False)
    break_end       = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)  # يُحسب تلقائياً عند الإنهاء

    work_session = relationship('WorkSession', backref=backref('break_logs', lazy='raise'))


# =================================================================================
# ⑯ الحوالات المعلقة (المصافحة - Handshake)
# عنق الزجاجة الذي يمنع دخول أي بضاعة للعهدة إلا بموافقة المندوب
# =================================================================================
# (تمت إزالة InventoryTransfer و MainWarehouse: استُبدلا بـ InventoryTransferHeader/Line و InventoryBalance)


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
# ⑯ الحوالات المعلقة (المصافحة - Handshake)
# عنق الزجاجة الذي يمنع دخول أي بضاعة للعهدة إلا بموافقة المندوب
# =================================================================================
class InventoryTransfer(Base):
    __tablename__ = 'inventory_transfers'
    __table_args__ = (
        Index('uq_pending_transfer', 'company_id', 'work_session_id', 'product_variant_id', unique=True, postgresql_where=text("status = 'pending'")),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
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
# (تمت إزالة WarehouseLedger: استُبدل بدفتر الأستاذ الموحد للحركات InventoryMovement)

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


# =================================================================================
# [المرحلة الثالثة والرابعة] المحرك الموحد للمخزون ودورة حياة الصلاحية (Batches)
# =================================================================================
class ProductBatch(Base):
    """جدول الدفعات (لإدارة تواريخ الإنتاج والصلاحية ونظام FEFO)"""
    __tablename__ = 'product_batches'
    __table_args__ = (
        UniqueConstraint('company_id', 'product_variant_id', 'batch_number', name='uq_product_batch_number'),
        UniqueConstraint('company_id', 'id', name='uq_product_batches_company_id'), # +++ Parent Guard +++
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False, index=True)
    batch_number       = Column(String(100), nullable=False, index=True)
    production_date    = Column(Date, nullable=True)
    expiry_date        = Column(Date, nullable=False, index=True) # إلزامي لنظام FEFO
    is_active          = Column(Boolean, nullable=False, default=True)
    created_at         = Column(DateTime, nullable=False, default=utc_now)

class OverrideReason(Base):
    """قائمة أسباب تجاوز نظام FEFO للمشرفين"""
    __tablename__ = 'override_reasons'
    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_override_reason_code'),
    )
    id          = Column(Integer, primary_key=True)
    company_id  = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    code        = Column(String(50), nullable=False)
    description = Column(String(255), nullable=False)
    is_active   = Column(Boolean, nullable=False, default=True)
    
class InventoryLocation(Base):
    """سجل المواقع: يوحد المستودعات، سيارات المناديب، ومناطق العبور"""
    __tablename__ = 'inventory_locations'
    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_inv_loc_company_code'),
        UniqueConstraint('company_id', 'id', name='uq_inventory_locations_company_id'), # +++ Parent Guard +++
        CheckConstraint("location_type IN ('WAREHOUSE', 'VEHICLE', 'IN_TRANSIT', 'SCRAP')", name='chk_inv_loc_type'),
    )
    id            = Column(Integer, primary_key=True)
    company_id    = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    branch_id     = Column(Integer, ForeignKey('branches.id', ondelete='CASCADE'), nullable=True, index=True)
    name          = Column(String(150), nullable=False)
    code          = Column(String(50),  nullable=False)
    location_type = Column(String(50),  nullable=False, index=True) 
    driver_id     = Column(Integer, ForeignKey('drivers.id', ondelete='SET NULL'), nullable=True, index=True)
    vehicle_id    = Column(Integer, ForeignKey('vehicles.id', ondelete='SET NULL'), nullable=True, index=True) # +++ لربط الموقع بالسيارة الفعلية +++
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime, nullable=False, default=utc_now)

class InventoryBalance(Base):
    """مصدر الحقيقة الوحيد للأرصدة في المحرك الموحد"""
    __tablename__ = 'inventory_balances'
    __table_args__ = (
        UniqueConstraint('company_id', 'location_id', 'product_variant_id', 'batch_id', 'stock_status', name='uq_inv_balance_core'),
        UniqueConstraint('company_id', 'id', name='uq_inventory_balances_company_id'),
        ForeignKeyConstraint(['company_id', 'location_id'], ['inventory_locations.company_id', 'inventory_locations.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['company_id', 'batch_id'], ['product_batches.company_id', 'product_batches.id'], ondelete='RESTRICT'),
        CheckConstraint("stock_status IN ('AVAILABLE', 'RESERVED', 'DAMAGED')", name='chk_inv_bal_status'),
        Index('ix_inv_balance_search', 'company_id', 'location_id', 'product_variant_id', 'stock_status'),
        Index('ix_inv_balance_fefo', 'company_id', 'product_variant_id', 'batch_id'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    location_id        = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    batch_id           = Column(Integer, nullable=False, index=True)
    stock_status       = Column(String(50), nullable=False, default='AVAILABLE') 
    
    # +++ فصل الأرصدة لدعم الحوالات المعلقة (IN_TRANSIT) بناءً على خطتك +++
    on_hand_quantity   = Column(Integer, CheckConstraint('on_hand_quantity >= 0', name='chk_inv_bal_onhand_qty'), nullable=False, default=0)
    reserved_quantity  = Column(Integer, CheckConstraint('reserved_quantity >= 0', name='chk_inv_bal_res_qty'), nullable=False, default=0)
    
    last_updated       = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

class InventoryMovement(Base):
    """دفتر الأستاذ للحركات: يوثق كل إبرة تتحرك داخل النظام لمنع التلاعب المحاسبي"""
    __tablename__ = 'inventory_movements'
    __table_args__ = (
        UniqueConstraint('company_id', 'idempotency_key', name='uq_inv_movement_idempotency'),
        UniqueConstraint('company_id', 'id', name='uq_inventory_movements_company_id'), # +++ Parent Guard +++
        Index('ix_inv_movement_locations', 'company_id', 'source_location_id', 'destination_location_id'),
    )
    id                      = Column(Integer, primary_key=True)
    company_id              = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    performed_by            = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=False)
    source_location_id      = Column(Integer, ForeignKey('inventory_locations.id', ondelete='RESTRICT'), nullable=True, index=True)
    destination_location_id = Column(Integer, ForeignKey('inventory_locations.id', ondelete='RESTRICT'), nullable=True, index=True)
    product_variant_id      = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False, index=True)
    batch_id                = Column(Integer, ForeignKey('product_batches.id', ondelete='RESTRICT'), nullable=True, index=True)
    quantity                = Column(Integer, CheckConstraint('quantity > 0', name='chk_inv_movement_qty_positive'), nullable=False)
    reference_type          = Column(String(50), nullable=False, index=True) 
    reference_id            = Column(String(100), nullable=False, index=True)
    idempotency_key         = Column(String(100), nullable=False)
    notes                   = Column(Text, nullable=True)
    created_at              = Column(DateTime, nullable=False, default=utc_now)


# =================================================================================
# [المرحلة الخامسة] هيكلة الحوالات الصارمة (Header & Line Architecture)
# =================================================================================
class InventoryTransferHeader(Base):
    """رأس الحوالة: يتحكم بحالة النقل بين المستودعات والسيارات"""
    __tablename__ = 'inventory_transfer_headers'
    __table_args__ = (
        UniqueConstraint('company_id', 'reference_number', name='uq_transfer_header_ref'),
        UniqueConstraint('company_id', 'id', name='uq_transfer_headers_company_id'),
        # +++ عقد دورة الحياة الصارمة: فرض الحالات المسموحة على مستوى محرك قاعدة البيانات +++
        CheckConstraint("status IN ('DRAFT', 'PENDING', 'ACCEPTED', 'REJECTED', 'POSTED', 'CANCELLED')", name='chk_transfer_header_status'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    reference_number   = Column(String(100), nullable=False, index=True)
    source_location_id = Column(Integer, ForeignKey('inventory_locations.id', ondelete='RESTRICT'), nullable=False, index=True)
    destination_location_id = Column(Integer, ForeignKey('inventory_locations.id', ondelete='RESTRICT'), nullable=False, index=True)
    
    # +++ دورة الحياة الصارمة (خطتك الشاملة): DRAFT, PENDING, ACCEPTED, REJECTED, POSTED, CANCELLED +++
    status             = Column(String(50), nullable=False, default='PENDING', index=True) 
    
    dispatched_by      = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=False)
    received_by        = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=True)
    created_at         = Column(DateTime, nullable=False, default=utc_now)
    updated_at         = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

class InventoryTransferLine(Base):
    """تفاصيل الحوالة: يمنع حشر الداتا ويوثق الدفعات المحولة"""
    __tablename__ = 'inventory_transfer_lines'
    __table_args__ = (
        UniqueConstraint('transfer_header_id', 'product_variant_id', 'batch_id', name='uq_transfer_line_item'),
        UniqueConstraint('company_id', 'id', name='uq_inventory_transfer_lines_company_id'), # +++ Parent Guard +++
        # +++ Cross-Tenant FK Guard: خط الحوالة لا يمكن أن يتبع رأس حوالة لشركة أخرى +++
        ForeignKeyConstraint(['company_id', 'transfer_header_id'],
                             ['inventory_transfer_headers.company_id', 'inventory_transfer_headers.id'],
                             ondelete='CASCADE', name='fk_transfer_lines_tenant_header'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, nullable=False, index=True) # +++ زرع الهوية (بند الخطة: كل الجداول) +++
    transfer_header_id = Column(Integer, nullable=False, index=True) # الربط المرجعي يتم عبر الـ FK المركب أعلاه (fk_transfer_lines_tenant_header)
    product_variant_id = Column(Integer, ForeignKey('product_variants.id', ondelete='RESTRICT'), nullable=False)
    batch_id           = Column(Integer, ForeignKey('product_batches.id', ondelete='RESTRICT'), nullable=True)
    quantity           = Column(Integer, CheckConstraint('quantity > 0', name='chk_transfer_line_qty'), nullable=False)


# =================================================================================
# [المرحلة السادسة] محرك الجرد القانوني (Stocktake Engine)
# =================================================================================
class StocktakeSession(Base):
    """جلسة الجرد: تدير دورة الحياة وتفصل بين Snapshot المخزون ومحاولات العد."""
    __tablename__ = 'stocktake_sessions'
    __table_args__ = (
        UniqueConstraint('company_id', 'reference_number', name='uq_stocktake_session_ref'),
        UniqueConstraint('company_id', 'id', name='uq_stocktake_sessions_company_id'),
        CheckConstraint("status IN ('DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED', 'POSTED', 'CANCELLED')", name='chk_stocktake_status'),
        CheckConstraint("stocktake_type IN ('FULL_COUNT', 'CYCLE_COUNT', 'VEHICLE_RECON')", name='chk_stocktake_type'),

        ForeignKeyConstraint(
            ['company_id', 'location_id'],
            ['inventory_locations.company_id', 'inventory_locations.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_session_tenant_location'
        ),
        ForeignKeyConstraint(
            ['company_id', 'started_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_session_started_by'
        ),
        ForeignKeyConstraint(
            ['company_id', 'counted_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_session_counted_by'
        ),
        ForeignKeyConstraint(
            ['company_id', 'approved_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_session_approved_by'
        ),
        ForeignKeyConstraint(
            ['company_id', 'pending_recount_authorized_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_session_pending_recount_authorizer'
        ),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    location_id        = Column(Integer, nullable=False, index=True)
    reference_number   = Column(String(100), nullable=False, index=True)
    stocktake_type     = Column(String(50), nullable=False)
    status             = Column(String(50), nullable=False, default='DRAFT', index=True)

    started_by         = Column(Integer, nullable=False)
    counted_by         = Column(Integer, nullable=True)
    approved_by        = Column(Integer, nullable=True)

    # حالة تشغيلية مؤقتة لإعادة العد؛ التاريخ الدائم ينسخ داخل محاولة العد وسجل الرقابة.
    pending_recount_authorized_by = Column(Integer, nullable=True)
    pending_recount_reason        = Column(Text, nullable=True)
    independent_recount_required  = Column(Boolean, nullable=False, default=False, server_default='false')

    notes              = Column(Text, nullable=True)
    created_at         = Column(DateTime, nullable=False, default=utc_now)
    updated_at         = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class StocktakeLine(Base):
    """Snapshot ثابت للرصيد المتوقع لحظة بدء الجرد؛ لا يخزن العد الفعلي."""
    __tablename__ = 'stocktake_lines'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_stocktake_lines_company_id'),
        ForeignKeyConstraint(
            ['company_id', 'stocktake_session_id'],
            ['stocktake_sessions.company_id', 'stocktake_sessions.id'],
            ondelete='CASCADE',
            name='fk_stocktake_lines_tenant_session'
        ),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id'],
            ['product_variants.company_id', 'product_variants.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_line_tenant_variant'
        ),
        ForeignKeyConstraint(
            ['company_id', 'batch_id'],
            ['product_batches.company_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_line_tenant_batch'
        ),
        Index(
            'uq_stocktake_line_item_batch',
            'company_id', 'stocktake_session_id', 'product_variant_id', 'batch_id',
            unique=True,
            postgresql_where=text("batch_id IS NOT NULL")
        ),
        Index(
            'uq_stocktake_line_item_no_batch',
            'company_id', 'stocktake_session_id', 'product_variant_id',
            unique=True,
            postgresql_where=text("batch_id IS NULL")
        ),
    )
    id                   = Column(Integer, primary_key=True)
    company_id           = Column(Integer, nullable=False, index=True)
    stocktake_session_id = Column(Integer, nullable=False, index=True)
    product_variant_id   = Column(Integer, nullable=False)
    batch_id             = Column(Integer, nullable=True)

    expected_quantity    = Column(Integer, CheckConstraint('expected_quantity >= 0', name='chk_st_line_exp_qty'), nullable=False)
    notes                = Column(Text, nullable=True)


class StocktakeCountAttempt(Base):
    """محاولة عد مستقلة: كل إنهاء عد ينشئ نسخة جديدة ولا يستبدل أي محاولة سابقة."""
    __tablename__ = 'stocktake_count_attempts'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_stocktake_count_attempts_company_id'),
        UniqueConstraint('company_id', 'stocktake_session_id', 'attempt_number', name='uq_stocktake_attempt_number'),
        ForeignKeyConstraint(
            ['company_id', 'stocktake_session_id'],
            ['stocktake_sessions.company_id', 'stocktake_sessions.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_tenant_session'
        ),
        ForeignKeyConstraint(
            ['company_id', 'recount_of_attempt_id'],
            ['stocktake_count_attempts.company_id', 'stocktake_count_attempts.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_recount_parent'
        ),
        ForeignKeyConstraint(
            ['company_id', 'counted_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_counted_by'
        ),
        ForeignKeyConstraint(
            ['company_id', 'authorized_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_authorized_by'
        ),
        CheckConstraint('attempt_number > 0', name='chk_stocktake_attempt_number_positive'),
    )
    id                   = Column(Integer, primary_key=True)
    company_id           = Column(Integer, nullable=False, index=True)
    stocktake_session_id = Column(Integer, nullable=False, index=True)
    attempt_number       = Column(Integer, nullable=False)
    recount_of_attempt_id= Column(Integer, nullable=True, index=True)

    counted_by           = Column(Integer, nullable=False, index=True)
    authorized_by        = Column(Integer, nullable=True, index=True)
    recount_reason       = Column(Text, nullable=True)
    requires_independent_recount = Column(Boolean, nullable=False, default=False, server_default='false')

    submitted_at         = Column(DateTime, nullable=False, default=utc_now, index=True)


class StocktakeCountAttemptLine(Base):
    """أسطر محاولة العد: تحفظ المتوقع الفعّال والفعلي والفرق كما كانت لحظة الإرسال."""
    __tablename__ = 'stocktake_count_attempt_lines'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_stocktake_count_attempt_lines_company_id'),
        ForeignKeyConstraint(
            ['company_id', 'count_attempt_id'],
            ['stocktake_count_attempts.company_id', 'stocktake_count_attempts.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_line_tenant_attempt'
        ),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id'],
            ['product_variants.company_id', 'product_variants.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_line_tenant_variant'
        ),
        ForeignKeyConstraint(
            ['company_id', 'batch_id'],
            ['product_batches.company_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_line_tenant_batch'
        ),
        Index(
            'uq_stocktake_attempt_line_batch',
            'company_id', 'count_attempt_id', 'product_variant_id', 'batch_id',
            unique=True,
            postgresql_where=text("batch_id IS NOT NULL")
        ),
        Index(
            'uq_stocktake_attempt_line_no_batch',
            'company_id', 'count_attempt_id', 'product_variant_id',
            unique=True,
            postgresql_where=text("batch_id IS NULL")
        ),
        CheckConstraint('expected_quantity >= 0', name='chk_stocktake_attempt_line_expected'),
        CheckConstraint('actual_quantity >= 0', name='chk_stocktake_attempt_line_actual'),
        CheckConstraint('variance_quantity = actual_quantity - expected_quantity', name='chk_stocktake_attempt_line_variance'),
    )
    id                   = Column(Integer, primary_key=True)
    company_id           = Column(Integer, nullable=False, index=True)
    count_attempt_id     = Column(Integer, nullable=False, index=True)
    product_variant_id   = Column(Integer, nullable=False)
    batch_id             = Column(Integer, nullable=True)

    expected_quantity    = Column(Integer, nullable=False)
    actual_quantity      = Column(Integer, nullable=False)
    variance_quantity    = Column(Integer, nullable=False)
    notes                = Column(Text, nullable=True)


class InventoryLock(Base):
    """الأقفال الجراحية: تمنع الحركات على رف/صنف/دفعة محددة دون شل باقي المستودع"""
    __tablename__ = 'inventory_locks'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_inventory_locks_company_id'),
        ForeignKeyConstraint(['company_id', 'stocktake_session_id'],
                             ['stocktake_sessions.company_id', 'stocktake_sessions.id'],
                             ondelete='CASCADE', name='fk_inv_lock_tenant_session'),
        # +++ فهرس جزئي لتسريع فحص الأقفال الفعالة فقط (P2-3) +++
        Index('ix_active_inv_lock', 'company_id', 'location_id', postgresql_where=text("released_at IS NULL")),
    )
    id                   = Column(Integer, primary_key=True)
    company_id           = Column(Integer, nullable=False, index=True)
    stocktake_session_id = Column(Integer, nullable=False, index=True)
    location_id          = Column(Integer, ForeignKey('inventory_locations.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # +++ للـ Cycle Count: يمكن قفل صنف أو دفعة معينة فقط. إذا كانا Null، يقفل الموقع بالكامل (FULL_COUNT) +++
    product_variant_id   = Column(Integer, ForeignKey('product_variants.id', ondelete='CASCADE'), nullable=True)
    batch_id             = Column(Integer, ForeignKey('product_batches.id', ondelete='CASCADE'), nullable=True)
    
    created_by           = Column(Integer, ForeignKey('drivers.id', ondelete='RESTRICT'), nullable=False)
    created_at           = Column(DateTime, nullable=False, default=utc_now)
    released_at          = Column(DateTime, nullable=True) # Null تعني القفل فعال