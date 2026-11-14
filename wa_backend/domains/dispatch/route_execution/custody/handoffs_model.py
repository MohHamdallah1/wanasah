"""Append-only request history with a single live (pending/confirmed) vehicle offer."""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    Index, Integer, String, UniqueConstraint, text,
)
from models import Base, utc_now


class VehicleCustodyHandoff(Base):
    __tablename__ = "vehicle_custody_handoffs"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_custody_handoff_tenant_id"),
        UniqueConstraint("company_id", "request_id", name="uq_custody_handoff_create_uuid"),
        UniqueConstraint("company_id", "decision_request_id", name="uq_custody_handoff_decision_uuid"),
        UniqueConstraint("company_id", "cancel_request_id", name="uq_custody_handoff_cancel_uuid"),
        UniqueConstraint("company_id", "approve_request_id", name="uq_custody_handoff_approve_uuid"),
        ForeignKeyConstraint(["company_id", "vehicle_id"], ["vehicles.company_id", "vehicles.id"],
                             ondelete="RESTRICT", name="fk_custody_handoff_vehicle"),
        ForeignKeyConstraint(["company_id", "vehicle_location_id", "vehicle_id"],
                             ["inventory_locations.company_id", "inventory_locations.id", "inventory_locations.vehicle_id"],
                             ondelete="RESTRICT", name="fk_custody_handoff_vehicle_location"),
        ForeignKeyConstraint(["company_id", "manager_principal_id"], ["company_principals.company_id", "company_principals.id"],
                             ondelete="RESTRICT", name="fk_custody_handoff_manager"),
        ForeignKeyConstraint(["company_id", "recipient_principal_id"], ["company_principals.company_id", "company_principals.id"],
                             ondelete="RESTRICT", name="fk_custody_handoff_recipient"),
        ForeignKeyConstraint(["company_id", "recipient_rep_id", "recipient_principal_id"],
                             ["field_representatives.company_id", "field_representatives.id", "field_representatives.principal_id"],
                             ondelete="RESTRICT", name="fk_custody_handoff_rep"),
        ForeignKeyConstraint(["company_id", "prior_epoch_id"], ["vehicle_custody_epochs.company_id", "vehicle_custody_epochs.id"],
                             ondelete="RESTRICT", name="fk_custody_handoff_prior_epoch"),
        ForeignKeyConstraint(["company_id", "accepted_epoch_id"], ["vehicle_custody_epochs.company_id", "vehicle_custody_epochs.id"],
                             ondelete="RESTRICT", name="fk_custody_handoff_accepted_epoch"),
        CheckConstraint("state IN ('PENDING','CONFIRMED','DECLINED','CANCELLED','EXPIRED','COMMITTED')",
                        name="custody_handoff_state_valid"),
        CheckConstraint("mode IN ('FIRST_ACCEPT','REASSIGN')", name="custody_handoff_mode_valid"),
        CheckConstraint("expected_context_revision >= 0 AND offer_issued_at > 0", name="custody_handoff_revision_valid"),
        CheckConstraint("(confirmed_at IS NULL AND confirmed_auth_revision IS NULL OR confirmed_at IS NOT NULL AND confirmed_auth_revision IS NOT NULL) AND (state NOT IN ('CONFIRMED','COMMITTED') OR confirmed_at IS NOT NULL)",
                        name="custody_handoff_confirmation_valid"),
        CheckConstraint("(state = 'COMMITTED') = (accepted_epoch_id IS NOT NULL AND approve_request_id IS NOT NULL)",
                        name="custody_handoff_commit_valid"),
        Index("uq_custody_handoff_live_vehicle", "company_id", "vehicle_id", unique=True,
              postgresql_where=text("state IN ('PENDING','CONFIRMED')")),
        Index("ix_custody_handoff_latest_vehicle", "company_id", "vehicle_id", "id"),
        Index("ix_custody_handoff_recipient", "company_id", "recipient_principal_id", "state", "expires_at", "id"),
    )
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    vehicle_id = Column(Integer, nullable=False)
    vehicle_location_id = Column(Integer, nullable=False)
    manager_principal_id = Column(Integer, nullable=False)
    target_driver_id = Column(Integer, nullable=False)
    recipient_rep_id = Column(Integer, nullable=False)
    recipient_principal_id = Column(Integer, nullable=False)
    prior_epoch_id = Column(BigInteger, nullable=True)
    mode = Column(String(16), nullable=False)
    expected_context_revision = Column(BigInteger, nullable=False)
    expected_stock_snapshot = Column(String(64), nullable=False)
    request_id = Column(String(36), nullable=False)
    request_hash = Column(String(64), nullable=False)
    offer_issued_at = Column(BigInteger, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    state = Column(String(16), nullable=False)
    decision_request_id = Column(String(36), nullable=True)
    decision_hash = Column(String(64), nullable=True)
    confirmed_at = Column(BigInteger, nullable=True)
    confirmed_auth_revision = Column(Integer, nullable=True)
    decline_reason_code = Column(String(32), nullable=True)
    decline_reason_text = Column(String(300), nullable=True)
    cancel_request_id = Column(String(36), nullable=True)
    approve_request_id = Column(String(36), nullable=True)
    accepted_epoch_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
