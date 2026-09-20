from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
import jwt
from config import Config
from database import get_db, tenant_context
from models import Driver, TokenBlacklist
from sqlalchemy.future import select
from sqlalchemy import text
from token_identity import access_token_identity

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
        driver_id_int, comp_id_int = access_token_identity(payload)
        tenant_context.set(comp_id_int)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Token payload is invalid")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token is invalid or expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token processing error")

    try:
        # المسار الطبيعي: لا تسحب قاعدة البيانات الاتصال قبل فك الـ JWT.
        # tenant_context صار مضبوطاً أعلاه؛ أول checkout سيزرع RLS تلقائياً
        # عبر database.on_checkout بدون رحلة SQL ثانية مكررة.
        #
        # إذا دخلنا من test/override أو dependency سحب الاتصال مسبقاً، نحافظ
        # على الأمان ونزرع tenant صراحةً على الاتصال الموجود.
        if db.in_transaction():
            await db.execute(
                text("SELECT set_config('app.current_tenant', :c, false)"),
                {"c": str(comp_id_int)},
            )
        else:
            await db.connection()

        # المسار الطبيعي للمصادقة = استعلام واحد فقط:
        # Driver + حالة blacklist معاً، بدون إسقاط أي فحص أمني.
        blacklisted_exists = (
            select(TokenBlacklist.id)
            .where(TokenBlacklist.token == token)
            .exists()
        )
        stmt_auth = (
            select(
                Driver,
                blacklisted_exists.label("is_blacklisted"),
            )
            .where(
                Driver.id == driver_id_int,
                Driver.company_id == comp_id_int,
            )
        )
        auth_row = (await db.execute(stmt_auth)).one_or_none()

        if auth_row is None:
            # نحافظ على أولوية خطأ blacklist القديمة حتى في الحالة النادرة
            # التي يكون فيها الحساب محذوفاً والتوكن محروقاً معاً.
            is_blacklisted = bool(
                await db.scalar(select(blacklisted_exists))
            )
            if is_blacklisted:
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "مرفوض أمنياً: تم تسجيل الخروج مسبقاً "
                        "(التوكن محروق)."
                    ),
                )
            driver = None
        else:
            driver, is_blacklisted = auth_row
            if bool(is_blacklisted):
                raise HTTPException(
                    status_code=401,
                    detail=(
                        "مرفوض أمنياً: تم تسجيل الخروج مسبقاً "
                        "(التوكن محروق)."
                    ),
                )
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
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ACCOUNT_DISABLED",
                "message": "Account is disabled.",
                "context": {},
            },
        )
        
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