from app import app
from models import db, Shop, Zone, Visit, VisitItem, VisitReturn, DispatchRoute, ShortageRequest, ImportLog

with app.app_context():
    print("جاري تنظيف قاعدة البيانات لبدء بيئة الإنتاج...")
    
    # يجب حذف الجداول المعتمدة أولاً لتجنب أخطاء المفاتيح الأجنبية (Foreign Keys)
    VisitItem.query.delete()
    VisitReturn.query.delete()
    Visit.query.delete()
    ShortageRequest.query.delete()
    DispatchRoute.query.delete()
    ImportLog.query.delete()
    
    # أخيراً حذف المحلات والمناطق
    Shop.query.delete()
    Zone.query.delete()
    
    db.session.commit()
    print("تم تصفير جميع المحلات والمناطق والعمليات المرتبطة بنجاح! 🧹 جاهز للإنتاج.")