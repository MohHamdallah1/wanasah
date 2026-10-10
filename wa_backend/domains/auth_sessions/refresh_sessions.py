"""Principal refresh lifecycle inside an explicit caller-owned transaction.

No HTTP orchestration or transaction completion belongs here. Tenant binding is
transaction-local and may never replace a different established tenant. Rejected
operations raise an opaque internal error; the caller decides rollback/response.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .claims import CompanyTokenClaims, TokenContractError
from .codec import REFRESH_TTL, decode_company_token, issue_refresh_token
from .context import AuthenticatedRequestContext, DashboardRequestContext, FieldRequestContext
from .models import PrincipalRefreshToken
from ..identity.channels import IdentityChannel, coerce_channel, expected_principal_type
from ..identity.repository import (
    IdentityRecordNotFound, load_principal_by_id, require_active_company,
    require_backoffice_profile, require_field_representative_profile,
)
from ..identity.types import PrincipalType

REFRESH_ROTATION_GRACE_SECONDS = 15


class RefreshSessionRejected(Exception):
    """Fail-closed internal rejection without token or check-specific details."""


class RefreshSessionTransactionRequired(RuntimeError):
    """The caller must begin and complete the transaction."""


@dataclass(frozen=True)
class RefreshSessionResult:
    principal_id: int
    company_id: int
    channel: IdentityChannel
    principal_type: PrincipalType
    auth_revision: int
    refresh_token: str = field(repr=False)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _transaction(db: AsyncSession) -> None:
    if not db.in_transaction():
        raise RefreshSessionTransactionRequired("Caller transaction required")


def _decode(token: str, secret: str) -> CompanyTokenClaims:
    try:
        return decode_company_token(token, secret=secret, expected_type="refresh")
    except (jwt.PyJWTError, TokenContractError, ValueError, TypeError):
        raise RefreshSessionRejected from None


async def _tenant(db: AsyncSession, company_id: int) -> None:
    current = await db.scalar(text("SELECT NULLIF(current_setting('app.current_tenant', true), '')"))
    if current is not None:
        try:
            if int(current) != company_id:
                raise RefreshSessionRejected
        except (TypeError, ValueError):
            raise RefreshSessionRejected from None
    await db.execute(text("SELECT set_config('app.current_tenant', :tenant, true)"), {"tenant": str(company_id)})


async def _persisted_identity(db: AsyncSession, identity) -> object:
    """Re-read identity attributes even when the caller's ORM identity map is warm."""
    channel = coerce_channel(identity.channel)
    kind = expected_principal_type(channel)
    if identity.principal_type != kind.value:
        raise RefreshSessionRejected
    try:
        company = await require_active_company(db, identity.company_id)
        await db.refresh(company)
        principal = await load_principal_by_id(db, company_id=identity.company_id, principal_id=identity.principal_id)
        if principal is None:
            raise RefreshSessionRejected
        await db.refresh(principal)
        if (company.id != identity.company_id or not company.is_active
                or principal.id != identity.principal_id or principal.company_id != identity.company_id
                or not principal.is_active or principal.principal_type != kind.value
                or principal.auth_revision != identity.auth_revision):
            raise RefreshSessionRejected
        lookup = require_backoffice_profile if channel is IdentityChannel.DASHBOARD else require_field_representative_profile
        profile = await lookup(db, company_id=identity.company_id, principal_id=identity.principal_id)
        await db.refresh(profile)
    except IdentityRecordNotFound:
        raise RefreshSessionRejected from None
    if (profile.company_id != identity.company_id or profile.principal_id != identity.principal_id
            or profile.principal_type != kind.value):
        raise RefreshSessionRejected
    return profile


def _match(row: PrincipalRefreshToken, claims: CompanyTokenClaims, now: datetime) -> None:
    if (row.company_id != claims.company_id or row.principal_id != claims.principal_id
            or row.channel != claims.channel or row.auth_revision != claims.auth_revision
            or claims.exp <= int(now.timestamp()) or _naive_utc(row.expires_at) <= _naive_utc(now)):
        raise RefreshSessionRejected


async def _exact(db: AsyncSession, token: str, claims: CompanyTokenClaims) -> PrincipalRefreshToken:
    row = await db.scalar(select(PrincipalRefreshToken).where(
        PrincipalRefreshToken.company_id == claims.company_id,
        PrincipalRefreshToken.token == token,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise RefreshSessionRejected
    _match(row, claims, _utc_now())
    return row


def _result(identity, token: str) -> RefreshSessionResult:
    return RefreshSessionResult(
        principal_id=identity.principal_id, company_id=identity.company_id,
        channel=coerce_channel(identity.channel), principal_type=expected_principal_type(identity.channel),
        auth_revision=identity.auth_revision, refresh_token=token,
    )


async def _insert(db: AsyncSession, identity, secret: str) -> PrincipalRefreshToken:
    now = _utc_now()
    token = issue_refresh_token(
        principal_id=identity.principal_id, company_id=identity.company_id,
        channel=coerce_channel(identity.channel).value, principal_type=expected_principal_type(identity.channel).value,
        auth_revision=identity.auth_revision, secret=secret, now=now,
    )
    # Match the codec's integer UTC exp exactly; persistence uses project's naive UTC.
    expires = datetime.fromtimestamp(int((now + REFRESH_TTL).timestamp()), timezone.utc)
    row = PrincipalRefreshToken(
        company_id=identity.company_id, principal_id=identity.principal_id,
        channel=coerce_channel(identity.channel).value, token=token,
        expires_at=_naive_utc(expires), is_revoked=False,
        auth_revision=identity.auth_revision, created_at=_naive_utc(now),
    )
    db.add(row)
    await db.flush()
    return row


async def create_refresh_session(
    db: AsyncSession, context: AuthenticatedRequestContext, *, secret: str,
) -> RefreshSessionResult:
    """Persist a session for an already authenticated, still-valid canonical context."""
    _transaction(db)
    if not isinstance(context, (DashboardRequestContext, FieldRequestContext)):
        raise RefreshSessionRejected
    if any(type(value) is not int or value <= 0 for value in (context.company_id, context.principal_id, context.auth_revision)):
        raise RefreshSessionRejected
    profile_id = context.backoffice_user_id if isinstance(context, DashboardRequestContext) else context.representative_id
    if type(profile_id) is not int or profile_id <= 0:
        raise RefreshSessionRejected
    await _tenant(db, context.company_id)
    profile = await _persisted_identity(db, context)
    if profile.id != profile_id:
        raise RefreshSessionRejected
    row = await _insert(db, context, secret)
    return _result(context, row.token)


async def _grace_successor(db: AsyncSession, predecessor, claims, *, secret: str) -> PrincipalRefreshToken:
    if predecessor.replaced_by_id is None:
        raise RefreshSessionRejected
    successor = await db.scalar(select(PrincipalRefreshToken).where(
        PrincipalRefreshToken.company_id == claims.company_id,
        PrincipalRefreshToken.id == predecessor.replaced_by_id,
    ).with_for_update().execution_options(populate_existing=True))
    now = _utc_now()  # Take time after lock waits, so grace never grows with contention.
    _match(predecessor, claims, now)
    if successor is None or successor.is_revoked:
        raise RefreshSessionRejected
    _match(successor, claims, now)
    created = _naive_utc(successor.created_at)
    if created > _naive_utc(now) or created < _naive_utc(now) - timedelta(seconds=REFRESH_ROTATION_GRACE_SECONDS):
        raise RefreshSessionRejected
    successor_claims = _decode(successor.token, secret)
    if any(getattr(successor_claims, name) != getattr(claims, name) for name in
           ("principal_id", "company_id", "channel", "principal_type", "auth_revision")):
        raise RefreshSessionRejected
    _match(successor, successor_claims, now)
    return successor


async def rotate_refresh_session(db: AsyncSession, refresh_token: str, *, secret: str) -> RefreshSessionResult:
    """Rotate once, or replay the valid successor within the inclusive 15s grace."""
    _transaction(db)
    claims = _decode(refresh_token, secret)
    await _tenant(db, claims.company_id)
    predecessor = await _exact(db, refresh_token, claims)
    await _persisted_identity(db, claims)
    if predecessor.is_revoked:
        successor = await _grace_successor(db, predecessor, claims, secret=secret)
    else:
        # A linked but unrevoked predecessor is inconsistent; never mint another successor.
        if predecessor.replaced_by_id is not None:
            raise RefreshSessionRejected
        _match(predecessor, claims, _utc_now())
        successor = await _insert(db, claims, secret)
        predecessor.is_revoked = True
        predecessor.replaced_by_id = successor.id
        await db.flush()
    return _result(claims, successor.token)


async def revoke_refresh_session(db: AsyncSession, refresh_token: str, *, secret: str) -> None:
    """Idempotently revoke exactly this row; clearing its link disables grace replay.

    Does not revoke other sessions or its successor. Account-wide invalidation
    and access blacklist orchestration remain outside this exact-session helper.
    """
    _transaction(db)
    claims = _decode(refresh_token, secret)
    await _tenant(db, claims.company_id)
    row = await _exact(db, refresh_token, claims)
    await _persisted_identity(db, claims)
    row.is_revoked = True
    row.replaced_by_id = None
    await db.flush()


__all__ = ["RefreshSessionRejected", "RefreshSessionTransactionRequired", "RefreshSessionResult",
           "create_refresh_session", "rotate_refresh_session", "revoke_refresh_session"]
