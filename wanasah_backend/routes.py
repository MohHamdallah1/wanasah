from flask import Blueprint, request, jsonify, g
from datetime import datetime, date, timezone
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import traceback
from sqlalchemy import func

from models import db, Driver, Shop, Visit, WorkSession, ProductVariant, SessionInventory
from services import calculate_invoice, check_debt_limits, adjust_inventory
from config import Config
from sqlalchemy import func
from sqlalchemy.orm import joinedload

api = Blueprint('api', __name__)
token_serializer = URLSafeTimedSerializer(Config.SECRET_KEY)

# --- دالة حماية الروابط ---
from functools import wraps
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            try:
                token = request.headers['Authorization'].split(" ")[1]
            except IndexError:
                return jsonify({"message": "Invalid Authorization header format"}), 401
        
        if not token:
            return jsonify({"message": "Token is missing"}), 401

        try:
            data = token_serializer.loads(token, max_age=86400)
            g.current_driver_id = data['driver_id']
        except (SignatureExpired, BadSignature):
            return jsonify({"message": "Token is invalid or expired"}), 401
        except Exception:
            return jsonify({"message": "Token processing error"}), 401

        return f(*args, **kwargs)
    return decorated_function

# =========================================
# 1. تسجيل الدخول
# =========================================
@api.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"message": "Missing username or password"}), 400

    driver = Driver.query.filter_by(username=data.get('username'), is_active=True).first()

    if driver and driver.check_password(data.get('password')):
        token = token_serializer.dumps({'driver_id': driver.id})
        return jsonify({
            "message": "Login Successful!",
            "token": token,
            "driver_id": driver.id,
            "driver_name": driver.full_name,
            "is_admin": driver.is_admin
        }), 200
    return jsonify({"message": "Invalid username or password"}), 401

# =========================================
# 2. بدء جلسة العمل (نسخة الخبير - صاروخية وبدون N+1)
# =========================================
@api.route('/driver/<int:driver_id>/sessions/start', methods=['POST'])
@token_required
def start_work_session(driver_id):
    if getattr(g, 'current_driver_id', None) != driver_id:
         return jsonify({"message": "Forbidden"}), 403

    today_date = date.today()
    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=today_date, end_time=None).first()

    if active_session:
        return jsonify({"message": "Session already active", "session_id": active_session.id}), 409

    data = request.get_json() or {}

    try:
        new_session = WorkSession(
            driver_id=driver_id,
            session_date=today_date,
            start_time=datetime.now(timezone.utc),
            start_latitude=data.get('latitude'),
            start_longitude=data.get('longitude')
        )
        db.session.add(new_session)
        db.session.flush() # للحصول على الـ ID فوراً بدون commit

        # 1. جلب المنتجات الفعالة فقط (توفير استهلاك الذاكرة كما نصح الخبير)
        active_products = ProductVariant.query.filter_by(is_active=True).all()
        
        # +++ حل مشكلة البوكسات المخفية +++
        # إذا كانت المنتجات بالداتا بيس مش مفعلة (is_active=False) بسبب ملف seed، هاد الشرط رح يتدارك الموقف ويجيبهم:
        if not active_products:
            active_products = ProductVariant.query.all()

        # 2. تجهيز الجرد بـ "الذاكرة العشوائية" (RAM) أولاً بدون لمس الداتا بيس
        inventory_objects = []
        for variant in active_products:
            inventory_objects.append(
                SessionInventory(
                    work_session_id=new_session.id,
                    product_variant_id=variant.id,
                    starting_cartons=10,
                    starting_packs=0,
                    current_remaining_cartons=10,
                    current_remaining_packs=0
                )
            )

        # 3. الحقن الصاروخي: إرسال القائمة كاملة بطلب واحد (Single Query)
        if inventory_objects:
            db.session.bulk_save_objects(inventory_objects)

        db.session.commit()

        # 4. إرجاع الأرقام للواجهة كما طلب الخبير لتجنب أي أخطاء (Null)
        total_test_cartons = len(inventory_objects) * 10
        return jsonify({
            "message": "Session started", 
            "session_id": new_session.id,
            "starting_cartons": total_test_cartons,
            "remaining_cartons": total_test_cartons
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Error starting session", "error": str(e)}), 500
    

# =========================================
# 3. إنهاء جلسة العمل
# =========================================
@api.route('/driver/<int:driver_id>/sessions/end', methods=['PUT'])
@token_required
def end_work_session(driver_id):
    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=date.today(), end_time=None).first()
    if not active_session:
        return jsonify({"message": "No active session"}), 404

    try:
        active_session.end_time = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({"message": "Session ended"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Error ending session"}), 500

# =========================================
# 4. تحديث نتيجة الزيارة
# =========================================
@api.route('/visits/<int:visit_id>', methods=['PUT'])
@token_required
def update_visit(visit_id):
    visit = db.get_or_404(Visit, visit_id)
    if visit.driver_id != getattr(g, 'current_driver_id', None):
         return jsonify({"message": "Forbidden"}), 403

    data = request.get_json()
    outcome = data.get('outcome')
    if outcome not in ['Sale', 'NoSale', 'Postponed']:
        return jsonify({"message": "Invalid outcome"}), 400

    shop = visit.shop
    active_session = WorkSession.query.filter_by(driver_id=visit.driver_id, session_date=date.today(), end_time=None).first()

    try:
        debt_paid_input = float(data.get('debt_paid', 0.0))
        
        # --- قراءة القيم القديمة ---
        original_shop_balance = shop.current_balance or 0.0
        old_quantity_sold = visit.quantity_sold or 0
        new_shop_balance = original_shop_balance

        # +++ منع دفع ذمة أكبر من رصيد المحل الفعلي +++
        if debt_paid_input > 0 and debt_paid_input > original_shop_balance:
             return jsonify({"message": f"مرفوض: لا يمكن تحصيل مبلغ ({debt_paid_input}) أكبر من الذمة الحالية للمحل ({original_shop_balance})."}), 400
        # +++++++++++++++++++++++++++++++++++++++++++++++++++++++++

        visit.visit_timestamp = datetime.now(timezone.utc)
        visit.notes = data.get('notes')
        visit.latitude = data.get('latitude', visit.latitude)
        visit.longitude = data.get('longitude', visit.longitude)
        visit.shop_balance_before = original_shop_balance
        
        if active_session:
            visit.work_session_id = active_session.id

        if outcome == 'Sale':
            quantity = int(data.get('quantity_sold', 0))
            cash_collected = float(data.get('cash_collected', 0.0))
            variant_id = data.get('product_variant_id')
            
            if quantity <= 0 or not variant_id:
                return jsonify({"message": "Invalid sale data"}), 400
                
            variant = db.get_or_404(ProductVariant, variant_id)
            
            # حساب الفاتورة من ملف services
            invoice = calculate_invoice(quantity, variant.price_per_carton)
            
            # فحص سقف الذمم
            new_debt = invoice['final_amount'] - cash_collected
            if new_debt > 0:
                is_allowed, msg = check_debt_limits(visit.driver_id, shop.id, new_debt)
                if not is_allowed:
                    return jsonify({"message": msg}), 403

            # تعديل المخزون (بالنظام المفصل الجديد)
            if active_session:
                net_cartons = -(quantity + invoice['bonus_cartons'])
                net_packs = -(invoice['bonus_packs'])
                inv_success, inv_msg = adjust_inventory(active_session.id, variant_id, net_cartons, net_packs)
                if not inv_success:
                    return jsonify({"message": inv_msg}), 409

            # تحديث الزيارة
            visit.outcome = 'Sale'
            visit.status = 'Completed'
            visit.product_variant_id = variant_id
            visit.quantity_sold = quantity
            visit.price_per_carton_at_sale = variant.price_per_carton
            visit.amount_before_tax_and_discount = invoice['base_amount']
            visit.discount_applied = invoice['discount_applied']
            visit.tax_percentage_applied = invoice['tax_percentage']
            visit.tax_amount = invoice['tax_amount']
            visit.final_amount_due = invoice['final_amount']
            visit.cash_collected = cash_collected
            visit.debt_paid = debt_paid_input
            
            new_balance = original_shop_balance + new_debt - debt_paid_input
            shop.current_balance = new_balance
            visit.shop_balance_after = new_balance

        elif outcome == 'NoSale':
            visit.outcome = 'NoSale'
            visit.status = 'Completed'
            visit.debt_paid = debt_paid_input
            visit.no_sale_reason = data.get('notes')
            new_balance = original_shop_balance - debt_paid_input
            shop.current_balance = new_balance
            visit.shop_balance_after = new_balance

        elif outcome == 'Postponed':
            visit.outcome = 'Postponed'
            visit.status = 'Pending'
            visit.no_sale_reason = data.get('notes')
            visit.shop_balance_after = original_shop_balance

        db.session.commit()
        return jsonify({
            "message": "Visit updated",
            "new_balance": shop.current_balance
        }), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "Error updating visit", "error": str(e)}), 500

# =========================================
# 5. جلب بيانات الداشبورد (بسرعة الصاروخ وبأقل تكلفة سيرفر)
# =========================================
@api.route('/driver/<int:driver_id>/dashboard', methods=['GET'])
@token_required
def dashboard(driver_id):
    driver = db.session.get(Driver, driver_id)
    if not driver: return jsonify({"message": "Not found"}), 404

    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=date.today(), end_time=None).first()
    
    # +++ استخدام قاعدة البيانات للحساب بدلاً من البايثون (تقليل التكاليف) +++
    stats = db.session.query(
        func.count(Visit.id).label('completed_count'),
        func.sum(Visit.cash_collected).label('total_cash'),
        func.sum(Visit.debt_paid).label('total_debt')
    ).filter(Visit.driver_id == driver_id, Visit.status == 'Completed').first()

    sales_count = db.session.query(func.count(Visit.id)).filter(
        Visit.driver_id == driver_id, Visit.status == 'Completed', Visit.outcome == 'Sale'
    ).scalar() or 0

    pending_count = Visit.query.filter_by(driver_id=driver_id, status='Pending').count()
    
    total_sales_cash = float(stats.total_cash or 0.0)
    total_debt_paid = float(stats.total_debt or 0.0)
    
    # +++ استخدام joinedload لجلب المنتجات بطلب واحد (Single Query) +++
    inventory_list = []
    if active_session:
        inventories = SessionInventory.query.options(
            joinedload(SessionInventory.product_variant)
        ).filter_by(work_session_id=active_session.id).all()
        
        for inv in inventories:
            inventory_list.append({
                "product_name": inv.product_variant.variant_name,
                "starting_cartons": inv.starting_cartons,
                "remaining_cartons": inv.current_remaining_cartons,
                "remaining_packs": inv.current_remaining_packs
            })

    return jsonify({
        "driver_name": driver.full_name,
        "assigned_region": "قطر (ميداني)",
        "financials": {
            "total_sales_cash": total_sales_cash,
            "total_debt_paid": total_debt_paid,
            "total_cash_overall": total_sales_cash + total_debt_paid
        },
        "counts": {
            "total_completed": stats.completed_count or 0,
            "total_pending": pending_count,
            "sales_in_completed": sales_count
        },
        "active_session": {
            "session_id": active_session.id,
            "start_time": active_session.start_time.isoformat() if active_session.start_time else None,
            "inventory": inventory_list
        } if active_session else None
    }), 200

# =========================================
# 6. إضافة محل جديد (بحماية مشددة)
# =========================================
@api.route('/shops', methods=['POST'])
@token_required
def add_new_shop():
    driver_id = getattr(g, 'current_driver_id', None)
    data = request.get_json()
    
    # 1. قراءة البيانات
    name = data.get('name', '').strip() if data.get('name') else ''
    phone = data.get('phone_number', '').strip() if data.get('phone_number') else ''
    address = data.get('address', '').strip() if data.get('address') else ''
    
    # 2. حماية السيرفر: رفض الطلب إذا كانت الحقول الإلزامية فارغة
    if not name:
        return jsonify({"message": "فشل الحفظ: اسم المحل إجباري"}), 400
    if not phone:
        return jsonify({"message": "فشل الحفظ: رقم الهاتف إجباري"}), 400
    if not data.get('latitude') and not data.get('longitude') and not data.get('location_link'):
        return jsonify({"message": "فشل الحفظ: الموقع الجغرافي أو رابط الخريطة إجباري"}), 400

    try:
        new_shop = Shop(
            name=name,
            address=address,
            phone_number=phone,
            contact_person=data.get('contact_person'),
            notes=data.get('notes'),
            location_link=data.get('location_link'),
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            added_by_driver_id=driver_id
            # ملاحظة: zone_id رح نخليها فارغة مؤقتاً لحد ما نبرمج قائمة منسدلة للمناطق في التطبيق
        )
        db.session.add(new_shop)
        db.session.flush()

        new_visit = Visit(
            driver_id=driver_id,
            shop_id=new_shop.id,
            status='Pending',
            visit_timestamp=datetime.now(timezone.utc)
        )
        db.session.add(new_visit)
        db.session.commit()

        return jsonify({"message": "Shop added successfully", "shop": {"id": new_shop.id, "name": new_shop.name}}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Failed to add shop", "error": str(e)}), 500
    
    
# =========================================
# 7. باقي الروابط الأساسية (قائمة الزيارات والمنتجات)
# =========================================
@api.route('/product_variants', methods=['GET'])
@token_required
def get_products():
    variants = ProductVariant.query.filter_by(is_active=True).all()
    return jsonify([{"id": v.id, "variant_name": v.variant_name, "price_per_carton": v.price_per_carton} for v in variants]), 200

@api.route('/driver/<int:driver_id>/visits', methods=['GET'])
@token_required
def get_visits(driver_id):
    visits = Visit.query.filter_by(driver_id=driver_id).order_by(Visit.sequence.asc().nulls_last()).all()
    return jsonify([{
        "visit_id": v.id, "shop_id": v.shop_id, "shop_name": v.shop.name,
        "shop_location_link": v.shop.location_link, "shop_balance": v.shop.current_balance,
        "visit_status": v.status, "visit_sequence": v.sequence
    } for v in visits]), 200

@api.route('/visits/<int:visit_id>', methods=['GET'])
@token_required
def get_visit_details(visit_id):
    visit = db.session.get(Visit, visit_id)
    if not visit: return jsonify({"message": "Visit not found"}), 404
    shop = visit.shop
    return jsonify({
        "visit_id": visit.id, "driver_id": visit.driver_id, "outcome": visit.outcome,
        "product_variant_id": visit.product_variant_id, "quantity_sold": visit.quantity_sold,
        "cash_collected": visit.cash_collected, "debt_paid": visit.debt_paid,
        "notes": visit.notes, "no_sale_reason": visit.no_sale_reason, "status": visit.status,
        "shop": {"latitude": shop.latitude, "longitude": shop.longitude, "location_link": shop.location_link}
    }), 200

@api.route('/driver/<int:driver_id>/sessions/active', methods=['GET'])
@token_required
def get_active_session(driver_id):
    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=date.today(), end_time=None).first()
    if active_session:
        return jsonify({"active_session_found": True, "session_id": active_session.id, "start_time": active_session.start_time.isoformat()}), 200
    return jsonify({"active_session_found": False}), 200