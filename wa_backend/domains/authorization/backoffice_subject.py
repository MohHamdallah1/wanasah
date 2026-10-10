"""Canonical Backoffice authorization subject with a temporary grant-storage bridge.

Owner authority comes only from the persisted Dashboard request context. Until
UserRole/UserLocationAccess ownership is migrated, ordinary Backoffice subjects
may carry the mapped legacy Driver id solely as a locator for those grant rows.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.context import DashboardRequestContext
from domains.identity.migration.models import IdentityLegacyDriverMap


class BackofficeAuthorizationSubjectRejected(Exception):
    """Fail-closed subject resolution error with no transport semantics."""


@dataclass(frozen=True)
class BackofficeAuthorizationSubject:
    principal_id: int
    backoffice_user_id: int
    company_id: int
    is_company_owner: bool
    legacy_grant_driver_id: int | None


def _reject() -> None:
    raise BackofficeAuthorizationSubjectRejected


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


def _validate_context(context: DashboardRequestContext) -> None:
    if not isinstance(context, DashboardRequestContext):
        _reject()
    if not all(
        _positive_id(value)
        for value in (
            context.principal_id,
            context.backoffice_user_id,
            context.company_id,
        )
    ):
        _reject()
    if type(context.is_company_owner) is not bool:
        _reject()


async def resolve_backoffice_authorization_subject(
    db: AsyncSession,
    context: DashboardRequestContext,
) -> BackofficeAuthorizationSubject:
    """Resolve canonical Backoffice identity plus the temporary grant-row locator.

    Company Owner authority is already persisted in ``DashboardRequestContext``
    and never depends on the migration bridge. Non-owner subjects must have one
    exact tenant/principal/profile bridge row; its legacy id is returned only so
    later authorization code can locate still-legacy role/location assignments.
    """
    _validate_context(context)

    if context.is_company_owner:
        return BackofficeAuthorizationSubject(
            principal_id=context.principal_id,
            backoffice_user_id=context.backoffice_user_id,
            company_id=context.company_id,
            is_company_owner=True,
            legacy_grant_driver_id=None,
        )

    bridge = await db.scalar(
        select(IdentityLegacyDriverMap).where(
            IdentityLegacyDriverMap.company_id == context.company_id,
            IdentityLegacyDriverMap.backoffice_principal_id == context.principal_id,
            IdentityLegacyDriverMap.backoffice_user_id == context.backoffice_user_id,
        )
    )
    if bridge is None:
        _reject()

    if (
        bridge.company_id != context.company_id
        or bridge.backoffice_principal_id != context.principal_id
        or bridge.backoffice_user_id != context.backoffice_user_id
    ):
        _reject()

    legacy_driver_id = bridge.legacy_driver_id
    if not _positive_id(legacy_driver_id):
        _reject()

    return BackofficeAuthorizationSubject(
        principal_id=context.principal_id,
        backoffice_user_id=context.backoffice_user_id,
        company_id=context.company_id,
        is_company_owner=False,
        legacy_grant_driver_id=legacy_driver_id,
    )


__all__ = [
    "BackofficeAuthorizationSubject",
    "BackofficeAuthorizationSubjectRejected",
    "resolve_backoffice_authorization_subject",
]
