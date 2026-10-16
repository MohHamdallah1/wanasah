"""Canonical Backoffice introspection and CompanyOwner-only grant management."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, delete, func, and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.capabilities import PERMISSIONS, COMPANY_ONLY
from domains.identity.models import BackofficeUser, CompanyOwner, CompanyPrincipal
from domains.identity.types import PrincipalType
from domains.inventory_access import (
    InventoryAccessBridgeRejected,
    InventoryAccessCatalogMismatch,
    InventoryAccessTargetNotFound,
    ensure_permission_catalog,
    permission_ids_for_codes,
    target_legacy_grant_driver_id as resolve_target_legacy_grant_driver_id,
)
from models import (
    Driver,
    Role,
    Permission,
    UserRole,
    UserLocationAccess,
    role_permissions,
    InventoryLocation,
    SystemAuditLog,
)

router = APIRouter(prefix='/inventory/access', tags=['Inventory Permissions'])


class RoleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(max_length=len(PERMISSIONS))


class GrantInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role_id: int = Field(gt=0)
    location_id: int | None = Field(default=None, gt=0)


async def _require_company_owner(
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
) -> BackofficeCapabilityAccess:
    # Owner authority is canonical subject state only; no capability or legacy flag may substitute.
    if access.subject.is_company_owner is not True:
        raise HTTPException(403, 'Authorization denied.')
    return access


def audit(db, company_id, legacy_actor_id, target, action, old, new):
    import json
    db.add(SystemAuditLog(
        company_id=company_id,
        admin_id=legacy_actor_id,
        target_id=target,
        action_type=action,
        old_value=json.dumps(old, ensure_ascii=False),
        new_value=json.dumps(new, ensure_ascii=False),
    ))


@router.get('/me')
async def capabilities(
    location_id: int | None = Query(None, gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    if location_id is not None:
        location = await db.scalar(select(InventoryLocation.id).where(
            InventoryLocation.company_id == access.company_id,
            InventoryLocation.id == location_id,
        ))
        if location is None:
            raise HTTPException(403, 'Authorization denied.')
    subject = access.subject
    return {
        'company_id': access.company_id,
        'principal_id': subject.principal_id,
        'backoffice_user_id': subject.backoffice_user_id,
        'is_company_owner': subject.is_company_owner,
        'location_id': location_id,
        'permissions': await access.codes(),
        'any_permissions': await access.codes(any_location=True),
        'location_permissions': await access.codes(location_id) if location_id is not None else [],
    }


class LocationCapabilitiesInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    location_ids: list[int] = Field(min_length=1, max_length=100)


@router.post('/locations/capabilities')
async def location_capabilities(
    payload: LocationCapabilitiesInput,
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    if any(type(value) is not int or not 0 < value <= 2147483647 for value in payload.location_ids):
        raise HTTPException(422, 'Invalid location id.')
    return {'locations': await access.codes_by_location(payload.location_ids)}


@router.get('/catalog')
async def permission_catalog(
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_require_company_owner),
):
    try:
        await ensure_permission_catalog(db)
    except InventoryAccessCatalogMismatch:
        raise HTTPException(503, 'Permission catalog is incomplete.') from None
    return {'permissions': sorted(PERMISSIONS), 'company_only': sorted(COMPANY_ONLY)}


@router.get('/roles')
async def roles(
    after_id: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_require_company_owner),
):
    rows = (await db.scalars(select(Role).where(
        Role.company_id == access.company_id,
        Role.id > after_id,
    ).order_by(Role.id).limit(limit + 1))).all()
    page = rows[:limit]
    by_role = {r.id: [] for r in page}
    if page:
        grants = (await db.execute(select(role_permissions.c.role_id, Permission.code).join(
            Permission, Permission.id == role_permissions.c.permission_id,
        ).where(
            role_permissions.c.company_id == access.company_id,
            role_permissions.c.role_id.in_(by_role),
            Permission.code.in_(PERMISSIONS),
        ).order_by(Permission.code))).all()
        for role_id, code in grants:
            by_role[role_id].append(code)
    return {
        'items': [
            {
                'id': r.id,
                'name': r.name,
                'permissions': by_role[r.id],
                'is_system_role': r.is_system_role,
            }
            for r in page
        ],
        'next_id': page[-1].id if len(rows) > limit else None,
    }


async def save_role(payload, db, access, legacy_actor, role_id=None):
    name = payload.name.strip()
    codes = sorted(set(payload.permissions))
    if not name or not set(codes) <= PERMISSIONS:
        raise HTTPException(422, 'Invalid role name or capability codes.')
    try:
        permission_ids = await permission_ids_for_codes(db, codes)
    except InventoryAccessCatalogMismatch:
        raise HTTPException(503, 'Permission catalog is incomplete.') from None

    # Serialize role management within a tenant (including a new role's name).
    await db.execute(select(func.pg_advisory_xact_lock(access.company_id, func.hashtext('inventory-rbac'))))
    role = None
    old_codes = []
    if role_id is not None:
        role = await db.scalar(select(Role).where(
            Role.company_id == access.company_id,
            Role.id == role_id,
        ).with_for_update())
        if role is None:
            raise HTTPException(404, 'Role not found.')
        if role.is_system_role:
            raise HTTPException(409, 'System roles cannot be edited here.')
        old_codes = list((await db.scalars(select(Permission.code).join(
            role_permissions,
            role_permissions.c.permission_id == Permission.id,
        ).where(
            role_permissions.c.company_id == access.company_id,
            role_permissions.c.role_id == role.id,
        ))).all())

    duplicate = await db.scalar(select(Role.id).where(
        Role.company_id == access.company_id,
        Role.name == name,
        Role.id != role_id if role_id is not None else True,
    ))
    if duplicate is not None:
        raise HTTPException(409, 'Role name is already used in this company.')

    if role is None:
        role = Role(company_id=access.company_id, name=name, is_system_role=False)
        db.add(role)
        await db.flush()
    old_name = role.name
    role.name = name

    # Permission rows are migration-owned. Administration never invents catalog rows.
    await db.execute(delete(role_permissions).where(
        role_permissions.c.company_id == access.company_id,
        role_permissions.c.role_id == role.id,
    ))
    if codes:
        await db.execute(insert(role_permissions), [
            {
                'company_id': access.company_id,
                'role_id': role.id,
                'permission_id': permission_ids[code],
            }
            for code in codes
        ])
    audit(
        db,
        access.company_id,
        legacy_actor.id,
        f'Role_{role.id}',
        'INVENTORY_ROLE_SAVED',
        {'name': old_name, 'permissions': old_codes},
        {'name': name, 'permissions': codes},
    )
    await db.commit()
    return {'id': role.id, 'name': name, 'permissions': codes}


@router.post('/roles', status_code=201)
async def create_role(
    payload: RoleInput,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_require_company_owner),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    return await save_role(payload, db, access, legacy_actor)


@router.put('/roles/{role_id}')
async def update_role(
    role_id: int,
    payload: RoleInput,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_require_company_owner),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    return await save_role(payload, db, access, legacy_actor, role_id)


@router.get('/users')
async def users(
    after_id: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_require_company_owner),
):
    owner = select(1).where(
        CompanyOwner.company_id == access.company_id,
        CompanyOwner.backoffice_user_id == BackofficeUser.id,
    ).exists()
    rows = (await db.execute(select(
        CompanyPrincipal.id.label('principal_id'),
        BackofficeUser.id.label('backoffice_user_id'),
        CompanyPrincipal.full_name,
        CompanyPrincipal.is_active,
        owner.label('is_company_owner'),
    ).select_from(BackofficeUser).join(
        CompanyPrincipal,
        and_(
            CompanyPrincipal.company_id == BackofficeUser.company_id,
            CompanyPrincipal.id == BackofficeUser.principal_id,
        ),
    ).where(
        BackofficeUser.company_id == access.company_id,
        CompanyPrincipal.company_id == access.company_id,
        BackofficeUser.principal_type == PrincipalType.BACKOFFICE.value,
        CompanyPrincipal.principal_type == PrincipalType.BACKOFFICE.value,
        BackofficeUser.id > after_id,
    ).order_by(BackofficeUser.id).limit(limit + 1))).all()
    return {
        'items': [dict(r._mapping) for r in rows[:limit]],
        'next_id': rows[limit - 1].backoffice_user_id if len(rows) > limit else None,
    }


@router.get('/locations')
async def locations(
    after_id: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_require_company_owner),
):
    rows = (await db.execute(select(
        InventoryLocation.id,
        InventoryLocation.name,
        InventoryLocation.code,
        InventoryLocation.location_type,
        InventoryLocation.is_active,
    ).where(
        InventoryLocation.company_id == access.company_id,
        InventoryLocation.id > after_id,
        InventoryLocation.location_type.in_(['WAREHOUSE', 'VEHICLE']),
    ).order_by(InventoryLocation.id).limit(limit + 1))).all()
    return {
        'items': [dict(r._mapping) for r in rows[:limit]],
        'next_id': rows[limit - 1].id if len(rows) > limit else None,
    }


async def target_legacy_grant_driver_id(db, access, backoffice_user_id):
    """Transport wrapper around the bounded canonical-target grant-storage bridge."""
    try:
        return await resolve_target_legacy_grant_driver_id(
            db,
            company_id=access.company_id,
            backoffice_user_id=backoffice_user_id,
        )
    except InventoryAccessTargetNotFound:
        raise HTTPException(404, 'Backoffice target not found.') from None
    except InventoryAccessBridgeRejected:
        raise HTTPException(403, 'Authorization denied.') from None


@router.get('/users/{user_id}/grants')
async def user_grants(
    user_id: int,
    scope: str = Query('location', pattern='^(location|company)$'),
    after_id: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_require_company_owner),
):
    legacy_grant_driver_id = await target_legacy_grant_driver_id(db, access, user_id)
    model = UserRole if scope == 'company' else UserLocationAccess
    rows = (await db.scalars(select(model).where(
        model.company_id == access.company_id,
        model.driver_id == legacy_grant_driver_id,
        model.id > after_id,
    ).order_by(model.id).limit(limit + 1))).all()
    return {
        'items': [
            {
                'id': r.id,
                'role_id': r.role_id,
                'location_id': getattr(r, 'location_id', None),
            }
            for r in rows[:limit]
        ],
        'next_id': rows[limit - 1].id if len(rows) > limit else None,
    }


@router.post('/users/{user_id}/grants', status_code=201)
async def grant(
    user_id: int,
    payload: GrantInput,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_require_company_owner),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    legacy_grant_driver_id = await target_legacy_grant_driver_id(db, access, user_id)
    role = await db.scalar(select(Role).where(
        Role.company_id == access.company_id,
        Role.id == payload.role_id,
    ).with_for_update())
    if role is None:
        raise HTTPException(404, 'Role not found.')

    values = {
        'company_id': access.company_id,
        'driver_id': legacy_grant_driver_id,
        'role_id': role.id,
    }
    if payload.location_id is not None:
        location = await db.scalar(select(InventoryLocation.id).where(
            InventoryLocation.company_id == access.company_id,
            InventoryLocation.id == payload.location_id,
            InventoryLocation.location_type.in_(['WAREHOUSE', 'VEHICLE']),
            InventoryLocation.is_active.is_(True),
        ))
        if location is None:
            raise HTTPException(404, 'Location not found or inactive.')
        values['location_id'] = location

    model = UserRole if payload.location_id is None else UserLocationAccess
    result = await db.scalar(
        insert(model).values(**values).on_conflict_do_nothing().returning(model.id)
    )
    if result is not None:
        audit(
            db,
            access.company_id,
            legacy_actor.id,
            f'BackofficeUser_{user_id}',
            'INVENTORY_GRANT_ADDED',
            None,
            values,
        )
    await db.commit()
    return {'created': result is not None}


@router.delete('/users/{user_id}/grants/{grant_id}')
async def revoke(
    user_id: int,
    grant_id: int,
    scope: str = Query(..., pattern='^(location|company)$'),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_require_company_owner),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    legacy_grant_driver_id = await target_legacy_grant_driver_id(db, access, user_id)
    model = UserRole if scope == 'company' else UserLocationAccess
    row = await db.scalar(select(model).where(
        model.company_id == access.company_id,
        model.driver_id == legacy_grant_driver_id,
        model.id == grant_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(404, 'Grant not found.')
    old = {'role_id': row.role_id, 'location_id': getattr(row, 'location_id', None)}
    await db.delete(row)
    audit(
        db,
        access.company_id,
        legacy_actor.id,
        f'BackofficeUser_{user_id}',
        'INVENTORY_GRANT_REVOKED',
        old,
        None,
    )
    await db.commit()
    return {'revoked': True}
