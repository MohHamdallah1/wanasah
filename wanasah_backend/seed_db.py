# -*- coding: utf-8 -*-
import os
from app import app, db, Driver, Product, ProductVariant, Shop, Visit, WorkSession # استيراد النماذج
from datetime import datetime, date
import traceback
# import random # يمكن استخدامه لرصيد عشوائي إذا أردت

def seed_database():
    """يقوم بإضافة البيانات التجريبية الأساسية (مع 20 محلاً وزياراتها)."""
    print("Starting database seeding...")
    try:
        # --- !!! خطوة 1: تنظيف البيانات القديمة (اختياري لكن موصى به للعرض) !!! ---
        # حذف الزيارات وجلسات العمل والمحلات لضمان عدم التداخل مع البيانات القديمة
        print("Deleting existing Visits, WorkSessions, and Shops...")
        # حذف الزيارات أولاً بسبب المفتاح الأجنبي للمحل
        Visit.query.delete()
        WorkSession.query.delete() # حذف الجلسات القديمة
        Shop.query.delete()      # حذف المحلات القديمة
        db.session.commit()      # تأكيد الحذف
        print("Old operational data deleted.")
        # --------------------------------------------------------------------

        # --- خطوة 2: التأكد من وجود السائق التجريبي (ID=1) ---
        print("Ensuring test driver (ID=1)...")
        test_driver = db.session.get(Driver, 1)
        if not test_driver:
            test_driver = Driver(
                id=1, username='testdriver', full_name='Test Driver Abu Ali',
                is_active=True, is_admin=False, default_starting_cartons=61 # افترضنا قيمة افتراضية للمخزون
            )
            test_driver.set_password('password')
            db.session.add(test_driver)
            # Commit هنا ضروري للحصول على test_driver.id بشكل موثوق إذا كان جديداً
            db.session.commit()
            test_driver = db.session.get(Driver, 1) # إعادة جلبه للتأكيد
            print("Test driver created.")
        else:
             # التأكد من وجود قيمة للمخزون الافتراضي إذا كان السائق موجوداً
             if test_driver.default_starting_cartons is None:
                 test_driver.default_starting_cartons = 61
                 db.session.add(test_driver) # يحتاج لإضافة للتحديث
                 db.session.commit()
             print("Test driver already exists.")
        # ---------------------------------------------------

        # --- خطوة 3: التأكد من وجود المنتج الأساسي ---
        print("Ensuring base product...")
        base_product = Product.query.filter_by(base_name='شيبس لولو').first()
        if not base_product:
            base_product = Product(base_name='شيبس لولو', brand='Lulu Brand', category='Snacks')
            db.session.add(base_product)
            db.session.commit() # Commit ضروري للحصول على ID المنتج
            base_product = Product.query.filter_by(base_name='شيبس لولو').first()
            print("Base product created.")
        else:
            print("Base product already exists.")
        # ------------------------------------------

        # --- خطوة 4: التأكد من وجود متغيرات المنتج ---
        print("Ensuring product variants...")
        variants_data = [
            {'name': 'شيبس لولو - جبنة حجم صغير', 'price': 5.25, 'flavor': 'جبنة', 'size': 'صغير'},
            {'name': 'شيبس لولو - جبنة حجم كبير', 'price': 10.50, 'flavor': 'جبنة', 'size': 'كبير'},
            {'name': 'شيبس لولو - كاتشاب حجم صغير', 'price': 5.25, 'flavor': 'كاتشاب', 'size': 'صغير'},
            {'name': 'شيبس لولو - كاتشاب حجم كبير', 'price': 10.50, 'flavor': 'كاتشاب', 'size': 'كبير'},
            {'name': 'شيبس لولو - ملح وخل حجم كبير', 'price': 10.50, 'flavor': 'ملح وخل', 'size': 'كبير'}
        ]
        variants_added_count = 0
        if base_product and base_product.id:
            for variant_info in variants_data:
                existing_variant = ProductVariant.query.filter_by(variant_name=variant_info['name'], product_id=base_product.id).first()
                if not existing_variant:
                    new_variant = ProductVariant(
                        product_id=base_product.id, variant_name=variant_info['name'],
                        flavor=variant_info['flavor'], size=variant_info['size'],
                        price_per_carton=variant_info['price'], is_active=True
                    )
                    db.session.add(new_variant)
                    variants_added_count += 1
            if variants_added_count > 0:
                db.session.commit() # Commit للمتغيرات الجديدة
                print(f"{variants_added_count} new product variants created.")
            else:
                 print("Product variants already exist.")
        else:
             print("Base product not found, skipping variant creation.")
        # ---------------------------------------------

        # --- !!! خطوة 5: إنشاء 20 محلاً وزياراتها المعلقة !!! ---
        print("Creating 20 shops and their pending visits...")
        shops_created = 0
        visits_created = 0
        target_driver_id = test_driver.id # استخدام الـ ID للسائق التجريبي

        for i in range(20):
            shop_name = f"بقالة {i + 1}"
            # حساب رصيد ذمة متدرج من 0 إلى 50 تقريباً (يمكن استخدام random إذا أردت عشوائية)
            shop_balance = round((i * 50.0) / 19.0, 2) # يتدرج من 0.0 إلى 50.0

            # إنشاء المحل
            new_shop = Shop(
                name=shop_name,
                current_balance=shop_balance,
                is_active=True,
                region_name="المنطقة التجريبية", # منطقة افتراضية
                added_by_driver_id = target_driver_id # ربطه بالسائق
                # أضف عناوين أو هواتف افتراضية إذا أردت
                # address=f"عنوان افتراضي {i+1}",
                # phone_number=f"077{i:07d}"
            )
            db.session.add(new_shop)
            shops_created += 1

            # تنفيذ flush للحصول على ID المحل الجديد قبل إنشاء الزيارة المرتبطة به
            try:
                 db.session.flush() # الحصول على new_shop.id
                 if new_shop.id:
                      # إنشاء زيارة Pending للمحل الجديد
                      new_visit = Visit(
                          driver_id=target_driver_id,
                          shop_id=new_shop.id,
                          status='Pending', # الحالة الأولية
                          sequence=i + 1,   # ترتيب الزيارة
                          visit_timestamp=datetime.utcnow(), # وقت الإنشاء
                          outcome=None,
                          work_session_id=None, # غير مرتبطة بجلسة بعد
                          quantity_sold=0,
                          cash_collected=0.0,
                          debt_paid=0.0
                          # بقية الحقول تأخذ قيمها الافتراضية أو Nullable
                      )
                      db.session.add(new_visit)
                      visits_created += 1
                 else:
                      print(f"WARNING: Could not get ID for shop '{shop_name}' after flush. Visit not created.")
            except Exception as flush_err:
                 print(f"ERROR during flush/visit creation for shop '{shop_name}': {flush_err}")
                 # في حالة الخطأ هنا، الأفضل عمل rollback في النهاية

        # --- Commit نهائي للمحلات والزيارات الجديدة ---
        db.session.commit()
        print(f"{shops_created} shops and {visits_created} visits created/added.")
        print("Database seeding completed successfully!")
        # --- !!! نهاية خطوة إنشاء المحلات والزيارات !!! ---

    except Exception as e:
        db.session.rollback() # تراجع عن كل التغييرات في حالة أي خطأ
        print(f"An error occurred during seeding: {e}")
        traceback.print_exc()

    finally:
        db.session.close()

# --- تشغيل الدالة ---
if __name__ == '__main__':
    # استخدام سياق التطبيق ضروري للوصول لـ db والإعدادات
    with app.app_context():
        seed_database()