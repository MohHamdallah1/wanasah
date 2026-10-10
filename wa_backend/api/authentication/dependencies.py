"""HTTP-only boundary from canonical access tokens to trusted request context."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from context import tenant_context
from database import get_db
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


def _authentication_rejected() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_AUTH_REJECTION_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_access_token(token: str):
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


async def _resolve_http_context(
    *,
    token: str,
    db: AsyncSession,
) -> AuthenticatedRequestContext:
    claims = _decode_access_token(token)

    try:
        await _establish_tenant_context(db, company_id=claims.company_id)
        await _reject_blacklisted_token(db, token=token)
        return await resolve_access_context(db, claims)
    except HTTPException:
        raise
    except RequestContextRejected:
        raise _authentication_rejected() from None
    except Exception:
        # Persistence/RLS failures remain fail-closed and do not expose internals.
        raise _authentication_rejected() from None


async def get_current_principal_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    db: AsyncSession = Depends(get_db),
) -> AuthenticatedRequestContext:
    """Resolve a canonical company access token into persisted trusted identity."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_rejected()
    token = credentials.credentials
    if not token:
        raise _authentication_rejected()
    return await _resolve_http_context(token=token, db=db)


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
    "get_current_backoffice_context",
    "get_current_field_context",
    "get_current_principal_context",
]
