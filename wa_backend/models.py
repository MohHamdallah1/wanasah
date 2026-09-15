from sqlalchemy import BigInteger, Column, Integer, String, Boolean, DateTime, Date, Numeric, Text, JSON, Uuid, ForeignKey, CheckConstraint, UniqueConstraint, Index, MetaData, text, Table, ForeignKeyConstraint, Computed
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import relationship, declarative_base, backref
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
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
    Column('company_id', Integer, nullable=False),
    Column('role_id', Integer, primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
    ForeignKeyConstraint(['company_id', 'role_id'], ['roles.company_id', 'roles.id'],
                         ondelete='CASCADE', name='fk_role_permissions_tenant_role'),
    Index('ix_role_permissions_company_role', 'company_id', 'role_id'),
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
    """منطقة توزيع بجدولة رقمية صريحة: start_date هي الزيارة القادمة وinterval_days هو التكرار بالأيام."""
    __tablename__ = 'zones'
    __table_args__ = (
        UniqueConstraint('company_id', 'name', 'governorate_id', name='uq_company_zone_gov'),
        Index('idx_uq_zone_company_name_null_gov', 'company_id', 'name', unique=True, postgresql_where=text("governorate_id IS NULL")),
        UniqueConstraint('company_id', 'id', name='uq_zones_company_id'),
        CheckConstraint('interval_days IS NULL OR interval_days > 0', name='chk_zone_interval_days_positive'),
        CheckConstraint(
            '((start_date IS NULL AND interval_days IS NULL) OR '
            '(start_date IS NOT NULL AND interval_days IS NOT NULL))',
            name='chk_zone_schedule_pair'
        ),
    )
    id              = Column(Integer, primary_key=True)
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    name            = Column(String(100), nullable=False)
    governorate_id  = Column(Integer, ForeignKey('governorates.id', ondelete='SET NULL'), nullable=True)
    sequence_number = Column(Integer, nullable=True)

    # لا parsing نصي: كل N يوم فقط. "شهري" التقويمي ليس 30 يوماً ولا نمثله بهذا الحقل.
    start_date    = Column(Date, nullable=True)
    interval_days = Column(Integer, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    shops = relationship('Shop', backref='zone', lazy='raise', foreign_keys='Shop.zone_id')



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
    """عائلة Master Data مستقلة عن المواقع والمخزون والتسعير."""
    __tablename__ = 'products'
    __table_args__ = (
        UniqueConstraint('company_id', 'code', name='uq_company_product_code'),
        UniqueConstraint('company_id', 'id', name='uq_products_company_id'),
        Index('ix_product_company_name_id', 'company_id', 'name', 'id'),
    )
    id          = Column(Integer, primary_key=True)
    company_id  = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    code        = Column(String(100), nullable=False)
    name        = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    brand       = Column(String(100), nullable=True)
    category    = Column(String(100), nullable=True)
    version     = Column(Integer, nullable=False, default=1, server_default='1')
    created_at  = Column(DateTime, nullable=False, default=utc_now)
    updated_at  = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    variants = relationship('ProductVariant', backref='product', lazy='raise')

class ProductVariant(Base):
    """SKU بنيوي؛ يبدأ Draft وتخضع كمياته لدقة وخطوة UOM."""
    __tablename__ = 'product_variants'
    __table_args__ = (
        UniqueConstraint('company_id', 'sku', name='uq_company_sku'),
        UniqueConstraint('company_id', 'id', name='uq_product_variants_company_id'),
        Index('ix_product_variant_company_name_id', 'company_id', 'name', 'id'),
        Index('uq_product_variant_company_gtin', 'company_id', 'gtin', unique=True, postgresql_where=text('gtin IS NOT NULL')),
        ForeignKeyConstraint(
            ['company_id', 'product_id'],
            ['products.company_id', 'products.id'],
            ondelete='RESTRICT',
            name='fk_product_variant_tenant_product'
        ),
        CheckConstraint('quantity_scale BETWEEN 0 AND 6', name='chk_product_variant_quantity_scale'),
        CheckConstraint('quantity_step > 0', name='chk_product_variant_quantity_step'),
        CheckConstraint('quantity_step = round(quantity_step, quantity_scale)', name='chk_product_variant_quantity_step_scale'),
        CheckConstraint("lot_control_mode IN ('NONE', 'OPTIONAL', 'REQUIRED')", name='chk_product_variant_lot_control'),
        CheckConstraint("expiry_control_mode IN ('NONE', 'OPTIONAL', 'REQUIRED')", name='chk_product_variant_expiry_control'),
        CheckConstraint("lifecycle_status IN ('DRAFT', 'ACTIVE', 'RETIRING', 'ARCHIVED')", name='chk_product_variant_lifecycle'),
        CheckConstraint("operational_hold IN ('NONE', 'SALES_HOLD', 'RECALL')", name='chk_product_variant_hold'),
        CheckConstraint(
            "((lifecycle_status = 'DRAFT' AND published_at IS NULL AND retired_at IS NULL AND archived_at IS NULL) OR "
            "(lifecycle_status = 'ACTIVE' AND published_at IS NOT NULL AND retired_at IS NULL AND archived_at IS NULL) OR "
            "(lifecycle_status = 'RETIRING' AND published_at IS NOT NULL AND retired_at IS NOT NULL AND archived_at IS NULL) OR "
            "(lifecycle_status = 'ARCHIVED' AND published_at IS NOT NULL AND retired_at IS NOT NULL AND archived_at IS NOT NULL))",
            name='chk_product_variant_lifecycle_timestamps'
        ),
        CheckConstraint('lifecycle_revision > 0', name='chk_product_variant_lifecycle_revision'),
        CheckConstraint('version > 0', name='chk_product_variant_version'),
        CheckConstraint('packs_per_carton > 0', name='chk_packs_per_carton_positive'),
        CheckConstraint('default_max_samples_per_day >= 0', name='chk_product_variant_samples_limit'),
    )
    id          = Column(Integer, primary_key=True)
    company_id  = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    product_id  = Column(Integer, nullable=False, index=True)
    base_uom_id = Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False)

    name             = Column(String(200), nullable=False)
    sku              = Column(String(100), nullable=False)
    gtin             = Column(String(14), nullable=True)
    quantity_scale   = Column(Integer, nullable=False, default=0, server_default='0')
    quantity_step    = Column(Numeric(20, 6), nullable=False, default=Decimal('1'), server_default='1')
    lot_control_mode = Column(String(20), nullable=False, default='REQUIRED', server_default='REQUIRED')
    expiry_control_mode = Column(String(20), nullable=False, default='REQUIRED', server_default='REQUIRED')
    lifecycle_status = Column(String(20), nullable=False, default='DRAFT', server_default='DRAFT', index=True)
    operational_hold = Column(String(20), nullable=False, default='NONE', server_default='NONE', index=True)
    lifecycle_revision = Column(Integer, nullable=False, default=1, server_default='1')
    version          = Column(Integer, nullable=False, default=1, server_default='1')
    published_at     = Column(DateTime, nullable=True)
    retired_at       = Column(DateTime, nullable=True)
    archived_at      = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, nullable=False, default=utc_now)
    updated_at       = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    # Carton shape remains only as quantity/UOM compatibility.
    # Commercial prices are authoritative only in temporal PriceBook publications.
    packs_per_carton = Column(Integer, nullable=False, default=50, server_default='50')
    default_max_samples_per_day = Column(Integer, nullable=False, default=0, server_default='0')

    @property
    def variant_name(self):
        return self.name


class ProductUomConversion(Base):
    """تحويل Exact Rational خاص بـVariant، قابل للتحرير في DRAFT فقط."""
    __tablename__ = 'product_uom_conversions'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_product_uom_conversions_company_id'),
        UniqueConstraint('company_id', 'product_variant_id', 'from_uom_id', 'to_uom_id', name='uq_product_uom_conversion'),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id'],
            ['product_variants.company_id', 'product_variants.id'],
            ondelete='RESTRICT',
            name='fk_product_uom_conversion_tenant_variant'
        ),
        CheckConstraint('from_uom_id <> to_uom_id', name='chk_product_uom_conversion_distinct'),
        CheckConstraint('numerator > 0', name='chk_product_uom_conversion_numerator'),
        CheckConstraint('denominator > 0', name='chk_product_uom_conversion_denominator'),
        CheckConstraint('quantity_scale BETWEEN 0 AND 6', name='chk_product_uom_conversion_scale'),
        CheckConstraint('version > 0', name='chk_product_uom_conversion_version'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    from_uom_id        = Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False)
    to_uom_id          = Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False)
    numerator          = Column(Numeric(20, 6), nullable=False)
    denominator        = Column(Numeric(20, 6), nullable=False)
    quantity_scale     = Column(Integer, nullable=False, default=0, server_default='0')
    version            = Column(Integer, nullable=False, default=1, server_default='1')
    created_at         = Column(DateTime, nullable=False, default=utc_now)
    updated_at         = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class ProductBarcode(Base):
    """هوية مسح one-to-many؛ lot/expiry/serial تستخرج من GS1 ولا تثبت هنا."""
    __tablename__ = 'product_barcodes'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_product_barcodes_company_id'),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id'],
            ['product_variants.company_id', 'product_variants.id'],
            ondelete='RESTRICT',
            name='fk_product_barcode_tenant_variant'
        ),
        CheckConstraint("barcode_type IN ('EAN8', 'EAN13', 'UPC_A', 'GTIN14', 'GS1_128', 'INTERNAL')", name='chk_product_barcode_type'),
        CheckConstraint('valid_to IS NULL OR valid_to > valid_from', name='chk_product_barcode_validity'),
        CheckConstraint('version > 0', name='chk_product_barcode_version'),
        Index('uq_active_product_barcode', 'company_id', 'barcode', unique=True, postgresql_where=text('is_active IS TRUE')),
        Index('uq_primary_product_barcode_uom', 'company_id', 'product_variant_id', 'uom_id', unique=True, postgresql_where=text('is_primary IS TRUE AND is_active IS TRUE')),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    uom_id             = Column(Integer, ForeignKey('uom.id', ondelete='RESTRICT'), nullable=False)
    barcode            = Column(String(128), nullable=False)
    barcode_type       = Column(String(20), nullable=False)
    is_primary         = Column(Boolean, nullable=False, default=False, server_default='false')
    valid_from         = Column(DateTime, nullable=False, default=utc_now)
    valid_to           = Column(DateTime, nullable=True)
    is_active          = Column(Boolean, nullable=False, default=True, server_default='true')
    version            = Column(Integer, nullable=False, default=1, server_default='1')
    created_at         = Column(DateTime, nullable=False, default=utc_now)
    updated_at         = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class ProductLocation(Base):
    """Sparse operational assignment; never stores stock, reservations or prices."""
    __tablename__ = 'product_locations'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_product_locations_company_id'),
        UniqueConstraint('company_id', 'location_id', 'product_variant_id', name='uq_product_location_assignment'),
        ForeignKeyConstraint(
            ['company_id', 'location_id'],
            ['inventory_locations.company_id', 'inventory_locations.id'],
            ondelete='RESTRICT',
            name='fk_product_location_tenant_location'
        ),
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id'],
            ['product_variants.company_id', 'product_variants.id'],
            ondelete='RESTRICT',
            name='fk_product_location_tenant_variant'
        ),
        ForeignKeyConstraint(
            ['company_id', 'created_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_product_location_tenant_creator'
        ),
        CheckConstraint("jsonb_typeof(operational_flags) = 'object'", name='chk_product_location_flags_object'),
        CheckConstraint(
            "operational_flags ?& ARRAY['inbound_enabled', 'outbound_enabled'] "
            "AND operational_flags - 'inbound_enabled' - 'outbound_enabled' = '{}'::jsonb "
            "AND jsonb_typeof(operational_flags->'inbound_enabled') = 'boolean' "
            "AND jsonb_typeof(operational_flags->'outbound_enabled') = 'boolean'",
            name='chk_product_location_flags_contract'
        ),
        CheckConstraint('version > 0', name='chk_product_location_version'),
        Index('ix_product_location_variant_location', 'company_id', 'product_variant_id', 'location_id'),
        Index('ix_product_location_location_variant', 'company_id', 'location_id', 'product_variant_id'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    location_id        = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    operational_flags  = Column(
        JSONB,
        nullable=False,
        default=lambda: {'inbound_enabled': True, 'outbound_enabled': True},
        server_default=text("'{\"inbound_enabled\": true, \"outbound_enabled\": true}'::jsonb"),
    )
    version            = Column(Integer, nullable=False, default=1, server_default='1')
    created_by         = Column(Integer, nullable=False, index=True)
    created_at         = Column(DateTime, nullable=False, default=utc_now)
    updated_at         = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


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
        UniqueConstraint(
            'company_id', 'commercial_context_id',
            name='uq_work_sessions_commercial_context'
        ),
        ForeignKeyConstraint(
            ['company_id', 'driver_id'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_work_session_tenant_driver'
        ),
        ForeignKeyConstraint(
            ['company_id', 'commercial_context_id'],
            ['route_commercial_contexts.company_id', 'route_commercial_contexts.id'],
            ondelete='RESTRICT',
            name='fk_work_session_tenant_commercial_context'
        ),
        CheckConstraint(
            'end_time IS NULL OR end_time >= start_time',
            name='chk_work_session_time_order'
        ),
        CheckConstraint(
            'is_settled IS FALSE OR end_time IS NOT NULL',
            name='chk_work_session_settlement_requires_end'
        ),
        ForeignKeyConstraint(
            ['company_id', 'inventory_reconciled_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_work_session_inventory_reconciler'
        ),
        CheckConstraint(
            "((inventory_reconciled_at IS NULL AND inventory_reconciled_by IS NULL) OR "
            "(inventory_reconciled_at IS NOT NULL AND inventory_reconciled_by IS NOT NULL "
            "AND end_time IS NOT NULL))",
            name='chk_work_session_inventory_reconciliation_pair'
        ),
        CheckConstraint(
            'inventory_reconciled_at IS NULL OR inventory_reconciled_at >= end_time',
            name='chk_work_session_inventory_reconciliation_after_end'
        ),
        CheckConstraint(
            'is_settled IS FALSE OR inventory_reconciled_at IS NOT NULL',
            name='chk_work_session_financial_settlement_requires_inventory_reconciliation'
        ),
    )
    id           = Column(Integer, primary_key=True)
    company_id   = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    driver_id    = Column(Integer, nullable=False, index=True)
    commercial_context_id = Column(Integer, nullable=True)
    start_time   = Column(DateTime, nullable=False, default=utc_now)
    end_time     = Column(DateTime, nullable=True, index=True)
    session_date = Column(Date, nullable=False, default=lambda: utc_now().date(), index=True)
    start_latitude  = Column(Numeric(10, 7), nullable=True)
    start_longitude = Column(Numeric(10, 7), nullable=True)

    is_authorized_to_sell = Column(Boolean, nullable=False, default=False, server_default='false')
    break_start_time      = Column(DateTime, nullable=True)
    break_end_time        = Column(DateTime, nullable=True)

    # مرحلتان مستقلتان عمداً:
    # inventory_reconciled_* = إغلاق عهدة المخزون فقط.
    # is_settled = التسوية المالية النهائية لدى المحاسب فقط.
    inventory_reconciled_at = Column(DateTime, nullable=True, index=True)
    inventory_reconciled_by = Column(Integer, nullable=True, index=True)
    is_settled              = Column(Boolean, nullable=False, default=False, server_default='false', index=True)

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
            'company_id', 'work_session_id', 'product_variant_id', 'stock_status',
            name='uq_session_inventory_snapshot_variant_status'
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
        CheckConstraint("stock_status IN ('AVAILABLE', 'QUARANTINED', 'BLOCKED', 'RECALLED', 'DAMAGED', 'DISPOSAL_PENDING')", name='chk_session_snapshot_stock_status'),
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
    stock_status       = Column(String(50), nullable=False, index=True)

    starting_quantity = Column(Numeric(20, 6), nullable=False)
    ending_quantity   = Column(Numeric(20, 6), nullable=True)
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
        # PostgreSQL يسمح بعدة NULL؛ أي هاتف فعلي يبقى فريداً داخل Tenant.
        UniqueConstraint('company_id', 'phone_number', name='uq_shop_company_phone'),
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
        ForeignKeyConstraint(
            ['company_id', 'archived_due_to_zone_id'],
            ['zones.company_id', 'zones.id'],
            ondelete='RESTRICT',
            name='fk_shop_tenant_archive_source_zone'
        ),
        ForeignKeyConstraint(
            ['company_id', 'tax_jurisdiction_id'],
            ['tax_jurisdictions.company_id', 'tax_jurisdictions.id'],
            ondelete='RESTRICT',
            name='fk_shop_tenant_tax_jurisdiction'
        ),
        CheckConstraint(
            'archived_due_to_zone_id IS NULL OR '
            '(is_archived IS TRUE AND zone_id = archived_due_to_zone_id)',
            name='chk_shop_zone_archive_provenance'
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
    # سلطة ضريبية صريحة؛ لا تُستنتج أبداً من العنوان أو Zone.
    tax_jurisdiction_id = Column(Integer, nullable=True, index=True)
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
    # يحدد فقط المحلات التي أرشفت تلقائياً بسبب أرشفة منطقتها؛ الأرشفة اليدوية تبقى NULL.
    archived_due_to_zone_id = Column(Integer, nullable=True, index=True)

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
        # يدعم lookup أحدث route لكل سيارة عبر equality prefix ثم backward scan على id.
        Index('ix_dispatch_route_company_vehicle_latest', 'company_id', 'vehicle_id', 'id'),
        UniqueConstraint('company_id', 'id', name='uq_dispatch_routes_company_id'),
        UniqueConstraint('company_id', 'work_session_id', name='uq_dispatch_routes_work_session'),
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
        CheckConstraint('work_session_id IS NULL OR vehicle_id IS NOT NULL',
                        name='chk_dispatch_route_session_requires_vehicle'),
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

# =================================================================================
# ⑧.1 التسعير الزمني وسياق Route التجاري — Stage 5
# =================================================================================
class PriceBook(Base):
    """Tenant-owned price book. Product master data never stores a live sale price."""
    __tablename__ = "price_books"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_price_books_company_id"),
        UniqueConstraint("company_id", "code", name="uq_price_book_company_code"),
        ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_price_book_tenant_creator",
        ),
        CheckConstraint("length(trim(code)) > 0", name="chk_price_book_code_not_blank"),
        CheckConstraint("length(trim(name)) > 0", name="chk_price_book_name_not_blank"),
        CheckConstraint("length(trim(currency_code)) > 0", name="chk_price_book_currency_not_blank"),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="chk_price_book_status"),
        CheckConstraint("version > 0", name="chk_price_book_version"),
        CheckConstraint(
            "jsonb_typeof(applicability_metadata) = 'object'",
            name="chk_price_book_applicability_object",
        ),
        Index("ix_price_book_company_status", "company_id", "status", "id"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    currency_code = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    applicability_metadata = Column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_by = Column(Integer, nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PricePublication(Base):
    """Immutable-after-publish revision of one PriceBook.

    revision is tenant-global (not merely per book) so a RouteCommercialContext can
    store one deterministic publication revision ceiling without copying every price.
    """
    __tablename__ = "price_publications"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_price_publications_company_id"),
        UniqueConstraint(
            "company_id", "id", "price_book_id",
            name="uq_price_publication_company_id_book",
        ),
        UniqueConstraint(
            "company_id", "revision",
            name="uq_price_publication_company_revision",
        ),
        UniqueConstraint(
            "company_id", "request_id",
            name="uq_price_publication_company_request",
        ),
        ForeignKeyConstraint(
            ["company_id", "price_book_id"],
            ["price_books.company_id", "price_books.id"],
            ondelete="RESTRICT",
            name="fk_price_publication_tenant_book",
        ),
        ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_price_publication_tenant_creator",
        ),
        ForeignKeyConstraint(
            ["company_id", "approved_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_price_publication_tenant_approver",
        ),
        CheckConstraint("revision > 0", name="chk_price_publication_revision"),
        CheckConstraint(
            "status IN ('DRAFT','PENDING_APPROVAL','PUBLISHED','SUPERSEDED','CANCELLED')",
            name="chk_price_publication_status",
        ),
        CheckConstraint("version > 0", name="chk_price_publication_version"),
        CheckConstraint(
            "status NOT IN ('PUBLISHED','SUPERSEDED') OR "
            "(effective_at IS NOT NULL AND approved_by IS NOT NULL "
            "AND approved_at IS NOT NULL AND published_at IS NOT NULL)",
            name="chk_price_publication_published_metadata",
        ),
        Index(
            "ix_price_publication_resolver",
            "company_id", "price_book_id", "status", "revision", "effective_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    price_book_id = Column(Integer, nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="DRAFT", server_default="DRAFT", index=True)
    effective_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_by = Column(Integer, nullable=False, index=True)
    approved_by = Column(Integer, nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True, index=True)
    request_id = Column(Uuid(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PriceBookEntry(Base):
    """Effective-dated price row; published history is overlap-protected in PostgreSQL."""
    __tablename__ = "price_book_entries"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_price_book_entries_company_id"),
        ForeignKeyConstraint(
            ["company_id", "price_book_id"],
            ["price_books.company_id", "price_books.id"],
            ondelete="RESTRICT",
            name="fk_price_book_entry_tenant_book",
        ),
        ForeignKeyConstraint(
            ["company_id", "publication_id", "price_book_id"],
            [
                "price_publications.company_id",
                "price_publications.id",
                "price_publications.price_book_id",
            ],
            ondelete="RESTRICT",
            name="fk_price_book_entry_tenant_publication_book",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_variant_id"],
            ["product_variants.company_id", "product_variants.id"],
            ondelete="RESTRICT",
            name="fk_price_book_entry_tenant_variant",
        ),
        CheckConstraint("amount >= 0", name="chk_price_book_entry_amount"),
        CheckConstraint("priority >= 0", name="chk_price_book_entry_priority"),
        CheckConstraint("version > 0", name="chk_price_book_entry_version"),
        CheckConstraint(
            "NOT isempty(effectivity) AND lower(effectivity) IS NOT NULL "
            "AND lower_inc(effectivity) AND NOT upper_inc(effectivity)",
            name="chk_price_book_entry_effectivity_half_open",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="chk_price_book_entry_metadata_object",
        ),
        ExcludeConstraint(
            ("company_id", "="),
            ("price_book_id", "="),
            ("product_variant_id", "="),
            ("uom_id", "="),
            ("effectivity", "&&"),
            where=text("is_published IS TRUE"),
            using="gist",
            name="excl_price_book_entry_published_overlap",
        ),
        Index(
            "ix_price_book_entry_resolver",
            "company_id", "price_book_id", "product_variant_id", "uom_id",
            "is_published", "priority", "publication_id",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    price_book_id = Column(Integer, nullable=False, index=True)
    publication_id = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    uom_id = Column(Integer, ForeignKey("uom.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount = Column(Numeric(20, 6), nullable=False)
    effectivity = Column(TSTZRANGE, nullable=False)
    priority = Column(Integer, nullable=False, default=0, server_default="0")
    is_published = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    entry_metadata = Column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )


class PriceBookAssignment(Base):
    """Effective-dated assignment with deterministic precedence.

    Stage 5 initially supports CUSTOMER (Shop), BRANCH, and COMPANY_DEFAULT.
    CUSTOMER_GROUP and CHANNEL remain reserved resolver scopes until real tenant
    entities exist; they are intentionally rejected by the database today.
    """
    __tablename__ = "price_book_assignments"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_price_book_assignments_company_id"),
        UniqueConstraint(
            "company_id", "revision",
            name="uq_price_book_assignment_company_revision",
        ),
        ForeignKeyConstraint(
            ["company_id", "price_book_id"],
            ["price_books.company_id", "price_books.id"],
            ondelete="RESTRICT",
            name="fk_price_book_assignment_tenant_book",
        ),
        ForeignKeyConstraint(
            ["company_id", "customer_scope_id"],
            ["shops.company_id", "shops.id"],
            ondelete="RESTRICT",
            name="fk_price_book_assignment_tenant_customer",
        ),
        ForeignKeyConstraint(
            ["company_id", "branch_scope_id"],
            ["branches.company_id", "branches.id"],
            ondelete="RESTRICT",
            name="fk_price_book_assignment_tenant_branch",
        ),
        ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_price_book_assignment_tenant_creator",
        ),
        CheckConstraint(
            "scope_type IN ('CUSTOMER','BRANCH','COMPANY_DEFAULT')",
            name="chk_price_book_assignment_scope_type",
        ),
        CheckConstraint(
            "((scope_type IN ('CUSTOMER','BRANCH') AND scope_id IS NOT NULL AND scope_id > 0) "
            "OR (scope_type = 'COMPANY_DEFAULT' AND scope_id IS NULL))",
            name="chk_price_book_assignment_scope_id",
        ),
        CheckConstraint("priority >= 0", name="chk_price_book_assignment_priority"),
        CheckConstraint("revision > 0", name="chk_price_book_assignment_revision"),
        CheckConstraint("version > 0", name="chk_price_book_assignment_version"),
        CheckConstraint(
            "NOT isempty(effectivity) AND lower(effectivity) IS NOT NULL "
            "AND lower_inc(effectivity) AND NOT upper_inc(effectivity)",
            name="chk_price_book_assignment_effectivity_half_open",
        ),
        ExcludeConstraint(
            ("company_id", "="),
            ("scope_type", "="),
            ("scope_identity", "="),
            ("priority", "="),
            ("effectivity", "&&"),
            using="gist",
            name="excl_price_book_assignment_equal_priority_overlap",
        ),
        Index(
            "ix_price_book_assignment_resolver",
            "company_id", "scope_type", "scope_identity", "priority", "revision",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    price_book_id = Column(Integer, nullable=False, index=True)
    scope_type = Column(String(30), nullable=False, index=True)
    scope_id = Column(Integer, nullable=True)
    customer_scope_id = Column(
        Integer,
        Computed(
            "CASE WHEN scope_type = 'CUSTOMER' THEN scope_id ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    branch_scope_id = Column(
        Integer,
        Computed(
            "CASE WHEN scope_type = 'BRANCH' THEN scope_id ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    scope_identity = Column(
        Integer,
        Computed("COALESCE(scope_id, 0)", persisted=True),
        nullable=False,
    )
    allow_offers = Column(Boolean, nullable=False, default=True, server_default="true")
    priority = Column(Integer, nullable=False, default=0, server_default="0")
    effectivity = Column(TSTZRANGE, nullable=False)
    revision = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_by = Column(Integer, nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )


class RouteCommercialContext(Base):
    """One immutable commercial lock per launched DispatchRoute."""
    __tablename__ = "route_commercial_contexts"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_route_commercial_contexts_company_id"),
        UniqueConstraint(
            "company_id", "dispatch_route_id",
            name="uq_route_commercial_context_route",
        ),
        ForeignKeyConstraint(
            ["company_id", "dispatch_route_id"],
            ["dispatch_routes.company_id", "dispatch_routes.id"],
            ondelete="RESTRICT",
            name="fk_route_commercial_context_tenant_route",
        ),
        CheckConstraint(
            "price_publication_revision > 0",
            name="chk_route_commercial_context_price_revision",
        ),
        CheckConstraint(
            "assignment_revision > 0",
            name="chk_route_commercial_context_assignment_revision",
        ),
        CheckConstraint(
            "offer_ruleset_version >= 0",
            name="chk_route_commercial_context_offer_revision",
        ),
        CheckConstraint(
            "tax_ruleset_version > 0",
            name="chk_route_commercial_context_tax_revision",
        ),
        CheckConstraint(
            "rounding_policy_version > 0",
            name="chk_route_commercial_context_rounding_version",
        ),
        CheckConstraint(
            "tenant_policy_revision > 0",
            name="chk_route_commercial_context_tenant_policy_revision",
        ),
        CheckConstraint(
            "length(trim(transaction_currency_code)) > 0",
            name="chk_route_commercial_context_transaction_currency",
        ),
        CheckConstraint(
            "length(trim(functional_currency_code)) > 0",
            name="chk_route_commercial_context_functional_currency",
        ),
        Index(
            "ix_route_commercial_context_lock",
            "company_id", "pricing_locked_at", "price_publication_revision",
            "assignment_revision",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    dispatch_route_id = Column(Integer, nullable=False, index=True)
    pricing_locked_at = Column(DateTime(timezone=True), nullable=False)
    price_publication_revision = Column(Integer, nullable=False)
    assignment_revision = Column(Integer, nullable=False)
    offer_ruleset_version = Column(Integer, nullable=False)
    tax_ruleset_version = Column(Integer, nullable=False)
    transaction_currency_code = Column(String(10), nullable=False)
    functional_currency_code = Column(String(10), nullable=False)
    rounding_policy_version = Column(Integer, nullable=False)
    tenant_policy_revision = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("CURRENT_TIMESTAMP"),
    )



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
    target_quantity_packs = Column(Numeric(20, 6), nullable=False, default=Decimal('0'), server_default='0')
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
        ForeignKeyConstraint(
            ['company_id', 'commercial_context_id'],
            ['route_commercial_contexts.company_id', 'route_commercial_contexts.id'],
            ondelete='RESTRICT',
            name='fk_visit_tenant_commercial_context'
        ),
        ForeignKeyConstraint(
            ['company_id', 'id', 'current_sales_revision_id'],
            [
                'sales_visit_revisions.company_id',
                'sales_visit_revisions.visit_id',
                'sales_visit_revisions.id',
            ],
            ondelete='RESTRICT',
            name='fk_visit_tenant_current_sales_revision'
        ),
        CheckConstraint(
            """
            (
                current_sales_revision_id IS NULL
                AND financial_evidence_version IS NULL
            )
            OR
            (
                current_sales_revision_id IS NOT NULL
                AND financial_evidence_version = 4
            )
            """,
            name='visit_current_sales_revision_shape'
        ),
        CheckConstraint(
            """
            (
                financial_evidence_version IS NULL
                AND financial_evidence_frozen_at IS NULL
                AND commercial_calculated_at IS NULL
                AND commercial_context_id IS NULL
                AND transaction_currency_code IS NULL
                AND functional_currency_code IS NULL
                AND rounding_policy_version IS NULL
                AND rounding_precision IS NULL
                AND rounding_mode IS NULL
                AND price_publication_revision_ceiling IS NULL
                AND assignment_revision_ceiling IS NULL
                AND offer_revision_ceiling IS NULL
                AND tax_revision_ceiling IS NULL
                AND post_offer_amount IS NULL
                AND taxable_amount IS NULL
                AND line_total_amount IS NULL
                AND rounding_adjustment IS NULL
                AND offer_snapshot IS NULL
            )
            OR
            (
                financial_evidence_version = 4
                AND financial_evidence_frozen_at IS NOT NULL
                AND commercial_calculated_at IS NOT NULL
                AND transaction_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
                AND functional_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
                AND rounding_policy_version > 0
                AND rounding_precision BETWEEN 0 AND 6
                AND rounding_mode IN ('HALF_UP','HALF_EVEN')
                AND price_publication_revision_ceiling > 0
                AND assignment_revision_ceiling > 0
                AND offer_revision_ceiling >= 0
                AND tax_revision_ceiling > 0
                AND amount_before_tax_and_discount >= 0
                AND discount_applied >= 0
                AND post_offer_amount >= 0
                AND taxable_amount >= 0
                AND tax_amount >= 0
                AND line_total_amount >= 0
                AND final_amount_due >= 0
                AND post_offer_amount = amount_before_tax_and_discount - discount_applied
                AND line_total_amount = taxable_amount + tax_amount
                AND final_amount_due = line_total_amount + rounding_adjustment
                AND offer_snapshot IS NOT NULL
                AND jsonb_typeof(offer_snapshot) = 'object'
            )
            """,
            name='visit_financial_evidence_shape'
        ),
        Index('ix_visit_shop_timestamp', 'shop_id', 'visit_timestamp'),
        Index('ix_visit_session_outcome', 'work_session_id', 'outcome'),
        Index(
            'uq_visit_one_pending_owner_day',
            'company_id', 'driver_id', 'shop_id', 'operational_date',
            unique=True,
            postgresql_where=text("status = 'Pending' AND driver_id IS NOT NULL"),
        ),
    )
    id              = Column(Integer, primary_key=True)
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    driver_id       = Column(Integer, nullable=True,  index=True)
    shop_id         = Column(Integer, nullable=False, index=True)
    work_session_id = Column(Integer, nullable=True, index=True)
    # يوم العمل حسب Timezone الشركة؛ منفصل عمداً عن timestamp الرقابي UTC.
    operational_date = Column(Date, nullable=False, index=True)
    visit_timestamp = Column(DateTime, nullable=False, default=utc_now, index=True)

    outcome = Column(String(50), nullable=True, default='Pending', index=True)

    # +++ الدرع المحاسبي (Issue 2): تحويل جميع القيم المالية إلى Decimal لحماية دقة القروش وفرض server_default +++
    amount_before_tax_and_discount = Column(Numeric(20, 6), nullable=True, default=Decimal('0.000000'), server_default='0.000000')
    discount_applied               = Column(Numeric(20, 6), nullable=True, default=Decimal('0.000000'), server_default='0.000000')
    tax_percentage_applied         = Column(Numeric(12, 3), nullable=True, default=Decimal('0.000'), server_default='0.000')
    tax_amount                     = Column(Numeric(20, 6), nullable=True, default=Decimal('0.000000'), server_default='0.000000')
    final_amount_due               = Column(Numeric(20, 6), nullable=True, default=Decimal('0.000000'), server_default='0.000000')

    # Stage 6F — immutable financial evidence. Nullable until the Stage 6H cutover
    # freezes a completed sale; the DB shape constraint forbids partial evidence.
    financial_evidence_version = Column(Integer, nullable=True)
    financial_evidence_frozen_at = Column(DateTime(timezone=True), nullable=True)
    commercial_calculated_at = Column(DateTime(timezone=True), nullable=True)
    commercial_context_id = Column(Integer, nullable=True, index=True)
    current_sales_revision_id = Column(Integer, nullable=True, index=True)
    transaction_currency_code = Column(String(10), nullable=True)
    functional_currency_code = Column(String(10), nullable=True)
    rounding_policy_version = Column(Integer, nullable=True)
    rounding_precision = Column(Integer, nullable=True)
    rounding_mode = Column(String(20), nullable=True)
    price_publication_revision_ceiling = Column(Integer, nullable=True)
    assignment_revision_ceiling = Column(Integer, nullable=True)
    offer_revision_ceiling = Column(Integer, nullable=True)
    tax_revision_ceiling = Column(Integer, nullable=True)
    post_offer_amount = Column(Numeric(20, 6), nullable=True)
    taxable_amount = Column(Numeric(20, 6), nullable=True)
    line_total_amount = Column(Numeric(20, 6), nullable=True)
    rounding_adjustment = Column(Numeric(20, 6), nullable=True)
    offer_snapshot = Column(JSONB, nullable=True)
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
        UniqueConstraint('company_id', 'id', name='uq_visit_items_company_id'),
        ForeignKeyConstraint(['company_id', 'visit_id'], ['visits.company_id', 'visits.id'],
                             name='fk_visit_item_tenant_visit'),
        ForeignKeyConstraint(['company_id', 'product_variant_id'], ['product_variants.company_id', 'product_variants.id'],
                             ondelete='RESTRICT', name='fk_visit_item_tenant_variant'),
        ForeignKeyConstraint(
            ['company_id', 'commercial_context_id'],
            ['route_commercial_contexts.company_id', 'route_commercial_contexts.id'],
            ondelete='RESTRICT',
            name='fk_visit_item_tenant_commercial_context'
        ),
        ForeignKeyConstraint(
            ['company_id', 'visit_id', 'sales_revision_id'],
            [
                'sales_visit_revisions.company_id',
                'sales_visit_revisions.visit_id',
                'sales_visit_revisions.id',
            ],
            ondelete='RESTRICT',
            name='fk_visit_item_tenant_sales_revision'
        ),
        ForeignKeyConstraint(
            ['company_id', 'selected_price_entry_id'],
            ['price_book_entries.company_id', 'price_book_entries.id'],
            ondelete='RESTRICT',
            name='fk_visit_item_tenant_price_entry'
        ),
        ForeignKeyConstraint(
            ['base_uom_id'],
            ['uom.id'],
            ondelete='RESTRICT',
            name='fk_visit_item_base_uom'
        ),
        CheckConstraint(
            'price_per_unit_at_sale >= 0 AND total_price >= 0',
            name='visit_item_sale_money_nonnegative'
        ),
        CheckConstraint(
            """
            (
                financial_evidence_version IS NULL
                AND financial_evidence_frozen_at IS NULL
                AND commercial_context_id IS NULL
                AND sales_revision_id IS NULL
                AND base_uom_id IS NULL
                AND canonical_quantity IS NULL
                AND selected_price_entry_id IS NULL
                AND price_publication_revision IS NULL
                AND assignment_revision IS NULL
                AND gross_amount IS NULL
                AND discount_amount IS NULL
                AND post_offer_amount IS NULL
                AND taxable_amount IS NULL
                AND tax_amount IS NULL
                AND net_amount IS NULL
                AND transaction_currency_code IS NULL
                AND functional_currency_code IS NULL
                AND offer_snapshot IS NULL
                AND tax_snapshot IS NULL
            )
            OR
            (
                financial_evidence_version = 4
                AND financial_evidence_frozen_at IS NOT NULL
                AND sales_revision_id IS NOT NULL
                AND base_uom_id IS NOT NULL
                AND canonical_quantity > 0
                AND selected_price_entry_id IS NULL
                AND price_publication_revision IS NULL
                AND assignment_revision IS NULL
                AND gross_amount >= 0
                AND discount_amount >= 0
                AND post_offer_amount >= 0
                AND taxable_amount >= 0
                AND tax_amount >= 0
                AND net_amount >= 0
                AND discount_amount <= gross_amount
                AND post_offer_amount = gross_amount - discount_amount
                AND net_amount = taxable_amount + tax_amount
                AND total_price = net_amount
                AND transaction_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
                AND functional_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
                AND offer_snapshot IS NOT NULL
                AND jsonb_typeof(offer_snapshot) = 'object'
                AND tax_snapshot IS NOT NULL
                AND jsonb_typeof(tax_snapshot) = 'object'
            )
            """,
            name='visit_item_financial_evidence_shape'
        ),
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
    price_per_unit_at_sale = Column(Numeric(20, 6), nullable=False) # +++ إلزامي لحماية الفواتير +++
    total_price            = Column(Numeric(20, 6), nullable=False, default=Decimal('0.000000'), server_default='0.000000')

    financial_evidence_version = Column(Integer, nullable=True)
    financial_evidence_frozen_at = Column(DateTime(timezone=True), nullable=True)
    commercial_context_id = Column(Integer, nullable=True, index=True)
    sales_revision_id = Column(Integer, nullable=True, index=True)
    base_uom_id = Column(Integer, nullable=True)
    canonical_quantity = Column(Numeric(20, 6), nullable=True)
    selected_price_entry_id = Column(Integer, nullable=True, index=True)
    price_publication_revision = Column(Integer, nullable=True)
    assignment_revision = Column(Integer, nullable=True)
    gross_amount = Column(Numeric(20, 6), nullable=True)
    discount_amount = Column(Numeric(20, 6), nullable=True)
    post_offer_amount = Column(Numeric(20, 6), nullable=True)
    taxable_amount = Column(Numeric(20, 6), nullable=True)
    tax_amount = Column(Numeric(20, 6), nullable=True)
    net_amount = Column(Numeric(20, 6), nullable=True)
    transaction_currency_code = Column(String(10), nullable=True)
    functional_currency_code = Column(String(10), nullable=True)
    offer_snapshot = Column(JSONB, nullable=True)
    tax_snapshot = Column(JSONB, nullable=True)

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
        ForeignKeyConstraint(
            ['company_id', 'product_variant_id', 'batch_id'],
            ['product_batches.company_id', 'product_batches.product_variant_id', 'product_batches.id'],
            ondelete='RESTRICT',
            name='fk_visit_return_tenant_batch'
        ),
        Index('ix_visit_return_composite', 'visit_id', 'product_variant_id'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    visit_id           = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    batch_id           = Column(Integer, nullable=False, index=True)

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
        ForeignKeyConstraint(['company_id', 'fulfilled_by_visit_id'], ['visits.company_id', 'visits.id'],
                             ondelete='RESTRICT', name='fk_shortage_tenant_fulfilled_visit'),
        CheckConstraint(
            "((fulfilled_by_visit_id IS NULL AND fulfilled_at IS NULL) OR "
            "(fulfilled_by_visit_id IS NOT NULL AND fulfilled_at IS NOT NULL))",
            name='chk_shortage_fulfillment_pair'
        ),
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
    fulfilled_by_visit_id = Column(Integer, nullable=True, index=True)
    fulfilled_at          = Column(DateTime, nullable=True, index=True)
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


class DomainAuditEvent(Base):
    """Immutable, structured evidence for approved domain commands."""
    __tablename__ = 'domain_audit_events'
    __table_args__ = (
        UniqueConstraint('external_id', name='uq_domain_audit_external_id'),
        UniqueConstraint('company_id', 'id', name='uq_domain_audit_company_id'),
        ForeignKeyConstraint(
            ['company_id', 'actor_user_id'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_domain_audit_tenant_actor'
        ),
        CheckConstraint('schema_version > 0', name='chk_domain_audit_schema_version'),
        Index('ix_domain_audit_entity_time', 'company_id', 'entity_type', 'entity_id', 'occurred_at'),
        Index('ix_domain_audit_event_time', 'company_id', 'event_type', 'occurred_at'),
    )
    id              = Column(BigInteger, primary_key=True)
    external_id     = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    event_type      = Column(String(100), nullable=False, index=True)
    entity_type     = Column(String(100), nullable=False)
    entity_id       = Column(String(100), nullable=False)
    actor_user_id   = Column(Integer, nullable=True, index=True)
    actor_context   = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    reason_code     = Column(String(100), nullable=True)
    reason_text     = Column(Text, nullable=True)
    request_id      = Column(Uuid(as_uuid=True), nullable=False, index=True)
    before_snapshot = Column(JSONB, nullable=True)
    after_snapshot  = Column(JSONB, nullable=True)
    schema_version  = Column(Integer, nullable=False, default=1, server_default='1')
    occurred_at     = Column(DateTime, nullable=False, default=utc_now, index=True)


class TransactionalOutbox(Base):
    """Tenant-scoped outbox written atomically with the aggregate mutation."""
    __tablename__ = 'transactional_outbox'
    __table_args__ = (
        UniqueConstraint('company_id', 'id', name='uq_transactional_outbox_company_id'),
        UniqueConstraint('company_id', 'idempotency_key', name='uq_transactional_outbox_idempotency'),
        CheckConstraint("status IN ('PENDING', 'PROCESSING', 'PUBLISHED', 'FAILED')", name='chk_transactional_outbox_status'),
        CheckConstraint('attempts >= 0', name='chk_transactional_outbox_attempts'),
        CheckConstraint('schema_version > 0', name='chk_transactional_outbox_schema_version'),
        Index(
            'ix_transactional_outbox_pending',
            'status', 'available_at', 'id',
            postgresql_where=text("status IN ('PENDING', 'FAILED')")
        ),
        Index('ix_transactional_outbox_aggregate', 'company_id', 'aggregate_type', 'aggregate_id', 'id'),
    )
    id              = Column(BigInteger, primary_key=True)
    company_id      = Column(Integer, ForeignKey('companies.id', ondelete='RESTRICT'), nullable=False, index=True)
    event_type      = Column(String(100), nullable=False, index=True)
    aggregate_type  = Column(String(100), nullable=False)
    aggregate_id    = Column(String(100), nullable=False)
    payload         = Column(JSONB, nullable=False)
    schema_version  = Column(Integer, nullable=False, default=1, server_default='1')
    idempotency_key = Column(String(255), nullable=False)
    status          = Column(String(20), nullable=False, default='PENDING', server_default='PENDING', index=True)
    attempts        = Column(Integer, nullable=False, default=0, server_default='0')
    available_at    = Column(DateTime, nullable=False, default=utc_now, index=True)
    processed_at    = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, nullable=False, default=utc_now)

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
class OperationIdempotency(Base):
    # سجل عام للـ idempotency على مستوى العملية التجارية داخل Tenant واحد.
    __tablename__ = 'operation_idempotency'
    __table_args__ = (
        UniqueConstraint(
            'company_id', 'operation', 'request_id',
            name='uq_operation_idempotency_request'
        ),
        UniqueConstraint(
            'company_id', 'id',
            name='uq_operation_idempotency_company_id'
        ),
        ForeignKeyConstraint(
            ['company_id', 'created_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_operation_idempotency_tenant_actor'
        ),
        CheckConstraint(
            "length(trim(operation)) > 0",
            name='chk_operation_idempotency_operation_not_blank'
        ),
        CheckConstraint(
            "request_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name='chk_operation_idempotency_request_id_format'
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name='chk_operation_idempotency_hash_format'
        ),
        CheckConstraint(
            "((response_json IS NULL AND completed_at IS NULL) OR "
            "(response_json IS NOT NULL AND completed_at IS NOT NULL))",
            name='chk_operation_idempotency_completion_pair'
        ),
    )

    id            = Column(Integer, primary_key=True)
    company_id    = Column(
        Integer,
        ForeignKey('companies.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    operation     = Column(String(80), nullable=False)
    request_id    = Column(String(36), nullable=False)
    request_hash  = Column(String(64), nullable=False)
    created_by    = Column(Integer, nullable=False, index=True)
    response_json = Column(JSON, nullable=True)
    created_at    = Column(DateTime, nullable=False, default=utc_now, index=True)
    completed_at  = Column(DateTime, nullable=True)


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
        CheckConstraint(
            'expiry_date IS NULL OR production_date IS NULL OR production_date <= expiry_date',
            name='chk_product_batch_date_order'
        ),
        CheckConstraint(
            "disposition IN ('RELEASED', 'QUARANTINED', 'BLOCKED', 'RECALLED')",
            name='chk_product_batch_disposition'
        ),
        CheckConstraint(
            'disposition_revision > 0',
            name='chk_product_batch_disposition_revision'
        ),
        CheckConstraint(
            "disposition_reason IS NULL OR length(trim(disposition_reason)) > 0",
            name='chk_product_batch_disposition_reason'
        ),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    batch_number       = Column(String(100), nullable=False, index=True)
    production_date       = Column(Date, nullable=True)
    expiry_date           = Column(Date, nullable=True, index=True)
    disposition           = Column(
        String(50),
        nullable=False,
        default='RELEASED',
        server_default='RELEASED',
        index=True,
    )
    disposition_reason    = Column(Text, nullable=True)
    disposition_revision  = Column(
        Integer,
        nullable=False,
        default=1,
        server_default='1',
    )
    is_active             = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default='true',
        index=True,
    )
    created_at            = Column(DateTime, nullable=False, default=utc_now)
    updated_at            = Column(
        DateTime,
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

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
        CheckConstraint("length(trim(name)) > 0", name='chk_inv_loc_name_not_blank'),
        CheckConstraint("length(trim(code)) > 0", name='chk_inv_loc_code_not_blank'),
        CheckConstraint("vehicle_id IS NULL OR location_type = 'VEHICLE'", name='chk_inv_loc_vehicle_type'),
        CheckConstraint("location_type <> 'VEHICLE' OR vehicle_id IS NOT NULL", name='chk_inv_loc_vehicle_required'),
        CheckConstraint("version > 0", name='chk_inv_loc_version_positive'),
        CheckConstraint(
            "(system_role IS NULL AND is_system_managed IS FALSE) OR "
            "(system_role = 'TRANSIT' AND is_system_managed IS TRUE "
            "AND location_type = 'IN_TRANSIT' AND branch_id IS NULL "
            "AND vehicle_id IS NULL AND is_active IS TRUE)",
            name='chk_inv_loc_system_identity'
        ),
        Index(
            'ix_inventory_location_company_type_active_id',
            'company_id', 'location_type', 'is_active', 'id'
        ),
        Index('uq_active_inventory_location_vehicle', 'company_id', 'vehicle_id', unique=True,
              postgresql_where=text("vehicle_id IS NOT NULL AND is_active IS TRUE")),
        Index('uq_inventory_location_system_role', 'company_id', 'system_role', unique=True,
              postgresql_where=text("system_role IS NOT NULL")),
    )
    id            = Column(Integer, primary_key=True)
    company_id    = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    branch_id     = Column(Integer, nullable=True, index=True)
    name          = Column(String(150), nullable=False)
    code          = Column(String(50), nullable=False)
    location_type = Column(String(50), nullable=False, index=True)
    vehicle_id    = Column(Integer, nullable=True, index=True)
    system_role   = Column(String(30), nullable=True, index=True)
    is_system_managed = Column(Boolean, nullable=False, default=False, server_default='false')
    version       = Column(Integer, nullable=False, default=1, server_default='1')
    is_active     = Column(Boolean, nullable=False, default=True, server_default='true')
    created_at    = Column(DateTime, nullable=False, default=utc_now)
    updated_at    = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)



class TenantOperationalPolicy(Base):
    """Versioned, validated tenant policy. JSONB is data only; no executable expressions."""

    __tablename__ = 'tenant_operational_policies'
    __table_args__ = (
        UniqueConstraint(
            'company_id', 'id',
            name='uq_tenant_operational_policies_company_id'
        ),
        UniqueConstraint(
            'company_id', 'policy_code', 'revision',
            name='uq_tenant_operational_policy_revision'
        ),
        UniqueConstraint(
            'company_id', 'id', 'revision',
            name='uq_tenant_operational_policy_identity_revision'
        ),
        ForeignKeyConstraint(
            ['company_id', 'created_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_tenant_operational_policy_creator'
        ),
        ForeignKeyConstraint(
            ['company_id', 'approved_by'],
            ['drivers.company_id', 'drivers.id'],
            ondelete='RESTRICT',
            name='fk_tenant_operational_policy_approver'
        ),
        CheckConstraint(
            "length(trim(policy_code)) > 0",
            name='chk_tenant_operational_policy_code_not_blank'
        ),
        CheckConstraint(
            'schema_version > 0',
            name='chk_tenant_operational_policy_schema_version'
        ),
        CheckConstraint(
            'revision > 0',
            name='chk_tenant_operational_policy_revision'
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')",
            name='chk_tenant_operational_policy_status'
        ),
        CheckConstraint(
            "jsonb_typeof(validated_payload) = 'object'",
            name='chk_tenant_operational_policy_payload_object'
        ),
        CheckConstraint(
            "((status = 'DRAFT' AND effective_from IS NULL AND effective_to IS NULL "
            "AND approved_by IS NULL AND approved_at IS NULL) OR "
            "(status = 'PUBLISHED' AND effective_from IS NOT NULL AND effective_to IS NULL "
            "AND approved_by IS NOT NULL AND approved_at IS NOT NULL) OR "
            "(status = 'SUPERSEDED' AND effective_from IS NOT NULL AND effective_to IS NOT NULL "
            "AND approved_by IS NOT NULL AND approved_at IS NOT NULL "
            "AND effective_to >= effective_from))",
            name='chk_tenant_operational_policy_state_metadata'
        ),
        Index(
            'ix_tenant_operational_policy_lookup',
            'company_id', 'policy_code', 'status', 'revision'
        ),
        Index(
            'uq_tenant_operational_policy_one_draft',
            'company_id', 'policy_code',
            unique=True,
            postgresql_where=text("status = 'DRAFT'")
        ),
        Index(
            'uq_tenant_operational_policy_one_published',
            'company_id', 'policy_code',
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'")
        ),
    )

    id                = Column(Integer, primary_key=True)
    company_id        = Column(
        Integer,
        ForeignKey('companies.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    policy_code       = Column(String(80), nullable=False)
    schema_version    = Column(Integer, nullable=False, default=1)
    revision          = Column(Integer, nullable=False)
    validated_payload = Column(JSONB, nullable=False)
    status            = Column(String(20), nullable=False, default='DRAFT')
    effective_from    = Column(DateTime, nullable=True)
    effective_to      = Column(DateTime, nullable=True)
    approved_by       = Column(Integer, nullable=True, index=True)
    approved_at       = Column(DateTime, nullable=True)
    created_by        = Column(Integer, nullable=False, index=True)
    created_at        = Column(DateTime, nullable=False, default=utc_now)
    updated_at        = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)



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
        CheckConstraint(
            'minimum_remaining_shelf_life_days >= 0',
            name='chk_inventory_stock_policy_min_shelf_life'
        ),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    location_id        = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    minimum_quantity   = Column(Numeric(20, 6), nullable=False, default=Decimal('0'), server_default='0')
    target_quantity    = Column(Numeric(20, 6), nullable=True)
    minimum_remaining_shelf_life_days = Column(
        Integer,
        nullable=False,
        default=0,
        server_default='0',
    )
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
        CheckConstraint("stock_status IN ('AVAILABLE', 'QUARANTINED', 'BLOCKED', 'RECALLED', 'DAMAGED', 'DISPOSAL_PENDING')", name='chk_inv_bal_status'),
        CheckConstraint('on_hand_quantity >= 0', name='chk_inv_bal_onhand_qty'),
        CheckConstraint('reserved_quantity >= 0', name='chk_inv_bal_res_qty'),
        CheckConstraint('reserved_quantity <= on_hand_quantity', name='chk_inv_bal_reserved_within_onhand'),
        CheckConstraint("stock_status = 'AVAILABLE' OR reserved_quantity = 0", name='chk_inv_bal_nonavailable_not_reserved'),
        Index('ix_inv_balance_search', 'company_id', 'location_id', 'product_variant_id', 'stock_status'),
        Index('ix_inv_balance_fefo', 'company_id', 'location_id', 'product_variant_id', 'stock_status', 'batch_id'),
    )
    id                 = Column(Integer, primary_key=True)
    company_id         = Column(Integer, ForeignKey('companies.id', ondelete='CASCADE'), nullable=False, index=True)
    location_id        = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    batch_id           = Column(Integer, nullable=False, index=True)
    stock_status       = Column(String(50), nullable=False, default='AVAILABLE', server_default='AVAILABLE')
    on_hand_quantity   = Column(Numeric(20, 6), nullable=False, default=Decimal('0'), server_default='0')
    reserved_quantity  = Column(Numeric(20, 6), nullable=False, default=Decimal('0'), server_default='0')
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
        CheckConstraint("source_stock_status IS NULL OR source_stock_status IN ('AVAILABLE', 'QUARANTINED', 'BLOCKED', 'RECALLED', 'DAMAGED', 'DISPOSAL_PENDING')", name='chk_inv_movement_source_status'),
        CheckConstraint("destination_stock_status IS NULL OR destination_stock_status IN ('AVAILABLE', 'QUARANTINED', 'BLOCKED', 'RECALLED', 'DAMAGED', 'DISPOSAL_PENDING')", name='chk_inv_movement_destination_status'),
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
        CheckConstraint(
            'financial_unit_price_snapshot IS NULL OR financial_unit_price_snapshot >= 0',
            name='chk_inv_movement_financial_unit_price_nonnegative'
        ),
        CheckConstraint(
            "((reference_type = 'DRIVER_SHORTAGE' AND financial_unit_price_snapshot IS NOT NULL) OR "
            "(reference_type <> 'DRIVER_SHORTAGE' AND financial_unit_price_snapshot IS NULL))",
            name='chk_inv_movement_shortage_price_snapshot_scope'
        ),
        CheckConstraint("length(trim(reference_type)) > 0", name='chk_inv_movement_reference_type'),
        CheckConstraint("length(trim(reference_id)) > 0", name='chk_inv_movement_reference_id'),
        CheckConstraint("length(trim(idempotency_key)) > 0", name='chk_inv_movement_idempotency_key'),
        Index('ix_inv_movement_locations', 'company_id', 'source_location_id', 'destination_location_id'),
        Index('ix_inv_movement_item_created', 'company_id', 'product_variant_id', 'batch_id', 'created_at'),
        Index('ix_inv_movement_stocktake_attempt', 'company_id', 'stocktake_count_attempt_id'),
        # Keyset pagination / exact-reference paths for the append-only ledger.
        Index('ix_inv_movement_company_created_id', 'company_id', 'created_at', 'id'),
        Index('ix_inv_movement_company_source_created_id', 'company_id', 'source_location_id', 'created_at', 'id'),
        Index('ix_inv_movement_company_destination_created_id', 'company_id', 'destination_location_id', 'created_at', 'id'),
        Index('ix_inv_movement_company_reference', 'company_id', 'reference_id'),
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
    quantity                  = Column(Numeric(20, 6), nullable=False)
    # Immutable financial valuation only for DRIVER_SHORTAGE; other movements must keep it NULL.
    financial_unit_price_snapshot = Column(Numeric(12, 3), nullable=True)

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

    on_hand_before  = Column(Numeric(20, 6), nullable=False)
    on_hand_after   = Column(Numeric(20, 6), nullable=False)
    reserved_before = Column(Numeric(20, 6), nullable=False)
    reserved_after  = Column(Numeric(20, 6), nullable=False)

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
            ['company_id', 'tenant_policy_id', 'tenant_policy_revision'],
            ['tenant_operational_policies.company_id', 'tenant_operational_policies.id', 'tenant_operational_policies.revision'],
            ondelete='RESTRICT',
            name='fk_transfer_header_tenant_policy_snapshot'
        ),
        ForeignKeyConstraint(
            ['company_id', 'work_session_id', 'expected_receiver_id'],
            ['work_sessions.company_id', 'work_sessions.id', 'work_sessions.driver_id'],
            ondelete='RESTRICT',
            name='fk_transfer_header_handshake_session_receiver'
        ),
        CheckConstraint("workflow_type IN ('DIRECT', 'HANDSHAKE', 'TRANSIT')", name='chk_transfer_header_workflow'),
        CheckConstraint("status IN ('DRAFT', 'PENDING', 'IN_TRANSIT', 'ACCEPTED', 'REJECTED', 'POSTED', 'CANCELLED')", name='chk_transfer_header_status'),
        CheckConstraint(
            "transfer_purpose IN ('REPLENISHMENT', 'ROUTE_LOAD', 'ROUTE_RETURN', 'WAREHOUSE_BALANCING', "
            "'RETURN_TO_VENDOR', 'QUARANTINE', 'RECALL_RETURN', 'DISPOSAL')",
            name='chk_transfer_header_purpose'
        ),
        CheckConstraint(
            "((tenant_policy_id IS NULL AND tenant_policy_revision IS NULL) OR "
            "(tenant_policy_id IS NOT NULL AND tenant_policy_revision IS NOT NULL))",
            name='chk_transfer_header_policy_snapshot_pair'
        ),
        CheckConstraint(
            "transfer_purpose NOT IN ('RETURN_TO_VENDOR','QUARANTINE','RECALL_RETURN','DISPOSAL') "
            "OR (tenant_policy_id IS NOT NULL AND tenant_policy_revision IS NOT NULL)",
            name='chk_transfer_header_special_policy_required'
        ),
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
            "workflow_type <> 'TRANSIT' OR status = 'DRAFT' OR transit_location_id IS NOT NULL",
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
            "workflow_type = 'HANDSHAKE' OR work_session_id IS NULL",
            name='chk_transfer_header_session_scope'
        ),
        CheckConstraint(
            "status IN ('ACCEPTED', 'REJECTED', 'POSTED') OR received_by IS NULL",
            name='chk_transfer_header_received_by_scope'
        ),
        CheckConstraint(
            "workflow_type <> 'TRANSIT' OR status NOT IN ('POSTED', 'REJECTED') "
            "OR received_by <> dispatched_by",
            name='chk_transfer_header_separation_of_duties'
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
        Index(
            'ix_transfer_header_transit_queue',
            'company_id', 'status', 'created_at', 'id',
            postgresql_where=text("workflow_type = 'TRANSIT'")
        ),
        Index(
            'ix_transfer_header_policy_snapshot',
            'company_id', 'tenant_policy_id', 'tenant_policy_revision'
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
    # STAGE4E_CORE_PURPOSE_INFLIGHT: purpose is mandatory at every constructor; no silent fallback.
    transfer_purpose        = Column(String(50), nullable=False, index=True)
    commercial_context      = Column(JSONB, nullable=False)
    tenant_policy_id        = Column(Integer, nullable=True, index=True)
    tenant_policy_revision  = Column(Integer, nullable=True)

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
        CheckConstraint(
            "source_stock_status IN ('AVAILABLE', 'QUARANTINED', 'BLOCKED', 'RECALLED', 'DAMAGED', 'DISPOSAL_PENDING')",
            name='chk_transfer_line_source_status'
        ),
        CheckConstraint(
            'lifecycle_revision_snapshot > 0',
            name='chk_transfer_line_lifecycle_revision_snapshot'
        ),
        CheckConstraint(
            "lifecycle_status_snapshot IN ('DRAFT', 'ACTIVE', 'RETIRING', 'ARCHIVED')",
            name='chk_transfer_line_lifecycle_status_snapshot'
        ),
        CheckConstraint(
            "operational_hold_snapshot IN ('NONE', 'SALES_HOLD', 'RECALL')",
            name='chk_transfer_line_operational_hold_snapshot'
        ),
    )
    id                      = Column(Integer, primary_key=True)
    company_id              = Column(Integer, nullable=False, index=True)
    transfer_header_id      = Column(Integer, nullable=False, index=True)
    product_variant_id      = Column(Integer, nullable=False, index=True)
    batch_id                = Column(Integer, nullable=False, index=True)
    quantity                = Column(Numeric(20, 6), nullable=False)
    source_stock_status     = Column(String(50), nullable=False)
    lifecycle_revision_snapshot = Column(Integer, nullable=False)
    lifecycle_status_snapshot   = Column(String(20), nullable=False)
    operational_hold_snapshot   = Column(String(20), nullable=False)
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
        CheckConstraint(
            "((stocktake_type = 'VEHICLE_RECON' AND related_work_session_id IS NOT NULL) OR "
            "(stocktake_type <> 'VEHICLE_RECON' AND related_work_session_id IS NULL))",
            name='chk_stocktake_work_session_scope'
        ),
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
        Index(
            'uq_vehicle_recon_work_session',
            'company_id',
            'related_work_session_id',
            unique=True,
            postgresql_where=text(
                "stocktake_type = 'VEHICLE_RECON' "
                "AND related_work_session_id IS NOT NULL "
                "AND status <> 'CANCELLED'"
            ),
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
        CheckConstraint("stock_status IN ('AVAILABLE', 'QUARANTINED', 'BLOCKED', 'RECALLED', 'DAMAGED', 'DISPOSAL_PENDING')", name='chk_stocktake_line_status'),
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

    expected_quantity = Column(Numeric(20, 6), nullable=False)
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

    expected_quantity = Column(Numeric(20, 6), nullable=False)
    actual_quantity   = Column(Numeric(20, 6), nullable=False)
    variance_quantity = Column(Numeric(20, 6), nullable=False)
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
