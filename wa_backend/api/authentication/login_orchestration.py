"""Canonical company-login orchestration prepared for the Phase 5 runtime cutover.

This module composes the already-separated identity, authorization, session, and
HTTP-boundary components. It does not define routes and therefore does not change
runtime behavior until the explicit router cutover.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from domains.authorization.dashboard_admission import (
    DashboardAdmissionRejected,
    require_dashboard_admission,
)
from domains.auth_sessions.codec import issue_access_token
from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
from domains.auth_sessions.login_attempts import (
    LoginAttemptRateLimited,
    enforce_company_login_attempt_limit,
    record_login_attempt,
)
from domains.auth_sessions.refresh_sessions import (
    RefreshSessionRejected,
    RefreshSessionTransactionRequired,
    create_refresh_session,
)
from domains.identity.authentication import authenticate_identity
from domains.identity.channels import IdentityChannel
from domains.identity.contracts import (
    AuthenticationRejected,
    DashboardAuthenticationResult,
    FieldAuthenticationResult,
)

from .login import (
    LoginBoundaryRejected,
    build_dashboard_login_response,
    build_field_login_response,
    prepare_login_company,
    require_dashboard_login_compatibility,
    require_field_login_compatibility,
)
from .schemas import DashboardPrincipalLoginResponse, FieldPrincipalLoginResponse


class PrincipalLoginRejected(Exception):
    """Opaque company-login rejection with no credential or policy detail."""


class PrincipalLoginRateLimited(Exception):
    """Opaque signal that the preserved IP-based login limit was reached."""


async def _record_failed_login(
    db: AsyncSession,
    *,
    ip_address: str,
    username: str,
    company_code: str,
) -> None:
    """Persist one failed attempt without leaving an identity/session write behind."""
    record_login_attempt(
        db,
        ip_address=ip_address,
        username=username,
        company_code=company_code,
        successful=False,
    )
    await db.commit()


def _dashboard_context(identity: DashboardAuthenticationResult) -> DashboardRequestContext:
    return DashboardRequestContext(
        principal_id=identity.principal_id,
        company_id=identity.company_id,
        backoffice_user_id=identity.backoffice_user_id,
        auth_revision=identity.auth_revision,
        is_company_owner=identity.is_company_owner,
    )


def _field_context(identity: FieldAuthenticationResult) -> FieldRequestContext:
    return FieldRequestContext(
        principal_id=identity.principal_id,
        company_id=identity.company_id,
        representative_id=identity.representative_id,
        auth_revision=identity.auth_revision,
    )


async def _enforce_attempt_limit(db: AsyncSession, *, ip_address: str) -> None:
    try:
        await enforce_company_login_attempt_limit(db, ip_address=ip_address)
    except LoginAttemptRateLimited:
        # The limit check is read-only. End its autobegun transaction cleanly.
        await db.rollback()
        raise PrincipalLoginRateLimited from None


async def login_dashboard_principal(
    db: AsyncSession,
    *,
    company_code: str,
    username: str,
    password: str,
    ip_address: str,
    secret: str,
) -> DashboardPrincipalLoginResponse:
    """Compose canonical Dashboard login without mounting a runtime route."""
    await _enforce_attempt_limit(db, ip_address=ip_address)

    try:
        company = await prepare_login_company(db, company_code=company_code)
        identity = await authenticate_identity(
            db,
            company_id=company.company_id,
            username=username,
            password=password,
            channel=IdentityChannel.DASHBOARD,
        )
        if not isinstance(identity, DashboardAuthenticationResult):
            raise PrincipalLoginRejected
        await require_dashboard_admission(db, identity)
        compatibility = await require_dashboard_login_compatibility(
            db,
            company=company,
            authentication=identity,
        )
    except (LoginBoundaryRejected, AuthenticationRejected, DashboardAdmissionRejected):
        await _record_failed_login(
            db,
            ip_address=ip_address,
            username=username,
            company_code=company_code,
        )
        raise PrincipalLoginRejected from None

    try:
        refresh = await create_refresh_session(
            db,
            _dashboard_context(identity),
            secret=secret,
        )
        access_token = issue_access_token(
            principal_id=identity.principal_id,
            company_id=identity.company_id,
            channel=identity.channel.value,
            principal_type=identity.principal_type.value,
            auth_revision=identity.auth_revision,
            secret=secret,
        )
        payload = build_dashboard_login_response(
            company=company,
            authentication=identity,
            access_token=access_token,
            refresh_token=refresh.refresh_token,
            compatibility=compatibility,
        )
        response = DashboardPrincipalLoginResponse(**payload)
        record_login_attempt(
            db,
            ip_address=ip_address,
            username=username,
            company_code=company_code,
            successful=True,
        )
        await db.commit()
        return response
    except (RefreshSessionRejected, RefreshSessionTransactionRequired, LoginBoundaryRejected):
        await db.rollback()
        raise PrincipalLoginRejected from None
    except Exception:
        await db.rollback()
        raise


async def login_field_principal(
    db: AsyncSession,
    *,
    company_code: str,
    username: str,
    password: str,
    ip_address: str,
    secret: str,
) -> FieldPrincipalLoginResponse:
    """Compose canonical Field login without mounting a runtime route."""
    await _enforce_attempt_limit(db, ip_address=ip_address)

    try:
        company = await prepare_login_company(db, company_code=company_code)
        identity = await authenticate_identity(
            db,
            company_id=company.company_id,
            username=username,
            password=password,
            channel=IdentityChannel.FIELD,
        )
        if not isinstance(identity, FieldAuthenticationResult):
            raise PrincipalLoginRejected
        compatibility = await require_field_login_compatibility(
            db,
            company=company,
            authentication=identity,
        )
    except (LoginBoundaryRejected, AuthenticationRejected):
        await _record_failed_login(
            db,
            ip_address=ip_address,
            username=username,
            company_code=company_code,
        )
        raise PrincipalLoginRejected from None

    try:
        refresh = await create_refresh_session(
            db,
            _field_context(identity),
            secret=secret,
        )
        access_token = issue_access_token(
            principal_id=identity.principal_id,
            company_id=identity.company_id,
            channel=identity.channel.value,
            principal_type=identity.principal_type.value,
            auth_revision=identity.auth_revision,
            secret=secret,
        )
        payload = build_field_login_response(
            company=company,
            authentication=identity,
            access_token=access_token,
            refresh_token=refresh.refresh_token,
            compatibility=compatibility,
        )
        response = FieldPrincipalLoginResponse(**payload)
        record_login_attempt(
            db,
            ip_address=ip_address,
            username=username,
            company_code=company_code,
            successful=True,
        )
        await db.commit()
        return response
    except (RefreshSessionRejected, RefreshSessionTransactionRequired, LoginBoundaryRejected):
        await db.rollback()
        raise PrincipalLoginRejected from None
    except Exception:
        await db.rollback()
        raise


__all__ = [
    "PrincipalLoginRateLimited",
    "PrincipalLoginRejected",
    "login_dashboard_principal",
    "login_field_principal",
]
