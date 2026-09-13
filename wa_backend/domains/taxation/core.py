from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.taxation.models import TaxRuleSetVersion
from models import Company, SystemSetting


TAX_MAKER_CHECKER_SETTING = "tax_maker_checker_enabled"


class TaxError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}


async def lock_company(db: AsyncSession, company_id: int) -> None:
    locked = await db.scalar(
        select(Company.id).where(Company.id == company_id).with_for_update()
    )
    if locked is None:
        raise TaxError("TAX_TENANT_NOT_FOUND", "Company is not available.", status_code=404)


async def maker_checker_enabled(db: AsyncSession, company_id: int) -> bool:
    value = await db.scalar(
        select(SystemSetting.setting_value).where(
            SystemSetting.company_id == company_id,
            SystemSetting.setting_key == TAX_MAKER_CHECKER_SETTING,
        )
    )
    if value is None:
        return False
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    raise TaxError(
        "TAX_APPROVAL_POLICY_INVALID",
        "Tax approval policy has an invalid value.",
        context={"setting_key": TAX_MAKER_CHECKER_SETTING},
    )


async def next_tenant_revision(db: AsyncSession, company_id: int) -> int:
    await lock_company(db, company_id)
    current = await db.scalar(
        select(func.max(TaxRuleSetVersion.revision)).where(
            TaxRuleSetVersion.company_id == company_id
        )
    )
    return int(current or 0) + 1
