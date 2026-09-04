from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, func, text
from database import get_db, tenant_context
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
import bcrypt
import uuid

logger = logging.getLogger("wanasah_logger")
router = APIRouter(tags=["Authentication"])

# +++  (A-02): هاش ثابت مسبق الحساب لمنع إرهاق الـ CPU وبطء السيرفر عند كل إعادة تشغيل +++
DUMMY_PASSWORD_HASH = "$2b$12$C.O1Tz2R8o7Vq78UoA61ueh3b7Qz7t0V1H1t.zU0TzO1Q0xO7Qz.O"

class RefreshRequest(BaseModel):
    refresh_token: str

from models import Company, LoginAttempt
from context import tenant_context

def create_access_token(data: dict, company_id: int, role_name: str = "Driver"): 
    to_encode = data.copy()
    expire_timestamp = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({
        "exp": expire_timestamp, 
        "type": "access", 
        "jti": uuid.uuid4().hex,
        "company_id": company_id,
        "role": role_name  # +++ حقن الـ Role للـ RBAC +++
    })
    return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")

def create_refresh_token(data: dict, company_id: int):
    to_encode = data.copy()
    expire_timestamp = datetime.now(timezone.utc) + timedelta(days=30)
    to_encode.update({
        "exp": expire_timestamp, 
        "type": "refresh", 
        "jti": uuid.uuid4().hex,
        "company_id": company_id
    })
    return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")

async def check_brute_force(ip: str, db: AsyncSession):
    limit_time = utc_now() - timedelta(minutes=15)
    stmt_count = select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.ip_address == ip,
        LoginAttempt.is_successful == False,
        LoginAttempt.created_at >= limit_time 
    )
    failed_count = (await db.execute(stmt_count)).scalar() or 0
    if failed_count >= 5:
        raise HTTPException(status_code=429, detail="تم حظر عنوان IP مؤقتاً بسبب محاولات اختراق متكررة.")
    return failed_count

def queue_login_attempt(ip: str, payload: LoginRequest, success: bool, db: AsyncSession):
    """
    + الدرع المعماري: إضافة السجل للجلسة الحالية دون عمل commit مستقل 
    لمنع كسر الـ Transaction الخاص بـ SQLAlchemy ولتفادي خطأ (This connection is closed)
    """
    attempt = LoginAttempt(
        ip_address=ip,
        username_attempted=payload.username,
        company_code_attempted=payload.company_code,
        is_successful=success
    )
    db.add(attempt)

from models import Company # تأكد من وجود الاستيراد في أعلى الملف

@router.post("/driver/login", response_model=LoginResponse)
async def driver_login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    from main import get_real_ip
    ip = get_real_ip(request)
    failed_count = await check_brute_force(ip, db)
    
    stmt_comp = select(Company.id).filter_by(company_code=payload.company_code, is_active=True)
    comp_id = (await db.execute(stmt_comp)).scalar_one_or_none()
    
    if not comp_id:
        queue_login_attempt(ip, payload, False, db)
        await db.commit()
        raise HTTPException(status_code=401, detail="رمز الشركة غير صحيح أو الشركة غير مفعلة.")
        
    # +++ حقن السياق فوراً لفتح بوابات الـ RLS قبل استعلام المندوب +++
    tenant_context.set(comp_id)
    # +++ (QA) زرع الهوية على الاتصال الحي: الـ checkout وقع أثناء استعلام الشركة
    # (قبل معرفة الهوية) بسياق فارغ، والسياسات RESTRICTIVE ستحجب استعلام المندوب
    # التالي على نفس الاتصال ما لم تُزرع الهوية الآن صراحةً +++
    await db.execute(text("SELECT set_config('app.current_tenant', :v, false)"), {"v": str(comp_id)})
    
    stmt = select(Driver).filter_by(username=payload.username, company_id=comp_id, is_active=True)
    driver = (await db.execute(stmt)).scalar_one_or_none()

    hash_to_check = driver.password_hash if driver else DUMMY_PASSWORD_HASH
    pwd_bytes = payload.password.encode('utf-8')
    hash_bytes = hash_to_check.encode('utf-8')
    
    password_match = await asyncio.to_thread(bcrypt.checkpw, pwd_bytes, hash_bytes)

    if not driver or not password_match:
        queue_login_attempt(ip, payload, False, db)
        await db.commit()
        remaining = max(0, 4 - failed_count)
        fail_detail = f"البيانات غير صحيحة. تبقى لك {remaining} محاولات." if remaining > 0 else "البيانات غير صحيحة. هذه المحاولة الأخيرة."
        raise HTTPException(status_code=401, detail=fail_detail)

    queue_login_attempt(ip, payload, True, db)
    access_token = create_access_token({"sub": str(driver.id), "is_admin": driver.is_admin, "username": driver.username}, company_id=comp_id, role_name="Driver")
    refresh_token = create_refresh_token({"sub": str(driver.id)}, company_id=comp_id)
    
    db.add(RefreshToken(token=refresh_token, driver_id=driver.id, expires_at=utc_now() + timedelta(days=30)))
    await db.commit()

    return {
        "message": "Login Successful!",
        "token": access_token,
        "refresh_token": refresh_token,
        "driver_id": driver.id,
        "driver_name": driver.full_name,
        "is_admin": driver.is_admin,
        "company_id": comp_id, # +++ تسليم الهوية للموبايل +++
        "company_code": payload.company_code # +++ تسليم الرمز لاسم ملف الداتابيز +++
    }

@router.post("/login", response_model=LoginResponse)
async def admin_login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    from main import get_real_ip
    ip = get_real_ip(request)
    failed_count = await check_brute_force(ip, db)
    
    stmt_comp = select(Company.id).filter_by(company_code=payload.company_code, is_active=True)
    comp_id = (await db.execute(stmt_comp)).scalar_one_or_none()
    
    if not comp_id:
        queue_login_attempt(ip, payload, False, db)
        await db.commit()
        raise HTTPException(status_code=401, detail="رمز الشركة غير صحيح أو الشركة غير مفعلة.")
        
    tenant_context.set(comp_id)
    # +++ (QA) زرع الهوية على الاتصال الحي — نفس درع driver_login +++
    await db.execute(text("SELECT set_config('app.current_tenant', :v, false)"), {"v": str(comp_id)})

    stmt = select(Driver).filter_by(username=payload.username, company_id=comp_id, is_active=True)
    admin = (await db.execute(stmt)).scalar_one_or_none()

    is_valid_admin = admin is not None and admin.is_admin
    hash_to_check = admin.password_hash if is_valid_admin else DUMMY_PASSWORD_HASH
    
    pwd_bytes = payload.password.encode('utf-8')
    hash_bytes = hash_to_check.encode('utf-8')
    
    password_match = await asyncio.to_thread(bcrypt.checkpw, pwd_bytes, hash_bytes)

    if not is_valid_admin or not password_match:
        queue_login_attempt(ip, payload, False, db)
        await db.commit()
        raise HTTPException(status_code=401, detail="البيانات غير صحيحة، أو الحساب غير مصرح له")

    queue_login_attempt(ip, payload, True, db)
    access_token = create_access_token({"sub": str(admin.id), "is_admin": admin.is_admin, "username": admin.username}, company_id=comp_id, role_name="Admin")
    refresh_token = create_refresh_token({"sub": str(admin.id)}, company_id=comp_id)
    
    db.add(RefreshToken(token=refresh_token, driver_id=admin.id, expires_at=utc_now() + timedelta(days=30)))
    await db.commit()

    return {
        "message": "Admin Login Successful!",
        "token": access_token,
        "refresh_token": refresh_token,
        "driver_id": admin.id,
        "driver_name": admin.full_name,
        "is_admin": admin.is_admin,
        "company_id": comp_id, # +++ تسليم الهوية للداشبورد +++
        "company_code": payload.company_code
    }

@router.post("/refresh", status_code=200)
async def refresh_access_token(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        decoded = jwt.decode(payload.refresh_token, Config.SECRET_KEY, algorithms=["HS256"], options={"require": ["exp"]})
        if decoded.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="نوع التوكن غير صالح.")
            
        driver_id = int(decoded.get("sub", 0))
        company_id = decoded.get("company_id")
        
        if not driver_id or not company_id:
            raise HTTPException(status_code=401, detail="توكن غير صالح أو مفقود الهوية.")
            
        tenant_context.set(company_id)
        
        # +++ الحقن غير المتزامن (Native Async RLS): تأمين مسار التجديد قبل لمس الداتابيز +++
        await db.execute(text("SELECT set_config('app.current_tenant', :c, false)"), {"c": str(company_id)})
        
        stmt = select(RefreshToken).filter_by(token=payload.refresh_token).with_for_update()
        db_token = (await db.execute(stmt)).scalars().first()
        
        if not db_token or db_token.is_revoked:
            await db.rollback() # +++ الإغلاق الآمن للـ Row Lock لمنع تسريب الاتصالات +++
            raise HTTPException(status_code=401, detail="التوكن ملغي أو تم تسجيل الخروج.")
            
        driver = await db.get(Driver, driver_id)
        company = await db.get(Company, company_id) # +++ جلب الشركة للتحقق من حالتها +++
        
        if not driver or not getattr(driver, 'is_active', False) or driver.company_id != company_id or not company or not getattr(company, 'is_active', False):
            await db.rollback() # +++ الإغلاق الآمن للـ Row Lock لمنع تسريب الاتصالات +++
            raise HTTPException(status_code=403, detail="الحساب أو الشركة موقوفة. لا يمكن تجديد الجلسة.")
            
        db_token.is_revoked = True
        
        new_access = create_access_token({"sub": str(driver.id), "is_admin": driver.is_admin, "username": driver.username}, company_id=company_id, role_name="Driver" if not driver.is_admin else "Admin")
        new_refresh = create_refresh_token({"sub": str(driver.id)}, company_id=company_id)
        
        db.add(RefreshToken(token=new_refresh, driver_id=driver.id, expires_at=utc_now() + timedelta(days=30)))
        await db.commit()
        
        return {"token": new_access, "refresh_token": new_refresh}
        
    except jwt.ExpiredSignatureError:
        await db.execute(delete(RefreshToken).where(RefreshToken.token == payload.refresh_token))
        await db.commit()
        raise HTTPException(status_code=401, detail="انتهت صلاحية الجلسة.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="توكن غير صالح.")
    
# =========================================
# +++ مسار الـ Logout (حرق المفاتيح) +++
# =========================================
@router.post("/logout", status_code=200)
async def logout(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    access_token = credentials.credentials
    
    # +++ حماية السيرفر من هجوم الإغراق (DoS) والتحقق الهيكلي من التوكن قبل إجهاد الداتابيز +++
    if len(access_token) > 500:
        raise HTTPException(status_code=400, detail="توكن غير صالح.")
    try:
        jwt.decode(access_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="صيغة التوكن غير صالحة ولا يمكن إدراجه في القائمة السوداء.")
        
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