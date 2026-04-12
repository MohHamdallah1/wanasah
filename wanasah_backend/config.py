import os
from dotenv import load_dotenv

# تحميل متغيرات البيئة (مثل كلمات المرور) من ملف مخفي
load_dotenv()

class Config:
    # مفتاح الأمان للتطبيقات والتوكن (يتغير في السيرفر الحقيقي)
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("خطأ أمني قاتل: لم يتم العثور على SECRET_KEY في بيئة التشغيل!")
    
    # إعدادات قاعدة البيانات PostgreSQL
    # يتم قراءة الرابط من متغيرات البيئة، وإذا لم يوجد يستخدم هذا الرابط الافتراضي
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'postgresql://postgres:yourpassword@localhost:5432/lulu_db'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # +++ إعدادات تجمع الاتصالات (Connection Pool) لمنع الشلل التام (Deadlock) عند استخدام أقفال المخزون +++
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 20,           # عدد الاتصالات المتزامنة المسموح بها
        "pool_timeout": 30,        # أقصى مدة للانتظار (بالثواني) قبل رفض الطلب في حال الضغط
        "pool_recycle": 1800,      # إعادة تدوير الاتصال كل نصف ساعة لمنع انقطاعه من قاعدة البيانات
    }