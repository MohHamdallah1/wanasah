"""FIELD assignment/edit policy over the single shared capability catalog."""
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Permission, role_permissions
from .capabilities import FIELD_ASSIGNABLE_PERMISSIONS
from .field_models import FieldRepresentativeRole


class FieldRoleError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


async def role_codes(db: AsyncSession, company_id: int, role_id: int) -> frozenset[str]:
    return frozenset((await db.scalars(select(Permission.code).join(
        role_permissions, role_permissions.c.permission_id == Permission.id
    ).where(role_permissions.c.company_id == company_id,
            role_permissions.c.role_id == role_id))).all())


def require_field_safe(codes):
    if not set(codes) <= FIELD_ASSIGNABLE_PERMISSIONS:
        raise FieldRoleError("FIELD_ROLE_FORBIDDEN_CAPABILITY")


async def guard_field_assigned_role_edit(db, company_id, role_id, codes):
    if set(codes) <= FIELD_ASSIGNABLE_PERMISSIONS:
        return
    assigned = await db.scalar(select(exists().where(
        FieldRepresentativeRole.company_id == company_id,
        FieldRepresentativeRole.role_id == role_id)))
    if assigned:
        raise FieldRoleError("FIELD_ROLE_FORBIDDEN_CAPABILITY")
