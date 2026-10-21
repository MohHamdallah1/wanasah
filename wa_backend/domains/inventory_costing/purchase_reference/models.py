"""Domain-owned reference state, immutable commands and change evidence.

Core models.py is intentionally untouched. Metadata registration is explicit in
Alembic and the domain router. Canonical principal/profile IDs are independent.
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, Numeric, String, Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from models import Base


def _value_constraints(prefix):
    return (
        CheckConstraint("amount BETWEEN 0 AND 99999999999999.999999", name=prefix + "_amount"),
        CheckConstraint("revision > 0", name=prefix + "_revision"),
        CheckConstraint("factor_numerator > 0 AND factor_numerator < 'Infinity'::numeric AND "
            "factor_denominator > 0 AND factor_denominator < 'Infinity'::numeric", name=prefix + "_ratio"),
        CheckConstraint("currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'", name=prefix + "_currency"),
        CheckConstraint("jsonb_typeof(provenance) = 'object'", name=prefix + "_provenance"),
        CheckConstraint(
            "(source IN ('MANUAL_PRODUCT','PRODUCT_IMPORT') AND source_cost_event_id IS NULL) OR "
            "(source = 'SUPPLIER_INBOUND' AND source_cost_event_id IS NOT NULL)",
            name=prefix + "_source",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_variant_id"],
            ["product_variants.company_id", "product_variants.id"],
            name=prefix + "_variant_fk", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "source_cost_event_id"],
            ["inventory_cost_events.company_id", "inventory_cost_events.id"],
            name=prefix + "_event_fk", ondelete="RESTRICT",
        ),
    )


class PurchaseReferenceCommand(Base):
    __tablename__ = "purchase_cost_reference_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "actor_principal_id"],
            ["company_principals.company_id", "company_principals.id"],
            name="pcrc_principal_fk", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "actor_backoffice_user_id"],
            ["backoffice_users.company_id", "backoffice_users.id"],
            name="pcrc_profile_fk", ondelete="RESTRICT",
        ),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="pcrc_hash"),
        CheckConstraint("operation IN ('MANUAL_PRODUCT_SET','SUPPLIER_INBOUND_SET','PRODUCT_IMPORT_SET')", name="pcrc_operation"),
        CheckConstraint("jsonb_typeof(response_json) = 'object'", name="pcrc_response"),
    )
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), primary_key=True)
    request_id = Column(Uuid(as_uuid=True), primary_key=True)
    operation = Column(String(30), nullable=False)
    actor_principal_id = Column(Integer, nullable=False)
    actor_backoffice_user_id = Column(Integer, nullable=False)
    request_hash = Column(String(64), nullable=False)
    response_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class PurchaseReferenceChange(Base):
    __tablename__ = "purchase_cost_reference_changes"
    __table_args__ = (
        *_value_constraints("pcrh"),
        ForeignKeyConstraint(
            ["company_id", "request_id"],
            ["purchase_cost_reference_commands.company_id", "purchase_cost_reference_commands.request_id"],
            name="pcrh_command_fk", ondelete="RESTRICT",
        ),
    )
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), primary_key=True)
    product_variant_id = Column(Integer, primary_key=True)
    revision = Column(Integer, primary_key=True)
    request_id = Column(Uuid(as_uuid=True), nullable=False)
    before_snapshot = Column(JSONB, nullable=True)
    amount = Column(Numeric(20, 6), nullable=False)
    purchase_uom_id = Column(Integer, ForeignKey("uom.id", ondelete="RESTRICT"), nullable=False)
    base_uom_id = Column(Integer, ForeignKey("uom.id", ondelete="RESTRICT"), nullable=False)
    factor_numerator = Column(Numeric(78, 0), nullable=False)
    factor_denominator = Column(Numeric(78, 0), nullable=False)
    currency_code = Column(String(10), nullable=False)
    source = Column(String(30), nullable=False)
    source_cost_event_id = Column(BigInteger, nullable=True)
    provenance = Column(JSONB, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False)


class PurchaseCostReference(Base):
    __tablename__ = "purchase_cost_references"
    __table_args__ = (
        *_value_constraints("pcr"),
        ForeignKeyConstraint(
            ["company_id", "product_variant_id", "revision"],
            ["purchase_cost_reference_changes.company_id",
             "purchase_cost_reference_changes.product_variant_id",
             "purchase_cost_reference_changes.revision"],
            name="pcr_history_fk", ondelete="RESTRICT", deferrable=True, initially="DEFERRED",
        ),
    )
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), primary_key=True)
    product_variant_id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False)
    amount = Column(Numeric(20, 6), nullable=False)
    purchase_uom_id = Column(Integer, ForeignKey("uom.id", ondelete="RESTRICT"), nullable=False)
    base_uom_id = Column(Integer, ForeignKey("uom.id", ondelete="RESTRICT"), nullable=False)
    factor_numerator = Column(Numeric(78, 0), nullable=False)
    factor_denominator = Column(Numeric(78, 0), nullable=False)
    currency_code = Column(String(10), nullable=False)
    source = Column(String(30), nullable=False)
    source_cost_event_id = Column(BigInteger, nullable=True)
    provenance = Column(JSONB, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False)
