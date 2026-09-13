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


class OfferDefinition(Base):
    """Stable business identity; commercial behavior lives in OfferVersion."""

    __tablename__ = "offer_definitions"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_offer_definitions_company_id"),
        UniqueConstraint("company_id", "code", name="uq_offer_definition_company_code"),
        ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_offer_definition_tenant_creator",
        ),
        CheckConstraint("length(trim(code)) > 0", name="offer_definition_code_not_blank"),
        CheckConstraint("length(trim(name)) > 0", name="offer_definition_name_not_blank"),
        CheckConstraint("version > 0", name="offer_definition_version_positive"),
        Index("ix_offer_definition_company_id", "company_id", "id"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code = Column(String(100), nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_by = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class OfferVersion(Base):
    """Typed, versioned commercial definition; immutable once published."""

    __tablename__ = "offer_versions"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_offer_versions_company_id"),
        UniqueConstraint(
            "company_id", "id", "offer_definition_id",
            name="uq_offer_versions_company_id_definition",
        ),
        UniqueConstraint("company_id", "revision", name="uq_offer_version_company_revision"),
        UniqueConstraint(
            "company_id",
            "offer_definition_id",
            "definition_version",
            name="uq_offer_version_definition_number",
        ),
        UniqueConstraint("company_id", "request_id", name="uq_offer_version_company_request"),
        ForeignKeyConstraint(
            ["company_id", "offer_definition_id"],
            ["offer_definitions.company_id", "offer_definitions.id"],
            ondelete="RESTRICT",
            name="fk_offer_version_tenant_definition",
        ),
        ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_offer_version_tenant_creator",
        ),
        ForeignKeyConstraint(
            ["company_id", "approved_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_offer_version_tenant_approver",
        ),
        ForeignKeyConstraint(
            ["company_id", "cancelled_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_offer_version_tenant_canceller",
        ),
        CheckConstraint("revision > 0", name="offer_version_revision_positive"),
        CheckConstraint("definition_version > 0", name="offer_version_definition_number_positive"),
        CheckConstraint("priority >= 0", name="offer_version_priority_nonnegative"),
        CheckConstraint("version > 0", name="offer_version_row_version_positive"),
        CheckConstraint(
            "status IN ('DRAFT','PENDING_APPROVAL','PUBLISHED','SUPERSEDED','CANCELLED')",
            name="offer_version_status_valid",
        ),
        CheckConstraint(
            "offer_type IN ('PERCENTAGE_DISCOUNT','FIXED_DISCOUNT','BUY_X_GET_Y','FREE_GOODS','QUANTITY_TIERS','BUNDLE')",
            name="offer_version_type_valid",
        ),
        CheckConstraint(
            "stacking_mode IN ('EXCLUSIVE','STACKABLE')",
            name="offer_version_stacking_mode_valid",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="offer_version_effectivity_valid",
        ),
        CheckConstraint(
            "jsonb_typeof(validated_payload) = 'object'",
            name="offer_version_payload_object",
        ),
        CheckConstraint(
            "status NOT IN ('PUBLISHED','SUPERSEDED') OR "
            "(approved_by IS NOT NULL AND approved_at IS NOT NULL AND published_at IS NOT NULL)",
            name="offer_version_published_metadata",
        ),
        CheckConstraint(
            "status <> 'CANCELLED' OR "
            "(cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL "
            "AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) > 0)",
            name="offer_version_cancelled_metadata",
        ),
        CheckConstraint(
            "currency_code IS NULL OR length(trim(currency_code)) > 0",
            name="offer_version_currency_not_blank",
        ),
        Index(
            "ix_offer_version_resolver",
            "company_id",
            "status",
            "revision",
            "effective_from",
            "priority",
        ),
        Index(
            "uq_offer_version_one_published_definition",
            "company_id",
            "offer_definition_id",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offer_definition_id = Column(Integer, nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    definition_version = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="DRAFT", server_default="DRAFT")
    offer_type = Column(String(40), nullable=False)
    validated_payload = Column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    currency_code = Column(String(10), nullable=True)
    priority = Column(Integer, nullable=False, default=0, server_default="0")
    stacking_mode = Column(
        String(20), nullable=False, default="EXCLUSIVE", server_default="EXCLUSIVE"
    )
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
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class OfferVersionScope(Base):
    """Tenant-safe targeting dimensions. Entity IDs never hide inside JSON."""

    __tablename__ = "offer_version_scopes"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_offer_version_scopes_company_id"),
        ForeignKeyConstraint(
            ["company_id", "offer_version_id"],
            ["offer_versions.company_id", "offer_versions.id"],
            ondelete="CASCADE",
            name="fk_offer_scope_tenant_version",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_variant_id"],
            ["product_variants.company_id", "product_variants.id"],
            ondelete="RESTRICT",
            name="fk_offer_scope_tenant_variant",
        ),
        ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["shops.company_id", "shops.id"],
            ondelete="RESTRICT",
            name="fk_offer_scope_tenant_customer",
        ),
        ForeignKeyConstraint(
            ["company_id", "branch_id"],
            ["branches.company_id", "branches.id"],
            ondelete="RESTRICT",
            name="fk_offer_scope_tenant_branch",
        ),
        CheckConstraint(
            "scope_type IN ('PRODUCT_VARIANT','CUSTOMER','BRANCH','CHANNEL')",
            name="offer_scope_type_valid",
        ),
        CheckConstraint(
            """
            (scope_type = 'PRODUCT_VARIANT' AND product_variant_id IS NOT NULL
                AND customer_id IS NULL AND branch_id IS NULL AND channel_code IS NULL)
            OR
            (scope_type = 'CUSTOMER' AND customer_id IS NOT NULL
                AND product_variant_id IS NULL AND branch_id IS NULL AND channel_code IS NULL)
            OR
            (scope_type = 'BRANCH' AND branch_id IS NOT NULL
                AND product_variant_id IS NULL AND customer_id IS NULL AND channel_code IS NULL)
            OR
            (scope_type = 'CHANNEL' AND channel_code IS NOT NULL
                AND length(trim(channel_code)) > 0
                AND product_variant_id IS NULL AND customer_id IS NULL AND branch_id IS NULL)
            """,
            name="offer_scope_target_matches_type",
        ),
        Index("ix_offer_scope_version", "company_id", "offer_version_id", "scope_type"),
        Index(
            "uq_offer_scope_product",
            "company_id",
            "offer_version_id",
            "product_variant_id",
            unique=True,
            postgresql_where=text("scope_type = 'PRODUCT_VARIANT'"),
        ),
        Index(
            "uq_offer_scope_customer",
            "company_id",
            "offer_version_id",
            "customer_id",
            unique=True,
            postgresql_where=text("scope_type = 'CUSTOMER'"),
        ),
        Index(
            "uq_offer_scope_branch",
            "company_id",
            "offer_version_id",
            "branch_id",
            unique=True,
            postgresql_where=text("scope_type = 'BRANCH'"),
        ),
        Index(
            "uq_offer_scope_channel",
            "company_id",
            "offer_version_id",
            "channel_code",
            unique=True,
            postgresql_where=text("scope_type = 'CHANNEL'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offer_version_id = Column(Integer, nullable=False, index=True)
    scope_type = Column(String(30), nullable=False)
    product_variant_id = Column(Integer, nullable=True)
    customer_id = Column(Integer, nullable=True)
    branch_id = Column(Integer, nullable=True)
    channel_code = Column(String(50), nullable=True)


class OfferVersionProduct(Base):
    """Cross-product roles needed by BOGO/free-goods/bundle configurations."""

    __tablename__ = "offer_version_products"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_offer_version_products_company_id"),
        UniqueConstraint(
            "company_id",
            "offer_version_id",
            "role",
            "product_variant_id",
            name="uq_offer_version_product_role_variant",
        ),
        ForeignKeyConstraint(
            ["company_id", "offer_version_id"],
            ["offer_versions.company_id", "offer_versions.id"],
            ondelete="CASCADE",
            name="fk_offer_product_tenant_version",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_variant_id"],
            ["product_variants.company_id", "product_variants.id"],
            ondelete="RESTRICT",
            name="fk_offer_product_tenant_variant",
        ),
        CheckConstraint(
            "role IN ('QUALIFYING','REWARD','BUNDLE_COMPONENT')",
            name="offer_product_role_valid",
        ),
        Index("ix_offer_product_version", "company_id", "offer_version_id", "role"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offer_version_id = Column(Integer, nullable=False, index=True)
    role = Column(String(30), nullable=False)
    product_variant_id = Column(Integer, nullable=False)
