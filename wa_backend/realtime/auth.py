from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from config import Config
from domains.auth_sessions.claims import CompanyTokenClaims
from domains.auth_sessions.codec import decode_company_token
from domains.auth_sessions.context import (
    DashboardRequestContext,
    RequestContextRejected,
    resolve_access_context,
)
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import (
    BackofficeAuthorizationSubject,
    BackofficeAuthorizationSubjectRejected,
    resolve_backoffice_authorization_subject,
)
from models import TokenBlacklist
from workers.tenant import tenant_session


class WebSocketAuthError(Exception):
    pass


@dataclass(frozen=True)
class WebSocketAdminIdentity:
    """Canonical persisted Dashboard websocket identity."""

    company_id: int
    token_expires_at: int


def _decode_websocket_access_token(token: str) -> CompanyTokenClaims:
    try:
        return decode_company_token(
            token,
            secret=Config.SECRET_KEY,
            expected_type="access",
        )
    except Exception as exc:
        raise WebSocketAuthError("invalid websocket token") from exc


async def _reject_blacklisted_websocket_token(db, *, token: str) -> None:
    blacklisted_exists = (
        select(TokenBlacklist.id)
        .where(TokenBlacklist.token == token)
        .exists()
    )
    if bool(await db.scalar(select(blacklisted_exists))):
        raise WebSocketAuthError("revoked websocket token")


async def _authenticate_websocket_identity(
    token: str,
    *,
    capability: str | None = None,
    any_location: bool = False,
) -> tuple[WebSocketAdminIdentity, BackofficeAuthorizationSubject]:
    claims = _decode_websocket_access_token(token)

    try:
        # The signed company claim is used only to bootstrap the tenant/RLS
        # session. Persisted canonical context below remains the authority.
        async with tenant_session(claims.company_id) as db:
            await _reject_blacklisted_websocket_token(db, token=token)

            context = await resolve_access_context(db, claims)
            if not isinstance(context, DashboardRequestContext):
                raise WebSocketAuthError("websocket authorization failed")
            if context.company_id != claims.company_id:
                raise WebSocketAuthError("websocket authorization failed")

            subject = await resolve_backoffice_authorization_subject(
                db,
                context,
            )
            if (
                subject.company_id != context.company_id
                or subject.principal_id != context.principal_id
                or subject.backoffice_user_id != context.backoffice_user_id
            ):
                raise WebSocketAuthError("websocket authorization failed")

            # Capability checks run while the same canonical tenant/RLS session
            # is still open. No DB-bound access object escapes this boundary.
            if capability is not None:
                await BackofficeCapabilityAccess(
                    db,
                    subject,
                ).require(
                    capability,
                    any_location=any_location,
                )

            return (
                WebSocketAdminIdentity(
                    company_id=context.company_id,
                    token_expires_at=claims.exp,
                ),
                subject,
            )
    except WebSocketAuthError:
        raise
    except (
        RequestContextRejected,
        BackofficeAuthorizationSubjectRejected,
        BackofficeCapabilityAccessRejected,
    ) as exc:
        raise WebSocketAuthError("websocket authorization failed") from exc
    except Exception as exc:
        # Persistence, tenant/RLS and authorization failures all fail closed
        # without exposing internal identity state to websocket clients.
        raise WebSocketAuthError("websocket authorization failed") from exc


async def authenticate_websocket_admin(
    token: str,
) -> WebSocketAdminIdentity:
    """Authenticate only the explicit persisted Company Owner Dashboard subject."""
    identity, subject = await _authenticate_websocket_identity(token)
    if not subject.is_company_owner:
        raise WebSocketAuthError("websocket authorization failed")
    return identity


async def authenticate_websocket_user(
    token: str,
    *,
    capability: str | None = None,
    any_location: bool = False,
) -> WebSocketAdminIdentity:
    """Authenticate Dashboard identity and optionally require a capability in-session."""
    identity, _subject = await _authenticate_websocket_identity(
        token,
        capability=capability,
        any_location=any_location,
    )
    return identity
