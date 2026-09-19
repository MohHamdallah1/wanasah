import os
from pathlib import Path
from dotenv import load_dotenv

# تحميل متغيرات البيئة (مثل كلمات المرور) من ملف مخفي
load_dotenv(Path(__file__).resolve().with_name(".env"), override=False)

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
    
    # ميزانية الاتصالات مقاسة من Stage 8.2.1: نقطة التشبع الحالية ≈ 40
    # اتصال PostgreSQL متزامناً للتطبيق كله. لا ترفعها عشوائياً؛ أعد تشغيل
    # diagnose_stage821_concurrency_knee.py على نفس طبقة قاعدة بيانات الإنتاج.
    WEB_CONCURRENCY = int(os.environ.get("WEB_CONCURRENCY", "4"))
    DB_APP_CONNECTION_BUDGET = int(
        os.environ.get("DB_APP_CONNECTION_BUDGET", "40")
    )
    DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "8"))
    DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "2"))
    DB_POOL_TIMEOUT = float(os.environ.get("DB_POOL_TIMEOUT", "3"))
    DB_POOL_RECYCLE = int(os.environ.get("DB_POOL_RECYCLE", "1800"))

    if WEB_CONCURRENCY <= 0:
        raise ValueError("WEB_CONCURRENCY يجب أن يكون أكبر من صفر.")
    if DB_APP_CONNECTION_BUDGET <= 0:
        raise ValueError("DB_APP_CONNECTION_BUDGET يجب أن يكون أكبر من صفر.")
    if DB_POOL_SIZE <= 0 or DB_MAX_OVERFLOW < 0:
        raise ValueError("إعدادات DB pool غير صالحة.")
    if DB_POOL_TIMEOUT <= 0 or DB_POOL_RECYCLE <= 0:
        raise ValueError("DB pool timeout/recycle يجب أن يكونا أكبر من صفر.")

    DB_CONNECTIONS_PER_WORKER = DB_POOL_SIZE + DB_MAX_OVERFLOW
    DB_CONNECTIONS_TOTAL = DB_CONNECTIONS_PER_WORKER * WEB_CONCURRENCY
    if DB_CONNECTIONS_TOTAL > DB_APP_CONNECTION_BUDGET:
        raise ValueError(
            "إعدادات قاعدة البيانات تتجاوز ميزانية الاتصالات الآمنة: "
            f"{DB_CONNECTIONS_TOTAL} > {DB_APP_CONNECTION_BUDGET}. "
            "خفّض DB_POOL_SIZE/DB_MAX_OVERFLOW أو أعد قياس نقطة التشبع."
        )

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": DB_POOL_SIZE,
        "max_overflow": DB_MAX_OVERFLOW,
        "pool_timeout": DB_POOL_TIMEOUT,
        "pool_recycle": DB_POOL_RECYCLE,
        "pool_use_lifo": True,
    }
