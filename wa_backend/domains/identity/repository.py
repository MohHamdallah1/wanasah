"""Tenant-scoped persistence reads for CompanyPrincipal authentication."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Company
from .models import BackofficeUser, CompanyOwner, CompanyPrincipal, FieldRepresentative
from .types import PrincipalType


class IdentityRecordNotFound(LookupError):
    """Internal fail-closed lookup failure; never a user-facing response."""


async def require_active_company(db: AsyncSession, company_id: int) -> Company:
    company = await db.scalar(
        select(Company).where(
            Company.id == company_id,
            Company.is_active.is_(True),
        )
    )
    if company is None:
        raise IdentityRecordNotFound
    return company


async def load_active_principal_by_username(
    db: AsyncSession,
    *,
    company_id: int,
    username: str,
) -> CompanyPrincipal | None:
    return await db.scalar(
        select(CompanyPrincipal).where(
            CompanyPrincipal.company_id == company_id,
            CompanyPrincipal.username == username,
            CompanyPrincipal.is_active.is_(True),
        )
    )


async def load_principal_by_id(
    db: AsyncSession,
    *,
    company_id: int,
    principal_id: int,
) -> CompanyPrincipal | None:
    return await db.scalar(
        select(CompanyPrincipal).where(
            CompanyPrincipal.company_id == company_id,
            CompanyPrincipal.id == principal_id,
        )
    )


async def require_backoffice_profile(
    db: AsyncSession,
    *,
    company_id: int,
    principal_id: int,
) -> BackofficeUser:
    profile = await db.scalar(
        select(BackofficeUser).where(
            BackofficeUser.company_id == company_id,
            BackofficeUser.principal_id == principal_id,
            BackofficeUser.principal_type == PrincipalType.BACKOFFICE.value,
        )
    )
    if profile is None:
        raise IdentityRecordNotFound
    return profile


async def require_field_representative_profile(
    db: AsyncSession,
    *,
    company_id: int,
    principal_id: int,
) -> FieldRepresentative:
    profile = await db.scalar(
        select(FieldRepresentative).where(
            FieldRepresentative.company_id == company_id,
            FieldRepresentative.principal_id == principal_id,
            FieldRepresentative.principal_type == PrincipalType.FIELD_REPRESENTATIVE.value,
        )
    )
    if profile is None:
        raise IdentityRecordNotFound
    return profile


async def load_company_owner(
    db: AsyncSession,
    *,
    company_id: int,
) -> CompanyOwner | None:
    return await db.scalar(
        select(CompanyOwner).where(CompanyOwner.company_id == company_id)
    )
