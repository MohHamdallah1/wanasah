import os
from flask import Flask
from flask_cors import CORS  # +++ 1. استدعاء مكتبة CORS هنا +++
from flask_migrate import Migrate
from config import Config
from models import db
from routes import api
import traceback
import logging
from logging.handlers import RotatingFileHandler

def create_app():
    # إنشاء تطبيق فلاسك
    app = Flask(__name__)
  
    # +++ 2. تفعيل CORS للتطبيق للسماح للوحة التحكم بالاتصال +++
    CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True, allow_headers=["Content-Type", "Authorization"])
    
    # تحميل الإعدادات من ملف config.py
    app.config.from_object(Config)

    # ربط قاعدة البيانات بالتطبيق
    db.init_app(app)
    from flask_migrate import Migrate
    
    # تهيئة نظام التحديثات (Migrations) مع دعم SQLite
    migrate = Migrate(app, db, render_as_batch=True)

    # تسجيل كل الروابط اللي عملناها في ملف routes.py
    app.register_blueprint(api)

    return app

# تعريف التطبيق
app = create_app()

# إعداد ملف الأخطاء (error.log) بحجم أقصى 1 ميجابايت للملف
file_handler = RotatingFileHandler('error.log', maxBytes=1024 * 1024, backupCount=5, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s\n%(pathname)s:%(lineno)d'))
file_handler.setLevel(logging.ERROR)
app.logger.addHandler(file_handler)

@app.errorhandler(Exception)
def handle_global_error(error):
    # طباعة في التيرمنال
    print("\n🔥 كارثة برمجية:")
    traceback.print_exc()
    # حفظ في الملف للأبد
    app.logger.error(f"حدث خطأ غير متوقع: {str(error)}\n{traceback.format_exc()}")
    return {"message": "خطأ داخلي في الخادم", "error": str(error)}, 500

if __name__ == '__main__':
    # تشغيل السيرفر في وضع التطوير (سيتم تغييره عند الإطلاق)
    app.run(host='0.0.0.0', port=5000, debug=True)

