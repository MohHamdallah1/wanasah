"""FIELD role assignments in the shared authorization catalog.

The subject is a canonical FieldRepresentative, never an operational Driver.
No permission resolution, HTTP admission or grant-management API lives here.
"""
from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, text

from models import Base, utc_now
from domains.identity import models as identity_models  # noqa: F401


class FieldRepresentativeRole(Base):
    __tablename__ = "field_representative_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "field_representative_id"],
            ["field_representatives.company_id", "field_representatives.id"],
            name="fk_field_roles_tenant_representative", ondelete="RESTRICT", onupdate="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "role_id"], ["roles.company_id", "roles.id"],
            name="fk_field_roles_tenant_role", ondelete="RESTRICT", onupdate="RESTRICT",
        ),
        Index("ix_field_roles_company_role", "company_id", "role_id"),
    )

    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"),
                        primary_key=True, autoincrement=False)
    field_representative_id = Column(Integer, primary_key=True, autoincrement=False)
    role_id = Column(Integer, primary_key=True, autoincrement=False)
    created_at = Column(DateTime, nullable=False, default=utc_now,
                        server_default=text("CURRENT_TIMESTAMP"))
