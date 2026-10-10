"""Temporary bridge. Target pair correspondence is also verified by the service."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint, text

from models import Base, utc_now
from domains.identity import models as identity_models  # noqa: F401

TABLE = "identity_legacy_driver_map"
TARGETS = {
    "backoffice_principal_id": "company_principals",
    "backoffice_user_id": "backoffice_users",
    "field_principal_id": "company_principals",
    "field_representative_id": "field_representatives",
}
SHAPE = """
    (classification = 'BACKOFFICE_ONLY'
     AND backoffice_principal_id IS NOT NULL AND backoffice_user_id IS NOT NULL
     AND field_principal_id IS NULL AND field_representative_id IS NULL)
 OR (classification = 'FIELD_ONLY'
     AND backoffice_principal_id IS NULL AND backoffice_user_id IS NULL
     AND field_principal_id IS NOT NULL AND field_representative_id IS NOT NULL)
 OR (classification = 'DUAL_SPLIT'
     AND backoffice_principal_id IS NOT NULL AND backoffice_user_id IS NOT NULL
     AND field_principal_id IS NOT NULL AND field_representative_id IS NOT NULL
     AND backoffice_principal_id <> field_principal_id)
"""


class IdentityLegacyDriverMap(Base):
    __tablename__ = TABLE
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "legacy_driver_id"], ["drivers.company_id", "drivers.id"],
                             name="fk_identity_legacy_map_tenant_driver", ondelete="RESTRICT", onupdate="RESTRICT"),
        *[ForeignKeyConstraint(["company_id", column], [f"{target}.company_id", f"{target}.id"],
                               name=f"fk_identity_legacy_map_{column}", ondelete="RESTRICT", onupdate="RESTRICT")
          for column, target in TARGETS.items()],
        *[UniqueConstraint("company_id", column, name=f"uq_identity_legacy_map_{column}") for column in TARGETS],
        CheckConstraint(SHAPE, name="classification_targets"),
    )
    company_id = Column(Integer, primary_key=True, autoincrement=False)
    legacy_driver_id = Column(Integer, primary_key=True, autoincrement=False)
    classification = Column(String(32), nullable=False)
    backoffice_principal_id = Column(Integer, nullable=True)
    backoffice_user_id = Column(Integer, nullable=True)
    field_principal_id = Column(Integer, nullable=True)
    field_representative_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
