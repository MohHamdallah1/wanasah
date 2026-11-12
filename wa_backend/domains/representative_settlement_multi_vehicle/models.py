"""M04-owned immutable signed receipts, separate from live InventoryBalance.

Mapping only until the ordered M04 Alembic revision follows merged M02/M03.
Do not create these tables with metadata.create_all or import them into the
application's global metadata before that migration is ready.
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKeyConstraint, Index,
    Integer, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from models import Base, utc_now


class VehicleCustodyCheckpoint(Base):
    __tablename__ = "representative_vehicle_custody_checkpoints"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_m04_checkpoint_tenant_id"),
        UniqueConstraint("company_id", "id", "work_session_id", name="uq_m04_checkpoint_session_id"),
        UniqueConstraint("company_id", "work_session_id", "vehicle_location_id",
                         name="uq_m04_checkpoint_session_location"),
        UniqueConstraint("company_id", "request_id", name="uq_m04_checkpoint_request"),
        ForeignKeyConstraint(["company_id", "work_session_id"],
                             ["work_sessions.company_id", "work_sessions.id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_session"),
        ForeignKeyConstraint(["company_id", "vehicle_location_id", "vehicle_id"],
                             ["inventory_locations.company_id", "inventory_locations.id",
                              "inventory_locations.vehicle_id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_vehicle_location"),
        ForeignKeyConstraint(["company_id", "signed_by_principal_id"],
                             ["company_principals.company_id", "company_principals.id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_signer"),
        ForeignKeyConstraint(["company_id", "latest_epoch_id"],
                             ["vehicle_custody_epochs.company_id", "vehicle_custody_epochs.id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_latest_epoch"),
        ForeignKeyConstraint(["company_id", "destination_location_id"],
                             ["inventory_locations.company_id", "inventory_locations.id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_destination"),
        ForeignKeyConstraint(["company_id", "stocktake_session_id", "vehicle_location_id"],
                             ["stocktake_sessions.company_id", "stocktake_sessions.id",
                              "stocktake_sessions.location_id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_recon_location"),
        CheckConstraint("mode IN ('COUNT_IN_PLACE','PHYSICAL_HANDOFF')", name="m04_checkpoint_mode"),
        CheckConstraint("(mode = 'COUNT_IN_PLACE' AND destination_location_id IS NULL) OR "
                        "(mode = 'PHYSICAL_HANDOFF' AND destination_location_id IS NOT NULL "
                        "AND destination_location_id <> vehicle_location_id)", name="m04_checkpoint_destination"),
        CheckConstraint("movement_watermark >= 0 AND final_movement_watermark >= movement_watermark",
                        name="m04_checkpoint_watermark"),
        CheckConstraint("latest_epoch_revision > 0", name="m04_checkpoint_epoch_positive"),
        CheckConstraint("mode <> 'COUNT_IN_PLACE' OR movement_watermark = final_movement_watermark",
                        name="m04_checkpoint_no_transfer"),
        CheckConstraint("length(snapshot_token) = 64 AND length(payload_hash) = 64 "
                        "AND length(context_digest) = 64", name="m04_checkpoint_hashes"),
        Index("ix_m04_checkpoint_session", "company_id", "work_session_id", "id"),
    )
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(Integer, nullable=False)
    work_session_id = Column(Integer, nullable=False)
    vehicle_id = Column(Integer, nullable=False)
    vehicle_location_id = Column(Integer, nullable=False)
    mode = Column(String(24), nullable=False)
    destination_location_id = Column(Integer)
    signed_by_principal_id = Column(Integer, nullable=False)
    signed_at = Column(DateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    request_id = Column(String(36), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    snapshot_token = Column(String(64), nullable=False)
    context_digest = Column(String(64), nullable=False)
    latest_epoch_id = Column(BigInteger, nullable=False)
    latest_epoch_revision = Column(BigInteger, nullable=False)
    movement_watermark = Column(BigInteger, nullable=False)
    final_movement_watermark = Column(BigInteger, nullable=False)
    stocktake_session_id = Column(Integer)
    # Frozen period/revision + epoch/revision manifest, never a live projection.
    context_manifest = Column(JSONB, nullable=False)
    notes = Column(Text)


class VehicleCustodyCheckpointEpoch(Base):
    __tablename__ = "representative_vehicle_custody_checkpoint_epochs"
    __table_args__ = (
        UniqueConstraint("company_id", "work_session_id", "epoch_id", name="uq_m04_checkpoint_epoch_once"),
        ForeignKeyConstraint(["company_id", "checkpoint_id", "work_session_id"],
                             ["representative_vehicle_custody_checkpoints.company_id",
                              "representative_vehicle_custody_checkpoints.id",
                              "representative_vehicle_custody_checkpoints.work_session_id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_epoch_receipt"),
        ForeignKeyConstraint(["company_id", "epoch_id"],
                             ["vehicle_custody_epochs.company_id", "vehicle_custody_epochs.id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_epoch_tenant"),
    )
    company_id = Column(Integer, primary_key=True)
    checkpoint_id = Column(BigInteger, primary_key=True)
    epoch_id = Column(BigInteger, primary_key=True)
    work_session_id = Column(Integer, nullable=False)


class VehicleCustodyCheckpointLine(Base):
    __tablename__ = "representative_vehicle_custody_checkpoint_lines"
    __table_args__ = (
        ForeignKeyConstraint(["company_id", "checkpoint_id"],
                             ["representative_vehicle_custody_checkpoints.company_id",
                              "representative_vehicle_custody_checkpoints.id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_line_receipt"),
        ForeignKeyConstraint(["company_id", "product_variant_id", "batch_id"],
                             ["product_batches.company_id", "product_batches.product_variant_id",
                              "product_batches.id"],
                             ondelete="RESTRICT", name="fk_m04_checkpoint_line_batch"),
        CheckConstraint("expected_quantity >= 0 AND actual_quantity >= 0 "
                        "AND expected_quantity = actual_quantity", name="m04_checkpoint_line_reconciled"),
        CheckConstraint("stock_status IN ('AVAILABLE','QUARANTINED','BLOCKED','RECALLED',"
                        "'DAMAGED','DISPOSAL_PENDING')", name="m04_checkpoint_line_status"),
    )
    company_id = Column(Integer, primary_key=True)
    checkpoint_id = Column(BigInteger, primary_key=True)
    product_variant_id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, primary_key=True)
    stock_status = Column(String(50), primary_key=True)
    expected_quantity = Column(Numeric(20, 6), nullable=False)
    actual_quantity = Column(Numeric(20, 6), nullable=False)
