# -*- coding: utf-8 -*-
import os
from datetime import datetime
from app import create_app
from models import db, SystemSetting, Country, Governorate, Zone, Driver, Product, ProductVariant, OfferRule, Shop, Visit

def seed_database():
    print("Starting database seeding for Qatar with FULL flexibility...")
    try:
        # مسح الجداول وبناؤها من الصفر لتطبيق الهيكلة الجديدة
        db.drop_all()
        db.create_all()
        
        # 1. إعدادات النظام
        settings = [
            SystemSetting(setting_key='tax_percentage', setting_value='0.0', description='الضريبة')
        ]
        db.session.bulk_save_objects(settings)

        # 2. الهيكلة الجغرافية
        qatar = Country(name="قطر")
        db.session.add(qatar)
        db.session.commit()

        doha = Governorate(name="بلدية الدوحة", country_id=qatar.id)
        rayyan = Governorate(name="بلدية الريان", country_id=qatar.id)
        db.session.add_all([doha, rayyan])
        db.session.commit()

        zone_1 = Zone(name="خط الدوحة الكورنيش", governorate_id=doha.id, sequence_number=1)
        zone_2 = Zone(name="خط الريان التجاري", governorate_id=rayyan.id, sequence_number=2)
        db.session.add_all([zone_1, zone_2])
        db.session.commit()

        # 3. المناديب
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

        # 4. المنتجات بمرونتها الكاملة (كل منتج له حجم وسعر)
        product_lulu = Product(base_name='شيبس لولو', brand='Lulu', category='Snacks')
        product_police = Product(base_name='شيبس الشرطي', brand='Police', category='Snacks')
        db.session.add_all([product_lulu, product_police])
        db.session.commit()

        v1 = ProductVariant(
            product_id=product_lulu.id, variant_name='شيبس لولو - جبنة',
            packs_per_carton=50, price_per_carton=45.0, price_per_pack=1.0
        )
        v2 = ProductVariant(
            product_id=product_police.id, variant_name='شيبس الشرطي - حار',
            packs_per_carton=24, price_per_carton=30.0, price_per_pack=1.5
        )
        db.session.add_all([v1, v2])

        # 5. قواعد العروض
        rules = [
            OfferRule(threshold_cartons=50, offer_type='free_items', bonus_cartons=7, bonus_packs=0),
            OfferRule(threshold_cartons=25, offer_type='free_items', bonus_cartons=3, bonus_packs=0),
        ]
        db.session.bulk_save_objects(rules)

        # 6. المحلات والزيارات التجريبية
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
        print("Database seeding completed successfully! Ready for flexible inventory!")

    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        seed_database()