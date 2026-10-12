"""Bounded public login fields required by the current Dashboard/Flutter clients.

Retire this adapter after the client cutover in IDENTITY_CLIENT_LOGIN_CUTOVER_CONTRACT.
The canonical DTOs stay strict. Legacy IDs locate actual mapped operational rows;
names and presentation flags come only from the canonical authentication result.
No field here authenticates credentials or grants a backend capability.
"""
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from domains.identity.contracts import DashboardAuthenticationResult, FieldAuthenticationResult

from .backoffice_compatibility import get_current_backoffice_legacy_driver
from .field_compatibility import get_current_field_legacy_driver
from .login_orchestration import PrincipalLoginRejected, _dashboard_context, _field_context
from .schemas import DashboardPrincipalLoginResponse, FieldPrincipalLoginResponse, PositiveId


class DashboardLoginTransportResponse(DashboardPrincipalLoginResponse):
    principal_type: Literal["BACKOFFICE"] = "BACKOFFICE"
    display_name: str
    message: Literal["Admin Login Successful!"] = "Admin Login Successful!"
    legacy_driver_id: PositiveId
    driver_id: PositiveId
    driver_name: str


class FieldLoginTransportResponse(FieldPrincipalLoginResponse):
    principal_type: Literal["FIELD_REPRESENTATIVE"] = "FIELD_REPRESENTATIVE"
    display_name: str
    message: Literal["Login Successful!"] = "Login Successful!"
    legacy_driver_id: PositiveId
    driver_id: PositiveId
    driver_name: str
    dashboard_access: Literal[False] = False


async def prepare_dashboard_transport(db: AsyncSession, identity: DashboardAuthenticationResult):
    """Resolve required client data before creating a valid refresh session."""
    try:
        legacy_actor = await get_current_backoffice_legacy_driver(
            current=_dashboard_context(identity), db=db,
        )
        legacy_driver_id = legacy_actor.id
        if type(legacy_driver_id) is not int or legacy_driver_id <= 0:
            raise ValueError
    except Exception:
        raise PrincipalLoginRejected from None

    def adapt(response: DashboardPrincipalLoginResponse) -> DashboardLoginTransportResponse:
        return DashboardLoginTransportResponse(
            **response.model_dump(), display_name=identity.full_name,
            legacy_driver_id=legacy_driver_id, driver_id=legacy_driver_id,
            driver_name=identity.full_name,
        )

    return adapt


async def prepare_field_transport(db: AsyncSession, identity: FieldAuthenticationResult):
    """Keep the legacy field/offline identifier separate from principal/profile IDs."""
    try:
        legacy_actor = await get_current_field_legacy_driver(
            current=_field_context(identity), db=db,
        )
        legacy_driver_id = legacy_actor.id
        if type(legacy_driver_id) is not int or legacy_driver_id <= 0:
            raise ValueError
    except Exception:
        raise PrincipalLoginRejected from None

    def adapt(response: FieldPrincipalLoginResponse) -> FieldLoginTransportResponse:
        return FieldLoginTransportResponse(
            **response.model_dump(), display_name=identity.full_name,
            legacy_driver_id=legacy_driver_id, driver_id=legacy_driver_id,
            driver_name=identity.full_name,
        )

    return adapt
