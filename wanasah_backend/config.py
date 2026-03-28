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