"""Temporary canonical Backoffice to legacy operational-actor locator."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.context import DashboardRequestContext
from domains.identity.migration.models import IdentityLegacyDriverMap


class BackofficeLegacyActorLocatorRejected(Exception):
    """Fail-closed compatibility mapping error with no transport semantics."""


@dataclass(frozen=True)
class BackofficeLegacyActorLocator:
    principal_id: int
    backoffice_user_id: int
    company_id: int
    legacy_driver_id: int


def _reject() -> None:
    raise BackofficeLegacyActorLocatorRejected


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


async def resolve_backoffice_legacy_actor_locator(
    db: AsyncSession,
    context: DashboardRequestContext,
) -> BackofficeLegacyActorLocator:
    """Resolve a legacy operational/FK id from an already trusted context.

    This mapping is compatibility data only. Authentication and authorization
    remain canonical and are not inferred from the returned legacy id.
    """
    _validate_context(context)

    try:
        result = await db.execute(
            select(IdentityLegacyDriverMap).where(
                IdentityLegacyDriverMap.company_id == context.company_id,
                IdentityLegacyDriverMap.backoffice_principal_id == context.principal_id,
                IdentityLegacyDriverMap.backoffice_user_id == context.backoffice_user_id,
            )
        )
        bridge = result.scalar_one_or_none()
    except MultipleResultsFound:
        _reject()

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

    return BackofficeLegacyActorLocator(
        principal_id=context.principal_id,
        backoffice_user_id=context.backoffice_user_id,
        company_id=context.company_id,
        legacy_driver_id=legacy_driver_id,
    )


__all__ = [
    "BackofficeLegacyActorLocator",
    "BackofficeLegacyActorLocatorRejected",
    "resolve_backoffice_legacy_actor_locator",
]
