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
# 2. بدء جلسة العمل (عداد وقت فقط - بدون لمس المخزون)
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
    action = data.get('action') # يجب أن يرسل التطبيق إما 'start' أو 'end'

    try:
        if action == 'start':
            if active_session.break_start_time and not active_session.break_end_time:
                 return jsonify({"message": "الاستراحة بدأت بالفعل"}), 400
            active_session.break_start_time = datetime.now(timezone.utc)
            active_session.break_end_time = None # تصفير الانتهاء في حال أخذ استراحة ثانية
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
        
        # --- قراءة القيم القديمة ---
        original_shop_balance = shop.current_balance or 0.0
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
        visit.is_emergency = data.get('is_emergency', False) # +++ تسجيل الطوارئ +++

        if active_session:
            visit.work_session_id = active_session.id

        if outcome == 'Sale':
            cart_items = data.get('cart_items', [])
            returns_data = data.get('returns', []) # +++ استقبال التوالف +++
            cash_collected = float(data.get('cash_collected', 0.0))

            total_final_amount = 0.0
            total_base_amount = 0.0
            total_discount = 0.0
            total_tax = 0.0
            total_quantity_cartons = 0

            from models import VisitItem, VisitReturn # استيراد الجداول الجديدة

            # 1. معالجة المبيعات والعينات
            for item in cart_items:
                variant_id = item.get('product_variant_id')
                quantity_cartons = int(item.get('quantity', 0))
                quantity_packs = int(item.get('packs', 0))
                sample_cartons = int(item.get('sample_cartons', 0)) # +++ العينات +++
                sample_packs = int(item.get('sample_packs', 0))     # +++ العينات +++
                
                if (quantity_cartons <= 0 and quantity_packs <= 0 and sample_cartons <= 0 and sample_packs <= 0) or not variant_id:
                    continue
                    
                variant = db.get_or_404(ProductVariant, variant_id)
                invoice = calculate_invoice(quantity_cartons, variant.price_per_carton)
                
                # خصم (المبيعات + البونص + العينات) من جرد السيارة
                if active_session:
                    net_cartons = -(quantity_cartons + invoice['bonus_cartons'] + sample_cartons)
                    net_packs = -(quantity_packs + invoice['bonus_packs'] + sample_packs)
                    inv_success, inv_msg = adjust_inventory(active_session.id, variant_id, net_cartons, net_packs)
                    if not inv_success:
                        return jsonify({"message": f"مخزونك لا يكفي من {variant.variant_name}. {inv_msg}"}), 409

                new_visit_item = VisitItem(
                    visit_id=visit.id,
                    product_variant_id=variant_id,
                    quantity_cartons=quantity_cartons,
                    quantity_packs=quantity_packs,
                    bonus_cartons=invoice['bonus_cartons'],
                    bonus_packs=invoice['bonus_packs'],
                    sample_cartons=sample_cartons, # +++ حفظ العينات +++
                    sample_packs=sample_packs,     # +++ حفظ العينات +++
                    price_per_carton_at_sale=variant.price_per_carton,
                    price_per_pack_at_sale=variant.price_per_pack,
                    total_price=invoice['final_amount']
                )
                db.session.add(new_visit_item)
                
                total_final_amount += invoice['final_amount']
                total_base_amount += invoice['base_amount']
                total_discount += invoice['discount_applied']
                total_tax += invoice['tax_amount']
                total_quantity_cartons += quantity_cartons

            # 2. معالجة التوالف (تبديل التالف بجديد)
            for ret in returns_data:
                ret_variant_id = ret.get('product_variant_id')
                ret_cartons = int(ret.get('cartons', 0))
                ret_packs = int(ret.get('packs', 0))
                ret_type = ret.get('return_type')
                ret_reason = ret.get('reason', '')

                if (ret_cartons <= 0 and ret_packs <= 0) or not ret_variant_id:
                    continue
                
                # خصم (البضاعة السليمة اللي عطيناها للمحل بدل التالف) من جرد السيارة
                if active_session:
                    inv_success, inv_msg = adjust_inventory(active_session.id, ret_variant_id, -ret_cartons, -ret_packs)
                    if not inv_success:
                        return jsonify({"message": f"مخزونك لا يكفي لتبديل التوالف. {inv_msg}"}), 409
                
                new_return = VisitReturn(
                    visit_id=visit.id,
                    product_variant_id=ret_variant_id,
                    quantity_cartons=ret_cartons,
                    quantity_packs=ret_packs,
                    return_type=ret_type,
                    reason=ret_reason
                )
                db.session.add(new_return)

            # فحص سقف الذمم
            new_debt = total_final_amount - cash_collected
            if new_debt > 0:
                is_allowed, msg = check_debt_limits(visit.driver_id, shop.id, new_debt)
                if not is_allowed:
                    return jsonify({"message": msg}), 403

            # تحديث معلومات الزيارة الرئيسية
            visit.outcome = 'Sale'
            visit.status = 'Completed'
            visit.quantity_sold = total_quantity_cartons
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
        import traceback
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
            # +++ إضافة المتغيرات الجديدة للرد +++
            "is_authorized_to_sell": active_session.is_authorized_to_sell,
            "break_start_time": active_session.break_start_time.isoformat() if active_session.break_start_time else None,
            "break_end_time": active_session.break_end_time.isoformat() if active_session.break_end_time else None,
            # +++++++++++++++++++++++++++++++++
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
    # +++ الحماية المطلقة: التحقق من الجلسة والضوء الأخضر +++
    active_session = WorkSession.query.filter_by(driver_id=driver_id, session_date=date.today(), end_time=None).first()
    if not active_session or not active_session.is_authorized_to_sell:
        return jsonify({"message": "مرفوض: غير مصرح لك بإضافة محلات جديدة قبل تفعيل خط السير من الإدارة."}), 403
    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++
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
    return jsonify([{
        "id": v.id, 
        "variant_name": v.variant_name, 
        "price_per_carton": v.price_per_carton,
        "packs_per_carton": v.packs_per_carton,
        "price_per_pack": v.price_per_pack,
        "max_samples": v.default_max_samples_per_day # +++ إرسال سقف العينات للتطبيق +++
    } for v in variants]), 200

@api.route('/driver/<int:driver_id>/visits', methods=['GET'])
@token_required
def get_visits(driver_id):
    visits = Visit.query.filter_by(driver_id=driver_id).order_by(Visit.sequence.asc().nulls_last()).all()
    return jsonify([{
        "visit_id": v.id, 
        "shop_id": v.shop_id, 
        "shop_name": v.shop.name,
        "shop_location_link": v.shop.location_link, 
        "shop_balance": v.shop.current_balance,
        "visit_status": v.status, 
        "visit_sequence": v.sequence,
        "is_emergency": getattr(v, 'is_emergency', False) # +++ إرسال حالة الطوارئ للتطبيق +++
    } for v in visits]), 200

# =========================================
# 7.5 جلب تفاصيل زيارة معينة (مع السلة الكاملة)
# =========================================
@api.route('/visits/<int:visit_id>', methods=['GET'])
@token_required
def get_visit_details(visit_id):
    visit = db.session.get(Visit, visit_id)
    if not visit: return jsonify({"message": "Visit not found"}), 404
    shop = visit.shop
    
    # +++ تجهيز سلة المشتريات الجديدة +++
    cart_items = []
    for item in visit.items:
        cart_items.append({
            "product_variant_id": item.product_variant_id,
            "variant_name": item.product_variant.variant_name if item.product_variant else "غير معروف",
            "quantity_cartons": item.quantity_cartons,
            "quantity_packs": item.quantity_packs,
            "bonus_cartons": item.bonus_cartons,
            "bonus_packs": item.bonus_packs,
            "total_price": item.total_price
        })

    return jsonify({
        "visit_id": visit.id, 
        "driver_id": visit.driver_id, 
        "outcome": visit.outcome,
        "cart_items": cart_items, # إرسال السلة كاملة بدلاً من الحقول الفردية القديمة
        "cash_collected": visit.cash_collected, 
        "debt_paid": visit.debt_paid,
        "notes": visit.notes, 
        "no_sale_reason": visit.no_sale_reason, 
        "status": visit.status,
        "shop": {"latitude": shop.latitude, "longitude": shop.longitude, "location_link": shop.location_link}
    }), 200

# =========================================
# 7.6 التحقق من وجود جلسة عمل نشطة للمندوب
# =========================================
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

# 8.1 إعطاء أو سحب "الضوء الأخضر" وتحميل المخزون
@api.route('/admin/sessions/<int:session_id>/authorize', methods=['PUT'])
@token_required
def toggle_session_authorization(session_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    session = db.session.get(WorkSession, session_id)
    if not session:
        return jsonify({"message": "الجلسة غير موجودة"}), 404

    data = request.get_json() or {}
    is_authorized = data.get('is_authorized', True) 
    inventory_data = data.get('inventory', []) # مصفوفة لتحديد كميات البضاعة المحملة

    try:
        session.is_authorized_to_sell = is_authorized
        
        # إذا المدير أعطى الضوء الأخضر، نقوم بتحميل سيارة المندوب بالبضاعة
        if is_authorized and inventory_data:
            # مسح أي جرد سابق لتجنب التكرار
            SessionInventory.query.filter_by(work_session_id=session.id).delete()
            
            inventory_objects = []
            for item in inventory_data:
                inventory_objects.append(
                    SessionInventory(
                        work_session_id=session.id,
                        product_variant_id=item['product_variant_id'],
                        starting_cartons=item.get('cartons', 0),
                        starting_packs=item.get('packs', 0),
                        current_remaining_cartons=item.get('cartons', 0),
                        current_remaining_packs=item.get('packs', 0)
                    )
                )
            if inventory_objects:
                db.session.bulk_save_objects(inventory_objects)

        db.session.commit()
        status_msg = "تم تفعيل خط السير وتحميل المخزون بنجاح" if is_authorized else "تم إقفال خط السير"
        return jsonify({"message": status_msg, "is_authorized": session.is_authorized_to_sell}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في تعديل الصلاحية", "error": str(e)}), 500


# 8.2 جلب ملخص كل الجلسات النشطة اليوم (لشاشة المدير الرئيسية)
@api.route('/admin/sessions/today', methods=['GET'])
@token_required
def get_todays_sessions():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    today_date = date.today()
    active_sessions = WorkSession.query.filter_by(session_date=today_date).all()
    
    sessions_data = []
    for session in active_sessions:
        sessions_data.append({
            "session_id": session.id,
            "driver_name": session.driver.full_name,
            "start_time": session.start_time.isoformat() if session.start_time else None,
            "is_authorized_to_sell": session.is_authorized_to_sell,
            "is_on_break": bool(session.break_start_time and not session.break_end_time)
        })

    return jsonify({"todays_sessions": sessions_data}), 200

# 8.3 تقرير التسوية اليومية وجرد السيارة (للمدير)
@api.route('/admin/sessions/<int:session_id>/settlement_report', methods=['GET'])
@token_required
def get_session_settlement_report(session_id):
    # 1. حماية فائقة: التأكد أن الطالب هو المدير
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    session = db.session.get(WorkSession, session_id)
    if not session:
        return jsonify({"message": "الجلسة غير موجودة"}), 404

    # 2. الحسابات المالية الدقيقة (باستخدام قاعدة البيانات مباشرة لتجنب N+1)
    stats = db.session.query(
        func.count(Visit.id).label('total_visits'),
        func.sum(Visit.cash_collected).label('total_cash'),
        func.sum(Visit.debt_paid).label('total_debt')
    ).filter(Visit.work_session_id == session_id, Visit.status == 'Completed').first()

    # المبيعات الناجحة فقط
    sales_count = db.session.query(func.count(Visit.id)).filter(
        Visit.work_session_id == session_id, Visit.status == 'Completed', Visit.outcome == 'Sale'
    ).scalar() or 0

    pending_count = Visit.query.filter_by(driver_id=session.driver_id, status='Pending').count()

    # 3. جرد المخزون (بالتفصيل)
    inventories = SessionInventory.query.options(
        joinedload(SessionInventory.product_variant)
    ).filter_by(work_session_id=session.id).all()

    inventory_report = []
    for inv in inventories:
        sold_cartons = inv.starting_cartons - inv.current_remaining_cartons
        inventory_report.append({
            "product_id": inv.product_variant_id,
            "product_name": inv.product_variant.variant_name,
            "starting_cartons": inv.starting_cartons,
            "sold_cartons": sold_cartons,
            "remaining_cartons": inv.current_remaining_cartons
        })

    # 4. تجميع التقرير وإرساله
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
        "inventory": inventory_report
    }), 200

# 8.4 اعتماد التسوية اليومية لجلسة المندوب
@api.route('/admin/sessions/<int:session_id>/settle', methods=['PUT'])
@token_required
def settle_session(session_id):
    # 1. حماية فائقة: التأكد أن الطالب هو المدير
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    session = db.session.get(WorkSession, session_id)
    if not session:
        return jsonify({"message": "الجلسة غير موجودة"}), 404

    # 2. منع تسوية جلسة مسواة مسبقاً
    if session.is_settled:
        return jsonify({"message": "تم اعتماد تسوية هذه الجلسة مسبقاً ولا يمكن التعديل عليها."}), 400

    # 3. التأكد من أن المندوب أنهى عمله (لا يمكن تسوية جلسة ما زالت نشطة بالشارع)
    if not session.end_time:
        return jsonify({"message": "مرفوض: لا يمكن تسوية الجلسة لأن المندوب لم يقم بإنهاء العمل من تطبيقه."}), 400

    try:
        # 4. إغلاق الجلسة واعتمادها محاسبياً
        session.is_settled = True
        db.session.commit()
        
        return jsonify({"message": "تم اعتماد التسوية وإغلاق العهدة بنجاح", "is_settled": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في اعتماد التسوية", "error": str(e)}), 500