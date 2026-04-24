from flask import Blueprint, request, jsonify, g
from datetime import datetime, date, timezone, timedelta
from collections import Counter
import re
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import traceback
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from decimal import Decimal
# توحيد الاستيرادات وحذف التكرار
from models import db, Driver, Shop, Visit, VisitItem, VisitReturn, WorkSession, ProductVariant, SessionInventory, Zone, Vehicle, DispatchRoute, VehicleLoad, ShortageRequest, ImportLog, InventoryLedger, SystemAuditLog, WorkBreakLog, InventoryTransfer, OfferRule
from services import calculate_invoice, check_debt_limits, adjust_inventory, get_setting
from config import Config
from models import Governorate, Country
import time
from functools import wraps

# +++ حرس الحدود: ذاكرة مؤقتة ذات تنظيف ذاتي (Garbage Collected) لصد هجمات Brute Force +++
# (ملاحظة: للاستخدام المتقدم مع Gunicorn، ينصح بـ Flask-Limiter/Redis لاحقاً، لكن هذا الدرع يكفي حالياً ويمنع Memory Leak)
login_attempts = {}

def rate_limit_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ip = request.remote_addr
        now = time.time()
        
        # +++ النسف المعماري للـ Memory Leak (قانون أبو الجماجيم): تنظيف الـ IP إذا مر ساعة على آخر محاولة وانتهى الحظر +++
        keys_to_delete = [
            k for k, v in login_attempts.items() 
            if now > v.get('lockout_until', 0) and now > v.get('last_attempt', 0) + 3600
        ]
        for k in keys_to_delete:
            del login_attempts[k]
            
        # +++ تسجيل "وقت آخر محاولة" لضبط التنظيف بدقة +++
        record = login_attempts.get(ip, {'count': 0, 'lockout_until': 0, 'last_attempt': now})
        record['last_attempt'] = now
        
        if now < record['lockout_until']:
            return jsonify({"message": "تم حظر عنوان IP مؤقتاً (لمدة 15 دقيقة) بسبب محاولات اختراق متكررة."}), 429
            
        response, status = f(*args, **kwargs)
        
        if status in [401, 404]: 
            record['count'] += 1
            if record['count'] >= 5: 
                record['lockout_until'] = now + 900 
        else:
            record['count'] = 0 
            
        login_attempts[ip] = record
        return response, status
    return decorated_function

api = Blueprint('api', __name__)
token_serializer = URLSafeTimedSerializer(Config.SECRET_KEY)

# --- دالة حماية الروابط ---
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
            driver_id = data['driver_id']
            
            # +++ الدرع الفولاذي: استعلام واحد فقط (O(1)) لمنع إرهاق قاعدة البيانات +++
            driver = db.session.get(Driver, driver_id)
            if not driver or not getattr(driver, 'is_active', True):
                return jsonify({"message": "مرفوض أمنياً: تم إيقاف حسابك أو طردك من النظام. التوكن ملغي."}), 403
                
            g.current_driver_id = driver_id
        except (SignatureExpired, BadSignature):
            return jsonify({"message": "Token is invalid or expired"}), 401
        except Exception:
            return jsonify({"message": "Token processing error"}), 401

        return f(*args, **kwargs)
    return decorated_function

# =========================================
# 1. تسجيل الدخول
# =========================================
# --- 1. دالة تسجيل دخول المندوب (الموبايل) ---
@api.route('/driver/login', methods=['POST'])
@rate_limit_login
def driver_login():
    data = request.get_json(silent=True) or {}
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

# --- 2. دالة تسجيل دخول لوحة التحكم (Admin Dashboard) ---
@api.route('/login', methods=['POST'])
@rate_limit_login
def admin_login():
    data = request.get_json(silent=True) or {}
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"message": "Missing username or password"}), 400

    admin = Driver.query.filter_by(username=data.get('username'), is_active=True).first()

    if admin and admin.check_password(data.get('password')):
        # زيادة في الأمان: نتحقق أن الحساب هو "أدمن" فعلاً قبل إصدار التوكن للوحة
        if not admin.is_admin:
            return jsonify({"message": "عذراً، هذا الحساب غير مصرح له بالدخول للوحة التحكم"}), 403
            
        token = token_serializer.dumps({'driver_id': admin.id})
        return jsonify({
            "message": "Admin Login Successful!",
            "token": token,
            "driver_id": admin.id,
            "driver_name": admin.full_name,
            "is_admin": admin.is_admin
        }), 200
    return jsonify({"message": "Invalid username or password"}), 401

    
# =========================================
# 2. بدء جلسة العمل (مربوطة بالتوزيع والجرد)
# =========================================
@api.route('/driver/<int:driver_id>/sessions/start', methods=['POST'])
@token_required
def start_work_session(driver_id):
    if getattr(g, 'current_driver_id', None) != driver_id:
         return jsonify({"message": "مرفوض: غير مصرح لك."}), 403

    # 1. الحماية من تراكم العهدة
    unsettled_session = WorkSession.query.filter_by(driver_id=driver_id, is_settled=False).first()
    if unsettled_session:
        return jsonify({
            "message": "لا يمكنك بدء يوم عمل جديد. لديك عهدة سابقة معلقة لم يتم تسويتها من قبل الإدارة."
        }), 403

    # 2. +++ منع بدء العمل بدون خط سير (حماية التوزيع) +++
    active_route = DispatchRoute.query.filter_by(driver_id=driver_id, status='active').first()
    if not active_route:
        return jsonify({
            "message": "لا يوجد لديك خط سير مخصص اليوم. الرجاء مراجعة مدير التوزيع."
        }), 403

    # +++ قفل التزامن الفولاذي: قفل سطر المندوب لمنع استنساخ الجلسات والعهد إذا ضغط المندوب مرتين بسرعة +++
    db.session.query(Driver).with_for_update().filter_by(id=driver_id).first()

    # 3. التحقق من عدم وجود جلسة نشطة (لم يتم إنهاؤها) بغض النظر عن التاريخ
    existing_session = WorkSession.query.filter_by(
        driver_id=driver_id,
        end_time=None
    ).first()

    if existing_session:
        return jsonify({"message": "لديك جلسة عمل نشطة بالفعل لم يتم إنهاؤها."}), 409

    try:
        data = request.get_json(silent=True) or {}
        lat = data.get('latitude')
        lng = data.get('longitude')

        # 4. إنشاء الجلسة الجديدة
        new_session = WorkSession(
            driver_id=driver_id,
            start_time=datetime.now(timezone.utc),
            start_latitude=lat,
            start_longitude=lng,
            is_authorized_to_sell=False # يبدأ بدون صلاحية بيع (الضوء الأحمر)
        )
        db.session.add(new_session)
        db.session.flush() # للحصول على new_session.id

        # 5. +++ ربط خط السير بالجلسة ونقل حمولة السيارة لتصبح جرد المندوب (مصافحة الصباح الدقيقة) +++
        active_route.work_session_id = new_session.id
        
        # جلب الحمولة مع تفاصيل المنتج لضرب الكراتين في عدد الحبات
        vehicle_loads = VehicleLoad.query.options(joinedload(VehicleLoad.product_variant)).filter_by(vehicle_id=active_route.vehicle_id).all()
        for load in vehicle_loads:
            variant = load.product_variant
            packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton else 1
            total_packs = load.quantity * packs_per_carton
            
            inventory_item = SessionInventory(
                work_session_id=new_session.id,
                product_variant_id=load.product_variant_id,
                starting_quantity=total_packs,
                current_remaining_quantity=total_packs
            )
            db.session.add(inventory_item)
            
        # 6. +++ النسف المعماري (Bulk Update): تحديث كل المحلات المعلقة بـ Query واحد فقط في الداتابيز لمنع إرهاق الذاكرة +++
        Visit.query.filter_by(
            driver_id=driver_id, 
            status='Pending'
        ).update(
            {'work_session_id': new_session.id}, 
            synchronize_session=False
        )

        db.session.commit()
        return jsonify({
            "message": "تم بدء الجلسة بنجاح، وتم استلام جرد السيارة.", 
            "session_id": new_session.id
        }), 201

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "خطأ داخلي أثناء بدء الجلسة."}), 500

# =========================================
# 3. إنهاء جلسة العمل
# =========================================
@api.route('/driver/<int:driver_id>/sessions/end', methods=['PUT'])
@token_required
def end_work_session(driver_id):
    # +++ الدرع الفولاذي (IDOR Fix): منع أي مندوب من إنهاء جلسة مندوب آخر +++
    if getattr(g, 'current_driver_id', None) != driver_id:
        return jsonify({"message": "مرفوض أمنياً: لا يمكنك إنهاء جلسة زميلك."}), 403

    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
    if not active_session:
        return jsonify({"message": "No active session"}), 404

    # +++ حرس الحدود (Backend): لا نثق بالفرونت إند أبداً، منع إنهاء العمل أثناء الاستراحة من جذور السيرفر +++
    if active_session.break_start_time and not active_session.break_end_time:
        return jsonify({"message": "مرفوض أمنياً: أنت الآن في وقت الاستراحة. يجب إنهاء الاستراحة أولاً قبل إنهاء يوم العمل."}), 400

    # +++ الدرع الحديدي: منع إنهاء العمل إذا كان هناك مصافحات معلقة +++
    pending_transfers = InventoryTransfer.query.filter_by(
        work_session_id=active_session.id, 
        status='pending'
    ).first()
    
    if pending_transfers:
        return jsonify({
            "message": "لا يمكنك إنهاء العمل! لديك حوالات معلقة من الإدارة (مصافحة) يجب الموافقة عليها أو رفضها أولاً."
        }), 400

    try:
        active_session.end_time = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({"message": "تم إنهاء الجلسة بنجاح."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ داخلي أثناء إنهاء الجلسة."}), 500
    
# =========================================
# 3.5 تسجيل وقت الاستراحة
# =========================================
@api.route('/driver/<int:driver_id>/sessions/break', methods=['PUT'])
@token_required
def toggle_break(driver_id):
    if getattr(g, 'current_driver_id', None) != driver_id:
         return jsonify({"message": "Forbidden"}), 403

    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
    if not active_session:
        return jsonify({"message": "No active session"}), 404

    data = request.get_json(silent=True) or {}
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
            
            # +++ توحيد الوقت: استخدام Aware Datetime بالكامل +++
            end_t = datetime.now(timezone.utc)
            break_start = active_session.break_start_time
            
            if break_start and break_start.tzinfo is None:
                break_start = break_start.replace(tzinfo=timezone.utc)
                
            duration = int((end_t - break_start).total_seconds() / 60) if break_start else 0
            break_log = WorkBreakLog(
                work_session_id=active_session.id,
                break_start=active_session.break_start_time,
                break_end=end_t,
                duration_minutes=duration
            )
            db.session.add(break_log)
            
            # +++ تصفير الحقول الأساسية لتسمح باستراحة جديدة لاحقاً +++
            active_session.break_start_time = None
            active_session.break_end_time = None
            
            msg = "تم إنهاء الاستراحة وتوثيقها"
        else:
            return jsonify({"message": "إجراء غير صالح"}), 400

        db.session.commit()
        return jsonify({"message": msg}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في تسجيل الاستراحة", "error": "Internal Server Error"}), 500

# =========================================
# 4. تحديث نتيجة الزيارة
# =========================================

# +++ خدمة التراجع المستقلة (Reversal Service) تطبيقاً لمبدأ SRP ومنع الـ Hard Delete +++
def reverse_previous_visit_state(visit, active_session, shop):    
    # 1. التراجع المستودعي للمبيعات والعينات (مع حماية الأقفال الجماعية)
    if visit.outcome in ['Sale', 'NoSale']:
        # +++ الكي الجراحي: جلب كل السجلات المطلوبة وقفلها دفعة واحدة مع ترتيب إجباري لمنع الـ Database Deadlock +++
        item_variant_ids = [i.product_variant_id for i in visit.items if not getattr(i, 'is_cancelled', False)]
        if active_session and item_variant_ids:
            locked_inv = {inv.product_variant_id: inv for inv in db.session.query(SessionInventory)
                          .with_for_update().filter(SessionInventory.work_session_id == active_session.id,
                                                   SessionInventory.product_variant_id.in_(item_variant_ids))
                          .order_by(SessionInventory.product_variant_id.asc()).all()}

            for item in visit.items:
                if getattr(item, 'is_cancelled', False): continue
                # +++ حماية الرياضيات: تأمين حبات الكرتونة لمنع 500 Crash (الذي يسبب وهم الأوفلاين) +++
                safe_packs = item.product_variant.packs_per_carton if item.product_variant and item.product_variant.packs_per_carton else 1
                packs_to_return = ((item.quantity + item.bonus_quantity + item.sample_quantity) * safe_packs) + getattr(item, 'packs_quantity', 0) + getattr(item, 'sample_packs_quantity', 0)
                
                inv_record = locked_inv.get(item.product_variant_id)
                expected_qty = inv_record.current_remaining_quantity if inv_record else 0
                
                # +++ فك الـ Deadlock: تعديل المخزون مباشرة من الكائن المقفل مسبقاً (No External Calls) +++
                if inv_record:
                    inv_record.current_remaining_quantity += packs_to_return
                else:
                    db.session.add(SessionInventory(work_session_id=active_session.id, product_variant_id=item.product_variant_id, starting_quantity=packs_to_return, current_remaining_quantity=packs_to_return))
                    
                db.session.add(InventoryLedger(
                    work_session_id=active_session.id, driver_id=visit.driver_id,
                    product_variant_id=item.product_variant_id, transaction_type='Adjustment (Reversal)',
                    expected_quantity=expected_qty, actual_quantity=expected_qty + packs_to_return,
                    difference=packs_to_return, admin_id=visit.driver_id, notes=f"إلغاء بيع سابق للمحل: {shop.name}"
                ))
                item.is_cancelled = True 

    # 2. إرجاع المرتجعات التي استلمها المندوب (مع حماية الأقفال الجماعية والترتيب الإجباري لمنع Deadlock)
    ret_variant_ids = [r.product_variant_id for r in visit.returns if not getattr(r, 'is_cancelled', False)]
    locked_inv_ret = {}
    # +++ النسف المعماري لـ N+1: جلب المنتجات دفعة واحدة للذاكرة +++
    bulk_ret_variants = {}
    
    if active_session and ret_variant_ids:
        locked_inv_ret = {inv.product_variant_id: inv for inv in db.session.query(SessionInventory)
                      .with_for_update().filter(SessionInventory.work_session_id == active_session.id,
                                               SessionInventory.product_variant_id.in_(ret_variant_ids))
                      .order_by(SessionInventory.product_variant_id.asc()).all()}
        bulk_ret_variants = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(ret_variant_ids)).all()}

    for ret in visit.returns:
        if getattr(ret, 'is_cancelled', False): continue 
        if active_session:
            # +++ جلب المنتج من الذاكرة (O(1)) بدل ضرب قاعدة البيانات +++
            ret_variant = bulk_ret_variants.get(ret.product_variant_id)
            packs_per_carton = ret_variant.packs_per_carton if ret_variant and ret_variant.packs_per_carton else 1
            total_ret_packs = (ret.quantity * packs_per_carton) + getattr(ret, 'packs_quantity', 0)
            
            # +++ جلب الرصيد من الذاكرة المقفلة جماعياً +++
            inv_record = locked_inv_ret.get(ret.product_variant_id)
            expected_qty = inv_record.current_remaining_quantity if inv_record else 0
            
            # +++ النسف المعماري للثقب الأسود: التوالف لم تدخل العهدة أصلاً لكي تُسحب منها! نسحب الصالح فقط +++
            is_sellable = ret.return_type not in ['Expired', 'Damaged', 'Factory_Defect']
            if is_sellable:
                # +++ فك الـ Deadlock وإعدام الفشل الصامت بضربة واحدة: تحقق مباشر من الكائن +++
                if not inv_record or inv_record.current_remaining_quantity - total_ret_packs < 0:
                    raise Exception(f"فشل سحب المرتجعات أثناء التراجع. يبدو أن المندوب قد صرف هذه المرتجعات.")
                    
                inv_record.current_remaining_quantity -= total_ret_packs
                
            db.session.add(InventoryLedger(
                work_session_id=active_session.id, driver_id=visit.driver_id,
                product_variant_id=ret.product_variant_id, transaction_type='Adjustment (Reversal Return)',
                expected_quantity=expected_qty, actual_quantity=expected_qty - total_ret_packs,
                difference=-total_ret_packs, admin_id=visit.driver_id, notes=f"عكس مرتجع سابق للمحل: {shop.name}"
            ))
        ret.is_cancelled = True

    # 3. التراجع المالي الشامل (قاعدة Inverse Delta)
    # لا نقوم بنسخ الرصيد القديم أبداً لمنع مسح العمليات اللاحقة
    
    # أ. عكس أثر المبيعات: طرح "صافي الدين" الذي أضيف في تلك الزيارة
    net_visit_debt = Decimal(str(visit.final_amount_due or 0.0)) - Decimal(str(visit.cash_collected or 0.0))
    # +++ التدمير المحاسبي لثغرة مسح الديون: يجب طرح القيمة سواء كانت موجبة (دين) أو سالبة (فائض) +++
    shop.current_balance -= net_visit_debt
        
    # ب. عكس أثر التحصيل: إعادة "المبلغ الذي سدده المندوب" إلى رصيد المحل
    # (لأنه عند التراجع، نعتبر كأن السداد لم يتم)
    debt_paid_to_revert = Decimal(str(visit.debt_paid or 0.0))
    shop.current_balance += debt_paid_to_revert

    # +++ كشف الاختلاس (التموضع الصحيح): التقاط وتوثيق الكاش *قبل* تصفيره لإجبار المندوب على إعادته +++
    old_cash = visit.cash_collected or 0.0
    old_debt_paid = visit.debt_paid or 0.0
    
    if old_cash > 0 or old_debt_paid > 0:
        db.session.add(SystemAuditLog(
            admin_id=visit.driver_id,
            target_id=f"Visit_{visit.id}_Shop_{shop.id}",
            action_type="CASH_REVERSAL_ALERT",
            old_value=f"Cash: {old_cash} | Debt Paid: {old_debt_paid}",
            new_value="Reversed to 0.0. تحذير: يجب على المندوب إعادة هذا النقد يدوياً لصاحب المحل."
        ))

    # 4. تصفير العدادات المالية للزيارة بأمان
    visit.amount_before_tax_and_discount = 0.0
    visit.discount_applied = 0.0
    visit.tax_amount = 0.0
    visit.final_amount_due = 0.0
    visit.cash_collected = 0.0
    visit.debt_paid = 0.0
    visit.shop_balance_before = None
    visit.shop_balance_after = None
    visit.tax_qr_code = None

    # 5. إرجاع لحالة الانتظار
    visit.outcome = 'Pending'
    visit.status = 'Pending'


# =========================================
# 4.1 تحديث نتيجة الزيارة
# =========================================
@api.route('/visits/<int:visit_id>', methods=['PUT'])
@token_required
def update_visit(visit_id):
    # +++ نسف ثغرة N+1 وقفل الزيارة لمنع الدفع المزدوج (Double Billing) +++
    visit = Visit.query.options(
        joinedload(Visit.shop),
        joinedload(Visit.items).joinedload(VisitItem.product_variant),
        joinedload(Visit.returns)
    ).with_for_update().filter_by(id=visit_id).first_or_404()
    
    if visit.driver_id != getattr(g, 'current_driver_id', None):
         return jsonify({"message": "Forbidden"}), 403
         
    data = request.get_json(silent=True) or {}
    outcome = data.get('outcome')
    if outcome not in ['Sale', 'NoSale', 'Postponed']:
        return jsonify({"message": "Invalid outcome"}), 400

    # +++ قفل التزامن الفولاذي (Row-Level Lock) لمنع كارثة الـ Double Click +++
    # نُقفل سجل المحل في قاعدة البيانات حتى تنتهي المعاملة المالية بالكامل
    shop = db.session.query(Shop).with_for_update().filter_by(id=visit.shop_id).first()
    visit.shop = shop 
    active_session = WorkSession.query.filter_by(driver_id=visit.driver_id, end_time=None).first()

    # +++ قفل الحماية الصارم: التحقق من الجلسة، المنطقة، والاستراحة +++
    if not active_session:
        return jsonify({"message": "لا يمكنك تنفيذ العملية. الرجاء بدء يوم العمل أولاً."}), 403
        
    # +++ حماية الـ Ghost Sale (معمارية Zero Trust) +++
    current_route = DispatchRoute.query.filter_by(work_session_id=active_session.id, status='active').first()
    if not current_route:
         return jsonify({"message": "تم سحب خط السير أو إيقافه من قبل الإدارة. لا يمكنك إتمام العملية."}), 403
         
    # +++ حماية معمارية ديناميكية: التحقق اللحظي من وجود طلب عاجل حتى لو لم يكن مختوماً على الزيارة +++
    has_active_shortage = ShortageRequest.query.filter_by(shop_id=shop.id, status='pending').first() is not None
    if shop.zone_id != current_route.zone_id and not (visit.is_emergency or has_active_shortage):
         return jsonify({"message": "مرفوض أمنياً: لا يمكنك البيع لمحل خارج منطقة عملك المخصصة إلا بتصريح طلب عاجل."}), 403

    # حماية الاستراحة (إرجاع الرسالة الصحيحة للموبايل)
    if active_session.break_start_time and not active_session.break_end_time:
        return jsonify({"message": "أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل."}), 403
        
    # حماية الضوء الأخضر
    if not active_session.is_authorized_to_sell:
        return jsonify({"message": "غير مصرح لك بإجراء عمليات بيع حالياً. بانتظار تفعيل خط السير من الإدارة."}), 403

    # +++ الدرع الأمني: منع البيع إذا كانت هناك حوالة معلقة (مصافحة) لحماية العهدة من التضارب +++
    pending_transfers = InventoryTransfer.query.filter_by(work_session_id=active_session.id, status='pending').first()
    if pending_transfers:
        return jsonify({"message": "مرفوض: لديك حوالة معلقة من الإدارة (مصافحة). يرجى تأكيدها أو رفضها أولاً لضبط العهدة."}), 403

    try:        
        # +++ نظام الارتجاع الشامل (تم عزله في خدمة مستقلة تطبيقاً لمبدأ SRP + Soft Delete) +++
        if visit.status == 'Completed':
            reverse_previous_visit_state(visit, active_session, shop)

        # +++ المعالجة المالية الصارمة بالـ Decimal +++
        # +++ الدرع الفولاذي الأخير: حماية السيرفر من هجمات النصوص (مثل 'abc') التي تفجر الـ Decimal بـ 500 Crash +++
        try:
            raw_debt_paid = str(data.get('debt_paid') or '0.0').strip()
            debt_paid_input = Decimal(raw_debt_paid) if raw_debt_paid else Decimal('0.0')
        except Exception:
            debt_paid_input = Decimal('0.0')
            
        try:
            raw_shop_bal = str(shop.current_balance or '0.0').strip()
            original_shop_balance = Decimal(raw_shop_bal) if raw_shop_bal else Decimal('0.0')
        except Exception:
            original_shop_balance = Decimal('0.0')

        # +++ اللوجيك المحاسبي الذكي للذمم السالبة +++
        if debt_paid_input > Decimal('0'):
            if original_shop_balance <= Decimal('0'):
                return jsonify({"message": f"مرفوض: المحل رصيده دائن أو مُصفر ({original_shop_balance}). لا توجد ذمم لتحصيلها."}), 400
            if debt_paid_input > original_shop_balance:
                 return jsonify({"message": f"مرفوض: المبلغ المحصل ({debt_paid_input}) أكبر من ذمة المحل الحالية ({original_shop_balance})."}), 400
                 
        new_shop_balance = original_shop_balance

        # +++ النسف المعماري لآلة الزمن (Time-Travel Fraud): نسجل وقت الزيارة فقط إذا كانت جديدة، لمنع تدمير تقارير الأيام السابقة عند التعديل +++
        if visit.status == 'Pending':
            visit.visit_timestamp = datetime.now(timezone.utc)
            
        visit.notes = data.get('notes')
        visit.latitude = data.get('latitude', visit.latitude)
        visit.longitude = data.get('longitude', visit.longitude)
        visit.shop_balance_before = original_shop_balance
        visit.is_emergency = data.get('is_emergency', visit.is_emergency)

        if active_session:
            visit.work_session_id = active_session.id

        # +++ السماح بمعالجة البضاعة (عينات/مرتجعات) في حالتي البيع وعدم البيع +++
        if outcome in ['Sale', 'NoSale']:
            # +++ حماية הـ 500 Crash: get() ترجع None إذا تم إرسال null صراحة، لذا نستخدم or [] +++
            cart_items = data.get('cart_items') or []
            returns_data = data.get('returns') or [] 
            
            # +++ إيقاف غسيل الأموال: استلام الكاش كـ Decimal بأمان من الفراغات وهجمات النصوص العشوائية +++
            try:
                raw_cash = str(data.get('cash_collected') or '0.0').strip()
                cash_collected = Decimal(raw_cash) if raw_cash else Decimal('0.0')
            except Exception:
                cash_collected = Decimal('0.0')
            
            vehicle_id = current_route.vehicle_id if current_route else None

            # تصفير العدادات كـ Decimal نقي
            total_final_amount = Decimal('0.0')
            total_base_amount = Decimal('0.0')
            total_discount = Decimal('0.0')
            total_tax = Decimal('0.0')
            total_quantity = 0

            # +++ الدرع الفولاذي: مسح طفيليات الحفظ (Soft Delete) للمنتجات السابقة قبل إضافة التعديلات الجديدة لمنع تكرار الريكوردات +++
            VisitItem.query.filter_by(visit_id=visit.id, is_cancelled=False).update({'is_cancelled': True}, synchronize_session=False)
            VisitReturn.query.filter_by(visit_id=visit.id, is_cancelled=False).update({'is_cancelled': True}, synchronize_session=False)

            # +++ النسف المعماري لـ N+1 (Bulk Fetch in Memory) +++
            all_var_ids = [i.get('product_variant_id') for i in cart_items] + [r.get('product_variant_id') for r in returns_data]
            all_var_ids = list(set([vid for vid in all_var_ids if vid]))
            
            variants_map = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(all_var_ids)).all()}
            
            inv_map = {}
            if active_session and all_var_ids:
                # +++ إقفال الخزنة المعماري المطلق: إضافة order_by إجبارياً لمنع الـ Deadlocks المتصالبة (Cross-Locks) في Postgres +++
                inv_records = db.session.query(SessionInventory).with_for_update().filter(
                    SessionInventory.work_session_id == active_session.id,
                    SessionInventory.product_variant_id.in_(all_var_ids)
                ).order_by(SessionInventory.product_variant_id.asc()).all()
                inv_map = {inv.product_variant_id: inv for inv in inv_records}
            # ++++++++++++++++++++++++++++++++++++++++++++++++++++++

            # +++ جلب الضريبة والعروض والمندوب مرة واحدة للذاكرة (O(1)) لنسف N+1 والزهايمر +++
            current_tax_pct = get_setting('tax_percentage', '0.0')
            active_offers = OfferRule.query.filter_by(is_active=True).order_by(OfferRule.threshold_quantity.desc()).all()
            current_driver = db.session.get(Driver, visit.driver_id)

            for item in cart_items:
                variant_id = item.get('product_variant_id')
                # +++ الدرع الفولاذي: حماية الـ Integer من قنبلة الـ Empty String القادمة من React +++
                quantity = int(str(item.get('quantity') or '0').strip() or '0')
                packs_quantity = int(str(item.get('packs_quantity') or '0').strip() or '0')
                sample_quantity = int(str(item.get('sample_cartons', item.get('sample_quantity', '0')) or '0').strip() or '0') 
                sample_packs_quantity = int(str(item.get('sample_packs', item.get('sample_packs_quantity', '0')) or '0').strip() or '0') 

                # +++ الدرع الفولاذي: منع اختراق الكميات السالبة وسرقة العهدة +++
                if quantity < 0 or packs_quantity < 0 or sample_quantity < 0 or sample_packs_quantity < 0:
                    return jsonify({"message": "مرفوض أمنياً: تم رصد محاولة تلاعب بالكميات (قيم سالبة)."}), 400

                # السماح بالمرور إذا كان هناك أي قيمة موجبة (تعديل منطقي)
                if (quantity == 0 and packs_quantity == 0 and sample_quantity == 0 and sample_packs_quantity == 0) or not variant_id:
                    continue
                    
                variant = variants_map.get(variant_id)
                if not variant:
                    return jsonify({"message": f"المنتج رقم {variant_id} غير موجود."}), 404
                    
                # +++ حرس الحدود (منطق الميدان): السماح بتجاوز العينات لتسهيل العمل، مع زرع "إنذار صامت" للمحاسب آخر اليوم +++
                max_samples = variant.default_max_samples_per_day or 0
                if sample_quantity > max_samples:
                    db.session.add(SystemAuditLog(
                        admin_id=visit.driver_id,
                        target_id=f"Visit_{visit.id}_Var_{variant.id}",
                        action_type="SAMPLES_EXCEED_WARNING",
                        old_value=str(max_samples),
                        new_value=str(sample_quantity),
                        description=f"تحذير: المندوب قام بتوزيع عينات ({sample_quantity}) تتجاوز السقف المسموح ({max_samples}) لمنتج {variant.variant_name}. يجب سؤاله أثناء الجرد."
                    ))
                    
                # +++ التوافق مع تعديل الصديق: تمرير active_offers +++
                invoice = calculate_invoice(quantity, packs_quantity, variant.price_per_carton, variant.price_per_pack, current_tax_pct, active_offers=active_offers)
                
                if invoice is None:
                    invoice = {
                        'bonus_units': 0,
                        'final_amount': 0.0,
                        'base_amount': 0.0,
                        'discount_applied': 0.0,
                        'tax_amount': 0.0
                    }
                
                if active_session:
                    # +++ الحماية المطلقة من الـ TypeError: تأمين packs_per_carton إذا كانت NULL بالداتابيز +++
                    safe_packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
                    
                    # +++ الحساب الجراحي الدقيق: دمج (حبات العينات) المفقودة في معادلة الخصم من المخزون +++
                    total_packs_to_deduct = (quantity * safe_packs_per_carton) + packs_quantity + \
                                            (invoice['bonus_units'] * safe_packs_per_carton) + \
                                            (sample_quantity * safe_packs_per_carton) + sample_packs_quantity
                    net_quantity_in_packs = -total_packs_to_deduct
                    
                    inv_record = inv_map.get(variant_id)
                    if not inv_record:
                        return jsonify({"message": f"المنتج {variant.variant_name} غير موجود في عهدتك."}), 409
                        
                    expected_qty = inv_record.current_remaining_quantity
                    
                    # +++ فك الـ Deadlock: الخصم المباشر من الذاكرة المقفلة +++
                    if expected_qty + net_quantity_in_packs < 0:
                        return jsonify({"message": f"مخزونك لا يكفي من {variant.variant_name}."}), 409
                        
                    inv_record.current_remaining_quantity += net_quantity_in_packs
                        
                    # +++ الربط اللحظي: تسجيل حركة البيع في دفتر الأستاذ (Ledger) +++
                    db.session.add(InventoryLedger(
                        work_session_id=active_session.id,
                        driver_id=visit.driver_id,
                        vehicle_id=vehicle_id,
                        product_variant_id=variant_id,
                        transaction_type='Sale',
                        expected_quantity=expected_qty,
                        actual_quantity=expected_qty + net_quantity_in_packs,
                        difference=net_quantity_in_packs, # +++ تصحيح المتغير القاتل +++
                        admin_id=visit.driver_id, # المندوب هو من قام بالحركة
                        notes=f"فاتورة بيع للمحل: {shop.name}"
                    ))

                new_visit_item = VisitItem(
                    visit_id=visit.id,
                    product_variant_id=variant_id,
                    quantity=quantity,
                    packs_quantity=packs_quantity,
                    bonus_quantity=invoice['bonus_units'],
                    sample_quantity=sample_quantity,
                    sample_packs_quantity=sample_packs_quantity, # +++ حفظ حبات العينات في الداتابيز +++
                    sample_reason=item.get('sample_reason', ''), # +++ حفظ سبب العينة +++
                    price_per_unit_at_sale=variant.price_per_carton,
                    total_price=invoice['final_amount']
                )
                db.session.add(new_visit_item)
               
                # +++ جمع دقيق بالـ Decimal لمنع تدمير الدقة العشرية +++
                total_final_amount += Decimal(str(invoice['final_amount'] or 0.0))
                total_base_amount += Decimal(str(invoice['base_amount'] or 0.0))
                total_discount += Decimal(str(invoice['discount_applied'] or 0.0))
                total_tax += Decimal(str(invoice['tax_amount'] or 0.0))
                total_quantity += quantity

            for ret in returns_data:
                ret_variant_id = ret.get('product_variant_id')
                # +++ الدرع الفولاذي للمرتجعات: منع الـ ValueError من الفراغات التي تسقط السيرفر وتسبب وهم الأوفلاين +++
                try:
                    ret_quantity = int(str(ret.get('cartons', ret.get('quantity', '0'))).strip() or '0')
                    ret_packs_quantity = int(str(ret.get('packs', ret.get('packs_quantity', '0'))).strip() or '0')
                except Exception:
                    continue
                ret_type = ret.get('return_type')
                ret_reason = ret.get('reason', '')

                if (ret_quantity <= 0 and ret_packs_quantity <= 0) or not ret_variant_id:
                    continue
                
                if active_session:
                    inv_record = inv_map.get(ret_variant_id)
                    # 1. التقاط المخزون المتوقع "قبل" عملية الاستبدال
                    expected_qty_before = inv_record.current_remaining_quantity if inv_record else 0
                    
                    variant = variants_map.get(ret_variant_id)
                    packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton else 1
                    total_exchange_packs = (ret_quantity * packs_per_carton) + ret_packs_quantity
                    
                    # 2. (الخطوة أ): خصم البضاعة الصالحة التي خرجت من السيارة (No Deadlock)
                    if not inv_record or inv_record.current_remaining_quantity - total_exchange_packs < 0:
                        return jsonify({"message": f"خطأ في خصم العهدة الصالحة للمرتجعات (الرصيد لا يكفي)."}), 409
                    
                    inv_record.current_remaining_quantity -= total_exchange_packs

                    # توثيق حركة الخصم (البضاعة الصالحة)
                    db.session.add(InventoryLedger(
                        work_session_id=active_session.id, driver_id=visit.driver_id, vehicle_id=vehicle_id,
                        product_variant_id=ret_variant_id, transaction_type='Exchange (Deduction)',
                        expected_quantity=expected_qty_before,
                        actual_quantity=expected_qty_before - total_exchange_packs,
                        difference=-total_exchange_packs, admin_id=visit.driver_id,
                        notes=f"استبدال: بضاعة صالحة خرجت للمحل {shop.name}"
                    ))
                    
                    # 3. (الخطوة ب): معالجة البضاعة الداخلة للسيارة (فصل الصالح عن الطالح)
                    # +++ الدرع الفولاذي (Zero Trust): إذا لم يرسل المندوب نوع التلف (Null/Empty)، نعتبره تالفاً إجبارياً لمنع غسيل البضاعة! +++
                    expected_qty_after_deduction = expected_qty_before - total_exchange_packs
                    is_sellable = ret_type not in ['Expired', 'Damaged', 'Factory_Defect', None, '']
                    
                    actual_inv_after = expected_qty_after_deduction
                    if is_sellable:
                        # +++ التحديث المباشر للمخزون المقفل مسبقاً (No Deadlock) +++
                        inv_record.current_remaining_quantity += total_exchange_packs
                        actual_inv_after += total_exchange_packs

                    # توثيق الحركة في الدفتر بما حدث فعلياً (بدون تزوير)
                    db.session.add(InventoryLedger(
                        work_session_id=active_session.id, driver_id=visit.driver_id, vehicle_id=vehicle_id,
                        product_variant_id=ret_variant_id, transaction_type='Return (Addition)',
                        expected_quantity=expected_qty_after_deduction,
                        actual_quantity=actual_inv_after, # يسجل الرقم الحقيقي سواء زاد أو بقي كما هو
                        difference=total_exchange_packs if is_sellable else 0, # الفرق المحاسبي في العهدة الصالحة
                        admin_id=visit.driver_id,
                        notes=f"مرتجع {ret_type} (استبدال عيني). تم {'إضافته للعهدة' if is_sellable else 'عزله كتالف ولم يضف للعهدة الصالحة'}."
                    ))
                
                new_return = VisitReturn(
                    visit_id=visit.id, product_variant_id=ret_variant_id,
                    quantity=ret_quantity, packs_quantity=ret_packs_quantity,
                    return_type=ret_type, reason=ret_reason
                )
                db.session.add(new_return)

            # +++ منع المندوب من إدخال كاش يتجاوز قيمة الفاتورة لسرقة رصيد المحل الدائن +++
            if cash_collected > total_final_amount:
                return jsonify({"message": f"مرفوض: النقد المحصل للفاتورة ({cash_collected}) لا يمكن أن يتجاوز قيمة الفاتورة نفسها ({total_final_amount}). لسداد الديون القديمة استخدم حقل التحصيل."}), 400

            # +++ تم تنظيف المعسكر: المتغيرات أصبحت Decimal بالأساس، الطرح مباشر وآمن +++
            new_debt = total_final_amount - cash_collected
            
            if new_debt > Decimal('0'):
                # +++ التوافق مع تعديل الصديق: تمرير المندوب والمحل كـ pre_fetched +++
                is_allowed, msg = check_debt_limits(visit.driver_id, shop.id, new_debt, pre_fetched_driver=current_driver, pre_fetched_shop=shop)
                if not is_allowed:
                    return jsonify({"message": msg}), 403

            visit.outcome = outcome # يأخذ Sale أو NoSale
            visit.status = 'Completed'
            visit.updated_at = datetime.now(timezone.utc) 
            
            visit.amount_before_tax_and_discount = total_base_amount
            visit.discount_applied = total_discount
            visit.tax_amount = total_tax
            visit.final_amount_due = total_final_amount
            visit.cash_collected = cash_collected
            visit.debt_paid = debt_paid_input
            
            if outcome == 'NoSale':
                visit.no_sale_reason = data.get('notes')
            
            new_balance = original_shop_balance + new_debt - debt_paid_input
            
            # +++ الدرع الفولاذي لحماية الداتابيز: منع القيمة السالبة من كسر الـ Constraint +++
            if new_balance < Decimal('0'):
                new_balance = Decimal('0')
                
            shop.current_balance = new_balance
            visit.shop_balance_after = new_balance

            # +++ بناء دفتر الأستاذ المالي (Audit Trail) لتعقب الأموال المحصلة +++
            if debt_paid_input > Decimal('0'):
                db.session.add(SystemAuditLog(
                    admin_id=visit.driver_id,
                    target_id=f"Shop_{shop.id}_Visit_{visit.id}",
                    action_type="DEBT_COLLECTION",
                    old_value=f"Balance: {original_shop_balance}",
                    new_value=f"Collected: {debt_paid_input} | New Balance: {new_balance}"
                ))

        elif outcome == 'Postponed':
            visit.updated_at = datetime.now(timezone.utc) # توثيق تاريخ التأجيل
            visit.outcome = 'Postponed'
            visit.status = 'Pending'
            visit.no_sale_reason = data.get('notes')
            visit.shop_balance_after = original_shop_balance

        # +++ إغلاق الطلب العاجل في غرفة العمليات فور إنجاز الزيارة +++
         
            shortage = ShortageRequest.query.filter_by(shop_id=shop.id, status='pending').first()
            if shortage:
                shortage.status = 'fulfilled'
            
            # +++ اللوجيك الدقيق (فرز المحلات العاجلة بعد إنجازها) +++
            # إذا كان المحل العاجل يتبع أساساً لمنطقة خط السير الحالي، نعيده لقائمة (جولة اليوم).
            # أما إذا كان من منطقة خارجية، نُبقي ختم الطوارئ ليبقى في قائمة (الطلبات العاجلة).
            current_route = DispatchRoute.query.filter_by(work_session_id=active_session.id, status='active').first() if active_session else None
            if current_route and shop.zone_id == current_route.zone_id:
                visit.is_emergency = False
                
        db.session.commit()
        return jsonify({
            "message": "Visit updated successfully",
            # +++ تحويل الـ Decimal إلى Float صريح +++
            "new_balance": float(shop.current_balance or 0.0)
        }), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "Error updating visit", "error": "Internal Server Error"}), 500
    

# =========================================
# 5. جلب بيانات الداشبورد للمندوب
# =========================================
@api.route('/driver/<int:driver_id>/dashboard', methods=['GET'])
@token_required
def get_driver_dashboard(driver_id):
    if getattr(g, 'current_driver_id', None) != driver_id:
        return jsonify({"message": "Forbidden"}), 403

    driver = db.session.get(Driver, driver_id)
    if not driver:
        return jsonify({"message": "المندوب غير موجود"}), 404
    
    # 1. البحث عن خط سير نشط (حتى لو لم يبدأ العمل بعد)
    active_route = DispatchRoute.query.filter_by(driver_id=driver_id, status='active').first()
    
    # 2. البحث عن جلسة عمل نشطة اليوم
    active_session = WorkSession.query.filter_by(
        driver_id=driver_id,
        end_time=None
    ).order_by(WorkSession.id.desc()).first()

    assigned_region = "غير محددة"
    inventory_list = []

    # +++ اللوجيك الجديد: إذا تم إطلاق خط سير، أرسل المنطقة والحمولة +++
    if active_route:
        # جلب اسم المنطقة
        zone = db.session.get(Zone, active_route.zone_id)
        if zone:
            assigned_region = zone.name

        # جلب الحمولة من السيارة (VehicleLoad) إذا لم تبدأ الجلسة بعد
        if not active_session:
            vehicle_loads = db.session.query(VehicleLoad, ProductVariant).join(
                ProductVariant, VehicleLoad.product_variant_id == ProductVariant.id
            ).filter(VehicleLoad.vehicle_id == active_route.vehicle_id).all()
            
            for load, variant in vehicle_loads:
                inventory_list.append({
                    "product_id": variant.id,
                    "product_name": variant.variant_name,
                    "starting_cartons": load.quantity,
                    "remaining_cartons": load.quantity,
                    "remaining_packs": 0 
                })

    # إذا بدأت الجلسة الفعلية، نعتمد على جرد الجلسة (SessionInventory)
    if active_session:
        inventories = SessionInventory.query.options(
            joinedload(SessionInventory.product_variant)
        ).filter_by(work_session_id=active_session.id).all()
        
        inventory_list = [] # تفريغ القائمة لملئها بالجرد الفعلي
        for inv in inventories:
            variant = inv.product_variant
            # +++ تحويل الحبات إلى كراتين للعرض الدقيق في شاشة المندوب +++
            packs = variant.packs_per_carton if variant.packs_per_carton and variant.packs_per_carton > 0 else 1
            
            inventory_list.append({
                "product_id": variant.id,
                "product_name": variant.variant_name,
                "starting_cartons": inv.starting_quantity // packs,
                "remaining_cartons": inv.current_remaining_quantity // packs,
                "remaining_packs": inv.current_remaining_quantity % packs
            })

    # حساب الماليات والزيارات
    total_sales_cash = 0.0
    total_debt_paid = 0.0
    debt_payments_count = 0
    total_completed = 0
    sales_in_completed = 0
    total_pending = 0

    if active_session:
        stats = db.session.query(
            func.count(Visit.id).label('total_visits'),
            func.sum(Visit.cash_collected).label('total_cash'),
            func.sum(Visit.debt_paid).label('total_debt')
        ).filter(Visit.work_session_id == active_session.id, Visit.status == 'Completed').first()

        total_completed = stats.total_visits or 0
        total_sales_cash = float(stats.total_cash or 0.0)
        total_debt_paid = float(stats.total_debt or 0.0)
        
        debt_payments_count = Visit.query.filter(
            Visit.work_session_id == active_session.id, 
            Visit.status == 'Completed',
            Visit.debt_paid > 0
        ).count()
        
        sales_in_completed = Visit.query.filter(
            Visit.work_session_id == active_session.id, 
            Visit.status == 'Completed',
            Visit.cash_collected > 0
        ).count()

        # +++ إصلاح الانهيار: التحقق من وجود خط سير نشط قبل محاولة قراءة منطقته +++
        if active_route:
            total_pending = Visit.query.join(Shop).filter(
                Visit.driver_id == driver_id, # ربط الزيارة بالمندوب بدلاً من فخ الـ IDs
                Visit.status == 'Pending',
                Shop.is_archived == False,
                # +++ نسف الثقب الأسود: تم مسح الشرط المستحيل (session_id == route_id) +++
                db.or_(
                    Shop.zone_id == active_route.zone_id,
                    Visit.is_emergency == True
                )
            ).count()
        else:
            total_pending = 0

    # إذا كان هناك خط سير ولكن الجلسة لم تبدأ، نحسب المحلات المعلقة المربوطة بخط السير
    elif active_route:
        total_pending = Visit.query.join(Shop).filter(
            Visit.driver_id == driver_id, 
            Visit.status == 'Pending',
            Shop.zone_id == active_route.zone_id
        ).count()

    response_data = {
        "driver_name": driver.full_name,
        "assigned_region": assigned_region,
        "active_session": {
            "session_id": active_session.id,
            "start_time": active_session.start_time.isoformat() if active_session.start_time else None,
            "is_authorized_to_sell": active_session.is_authorized_to_sell,
            "break_start_time": active_session.break_start_time.isoformat() if active_session.break_start_time else None,
            "break_end_time": active_session.break_end_time.isoformat() if active_session.break_end_time else None,
            "inventory": inventory_list
        } if active_session else None,
        "financials": {
            "total_sales_cash": total_sales_cash,
            "total_debt_paid": total_debt_paid,
            "debt_payments_count": debt_payments_count,
            # +++ الكي الجراحي المحاسبي: استخدام Decimal قبل الجمع لمنع أخطاء التقريب العائمة +++
            "total_cash_overall": float(Decimal(str(total_sales_cash)) + Decimal(str(total_debt_paid)))
        },
        "counts": {
            "total_pending": total_pending,
            "total_completed": total_completed,
            "sales_in_completed": sales_in_completed
        }
    }
    
    # +++ حل مشكلة إرسال الحمولة حتى لو الجلسة لم تبدأ +++
    if not active_session and active_route:
        response_data['active_session'] = {
            "session_id": None,
            "start_time": None,
            "is_authorized_to_sell": False,
            "inventory": inventory_list
        }

    return jsonify(response_data), 200

# =========================================
# 5.5 تأكيد استلام/رفض حوالة منتصف اليوم (المصافحة)
# =========================================
@api.route('/driver/transfers/<int:transfer_id>/respond', methods=['PUT'])
@token_required
def respond_to_transfer(transfer_id):
    driver_id = getattr(g, 'current_driver_id', None)
    
    transfer = db.session.get(InventoryTransfer, transfer_id)
    if not transfer or transfer.work_session.driver_id != driver_id:
        return jsonify({"message": "الحوالة غير موجودة أو لا تخصك."}), 404
        
    if transfer.status != 'pending':
        return jsonify({"message": f"هذه الحوالة تمت معالجتها مسبقاً ({transfer.status})."}), 400

    data = request.get_json(silent=True) or {}
    response = data.get('response') # 'accepted' or 'rejected'
    
    if response not in ['accepted', 'rejected']:
        return jsonify({"message": "رد غير صالح."}), 400

    try:
        transfer.status = response
        
        # جلب البيانات الأساسية (المنطقة والعهدة) مرة واحدة
        route = DispatchRoute.query.filter_by(work_session_id=transfer.work_session_id).first()
        sess_inv = SessionInventory.query.filter_by(work_session_id=transfer.work_session_id, product_variant_id=transfer.product_variant_id).first()
        expected_qty = sess_inv.current_remaining_quantity if sess_inv else 0

        if response == 'accepted':
            # +++ الفحص الاستباقي لمنع قنبلة التزامن (الرصيد السالب) +++
            if transfer.quantity_packs < 0: # حالة السحب من المندوب
                if not sess_inv or (sess_inv.current_remaining_quantity + transfer.quantity_packs < 0):
                    return jsonify({"message": "فشل التأكيد: رصيدك الحالي لا يكفي لتسليم هذه الكمية للإدارة. يبدو أنك قمت بعمليات بيع مؤخراً."}), 400

            # 1. تحديث عهدة المندوب المالية (بالحبات)
            if sess_inv:
                sess_inv.current_remaining_quantity += transfer.quantity_packs
                sess_inv.starting_quantity += transfer.quantity_packs
            else:
                sess_inv = SessionInventory(
                    work_session_id=transfer.work_session_id, 
                    product_variant_id=transfer.product_variant_id, 
                    starting_quantity=transfer.quantity_packs, 
                    current_remaining_quantity=transfer.quantity_packs
                )
                db.session.add(sess_inv)
                
            # +++ تطبيق قانون الـ Zero Trust: تحديث سيارة الشركة (VehicleLoad) الآن فقط، لأن المندوب وافق واستلم البضاعة فعلياً +++
            if route:
                v_load = VehicleLoad.query.filter_by(vehicle_id=route.vehicle_id, product_variant_id=transfer.product_variant_id).first()
                variant = db.session.get(ProductVariant, transfer.product_variant_id)
                packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton else 1
                delta_cartons = transfer.quantity_packs // packs_per_carton
                
                if v_load:
                    v_load.quantity += delta_cartons
                else:
                    db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=transfer.product_variant_id, quantity=delta_cartons))
                
            # تسجيل الحركة رسمياً في دفتر الأستاذ (مصافحة)
            trans_type = 'تأكيد استلام حمولة' if transfer.quantity_packs > 0 else 'تأكيد سحب حمولة'
            db.session.add(InventoryLedger(
                work_session_id=transfer.work_session_id, 
                driver_id=driver_id, 
                vehicle_id=route.vehicle_id if route else None,
                product_variant_id=transfer.product_variant_id, 
                transaction_type=trans_type,
                expected_quantity=expected_qty, 
                actual_quantity=expected_qty + transfer.quantity_packs,
                difference=transfer.quantity_packs, 
                admin_id=transfer.admin_id, 
                notes="موافقة المندوب الرقمية (مصافحة)"
            ))

        elif response == 'rejected':
            # +++ تطبيق قانون الـ Zero Trust: لا نفعل أي شيء في حمولة السيارة، لأن الإدارة لم تضفها من الأساس والمندوب رفض الاستلام (حذفنا عملية الطرح القاتلة) +++

            # توثيق حالة التعارض
            trans_type = 'تعارض: رفض استلام حمولة' if transfer.quantity_packs > 0 else 'تعارض: رفض سحب حمولة'
            db.session.add(InventoryLedger(
                work_session_id=transfer.work_session_id, 
                driver_id=driver_id, 
                vehicle_id=route.vehicle_id if route else None,
                product_variant_id=transfer.product_variant_id, 
                transaction_type=trans_type,
                expected_quantity=expected_qty, 
                actual_quantity=expected_qty, # لم يتغير شيء
                difference=0, 
                admin_id=transfer.admin_id, 
                notes="سجل النظام تعارضاً: المندوب رفض التعديل وتم عكس الكمية بالسيارة."
            ))

        # +++ Commit واحد فقط في نهاية العملية لضمان عدم وجود فخ التعدد +++
        db.session.commit()
        return jsonify({"message": f"تم تسجيل الرد ({response}) بنجاح."}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "خطأ في معالجة الحوالة", "error": "Internal Server Error"}), 500

# =========================================
# 5.55 معالجة الحوالات بالجملة (Batch Response) - نسف الـ HTTP N+1
# =========================================
@api.route('/driver/transfers/batch_respond', methods=['PUT'])
@token_required
def batch_respond_to_transfers():
    driver_id = getattr(g, 'current_driver_id', None)
    data = request.get_json(silent=True) or {}
    
    transfer_ids = data.get('transfer_ids', [])
    response_status = data.get('response') # 'accepted' or 'rejected'
    
    if not transfer_ids or response_status not in ['accepted', 'rejected']:
        return jsonify({"message": "بيانات الطلب غير مكتملة."}), 400

    try:
        # 1. درع IDOR: جلب الحوالات التي تخص هذا المندوب حصراً
        transfers = InventoryTransfer.query.join(WorkSession).filter(
            InventoryTransfer.id.in_(transfer_ids),
            InventoryTransfer.status == 'pending',
            WorkSession.driver_id == driver_id
        ).all()

        if not transfers:
            return jsonify({"message": "لا يوجد حوالات صالحة للمعالجة."}), 404

        # +++ النسف المعماري لـ N+1 (O(1) Database Hits) +++
        var_ids = [t.product_variant_id for t in transfers]
        variants_map = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(var_ids)).all()}
        
        route = DispatchRoute.query.filter_by(work_session_id=transfers[0].work_session_id).first()
        v_load_map = {}
        if route:
            v_loads = VehicleLoad.query.filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(var_ids)).all()
            v_load_map = {vl.product_variant_id: vl for vl in v_loads}

        sess_inv_map = {si.product_variant_id: si for si in SessionInventory.query.filter(
            SessionInventory.work_session_id == transfers[0].work_session_id, 
            SessionInventory.product_variant_id.in_(var_ids)
        ).all()}

        for transfer in transfers:
            transfer.status = response_status
            p_id = transfer.product_variant_id
            variant = variants_map.get(p_id)
            sess_inv = sess_inv_map.get(p_id)
            expected_qty = sess_inv.current_remaining_quantity if sess_inv else 0

            if response_status == 'accepted':
                # الدرع الفولاذي: منع الرصيد السالب
                if transfer.quantity_packs < 0 and (not sess_inv or sess_inv.current_remaining_quantity + transfer.quantity_packs < 0):
                    db.session.rollback()
                    return jsonify({"message": f"فشل: رصيدك من {variant.variant_name if variant else p_id} لا يكفي للسحب."}), 400

                if sess_inv:
                    sess_inv.current_remaining_quantity += transfer.quantity_packs
                    sess_inv.starting_quantity += transfer.quantity_packs
                else:
                    sess_inv = SessionInventory(work_session_id=transfer.work_session_id, product_variant_id=p_id, 
                                               starting_quantity=transfer.quantity_packs, current_remaining_quantity=transfer.quantity_packs)
                    db.session.add(sess_inv)

                if route:
                    safe_packs = variant.packs_per_carton if variant and variant.packs_per_carton else 1
                    delta_cartons = transfer.quantity_packs // safe_packs
                    v_load = v_load_map.get(p_id)
                    if v_load: v_load.quantity += delta_cartons
                    else: db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=p_id, quantity=delta_cartons))

            # +++ تم تنظيف السطر من transfer.notes لتجنب الانهيار +++
            db.session.add(InventoryLedger(
                work_session_id=transfer.work_session_id, driver_id=driver_id, vehicle_id=route.vehicle_id if route else None,
                product_variant_id=p_id, transaction_type=f'Batch {response_status.capitalize()}',
                expected_quantity=expected_qty, actual_quantity=expected_qty + (transfer.quantity_packs if response_status == 'accepted' else 0),
                difference=transfer.quantity_packs if response_status == 'accepted' else 0, admin_id=transfer.admin_id,
                notes=f"معالجة جماعية - رقم الحوالة: {transfer.id}"
            ))

        db.session.commit()
        return jsonify({"message": f"تمت معالجة {len(transfers)} أصناف بنجاح."}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "خطأ داخلي في المعالجة الجماعية."}), 500

# =========================================
# 5.6 التحقق من وجود حوالات معلقة (للمندوب - Polling)
# =========================================
@api.route('/driver/transfers/pending', methods=['GET'])
@token_required
def get_pending_transfers():
    driver_id = getattr(g, 'current_driver_id', None)
    
    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
    if not active_session:
        return jsonify([]), 200
        
    pending_transfers = InventoryTransfer.query.options(joinedload(InventoryTransfer.product_variant)).filter_by(
        work_session_id=active_session.id, 
        status='pending'
    ).all()
    
    # +++ العودة للمسار الاحترافي: الاعتماد على عمود notes الرسمي للدمج +++
    batches = {}
    for t in pending_transfers:
        batch_id = t.notes if (t.notes and "BATCH_" in t.notes) else f"SINGLE_{t.id}"
        
        if batch_id not in batches:
            # نضع transfer_id كخدعة لكي لا ينهار الـ Bloc في الموبايل
            batches[batch_id] = {
                "transfer_id": batch_id, 
                "created_at": t.created_at.isoformat() if t.created_at else None, 
                "items": []
            }
            
        variant = t.product_variant
        packs = variant.packs_per_carton if variant and variant.packs_per_carton else 1
        
        batches[batch_id]["items"].append({
            "real_transfer_id": t.id,
            "product_name": variant.variant_name if variant else "غير معروف",
            "delta_cartons": t.quantity_packs // packs,
            "delta_packs": t.quantity_packs % packs
        })
        
    return jsonify(list(batches.values())), 200

# =========================================
# 6. إضافة محل جديد
# =========================================
@api.route('/shops', methods=['POST'])
@token_required
def add_new_shop():
    driver_id = getattr(g, 'current_driver_id', None)
    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
    if not active_session:
        return jsonify({"message": "مرفوض: الرجاء بدء يوم العمل أولاً."}), 403
        
    # +++ الكي الجراحي: جلب خط السير النشط لمنع كارثة "المحل الشبح" +++
    active_route = DispatchRoute.query.filter_by(work_session_id=active_session.id, status='active').first()
    if not active_route:
        return jsonify({"message": "مرفوض: لا يوجد لديك خط سير نشط لربط المحل الجديد به."}), 403
    if active_session.break_start_time and not active_session.break_end_time:
        return jsonify({"message": "أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل."}), 403
    if not active_session.is_authorized_to_sell:
        return jsonify({"message": "مرفوض: غير مصرح لك بإضافة محلات حالياً. بانتظار تفعيل خط السير من الإدارة."}), 403
        
    data = request.get_json(silent=True) or {}
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
        # +++ حماية الفراغات (Empty Strings) للإحداثيات لتجنب ValueError و 500 Crash +++
        raw_lat = str(data.get('latitude') or '').strip()
        raw_lng = str(data.get('longitude') or '').strip()
        lat_val = float(raw_lat) if raw_lat else None
        lng_val = float(raw_lng) if raw_lng else None

        new_shop = Shop(
            name=name,
            address=address,
            phone_number=phone,
            contact_person=data.get('contact_person'),
            notes=data.get('notes'),
            location_link=data.get('location_link'),
            latitude=lat_val,
            longitude=lng_val,
            zone_id=active_route.zone_id, # +++ ربط المحل بمنطقة المندوب الحالية فوراً لكي لا يطرده النظام +++
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
        return jsonify({"message": "Failed to add shop", "error": "Internal Server Error"}), 500
    
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
        # +++ تحويل القيمة المالية إلى float لمنع خطأ النوع في فلاتر +++
        "price_per_carton": float(v.price_per_carton or 0.0), 
        "packs_per_carton": v.packs_per_carton,
        "price_per_pack": float(v.price_per_pack or 0.0),
    } for v in variants]), 200


@api.route('/driver/<int:driver_id>/visits', methods=['GET'])
@token_required
def get_visits(driver_id):
    # +++ الدرع الفولاذي: نسف ثغرة التجسس (IDOR) لمنع المندوب من سرقة بيانات غيره +++
    if getattr(g, 'current_driver_id', None) != driver_id:
        return jsonify({"message": "مرفوض أمنياً: محاولة اختراق أو وصول غير مصرح به لبيانات مندوب آخر."}), 403

    # 1. جلب الجلسة النشطة حالياً للمندوب
    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
    
    # +++ سد ثغرة تسرب المحلات: جلب المحلات المخصصة للمندوب فقط +++
    active_route = DispatchRoute.query.filter(
        DispatchRoute.driver_id == driver_id, 
        DispatchRoute.status.in_(['active', 'waiting', 'postponed'])
    ).first()
    
    if not active_route:
        return jsonify([]), 200 # نمنع المحلات فقط إذا تم سحب المنطقة منه بالكامل

    # +++ الدرع الفولاذي لمنع تداخل المناطق وتسريب المحلات المنجزة +++
    # القاعدة: نجلب المحل فقط إذا كان: (معلقاً ويتبع للمنطقة الحالية) أو (تم إنجازه في جلسة اليوم حصراً) أو (طلب عاجل)
    condition = db.or_(
        db.and_(Visit.status == 'Pending', Shop.zone_id == active_route.zone_id),
        Visit.work_session_id == (active_session.id if active_session else -1),
        Visit.is_emergency == True
    )

    visits_query = Visit.query.join(Shop).options(joinedload(Visit.shop)).filter(
        Visit.driver_id == driver_id,
        Shop.is_archived == False,
        condition
    )

    # +++ التطابق المطلق: إجبار الموبايل على فرز الزيارات بناءً على الترتيب الحي للمحلات (Shop.sequence) +++
    if active_session:
        visits = visits_query.filter((Visit.status == 'Pending') | (Visit.work_session_id == active_session.id)).order_by(Shop.sequence.asc().nulls_last(), Visit.id.asc()).all()
    else:
        visits = visits_query.filter(Visit.status == 'Pending').order_by(Shop.sequence.asc().nulls_last(), Visit.id.asc()).all()

    visits_data = [{
        "visit_id": v.id, 
        "shop_id": v.shop_id, 
        "shop_name": v.shop.name,
        "shop_location_link": v.shop.location_link, 
        "shop_latitude": v.shop.latitude,
        "shop_longitude": v.shop.longitude,
        "shop_balance": float(v.shop.current_balance or 0.0),
        "max_debt_limit": float(v.shop.max_debt_limit or 0.0),
        "shop_zone_id": v.shop.zone_id,
        "allowed_zone_id": active_route.zone_id,
        "visit_status": v.status, 
        # +++ النسف المعماري لثغرة الترتيب (Stale Data): المصدر الوحيد للحقيقة هو جدول المحل (Shop) ليتطابق مع الإدارة +++
        "visit_sequence": v.shop.sequence if v.shop.sequence is not None else 999, 
        "sequence": v.shop.sequence if v.shop.sequence is not None else 999,
        "is_emergency": v.is_emergency
    } for v in visits]

    # +++ جلب مخزون السيارة أو العهدة لإرساله مع الزيارات ليعمل الأوفلاين +++
    inventory_data = []
    if active_session:
        inventories = SessionInventory.query.options(joinedload(SessionInventory.product_variant)).filter_by(work_session_id=active_session.id).all()
        for inv in inventories:
            variant = inv.product_variant
            packs = variant.packs_per_carton if variant.packs_per_carton else 1
            inventory_data.append({
                "id": variant.id,
                "name": variant.variant_name,
                "price_per_carton": float(variant.price_per_carton or 0.0),
                "price_per_pack": float(variant.price_per_pack or 0.0),
                "packs_per_carton": packs,
                "starting_cartons": inv.starting_quantity // packs,
                "current_cartons": inv.current_remaining_quantity // packs,
                "current_packs": inv.current_remaining_quantity % packs
            })
    elif active_route:
        vehicle_loads = db.session.query(VehicleLoad, ProductVariant).join(
            ProductVariant, VehicleLoad.product_variant_id == ProductVariant.id
        ).filter(VehicleLoad.vehicle_id == active_route.vehicle_id).all()
        for load, variant in vehicle_loads:
            packs = variant.packs_per_carton if variant.packs_per_carton else 1
            inventory_data.append({
                "id": variant.id,
                "name": variant.variant_name,
                "price_per_carton": float(variant.price_per_carton or 0.0),
                "price_per_pack": float(variant.price_per_pack or 0.0),
                "packs_per_carton": packs,
                "starting_cartons": load.quantity,
                "current_cartons": load.quantity,
                "current_packs": 0
            })

    # +++ إعادة البيانات كـ Map يتطابق مع ما يتوقعه sync_repository +++
    return jsonify({
        "visits": visits_data,
        "inventory": inventory_data
    }), 200


@api.route('/visits/<int:visit_id>', methods=['GET'])
@token_required
def get_visit_details(visit_id):
    # +++ الحل المعماري الشامل: Eager Loading متسلسل لنسف N+1 بالكامل +++
    visit = Visit.query.options(
        joinedload(Visit.shop),
        joinedload(Visit.items).joinedload(VisitItem.product_variant),
        joinedload(Visit.returns) # +++ جلب التوالف لكي لا تتصفر في شاشة المندوب +++
    ).filter_by(id=visit_id).first()
    
    if not visit: return jsonify({"message": "Visit not found"}), 404
    
    # +++ الدرع الأمني لمنع تلصص المناديب على فواتير بعضهم +++
    current_driver_id = getattr(g, 'current_driver_id', None)
    admin = db.session.get(Driver, current_driver_id)
    if not admin.is_admin and visit.driver_id != current_driver_id:
        return jsonify({"message": "مرفوض: لا يحق لك الاطلاع على زيارات مناديب آخرين."}), 403
        
    shop = visit.shop
    
    cart_items = []
    # تم جلب العناصر مع تفاصيل منتجاتها مسبقاً في الاستعلام الرئيسي بكفاءة O(1)
    items = visit.items
    for item in items:
        if getattr(item, 'is_cancelled', False): continue # +++ إخفاء العناصر الملغاة (Soft Delete) +++
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
        # +++ تحويل الـ Decimal إلى Float صريح +++
        "cash_collected": float(visit.cash_collected or 0.0),
        "debt_paid": float(visit.debt_paid or 0.0),
        "notes": visit.notes,
        "no_sale_reason": visit.no_sale_reason,
        "status": visit.status,
        "shop": {"latitude": shop.latitude, "longitude": shop.longitude, "location_link": shop.location_link},
        # +++ تزويد الموبايل ببيانات التوالف المحفوظة لكي يعرضها بدلاً من الصفر +++
        "returns": [{"product_variant_id": r.product_variant_id, "quantity": r.quantity, "return_type": r.return_type, "reason": r.reason} for r in visit.returns if not getattr(r, 'is_cancelled', False)] # +++ حجب الملغى +++
    }), 200

@api.route('/driver/<int:driver_id>/sessions/active', methods=['GET'])
@token_required
def get_active_session(driver_id):
    # +++ الدرع الفولاذي: منع التجسس على جلسات المناديب الآخرين +++
    if getattr(g, 'current_driver_id', None) != driver_id:
        return jsonify({"message": "مرفوض أمنياً."}), 403
        
    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
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

    data = request.get_json(silent=True) or {}
    is_authorized = data.get('is_authorized', True)

    try:
        session.is_authorized_to_sell = is_authorized
        db.session.commit()
        return jsonify({"message": "تم تحديث صلاحية البيع بنجاح"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في التحديث", "error": "Internal Server Error"}), 500

# 8.2 جلب ملخص كل الجلسات النشطة اليوم (لشاشة المدير الرئيسية / غرفة العمليات)
@api.route('/admin/sessions/today', methods=['GET'])
@token_required
def get_admin_dashboard_data():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض أمنياً: هذه الداشبورد مخصصة للجنرالات فقط، وليس للجنود المتسللين."}), 403

    # +++ النسف المعماري لثقب الزمن (Timezone Bermuda Triangle): توحيد تقويم السيرفر مع الداتابيز (UTC) لمنع ضياع جلسات الفجر +++
    today_date = datetime.now(timezone.utc).date()
    
    # +++ الدرع الفولاذي: حماية السيرفر من الانهيار (OOM) عبر تجاهل الجلسات المعلقة منذ أكثر من 14 يوماً +++
    limit_date = today_date - timedelta(days=14)
    sessions = WorkSession.query.options(joinedload(WorkSession.driver)).filter(
        (func.date(WorkSession.start_time) == today_date) | 
        (db.and_(WorkSession.is_settled == False, func.date(WorkSession.start_time) >= limit_date))
    ).all()
    
    # +++ النسف المعماري لـ N+1 في الداشبورد +++
    session_ids = [s.id for s in sessions]
    stats_map = {}
    pending_map = {}
    inv_map = {}
    
    if session_ids:
        stats_query = db.session.query(
            Visit.work_session_id,
            func.count(Visit.id).label('total_visits'),
            func.sum(Visit.cash_collected).label('total_cash'),
            func.sum(Visit.debt_paid).label('total_debt')
        ).filter(Visit.work_session_id.in_(session_ids), Visit.status == 'Completed').group_by(Visit.work_session_id).all()
        stats_map = {r.work_session_id: r for r in stats_query}
        
        driver_ids = [s.driver_id for s in sessions]
        # +++ الدرع الفولاذي: عد الزيارات المعلقة المرتبطة بجلسة اليوم أو تاريخ اليوم فقط لمنع التضخم الوهمي +++
        pending_query = db.session.query(
            Visit.driver_id, func.count(Visit.id)
        ).filter(
            Visit.driver_id.in_(driver_ids), 
            Visit.status == 'Pending',
            db.or_(Visit.work_session_id.in_(session_ids), func.date(Visit.visit_timestamp) == today_date)
        ).group_by(Visit.driver_id).all()
        pending_map = {r.driver_id: r[1] for r in pending_query}
        
        inventories = SessionInventory.query.options(joinedload(SessionInventory.product_variant)).filter(SessionInventory.work_session_id.in_(session_ids)).all()
        for inv in inventories:
            if inv.work_session_id not in inv_map: inv_map[inv.work_session_id] = []
            inv_map[inv.work_session_id].append(inv)
    # ++++++++++++++++++++++++++++++++++++++++

    drivers_data = []
    for session in sessions:
        driver = session.driver
        if not driver or not driver.is_active or driver.is_admin:
            continue
            
        session_id = session.id
        start_time = session.start_time.isoformat() if session.start_time else None
        is_authorized = session.is_authorized_to_sell
        is_on_break = bool(session.break_start_time and not session.break_end_time)
        
        # حساب الزيارات والمالية باستخدام الذاكرة O(1)
        stats = stats_map.get(session.id)

        completed_total = stats.total_visits if stats else 0
        cash_from_sales = float(stats.total_cash or 0.0) if (stats and stats.total_cash) else 0.0
        cash_from_debts = float(stats.total_debt or 0.0) if (stats and stats.total_debt) else 0.0
        expected_cash_in_hand = cash_from_sales + cash_from_debts
        
        pending_remaining = pending_map.get(session.driver_id, 0)
        
        # جرد المخزون باستخدام الذاكرة O(1)
        inventories = inv_map.get(session.id, [])
        
        inv_list = []
        for inv in inventories:
            variant = inv.product_variant
            # +++ استخراج التعبئة للتحويل من حبات إلى كراتين +++
            packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton > 0 else 1
            
            started_cartons = inv.starting_quantity // packs_per_carton
            remaining_cartons = inv.current_remaining_quantity // packs_per_carton
            sold_cartons = started_cartons - remaining_cartons

            inv_list.append({
                "product_id": inv.product_variant_id,
                "product_name": variant.variant_name,
                "starting_quantity": started_cartons,
                "sold_quantity": sold_cartons,
                "remaining_quantity": remaining_cartons
            })
        
        # تحديد الحالة
        if session.is_settled:
            status = "تمت التسوية"
        elif session.end_time:
            status = "مغلقة بانتظار التسوية"
        elif is_on_break:
            status = "استراحة"
        else:
            status = "في الطريق"
            
        # إذا تمت التسوية وهي ليست من اليوم، لا نعرضها لعدم زحمة الشاشة
        if session.is_settled and session.start_time and session.start_time.date() != today_date:
            continue

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
        
    def get_status_rank(d):
        s = d['settlement']['status']
        if s == "في الطريق": return 1
        if s == "استراحة": return 2
        if s == "مغلقة بانتظار التسوية": return 3
        return 4
        
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

# 8.4 اعتماد التسوية اليومية لجلسة المندوب واستلام الجرد الفعلي
@api.route('/admin/sessions/<int:session_id>/settle', methods=['PUT'])
@token_required
def settle_session(session_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    # +++ الدرع الفولاذي: قفل الجلسة (Row-Level Lock) لمنع كارثة الدبل-كليك وتسجيل العجز مرتين +++
    session = db.session.query(WorkSession).with_for_update().filter_by(id=session_id).first()
    if not session:
        return jsonify({"message": "الجلسة غير موجودة"}), 404

    if session.is_settled:
        return jsonify({"message": "تم اعتماد تسوية هذه الجلسة مسبقاً ولا يمكن التعديل عليها."}), 400

    if not session.end_time:
        return jsonify({"message": "مرفوض: لا يمكن تسوية الجلسة لأن المندوب لم يقم بإنهاء العمل."}), 400

    data = request.get_json(silent=True) or {}
    # +++ الدرع المحاسبي: حماية التسوية من أخطاء الكتابة (Typos) التي تفجر الـ Decimal +++
    raw_cash = str(data.get('actual_cash') or '0.0').strip()
    try:
        actual_cash_dec = Decimal(raw_cash) if raw_cash else Decimal('0.0')
    except Exception:
        actual_cash_dec = Decimal('0.0')
    inventory_jard = data.get('inventory_jard', [])

    try:
        # 1. حساب العجز/الزيادة المالية
        stats = db.session.query(
            func.sum(Visit.cash_collected).label('total_cash'),
            func.sum(Visit.debt_paid).label('total_debt')
        ).filter(Visit.work_session_id == session.id, Visit.status == 'Completed').first()
        
        # +++ التطهير المحاسبي: حساب الماليات بـ Decimal نقي لمنع غبار الكسور العشرية +++
        expected_cash_dec = Decimal(str(stats.total_cash or '0.0')) + Decimal(str(stats.total_debt or '0.0'))
        cash_difference_dec = actual_cash_dec - expected_cash_dec
        cash_difference = float(cash_difference_dec) # التحويل النهائي للـ JSON فقط

        # 2. معالجة الجرد المستودعي (اكتشاف العجز/الزيادة وتسجيلها)
        # نحتاج معرفة السيارة المرتبطة بالجلسة لتسجيلها في الدفتر
        route = DispatchRoute.query.filter_by(work_session_id=session.id).first()
        
        # +++ النسف المعماري الشامل (تطبيق قانون أبو علي): جلب كل العهدة، وليس فقط ما جرده المشرف +++
        all_session_inv = SessionInventory.query.filter_by(work_session_id=session.id).all()
        bulk_inv_records = {inv.product_variant_id: inv for inv in all_session_inv}
        
        all_var_ids = list(bulk_inv_records.keys())
        bulk_variants = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(all_var_ids)).all()} if all_var_ids else {}

        # 1. معالجة الجرد المدخل من المشرف (تحديث العهدة الحية وكتابة الفروقات)
        for item in inventory_jard:
            raw_id = item.get('product_id')
            if raw_id is None: continue
            prod_id = int(raw_id)
            
            raw_actual = str(item.get('actual') or '0').strip()
            actual_qty = int(raw_actual) if raw_actual else 0
            
            inv_record = bulk_inv_records.get(prod_id)
            if inv_record:
                expected_qty = inv_record.current_remaining_quantity
                difference = actual_qty - expected_qty
                
                if difference != 0:
                    t_type = 'Surplus' if difference > 0 else 'Deficit'
                    db.session.add(InventoryLedger(
                        work_session_id=session.id, driver_id=session.driver_id, vehicle_id=route.vehicle_id if route else None,
                        product_variant_id=prod_id, transaction_type=t_type, expected_quantity=expected_qty,
                        actual_quantity=actual_qty, difference=difference, admin_id=admin.id,
                        notes=f"تسوية نهاية اليوم. المتوقع: {expected_qty}، الفعلي المستلم: {actual_qty}"
                    ))
                inv_record.current_remaining_quantity = actual_qty

        # 2. ترحيل البضاعة للسيارة (سواء جردها المشرف أو نسيها، نعتمد الرصيد النهائي الموثق)
        if route and route.vehicle_id:
            VehicleLoad.query.filter_by(vehicle_id=route.vehicle_id).delete() # تنظيف استباقي للسيارة
            for inv_record in all_session_inv:
                prod_id = inv_record.product_variant_id
                final_qty = inv_record.current_remaining_quantity
                
                variant = bulk_variants.get(prod_id)
                packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton else 1
                
                actual_cartons = final_qty // packs_per_carton
                loose_packs = final_qty % packs_per_carton
                
                if loose_packs > 0:
                    db.session.add(InventoryLedger(
                        work_session_id=session.id, driver_id=session.driver_id, vehicle_id=route.vehicle_id,
                        product_variant_id=prod_id, transaction_type='Warehouse Return',
                        expected_quantity=loose_packs, actual_quantity=0, difference=-loose_packs,
                        admin_id=admin.id, notes="تصفير الفراطة: تم سحب الحبات المفتوحة وإعادتها للمستودع الرئيسي نهاية اليوم"
                    ))
                
                if actual_cartons > 0:
                    db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=prod_id, quantity=actual_cartons))

        # 3. إغلاق العهدة
        session.is_settled = True
        
        # 4. فصل الجلسة المالية عن خط السير، مع إبقاء المنطقة للمندوب لليوم التالي
        # +++ تم حذف الاستعلام المكرر واستخدام كائن route الذي تم جلبه في بداية الدالة +++
        if route:
            route.work_session_id = None
            # +++ تم حذف تغيير حالة المنطقة (status). ستبقى 'active' وظاهرة للمندوب +++

        db.session.commit()
        return jsonify({
            "message": "تم اعتماد التسوية بنجاح", 
            "cash_difference": cash_difference,
            "is_settled": True
        }), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "خطأ في اعتماد التسوية", "error": "Internal Server Error"}), 500

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

    today = datetime.now(timezone.utc).date()
    zones_data = []
    for z in zones:
        # +++ استخدام الذاكرة المسبقة (O(1)) بدلاً من استعلام مهدر داخل الحلقة +++
        shops_count = shop_count_map.get(z.id, 0)
        
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

    data = request.get_json(silent=True) or {}
    zone_id = data.get('zone_id')
    driver_id = data.get('driver_id')
    vehicle_id = data.get('vehicle_id')
    inventory = data.get('inventory', {}) # +++ استلام جرد الحمولة +++

    if not all([zone_id, driver_id, vehicle_id]):
        return jsonify({"message": "يرجى توفير المنطقة، المندوب، والسيارة."}), 400

    # +++ قفل التزامن الفولاذي (Row-Level Lock): لمنع استنساخ خطوط السير إذا ضغط أكثر من مشرف بنفس اللحظة +++
    driver_lock = db.session.query(Driver).with_for_update().filter_by(id=driver_id).first()
    if not driver_lock:
        return jsonify({"message": "المندوب غير موجود."}), 404

    # +++ الحماية المعمارية المرنة (Senior Logic) +++
    # 1. المنطقة (Zone): تقفل تماماً إذا كانت (نشطة، انتظار، أو مؤجلة) لمنع التضارب الجغرافي.
    if DispatchRoute.query.filter(DispatchRoute.status.in_(['active', 'waiting', 'postponed']), DispatchRoute.zone_id == zone_id).first():
        return jsonify({"message": "⚠️ المنطقة المحددة قيد العمل أو مؤجلة مسبقاً. الرجاء إغلاقها أو تحويلها أولاً."}), 409
    
    # 2. المندوب (Driver): يُقفل فقط إذا كان لديه خط (نشط أو قيد الانتظار). يُسمح له بخط جديد إذا كان خطه القديم (مؤجل).
    if DispatchRoute.query.filter(DispatchRoute.status.in_(['active', 'waiting']), DispatchRoute.driver_id == driver_id).first():
        return jsonify({"message": "⚠️ المندوب المختار لديه خط سير نشط أو قيد الانتظار حالياً."}), 409
        
    # 3. السيارة (Vehicle): تُقفل فقط إذا كانت في خط (نشط أو قيد الانتظار).
    if DispatchRoute.query.filter(DispatchRoute.status.in_(['active', 'waiting']), DispatchRoute.vehicle_id == vehicle_id).first():
        return jsonify({"message": "⚠️ السيارة المحددة مستخدمة في خط سير نشط أو قيد الانتظار حالياً."}), 409

    try:
        new_route = DispatchRoute(zone_id=zone_id, driver_id=driver_id, vehicle_id=vehicle_id, status='active')
        db.session.add(new_route)

        # +++ حماية العهدة والجرد (السيناريو المعماري الجديد) +++
        # نتحقق: هل المندوب لديه جلسة عمل (عهدة) نشطة حالياً؟
        active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
        
        # +++ النسف المعماري لـ N+1 أثناء الجرد وتوحيد القياس (الكراتين إلى حبات) +++
        if inventory is not None:
            # +++ الدرع الفولاذي: السماح بقيم الصفر للعمل، وحجب الفراغات فقط +++
            prod_ids = [int(p) for p, q in inventory.items() if str(q).strip() != '']
            bulk_variants = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(prod_ids)).all()} if prod_ids else {}
            
            if not active_session:
                # إذا لم يبدأ يومه بعد (صباحاً)، نعتمد الجرد المدخل كحمولة جديدة للسيارة
                VehicleLoad.query.filter_by(vehicle_id=vehicle_id).delete()
                for prod_id, qty in inventory.items():
                    # +++ حماية السيرفر من أخطاء إدخال المشرفين (ValueError) +++
                    try:
                        qty_cartons = int(str(qty).strip())
                        p_id = int(str(prod_id).strip())
                    except ValueError:
                        continue # تجاهل النص الخاطئ بدل إسقاط السيرفر
                        
                    if qty_cartons > 0:
                        db.session.add(VehicleLoad(vehicle_id=vehicle_id, product_variant_id=p_id, quantity=qty_cartons))
                        # (تحويل الكراتين إلى حبات سيتم عند بدء الجلسة في start_work_session)
            else:
                # +++ المعالجة الذكية والموحدة لتزويد السيارة منتصف اليوم عبر إطلاق السير (نظام المصافحة) +++
                bulk_vloads = {vl.product_variant_id: vl for vl in VehicleLoad.query.filter(VehicleLoad.vehicle_id == vehicle_id, VehicleLoad.product_variant_id.in_(prod_ids)).all()} if prod_ids and vehicle_id else {}
                bulk_sinvs = {si.product_variant_id: si for si in SessionInventory.query.filter(SessionInventory.work_session_id == active_session.id, SessionInventory.product_variant_id.in_(prod_ids)).all()} if prod_ids else {}

                for prod_id, new_qty_str in inventory.items():
                    if str(new_qty_str).strip() == '': continue # نتجاوز الفراغات فقط
                    new_actual_qty_cartons = int(new_qty_str)
                    # +++ نسف حصانة المندوب: الصفر (0) هو قيمة جرد حقيقية تعني سحب الكمية بالكامل +++
                    
                    p_id = int(prod_id)
                    variant = bulk_variants.get(p_id)
                    if not variant: continue

                    # +++ الكيّ الجراحي المعماري: حساب الفرق بناءً على عهدة الشارع الحية +++
                    sess_inv = bulk_sinvs.get(p_id)
                    current_live_packs = sess_inv.current_remaining_quantity if sess_inv else 0
                    current_live_cartons = current_live_packs // variant.packs_per_carton
                    
                    # 1. حساب الفرق (الدلتا) بين ما يطلبه المشرف وبين ما يحمله المندوب فعلياً
                    delta_cartons = new_actual_qty_cartons - current_live_cartons
                    
                    # 2. تحديث حمولة السيارة للإدارة لتطابق الرقم الجديد (حتى لو الدلتا صفر)
                    v_load = bulk_vloads.get(p_id)
                    if v_load: v_load.quantity = new_actual_qty_cartons
                    else: db.session.add(VehicleLoad(vehicle_id=vehicle_id, product_variant_id=p_id, quantity=new_actual_qty_cartons))

                    if delta_cartons == 0: continue # لا داعي لإزعاج المندوب بحوالة وهمية

                    # 3. إرسال الدلتا الحقيقية كحوالة معلقة للمندوب
                    delta_packs = delta_cartons * variant.packs_per_carton
                    new_transfer = InventoryTransfer(
                        work_session_id=active_session.id,
                        product_variant_id=p_id,
                        quantity_packs=delta_packs,
                        status='pending',
                        admin_id=admin.id
                    )
                    db.session.add(new_transfer)

        # +++ التوليد الذكي والمضاد للاستنساخ (تبني الأيتام) أثناء إطلاق الخط +++
        shops_in_zone = Shop.query.filter_by(zone_id=zone_id, is_active=True, is_archived=False).all()
        shop_ids = [s.id for s in shops_in_zone]
        
        today = datetime.now(timezone.utc).date()
        
        # 1. المطالبة بالزيارات المعلقة (الأيتام) التي تم تحريرها سابقاً عند سحب المنطقة
        orphaned_visits = Visit.query.filter(
            Visit.shop_id.in_(shop_ids),
            Visit.status == 'Pending',
            Visit.driver_id == None
        ).all()
        for v in orphaned_visits:
            v.driver_id = driver_id # المندوب الجديد يتبنى المحل اليتيم
            
        # 2. جلب كل الزيارات الموجودة اليوم لهذا المندوب (بما فيها التي تبناها للتو)
        existing_visits = Visit.query.filter(
            Visit.driver_id == driver_id,
            Visit.shop_id.in_(shop_ids),
            db.or_(Visit.status == 'Pending', func.date(Visit.visit_timestamp) == today)
        ).all()
        # +++ النسف المعماري: خريطة ذاكرة (O(1)) بدل اللوب القاتل +++
        existing_visits_map = {v.shop_id: v for v in existing_visits}
        visited_shop_ids = set(existing_visits_map.keys())

        # 3. جلب الطلبات العاجلة المعلقة لهذه المحلات
        pending_shortages = ShortageRequest.query.filter(ShortageRequest.shop_id.in_(shop_ids), ShortageRequest.status == 'pending').all()
        shortage_shop_ids = {s.shop_id for s in pending_shortages}

        for shop in shops_in_zone:
            is_emerg = shop.id in shortage_shop_ids
            if shop.id not in visited_shop_ids:
                # إنشاء زيارة جديدة فقط إذا لم تكن هناك زيارة مسبقة
                new_visit = Visit(
                    driver_id=driver_id,
                    shop_id=shop.id,
                    status='Pending',
                    sequence=shop.sequence,
                    is_emergency=is_emerg
                )
                db.session.add(new_visit)
            else:
                # +++ جلب مباشر وسريع من الخريطة O(1) +++
                visit_to_update = existing_visits_map.get(shop.id)
                if visit_to_update and is_emerg:
                     visit_to_update.is_emergency = True

        db.session.commit()
        return jsonify({"message": "تم إطلاق خط السير بنجاح"}), 201
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "خطأ في إطلاق خط السير", "error": "Internal Server Error"}), 500

# =========================================
# 9.1 جلب الحمولة الافتتاحية للسيارة (للإدارة والمستودع)
# =========================================
@api.route('/dispatch/inventory/<int:vehicle_id>', methods=['GET'])
@token_required
def get_vehicle_inventory(vehicle_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    # +++ النسف المعماري لسيارة الأشباح: الربط الصارم عبر رقم الجلسة المباشر لمنع تداخل أرواح المندوبين +++
    unsettled_session = db.session.query(WorkSession).join(
        DispatchRoute, DispatchRoute.work_session_id == WorkSession.id
    ).filter(
        DispatchRoute.vehicle_id == vehicle_id,
        WorkSession.is_settled == False
    ).order_by(WorkSession.id.desc()).first()

    inventory_map = {}
    is_live = False

    if unsettled_session:
        is_live = True
        # السيارة "عهدة في الشارع": نقرأ من جرد الجلسة المرتبطة بها حصراً
        sess_invs = SessionInventory.query.filter_by(work_session_id=unsettled_session.id).all()
        for inv in sess_invs:
            inventory_map[inv.product_variant_id] = inv.current_remaining_quantity
    else:
        # السيارة "نائمة في المستودع": نقرأ حمولة السيارة المعتمدة (بعد التصفية)
        loads = VehicleLoad.query.filter_by(vehicle_id=vehicle_id).all()
        for l in loads:
            inventory_map[l.product_variant_id] = l.quantity

    variants = ProductVariant.query.filter_by(is_active=True).all()
    result = []
    for v in variants:
        qty = inventory_map.get(v.id, 0)
        packs = v.packs_per_carton if v.packs_per_carton and v.packs_per_carton > 0 else 1
        
        # إذا كان الجرد حياً، نحول الحبات لكراتين. إذا كان من السيارة، فهو كراتين أصلاً.
        current_quantity = (qty // packs) if is_live else qty

        result.append({
            "product_id": str(v.id),
            "product_name": v.variant_name,
            "current_quantity": current_quantity 
        })

    return jsonify(result), 200

# =========================================
# 9.2 جلب الجرد اللحظي (الحي) لسيارة المندوب بالشارع (In-Van)
# =========================================
@api.route('/dispatch/route/<int:route_id>/live_inventory', methods=['GET'])
@token_required
def get_route_live_inventory(route_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    route = db.session.get(DispatchRoute, route_id)
    if not route or not route.driver_id:
        return jsonify({"message": "خط السير غير موجود أو غير مرتبط بمندوب."}), 404

    active_session = WorkSession.query.filter_by(driver_id=route.driver_id, end_time=None).first()
    
    # +++ المعالجة الذكية: إذا لم يبدأ المندوب، نقرأ من حمولة السيارة. إذا بدأ، نقرأ من عهدته +++
    inventory_map = {}
    pending_withdrawals_map = {}
    if active_session:
        inventories = SessionInventory.query.filter_by(work_session_id=active_session.id).all()
        inventory_map = {inv.product_variant_id: inv for inv in inventories}
        
        # +++ تصحيح خيانة العرض (Lying Dashboard): جلب السحوبات المعلقة لعرض الرصيد المتاح الفعلي +++
        pending_transfers_query = db.session.query(
            InventoryTransfer.product_variant_id, 
            func.sum(InventoryTransfer.quantity_packs)
        ).filter(
            InventoryTransfer.work_session_id == active_session.id,
            InventoryTransfer.status == 'pending',
            InventoryTransfer.quantity_packs < 0
        ).group_by(InventoryTransfer.product_variant_id).all()
        pending_withdrawals_map = {v_id: total for v_id, total in pending_transfers_query}
    else:
        loads = VehicleLoad.query.filter_by(vehicle_id=route.vehicle_id).all()
        # نضعها في شكل وهمي يشبه الـ SessionInventory لتوحيد الرد
        class DummyInv:
            def __init__(self, qty, packs_per_carton):
                self.current_remaining_quantity = qty * (packs_per_carton if packs_per_carton else 1)
        
        variants_for_load = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_([l.product_variant_id for l in loads])).all()}
        inventory_map = {l.product_variant_id: DummyInv(l.quantity, variants_for_load.get(l.product_variant_id).packs_per_carton if variants_for_load.get(l.product_variant_id) else 1) for l in loads}

    variants = ProductVariant.query.filter_by(is_active=True).all()
    result = []
    for v in variants:
        inv = inventory_map.get(v.id)
        packs = v.packs_per_carton if v.packs_per_carton and v.packs_per_carton > 0 else 1
        
        # +++ خصم الحوالات المعلقة (السالبة) من الرصيد الحي لمنع المشرف من تكرار السحب +++
        pending_packs = pending_withdrawals_map.get(v.id, 0)
        actual_remaining_packs = (inv.current_remaining_quantity + pending_packs) if inv else 0
        
        current_cartons = actual_remaining_packs // packs if actual_remaining_packs > 0 else 0
        current_packs = actual_remaining_packs % packs if actual_remaining_packs > 0 else 0
        
        result.append({
            "product_id": str(v.id),
            "product_name": v.variant_name,
            "current_cartons": current_cartons,
            "current_packs": current_packs
        })

    return jsonify(result), 200

# =========================================
# 9.3 تعديل الحمولة اللحظي (بالزيادة والنقصان) مع توثيق الحركة
# =========================================
@api.route('/dispatch/route/<int:route_id>/adjust_inventory', methods=['PUT'])
@token_required
def adjust_route_inventory(route_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: هذه العملية تتطلب صلاحيات إدارة."}), 403

    route = db.session.get(DispatchRoute, route_id)
    if not route or not route.driver_id:
        return jsonify({"message": "خط السير غير موجود أو غير مرتبط بمندوب."}), 404

    # +++ الدرع المعماري: تحديد حالة الجلسة بدقة (نشط، بانتظار تسوية، أو نائم) +++
    # نجلب أي جلسة لم يتم تسويتها بعد
    unsettled_session = WorkSession.query.filter_by(driver_id=route.driver_id, is_settled=False).order_by(WorkSession.id.desc()).first()
    
    # إذا كانت الجلسة في "غرفة الانتظار" (أنهى العمل وبانتظار المحاسب)، نمنع التعديل تماماً
    if unsettled_session and unsettled_session.end_time:
        return jsonify({"message": "مرفوض: لا يمكن تعديل الجرد لأن المندوب أنهى عمله وبانتظار التسوية المالية. قم باعتماد التسوية أولاً أو تراجع عن إنهاء العمل."}), 403

    active_session = unsettled_session if (unsettled_session and not unsettled_session.end_time) else None
    
    data = request.get_json(silent=True) or {}
    deltas = data.get('deltas', []) # List of {product_id, delta_cartons}
    
    if not deltas:
        return jsonify({"message": "لم يتم إرسال أي تعديلات."}), 400

    try:
        # +++ قفل التزامن الجراحي (Row-Level Lock): قفل الجلسة لمنع المشرف من إرسال حوالات مزدوجة (Double-Tap) +++
        if active_session:
            db.session.query(WorkSession).with_for_update().filter_by(id=active_session.id).first()

        # +++ النسف المعماري لـ N+1: جلب البيانات دفعة واحدة +++
        prod_ids = [int(item['product_id']) for item in deltas]
        variants_map = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(prod_ids)).all()}
        bulk_vloads = {vl.product_variant_id: vl for vl in VehicleLoad.query.filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(prod_ids)).all()}
        
        # جلب عهدة المندوب فقط إذا كان يعمل حالياً
        bulk_sinvs = {}
        pending_withdrawals_map = {}
        if active_session:
            bulk_sinvs = {si.product_variant_id: si for si in SessionInventory.query.filter(SessionInventory.work_session_id == active_session.id, SessionInventory.product_variant_id.in_(prod_ids)).all()}
            
            # +++ النسف المعماري الحقيقي لـ N+1: جلب كل السحوبات المعلقة دفعة واحدة للذاكرة +++
            pending_transfers_query = db.session.query(
                InventoryTransfer.product_variant_id, 
                func.sum(InventoryTransfer.quantity_packs)
            ).filter(
                InventoryTransfer.work_session_id == active_session.id,
                InventoryTransfer.product_variant_id.in_(prod_ids),
                InventoryTransfer.status == 'pending',
                InventoryTransfer.quantity_packs < 0
            ).group_by(InventoryTransfer.product_variant_id).all()
            pending_withdrawals_map = {v_id: total for v_id, total in pending_transfers_query}

        # +++ تجميع الطلبات المتكررة (Aggregation) لنسف ثغرة التجزئة (Split-Payload Bypass) +++
        aggregated_deltas = {}
        for item in deltas:
            try:
                p_id = int(item['product_id'])
                d_cartons = int(str(item['delta_cartons']).strip())
                aggregated_deltas[p_id] = aggregated_deltas.get(p_id, 0) + d_cartons
            except (ValueError, TypeError):
                continue

        # +++ مرحلة التحقق الصارم لمنع السالب وحماية السيرفر من هجمات النصوص +++
        for p_id, delta_cartons in aggregated_deltas.items():
            if delta_cartons == 0: continue
                
            variant = variants_map.get(p_id)
            if not variant: continue

            # التحقق يختلف حسب حالة المندوب (نشط أم لا)
            if active_session:
                # +++ الدرع الفولاذي: حماية السيرفر من الانهيار (TypeError) إذا كان حقل التعبئة Null في الداتابيز +++
                safe_packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
                delta_packs = delta_cartons * safe_packs_per_carton
                
                sess_inv = bulk_sinvs.get(p_id)
                current_packs = sess_inv.current_remaining_quantity if sess_inv else 0
                
                # +++ الدرع الاستباقي من الذاكرة (O(1)): حساب الحوالات السالبة المعلقة لمنع الرصيد الوهمي ونسف N+1 +++
                pending_withdrawals = pending_withdrawals_map.get(p_id, 0)
                
                # pending_withdrawals قيمتها سالبة أصلاً، لذا نجمعها مباشرة مع الرصيد الحالي لمعرفة "المتاح الفعلي"
                available_packs = current_packs + pending_withdrawals 
                
                if available_packs + delta_packs < 0:
                    max_withdraw_cartons = available_packs // variant.packs_per_carton
                    return jsonify({"message": f"عذراً، المتاح فعلياً من ({variant.variant_name}) للسحب هو {max_withdraw_cartons} كرتونة فقط (بعد خصم الحوالات المعلقة)."}), 400
            else:
                v_load = bulk_vloads.get(p_id)
                current_cartons = v_load.quantity if v_load else 0
                if current_cartons + delta_cartons < 0:
                    return jsonify({"message": f"عذراً، حمولة السيارة المبدئية من ({variant.variant_name}) لا تكفي لهذا السحب."}), 400

        # +++ مرحلة التنفيذ الموحدة (Zero Trust Model) +++
        # نستخدم aggregated_deltas التي تم تنظيفها وحمايتها بدلاً من deltas الخام
        for p_id, delta_cartons in aggregated_deltas.items():
            if delta_cartons == 0: continue
            
            variant = variants_map.get(p_id)
            if not variant: continue

            if active_session:
                # الدرع الفولاذي: تأمين الـ Null من الداتابيز
                safe_packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
                delta_packs = delta_cartons * safe_packs_per_carton
                
                # +++ هندسة المصافحة الموحدة: نستخدم طابع زمني دقيق كـ Batch ID لربط الأصناف ببعضها في الموبايل +++
                batch_timestamp = str(int(time.time()))
                # +++ تم حذف حقل notes الوهمي لمنع الـ TypeError - سنعتمد على التوقيت أو admin_id للربط مؤقتاً +++
                # +++ النسف المعماري: ختم الدفعة كاملة بـ Batch ID واحد لربطها في الموبايل والرادار +++
                batch_timestamp = str(int(time.time()))
                new_transfer = InventoryTransfer(
                    work_session_id=active_session.id,
                    product_variant_id=p_id,
                    quantity_packs=delta_packs,
                    status='pending',
                    admin_id=admin.id,
                    notes=f"BATCH_{batch_timestamp}" # استخدمنا العمود الجديد رسمياً
                )
                db.session.add(new_transfer)
            else:
                v_load = bulk_vloads.get(p_id)
                if v_load:
                    v_load.quantity += delta_cartons
                else:
                    db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=p_id, quantity=delta_cartons))

        # +++ الدرع الرقابي: توثيق العملية الحساسة بدون قنابل الـ ValueError +++
        audit_details = " | ".join([
            f"المنتج ID:{p_id} (تغير: {delta_cartons} كرتونة)" 
            for p_id, delta_cartons in aggregated_deltas.items() if delta_cartons != 0
        ])
        
        db.session.add(SystemAuditLog(
            admin_id=admin.id,
            target_id=f"Route_{route.id}_Driver_{route.driver_id}",
            action_type="MANUAL_INVENTORY_ADJUSTMENT",
            old_value="تعديل يدوي للحمولة من المشرف",
            new_value=audit_details
        ))

        db.session.commit()
        
        msg = "تم تحديث حمولة السيارة."
        if active_session:
            msg += " تم إرسال الحوالة للمندوب، بانتظار تأكيده للاستلام لتحديث عهدته المالية."
            
        return jsonify({"message": msg}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "خطأ في تعديل الحمولة", "error": "Internal Server Error"}), 500

# =========================================
# 9.4 مراقبة حالة الحوالات المعلقة والمرفوضة (للمسؤول)
# =========================================
@api.route('/dispatch/route/<int:route_id>/transfers', methods=['GET'])
@token_required
def get_route_transfers(route_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض"}), 403

    route = db.session.get(DispatchRoute, route_id)
    if not route or not route.driver_id:
        return jsonify([]), 200

    active_session = WorkSession.query.filter_by(driver_id=route.driver_id, end_time=None).first()
    if not active_session:
        return jsonify([]), 200

    # جلب جميع الحوالات لهذه الجلسة
    transfers = InventoryTransfer.query.options(joinedload(InventoryTransfer.product_variant)).filter_by(work_session_id=active_session.id).order_by(InventoryTransfer.created_at.desc()).all()
    
    result = []
    for t in transfers:
        variant = t.product_variant
        packs_per_carton = variant.packs_per_carton if variant and variant.packs_per_carton else 1
        delta_cartons = t.quantity_packs // packs_per_carton
        
        result.append({
            "transfer_id": t.id,
            "product_name": variant.variant_name if variant else "غير معروف",
            "delta_cartons": delta_cartons,
            "status": t.status, # 'pending', 'accepted', 'rejected'
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else None,
            "batch_id": t.notes if (t.notes and "BATCH_" in t.notes) else f"SINGLE_{t.id}" # +++ إرسال المفتاح لـ React +++
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
        
    # +++ حماية السيرفر بـ Limit آمن لا يكسر واجهة React (إلى حين بناء Pagination في الفرونت إند) +++
    shops = Shop.query.order_by(Shop.sequence.asc().nulls_last(), Shop.id.asc()).limit(2000).all()
    return jsonify([{
        "id": str(s.id),
        "name": s.name,
        "owner": s.contact_person or "",
        "phone": s.phone_number or "",
        "mapLink": s.location_link or "",
        "zoneId": str(s.zone_id) if s.zone_id else "",
        # +++ تحويل الـ Decimal إلى Float صريح +++
        "initialDebt": float(s.current_balance or 0.0),
        "maxDebtLimit": float(s.max_debt_limit or 0.0),
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
        
    data = request.get_json(silent=True) or {}
    try:
        # +++ النسف المعماري لـ N+1: جلب المحلات والمناطق دفعة واحدة في الذاكرة +++
        shop_ids = [str(s.get('id')).replace('s', '') for s in data if s.get('id')]
        bulk_shops = {str(sh.id): sh for sh in Shop.query.filter(Shop.id.in_(shop_ids)).all()} if shop_ids else {}
        
        # +++ فك طلاسم السحر الأسود إلى كود نظيف ومقروء (Clean Code) +++
        zone_ids_to_check_set = set()
        for s in data:
            if s.get('archived') is False:
                shop_id_str = str(s.get('id')).replace('s', '')
                zone_id = s.get('zoneId')
                if not zone_id and shop_id_str in bulk_shops:
                    zone_id = bulk_shops[shop_id_str].zone_id
                if zone_id is not None:
                    zone_ids_to_check_set.add(zone_id)
        zone_ids_to_check = list(zone_ids_to_check_set)
        bulk_zones = {z.id: z for z in Zone.query.filter(Zone.id.in_(zone_ids_to_check)).all()} if zone_ids_to_check else {}

        for s_data in data:
            shop_id_str = str(s_data.get('id')).replace('s', '')
            shop = bulk_shops.get(shop_id_str)
            if shop:
                # الحماية الذكية: منع استعادة المحل إذا كانت منطقته مؤرشفة أو محذوفة
                is_restoring = 'archived' in s_data and s_data['archived'] == False
                if is_restoring:
                    # +++ الكي الجراحي: تحويل المتغير إلى int بأمان لمنع الـ Type Mismatch القادم من React +++
                    raw_zone = s_data.get('zoneId', shop.zone_id)
                    zone_to_check = int(raw_zone) if raw_zone else None
                    zone_exists = bulk_zones.get(zone_to_check)
                    
                    if not zone_exists or not getattr(zone_exists, 'is_active', True):
                        return jsonify({"message": f"لا يمكن استعادة المحل '{shop.name}' لأن منطقته مؤرشفة. يرجى نقله لمنطقة نشطة أولاً."}), 400

                # +++ نسف قنبلة الـ 500 Crash القادمة من React: حماية الترتيب من الفراغات (Empty Strings) +++
                if 'sequence' in s_data: 
                    raw_seq = str(s_data['sequence']).strip()
                    shop.sequence = int(raw_seq) if raw_seq.isdigit() else 999
                    
                if 'archived' in s_data: 
                    shop.is_archived = s_data['archived']
                    # الإلغاء سيتم بشكل جماعي خارج اللوب لنسف N+1
                if 'zoneId' in s_data: shop.zone_id = s_data['zoneId']
                
        # +++ كي جراحي: تحديث الزيارات للمحلات المؤرشفة دفعة واحدة خارج الحلقة +++
        archived_shop_ids = [str(s.get('id')).replace('s', '') for s in data if s.get('archived') is True]
        if archived_shop_ids:
            Visit.query.filter(Visit.shop_id.in_(archived_shop_ids), Visit.status == 'Pending').update({'status': 'Cancelled'}, synchronize_session=False)
            
        db.session.commit()
        return jsonify({"message": "تم تحديث المحلات بنجاح"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في التحديث", "error": "Internal Server Error"}), 500

# إضافة محل جديد من لوحة التحكم (مع منع التكرار الذكي)
@api.route('/dispatch/shops', methods=['POST'])
@token_required
def admin_add_shop():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة."}), 403

    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    map_link = data.get('mapLink', '').strip()
    zone_id = data.get('zoneId')
    
    # +++ حماية הـ 500 Crash من الإحداثيات الملوثة بالنصوص أو الأقواس +++
    raw_lat = str(data.get('latitude') or '').strip()
    raw_lng = str(data.get('longitude') or '').strip()
    try:
        lat = float(raw_lat) if raw_lat else None
        lng = float(raw_lng) if raw_lng else None
    except ValueError:
        lat = None
        lng = None

    # +++ حرس الحدود للإدارة: منع إنشاء دكاكين الأشباح +++
    if not name: return jsonify({"message": "مرفوض: اسم المحل إجباري"}), 400
    if not zone_id: return jsonify({"message": "مرفوض: المنطقة إجبارية لإنشاء المحل"}), 400

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
        # +++ التطهير المحاسبي ونسف الفراغات والنصوص العشوائية لمنع انهيار السيرفر (500 Crash) +++
        try:
            raw_initial_debt = str(data.get('initialDebt') or '0.0').strip()
            safe_initial_debt = Decimal(raw_initial_debt) if raw_initial_debt else Decimal('0.0')
        except Exception:
            safe_initial_debt = Decimal('0.0')
            
        try:
            raw_max_limit = str(data.get('maxDebtLimit') or '0.0').strip()
            safe_max_limit = Decimal(raw_max_limit) if raw_max_limit else Decimal('0.0')
        except Exception:
            safe_max_limit = Decimal('0.0')

        new_shop = Shop(
                name=name,
                contact_person=data.get('owner', ''),
                phone_number=phone,
                location_link=map_link,
                latitude=lat,
                longitude=lng,
                zone_id=zone_id,
                current_balance=max(Decimal('0.0'), safe_initial_debt),
                max_debt_limit=safe_max_limit,
                added_by_driver_id=admin.id,
                # +++ حماية הـ 500 Crash من الفراغات (Empty Strings) في الترتيب +++
                sequence=int(str(data.get('sequence') or '999').strip() or '999') if str(data.get('sequence') or '').strip().isdigit() else 999
            )
        db.session.add(new_shop)
        db.session.commit()
        return jsonify({"message": "تم إضافة المحل بنجاح", "shop_id": str(new_shop.id)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "خطأ في إضافة المحل", "error": "Internal Server Error"}), 500


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
    session_ended_map = {} # +++ خريطة لمعرفة حالة إنهاء العمل +++
    
    if driver_ids:
        # +++ النسف المعماري لـ "كمين الصفر": نعد المحلات المعلقة للمندوب في منطقته النشطة حالياً فقط +++
        # هذا يضمن دقة العداد حتى لو بدأ خط السير قبل أسبوع ولم ينتهِ بعد
        pending_visits_map = {}
        for r in routes:
            if r.driver_id:
                count = Visit.query.join(Shop).filter(
                    Visit.driver_id == r.driver_id,
                    Visit.status == 'Pending',
                    db.or_(Shop.zone_id == r.zone_id, Visit.is_emergency == True)
                ).count()
                pending_visits_map[r.driver_id] = count
        
        # +++ جلب حالات نهاية الجلسة +++
        sessions_info = db.session.query(WorkSession.id, WorkSession.end_time).filter(WorkSession.id.in_(session_ids)).all()
        session_ended_map = {s_id: (end_t is not None) for s_id, end_t in sessions_info}
    
    # +++ حساب المحلات (المتبقية فقط) في المنطقة التي ليس لها مندوب +++
    # نعد فقط الزيارات المحررة (الأيتام) التي لم تنجز بعد، لكي لا نظهر المحلات المنجزة كأنها متبقية
    shop_counts = db.session.query(
        Shop.zone_id, func.count(Visit.id)
    ).join(Visit, Shop.id == Visit.shop_id).filter(
        Shop.is_active == True,
        Shop.is_archived == False,
        Visit.status == 'Pending',
        Visit.driver_id == None
    ).group_by(Shop.zone_id).all()
    zone_shops_map = {z_id: count for z_id, count in shop_counts}

    res = []
    for r in routes:
        # إذا كان الخط نشطاً والمندوب موجوداً، احسب الزيارات المعلقة للمندوب.
        # أما إذا كان موقوفاً أو بدون مندوب، فالمحلات المتبقية هي كل محلات المنطقة.
        if r.status == 'active' and r.driver_id:
            shops_remaining = pending_visits_map.get(r.driver_id, 0)
        else:
            shops_remaining = zone_shops_map.get(r.zone_id, 0)
            
        session_ended = session_ended_map.get(r.work_session_id, False) if r.work_session_id else False
            
        res.append({
            "id": str(r.id),
            "zoneId": str(r.zone_id),
            "zoneName": zones_map.get(r.zone_id, "منطقة محذوفة"),
            "driverId": str(r.driver_id) if r.driver_id else "",
            "driverName": drivers_map.get(r.driver_id, "بدون مندوب") if r.driver_id else "بدون مندوب",
            "vehicleId": str(r.vehicle_id),
            "shopsRemaining": shops_remaining,
            "status": r.status,
            "sessionEnded": session_ended # +++ إضافة الحالة للواجهة الأمامية +++
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
        
    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    new_driver_id = data.get('driverId')
    new_vehicle_id = data.get('vehicleId') # +++ استلام السيارة الجديدة +++
    inventory = data.get('inventory')      # +++ استلام الجرد المُحدث +++
    
    # +++ قفل معماري صارم: الفحص يشمل تغيير المندوب أو تغيير حالة الخط إلى نشط +++
    target_driver_id = new_driver_id or route.driver_id
    is_activating = (new_status == 'active') or (not new_status and route.status == 'active')
    
    if target_driver_id and is_activating:
        existing_active = DispatchRoute.query.filter_by(driver_id=target_driver_id, status='active').first()
        if existing_active and existing_active.id != route.id:
            return jsonify({"message": "كارثة مرفوضة: هذا المندوب يمتلك خط سير نشط حالياً. يجب إغلاق خطه الحالي أولاً!"}), 400

    try:
        if new_status: 
            route.status = new_status
            # +++ الجدولة التلقائية عند الإغلاق +++
            if new_status == 'closed':
                zone = db.session.get(Zone, route.zone_id)
                if zone and zone.start_date and zone.schedule_frequency:
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

            if new_status in ['closed', 'waiting', 'postponed'] and route.driver_id:
                # +++ النسف المعماري لزومبي الطوارئ: سحب *كل* الزيارات المعلقة من المندوب (بما فيها طلبات الطوارئ الخارجية) لمنع تعليقها للأبد +++
                Visit.query.filter(
                    Visit.driver_id == route.driver_id, 
                    Visit.status == 'Pending'
                ).update({
                    'driver_id': None, 
                    'work_session_id': None,
                    'is_emergency': False # إزالة حالة الطوارئ لتعود لغرفة العمليات
                }, synchronize_session=False)

        if new_driver_id: 
            if new_driver_id != route.driver_id:
                # +++ النسف المعماري لاستنساخ البضاعة: نقل الجرد الحي (Live Inventory) إلى حمولة السيارة قبل تبديل المندوب +++
                old_active_session = WorkSession.query.filter_by(driver_id=route.driver_id, end_time=None).first()
                if old_active_session:
                    live_invs = SessionInventory.query.filter_by(work_session_id=old_active_session.id).all()
                    if live_invs:
                        # +++ النسف المعماري لـ N+1: جلب كل المنتجات والحمولات باستعلامين فقط (Bulk Fetch) +++
                        var_ids = [inv.product_variant_id for inv in live_invs]
                        
                        variants = ProductVariant.query.filter(ProductVariant.id.in_(var_ids)).all()
                        var_map = {v.id: (v.packs_per_carton if v.packs_per_carton else 1) for v in variants}
                        
                        v_loads = VehicleLoad.query.filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(var_ids)).all()
                        v_load_map = {vl.product_variant_id: vl for vl in v_loads}
                        
                        for live_inv in live_invs:
                            safe_packs = var_map.get(live_inv.product_variant_id, 1)
                            actual_cartons = live_inv.current_remaining_quantity // safe_packs
                            
                            v_load = v_load_map.get(live_inv.product_variant_id)
                            if v_load:
                                v_load.quantity = actual_cartons
                            else:
                                db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=live_inv.product_variant_id, quantity=actual_cartons))
                            
                    # إجبار المندوب القديم على إنهاء الجلسة فوراً لمنع التضارب
                    old_active_session.end_time = datetime.now(timezone.utc)
                    
                    # +++ التنظيف الجراحي: الرفض الآلي لأي حوالات معلقة للمندوب القديم لكي لا تتجمد في الداتابيز للأبد +++
                    InventoryTransfer.query.filter_by(
                        work_session_id=old_active_session.id, 
                        status='pending'
                    ).update({
                        'status': 'rejected'
                    }, synchronize_session=False)

                # نقل الزيارات للمندوب الجديد
                db.session.query(Visit).filter(
                    Visit.driver_id == route.driver_id,
                    Visit.status == 'Pending',
                    Visit.shop_id.in_(
                        db.session.query(Shop.id).filter(Shop.zone_id == route.zone_id)
                    )
                ).update({'driver_id': new_driver_id, 'work_session_id': None}, synchronize_session=False)
                
            route.driver_id = new_driver_id
            # +++ النسف المعماري لتسمم خط السير: فك ارتباط الخط بجلسة المندوب القديم لكي يستلمه المندوب الجديد نظيفاً +++
            route.work_session_id = None
            
        if new_vehicle_id: route.vehicle_id = new_vehicle_id
        
        if inventory is not None and route.vehicle_id:
            active_session = WorkSession.query.filter_by(driver_id=route.driver_id, end_time=None).first() if route.driver_id else None
            
            if not active_session:
                # الاعتماد الكلي على جرد المشرف لأن السيارة فارغة أو اليوم لم يبدأ
                VehicleLoad.query.filter_by(vehicle_id=route.vehicle_id).delete()
                for prod_id, qty in inventory.items():
                    if str(qty).strip() == '': continue
                    # +++ تسجيل الصفر كقيمة عهدة مقصودة من المشرف +++
                    db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=int(prod_id), quantity=int(qty)))
            else:
                # +++ المعالجة الذكية لتزويد السيارة مع نسف ثغرة الـ N+1 (Bulk Fetch) +++
                admin_user_id = getattr(g, 'current_driver_id', None)
                
                # +++ كي جراحي: السماح بالصفر ليتمكن المشرف من تصفير وسحب بضاعة المندوب الحرامي +++
                prod_ids_to_update = [int(p) for p, q in inventory.items() if str(q).strip() != '']
                bulk_vloads = {vl.product_variant_id: vl for vl in VehicleLoad.query.filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(prod_ids_to_update)).all()} if prod_ids_to_update and route.vehicle_id else {}
                bulk_sinvs = {si.product_variant_id: si for si in SessionInventory.query.filter(SessionInventory.work_session_id == active_session.id, SessionInventory.product_variant_id.in_(prod_ids_to_update)).all()} if prod_ids_to_update else {}

                # +++ الكي الجراحي: جلب الحوالات المعلقة لمنع التكرار المميت (Ghost Transfers) +++
                pending_transfers_query = db.session.query(
                    InventoryTransfer.product_variant_id, 
                    func.sum(InventoryTransfer.quantity_packs)
                ).filter(
                    InventoryTransfer.work_session_id == active_session.id,
                    InventoryTransfer.product_variant_id.in_(prod_ids_to_update),
                    InventoryTransfer.status == 'pending'
                ).group_by(InventoryTransfer.product_variant_id).all() if prod_ids_to_update else []
                pending_transfers_map = {v_id: total for v_id, total in pending_transfers_query}

                # جلب المنتجات لمعرفة كم حبة في الكرتونة
                variants_map = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(prod_ids_to_update)).all()}
                
                # +++ توليد Batch ID واحد لكل الدفعة لربطها في رادار الإدارة وشاشة المندوب +++
                batch_timestamp = str(int(time.time()))
                
                for prod_id, new_qty_str in inventory.items():
                    clean_qty_str = str(new_qty_str).strip()
                    if clean_qty_str == '': continue
                    
                    # +++ الدرع الفولاذي: حماية الـ 500 Crash من إدخالات المشرفين الخاطئة (نصوص بدلاً من أرقام) +++
                    try:
                        new_actual_qty_cartons = int(clean_qty_str)
                        p_id = int(prod_id)
                    except ValueError:
                        continue
                        
                    # +++ السماح بإرسال حوالات التصفير والسحب الكامل لمعاقبة المندوب الذي فقد عهدته +++
                    variant = variants_map.get(p_id)
                    if not variant: continue
                        
                    # +++ توحيد القياس وحماية الـ TypeError: تأمين قيمة packs_per_carton +++
                    safe_packs_per_carton = variant.packs_per_carton if variant.packs_per_carton else 1
                    new_actual_qty_packs = new_actual_qty_cartons * safe_packs_per_carton
                        
                    v_load = bulk_vloads.get(p_id)
                    if v_load: v_load.quantity = new_actual_qty_cartons # حمولة السيارة تبقى بالكرتونة للمشرف
                    else: db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=p_id, quantity=new_actual_qty_cartons))

                    sess_inv = bulk_sinvs.get(p_id)
                    # +++ الكيّ الجراحي: سد ثغرة التعديل الإجباري وتفعيل نظام المصافحة الفولاذي وحماية التكرار +++
                    if sess_inv:
                        existing_pending_packs = pending_transfers_map.get(p_id, 0)
                        # نحسب الفرق بناءً على العهدة الحالية + الحوالات المعلقة مسبقاً لمنع التكرار المميت
                        difference_in_packs = new_actual_qty_packs - (sess_inv.current_remaining_quantity + existing_pending_packs)
                        if difference_in_packs != 0:
                            # 1. نمنع التعديل المباشر على عهدة المندوب (sess_inv) هنا.
                            # 2. نمنع التسجيل في دفتر الأستاذ (InventoryLedger) هنا (سيتم التسجيل عند الموافقة).
                            # 3. نصدر حوالة مصافحة (Transfer) وننتظر موافقة المندوب الرقمية.
                                new_transfer = InventoryTransfer(
                                    work_session_id=active_session.id,
                                    product_variant_id=p_id,
                                    quantity_packs=difference_in_packs,
                                    status='pending',
                                    admin_id=admin_user_id,
                                    notes=f"BATCH_{batch_timestamp}" # +++ استخدام العمود الجديد للربط +++
                                )
                                db.session.add(new_transfer)
                        else:
                            db.session.add(SessionInventory(work_session_id=active_session.id, product_variant_id=p_id, starting_quantity=new_actual_qty_packs, current_remaining_quantity=new_actual_qty_packs))

        # +++ إعادة التوليد بدون N+1 ومضاد للاستنساخ (تبني الأيتام) +++
        if route.status == 'active' and route.driver_id:
            # +++ النسف المعماري: توحيد التوقيت لـ UTC لمنع تداخل الأيام بين سيرفرات الكلاود والمناديب +++
            today = datetime.now(timezone.utc).date()
            
            shops_in_zone = Shop.query.filter_by(zone_id=route.zone_id, is_active=True, is_archived=False).all()
            shop_ids = [s.id for s in shops_in_zone]
            
            # 1. المطالبة بالزيارات المعلقة (الأيتام) التي تم تحريرها سابقاً عند سحب المنطقة
            orphaned_visits = Visit.query.filter(
                Visit.shop_id.in_(shop_ids),
                Visit.status == 'Pending',
                Visit.driver_id == None
            ).all()
            for v in orphaned_visits:
                v.driver_id = route.driver_id # تبني اليتيم وإعادته للمندوب الحالي
                
            # 2. جلب جميع زيارات هذا المندوب (بما فيها التي للتو تبناها)
            existing_visits = Visit.query.filter(
                Visit.driver_id == route.driver_id,
                Visit.shop_id.in_(shop_ids),
                db.or_(Visit.status == 'Pending', func.date(Visit.visit_timestamp) == today)
            ).all()
            # +++ النسف المعماري: خريطة ذاكرة (O(1)) بدل اللوب القاتل +++
            existing_visits_map = {v.shop_id: v for v in existing_visits}
            visited_shop_ids = set(existing_visits_map.keys())
            
            pending_shortages = ShortageRequest.query.filter(
                ShortageRequest.shop_id.in_(shop_ids), 
                ShortageRequest.status == 'pending'
            ).all()
            shortage_shop_ids = {s.shop_id for s in pending_shortages}
            
            for shop in shops_in_zone:
                is_emerg = shop.id in shortage_shop_ids
                if shop.id not in visited_shop_ids:
                    # بناء زيارة جديدة فقط إذا لم تكن موجودة نهائياً (لا كيتيم ولا كمنجزة)
                    db.session.add(Visit(
                        driver_id=route.driver_id, 
                        shop_id=shop.id, 
                        status='Pending', 
                        sequence=shop.sequence,
                        is_emergency=is_emerg
                    ))
                else:
                    # +++ جلب مباشر وسريع من الخريطة O(1) +++
                    visit_to_update = existing_visits_map.get(shop.id)
                    if visit_to_update and is_emerg:
                         visit_to_update.is_emergency = True
 
        db.session.commit()
        return jsonify({"message": "تم تحديث خط السير بنجاح"}), 200
        
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "خطأ في التحديث", "error": "Internal Server Error"}), 500

# =========================================
# تراجع عن إنهاء العمل (Admin Override)
# =========================================
@api.route('/dispatch/session/<int:session_id>/undo_end_work', methods=['PUT'])
@token_required
def undo_end_work(session_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة"}), 403

    session = db.session.get(WorkSession, session_id)
    if not session:
        return jsonify({"message": "الجلسة غير موجودة."}), 404

    if session.is_settled:
        return jsonify({"message": "لا يمكن التراجع، تم اعتماد التسوية لهذه الجلسة مسبقاً."}), 400

    # +++ قفل الدماغ المنقسم (Split-Brain): منع التراجع إذا كان المندوب قد بدأ جلسة جديدة أو استلم خط سير جديد +++
    active_session_now = WorkSession.query.filter(WorkSession.driver_id == session.driver_id, WorkSession.end_time == None).first()
    active_route_now = DispatchRoute.query.filter(DispatchRoute.driver_id == session.driver_id, DispatchRoute.status == 'active').first()
    
    if active_session_now or active_route_now:
        return jsonify({"message": "مرفوض: المندوب لديه جلسة عمل نشطة حالياً. يجب إغلاقها قبل التراجع عن الجلسة القديمة."}), 400

    try:
        old_end_time = session.end_time.isoformat() if session.end_time else "None"
        
        # 1. إرجاع الجلسة لحالة نشطة بإزالة وقت النهاية
        session.end_time = None
        
        # 2. إرجاع حالة خط السير إلى نشط (إن وجد)
        route = DispatchRoute.query.filter_by(work_session_id=session.id).first()
        if route:
            # +++ الدرع الفولاذي: لا نعيد تفعيل الخط إذا تم سحبه وإعطاؤه لمندوب آخر أثناء فترة إغلاق الجلسة +++
            if route.driver_id == session.driver_id:
                route.status = 'active'
            else:
                route.work_session_id = None # فك الارتباط المكسور
            
        # +++ تسجيل الحركة الحساسة في دفتر النظام (System Audit Log) +++
        audit_log = SystemAuditLog(
            admin_id=admin.id,
            target_id=str(session.id),
            action_type='UNDO_END_WORK',
            old_value=f"end_time: {old_end_time}",
            new_value="end_time: NULL (Session Reopened)"
        )
        db.session.add(audit_log)
        
        db.session.commit()
        return jsonify({"message": "تم التراجع عن إنهاء العمل بنجاح. يمكن للمندوب متابعة عمله الآن."}), 200

    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({"message": "خطأ أثناء التراجع عن إنهاء العمل", "error": "Internal Server Error"}), 500

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

    data = request.get_json(silent=True) or {}
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
        traceback.print_exc() # طباعة الخطأ في التيرمنال
        return jsonify({"message": "خطأ في إضافة المنطقة", "error": "Internal Server Error"}), 500

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
            return jsonify({"message": "لا يمكن أرشفة المنطقة، يوجد بها محلات نشطة. يرجى نقلها أو أرشفتها أولاً."}), 400
            
        # +++ الدرع المعماري: منع أرشفة منطقة يمتلكها مندوب في الشارع حالياً (Rug-Pull) +++
        active_routes = DispatchRoute.query.filter(DispatchRoute.zone_id == zone_id, DispatchRoute.status.in_(['active', 'waiting'])).count()
        if active_routes > 0:
            return jsonify({"message": "مرفوض: يوجد خط سير نشط أو قيد الانتظار يعمل في هذه المنطقة. يجب إغلاق خط السير أولاً."}), 400

        try:
            # +++ أرشفة المنطقة بدل حذفها نهائياً لتجنب كسر الفواتير السابقة +++
            zone.is_active = False
            db.session.commit()
            return jsonify({"message": "تم أرشفة المنطقة بنجاح"}), 200
        except Exception as e:
            db.session.rollback()
            traceback.print_exc()
            # +++ النسف الأمني لتسريب البيانات +++
            return jsonify({"message": "حدث خطأ داخلي في الخادم أثناء أرشفة المنطقة. تم تسجيل المشكلة."}), 500

    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
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
                zone.start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                
            db.session.commit()
            return jsonify({"message": "تم التعديل بنجاح"}), 200
        except Exception as e:
            db.session.rollback()
            traceback.print_exc() # هذا السطر سيفضح الخطأ في التيرمنال
            return jsonify({"message": "خطأ في التعديل", "error": "Internal Server Error"}), 500

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
    # +++ الدرع المحاسبي: قفل المحل لمنع المشرف من مسح مبيعات المندوب التي تحدث في نفس الثانية +++
    shop = db.session.query(Shop).with_for_update().filter_by(id=clean_id).first()
    
    if not shop:
        return jsonify({"message": "المحل غير موجود"}), 404
        
    data = request.get_json(silent=True) or {}
    new_phone = data.get('phone', '').strip()
    
    # فحص تكرار رقم الهاتف لمحل آخر
    if new_phone and new_phone != shop.phone_number:
        if Shop.query.filter_by(phone_number=new_phone).first():
            return jsonify({"message": "رقم الهاتف مستخدم لمحل آخر"}), 409
            
    try:
        shop.name = data.get('name', shop.name)
        shop.contact_person = data.get('owner', shop.contact_person)
        
        # +++ حماية البيانات من المسح: نعتمد الرقم الجديد فقط إذا لم يكن فارغاً، وإلا نحتفظ بالقديم +++
        shop.phone_number = new_phone if new_phone else shop.phone_number
        shop.location_link = data.get('mapLink', shop.location_link)
        shop.zone_id = data.get('zoneId', shop.zone_id)
        
        # +++ التطهير المحاسبي: منع تعديل الرصيد الحي (current_balance) من شاشة البروفايل لمنع مسح مبيعات المندوب +++
        # يتم فقط تعديل سقف الدين (max_debt_limit) إذا تم إرساله من الإدارة
        try:
            raw_limit = str(data.get('maxDebtLimit') or '').strip()
            if raw_limit:
                shop.max_debt_limit = Decimal(raw_limit)
        except Exception:
            pass # احتفظ بالسقف القديم إذا كان الإدخال خبيثاً
        
        db.session.commit()
        return jsonify({"message": "تم التعديل بنجاح"}), 200
    except Exception as e:
        db.session.rollback()
        print("🚨 خطأ في تعديل المحل:", str(e)) # رح تظهر بالتيرمنال
        return jsonify({"message": "خطأ في التعديل", "error": "Internal Server Error"}), 500

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
        # +++ التدمير الحقيقي لـ N+1: جلب المنتجات لنسف الاستعلامات المخفية +++
        shortages = ShortageRequest.query.options(
            joinedload(ShortageRequest.zone),
            joinedload(ShortageRequest.shop),
            joinedload(ShortageRequest.driver),
            joinedload(ShortageRequest.product_variant) # +++ الدرع المفقود +++
        ).filter_by(status='pending').all()
        
        result = [{
            "id": str(s.id),
            "zoneId": str(s.zone_id),
            "zoneName": s.zone.name if s.zone else "",
            "shopId": str(s.shop_id),
            "shopName": s.shop.name if s.shop else "",
            "driverId": str(s.driver_id) if s.driver_id else "",
            "driverName": s.driver.full_name if s.driver else "",
            "productName": s.product_variant.variant_name if s.product_variant else "غير معروف",
            "quantity": s.quantity,
            "status": s.status,
            "waitTime": s.wait_time,
            "createdAt": s.created_at.isoformat() if s.created_at else None
        } for s in shortages]
        return jsonify(result), 200

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        try:
            # +++ التعديل المعماري: القضاء على N+1 في التحقق من التكرار +++
            shop_ids = [str(item.get('shopId')) for item in data if item.get('shopId')]
            
            # +++ النسف المعماري الشامل (Double N+1): جلب المحلات والزيارات دفعة واحدة +++
            bulk_shops = {str(sh.id): sh for sh in Shop.query.filter(Shop.id.in_(shop_ids)).all()} if shop_ids else {}
            
            # +++ النسف المعماري لشبح الطوارئ: نبحث فقط عن الزيارات (المعلقة) لنختمها بالطوارئ +++
            # إذا كانت الزيارة السابقة مكتملة، يجب إنشاء زيارة معلقة "جديدة" ليراها المندوب
            pending_visits = Visit.query.filter(
                Visit.shop_id.in_(shop_ids),
                Visit.status == 'Pending'
            ).order_by(Visit.id.desc()).all() if shop_ids else []
            
            # خريطة الزيارات: المفتاح (driver_id, shop_id)
            bulk_visits = {(str(v.driver_id), str(v.shop_id)): v for v in pending_visits}
            
            existing_requests = {}
            if shop_ids:
                existing_reqs = ShortageRequest.query.options(joinedload(ShortageRequest.shop)).filter(
                    ShortageRequest.shop_id.in_(shop_ids), 
                    ShortageRequest.status == 'pending'
                ).all()
                existing_requests = {str(req.shop_id): req for req in existing_reqs}

            processed_shop_ids = set() # +++ تتبع المحلات في نفس الطلب لمنع الإضافة المزدوجة +++
            
            # +++ النسف المعماري الحقيقي لـ N+1: جلب المنتجات دفعة واحدة خارج الحلقة +++
            product_names = [str(item.get('productName') or item.get('productId') or '').strip() for item in data]
            bulk_variants_map = {v.variant_name: v for v in ProductVariant.query.filter(ProductVariant.variant_name.in_(product_names)).all()} if product_names else {}

            for item in data:
                shop_id = str(item.get('shopId'))
                if shop_id and (shop_id in existing_requests or shop_id in processed_shop_ids):
                    shop_name = existing_requests[shop_id].shop.name if (shop_id in existing_requests and existing_requests[shop_id].shop) else shop_id
                    return jsonify({"message": f"مرفوض: لا يمكن تقديم أكثر من طلب عاجل واحد لنفس المحل (المحل: {shop_name})"}), 409

                processed_shop_ids.add(shop_id)
                
                # +++ قراءة سريعة من الذاكرة (O(1)) لمنع اختناق الداتابيز +++
                product_name = str(item.get('productName') or item.get('productId') or '').strip()
                variant = bulk_variants_map.get(product_name)
                if not variant:
                    return jsonify({"message": f"المنتج '{product_name}' غير موجود في النظام."}), 404
                
                # +++ حماية הـ 500 Crash من القيود الإجبارية (NOT NULL constraint) +++
                zone_id_val = item.get('zoneId')
                if not zone_id_val:
                    return jsonify({"message": f"مرفوض: المنطقة إجبارية للطلب العاجل الخاص بالمحل. يرجى تحديث البيانات."}), 400

                new_shortage = ShortageRequest(
                    zone_id=zone_id_val,
                    shop_id=shop_id,
                    driver_id=item.get('driverId') or None,
                    product_variant_id=variant.id, 
                    quantity=item.get('quantity', 1)
                )
                db.session.add(new_shortage)
                
                # +++ التعديل الجراحي: إنشاء زيارة فعلية إذا تم توجيه الطلب لمندوب لضمان ظهورها بتطبيقه +++
                target_driver_id = item.get('driverId')
                # +++ هندسة منع الاستنساخ (بدون استعلامات داخل اللوب) +++
                target_driver_id = str(target_driver_id) if target_driver_id else None
                if target_driver_id:
                    existing_visit = bulk_visits.get((target_driver_id, shop_id))
                    
                    if existing_visit:
                        existing_visit.is_emergency = True
                    else:
                        shop_record = bulk_shops.get(shop_id)
                        new_visit = Visit(
                            driver_id=int(target_driver_id),
                            shop_id=int(shop_id),
                            status='Pending',
                            sequence=shop_record.sequence if shop_record else 999,
                            is_emergency=True
                        )
                        db.session.add(new_visit)
                        bulk_visits[(target_driver_id, shop_id)] = new_visit # لحمايتها من التكرار اللحظي
                # ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
            db.session.commit()
            return jsonify({"message": "تم تسجيل الطلبات بنجاح"}), 201
        except Exception as e:
            db.session.rollback()
            traceback.print_exc()
            return jsonify({"message": "خطأ في حفظ الطلبات", "error": "Internal Server Error"}), 500

# +++ مسار حذف الطلب العاجل +++
@api.route('/dispatch/shortages/<int:shortage_id>', methods=['DELETE'])
@token_required
def delete_shortage(shortage_id):
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin: return jsonify({"message": "مرفوض"}), 403
    shortage = db.session.get(ShortageRequest, shortage_id)
    if shortage:
        shop_id = shortage.shop_id
        db.session.delete(shortage)
        db.session.flush() # لتحديث الجرد المؤقت قبل فحص المتبقي
        
        # +++ التزامن المعماري: سحب ختم (عاجل) من هاتف المندوب إذا لم يتبقَ أي طلبات أخرى +++
        remaining = ShortageRequest.query.filter_by(shop_id=shop_id, status='pending').count()
        if remaining == 0:
            target_visit = Visit.query.filter_by(shop_id=shop_id, status='Pending').first()
            if target_visit:
                target_visit.is_emergency = False
                
                # +++ نسف الشبح: إذا كان المحل خارج منطقة المندوب (أضيف للطوارئ فقط)، نسحبه منه لكي لا يعلق الشبح في تطبيقه +++
                if target_visit.driver_id:
                    route = DispatchRoute.query.filter_by(driver_id=target_visit.driver_id, status='active').first()
                    shop = db.session.get(Shop, shop_id)
                    if route and shop and shop.zone_id != route.zone_id:
                        target_visit.driver_id = None
                        target_visit.work_session_id = None
            
        db.session.commit()
    return jsonify({"message": "تم حذف الطلب"}), 200

# =========================================
# 14. الاستيراد الآمن للمحلات بالجملة (Bulk Import)
# =========================================
@api.route('/dispatch/shops/bulk_import', methods=['POST'])
@token_required
def bulk_import_shops():
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض: تتطلب صلاحيات إدارة."}), 403

    data = request.get_json(silent=True) or {}
    zone_id = data.get('zoneId')
    shops_list = data.get('shops', [])
    file_name = data.get('fileName', 'استيراد غير معروف')

    if not zone_id or not shops_list:
        return jsonify({"message": "المنطقة وقائمة المحلات مطلوبة"}), 400

    # +++ حرس الحدود الفولاذي: منع انهيار قاعدة البيانات (SQL Parameters Limit Crash) +++
    if len(shops_list) > 1000:
        return jsonify({"message": "مرفوض: الملف ضخم جداً. الحد الأقصى هو 1000 محل في الرفعة الواحدة لتجنب توقف خوادم الشركة."}), 400

    try:
        # +++ المهمة 2: حفظ السجل مبدئياً بـ Commit منفصل لضمان عدم ضياعه إذا حدث خطأ (Rollback) لاحقاً +++
        import_log = ImportLog(admin_id=admin.id, zone_id=zone_id, file_name=file_name, total_records=len(shops_list), status='Processing')
        db.session.add(import_log)
        db.session.commit()

        # +++ تفكيك قنبلة الذاكرة: جلب المحلات التي قد تتطابق فقط (بدل جلب كامل الداتا بيز) +++
        incoming_names = {s.get('name', '').strip().lower() for s in shops_list if s.get('name')}
        incoming_phones = {str(s.get('phone', '')).strip() for s in shops_list if s.get('phone')}
        incoming_links = {s.get('mapLink', '').strip().lower() for s in shops_list if s.get('mapLink')}

        filters = []
        if incoming_names: filters.append(func.lower(Shop.name).in_(incoming_names))
        if incoming_phones: filters.append(Shop.phone_number.in_(incoming_phones))
        if incoming_links: filters.append(func.lower(Shop.location_link).in_(incoming_links))

        if filters:
            all_existing_shops = Shop.query.filter(Shop.is_archived == False, db.or_(*filters)).all()
        else:
            all_existing_shops = []
        
        # +++ هندسة الخوارزميات: تحويل O(N^2) إلى O(N) باستخدام Hash Maps و Counter +++
        name_idx, phone_idx, link_idx = {}, {}, {}
        
        for ext in all_existing_shops:
            n = (ext.name or '').strip().lower()
            p = str(ext.phone_number or '').strip()
            l = (ext.location_link or '').strip().lower()
            if n: name_idx.setdefault(n, []).append(ext.id)
            if p: phone_idx.setdefault(p, []).append(ext.id)
            if l: link_idx.setdefault(l, []).append(ext.id)

        new_shops = []
        ignored_count = 0

        for s in shops_list:
            s_name = s.get('name', '').strip().lower()
            s_phone = str(s.get('phone', '')).strip()
            s_link = s.get('mapLink', '').strip().lower()

            candidate_ids = []
            if s_name in name_idx: candidate_ids.extend(name_idx[s_name])
            if s_phone in phone_idx: candidate_ids.extend(phone_idx[s_phone])
            if s_link in link_idx: candidate_ids.extend(link_idx[s_link])
            
            # +++ الدرع الأمني: التكرار برقم الهاتف لوحده يعتبر تطابقاً صارماً يمنع الإضافة، أو "2 من 3" لباقي الحقول +++
            is_phone_duplicate = bool(s_phone and s_phone in phone_idx)
            is_duplicate = is_phone_duplicate or any(count >= 2 for count in Counter(candidate_ids).values())
            
            if is_duplicate:
                ignored_count += 1
                continue

            # +++ الدرع الفولاذي: حماية الـ Decimal من النصوص العشوائية بالإكسل (مثل "N/A" أو "لا يوجد") لمنع انهيار السيرفر +++
            raw_debt = str(s.get('initialDebt') or '0.0').strip()
            try:
                safe_debt = Decimal(raw_debt)
            except Exception:
                safe_debt = Decimal('0.0')

            new_shop = Shop(
                name=s.get('name', '').strip(),
                contact_person=s.get('owner', '').strip(),
                phone_number=s_phone,
                location_link=s.get('mapLink', '').strip(),
                zone_id=zone_id,
                current_balance=max(Decimal('0.0'), safe_debt),
                added_by_driver_id=admin.id,
                # +++ نسف قنبلة الـ ValueError: حماية حقل الترتيب من الفراغات والنصوص العشوائية في الإكسل +++
                sequence=int(str(s.get('sequence', '999')).strip()) if str(s.get('sequence', '')).strip().isdigit() else 999
            )
            new_shops.append(new_shop)
            
            # +++ النسف المعماري: تحديث الـ Hash Maps فوراً بمعرف وهمي لمنع التكرار داخل الإكسل نفسه +++
            temp_id = f"temp_{len(new_shops)}"
            if s_name: name_idx.setdefault(s_name, []).append(temp_id)
            if s_phone: phone_idx.setdefault(s_phone, []).append(temp_id)
            if s_link: link_idx.setdefault(s_link, []).append(temp_id)
            

        db.session.add_all(new_shops)
        
        import_log.success_count = len(new_shops)
        import_log.status = 'Success'
        db.session.commit()
        
        msg = f"تم رفع {len(new_shops)} محل بنجاح."
        if ignored_count > 0: msg += f" وتم تجاهل {ignored_count} محل لأنها موجودة مسبقاً."
        
        return jsonify({"message": msg, "log_id": import_log.id}), 201

    except Exception as e:
        # نحتفظ بالـ ID قبل الـ Rollback لأن الكائن سيطير من الذاكرة
        log_id = import_log.id if import_log else None
        
        db.session.rollback()
        traceback.print_exc()
        
        # +++ إعادة الجلب بعد الـ Rollback لتجنب DetachedInstanceError +++
        if log_id:
            try:
                failed_log = db.session.get(ImportLog, log_id)
                if failed_log:
                    failed_log.status = 'Failed'
                    db.session.commit()
            except:
                db.session.rollback()

        return jsonify({"message": "فشل في رفع البيانات، تم إلغاء العملية بالكامل لحماية قاعدة البيانات.", "error": "Internal Server Error"}), 500