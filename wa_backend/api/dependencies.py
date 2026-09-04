from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
import jwt
from config import Config
from database import get_db, tenant_context
from models import Driver, TokenBlacklist
from sqlalchemy.future import select
from sqlalchemy import text

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
        company_id = payload.get("company_id") # +++ استخراج الهوية +++
        
        if driver_id is None or company_id is None:
            raise HTTPException(status_code=401, detail="Invalid token structure")
            
        # +++ زرع هوية الشركة في السياق (Context) لفتح بوابة الـ RLS قبل أي استعلام +++
        tenant_context.set(int(company_id))
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token is invalid or expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token processing error")

    try:
        # +++ A-01: التحقق من أن التوكن ليس محروقاً في القائمة السوداء +++
        stmt_blacklisted = select(TokenBlacklist).filter_by(token=token)
        is_blacklisted = (await db.execute(stmt_blacklisted)).scalars().first()
        if is_blacklisted:
            raise HTTPException(status_code=401, detail="مرفوض أمنياً: تم تسجيل الخروج مسبقاً (التوكن محروق).")

        # الدرع الفولاذي: استعلام واحد فقط (O(1)) لمنع إرهاق قاعدة البيانات
        try:
            driver_id_int = int(driver_id)
            comp_id_int = int(company_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=401, detail="Token payload is invalid")
            
        # +++ زرع هوية المستأجر مباشرة على الاتصال الحي المسحوب من الـ Pool قبل أي استعلام +++
        await db.execute(text("SELECT set_config('app.current_tenant', :c, false)"), {"c": str(comp_id_int)})

        # +++ التحقق الصارم من أن المندوب ينتمي للشركة الموجودة في التوكن +++
        stmt_driver = select(Driver).filter_by(id=driver_id_int, company_id=comp_id_int)
        driver = (await db.execute(stmt_driver)).scalar_one_or_none()
    except HTTPException:
        raise
    except Exception as e:
        # +++ الدرع المعماري: اصطياد خطأ (This connection is closed) وتحويله لرفض أمني دون كسر السيرفر +++
        import logging
        logging.getLogger("wanasah_logger").error(f"DB Dependency Connection Error: {e}")
        raise HTTPException(status_code=401, detail="انقطع الاتصال بقاعدة البيانات. يرجى إعادة المحاولة.")
    
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