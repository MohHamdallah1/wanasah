"""Canonical company request seams and fail-closed retired dependency names.

Resource routers must select an explicit channel and capability dependency.
Operational Driver objects belong only to the named compatibility adapters;
the former generic entry points cannot infer authority for unmigrated callers.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from domains.auth_sessions.context import (
    AuthenticatedRequestContext, DashboardRequestContext, FieldRequestContext,
)
from models import Driver

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
    require_backoffice_capabilities,
    require_backoffice_capability,
)
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from api.authentication.dependencies import (
    _authentication_rejected,
    get_authenticated_access_session,
    get_current_backoffice_context,
    get_current_field_context,
    get_current_principal_context,
)
from api.authentication.field_compatibility import get_current_field_legacy_driver


def _retired_dependency() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Authorization denied.",
    )


async def get_current_driver(
    current: AuthenticatedRequestContext = Depends(get_current_principal_context),
    db: AsyncSession = Depends(get_db),
) -> Driver:
    """Locate an operational row from canonical identity for old FK consumers.

    This name does not authorize a resource. Remaining callers must independently
    migrate tenant/capability/ownership checks to their explicit canonical seams.
    """
    if isinstance(current, DashboardRequestContext):
        return await get_current_backoffice_legacy_driver(current=current, db=db)
    if isinstance(current, FieldRequestContext):
        return await get_current_field_legacy_driver(current=current, db=db)
    raise _authentication_rejected()


async def get_current_driver_owned(driver_id: int):
    """Reject legacy ownership checks; field ownership needs trusted field context."""
    raise _retired_dependency()


async def get_current_admin():
    """Reject the retired generic gate; routers must require exact capabilities."""
    raise _retired_dependency()


__all__ = [
    "get_authenticated_access_session",
    "get_current_backoffice_capability_access",
    "get_current_backoffice_context",
    "get_current_backoffice_legacy_driver",
    "get_current_field_context",
    "get_current_field_legacy_driver",
    "get_current_principal_context",
    "require_backoffice_capabilities",
    "require_backoffice_capability",
]
