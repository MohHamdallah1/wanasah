"""HTTP-only boundary from canonical access tokens to trusted request context."""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from context import tenant_context
from database import get_db
from domains.auth_sessions.claims import CompanyTokenClaims
from domains.auth_sessions.codec import decode_company_token
from domains.auth_sessions.context import (
    AuthenticatedRequestContext,
    DashboardRequestContext,
    FieldRequestContext,
    RequestContextRejected,
    resolve_access_context,
)
from models import TokenBlacklist

_security = HTTPBearer(auto_error=False)
_AUTH_REJECTION_DETAIL = "Authentication credentials are invalid or expired."


@dataclass(frozen=True)
class AuthenticatedAccessSession:
    """One request's exact token, decoded claims and persisted trusted identity."""

    token: str = field(repr=False)
    claims: CompanyTokenClaims
    context: AuthenticatedRequestContext


def _authentication_rejected() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_AUTH_REJECTION_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_access_token(token: str) -> CompanyTokenClaims:
    try:
        return decode_company_token(
            token,
            secret=Config.SECRET_KEY,
            expected_type="access",
        )
    except Exception:
        raise _authentication_rejected() from None


async def _establish_tenant_context(db: AsyncSession, *, company_id: int) -> None:
    """Set request tenant before any tenant-owned persistence lookup."""
    tenant_context.set(company_id)

    # Normal path: the first checkout sees tenant_context and database.on_checkout
    # seeds app.current_tenant. If this session already owns a connection/transaction,
    # mirror the existing dependency behavior and seed the live connection explicitly.
    if db.in_transaction():
        await db.execute(
            text("SELECT set_config('app.current_tenant', :c, false)"),
            {"c": str(company_id)},
        )
    else:
        await db.connection()


async def _reject_blacklisted_token(db: AsyncSession, *, token: str) -> None:
    blacklisted_exists = (
        select(TokenBlacklist.id)
        .where(TokenBlacklist.token == token)
        .exists()
    )
    if bool(await db.scalar(select(blacklisted_exists))):
        raise _authentication_rejected()


async def _resolve_authenticated_access_session(
    *,
    token: str,
    db: AsyncSession,
) -> AuthenticatedAccessSession:
    claims = _decode_access_token(token)

    try:
        await _establish_tenant_context(db, company_id=claims.company_id)
        await _reject_blacklisted_token(db, token=token)
        current = await resolve_access_context(db, claims)
        return AuthenticatedAccessSession(token=token, claims=claims, context=current)
    except HTTPException:
        raise
    except RequestContextRejected:
        raise _authentication_rejected() from None
    except Exception:
        # Persistence/RLS failures remain fail-closed and do not expose internals.
        raise _authentication_rejected() from None


async def _resolve_http_context(
    *, token: str, db: AsyncSession,
) -> AuthenticatedRequestContext:
    """Keep the existing internal context-only boundary backed by the carrier."""
    return (await _resolve_authenticated_access_session(token=token, db=db)).context


async def get_authenticated_access_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedAccessSession:
    """Authenticate once; FastAPI shares this carrier through its request cache."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_rejected()
    token = credentials.credentials
    if not token:
        raise _authentication_rejected()
    return await _resolve_authenticated_access_session(token=token, db=db)


async def get_current_principal_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    db: AsyncSession = Depends(get_db),
    *,
    session: AuthenticatedAccessSession = Depends(get_authenticated_access_session),
) -> AuthenticatedRequestContext:
    """Use FastAPI's cached carrier; keep direct credentials/db callers compatible."""
    if not isinstance(session, AuthenticatedAccessSession):
        session = await get_authenticated_access_session(credentials=credentials, db=db)
    return session.context


async def get_current_backoffice_context(
    current: AuthenticatedRequestContext = Depends(get_current_principal_context),
) -> DashboardRequestContext:
    """Require the already-trusted Dashboard/Backoffice request channel."""
    if not isinstance(current, DashboardRequestContext):
        raise _authentication_rejected()
    return current


async def get_current_field_context(
    current: AuthenticatedRequestContext = Depends(get_current_principal_context),
) -> FieldRequestContext:
    """Require the already-trusted FieldRepresentative request channel."""
    if not isinstance(current, FieldRequestContext):
        raise _authentication_rejected()
    return current


__all__ = [
    "AuthenticatedAccessSession",
    "get_authenticated_access_session",
    "get_current_backoffice_context",
    "get_current_field_context",
    "get_current_principal_context",
]
