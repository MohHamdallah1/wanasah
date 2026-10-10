"""Temporary Dashboard admission bridge for canonical Backoffice identities.

Owner admission is canonical and centralized. Ordinary Backoffice admission reuses
only the existing legacy grant rows through the reviewed identity bridge until
UserRole/UserLocationAccess are cut over to canonical Backoffice ownership.
"""
from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Permission, UserLocationAccess, UserRole, role_permissions
from domains.identity.contracts import DashboardAuthenticationResult
from domains.identity.migration.models import IdentityLegacyDriverMap

from .capabilities import COMPANY_ONLY, PERMISSIONS


class DashboardAdmissionRejected(Exception):
    """Fail-closed Dashboard admission rejection with no transport semantics."""


def _reject() -> None:
    raise DashboardAdmissionRejected


async def _load_legacy_driver_id(
    db: AsyncSession,
    *,
    identity: DashboardAuthenticationResult,
) -> int:
    bridge = await db.scalar(
        select(IdentityLegacyDriverMap).where(
            IdentityLegacyDriverMap.company_id == identity.company_id,
            IdentityLegacyDriverMap.backoffice_user_id == identity.backoffice_user_id,
        )
    )
    if bridge is None:
        _reject()

    if (
        bridge.company_id != identity.company_id
        or bridge.backoffice_user_id != identity.backoffice_user_id
        or bridge.backoffice_principal_id != identity.principal_id
    ):
        _reject()

    legacy_driver_id = bridge.legacy_driver_id
    if (
        isinstance(legacy_driver_id, bool)
        or not isinstance(legacy_driver_id, int)
        or legacy_driver_id <= 0
    ):
        _reject()
    return legacy_driver_id


def _grant_exists(
    assignment,
    *,
    company_id: int,
    legacy_driver_id: int,
    location_scoped: bool,
):
    conditions = [
        assignment.company_id == company_id,
        assignment.driver_id == legacy_driver_id,
        role_permissions.c.company_id == company_id,
        Permission.code.in_(PERMISSIONS),
    ]
    if location_scoped:
        conditions.append(Permission.code.not_in(COMPANY_ONLY))

    return (
        select(1)
        .select_from(assignment)
        .join(
            role_permissions,
            and_(
                role_permissions.c.company_id == assignment.company_id,
                role_permissions.c.role_id == assignment.role_id,
            ),
        )
        .join(Permission, Permission.id == role_permissions.c.permission_id)
        .where(*conditions)
        .exists()
    )


async def _has_company_grant(
    db: AsyncSession,
    *,
    company_id: int,
    legacy_driver_id: int,
) -> bool:
    return bool(
        await db.scalar(
            select(
                _grant_exists(
                    UserRole,
                    company_id=company_id,
                    legacy_driver_id=legacy_driver_id,
                    location_scoped=False,
                )
            )
        )
    )


async def _has_location_grant(
    db: AsyncSession,
    *,
    company_id: int,
    legacy_driver_id: int,
) -> bool:
    return bool(
        await db.scalar(
            select(
                _grant_exists(
                    UserLocationAccess,
                    company_id=company_id,
                    legacy_driver_id=legacy_driver_id,
                    location_scoped=True,
                )
            )
        )
    )


async def require_dashboard_admission(
    db: AsyncSession,
    identity: DashboardAuthenticationResult,
) -> DashboardAuthenticationResult:
    """Require persisted Owner or at least one existing Dashboard capability.

    Owner authority is canonical and bypasses the temporary legacy grant bridge.
    Non-owner identities use the bridge only to locate current grant assignments;
    the bridge itself never grants authority.
    """
    if identity.is_company_owner:
        return identity

    legacy_driver_id = await _load_legacy_driver_id(db, identity=identity)

    if await _has_company_grant(
        db,
        company_id=identity.company_id,
        legacy_driver_id=legacy_driver_id,
    ):
        return identity

    if await _has_location_grant(
        db,
        company_id=identity.company_id,
        legacy_driver_id=legacy_driver_id,
    ):
        return identity

    _reject()
    raise AssertionError("unreachable")


__all__ = [
    "DashboardAdmissionRejected",
    "require_dashboard_admission",
]
