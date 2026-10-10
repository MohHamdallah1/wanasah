"""Thin HTTP/login preparation boundary for canonical company identity cutover.

This module does not authenticate passwords, issue tokens, persist sessions, or
make authorization decisions. It prepares the tenant boundary and formats the
future dual canonical/legacy login responses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from context import tenant_context
from models import Company
from domains.identity.contracts import (
    DashboardAuthenticationResult,
    FieldAuthenticationResult,
)
from domains.identity.legacy_compatibility import (
    LegacyLoginCompatibility,
    LegacyLoginCompatibilityMissing,
    load_dashboard_login_compatibility,
    load_field_login_compatibility,
)


class LoginBoundaryRejected(Exception):
    """Fail-closed login-boundary rejection with no user-facing detail."""


@dataclass(frozen=True)
class LoginCompanyContext:
    company_id: int
    company_code: str


class DashboardLoginResponse(TypedDict):
    token: str
    refresh_token: str
    principal_id: int
    backoffice_user_id: int
    channel: Literal["DASHBOARD"]
    is_company_owner: bool
    company_id: int
    company_code: str
    driver_id: int
    driver_name: str
    is_admin: bool
    dashboard_access: Literal[True]


class FieldLoginResponse(TypedDict):
    token: str
    refresh_token: str
    principal_id: int
    representative_id: int
    channel: Literal["FIELD"]
    company_id: int
    company_code: str
    driver_id: int
    driver_name: str
    is_admin: bool


async def prepare_login_company(
    db: AsyncSession,
    *,
    company_code: str,
) -> LoginCompanyContext:
    """Resolve one active company, then seed tenant/RLS state for identity reads."""
    company_id = await db.scalar(
        select(Company.id).where(
            Company.company_code == company_code,
            Company.is_active.is_(True),
        )
    )
    if company_id is None:
        raise LoginBoundaryRejected

    company_id = int(company_id)
    context_token = tenant_context.set(company_id)
    try:
        # The company lookup already checked out the live connection before the
        # tenant was known. Preserve the current login route's explicit RLS seed.
        await db.execute(
            text("SELECT set_config('app.current_tenant', :v, false)"),
            {"v": str(company_id)},
        )
    except Exception as exc:
        tenant_context.reset(context_token)
        raise LoginBoundaryRejected from exc

    return LoginCompanyContext(
        company_id=company_id,
        company_code=company_code,
    )


def _require_same_company(
    company: LoginCompanyContext,
    authentication: DashboardAuthenticationResult | FieldAuthenticationResult,
) -> None:
    if authentication.company_id != company.company_id:
        raise LoginBoundaryRejected


async def require_dashboard_login_compatibility(
    db: AsyncSession,
    *,
    company: LoginCompanyContext,
    authentication: DashboardAuthenticationResult,
) -> LegacyLoginCompatibility:
    """Resolve the temporary Dashboard fields through the reviewed bridge only."""
    _require_same_company(company, authentication)
    try:
        return await load_dashboard_login_compatibility(
            db,
            company_id=company.company_id,
            backoffice_user_id=authentication.backoffice_user_id,
        )
    except LegacyLoginCompatibilityMissing as exc:
        raise LoginBoundaryRejected from exc


async def require_field_login_compatibility(
    db: AsyncSession,
    *,
    company: LoginCompanyContext,
    authentication: FieldAuthenticationResult,
) -> LegacyLoginCompatibility:
    """Resolve the temporary Field fields through the reviewed bridge only."""
    _require_same_company(company, authentication)
    try:
        return await load_field_login_compatibility(
            db,
            company_id=company.company_id,
            representative_id=authentication.representative_id,
        )
    except LegacyLoginCompatibilityMissing as exc:
        raise LoginBoundaryRejected from exc


def build_dashboard_login_response(
    *,
    company: LoginCompanyContext,
    authentication: DashboardAuthenticationResult,
    access_token: str,
    refresh_token: str,
    compatibility: LegacyLoginCompatibility | None,
) -> DashboardLoginResponse:
    """Build the future Dashboard dual response without side effects."""
    _require_same_company(company, authentication)
    if compatibility is None:
        raise LoginBoundaryRejected

    return {
        "token": access_token,
        "refresh_token": refresh_token,
        "principal_id": authentication.principal_id,
        "backoffice_user_id": authentication.backoffice_user_id,
        "channel": "DASHBOARD",
        "is_company_owner": authentication.is_company_owner,
        "company_id": authentication.company_id,
        "company_code": company.company_code,
        "driver_id": compatibility.legacy_driver_id,
        "driver_name": compatibility.legacy_driver_name,
        "is_admin": compatibility.legacy_is_admin,
        "dashboard_access": True,
    }


def build_field_login_response(
    *,
    company: LoginCompanyContext,
    authentication: FieldAuthenticationResult,
    access_token: str,
    refresh_token: str,
    compatibility: LegacyLoginCompatibility | None,
) -> FieldLoginResponse:
    """Build the future Field dual response without side effects."""
    _require_same_company(company, authentication)
    if compatibility is None:
        raise LoginBoundaryRejected

    return {
        "token": access_token,
        "refresh_token": refresh_token,
        "principal_id": authentication.principal_id,
        "representative_id": authentication.representative_id,
        "channel": "FIELD",
        "company_id": authentication.company_id,
        "company_code": company.company_code,
        "driver_id": compatibility.legacy_driver_id,
        "driver_name": compatibility.legacy_driver_name,
        "is_admin": compatibility.legacy_is_admin,
    }


__all__ = [
    "DashboardLoginResponse",
    "FieldLoginResponse",
    "LoginBoundaryRejected",
    "LoginCompanyContext",
    "build_dashboard_login_response",
    "build_field_login_response",
    "prepare_login_company",
    "require_dashboard_login_compatibility",
    "require_field_login_compatibility",
]
