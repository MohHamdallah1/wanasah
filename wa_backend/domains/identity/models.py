"""Additive company credentials, independent profiles and protected ownership.

No legacy identity is read or backfilled here. Profile type is enforced by a
fixed discriminator plus a tenant/type composite FK, including parent updates.
The profiles each have their own sequence-backed primary key.
"""
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, Numeric, String, UniqueConstraint, text,
)

from models import Base, utc_now
from .types import PrincipalType


class CompanyPrincipal(Base):
    __tablename__ = "company_principals"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_company_principals_company_id"),
        UniqueConstraint("company_id", "username", name="uq_company_principals_company_username"),
        UniqueConstraint("company_id", "id", "principal_type", name="uq_company_principals_company_id_type"),
        CheckConstraint("principal_type IN ('BACKOFFICE', 'FIELD_REPRESENTATIVE')", name="principal_type"),
        CheckConstraint("auth_revision > 0", name="auth_revision_positive"),
        Index("ix_company_principals_tenant_type_active_id", "company_id", "principal_type", "is_active", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    username = Column(String(80), nullable=False)
    password_hash = Column(String(128), nullable=False)
    full_name = Column(String(120), nullable=False)
    phone_number = Column(String(20), nullable=True)
    principal_type = Column(String(32), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    auth_revision = Column(Integer, nullable=False, default=1, server_default=text("1"))
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))


class BackofficeUser(Base):
    __tablename__ = "backoffice_users"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_backoffice_users_company_id"),
        UniqueConstraint("company_id", "principal_id", name="uq_backoffice_users_tenant_principal"),
        ForeignKeyConstraint(
            ["company_id", "principal_id", "principal_type"],
            ["company_principals.company_id", "company_principals.id", "company_principals.principal_type"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_backoffice_users_tenant_principal_type",
        ),
        CheckConstraint("principal_type = 'BACKOFFICE'", name="principal_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    principal_id = Column(Integer, nullable=False)
    principal_type = Column(String(32), nullable=False, default=PrincipalType.BACKOFFICE.value, server_default=text("'BACKOFFICE'"))
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))


class FieldRepresentative(Base):
    __tablename__ = "field_representatives"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_field_representatives_company_id"),
        UniqueConstraint("company_id", "principal_id", name="uq_field_representatives_tenant_principal"),
        ForeignKeyConstraint(
            ["company_id", "principal_id", "principal_type"],
            ["company_principals.company_id", "company_principals.id", "company_principals.principal_type"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_field_representatives_tenant_principal_type",
        ),
        CheckConstraint("principal_type = 'FIELD_REPRESENTATIVE'", name="principal_type"),
        CheckConstraint("max_debt_limit >= 0", name="max_debt_limit_nonnegative"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    principal_id = Column(Integer, nullable=False)
    principal_type = Column(String(32), nullable=False, default=PrincipalType.FIELD_REPRESENTATIVE.value, server_default=text("'FIELD_REPRESENTATIVE'"))
    can_allow_debt = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    max_debt_limit = Column(Numeric(12, 3), nullable=False, default=Decimal("0.000"), server_default=text("0.000"))
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))


class CompanyOwner(Base):
    """One system-managed owner slot per company, linked to Backoffice identity.

    Expand deliberately creates no owner rows. The later approved provisioning/
    preflight must populate the slot; presence is a cutover acceptance invariant.
    Ownership transfer is not implemented by this persistence foundation.
    """
    __tablename__ = "company_owners"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "backoffice_user_id"],
            ["backoffice_users.company_id", "backoffice_users.id"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_company_owners_tenant_backoffice",
        ),
    )

    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), primary_key=True, autoincrement=False)
    backoffice_user_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))
