"""M01 vehicle responsibility ledger. A custody change never moves inventory."""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKeyConstraint,
    Index, Integer, String, ForeignKey, UniqueConstraint, text,
)
from models import Base, InventoryLocation, utc_now
from domains.identity.models import FieldRepresentative

# Parent composite keys bind a period/epoch to the *actual* vehicle or principal.
Index("uq_inv_location_company_id_vehicle_id",
      InventoryLocation.company_id, InventoryLocation.id, InventoryLocation.vehicle_id,
      unique=True)
Index("uq_field_rep_company_id_principal_id",
      FieldRepresentative.company_id, FieldRepresentative.id, FieldRepresentative.principal_id,
      unique=True)


class VehicleCustodyEpoch(Base):
    __tablename__ = "vehicle_custody_epochs"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_vehicle_custody_tenant_id"),
        UniqueConstraint("company_id", "vehicle_id", "context_revision", name="uq_vehicle_custody_revision"),
        ForeignKeyConstraint(["company_id", "vehicle_id"],
                             ["vehicles.company_id", "vehicles.id"],
                             ondelete="RESTRICT", name="fk_vehicle_custody_tenant_vehicle"),
        ForeignKeyConstraint(["company_id", "vehicle_location_id", "vehicle_id"],
                             ["inventory_locations.company_id", "inventory_locations.id",
                              "inventory_locations.vehicle_id"],
                             ondelete="RESTRICT", name="fk_vehicle_custody_tenant_location_vehicle"),
        ForeignKeyConstraint(["company_id", "custodian_principal_id", "custodian_kind"],
                             ["company_principals.company_id", "company_principals.id",
                              "company_principals.principal_type"],
                             ondelete="RESTRICT", name="fk_vehicle_custody_tenant_principal_type"),
        ForeignKeyConstraint(["company_id", "field_representative_id", "custodian_principal_id"],
                             ["field_representatives.company_id", "field_representatives.id",
                              "field_representatives.principal_id"],
                             ondelete="RESTRICT", name="fk_vehicle_custody_tenant_rep_principal"),
        ForeignKeyConstraint(["company_id", "related_session_id"],
                             ["work_sessions.company_id", "work_sessions.id"],
                             ondelete="RESTRICT", name="fk_vehicle_custody_tenant_session"),
        ForeignKeyConstraint(["company_id", "accepted_by_principal_id"],
                             ["company_principals.company_id", "company_principals.id"],
                             ondelete="RESTRICT", name="fk_vehicle_custody_tenant_acceptor"),
        CheckConstraint("state IN ('ACCEPTED','NEEDS_REVIEW')", name="vehicle_custody_state"),
        CheckConstraint("custodian_kind IN ('BACKOFFICE','FIELD_REPRESENTATIVE','UNCONFIRMED')",
                        name="vehicle_custody_kind"),
        CheckConstraint("context_revision > 0", name="vehicle_custody_revision_positive"),
        CheckConstraint("ended_at IS NULL OR started_at IS NOT NULL AND ended_at >= started_at",
                        name="vehicle_custody_time_order"),
        CheckConstraint(
            "(state = 'NEEDS_REVIEW' AND custodian_kind = 'UNCONFIRMED' "
            "AND custodian_principal_id IS NULL AND field_representative_id IS NULL "
            "AND accepted_by_principal_id IS NULL) OR "
            "(state = 'ACCEPTED' AND custodian_kind IN ('BACKOFFICE','FIELD_REPRESENTATIVE') "
            "AND custodian_principal_id IS NOT NULL AND accepted_by_principal_id IS NOT NULL "
            "AND started_at IS NOT NULL AND request_id IS NOT NULL AND payload_hash IS NOT NULL "
            "AND ((custodian_kind = 'BACKOFFICE' AND field_representative_id IS NULL) OR "
            "(custodian_kind = 'FIELD_REPRESENTATIVE' AND field_representative_id IS NOT NULL)))",
            name="vehicle_custody_acceptance_evidence"),
        Index("uq_vehicle_custody_current", "company_id", "vehicle_id", unique=True,
              postgresql_where=text("ended_at IS NULL")),
        Index("uq_vehicle_custody_request", "company_id", "request_id", unique=True,
              postgresql_where=text("request_id IS NOT NULL")),
        Index("ix_vehicle_custody_session", "company_id", "related_session_id", "id"),
    )
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    vehicle_id = Column(Integer, nullable=False)
    vehicle_location_id = Column(Integer, nullable=False)
    custodian_kind = Column(String(32), nullable=False)
    custodian_principal_id = Column(Integer, nullable=True)
    field_representative_id = Column(Integer, nullable=True)
    related_session_id = Column(Integer, nullable=True)
    accepted_by_principal_id = Column(Integer, nullable=True)
    handoff_reference = Column(String(120), nullable=True)
    state = Column(String(20), nullable=False)
    context_revision = Column(BigInteger, nullable=False)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    reason = Column(String(120), nullable=True)
    evidence_origin = Column(String(24), nullable=False, default="CANONICAL", server_default="CANONICAL")
    request_id = Column(String(64), nullable=True)
    payload_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
