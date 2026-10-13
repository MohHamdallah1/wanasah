from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from domains.identity.types import PrincipalType
from models import Driver

from .contracts import RepresentativeError


async def username_exists(
    db: AsyncSession,
    *,
    company_id: int,
    username: str,
    exclude_principal_id: int | None = None,
    exclude_legacy_driver_id: int | None = None,
) -> bool:
    principal_stmt = select(CompanyPrincipal.id).where(
        CompanyPrincipal.company_id == company_id,
        CompanyPrincipal.username == username,
    )
    if exclude_principal_id is not None:
        principal_stmt = principal_stmt.where(CompanyPrincipal.id != exclude_principal_id)
    if await db.scalar(principal_stmt.limit(1)) is not None:
        return True

    legacy_stmt = select(Driver.id).where(
        Driver.company_id == company_id,
        Driver.username == username,
    )
    if exclude_legacy_driver_id is not None:
        legacy_stmt = legacy_stmt.where(Driver.id != exclude_legacy_driver_id)
    return await db.scalar(legacy_stmt.limit(1)) is not None


async def load_management_row(
    db: AsyncSession,
    *,
    company_id: int,
    representative_id: int,
    for_update: bool = False,
):
    canonical_statement = (
        select(FieldRepresentative, CompanyPrincipal)
        .join(
            CompanyPrincipal,
            and_(
                CompanyPrincipal.company_id == FieldRepresentative.company_id,
                CompanyPrincipal.id == FieldRepresentative.principal_id,
                CompanyPrincipal.principal_type == PrincipalType.FIELD_REPRESENTATIVE.value,
            ),
        )
        .where(
            FieldRepresentative.company_id == company_id,
            FieldRepresentative.id == representative_id,
            FieldRepresentative.principal_type == PrincipalType.FIELD_REPRESENTATIVE.value,
        )
    )
    if for_update:
        canonical_statement = canonical_statement.with_for_update(
            of=(FieldRepresentative, CompanyPrincipal)
        )
    canonical_row = (await db.execute(canonical_statement)).one_or_none()
    if canonical_row is None:
        raise RepresentativeError(
            "REPRESENTATIVE_NOT_FOUND",
            "Representative was not found.",
            status_code=404,
        )
    profile, principal = canonical_row
    if (
        profile.company_id != company_id
        or principal.company_id != company_id
        or profile.principal_id != principal.id
    ):
        raise RepresentativeError(
            "REPRESENTATIVE_IDENTITY_INCONSISTENT",
            "Representative identity is inconsistent.",
            status_code=409,
        )

    compatibility_statement = (
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
            IdentityLegacyDriverMap.field_principal_id == principal.id,
            IdentityLegacyDriverMap.field_representative_id == profile.id,
        )
    )
    if for_update:
        compatibility_statement = compatibility_statement.with_for_update(
            of=(IdentityLegacyDriverMap, Driver)
        )
    compatibility_row = (await db.execute(compatibility_statement)).one_or_none()
    bridge = compatibility_row[0] if compatibility_row is not None else None
    legacy_driver = compatibility_row[1] if compatibility_row is not None else None
    return profile, principal, bridge, legacy_driver


async def require_operational_compatibility(
    db: AsyncSession,
    *,
    company_id: int,
    representative_id: int,
):
    profile, principal, bridge, legacy_driver = await load_management_row(
        db,
        company_id=company_id,
        representative_id=representative_id,
        for_update=True,
    )
    if (
        bridge is None
        or legacy_driver is None
        or bridge.classification != "FIELD_ONLY"
        or bridge.company_id != company_id
        or bridge.field_principal_id != principal.id
        or bridge.field_representative_id != profile.id
        or bridge.legacy_driver_id != legacy_driver.id
        or legacy_driver.company_id != company_id
    ):
        raise RepresentativeError(
            "REPRESENTATIVE_OPERATIONAL_COMPATIBILITY_MISSING",
            "Representative operational compatibility is incomplete.",
            status_code=409,
        )
    return profile, principal, bridge, legacy_driver


__all__ = [
    "load_management_row",
    "require_operational_compatibility",
    "username_exists",
]
