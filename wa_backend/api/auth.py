from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, func
from database import get_db
from models import Driver, SystemAuditLog, TokenBlacklist, RefreshToken, utc_now
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
security = HTTPBearer()
from schemas import LoginRequest, LoginResponse
import jwt
from datetime import datetime, timedelta, timezone
from config import Config
import traceback
import asyncio
import logging
import bcrypt # +++ الدرع الفولاذي: استدعاء مكتبة التشفير مباشرة +++

logger = logging.getLogger("wanasah_logger")
router = APIRouter(tags=["Authentication"])

# +++ الكي الجراحي (A-02): هاش ثابت مسبق الحساب لمنع إرهاق الـ CPU وبطء السيرفر عند كل إعادة تشغيل +++
DUMMY_PASSWORD_HASH = "$2b$12$C.O1Tz2R8o7Vq78UoA61ueh3b7Qz7t0V1H1t.zU0TzO1Q0xO7Qz.O"

class RefreshRequest(BaseModel):
    refresh_token: str

def create_access_token(data: dict):
    """مفتاح الباب: استخدام Aware UTC لمنع كراش الـ Naive Datetime في PyJWT"""
    to_encode = data.copy()
    expire_timestamp = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire_timestamp, "type": "access"})
    return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")

def create_refresh_token(data: dict):
    """مفتاح الخزنة: استخدام Aware UTC لمنع كراش الـ Naive Datetime في PyJWT"""
    to_encode = data.copy()
    expire_timestamp = datetime.now(timezone.utc) + timedelta(days=30)
    to_encode.update({"exp": expire_timestamp, "type": "refresh"})
    return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")

async def check_brute_force(ip: str, db: AsyncSession):
    """درع الحماية مع معالجة الـ Deadlock المحتملة"""
    # +++ النسف المعماري لهجوم الـ DDoS والـ Permanent Ban +++
    # إيقاف الـ DELETE مع كل طلب لأنه يفجر الداتابيز بالـ Row Locks أثناء الهجوم
    limit_time = utc_now() - timedelta(minutes=15)

    # فحص عدد المحاولات الفاشلة في آخر 15 دقيقة فقط (بدون حذف)
    stmt_count = select(func.count()).select_from(SystemAuditLog).where(
        SystemAuditLog.action_type == 'FAILED_LOGIN',
        SystemAuditLog.target_id == ip,
        SystemAuditLog.timestamp >= limit_time # +++ الدرع الفولاذي: استخدام اسم العمود الصحيح لمنع كراش الـ 500 +++
    )
    failed_count = (await db.execute(stmt_count)).scalar() or 0
    
    if failed_count >= 5:
        raise HTTPException(status_code=429, detail="تم حظر عنوان IP مؤقتاً بسبب محاولات اختراق متكررة.")

async def log_failed_attempt(ip: str, db: AsyncSession):
    """توثيق الفشل (FAILED_LOGIN)"""
    try:
        # +++ النسف المعماري للاستعلام المهدر: لا داعي للبحث عن مشرف لتوثيق اختراق من مجهول +++
        audit = SystemAuditLog(
            admin_id=None, # السماح بـ NULL لأن المخترق ليس مشرفاً
            target_id=ip,
            action_type='FAILED_LOGIN',
            old_value='Brute Force Attempt',
            new_value='Failed'
        )
        db.add(audit)
        await db.commit()
    except Exception as e:
        await db.rollback()
        # +++ الكي الجراحي (A-06): منع ابتلاع الأخطاء وتسجيلها لفريق الـ Operations +++
        logger.error(f"Failed to log audit event (FAILED_LOGIN): {e}")

@router.post("/driver/login", response_model=LoginResponse)
async def driver_login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    # +++ الكي الجراحي (Local Import): نسف الاستيراد الدائري الذي يشل تشغيل السيرفر +++
    from main import get_real_ip
    ip = get_real_ip(request)
    await check_brute_force(ip, db)
    
    stmt = select(Driver).filter_by(username=payload.username, is_active=True)
    driver = (await db.execute(stmt)).scalar_one_or_none()

    # +++ النسف المعماري الشامل: منع (Timing Attack) وحماية (SQLAlchemy) من شلل الـ Threads +++
    hash_to_check = driver.password_hash if driver else DUMMY_PASSWORD_HASH
    pwd_bytes = payload.password.encode('utf-8')
    hash_bytes = hash_to_check.encode('utf-8')
    
    password_match = await asyncio.to_thread(bcrypt.checkpw, pwd_bytes, hash_bytes)

    if not driver or not password_match:
        await log_failed_attempt(ip, db)
        raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة")

    # +++ إصدار المفتاحين للمندوب +++
    access_token = create_access_token({"sub": str(driver.id), "is_admin": driver.is_admin, "username": driver.username})
    refresh_token = create_refresh_token({"sub": str(driver.id)})
    
    # حفظ مفتاح التجديد في قاعدة البيانات للمراقبة وإمكانية الإلغاء
    expire_date = utc_now() + timedelta(days=30)
    db.add(RefreshToken(token=refresh_token, driver_id=driver.id, expires_at=expire_date))
    await db.commit()

    return {
        "message": "Login Successful!",
        "token": access_token,
        "refresh_token": refresh_token,
        "driver_id": driver.id,
        "driver_name": driver.full_name,
        "is_admin": driver.is_admin
    }

@router.post("/login", response_model=LoginResponse)
async def admin_login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    # +++ الكي الجراحي (Local Import): حماية الـ Runtime من الـ Circular Dependency +++
    from main import get_real_ip
    ip = get_real_ip(request)
    await check_brute_force(ip, db)
    
    stmt = select(Driver).filter_by(username=payload.username, is_active=True)
    admin = (await db.execute(stmt)).scalar_one_or_none()

    # +++ الكي الجراحي (A-03): التحقق من أنه مشرف *قبل* فحص الباسوورد لمنع تسريب المعلومات واستهلاك الـ CPU +++
    is_valid_admin = admin is not None and admin.is_admin
    hash_to_check = admin.password_hash if is_valid_admin else DUMMY_PASSWORD_HASH
    
    pwd_bytes = payload.password.encode('utf-8')
    hash_bytes = hash_to_check.encode('utf-8')
    
    password_match = await asyncio.to_thread(bcrypt.checkpw, pwd_bytes, hash_bytes)

    if not is_valid_admin or not password_match:
        await log_failed_attempt(ip, db)
        # نوحد الرسالة دائماً بـ 401 لمنع التخمين للمخترق
        raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة، أو الحساب غير مصرح له")

    # +++ إصدار المفتاحين (Facebook Architecture) +++
    access_token = create_access_token({"sub": str(admin.id), "is_admin": admin.is_admin, "username": admin.username})
    refresh_token = create_refresh_token({"sub": str(admin.id)})
    
    # حفظ مفتاح التجديد في قاعدة البيانات للمراقبة وإمكانية الإلغاء
    expire_date = utc_now() + timedelta(days=30)
    db.add(RefreshToken(token=refresh_token, driver_id=admin.id, expires_at=expire_date))
    await db.commit()

    return {
        "message": "Admin Login Successful!",
        "token": access_token,
        "refresh_token": refresh_token,
        "driver_id": admin.id,
        "driver_name": admin.full_name,
        "is_admin": admin.is_admin
    }

# =========================================
# +++ مسار التجديد الصامت (Silent Refresh) +++
# =========================================
@router.post("/refresh", status_code=200)
async def refresh_access_token(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        decoded = jwt.decode(payload.refresh_token, Config.SECRET_KEY, algorithms=["HS256"], options={"require": ["exp"]})
        if decoded.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="نوع التوكن غير صالح.")
            
        sub_val = str(decoded.get("sub", ""))
        if not sub_val.isdigit():
            raise HTTPException(status_code=401, detail="توكن غير صالح.")
        driver_id = int(sub_val)
        
        # +++ الكي الجراحي: البحث عن التوكن بدون is_revoked لتجنب مشاكل فحص البوليان في قواعد البيانات +++
        stmt = select(RefreshToken).filter_by(token=payload.refresh_token)
        db_token = (await db.execute(stmt)).scalars().first()
        
        if not db_token:
            logger.error(f"Refresh token missing from DB: {payload.refresh_token[:20]}...")
            raise HTTPException(status_code=401, detail="تم إلغاء الجلسة من قبل الإدارة.")
            
        if db_token.is_revoked:
            raise HTTPException(status_code=401, detail="التوكن تم إيقافه.")
            
        driver = await db.get(Driver, driver_id)
        if not driver or not driver.is_active:
            raise HTTPException(status_code=403, detail="تم إيقاف حسابك من قبل الإدارة.")
            
        new_access = create_access_token({"sub": str(driver.id), "is_admin": driver.is_admin, "username": driver.username})
        return {"token": new_access}
        
    except jwt.ExpiredSignatureError:
        await db.execute(delete(RefreshToken).where(RefreshToken.token == payload.refresh_token))
        await db.commit()
        raise HTTPException(status_code=401, detail="انتهت صلاحية الجلسة بالكامل. يرجى تسجيل الدخول.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="توكن غير صالح.")
    
# =========================================
# +++ مسار الـ Logout (حرق المفاتيح) +++
# =========================================
@router.post("/logout", status_code=200)
async def logout(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    access_token = credentials.credentials
    # قراءة الـ Refresh Token من الهيدر (إن وجد)
    refresh_token = request.headers.get("X-Refresh-Token")
    
    try:
        # 1. حرق المفتاح القصير (Blacklist) - فحص وجوده أولاً لمنع 500 UniqueViolation عند التكرار
        stmt_check = select(TokenBlacklist.id).filter_by(token=access_token)
        already_blacklisted = (await db.execute(stmt_check)).first()
        
        if not already_blacklisted:
            db.add(TokenBlacklist(token=access_token))
        
        # 2. إعدام المفتاح الطويل في الداتابيز
        if refresh_token:
            await db.execute(delete(RefreshToken).where(RefreshToken.token == refresh_token))
            
        await db.commit()
        return {"message": "تم تسجيل الخروج وتدمير الجلسة بنجاح."}
    except Exception as e:
        await db.rollback()
        logger.error(f"Logout error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="حدث خطأ أثناء تسجيل الخروج.")