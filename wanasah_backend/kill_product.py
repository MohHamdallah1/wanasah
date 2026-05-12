# -*- coding: utf-8 -*-
from app import create_app
from models import db, ProductVariant, Product

def kill_the_variant():
    print("🔫 جاري البحث عن الصنف المطلوب نسفه...")
    try:
        # نبحث عن الصنف باستخدام הـ SKU الذي وضعناه له
        target_sku = "CHP-FAM-1"
        variant_to_kill = ProductVariant.query.filter_by(sku=target_sku).first()
        
        if variant_to_kill:
            print(f"🎯 تم العثور على: {variant_to_kill.variant_name}")
            db.session.delete(variant_to_kill)
            db.session.commit()
            print("💥 تم نسف الصنف الفرعي بنجاح!")
            
            # اختياري: تنظيف الأب إذا لم يتبقَ له أبناء
            parent = Product.query.filter_by(base_name="شيبس عائلي").first()
            if parent and not parent.variants:
                 db.session.delete(parent)
                 db.session.commit()
                 print("💥 تم نسف عائلة المنتج (الأب) أيضاً لأنها أصبحت فارغة!")
        else:
            print("⚠️ الصنف غير موجود بالداتابيز أصلاً!")

    except Exception as e:
        db.session.rollback()
        print(f"❌ حدث خطأ أثناء النسف: {e}")

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        kill_the_variant()