"""Bounded invalidation of legacy Driver-bound refresh sessions at identity cutover.

This module deliberately does not issue, decode, rotate, or migrate tokens. It
exists only for the approved one-time cutover rule: once legacy refresh issuance
has been disabled, revoke every legacy company refresh session so users perform
one clean login through the canonical principal/channel flow.

Transaction ownership remains with the caller.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import Driver, RefreshToken


class LegacyRefreshCutoverRejected(Exception):
    """Fail-closed cutover rejection without token/session detail."""


@dataclass(frozen=True)
class LegacyRefreshSessionCounts:
    company_id: int
    total_sessions: int
    active_sessions: int


@dataclass(frozen=True)
class LegacyRefreshInvalidationResult:
    company_id: int
    total_sessions: int
    newly_revoked: int
    remaining_active: int


def _require_company_id(company_id: int) -> int:
    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
        raise LegacyRefreshCutoverRejected
    return company_id


def _company_driver_ids(company_id: int):
    return select(Driver.id).where(Driver.company_id == company_id)


async def legacy_refresh_session_counts(
    db: AsyncSession,
    *,
    company_id: int,
) -> LegacyRefreshSessionCounts:
    """Count only legacy refresh rows belonging to Drivers of one company."""
    company_id = _require_company_id(company_id)
    driver_ids = _company_driver_ids(company_id)

    total = int(
        await db.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.driver_id.in_(driver_ids))
        )
        or 0
    )
    active = int(
        await db.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(
                RefreshToken.driver_id.in_(driver_ids),
                RefreshToken.is_revoked.is_(False),
            )
        )
        or 0
    )
    return LegacyRefreshSessionCounts(
        company_id=company_id,
        total_sessions=total,
        active_sessions=active,
    )


async def invalidate_legacy_refresh_sessions(
    db: AsyncSession,
    *,
    company_id: int,
) -> LegacyRefreshInvalidationResult:
    """Revoke every existing legacy refresh session for one company.

    PRECONDITION: legacy refresh issuance for the company has already been
    disabled at the deployment/cutover boundary. Existing matching rows are
    locked before update; a final verification fails closed if any active legacy
    row remains visible in the caller transaction.

    The caller owns commit/rollback so this can be composed atomically with the
    wider cutover operation.
    """
    company_id = _require_company_id(company_id)
    before = await legacy_refresh_session_counts(db, company_id=company_id)
    driver_ids = _company_driver_ids(company_id)

    # Lock currently visible matching sessions before mutation. This protects
    # existing rotation rows from concurrent updates while the cutover transaction
    # revokes them. New legacy issuance must already be disabled by the caller.
    await db.execute(
        select(RefreshToken.id)
        .where(RefreshToken.driver_id.in_(driver_ids))
        .with_for_update()
    )

    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.driver_id.in_(driver_ids),
            RefreshToken.is_revoked.is_(False),
        )
        .values(is_revoked=True)
    )

    after = await legacy_refresh_session_counts(db, company_id=company_id)
    if after.active_sessions != 0:
        raise LegacyRefreshCutoverRejected

    return LegacyRefreshInvalidationResult(
        company_id=company_id,
        total_sessions=before.total_sessions,
        newly_revoked=before.active_sessions - after.active_sessions,
        remaining_active=after.active_sessions,
    )


__all__ = [
    "LegacyRefreshCutoverRejected",
    "LegacyRefreshInvalidationResult",
    "LegacyRefreshSessionCounts",
    "invalidate_legacy_refresh_sessions",
    "legacy_refresh_session_counts",
]
