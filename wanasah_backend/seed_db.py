# -*- coding: utf-8 -*-
import os
from datetime import datetime
from app import create_app
from models import db, SystemSetting, Country, Governorate, Zone, Driver, Product, ProductVariant, OfferRule, Shop, Visit, Vehicle, VehicleLoad

def seed_database():
    print("🌱 جاري زراعة البيانات الأساسية (نسخة قطر + الأسطول والوحدة الأساسية)...")
    try:
        # مسح الجداول وبناؤها من الصفر لتطبيق الهيكلة الجديدة
        db.drop_all()
        db.create_all()
        
        # 1. إعدادات النظام
        settings = [
            SystemSetting(setting_key='tax_percentage', setting_value='0.0', description='الضريبة')
        ]
        db.session.bulk_save_objects(settings)

        # 2. الهيكلة الجغرافية (قطر)
        qatar = Country(name="قطر")
        db.session.add(qatar)
        db.session.commit()

        doha = Governorate(name="بلدية الدوحة", country_id=qatar.id)
        rayyan = Governorate(name="بلدية الريان", country_id=qatar.id)
        db.session.add_all([doha, rayyan])
        db.session.commit()

        zone_1 = Zone(name="خط الدوحة الكورنيش", governorate_id=doha.id, sequence_number=1, schedule_frequency="أسبوعي", visit_day="الأحد")
        zone_2 = Zone(name="خط الريان التجاري", governorate_id=rayyan.id, sequence_number=2, schedule_frequency="أسبوعي", visit_day="الاثنين")
        db.session.add_all([zone_1, zone_2])
        db.session.commit()

        # 3. المناديب (المدير والمندوب التجريبي)
        admin_driver = Driver(
            username='abuali', full_name='أبو علي (المدير)',
            is_active=True, is_admin=True, can_allow_debt=True, max_debt_limit=50000.0
        )
        admin_driver.set_password('password')

        test_driver = Driver(
            username='testdriver', full_name='مندوب تجريبي',
            is_active=True, is_admin=False, can_allow_debt=True, max_debt_limit=2000.0
        )
        test_driver.set_password('password')
        db.session.add_all([admin_driver, test_driver])
        db.session.commit()

        # 4. إضافة أسطول السيارات (الجديد)
        v1 = Vehicle(plate_number="50-12345", vehicle_type="باص كيا", current_mileage=150000, maintenance_status="Active")
        v2 = Vehicle(plate_number="50-67890", vehicle_type="دينا ايسوزو", current_mileage=85000, maintenance_status="Active")
        db.session.add_all([v1, v2])
        db.session.commit()

        # 5. المنتجات بمرونتها الكاملة
        product_lulu = Product(base_name='شيبس لولو', brand='Lulu', category='Snacks')
        product_police = Product(base_name='شيبس الشرطي', brand='Police', category='Snacks')
        db.session.add_all([product_lulu, product_police])
        db.session.commit()

        var1 = ProductVariant(
            product_id=product_lulu.id, variant_name='شيبس لولو - حجم عائلي',
            packs_per_carton=50, price_per_carton=45.0, price_per_pack=1.0
        )
        var2 = ProductVariant(
            product_id=product_police.id, variant_name='شيبس الشرطي - حار',
            packs_per_carton=24, price_per_carton=30.0, price_per_pack=1.5
        )
        db.session.add_all([var1, var2])
        db.session.commit()

        # 6. شحن السيارة بمسودة بضاعة (لاختبار سحب المخزون)
        # هنشحن سيارة 1 بـ 150 حبة لولو (3 كراتين) و 48 حبة شرطي (كرتونتين)
        load1 = VehicleLoad(vehicle_id=v1.id, product_variant_id=var1.id, quantity=150)
        load2 = VehicleLoad(vehicle_id=v1.id, product_variant_id=var2.id, quantity=48)
        db.session.add_all([load1, load2])

        # 7. قواعد العروض
        rules = [
            OfferRule(threshold_quantity=50, offer_type='free_items', bonus_quantity=7),
            OfferRule(threshold_quantity=25, offer_type='free_items', bonus_quantity=3),
        ]
        db.session.bulk_save_objects(rules)

        # 8. المحلات والزيارات التجريبية
        for i in range(1, 11):
            shop = Shop(
                name=f"بقالة قطر {i}",
                current_balance=0.0,
                max_debt_limit=1000.0,
                zone_id=zone_1.id if i <= 5 else zone_2.id,
                added_by_driver_id=admin_driver.id
            )
            db.session.add(shop)
            db.session.flush()

            visit = Visit(
                driver_id=test_driver.id,
                shop_id=shop.id,
                status='Pending',
                sequence=i,
                visit_timestamp=datetime.utcnow()
            )
            db.session.add(visit)

        db.session.commit()
        print("✅ تم زراعة البيانات بنجاح! السيرفر جاهز للعمل مع التوزيع والمخزون الموحد.")

    except Exception as e:
        db.session.rollback()
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        seed_database()