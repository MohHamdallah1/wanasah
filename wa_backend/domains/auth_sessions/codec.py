"""Pure JWT codec for canonical company access and refresh tokens."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import jwt

from .claims import (
    Channel,
    CompanyTokenClaims,
    PrincipalType,
    TokenType,
    validate_channel_principal_pair,
)

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)
_ALGORITHM = "HS256"
_REQUIRED_CLAIMS = (
    "type",
    "sub",
    "company_id",
    "channel",
    "principal_type",
    "auth_revision",
    "jti",
    "exp",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _issue(
    *,
    token_type: TokenType,
    principal_id: int,
    company_id: int,
    channel: Channel,
    principal_type: PrincipalType,
    auth_revision: int,
    secret: str,
    ttl: timedelta,
    now: datetime | None = None,
) -> str:
    if not secret:
        raise ValueError("JWT secret is required")
    validate_channel_principal_pair(channel, principal_type)
    issued_at = now or _utc_now()
    if issued_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    expires_at = issued_at + ttl
    claims = CompanyTokenClaims(
        token_type=token_type,
        principal_id=principal_id,
        company_id=company_id,
        channel=channel,
        principal_type=principal_type,
        auth_revision=auth_revision,
        jti=uuid.uuid4().hex,
        exp=int(expires_at.timestamp()),
    )
    canonical = CompanyTokenClaims.from_payload(
        claims.to_payload(), expected_type=token_type
    )
    return jwt.encode(canonical.to_payload(), secret, algorithm=_ALGORITHM)


def issue_access_token(
    *,
    principal_id: int,
    company_id: int,
    channel: Channel,
    principal_type: PrincipalType,
    auth_revision: int,
    secret: str,
    now: datetime | None = None,
) -> str:
    return _issue(
        token_type="access",
        principal_id=principal_id,
        company_id=company_id,
        channel=channel,
        principal_type=principal_type,
        auth_revision=auth_revision,
        secret=secret,
        ttl=ACCESS_TTL,
        now=now,
    )


def issue_refresh_token(
    *,
    principal_id: int,
    company_id: int,
    channel: Channel,
    principal_type: PrincipalType,
    auth_revision: int,
    secret: str,
    now: datetime | None = None,
) -> str:
    return _issue(
        token_type="refresh",
        principal_id=principal_id,
        company_id=company_id,
        channel=channel,
        principal_type=principal_type,
        auth_revision=auth_revision,
        secret=secret,
        ttl=REFRESH_TTL,
        now=now,
    )


def decode_company_token(
    token: str,
    *,
    secret: str,
    expected_type: TokenType | None = None,
) -> CompanyTokenClaims:
    if not secret:
        raise ValueError("JWT secret is required")
    payload = jwt.decode(
        token,
        secret,
        algorithms=[_ALGORITHM],
        options={"require": list(_REQUIRED_CLAIMS)},
    )
    return CompanyTokenClaims.from_payload(payload, expected_type=expected_type)


__all__ = [
    "ACCESS_TTL",
    "REFRESH_TTL",
    "decode_company_token",
    "issue_access_token",
    "issue_refresh_token",
]
