from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from models import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SalesReturnDocument(Base):
    __tablename__ = "sales_return_documents"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_sales_return_documents_company_id"),
        UniqueConstraint("company_id", "request_id", name="uq_sales_return_documents_request_id"),
        ForeignKeyConstraint(
            ["company_id"], ["companies.id"],
            ondelete="CASCADE", name="fk_sales_return_document_company",
        ),
        ForeignKeyConstraint(
            ["company_id", "original_visit_id"],
            ["visits.company_id", "visits.id"],
            ondelete="RESTRICT", name="fk_sales_return_document_visit",
        ),
        ForeignKeyConstraint(
            ["company_id", "original_visit_id", "original_sales_revision_id"],
            [
                "sales_visit_revisions.company_id",
                "sales_visit_revisions.visit_id",
                "sales_visit_revisions.id",
            ],
            ondelete="RESTRICT", name="fk_sales_return_document_revision",
        ),
        ForeignKeyConstraint(
            ["company_id", "shop_id"],
            ["shops.company_id", "shops.id"],
            ondelete="RESTRICT", name="fk_sales_return_document_shop",
        ),
        ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT", name="fk_sales_return_document_actor",
        ),
        CheckConstraint("status = 'POSTED'", name="sales_return_document_status_posted"),
        CheckConstraint("credit_amount >= 0", name="sales_return_document_credit_nonnegative"),
        CheckConstraint(
            "char_length(reason) BETWEEN 3 AND 1000",
            name="sales_return_document_reason_length",
        ),
        CheckConstraint(
            "transaction_currency_code ~ '^[A-Z]{3,10}$'",
            name="sales_return_document_currency_shape",
        ),
        CheckConstraint(
            "functional_currency_code ~ '^[A-Z]{3,10}$'",
            name="sales_return_document_functional_currency_shape",
        ),
        Index(
            "ix_sales_return_document_source",
            "company_id", "original_sales_revision_id", "id",
        ),
        Index(
            "ix_sales_return_document_shop",
            "company_id", "shop_id", "id",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    request_id = Column(Uuid(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    original_visit_id = Column(Integer, nullable=False, index=True)
    original_sales_revision_id = Column(Integer, nullable=False, index=True)
    shop_id = Column(Integer, nullable=False, index=True)
    created_by = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="POSTED", server_default="POSTED")
    transaction_currency_code = Column(String(10), nullable=False)
    functional_currency_code = Column(String(10), nullable=False)
    rounding_reversal = Column(
        Numeric(20, 6), nullable=False, default=0, server_default="0.000000"
    )
    credit_amount = Column(Numeric(20, 6), nullable=False)
    evidence_schema_version = Column(
        Integer, nullable=False, default=1, server_default="1"
    )
    posted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SalesReturnLine(Base):
    __tablename__ = "sales_return_lines"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_sales_return_lines_company_id"),
        UniqueConstraint(
            "company_id", "sales_return_id", "original_visit_item_id",
            name="uq_sales_return_line_source_item",
        ),
        ForeignKeyConstraint(
            ["company_id", "sales_return_id"],
            ["sales_return_documents.company_id", "sales_return_documents.id"],
            ondelete="RESTRICT", name="fk_sales_return_line_document",
        ),
        ForeignKeyConstraint(
            ["company_id", "original_visit_item_id"],
            ["visit_items.company_id", "visit_items.id"],
            ondelete="RESTRICT", name="fk_sales_return_line_source_item",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_variant_id"],
            ["product_variants.company_id", "product_variants.id"],
            ondelete="RESTRICT", name="fk_sales_return_line_variant",
        ),
        CheckConstraint("returned_base_quantity > 0", name="sales_return_line_qty_positive"),
        CheckConstraint(
            "gross_reversal >= 0 AND discount_reversal >= 0 "
            "AND post_offer_reversal >= 0 AND taxable_reversal >= 0 "
            "AND tax_reversal >= 0 AND line_total_reversal >= 0 "
            "AND credit_amount >= 0",
            name="sales_return_line_money_nonnegative",
        ),
        CheckConstraint(
            "post_offer_reversal = gross_reversal - discount_reversal",
            name="sales_return_line_offer_reconcile",
        ),
        CheckConstraint(
            "line_total_reversal = taxable_reversal + tax_reversal",
            name="sales_return_line_tax_reconcile",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'",
            name="sales_return_line_snapshot_object",
        ),
        Index(
            "ix_sales_return_line_source",
            "company_id", "original_visit_item_id", "id",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    sales_return_id = Column(Integer, nullable=False, index=True)
    original_visit_item_id = Column(Integer, nullable=False, index=True)
    product_variant_id = Column(Integer, nullable=False, index=True)
    returned_base_quantity = Column(Numeric(20, 6), nullable=False)
    gross_reversal = Column(Numeric(20, 6), nullable=False)
    discount_reversal = Column(Numeric(20, 6), nullable=False)
    post_offer_reversal = Column(Numeric(20, 6), nullable=False)
    taxable_reversal = Column(Numeric(20, 6), nullable=False)
    tax_reversal = Column(Numeric(20, 6), nullable=False)
    line_total_reversal = Column(Numeric(20, 6), nullable=False)
    credit_amount = Column(Numeric(20, 6), nullable=False)
    evidence_snapshot = Column(JSONB, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SalesReturnQuantityComponent(Base):
    __tablename__ = "sales_return_quantity_components"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "id", name="uq_sales_return_quantity_components_company_id"
        ),
        UniqueConstraint(
            "company_id", "sales_return_line_id", "original_price_component_id",
            name="uq_sales_return_quantity_source",
        ),
        ForeignKeyConstraint(
            ["company_id", "sales_return_line_id"],
            ["sales_return_lines.company_id", "sales_return_lines.id"],
            ondelete="RESTRICT", name="fk_sales_return_quantity_line",
        ),
        ForeignKeyConstraint(
            ["company_id", "original_price_component_id"],
            ["sales_line_price_components.company_id", "sales_line_price_components.id"],
            ondelete="RESTRICT", name="fk_sales_return_quantity_source_price",
        ),
        ForeignKeyConstraint(
            ["uom_id"], ["uom.id"],
            ondelete="RESTRICT", name="fk_sales_return_quantity_uom",
        ),
        CheckConstraint("quantity > 0", name="sales_return_quantity_positive"),
        CheckConstraint("base_quantity > 0", name="sales_return_base_quantity_positive"),
        CheckConstraint("gross_reversal >= 0", name="sales_return_quantity_gross_nonnegative"),
        CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'",
            name="sales_return_quantity_snapshot_object",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    sales_return_line_id = Column(Integer, nullable=False, index=True)
    original_price_component_id = Column(Integer, nullable=False, index=True)
    uom_id = Column(Integer, nullable=False)
    quantity = Column(Numeric(20, 6), nullable=False)
    base_quantity = Column(Numeric(20, 6), nullable=False)
    gross_reversal = Column(Numeric(20, 6), nullable=False)
    evidence_snapshot = Column(JSONB, nullable=False)


class SalesReturnAdjustment(Base):
    __tablename__ = "sales_return_adjustments"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "id", name="uq_sales_return_adjustments_company_id"
        ),
        UniqueConstraint(
            "company_id", "sales_return_line_id", "original_adjustment_id",
            name="uq_sales_return_adjustment_source",
        ),
        ForeignKeyConstraint(
            ["company_id", "sales_return_line_id"],
            ["sales_return_lines.company_id", "sales_return_lines.id"],
            ondelete="RESTRICT", name="fk_sales_return_adjustment_line",
        ),
        ForeignKeyConstraint(
            ["company_id", "original_adjustment_id"],
            ["sales_line_adjustments.company_id", "sales_line_adjustments.id"],
            ondelete="RESTRICT", name="fk_sales_return_adjustment_source",
        ),
        ForeignKeyConstraint(
            ["uom_id"], ["uom.id"],
            ondelete="RESTRICT", name="fk_sales_return_adjustment_uom",
        ),
        CheckConstraint(
            "adjustment_reversal >= 0",
            name="sales_return_adjustment_nonnegative",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'",
            name="sales_return_adjustment_snapshot_object",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    sales_return_line_id = Column(Integer, nullable=False, index=True)
    original_adjustment_id = Column(Integer, nullable=False, index=True)
    uom_id = Column(Integer, nullable=False)
    adjustment_reversal = Column(Numeric(20, 6), nullable=False)
    evidence_snapshot = Column(JSONB, nullable=False)


class SalesReturnTaxComponent(Base):
    __tablename__ = "sales_return_tax_components"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "id", name="uq_sales_return_tax_components_company_id"
        ),
        UniqueConstraint(
            "company_id", "sales_return_line_id", "original_tax_component_id",
            name="uq_sales_return_tax_source",
        ),
        ForeignKeyConstraint(
            ["company_id", "sales_return_line_id"],
            ["sales_return_lines.company_id", "sales_return_lines.id"],
            ondelete="RESTRICT", name="fk_sales_return_tax_line",
        ),
        ForeignKeyConstraint(
            ["company_id", "original_tax_component_id"],
            ["sales_line_tax_components.company_id", "sales_line_tax_components.id"],
            ondelete="RESTRICT", name="fk_sales_return_tax_source",
        ),
        CheckConstraint(
            "taxable_reversal >= 0 AND tax_reversal >= 0",
            name="sales_return_tax_nonnegative",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'",
            name="sales_return_tax_snapshot_object",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    sales_return_line_id = Column(Integer, nullable=False, index=True)
    original_tax_component_id = Column(Integer, nullable=False, index=True)
    taxable_reversal = Column(Numeric(20, 6), nullable=False)
    tax_reversal = Column(Numeric(20, 6), nullable=False)
    evidence_snapshot = Column(JSONB, nullable=False)
