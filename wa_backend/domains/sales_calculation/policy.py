from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.pricing.core import acquire_pricing_company_lock
from domains.sales_calculation.contracts import RoundingPolicy
from domains.sales_calculation.rounding import validate_rounding_policy
from models import Company, TenantOperationalPolicy


COMMERCIAL_ROUNDING_POLICY_CODE = "COMMERCIAL_ROUNDING"
COMMERCIAL_ROUNDING_SCHEMA_VERSION = 1


class CommercialPolicyError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        context: dict[str, Any] | None = None,
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


@dataclass(frozen=True)
class ResolvedCommercialRoundingPolicy:
    policy_id: int
    policy_revision: int
    effective_from: datetime
    rounding_policy: RoundingPolicy


def _aware(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CommercialPolicyError(
            "COMMERCIAL_POLICY_DATETIME_REQUIRED",
            "Commercial policy resolution time must include a UTC offset.",
            status_code=422,
        )
    return value.astimezone(timezone.utc)


def _db_time(value: datetime) -> datetime:
    return _aware(value).replace(tzinfo=None)


async def _company_currency(
    db: AsyncSession,
    *,
    company_id: int,
) -> str:
    value = await db.scalar(
        select(Company.currency_code).where(Company.id == int(company_id))
    )
    if value is None:
        raise CommercialPolicyError(
            "COMMERCIAL_POLICY_TENANT_NOT_FOUND",
            "Company is not available.",
            status_code=404,
        )
    currency = str(value).strip().upper()
    if not currency:
        raise CommercialPolicyError(
            "COMMERCIAL_POLICY_CURRENCY_INVALID",
            "Company currency is not configured.",
        )
    return currency


def _resolved_row(
    row: TenantOperationalPolicy,
    *,
    expected_currency_code: str,
) -> ResolvedCommercialRoundingPolicy:
    if int(row.schema_version) != COMMERCIAL_ROUNDING_SCHEMA_VERSION:
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_SCHEMA_UNSUPPORTED",
            "Published commercial rounding policy uses an unsupported schema version.",
            context={
                "policy_id": int(row.id),
                "schema_version": int(row.schema_version),
            },
        )

    payload = dict(row.validated_payload or {})
    if set(payload) != {"currency_code", "precision", "mode"}:
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_PAYLOAD_INVALID",
            "Published commercial rounding policy has an invalid payload shape.",
            context={"policy_id": int(row.id)},
        )

    precision = payload.get("precision")
    if (
        not isinstance(precision, int)
        or isinstance(precision, bool)
        or precision < 0
        or precision > 6
    ):
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_PAYLOAD_INVALID",
            "Commercial rounding precision must be an integer between 0 and 6.",
            context={"policy_id": int(row.id)},
        )

    mode = str(payload.get("mode") or "").strip().upper()
    currency = str(payload.get("currency_code") or "").strip().upper()
    expected_currency = str(expected_currency_code or "").strip().upper()
    if currency != expected_currency:
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_CURRENCY_MISMATCH",
            "Commercial rounding currency does not match company transaction currency.",
            context={
                "policy_id": int(row.id),
                "policy_currency_code": currency,
                "transaction_currency_code": expected_currency,
            },
        )

    try:
        policy = validate_rounding_policy(
            RoundingPolicy(
                version=COMMERCIAL_ROUNDING_SCHEMA_VERSION,
                currency_code=currency,
                precision=precision,
                mode=mode,
            )
        )
    except Exception as exc:
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_PAYLOAD_INVALID",
            "Published commercial rounding policy is invalid.",
            context={"policy_id": int(row.id)},
        ) from exc

    effective_from = row.effective_from
    if effective_from is None:
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_PAYLOAD_INVALID",
            "Published commercial rounding policy has no effective_from timestamp.",
            context={"policy_id": int(row.id)},
        )
    if effective_from.tzinfo is None:
        effective_from = effective_from.replace(tzinfo=timezone.utc)
    else:
        effective_from = effective_from.astimezone(timezone.utc)

    return ResolvedCommercialRoundingPolicy(
        policy_id=int(row.id),
        policy_revision=int(row.revision),
        effective_from=effective_from,
        rounding_policy=policy,
    )


async def resolve_commercial_rounding_policy(
    db: AsyncSession,
    *,
    company_id: int,
    as_of: datetime,
    expected_currency_code: str | None = None,
) -> ResolvedCommercialRoundingPolicy:
    if int(company_id) <= 0:
        raise CommercialPolicyError(
            "COMMERCIAL_POLICY_TENANT_INVALID",
            "company_id must be positive.",
            status_code=422,
        )

    when = _aware(as_of)
    database_when = _db_time(when)
    currency = (
        str(expected_currency_code).strip().upper()
        if expected_currency_code is not None
        else await _company_currency(db, company_id=company_id)
    )
    if not currency:
        raise CommercialPolicyError(
            "COMMERCIAL_POLICY_CURRENCY_INVALID",
            "Expected transaction currency is required.",
            status_code=422,
        )

    rows = list(
        (
            await db.scalars(
                select(TenantOperationalPolicy)
                .where(
                    TenantOperationalPolicy.company_id == int(company_id),
                    TenantOperationalPolicy.policy_code
                    == COMMERCIAL_ROUNDING_POLICY_CODE,
                    TenantOperationalPolicy.status.in_(
                        ("PUBLISHED", "SUPERSEDED")
                    ),
                    TenantOperationalPolicy.effective_from.is_not(None),
                    TenantOperationalPolicy.effective_from <= database_when,
                    or_(
                        TenantOperationalPolicy.effective_to.is_(None),
                        TenantOperationalPolicy.effective_to > database_when,
                    ),
                )
                .order_by(TenantOperationalPolicy.revision.desc())
                .limit(2)
            )
        ).all()
    )
    if not rows:
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_NOT_CONFIGURED",
            "Commercial rounding policy must be published before route launch.",
            context={"policy_code": COMMERCIAL_ROUNDING_POLICY_CODE},
        )
    if len(rows) != 1:
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_CONFLICT",
            "More than one commercial rounding policy is effective at the same time.",
            context={
                "policy_ids": [int(row.id) for row in rows],
                "as_of": when.isoformat(),
            },
        )

    return _resolved_row(rows[0], expected_currency_code=currency)


async def publish_commercial_rounding_policy(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    expected_revision: int,
    precision: int,
    mode: str,
) -> ResolvedCommercialRoundingPolicy:
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision < 0
    ):
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_REVISION_INVALID",
            "expected_revision must be a non-negative integer.",
            status_code=422,
        )

    await acquire_pricing_company_lock(db, int(company_id))
    currency = await _company_currency(db, company_id=company_id)

    normalized_mode = str(mode or "").strip().upper()
    try:
        candidate = validate_rounding_policy(
            RoundingPolicy(
                version=COMMERCIAL_ROUNDING_SCHEMA_VERSION,
                currency_code=currency,
                precision=precision,
                mode=normalized_mode,
            )
        )
    except Exception as exc:
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_PAYLOAD_INVALID",
            "Commercial rounding policy values are invalid.",
            status_code=422,
        ) from exc

    current = await db.scalar(
        select(TenantOperationalPolicy)
        .where(
            TenantOperationalPolicy.company_id == int(company_id),
            TenantOperationalPolicy.policy_code
            == COMMERCIAL_ROUNDING_POLICY_CODE,
            TenantOperationalPolicy.status == "PUBLISHED",
        )
        .with_for_update()
    )
    current_revision = int(current.revision) if current is not None else 0
    if current_revision != int(expected_revision):
        raise CommercialPolicyError(
            "COMMERCIAL_ROUNDING_VERSION_CONFLICT",
            "Commercial rounding policy changed; refresh before publishing.",
            context={
                "expected_revision": int(expected_revision),
                "current_revision": current_revision,
            },
        )

    maximum_revision = await db.scalar(
        select(func.max(TenantOperationalPolicy.revision)).where(
            TenantOperationalPolicy.company_id == int(company_id),
            TenantOperationalPolicy.policy_code
            == COMMERCIAL_ROUNDING_POLICY_CODE,
        )
    )
    next_revision = int(maximum_revision or 0) + 1
    now_aware = datetime.now(timezone.utc)
    now_db = now_aware.replace(tzinfo=None)

    if current is not None:
        current.status = "SUPERSEDED"
        current.effective_to = now_db
        # Clear the one-PUBLISHED partial unique slot before inserting the
        # replacement revision in the same transaction.
        await db.flush()

    row = TenantOperationalPolicy(
        company_id=int(company_id),
        policy_code=COMMERCIAL_ROUNDING_POLICY_CODE,
        schema_version=COMMERCIAL_ROUNDING_SCHEMA_VERSION,
        revision=next_revision,
        validated_payload={
            "currency_code": candidate.currency_code,
            "precision": candidate.precision,
            "mode": candidate.mode,
        },
        status="PUBLISHED",
        effective_from=now_db,
        effective_to=None,
        approved_by=int(actor_id),
        approved_at=now_db,
        created_by=int(actor_id),
    )
    db.add(row)
    await db.flush()

    return _resolved_row(row, expected_currency_code=currency)
