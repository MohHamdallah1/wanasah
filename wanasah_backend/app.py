import os
from flask import Flask, request, jsonify  # <<<--- تم دمج استيرادات Flask هنا
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date  # <<<--- تم إضافة date هنا
import bcrypt
from flask_migrate import Migrate
from sqlalchemy import func          # <<<--- تأكدنا من وجود هذا سابقاً
import traceback
from itsdangerous import URLSafeTimedSerializer
import math

# الحصول على المسار الحالي للملف لتحديد مكان قاعدة البيانات
basedir = os.path.abspath(os.path.dirname(__file__))

# إنشاء نسخة من تطبيق فلاسك
app = Flask(__name__)

# ---- إعدادات قاعدة البيانات ----
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

from sqlalchemy import MetaData # <-- أضف هذا الاستيراد في الأعلى مع باقي الاستيرادات

# Define a naming convention (اصطلاح تسمية قياسي وموصى به)
convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# إنشاء MetaData مع اصطلاح التسمية
metadata = MetaData(naming_convention=convention)
# إنشاء كائن قاعدة البيانات وربطه بتطبيق فلاسك
db = SQLAlchemy(app, metadata=metadata)
migrate = Migrate(app, db, render_as_batch=True)


# ---- إعدادات التطبيق الأساسية ----
# !!! مهم جداً: استبدل هذا بمفتاح سري قوي وعشوائي وفريد لتطبيقك !!!
# يمكنك توليد واحد باستخدام: python -c 'import os; print(os.urandom(24))'
app.config['SECRET_KEY'] = 'fallback-secret-key-replace-me-in-production'
# يمكنك أيضاً تحميله من متغيرات البيئة لزيادة الأمان
# app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-secret-key')

# ---- إعدادات قاعدة البيانات ----
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# -----------------------------


# --- تعريف نماذج قاعدة البيانات (Data Models) ---

# نموذج جدول المناديب/المستخدمين
class Driver(db.Model):
    __tablename__ = 'drivers'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    default_starting_cartons = db.Column(db.Integer, nullable=False, server_default='61') # تأكد أنها هكذا

    def set_password(self, password):
        pw_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(pw_bytes, salt).decode('utf-8')

    def check_password(self, password):
        pw_bytes = password.encode('utf-8')
        stored_hash_bytes = self.password_hash.encode('utf-8')
        return bcrypt.checkpw(pw_bytes, stored_hash_bytes)

    def __repr__(self):
        return f'<Driver {self.username}>'

# نموذج جدول المنتجات الأساسية
class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    base_name = db.Column(db.String(150), nullable=False)
    brand = db.Column(db.String(100), nullable=True)
    category = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    variants = db.relationship('ProductVariant', backref='product', lazy=True)

    def __repr__(self):
        return f'<Product {self.base_name}>'

# نموذج جدول متغيرات المنتج (النكهات/الأحجام)
class ProductVariant(db.Model):
    __tablename__ = 'product_variants'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_name = db.Column(db.String(200), nullable=False)
    flavor = db.Column(db.String(50), nullable=True)
    size = db.Column(db.String(50), nullable=True)
    sku = db.Column(db.String(100), nullable=True, unique=True)
    price_per_carton = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<ProductVariant {self.variant_name}>'

# نموذج جدول المحلات
class Shop(db.Model):
    __tablename__ = 'shops'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.Text, nullable=True)
    map_link = db.Column(db.Text, nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)
    region_name = db.Column(db.String(100), nullable=True)
    current_balance = db.Column(db.Float, nullable=False, default=0.0)
    added_by_driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True) # ملاحظات عامة عن المحل
    location_link = db.Column(db.String(500), nullable=True)
    visits = db.relationship('Visit', backref='shop', lazy='dynamic')

    def __repr__(self):
        return f'<Shop {self.name}>'

# نموذج جدول الزيارات
class Visit(db.Model):
    __tablename__ = 'visits'
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False)
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=False)
    visit_timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    outcome = db.Column(db.String(50), nullable=True, default='Pending') # تم تغيير النوع لـ 50 والسماح بـ null أو Pending
    product_variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    quantity_sold = db.Column(db.Integer, nullable=True, default=0)
    price_per_carton_at_sale = db.Column(db.Float, nullable=True)
    amount_due_for_goods = db.Column(db.Float, nullable=True, default=0.0)
    cash_collected = db.Column(db.Float, nullable=True, default=0.0)
    payment_allocation = db.Column(db.String(20), nullable=True)
    no_sale_reason = db.Column(db.String(200), nullable=True)
    shop_balance_before = db.Column(db.Float, nullable=True)
    shop_balance_after = db.Column(db.Float, nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    sequence = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(50), nullable=False, default='Pending')
    # <<<--- تم حذف التعريف المكرر لـ notes من هنا --->>>
    notes = db.Column(db.Text, nullable=True) # التعريف الصحيح مرة واحدة
    # +++ أضف هذا السطر لتسجيل المبلغ المسدد من الذمة القديمة +++
    debt_paid = db.Column(db.Float, nullable=False, server_default='0.0')
    
    work_session_id = db.Column(db.Integer, db.ForeignKey('work_sessions.id'), nullable=True)
    work_session = db.relationship('WorkSession', backref=db.backref('visits', lazy='dynamic'))

    driver = db.relationship('Driver', backref=db.backref('visits', lazy='dynamic'))
    product_variant = db.relationship('ProductVariant', backref=db.backref('sales', lazy=True))

    def __repr__(self):
        return f'<Visit {self.id} - Shop {self.shop_id} by Driver {self.driver_id}>'

# نموذج جدول فترات العمل
class WorkSession(db.Model):
    __tablename__ = 'work_sessions'
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)
    session_date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date())
    driver = db.relationship('Driver', backref=db.backref('work_sessions', lazy=True))
    starting_cartons = db.Column(db.Integer, nullable=False) # <-- إرجاع False
    current_remaining_cartons = db.Column(db.Integer, nullable=False) # <-- إرجاع False
    start_latitude = db.Column(db.Float, nullable=True)
    start_longitude = db.Column(db.Float, nullable=True)
    current_remaining_packs = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    def __repr__(self):
        return f'<WorkSession {self.id} - Driver {self.driver_id} on {self.session_date}>'

# ... (بعد db = SQLAlchemy(app) و migrate = Migrate(app, db)) ...

# --- +++ تهيئة Serializer للتوكن +++ ---
# التأكد من أن المفتاح السري موجود قبل المتابعة
if not app.config.get('SECRET_KEY'):
    raise ValueError("SECRET_KEY not set in Flask config, required for token generation")

# إنشاء Serializer باستخدام المفتاح السري للتطبيق
# هذا الكائن سيقوم بتوليد توكنز تحتوي على timestamp ويمكن التحقق من صلاحيتها
token_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
# --------------------------------------

# --- Helper Functions for Bonus Calculation (Iterative Logic) ---
# تأكد من أن هذه القيم ثابتة أو اقرأها من مكان آخر إذا لزم الأمر
# --- دوال مساعدة لحساب البونص ---
# تأكد من وجود هذا الاستيراد في الأعلى

# عدد الباكيتات في الكرتونة الواحدة (تأكد من صحة هذه القيمة)
PACKS_PER_CARTON = 50

def _calculate_total_bonus(quantity):
    """
    يحسب إجمالي كراتين البونص وإجمالي باكيتات البونص
    بناءً على تطبيق الشرائح بشكل تكراري.
    !!! راجع الشرائح وقيم البونص هنا لتطابق قواعد شركتك النهائية !!!
    """
    if quantity <= 0:
        return 0, 0 # (كراتين بونص, باكيتات بونص)

    bonus_cartons = 0
    bonus_packs = 0
    q = quantity # متغير مؤقت للكمية المتبقية

    # --- !!! عدّل هذه الشرائح وقيم البونص حسب المعتمد لديكم !!! ---
    tiers = [
        {'threshold': 50, 'bonus_cartons': 7, 'bonus_packs': 0},
        {'threshold': 25, 'bonus_cartons': 3, 'bonus_packs': 0},
        {'threshold': 10, 'bonus_cartons': 1, 'bonus_packs': 0},
        {'threshold': 5,  'bonus_cartons': 0, 'bonus_packs': 15},
    ]
    # -------------------------------------------------------------

    # تطبيق الشرائح الأكبر أولاً
    for tier in tiers:
        threshold = tier['threshold']
        if q >= threshold:
            num_tiers = q // threshold
            bonus_cartons += num_tiers * tier['bonus_cartons']
            bonus_packs += num_tiers * tier['bonus_packs']
            q %= threshold # الكمية المتبقية

    # تطبيق القاعدة الأساسية (+2 باكيت/كرتونة) على المتبقي النهائي (0-4 كراتين)
    bonus_packs += q * 2

    return bonus_cartons, bonus_packs

def _calculate_bonus_cartons(quantity):
    """دالة مساعدة للحصول على بونص الكراتين فقط"""
    cartons, _ = _calculate_total_bonus(quantity)
    return cartons

def _calculate_total_bonus_packs(quantity):
    """دالة مساعدة للحصول على بونص الباكيتات فقط"""
    _, packs = _calculate_total_bonus(quantity)
    return packs
# --- نهاية الدوال المساعدة ---


# --- نقاط وصول API ---
# =========================================
# --- تعريف دالة login المعدلة ---
# =========================================
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({"message": "Missing username or password"}), 400

    username = data.get('username')
    password = data.get('password')

    # البحث عن المستخدم النشط
    driver = Driver.query.filter_by(username=username, is_active=True).first()

    # التحقق من وجود المستخدم وصحة كلمة المرور
    if driver and driver.check_password(password):
        # --- المصادقة ناجحة: قم بتوليد التوكن ---
        try:
            # البيانات التي نريد تضمينها في التوكن (فقط ID السائق يكفي)
            data_to_serialize = {'driver_id': driver.id}

            # توليد التوكن الموقع والمحدد بوقت (باستخدام الـ Serializer الذي عرفناه)
            # يمكنك إضافة معامل salt='some-salt' لمزيد من الأمان إذا أردت
            token = token_serializer.dumps(data_to_serialize)

            # --- تعديل الاستجابة لإعادة التوكن ومعلومات إضافية ---
            return jsonify({
                "message": "Login Successful!",
                "token": token, # <-- التوكن الجديد
                "driver_id": driver.id, # إبقاء ID السائق مفيد للواجهة
                "driver_name": driver.full_name # إرجاع الاسم أيضاً مفيد
                }), 200
            # ----------------------------------------------------

        except Exception as e:
            # في حالة حدوث خطأ أثناء توليد التوكن (نادر)
            print(f"Error generating token for driver {driver.id}: {e}") # استبدل بـ logging لاحقاً
            # يمكنك إضافة تسجيل للخطأ هنا logging.exception(e)
            return jsonify({"message": "Error generating authentication token"}), 500
        # --- نهاية جزء النجاح ---
    else:
        # المصادقة فشلت
        return jsonify({"message": "Invalid username or password"}), 401
# --- نهاية دالة login المعدلة ---

from functools import wraps
from flask import request, jsonify, g # تأكد من وجود request, jsonify, و g في استيراد flask
from itsdangerous import SignatureExpired, BadSignature # استيراد أنواع الأخطاء

# (تأكد أن token_serializer معرف بشكل عام كما في الخطوة السابقة)
# token_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        # تحقق من وجود التوكن في هيدر Authorization
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                # الهيدر يكون عادة "Bearer <token>"
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({"message": "Invalid Authorization header format"}), 401

        if not token:
            return jsonify({"message": "Token is missing"}), 401

        try:
            # التحقق من التوكن وفك تشفيره مع تحديد مدة صلاحية (مثلاً يوم واحد = 86400 ثانية)
            # يمكنك تغيير مدة الصلاحية حسب الحاجة
            max_age_seconds = 86400 # 24 hours
            data = token_serializer.loads(token, max_age=max_age_seconds)
            # تخزين driver_id المستخرج في 'g' ليكون متاحاً داخل الدالة الأصلية
            g.current_driver_id = data['driver_id']
            # يمكنك أيضاً جلب كائن السائق كاملاً إذا أردت
            # g.current_driver = db.session.get(Driver, g.current_driver_id)
            # if not g.current_driver:
            #     return jsonify({"message": "Token valid but driver not found"}), 401

        except SignatureExpired:
            return jsonify({"message": "Token has expired"}), 401
        except BadSignature:
            return jsonify({"message": "Token signature is invalid"}), 401
        except Exception as e: # لإلتقاط أي أخطاء أخرى محتملة
            print(f"Error decoding token: {e}")
            return jsonify({"message": "Token is invalid or processing error"}), 401

        # إذا كان التوكن صالحاً، قم بتنفيذ الدالة الأصلية للـ API route
        return f(*args, **kwargs)
    return decorated_function

# =========================================
#  API Endpoint: Get Dashboard Data for a Driver (معدلة لتشمل تفاصيل الكاش والمخزون)
# =========================================
@app.route('/driver/<int:driver_id>/dashboard', methods=['GET'])
@token_required
def get_driver_dashboard(driver_id):
    """
    جلب البيانات الملخصة لعرضها في شاشة الـ Dashboard للمندوب،
    بما في ذلك تفاصيل الكاش، حالة الجلسة النشطة، ومعلومات المخزون.
    """
    # جلب معلومات المندوب
    driver = db.session.get(Driver, driver_id)
    if not driver:
        return jsonify({"message": "Driver not found"}), 404
    driver_name = driver.full_name

    # المنطقة (لا تزال مؤقتة)
    assigned_region = "المنطقة الشرقية (مؤقت)" # TODO: جلب المنطقة الحقيقية

    try:
        # --- حسابات الزيارات ---
        # جلب كل زيارات المندوب (يمكن فلترتها بتاريخ اليوم لاحقاً للإحصائيات اليومية فقط)
        # جلب فقط الزيارات المكتملة لحساب الإحصائيات المالية والعددية منها
        completed_visits_query = Visit.query.filter(
            Visit.driver_id == driver_id,
            Visit.status == 'Completed'
            # يمكنك إضافة فلتر للتاريخ هنا إذا أردت إحصائيات اليوم فقط
            # func.date(Visit.visit_timestamp) == date.today()
        )

        completed_visits = completed_visits_query.all()
        total_completed_visits = len(completed_visits) # عدد الزيارات المكتملة

        # جلب الزيارات المعلقة
        pending_visits_count = Visit.query.filter(
             Visit.driver_id == driver_id,
             Visit.status == 'Pending'
             # func.date(Visit.visit_timestamp) == date.today() # إذا أردت المعلقة لليوم فقط
        ).count()

        total_visits_count = total_completed_visits + pending_visits_count # الإجمالي (مكتمل + معلق)

        # حساب عدد المبيعات من الزيارات المكتملة
        sales_count = sum(1 for v in completed_visits if v.outcome == 'Sale')

        # --- حسابات الكاش المفصلة (من الزيارات المكتملة) ---
        # 1. إجمالي كاش المبيعات (cash_collected من زيارات البيع)
        #    (نفترض أن cash_collected يسجل فقط المبلغ مقابل البضاعة في حالة البيع)
        sales_cash_query = db.session.query(func.sum(Visit.cash_collected)).filter(
             Visit.driver_id == driver_id,
             Visit.status == 'Completed',
             Visit.outcome == 'Sale' # فقط من زيارات البيع
        ).scalar()
        total_sales_cash = float(sales_cash_query) if sales_cash_query is not None else 0.0

        # 2. إجمالي الذمم المحصلة (debt_paid من كل الزيارات المكتملة)
        debt_paid_query = db.session.query(func.sum(Visit.debt_paid)).filter(
            Visit.driver_id == driver_id,
            Visit.status == 'Completed',
            Visit.debt_paid > 0 # فقط الزيارات التي تم فيها تحصيل ذمة
        ).scalar()
        total_debt_paid = float(debt_paid_query) if debt_paid_query is not None else 0.0

        # 3. عدد عمليات تحصيل الذمم
        debt_payments_count_query = db.session.query(func.count(Visit.id)).filter(
             Visit.driver_id == driver_id,
             Visit.status == 'Completed',
             Visit.debt_paid > 0 # عدد الزيارات التي تم فيها تحصيل ذمة
        ).scalar()
        debt_payments_count = int(debt_payments_count_query) if debt_payments_count_query is not None else 0

        # 4. إجمالي الكاش المستلم (المجموع الكلي)
        total_cash_collected = total_sales_cash + total_debt_paid
        # ----------------------------------------------------

        # --- البحث عن الجلسة النشطة لليوم الحالي ومعلومات المخزون ---
        today_date = date.today()
        active_session_data = None
        active_session = WorkSession.query.filter_by(
            driver_id=driver_id,
            session_date=today_date,
            end_time=None # البحث عن جلسة لم تنته بعد
        ).first()

        if active_session:
            active_session_data = {
                "session_id": active_session.id,
                "start_time": active_session.start_time.isoformat() if active_session.start_time else None, # Handle potential None
                "starting_cartons": active_session.starting_cartons,
                "remaining_cartons": active_session.current_remaining_cartons,
                "remaining_packs": active_session.current_remaining_packs
                # -------------------------------------------
            }
        # -------------------------------------------------------

        # تجهيز الرد النهائي بالبيانات الجديدة
        dashboard_data = {
            "driver_name": driver_name,
            "assigned_region": assigned_region,
            "counts": {
                # تغيير بسيط في معنى الإحصائيات لتكون أوضح
                "total_pending": pending_visits_count,
                "total_completed": total_completed_visits,
                "sales_in_completed": sales_count,
                # يمكنك إضافة total_visits_count إذا أردت المجموع
            },
            # --- إضافة البيانات المالية المفصلة ---
            "financials": {
                "total_sales_cash": total_sales_cash,
                "total_debt_paid": total_debt_paid,
                "debt_payments_count": debt_payments_count,
                "total_cash_overall": total_cash_collected # المجموع الكلي
            },
             # ------------------------------------
            "active_session": active_session_data # بيانات الجلسة النشطة + المخزون
        }

        return jsonify(dashboard_data), 200

    except Exception as e:
        print(f"Error fetching dashboard data for driver {driver_id}: {e}")
        import traceback
        traceback.print_exc() # لطباعة تفاصيل الخطأ للمساعدة
        return jsonify({"message": "Error fetching dashboard data", "error": str(e)}), 500

# --- اترك باقي المسارات وكود التشغيل كما هو ---
# =========================================
#  API Endpoint: Get Visits for a Driver (معدل ليدعم التسلسل والفلترة)
# =========================================
@app.route('/driver/<int:driver_id>/visits', methods=['GET'])
@token_required
def get_driver_visits(driver_id):
    # <<<--- تم تعديل طريقة جلب السائق هنا --->>>
    driver = db.session.get(Driver, driver_id) # استخدام Session.get الأحدث
    if not driver:
        return jsonify({"message": "Driver not found"}), 404

    status_filter = request.args.get('status')
    try:
        query = db.session.query(
            Visit.id.label('visit_id'), Visit.status.label('visit_status'),
            Visit.notes.label('visit_notes'), Visit.sequence.label('visit_sequence'),
            Shop.id.label('shop_id'), Shop.name.label('shop_name'),
            Shop.location_link.label('shop_location_link'),
            Shop.current_balance.label('shop_balance') # الاسم الصحيح
        ).join(Shop, Visit.shop_id == Shop.id)\
         .filter(Visit.driver_id == driver_id)

        if status_filter and status_filter in ['Pending', 'Completed', 'Attempted']:
            query = query.filter(Visit.status == status_filter)

        visits_data = query.order_by(Visit.sequence.asc().nulls_last(), Visit.id.asc()).all()

        results_list = [ {
                "visit_id": visit.visit_id, "shop_id": visit.shop_id,
                "shop_name": visit.shop_name, "shop_location_link": visit.shop_location_link,
                "shop_balance": float(visit.shop_balance) if visit.shop_balance is not None else 0.0,
                "visit_status": visit.visit_status, "visit_notes": visit.visit_notes,
                "visit_sequence": visit.visit_sequence
            } for visit in visits_data ]
        return jsonify(results_list), 200
    except Exception as e:
        print(f"Error fetching visits for driver {driver_id} with status '{status_filter}': {e}")
        return jsonify({"message": "Error fetching visits data"}), 500
    

# --- دالة مساعدة لحساب بونص الكراتين فقط ---
def _calculate_bonus_cartons(quantity):
    if quantity >= 120: return 20
    if quantity >= 100: return 15
    if quantity >= 50: return 7
    if quantity >= 25: return 3
    if quantity >= 10: return 1
    return 0 # لا يوجد بونص كراتين لأقل من 10
# ------------------------------------------


# =========================================
#  API Endpoint: Update / Complete a Visit (النسخة النهائية بحساب الباكيتات والكراتين)
# =========================================
@app.route('/visits/<int:visit_id>', methods=['PUT'])
@token_required
def update_visit(visit_id):
    print(f"--- Request received for PUT /visits/{visit_id} ---")
    visit = db.get_or_404(Visit, visit_id, description="Visit not found")

    # --- التحقق من صلاحية السائق ---
    authenticated_driver_id = getattr(g, 'current_driver_id', None)
    if visit.driver_id != authenticated_driver_id:
         print(f"WARNING: Driver {authenticated_driver_id} attempted to update visit {visit_id} owned by driver {visit.driver_id}.")
         return jsonify({"message": "Forbidden: You are not authorized to update this visit"}), 403
    # -------------------------

    data = request.get_json()
    if not data: return jsonify({"message": "Missing request body"}), 400

    outcome = data.get('outcome')
    notes = data.get('notes') # الملاحظات العامة
    if not outcome or outcome not in ['Sale', 'NoSale', 'Postponed']:
        return jsonify({"message": "Missing or invalid 'outcome'"}), 400

    try:
        shop = visit.shop
        if not shop:
             print(f"ERROR: Visit {visit_id} has no associated shop in DB.")
             return jsonify({"message": "Integrity Error: Shop associated with visit not found"}), 500

        # --- التحقق إذا كانت جلسة الزيارة الأصلية مغلقة ---
        is_original_session_closed = False
        if visit.work_session and visit.work_session.end_time is not None:
            is_original_session_closed = True
            print(f">>> Visit {visit_id} belongs to a closed session. Current inventory will NOT be adjusted.")
        # ----------------------------------------------------

        # --- قراءة المدخلات الرقمية بأمان ---
        cash_collected_input = 0.0; debt_paid_input = 0.0; new_quantity_sold = 0; product_variant_id = None
        try:
            cash_collected_input = float(data.get('cash_collected') or 0.0)
            debt_paid_input = float(data.get('debt_paid') or 0.0)
            if cash_collected_input < 0 or debt_paid_input < 0: return jsonify({"message": "Negative values not allowed"}), 400
            if outcome == 'Sale':
                 quantity_str = data.get('quantity_sold')
                 if not quantity_str: return jsonify({"message": "Missing 'quantity_sold' for Sale"}), 400
                 new_quantity_sold = int(quantity_str) # التحويل لـ int سيعطي ValueError إذا لم يكن رقم
                 product_variant_id = data.get('product_variant_id')
                 if new_quantity_sold <= 0: return jsonify({"message": "'quantity_sold' must be positive for Sale"}), 400
                 if not product_variant_id: return jsonify({"message": "Missing 'product_variant_id' for Sale"}), 400
                 try: product_variant_id = int(product_variant_id)
                 except (ValueError, TypeError): return jsonify({"message": "Invalid 'product_variant_id' format"}), 400
        except (ValueError, TypeError) as num_err:
            return jsonify({"message": f"Invalid numeric format: {num_err}"}), 400
        # --------------------------------

        # --- قراءة القيم القديمة ---
        original_shop_balance = shop.current_balance or 0.0
        old_quantity_sold = visit.quantity_sold or 0
        new_shop_balance = original_shop_balance

        # --- حساب التغير الصافي للمخزون (كراتين وباكيتات) ---
        net_carton_change = 0
        net_pack_change = 0

        new_bonus_cartons, new_bonus_packs = _calculate_total_bonus(new_quantity_sold) if outcome == 'Sale' else (0, 0)
        old_bonus_cartons, old_bonus_packs = _calculate_total_bonus(old_quantity_sold) if old_quantity_sold > 0 else (0, 0)

        if outcome == 'Sale':
            net_carton_change = (new_quantity_sold - old_quantity_sold) + (new_bonus_cartons - old_bonus_cartons)
            net_pack_change = new_bonus_packs - old_bonus_packs
        elif old_quantity_sold > 0 and outcome in ['NoSale', 'Postponed']:
            # إلغاء بيع سابق (إرجاع للمخزون)
            net_carton_change = (0 - old_quantity_sold) - old_bonus_cartons
            net_pack_change = 0 - old_bonus_packs
        # -------------------------------------------------

        # --- تطبيق تعديل المخزون الدقيق (إذا كان هناك تغيير والجلسة الأصلية غير مغلقة) ---
        final_remaining_cartons = None # لتخزين القيمة النهائية للرد
        final_remaining_packs = None

        if (net_carton_change != 0 or net_pack_change != 0) and not is_original_session_closed:
            print(f">>> Calculating inventory adjustment. Cartons Change: {net_carton_change}, Packs Change: {net_pack_change}")
            today_date = date.today()
            active_session = WorkSession.query.filter_by(driver_id=visit.driver_id, session_date=today_date, end_time=None).first()

            if active_session:
                current_cartons = active_session.current_remaining_cartons or 0
                current_packs = active_session.current_remaining_packs or 0

                # 1. حساب رصيد الباكيتات المبدئي بعد التغيير المباشر
                packs_after_direct_change = current_packs - net_pack_change

                # 2. حساب تعديل الكراتين بسبب الباكيتات
                cartons_to_adjust_for_packs = 0
                final_packs = packs_after_direct_change

                if packs_after_direct_change < 0: # نحتاج لفتح كراتين
                    packs_needed = abs(packs_after_direct_change)
                    cartons_to_adjust_for_packs = math.ceil(packs_needed / PACKS_PER_CARTON) # عدد الكراتين المطلوب فتحها (يُخصم)
                    packs_gained = cartons_to_adjust_for_packs * PACKS_PER_CARTON
                    final_packs = packs_gained - packs_needed # الباكيتات المتبقية بعد فتح الكراتين وتلبية الحاجة
                    print(f">>> Opened {cartons_to_adjust_for_packs} carton(s) to cover pack deficit.")
                elif packs_after_direct_change >= PACKS_PER_CARTON: # يمكن تحويل باكيتات لكراتين (إعادة)
                    cartons_to_adjust_for_packs = - (packs_after_direct_change // PACKS_PER_CARTON) # عدد الكراتين المُعادة (يُضاف)
                    final_packs = packs_after_direct_change % PACKS_PER_CARTON # الباكيتات المفردة المتبقية
                    print(f">>> Converted {abs(cartons_to_adjust_for_packs)} full cartons back from packs.")

                # 3. حساب إجمالي خصم الكراتين المطلوب
                total_carton_deduction = net_carton_change + cartons_to_adjust_for_packs

                # 4. التحقق النهائي من كفاية المخزون
                if current_cartons < total_carton_deduction:
                    print(f"ERROR: Insufficient TOTAL inventory for visit {visit_id}. Required Carton Deduction: {total_carton_deduction}, Available Cartons: {current_cartons}")
                    return jsonify({"message": f"المخزون الإجمالي غير كافٍ. مطلوب خصم: {total_carton_deduction} كرتونة, المتوفر: {current_cartons}"}), 409

                # 5. تطبيق التغييرات النهائية على الأرصدة
                final_remaining_cartons = current_cartons - total_carton_deduction
                final_remaining_packs = final_packs # تم حسابه في الخطوة 2

                # 6. تحديث أرصدة الجلسة النشطة
                active_session.current_remaining_cartons = final_remaining_cartons
                active_session.current_remaining_packs = final_remaining_packs
                print(f"Inventory adjusted for ACTIVE session {active_session.id}. Remaining C: {final_remaining_cartons}, Remaining P: {final_remaining_packs}")

            else: # لم يتم العثور على جلسة نشطة
                print(f"Warning: No active work session found for driver {visit.driver_id} on {today_date} to adjust inventory.")
        elif (net_carton_change != 0 or net_pack_change != 0) and is_original_session_closed:
             print(f">>> Inventory change calculated (C:{net_carton_change}, P:{net_pack_change}), but skipped because visit {visit_id} belongs to a closed session.")
        # --- نهاية تعديل المخزون ---


        # --- تحديث سجل الزيارة ورصيد المحل ---
        # (تحديث تفاصيل الزيارة حسب الـ Outcome كما في الكود السابق الذي أرسلته)
        sale_value = 0.0 # إعادة حساب قيمة البيع إذا كان Outcome هو Sale
        product_price = None
        if outcome == 'Sale':
            product_variant = db.get_or_404(ProductVariant, product_variant_id)
            if not product_variant.is_active: return jsonify({"message": f"Product variant {product_variant_id} is inactive"}), 400
            product_price = product_variant.price_per_carton
            if product_price is None: return jsonify({"message": f"Product variant {product_variant_id} is missing price."}), 400
            sale_value = new_quantity_sold * product_price
            total_payment_received = cash_collected_input + debt_paid_input
            balance_change = sale_value - total_payment_received
            new_shop_balance = original_shop_balance + balance_change
            if new_shop_balance < 0: return jsonify({"message": "Negative shop balance error."}), 400

            visit.product_variant_id = product_variant_id; visit.quantity_sold = new_quantity_sold;
            visit.price_per_carton_at_sale = product_price; visit.amount_due_for_goods = sale_value;
            visit.cash_collected = cash_collected_input; visit.debt_paid = debt_paid_input;
            visit.status = 'Completed'; visit.no_sale_reason = None;

        elif outcome == 'NoSale':
            total_payment_received = debt_paid_input
            balance_change = 0 - total_payment_received
            new_shop_balance = original_shop_balance + balance_change
            if new_shop_balance < 0: return jsonify({"message": "Negative shop balance error."}), 400

            visit.product_variant_id = None; visit.quantity_sold = 0; visit.price_per_carton_at_sale = None;
            visit.amount_due_for_goods = 0; visit.cash_collected = 0.0; visit.debt_paid = debt_paid_input;
            visit.status = 'Completed'; visit.no_sale_reason = notes;

        elif outcome == 'Postponed':
            new_shop_balance = original_shop_balance # No financial change
            visit.status = 'Pending'; visit.no_sale_reason = notes;
            visit.product_variant_id = None; visit.quantity_sold = 0; visit.price_per_carton_at_sale = None;
            visit.amount_due_for_goods = 0; visit.cash_collected = 0.0; visit.debt_paid = 0.0;

        # تحديث الحقول المشتركة للزيارة ورصيد المحل
        visit.outcome = outcome
        visit.visit_timestamp = datetime.utcnow()
        visit.notes = notes # تحديث الملاحظات العامة
        if 'latitude' in data: visit.latitude = data.get('latitude') # تحديث إحداثيات تسجيل الزيارة إن وجدت
        if 'longitude' in data: visit.longitude = data.get('longitude')
        visit.shop_balance_before = original_shop_balance
        visit.shop_balance_after = new_shop_balance
        shop.current_balance = new_shop_balance # تحديث رصيد المحل النهائي

        # --- ربط الزيارة بالجلسة النشطة ---
        if outcome in ['Completed', 'Postponed'] and visit.work_session_id is None:
             today_date_for_link = date.today()
             active_session_for_link = WorkSession.query.filter_by(driver_id=visit.driver_id, session_date=today_date_for_link, end_time=None).first()
             if active_session_for_link:
                  visit.work_session_id = active_session_for_link.id
                  print(f">>> Linking visit {visit_id} to active session {active_session_for_link.id}")
             else:
                  print(f">>> Could not link visit {visit_id}: No active session found.")
        # -----------------------------------

        print(">>> About to commit visit update changes...")
        db.session.commit() # حفظ كل التغييرات
        print(">>> Commit successful.")

        # إرجاع الرد مع الأرصدة المحدثة للمخزون والرصيد المالي
        return jsonify({
            "message": f"Visit {visit_id} updated successfully with outcome: {outcome}",
            "new_balance": new_shop_balance,
            # التأكد من إرجاع القيم حتى لو لم يتم التحديث (تبقى كما هي)
            "remaining_cartons": (active_session.current_remaining_cartons if 'active_session' in locals() and active_session else None) if final_remaining_cartons is None else final_remaining_cartons,
            "remaining_packs": (active_session.current_remaining_packs if 'active_session' in locals() and active_session else None) if final_remaining_packs is None else final_remaining_packs
            }), 200

    except Exception as e:
        db.session.rollback()
        print(f"Error updating visit {visit_id}: {e}")
        traceback.print_exc()
        return jsonify({"message": "An unexpected error occurred while updating visit data", "error": str(e)}), 500
# --- End Update Visit ---
   

# =========================================
#  API Endpoint: Start Work Session (MODIFIED to accept and save coordinates)
# =========================================
@app.route('/driver/<int:driver_id>/sessions/start', methods=['POST'])
@token_required # افتراض أنه يضيف g.current_driver_id
def start_work_session(driver_id):
    """إنشاء سجل جلسة عمل جديدة للمندوب عند بدء العمل، مع تهيئة المخزون وحفظ إحداثيات البدء."""
    print(f"--- Request received for POST /driver/{driver_id}/sessions/start ---")

    # --- التحقق من صلاحية السائق (مهم للأمان) ---
    authenticated_driver_id = getattr(g, 'current_driver_id', None)
    # if authenticated_driver_id is None: # Should be caught by decorator
    #     return jsonify({"message": "Authentication context error"}), 500
    if authenticated_driver_id != driver_id:
         print(f"WARNING: Driver {authenticated_driver_id} attempted to start session for driver {driver_id}.")
         return jsonify({"message": "Forbidden: You cannot start a session for another driver"}), 403
    # --------------------------------------------

    # التحقق من وجود المندوب
    driver = db.get_or_404(Driver, driver_id, description="Driver not found")

    # التحقق من عدم وجود جلسة نشطة بالفعل لهذا اليوم
    today_date = date.today()
    active_session = WorkSession.query.filter_by(
        driver_id=driver_id,
        session_date=today_date,
        end_time=None
    ).first()

    if active_session:
        # إذا وجدت جلسة نشطة، أعد بياناتها
        print(f"Active session {active_session.id} already exists for driver {driver_id} on {today_date}.")
        return jsonify({
            "message": "An active session already exists for today.",
            "session_id": active_session.id,
            "start_time": active_session.start_time.isoformat() if active_session.start_time else None,
            "starting_cartons": active_session.starting_cartons,
            "remaining_cartons": active_session.current_remaining_cartons,
            "start_latitude": active_session.start_latitude, # أعد الإحداثيات أيضاً
            "start_longitude": active_session.start_longitude
        }), 409 # Conflict

    # --- !!! التعديل: قراءة الإحداثيات من جسم الطلب !!! ---
    data = request.get_json()
    start_lat = None
    start_lon = None
    if data:
        raw_lat = data.get('latitude') # اقرأ المفتاح 'latitude'
        raw_lon = data.get('longitude') # اقرأ المفتاح 'longitude'
        try:
            # حاول تحويل القيم إلى float (إذا لم تكن None)
            start_lat = float(raw_lat) if raw_lat is not None else None
            start_lon = float(raw_lon) if raw_lon is not None else None
            print(f"Received coordinates: Lat={start_lat}, Lon={start_lon}")
        except (ValueError, TypeError):
             # إذا فشل التحويل (القيمة ليست رقمية) احفظها كـ None
             print(f"Warning: Received invalid format for coordinates. Lat='{raw_lat}', Lon='{raw_lon}'. Saving as NULL.")
             start_lat = None
             start_lon = None
    else:
        # لم يتم إرسال body مع الطلب (قد يحدث إذا فشل Flutter في إرسالها)
        print("Warning: No request body received for starting session. Coordinates will be NULL.")
    # --- !!! نهاية التعديل !!! ---

    # إنشاء جلسة جديدة
    try:
        start_quantity = driver.default_starting_cartons or 0

        new_session = WorkSession(
            driver_id=driver_id,
            start_time=datetime.utcnow(), # وقت السيرفر
            session_date=today_date,
            starting_cartons=start_quantity,
            current_remaining_cartons=start_quantity,
            # --- !!! التعديل: إضافة الإحداثيات عند الإنشاء !!! ---
            start_latitude=start_lat,
            start_longitude=start_lon
            # -----------------------------------------------
        )

        db.session.add(new_session)
        # تنفيذ flush للحصول على ID قبل commit (مفيد أحياناً لإرجاعه في الرد)
        db.session.flush()
        session_id = new_session.id
        start_time_iso = new_session.start_time.isoformat() if new_session.start_time else None

        db.session.commit() # حفظ الجلسة الجديدة في قاعدة البيانات
        print(f"New session {session_id} created for driver {driver_id} at {start_time_iso} with coords ({start_lat}, {start_lon}).")

        # --- إرجاع بيانات الجلسة الجديدة (بما فيها الإحداثيات) ---
        return jsonify({
            "message": "Work session started successfully.",
            "session_id": session_id,
            "start_time": start_time_iso,
            "starting_cartons": new_session.starting_cartons,
            "remaining_cartons": new_session.current_remaining_cartons,
            "start_latitude": new_session.start_latitude, # <-- إرجاع الإحداثيات
            "start_longitude": new_session.start_longitude # <-- إرجاع الإحداثيات
        }), 201 # Created

    except Exception as e:
        db.session.rollback()
        print(f"Error starting work session for driver {driver_id}: {e}")
        import traceback # تأكد من وجود الاستيراد في الأعلى
        traceback.print_exc()
        return jsonify({"message": "Error starting work session", "error": str(e)}), 500

# =========================================================
# --- إضافة نقطة API جديدة لجلب تفاصيل زيارة واحدة ---
# =========================================================
@app.route('/visits/<int:visit_id>', methods=['GET'])
@token_required
def get_visit_details(visit_id):
    visit = db.session.get(Visit, visit_id)
    if not visit:
        return jsonify({"message": "Visit not found"}), 404

    # --- Authorization Check (Keep as is) ---
    authenticated_driver_id = getattr(g, 'current_driver_id', None)
    if authenticated_driver_id is None:
         return jsonify({"message": "Authentication error"}), 500
    if visit.driver_id != authenticated_driver_id:
         return jsonify({"message": "Forbidden: You are not authorized to view this visit"}), 403
    # ------------------------------------------

    # --- !!! التعديل: جلب بيانات المحل المرتبط !!! ---
    shop = visit.shop # افتراض أن العلاقة اسمها 'shop' في موديل Visit
    shop_data = None
    if shop:
        shop_data = {
            "shop_id": shop.id,
            "name": shop.name,
            "address": shop.address,                  # <-- إضافة عنوان المحل
            "region_name": shop.region_name,          # <-- إضافة المنطقة/المحافظة
            "location_link": shop.location_link,      # <-- إضافة رابط المحل
            "latitude": shop.latitude,                # <-- إضافة خط عرض المحل
            "longitude": shop.longitude,              # <-- إضافة خط طول المحل
            "current_balance": shop.current_balance   # رصيد المحل قد يكون مفيداً أيضاً
            # أضف أي حقول أخرى من المحل قد تحتاجها الواجهة
        }
    # --- !!! نهاية التعديل !!! ---


    # --- استيراد datetime و date في أعلى ملف app.py إذا لم يكونا موجودين ---
    from datetime import datetime, date
    # -------------------------------------------------------------------

    # --- (داخل دالة get_visit_details) ---

    # ... (الكود الخاص بجلب visit و shop و shop_data كما هو) ...

    # --- التعامل الآمن مع حقل visit_timestamp قبل بناء القاموس ---
    visit_ts_value = visit.visit_timestamp
    visit_ts_iso = None # القيمة الافتراضية
    if isinstance(visit_ts_value, (datetime, date)): # تحقق من النوع أولاً
        try:
            visit_ts_iso = visit_ts_value.isoformat() # حوله لنص إذا كان النوع صحيحاً
        except Exception as fmt_err:
            print(f"ERROR formatting visit_timestamp {visit_ts_value}: {fmt_err}")
            # إذا فشل التحويل لسبب ما، ستبقى القيمة None
    # --- نهاية التعامل الآمن ---


    # --- تجهيز بيانات الزيارة للإرجاع بتنسيق JSON (باستخدام القيمة المعالجة) ---
    visit_data = {
        "visit_id": visit.id,
        "driver_id": visit.driver_id,
        "shop": shop_data, # بيانات المحل المتداخلة

        "visit_timestamp": visit_ts_iso, # <-- استخدام القيمة المعالجة بأمان

        "outcome": visit.outcome,
        "product_variant_id": visit.product_variant_id,
        "quantity_sold": visit.quantity_sold,
        "cash_collected": visit.cash_collected,
        "debt_paid": visit.debt_paid,
        "notes": visit.notes,
        "no_sale_reason": visit.no_sale_reason,
        "status": visit.status,
        "sequence": visit.sequence,

        # إحداثيات الزيارة نفسها (إذا أردت الإبقاء عليها)
        "visit_latitude": visit.latitude,
        "visit_longitude": visit.longitude,

        "shop_balance_before": visit.shop_balance_before,
        "shop_balance_after": visit.shop_balance_after,
        "price_per_carton_at_sale": visit.price_per_carton_at_sale,
        "amount_due_for_goods": visit.amount_due_for_goods

        # !!! مهم: طبق نفس منطق التحقق الآمن (isinstance) على أي حقول تاريخ/وقت أخرى !!!
        # قد تكون موجودة في visit_data أو shop_data إذا كنت ترجعها (مثل created_at)
    }
    return jsonify(visit_data), 200
    # --- نهاية الدالة ---

# ==============================================================
# --- تعديل/إضافة نقطة API لإضافة محل جديد مع إنشاء زيارة ---
# ===============================================================
@app.route('/shops', methods=['POST'])
@app.route('/shops', methods=['POST'])
@token_required # حماية نقطة الـ API
def add_new_shop():
    driver_id = getattr(g, 'current_driver_id', None)
    if not driver_id:
        return jsonify({"message": "Authentication error: Driver ID not found"}), 500

    data = request.get_json()
    if not data:
        return jsonify({"message": "Missing request body"}), 400

    shop_name = data.get('name')
    if not shop_name or not isinstance(shop_name, str) or len(shop_name.strip()) == 0:
        return jsonify({"message": "Missing or invalid shop 'name' field"}), 400

    # قراءة الحقول الاختيارية (بما فيها رابط الموقع)
    address = data.get('address')
    phone_number = data.get('phone_number')
    contact_person = data.get('contact_person')
    region_name = data.get('region_name')
    notes = data.get('notes')
    location_link = data.get('location_link') # <-- قراءة رابط الموقع
    latitude_str = data.get('latitude')
    longitude_str = data.get('longitude')

    lat_float = None
    lon_float = None
    try:
         if latitude_str is not None: lat_float = float(latitude_str)
         if longitude_str is not None: lon_float = float(longitude_str)
    except (ValueError, TypeError):
         return jsonify({"message": "Invalid format for latitude or longitude"}), 400

    # إنشاء كائن المحل الجديد
    new_shop = Shop(
        name=shop_name.strip(),
        address=address,
        phone_number=phone_number,
        contact_person=contact_person,
        region_name=region_name, # قد نحتاج لجلب منطقة السائق هنا؟
        notes=notes,
        location_link=location_link, # <-- حفظ رابط الموقع
        latitude=lat_float,
        longitude=lon_float,
        added_by_driver_id=driver_id,
        # current_balance=0.0, is_active=True (تأتي من النموذج افتراضياً)
    )

    # حفظ المحل وإنشاء الزيارة داخل Transaction واحد
    try:
        # 1. إضافة المحل للجلسة
        db.session.add(new_shop)
        # 2. تنفيذ flush للحصول على ID المحل الجديد قبل الـ commit
        #    (ضروري لاستخدامه كمفتاح أجنبي في الزيارة)
        db.session.flush()

        # 3. إنشاء سجل زيارة جديد لهذا المحل والمندوب بتاريخ اليوم
        today_date = date.today()
        new_visit = Visit(
            driver_id=driver_id,
            shop_id=new_shop.id, # <-- استخدام ID المحل الجديد
            status='Pending',     # حالة الزيارة معلقة
            sequence=None,        # الترتيب null ليظهر في نهاية القائمة
            visit_timestamp=datetime.utcnow() # أو الاعتماد على القيمة الافتراضية
            # outcome وغيرها تكون null أو قيمها الافتراضية
        )
        # 4. إضافة الزيارة للجلسة
        db.session.add(new_visit)

        # 5. تنفيذ الـ commit لحفظ المحل والزيارة معاً
        db.session.commit()

        print(f"Shop '{new_shop.name}' (ID: {new_shop.id}) added and Visit (ID: {new_visit.id}) created.") # طباعة للتأكيد

        # إرجاع تفاصيل المحل الجديد
        return jsonify({
            "message": "Shop added successfully and scheduled for visit!",
            "shop": {
                "id": new_shop.id,
                "name": new_shop.name,
                "address": new_shop.address,
                "location_link": new_shop.location_link, # إرجاع الرابط أيضاً
                # ... يمكنك إضافة باقي التفاصيل إذا احتاجتها الواجهة ...
            }
        }), 201 # 201 Created

    except Exception as e:
        db.session.rollback() # تراجع عند حدوث أي خطأ
        print(f"Error adding new shop or visit: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"message": "Failed to add shop or schedule visit", "error": str(e)}), 500

# --- نهاية نقطة API إضافة محل ---

# =========================================
#  API Endpoint: Get Active Product Variants
# =========================================
@app.route('/product_variants', methods=['GET'])
@token_required
def get_active_product_variants():
    """
    جلب قائمة بمتغيرات المنتجات النشطة المتاحة للبيع.
    يعيد قائمة تحتوي على ID, اسم المتغير, وسعر الكرتونة.
    """
    try:
        # جلب فقط المتغيرات النشطة (is_active=True)
        active_variants = ProductVariant.query.filter_by(is_active=True)\
                                            .order_by(ProductVariant.variant_name)\
                                            .all()

        # تنسيق النتائج
        results_list = [
            {
                "id": variant.id,
                "variant_name": variant.variant_name, # الاسم الذي سيظهر للمندوب
                "price_per_carton": variant.price_per_carton
            } for variant in active_variants
        ]

        return jsonify(results_list), 200

    except Exception as e:
        print(f"Error fetching active product variants: {e}")
        return jsonify({"message": "Error fetching product variants"}), 500

# --- اترك باقي المسارات وكود التشغيل كما هو ---


# =========================================
#  API Endpoint: Get Active Work Session for Driver Today
# =========================================
@app.route('/driver/<int:driver_id>/sessions/active', methods=['GET'])
@token_required
def get_active_session(driver_id):
    """
    التحقق من وجود جلسة عمل نشطة للمندوب في تاريخ اليوم.
    يعيد تفاصيل الجلسة إذا وجدت، أو رسالة إذا لم توجد.
    """
    # التحقق من وجود المندوب (اختياري)
    driver = db.session.get(Driver, driver_id)
    if not driver:
        return jsonify({"message": "Driver not found"}), 404

    today_date = date.today()
    try:
        active_session = WorkSession.query.filter_by(
            driver_id=driver_id,
            session_date=today_date,
            end_time=None # البحث عن جلسة لم تنته بعد
        ).first()

        if active_session:
            # وجدت جلسة نشطة
            return jsonify({
                "active_session_found": True,
                "session_id": active_session.id,
                "start_time": active_session.start_time.isoformat() # أرسل وقت البدء
            }), 200
        else:
            # لا توجد جلسة نشطة
            return jsonify({
                "active_session_found": False
            }), 200 # نرجع 200 OK حتى لو لم توجد جلسة، لأن الطلب نفسه ناجح

    except Exception as e:
        print(f"Error fetching active session for driver {driver_id}: {e}")
        return jsonify({"message": "Error checking active session"}), 500

# --- اترك باقي المسارات وكود التشغيل كما هو ---



# =========================================
#  API Endpoint: End Work Session
# =========================================
@app.route('/driver/<int:driver_id>/sessions/end', methods=['PUT']) # استخدام PUT لتحديث الجلسة
@token_required
def end_work_session(driver_id):
    """تحديث جلسة العمل النشطة للمندوب بإضافة وقت الانتهاء"""
     # التحقق من وجود المندوب
    driver = db.session.get(Driver, driver_id)
    if not driver:
        return jsonify({"message": "Driver not found"}), 404

    # البحث عن الجلسة النشطة لهذا اليوم
    today_date = date.today()
    active_session = WorkSession.query.filter_by(
        driver_id=driver_id,
        session_date=today_date,
        end_time=None
    ).first()

    if not active_session:
        # لا توجد جلسة نشطة لإنهاءها
        return jsonify({"message": "No active work session found to end for today."}), 404 # Not Found

    # تحديث وقت الانتهاء
    try:
        active_session.end_time = datetime.utcnow() # وقت السيرفر الحالي
        db.session.commit()
        return jsonify({
            "message": "Work session ended successfully.",
            "session_id": active_session.id,
            "start_time": active_session.start_time.isoformat(),
            "end_time": active_session.end_time.isoformat()
        }), 200 # OK
    except Exception as e:
        db.session.rollback()
        print(f"Error ending work session {active_session.id}: {e}")
        return jsonify({"message": "Error ending work session"}), 500

# --- اترك باقي المسارات وكود التشغيل كما هو ---


# تشغيل التطبيق (وضع التطوير)
if __name__ == '__main__':
    instance_path = os.path.join(basedir, 'instance')
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
    app.run(host='0.0.0.0', port=5000, debug=True)