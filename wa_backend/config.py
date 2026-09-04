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
    
    # +++ إعدادات البنية التحتية للعزل (Redis & Storage) +++
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    STORAGE_BASE_PATH = os.environ.get('STORAGE_BASE_PATH', 'local_storage/')
    
    # إعدادات قاعدة البيانات PostgreSQL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("خطأ أمني قاتل: لم يتم العثور على DATABASE_URL في بيئة التشغيل! السيرفر يرفض الإقلاع حمايةً للبيانات.")
    
    # +++ إعدادات تجمع الاتصالات (Connection Pool) للعمل مع 4 Workers محلياً +++
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 15,           # 15 * 4 = 60 اتصال أساسي
        "max_overflow": 5,         # 5 * 4 = 20 اتصال فائض للضغط (الإجمالي 80 < 100)
        "pool_timeout": 30,        
        "pool_recycle": 1800,      
    }
    #في بيئة الانتاج ارفعهم الى 
    # +++ إعدادات تجمع الاتصالات (Connection Pool) لمنع الشلل التام (Deadlock) عند استخدام أقفال المخزون +++
        #SQLALCHEMY_ENGINE_OPTIONS = {
        #    "pool_size": 40,           # قاعدة دائمة (يجب أن تبقى أقل من max_connections في PostgreSQL)
        #    "max_overflow": 30,        # فائض للضغط: الإجمالي الأقصى 70 اتصال < 100 (حد PostgreSQL الافتراضي)
        #   "pool_timeout": 30,        
        #    # +++ درع الاستضافة السحابية: لا تحذفه أبداً — يقتل الاتصالات الخاملة قبل أن تقتلها المنصة +++
            # (Supabase/Heroku/RDS تقفل الاتصال الخامل بعد دقائق؛ بدونه ينهار أول طلب بعد فترة سكون)
        #   "pool_recycle": 1800,      
        #}