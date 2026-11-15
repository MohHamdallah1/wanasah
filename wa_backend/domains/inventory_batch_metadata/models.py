"""Immutable before/after audit, tenant-scoped to original supplier source."""
from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKeyConstraint, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from models import Base, utc_now


class BatchMetadataCorrectionEvent(Base):
    __tablename__ = "batch_metadata_correction_events"
    __table_args__ = (
        Index("ix_batch_meta_event_history","company_id","batch_id","id"),
        UniqueConstraint("company_id", "id", name="uq_batch_meta_event_tenant_id"),
        UniqueConstraint("company_id", "request_id", name="uq_batch_meta_event_request"),
        UniqueConstraint("company_id", "batch_id", "revision", name="uq_batch_meta_event_revision"),
        ForeignKeyConstraint(
            ["company_id", "batch_id"], ["product_batches.company_id", "product_batches.id"],
            ondelete="RESTRICT", name="fk_batch_meta_event_batch",
        ),
        ForeignKeyConstraint(
            ["company_id", "location_id"],
            ["inventory_locations.company_id", "inventory_locations.id"],
            ondelete="RESTRICT", name="fk_batch_meta_event_location",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_movement_id"],
            ["inventory_movements.company_id", "inventory_movements.id"],
            ondelete="RESTRICT", name="fk_batch_meta_event_source_movement",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_cost_event_id"],
            ["inventory_cost_events.company_id", "inventory_cost_events.id"],
            ondelete="RESTRICT", name="fk_batch_meta_event_source_cost",
        ),
        ForeignKeyConstraint(
            ["company_id", "actor_principal_id"],
            ["company_principals.company_id", "company_principals.id"],
            ondelete="RESTRICT", name="fk_batch_meta_event_principal",
        ),
    )
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(Integer, nullable=False)
    batch_id = Column(Integer, nullable=False)
    location_id = Column(Integer, nullable=False)
    source_movement_id = Column(Integer, nullable=False)
    source_cost_event_id = Column(BigInteger, nullable=False)
    source_invoice = Column(String(100), nullable=False)
    revision = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    actor_principal_id = Column(Integer, nullable=False)
    actor_username = Column(String(80), nullable=False)
    actor_auth_revision = Column(Integer, nullable=False)
    verified_at = Column(DateTime, nullable=False, default=utc_now)
    reason = Column(Text, nullable=False)
    before_values = Column(JSONB, nullable=False)
    after_values = Column(JSONB, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
