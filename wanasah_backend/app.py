import os
from flask import Flask
from flask_migrate import Migrate
from config import Config
from models import db
from routes import api

def create_app():
    # إنشاء تطبيق فلاسك
    app = Flask(__name__)
    
    # تحميل الإعدادات من ملف config.py
    app.config.from_object(Config)

    # ربط قاعدة البيانات بالتطبيق
    db.init_app(app)
    
    # تهيئة نظام التحديثات (Migrations)
    Migrate(app, db, render_as_batch=True)

    # تسجيل كل الروابط اللي عملناها في ملف routes.py
    app.register_blueprint(api)

    return app

# تعريف التطبيق
app = create_app()

if __name__ == '__main__':
    # تشغيل السيرفر في وضع التطوير (سيتم تغييره عند الإطلاق)
    app.run(host='0.0.0.0', port=5000, debug=True)