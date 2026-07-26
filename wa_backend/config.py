import os
from dotenv import load_dotenv

# تحميل متغيرات البيئة (مثل كلمات المرور) من ملف مخفي
load_dotenv(override=True)

class Config:
    # مفتاح الأمان للتطبيقات والتوكن (يتغير في السيرفر الحقيقي)
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("خطأ أمني قاتل: لم يتم العثور على SECRET_KEY في بيئة التشغيل!")
    
    # S-08: Enforce minimum cryptographic strength for HS256
    MIN_KEY_LENGTH = 32
    if len(SECRET_KEY) < MIN_KEY_LENGTH:
        raise ValueError(
            f"خطأ أمني قاتل: SECRET_KEY يجب أن يكون طوله {MIN_KEY_LENGTH} حرفاً على الأقل "
            f"(الطول الحالي: {len(SECRET_KEY)}). استخدم: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    import re
    if not re.search(r'[A-Z]', SECRET_KEY) or not re.search(r'[a-z]', SECRET_KEY) or not re.search(r'[0-9]', SECRET_KEY):
        raise ValueError(
            "خطأ أمني قاتل: SECRET_KEY يجب أن يحتوي على أحرف كبيرة وصغيرة وأرقام على الأقل."
        )
    
    # إعدادات قاعدة البيانات PostgreSQL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("خطأ أمني قاتل: لم يتم العثور على DATABASE_URL في بيئة التشغيل! السيرفر يرفض الإقلاع حمايةً للبيانات.")
    
    # +++ إعدادات تجمع الاتصالات (Connection Pool) لمنع الشلل التام (Deadlock) عند استخدام أقفال المخزون +++
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 50,           # رفعناها لـ 50 لاستيعاب جيش المناديب الصباحي
        "max_overflow": 20,        # فائض إضافي لحالات الضغط القصوى
        "pool_timeout": 30,        
        "pool_recycle": 1800,      
    }