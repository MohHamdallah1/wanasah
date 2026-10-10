"""Exact access-token blacklist boundary for canonical company sessions.

This module owns only exact access-token revocation. Refresh-session revocation is
separate so logout orchestration can keep both concerns explicit and transactional.
"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
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

    Returns True only when this call inserted the blacklist row. PostgreSQL conflict
    handling makes repeated or concurrent logout idempotent. The caller owns the
    surrounding commit/rollback.
    """
    if claims.token_type != "access":
        raise AccessRevocationRejected
    if not isinstance(token, str) or not token or len(token) > 500:
        raise AccessRevocationRejected

    statement = (
        pg_insert(TokenBlacklist)
        .values(token=token)
        .on_conflict_do_nothing(index_elements=[TokenBlacklist.token])
        .returning(TokenBlacklist.id)
    )
    inserted_id = (await db.execute(statement)).scalar_one_or_none()
    return inserted_id is not None


__all__ = [
    "AccessRevocationRejected",
    "blacklist_authenticated_access_token",
]
