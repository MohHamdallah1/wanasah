"""FastAPI seam from canonical Backoffice identity to capability authorization."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

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

from .dependencies import get_current_backoffice_context


_AUTHORIZATION_REJECTION_DETAIL = "Authorization denied."
BackofficeCapabilityDependency = Callable[..., Awaitable[BackofficeCapabilityAccess]]


def _authorization_rejected() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_AUTHORIZATION_REJECTION_DETAIL,
    )


def _validated_static_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    if (
        type(codes) is not tuple
        or not codes
        or any(type(code) is not str for code in codes)
        or not set(codes) <= PERMISSIONS
    ):
        raise ValueError("Unknown capability")
    return codes


async def get_current_backoffice_capability_access(
    current: DashboardRequestContext = Depends(get_current_backoffice_context),
    db: AsyncSession = Depends(get_db),
) -> BackofficeCapabilityAccess:
    """Build canonical capability access from an already-authenticated Dashboard context."""
    try:
        subject = await resolve_backoffice_authorization_subject(db, current)
    except BackofficeAuthorizationSubjectRejected:
        raise _authorization_rejected() from None
    return BackofficeCapabilityAccess(db=db, subject=subject)


def require_backoffice_capability(code: str) -> BackofficeCapabilityDependency:
    """Create a cached FastAPI dependency for one statically declared capability."""
    capability = _validated_static_codes((code,))[0]

    async def dependency(
        access: BackofficeCapabilityAccess = Depends(
            get_current_backoffice_capability_access
        ),
    ) -> BackofficeCapabilityAccess:
        try:
            await access.require(capability)
        except BackofficeCapabilityAccessRejected:
            raise _authorization_rejected() from None
        return access

    return dependency


def require_backoffice_capabilities(
    codes: tuple[str, ...],
) -> BackofficeCapabilityDependency:
    """Create a cached FastAPI dependency requiring every declared capability."""
    capabilities = _validated_static_codes(codes)

    async def dependency(
        access: BackofficeCapabilityAccess = Depends(
            get_current_backoffice_capability_access
        ),
    ) -> BackofficeCapabilityAccess:
        try:
            await access.require_all(capabilities)
        except BackofficeCapabilityAccessRejected:
            raise _authorization_rejected() from None
        return access

    return dependency


__all__ = [
    "get_current_backoffice_capability_access",
    "require_backoffice_capabilities",
    "require_backoffice_capability",
]
