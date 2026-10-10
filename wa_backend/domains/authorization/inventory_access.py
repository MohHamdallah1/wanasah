"""Company and exact-location capability resolution for inventory-facing workflows.

Tenant isolation always precedes authorization. UserRole grants apply company-wide;
UserLocationAccess grants apply only to their exact location. The legacy full-authority
state is supplied only through the subject compatibility adapter during this phase.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    InventoryLocation,
    Permission,
    UserLocationAccess,
    UserRole,
    role_permissions,
)

from .capabilities import COMPANY_ONLY, PERMISSIONS
from .subject import (
    AuthorizationSubject,
    LegacyDriverAuthorizationSource,
    subject_from_legacy_driver,
)


def _permission_codes(codes):
    result = (codes,) if isinstance(codes, str) else tuple(codes)
    if not result or not set(result) <= PERMISSIONS:
        raise ValueError('Unknown inventory permission')
    return result


@dataclass(frozen=True)
class InventoryAccess:
    """Resolve existing company/location grants without changing caller contracts."""

    db: AsyncSession
    actor: LegacyDriverAuthorizationSource

    @property
    def subject(self) -> AuthorizationSubject:
        return subject_from_legacy_driver(self.actor)

    @property
    def company_id(self):
        return self.subject.company_id

    def _grant_exists(self, assignment, codes, location=None):
        subject = self.subject
        conditions = [
            assignment.company_id == subject.company_id,
            assignment.driver_id == subject.principal_id,
            role_permissions.c.company_id == subject.company_id,
            Permission.code.in_(codes),
        ]
        if assignment is UserLocationAccess:
            conditions.append(Permission.code.not_in(COMPANY_ONLY))
            if location is not None:
                conditions.append(assignment.location_id == location)
        return select(1).select_from(assignment).join(
            role_permissions,
            and_(role_permissions.c.company_id == assignment.company_id,
                 role_permissions.c.role_id == assignment.role_id),
        ).join(Permission, Permission.id == role_permissions.c.permission_id).where(*conditions).exists()

    def allows(self, codes, location=None, *, any_location=False):
        """SQL predicate usable before pagination/counts; never post-filter a page."""
        codes = _permission_codes(codes)
        if self.subject.legacy_full_authority:
            return true()
        company_grant = self._grant_exists(UserRole, codes)
        if location is None and not any_location:
            return company_grant
        return or_(company_grant, self._grant_exists(UserLocationAccess, codes, location))

    def location_filter(self, codes, column=InventoryLocation.id):
        return self.allows(codes, column)

    async def require(self, code, location_id=None, *, any_location=False):
        if location_id is not None:
            exists = await self.db.scalar(select(InventoryLocation.id).where(
                InventoryLocation.company_id == self.company_id,
                InventoryLocation.id == location_id,
            ))
            if exists is None:
                raise HTTPException(404, 'الموقع غير موجود أو غير متاح.')
        if not await self.db.scalar(select(self.allows(code, location_id, any_location=any_location))):
            raise HTTPException(403, 'لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.')

    async def require_all(self, codes, *, any_location=False):
        """Require every code without redundant legacy-full-authority SELECT calls.

        Caller supplies the active actor loaded for this transaction.
        Validate codes before the existing full-authority shortcut. Non-full-authority
        checks retain require()'s separate fresh reads and denial order; do not turn
        them into an ANY-code check or memoize grants across batches/retries.
        Exact-location commands continue to use require(code, location_id).
        """
        codes = _permission_codes(codes)
        if self.subject.legacy_full_authority:
            return
        for code in codes:
            await self.require(code, any_location=any_location)

    async def codes(self, location_id=None, *, any_location=False):
        if self.subject.legacy_full_authority:
            return sorted(PERMISSIONS)
        subject = self.subject
        # One bounded query over the fixed permission catalog, no query per code.
        company_roles = select(UserRole.role_id).where(
            UserRole.company_id == subject.company_id,
            UserRole.driver_id == subject.principal_id,
        )
        role_filter = role_permissions.c.role_id.in_(company_roles)
        if location_id is not None or any_location:
            location_roles = select(UserLocationAccess.role_id).where(
                UserLocationAccess.company_id == subject.company_id,
                UserLocationAccess.driver_id == subject.principal_id,
            )
            if location_id is not None:
                location_roles = location_roles.where(UserLocationAccess.location_id == location_id)
            role_filter = or_(role_filter, and_(
                role_permissions.c.role_id.in_(location_roles), Permission.code.not_in(COMPANY_ONLY)))
        return list((await self.db.scalars(select(Permission.code).join(
            role_permissions, role_permissions.c.permission_id == Permission.id,
        ).where(role_permissions.c.company_id == subject.company_id,
                Permission.code.in_(PERMISSIONS), role_filter).distinct().order_by(Permission.code))).all())

    async def codes_by_location(self, location_ids):
        """Bounded batch, constant query count; foreign/ungranted IDs are omitted."""
        ids = sorted(set(location_ids))
        if not ids or len(ids) > 100:
            raise ValueError('Expected 1..100 locations')
        visible = list((await self.db.scalars(select(InventoryLocation.id).where(
            InventoryLocation.company_id == self.company_id,
            InventoryLocation.id.in_(ids), self.location_filter(PERMISSIONS)))).all())
        global_codes = await self.codes()
        result = {location: set(global_codes) for location in visible}
        if visible and not self.subject.legacy_full_authority:
            subject = self.subject
            rows = (await self.db.execute(select(UserLocationAccess.location_id, Permission.code)
                .join(role_permissions, and_(role_permissions.c.company_id == UserLocationAccess.company_id,
                      role_permissions.c.role_id == UserLocationAccess.role_id))
                .join(Permission, Permission.id == role_permissions.c.permission_id).where(
                    UserLocationAccess.company_id == subject.company_id,
                    UserLocationAccess.driver_id == subject.principal_id,
                    UserLocationAccess.location_id.in_(visible),
                    Permission.code.in_(PERMISSIONS - COMPANY_ONLY)).distinct())).all()
            for location, code in rows:
                result[location].add(code)
        return {location: sorted(codes) for location, codes in result.items()}


__all__ = ["InventoryAccess"]
