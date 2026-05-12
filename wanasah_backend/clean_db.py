# -*- coding: utf-8 -*-
from app import create_app
from models import db, VisitItem, VisitReturn, Visit, ShortageRequest, InventoryLedger, SessionInventory, VehicleLoad, DispatchRoute, WorkSession, WorkBreakLog, Driver, MainWarehouse, ProductVariant, WarehouseLedger, DamagedItemLog, SystemAuditLog, ImportLog, InventoryTransfer, Product
import bcrypt # +++ استيراد مكتبة التشفير +++

def clean_operational_data():
    print("🧹 جاري تنظيف البيانات التشغيلية الوهمية والملوثة...")
    try:
        deleted_breaks = db.session.query(WorkBreakLog).delete()
        # 1. الترتيب هنا هندسي وإجباري (من الأبناء للآباء) لتجنب أخطاء Foreign Key (القيود)
        deleted_visit_items = db.session.query(VisitItem).delete() # +++ تم حذف السطر المكرر لمنع إرهاق الداتابيز +++
        deleted_visit_returns = db.session.query(VisitReturn).delete()
        deleted_visits = db.session.query(Visit).delete() # هذا السطر سينسف شبح المحل 11
        
        deleted_shortages = db.session.query(ShortageRequest).delete()
        
        # +++ نسف جميع الحوالات (المصافحات) المعلقة والمنتهية +++
        deleted_transfers = db.session.query(InventoryTransfer).delete()
        
        deleted_ledgers = db.session.query(InventoryLedger).delete()
        deleted_session_inv = db.session.query(SessionInventory).delete()
        
        deleted_loads = db.session.query(VehicleLoad).delete()
        deleted_routes = db.session.query(DispatchRoute).delete()
        deleted_sessions = db.session.query(WorkSession).delete()
        
        # +++ الكي الجراحي الجذري: نسف سجلات المستودع المركزي وسجلات الرقابة بالكامل +++
        deleted_wh_ledgers = db.session.query(WarehouseLedger).delete()
        deleted_damaged_logs = db.session.query(DamagedItemLog).delete()
        deleted_audit_logs = db.session.query(SystemAuditLog).delete()
        deleted_import_logs = db.session.query(ImportLog).delete()
        
        # +++ تصفير كميات المنتجات (التوالف) لتجنب الأرصدة الشبحية +++
        warehouse_items = ProductVariant.query.all()
        for item in warehouse_items:
            item.available_quantity_packs = 0
            item.reserved_quantity_packs = 0
            item.damaged_quantity_packs = 0
        
        # +++ نسف المخزون المركزي (Central Warehouse) بالكامل +++
        # هذا الجدول يمثل "الخزنة الرئيسية" للشركة
        deleted_warehouse_items = db.session.query(MainWarehouse).delete()
        
        db.session.commit()
        
        print("✅ تم النسف بنجاح! الأرقام الآن:")
        print(f"- الزيارات والمبيعات المحذوفة: {deleted_visits + deleted_visit_items + deleted_visit_returns}")
        print(f"- خطوط السير والجلسات المحذوفة: {deleted_routes + deleted_sessions}")
        print(f"- سجلات المخزون والطلبات المحذوفة: {deleted_ledgers + deleted_session_inv + deleted_loads + deleted_shortages}")
        print("🎯 النظام الآن نظيف 100%، حساباتك ومحلاتك سليمة وجاهزة للعمل الحقيقي.")

    except Exception as e:
        db.session.rollback()
        print(f"❌ حدث خطأ أثناء التنظيف: {e}")

#كود اضافة مندوب ثاني
def add_test_driver():
    print("👤 جاري التحقق من المندوب التجريبي...")
    try:
        # رقم هاتف المندوب التجريبي
        test_phone = "0799999999"
        
        # التحقق مما إذا كان المندوب موجوداً لمنع تكرار الإضافة
        existing_driver = Driver.query.filter_by(phone_number=test_phone).first()
        if existing_driver:
            # +++ التصفيح: تغيير name إلى full_name ليتوافق مع الموديل +++
            print(f"⚠️ المندوب موجود مسبقاً باسم: {existing_driver.full_name}")
            return

        # تشفير كلمة المرور (123456)
        hashed_pw = bcrypt.hashpw("123456".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # إنشاء المندوب الجديد
        new_driver = Driver(
            username="test_driver", 
            full_name="مندوب تجارب (مؤقت)", 
            phone_number=test_phone, 
            password_hash=hashed_pw,
            is_admin=False,
            is_active=True,
            can_allow_debt=True
        )
        
        db.session.add(new_driver)
        db.session.commit()
        print(f"✅ تم إضافة المندوب التجريبي بنجاح!")
        print(f"🔑 رقم الدخول: {test_phone} | كلمة المرور: 123456")

    except Exception as e:
        db.session.rollback()
        print(f"❌ حدث خطأ أثناء إضافة المندوب: {e}")

# +++ النسف المعماري: دالة إضافة صنف عينات فقط (لا يباع) +++
def add_sample_product():
    print("📦 جاري التحقق من صنف العينات...")
    try:
        sample_sku = "SAMPLE-001"
        existing_sample = ProductVariant.query.filter_by(sku=sample_sku).first()
        
        if existing_sample:
            print(f"⚠️ صنف العينة موجود مسبقاً باسم: {existing_sample.variant_name}")
            return

        # 1. إنشاء المنتج الأب أولاً (Product) باستخدام base_name كما هو في models.py
        parent_product = Product.query.filter_by(base_name="عينات ترويجية").first()
        if not parent_product:
            parent_product = Product(base_name="عينات ترويجية", brand="وناسة", category="عينات")
            db.session.add(parent_product)
            db.session.flush() # للحصول على الـ ID فوراً قبل الحفظ النهائي

        # 2. إنشاء الصنف الفرعي (ProductVariant) وربطه بالأب
        new_sample = ProductVariant(
            product_id=parent_product.id, 
            variant_name="عينة ترويجية (غير مخصصة للبيع)",
            sku=sample_sku,
            price_per_carton=0.0,
            price_per_pack=0.0,
            packs_per_carton=10,
            default_max_samples_per_day=5, # الحد الأقصى المطلوب
            is_active=True
        )
        
        db.session.add(new_sample)
        db.session.commit()
        print("✅ تم إضافة صنف العينات بنجاح! (10 حبات، حد 5 يومياً).")

    except Exception as e:
        db.session.rollback()
        print(f"❌ حدث خطأ أثناء إضافة صنف العينة: {e}")

# +++ إضافة 7 أصناف جديدة معمارياً (منتجات متنوعة لاختبار الفراطة والحسابات) +++
def add_extra_products():
    print("🛒 جاري حقن 7 منتجات جديدة للداتابيز لاختبار النظام...")
    
    products_to_add = [
        # المنتج 1 (عائلة البسكويت)
        {"base_name": "بسكويت شاي", "brand": "وناسة", "category": "بسكويت", 
         "variants": [
             {"variant_name": "بسكويت شاي سادة (كبير)", "sku": "BIS-SH-L", "packs": 24, "price_c": 12.0, "price_p": 0.5},
             {"variant_name": "بسكويت شاي بالكاكاو (صغير)", "sku": "BIS-SH-S", "packs": 48, "price_c": 15.0, "price_p": 0.35}
         ]},
        # المنتج 2 (عائلة الكيك)
        {"base_name": "كيك وناسة", "brand": "وناسة", "category": "كيك", 
         "variants": [
             {"variant_name": "كيك رول فانيلا", "sku": "CAK-ROL-V", "packs": 12, "price_c": 6.0, "price_p": 0.55},
             {"variant_name": "كيك بار شوكولاتة", "sku": "CAK-BAR-C", "packs": 36, "price_c": 18.0, "price_p": 0.5}
         ]},
        # المنتج 3 (عائلة العصير)
        {"base_name": "عصير فريش", "brand": "وناسة", "category": "مشروبات", 
         "variants": [
             {"variant_name": "عصير برتقال 250 مل", "sku": "JUC-ORG-250", "packs": 24, "price_c": 8.0, "price_p": 0.35},
             {"variant_name": "عصير تفاح 1 لتر", "sku": "JUC-APL-1L", "packs": 6, "price_c": 9.0, "price_p": 1.5}
         ]}
    ]
    
    added_count = 0
    try:
        for prod_data in products_to_add:
            # التحقق أو إنشاء المنتج الأب
            parent_product = Product.query.filter_by(base_name=prod_data["base_name"]).first()
            if not parent_product:
                parent_product = Product(
                    base_name=prod_data["base_name"], 
                    brand=prod_data["brand"], 
                    category=prod_data["category"]
                )
                db.session.add(parent_product)
                db.session.flush() # للحصول على הـ ID
                
            # إنشاء الأصناف الفرعية التابعة له
            for var_data in prod_data["variants"]:
                existing_var = ProductVariant.query.filter_by(sku=var_data["sku"]).first()
                if not existing_var:
                    new_var = ProductVariant(
                        product_id=parent_product.id,
                        variant_name=var_data["variant_name"],
                        sku=var_data["sku"],
                        packs_per_carton=var_data["packs"],
                        price_per_carton=var_data["price_c"],
                        price_per_pack=var_data["price_p"],
                        default_max_samples_per_day=0, # مبيعات عادية، العينات 0
                        is_active=True
                    )
                    db.session.add(new_var)
                    added_count += 1
                    
        db.session.commit()
        if added_count > 0:
            print(f"✅ تم حقن {added_count} أصناف جديدة بنجاح!")
        else:
            print("⚠️ الأصناف الإضافية موجودة مسبقاً في النظام.")
            
    except Exception as e:
        db.session.rollback()
        print(f"❌ حدث خطأ أثناء إضافة المنتجات الإضافية: {e}")


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        clean_operational_data()
        #كود اضافة مندوب ثاني تكملة
        add_test_driver()
        # تشغيل دالة العينات
        add_sample_product()
        # +++ تشغيل دالة المنتجات السبعة الجديدة +++
        add_extra_products()