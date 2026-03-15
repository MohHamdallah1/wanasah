from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        # 1. مسح جدول سجل الميجريشن اللي عامل المشكلة
        db.session.execute(text('DROP TABLE IF EXISTS alembic_version CASCADE'))
        # 2. مسح كل جداول المشروع
        db.drop_all()
        db.session.commit()
        print("✅ تم تصفير قاعدة البيانات lulu_db بالكامل!")
    except Exception as e:
        print(f"❌ خطأ: {e}")