"""Temporary login-response compatibility over the reviewed identity bridge.

This module exists only for the bounded identity cutover window. It resolves the
legacy Driver row that current Dashboard/Flutter clients still expect. The
bridge is never authority: channel/profile eligibility is decided before this
adapter is called by canonical identity authentication.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Driver
from .migration.models import IdentityLegacyDriverMap


class LegacyLoginCompatibilityMissing(Exception):
    """Raised when canonical identity has no exact reviewed legacy mapping."""


@dataclass(frozen=True)
class LegacyLoginCompatibility:
    legacy_driver_id: int
    legacy_is_admin: bool
    legacy_driver_name: str


async def _load_legacy_login_compatibility(
    db: AsyncSession,
    *,
    company_id: int,
    profile_column,
    profile_id: int,
) -> LegacyLoginCompatibility:
    row = (
        await db.execute(
            select(IdentityLegacyDriverMap, Driver)
            .join(
                Driver,
                and_(
                    Driver.company_id == IdentityLegacyDriverMap.company_id,
                    Driver.id == IdentityLegacyDriverMap.legacy_driver_id,
                ),
            )
            .where(
                IdentityLegacyDriverMap.company_id == company_id,
                profile_column == profile_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise LegacyLoginCompatibilityMissing

    bridge, driver = row
    if (
        bridge.company_id != company_id
        or driver.company_id != company_id
        or driver.id != bridge.legacy_driver_id
    ):
        raise LegacyLoginCompatibilityMissing

    return LegacyLoginCompatibility(
        legacy_driver_id=driver.id,
        legacy_is_admin=bool(driver.is_admin),
        legacy_driver_name=driver.full_name,
    )


async def load_dashboard_login_compatibility(
    db: AsyncSession,
    *,
    company_id: int,
    backoffice_user_id: int,
) -> LegacyLoginCompatibility:
    """Resolve the exact legacy Driver backing one Backoffice profile."""
    return await _load_legacy_login_compatibility(
        db,
        company_id=company_id,
        profile_column=IdentityLegacyDriverMap.backoffice_user_id,
        profile_id=backoffice_user_id,
    )


async def load_field_login_compatibility(
    db: AsyncSession,
    *,
    company_id: int,
    representative_id: int,
) -> LegacyLoginCompatibility:
    """Resolve the exact legacy Driver backing one FieldRepresentative profile."""
    return await _load_legacy_login_compatibility(
        db,
        company_id=company_id,
        profile_column=IdentityLegacyDriverMap.field_representative_id,
        profile_id=representative_id,
    )


__all__ = [
    "LegacyLoginCompatibility",
    "LegacyLoginCompatibilityMissing",
    "load_dashboard_login_compatibility",
    "load_field_login_compatibility",
]
