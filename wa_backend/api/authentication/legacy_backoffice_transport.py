"""Transitional live transport from legacy Driver tokens to canonical Backoffice authority.

The legacy Driver is already authenticated by the current live transport. Its
company/id pair is used only to locate the migration bridge. All identity and
authorization decisions after that point are canonical and persistence-backed.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.auth_sessions.context import DashboardRequestContext
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.authorization.backoffice_subject import (
    BackofficeAuthorizationSubjectRejected,
    resolve_backoffice_authorization_subject,
)
from domains.authorization.capabilities import PERMISSIONS
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import BackofficeUser, CompanyOwner, CompanyPrincipal
from domains.identity.types import PrincipalType
from models import Driver


_AUTHENTICATION_REJECTION_DETAIL = "Authentication credentials are invalid or expired."
_AUTHORIZATION_REJECTION_DETAIL = "Authorization denied."
LegacyBackofficeCapabilityDependency = Callable[..., Awaitable[BackofficeCapabilityAccess]]


def _authentication_rejected() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_AUTHENTICATION_REJECTION_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authorization_rejected() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_AUTHORIZATION_REJECTION_DETAIL,
    )


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


async def get_legacy_transport_backoffice_context(
    current_driver: Driver = Depends(get_current_driver),
    db: AsyncSession = Depends(get_db),
) -> DashboardRequestContext:
    """Resolve the current live Driver token into exact canonical Backoffice identity."""
    company_id = current_driver.company_id
    legacy_driver_id = current_driver.id
    if not _positive_id(company_id) or not _positive_id(legacy_driver_id):
        raise _authentication_rejected()

    try:
        bridge = await db.scalar(
            select(IdentityLegacyDriverMap).where(
                IdentityLegacyDriverMap.company_id == company_id,
                IdentityLegacyDriverMap.legacy_driver_id == legacy_driver_id,
                IdentityLegacyDriverMap.backoffice_principal_id.is_not(None),
                IdentityLegacyDriverMap.backoffice_user_id.is_not(None),
            )
        )
        if bridge is None:
            raise _authentication_rejected()

        principal_id = bridge.backoffice_principal_id
        backoffice_user_id = bridge.backoffice_user_id
        if (
            bridge.company_id != company_id
            or bridge.legacy_driver_id != legacy_driver_id
            or not _positive_id(principal_id)
            or not _positive_id(backoffice_user_id)
        ):
            raise _authentication_rejected()

        principal = await db.scalar(
            select(CompanyPrincipal).where(
                CompanyPrincipal.company_id == company_id,
                CompanyPrincipal.id == principal_id,
                CompanyPrincipal.principal_type == PrincipalType.BACKOFFICE.value,
            )
        )
        if (
            principal is None
            or principal.company_id != company_id
            or principal.id != principal_id
            or principal.principal_type != PrincipalType.BACKOFFICE.value
            or principal.is_active is not True
            or not _positive_id(principal.auth_revision)
        ):
            raise _authentication_rejected()

        profile = await db.scalar(
            select(BackofficeUser).where(
                BackofficeUser.company_id == company_id,
                BackofficeUser.id == backoffice_user_id,
                BackofficeUser.principal_id == principal_id,
                BackofficeUser.principal_type == PrincipalType.BACKOFFICE.value,
            )
        )
        if (
            profile is None
            or profile.company_id != company_id
            or profile.id != backoffice_user_id
            or profile.principal_id != principal_id
            or profile.principal_type != PrincipalType.BACKOFFICE.value
        ):
            raise _authentication_rejected()

        owner = await db.scalar(
            select(CompanyOwner).where(CompanyOwner.company_id == company_id)
        )
        if owner is not None and (
            owner.company_id != company_id
            or not _positive_id(owner.backoffice_user_id)
        ):
            raise _authentication_rejected()

        return DashboardRequestContext(
            principal_id=principal_id,
            company_id=company_id,
            backoffice_user_id=backoffice_user_id,
            auth_revision=principal.auth_revision,
            is_company_owner=(
                owner is not None and owner.backoffice_user_id == backoffice_user_id
            ),
        )
    except HTTPException:
        raise
    except Exception:
        raise _authentication_rejected() from None


async def get_legacy_transport_backoffice_capability_access(
    current: DashboardRequestContext = Depends(get_legacy_transport_backoffice_context),
    db: AsyncSession = Depends(get_db),
) -> BackofficeCapabilityAccess:
    """Reuse canonical subject/access resolution after transitional authentication."""
    try:
        subject = await resolve_backoffice_authorization_subject(db, current)
    except BackofficeAuthorizationSubjectRejected:
        raise _authentication_rejected() from None
    return BackofficeCapabilityAccess(db=db, subject=subject)


def require_legacy_transport_backoffice_capability(
    code: str,
) -> LegacyBackofficeCapabilityDependency:
    """Require one canonical capability behind the current legacy token transport."""
    if type(code) is not str or code not in PERMISSIONS:
        raise ValueError("Unknown capability")
    capability = code

    async def dependency(
        access: BackofficeCapabilityAccess = Depends(
            get_legacy_transport_backoffice_capability_access
        ),
    ) -> BackofficeCapabilityAccess:
        try:
            await access.require(capability)
        except BackofficeCapabilityAccessRejected:
            raise _authorization_rejected() from None
        return access

    return dependency


__all__ = [
    "get_legacy_transport_backoffice_capability_access",
    "get_legacy_transport_backoffice_context",
    "require_legacy_transport_backoffice_capability",
]
