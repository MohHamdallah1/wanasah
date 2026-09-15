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


class SalesLinePriceComponent(Base):
    __tablename__ = "sales_line_price_components"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "id",
            name="uq_sales_line_price_components_company_id",
        ),
        UniqueConstraint(
            "company_id",
            "visit_item_id",
            "sequence",
            name="uq_sales_line_price_component_sequence",
        ),
        UniqueConstraint(
            "company_id",
            "visit_item_id",
            "uom_id",
            name="uq_sales_line_price_component_uom",
        ),
        ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_line_price_component_company",
        ),
        ForeignKeyConstraint(
            ["company_id", "visit_item_id"],
            ["visit_items.company_id", "visit_items.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_price_component_tenant_line",
        ),
        ForeignKeyConstraint(
            ["company_id", "price_entry_id"],
            ["price_book_entries.company_id", "price_book_entries.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_price_component_tenant_price_entry",
        ),
        ForeignKeyConstraint(
            ["uom_id"],
            ["uom.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_price_component_uom",
        ),
        CheckConstraint(
            "sequence > 0",
            name="sales_line_price_component_sequence_positive",
        ),
        CheckConstraint(
            "quantity > 0",
            name="sales_line_price_component_quantity_positive",
        ),
        CheckConstraint(
            "base_quantity > 0",
            name="sales_line_price_component_base_quantity_positive",
        ),
        CheckConstraint(
            "price_publication_revision > 0",
            name="sales_line_price_component_publication_revision_positive",
        ),
        CheckConstraint(
            "assignment_revision > 0",
            name="sales_line_price_component_assignment_revision_positive",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="sales_line_price_component_unit_price_nonnegative",
        ),
        CheckConstraint(
            "gross_amount >= 0",
            name="sales_line_price_component_gross_nonnegative",
        ),
        CheckConstraint(
            "gross_amount = round(quantity * unit_price, 6)",
            name="sales_line_price_component_gross_exact",
        ),
        Index(
            "ix_sales_line_price_component_line",
            "company_id",
            "visit_item_id",
            "sequence",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    visit_item_id = Column(Integer, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    uom_id = Column(Integer, nullable=False)
    quantity = Column(Numeric(20, 6), nullable=False)
    base_quantity = Column(Numeric(20, 6), nullable=False)
    price_entry_id = Column(Integer, nullable=False)
    price_publication_revision = Column(Integer, nullable=False)
    assignment_revision = Column(Integer, nullable=False)
    unit_price = Column(Numeric(20, 6), nullable=False)
    gross_amount = Column(Numeric(20, 6), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SalesVisitRevision(Base):
    __tablename__ = "sales_visit_revisions"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "id",
            name="uq_sales_visit_revisions_company_id",
        ),
        UniqueConstraint(
            "company_id",
            "visit_id",
            "id",
            name="uq_sales_visit_revisions_tenant_visit_id",
        ),
        UniqueConstraint(
            "company_id",
            "visit_id",
            "revision_number",
            name="uq_sales_visit_revision_number",
        ),
        ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_visit_revision_company",
        ),
        ForeignKeyConstraint(
            ["company_id", "visit_id"],
            ["visits.company_id", "visits.id"],
            ondelete="RESTRICT",
            name="fk_sales_visit_revision_tenant_visit",
        ),
        ForeignKeyConstraint(
            ["company_id", "commercial_context_id"],
            [
                "route_commercial_contexts.company_id",
                "route_commercial_contexts.id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_visit_revision_tenant_context",
        ),
        ForeignKeyConstraint(
            ["company_id", "visit_id", "supersedes_revision_id"],
            [
                "sales_visit_revisions.company_id",
                "sales_visit_revisions.visit_id",
                "sales_visit_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_visit_revision_supersedes",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="sales_visit_revision_number_positive",
        ),
        CheckConstraint(
            "(revision_number = 1 AND supersedes_revision_id IS NULL) OR "
            "(revision_number > 1 AND supersedes_revision_id IS NOT NULL)",
            name="sales_visit_revision_chain_shape",
        ),
        CheckConstraint(
            "evidence_schema_version = 4",
            name="sales_visit_revision_schema_v4",
        ),
        CheckConstraint(
            "rounding_policy_version > 0",
            name="sales_visit_revision_rounding_version_positive",
        ),
        CheckConstraint(
            "rounding_precision BETWEEN 0 AND 6",
            name="sales_visit_revision_rounding_precision",
        ),
        CheckConstraint(
            "rounding_mode IN ('HALF_UP','HALF_EVEN')",
            name="sales_visit_revision_rounding_mode",
        ),
        CheckConstraint(
            "price_publication_revision_ceiling > 0",
            name="sales_visit_revision_price_revision_positive",
        ),
        CheckConstraint(
            "assignment_revision_ceiling > 0",
            name="sales_visit_revision_assignment_revision_positive",
        ),
        CheckConstraint(
            "offer_revision_ceiling >= 0",
            name="sales_visit_revision_offer_revision_nonnegative",
        ),
        CheckConstraint(
            "tax_revision_ceiling > 0",
            name="sales_visit_revision_tax_revision_positive",
        ),
        CheckConstraint(
            "gross_amount >= 0 AND discount_amount >= 0 "
            "AND post_offer_amount >= 0 AND taxable_amount >= 0 "
            "AND tax_amount >= 0 AND line_total_amount >= 0 "
            "AND final_amount >= 0",
            name="sales_visit_revision_money_nonnegative",
        ),
        CheckConstraint(
            "post_offer_amount = gross_amount - discount_amount",
            name="sales_visit_revision_offer_reconcile",
        ),
        CheckConstraint(
            "line_total_amount = taxable_amount + tax_amount",
            name="sales_visit_revision_tax_reconcile",
        ),
        CheckConstraint(
            "final_amount = line_total_amount + rounding_adjustment",
            name="sales_visit_revision_final_reconcile",
        ),
        CheckConstraint(
            "jsonb_typeof(offer_snapshot) = 'object'",
            name="sales_visit_revision_offer_snapshot_object",
        ),
        Index(
            "ix_sales_visit_revision_visit",
            "company_id",
            "visit_id",
            "revision_number",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    visit_id = Column(Integer, nullable=False, index=True)
    revision_number = Column(Integer, nullable=False)
    supersedes_revision_id = Column(Integer, nullable=True)
    evidence_schema_version = Column(Integer, nullable=False)
    frozen_at = Column(DateTime(timezone=True), nullable=True)
    commercial_calculated_at = Column(DateTime(timezone=True), nullable=False)
    commercial_context_id = Column(Integer, nullable=False)
    transaction_currency_code = Column(String(10), nullable=False)
    functional_currency_code = Column(String(10), nullable=False)
    rounding_policy_version = Column(Integer, nullable=False)
    rounding_precision = Column(Integer, nullable=False)
    rounding_mode = Column(String(20), nullable=False)
    price_publication_revision_ceiling = Column(Integer, nullable=False)
    assignment_revision_ceiling = Column(Integer, nullable=False)
    offer_revision_ceiling = Column(Integer, nullable=False)
    tax_revision_ceiling = Column(Integer, nullable=False)
    gross_amount = Column(Numeric(20, 6), nullable=False)
    discount_amount = Column(Numeric(20, 6), nullable=False)
    post_offer_amount = Column(Numeric(20, 6), nullable=False)
    taxable_amount = Column(Numeric(20, 6), nullable=False)
    tax_amount = Column(Numeric(20, 6), nullable=False)
    line_total_amount = Column(Numeric(20, 6), nullable=False)
    rounding_adjustment = Column(Numeric(20, 6), nullable=False)
    final_amount = Column(Numeric(20, 6), nullable=False)
    offer_snapshot = Column(JSONB, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SalesRewardEvidence(Base):
    __tablename__ = "sales_reward_evidence"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "id",
            name="uq_sales_reward_evidence_company_id",
        ),
        UniqueConstraint(
            "company_id",
            "sales_revision_id",
            "sequence",
            "product_variant_id",
            "uom_id",
            name="uq_sales_reward_evidence_revision_sequence_product_uom",
        ),
        ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_reward_evidence_company",
        ),
        ForeignKeyConstraint(
            ["company_id", "visit_id"],
            ["visits.company_id", "visits.id"],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_tenant_visit",
        ),
        ForeignKeyConstraint(
            ["company_id", "visit_id", "sales_revision_id"],
            [
                "sales_visit_revisions.company_id",
                "sales_visit_revisions.visit_id",
                "sales_visit_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_tenant_revision",
        ),
        ForeignKeyConstraint(
            ["company_id", "offer_version_id", "offer_definition_id"],
            [
                "offer_versions.company_id",
                "offer_versions.id",
                "offer_versions.offer_definition_id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_tenant_offer",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_variant_id"],
            ["product_variants.company_id", "product_variants.id"],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_tenant_variant",
        ),
        ForeignKeyConstraint(
            ["company_id", "price_entry_id"],
            ["price_book_entries.company_id", "price_book_entries.id"],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_tenant_price_entry",
        ),
        ForeignKeyConstraint(
            ["uom_id"],
            ["uom.id"],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_uom",
        ),
        CheckConstraint(
            "sequence > 0",
            name="sales_reward_evidence_sequence_positive",
        ),
        CheckConstraint(
            "offer_revision > 0",
            name="sales_reward_evidence_offer_revision_positive",
        ),
        CheckConstraint(
            "offer_type IN "
            "('PERCENTAGE_DISCOUNT','FIXED_DISCOUNT','BUY_X_GET_Y',"
            "'FREE_GOODS','QUANTITY_TIERS','BUNDLE')",
            name="sales_reward_evidence_offer_type_valid",
        ),
        CheckConstraint(
            "quantity > 0",
            name="sales_reward_evidence_quantity_positive",
        ),
        CheckConstraint(
            "base_quantity > 0",
            name="sales_reward_evidence_base_quantity_positive",
        ),
        CheckConstraint(
            "price_publication_revision > 0",
            name="sales_reward_evidence_publication_revision_positive",
        ),
        CheckConstraint(
            "assignment_revision > 0",
            name="sales_reward_evidence_assignment_revision_positive",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="sales_reward_evidence_unit_price_nonnegative",
        ),
        CheckConstraint(
            "reward_value >= 0",
            name="sales_reward_evidence_value_nonnegative",
        ),
        CheckConstraint(
            "reward_value = round(quantity * unit_price, 6)",
            name="sales_reward_evidence_value_exact",
        ),
        Index(
            "ix_sales_reward_evidence_visit",
            "company_id",
            "visit_id",
            "sales_revision_id",
            "sequence",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, nullable=False, index=True)
    visit_id = Column(Integer, nullable=False, index=True)
    sales_revision_id = Column(Integer, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    offer_version_id = Column(Integer, nullable=False)
    offer_definition_id = Column(Integer, nullable=False)
    offer_revision = Column(Integer, nullable=False)
    offer_type = Column(String(40), nullable=False)
    product_variant_id = Column(Integer, nullable=False, index=True)
    uom_id = Column(Integer, nullable=False)
    quantity = Column(Numeric(20, 6), nullable=False)
    base_quantity = Column(Numeric(20, 6), nullable=False)
    price_entry_id = Column(Integer, nullable=False)
    price_publication_revision = Column(Integer, nullable=False)
    assignment_revision = Column(Integer, nullable=False)
    unit_price = Column(Numeric(20, 6), nullable=False)
    reward_value = Column(Numeric(20, 6), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class SalesLineAdjustment(Base):
    __tablename__ = "sales_line_adjustments"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "id",
            name="uq_sales_line_adjustments_company_id",
        ),
        UniqueConstraint(
            "company_id", "visit_item_id", "sequence", "uom_id",
            name="uq_sales_line_adjustment_sequence_uom",
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
        ForeignKeyConstraint(
            ["uom_id"],
            ["uom.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_adjustment_uom",
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
    uom_id = Column(Integer, nullable=False)
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
            "(matched_jurisdiction_id IS NULL AND jurisdiction_distance IS NULL) OR "
            "(matched_jurisdiction_id IS NOT NULL AND jurisdiction_distance IS NOT NULL)",
            name="sales_line_tax_component_jurisdiction_shape",
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
