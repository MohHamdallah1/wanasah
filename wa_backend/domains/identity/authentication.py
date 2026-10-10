"""Channel-aware authentication for the new company identity model.

This module has no FastAPI, JWT, refresh-session, legacy Driver, or capability
responsibility. Runtime adapters are intentionally not cut over in this phase.
"""
import asyncio

import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from .channels import IdentityChannel, coerce_channel, expected_principal_type
from .contracts import (
    AuthenticationRejected,
    AuthenticationResult,
    DashboardAuthenticationResult,
    FieldAuthenticationResult,
)
from .repository import (
    IdentityRecordNotFound,
    load_active_principal_by_username,
    load_company_owner,
    require_active_company,
    require_backoffice_profile,
    require_field_representative_profile,
)


# Same precomputed bcrypt fallback used by the existing login path. Unknown or
# inactive usernames still exercise password verification without storing or
# returning any credential material.
DUMMY_PASSWORD_HASH = "$2b$12$C.O1Tz2R8o7Vq78UoA61ueh3b7Qz7t0V1H1t.zU0TzO1Q0xO7Qz.O"


async def verify_existing_password(password: str, password_hash: str) -> bool:
    """Verify the existing bcrypt hash format without introducing a new scheme."""
    try:
        return await asyncio.to_thread(
            bcrypt.checkpw,
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (TypeError, ValueError):
        return False


async def authenticate_identity(
    db: AsyncSession,
    *,
    company_id: int,
    username: str,
    password: str,
    channel: IdentityChannel | str,
) -> AuthenticationResult:
    """Authenticate an already resolved tenant against the frozen channel pair.

    The caller continues to own the existing login-time tenant-context setup.
    This service independently revalidates active company state and every
    identity/profile read remains explicitly tenant scoped.
    """
    try:
        resolved_channel = coerce_channel(channel)
    except ValueError as exc:
        raise AuthenticationRejected from exc

    try:
        await require_active_company(db, company_id)
    except IdentityRecordNotFound as exc:
        raise AuthenticationRejected from exc

    principal = await load_active_principal_by_username(
        db,
        company_id=company_id,
        username=username,
    )
    password_hash = principal.password_hash if principal is not None else DUMMY_PASSWORD_HASH
    password_matches = await verify_existing_password(password, password_hash)
    if principal is None or not password_matches:
        raise AuthenticationRejected

    expected_type = expected_principal_type(resolved_channel)
    if principal.principal_type != expected_type.value:
        raise AuthenticationRejected

    try:
        if resolved_channel is IdentityChannel.DASHBOARD:
            profile = await require_backoffice_profile(
                db,
                company_id=company_id,
                principal_id=principal.id,
            )
            owner = await load_company_owner(db, company_id=company_id)
            return DashboardAuthenticationResult(
                principal_id=principal.id,
                company_id=principal.company_id,
                backoffice_user_id=profile.id,
                username=principal.username,
                full_name=principal.full_name,
                auth_revision=principal.auth_revision,
                is_company_owner=(
                    owner is not None and owner.backoffice_user_id == profile.id
                ),
            )

        profile = await require_field_representative_profile(
            db,
            company_id=company_id,
            principal_id=principal.id,
        )
        return FieldAuthenticationResult(
            principal_id=principal.id,
            company_id=principal.company_id,
            representative_id=profile.id,
            username=principal.username,
            full_name=principal.full_name,
            auth_revision=principal.auth_revision,
        )
    except IdentityRecordNotFound as exc:
        raise AuthenticationRejected from exc
