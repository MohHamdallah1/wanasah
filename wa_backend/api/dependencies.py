from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
import jwt
from config import Config
from database import get_db
from models import Driver

security = HTTPBearer()

async def get_current_driver(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    """هذه الدالة تعادل بالضبط @token_required التي كانت في فلاسك"""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
        driver_id = payload.get("sub")
        if driver_id is None:
            raise HTTPException(status_code=401, detail="Invalid token structure")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token is invalid or expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token processing error")

    # الدرع الفولاذي: استعلام واحد فقط (O(1)) لمنع إرهاق قاعدة البيانات
    # +++ حماية הـ 500 Crash: التحقق من أن الـ driver_id هو رقم صالح لتجنب هجمات حقن النصوص +++
    try:
        driver_id_int = int(driver_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Token payload is invalid")
        
    driver = await db.get(Driver, driver_id_int)
    if not driver or not getattr(driver, 'is_active', True):
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: تم إيقاف حسابك أو طردك من النظام. التوكن ملغي.")
        
    return driver

# +++ الدرع الرقابي المركزي (SaaS Guard): بوابة الإدارة +++
async def get_current_admin(current_driver: Driver = Depends(get_current_driver)):
    """حارس البوابة: يمنع دخول أي شخص لا يملك صلاحيات (is_admin) لمسارات الإدارة"""
    if not current_driver.is_admin:
        raise HTTPException(status_code=403, detail="مرفوض أمنياً: هذه العملية تتطلب صلاحيات إدارة.")
    return current_driver