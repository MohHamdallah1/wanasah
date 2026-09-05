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
    """معامل تحويل Tenant-safe بين وحدات القياس لمنتج محدد."""
    __tablename__ = 'uom_conversions'
    __table_args__ = (
        UniqueConstraint(
            'company_id', 'product_variant_id', 'from_uom_id', 'to_uom_id',
            name='uq_uom_conversion'
        ),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id'],
            ['product_variants.company_id', 'product_variants.id'],
            ondelete='RESTRICT',
            name='fk_uom_conversion_tenant_variant'
        ),
        CheckConstraint('from_uom_id <> to_uom_id', name='chk_uom_conversion_distinct_units'),
        CheckConstraint('conversion_factor > 0', name='chk_positive_conversion'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    from_uom_id        = Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False)
    to_uom_id          = Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False)
    conversion_factor  = Column(Numeric(10, 4), nullable=False)

class ProductVariant(Base):
    """نسخة المنتج التجارية؛ لا يمكن ربطها بمنتج من Tenant آخر."""
    __tablename__ = 'product_variants'
    __table_args__ = (
        UniqueConstraint('company_id', 'sku', name='uq_company_sku'),
        UniqueConstraint('company_id', 'id', name='uq_product_variants_company_id'),
        ForeignKeyConstraint(
            ['company_id', 'product_id'],
            ['products.company_id', 'products.id'],
            ondelete='RESTRICT',
            name='fk_product_variant_tenant_product'
        ),
        CheckConstraint('packs_per_carton > 0', name='chk_packs_per_carton_positive'),
        CheckConstraint('price_per_carton >= 0', name='chk_product_variant_carton_price'),
        CheckConstraint('price_per_pack IS NULL OR price_per_pack >= 0', name='chk_product_variant_pack_price'),
        CheckConstraint('default_max_samples_per_day >= 0', name='chk_product_variant_samples_limit'),
    )
    id          = Column(Integer, primary_key=True)
    company_id  = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    product_id  = Column(Integer, nullable=False, index=True)
    base_uom_id = Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False)

    variant_name     = Column(String(200), nullable=False)
    flavor           = Column(String(50), nullable=True)
    size             = Column(String(50), nullable=True)
    sku              = Column(String(100), nullable=True)
    packs_per_carton = Column(Integer, nullable=False, default=50, server_default='50')
    price_per_carton = Column(Numeric(12, 3), nullable=False)
    price_per_pack   = Column(Numeric(12, 3), nullable=True)
    is_active        = Column(Boolean, nullable=False, default=True, server_default='true', index=True)
    default_max_samples_per_day = Column(Integer, nullable=False, default=0, server_default='0')


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


# =================================================================================
class WorkSession(Base):
    # جلسة عمل المندوب؛ ترتبط بهوية الشركة والمندوب بقيود Tenant صريحة.
    __tablename__ = 'work_sessions'
    __table_args__ = (
        Index('ix_ws_driver_unsettled', 'driver_id', 'is_settled', 'end_time'),
        Index(
            'uq_active_session_per_driver',
            'company_id',
            'driver_id',
            unique=True,
            postgresql_where=text("end_time IS NULL")
        ),
        UniqueConstraint('company_id', 'id', name='uq_work_sessions_company_id'),
        UniqueConstraint('company_id', 'id', 'driver_id', name='uq_work_sessions_company_driver_id'),
        ForeignKeyConstraint(
            ['company_id', 'driver_id'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_work_session_tenant_driver'
        ),
        CheckConstraint(
            'end_time IS NULL OR end_time >= start_time',
            name='chk_work_session_time_order'
        ),
    )
    id           = Column(Integer, primary_key=True)
    company_id   = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    driver_id    = Column(Integer, nullable=False, index=True)
    start_time   = Column(DateTime, nullable=False, default=utc_now)
    end_time     = Column(DateTime, nullable=True, index=True)
    session_date = Column(Date, nullable=False, default=lambda: utc_now().date(), index=True)
    start_latitude  = Column(Numeric(10, 7), nullable=True)
    start_longitude = Column(Numeric(10, 7), nullable=True)

    is_authorized_to_sell = Column(Boolean, nullable=False, default=False, server_default='false')
    break_start_time      = Column(DateTime, nullable=True)
    break_end_time        = Column(DateTime, nullable=True)
    is_settled            = Column(Boolean, nullable=False, default=False, server_default='false', index=True)

    driver = relationship('Driver', foreign_keys=[driver_id], backref=backref('work_sessions', lazy='raise'), lazy='raise')

class SessionInventorySnapshot(Base):
    """
    لقطة تاريخية لعهدة جلسة المندوب وليست رصيداً حياً.

    الرصيد الحي يُقرأ حصرياً من InventoryBalance لموقع السيارة.
    starting_quantity يثبت عند بدء الجلسة، وending_quantity يثبت عند التسوية.
    صافي الحوالات والحركات يُستخرج من InventoryMovement المرتبط بالجلسة.
    """
    __tablename__ = 'session_inventory_snapshots'
    __table_args__ = (
        UniqueConstraint(
            'company_id', 'work_session_id', 'product_variant_id',
            name='uq_session_inventory_snapshot_variant'
        ),
        ForeignKeyConstraint(
            ['company_id', 'work_session_id'],
            ['work_sessions.company_id', 'work_sessions.id'],
            ondelete='RESTRICT',
            name='fk_session_snapshot_tenant_session'
        ),
        ForeignKeyConstraint(
            ['company_id', 'location_id'],
            ['inventory_locations.company_id', 'inventory_locations.id'],
            ondelete='RESTRICT',
            name='fk_session_snapshot_tenant_location'
        ),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id'],
            ['product_variants.company_id', 'product_variants.id'],
            ondelete='RESTRICT',
            name='fk_session_snapshot_tenant_variant'
        ),
        ForeignKeyConstraint(
            ['company_id', 'settled_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_session_snapshot_tenant_settler'
        ),
        CheckConstraint('starting_quantity >= 0', name='chk_session_snapshot_starting'),
        CheckConstraint('ending_quantity IS NULL OR ending_quantity >= 0', name='chk_session_snapshot_ending'),
        CheckConstraint(
            "((settled_at IS NULL AND ending_quantity IS NULL AND settled_by IS NULL) OR "
            "(settled_at IS NOT NULL AND ending_quantity IS NOT NULL AND settled_by IS NOT NULL))",
            name='chk_session_snapshot_settlement_triplet'
        ),
        CheckConstraint(
            'settled_at IS NULL OR settled_at >= created_at',
            name='chk_session_snapshot_settlement_time'
        ),
    )

    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    work_session_id    = Column(Integer, nullable=False, index=True)
    location_id        = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)

    starting_quantity = Column(Integer, nullable=False)
    ending_quantity   = Column(Integer, nullable=True)
    created_at        = Column(DateTime, nullable=False, default=utc_now)
    settled_by        = Column(Integer, nullable=True, index=True)
    settled_at        = Column(DateTime, nullable=True, index=True)

# =================================================================================
# ⑦ المحلات
# =================================================================================
class Shop(Base):
    __tablename__ = 'shops'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_shops_company_id'),
        ForeignKeyConstraint(
            ['company_id', 'zone_id'],
            ['zones.company_id', 'zones.id'],
            ondelete='SET NULL (zone_id)',
            name='fk_shop_tenant_zone'
        ),
        ForeignKeyConstraint(
            ['company_id', 'added_by_driver_id'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='SET NULL (added_by_driver_id)',
            name='fk_shop_tenant_added_by'
        ),
    )
    id             = Column(Integer, primary_key=True)
    company_id     = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    name           = Column(String(150), nullable=False)
    address        = Column(Text,        nullable=True)
    latitude       = Column(Numeric(10, 7), nullable=True)
    longitude      = Column(Numeric(10, 7), nullable=True)
    phone_number   = Column(String(20),  nullable=True)
    contact_person = Column(String(100), nullable=True)
    zone_id        = Column(Integer, nullable=True, index=True)
    # +++  حماية الـ Decimal، فرض server_default، وتطبيق سياسة (SET NULL) لحماية الداتابيز +++
    current_balance  = Column(Numeric(12, 3), CheckConstraint('current_balance >= 0', name='chk_positive_balance'), nullable=False, default=Decimal('0.000'), server_default='0.000')
    max_debt_limit   = Column(Numeric(12, 3), CheckConstraint('max_debt_limit >= 0', name='chk_positive_max_debt'), nullable=False, default=Decimal('0.000'), server_default='0.000')
    added_by_driver_id = Column(Integer, nullable=True, index=True)
    is_active        = Column(Boolean,  nullable=False, default=True, server_default='true')
    created_at       = Column(DateTime, nullable=False, default=utc_now)  # FIX ①
    notes            = Column(Text,     nullable=True)
    location_link    = Column(String(500), nullable=True)
    # +++ إصلاح المنطق الترتيبي (Issue 5): المحل الجديد يأخذ 999 افتراضياً ليظهر بآخر خط السير +++
    sequence         = Column(Integer,  nullable=True, default=999, server_default='999')
    is_archived      = Column(Boolean,  nullable=False, default=False, server_default='false')

    visits = relationship('Visit', backref='shop', lazy='raise', foreign_keys='Visit.shop_id')


# =================================================================================
# ⑧ خطوط السير اليومية (الجدولة والتوزيع)
# =================================================================================
class DispatchRoute(Base):
    # خط السير يحمل مستودع المصدر صراحةً لدعم تعدد المستودعات دون تخمين.
    __tablename__ = 'dispatch_routes'
    __table_args__ = (
        Index('uq_active_route_per_driver', 'company_id', 'driver_id', unique=True,
              postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
        Index('uq_active_route_per_vehicle', 'company_id', 'vehicle_id', unique=True,
              postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
        Index('uq_active_route_per_zone', 'company_id', 'zone_id', unique=True,
              postgresql_where=text("status IN ('active', 'waiting', 'postponed')")),
        UniqueConstraint('company_id', 'id', name='uq_dispatch_routes_company_id'),
        ForeignKeyConstraint(['company_id', 'zone_id'], ['zones.company_id', 'zones.id'],
                             ondelete='RESTRICT', name='fk_dispatch_route_tenant_zone'),
        ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'],
                             ondelete='RESTRICT', name='fk_dispatch_route_tenant_driver'),
        ForeignKeyConstraint(['company_id', 'vehicle_id'], ['vehicles.company_id', 'vehicles.id'],
                             ondelete='RESTRICT', name='fk_dispatch_route_tenant_vehicle'),
        ForeignKeyConstraint(
            ['company_id', 'work_session_id', 'driver_id'],
            ['work_sessions.company_id', 'work_sessions.id', 'work_sessions.driver_id'],
            ondelete='RESTRICT',
            name='fk_dispatch_route_tenant_session_driver'
        ),
        ForeignKeyConstraint(['company_id', 'source_location_id'], ['inventory_locations.company_id', 'inventory_locations.id'],
                             ondelete='RESTRICT', name='fk_dispatch_route_tenant_source_location'),
        CheckConstraint("status IN ('active', 'closed', 'waiting', 'postponed')",
                        name='chk_dispatch_route_status'),
        CheckConstraint('work_session_id IS NULL OR driver_id IS NOT NULL',
                        name='chk_dispatch_route_session_requires_driver'),
    )

    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    zone_id            = Column(Integer, nullable=False, index=True)
    driver_id          = Column(Integer, nullable=True, index=True)
    vehicle_id         = Column(Integer, nullable=True, index=True)
    work_session_id    = Column(Integer, nullable=True, index=True)
    source_location_id = Column(Integer, nullable=False, index=True)
    dispatch_date      = Column(Date, nullable=False, default=lambda: utc_now().date(), index=True)
    status             = Column(String(50), nullable=False, default='waiting', index=True)
    created_at         = Column(DateTime, nullable=False, default=utc_now)

    zone    = relationship('Zone', foreign_keys=[zone_id], lazy='raise')
    driver  = relationship('Driver', foreign_keys=[driver_id], lazy='raise')
    vehicle = relationship('Vehicle', foreign_keys=[vehicle_id], lazy='raise')

class DispatchLoadPlanLine(Base):
    """
    هدف تحميل مخطط لخط سير؛ ليس رصيداً مخزنياً.

    target_quantity_packs يمثل الكمية المستهدفة على السيارة بعد تنفيذ التحميل،
    بينما الرصيد الفعلي يبقى حصرياً في InventoryBalance.
    """
    __tablename__ = 'dispatch_load_plan_lines'
    __table_args__ = (
        UniqueConstraint(
            'company_id', 'dispatch_route_id', 'product_variant_id',
            name='uq_dispatch_load_plan_variant'
        ),
        ForeignKeyConstraint(
            ['company_id', 'dispatch_route_id'],
            ['dispatch_routes.company_id', 'dispatch_routes.id'],
            ondelete='CASCADE',
            name='fk_dispatch_load_plan_tenant_route'
        ),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id'],
            ['product_variants.company_id', 'product_variants.id'],
            ondelete='RESTRICT',
            name='fk_dispatch_load_plan_tenant_variant'
        ),
        ForeignKeyConstraint(
            ['company_id', 'updated_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_dispatch_load_plan_tenant_actor'
        ),
        CheckConstraint('target_quantity_packs >= 0', name='chk_dispatch_load_plan_target'),
    )

    id                    = Column(Integer, primary_key=True)
    company_id            = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    dispatch_route_id     = Column(Integer, nullable=False, index=True)
    product_variant_id    = Column(Integer, nullable=False, index=True)
    target_quantity_packs = Column(Integer, nullable=False, default=0, server_default='0')
    updated_by            = Column(Integer, nullable=False, index=True)
    created_at            = Column(DateTime, nullable=False, default=utc_now)
    updated_at            = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


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
        UniqueConstraint('company_id', 'id', name='uq_visits_company_id'),
        ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'],
                             ondelete='RESTRICT', name='fk_visit_tenant_driver'),
        ForeignKeyConstraint(['company_id', 'shop_id'], ['shops.company_id', 'shops.id'],
                             name='fk_visit_tenant_shop'),
        ForeignKeyConstraint(
            ['company_id', 'work_session_id', 'driver_id'],
            ['work_sessions.company_id', 'work_sessions.id', 'work_sessions.driver_id'],
            name='fk_visit_tenant_session_driver'
        ),
        CheckConstraint('work_session_id IS NULL OR driver_id IS NOT NULL',
                        name='chk_visit_session_requires_driver'),
        Index('ix_visit_shop_timestamp', 'shop_id', 'visit_timestamp'),
        Index('ix_visit_session_outcome', 'work_session_id', 'outcome'),
    )
    id              = Column(Integer, primary_key=True)
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    driver_id       = Column(Integer, nullable=True,  index=True)
    shop_id         = Column(Integer, nullable=False, index=True)
    work_session_id = Column(Integer, nullable=True, index=True)
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

    work_session = relationship('WorkSession', foreign_keys=[work_session_id], backref=backref('visits', lazy='raise'))
    driver       = relationship('Driver', foreign_keys=[driver_id], backref=backref('visits', lazy='raise'))
    items        = relationship('VisitItem', backref='visit', lazy='raise',
                                foreign_keys='VisitItem.visit_id',
                                cascade='all, delete-orphan')


class VisitItem(Base):
    """
    تفاصيل الفاتورة - مصدر الحقيقة الأول للأرقام المالية.
    يحفظ أسعار البيع اللحظية لضمان دقة السجل حتى لو تغير السعر لاحقاً.
    """
    __tablename__ = 'visit_items'
    __table_args__ = (
        ForeignKeyConstraint(['company_id', 'visit_id'], ['visits.company_id', 'visits.id'],
                             name='fk_visit_item_tenant_visit'),
        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'],
                             ondelete='RESTRICT', name='fk_visit_item_tenant_variant'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    visit_id           = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)

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

    product_variant = relationship('ProductVariant', foreign_keys=[product_variant_id], lazy='raise')


class VisitReturn(Base):
    """
    المرتجعات والتوالف المستلمة خلال الزيارة.
    return_type: Factory_Defect | Expired | Damaged
    """
    __tablename__ = 'visit_returns'
    __table_args__ = (
        ForeignKeyConstraint(['company_id', 'visit_id'], ['visits.company_id', 'visits.id'],
                             ondelete='CASCADE', name='fk_visit_return_tenant_visit'),
        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'],
                             ondelete='RESTRICT', name='fk_visit_return_tenant_variant'),
        Index('ix_visit_return_composite', 'visit_id', 'product_variant_id'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    visit_id           = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)

    # +++ حماية مخزون المرتجعات من الاختلاس العكسي +++
    quantity    = Column(Integer, CheckConstraint('quantity >= 0', name='chk_vret_qty'), nullable=False, default=0)
    packs_quantity = Column(Integer, CheckConstraint('packs_quantity >= 0', name='chk_vret_pqty'), nullable=False, default=0)
    return_type = Column(String(50), nullable=False)
    reason      = Column(Text,       nullable=True)
    is_cancelled = Column(Boolean, nullable=False, default=False, server_default='false') # +++ لمنع طمس الأدلة وإغلاق ثغرة الـ NULL بالداتابيز +++

    product_variant = relationship('ProductVariant', foreign_keys=[product_variant_id], lazy='raise')
    visit = relationship('Visit', foreign_keys=[visit_id],
                         backref=backref('returns', lazy='raise',
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
    __table_args__ = (
        ForeignKeyConstraint(['company_id', 'zone_id'], ['zones.company_id', 'zones.id'],
                             name='fk_shortage_tenant_zone'),
        ForeignKeyConstraint(['company_id', 'shop_id'], ['shops.company_id', 'shops.id'],
                             name='fk_shortage_tenant_shop'),
        ForeignKeyConstraint(['company_id', 'driver_id'], ['drivers.company_id', 'drivers.id'],
                             name='fk_shortage_tenant_driver'),
        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'],
                             ondelete='RESTRICT', name='fk_shortage_tenant_variant'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    zone_id            = Column(Integer, nullable=False, index=True)
    shop_id            = Column(Integer, nullable=False, index=True)
    driver_id          = Column(Integer, nullable=True,  index=True)
    # FIX ③: product_variant_id بدل product_name النصي
    product_variant_id = Column(Integer, nullable=False, index=True)

    quantity   = Column(Integer, CheckConstraint('quantity > 0', name='chk_shortage_qty_positive'), nullable=False)
    status     = Column(String(50), nullable=False, default='pending', index=True)
    wait_time  = Column(String(50), nullable=True,  default='الآن')
    notes      = Column(Text,       nullable=True)   # بدل product_name - لو في ملاحظات إضافية
    created_at = Column(DateTime,   nullable=False,  default=utc_now)  # FIX ①

    zone            = relationship('Zone', foreign_keys=[zone_id], lazy='raise')
    shop            = relationship('Shop', foreign_keys=[shop_id], lazy='raise')
    driver          = relationship('Driver', foreign_keys=[driver_id], lazy='raise')
    product_variant = relationship('ProductVariant', foreign_keys=[product_variant_id], lazy='raise')  # FIX ③


# =================================================================================
# ⑪ العروض
# =================================================================================
class OfferRule(Base):
    __tablename__ = 'offer_rules'
    __table_args__ = (
        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'],
                             ondelete='CASCADE', name='fk_offer_rule_tenant_variant'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    # +++  (G-01): ربط العرض بمنتج معين. (Null تعني عرض عام لجميع المنتجات) +++
    product_variant_id = Column(Integer, nullable=True, index=True)
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
    __table_args__ = (
        ForeignKeyConstraint(['company_id', 'admin_id'], ['drivers.company_id', 'drivers.id'],
                             ondelete='RESTRICT', name='fk_import_log_tenant_admin'),
        ForeignKeyConstraint(['company_id', 'zone_id'], ['zones.company_id', 'zones.id'],
                             name='fk_import_log_tenant_zone'),
    )
    id            = Column(Integer, primary_key=True)
    company_id    = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    # +++ حماية الداتابيز من كراش الـ IntegrityError عند إلغاء حساب موظف +++
    admin_id      = Column(Integer, nullable=False)
    zone_id       = Column(Integer, nullable=False)
    file_name     = Column(String(255), nullable=True)
    total_records = Column(Integer,     nullable=False, default=0)
    success_count = Column(Integer,     nullable=False, default=0)
    status        = Column(String(50),  nullable=False)  # Success | Failed | Partial
    created_at    = Column(DateTime,    nullable=False, default=utc_now)  # FIX ①

    admin = relationship('Driver', foreign_keys=[admin_id], lazy='raise')
    zone  = relationship('Zone', foreign_keys=[zone_id], lazy='raise')


# =================================================================================
# ⑬ سجل حركات المخزون (Inventory Ledger) - دفتر الأستاذ
# السجل المالي غير القابل للمسح
# =================================================================================
# السجل المخزني الموحد الوحيد هو InventoryMovement.


# =================================================================================
# ⑭ سجل النظام الشامل (System Audit Log)
# يسجل الحركات الحساسة لمنع التلاعب
# =================================================================================
class SystemAuditLog(Base):
    # سجل رقابي Append-only؛ منع UPDATE/DELETE النهائي سيُفرض في PostgreSQL لاحقاً.
    __tablename__ = 'system_audit_logs'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_system_audit_logs_company_id'),
        ForeignKeyConstraint(
            ['company_id', 'admin_id'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_system_audit_tenant_admin'
        ),
    )
    id          = Column(Integer, primary_key=True)
    company_id  = Column(Integer, ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    admin_id    = Column(Integer, nullable=True, index=True)
    target_id   = Column(String(100), nullable=False, index=True)
    action_type = Column(String(100), nullable=False, index=True)
    old_value   = Column(Text, nullable=True)
    new_value   = Column(Text, nullable=True)
    timestamp   = Column(DateTime, nullable=False, default=utc_now, index=True)

    admin = relationship('Driver', foreign_keys=[admin_id], lazy='raise')

# =================================================================================
# ⑮ أرشيف الاستراحات
# يحل مشكلة ضياع الاستراحة الأولى إذا قام المندوب باستراحة ثانية
# =================================================================================
class WorkBreakLog(Base):
    __tablename__ = 'work_break_logs'
    __table_args__ = (
        ForeignKeyConstraint(['company_id', 'work_session_id'], ['work_sessions.company_id', 'work_sessions.id'],
                             name='fk_work_break_log_tenant_session'),
    )
    id              = Column(Integer, primary_key=True)
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    work_session_id = Column(Integer, nullable=False, index=True)
    break_start     = Column(DateTime, nullable=False)
    break_end       = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)  # يُحسب تلقائياً عند الإنهاء

    work_session = relationship('WorkSession', foreign_keys=[work_session_id], backref=backref('break_logs', lazy='raise'))


# =================================================================================
# ⑯ الحوالات المعلقة (المصافحة - Handshake)
# عنق الزجاجة الذي يمنع دخول أي بضاعة للعهدة إلا بموافقة المندوب
# =================================================================================
# تم إلغاء مخزن MainWarehouse والحوالة القديمة نهائياً؛ المصدر هو المحرك الموحد فقط.


# =================================================================================
# ⑱ مقبرة التوالف (Damaged Goods Log)
# سجل دقيق لكل حبة تالفة تعود للمستودع مع توثيق (من أحضرها ومن أي محل).
# =================================================================================
class InventoryDamageEvent(Base):
    """
    بيانات سبب/مصدر الضرر المرتبطة بحركة مخزون واحدة.

    الكمية والصنف والدفعة والموقع لا تُكرر هنا؛ مصدرها الوحيد InventoryMovement.
    """
    __tablename__ = 'inventory_damage_events'
    __table_args__ = (
        UniqueConstraint('company_id', 'inventory_movement_id', name='uq_inventory_damage_event_movement'),
        ForeignKeyConstraint(
            ['company_id', 'inventory_movement_id'],
            ['inventory_movements.company_id', 'inventory_movements.id'],
            ondelete='RESTRICT',
            name='fk_inventory_damage_event_tenant_movement'
        ),
        ForeignKeyConstraint(
            ['company_id', 'source_visit_id'],
            ['visits.company_id', 'visits.id'],
            ondelete='RESTRICT',
            name='fk_inventory_damage_event_tenant_visit'
        ),
        ForeignKeyConstraint(
            ['company_id', 'source_driver_id'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_inventory_damage_event_tenant_driver'
        ),
        ForeignKeyConstraint(
            ['company_id', 'receiving_admin_id'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_inventory_damage_event_tenant_admin'
        ),
        CheckConstraint(
            "damage_type IN ('Expired', 'Factory_Defect', 'Damaged')",
            name='chk_inventory_damage_event_type'
        ),
    )

    id                    = Column(Integer, primary_key=True)
    company_id            = Column(Integer, ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    inventory_movement_id = Column(Integer, nullable=False, index=True)
    source_visit_id       = Column(Integer, nullable=True, index=True)
    source_driver_id      = Column(Integer, nullable=True, index=True)
    receiving_admin_id    = Column(Integer, nullable=False, index=True)
    damage_type           = Column(String(50), nullable=False)
    notes                 = Column(Text, nullable=True)
    created_at            = Column(DateTime, nullable=False, default=utc_now, index=True)


# =================================================================================
# ⑲ دفتر أستاذ المستودع (Warehouse Ledger)
# السجل المالي للبضاعة - لا يمكن مسحه أو تعديله. يوثق الموردين وحركات التحميل.
# =================================================================================
# دفتر حركة المستودع والسيارات والتسويات موحد في InventoryMovement.


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
    # دفعة Tenant-safe لإدارة الإنتاج والصلاحية وFEFO.
    __tablename__ = 'product_batches'
    __table_args__ = (
        UniqueConstraint('company_id', 'product_variant_id', 'batch_number', name='uq_product_batch_number'),
        UniqueConstraint('company_id', 'id', name='uq_product_batches_company_id'),
        UniqueConstraint('company_id', 'product_variant_id', 'id', name='uq_product_batches_variant_id'),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id'],
            ['product_variants.company_id', 'product_variants.id'],
            ondelete='RESTRICT',
            name='fk_product_batch_tenant_variant'
        ),
        CheckConstraint("length(trim(batch_number)) > 0", name='chk_product_batch_number_not_blank'),
        CheckConstraint('production_date IS NULL OR production_date <= expiry_date', name='chk_product_batch_date_order'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    batch_number       = Column(String(100), nullable=False, index=True)
    production_date    = Column(Date, nullable=True)
    expiry_date        = Column(Date, nullable=False, index=True)
    is_active          = Column(Boolean, nullable=False, default=True, server_default='true', index=True)
    created_at         = Column(DateTime, nullable=False, default=utc_now)

class OverrideReason(Base):
    # سبب معتمد لتجاوز FEFO ويبقى مرجعاً تدقيقياً للحركة.
    __tablename__ = 'override_reasons'
    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_override_reason_code'),
        UniqueConstraint('company_id', 'id', name='uq_override_reasons_company_id'),
    )
    id          = Column(Integer, primary_key=True)
    company_id  = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    code        = Column(String(50), nullable=False)
    description = Column(String(255), nullable=False)
    is_active   = Column(Boolean, nullable=False, default=True, server_default='true')

class InventoryLocation(Base):
    # موقع مخزني موحد: مستودع، سيارة، عبور أو تالف.
    __tablename__ = 'inventory_locations'
    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_inv_loc_company_code'),
        UniqueConstraint('company_id', 'id', name='uq_inventory_locations_company_id'),
        ForeignKeyConstraint(['company_id', 'branch_id'], ['branches.company_id', 'branches.id'],
                             ondelete='RESTRICT', name='fk_inventory_location_tenant_branch'),
        ForeignKeyConstraint(['company_id', 'vehicle_id'], ['vehicles.company_id', 'vehicles.id'],
                             ondelete='RESTRICT', name='fk_inventory_location_tenant_vehicle'),
        CheckConstraint("location_type IN ('WAREHOUSE', 'VEHICLE', 'IN_TRANSIT', 'SCRAP')", name='chk_inv_loc_type'),
        CheckConstraint("length(trim(code)) > 0", name='chk_inv_loc_code_not_blank'),
        CheckConstraint("vehicle_id IS NULL OR location_type = 'VEHICLE'", name='chk_inv_loc_vehicle_type'),
        CheckConstraint("location_type <> 'VEHICLE' OR vehicle_id IS NOT NULL", name='chk_inv_loc_vehicle_required'),
        Index('uq_active_inventory_location_vehicle', 'company_id', 'vehicle_id', unique=True,
              postgresql_where=text("vehicle_id IS NOT NULL AND is_active IS TRUE")),
    )
    id            = Column(Integer, primary_key=True)
    company_id    = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    branch_id     = Column(Integer, nullable=True, index=True)
    name          = Column(String(150), nullable=False)
    code          = Column(String(50), nullable=False)
    location_type = Column(String(50), nullable=False, index=True)
    vehicle_id    = Column(Integer, nullable=True, index=True)
    is_active     = Column(Boolean, nullable=False, default=True, server_default='true')
    created_at    = Column(DateTime, nullable=False, default=utc_now)
    updated_at    = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class InventoryStockPolicy(Base):
    # حد النقص والهدف لكل مستودع/صنف بدلاً من MainWarehouse.min_threshold_packs.
    __tablename__ = 'inventory_stock_policies'
    __table_args__ = (
        UniqueConstraint('company_id', 'location_id', 'product_variant_id', name='uq_inventory_stock_policy'),
        ForeignKeyConstraint(['company_id', 'location_id'], ['inventory_locations.company_id', 'inventory_locations.id'],
                             ondelete='RESTRICT', name='fk_inventory_stock_policy_tenant_location'),
        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'],
                             ondelete='RESTRICT', name='fk_inventory_stock_policy_tenant_variant'),
        CheckConstraint('minimum_quantity >= 0', name='chk_inventory_stock_policy_minimum'),
        CheckConstraint('target_quantity IS NULL OR target_quantity >= minimum_quantity', name='chk_inventory_stock_policy_target'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    location_id        = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    minimum_quantity   = Column(Integer, nullable=False, default=0, server_default='0')
    target_quantity    = Column(Integer, nullable=True)
    is_active          = Column(Boolean, nullable=False, default=True, server_default='true')
    created_at         = Column(DateTime, nullable=False, default=utc_now)
    updated_at         = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

class InventoryBalance(Base):
    # مصدر الحقيقة الوحيد: on_hand فيزيائي كامل، وreserved جزء محجوز منه.
    __tablename__ = 'inventory_balances'
    __table_args__ = (
        UniqueConstraint('company_id', 'location_id', 'product_variant_id', 'batch_id', 'stock_status', name='uq_inv_balance_core'),
        UniqueConstraint('company_id', 'id', name='uq_inventory_balances_company_id'),
        ForeignKeyConstraint(['company_id', 'location_id'], ['inventory_locations.company_id', 'inventory_locations.id'],
                             ondelete='RESTRICT', name='fk_inv_balance_tenant_location'),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id', 'batch_id'],
            ['product_batches.company_id', 'product_batches.product_variant_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_inv_balance_variant_batch'
        ),
        CheckConstraint("stock_status IN ('AVAILABLE', 'DAMAGED')", name='chk_inv_bal_status'),
        CheckConstraint('on_hand_quantity >= 0', name='chk_inv_bal_onhand_qty'),
        CheckConstraint('reserved_quantity >= 0', name='chk_inv_bal_res_qty'),
        CheckConstraint('reserved_quantity <= on_hand_quantity', name='chk_inv_bal_reserved_within_onhand'),
        CheckConstraint("stock_status <> 'DAMAGED' OR reserved_quantity = 0", name='chk_inv_bal_damaged_not_reserved'),
        Index('ix_inv_balance_search', 'company_id', 'location_id', 'product_variant_id', 'stock_status'),
        Index('ix_inv_balance_fefo', 'company_id', 'location_id', 'product_variant_id', 'stock_status', 'batch_id'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    location_id        = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    batch_id           = Column(Integer, nullable=False, index=True)
    stock_status       = Column(String(50), nullable=False, default='AVAILABLE', server_default='AVAILABLE')
    on_hand_quantity   = Column(Integer, nullable=False, default=0, server_default='0')
    reserved_quantity  = Column(Integer, nullable=False, default=0, server_default='0')
    last_updated       = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

class InventoryMovement(Base):
    # دفتر حركة موحد وصريح: PHYSICAL / RESERVATION / STATUS_CHANGE.
    __tablename__ = 'inventory_movements'
    __table_args__ = (
        UniqueConstraint('company_id', 'idempotency_key', name='uq_inv_movement_idempotency'),
        UniqueConstraint('company_id', 'id', name='uq_inventory_movements_company_id'),
        ForeignKeyConstraint(['company_id', 'performed_by'], ['drivers.company_id', 'drivers.id'],
                             ondelete='RESTRICT', name='fk_inv_movement_tenant_actor'),
        ForeignKeyConstraint(['company_id', 'source_location_id'], ['inventory_locations.company_id', 'inventory_locations.id'],
                             ondelete='RESTRICT', name='fk_inv_movement_tenant_source'),
        ForeignKeyConstraint(['company_id', 'destination_location_id'], ['inventory_locations.company_id', 'inventory_locations.id'],
                             ondelete='RESTRICT', name='fk_inv_movement_tenant_destination'),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id', 'batch_id'],
            ['product_batches.company_id', 'product_batches.product_variant_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_inv_movement_variant_batch'
        ),
        ForeignKeyConstraint(['company_id', 'work_session_id'], ['work_sessions.company_id', 'work_sessions.id'],
                             ondelete='RESTRICT', name='fk_inv_movement_tenant_session'),
        ForeignKeyConstraint(['company_id', 'transfer_header_id'], ['inventory_transfer_headers.company_id', 'inventory_transfer_headers.id'],
                             ondelete='RESTRICT', name='fk_inv_movement_tenant_transfer'),
        ForeignKeyConstraint(['company_id', 'stocktake_session_id'], ['stocktake_sessions.company_id', 'stocktake_sessions.id'],
                             ondelete='RESTRICT', name='fk_inv_movement_tenant_stocktake'),
        ForeignKeyConstraint(
            ['company_id', 'stocktake_session_id', 'stocktake_count_attempt_id'],
            ['stocktake_count_attempts.company_id', 'stocktake_count_attempts.stocktake_session_id', 'stocktake_count_attempts.id'],
            ondelete='RESTRICT',
            name='fk_inv_movement_tenant_stocktake_attempt'
        ),
        CheckConstraint("movement_kind IN ('PHYSICAL', 'RESERVATION', 'STATUS_CHANGE')", name='chk_inv_movement_kind'),
        CheckConstraint("reservation_action IS NULL OR reservation_action IN ('RESERVE', 'RELEASE')", name='chk_inv_movement_reservation_action'),
        CheckConstraint(
            "((movement_kind = 'RESERVATION' AND reservation_action IS NOT NULL) OR "
            "(movement_kind <> 'RESERVATION' AND reservation_action IS NULL))",
            name='chk_inv_movement_reservation_action_pair'
        ),
        CheckConstraint(
            "movement_kind <> 'RESERVATION' OR source_stock_status = 'AVAILABLE'",
            name='chk_inv_movement_reservation_available_only'
        ),
        CheckConstraint("source_stock_status IS NULL OR source_stock_status IN ('AVAILABLE', 'DAMAGED')", name='chk_inv_movement_source_status'),
        CheckConstraint("destination_stock_status IS NULL OR destination_stock_status IN ('AVAILABLE', 'DAMAGED')", name='chk_inv_movement_destination_status'),
        CheckConstraint("((source_location_id IS NULL AND source_stock_status IS NULL) OR (source_location_id IS NOT NULL AND source_stock_status IS NOT NULL))", name='chk_inv_movement_source_status_pair'),
        CheckConstraint("((destination_location_id IS NULL AND destination_stock_status IS NULL) OR (destination_location_id IS NOT NULL AND destination_stock_status IS NOT NULL))", name='chk_inv_movement_destination_status_pair'),
        CheckConstraint('source_location_id IS NOT NULL OR destination_location_id IS NOT NULL', name='chk_inv_movement_has_endpoint'),
        CheckConstraint(
            "((movement_kind = 'PHYSICAL' AND (source_location_id IS NULL OR destination_location_id IS NULL OR source_location_id <> destination_location_id)) "
            "OR (movement_kind = 'RESERVATION' AND source_location_id IS NOT NULL AND destination_location_id = source_location_id AND destination_stock_status = source_stock_status) "
            "OR (movement_kind = 'STATUS_CHANGE' AND source_location_id IS NOT NULL AND destination_location_id = source_location_id AND destination_stock_status <> source_stock_status))",
            name='chk_inv_movement_shape'
        ),
        CheckConstraint(
            "movement_kind <> 'PHYSICAL' OR source_location_id IS NULL OR destination_location_id IS NULL "
            "OR source_stock_status = destination_stock_status",
            name='chk_inv_movement_physical_preserves_status'
        ),
        CheckConstraint(
            'stocktake_count_attempt_id IS NULL OR stocktake_session_id IS NOT NULL',
            name='chk_inv_movement_attempt_requires_stocktake'
        ),
        CheckConstraint('quantity > 0', name='chk_inv_movement_qty_positive'),
        CheckConstraint("length(trim(reference_type)) > 0", name='chk_inv_movement_reference_type'),
        CheckConstraint("length(trim(reference_id)) > 0", name='chk_inv_movement_reference_id'),
        CheckConstraint("length(trim(idempotency_key)) > 0", name='chk_inv_movement_idempotency_key'),
        Index('ix_inv_movement_locations', 'company_id', 'source_location_id', 'destination_location_id'),
        Index('ix_inv_movement_item_created', 'company_id', 'product_variant_id', 'batch_id', 'created_at'),
        Index('ix_inv_movement_stocktake_attempt', 'company_id', 'stocktake_count_attempt_id'),
    )
    id                       = Column(Integer, primary_key=True)
    company_id               = Column(Integer, ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    performed_by             = Column(Integer, nullable=False, index=True)
    source_location_id       = Column(Integer, nullable=True, index=True)
    destination_location_id  = Column(Integer, nullable=True, index=True)
    source_stock_status      = Column(String(50), nullable=True)
    destination_stock_status = Column(String(50), nullable=True)
    product_variant_id       = Column(Integer, nullable=False, index=True)
    batch_id                 = Column(Integer, nullable=False, index=True)

    movement_kind             = Column(String(30), nullable=False, default='PHYSICAL', server_default='PHYSICAL', index=True)
    reservation_action        = Column(String(20), nullable=True, index=True)
    quantity                  = Column(Integer, nullable=False)

    work_session_id            = Column(Integer, nullable=True, index=True)
    transfer_header_id         = Column(Integer, nullable=True, index=True)
    stocktake_session_id       = Column(Integer, nullable=True, index=True)
    stocktake_count_attempt_id = Column(Integer, nullable=True, index=True)

    reference_type = Column(String(50), nullable=False, index=True)
    reference_id   = Column(String(100), nullable=False, index=True)
    idempotency_key= Column(String(100), nullable=False)
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime, nullable=False, default=utc_now, index=True)

class InventoryMovementImpact(Base):
    """
    لقطة الرصيد قبل/بعد لكل InventoryBalance تأثر بحركة واحدة.

    لا تُكرر هوية الرصيد هنا؛ inventory_balance_id يشير إلى صف الرصيد الحقيقي،
    بينما before/after مجرد Snapshot رقابي غير قابل لأن يصبح مصدراً حياً للمخزون.
    """
    __tablename__ = 'inventory_movement_impacts'
    __table_args__ = (
        UniqueConstraint(
            'company_id', 'movement_id', 'inventory_balance_id',
            name='uq_inventory_movement_impact_balance'
        ),
        ForeignKeyConstraint(
            ['company_id', 'movement_id'],
            ['inventory_movements.company_id', 'inventory_movements.id'],
            ondelete='RESTRICT',
            name='fk_inventory_movement_impact_tenant_movement'
        ),
        ForeignKeyConstraint(
            ['company_id', 'inventory_balance_id'],
            ['inventory_balances.company_id', 'inventory_balances.id'],
            ondelete='RESTRICT',
            name='fk_inventory_movement_impact_tenant_balance'
        ),
        CheckConstraint('on_hand_before >= 0', name='chk_inventory_movement_impact_onhand_before'),
        CheckConstraint('on_hand_after >= 0', name='chk_inventory_movement_impact_onhand_after'),
        CheckConstraint('reserved_before >= 0', name='chk_inventory_movement_impact_reserved_before'),
        CheckConstraint('reserved_after >= 0', name='chk_inventory_movement_impact_reserved_after'),
        CheckConstraint('reserved_before <= on_hand_before', name='chk_inventory_movement_impact_reserved_before_bound'),
        CheckConstraint('reserved_after <= on_hand_after', name='chk_inventory_movement_impact_reserved_after_bound'),
        CheckConstraint(
            'on_hand_before <> on_hand_after OR reserved_before <> reserved_after',
            name='chk_inventory_movement_impact_has_change'
        ),
    )

    id                   = Column(Integer, primary_key=True)
    company_id           = Column(Integer, ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    movement_id          = Column(Integer, nullable=False, index=True)
    inventory_balance_id = Column(Integer, nullable=False, index=True)

    on_hand_before  = Column(Integer, nullable=False)
    on_hand_after   = Column(Integer, nullable=False)
    reserved_before = Column(Integer, nullable=False)
    reserved_after  = Column(Integer, nullable=False)

    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)


# =================================================================================
# [المرحلة الخامسة] هيكلة الحوالات الصارمة (Header & Line Architecture)
# =================================================================================
class InventoryTransferHeader(Base):
    # DIRECT = فوري، HANDSHAKE = قبول بشري، TRANSIT = شحنة فعلية بين موقعين.
    __tablename__ = 'inventory_transfer_headers'
    __table_args__ = (
        UniqueConstraint('company_id', 'reference_number', name='uq_transfer_header_ref'),
        UniqueConstraint('company_id', 'id', name='uq_transfer_headers_company_id'),
        ForeignKeyConstraint(['company_id', 'source_location_id'], ['inventory_locations.company_id', 'inventory_locations.id'],
                             ondelete='RESTRICT', name='fk_transfer_header_tenant_source'),
        ForeignKeyConstraint(['company_id', 'destination_location_id'], ['inventory_locations.company_id', 'inventory_locations.id'],
                             ondelete='RESTRICT', name='fk_transfer_header_tenant_destination'),
        ForeignKeyConstraint(['company_id', 'transit_location_id'], ['inventory_locations.company_id', 'inventory_locations.id'],
                             ondelete='RESTRICT', name='fk_transfer_header_tenant_transit'),
        ForeignKeyConstraint(['company_id', 'dispatched_by'], ['drivers.company_id', 'drivers.id'],
                             ondelete='RESTRICT', name='fk_transfer_header_tenant_dispatcher'),
        ForeignKeyConstraint(['company_id', 'received_by'], ['drivers.company_id', 'drivers.id'],
                             ondelete='RESTRICT', name='fk_transfer_header_tenant_receiver'),
        ForeignKeyConstraint(['company_id', 'cancelled_by'], ['drivers.company_id', 'drivers.id'],
                             ondelete='RESTRICT', name='fk_transfer_header_tenant_canceller'),
        ForeignKeyConstraint(['company_id', 'expected_receiver_id'], ['drivers.company_id', 'drivers.id'],
                             ondelete='RESTRICT', name='fk_transfer_header_tenant_expected_receiver'),
        ForeignKeyConstraint(['company_id', 'work_session_id'], ['work_sessions.company_id', 'work_sessions.id'],
                             ondelete='RESTRICT', name='fk_transfer_header_tenant_session'),
        ForeignKeyConstraint(
            ['company_id', 'work_session_id', 'expected_receiver_id'],
            ['work_sessions.company_id', 'work_sessions.id', 'work_sessions.driver_id'],
            ondelete='RESTRICT',
            name='fk_transfer_header_handshake_session_receiver'
        ),
        CheckConstraint("workflow_type IN ('DIRECT', 'HANDSHAKE', 'TRANSIT')", name='chk_transfer_header_workflow'),
        CheckConstraint("status IN ('DRAFT', 'PENDING', 'IN_TRANSIT', 'ACCEPTED', 'REJECTED', 'POSTED', 'CANCELLED')", name='chk_transfer_header_status'),
        CheckConstraint(
            "((workflow_type = 'DIRECT' AND status IN ('DRAFT', 'POSTED', 'CANCELLED')) OR "
            "(workflow_type = 'HANDSHAKE' AND status IN ('DRAFT', 'PENDING', 'ACCEPTED', 'REJECTED', 'POSTED', 'CANCELLED')) OR "
            "(workflow_type = 'TRANSIT' AND status IN ('DRAFT', 'IN_TRANSIT', 'ACCEPTED', 'REJECTED', 'POSTED', 'CANCELLED')))",
            name='chk_transfer_header_workflow_status'
        ),
        CheckConstraint('source_location_id <> destination_location_id', name='chk_transfer_header_distinct_locations'),
        CheckConstraint(
            "transit_location_id IS NULL OR "
            "(transit_location_id <> source_location_id AND transit_location_id <> destination_location_id)",
            name='chk_transfer_header_distinct_transit_location'
        ),
        CheckConstraint(
            "workflow_type = 'TRANSIT' OR transit_location_id IS NULL",
            name='chk_transfer_header_transit_location_scope'
        ),
        CheckConstraint(
            "workflow_type <> 'TRANSIT' OR status IN ('DRAFT', 'CANCELLED') OR transit_location_id IS NOT NULL",
            name='chk_transfer_header_transit_location_required'
        ),
        CheckConstraint(
            "status <> 'IN_TRANSIT' OR (transit_location_id IS NOT NULL AND received_by IS NULL)",
            name='chk_transfer_header_in_transit_state'
        ),
        CheckConstraint(
            "workflow_type <> 'HANDSHAKE' OR (work_session_id IS NOT NULL AND expected_receiver_id IS NOT NULL)",
            name='chk_transfer_header_handshake_context'
        ),
        CheckConstraint(
            "workflow_type = 'HANDSHAKE' OR expected_receiver_id IS NULL",
            name='chk_transfer_header_receiver_scope'
        ),
        CheckConstraint(
            "status NOT IN ('REJECTED', 'CANCELLED') OR "
            "(decision_reason IS NOT NULL AND length(trim(decision_reason)) > 0)",
            name='chk_transfer_header_terminal_reason'
        ),
        CheckConstraint(
            "status <> 'REJECTED' OR "
            "(received_by IS NOT NULL AND rejected_at IS NOT NULL AND accepted_at IS NULL "
            "AND posted_at IS NULL AND cancelled_at IS NULL)",
            name='chk_transfer_header_rejected_audit'
        ),
        CheckConstraint(
            "status <> 'CANCELLED' OR "
            "(cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL "
            "AND accepted_at IS NULL AND rejected_at IS NULL AND posted_at IS NULL)",
            name='chk_transfer_header_cancelled_audit'
        ),
        CheckConstraint("status = 'CANCELLED' OR cancelled_by IS NULL",
                        name='chk_transfer_header_canceller_scope'),
        CheckConstraint(
            "status <> 'ACCEPTED' OR "
            "(received_by IS NOT NULL AND accepted_at IS NOT NULL AND rejected_at IS NULL "
            "AND cancelled_at IS NULL AND posted_at IS NULL)",
            name='chk_transfer_header_accepted_audit'
        ),
        CheckConstraint(
            "status <> 'POSTED' OR (posted_at IS NOT NULL AND rejected_at IS NULL AND cancelled_at IS NULL)",
            name='chk_transfer_header_posted_audit'
        ),
        CheckConstraint(
            "NOT (status = 'POSTED' AND workflow_type IN ('HANDSHAKE', 'TRANSIT')) "
            "OR (received_by IS NOT NULL AND accepted_at IS NOT NULL)",
            name='chk_transfer_header_received_before_post'
        ),
        CheckConstraint(
            "status NOT IN ('DRAFT', 'PENDING', 'IN_TRANSIT') OR "
            "(accepted_at IS NULL AND rejected_at IS NULL AND cancelled_at IS NULL AND posted_at IS NULL)",
            name='chk_transfer_header_nonterminal_timestamps'
        ),
        CheckConstraint(
            "accepted_at IS NULL OR accepted_at >= created_at",
            name='chk_transfer_header_accepted_time'
        ),
        CheckConstraint(
            "rejected_at IS NULL OR rejected_at >= created_at",
            name='chk_transfer_header_rejected_time'
        ),
        CheckConstraint(
            "cancelled_at IS NULL OR cancelled_at >= created_at",
            name='chk_transfer_header_cancelled_time'
        ),
        CheckConstraint(
            "posted_at IS NULL OR posted_at >= created_at",
            name='chk_transfer_header_posted_time'
        ),
        CheckConstraint(
            "posted_at IS NULL OR accepted_at IS NULL OR posted_at >= accepted_at",
            name='chk_transfer_header_post_after_accept'
        ),
    )
    id                      = Column(Integer, primary_key=True)
    company_id              = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    reference_number        = Column(String(100), nullable=False, index=True)
    source_location_id      = Column(Integer, nullable=False, index=True)
    destination_location_id = Column(Integer, nullable=False, index=True)
    transit_location_id     = Column(Integer, nullable=True, index=True)

    workflow_type           = Column(String(30), nullable=False, default='TRANSIT', server_default='TRANSIT', index=True)
    status                  = Column(String(50), nullable=False, default='DRAFT', server_default='DRAFT', index=True)

    work_session_id      = Column(Integer, nullable=True, index=True)
    expected_receiver_id = Column(Integer, nullable=True, index=True)
    dispatched_by        = Column(Integer, nullable=False, index=True)
    received_by          = Column(Integer, nullable=True, index=True)
    cancelled_by         = Column(Integer, nullable=True, index=True)

    decision_reason = Column(Text, nullable=True)
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime, nullable=False, default=utc_now)
    updated_at      = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    accepted_at     = Column(DateTime, nullable=True)
    rejected_at     = Column(DateTime, nullable=True)
    cancelled_at    = Column(DateTime, nullable=True)
    posted_at       = Column(DateTime, nullable=True)

class InventoryTransferLine(Base):
    # سطر حوالة Batch-aware، مع حفظ تجاوز FEFO إن حصل.
    __tablename__ = 'inventory_transfer_lines'
    __table_args__ = (
        UniqueConstraint('company_id', 'transfer_header_id', 'product_variant_id', 'batch_id', name='uq_transfer_line_item'),
        UniqueConstraint('company_id', 'id', name='uq_inventory_transfer_lines_company_id'),
        ForeignKeyConstraint(['company_id', 'transfer_header_id'], ['inventory_transfer_headers.company_id', 'inventory_transfer_headers.id'], ondelete='RESTRICT', name='fk_transfer_lines_tenant_header'),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id', 'batch_id'],
            ['product_batches.company_id', 'product_batches.product_variant_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_transfer_line_variant_batch'
        ),
        ForeignKeyConstraint(['company_id', 'fefo_override_reason_id'], ['override_reasons.company_id', 'override_reasons.id'], ondelete='RESTRICT', name='fk_transfer_line_tenant_override_reason'),
        ForeignKeyConstraint(['company_id', 'fefo_overridden_by'], ['drivers.company_id', 'drivers.id'], ondelete='RESTRICT', name='fk_transfer_line_tenant_override_actor'),
        CheckConstraint('quantity > 0', name='chk_transfer_line_qty'),
        CheckConstraint("((fefo_override_reason_id IS NULL AND fefo_overridden_by IS NULL) OR (fefo_override_reason_id IS NOT NULL AND fefo_overridden_by IS NOT NULL))", name='chk_transfer_line_fefo_override_pair'),
    )
    id                      = Column(Integer, primary_key=True)
    company_id              = Column(Integer, nullable=False, index=True)
    transfer_header_id      = Column(Integer, nullable=False, index=True)
    product_variant_id      = Column(Integer, nullable=False, index=True)
    batch_id                = Column(Integer, nullable=False, index=True)
    quantity                = Column(Integer, nullable=False)
    fefo_override_reason_id = Column(Integer, nullable=True)
    fefo_overridden_by      = Column(Integer, nullable=True)
    fefo_override_note      = Column(String(255), nullable=True)

# =================================================================================
# [المرحلة السادسة] محرك الجرد القانوني (Stocktake Engine)
# =================================================================================
class StocktakeSession(Base):
    # جلسة جرد قانونية تحفظ النطاق والـSnapshot وحالة الاعتماد دون طمس التاريخ.
    __tablename__ = 'stocktake_sessions'
    __table_args__ = (
        UniqueConstraint('company_id', 'reference_number', name='uq_stocktake_session_ref'),
        UniqueConstraint('company_id', 'id', name='uq_stocktake_sessions_company_id'),
        UniqueConstraint('company_id', 'id', 'location_id', name='uq_stocktake_session_location'),
        ForeignKeyConstraint(['company_id', 'location_id'], ['inventory_locations.company_id', 'inventory_locations.id'], ondelete='RESTRICT', name='fk_stocktake_session_tenant_location'),
        ForeignKeyConstraint(['company_id', 'scope_product_variant_id'], ['product_variants.company_id', 'product_variants.id'], ondelete='RESTRICT', name='fk_stocktake_session_tenant_scope_variant'),
        ForeignKeyConstraint(
            ['company_id', 'scope_product_variant_id', 'scope_batch_id'],
            ['product_batches.company_id', 'product_batches.product_variant_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_session_scope_variant_batch'
        ),
        ForeignKeyConstraint(['company_id', 'related_work_session_id'], ['work_sessions.company_id', 'work_sessions.id'], ondelete='RESTRICT', name='fk_stocktake_session_tenant_work_session'),
        ForeignKeyConstraint(['company_id', 'started_by'], ['drivers.company_id', 'drivers.id'], ondelete='RESTRICT', name='fk_stocktake_session_started_by'),
        ForeignKeyConstraint(['company_id', 'approved_by'], ['drivers.company_id', 'drivers.id'], ondelete='RESTRICT', name='fk_stocktake_session_approved_by'),
        ForeignKeyConstraint(['company_id', 'cancelled_by'], ['drivers.company_id', 'drivers.id'], ondelete='RESTRICT', name='fk_stocktake_session_cancelled_by'),
        ForeignKeyConstraint(['company_id', 'pending_recount_authorized_by'], ['drivers.company_id', 'drivers.id'], ondelete='RESTRICT', name='fk_stocktake_session_pending_recount_authorizer'),
        CheckConstraint("status IN ('DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED', 'POSTED', 'CANCELLED')", name='chk_stocktake_status'),
        CheckConstraint("stocktake_type IN ('FULL_COUNT', 'CYCLE_COUNT', 'VEHICLE_RECON')", name='chk_stocktake_type'),
        CheckConstraint('scope_batch_id IS NULL OR scope_product_variant_id IS NOT NULL', name='chk_stocktake_scope_batch_requires_product'),
        CheckConstraint("((stocktake_type = 'CYCLE_COUNT' AND scope_product_variant_id IS NOT NULL) OR (stocktake_type IN ('FULL_COUNT', 'VEHICLE_RECON') AND scope_product_variant_id IS NULL AND scope_batch_id IS NULL))", name='chk_stocktake_scope_by_type'),
        CheckConstraint("related_work_session_id IS NULL OR stocktake_type = 'VEHICLE_RECON'", name='chk_stocktake_work_session_scope'),
        CheckConstraint(
            "status IN ('DRAFT', 'CANCELLED') OR snapshot_cutoff_at IS NOT NULL",
            name='chk_stocktake_snapshot_cutoff'
        ),
        CheckConstraint(
            "status <> 'RECOUNT_REQUIRED' OR "
            "(pending_recount_authorized_by IS NOT NULL "
            "AND pending_recount_reason IS NOT NULL "
            "AND length(trim(pending_recount_reason)) > 0)",
            name='chk_stocktake_recount_authorization'
        ),
        CheckConstraint(
            "status = 'RECOUNT_REQUIRED' OR "
            "(pending_recount_authorized_by IS NULL "
            "AND pending_recount_reason IS NULL "
            "AND pending_independent_recount_required IS FALSE)",
            name='chk_stocktake_recount_pending_scope'
        ),
        CheckConstraint(
            "status NOT IN ('APPROVED', 'POSTED') OR "
            "(approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name='chk_stocktake_approved_audit'
        ),
        CheckConstraint(
            "status <> 'POSTED' OR posted_at IS NOT NULL",
            name='chk_stocktake_posted_audit'
        ),
        CheckConstraint(
            "status <> 'CANCELLED' OR "
            "(cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL "
            "AND cancellation_reason IS NOT NULL "
            "AND length(trim(cancellation_reason)) > 0)",
            name='chk_stocktake_cancelled_audit'
        ),
        CheckConstraint(
            "approved_at IS NULL OR approved_at >= created_at",
            name='chk_stocktake_approved_time'
        ),
        CheckConstraint(
            "posted_at IS NULL OR posted_at >= created_at",
            name='chk_stocktake_posted_time'
        ),
        CheckConstraint(
            "posted_at IS NULL OR approved_at IS NULL OR posted_at >= approved_at",
            name='chk_stocktake_post_after_approval'
        ),
        CheckConstraint(
            "cancelled_at IS NULL OR cancelled_at >= created_at",
            name='chk_stocktake_cancelled_time'
        ),
        Index('uq_active_full_stocktake_location', 'company_id', 'location_id', unique=True,
              postgresql_where=text("stocktake_type IN ('FULL_COUNT', 'VEHICLE_RECON') AND status IN ('DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED')")),
        Index('uq_active_cycle_stocktake_product', 'company_id', 'location_id', 'scope_product_variant_id', unique=True,
              postgresql_where=text("stocktake_type = 'CYCLE_COUNT' AND scope_batch_id IS NULL AND status IN ('DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED')")),
        Index('uq_active_cycle_stocktake_batch', 'company_id', 'location_id', 'scope_product_variant_id', 'scope_batch_id', unique=True,
              postgresql_where=text("stocktake_type = 'CYCLE_COUNT' AND scope_batch_id IS NOT NULL AND status IN ('DRAFT', 'COUNTING', 'PENDING_REVIEW', 'RECOUNT_REQUIRED', 'APPROVED')")),
    )
    id                       = Column(Integer, primary_key=True)
    company_id               = Column(Integer, ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    location_id              = Column(Integer, nullable=False, index=True)
    reference_number         = Column(String(100), nullable=False, index=True)
    stocktake_type           = Column(String(50), nullable=False, index=True)
    status                   = Column(String(50), nullable=False, default='DRAFT', server_default='DRAFT', index=True)
    scope_product_variant_id = Column(Integer, nullable=True, index=True)
    scope_batch_id           = Column(Integer, nullable=True, index=True)
    related_work_session_id  = Column(Integer, nullable=True, index=True)
    snapshot_cutoff_at       = Column(DateTime, nullable=True, index=True)

    started_by  = Column(Integer, nullable=False)
    approved_by = Column(Integer, nullable=True)
    cancelled_by= Column(Integer, nullable=True)

    pending_recount_authorized_by       = Column(Integer, nullable=True)
    pending_recount_reason              = Column(Text, nullable=True)
    pending_independent_recount_required= Column(Boolean, nullable=False, default=False, server_default='false')

    cancellation_reason = Column(Text, nullable=True)
    notes               = Column(Text, nullable=True)

    created_at   = Column(DateTime, nullable=False, default=utc_now)
    updated_at   = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    approved_at  = Column(DateTime, nullable=True)
    posted_at    = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

class StocktakeLine(Base):
    # خط الجرد هو Snapshot ثابت، أو صنف/دفعة مكتشفة أثناء العد برصيد متوقع صفر.
    __tablename__ = 'stocktake_lines'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_stocktake_lines_company_id'),
        UniqueConstraint('company_id', 'stocktake_session_id', 'id', name='uq_stocktake_line_session_id'),
        UniqueConstraint(
            'company_id', 'stocktake_session_id', 'product_variant_id', 'batch_id', 'stock_status',
            name='uq_stocktake_line_item'
        ),
        ForeignKeyConstraint(['company_id', 'stocktake_session_id'], ['stocktake_sessions.company_id', 'stocktake_sessions.id'],
                             ondelete='RESTRICT', name='fk_stocktake_lines_tenant_session'),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id', 'batch_id'],
            ['product_batches.company_id', 'product_batches.product_variant_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_line_variant_batch'
        ),
        ForeignKeyConstraint(['company_id', 'discovered_by'], ['drivers.company_id', 'drivers.id'],
                             ondelete='RESTRICT', name='fk_stocktake_line_tenant_discoverer'),
        CheckConstraint("stock_status IN ('AVAILABLE', 'DAMAGED')", name='chk_stocktake_line_status'),
        CheckConstraint("line_origin IN ('SNAPSHOT', 'DISCOVERED')", name='chk_stocktake_line_origin'),
        CheckConstraint('expected_quantity >= 0', name='chk_st_line_exp_qty'),
        CheckConstraint(
            "((line_origin = 'SNAPSHOT' AND discovered_by IS NULL AND discovered_at IS NULL) OR "
            "(line_origin = 'DISCOVERED' AND expected_quantity = 0 "
            "AND discovered_by IS NOT NULL AND discovered_at IS NOT NULL))",
            name='chk_stocktake_line_origin_metadata'
        ),
    )
    id                   = Column(Integer, primary_key=True)
    company_id           = Column(Integer, nullable=False, index=True)
    stocktake_session_id = Column(Integer, nullable=False, index=True)
    product_variant_id   = Column(Integer, nullable=False, index=True)
    batch_id             = Column(Integer, nullable=False, index=True)
    stock_status         = Column(String(50), nullable=False, default='AVAILABLE', server_default='AVAILABLE')
    line_origin          = Column(String(20), nullable=False, default='SNAPSHOT', server_default='SNAPSHOT', index=True)

    expected_quantity = Column(Integer, nullable=False)
    discovered_by     = Column(Integer, nullable=True, index=True)
    discovered_at     = Column(DateTime, nullable=True)
    notes             = Column(Text, nullable=True)

class StocktakeCountAttempt(Base):
    # كل إنهاء عد ينشئ محاولة مستقلة؛ أي Recount يجب أن ينتسب لمحاولة من نفس الجلسة.
    __tablename__ = 'stocktake_count_attempts'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_stocktake_count_attempts_company_id'),
        UniqueConstraint('company_id', 'stocktake_session_id', 'id', name='uq_stocktake_attempt_session_id'),
        UniqueConstraint('company_id', 'stocktake_session_id', 'attempt_number', name='uq_stocktake_attempt_number'),
        ForeignKeyConstraint(
            ['company_id', 'stocktake_session_id'],
            ['stocktake_sessions.company_id', 'stocktake_sessions.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_tenant_session'
        ),
        ForeignKeyConstraint(
            ['company_id', 'stocktake_session_id', 'recount_of_attempt_id'],
            ['stocktake_count_attempts.company_id', 'stocktake_count_attempts.stocktake_session_id', 'stocktake_count_attempts.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_recount_parent_same_session'
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
        CheckConstraint(
            "((attempt_number = 1 "
            "AND recount_of_attempt_id IS NULL "
            "AND authorized_by IS NULL "
            "AND recount_reason IS NULL) "
            "OR "
            "(attempt_number > 1 "
            "AND recount_of_attempt_id IS NOT NULL "
            "AND authorized_by IS NOT NULL "
            "AND recount_reason IS NOT NULL "
            "AND length(trim(recount_reason)) > 0))",
            name='chk_stocktake_attempt_recount_metadata'
        ),
    )
    id                    = Column(Integer, primary_key=True)
    company_id            = Column(Integer, nullable=False, index=True)
    stocktake_session_id  = Column(Integer, nullable=False, index=True)
    attempt_number        = Column(Integer, nullable=False)
    recount_of_attempt_id = Column(Integer, nullable=True, index=True)

    counted_by    = Column(Integer, nullable=False, index=True)
    authorized_by = Column(Integer, nullable=True, index=True)
    recount_reason= Column(Text, nullable=True)
    requires_independent_recount = Column(Boolean, nullable=False, default=False, server_default='false')

    submitted_at = Column(DateTime, nullable=False, default=utc_now, index=True)

class StocktakeCountAttemptLine(Base):
    # سطر عد Immutable مرتبط بسطر الجرد الأصلي وبنفس جلسة المحاولة.
    __tablename__ = 'stocktake_count_attempt_lines'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_stocktake_count_attempt_lines_company_id'),
        UniqueConstraint('company_id', 'count_attempt_id', 'stocktake_line_id', name='uq_stocktake_attempt_line_snapshot'),
        ForeignKeyConstraint(
            ['company_id', 'stocktake_session_id', 'count_attempt_id'],
            ['stocktake_count_attempts.company_id', 'stocktake_count_attempts.stocktake_session_id', 'stocktake_count_attempts.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_line_same_session_attempt'
        ),
        ForeignKeyConstraint(
            ['company_id', 'stocktake_session_id', 'stocktake_line_id'],
            ['stocktake_lines.company_id', 'stocktake_lines.stocktake_session_id', 'stocktake_lines.id'],
            ondelete='RESTRICT',
            name='fk_stocktake_attempt_line_same_session_snapshot'
        ),
        CheckConstraint('expected_quantity >= 0', name='chk_stocktake_attempt_line_expected'),
        CheckConstraint('actual_quantity >= 0', name='chk_stocktake_attempt_line_actual'),
        CheckConstraint('variance_quantity = actual_quantity - expected_quantity', name='chk_stocktake_attempt_line_variance'),
    )
    id                   = Column(Integer, primary_key=True)
    company_id           = Column(Integer, nullable=False, index=True)
    stocktake_session_id = Column(Integer, nullable=False, index=True)
    count_attempt_id     = Column(Integer, nullable=False, index=True)
    stocktake_line_id    = Column(Integer, nullable=False, index=True)

    expected_quantity = Column(Integer, nullable=False)
    actual_quantity   = Column(Integer, nullable=False)
    variance_quantity = Column(Integer, nullable=False)
    notes             = Column(Text, nullable=True)

class InventoryLock(Base):
    # قفل جراحي قابل للتتبع؛ لا يُحذف بعد التحرير بل يبقى كسجل تاريخي.
    __tablename__ = 'inventory_locks'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_inventory_locks_company_id'),
        ForeignKeyConstraint(
            ['company_id', 'stocktake_session_id', 'location_id'],
            ['stocktake_sessions.company_id', 'stocktake_sessions.id', 'stocktake_sessions.location_id'],
            ondelete='RESTRICT',
            name='fk_inv_lock_same_stocktake_location'
        ),
        ForeignKeyConstraint(['company_id', 'location_id'], ['inventory_locations.company_id', 'inventory_locations.id'], ondelete='RESTRICT', name='fk_inv_lock_tenant_location'),
        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'], ondelete='RESTRICT', name='fk_inv_lock_tenant_variant'),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id', 'batch_id'],
            ['product_batches.company_id', 'product_batches.product_variant_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_inv_lock_variant_batch'
        ),
        ForeignKeyConstraint(['company_id', 'created_by'], ['drivers.company_id', 'drivers.id'], ondelete='RESTRICT', name='fk_inv_lock_tenant_creator'),
        ForeignKeyConstraint(['company_id', 'released_by'], ['drivers.company_id', 'drivers.id'], ondelete='RESTRICT', name='fk_inv_lock_tenant_releaser'),
        CheckConstraint('batch_id IS NULL OR product_variant_id IS NOT NULL', name='chk_inv_lock_batch_requires_product'),
        CheckConstraint(
            "((released_at IS NULL AND released_by IS NULL AND release_reason IS NULL) "
            "OR (released_at IS NOT NULL AND released_by IS NOT NULL "
            "AND release_reason IS NOT NULL AND length(trim(release_reason)) > 0))",
            name='chk_inv_lock_release_metadata'
        ),
        CheckConstraint(
            'released_at IS NULL OR released_at >= created_at',
            name='chk_inv_lock_release_time'
        ),
        Index('ix_active_inv_lock', 'company_id', 'location_id', postgresql_where=text("released_at IS NULL")),
        Index('uq_active_inv_lock_location', 'company_id', 'location_id', unique=True,
              postgresql_where=text("released_at IS NULL AND product_variant_id IS NULL AND batch_id IS NULL")),
        Index('uq_active_inv_lock_product', 'company_id', 'location_id', 'product_variant_id', unique=True,
              postgresql_where=text("released_at IS NULL AND product_variant_id IS NOT NULL AND batch_id IS NULL")),
        Index('uq_active_inv_lock_batch', 'company_id', 'location_id', 'product_variant_id', 'batch_id', unique=True,
              postgresql_where=text("released_at IS NULL AND batch_id IS NOT NULL")),
    )
    id                   = Column(Integer, primary_key=True)
    company_id           = Column(Integer, nullable=False, index=True)
    stocktake_session_id = Column(Integer, nullable=False, index=True)
    location_id          = Column(Integer, nullable=False, index=True)
    product_variant_id   = Column(Integer, nullable=True, index=True)
    batch_id             = Column(Integer, nullable=True, index=True)

    created_by     = Column(Integer, nullable=False, index=True)
    created_at     = Column(DateTime, nullable=False, default=utc_now)
    released_by    = Column(Integer, nullable=True, index=True)
    released_at    = Column(DateTime, nullable=True, index=True)
    release_reason = Column(Text, nullable=True)
