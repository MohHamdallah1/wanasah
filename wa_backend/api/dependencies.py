from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
import jwt
from config import Config
from database import get_db
from models import Driver, TokenBlacklist
from sqlalchemy.future import select

security = HTTPBearer()

async def get_current_driver(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    """هذه الدالة تعادل بالضبط @token_required التي كانت في فلاسك"""
    token = credentials.credentials
    try:
        # +++ الدرع الأمني: إجبار وجود تاريخ انتهاء للتوكن لمنع التوكن الأبدي +++
        payload = jwt.decode(
            token, 
            Config.SECRET_KEY, 
            algorithms=["HS256"], 
            options={"require": ["exp"]} 
        )
        driver_id = payload.get("sub")
        if driver_id is None:
            raise HTTPException(status_code=401, detail="Invalid token structure")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token is invalid or expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token processing error")

    # +++ A-01: التحقق من أن التوكن ليس محروقاً في القائمة السوداء +++
    stmt_blacklisted = select(TokenBlacklist).filter_by(token=token)
    is_blacklisted = (await db.execute(stmt_blacklisted)).scalars().first()
    if is_blacklisted:
        raise HTTPException(status_code=401, detail="مرفوض أمنياً: تم تسجيل الخروج مسبقاً (التوكن محروق).")

    # الدرع الفولاذي: استعلام واحد فقط (O(1)) لمنع إرهاق قاعدة البيانات
    # +++ حماية הـ 500 Crash: التحقق من أن الـ driver_id هو رقم صالح لتجنب هجمات حقن النصوص +++
    try:
        driver_id_int = int(driver_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Token payload is invalid")
        
    driver = await db.get(Driver, driver_id_int)
    
    # +++   فصل الحساب الممسوح (بسبب فورمات الداتابيز) عن الحساب الموقوف إدارياً +++
    if not driver:
        # 401 ستجعل الفرونت إند يمسح التوكن الميت بهدوء
        raise HTTPException(status_code=401, detail="الحساب غير موجود في قاعدة البيانات. يرجى تسجيل الدخول مجدداً.")
        
    if not getattr(driver, 'is_active', False):
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: تم إيقاف حسابك من قبل الإدارة. التوكن ملغي.")
        
    return driver

# +++ A-05: درع الملكية المركزية (IDOR Shield) لمنع تداخل صلاحيات المناديب +++
async def get_current_driver_owned(driver_id: int, current_driver: Driver = Depends(get_current_driver)):
    """حارس الملكية: يمنع أي مندوب من طلب أو تعديل بيانات مندوب آخر"""
    if current_driver.id != driver_id and not current_driver.is_admin:
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: لا تملك صلاحية الوصول لبيانات مندوب آخر.")
    return current_driver

# +++ الدرع الرقابي المركزي (SaaS Guard): بوابة الإدارة +++
async def get_current_admin(current_driver: Driver = Depends(get_current_driver)):
    """حارس البوابة: يمنع دخول أي شخص لا يملك صلاحيات (is_admin) لمسارات الإدارة"""
    if not current_driver.is_admin:
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: هذه العملية تتطلب صلاحيات إدارة.")
    return current_driver