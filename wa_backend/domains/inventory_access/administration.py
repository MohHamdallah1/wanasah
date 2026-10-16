"""Persistence helpers for the Inventory access administration seam.

Canonical identity and authorization stay in the Backoffice authorization domain.
This module only validates migrated permission rows and resolves the temporary
legacy grant-storage locator for a canonical Backoffice target.
"""
from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.authorization.capabilities import PERMISSIONS
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import BackofficeUser, CompanyPrincipal
from domains.identity.types import PrincipalType
from models import Permission


class InventoryAccessCatalogMismatch(Exception):
    """The persisted permission catalog is missing canonical registry rows."""


class InventoryAccessTargetNotFound(Exception):
    """The canonical Backoffice target is not visible in the actor tenant."""


class InventoryAccessBridgeRejected(Exception):
    """A canonical target has no exact legacy grant-storage bridge."""


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


async def ensure_permission_catalog(db: AsyncSession) -> None:
    """Fail closed when clean bootstrap/runtime storage drifts from the registry."""
    persisted = set(
        (await db.scalars(select(Permission.code).where(Permission.code.in_(PERMISSIONS)))).all()
    )
    missing = PERMISSIONS - persisted
    if missing:
        raise InventoryAccessCatalogMismatch(tuple(sorted(missing)))


async def permission_ids_for_codes(db: AsyncSession, codes: list[str]) -> dict[str, int]:
    """Resolve already-migrated registry rows without creating permissions on demand."""
    requested = set(codes)
    if not requested <= PERMISSIONS:
        raise ValueError("Unknown capability")
    rows = (
        await db.execute(
            select(Permission.code, Permission.id).where(Permission.code.in_(requested))
        )
    ).all()
    resolved = {code: permission_id for code, permission_id in rows}
    missing = requested - set(resolved)
    if missing:
        raise InventoryAccessCatalogMismatch(tuple(sorted(missing)))
    return resolved


async def target_legacy_grant_driver_id(
    db: AsyncSession,
    *,
    company_id: int,
    backoffice_user_id: int,
) -> int:
    """Validate canonical target identity, then resolve its existing grant storage."""
    if not _positive_id(company_id) or not _positive_id(backoffice_user_id):
        raise InventoryAccessTargetNotFound

    target = (
        await db.execute(
            select(
                BackofficeUser.company_id,
                BackofficeUser.id.label("backoffice_user_id"),
                BackofficeUser.principal_id,
            )
            .join(
                CompanyPrincipal,
                and_(
                    CompanyPrincipal.company_id == BackofficeUser.company_id,
                    CompanyPrincipal.id == BackofficeUser.principal_id,
                ),
            )
            .where(
                BackofficeUser.company_id == company_id,
                BackofficeUser.id == backoffice_user_id,
                CompanyPrincipal.company_id == company_id,
                BackofficeUser.principal_type == PrincipalType.BACKOFFICE.value,
                CompanyPrincipal.principal_type == PrincipalType.BACKOFFICE.value,
            )
        )
    ).one_or_none()
    if (
        target is None
        or target.company_id != company_id
        or target.backoffice_user_id != backoffice_user_id
        or not _positive_id(target.principal_id)
    ):
        raise InventoryAccessTargetNotFound

    bridge = await db.scalar(
        select(IdentityLegacyDriverMap).where(
            IdentityLegacyDriverMap.company_id == company_id,
            IdentityLegacyDriverMap.backoffice_principal_id == target.principal_id,
            IdentityLegacyDriverMap.backoffice_user_id == backoffice_user_id,
        )
    )
    if (
        bridge is None
        or bridge.company_id != company_id
        or bridge.backoffice_principal_id != target.principal_id
        or bridge.backoffice_user_id != backoffice_user_id
        or not _positive_id(bridge.legacy_driver_id)
    ):
        raise InventoryAccessBridgeRejected
    return bridge.legacy_driver_id
