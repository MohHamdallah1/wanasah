import asyncio
import sys
import os
import re
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()

# +++ اتصال السوبريوزر: للبناء والزراعة فقط (يتجاوز RLS) +++
DB_URL = os.getenv("DATABASE_URL_MIGRATION")
if not DB_URL:
    raise ValueError("CRITICAL: DATABASE_URL_MIGRATION is missing from .env")
if DB_URL.startswith("postgres://"): DB_URL = DB_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DB_URL.startswith("postgresql://") and "asyncpg" not in DB_URL: DB_URL = DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# +++ اتصال مستخدم التطبيق: لاستخراج اسم المستخدم ومنحه الصلاحيات على الجداول الجديدة +++
APP_DB_URL = os.getenv("DATABASE_URL")
if not APP_DB_URL:
    raise ValueError("CRITICAL: DATABASE_URL is missing from .env")

engine = create_async_engine(DB_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

from models import *

# ====================================================================
# 1. إعادة بناء قاعدة البيانات من الصفر (بدون Alembic - بيئة التطوير)
#    create_all من الـ Models + فرض RLS ديناميكياً على كل جدول يحمل company_id
# ====================================================================
async def rebuild_schema():
    print("WARNING: Wiping the public schema and rebuilding from Models...")

    async with engine.begin() as conn:
        # 1. طرد الاتصالات الأخرى حتى لا يمنعنا DROP SCHEMA
        await conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        ))

        # 2. المسح الشامل وإعادة بناء المخطط من الـ Models (المصدر الوحيد للحقيقة)
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
        print(f"[1/3] Created {len(Base.metadata.tables)} tables from Models.")

        # 3. فرض درع RLS ديناميكياً على كل جدول يملك company_id (المستأجَر)
        #    أي جدول جديد سيُضاف مستقبلاً ويحمل company_id سيُحمى تلقائياً هنا
        tenant_tables = [name for name, t in Base.metadata.tables.items() if "company_id" in t.columns]
        for t_name in tenant_tables:
            await conn.execute(text(f"ALTER TABLE {t_name} ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {t_name} FORCE ROW LEVEL SECURITY"))
            await conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {t_name}"))
            await conn.execute(text(f"""
                CREATE POLICY tenant_isolation_policy ON {t_name}
                FOR ALL
                USING (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
                WITH CHECK (company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer)
            """))
        print(f"[2/3] RLS (ENABLE + FORCE + Policy) applied to {len(tenant_tables)} tenant tables.")



        # 5. منح مستخدم التطبيق صلاحيات كاملة (الجداول أنشئت بواسطة السوبريوزر)
        m = re.match(r"postgresql(?:\+asyncpg)?://([^:@]+):", APP_DB_URL)
        if not m:
            raise ValueError("CRITICAL: cannot resolve app username from DATABASE_URL")
        app_user = m.group(1)
        await conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{app_user}"'))
        await conn.execute(text(f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "{app_user}"'))
        await conn.execute(text(f'GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "{app_user}"'))
        await conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{app_user}"'))
        await conn.execute(text(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{app_user}"'))
        print(f"[3/3] Grants applied to app user '{app_user}'.")

# ====================================================================
# 2. زراعة شركات متعددة (كل شركة: مستودعان + سيارة/مندوب/منتج/دفعة/رصيد)
# ====================================================================
async def mass_seed(num_companies: int = 2, inject_heavy: bool = False):
    import bcrypt
    hashed_pw = bcrypt.hashpw("password".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    async with AsyncSessionLocal() as session:
        try:
            country = Country(name="المملكة الأردنية الهاشمية")
            session.add(country)
            await session.flush()
            gov = Governorate(name="عمان", country_id=country.id)
            session.add(gov)
            uom_carton = UOM(name="كرتونة", code="CARTON")
            session.add(uom_carton)
            await session.flush()

            for i in range(1, num_companies + 1):
                c_name = "شركة وناسة" if i == 1 else f"شركة النسر {i}"
                c_code = "WNS-01" if i == 1 else f"EAGLE-{i:02d}"

                comp = Company(name=c_name, company_code=c_code, is_active=True)
                session.add(comp)
                await session.flush()
                cid = comp.id

                session.add(SystemSetting(company_id=cid, setting_key="tax_percentage", setting_value="0.0"))
                session.add(OverrideReason(company_id=cid, code="EXPIRED_REPLACEMENT", description="استبدال تالف", is_active=True))

                loc_main = InventoryLocation(company_id=cid, name="المستودع الرئيسي", code=f"WH-MAIN-{cid}", location_type="WAREHOUSE", is_active=True)
                loc_sec = InventoryLocation(company_id=cid, name="المستودع الفرعي", code=f"WH-SEC-{cid}", location_type="WAREHOUSE", is_active=True)
                loc_transit = InventoryLocation(company_id=cid, name="بضاعة في الطريق", code="TRANSIT-SYS", location_type="IN_TRANSIT", is_active=True)
                session.add_all([loc_main, loc_sec, loc_transit])

                zone = Zone(company_id=cid, name=f"منطقة {cid}", governorate_id=gov.id, sequence_number=1, schedule_frequency="أسبوعي", visit_day="الأحد")
                session.add(zone)

                admin = Driver(company_id=cid, username=f"admin_{i}", full_name=f"مدير {c_name}", password_hash=hashed_pw, is_admin=True, is_active=True, max_debt_limit=Decimal("50000.0"))
                driver = Driver(company_id=cid, username=f"driver_{i}", full_name=f"مندوب {c_name}", password_hash=hashed_pw, is_admin=False, is_active=True, max_debt_limit=Decimal("2000.0"))
                session.add_all([admin, driver])
                await session.flush()

                prod = Product(company_id=cid, base_name=f"منتج أساسي {cid}")
                session.add(prod)
                await session.flush()

                var = ProductVariant(company_id=cid, product_id=prod.id, base_uom_id=uom_carton.id, variant_name=f"صنف {cid}", sku=f"SKU-{cid}", packs_per_carton=24, price_per_carton=Decimal("24.0"), price_per_pack=Decimal("1.0"), is_active=True)
                session.add(var)
                await session.flush()

                batch = ProductBatch(company_id=cid, product_variant_id=var.id, batch_number=f"B-{cid}-01", production_date=datetime.now(timezone.utc).date(), expiry_date=datetime.now(timezone.utc).date() + timedelta(days=365), is_active=True)
                session.add(batch)
                await session.flush()

                session.add(InventoryBalance(company_id=cid, location_id=loc_main.id, product_variant_id=var.id, batch_id=batch.id, stock_status="AVAILABLE", on_hand_quantity=1000, reserved_quantity=0))
                session.add(MainWarehouse(product_variant_id=var.id, available_quantity_packs=1000, reserved_quantity_packs=0, min_threshold_packs=10))

                # فاتورة قديمة لاختبار Vector 12 (تعديل عكسي عابر للشركات)
                session.add(WarehouseLedger(product_variant_id=var.id, quantity_packs=1000, balance_before_packs=0, balance_after_packs=1000, transaction_type="INBOUND_SUPPLIER", admin_id=admin.id, reference_id=f"TEST-INV-{cid}", notes="فاتورة تجريبية"))

                # حقن مكثف لاختبارات التحميل
                if inject_heavy:
                    for v_idx in range(1, 21):
                        session.add(Vehicle(company_id=cid, plate_number=f"{cid}-{v_idx:04d}", vehicle_type="باص", current_mileage=10000, maintenance_status="Active"))
                    for d_idx in range(1, 21):
                        session.add(Driver(company_id=cid, username=f"drv_{cid}_{d_idx}", full_name=f"مندوب {d_idx}", password_hash=hashed_pw, is_admin=False, is_active=True, max_debt_limit=Decimal("1000.0")))
                    for p_idx in range(1, 21):
                        session.add(ProductVariant(company_id=cid, product_id=prod.id, base_uom_id=uom_carton.id, variant_name=f"صنف إضافي {p_idx}", sku=f"SKU-{cid}-{p_idx}", packs_per_carton=12, price_per_carton=Decimal("10.0"), price_per_pack=Decimal("1.0"), is_active=True))

            await session.commit()
            print(f"SEED OK: {num_companies} companies seeded." + (" (Heavy Injection)" if inject_heavy else ""))
        except Exception as e:
            await session.rollback()
            print(f"SEED ERROR: {e}")
            sys.exit(1)

# ====================================================================
# 3. التشغيل (CLI)
# ====================================================================
async def main_reset(num_companies: int, heavy: bool):
    await rebuild_schema()
    await mass_seed(num_companies=num_companies, inject_heavy=heavy)

if __name__ == "__main__":
    is_mass = "--mass" in sys.argv
    if "--reset" in sys.argv:
        asyncio.run(main_reset(num_companies=10 if is_mass else 2, heavy=is_mass))
    else:
        print("Usage: python db_manager.py --reset [--mass]")
        print("  --reset : Drop schema, rebuild from Models, apply RLS + Grants, seed 2 companies")
        print("  --mass  : Seed 10 companies + heavy injection (20 drivers/vehicles/products per company)")