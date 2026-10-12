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
from domains.authorization.backoffice_subject import (
    BackofficeAuthorizationSubject,
    BackofficeAuthorizationSubjectRejected,
    resolve_backoffice_authorization_subject,
)
from domains.identity.backoffice_legacy_actor import (
    BackofficeLegacyActorLocatorRejected,
    resolve_backoffice_legacy_actor_locator,
)
from models import TokenBlacklist
from workers.tenant import tenant_session


class WebSocketAuthError(Exception):
    pass


@dataclass(frozen=True)
class WebSocketAdminIdentity:
    """Canonical Dashboard websocket identity with one bounded legacy field.

    ``company_id`` is the persisted canonical Dashboard tenant. ``driver_id`` is
    retained only for current consumers that still need a legacy operational/FK
    identifier; it is resolved from the exact canonical identity mapping and is
    never the authenticated subject.
    """

    company_id: int
    driver_id: int
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

            # Bounded compatibility only: current Product Import websocket code
            # still consumes ``driver_id``. The exact canonical mapping service
            # validates company + principal + BackofficeUser together and never
            # turns the legacy Driver row into authentication authority.
            locator = await resolve_backoffice_legacy_actor_locator(
                db,
                context,
            )
            if (
                locator.company_id != context.company_id
                or locator.principal_id != context.principal_id
                or locator.backoffice_user_id != context.backoffice_user_id
            ):
                raise WebSocketAuthError("websocket authorization failed")

            identity = WebSocketAdminIdentity(
                company_id=context.company_id,
                driver_id=locator.legacy_driver_id,
                token_expires_at=claims.exp,
            )
            return identity, subject
    except WebSocketAuthError:
        raise
    except (
        RequestContextRejected,
        BackofficeAuthorizationSubjectRejected,
        BackofficeLegacyActorLocatorRejected,
    ) as exc:
        raise WebSocketAuthError("websocket authorization failed") from exc
    except Exception as exc:
        # Persistence, tenant/RLS and mapping failures all fail closed without
        # exposing internal identity state to websocket clients.
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
) -> WebSocketAdminIdentity:
    """Authenticate a persisted Dashboard/Backoffice identity; routes scope access."""
    identity, _subject = await _authenticate_websocket_identity(token)
    return identity
