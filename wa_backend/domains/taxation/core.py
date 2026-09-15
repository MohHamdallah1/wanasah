from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from domains.taxation.models import TaxJurisdiction, TaxRuleSetVersion
from models import Company, SystemSetting


TAX_MAKER_CHECKER_SETTING = "tax_maker_checker_enabled"
TAX_JURISDICTION_MAX_DEPTH = 64


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TaxError(
            "TAX_DATETIME_OFFSET_REQUIRED",
            f"{field_name} must include a UTC offset.",
            status_code=422,
            context={"field": field_name},
        )
    return value.astimezone(timezone.utc)


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


async def require_active_jurisdictions(
    db: AsyncSession,
    *,
    company_id: int,
    jurisdiction_ids: Iterable[int],
) -> set[int]:
    ids = sorted({int(value) for value in jurisdiction_ids if value is not None})
    if any(value <= 0 for value in ids):
        raise TaxError(
            "TAX_JURISDICTION_INVALID",
            "Tax jurisdiction IDs must be positive.",
            status_code=422,
        )
    if not ids:
        return set()

    found = {
        int(value)
        for value in (
            await db.scalars(
                select(TaxJurisdiction.id).where(
                    TaxJurisdiction.company_id == int(company_id),
                    TaxJurisdiction.id.in_(ids),
                    TaxJurisdiction.is_active.is_(True),
                )
            )
        ).all()
    }
    missing = sorted(set(ids) - found)
    if missing:
        raise TaxError(
            "TAX_JURISDICTION_NOT_FOUND",
            "One or more tax jurisdictions are missing, inactive, or outside this company.",
            status_code=404,
            context={"tax_jurisdiction_ids": missing},
        )
    return found


async def jurisdiction_chain(
    db: AsyncSession,
    *,
    company_id: int,
    jurisdiction_id: int,
) -> dict[int, int]:
    if int(company_id) <= 0 or int(jurisdiction_id) <= 0:
        raise TaxError(
            "TAX_JURISDICTION_INVALID",
            "Tax jurisdiction context must use positive identifiers.",
            status_code=422,
        )

    anchor = (
        select(
            TaxJurisdiction.id.label("id"),
            TaxJurisdiction.parent_jurisdiction_id.label("parent_id"),
            literal(0).label("distance"),
        )
        .where(
            TaxJurisdiction.company_id == int(company_id),
            TaxJurisdiction.id == int(jurisdiction_id),
        )
    )
    chain = anchor.cte(
        "tax_jurisdiction_chain",
        recursive=True,
    )
    parent = aliased(TaxJurisdiction)
    chain = chain.union_all(
        select(
            parent.id,
            parent.parent_jurisdiction_id,
            (chain.c.distance + 1).label("distance"),
        )
        .select_from(parent)
        .join(
            chain,
            parent.id == chain.c.parent_id,
        )
        .where(
            parent.company_id == int(company_id),
            chain.c.distance
            < TAX_JURISDICTION_MAX_DEPTH - 1,
        )
    )

    rows = (
        await db.execute(
            select(
                chain.c.id,
                chain.c.parent_id,
                chain.c.distance,
            ).order_by(chain.c.distance)
        )
    ).all()
    if not rows:
        raise TaxError(
            "TAX_JURISDICTION_NOT_FOUND",
            "Tax jurisdiction is not available inside this company.",
            status_code=404,
        )

    ids = [int(row.id) for row in rows]
    if len(ids) != len(set(ids)):
        raise TaxError(
            "TAX_JURISDICTION_CYCLE",
            "Tax jurisdiction hierarchy contains a cycle.",
            status_code=422,
        )

    last = rows[-1]
    if (
        int(last.distance)
        >= TAX_JURISDICTION_MAX_DEPTH - 1
        and last.parent_id is not None
    ):
        raise TaxError(
            "TAX_JURISDICTION_DEPTH_EXCEEDED",
            "Tax jurisdiction hierarchy exceeds the supported depth.",
            status_code=422,
            context={
                "max_depth": TAX_JURISDICTION_MAX_DEPTH,
            },
        )
    return {
        int(row.id): int(row.distance)
        for row in rows
    }


async def current_tax_revision_ceiling(
    db: AsyncSession,
    company_id: int,
    *,
    as_of: datetime | None = None,
) -> int:
    when = require_aware_datetime(as_of or utc_now(), "as_of")
    value = await db.scalar(
        select(func.max(TaxRuleSetVersion.revision)).where(
            TaxRuleSetVersion.company_id == int(company_id),
            TaxRuleSetVersion.status.in_(("PUBLISHED", "SUPERSEDED")),
            TaxRuleSetVersion.published_at.is_not(None),
            TaxRuleSetVersion.published_at <= when,
        )
    )
    return int(value or 0)
