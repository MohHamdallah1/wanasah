"""Behavior-preserving company login-attempt policy.

This module owns only login-attempt counting, rate-limit policy, and attaching
attempt records to the caller-owned transaction. It deliberately has no
credential, identity-profile, JWT, refresh-session, capability, or HTTP
response responsibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LoginAttempt, utc_now

LOGIN_ATTEMPT_WINDOW = timedelta(minutes=15)
MAX_FAILED_ATTEMPTS = 5
PLATFORM_ATTEMPT_SENTINEL = "__platform__"


class LoginAttemptRateLimited(Exception):
    """Internal signal that an IP already reached the company-login limit."""


@dataclass(frozen=True)
class LoginAttemptState:
    failed_count: int

    @property
    def remaining_after_next_failure(self) -> int:
        """Match the legacy message count after one more failed login."""
        return max(0, (MAX_FAILED_ATTEMPTS - 1) - self.failed_count)


async def read_login_attempt_state(
    db: AsyncSession,
    *,
    ip_address: str,
    now: datetime | None = None,
) -> LoginAttemptState:
    """Read recent failed non-platform attempts for one source IP."""
    reference_time = now or utc_now()
    limit_time = reference_time - LOGIN_ATTEMPT_WINDOW
    failed_count = (
        await db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.company_code_attempted != PLATFORM_ATTEMPT_SENTINEL,
                LoginAttempt.is_successful.is_(False),
                LoginAttempt.created_at >= limit_time,
            )
        )
    ) or 0
    return LoginAttemptState(failed_count=int(failed_count))


async def enforce_company_login_attempt_limit(
    db: AsyncSession,
    *,
    ip_address: str,
    now: datetime | None = None,
) -> LoginAttemptState:
    """Preserve the existing five-failures-per-15-minutes IP threshold."""
    state = await read_login_attempt_state(db, ip_address=ip_address, now=now)
    if state.failed_count >= MAX_FAILED_ATTEMPTS:
        raise LoginAttemptRateLimited
    return state


def record_login_attempt(
    db: AsyncSession,
    *,
    ip_address: str,
    username: str,
    company_code: str,
    successful: bool,
) -> LoginAttempt:
    """Attach one attempt to the current transaction; never commit here."""
    attempt = LoginAttempt(
        ip_address=ip_address,
        username_attempted=username,
        company_code_attempted=company_code,
        is_successful=successful,
    )
    db.add(attempt)
    return attempt


__all__ = [
    "LOGIN_ATTEMPT_WINDOW",
    "MAX_FAILED_ATTEMPTS",
    "LoginAttemptRateLimited",
    "LoginAttemptState",
    "enforce_company_login_attempt_limit",
    "read_login_attempt_state",
    "record_login_attempt",
]
