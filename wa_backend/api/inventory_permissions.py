"""Inventory capability contract and tenant-admin grant management."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, delete, func, and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from api.dependencies import get_current_driver, get_current_admin
from inventory_access import InventoryAccess, PERMISSIONS, COMPANY_ONLY
from models import (Driver, Role, Permission, UserRole, UserLocationAccess,
                    role_permissions, InventoryLocation, SystemAuditLog)

router = APIRouter(prefix='/inventory/access', tags=['Inventory Permissions'])


class RoleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(max_length=len(PERMISSIONS))


class GrantInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role_id: int = Field(gt=0)
    location_id: int | None = Field(default=None, gt=0)


def audit(db, actor, target, action, old, new):
    import json
    db.add(SystemAuditLog(company_id=actor.company_id, admin_id=actor.id,
                          target_id=target, action_type=action,
                          old_value=json.dumps(old, ensure_ascii=False),
                          new_value=json.dumps(new, ensure_ascii=False)))


@router.get('/me')
async def capabilities(location_id: int | None = Query(None, gt=0),
                       db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    access = InventoryAccess(db, actor)
    await access.require(PERMISSIONS, any_location=True)
    if location_id is not None:
        await access.require(PERMISSIONS, location_id)
    return {'company_id': actor.company_id, 'driver_id': actor.id,
            'is_company_admin': actor.is_admin, 'location_id': location_id,
            'permissions': await access.codes(),
            'any_permissions': await access.codes(any_location=True),
            'location_permissions': await access.codes(location_id) if location_id is not None else []}


class LocationCapabilitiesInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    location_ids: list[int] = Field(min_length=1, max_length=100)


@router.post('/locations/capabilities')
async def location_capabilities(payload: LocationCapabilitiesInput,
        db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    if any(type(value) is not int or not 0 < value <= 2147483647 for value in payload.location_ids):
        raise HTTPException(422, 'معرف الموقع غير صالح.')
    access = InventoryAccess(db, actor)
    await access.require(PERMISSIONS, any_location=True)
    return {'locations': await access.codes_by_location(payload.location_ids)}


@router.get('/catalog')
async def permission_catalog(actor: Driver = Depends(get_current_admin)):
    return {'permissions': sorted(PERMISSIONS), 'company_only': sorted(COMPANY_ONLY)}


@router.get('/roles')
async def roles(after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
    rows = (await db.scalars(select(Role).where(Role.company_id == actor.company_id,
        Role.id > after_id).order_by(Role.id).limit(limit + 1))).all()
    page = rows[:limit]
    by_role = {r.id: [] for r in page}
    if page:
        grants = (await db.execute(select(role_permissions.c.role_id, Permission.code).join(
            Permission, Permission.id == role_permissions.c.permission_id).where(
            role_permissions.c.company_id == actor.company_id,
            role_permissions.c.role_id.in_(by_role)).order_by(Permission.code))).all()
        for role_id, code in grants:
            by_role[role_id].append(code)
    return {'items': [{'id': r.id, 'name': r.name, 'permissions': by_role[r.id],
                       'is_system_role': r.is_system_role} for r in page],
            'next_id': page[-1].id if len(rows) > limit else None}


async def save_role(payload, db, actor, role_id=None):
    name = payload.name.strip()
    codes = sorted(set(payload.permissions))
    if not name or not set(codes) <= PERMISSIONS:
        raise HTTPException(422, 'اسم الدور أو أكواد الصلاحيات غير صالحة.')
    # Serialize role management within a tenant (including a new role's name).
    await db.execute(select(func.pg_advisory_xact_lock(actor.company_id, func.hashtext('inventory-rbac'))))
    role = None
    old_codes = []
    if role_id is not None:
        role = await db.scalar(select(Role).where(Role.company_id == actor.company_id,
            Role.id == role_id).with_for_update())
        if role is None:
            raise HTTPException(404, 'الدور غير موجود.')
        if role.is_system_role:
            raise HTTPException(409, 'الدور النظامي غير قابل للتعديل من هذه الشاشة.')
        old_codes = list((await db.scalars(select(Permission.code).join(role_permissions,
            role_permissions.c.permission_id == Permission.id).where(
            role_permissions.c.company_id == actor.company_id,
            role_permissions.c.role_id == role.id))).all())
    duplicate = await db.scalar(select(Role.id).where(Role.company_id == actor.company_id,
        Role.name == name, Role.id != role_id if role_id is not None else True))
    if duplicate is not None:
        raise HTTPException(409, 'اسم الدور مستخدم داخل الشركة.')
    if role is None:
        role = Role(company_id=actor.company_id, name=name, is_system_role=False)
        db.add(role)
        await db.flush()
    old_name = role.name
    role.name = name
    if codes:
        await db.execute(insert(Permission).values([{'code': c} for c in codes]).on_conflict_do_nothing(index_elements=['code']))
    await db.execute(delete(role_permissions).where(role_permissions.c.company_id == actor.company_id,
                                                   role_permissions.c.role_id == role.id))
    if codes:
        ids = (await db.scalars(select(Permission.id).where(Permission.code.in_(codes)))).all()
        await db.execute(insert(role_permissions), [{'company_id': actor.company_id,
            'role_id': role.id, 'permission_id': pid} for pid in ids])
    audit(db, actor, f'Role_{role.id}', 'INVENTORY_ROLE_SAVED',
          {'name': old_name, 'permissions': old_codes}, {'name': name, 'permissions': codes})
    await db.commit()
    return {'id': role.id, 'name': name, 'permissions': codes}


@router.post('/roles', status_code=201)
async def create_role(payload: RoleInput, db: AsyncSession = Depends(get_db),
                      actor: Driver = Depends(get_current_admin)):
    return await save_role(payload, db, actor)


@router.put('/roles/{role_id}')
async def update_role(role_id: int, payload: RoleInput, db: AsyncSession = Depends(get_db),
                      actor: Driver = Depends(get_current_admin)):
    return await save_role(payload, db, actor, role_id)


@router.get('/users')
async def users(after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
    rows = (await db.execute(select(Driver.id, Driver.full_name, Driver.is_active, Driver.is_admin).where(
        Driver.company_id == actor.company_id, Driver.id > after_id).order_by(Driver.id).limit(limit + 1))).all()
    return {'items': [dict(r._mapping) for r in rows[:limit]],
            'next_id': rows[limit-1].id if len(rows) > limit else None}


@router.get('/locations')
async def locations(after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                    db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
    rows = (await db.execute(select(InventoryLocation.id, InventoryLocation.name, InventoryLocation.code,
        InventoryLocation.location_type, InventoryLocation.is_active).where(
        InventoryLocation.company_id == actor.company_id, InventoryLocation.id > after_id,
        InventoryLocation.location_type.in_(['WAREHOUSE', 'VEHICLE'])).order_by(InventoryLocation.id).limit(limit+1))).all()
    return {'items': [dict(r._mapping) for r in rows[:limit]],
            'next_id': rows[limit-1].id if len(rows) > limit else None}


async def user_exists(db, actor, user_id):
    if await db.scalar(select(Driver.id).where(Driver.company_id == actor.company_id, Driver.id == user_id)) is None:
        raise HTTPException(404, 'المستخدم غير موجود.')


@router.get('/users/{user_id}/grants')
async def user_grants(user_id: int, scope: str = Query('location', pattern='^(location|company)$'),
                      after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                      db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
    await user_exists(db, actor, user_id)
    model = UserRole if scope == 'company' else UserLocationAccess
    rows = (await db.scalars(select(model).where(model.company_id == actor.company_id,
        model.driver_id == user_id, model.id > after_id).order_by(model.id).limit(limit+1))).all()
    return {'items': [{'id': r.id, 'role_id': r.role_id, 'location_id': getattr(r, 'location_id', None)} for r in rows[:limit]],
            'next_id': rows[limit-1].id if len(rows) > limit else None}


@router.post('/users/{user_id}/grants', status_code=201)
async def grant(user_id: int, payload: GrantInput, db: AsyncSession = Depends(get_db),
                actor: Driver = Depends(get_current_admin)):
    await user_exists(db, actor, user_id)
    role = await db.scalar(select(Role).where(Role.company_id == actor.company_id, Role.id == payload.role_id).with_for_update())
    if role is None:
        raise HTTPException(404, 'الدور غير موجود.')
    values = {'company_id': actor.company_id, 'driver_id': user_id, 'role_id': role.id}
    if payload.location_id is not None:
        location = await db.scalar(select(InventoryLocation.id).where(
            InventoryLocation.company_id == actor.company_id, InventoryLocation.id == payload.location_id,
            InventoryLocation.location_type.in_(['WAREHOUSE', 'VEHICLE']), InventoryLocation.is_active.is_(True)))
        if location is None:
            raise HTTPException(404, 'الموقع غير موجود أو غير فعال.')
        values['location_id'] = location
    model = UserRole if payload.location_id is None else UserLocationAccess
    result = await db.scalar(insert(model).values(**values).on_conflict_do_nothing().returning(model.id))
    if result is not None:
        audit(db, actor, f'Driver_{user_id}', 'INVENTORY_GRANT_ADDED', None, values)
    await db.commit()
    return {'created': result is not None}


@router.delete('/users/{user_id}/grants/{grant_id}')
async def revoke(user_id: int, grant_id: int, scope: str = Query(..., pattern='^(location|company)$'),
                 db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_admin)):
    await user_exists(db, actor, user_id)
    model = UserRole if scope == 'company' else UserLocationAccess
    row = await db.scalar(select(model).where(model.company_id == actor.company_id,
        model.driver_id == user_id, model.id == grant_id).with_for_update())
    if row is None:
        raise HTTPException(404, 'المنح غير موجود.')
    old = {'role_id': row.role_id, 'location_id': getattr(row, 'location_id', None)}
    await db.delete(row)
    audit(db, actor, f'Driver_{user_id}', 'INVENTORY_GRANT_REVOKED', old, None)
    await db.commit()
    return {'revoked': True}
