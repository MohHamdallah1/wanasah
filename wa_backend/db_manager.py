import asyncio
import sys
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, delete
from sqlalchemy.exc import IntegrityError
# استيراد إعدادات قاعدة البيانات الجديدة
from database import engine, AsyncSessionLocal
from models import (
    Base, SystemSetting, Country, Governorate, Zone, Driver, Product, 
    ProductVariant, OfferRule, Shop, Visit, Vehicle, VehicleLoad,
    WorkSession, WorkBreakLog, SessionInventory, InventoryLedger, 
    WarehouseLedger, DamagedItemLog, SystemAuditLog, ImportLog, 
    InventoryTransfer, VisitItem, VisitReturn, ShortageRequest, MainWarehouse, DispatchRoute
)

# ====================================================================
# 1. Full Reset & Seed Basic Data (تصفير كامل وزراعة)
# ====================================================================
async def reset_and_seed_db():
    print("\n⚠️  WARNING: Wiping entire database and rebuilding from scratch...")
    
    async with engine.begin() as conn:
        await conn.execute(text('DROP TABLE IF EXISTS alembic_version CASCADE'))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        
    print("✅  Schema rebuilt successfully. Seeding initial data...")
    
    async with AsyncSessionLocal() as session:
        try:
            session.add(SystemSetting(setting_key='tax_percentage', setting_value='0.0', description='الضريبة'))
            
            qatar = Country(name="قطر")
            session.add(qatar)
            await session.flush()
            
            doha = Governorate(name="بلدية الدوحة", country_id=qatar.id)
            rayyan = Governorate(name="بلدية الريان", country_id=qatar.id)
            session.add_all([doha, rayyan])
            await session.flush()
            
            zone_1 = Zone(name="خط الدوحة الكورنيش", governorate_id=doha.id, sequence_number=1, schedule_frequency="أسبوعي", visit_day="الأحد")
            zone_2 = Zone(name="خط الريان التجاري", governorate_id=rayyan.id, sequence_number=2, schedule_frequency="أسبوعي", visit_day="الاثنين")
            session.add_all([zone_1, zone_2])
            
            admin_driver = Driver(username='abuali', full_name='أبو علي (المدير)', is_active=True, is_admin=True, can_allow_debt=True, max_debt_limit=50000.0)
            admin_driver.set_password('password')
            
            test_driver = Driver(username='testdriver', full_name='مندوب تجريبي', is_active=True, is_admin=False, can_allow_debt=True, max_debt_limit=2000.0)
            test_driver.set_password('password')
            session.add_all([admin_driver, test_driver])
            await session.flush()
            
            v1 = Vehicle(plate_number="50-12345", vehicle_type="باص كيا", current_mileage=150000, maintenance_status="Active")
            v2 = Vehicle(plate_number="50-67890", vehicle_type="دينا ايسوزو", current_mileage=85000, maintenance_status="Active")
            session.add_all([v1, v2])
            await session.flush()
            
            product_lulu = Product(base_name='شيبس لولو', brand='Lulu', category='Snacks')
            product_police = Product(base_name='شيبس الشرطي', brand='Police', category='Snacks')
            session.add_all([product_lulu, product_police])
            await session.flush()
            
            var1 = ProductVariant(product_id=product_lulu.id, variant_name='شيبس لولو - حجم عائلي', sku='CHP-LULU-1', packs_per_carton=50, price_per_carton=Decimal('50.0'), price_per_pack=Decimal('1.0'))
            var2 = ProductVariant(product_id=product_police.id, variant_name='شيبس الشرطي - حار', sku='CHP-POL-1', packs_per_carton=24, price_per_carton=Decimal('24.0'), price_per_pack=Decimal('1.0'))
            session.add_all([var1, var2])
            await session.flush()
            
            session.add_all([
                VehicleLoad(vehicle_id=v1.id, product_variant_id=var1.id, quantity=150),
                VehicleLoad(vehicle_id=v1.id, product_variant_id=var2.id, quantity=48)
            ])
            
            session.add_all([
                OfferRule(threshold_quantity=50, offer_type='free_items', bonus_quantity=7),
                OfferRule(threshold_quantity=25, offer_type='free_items', bonus_quantity=3)
            ])
            
            for i in range(1, 11):
                shop = Shop(name=f"بقالة قطر {i}", current_balance=Decimal('0.0'), max_debt_limit=Decimal('1000.0'), zone_id=zone_1.id if i <= 5 else zone_2.id, added_by_driver_id=admin_driver.id)
                session.add(shop)
                await session.flush()
                visit = Visit(driver_id=test_driver.id, shop_id=shop.id, status='Pending', sequence=i, visit_timestamp=datetime.now(timezone.utc).replace(tzinfo=None))
                session.add(visit)
                
            await session.commit()
            print("✅  Database seeded successfully!")
        except Exception as e:
            await session.rollback()
            print(f"❌  Seed Error: {str(e)}")

# ====================================================================
# 2. Clean Operations Only (تنظيف العمليات فقط)
# ====================================================================
async def clean_operations():
    print("\n🧹  Cleaning operational data (Keeping Shops, Products, Zones)...")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(delete(WorkBreakLog))
            await session.execute(delete(VisitItem))
            await session.execute(delete(VisitReturn))
            await session.execute(delete(Visit))
            await session.execute(delete(ShortageRequest))
            await session.execute(delete(InventoryTransfer))
            await session.execute(delete(InventoryLedger))
            await session.execute(delete(SessionInventory))
            await session.execute(delete(VehicleLoad))
            await session.execute(delete(DispatchRoute))
            await session.execute(delete(WorkSession))
            await session.execute(delete(WarehouseLedger))
            await session.execute(delete(DamagedItemLog))
            await session.execute(delete(SystemAuditLog))
            await session.execute(delete(ImportLog))
            await session.execute(delete(MainWarehouse))
            
            await session.commit()
            print("✅  Operations cleaned successfully. System is ready.")
        except Exception as e:
            await session.rollback()
            print(f"❌  Cleaning Error: {e}")

# ====================================================================
# 3. Inject Extras (حقن المنتجات الإضافية)
# ====================================================================
async def inject_extras():
    print("\n🛒  Injecting extra products and test driver...")
    async with AsyncSessionLocal() as session:
        try:
            test_phone = "0799999999"
            stmt_driver = select(Driver).filter_by(phone_number=test_phone)
            if not (await session.execute(stmt_driver)).first():
                new_driver = Driver(username="test_driver2", full_name="مندوب تجارب (مؤقت)", phone_number=test_phone, is_admin=False, is_active=True, can_allow_debt=True)
                new_driver.set_password("123456")
                session.add(new_driver)
            
            sample_sku = "SAMPLE-001"
            stmt_sample = select(ProductVariant).filter_by(sku=sample_sku)
            if not (await session.execute(stmt_sample)).first():
                stmt_parent = select(Product).filter_by(base_name="عينات ترويجية")
                parent = (await session.execute(stmt_parent)).scalars().first()
                if not parent:
                    parent = Product(base_name="عينات ترويجية", brand="وناسة", category="عينات")
                    session.add(parent)
                    await session.flush()
                new_sample = ProductVariant(product_id=parent.id, variant_name="عينة ترويجية", sku=sample_sku, price_per_carton=Decimal('0.0'), price_per_pack=Decimal('0.0'), packs_per_carton=10, default_max_samples_per_day=5)
                session.add(new_sample)
            
            products_data = [
                {"base_name": "بسكويت شاي", "brand": "وناسة", "category": "بسكويت", "variants": [
                    {"name": "بسكويت شاي سادة (كبير)", "sku": "BIS-SH-L", "packs": 24, "price_c": '12.0', "price_p": '0.5'},
                    {"name": "بسكويت شاي بالكاكاو (صغير)", "sku": "BIS-SH-S", "packs": 48, "price_c": '15.0', "price_p": '0.35'}
                ]},
                {"base_name": "كيك وناسة", "brand": "وناسة", "category": "كيك", "variants": [
                    {"name": "كيك رول فانيلا", "sku": "CAK-ROL-V", "packs": 12, "price_c": '6.0', "price_p": '0.55'},
                    {"name": "كيك بار شوكولاتة", "sku": "CAK-BAR-C", "packs": 36, "price_c": '18.0', "price_p": '0.5'}
                ]},
                {"base_name": "عصير فريش", "brand": "وناسة", "category": "مشروبات", "variants": [
                    {"name": "عصير برتقال 250 مل", "sku": "JUC-ORG-250", "packs": 24, "price_c": '8.0', "price_p": '0.35'},
                    {"name": "عصير تفاح 1 لتر", "sku": "JUC-APL-1L", "packs": 6, "price_c": '9.0', "price_p": '1.5'}
                ]}
            ]
            
            for prod in products_data:
                stmt_parent = select(Product).filter_by(base_name=prod["base_name"])
                parent = (await session.execute(stmt_parent)).scalars().first()
                if not parent:
                    parent = Product(base_name=prod["base_name"], brand=prod["brand"], category=prod["category"])
                    session.add(parent)
                    await session.flush()
                for var in prod["variants"]:
                    stmt_var = select(ProductVariant).filter_by(sku=var["sku"])
                    if not (await session.execute(stmt_var)).first():
                        session.add(ProductVariant(product_id=parent.id, variant_name=var["name"], sku=var["sku"], packs_per_carton=var["packs"], price_per_carton=Decimal(var["price_c"]), price_per_pack=Decimal(var["price_p"])))
            
            await session.commit()
            print("✅  Extra products and driver injected successfully!")
        except Exception as e:
            await session.rollback()
            print(f"❌  Injection Error: {str(e)}")

# ====================================================================
# 4. Kill Product (إعدام منتج)
# ====================================================================
async def kill_product():
    sku = input("🔫  Enter product SKU to KILL (e.g. CHP-FAM-1): ").strip()
    if not sku: return
    
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(ProductVariant).filter_by(sku=sku)
            variant = (await session.execute(stmt)).scalars().first()
            if variant:
                parent_id = variant.product_id
                await session.execute(delete(ProductVariant).where(ProductVariant.id == variant.id))
                
                stmt_check = select(ProductVariant).filter_by(product_id=parent_id)
                if not (await session.execute(stmt_check)).first():
                    await session.execute(delete(Product).where(Product.id == parent_id))
                    print("💥  Parent product family also destroyed as it became empty!")
                
                await session.commit()
                print(f"🎯  Variant ({variant.variant_name}) Killed successfully!")
            else:
                print("⚠️  SKU not found!")
        except IntegrityError as e:
            # +++ الدرع الفولاذي: التقاط خطأ القيود الخارجية (Foreign Key Constraint) +++
            await session.rollback()
            print(f"❌  Kill Error: لا يمكن حذف هذا المنتج لأنه مرتبط بحركات مبيعات أو جرد سابقة. (اجعله is_active=False بدلاً من حذفه).")
        except Exception as e:
            await session.rollback()
            print(f"❌  Kill Error: {str(e)}")

# ====================================================================
# 5. Reset EXCEPT Logins, Vehicles, Products (مسح شامل مع الإبقاء على الأساسيات)
# ====================================================================
async def reset_except_essentials():
    print("\n⚠️  Deleting everything EXCEPT Logins, Vehicles, and Products...")
    async with AsyncSessionLocal() as session:
        try:
            # مسح العمليات
            await session.execute(delete(WorkBreakLog))
            await session.execute(delete(VisitItem))
            await session.execute(delete(VisitReturn))
            await session.execute(delete(Visit))
            await session.execute(delete(ShortageRequest))
            await session.execute(delete(InventoryTransfer))
            await session.execute(delete(InventoryLedger))
            await session.execute(delete(SessionInventory))
            await session.execute(delete(VehicleLoad))
            await session.execute(delete(DispatchRoute))
            await session.execute(delete(WorkSession))
            await session.execute(delete(WarehouseLedger))
            await session.execute(delete(DamagedItemLog))
            await session.execute(delete(SystemAuditLog))
            await session.execute(delete(ImportLog))
            await session.execute(delete(MainWarehouse))
            
            # مسح الإعدادات الجغرافية والمحلات
            await session.execute(delete(Shop))
            await session.execute(delete(OfferRule))
            await session.execute(delete(Zone))
            await session.execute(delete(Governorate))
            await session.execute(delete(Country))
            
            await session.commit()
            print("✅  Done! Only Drivers, Vehicles, and Products remain.")
        except Exception as e:
            await session.rollback()
            print(f"❌  Error: {e}")

# ====================================================================
# 6. Reset EXCEPT Logins ONLY (مسح كامل وإبقاء المشرف والمندوب فقط)
# ====================================================================
async def reset_except_logins():
    print("\n⚠️  Deleting EVERYTHING except Driver/Admin Logins...")
    async with AsyncSessionLocal() as session:
        try:
            # مسح العمليات
            await session.execute(delete(WorkBreakLog))
            await session.execute(delete(VisitItem))
            await session.execute(delete(VisitReturn))
            await session.execute(delete(Visit))
            await session.execute(delete(ShortageRequest))
            await session.execute(delete(InventoryTransfer))
            await session.execute(delete(InventoryLedger))
            await session.execute(delete(SessionInventory))
            await session.execute(delete(VehicleLoad))
            await session.execute(delete(DispatchRoute))
            await session.execute(delete(WorkSession))
            await session.execute(delete(WarehouseLedger))
            await session.execute(delete(DamagedItemLog))
            await session.execute(delete(SystemAuditLog))
            await session.execute(delete(ImportLog))
            await session.execute(delete(MainWarehouse))
            
            # مسح الإعدادات الجغرافية والمحلات
            await session.execute(delete(Shop))
            await session.execute(delete(OfferRule))
            await session.execute(delete(Zone))
            await session.execute(delete(Governorate))
            await session.execute(delete(Country))
            
            # +++ مسح المنتجات والسيارات +++
            await session.execute(delete(ProductVariant))
            await session.execute(delete(Product))
            await session.execute(delete(Vehicle))
            
            await session.commit()
            print("✅  Done! Database is completely empty except for Logins and System Settings.")
        except Exception as e:
            await session.rollback()
            print(f"❌  Error: {e}")

# ====================================================================
# القائمة الرئيسية (The CLI Menu)
# ====================================================================
async def main():
    while True:
        print("\n" + "="*60)
        print("🛠️  Wanasah DB Manager (FastAPI) 🛠️")
        print("="*60)
        print("1. Clean Operations Only (Keep Shops, Products, Vehicles)")
        print("2. FULL RESET & Seed Basic Data (Wipes EVERYTHING!)")
        print("3. Inject Extra Products & Test Driver")
        print("4. Kill Specific Product (by SKU)")
        print("5. Reset EXCEPT Logins, Vehicles, & Products")
        print("6. Reset EXCEPT Logins ONLY (Bare Minimum)")
        print("7. Exit")
        
        choice = input("\n👉 Select an option (1-7): ").strip()
        
        if choice == '1':
            confirm = input("⚠️  Are you sure? Type YES to confirm: ").strip().upper()
            if confirm == 'YES': await clean_operations()
            else: print("❌  Operation Cancelled.")
        elif choice == '2':
            confirm = input("🛑 DANGER: This will wipe the ENTIRE DB! Type YES to confirm: ").strip().upper()
            if confirm == 'YES': await reset_and_seed_db()
            else: print("❌  Operation Cancelled.")
        elif choice == '3':
            await inject_extras()
        elif choice == '4':
            await kill_product()
        elif choice == '5':
            confirm = input("⚠️  Delete all shops and operations? Type YES to confirm: ").strip().upper()
            if confirm == 'YES': await reset_except_essentials()
            else: print("❌  Operation Cancelled.")
        elif choice == '6':
            confirm = input("🛑 DANGER: Keep ONLY Logins? Type YES to confirm: ").strip().upper()
            if confirm == 'YES': await reset_except_logins()
            else: print("❌  Operation Cancelled.")
        elif choice == '7':
            print("👋  Goodbye!")
            break
        else:
            print("❌  Invalid option, try again.")

if __name__ == "__main__":
    asyncio.run(main())