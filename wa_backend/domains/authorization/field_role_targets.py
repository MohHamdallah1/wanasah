"""Persisted canonical targets for FIELD grant administration."""
from sqlalchemy import and_, select

from domains.identity.models import BackofficeUser, CompanyOwner, CompanyPrincipal, FieldRepresentative
from models import Company, Role
from .backoffice_access import BackofficeCapabilityAccess
from .field_role_policy import FieldRoleError


async def require_owner(db, access: BackofficeCapabilityAccess):
    if not isinstance(access, BackofficeCapabilityAccess) or access.subject.is_company_owner is not True:
        raise FieldRoleError("FIELD_ROLE_OWNER_REQUIRED", 403)
    subject = access.subject
    owner = await db.scalar(select(CompanyOwner.company_id)
        .join(BackofficeUser, and_(BackofficeUser.company_id == CompanyOwner.company_id,
                                  BackofficeUser.id == CompanyOwner.backoffice_user_id))
        .join(CompanyPrincipal, and_(CompanyPrincipal.company_id == BackofficeUser.company_id,
                                    CompanyPrincipal.id == BackofficeUser.principal_id))
        .join(Company, Company.id == CompanyPrincipal.company_id)
        .where(CompanyOwner.company_id == access.company_id,
               BackofficeUser.id == subject.backoffice_user_id,
               CompanyPrincipal.id == subject.principal_id,
               CompanyPrincipal.principal_type == "BACKOFFICE",
               CompanyPrincipal.is_active.is_(True), Company.is_active.is_(True)))
    if owner is None:
        raise FieldRoleError("FIELD_ROLE_OWNER_REQUIRED", 403)


async def require_representative(db, company_id, representative_id, *, lock=False):
    statement = select(FieldRepresentative.id).join(CompanyPrincipal, and_(
        CompanyPrincipal.company_id == FieldRepresentative.company_id,
        CompanyPrincipal.id == FieldRepresentative.principal_id)).where(
        FieldRepresentative.company_id == company_id, FieldRepresentative.id == representative_id,
        FieldRepresentative.principal_type == "FIELD_REPRESENTATIVE",
        CompanyPrincipal.principal_type == "FIELD_REPRESENTATIVE",
        CompanyPrincipal.is_active.is_(True))
    if lock:
        statement = statement.with_for_update(of=(FieldRepresentative, CompanyPrincipal))
    if await db.scalar(statement) is None:
        raise FieldRoleError("FIELD_ROLE_TARGET_NOT_FOUND", 404)


async def require_role(db, company_id, role_id, *, lock=False):
    statement = select(Role).where(Role.company_id == company_id, Role.id == role_id)
    if lock:
        statement = statement.with_for_update()
    role = await db.scalar(statement)
    if role is None:
        raise FieldRoleError("FIELD_ROLE_TARGET_NOT_FOUND", 404)
    return role
