from flask import Blueprint, request, jsonify, g
from datetime import datetime, date, timezone
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import traceback
from sqlalchemy import func
from sqlalchemy.orm import joinedload

# توحيد الاستيرادات وحذف التكرار
from models import db, Driver, Shop, Visit, VisitItem, VisitReturn, WorkSession, ProductVariant, SessionInventory, Zone, Vehicle, DispatchRoute, VehicleLoad, ShortageRequest, ImportLog
from services import calculate_invoice, check_debt_limits, adjust_inventory
from config import Config

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
# 2. بدء جلسة العمل
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
        db.session.commit()

        return jsonify({
            "message": "Session started successfully", 
            "session_id": new_session.id
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
# 3.5 تسجيل وقت الاستراحة
# =========================================
@api.route('/driver/<int:driver_id>/sessions/break', methods=['PUT'])
@token_required
def toggle_break(driver_id):
    if getattr(g, 'current_driver_id', None) != driver_id:
         return jsonify({"message": "Forbidden"}), 403

    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=date.today(), end_time=None).first()
    if not active_session:
        return jsonify({"message": "No active session"}), 404

    data = request.get_json() or {}
    action = data.get('action') 

    try:
        if action == 'start':
            if active_session.break_start_time and not active_session.break_end_time:
                 return jsonify({"message": "الاستراحة بدأت بالفعل"}), 400
            active_session.break_start_time = datetime.now(timezone.utc)
            active_session.break_end_time = None 
            msg = "تم بدء الاستراحة"
        elif action == 'end':
            if not active_session.break_start_time or active_session.break_end_time:
                 return jsonify({"message": "لا يوجد استراحة نشطة لإنهائها"}), 400
            active_session.break_end_time = datetime.now(timezone.utc)
            msg = "تم إنهاء الاستراحة"
        else:
            return jsonify({"message": "إجراء غير صالح"}), 400

        db.session.commit()
        return jsonify({"message": msg}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في تسجيل الاستراحة", "error": str(e)}), 500
    
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
        original_shop_balance = shop.current_balance or 0.0
        new_shop_balance = original_shop_balance

        if debt_paid_input > 0 and debt_paid_input > original_shop_balance:
             return jsonify({"message": f"مرفوض: لا يمكن تحصيل مبلغ ({debt_paid_input}) أكبر من الذمة الحالية للمحل ({original_shop_balance})."}), 400

        visit.visit_timestamp = datetime.now(timezone.utc)
        visit.notes = data.get('notes')
        visit.latitude = data.get('latitude', visit.latitude)
        visit.longitude = data.get('longitude', visit.longitude)
        visit.shop_balance_before = original_shop_balance
        visit.is_emergency = data.get('is_emergency', False)

        if active_session:
            visit.work_session_id = active_session.id

        if outcome == 'Sale':
            cart_items = data.get('cart_items', [])
            returns_data = data.get('returns', []) 
            cash_collected = float(data.get('cash_collected', 0.0))

            total_final_amount = 0.0
            total_base_amount = 0.0
            total_discount = 0.0
            total_tax = 0.0
            total_quantity = 0

            for item in cart_items:
                variant_id = item.get('product_variant_id')
                quantity = int(item.get('quantity', 0))
                sample_quantity = int(item.get('sample_quantity', 0)) 
                
                if (quantity <= 0 and sample_quantity <= 0) or not variant_id:
                    continue
                    
                variant = db.get_or_404(ProductVariant, variant_id)
                invoice = calculate_invoice(quantity, variant.price_per_carton) # price_per_carton is the unit price now
                
                if invoice is None:
                    invoice = {
                        'bonus_units': 0,
                        'final_amount': 0.0,
                        'base_amount': 0.0,
                        'discount_applied': 0.0,
                        'tax_amount': 0.0
                    }
                
                if active_session:
                    net_quantity = -(quantity + invoice['bonus_units'] + sample_quantity)
                    inv_success, inv_msg = adjust_inventory(active_session.id, variant_id, net_quantity)
                    if not inv_success:
                        return jsonify({"message": f"مخزونك لا يكفي من {variant.variant_name}. {inv_msg}"}), 409

                new_visit_item = VisitItem(
                    visit_id=visit.id,
                    product_variant_id=variant_id,
                    quantity=quantity,
                    bonus_quantity=invoice['bonus_units'],
                    sample_quantity=sample_quantity,     
                    price_per_unit_at_sale=variant.price_per_carton,
                    total_price=invoice['final_amount']
                )
                db.session.add(new_visit_item)
               
                total_final_amount += invoice['final_amount']
                total_base_amount += invoice['base_amount']
                total_discount += invoice['discount_applied']
                total_tax += invoice['tax_amount']
                total_quantity += quantity

            for ret in returns_data:
                ret_variant_id = ret.get('product_variant_id')
                ret_quantity = int(ret.get('quantity', 0))
                ret_type = ret.get('return_type')
                ret_reason = ret.get('reason', '')

                if ret_quantity <= 0 or not ret_variant_id:
                    continue
                
                if active_session:
                    # Returns add back to inventory if they are not damaged, but here we just adjust
                    inv_success, inv_msg = adjust_inventory(active_session.id, ret_variant_id, ret_quantity)
                    if not inv_success:
                        return jsonify({"message": f"خطأ في تعديل المخزون للمرتجعات. {inv_msg}"}), 409
                
                new_return = VisitReturn(
                    visit_id=visit.id,
                    product_variant_id=ret_variant_id,
                    quantity=ret_quantity,
                    return_type=ret_type,
                    reason=ret_reason
                )
                db.session.add(new_return)

            new_debt = total_final_amount - cash_collected
            if new_debt > 0:
                is_allowed, msg = check_debt_limits(visit.driver_id, shop.id, new_debt)
                if not is_allowed:
                    return jsonify({"message": msg}), 403

            visit.outcome = 'Sale'
            visit.status = 'Completed'
            visit.quantity_sold = total_quantity
            visit.amount_before_tax_and_discount = total_base_amount
            visit.discount_applied = total_discount
            visit.tax_amount = total_tax
            visit.final_amount_due = total_final_amount
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
            "message": "Visit updated successfully",
            "new_balance": shop.current_balance
        }), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "Error updating visit", "error": str(e)}), 500
    

# =========================================
# 5. جلب بيانات الداشبورد للمندوب
# =========================================
@api.route('/driver/<int:driver_id>/dashboard', methods=['GET'])
@token_required
def dashboard(driver_id):
    driver = db.session.get(Driver, driver_id)
    if not driver: return jsonify({"message": "Not found"}), 404

    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=date.today(), end_time=None).first()
    
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
    
    inventory_list = []
    if active_session:
        inventories = SessionInventory.query.options(
            joinedload(SessionInventory.product_variant)
        ).filter_by(work_session_id=active_session.id).all()
        
        for inv in inventories:
            inventory_list.append({
                "product_name": inv.product_variant.variant_name,
                "starting_quantity": inv.starting_quantity,
                "remaining_quantity": inv.current_remaining_quantity
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
            "is_authorized_to_sell": active_session.is_authorized_to_sell,
            "break_start_time": active_session.break_start_time.isoformat() if active_session.break_start_time else None,
            "break_end_time": active_session.break_end_time.isoformat() if active_session.break_end_time else None,
            "inventory": inventory_list
        } if active_session else None
    }), 200

# =========================================
# 6. إضافة محل جديد
# =========================================
@api.route('/shops', methods=['POST'])
@token_required
def add_new_shop():
    driver_id = getattr(g, 'current_driver_id', None)
    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=date.today(), end_time=None).first()
    if not active_session or not active_session.is_authorized_to_sell:
        return jsonify({"message": "مرفوض: غير مصرح لك بإضافة محلات جديدة قبل تفعيل خط السير من الإدارة."}), 403
        
    data = request.get_json()
    name = data.get('name', '').strip() if data.get('name') else ''
    phone = data.get('phone_number', '').strip() if data.get('phone_number') else ''
    address = data.get('address', '').strip() if data.get('address') else ''
    
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
# 7. الروابط الأساسية (قائمة الزيارات والمنتجات)
# =========================================
@api.route('/product_variants', methods=['GET'])
@token_required
def get_products():
    variants = ProductVariant.query.filter_by(is_active=True).all()
    return jsonify([{
        "id": v.id, 
        "variant_name": v.variant_name, 
        "price_per_carton": v.price_per_carton,
        "packs_per_carton": v.packs_per_carton,
        "price_per_pack": v.price_per_pack,
        "max_samples": v.default_max_samples_per_day 
    } for v in variants]), 200


@api.route('/driver/<int:driver_id>/visits', methods=['GET'])
@token_required
def get_visits(driver_id):
    # 1. جلب الجلسة النشطة حالياً للمندوب
    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=date.today(), end_time=None).first()
    
    # 2. اللوجيك المؤسسي: جلب المحلات المعلقة + المحلات المكتملة في الجلسة الحالية فقط
    if active_session:
        visits = Visit.query.filter(
            (Visit.driver_id == driver_id) & 
            ((Visit.status == 'Pending') | (Visit.work_session_id == active_session.id))
        ).order_by(Visit.sequence.asc().nulls_last()).all()
    else:
        # إذا لا توجد جلسة نشطة، نعرض المعلقات فقط
        visits = Visit.query.filter_by(driver_id=driver_id, status='Pending').order_by(Visit.sequence.asc().nulls_last()).all()

    return jsonify([{
        "visit_id": v.id, 
        "shop_id": v.shop_id, 
        "shop_name": v.shop.name,
        "shop_location_link": v.shop.location_link, 
        "shop_balance": v.shop.current_balance,
        "visit_status": v.status, 
        "visit_sequence": v.sequence,
        "is_emergency": getattr(v, 'is_emergency', False)
    } for v in visits]), 200


@api.route('/visits/<int:visit_id>', methods=['GET'])
@token_required
def get_visit_details(visit_id):
    visit = db.session.get(Visit, visit_id)
    if not visit: return jsonify({"message": "Visit not found"}), 404
    shop = visit.shop
    
    cart_items = []
    for item in visit.items:
        cart_items.append({
            "product_variant_id": item.product_variant_id,
            "variant_name": item.product_variant.variant_name if item.product_variant else "غير معروف",
            "quantity": item.quantity,
            "bonus_quantity": item.bonus_quantity,
            "sample_quantity": item.sample_quantity,
            "total_price": item.total_price
        })

    return jsonify({
        "visit_id": visit.id, 
        "driver_id": visit.driver_id, 
        "outcome": visit.outcome,
        "cart_items": cart_items, 
        "cash_collected": visit.cash_collected, 
        "debt_paid": visit.debt_paid,
        "notes": visit.notes, 
        "no_sale_reason": visit.no_sale_reason, 
        "status": visit.status,
        "shop": {"latitude": shop.latitude, "longitude": shop.longitude, "location_link": shop.location_link}
    }), 200

@api.route('/driver/<int:driver_id>/sessions/active', methods=['GET'])
@token_required
def get_active_session(driver_id):
    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=date.today(), end_time=None).first()
    if active_session:
        return jsonify({"active_session_found": True, "session_id": active_session.id, "start_time": active_session.start_time.isoformat()}), 200
    return jsonify({"active_session_found": False}), 200

# =========================================
# 8. روابط الإدارة (Admin APIs) - لوحة التحكم
# =========================================

# 8.1 إعطاء أو سحب "الضوء الأخضر"  
@api.route('/admin/sessions/<int:session_id>/authorize', methods=['PUT'])
@token_required
def authorize_session(session_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة"}), 403

    session = db.session.get(WorkSession, session_id)
    if not session:
        return jsonify({"message": "الجلسة غير موجودة"}), 404

    data = request.get_json()
    is_authorized = data.get('is_authorized', True)

    try:
        session.is_authorized_to_sell = is_authorized
        db.session.commit()
        return jsonify({"message": "تم تحديث صلاحية البيع بنجاح"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في التحديث", "error": str(e)}), 500

# 8.2 جلب ملخص كل الجلسات النشطة اليوم (لشاشة المدير الرئيسية / غرفة العمليات)
@api.route('/admin/sessions/today', methods=['GET'])
# @token_required
def get_admin_dashboard_data():
    today_date = date.today()
    
    # 1. جلب جميع المناديب الفعالين (باستثناء المدراء لعدم عرضهم بالرادار)
    drivers = Driver.query.filter_by(is_active=True, is_admin=False).all()
    
    drivers_data = []
    
    for driver in drivers:
        # 2. جلب أحدث جلسة للمندوب لليوم الحالي فقط (لمنع التكرار نهائياً)
        session = WorkSession.query.filter(
            WorkSession.driver_id == driver.id,
            func.date(WorkSession.start_time) == today_date
        ).order_by(WorkSession.id.desc()).first()
        
        # 3. إعطاء قيم افتراضية (بحال المندوب نايم بالبيت وما كبس بدء العمل)
        session_id = -driver.id  # رقم وهمي بالسالب عشان React ما يضرب خطأ
        start_time = None
        is_authorized = False
        is_on_break = False
        status = "غير متصل"
        completed_total = 0
        pending_remaining = 0
        cash_from_sales = 0.0
        cash_from_debts = 0.0
        expected_cash_in_hand = 0.0
        inv_list = []
        
        # 4. إذا المندوب عنده جلسة اليوم، بنسحب أرقامها الحقيقية
        if session:
            session_id = session.id
            start_time = session.start_time.isoformat() if session.start_time else None
            is_authorized = session.is_authorized_to_sell
            is_on_break = bool(session.break_start_time and not session.break_end_time)
            
            # حساب الزيارات والمالية بطلب واحد
            stats = db.session.query(
                func.count(Visit.id).label('total_visits'),
                func.sum(Visit.cash_collected).label('total_cash'),
                func.sum(Visit.debt_paid).label('total_debt')
            ).filter(Visit.work_session_id == session.id, Visit.status == 'Completed').first()

            completed_total = stats.total_visits or 0
            cash_from_sales = float(stats.total_cash or 0.0)
            cash_from_debts = float(stats.total_debt or 0.0)
            expected_cash_in_hand = cash_from_sales + cash_from_debts
            
            pending_remaining = Visit.query.filter_by(work_session_id=session.id, status='Pending').count()
            
            # جرد المخزون
            inventories = SessionInventory.query.options(
                joinedload(SessionInventory.product_variant)
            ).filter_by(work_session_id=session.id).all()
            
            for inv in inventories:
                started = inv.starting_quantity
                remaining = inv.current_remaining_quantity
                inv_list.append({
                    "product_id": inv.product_variant_id,
                    "product_name": inv.product_variant.variant_name,
                    "starting_quantity": started,
                    "sold_quantity": started - remaining,
                    "remaining_quantity": remaining
                })
            
            # تحديد الحالة الفعلية للجلسة
            if session.end_time:
                status = "مغلقة بانتظار التسوية"
            elif is_on_break:
                status = "استراحة"
            else:
                status = "في الطريق"
        
        # 5. بناء الهيكل اللي بيقرأه React
        drivers_data.append({
            "session": {
                "session_id": session_id,
                "driver_name": driver.full_name,
                "start_time": start_time,
                "is_authorized_to_sell": is_authorized,
                "is_on_break": is_on_break
            },
            "settlement": {
                "driver_name": driver.full_name,
                "status": status,
                "financials": {
                    "expected_cash_in_hand": expected_cash_in_hand,
                    "cash_from_sales": cash_from_sales,
                    "cash_from_debts": cash_from_debts
                },
                "visits": {
                    "completed_total": completed_total,
                    "successful_sales": completed_total,
                    "pending_remaining": pending_remaining
                },
                "inventory": inv_list
            }
        })
        
    # 6. فرز القائمة (Sorting) لإعطاء الأولوية للنشطين
    def get_status_rank(d):
        s = d['settlement']['status']
        if s == "في الطريق": return 1
        if s == "استراحة": return 2
        if s == "مغلقة بانتظار التسوية": return 3
        return 4 # غير متصل ينزل بآخر القائمة
        
    drivers_data.sort(key=get_status_rank)
    
    return jsonify(drivers_data), 200

# 8.3 تقرير التسوية اليومية وجرد السيارة (للمدير)
@api.route('/admin/sessions/<int:session_id>/settlement_report', methods=['GET'])
@token_required
def get_session_settlement_report(session_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    session = db.session.get(WorkSession, session_id)
    if not session:
        return jsonify({"message": "الجلسة غير موجودة"}), 404

    stats = db.session.query(
        func.count(Visit.id).label('total_visits'),
        func.sum(Visit.cash_collected).label('total_cash'),
        func.sum(Visit.debt_paid).label('total_debt')
    ).filter(Visit.work_session_id == session_id, Visit.status == 'Completed').first()

    sales_count = db.session.query(func.count(Visit.id)).filter(
        Visit.work_session_id == session_id, Visit.status == 'Completed', Visit.outcome == 'Sale'
    ).scalar() or 0

    pending_count = Visit.query.filter_by(driver_id=session.driver_id, status='Pending').count()

    inventories = SessionInventory.query.options(
        joinedload(SessionInventory.product_variant)
    ).filter_by(work_session_id=session.id).all()
    
    inv_list = []
    for inv in inventories:
        started = inv.starting_quantity
        remaining = inv.current_remaining_quantity
        inv_list.append({
            "product_id": inv.product_variant_id,
            "product_name": inv.product_variant.variant_name,
            "starting_quantity": started,
            "sold_quantity": started - remaining,
            "remaining_quantity": remaining
        })

    return jsonify({
        "driver_name": session.driver.full_name,
        "session_date": session.session_date.isoformat(),
        "status": "مغلقة بانتظار التسوية" if session.end_time else "نشطة الآن",
        "financials": {
            "expected_cash_in_hand": float(stats.total_cash or 0.0) + float(stats.total_debt or 0.0),
            "cash_from_sales": float(stats.total_cash or 0.0),
            "cash_from_debts": float(stats.total_debt or 0.0)
        },
        "visits": {
            "completed_total": stats.total_visits or 0,
            "successful_sales": sales_count,
            "pending_remaining": pending_count
        },
        "inventory": inv_list
    }), 200

# 8.4 اعتماد التسوية اليومية لجلسة المندوب
@api.route('/admin/sessions/<int:session_id>/settle', methods=['PUT'])
@token_required
def settle_session(session_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    session = db.session.get(WorkSession, session_id)
    if not session:
        return jsonify({"message": "الجلسة غير موجودة"}), 404

    if session.is_settled:
        return jsonify({"message": "تم اعتماد تسوية هذه الجلسة مسبقاً ولا يمكن التعديل عليها."}), 400

    if not session.end_time:
        return jsonify({"message": "مرفوض: لا يمكن تسوية الجلسة لأن المندوب لم يقم بإنهاء العمل من تطبيقه."}), 400

    try:
        session.is_settled = True
        db.session.commit()
        return jsonify({"message": "تم اعتماد التسوية وإغلاق العهدة بنجاح", "is_settled": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في اعتماد التسوية", "error": str(e)}), 500

# =========================================
# 9. لوحة التحكم (Dispatch Board APIs)
# =========================================

@api.route('/dispatch/init', methods=['GET'])
@token_required
def dispatch_init():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    zones = Zone.query.filter_by(is_active=True).all()
    drivers = Driver.query.filter_by(is_active=True, is_admin=False).all()
    vehicles = Vehicle.query.filter_by(is_active=True).all()
    products = ProductVariant.query.filter_by(is_active=True).all()

    # +++ الحل السحري لمشكلة N+1 (استعلام واحد يجلب عدد المحلات لكل المناطق) +++
    shop_counts = db.session.query(
        Shop.zone_id, func.count(Shop.id)
    ).filter(Shop.is_archived == False, Shop.is_active == True).group_by(Shop.zone_id).all()
    
    # تحويل النتيجة لقاموس (Dictionary) لسرعة البحث
    shop_count_map = {zone_id: count for zone_id, count in shop_counts if zone_id}

    today = date.today()
    zones_data = []
    for z in zones:
        shops_count = Shop.query.filter_by(zone_id=z.id, is_archived=False).count()
        
        # +++ تحديد حالة الجدولة للترتيب واللون الأحمر +++
        schedule_status = "null"
        if z.start_date:
            if z.start_date < today: schedule_status = "overdue"
            elif z.start_date == today: schedule_status = "today"
            else: schedule_status = "upcoming"

        zones_data.append({
            "id": str(z.id), 
            "name": z.name,
            "visitDay": z.visit_day or "غير محدد",
            "startDate": z.start_date.isoformat() if z.start_date else "",
            "frequency": z.schedule_frequency or "أسبوعي",
            "scheduleStatus": schedule_status,
            "shopsCount": shops_count
        })

    return jsonify({
        "zones": zones_data,
        "drivers": [{"id": str(d.id), "name": d.full_name} for d in drivers],
        "vehicles": [{"id": str(v.id), "label": f"{v.vehicle_type} - {v.plate_number}"} for v in vehicles],
        "products": [{"id": str(p.id), "name": p.variant_name} for p in products]
    }), 200

# =========================================
# إطلاق خط سير جديد وحفظ الحمولة
# =========================================
@api.route('/dispatch/route', methods=['POST'])
@token_required
def dispatch_route():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض"}), 403

    data = request.get_json()
    zone_id = data.get('zone_id')
    driver_id = data.get('driver_id')
    vehicle_id = data.get('vehicle_id')
    inventory = data.get('inventory', {}) # +++ استلام جرد الحمولة +++

    if not all([zone_id, driver_id, vehicle_id]):
        return jsonify({"message": "يرجى توفير المنطقة، المندوب، والسيارة."}), 400

    if DispatchRoute.query.filter_by(status='active', zone_id=zone_id).first():
        return jsonify({"message": "⚠️ المنطقة المحددة قيد العمل أو مؤجلة."}), 409
    if DispatchRoute.query.filter_by(status='active', driver_id=driver_id).first():
        return jsonify({"message": "⚠️ المندوب المختار مشغول بخط سير آخر."}), 409
    if DispatchRoute.query.filter_by(status='active', vehicle_id=vehicle_id).first():
        return jsonify({"message": "⚠️ السيارة المحددة مستخدمة حالياً."}), 409

    try:
        new_route = DispatchRoute(zone_id=zone_id, driver_id=driver_id, vehicle_id=vehicle_id, status='active')
        db.session.add(new_route)

        # +++ مسح الحمولة القديمة للسيارة وإضافة الحمولة الجديدة +++
        VehicleLoad.query.filter_by(vehicle_id=vehicle_id).delete()
        for prod_id, qty in inventory.items():
            if int(qty) > 0:
                db.session.add(VehicleLoad(vehicle_id=vehicle_id, product_variant_id=int(prod_id), quantity=int(qty)))

        db.session.commit()
        return jsonify({"message": "تم إطلاق خط السير بنجاح"}), 201
    except Exception as e:
        db.session.rollback()
        import traceback; traceback.print_exc()
        return jsonify({"message": "خطأ في إطلاق خط السير", "error": str(e)}), 500


@api.route('/dispatch/inventory/<int:vehicle_id>', methods=['GET'])
@token_required
def get_vehicle_inventory(vehicle_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    # 1. جلب الحمولة الأساسية
    loads = VehicleLoad.query.filter_by(vehicle_id=vehicle_id).all()
    inventory = {l.product_variant_id: l.quantity for l in loads}

    # 2. طرح المبيعات المكتملة اليوم
    today = date.today()
    routes = DispatchRoute.query.filter(
        DispatchRoute.vehicle_id == vehicle_id,
        DispatchRoute.dispatch_date == today
    ).all()
    
    session_ids = [r.work_session_id for r in routes if r.work_session_id]
    
    if session_ids:
        sales = db.session.query(
            VisitItem.product_variant_id,
            func.sum(VisitItem.quantity + VisitItem.bonus_quantity + VisitItem.sample_quantity).label('total_out')
        ).join(Visit).filter(
            Visit.work_session_id.in_(session_ids),
            Visit.status == 'Completed'
        ).group_by(VisitItem.product_variant_id).all()

        for s in sales:
            if s.product_variant_id in inventory:
                inventory[s.product_variant_id] -= int(s.total_out)
            else:
                inventory[s.product_variant_id] = -int(s.total_out)

    # 3. إرجاع النتائج
    variants = ProductVariant.query.filter(ProductVariant.id.in_(inventory.keys())).all()
    result = []
    for v in variants:
        result.append({
            "product_id": str(v.id),
            "product_name": v.variant_name,
            "current_quantity": inventory.get(v.id, 0)
        })

    return jsonify(result), 200

# =========================================
# 10. استرجاع وتحديث المحلات (شاشة التوزيع)
# =========================================

# جلب جميع المحلات لعرضها في الشاشة
@api.route('/dispatch/shops', methods=['GET'])
@token_required
def get_dispatch_shops():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة."}), 403
        
    shops = Shop.query.all()
    return jsonify([{
        "id": str(s.id),
        "name": s.name,
        "owner": s.contact_person or "",
        "phone": s.phone_number or "",
        "mapLink": s.location_link or "",
        "zoneId": str(s.zone_id) if s.zone_id else "",
        "initialDebt": s.current_balance,
        "maxDebtLimit": s.max_debt_limit,
        "sequence": getattr(s, 'sequence', 0),
        "archived": getattr(s, 'is_archived', False)
    } for s in shops]), 200

# حفظ التعديلات الجماعية للمحلات (نقل لمنطقة أخرى، أرشفة، إعادة ترتيب، استعادة)
@api.route('/dispatch/shops/bulk_update', methods=['PUT'])
@token_required
def bulk_update_shops():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة."}), 403
        
    data = request.get_json()
    try:
        for s_data in data:
            shop = db.session.get(Shop, str(s_data.get('id')).replace('s', ''))
            if shop:
                # الحماية الذكية: منع استعادة المحل إذا كانت منطقته مؤرشفة أو محذوفة
                is_restoring = 'archived' in s_data and s_data['archived'] == False
                if is_restoring:
                    zone_to_check = s_data.get('zoneId', shop.zone_id)
                    zone_exists = db.session.get(Zone, zone_to_check)
                    if not zone_exists or not getattr(zone_exists, 'is_active', True):
                        return jsonify({"message": f"لا يمكن استعادة المحل '{shop.name}' لأن منطقته مؤرشفة. يرجى نقله لمنطقة نشطة أولاً."}), 400

                if 'sequence' in s_data: shop.sequence = s_data['sequence']
                if 'archived' in s_data: shop.is_archived = s_data['archived']
                if 'zoneId' in s_data: shop.zone_id = s_data['zoneId']
        db.session.commit()
        return jsonify({"message": "تم تحديث المحلات بنجاح"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في التحديث", "error": str(e)}), 500

# إضافة محل جديد من لوحة التحكم (مع منع التكرار الذكي)
@api.route('/dispatch/shops', methods=['POST'])
@token_required
def admin_add_shop():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة."}), 403

    data = request.get_json()
    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    map_link = data.get('mapLink', '').strip()
    zone_id = data.get('zoneId')
    lat = data.get('latitude')
    lng = data.get('longitude')

    # 1. الفحص الذكي المركب (Duplicate Detection)
    duplicate_shop = None

    if phone:
        duplicate_shop = Shop.query.filter(Shop.phone_number == phone).first()

    # فحص التطابق بالاسم ورابط الموقع حتى لو اختلف الرقم
    if not duplicate_shop and name and map_link:
        duplicate_shop = Shop.query.filter(Shop.name == name, Shop.location_link == map_link).first()

    # فحص الإحداثيات إن وجدت
    if not duplicate_shop and lat and lng:
        try:
            lat_f = float(lat)
            lng_f = float(lng)
            duplicate_shop = Shop.query.filter(
                Shop.name == name,
                Shop.latitude.isnot(None), Shop.longitude.isnot(None)
            ).filter(
                func.abs(func.cast(Shop.latitude, db.Float) - lat_f) < 0.0001,
                func.abs(func.cast(Shop.longitude, db.Float) - lng_f) < 0.0001
            ).first()
        except ValueError:
            pass

    force_save = data.get('force_save', False)

    if duplicate_shop and not force_save:
        zone_name = duplicate_shop.zone.name if duplicate_shop.zone else "بدون منطقة"
        is_arch_msg = " (مؤرشف)" if getattr(duplicate_shop, 'is_archived', False) else ""
        return jsonify({
            "message": f"تنبيه: يوجد محل مسجل مسبقاً بمعلومات مطابقة.",
            "is_duplicate": True,
            "existing_shop": {
                "id": str(duplicate_shop.id),
                "name": duplicate_shop.name,
                "owner": duplicate_shop.contact_person or "غير مسجل",
                "phone": duplicate_shop.phone_number,
                "mapLink": duplicate_shop.location_link,
                "zone_name": zone_name + is_arch_msg
            }
        }), 409

    try:
        new_shop = Shop(
            name=name,
            contact_person=data.get('owner', ''),
            phone_number=phone,
            location_link=map_link,
            latitude=lat,
            longitude=lng,
            zone_id=zone_id,
            current_balance=float(data.get('initialDebt', 0.0)),
            max_debt_limit=float(data.get('maxDebtLimit', 0.0)),
            added_by_driver_id=admin.id,
            sequence=int(data.get('sequence', 999))
        )
        db.session.add(new_shop)
        db.session.commit()
        return jsonify({"message": "تم إضافة المحل بنجاح", "shop_id": str(new_shop.id)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في إضافة المحل", "error": str(e)}), 500


# =========================================
# 11. استرجاع وتحديث خطوط السير النشطة والمؤجلة
# =========================================
@api.route('/dispatch/active_routes', methods=['GET'])
@token_required
def get_active_routes():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة."}), 403
        
    routes = DispatchRoute.query.filter(DispatchRoute.status.in_(['active', 'waiting', 'postponed'])).all()
    
    # +++ تدمير N+1 باستخدام القواميس (Dictionaries) لحماية السيرفر +++
    zone_ids = [r.zone_id for r in routes]
    driver_ids = [r.driver_id for r in routes if r.driver_id]
    
    zones_map = {z.id: z.name for z in Zone.query.filter(Zone.id.in_(zone_ids)).all()} if zone_ids else {}
    drivers_map = {d.id: d.full_name for d in Driver.query.filter(Driver.id.in_(driver_ids)).all()} if driver_ids else {}

    session_ids = [r.work_session_id for r in routes if r.work_session_id]
    pending_visits_map = {}
    if session_ids:
        pending_counts = db.session.query(
            Visit.work_session_id, func.count(Visit.id)
        ).filter(Visit.work_session_id.in_(session_ids), Visit.status == 'Pending').group_by(Visit.work_session_id).all()
        pending_visits_map = {ws_id: count for ws_id, count in pending_counts}
    
    zones_without_session = [r.zone_id for r in routes if not r.work_session_id]
    zone_shops_map = {}
    if zones_without_session:
        shop_counts = db.session.query(
            Shop.zone_id, func.count(Shop.id)
        ).filter(Shop.zone_id.in_(zones_without_session), Shop.is_active == True, Shop.is_archived == False).group_by(Shop.zone_id).all()
        zone_shops_map = {z_id: count for z_id, count in shop_counts}

    res = []
    for r in routes:
        shops_remaining = pending_visits_map.get(r.work_session_id, 0) if r.work_session_id else zone_shops_map.get(r.zone_id, 0)
            
        res.append({
            "id": str(r.id),
            "zoneId": str(r.zone_id),
            "zoneName": zones_map.get(r.zone_id, "منطقة محذوفة"),
            "driverId": str(r.driver_id),
            "driverName": drivers_map.get(r.driver_id, "مندوب محذوف"),
            "vehicleId": str(r.vehicle_id),
            "shopsRemaining": shops_remaining,
            "status": r.status
        })
    return jsonify(res), 200

# =========================================
# تغيير حالة خط السير (ومتابعة الحمولة والتحويل)
# =========================================
@api.route('/dispatch/route/<int:route_id>/status', methods=['PUT'])
@token_required
def update_route_status(route_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض"}), 403
        
    route = db.session.get(DispatchRoute, route_id)
    if not route:
        return jsonify({"message": "خط السير غير موجود"}), 404
        
    data = request.get_json()
    new_status = data.get('status')
    new_driver_id = data.get('driverId')
    new_vehicle_id = data.get('vehicleId') # +++ استلام السيارة الجديدة +++
    inventory = data.get('inventory')      # +++ استلام الجرد المُحدث +++
    
    try:
        if new_status: 
            route.status = new_status
            # +++ الجدولة التلقائية عند الإغلاق +++
            if new_status == 'closed':
                zone = db.session.get(Zone, route.zone_id)
                if zone and zone.start_date and zone.schedule_frequency:
                    from datetime import timedelta
                    import re
                    
                    freq = str(zone.schedule_frequency)
                    days_to_add = 7 # افتراضي
                    if freq == 'أسبوعي': days_to_add = 7
                    elif freq == 'نصف شهري': days_to_add = 14
                    else:
                        # استخراج أي رقم من النص (مثلاً: "مخصص (20 يوم)")
                        numbers = re.findall(r'\d+', freq)
                        if numbers:
                            days_to_add = int(numbers[0])
                            
                    zone.start_date = zone.start_date + timedelta(days=days_to_add)

        if new_driver_id: route.driver_id = new_driver_id
        if new_vehicle_id: route.vehicle_id = new_vehicle_id
        
        if inventory is not None and route.vehicle_id:
            VehicleLoad.query.filter_by(vehicle_id=route.vehicle_id).delete()
            for prod_id, qty in inventory.items():
                if int(qty) > 0:
                    db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=int(prod_id), quantity=int(qty)))
            
        db.session.commit()
        return jsonify({"message": "تم تحديث خط السير بنجاح"}), 200
        
    except Exception as e:
        db.session.rollback()
        import traceback; traceback.print_exc()
        return jsonify({"message": "خطأ في التحديث", "error": str(e)}), 500

# =========================================
# 12. إدارة المناطق (شاشة التوزيع)
# =========================================
# إضافة منطقة جديدة
@api.route('/dispatch/zones', methods=['POST'])
@token_required
def add_zone():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة"}), 403

    data = request.get_json()
    name = data.get('name', '').strip()

    if not name:
        return jsonify({"message": "اسم المنطقة مطلوب"}), 400

    existing_zone = Zone.query.filter_by(name=name).first()
    if existing_zone:
        if not getattr(existing_zone, 'is_active', True):
            return jsonify({"message": "هذه المنطقة موجودة مسبقاً في (أرشيف المناطق). يرجى استعادتها بدلاً من إنشائها من جديد."}), 409
        return jsonify({"message": "المنطقة موجودة ونشطة مسبقاً"}), 409

    try:
        # +++ المعالجة الذكية لحقل المحافظة الإجباري +++
        from models import Governorate, Country
        gov = Governorate.query.first()
        if not gov:
            country = Country.query.first()
            if not country:
                country = Country(name="الأردن")
                db.session.add(country)
                db.session.flush()
            gov = Governorate(name="العاصمة", country_id=country.id)
            db.session.add(gov)
            db.session.flush()

        new_zone = Zone(name=name, governorate_id=gov.id)
        db.session.add(new_zone)
        db.session.commit()
        return jsonify({"message": "تم إضافة المنطقة بنجاح", "zone_id": new_zone.id}), 201
    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc() # طباعة الخطأ في التيرمنال
        return jsonify({"message": "خطأ في إضافة المنطقة", "error": str(e)}), 500

# تعديل أو حذف منطقة
@api.route('/dispatch/zones/<int:zone_id>', methods=['PUT', 'DELETE'])
@token_required
def manage_zone(zone_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض"}), 403

    zone = db.session.get(Zone, zone_id)
    if not zone:
        return jsonify({"message": "المنطقة غير موجودة"}), 404

    if request.method == 'DELETE':
        # التحقق من عدم وجود محلات نشطة قبل الحذف
        active_shops = Shop.query.filter_by(zone_id=zone_id, is_archived=False).count()
        if active_shops > 0:
            return jsonify({"message": "لا يمكن حذف المنطقة، يوجد بها محلات نشطة. يرجى نقلها أو أرشفتها أولاً."}), 400

        try:
            # +++ أرشفة المنطقة بدل حذفها نهائياً لتجنب كسر الفواتير السابقة +++
            zone.is_active = False
            db.session.commit()
            return jsonify({"message": "تم أرشفة المنطقة بنجاح"}), 200
        except Exception as e:
            db.session.rollback()
            import traceback; traceback.print_exc()
            return jsonify({"message": f"خطأ في أرشفة المنطقة: {str(e)}"}), 500

    if request.method == 'PUT':
        data = request.get_json()
        new_name = data.get('name')
        frequency = data.get('frequency')
        visit_day = data.get('visitDay')
        start_date = data.get('startDate')
        
        try:
            if new_name:
                existing = Zone.query.filter(Zone.name == new_name.strip(), Zone.id != zone_id).first()
                if existing:
                    return jsonify({"message": "يوجد منطقة أخرى بنفس الاسم"}), 409
                zone.name = new_name.strip()
                
            # حفظ إعدادات الجدولة في قاعدة البيانات الفعلية
            if frequency:
                zone.schedule_frequency = frequency  # تم التصحيح لاسم العمود الصحيح
            if visit_day:
                zone.visit_day = visit_day
            if start_date:
                from datetime import datetime
                zone.start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                
            db.session.commit()
            return jsonify({"message": "تم التعديل بنجاح"}), 200
        except Exception as e:
            db.session.rollback()
            import traceback
            traceback.print_exc() # هذا السطر سيفضح الخطأ في التيرمنال
            return jsonify({"message": "خطأ في التعديل", "error": str(e)}), 500

# جلب وإعادة المناطق المؤرشفة
@api.route('/dispatch/zones/archived', methods=['GET'])
@token_required
def get_archived_zones():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض"}), 403

    zones = Zone.query.filter_by(is_active=False).all()
    return jsonify([{"id": str(z.id), "name": z.name} for z in zones]), 200

@api.route('/dispatch/zones/<int:zone_id>/restore', methods=['PUT'])
@token_required
def restore_zone(zone_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض"}), 403

    zone = db.session.get(Zone, zone_id)
    if zone:
        zone.is_active = True
        db.session.commit()
        return jsonify({"message": "تم استعادة المنطقة"}), 200
    return jsonify({"message": "المنطقة غير موجودة"}), 404

# تعديل بيانات محل موجود (من لوحة التحكم)
@api.route('/dispatch/shops/<shop_id>', methods=['PUT'])
@token_required
def edit_shop_details(shop_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض"}), 403
        
    # تنظيف الـ ID لو الواجهة بعتت حرف s قبله
    clean_id = str(shop_id).replace('s', '')
    shop = db.session.get(Shop, clean_id)
    
    if not shop:
        return jsonify({"message": "المحل غير موجود"}), 404
        
    data = request.get_json()
    new_phone = data.get('phone', '').strip()
    
    # فحص تكرار رقم الهاتف لمحل آخر
    if new_phone and new_phone != shop.phone_number:
        if Shop.query.filter_by(phone_number=new_phone).first():
            return jsonify({"message": "رقم الهاتف مستخدم لمحل آخر"}), 409
            
    try:
        shop.name = data.get('name', shop.name)
        shop.contact_person = data.get('owner', shop.contact_person)
        shop.phone_number = new_phone
        shop.location_link = data.get('mapLink', shop.location_link)
        shop.zone_id = data.get('zoneId', shop.zone_id)
        shop.current_balance = float(data.get('initialDebt', shop.current_balance))
        shop.max_debt_limit = float(data.get('maxDebtLimit', shop.max_debt_limit))
        
        db.session.commit()
        return jsonify({"message": "تم التعديل بنجاح"}), 200
    except Exception as e:
        db.session.rollback()
        print("🚨 خطأ في تعديل المحل:", str(e)) # رح تظهر بالتيرمنال
        return jsonify({"message": "خطأ في التعديل", "error": str(e)}), 500

# =========================================
# 13. الطلبات والنواقص (Shortages)
# =========================================
@api.route('/dispatch/shortages', methods=['GET', 'POST'])
@token_required
def manage_shortages():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض"}), 403

    if request.method == 'GET':
        shortages = ShortageRequest.query.filter_by(status='pending').all()
        result = []
        for s in shortages:
            result.append({
                "id": str(s.id),
                "zoneId": str(s.zone_id),
                "zoneName": s.zone.name if s.zone else "",
                "shopId": str(s.shop_id),
                "shopName": s.shop.name if s.shop else "",
                "driverId": str(s.driver_id) if s.driver_id else "",
                "driverName": s.driver.full_name if s.driver else "",
                "productName": s.product_name,
                "quantity": s.quantity,
                "status": s.status,
                "waitTime": s.wait_time
            })
        return jsonify(result), 200

    if request.method == 'POST':
        data = request.get_json() # Array of shortages
        try:
            for item in data:
                new_shortage = ShortageRequest(
                    zone_id=item.get('zoneId'),
                    shop_id=item.get('shopId'),
                    driver_id=item.get('driverId') or None,
                    product_name=item.get('productName'),
                    quantity=item.get('quantity', 1)
                )
                db.session.add(new_shortage)
            db.session.commit()
            return jsonify({"message": "تم تسجيل الطلبات بنجاح"}), 201
        except Exception as e:
            db.session.rollback()
            import traceback
            traceback.print_exc()
            return jsonify({"message": "خطأ في حفظ الطلبات", "error": str(e)}), 500

# =========================================
# 14. الاستيراد الآمن للمحلات بالجملة (Bulk Import)
# =========================================
@api.route('/dispatch/shops/bulk_import', methods=['POST'])
@token_required
def bulk_import_shops():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة."}), 403

    data = request.get_json()
    zone_id = data.get('zoneId')
    shops_list = data.get('shops', [])
    file_name = data.get('fileName', 'استيراد غير معروف')

    if not zone_id or not shops_list:
        return jsonify({"message": "المنطقة وقائمة المحلات مطلوبة"}), 400

    try:
        import_log = ImportLog(admin_id=admin.id, zone_id=zone_id, file_name=file_name, total_records=len(shops_list), status='Processing')
        db.session.add(import_log)
        db.session.flush()

        # +++ سحب كل المحلات النشطة للذاكرة مرة واحدة لمنع الضغط على قاعدة البيانات +++
        all_existing_shops = Shop.query.filter_by(is_archived=False).all()
        
        new_shops = []
        ignored_count = 0

        for s in shops_list:
            s_name = s.get('name', '').strip().lower()
            s_phone = str(s.get('phone', '')).strip()
            s_link = s.get('mapLink', '').strip().lower()

            # +++ تطبيق قاعدة التكرار الذكية (2 من 3) +++
            is_duplicate = False
            for ext in all_existing_shops:
                ext_name = (ext.name or '').strip().lower()
                ext_phone = str(ext.phone_number or '').strip()
                ext_link = (ext.location_link or '').strip().lower()
                
                matches = 0
                if s_name and ext_name and s_name == ext_name: matches += 1
                if s_phone and ext_phone and s_phone == ext_phone: matches += 1
                if s_link and ext_link and s_link == ext_link: matches += 1
                
                if matches >= 2:
                    is_duplicate = True
                    break
            
            if is_duplicate:
                ignored_count += 1
                continue # تجاهل المحل وانتقل للي بعده

            new_shop = Shop(
                name=s.get('name', '').strip(),
                contact_person=s.get('owner', '').strip(),
                phone_number=s_phone,
                location_link=s.get('mapLink', '').strip(),
                zone_id=zone_id,
                current_balance=float(s.get('initialDebt', 0.0) or 0.0),
                added_by_driver_id=admin.id,
                sequence=int(s.get('sequence', 999))
            )
            new_shops.append(new_shop)
            # إضافة المحل الجديد للذاكرة فوراً لمنع التكرار داخل نفس الملف
            all_existing_shops.append(new_shop)

        db.session.bulk_save_objects(new_shops)
        
        import_log.success_count = len(new_shops)
        import_log.status = 'Success'
        db.session.commit()
        
        msg = f"تم رفع {len(new_shops)} محل بنجاح."
        if ignored_count > 0: msg += f" وتم تجاهل {ignored_count} محل لأنها موجودة مسبقاً."
        
        return jsonify({"message": msg, "log_id": import_log.id}), 201

    except Exception as e:
        # +++ الحماية القصوى: تراجع عن كل شيء في حال فشل أي سجل +++
        db.session.rollback()
        import traceback; traceback.print_exc()
        
        # محاولة تسجيل الفشل في سجل التدقيق بشكل منفصل
        try:
            failed_log = ImportLog(admin_id=admin.id, zone_id=zone_id, file_name=file_name, total_records=len(shops_list), status='Failed')
            db.session.add(failed_log)
            db.session.commit()
        except:
            pass # تجاهل إذا فشل السجل أيضاً

        return jsonify({"message": "فشل في رفع البيانات، تم إلغاء العملية بالكامل لحماية قاعدة البيانات.", "error": str(e)}), 500