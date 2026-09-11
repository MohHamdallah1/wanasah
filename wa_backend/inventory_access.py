"""Explicit inventory permissions. Tenant isolation always precedes authorization.

UserRole grants apply company-wide; UserLocationAccess grants apply only to its
location. Legacy company admins retain their approved company-wide authority.
Names, branch membership and route membership never confer a permission.
"""
from dataclasses import dataclass
from fastapi import HTTPException
from sqlalchemy import and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from models import (Driver, Permission, UserRole, UserLocationAccess, role_permissions,
                    InventoryLocation, InventoryTransferHeader, InventoryMovement, StocktakeSession)

PERMISSIONS = frozenset({
    'location.read', 'location.create', 'location.update', 'location.state',
    'inventory.read', 'inbound.create', 'ledger.read', 'ledger.adjust',
    'catalog.read', 'catalog.manage', 'catalog.publish', 'catalog.retire',
    'catalog.restore', 'catalog.archive', 'catalog.hold',
    'product_location.read', 'product_location.manage',
    'transfer.read', 'transfer.send', 'transfer.receive', 'transfer.cancel',
    'transfer.reject', 'transfer.destination', 'inventory.fefo_override',
    'stocktake.read', 'stocktake.start', 'stocktake.count', 'stocktake.review',
    'stocktake.approve', 'stocktake.recount', 'stocktake.cancel',
    'dispatch.read', 'dispatch.execute',
})
COMPANY_ONLY = frozenset({
    'location.create', 'catalog.manage', 'catalog.publish', 'catalog.retire',
    'catalog.restore', 'catalog.archive', 'catalog.hold',
})


def _permission_codes(codes):
    result = (codes,) if isinstance(codes, str) else tuple(codes)
    if not result or not set(result) <= PERMISSIONS:
        raise ValueError('Unknown inventory permission')
    return result


@dataclass(frozen=True)
class InventoryAccess:
    db: AsyncSession
    actor: Driver

    @property
    def company_id(self):
        return self.actor.company_id

    def _grant_exists(self, assignment, codes, location=None):
        conditions = [
            assignment.company_id == self.company_id,
            assignment.driver_id == self.actor.id,
            role_permissions.c.company_id == self.company_id,
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
        if self.actor.is_admin:
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

    async def codes(self, location_id=None, *, any_location=False):
        if self.actor.is_admin:
            return sorted(PERMISSIONS)
        # One bounded query over the fixed permission catalog, no query per code.
        assignment = UserRole
        company_roles = select(assignment.role_id).where(
            assignment.company_id == self.company_id, assignment.driver_id == self.actor.id)
        role_filter = role_permissions.c.role_id.in_(company_roles)
        if location_id is not None or any_location:
            location_roles = select(UserLocationAccess.role_id).where(
                UserLocationAccess.company_id == self.company_id,
                UserLocationAccess.driver_id == self.actor.id)
            if location_id is not None:
                location_roles = location_roles.where(UserLocationAccess.location_id == location_id)
            role_filter = or_(role_filter, and_(
                role_permissions.c.role_id.in_(location_roles), Permission.code.not_in(COMPANY_ONLY)))
        return list((await self.db.scalars(select(Permission.code).join(
            role_permissions, role_permissions.c.permission_id == Permission.id,
        ).where(role_permissions.c.company_id == self.company_id,
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
        if visible and not self.actor.is_admin:
            rows = (await self.db.execute(select(UserLocationAccess.location_id, Permission.code)
                .join(role_permissions, and_(role_permissions.c.company_id == UserLocationAccess.company_id,
                      role_permissions.c.role_id == UserLocationAccess.role_id))
                .join(Permission, Permission.id == role_permissions.c.permission_id).where(
                    UserLocationAccess.company_id == self.company_id,
                    UserLocationAccess.driver_id == self.actor.id,
                    UserLocationAccess.location_id.in_(visible),
                    Permission.code.in_(PERMISSIONS - COMPANY_ONLY)).distinct())).all()
            for location, code in rows:
                result[location].add(code)
        return {location: sorted(codes) for location, codes in result.items()}


async def inventory_actor(current_driver, db):
    access = InventoryAccess(db, current_driver)
    await access.require(PERMISSIONS, any_location=True)
    return current_driver


async def require_stocktake(access, code, session_id):
    location_id = await access.db.scalar(select(StocktakeSession.location_id).where(
        StocktakeSession.company_id == access.company_id, StocktakeSession.id == session_id))
    if location_id is None:
        raise HTTPException(404, 'جلسة الجرد غير موجودة أو غير متاحة.')
    await access.require(code, location_id)


def transfer_filter(access, code='transfer.read'):
    return or_(access.allows(code, InventoryTransferHeader.source_location_id),
               access.allows(code, InventoryTransferHeader.destination_location_id))


async def require_transfer(access, code, header_id, side=None):
    # Only server-stored endpoints determine the authority, including replay.
    row = (await access.db.execute(select(
        InventoryTransferHeader.source_location_id, InventoryTransferHeader.destination_location_id,
    ).where(InventoryTransferHeader.company_id == access.company_id,
            InventoryTransferHeader.id == header_id))).one_or_none()
    if row is None:
        raise HTTPException(404, 'الحوالة غير موجودة أو غير متاحة.')
    if side is not None:
        await access.require(code, row[0 if side == 'source' else 1])
    elif not await access.db.scalar(select(or_(access.allows(code, row[0]), access.allows(code, row[1])))):
        raise HTTPException(403, 'لا تملك صلاحية عرض هذه الحوالة.')


async def require_inbound_adjustment(access, entry_id):
    location_id = await access.db.scalar(select(InventoryMovement.destination_location_id).where(
        InventoryMovement.company_id == access.company_id, InventoryMovement.id == entry_id,
        InventoryMovement.reference_type == 'INBOUND_SUPPLIER'))
    if location_id is None:
        raise HTTPException(404, 'حركة التوريد غير موجودة أو غير متاحة.')
    await access.require('ledger.adjust', location_id)
