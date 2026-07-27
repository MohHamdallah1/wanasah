from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, func
from database import get_db
from models import Driver, SystemAuditLog, TokenBlacklist
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

def get_real_ip(request: Request):
    """حل مشكلة الـ Proxy/Nginx: جلب الـ IP الحقيقي للمستخدم"""
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.client.host

def create_access_token(data: dict):
    to_encode = data.copy()
    # +++ الكي الجراحي (A-07): سحب وقت الانتهاء من Config مع fallback آمن 24 ساعة +++
    expiry_seconds = getattr(Config, 'JWT_EXPIRY_SECONDS', 86400)
    expire = datetime.now(timezone.utc) + timedelta(seconds=expiry_seconds)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")

async def check_brute_force(ip: str, db: AsyncSession):
    """درع الحماية مع معالجة الـ Deadlock المحتملة"""
    # +++ النسف المعماري لهجوم الـ DDoS والـ Permanent Ban +++
    # إيقاف الـ DELETE مع كل طلب لأنه يفجر الداتابيز بالـ Row Locks أثناء الهجوم
    limit_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=15)

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

    token = create_access_token({"sub": str(driver.id), "is_admin": driver.is_admin, "username": driver.username})
    return {
        "message": "Login Successful!",
        "token": token,
        "driver_id": driver.id,
        "driver_name": driver.full_name,
        "is_admin": driver.is_admin
    }

@router.post("/login", response_model=LoginResponse)
async def admin_login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
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

    token = create_access_token({"sub": str(admin.id), "is_admin": admin.is_admin, "username": admin.username})
    return {
        "message": "Admin Login Successful!",
        "token": token,
        "driver_id": admin.id,
        "driver_name": admin.full_name,
        "is_admin": admin.is_admin
    }

# +++ A-01: مسار الـ Logout لحرق التوكن +++
@router.post("/logout", status_code=200)
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    token = credentials.credentials
    
    stmt = select(TokenBlacklist).filter_by(token=token)
    if (await db.execute(stmt)).scalars().first():
        return {"message": "تم تسجيل الخروج مسبقاً."}
        
    try:
        db.add(TokenBlacklist(token=token))
        await db.commit()
        return {"message": "تم تسجيل الخروج وحرق التوكن بنجاح."}
    except Exception as e:
        await db.rollback()
        logger.error(f"Logout Error: {e}")
        raise HTTPException(status_code=500, detail="حدث خطأ أثناء تسجيل الخروج.")