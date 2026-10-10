"""Thin HTTP boundary for canonical principal refresh rotation.

The refresh-session domain owns validation and rotation semantics. This module
owns only the caller transaction, canonical access-token issuance from the
returned persisted identity, and the generic HTTP rejection contract.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.codec import issue_access_token
from domains.auth_sessions.refresh_sessions import (
    RefreshSessionRejected,
    rotate_refresh_session,
)

from .schemas import PrincipalTokenPairResponse


_AUTH_REJECTED = "Authentication failed."


async def refresh_principal_session(
    db: AsyncSession,
    *,
    refresh_token: str,
    secret: str,
) -> PrincipalTokenPairResponse:
    """Rotate one canonical refresh session and return a matching access pair.

    The HTTP boundary is the caller that owns transaction completion required by
    ``rotate_refresh_session``. Access issuance stays inside that transaction so
    an issuance failure cannot leave a committed successor without its response.
    """
    try:
        async with db.begin():
            rotated = await rotate_refresh_session(
                db,
                refresh_token,
                secret=secret,
            )
            access_token = issue_access_token(
                principal_id=rotated.principal_id,
                company_id=rotated.company_id,
                channel=rotated.channel.value,
                principal_type=rotated.principal_type.value,
                auth_revision=rotated.auth_revision,
                secret=secret,
            )
            response = PrincipalTokenPairResponse(
                token=access_token,
                refresh_token=rotated.refresh_token,
            )
    except RefreshSessionRejected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_AUTH_REJECTED,
        ) from None

    return response


__all__ = ["refresh_principal_session"]
