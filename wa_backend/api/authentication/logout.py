"""Additive canonical logout orchestration; existing HTTP routes stay unwired.

The caller supplies the already-authenticated access token and its exact decoded
claims, and owns the transaction's completion. Authentication failures are opaque;
the caller must roll back when this function raises. No tokens are logged here.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.access_revocation import blacklist_authenticated_access_token
from domains.auth_sessions.claims import CompanyTokenClaims
from domains.auth_sessions.codec import decode_company_token
from domains.auth_sessions.refresh_sessions import revoke_refresh_session

from .dependencies import _authentication_rejected


async def logout_authenticated_principal(
    db: AsyncSession,
    *,
    access_token: str,
    claims: CompanyTokenClaims,
    secret: str,
    refresh_token: str | None = None,
) -> None:
    """Blacklist exact access and optionally revoke only its matching refresh row.

    Supplied refresh identity must equal authenticated access in all five identity
    fields. Repeated calls are state-idempotent. Neither helper completes the caller
    transaction, and logout never follows a refresh successor or revokes siblings.
    """
    try:
        if not db.in_transaction():
            raise ValueError
        if not isinstance(access_token, str) or not access_token or len(access_token) > 500:
            raise ValueError
        if not isinstance(claims, CompanyTokenClaims) or claims.token_type != "access":
            raise ValueError
        decoded_access = decode_company_token(access_token, secret=secret, expected_type="access")
        if decoded_access != claims:
            raise ValueError

        if refresh_token is not None:
            decoded_refresh = decode_company_token(refresh_token, secret=secret, expected_type="refresh")
            if any(getattr(decoded_refresh, name) != getattr(claims, name) for name in
                   ("company_id", "principal_id", "channel", "principal_type", "auth_revision")):
                raise ValueError
            # Revoke performs exact locked lookup and all persisted identity checks
            # before its write. Auth rejection therefore cannot leave a blacklist row.
            await revoke_refresh_session(db, refresh_token, secret=secret)

        await blacklist_authenticated_access_token(db, token=access_token, claims=claims)
    except Exception:
        # Includes persistence failures, whose SQL parameters may contain tokens.
        raise _authentication_rejected() from None


__all__ = ["logout_authenticated_principal"]
