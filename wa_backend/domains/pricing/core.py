from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Company, PriceBookAssignment, PricePublication, SystemSetting


PRICING_MAKER_CHECKER_SETTING = "pricing_maker_checker_enabled"
MONEY_QUANT = Decimal("0.000001")
MONEY_MAX = Decimal("99999999999999.999999")


class PricingError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = str(code)
        self.message = str(message)
        self.status_code = int(status_code)
        self.context = dict(context or {})
        super().__init__(self.message)

    def as_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PricingError(
            "PRICING_DATETIME_OFFSET_REQUIRED",
            f"{field_name} يجب أن يحتوي UTC offset.",
            status_code=422,
            context={"field": field_name},
        )
    return value.astimezone(timezone.utc)


def money_20_6(value: Any, field_name: str = "amount") -> Decimal:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PricingError(
            "PRICE_AMOUNT_INVALID",
            f"{field_name} قيمة مالية غير صالحة.",
            status_code=422,
            context={"field": field_name},
        ) from exc
    if not dec.is_finite() or dec < 0:
        raise PricingError(
            "PRICE_AMOUNT_INVALID",
            f"{field_name} يجب أن يكون رقماً مالياً غير سالب.",
            status_code=422,
            context={"field": field_name},
        )
    try:
        quantized = dec.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise PricingError(
            "PRICE_AMOUNT_INVALID",
            f"{field_name} لا يمكن تمثيله بدقة NUMERIC(20,6).",
            status_code=422,
            context={"field": field_name},
        ) from exc
    if quantized > MONEY_MAX:
        raise PricingError(
            "PRICE_AMOUNT_INVALID",
            f"{field_name} يتجاوز سعة NUMERIC(20,6).",
            status_code=422,
            context={"field": field_name},
        )
    return quantized


async def acquire_pricing_company_lock(db: AsyncSession, company_id: int) -> None:
    """Single tenant lock root used by pricing writes and later Route Launch.

    Lock order for Stage 5 is: Company row -> pricing rows. Route Launch will
    acquire the same Company row first before reading revision ceilings.
    """
    row = await db.scalar(
        select(Company.id)
        .where(Company.id == int(company_id))
        .with_for_update()
    )
    if row is None:
        raise PricingError(
            "TENANT_NOT_FOUND",
            "الشركة غير موجودة.",
            status_code=404,
        )


async def maker_checker_enabled(db: AsyncSession, company_id: int) -> bool:
    raw = await db.scalar(
        select(SystemSetting.setting_value).where(
            SystemSetting.company_id == int(company_id),
            SystemSetting.setting_key == PRICING_MAKER_CHECKER_SETTING,
        )
    )
    if raw is None:
        return False
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise PricingError(
        "PRICING_APPROVAL_POLICY_INVALID",
        "إعداد Maker/Checker للتسعير يحمل قيمة غير صالحة.",
        context={"setting_key": PRICING_MAKER_CHECKER_SETTING},
    )


async def next_publication_revision(db: AsyncSession, company_id: int) -> int:
    current = await db.scalar(
        select(func.max(PricePublication.revision)).where(
            PricePublication.company_id == int(company_id)
        )
    )
    return int(current or 0) + 1


async def next_assignment_revision(db: AsyncSession, company_id: int) -> int:
    current = await db.scalar(
        select(func.max(PriceBookAssignment.revision)).where(
            PriceBookAssignment.company_id == int(company_id)
        )
    )
    return int(current or 0) + 1


async def current_publication_revision_ceiling(
    db: AsyncSession,
    company_id: int,
) -> int:
    value = await db.scalar(
        select(func.max(PricePublication.revision)).where(
            PricePublication.company_id == int(company_id),
            PricePublication.status.in_(("PUBLISHED", "SUPERSEDED")),
        )
    )
    return int(value or 0)


async def current_assignment_revision_ceiling(
    db: AsyncSession,
    company_id: int,
) -> int:
    value = await db.scalar(
        select(func.max(PriceBookAssignment.revision)).where(
            PriceBookAssignment.company_id == int(company_id)
        )
    )
    return int(value or 0)
