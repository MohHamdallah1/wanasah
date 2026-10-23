"""Persisted FIELD operation grants; operational assignment scope is additional."""
from dataclasses import dataclass

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.context import FieldRequestContext
from domains.identity.models import CompanyPrincipal, FieldRepresentative
from models import Company, Permission, Role, role_permissions
from .capabilities import FIELD_ASSIGNABLE_PERMISSIONS
from .field_models import FieldRepresentativeRole


class FieldCapabilityAccessRejected(Exception):
    pass


@dataclass(frozen=True)
class FieldCapabilityAccess:
    db: AsyncSession
    context: FieldRequestContext

    def __post_init__(self):
        if not isinstance(self.context, FieldRequestContext) or any(
            type(v) is not int or v <= 0 for v in
            (self.context.company_id, self.context.principal_id,
             self.context.representative_id, self.context.auth_revision)
        ):
            raise FieldCapabilityAccessRejected

    @property
    def company_id(self):
        return self.context.company_id

    async def codes(self) -> frozenset[str]:
        c = self.context
        # Reject an entire corrupt/unsafe bundle, not just its forbidden code.
        unsafe_permissions = role_permissions.alias("unsafe_permissions")
        unsafe_catalog = Permission.__table__.alias("unsafe_catalog")
        unsafe = exists(select(1).select_from(unsafe_permissions).join(
            unsafe_catalog, unsafe_catalog.c.id == unsafe_permissions.c.permission_id
        ).where(unsafe_permissions.c.company_id == c.company_id,
                unsafe_permissions.c.role_id == Role.id,
                unsafe_catalog.c.code.not_in(FIELD_ASSIGNABLE_PERMISSIONS)))
        rows = await self.db.scalars(
            select(Permission.code).select_from(FieldRepresentativeRole)
            .join(FieldRepresentative, and_(
                FieldRepresentative.company_id == FieldRepresentativeRole.company_id,
                FieldRepresentative.id == FieldRepresentativeRole.field_representative_id))
            .join(CompanyPrincipal, and_(
                CompanyPrincipal.company_id == FieldRepresentative.company_id,
                CompanyPrincipal.id == FieldRepresentative.principal_id))
            .join(Company, Company.id == CompanyPrincipal.company_id)
            .join(Role, and_(Role.company_id == FieldRepresentativeRole.company_id,
                             Role.id == FieldRepresentativeRole.role_id))
            .join(role_permissions, and_(role_permissions.c.company_id == Role.company_id,
                                         role_permissions.c.role_id == Role.id))
            .join(Permission, Permission.id == role_permissions.c.permission_id)
            .where(FieldRepresentativeRole.company_id == c.company_id,
                   FieldRepresentative.id == c.representative_id,
                   CompanyPrincipal.id == c.principal_id,
                   CompanyPrincipal.principal_type == "FIELD_REPRESENTATIVE",
                   FieldRepresentative.principal_type == "FIELD_REPRESENTATIVE",
                   CompanyPrincipal.auth_revision == c.auth_revision,
                   CompanyPrincipal.is_active.is_(True), Company.is_active.is_(True),
                   Permission.code.in_(FIELD_ASSIGNABLE_PERMISSIONS), ~unsafe)
            .distinct()
        )
        return frozenset(rows.all())

    async def require(self, code: str) -> None:
        await self.require_all((code,))

    async def require_all(self, codes: tuple[str, ...]) -> None:
        if not codes or any(type(c) is not str for c in codes) or not set(codes) <= FIELD_ASSIGNABLE_PERMISSIONS:
            raise ValueError("Unknown FIELD capability")
        if not set(codes) <= await self.codes():
            raise FieldCapabilityAccessRejected
