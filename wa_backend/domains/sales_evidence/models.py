from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from models import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SalesLineAdjustment(Base):
    __tablename__ = "sales_line_adjustments"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "id",
            name="uq_sales_line_adjustments_company_id",
        ),
        UniqueConstraint(
            "company_id", "visit_item_id", "sequence",
            name="uq_sales_line_adjustment_sequence",
        ),
        ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_line_adjustment_company",
        ),
        ForeignKeyConstraint(
            ["company_id", "visit_item_id"],
            ["visit_items.company_id", "visit_items.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_adjustment_tenant_line",
        ),
        ForeignKeyConstraint(
            ["company_id", "offer_version_id", "rule_id"],
            [
                "offer_versions.company_id",
                "offer_versions.id",
                "offer_versions.offer_definition_id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_line_adjustment_tenant_offer",
        ),
        CheckConstraint(
            "sequence > 0",
            name="sales_line_adjustment_sequence_positive",
        ),
        CheckConstraint(
            "rule_version > 0",
            name="sales_line_adjustment_rule_version_positive",
        ),
        CheckConstraint(
            "rule_type IN "
            "('PERCENTAGE_DISCOUNT','FIXED_DISCOUNT','BUY_X_GET_Y',"
            "'FREE_GOODS','QUANTITY_TIERS','BUNDLE')",
            name="sales_line_adjustment_rule_type_valid",
        ),
        CheckConstraint(
            "basis_amount >= 0",
            name="sales_line_adjustment_basis_nonnegative",
        ),
        CheckConstraint(
            "adjustment_amount >= 0",
            name="sales_line_adjustment_amount_nonnegative",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata_snapshot) = 'object'",
            name="sales_line_adjustment_metadata_object",
        ),
        Index(
            "ix_sales_line_adjustment_line",
            "company_id", "visit_item_id", "sequence",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    visit_item_id = Column(Integer, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    offer_version_id = Column(Integer, nullable=False)
    rule_type = Column(String(40), nullable=False)
    rule_id = Column(Integer, nullable=False)
    rule_version = Column(Integer, nullable=False)
    basis_amount = Column(Numeric(20, 6), nullable=False)
    adjustment_amount = Column(Numeric(20, 6), nullable=False)
    metadata_snapshot = Column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SalesLineTaxComponent(Base):
    __tablename__ = "sales_line_tax_components"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "id",
            name="uq_sales_line_tax_components_company_id",
        ),
        UniqueConstraint(
            "company_id", "visit_item_id", "sequence",
            name="uq_sales_line_tax_component_sequence",
        ),
        ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_line_tax_component_company",
        ),
        ForeignKeyConstraint(
            ["company_id", "visit_item_id"],
            ["visit_items.company_id", "visit_items.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_tax_component_tenant_line",
        ),
        ForeignKeyConstraint(
            ["company_id", "tax_rule_set_version_id", "tax_rule_set_id"],
            [
                "tax_rule_set_versions.company_id",
                "tax_rule_set_versions.id",
                "tax_rule_set_versions.tax_rule_set_id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_line_tax_component_tenant_rule_version",
        ),
        ForeignKeyConstraint(
            ["company_id", "tax_component_id", "tax_rule_set_version_id"],
            [
                "tax_rule_components.company_id",
                "tax_rule_components.id",
                "tax_rule_components.tax_rule_set_version_id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_line_tax_component_tenant_component",
        ),
        ForeignKeyConstraint(
            ["company_id", "matched_jurisdiction_id"],
            ["tax_jurisdictions.company_id", "tax_jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_tax_component_tenant_jurisdiction",
        ),
        CheckConstraint(
            "sequence > 0",
            name="sales_line_tax_component_sequence_positive",
        ),
        CheckConstraint(
            "tax_revision > 0",
            name="sales_line_tax_component_revision_positive",
        ),
        CheckConstraint(
            "length(trim(component_code)) > 0",
            name="sales_line_tax_component_code_not_blank",
        ),
        CheckConstraint(
            "length(trim(tax_name)) > 0",
            name="sales_line_tax_component_name_not_blank",
        ),
        CheckConstraint(
            "rate >= 0",
            name="sales_line_tax_component_rate_nonnegative",
        ),
        CheckConstraint(
            "basis_mode IN ('TAXABLE_BASE','TAXABLE_BASE_PLUS_PRIOR_TAX')",
            name="sales_line_tax_component_basis_mode_valid",
        ),
        CheckConstraint(
            "taxable_amount >= 0",
            name="sales_line_tax_component_taxable_nonnegative",
        ),
        CheckConstraint(
            "tax_amount >= 0",
            name="sales_line_tax_component_amount_nonnegative",
        ),
        CheckConstraint(
            "jurisdiction_distance IS NULL OR jurisdiction_distance >= 0",
            name="sales_line_tax_component_jurisdiction_distance",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata_snapshot) = 'object'",
            name="sales_line_tax_component_metadata_object",
        ),
        Index(
            "ix_sales_line_tax_component_line",
            "company_id", "visit_item_id", "sequence",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    visit_item_id = Column(Integer, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    tax_rule_set_id = Column(Integer, nullable=False)
    tax_rule_set_version_id = Column(Integer, nullable=False)
    tax_revision = Column(Integer, nullable=False)
    tax_component_id = Column(Integer, nullable=False)
    component_code = Column(String(100), nullable=False)
    tax_name = Column(String(150), nullable=False)
    rate = Column(Numeric(20, 8), nullable=False)
    basis_mode = Column(String(40), nullable=False)
    taxable_amount = Column(Numeric(20, 6), nullable=False)
    tax_amount = Column(Numeric(20, 6), nullable=False)
    reporting_code = Column(String(100), nullable=True)
    matched_jurisdiction_id = Column(Integer, nullable=True)
    jurisdiction_distance = Column(Integer, nullable=True)
    metadata_snapshot = Column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
