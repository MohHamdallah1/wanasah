import os
import bcrypt
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from database import get_db
from models import PlatformAdmin, Company, Branch, Driver
from config import Config
import jwt

router = APIRouter(prefix="/platform", tags=["Platform Sovereign Admin"])

class PlatformLoginRequest(BaseModel):
    username: str
    password: str

class CreateCompanyRequest(BaseModel):
    name: str
    company_code: str
    admin_username: str
    admin_password: str
    admin_full_name: str
    currency_code: str = "JOD"
    subscription_status: str = "active"

@router.post("/login", status_code=200)
async def platform_admin_login(payload: PlatformLoginRequest, db: AsyncSession = Depends(get_db)):
    """دخول آلهة المنصة (God Mode): حساب سيادي يتجاوز RLS لإدارة الشركات"""
    stmt = select(PlatformAdmin).filter_by(username=payload.username, is_active=True)
    admin = (await db.execute(stmt)).scalar_one_or_none()

    if not admin or not bcrypt.checkpw(payload.password.encode('utf-8'), admin.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="بيانات دخول مدير المنصة غير صحيحة.")

    token = jwt.encode({
        "sub": str(admin.id),
        "username": admin.username,
        "is_platform_admin": True,
        "role": "GodMode"
    }, Config.SECRET_KEY, algorithm="HS256")

    return {"token": token, "admin": admin.username, "role": "PlatformAdmin"}

@router.post("/companies", status_code=201)
async def create_new_tenant(payload: CreateCompanyRequest, db: AsyncSession = Depends(get_db)):
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

        # 2. إنشاء الفرع الرئيسي
        branch = Branch(
            company_id=company.id,
            name="الفرع الرئيسي",
            branch_code="HQ"
        )
        db.add(branch)
        await db.flush()

        # 3. إنشاء حساب مدير الشركة (Tenant Owner)
        hashed_pw = bcrypt.hashpw(payload.admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        admin_driver = Driver(
            company_id=company.id,
            username=payload.admin_username,
            password_hash=hashed_pw,
            full_name=payload.admin_full_name,
            is_admin=True,
            is_active=True
        )
        db.add(admin_driver)

        await db.commit()
        return {
            "message": f"تم تأسيس شركة ({company.name}) وتهيئة بيئتها بنجاح.",
            "company_id": company.id,
            "company_code": company.company_code
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"فشل تأسيس المستأجر: {e}")

@router.get("/companies", status_code=200)
async def list_all_tenants(db: AsyncSession = Depends(get_db)):
    """سرد الشركات وخطط الاشتراك وحالة التفعيل (Platform Scope)"""
    stmt = select(Company.id, Company.name, Company.company_code, Company.subscription_status, Company.is_active, Company.created_at)
    comps = (await db.execute(stmt)).all()
    return [
        {
            "id": c.id, "name": c.name, "code": c.company_code,
            "subscription": c.subscription_status, "is_active": c.is_active,
            "created_at": c.created_at.isoformat() if c.created_at else None
        } for c in comps
    ]