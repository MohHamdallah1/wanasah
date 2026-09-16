import asyncio
import bcrypt
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from database import get_db
from models import Branch, Company, Driver, LoginAttempt, PlatformAdmin, utc_now
from config import Config
from domains.pricing.publishing import create_assignment, create_price_book
from domains.inventory_costing.service import provision_default_cost_policy
import jwt

router = APIRouter(prefix="/platform", tags=["Platform Sovereign Admin"])
platform_security = HTTPBearer()
PLATFORM_ACCESS_TOKEN_MINUTES = 15
PLATFORM_LOGIN_SCOPE = "__platform__"
DUMMY_PASSWORD_HASH = "$2b$12$C.O1Tz2R8o7Vq78UoA61ueh3b7Qz7t0V1H1t.zU0TzO1Q0xO7Qz.O"


async def get_current_platform_admin(
    credentials: HTTPAuthorizationCredentials = Depends(platform_security),
    db: AsyncSession = Depends(get_db),
) -> PlatformAdmin:
    try:
        payload = jwt.decode(
            credentials.credentials,
            Config.SECRET_KEY,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "type"]},
        )
        if payload.get("type") != "platform_access" or payload.get("is_platform_admin") is not True:
            raise ValueError("invalid platform token type")
        raw_admin_id = payload.get("sub")
        if isinstance(raw_admin_id, bool) or not isinstance(raw_admin_id, (str, int)):
            raise ValueError("invalid platform admin id")
        admin_id = int(raw_admin_id)
        if admin_id <= 0 or str(admin_id) != str(raw_admin_id):
            raise ValueError("invalid platform admin id")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="انتهت صلاحية جلسة مدير المنصة.")
    except (jwt.PyJWTError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="توكن مدير المنصة غير صالح.")

    admin = await db.scalar(
        select(PlatformAdmin).where(
            PlatformAdmin.id == admin_id,
            PlatformAdmin.is_active.is_(True),
        )
    )
    if admin is None:
        raise HTTPException(status_code=401, detail="حساب مدير المنصة غير متاح.")
    return admin

class PlatformLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("اسم المستخدم مطلوب.")
        return value

class CreateCompanyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    company_code: str = Field(min_length=1, max_length=50)
    admin_username: str = Field(min_length=1, max_length=80)
    admin_password: str = Field(min_length=8, max_length=72)
    admin_full_name: str = Field(min_length=1, max_length=120)
    currency_code: str = Field(default="JOD", min_length=1, max_length=10)
    subscription_status: Literal["active", "suspended", "expired", "trial"] = "active"

    @field_validator("name", "company_code", "admin_username", "admin_full_name", "currency_code")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("الحقل مطلوب.")
        return value

    @field_validator("admin_password")
    @classmethod
    def validate_admin_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("كلمة المرور تتجاوز الحد المدعوم للتشفير.")
        return value


async def _check_platform_login_limit(ip: str, db: AsyncSession) -> None:
    failed_since = utc_now() - timedelta(minutes=15)
    failed_count = await db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.ip_address == ip,
            LoginAttempt.company_code_attempted == PLATFORM_LOGIN_SCOPE,
            LoginAttempt.is_successful.is_(False),
            LoginAttempt.created_at >= failed_since,
        )
    )
    if (failed_count or 0) >= 5:
        raise HTTPException(
            status_code=429,
            detail="تم حظر عنوان IP مؤقتاً بسبب محاولات دخول متكررة.",
        )


def _record_platform_login(
    ip: str,
    username: str,
    succeeded: bool,
    db: AsyncSession,
) -> None:
    db.add(
        LoginAttempt(
            ip_address=ip,
            username_attempted=username,
            company_code_attempted=PLATFORM_LOGIN_SCOPE,
            is_successful=succeeded,
        )
    )

@router.post("/login", status_code=200)
async def platform_admin_login(
    request: Request,
    payload: PlatformLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a platform-owned account, independently from tenant sessions."""
    from main import get_real_ip

    ip = get_real_ip(request)
    await _check_platform_login_limit(ip, db)
    stmt = select(PlatformAdmin).filter_by(username=payload.username, is_active=True)
    admin = (await db.execute(stmt)).scalar_one_or_none()

    try:
        password_matches = await asyncio.to_thread(
            bcrypt.checkpw,
            payload.password.encode('utf-8'),
            (admin.password_hash if admin else DUMMY_PASSWORD_HASH).encode('utf-8'),
        )
    except ValueError:
        password_matches = False
    if not admin or not password_matches:
        _record_platform_login(ip, payload.username, False, db)
        await db.commit()
        raise HTTPException(status_code=401, detail="بيانات دخول مدير المنصة غير صحيحة.")

    _record_platform_login(ip, payload.username, True, db)
    await db.commit()

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=PLATFORM_ACCESS_TOKEN_MINUTES)
    token = jwt.encode({
        "sub": str(admin.id),
        "username": admin.username,
        "is_platform_admin": True,
        "role": "GodMode",
        "type": "platform_access",
        "jti": uuid.uuid4().hex,
        "exp": expires_at,
    }, Config.SECRET_KEY, algorithm="HS256")

    return {"token": token, "admin": admin.username, "role": "PlatformAdmin"}

@router.post("/companies", status_code=201)
async def create_new_tenant(
    payload: CreateCompanyRequest,
    db: AsyncSession = Depends(get_db),
    _platform_admin: PlatformAdmin = Depends(get_current_platform_admin),
):
    """إنشاء مستأجر (Tenant) جديد مع تهيئة الحساب الإداري والفرع الرئيسي تلقائياً"""
    # التحقق من عدم تكرار كود الشركة
    stmt_check = select(Company.id).filter_by(company_code=payload.company_code)
    if (await db.execute(stmt_check)).scalar():
        raise HTTPException(status_code=409, detail="رمز الشركة (company_code) مستخدم بالفعل.")

    try:
        # 1. إنشاء سجل الشركة
        company = Company(
            name=payload.name,
            company_code=payload.company_code,
            is_active=True,
            subscription_status=payload.subscription_status,
            currency_code=payload.currency_code
        )
        db.add(company)
        await db.flush()

        # Keep the tenant boundary active while inserting the new tenant's child rows.
        # The application role remains subject to RLS; it never receives a bypass.
        await db.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
            {"tenant_id": str(company.id)},
        )

        # 2. إنشاء الفرع الرئيسي
        branch = Branch(
            company_id=company.id,
            name="الفرع الرئيسي",
            branch_code="HQ"
        )
        db.add(branch)
        await db.flush()

        # 3. إنشاء حساب مدير الشركة (Tenant Owner)
        hashed_pw = await asyncio.to_thread(
            lambda: bcrypt.hashpw(
                payload.admin_password.encode('utf-8'),
                bcrypt.gensalt(),
            ).decode('utf-8')
        )
        admin_driver = Driver(
            company_id=company.id,
            username=payload.admin_username,
            password_hash=hashed_pw,
            full_name=payload.admin_full_name,
            is_admin=True,
            is_active=True
        )
        db.add(admin_driver)
        await db.flush()

        # Provision empty authorities only; no fake prices or fake costs.
        effective_from = datetime.now(timezone.utc)
        default_book = await create_price_book(
            db,
            company_id=company.id,
            actor_id=admin_driver.id,
            code="DEFAULT",
            name="Default selling prices",
            currency_code=company.currency_code,
        )
        await create_assignment(
            db,
            company_id=company.id,
            actor_id=admin_driver.id,
            price_book_id=default_book.id,
            scope_type="COMPANY_DEFAULT",
            scope_id=None,
            allow_offers=True,
            priority=0,
            effective_from=effective_from,
            effective_to=None,
        )
        await provision_default_cost_policy(
            db,
            company_id=company.id,
            actor_id=admin_driver.id,
        )

        await db.commit()
        return {
            "message": f"تم تأسيس شركة ({company.name}) وتهيئة بيئتها بنجاح.",
            "company_id": company.id,
            "company_code": company.company_code
        }
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="تعذر التأسيس بسبب بيانات مستخدمة مسبقاً.")
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="فشل تأسيس المستأجر.")

@router.get("/companies", status_code=200)
async def list_all_tenants(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
    _platform_admin: PlatformAdmin = Depends(get_current_platform_admin),
):
    """List companies through a bounded, searchable platform scope."""
    filters = []
    normalized_query = q.strip() if q else ""
    if normalized_query:
        pattern = f"%{normalized_query}%"
        filters.append(
            or_(
                Company.name.ilike(pattern),
                Company.company_code.ilike(pattern),
            )
        )

    total = await db.scalar(select(func.count()).select_from(Company).where(*filters)) or 0
    stmt = (
        select(
            Company.id,
            Company.name,
            Company.company_code,
            Company.subscription_status,
            Company.is_active,
            Company.created_at,
        )
        .where(*filters)
        .order_by(Company.created_at.desc(), Company.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    comps = (await db.execute(stmt)).all()
    return {
        "items": [
            {
                "id": c.id,
                "name": c.name,
                "code": c.company_code,
                "subscription": c.subscription_status,
                "is_active": c.is_active,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comps
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }
