"""Exact access-token blacklist boundary for canonical company sessions.

This module owns only exact access-token revocation. Refresh-session revocation is
separate so logout orchestration can keep both concerns explicit and transactional.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import TokenBlacklist
from .claims import CompanyTokenClaims


class AccessRevocationRejected(Exception):
    """Fail-closed access revocation rejection without token disclosure."""


async def blacklist_authenticated_access_token(
    db: AsyncSession,
    *,
    token: str,
    claims: CompanyTokenClaims,
) -> bool:
    """Queue exact canonical access-token revocation in the caller transaction.

    Returns True only when a new blacklist row is queued; repeated logout for the
    same token is idempotent and returns False. The caller owns commit/rollback.
    """
    if claims.token_type != "access":
        raise AccessRevocationRejected
    if not isinstance(token, str) or not token or len(token) > 500:
        raise AccessRevocationRejected

    existing = await db.scalar(
        select(TokenBlacklist.id).where(TokenBlacklist.token == token)
    )
    if existing is not None:
        return False

    db.add(TokenBlacklist(token=token))
    return True


__all__ = [
    "AccessRevocationRejected",
    "blacklist_authenticated_access_token",
]
