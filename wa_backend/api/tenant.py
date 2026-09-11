"""Authenticated tenant identity contract for shared Dashboard chrome."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from models import Company, Country, Driver, SystemSetting


router = APIRouter(prefix="/tenant", tags=["Tenant Identity"])

COUNTRY_SETTING_KEY = "company_country_id"
LOCATION_LABEL_SETTING_KEY = "company_location_label"


class TenantIdentityResponse(BaseModel):
    company_id: int = Field(gt=0)
    company_name: str = Field(min_length=1, max_length=150)
    company_code: str = Field(min_length=1, max_length=50)
    currency_code: str = Field(min_length=1, max_length=10)
    timezone: str = Field(min_length=1, max_length=50)
    country_id: Optional[int] = Field(default=None, gt=0)
    country_name: Optional[str] = Field(default=None, max_length=100)
    display_location: str = Field(min_length=1, max_length=100)


def _positive_setting_id(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    clean = raw.strip()
    if not clean.isdigit():
        return None
    value = int(clean)
    return value if 0 < value <= 2_147_483_647 else None


@router.get("/identity", response_model=TenantIdentityResponse, status_code=200)
async def tenant_identity(
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver),
):
    company_id = int(current_driver.company_id)
    company = (
        await db.execute(
            select(
                Company.id,
                Company.name,
                Company.company_code,
                Company.currency_code,
                Company.timezone,
            ).where(Company.id == company_id)
        )
    ).one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="هوية الشركة غير متاحة.")

    setting_rows = (
        await db.execute(
            select(SystemSetting.setting_key, SystemSetting.setting_value).where(
                SystemSetting.company_id == company_id,
                SystemSetting.setting_key.in_(
                    [COUNTRY_SETTING_KEY, LOCATION_LABEL_SETTING_KEY]
                ),
            )
        )
    ).all()
    settings = {str(key): str(value) for key, value in setting_rows}

    country_id = _positive_setting_id(settings.get(COUNTRY_SETTING_KEY))
    country_name = None
    if country_id is not None:
        country_name = await db.scalar(
            select(Country.name).where(Country.id == country_id)
        )
        if country_name is None:
            country_id = None

    explicit_location = settings.get(LOCATION_LABEL_SETTING_KEY, "").strip()
    display_location = (
        explicit_location
        or (str(country_name).strip() if country_name else "")
        or str(company.timezone).strip()
    )

    return {
        "company_id": int(company.id),
        "company_name": str(company.name),
        "company_code": str(company.company_code),
        "currency_code": str(company.currency_code),
        "timezone": str(company.timezone),
        "country_id": country_id,
        "country_name": str(country_name) if country_name is not None else None,
        "display_location": display_location,
    }
