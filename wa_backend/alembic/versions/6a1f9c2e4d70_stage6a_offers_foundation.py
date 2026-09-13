"""stage6a offers foundation

Revision ID: 6a1f9c2e4d70
Revises: e42b7c9d5a13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "6a1f9c2e4d70"
down_revision: Union[str, Sequence[str], None] = "e42b7c9d5a13"
branch_labels = None
depends_on = None

_TABLES = (
    "offer_definitions",
    "offer_versions",
    "offer_version_scopes",
    "offer_version_products",
)


def _enable_rls(table_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY {table_name}_company_isolation
        ON "{table_name}"
        USING (
            company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer
        )
        WITH CHECK (
            company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer
        )
        """
    )


def upgrade() -> None:
    op.create_table(
        "offer_definitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("length(trim(code)) > 0", name="ck_offer_definitions_offer_definition_code_not_blank"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_offer_definitions_offer_definition_name_not_blank"),
        sa.CheckConstraint("version > 0", name="ck_offer_definitions_offer_definition_version_positive"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_offer_definition_company"),
        sa.ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_offer_definition_tenant_creator"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_offer_definitions_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_offer_definition_company_code"),
    )
    op.create_index("ix_offer_definition_company_id", "offer_definitions", ["company_id", "id"])

    op.create_table(
        "offer_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("offer_definition_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), server_default="DRAFT", nullable=False),
        sa.Column("offer_type", sa.String(40), nullable=False),
        sa.Column("validated_payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("currency_code", sa.String(10), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stacking_mode", sa.String(20), server_default="EXCLUSIVE", nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_offer_versions_offer_version_revision_positive"),
        sa.CheckConstraint("definition_version > 0", name="ck_offer_versions_offer_version_definition_number_positive"),
        sa.CheckConstraint("priority >= 0", name="ck_offer_versions_offer_version_priority_nonnegative"),
        sa.CheckConstraint("version > 0", name="ck_offer_versions_offer_version_row_version_positive"),
        sa.CheckConstraint("status IN ('DRAFT','PENDING_APPROVAL','PUBLISHED','SUPERSEDED','CANCELLED')", name="ck_offer_versions_offer_version_status_valid"),
        sa.CheckConstraint("offer_type IN ('PERCENTAGE_DISCOUNT','FIXED_DISCOUNT','BUY_X_GET_Y','FREE_GOODS','QUANTITY_TIERS','BUNDLE')", name="ck_offer_versions_offer_version_type_valid"),
        sa.CheckConstraint("stacking_mode IN ('EXCLUSIVE','STACKABLE')", name="ck_offer_versions_offer_version_stacking_mode_valid"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_offer_versions_offer_version_effectivity_valid"),
        sa.CheckConstraint("jsonb_typeof(validated_payload) = 'object'", name="ck_offer_versions_offer_version_payload_object"),
        sa.CheckConstraint(
            "status NOT IN ('PUBLISHED','SUPERSEDED') OR "
            "(approved_by IS NOT NULL AND approved_at IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_offer_versions_offer_version_published_metadata",
        ),
        sa.CheckConstraint(
            "status <> 'CANCELLED' OR "
            "(cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL "
            "AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) > 0)",
            name="ck_offer_versions_offer_version_cancelled_metadata",
        ),
        sa.CheckConstraint("currency_code IS NULL OR length(trim(currency_code)) > 0", name="chk_offer_version_currency_not_blank"),
        sa.CheckConstraint(
            "status NOT IN ('PUBLISHED','SUPERSEDED') OR "
            "(approved_by IS NOT NULL AND approved_at IS NOT NULL AND published_at IS NOT NULL)",
            name="chk_offer_version_published_metadata",
        ),
        sa.CheckConstraint(
            "status <> 'CANCELLED' OR "
            "(cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL "
            "AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) > 0)",
            name="chk_offer_version_cancelled_metadata",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_offer_version_company"),
        sa.ForeignKeyConstraint(["company_id", "offer_definition_id"], ["offer_definitions.company_id", "offer_definitions.id"], ondelete="RESTRICT", name="fk_offer_version_tenant_definition"),
        sa.ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_offer_version_tenant_creator"),
        sa.ForeignKeyConstraint(["company_id", "approved_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_offer_version_tenant_approver"),
        sa.ForeignKeyConstraint(["company_id", "cancelled_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_offer_version_tenant_canceller"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_offer_versions_company_id"),
        sa.UniqueConstraint("company_id", "revision", name="uq_offer_version_company_revision"),
        sa.UniqueConstraint("company_id", "offer_definition_id", "definition_version", name="uq_offer_version_definition_number"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_offer_version_company_request"),
    )
    op.create_index(
        "ix_offer_version_resolver",
        "offer_versions",
        ["company_id", "status", "revision", "effective_from", "priority"],
    )
    op.create_index(
        "uq_offer_version_one_published_definition",
        "offer_versions",
        ["company_id", "offer_definition_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )

    op.create_table(
        "offer_version_scopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("offer_version_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(30), nullable=False),
        sa.Column("product_variant_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("channel_code", sa.String(50), nullable=True),
        sa.CheckConstraint("scope_type IN ('PRODUCT_VARIANT','CUSTOMER','BRANCH','CHANNEL')", name="ck_offer_version_scopes_offer_scope_type_valid"),
        sa.CheckConstraint(
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
            name="ck_offer_version_scopes_offer_scope_target_matches_type",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_offer_scope_company"),
        sa.ForeignKeyConstraint(["company_id", "offer_version_id"], ["offer_versions.company_id", "offer_versions.id"], ondelete="CASCADE", name="fk_offer_scope_tenant_version"),
        sa.ForeignKeyConstraint(["company_id", "product_variant_id"], ["product_variants.company_id", "product_variants.id"], ondelete="RESTRICT", name="fk_offer_scope_tenant_variant"),
        sa.ForeignKeyConstraint(["company_id", "customer_id"], ["shops.company_id", "shops.id"], ondelete="RESTRICT", name="fk_offer_scope_tenant_customer"),
        sa.ForeignKeyConstraint(["company_id", "branch_id"], ["branches.company_id", "branches.id"], ondelete="RESTRICT", name="fk_offer_scope_tenant_branch"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_offer_version_scopes_company_id"),
    )
    op.create_index("ix_offer_scope_version", "offer_version_scopes", ["company_id", "offer_version_id", "scope_type"])
    op.create_index("uq_offer_scope_product", "offer_version_scopes", ["company_id", "offer_version_id", "product_variant_id"], unique=True, postgresql_where=sa.text("scope_type = 'PRODUCT_VARIANT'"))
    op.create_index("uq_offer_scope_customer", "offer_version_scopes", ["company_id", "offer_version_id", "customer_id"], unique=True, postgresql_where=sa.text("scope_type = 'CUSTOMER'"))
    op.create_index("uq_offer_scope_branch", "offer_version_scopes", ["company_id", "offer_version_id", "branch_id"], unique=True, postgresql_where=sa.text("scope_type = 'BRANCH'"))
    op.create_index("uq_offer_scope_channel", "offer_version_scopes", ["company_id", "offer_version_id", "channel_code"], unique=True, postgresql_where=sa.text("scope_type = 'CHANNEL'"))

    op.create_table(
        "offer_version_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("offer_version_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("product_variant_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("role IN ('QUALIFYING','REWARD','BUNDLE_COMPONENT')", name="ck_offer_version_products_offer_product_role_valid"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_offer_product_company"),
        sa.ForeignKeyConstraint(["company_id", "offer_version_id"], ["offer_versions.company_id", "offer_versions.id"], ondelete="CASCADE", name="fk_offer_product_tenant_version"),
        sa.ForeignKeyConstraint(["company_id", "product_variant_id"], ["product_variants.company_id", "product_variants.id"], ondelete="RESTRICT", name="fk_offer_product_tenant_variant"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_offer_version_products_company_id"),
        sa.UniqueConstraint("company_id", "offer_version_id", "role", "product_variant_id", name="uq_offer_version_product_role_variant"),
    )
    op.create_index("ix_offer_product_version", "offer_version_products", ["company_id", "offer_version_id", "role"])

    for table_name in _TABLES:
        _enable_rls(table_name)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_offer_version_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'DRAFT' THEN
                    RAISE EXCEPTION 'non-draft offer version history is immutable' USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.status = 'DRAFT' THEN
                RETURN NEW;
            END IF;

            IF OLD.status = 'PENDING_APPROVAL' THEN
                IF NEW.status = 'PUBLISHED'
                   AND NEW.version = OLD.version + 1
                   AND NEW.approved_by IS NOT NULL
                   AND NEW.approved_at IS NOT NULL
                   AND NEW.published_at IS NOT NULL
                   AND (to_jsonb(NEW) - ARRAY['status','version','updated_at','approved_by','approved_at','published_at'])
                       = (to_jsonb(OLD) - ARRAY['status','version','updated_at','approved_by','approved_at','published_at']) THEN
                    RETURN NEW;
                END IF;
                IF NEW.status = 'CANCELLED'
                   AND NEW.version = OLD.version + 1
                   AND NEW.cancelled_by IS NOT NULL
                   AND NEW.cancelled_at IS NOT NULL
                   AND NEW.cancel_reason IS NOT NULL
                   AND length(trim(NEW.cancel_reason)) > 0
                   AND (to_jsonb(NEW) - ARRAY['status','version','updated_at','cancelled_by','cancelled_at','cancel_reason'])
                       = (to_jsonb(OLD) - ARRAY['status','version','updated_at','cancelled_by','cancelled_at','cancel_reason']) THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'pending offer configuration is immutable' USING ERRCODE = '55000';
            END IF;

            IF OLD.status = 'PUBLISHED' THEN
                IF NEW.status = 'SUPERSEDED'
                   AND NEW.version = OLD.version + 1
                   AND (to_jsonb(NEW) - ARRAY['status','version','updated_at'])
                       = (to_jsonb(OLD) - ARRAY['status','version','updated_at']) THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'published offer version history is immutable' USING ERRCODE = '55000';
            END IF;

            RAISE EXCEPTION 'closed offer version history is immutable' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_offer_version_immutable
        BEFORE UPDATE OR DELETE ON offer_versions
        FOR EACH ROW EXECUTE FUNCTION guard_offer_version_immutable()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_offer_version_child_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            tenant_id integer;
            version_id integer;
            parent_status text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                tenant_id := OLD.company_id;
                version_id := OLD.offer_version_id;
            ELSE
                tenant_id := NEW.company_id;
                version_id := NEW.offer_version_id;
            END IF;

            SELECT status INTO parent_status
            FROM offer_versions
            WHERE company_id = tenant_id AND id = version_id;

            IF parent_status IS DISTINCT FROM 'DRAFT' THEN
                RAISE EXCEPTION 'non-draft offer configuration is immutable' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_offer_scope_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON offer_version_scopes
        FOR EACH ROW EXECUTE FUNCTION guard_offer_version_child_immutable()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_offer_product_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON offer_version_products
        FOR EACH ROW EXECUTE FUNCTION guard_offer_version_child_immutable()
        """
    )

    op.execute(
        """
        INSERT INTO permissions (code)
        VALUES ('offers.view'), ('offers.manage'), ('offers.approve')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_offer_product_immutable ON offer_version_products")
    op.execute("DROP TRIGGER IF EXISTS trg_offer_scope_immutable ON offer_version_scopes")
    op.execute("DROP TRIGGER IF EXISTS trg_offer_version_immutable ON offer_versions")
    op.execute("DROP FUNCTION IF EXISTS guard_offer_version_child_immutable()")
    op.execute("DROP FUNCTION IF EXISTS guard_offer_version_immutable()")

    for table_name in reversed(_TABLES):
        op.execute(f'DROP POLICY IF EXISTS {table_name}_company_isolation ON "{table_name}"')

    op.drop_table("offer_version_products")
    op.drop_table("offer_version_scopes")
    op.drop_table("offer_versions")
    op.drop_table("offer_definitions")

    op.execute(
        "DELETE FROM permissions WHERE code IN ('offers.view','offers.manage','offers.approve')"
    )
