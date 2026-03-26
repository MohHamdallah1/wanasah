from flask import Blueprint, request, jsonify, g
from datetime import datetime, date, timezone
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import traceback
from sqlalchemy import func
from sqlalchemy.orm import joinedload

# توحيد الاستيرادات وحذف التكرار
from models import db, Driver, Shop, Visit, VisitItem, VisitReturn, WorkSession, ProductVariant, SessionInventory, Zone, Vehicle, DispatchRoute, VehicleLoad, ShortageRequest, ImportLog, InventoryLedger, SystemAuditLog, WorkBreakLog
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

    today_date = date.today()

    # 2. +++ منع بدء العمل بدون خط سير (حماية التوزيع) +++
    active_route = DispatchRoute.query.filter_by(driver_id=driver_id, status='active').first()
    if not active_route:
        return jsonify({
            "message": "لا يوجد لديك خط سير مخصص اليوم. الرجاء مراجعة مدير التوزيع."
        }), 403

    # 3. التحقق من عدم وجود جلسة نشطة (لم يتم إنهاؤها) بغض النظر عن التاريخ
    existing_session = WorkSession.query.filter_by(
        driver_id=driver_id,
        end_time=None
    ).first()

    if existing_session:
        return jsonify({"message": "لديك جلسة عمل نشطة بالفعل لم يتم إنهاؤها."}), 409

    try:
        data = request.get_json() or {}
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

        # 5. +++ ربط خط السير بالجلسة ونقل حمولة السيارة لتصبح جرد المندوب +++
        active_route.work_session_id = new_session.id
        
        vehicle_loads = VehicleLoad.query.filter_by(vehicle_id=active_route.vehicle_id).all()
        for load in vehicle_loads:
            inventory_item = SessionInventory(
                work_session_id=new_session.id,
                product_variant_id=load.product_variant_id,
                starting_quantity=load.quantity,
                current_remaining_quantity=load.quantity
            )
            db.session.add(inventory_item)
            
        # 6. تحديث حالة المحلات المعلقة لترتبط بهذه الجلسة
        pending_visits = Visit.query.filter_by(driver_id=driver_id, status='Pending').all()
        for visit in pending_visits:
            visit.work_session_id = new_session.id

        db.session.commit()
        return jsonify({
            "message": "تم بدء الجلسة بنجاح، وتم استلام جرد السيارة.", 
            "session_id": new_session.id
        }), 201

    except Exception as e:
        db.session.rollback()
        import traceback; traceback.print_exc()
        return jsonify({"message": "خطأ داخلي أثناء بدء الجلسة."}), 500

# =========================================
# 3. إنهاء جلسة العمل
# =========================================
@api.route('/driver/<int:driver_id>/sessions/end', methods=['PUT'])
@token_required
def end_work_session(driver_id):
    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
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

    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
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
            
            # +++ تصحيح الميثود المهجورة لضمان التوافق المستقبلي +++
            end_t = datetime.now(timezone.utc).replace(tzinfo=None)
            break_start = active_session.break_start_time
            
            # +++ حل مشكلة تعارض المناطق الزمنية (Timezone Naive vs Aware) +++
            if break_start and break_start.tzinfo is not None:
                break_start = break_start.replace(tzinfo=None)
                
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
        return jsonify({"message": "خطأ في تسجيل الاستراحة", "error": str(e)}), 500
    
# =========================================
# 4. تحديث نتيجة الزيارة
# =========================================
@api.route('/visits/<int:visit_id>', methods=['PUT'])
@token_required
def update_visit(visit_id):
    # +++ نسف ثغرة N+1 في نظام الارتجاع والتحديث +++
    visit = Visit.query.options(
        joinedload(Visit.shop),
        joinedload(Visit.items).joinedload(VisitItem.product_variant),
        joinedload(Visit.returns)
    ).filter_by(id=visit_id).first_or_404()
    
    if visit.driver_id != getattr(g, 'current_driver_id', None):
         return jsonify({"message": "Forbidden"}), 403

    data = request.get_json()
    outcome = data.get('outcome')
    if outcome not in ['Sale', 'NoSale', 'Postponed']:
        return jsonify({"message": "Invalid outcome"}), 400

    shop = visit.shop
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

    try:
        from decimal import Decimal
        
        # +++ نظام الارتجاع الشامل (Universal Reversal Logic) +++
        # يعمل على تفكيك أي زيارة مكتملة مسبقاً (سواء كانت بيع أو لم يتم البيع) لإرجاع الأمور لنقطة الصفر
        if visit.status == 'Completed':
            # 1. التراجع المستودعي للبضاعة المباعة (فقط إذا كانت الزيارة السابقة بيع)
            if visit.outcome == 'Sale':
                for item in visit.items:
                    if active_session:
                        # +++ نظام الارتجاع الشامل: إرجاع بضاعة الفاتورة السابقة للسيارة (بوحدة الحبات/الفرط بدقة) +++
                        packs_to_return = ((item.quantity + item.bonus_quantity + item.sample_quantity) * item.product_variant.packs_per_carton) + getattr(item, 'packs_quantity', 0)
                        
                        adjust_inventory(active_session.id, item.product_variant_id, packs_to_return)
                        
                        # توثيق الحركة العكسية في دفتر الأستاذ لغايات التدقيق
                        db.session.add(InventoryLedger(
                            work_session_id=active_session.id, driver_id=visit.driver_id,
                            product_variant_id=item.product_variant_id, transaction_type='Adjustment (Reversal)',
                            expected_quantity=0, actual_quantity=packs_to_return,
                            difference=packs_to_return,
                            admin_id=visit.driver_id, notes=f"إلغاء بيع سابق للمحل: {shop.name}"
                        ))
            
            # 2. إرجاع المرتجعات التي استلمها المندوب (يُنفذ دائماً لأن المرتجعات مسموحة في NoSale أيضاً)
            for ret in visit.returns:
                if active_session:
                    adjust_inventory(active_session.id, ret.product_variant_id, -ret.quantity)
            
            # 3. مسح سطور الفاتورة والمرتجعات نهائياً من قاعدة البيانات لبدء صفحة جديدة
            for item in visit.items: db.session.delete(item)
            for ret in visit.returns: db.session.delete(ret)

            # 4. التراجع المالي الشامل (استرجاع رصيد المحل بدقة الميزان لجميع الحالات)
            if visit.shop_balance_before is not None:
                shop.current_balance = visit.shop_balance_before
            else:
                # حماية طوارئ: استرجاع الرصيد بعملية حسابية عكسية في حال فقدان السجل المرجعي
                if visit.outcome == 'Sale':
                    old_debt = Decimal(str(visit.final_amount_due or 0.0)) - Decimal(str(visit.cash_collected or 0.0))
                    if old_debt > Decimal('0.0'): shop.current_balance -= old_debt # إلغاء الدين الجديد
                    shop.current_balance += Decimal(str(visit.debt_paid or 0.0))
                elif visit.outcome == 'NoSale':
                    shop.current_balance += Decimal(str(visit.debt_paid or 0.0))

            # 5. تصفير وتطهير العدادات المالية للزيارة في الداتابيز
            visit.amount_before_tax_and_discount = 0.0
            visit.discount_applied = 0.0
            visit.tax_amount = 0.0
            visit.final_amount_due = 0.0
            visit.cash_collected = 0.0
            visit.debt_paid = 0.0
            visit.shop_balance_before = None
            visit.shop_balance_after = None
            visit.tax_qr_code = None
            
            # 6. إعادة الزيارة لحالة "الانتظار" ليتم معالجتها بالبيانات الجديدة
            visit.outcome = 'Pending'
            visit.status = 'Pending'
            db.session.commit() # اعتماد "النسف" الكامل قبل بناء البيانات الجديدة

        # +++ المعالجة المالية الصارمة بالـ Decimal (ممنوع استخدام Float هنا نهائياً) +++
        debt_paid_input = Decimal(str(data.get('debt_paid', 0.0)))
        original_shop_balance = Decimal(str(shop.current_balance or 0.0))

        # +++ اللوجيك المحاسبي الذكي للذمم السالبة +++
        if debt_paid_input > Decimal('0'):
            if original_shop_balance <= Decimal('0'):
                return jsonify({"message": f"مرفوض: المحل رصيده دائن أو مُصفر ({original_shop_balance}). لا توجد ذمم لتحصيلها."}), 400
            if debt_paid_input > original_shop_balance:
                 return jsonify({"message": f"مرفوض: المبلغ المحصل ({debt_paid_input}) أكبر من ذمة المحل الحالية ({original_shop_balance})."}), 400
                 
        new_shop_balance = original_shop_balance

        visit.visit_timestamp = datetime.now(timezone.utc)
        visit.notes = data.get('notes')
        visit.latitude = data.get('latitude', visit.latitude)
        visit.longitude = data.get('longitude', visit.longitude)
        visit.shop_balance_before = original_shop_balance
        visit.is_emergency = data.get('is_emergency', visit.is_emergency)

        if active_session:
            visit.work_session_id = active_session.id

        if outcome == 'Sale':
            cart_items = data.get('cart_items', [])
            returns_data = data.get('returns', []) 
            cash_collected = float(data.get('cash_collected', 0.0))
            
            current_route = DispatchRoute.query.filter_by(work_session_id=active_session.id).first() if active_session else None
            vehicle_id = current_route.vehicle_id if current_route else None

            total_final_amount = 0.0
            total_base_amount = 0.0
            total_discount = 0.0
            total_tax = 0.0
            total_quantity = 0

            # +++ النسف المعماري لـ N+1 (Bulk Fetch in Memory) +++
            all_var_ids = [i.get('product_variant_id') for i in cart_items] + [r.get('product_variant_id') for r in returns_data]
            all_var_ids = list(set([vid for vid in all_var_ids if vid]))
            
            variants_map = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(all_var_ids)).all()}
            
            inv_map = {}
            if active_session and all_var_ids:
                inv_records = SessionInventory.query.filter(
                    SessionInventory.work_session_id == active_session.id,
                    SessionInventory.product_variant_id.in_(all_var_ids)
                ).all()
                inv_map = {inv.product_variant_id: inv for inv in inv_records}
            # ++++++++++++++++++++++++++++++++++++++++++++++++++++++

            for item in cart_items:
                variant_id = item.get('product_variant_id')
                quantity = int(item.get('quantity', 0)) # عدد الكراتين
                packs_quantity = int(item.get('packs_quantity', 0)) # +++ عدد حبات الفرط +++
                sample_quantity = int(item.get('sample_quantity', 0)) 
                
                # السماح بالمرور إذا كان هناك كراتين، فرط، أو عينات
                if (quantity <= 0 and packs_quantity <= 0 and sample_quantity <= 0) or not variant_id:
                    continue
                    
                variant = variants_map.get(variant_id)
                if not variant:
                    return jsonify({"message": f"المنتج رقم {variant_id} غير موجود."}), 404
                    
                # +++ استدعاء الدالة المحدثة مع أسعار الكرتونة والحبة +++
                invoice = calculate_invoice(quantity, packs_quantity, variant.price_per_carton, variant.price_per_pack)
                
                if invoice is None:
                    invoice = {
                        'bonus_units': 0,
                        'final_amount': 0.0,
                        'base_amount': 0.0,
                        'discount_applied': 0.0,
                        'tax_amount': 0.0
                    }
                
                if active_session:
                    # +++ تحويل كل الكميات (كراتين + بونص + عينات + فرط) إلى "إجمالي حبات" لخصمها من الجرد بدقة +++
                    total_packs_to_deduct = (quantity * variant.packs_per_carton) + packs_quantity + (invoice['bonus_units'] * variant.packs_per_carton) + (sample_quantity * variant.packs_per_carton)
                    net_quantity_in_packs = -total_packs_to_deduct
                    
                    inv_record = inv_map.get(variant_id)
                    expected_qty = inv_record.current_remaining_quantity if inv_record else 0
                    
                    inv_success, inv_msg = adjust_inventory(active_session.id, variant_id, net_quantity_in_packs)
                    if not inv_success:
                        return jsonify({"message": f"مخزونك لا يكفي من {variant.variant_name}. {inv_msg}"}), 409
                        
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
                    packs_quantity=packs_quantity, # +++ حفظ حبات الفرط في الداتابيز لحل لغز التبخر +++
                    bonus_quantity=invoice['bonus_units'],
                    sample_quantity=sample_quantity,     
                    price_per_unit_at_sale=variant.price_per_carton,
                    total_price=invoice['final_amount']
                )
                db.session.add(new_visit_item)
               
                total_final_amount += float(invoice['final_amount'] or 0.0)
                total_base_amount += float(invoice['base_amount'] or 0.0)
                total_discount += float(invoice['discount_applied'] or 0.0)
                total_tax += float(invoice['tax_amount'] or 0.0)
                total_quantity += quantity

            for ret in returns_data:
                ret_variant_id = ret.get('product_variant_id')
                ret_quantity = int(ret.get('quantity', 0))
                ret_type = ret.get('return_type')
                ret_reason = ret.get('reason', '')

                if ret_quantity <= 0 or not ret_variant_id:
                    continue
                
                if active_session:
                    inv_record = inv_map.get(ret_variant_id)
                    expected_qty = inv_record.current_remaining_quantity if inv_record else 0
                    
                    inv_success, inv_msg = adjust_inventory(active_session.id, ret_variant_id, ret_quantity)
                    if not inv_success:
                        return jsonify({"message": f"خطأ في تعديل المخزون للمرتجعات. {inv_msg}"}), 409

                    # +++ الربط اللحظي: تسجيل حركة الإرجاع في دفتر الأستاذ (Ledger) +++
                    db.session.add(InventoryLedger(
                        work_session_id=active_session.id,
                        driver_id=visit.driver_id,
                        vehicle_id=vehicle_id,
                        product_variant_id=ret_variant_id,
                        transaction_type='Return',
                        expected_quantity=expected_qty,
                        actual_quantity=expected_qty + ret_quantity,
                        difference=ret_quantity, # سيكون بالموجب لأنه إضافة
                        admin_id=visit.driver_id,
                        notes=f"مرتجع من المحل: {shop.name} - السبب: {ret_reason}"
                    ))
                
                new_return = VisitReturn(
                    visit_id=visit.id,
                    product_variant_id=ret_variant_id,
                    quantity=ret_quantity,
                    return_type=ret_type,
                    reason=ret_reason
                )
                db.session.add(new_return)

            # +++ توحيد الأنواع: تحويل ناتج الفاتورة إلى Decimal قبل جمعه مع الرصيد +++
            from decimal import Decimal
            new_debt = Decimal(str(total_final_amount)) - Decimal(str(cash_collected))
            
            if new_debt > Decimal('0'):
                # +++ نصيحة الصديق الخبير: إرسال القيمة مباشرة كـ Decimal لمنع هدر القروش +++
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
            visit.debt_paid = float(debt_paid_input) # تخزين كـ Float في الكائن مؤقتاً
            visit.no_sale_reason = data.get('notes')
            # +++ طرح دقيق باستخدام Decimal +++
            new_balance = original_shop_balance - debt_paid_input
            shop.current_balance = new_balance
            visit.shop_balance_after = new_balance

        elif outcome == 'Postponed':
            visit.outcome = 'Postponed'
            visit.status = 'Pending'
            visit.no_sale_reason = data.get('notes')
            visit.shop_balance_after = original_shop_balance

        # +++ إغلاق الطلب العاجل في غرفة العمليات فور إنجاز الزيارة +++
        if visit.status == 'Completed':
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
        return jsonify({"message": "Error updating visit", "error": str(e)}), 500
    

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

    today_date = date.today()
    
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
            inventory_list.append({
                "product_id": inv.product_variant_id,
                "product_name": inv.product_variant.variant_name,
                "starting_cartons": inv.starting_quantity,
                "remaining_cartons": inv.current_remaining_quantity,
                "remaining_packs": 0 # (يمكن حساب الباكيتات لاحقاً إذا لزم الأمر)
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
                Visit.work_session_id == active_session.id, 
                Visit.status == 'Pending',
                Shop.zone_id == active_route.zone_id,
                Shop.is_archived == False # +++ العلاج الذاتي: تجاهل المحلات المؤرشفة +++
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
            "total_cash_overall": total_sales_cash + total_debt_paid
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
# 6. إضافة محل جديد
# =========================================
@api.route('/shops', methods=['POST'])
@token_required
def add_new_shop():
    driver_id = getattr(g, 'current_driver_id', None)
    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
    if not active_session:
        return jsonify({"message": "مرفوض: الرجاء بدء يوم العمل أولاً."}), 403
    if active_session.break_start_time and not active_session.break_end_time:
        return jsonify({"message": "أنت الآن في وقت الاستراحة. قم بإنهاء الاستراحة لمتابعة العمل."}), 403
    if not active_session.is_authorized_to_sell:
        return jsonify({"message": "مرفوض: غير مصرح لك بإضافة محلات حالياً. بانتظار تفعيل خط السير من الإدارة."}), 403
        
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
        # +++ تحويل القيمة المالية إلى float لمنع خطأ النوع في فلاتر +++
        "price_per_carton": float(v.price_per_carton or 0.0), 
        "packs_per_carton": v.packs_per_carton,
        "price_per_pack": float(v.price_per_pack or 0.0),
    } for v in variants]), 200


@api.route('/driver/<int:driver_id>/visits', methods=['GET'])
@token_required
def get_visits(driver_id):
    # 1. جلب الجلسة النشطة حالياً للمندوب
    active_session = WorkSession.query.filter_by(driver_id=driver_id, end_time=None).first()
    
    # +++ سد ثغرة تسرب المحلات: جلب المحلات التابعة لخطة السير النشطة فقط +++
    active_route = DispatchRoute.query.filter_by(driver_id=driver_id, status='active').first()
    if not active_route:
        return jsonify([]), 200 # لا نعرض أي محلات إذا لم يكن هناك خط سير نشط

    # +++ الهندسة الصحيحة والتنظيف (نصيحة الصديق الخبير لإزالة N+1 والاستعلامات المهدرة) +++
    # الزيارة تعتبر ملكاً للمندوب بمجرد ربطها به (سواء كانت في منطقته أو طلب عاجل خارجي).
    visits_query = Visit.query.join(Shop).options(joinedload(Visit.shop)).filter(
        Visit.driver_id == driver_id,
        Shop.is_archived == False
    )

    # +++ التطابق المطلق: إجبار الموبايل على فرز الزيارات بناءً على الترتيب الحي للمحلات (Shop.sequence) +++
    if active_session:
        visits = visits_query.filter((Visit.status == 'Pending') | (Visit.work_session_id == active_session.id)).order_by(Shop.sequence.asc().nulls_last(), Visit.id.asc()).all()
    else:
        visits = visits_query.filter(Visit.status == 'Pending').order_by(Shop.sequence.asc().nulls_last(), Visit.id.asc()).all()

    return jsonify([{
        "visit_id": v.id, 
        "shop_id": v.shop_id, 
        "shop_name": v.shop.name,
        "shop_location_link": v.shop.location_link, 
        "shop_latitude": v.shop.latitude,   # +++ إرسال خط العرض للخارج +++
        "shop_longitude": v.shop.longitude, # +++ إرسال خط الطول للخارج +++
        "shop_balance": float(v.shop.current_balance or 0.0),
        "visit_status": v.status, 
        "visit_sequence": v.sequence,
        "is_emergency": v.is_emergency # +++ الاعتماد على ختم الداتابيز لكي لا يختفي المحل بعد إنجازه +++
    } for v in visits]), 200


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
    shop = visit.shop
    
    cart_items = []
    # تم جلب العناصر مع تفاصيل منتجاتها مسبقاً في الاستعلام الرئيسي بكفاءة O(1)
    items = visit.items
    for item in items:
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
        "returns": [{"product_variant_id": r.product_variant_id, "quantity": r.quantity, "return_type": r.return_type, "reason": r.reason} for r in visit.returns]
    }), 200

@api.route('/driver/<int:driver_id>/sessions/active', methods=['GET'])
@token_required
def get_active_session(driver_id):
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
@token_required
def get_admin_dashboard_data():
    today_date = date.today()
    
    # +++ اللوجيك المعماري الصحيح: جلب جلسات اليوم، أو أي جلسة سابقة لم يتم تسويتها (لحل مشكلة نسيان التسوية) +++
    sessions = WorkSession.query.options(joinedload(WorkSession.driver)).filter(
        (func.date(WorkSession.start_time) == today_date) | 
        (WorkSession.is_settled == False)
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
        pending_query = db.session.query(
            Visit.driver_id, func.count(Visit.id)
        ).filter(Visit.driver_id.in_(driver_ids), Visit.status == 'Pending').group_by(Visit.driver_id).all()
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
            started = inv.starting_quantity
            remaining = inv.current_remaining_quantity
            inv_list.append({
                "product_id": inv.product_variant_id,
                "product_name": inv.product_variant.variant_name,
                "starting_quantity": started,
                "sold_quantity": started - remaining,
                "remaining_quantity": remaining
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
        if session.is_settled and func.date(session.start_time) != today_date:
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

    session = db.session.get(WorkSession, session_id)
    if not session:
        return jsonify({"message": "الجلسة غير موجودة"}), 404

    if session.is_settled:
        return jsonify({"message": "تم اعتماد تسوية هذه الجلسة مسبقاً ولا يمكن التعديل عليها."}), 400

    if not session.end_time:
        return jsonify({"message": "مرفوض: لا يمكن تسوية الجلسة لأن المندوب لم يقم بإنهاء العمل من تطبيقه."}), 400

    data = request.get_json() or {}
    actual_cash = float(data.get('actual_cash', 0.0))
    inventory_jard = data.get('inventory_jard', [])

    try:
        # 1. حساب العجز/الزيادة المالية
        stats = db.session.query(
            func.sum(Visit.cash_collected).label('total_cash'),
            func.sum(Visit.debt_paid).label('total_debt')
        ).filter(Visit.work_session_id == session.id, Visit.status == 'Completed').first()
        
        expected_cash = float(stats.total_cash or 0.0) + float(stats.total_debt or 0.0)
        cash_difference = actual_cash - expected_cash

        # 2. معالجة الجرد المستودعي (اكتشاف العجز/الزيادة وتسجيلها)
        # نحتاج معرفة السيارة المرتبطة بالجلسة لتسجيلها في الدفتر
        route = DispatchRoute.query.filter_by(work_session_id=session.id).first()
        
        # +++ النسف المعماري لـ N+1: جلب جرد الجلسة دفعة واحدة +++
        prod_ids_in_jard = [item.get('product_id') for item in inventory_jard if item.get('product_id')]
        bulk_inv_records = {inv.product_variant_id: inv for inv in SessionInventory.query.filter(
            SessionInventory.work_session_id == session.id,
            SessionInventory.product_variant_id.in_(prod_ids_in_jard)
        ).all()} if prod_ids_in_jard else {}

        for item in inventory_jard:
            prod_id = item.get('product_id')
            actual_qty = int(item.get('actual', 0))
            
            inv_record = bulk_inv_records.get(prod_id)
            
            if inv_record:
                # +++ الذكاء المالي: المتوقع هو الرصيد المتبقي بعد طرح كل المبيعات +++
                expected_qty = inv_record.current_remaining_quantity
                difference = actual_qty - expected_qty
                
                # إذا كان هناك عجز أو زيادة، وثّق ذلك فوراً في دفتر الحركات
                if difference != 0:
                    t_type = 'Surplus' if difference > 0 else 'Deficit'
                    notes = f"تسوية نهاية اليوم. المتوقع: {expected_qty}، الفعلي المستلم: {actual_qty}"
                    
                    ledger_entry = InventoryLedger(
                        work_session_id=session.id,
                        driver_id=session.driver_id,
                        vehicle_id=route.vehicle_id if route else None,
                        product_variant_id=prod_id,
                        transaction_type=t_type,
                        expected_quantity=expected_qty,
                        actual_quantity=actual_qty,
                        difference=difference,
                        admin_id=admin.id,
                        notes=notes
                    )
                    db.session.add(ledger_entry)

                # تحديث الكمية المتبقية الفعلية في الجلسة لتطابق الجرد
                inv_record.current_remaining_quantity = actual_qty

        # 3. إغلاق العهدة
        session.is_settled = True
        
        # 4. فصل الجلسة المالية عن خط السير، مع إبقاء المنطقة للمندوب لليوم التالي
        route = DispatchRoute.query.filter_by(work_session_id=session.id, status='active').first()
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
        import traceback
        traceback.print_exc()
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

    data = request.get_json()
    zone_id = data.get('zone_id')
    driver_id = data.get('driver_id')
    vehicle_id = data.get('vehicle_id')
    inventory = data.get('inventory', {}) # +++ استلام جرد الحمولة +++

    if not all([zone_id, driver_id, vehicle_id]):
        return jsonify({"message": "يرجى توفير المنطقة، المندوب، والسيارة."}), 400

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
            prod_ids = [int(p) for p, q in inventory.items() if int(q) > 0]
            bulk_variants = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(prod_ids)).all()} if prod_ids else {}
            
            if not active_session:
                # إذا لم يبدأ يومه بعد (صباحاً)، نعتمد الجرد المدخل كحمولة جديدة للسيارة
                VehicleLoad.query.filter_by(vehicle_id=vehicle_id).delete()
                for prod_id, qty in inventory.items():
                    qty_cartons = int(qty)
                    if qty_cartons > 0:
                        db.session.add(VehicleLoad(vehicle_id=vehicle_id, product_variant_id=int(prod_id), quantity=qty_cartons))
                        # (تحويل الكراتين إلى حبات سيتم عند بدء الجلسة في start_work_session)
            else:
                # +++ المعالجة الذكية لتزويد السيارة منتصف اليوم (Mid-day Restock) +++
                bulk_vloads = {vl.product_variant_id: vl for vl in VehicleLoad.query.filter(VehicleLoad.vehicle_id == vehicle_id, VehicleLoad.product_variant_id.in_(prod_ids)).all()} if prod_ids and vehicle_id else {}
                bulk_sinvs = {si.product_variant_id: si for si in SessionInventory.query.filter(SessionInventory.work_session_id == active_session.id, SessionInventory.product_variant_id.in_(prod_ids)).all()} if prod_ids else {}

                for prod_id, new_qty_str in inventory.items():
                    new_actual_qty_cartons = int(new_qty_str)
                    if new_actual_qty_cartons > 0:
                        p_id = int(prod_id)
                        variant = bulk_variants.get(p_id)
                        if not variant: continue
                        
                        new_actual_qty_packs = new_actual_qty_cartons * variant.packs_per_carton
                        
                        # 1. تحديث حمولة السيارة الأساسية (تبقى بالكراتين لشاشة الإدارة)
                        v_load = bulk_vloads.get(p_id)
                        if v_load: v_load.quantity = new_actual_qty_cartons
                        else: db.session.add(VehicleLoad(vehicle_id=vehicle_id, product_variant_id=p_id, quantity=new_actual_qty_cartons))

                        # 2. تحديث عهدة المندوب اللحظية وتوثيق الفرق (بالحبات)
                        sess_inv = bulk_sinvs.get(p_id)
                        if sess_inv:
                            difference_in_packs = new_actual_qty_packs - sess_inv.current_remaining_quantity
                            if difference_in_packs != 0:
                                sess_inv.current_remaining_quantity = new_actual_qty_packs
                                sess_inv.starting_quantity += difference_in_packs 
                                db.session.add(InventoryLedger(
                                    work_session_id=active_session.id, driver_id=driver_id, vehicle_id=vehicle_id,
                                    product_variant_id=p_id, transaction_type='Mid-day Restock' if difference_in_packs > 0 else 'Mid-day Withdraw',
                                    expected_quantity=sess_inv.current_remaining_quantity - difference_in_packs, actual_quantity=new_actual_qty_packs,
                                    difference=difference_in_packs, admin_id=admin.id, notes="تعديل حمولة السيارة منتصف اليوم عند إطلاق خط السير"
                                ))
                        else:
                            db.session.add(SessionInventory(work_session_id=active_session.id, product_variant_id=p_id, starting_quantity=new_actual_qty_packs, current_remaining_quantity=new_actual_qty_packs))

        # +++ التوليد الذكي والمضاد للاستنساخ (Bulk Fetch) أثناء إطلاق الخط +++
        shops_in_zone = Shop.query.filter_by(zone_id=zone_id, is_active=True, is_archived=False).all()
        shop_ids = [s.id for s in shops_in_zone]

        # 1. جلب كل الزيارات الموجودة اليوم لهذا المندوب في هذه المحلات
        today = date.today()
        existing_visits = Visit.query.filter(
            Visit.driver_id == driver_id, 
            Visit.shop_id.in_(shop_ids), 
            db.or_(Visit.status == 'Pending', func.date(Visit.visit_timestamp) == today)
        ).all()
        visited_shop_ids = {v.shop_id for v in existing_visits}

        # 2. جلب الطلبات العاجلة المعلقة لهذه المحلات
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
                # إذا كانت الزيارة موجودة، نقوم فقط بتحديث حالة الطوارئ الخاصة بها
                visit_to_update = next((v for v in existing_visits if v.shop_id == shop.id), None)
                if visit_to_update and is_emerg:
                     visit_to_update.is_emergency = True

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

    # 1. جلب الحمولة الحالية للسيارة (دون طرح أي مبيعات لأن الجرد يجب أن يعكس الواقع اللحظي للسيارة)
    loads = VehicleLoad.query.filter_by(vehicle_id=vehicle_id).all()
    inventory = {l.product_variant_id: l.quantity for l in loads}

    # 2. إرجاع النتائج بناءً على الأصناف النشطة
    variants = ProductVariant.query.filter_by(is_active=True).all()
    result = []
    for v in variants:
        result.append({
            "product_id": str(v.id),
            "product_name": v.variant_name,
            "current_quantity": inventory.get(v.id, 0) # إذا لم تكن في السيارة نرسل 0
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
        
    # +++ إجبار قاعدة البيانات على ترتيب المحلات حسب التسلسل المعتمد لضمان التطابق +++
    shops = Shop.query.order_by(Shop.sequence.asc().nulls_last(), Shop.id.asc()).all()
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
        
    data = request.get_json()
    try:
        # +++ النسف المعماري لـ N+1: جلب المحلات والمناطق دفعة واحدة في الذاكرة +++
        shop_ids = [str(s.get('id')).replace('s', '') for s in data if s.get('id')]
        bulk_shops = {str(sh.id): sh for sh in Shop.query.filter(Shop.id.in_(shop_ids)).all()} if shop_ids else {}
        
        zone_ids_to_check = list(set([s.get('zoneId', bulk_shops[str(s.get('id')).replace('s', '')].zone_id if str(s.get('id')).replace('s', '') in bulk_shops else None) for s in data if 'archived' in s and s['archived'] == False]))
        zone_ids_to_check = [z for z in zone_ids_to_check if z is not None]
        bulk_zones = {z.id: z for z in Zone.query.filter(Zone.id.in_(zone_ids_to_check)).all()} if zone_ids_to_check else {}

        for s_data in data:
            shop_id_str = str(s_data.get('id')).replace('s', '')
            shop = bulk_shops.get(shop_id_str)
            if shop:
                # الحماية الذكية: منع استعادة المحل إذا كانت منطقته مؤرشفة أو محذوفة
                is_restoring = 'archived' in s_data and s_data['archived'] == False
                if is_restoring:
                    zone_to_check = s_data.get('zoneId', shop.zone_id)
                    zone_exists = bulk_zones.get(zone_to_check)
                    if not zone_exists or not getattr(zone_exists, 'is_active', True):
                        return jsonify({"message": f"لا يمكن استعادة المحل '{shop.name}' لأن منطقته مؤرشفة. يرجى نقله لمنطقة نشطة أولاً."}), 400

                if 'sequence' in s_data: shop.sequence = s_data['sequence']
                if 'archived' in s_data: 
                    shop.is_archived = s_data['archived']
                    # +++ حماية التقارير: إلغاء الزيارات المعلقة فوراً بدلاً من مسحها عند الأرشفة +++
                    if s_data['archived']:
                        Visit.query.filter_by(shop_id=shop.id, status='Pending').update({'status': 'Cancelled'}, synchronize_session=False)
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
            current_balance=max(0.0, float(data.get('initialDebt', 0.0))),
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
    session_ended_map = {} # +++ خريطة لمعرفة حالة إنهاء العمل +++
    
    if driver_ids:
        pending_counts = db.session.query(
            Visit.driver_id, func.count(Visit.id)
        ).filter(Visit.driver_id.in_(driver_ids), Visit.status == 'Pending').group_by(Visit.driver_id).all()
        pending_visits_map = {d_id: count for d_id, count in pending_counts}
        
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
        
    data = request.get_json()
    new_status = data.get('status')
    new_driver_id = data.get('driverId')
    new_vehicle_id = data.get('vehicleId') # +++ استلام السيارة الجديدة +++
    inventory = data.get('inventory')      # +++ استلام الجرد المُحدث +++
    
    # +++ قفل معماري صارم: منع تكرار خط السير لنفس المندوب +++
    if new_driver_id:
        existing_active = DispatchRoute.query.filter_by(driver_id=new_driver_id, status='active').first()
        if existing_active and existing_active.id != route.id:
            return jsonify({"message": "كارثة مرفوضة: هذا المندوب يمتلك خط سير نشط حالياً. يجب إغلاق منطقته الحالية أولاً!"}), 400

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

            # +++ المعالجة الذكية (المدمجة) لحالات إغلاق، تأجيل، وسحب المنطقة +++
            if new_status in ['closed', 'waiting', 'postponed'] and route.driver_id:
                # الحل المعماري الجذري والمرن: تحرير الزيارات وجعلها (أيتام) تنتظر مندوباً جديداً
                # هذا يحافظ على المحلات المنجزة للمندوب، ويسحب منه فقط المحلات التي لم يزرها (Pending)
                subq = db.session.query(Visit.id).join(Shop).filter(
                    Visit.driver_id == route.driver_id, Shop.zone_id == route.zone_id, Visit.status == 'Pending'
                ).subquery()
                Visit.query.filter(Visit.id.in_(subq)).update({'driver_id': None, 'work_session_id': None}, synchronize_session=False)

        if new_driver_id: 
            # +++ نقل المحلات المعلقة للمندوب الجديد عند تحويل خط السير +++
            if new_driver_id != route.driver_id:
                pending_visits = Visit.query.filter_by(driver_id=route.driver_id, status='Pending').all()
                for v in pending_visits:
                    if v.shop and v.shop.zone_id == route.zone_id:
                        v.driver_id = new_driver_id
            route.driver_id = new_driver_id
            
        if new_vehicle_id: route.vehicle_id = new_vehicle_id
        
        if inventory is not None and route.vehicle_id:
            active_session = WorkSession.query.filter_by(driver_id=route.driver_id, end_time=None).first() if route.driver_id else None
            
            if not active_session:
                # الاعتماد الكلي على جرد المشرف لأن السيارة فارغة أو اليوم لم يبدأ
                VehicleLoad.query.filter_by(vehicle_id=route.vehicle_id).delete()
                for prod_id, qty in inventory.items():
                    if int(qty) > 0:
                        db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=int(prod_id), quantity=int(qty)))
            else:
                # +++ المعالجة الذكية لتزويد السيارة مع نسف ثغرة الـ N+1 (Bulk Fetch) +++
                admin_user_id = getattr(g, 'current_driver_id', None)
                
                prod_ids_to_update = [int(p) for p, q in inventory.items() if int(q) > 0]
                bulk_vloads = {vl.product_variant_id: vl for vl in VehicleLoad.query.filter(VehicleLoad.vehicle_id == route.vehicle_id, VehicleLoad.product_variant_id.in_(prod_ids_to_update)).all()} if prod_ids_to_update and route.vehicle_id else {}
                bulk_sinvs = {si.product_variant_id: si for si in SessionInventory.query.filter(SessionInventory.work_session_id == active_session.id, SessionInventory.product_variant_id.in_(prod_ids_to_update)).all()} if prod_ids_to_update else {}

                # جلب المنتجات لمعرفة كم حبة في الكرتونة
                variants_map = {v.id: v for v in ProductVariant.query.filter(ProductVariant.id.in_(prod_ids_to_update)).all()}
                
                for prod_id, new_qty_str in inventory.items():
                    new_actual_qty_cartons = int(new_qty_str)
                    if new_actual_qty_cartons > 0:
                        p_id = int(prod_id)
                        variant = variants_map.get(p_id)
                        if not variant: continue
                        
                        # +++ توحيد القياس: تحويل الكراتين التي أدخلها المشرف إلى حبات (Packs) للتعامل الدقيق +++
                        new_actual_qty_packs = new_actual_qty_cartons * variant.packs_per_carton
                        
                        v_load = bulk_vloads.get(p_id)
                        if v_load: v_load.quantity = new_actual_qty_cartons # حمولة السيارة تبقى بالكرتونة للمشرف
                        else: db.session.add(VehicleLoad(vehicle_id=route.vehicle_id, product_variant_id=p_id, quantity=new_actual_qty_cartons))

                        sess_inv = bulk_sinvs.get(p_id)
                        # +++ النسخة المعمارية النظيفة: تحديث الجرد ودفتر الأستاذ بوحدة (الحبة) حصراً في بلوك واحد +++
                        if sess_inv:
                            difference_in_packs = new_actual_qty_packs - sess_inv.current_remaining_quantity
                            if difference_in_packs != 0:
                                expected_qty = sess_inv.current_remaining_quantity
                                sess_inv.current_remaining_quantity = new_actual_qty_packs
                                sess_inv.starting_quantity += difference_in_packs 
                                
                                db.session.add(InventoryLedger(
                                    work_session_id=active_session.id, 
                                    driver_id=route.driver_id, 
                                    vehicle_id=route.vehicle_id,
                                    product_variant_id=p_id, 
                                    transaction_type='Mid-day Restock' if difference_in_packs > 0 else 'Mid-day Withdraw',
                                    expected_quantity=expected_qty, 
                                    actual_quantity=new_actual_qty_packs,
                                    difference=difference_in_packs, 
                                    admin_id=admin_user_id, 
                                    notes="تعديل حمولة السيارة من شاشة التوزيع (بوحدة الحبات)"
                                ))
                        else:
                            db.session.add(SessionInventory(work_session_id=active_session.id, product_variant_id=p_id, starting_quantity=new_actual_qty_packs, current_remaining_quantity=new_actual_qty_packs))

        # +++ إعادة التوليد بدون N+1 ومضاد للاستنساخ (تبني الأيتام) +++
        if route.status == 'active' and route.driver_id:
            from datetime import date
            today = date.today()
            
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
            visited_shop_ids = {v.shop_id for v in existing_visits}
            
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
                    visit_to_update = next((v for v in existing_visits if v.shop_id == shop.id), None)
                    if visit_to_update and is_emerg:
                         visit_to_update.is_emergency = True
 
        db.session.commit()
        return jsonify({"message": "تم تحديث خط السير بنجاح"}), 200
        
    except Exception as e:
        db.session.rollback()
        import traceback; traceback.print_exc()
        return jsonify({"message": "خطأ في التحديث", "error": str(e)}), 500

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

    try:
        old_end_time = session.end_time.isoformat() if session.end_time else "None"
        
        # 1. إرجاع الجلسة لحالة نشطة بإزالة وقت النهاية
        session.end_time = None
        
        # 2. إرجاع حالة خط السير إلى نشط (إن وجد)
        route = DispatchRoute.query.filter_by(work_session_id=session.id).first()
        if route:
            route.status = 'active'
            
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
        import traceback; traceback.print_exc()
        return jsonify({"message": "خطأ أثناء التراجع عن إنهاء العمل", "error": str(e)}), 500

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
    import traceback # تم نقله للأعلى
    admin = db.session.get(Driver, getattr(g, 'current_driver_id', None))
    if not admin or not admin.is_admin:
        return jsonify({"message": "مرفوض"}), 403

    if request.method == 'GET':
        # +++ التعديل المعماري: القضاء على N+1 عبر joinedload +++
        shortages = ShortageRequest.query.options(
            joinedload(ShortageRequest.zone),
            joinedload(ShortageRequest.shop),
            joinedload(ShortageRequest.driver)
        ).filter_by(status='pending').all()
        
        result = [{
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
            "waitTime": s.wait_time,
            "createdAt": s.created_at.isoformat() if s.created_at else None
        } for s in shortages]
        return jsonify(result), 200

    if request.method == 'POST':
        data = request.get_json()
        try:
            # +++ التعديل المعماري: القضاء على N+1 في التحقق من التكرار +++
            shop_ids = [item.get('shopId') for item in data if item.get('shopId')]
            existing_requests = {}
            if shop_ids:
                existing_reqs = ShortageRequest.query.options(joinedload(ShortageRequest.shop)).filter(
                    ShortageRequest.shop_id.in_(shop_ids), 
                    ShortageRequest.status == 'pending'
                ).all()
                # +++ التعديل الجراحي: تحويل المفتاح لنص ليتطابق مع ما ترسله React +++
                existing_requests = {str(req.shop_id): req for req in existing_reqs}

            processed_shop_ids = set() # +++ تتبع المحلات في نفس الطلب لمنع الإضافة المزدوجة +++
            for item in data:
                shop_id = str(item.get('shopId'))
                if shop_id and (shop_id in existing_requests or shop_id in processed_shop_ids):
                    shop_name = existing_requests[shop_id].shop.name if (shop_id in existing_requests and existing_requests[shop_id].shop) else shop_id
                    return jsonify({"message": f"مرفوض: لا يمكن تقديم أكثر من طلب عاجل واحد لنفس المحل (المحل: {shop_name})"}), 409

                processed_shop_ids.add(shop_id)
                new_shortage = ShortageRequest(
                    zone_id=item.get('zoneId'),
                    shop_id=shop_id,
                    driver_id=item.get('driverId') or None,
                    product_name=item.get('productName'),
                    quantity=item.get('quantity', 1)
                )
                db.session.add(new_shortage)
                
                # +++ التعديل الجراحي: إنشاء زيارة فعلية إذا تم توجيه الطلب لمندوب لضمان ظهورها بتطبيقه +++
                target_driver_id = item.get('driverId')
                # +++ هندسة منع الاستنساخ: تحديث الزيارة الحالية لتصبح عاجلة بدلاً من خلق زيارة جديدة +++
                if target_driver_id:
                    existing_visit = Visit.query.filter(
                        Visit.driver_id == target_driver_id, 
                        Visit.shop_id == shop_id,
                        Visit.status.in_(['Pending', 'Completed']) # نبحث عن زيارة اليوم سواء تمت أو لا
                    ).order_by(Visit.id.desc()).first()
                    
                    if existing_visit:
                        existing_visit.is_emergency = True # نختمها كعاجلة فقط
                    else:
                        shop_record = db.session.get(Shop, shop_id)
                        new_visit = Visit(
                            driver_id=target_driver_id,
                            shop_id=shop_id,
                            status='Pending',
                            sequence=shop_record.sequence if shop_record else 999,
                            is_emergency=True
                        )
                        db.session.add(new_visit)
                # ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
            db.session.commit()
            return jsonify({"message": "تم تسجيل الطلبات بنجاح"}), 201
        except Exception as e:
            db.session.rollback()
            traceback.print_exc()
            return jsonify({"message": "خطأ في حفظ الطلبات", "error": str(e)}), 500

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
        
        # +++ التزامن المعماري: سحب ختم (عاجل) من هاتف المندوب إذا لم يتبقَ أي طلبات أخرى لهذا المحل +++
        remaining = ShortageRequest.query.filter_by(shop_id=shop_id, status='pending').count()
        if remaining == 0:
            Visit.query.filter(Visit.shop_id == shop_id, Visit.status == 'Pending').update({'is_emergency': False}, synchronize_session=False)
            
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
        from collections import Counter
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
            
            # إذا تكرر ID المحل القديم مرتين أو أكثر في مصفوفة التطابقات، إذن تحقق شرط "2 من 3"
            is_duplicate = any(count >= 2 for count in Counter(candidate_ids).values())
            
            if is_duplicate:
                ignored_count += 1
                continue

            new_shop = Shop(
                name=s.get('name', '').strip(),
                contact_person=s.get('owner', '').strip(),
                phone_number=s_phone,
                location_link=s.get('mapLink', '').strip(),
                zone_id=zone_id,
                current_balance=max(0.0, float(s.get('initialDebt', 0.0) or 0.0)),
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