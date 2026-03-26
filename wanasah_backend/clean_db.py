# -*- coding: utf-8 -*-
from app import create_app
from models import db, VisitItem, VisitReturn, Visit, ShortageRequest, InventoryLedger, SessionInventory, VehicleLoad, DispatchRoute, WorkSession, WorkBreakLog, Driver
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
        deleted_ledgers = db.session.query(InventoryLedger).delete()
        deleted_session_inv = db.session.query(SessionInventory).delete()
        
        deleted_loads = db.session.query(VehicleLoad).delete()
        deleted_routes = db.session.query(DispatchRoute).delete()
        deleted_sessions = db.session.query(WorkSession).delete()
        
        
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
            print(f"⚠️ المندوب موجود مسبقاً باسم: {existing_driver.name}")
            return

        # تشفير كلمة المرور (123456)
        hashed_pw = bcrypt.hashpw("123456".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # إنشاء المندوب الجديد
        new_driver = Driver(
        username="test_driver", # حقل إجباري في الداتابيز عندك
        full_name="مندوب تجارب (مؤقت)", # الاسم الصحيح في الموديل
        phone_number=test_phone, # الاسم الصحيح في الموديل
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
        #نهاية كود اضافة مندوب ثاني

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        clean_operational_data()
        #كود اضافة مندوب ثاني تكملة
        add_test_driver()