from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
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

from models import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaxJurisdiction(Base):
    """Stable tenant-owned jurisdiction identity; tax behavior lives in versioned rule sets."""

    __tablename__ = "tax_jurisdictions"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_tax_jurisdictions_company_id"),
        UniqueConstraint("company_id", "code", name="uq_tax_jurisdiction_company_code"),
        ForeignKeyConstraint(
            ["company_id", "parent_jurisdiction_id"],
            ["tax_jurisdictions.company_id", "tax_jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_tax_jurisdiction_tenant_parent",
        ),
        ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_tax_jurisdiction_tenant_creator",
        ),
        CheckConstraint("length(trim(code)) > 0", name="tax_jurisdiction_code_not_blank"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'", name="tax_jurisdiction_code_format"),
        CheckConstraint("length(trim(name)) > 0", name="tax_jurisdiction_name_not_blank"),
        CheckConstraint(
            "jurisdiction_type IN ('COUNTRY','SUBDIVISION','LOCALITY','CUSTOM')",
            name="tax_jurisdiction_type_valid",
        ),
        CheckConstraint(
            "country_code ~ '^[A-Z]{2,3}$'",
            name="tax_jurisdiction_country_code_format",
        ),
        CheckConstraint(
            """
            (jurisdiction_type = 'COUNTRY' AND parent_jurisdiction_id IS NULL
                AND subdivision_code IS NULL AND locality_code IS NULL)
            OR
            (jurisdiction_type = 'SUBDIVISION' AND parent_jurisdiction_id IS NOT NULL
                AND subdivision_code IS NOT NULL AND locality_code IS NULL)
            OR
            (jurisdiction_type = 'LOCALITY' AND parent_jurisdiction_id IS NOT NULL
                AND locality_code IS NOT NULL)
            OR
            (jurisdiction_type = 'CUSTOM')
            """,
            name="tax_jurisdiction_shape_valid",
        ),
        CheckConstraint(
            "parent_jurisdiction_id IS NULL OR parent_jurisdiction_id <> id",
            name="tax_jurisdiction_not_self_parent",
        ),
        CheckConstraint("version > 0", name="tax_jurisdiction_version_positive"),
        Index(
            "ix_tax_jurisdiction_parent",
            "company_id",
            "parent_jurisdiction_id",
            "is_active",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    jurisdiction_type = Column(String(20), nullable=False)
    country_code = Column(String(3), nullable=False)
    subdivision_code = Column(String(50), nullable=True)
    locality_code = Column(String(100), nullable=True)
    parent_jurisdiction_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_by = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class TaxRuleSet(Base):
    """Stable business identity for a versioned set of tax components."""

    __tablename__ = "tax_rule_sets"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_tax_rule_sets_company_id"),
        UniqueConstraint("company_id", "code", name="uq_tax_rule_set_company_code"),
        ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_tax_rule_set_tenant_creator",
        ),
        CheckConstraint("length(trim(code)) > 0", name="tax_rule_set_code_not_blank"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'", name="tax_rule_set_code_format"),
        CheckConstraint("length(trim(name)) > 0", name="tax_rule_set_name_not_blank"),
        CheckConstraint("version > 0", name="tax_rule_set_version_positive"),
        Index("ix_tax_rule_set_company_id", "company_id", "id"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_by = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class TaxRuleSetVersion(Base):
    """Effective-dated, tenant-global revision of one TaxRuleSet."""

    __tablename__ = "tax_rule_set_versions"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_tax_rule_set_versions_company_id"),
        UniqueConstraint("company_id", "revision", name="uq_tax_version_company_revision"),
        UniqueConstraint(
            "company_id", "tax_rule_set_id", "definition_version",
            name="uq_tax_version_definition_number",
        ),
        UniqueConstraint("company_id", "request_id", name="uq_tax_version_company_request"),
        ForeignKeyConstraint(
            ["company_id", "tax_rule_set_id"],
            ["tax_rule_sets.company_id", "tax_rule_sets.id"],
            ondelete="RESTRICT",
            name="fk_tax_version_tenant_rule_set",
        ),
        ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_tax_version_tenant_creator",
        ),
        ForeignKeyConstraint(
            ["company_id", "approved_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_tax_version_tenant_approver",
        ),
        ForeignKeyConstraint(
            ["company_id", "cancelled_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_tax_version_tenant_canceller",
        ),
        CheckConstraint("revision > 0", name="tax_version_revision_positive"),
        CheckConstraint("definition_version > 0", name="tax_version_definition_number_positive"),
        CheckConstraint("priority >= 0", name="tax_version_priority_nonnegative"),
        CheckConstraint("version > 0", name="tax_version_row_version_positive"),
        CheckConstraint(
            "status IN ('DRAFT','PENDING_APPROVAL','PUBLISHED','SUPERSEDED','CANCELLED')",
            name="tax_version_status_valid",
        ),
        CheckConstraint(
            "price_mode IN ('EXCLUSIVE','INCLUSIVE')",
            name="tax_version_price_mode_valid",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="tax_version_effectivity_valid",
        ),
        CheckConstraint(
            "status NOT IN ('PUBLISHED','SUPERSEDED') OR "
            "(approved_by IS NOT NULL AND approved_at IS NOT NULL AND published_at IS NOT NULL)",
            name="tax_version_published_metadata",
        ),
        CheckConstraint(
            "status <> 'CANCELLED' OR "
            "(cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL "
            "AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) > 0)",
            name="tax_version_cancelled_metadata",
        ),
        Index(
            "ix_tax_version_resolver",
            "company_id", "status", "revision", "effective_from", "priority",
        ),
        Index(
            "uq_tax_version_one_published_rule_set",
            "company_id", "tax_rule_set_id",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    tax_rule_set_id = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False)
    definition_version = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="DRAFT", server_default="DRAFT")
    priority = Column(Integer, nullable=False, default=0, server_default="0")
    price_mode = Column(String(20), nullable=False, default="EXCLUSIVE", server_default="EXCLUSIVE")
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    request_id = Column(Uuid, nullable=False)
    created_by = Column(Integer, nullable=False)
    approved_by = Column(Integer, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_by = Column(Integer, nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancel_reason = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class TaxRuleComponent(Base):
    """One ordered tax component within a rule-set version."""

    __tablename__ = "tax_rule_components"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_tax_rule_components_company_id"),
        UniqueConstraint(
            "company_id", "tax_rule_set_version_id", "component_code",
            name="uq_tax_component_code",
        ),
        UniqueConstraint(
            "company_id", "tax_rule_set_version_id", "sequence",
            name="uq_tax_component_sequence",
        ),
        ForeignKeyConstraint(
            ["company_id", "tax_rule_set_version_id"],
            ["tax_rule_set_versions.company_id", "tax_rule_set_versions.id"],
            ondelete="CASCADE",
            name="fk_tax_component_tenant_version",
        ),
        CheckConstraint("length(trim(component_code)) > 0", name="tax_component_code_not_blank"),
        CheckConstraint("component_code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'", name="tax_component_code_format"),
        CheckConstraint("length(trim(name)) > 0", name="tax_component_name_not_blank"),
        CheckConstraint(
            "reporting_code IS NULL OR reporting_code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'",
            name="tax_component_reporting_code_format",
        ),
        CheckConstraint("sequence > 0", name="tax_component_sequence_positive"),
        CheckConstraint("rate >= 0", name="tax_component_rate_nonnegative"),
        CheckConstraint(
            "basis_mode IN ('TAXABLE_BASE','TAXABLE_BASE_PLUS_PRIOR_TAX')",
            name="tax_component_basis_mode_valid",
        ),
        Index(
            "ix_tax_component_version",
            "company_id", "tax_rule_set_version_id", "sequence",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    tax_rule_set_version_id = Column(Integer, nullable=False)
    component_code = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    sequence = Column(Integer, nullable=False)
    rate = Column(Numeric(20, 8), nullable=False)
    basis_mode = Column(String(40), nullable=False, default="TAXABLE_BASE", server_default="TAXABLE_BASE")
    reporting_code = Column(String(100), nullable=True)


class TaxRuleScope(Base):
    """Typed applicability dimensions for one TaxRuleSetVersion."""

    __tablename__ = "tax_rule_scopes"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_tax_rule_scopes_company_id"),
        ForeignKeyConstraint(
            ["company_id", "tax_rule_set_version_id"],
            ["tax_rule_set_versions.company_id", "tax_rule_set_versions.id"],
            ondelete="CASCADE",
            name="fk_tax_scope_tenant_version",
        ),
        ForeignKeyConstraint(
            ["company_id", "jurisdiction_id"],
            ["tax_jurisdictions.company_id", "tax_jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_tax_scope_tenant_jurisdiction",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_variant_id"],
            ["product_variants.company_id", "product_variants.id"],
            ondelete="RESTRICT",
            name="fk_tax_scope_tenant_variant",
        ),
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["shops.company_id", "shops.id"],
            ondelete="RESTRICT",
            name="fk_tax_scope_tenant_customer",
        ),
        CheckConstraint(
            "scope_type IN ('JURISDICTION','PRODUCT_VARIANT','CUSTOMER','DOCUMENT_TYPE')",
            name="tax_scope_type_valid",
        ),
        CheckConstraint(
            "document_type_code IS NULL OR document_type_code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'",
            name="tax_scope_document_code_format",
        ),
        CheckConstraint(
            """
            (scope_type = 'JURISDICTION' AND jurisdiction_id IS NOT NULL
                AND product_variant_id IS NULL AND customer_id IS NULL
                AND document_type_code IS NULL)
            OR
            (scope_type = 'PRODUCT_VARIANT' AND product_variant_id IS NOT NULL
                AND jurisdiction_id IS NULL AND customer_id IS NULL
                AND document_type_code IS NULL)
            OR
            (scope_type = 'CUSTOMER' AND customer_id IS NOT NULL
                AND jurisdiction_id IS NULL AND product_variant_id IS NULL
                AND document_type_code IS NULL)
            OR
            (scope_type = 'DOCUMENT_TYPE' AND document_type_code IS NOT NULL
                AND length(trim(document_type_code)) > 0
                AND jurisdiction_id IS NULL AND product_variant_id IS NULL
                AND customer_id IS NULL)
            """,
            name="tax_scope_target_matches_type",
        ),
        Index(
            "ix_tax_scope_version",
            "company_id", "tax_rule_set_version_id", "scope_type",
        ),
        Index(
            "uq_tax_scope_jurisdiction",
            "company_id", "tax_rule_set_version_id", "jurisdiction_id",
            unique=True,
            postgresql_where=text("scope_type = 'JURISDICTION'"),
        ),
        Index(
            "uq_tax_scope_product",
            "company_id", "tax_rule_set_version_id", "product_variant_id",
            unique=True,
            postgresql_where=text("scope_type = 'PRODUCT_VARIANT'"),
        ),
        Index(
            "uq_tax_scope_customer",
            "company_id", "tax_rule_set_version_id", "customer_id",
            unique=True,
            postgresql_where=text("scope_type = 'CUSTOMER'"),
        ),
        Index(
            "uq_tax_scope_document",
            "company_id", "tax_rule_set_version_id", "document_type_code",
            unique=True,
            postgresql_where=text("scope_type = 'DOCUMENT_TYPE'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    tax_rule_set_version_id = Column(Integer, nullable=False)
    scope_type = Column(String(30), nullable=False)
    jurisdiction_id = Column(Integer, nullable=True)
    product_variant_id = Column(Integer, nullable=True)
    customer_id = Column(Integer, nullable=True)
    document_type_code = Column(String(80), nullable=True)
