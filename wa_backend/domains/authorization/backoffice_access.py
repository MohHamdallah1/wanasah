"""Canonical Backoffice capability resolution over current grant storage.

Company Owner authority comes only from canonical Backoffice subject state. Ordinary
Backoffice subjects temporarily locate legacy UserRole/UserLocationAccess rows through
the reviewed grant-storage locator; that legacy id is never canonical identity.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    InventoryLocation,
    Permission,
    UserLocationAccess,
    UserRole,
    role_permissions,
)

from .backoffice_subject import BackofficeAuthorizationSubject
from .capabilities import COMPANY_ONLY, PERMISSIONS


class BackofficeCapabilityAccessRejected(Exception):
    """Fail-closed capability/location rejection with no transport semantics."""


def _permission_codes(codes) -> tuple[str, ...]:
    result = (codes,) if isinstance(codes, str) else tuple(codes)
    if not result or not set(result) <= PERMISSIONS:
        raise ValueError("Unknown capability")
    return result


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


@dataclass(frozen=True)
class BackofficeCapabilityAccess:
    """Resolve canonical Owner authority and existing company/location grants."""

    db: AsyncSession
    subject: BackofficeAuthorizationSubject

    @property
    def company_id(self) -> int:
        if not _positive_id(self.subject.company_id):
            raise BackofficeCapabilityAccessRejected
        return self.subject.company_id

    def _grant_driver_id(self) -> int:
        if self.subject.is_company_owner:
            raise BackofficeCapabilityAccessRejected
        value = self.subject.legacy_grant_driver_id
        if not _positive_id(value):
            raise BackofficeCapabilityAccessRejected
        return value

    def _grant_exists(self, assignment, codes: tuple[str, ...], location=None):
        legacy_driver_id = self._grant_driver_id()
        conditions = [
            assignment.company_id == self.company_id,
            assignment.driver_id == legacy_driver_id,
            role_permissions.c.company_id == self.company_id,
            Permission.code.in_(codes),
        ]
        if assignment is UserLocationAccess:
            conditions.append(Permission.code.not_in(COMPANY_ONLY))
            if location is not None:
                conditions.append(assignment.location_id == location)
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

    def allows(self, codes, location_id=None, *, any_location: bool = False):
        """Return an SQL predicate suitable for pre-pagination filtering/counts."""
        codes = _permission_codes(codes)
        if self.subject.is_company_owner:
            if not _positive_id(self.subject.company_id):
                raise BackofficeCapabilityAccessRejected
            return true()

        company_grant = self._grant_exists(UserRole, codes)
        if location_id is None and not any_location:
            return company_grant
        return or_(
            company_grant,
            self._grant_exists(UserLocationAccess, codes, location_id),
        )

    def location_filter(self, codes, column=InventoryLocation.id):
        return self.allows(codes, location_id=column)

    async def require(self, code, location_id=None, *, any_location: bool = False) -> None:
        _permission_codes(code)
        if location_id is not None:
            if not _positive_id(location_id):
                raise BackofficeCapabilityAccessRejected
            exists = await self.db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == self.company_id,
                    InventoryLocation.id == location_id,
                )
            )
            if exists is None:
                raise BackofficeCapabilityAccessRejected

        if self.subject.is_company_owner:
            if not _positive_id(self.subject.company_id):
                raise BackofficeCapabilityAccessRejected
            return

        allowed = await self.db.scalar(
            select(self.allows(code, location_id=location_id, any_location=any_location))
        )
        if not bool(allowed):
            raise BackofficeCapabilityAccessRejected

    async def require_all(self, codes, *, any_location: bool = False) -> None:
        codes = _permission_codes(codes)
        if self.subject.is_company_owner:
            if not _positive_id(self.subject.company_id):
                raise BackofficeCapabilityAccessRejected
            return
        self._grant_driver_id()
        for code in codes:
            await self.require(code, any_location=any_location)

    async def codes(self, location_id=None, *, any_location: bool = False) -> list[str]:
        if self.subject.is_company_owner:
            if not _positive_id(self.subject.company_id):
                raise BackofficeCapabilityAccessRejected
            return sorted(PERMISSIONS)

        legacy_driver_id = self._grant_driver_id()
        company_roles = select(UserRole.role_id).where(
            UserRole.company_id == self.company_id,
            UserRole.driver_id == legacy_driver_id,
        )
        role_filter = role_permissions.c.role_id.in_(company_roles)

        if location_id is not None or any_location:
            if location_id is not None and not _positive_id(location_id):
                raise BackofficeCapabilityAccessRejected
            location_roles = select(UserLocationAccess.role_id).where(
                UserLocationAccess.company_id == self.company_id,
                UserLocationAccess.driver_id == legacy_driver_id,
            )
            if location_id is not None:
                location_roles = location_roles.where(
                    UserLocationAccess.location_id == location_id
                )
            role_filter = or_(
                role_filter,
                and_(
                    role_permissions.c.role_id.in_(location_roles),
                    Permission.code.not_in(COMPANY_ONLY),
                ),
            )

        rows = await self.db.scalars(
            select(Permission.code)
            .join(
                role_permissions,
                role_permissions.c.permission_id == Permission.id,
            )
            .where(
                role_permissions.c.company_id == self.company_id,
                Permission.code.in_(PERMISSIONS),
                role_filter,
            )
            .distinct()
            .order_by(Permission.code)
        )
        return list(rows.all())

    async def codes_by_location(self, location_ids) -> dict[int, list[str]]:
        ids = sorted(set(location_ids))
        if not ids or len(ids) > 100 or any(not _positive_id(value) for value in ids):
            raise ValueError("Expected 1..100 locations")

        if self.subject.is_company_owner:
            if not _positive_id(self.subject.company_id):
                raise BackofficeCapabilityAccessRejected
            visible_rows = await self.db.scalars(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == self.company_id,
                    InventoryLocation.id.in_(ids),
                )
            )
            return {
                location_id: sorted(PERMISSIONS)
                for location_id in visible_rows.all()
            }

        legacy_driver_id = self._grant_driver_id()
        visible_rows = await self.db.scalars(
            select(InventoryLocation.id).where(
                InventoryLocation.company_id == self.company_id,
                InventoryLocation.id.in_(ids),
                self.location_filter(PERMISSIONS),
            )
        )
        visible = list(visible_rows.all())

        global_codes = await self.codes()
        result = {location_id: set(global_codes) for location_id in visible}
        if visible:
            rows = await self.db.execute(
                select(UserLocationAccess.location_id, Permission.code)
                .join(
                    role_permissions,
                    and_(
                        role_permissions.c.company_id == UserLocationAccess.company_id,
                        role_permissions.c.role_id == UserLocationAccess.role_id,
                    ),
                )
                .join(Permission, Permission.id == role_permissions.c.permission_id)
                .where(
                    UserLocationAccess.company_id == self.company_id,
                    UserLocationAccess.driver_id == legacy_driver_id,
                    UserLocationAccess.location_id.in_(visible),
                    Permission.code.in_(PERMISSIONS - COMPANY_ONLY),
                )
                .distinct()
            )
            for location_id, code in rows.all():
                result[location_id].add(code)

        return {
            location_id: sorted(capability_codes)
            for location_id, capability_codes in result.items()
        }


__all__ = [
    "BackofficeCapabilityAccess",
    "BackofficeCapabilityAccessRejected",
]
