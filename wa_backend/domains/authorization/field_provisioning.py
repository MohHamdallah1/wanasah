"""Atomic limited default provisioning, called ONLY for genuinely new profiles."""
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from models import Permission, Role, role_permissions
from .capabilities import FIELD_ASSIGNABLE_PERMISSIONS
from .field_models import FieldRepresentativeRole
from .field_role_policy import FieldRoleError, role_codes

FIELD_SYSTEM_KEY = "FIELD_REPRESENTATIVE_V1"


async def ensure_field_default_role(db, company_id: int) -> int:
    # Serialize first provision per company without adopting a human role name.
    await db.execute(select(func.pg_advisory_xact_lock(company_id, func.hashtext("field-default-role"))))
    role = await db.scalar(select(Role).where(Role.company_id == company_id,
                                             Role.system_key == FIELD_SYSTEM_KEY))
    if role is not None:
        if role.is_system_role is not True or await role_codes(db, company_id, role.id) != FIELD_ASSIGNABLE_PERMISSIONS:
            raise FieldRoleError("FIELD_DEFAULT_ROLE_INVALID", 503)
        return role.id
    permissions = (await db.execute(select(Permission.id, Permission.code).where(
        Permission.code.in_(FIELD_ASSIGNABLE_PERMISSIONS)))).all()
    if {p.code for p in permissions} != FIELD_ASSIGNABLE_PERMISSIONS:
        raise FieldRoleError("FIELD_PERMISSION_CATALOG_INCOMPLETE", 503)
    if await db.scalar(select(Role.id).where(Role.company_id == company_id, Role.name == FIELD_SYSTEM_KEY)):
        raise FieldRoleError("FIELD_DEFAULT_ROLE_NAME_CONFLICT")
    role = Role(company_id=company_id, name=FIELD_SYSTEM_KEY, is_system_role=True, system_key=FIELD_SYSTEM_KEY)
    db.add(role)
    await db.flush()
    await db.execute(insert(role_permissions), [
        {"company_id":company_id, "role_id":role.id, "permission_id":p.id} for p in permissions])
    return role.id


async def assign_new_representative_default(db, company_id: int, representative_id: int):
    # No discovery/backfill of old profiles, no invocation from replay/update/login.
    role_id = await ensure_field_default_role(db, company_id)
    await db.execute(insert(FieldRepresentativeRole).values(
        company_id=company_id, field_representative_id=representative_id, role_id=role_id))
