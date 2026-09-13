"""stage6c tax foundation

Revision ID: 7c2a8b4d6e91
Revises: 6a1f9c2e4d70
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c2a8b4d6e91"
down_revision: Union[str, Sequence[str], None] = "6a1f9c2e4d70"
branch_labels = None
depends_on = None

_TABLES = (
    "tax_jurisdictions",
    "tax_rule_sets",
    "tax_rule_set_versions",
    "tax_rule_components",
    "tax_rule_scopes",
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
        "tax_jurisdictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("jurisdiction_type", sa.String(20), nullable=False),
        sa.Column("country_code", sa.String(3), nullable=False),
        sa.Column("subdivision_code", sa.String(50), nullable=True),
        sa.Column("locality_code", sa.String(100), nullable=True),
        sa.Column("parent_jurisdiction_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("length(trim(code)) > 0", name="tax_jurisdiction_code_not_blank"),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'", name="tax_jurisdiction_code_format"),
        sa.CheckConstraint("length(trim(name)) > 0", name="tax_jurisdiction_name_not_blank"),
        sa.CheckConstraint("jurisdiction_type IN ('COUNTRY','SUBDIVISION','LOCALITY','CUSTOM')", name="tax_jurisdiction_type_valid"),
        sa.CheckConstraint("country_code ~ '^[A-Z]{2,3}$'", name="tax_jurisdiction_country_code_format"),
        sa.CheckConstraint(
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
        sa.CheckConstraint("parent_jurisdiction_id IS NULL OR parent_jurisdiction_id <> id", name="tax_jurisdiction_not_self_parent"),
        sa.CheckConstraint("version > 0", name="tax_jurisdiction_version_positive"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_tax_jurisdiction_company"),
        sa.ForeignKeyConstraint(["company_id", "parent_jurisdiction_id"], ["tax_jurisdictions.company_id", "tax_jurisdictions.id"], ondelete="RESTRICT", name="fk_tax_jurisdiction_tenant_parent"),
        sa.ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_tax_jurisdiction_tenant_creator"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_tax_jurisdictions_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_tax_jurisdiction_company_code"),
    )
    op.create_index("ix_tax_jurisdiction_parent", "tax_jurisdictions", ["company_id", "parent_jurisdiction_id", "is_active", "id"])

    op.create_table(
        "tax_rule_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("length(trim(code)) > 0", name="tax_rule_set_code_not_blank"),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'", name="tax_rule_set_code_format"),
        sa.CheckConstraint("length(trim(name)) > 0", name="tax_rule_set_name_not_blank"),
        sa.CheckConstraint("version > 0", name="tax_rule_set_version_positive"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_tax_rule_set_company"),
        sa.ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_tax_rule_set_tenant_creator"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_tax_rule_sets_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_tax_rule_set_company_code"),
    )
    op.create_index("ix_tax_rule_set_company_id", "tax_rule_sets", ["company_id", "id"])

    op.create_table(
        "tax_rule_set_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("tax_rule_set_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), server_default="DRAFT", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("price_mode", sa.String(20), server_default="EXCLUSIVE", nullable=False),
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
        sa.CheckConstraint("revision > 0", name="tax_version_revision_positive"),
        sa.CheckConstraint("definition_version > 0", name="tax_version_definition_number_positive"),
        sa.CheckConstraint("priority >= 0", name="tax_version_priority_nonnegative"),
        sa.CheckConstraint("version > 0", name="tax_version_row_version_positive"),
        sa.CheckConstraint("status IN ('DRAFT','PENDING_APPROVAL','PUBLISHED','SUPERSEDED','CANCELLED')", name="tax_version_status_valid"),
        sa.CheckConstraint("price_mode IN ('EXCLUSIVE','INCLUSIVE')", name="tax_version_price_mode_valid"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="tax_version_effectivity_valid"),
        sa.CheckConstraint(
            "status NOT IN ('PUBLISHED','SUPERSEDED') OR (approved_by IS NOT NULL AND approved_at IS NOT NULL AND published_at IS NOT NULL)",
            name="tax_version_published_metadata",
        ),
        sa.CheckConstraint(
            "status <> 'CANCELLED' OR (cancelled_by IS NOT NULL AND cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL AND length(trim(cancel_reason)) > 0)",
            name="tax_version_cancelled_metadata",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_tax_version_company"),
        sa.ForeignKeyConstraint(["company_id", "tax_rule_set_id"], ["tax_rule_sets.company_id", "tax_rule_sets.id"], ondelete="RESTRICT", name="fk_tax_version_tenant_rule_set"),
        sa.ForeignKeyConstraint(["company_id", "created_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_tax_version_tenant_creator"),
        sa.ForeignKeyConstraint(["company_id", "approved_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_tax_version_tenant_approver"),
        sa.ForeignKeyConstraint(["company_id", "cancelled_by"], ["drivers.company_id", "drivers.id"], ondelete="RESTRICT", name="fk_tax_version_tenant_canceller"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_tax_rule_set_versions_company_id"),
        sa.UniqueConstraint("company_id", "revision", name="uq_tax_version_company_revision"),
        sa.UniqueConstraint("company_id", "tax_rule_set_id", "definition_version", name="uq_tax_version_definition_number"),
        sa.UniqueConstraint("company_id", "request_id", name="uq_tax_version_company_request"),
    )
    op.create_index(
        "ix_tax_version_resolver",
        "tax_rule_set_versions",
        ["company_id", "status", "revision", "effective_from", "priority"],
    )
    op.create_index(
        "uq_tax_version_one_published_rule_set",
        "tax_rule_set_versions",
        ["company_id", "tax_rule_set_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )

    op.create_table(
        "tax_rule_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("tax_rule_set_version_id", sa.Integer(), nullable=False),
        sa.Column("component_code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("basis_mode", sa.String(40), server_default="TAXABLE_BASE", nullable=False),
        sa.Column("reporting_code", sa.String(100), nullable=True),
        sa.CheckConstraint("length(trim(component_code)) > 0", name="tax_component_code_not_blank"),
        sa.CheckConstraint("component_code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'", name="tax_component_code_format"),
        sa.CheckConstraint("length(trim(name)) > 0", name="tax_component_name_not_blank"),
        sa.CheckConstraint("reporting_code IS NULL OR reporting_code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'", name="tax_component_reporting_code_format"),
        sa.CheckConstraint("sequence > 0", name="tax_component_sequence_positive"),
        sa.CheckConstraint("rate >= 0", name="tax_component_rate_nonnegative"),
        sa.CheckConstraint("basis_mode IN ('TAXABLE_BASE','TAXABLE_BASE_PLUS_PRIOR_TAX')", name="tax_component_basis_mode_valid"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_tax_component_company"),
        sa.ForeignKeyConstraint(["company_id", "tax_rule_set_version_id"], ["tax_rule_set_versions.company_id", "tax_rule_set_versions.id"], ondelete="CASCADE", name="fk_tax_component_tenant_version"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_tax_rule_components_company_id"),
        sa.UniqueConstraint("company_id", "tax_rule_set_version_id", "component_code", name="uq_tax_component_code"),
        sa.UniqueConstraint("company_id", "tax_rule_set_version_id", "sequence", name="uq_tax_component_sequence"),
    )
    op.create_index("ix_tax_component_version", "tax_rule_components", ["company_id", "tax_rule_set_version_id", "sequence"])

    op.create_table(
        "tax_rule_scopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("tax_rule_set_version_id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(30), nullable=False),
        sa.Column("jurisdiction_id", sa.Integer(), nullable=True),
        sa.Column("product_variant_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("document_type_code", sa.String(80), nullable=True),
        sa.CheckConstraint("scope_type IN ('JURISDICTION','PRODUCT_VARIANT','CUSTOMER','DOCUMENT_TYPE')", name="tax_scope_type_valid"),
        sa.CheckConstraint("document_type_code IS NULL OR document_type_code ~ '^[A-Z0-9][A-Z0-9_.:-]*$'", name="tax_scope_document_code_format"),
        sa.CheckConstraint(
            """
            (scope_type = 'JURISDICTION' AND jurisdiction_id IS NOT NULL
                AND product_variant_id IS NULL AND customer_id IS NULL AND document_type_code IS NULL)
            OR
            (scope_type = 'PRODUCT_VARIANT' AND product_variant_id IS NOT NULL
                AND jurisdiction_id IS NULL AND customer_id IS NULL AND document_type_code IS NULL)
            OR
            (scope_type = 'CUSTOMER' AND customer_id IS NOT NULL
                AND jurisdiction_id IS NULL AND product_variant_id IS NULL AND document_type_code IS NULL)
            OR
            (scope_type = 'DOCUMENT_TYPE' AND document_type_code IS NOT NULL
                AND length(trim(document_type_code)) > 0
                AND jurisdiction_id IS NULL AND product_variant_id IS NULL AND customer_id IS NULL)
            """,
            name="tax_scope_target_matches_type",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE", name="fk_tax_scope_company"),
        sa.ForeignKeyConstraint(["company_id", "tax_rule_set_version_id"], ["tax_rule_set_versions.company_id", "tax_rule_set_versions.id"], ondelete="CASCADE", name="fk_tax_scope_tenant_version"),
        sa.ForeignKeyConstraint(["company_id", "jurisdiction_id"], ["tax_jurisdictions.company_id", "tax_jurisdictions.id"], ondelete="RESTRICT", name="fk_tax_scope_tenant_jurisdiction"),
        sa.ForeignKeyConstraint(["company_id", "product_variant_id"], ["product_variants.company_id", "product_variants.id"], ondelete="RESTRICT", name="fk_tax_scope_tenant_variant"),
        sa.ForeignKeyConstraint(["company_id", "customer_id"], ["shops.company_id", "shops.id"], ondelete="RESTRICT", name="fk_tax_scope_tenant_customer"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_tax_rule_scopes_company_id"),
    )
    op.create_index("ix_tax_scope_version", "tax_rule_scopes", ["company_id", "tax_rule_set_version_id", "scope_type"])
    op.create_index("uq_tax_scope_jurisdiction", "tax_rule_scopes", ["company_id", "tax_rule_set_version_id", "jurisdiction_id"], unique=True, postgresql_where=sa.text("scope_type = 'JURISDICTION'"))
    op.create_index("uq_tax_scope_product", "tax_rule_scopes", ["company_id", "tax_rule_set_version_id", "product_variant_id"], unique=True, postgresql_where=sa.text("scope_type = 'PRODUCT_VARIANT'"))
    op.create_index("uq_tax_scope_customer", "tax_rule_scopes", ["company_id", "tax_rule_set_version_id", "customer_id"], unique=True, postgresql_where=sa.text("scope_type = 'CUSTOMER'"))
    op.create_index("uq_tax_scope_document", "tax_rule_scopes", ["company_id", "tax_rule_set_version_id", "document_type_code"], unique=True, postgresql_where=sa.text("scope_type = 'DOCUMENT_TYPE'"))

    for table_name in _TABLES:
        _enable_rls(table_name)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_tax_jurisdiction_cycle()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.parent_jurisdiction_id IS NULL THEN
                RETURN NEW;
            END IF;
            IF NEW.parent_jurisdiction_id = NEW.id THEN
                RAISE EXCEPTION 'tax jurisdiction cycle detected' USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                WITH RECURSIVE ancestors AS (
                    SELECT id, parent_jurisdiction_id, ARRAY[id] AS path
                    FROM tax_jurisdictions
                    WHERE company_id = NEW.company_id
                      AND id = NEW.parent_jurisdiction_id
                    UNION ALL
                    SELECT parent.id, parent.parent_jurisdiction_id, ancestors.path || parent.id
                    FROM tax_jurisdictions parent
                    JOIN ancestors ON parent.id = ancestors.parent_jurisdiction_id
                    WHERE parent.company_id = NEW.company_id
                      AND NOT parent.id = ANY(ancestors.path)
                      AND cardinality(ancestors.path) < 64
                )
                SELECT 1 FROM ancestors WHERE id = NEW.id
            ) THEN
                RAISE EXCEPTION 'tax jurisdiction cycle detected' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tax_jurisdiction_cycle
        BEFORE INSERT OR UPDATE OF parent_jurisdiction_id, company_id
        ON tax_jurisdictions
        FOR EACH ROW EXECUTE FUNCTION guard_tax_jurisdiction_cycle()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_tax_jurisdiction_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF (
                NEW.code IS DISTINCT FROM OLD.code
                OR NEW.jurisdiction_type IS DISTINCT FROM OLD.jurisdiction_type
                OR NEW.country_code IS DISTINCT FROM OLD.country_code
                OR NEW.subdivision_code IS DISTINCT FROM OLD.subdivision_code
                OR NEW.locality_code IS DISTINCT FROM OLD.locality_code
                OR NEW.parent_jurisdiction_id IS DISTINCT FROM OLD.parent_jurisdiction_id
            ) AND EXISTS (
                SELECT 1 FROM tax_rule_scopes
                WHERE company_id = OLD.company_id
                  AND jurisdiction_id = OLD.id
            ) THEN
                RAISE EXCEPTION 'referenced tax jurisdiction identity is immutable' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tax_jurisdiction_identity
        BEFORE UPDATE ON tax_jurisdictions
        FOR EACH ROW EXECUTE FUNCTION guard_tax_jurisdiction_identity()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_tax_version_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'DRAFT' THEN
                    RAISE EXCEPTION 'non-draft tax version history is immutable' USING ERRCODE = '55000';
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
                RAISE EXCEPTION 'pending tax configuration is immutable' USING ERRCODE = '55000';
            END IF;

            IF OLD.status = 'PUBLISHED' THEN
                IF NEW.status = 'SUPERSEDED'
                   AND NEW.version = OLD.version + 1
                   AND (to_jsonb(NEW) - ARRAY['status','version','updated_at'])
                       = (to_jsonb(OLD) - ARRAY['status','version','updated_at']) THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'published tax version history is immutable' USING ERRCODE = '55000';
            END IF;

            RAISE EXCEPTION 'closed tax version history is immutable' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tax_version_immutable
        BEFORE UPDATE OR DELETE ON tax_rule_set_versions
        FOR EACH ROW EXECUTE FUNCTION guard_tax_version_immutable()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_tax_version_child_immutable()
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
                version_id := OLD.tax_rule_set_version_id;
            ELSE
                tenant_id := NEW.company_id;
                version_id := NEW.tax_rule_set_version_id;
            END IF;

            SELECT status INTO parent_status
            FROM tax_rule_set_versions
            WHERE company_id = tenant_id AND id = version_id;

            IF parent_status IS DISTINCT FROM 'DRAFT' THEN
                RAISE EXCEPTION 'non-draft tax configuration is immutable' USING ERRCODE = '55000';
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
        CREATE TRIGGER trg_tax_component_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON tax_rule_components
        FOR EACH ROW EXECUTE FUNCTION guard_tax_version_child_immutable()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_tax_scope_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON tax_rule_scopes
        FOR EACH ROW EXECUTE FUNCTION guard_tax_version_child_immutable()
        """
    )

    op.execute(
        """
        INSERT INTO permissions (code)
        VALUES ('tax.view'), ('tax.manage'), ('tax.approve')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_tax_scope_immutable ON tax_rule_scopes")
    op.execute("DROP TRIGGER IF EXISTS trg_tax_component_immutable ON tax_rule_components")
    op.execute("DROP TRIGGER IF EXISTS trg_tax_version_immutable ON tax_rule_set_versions")
    op.execute("DROP TRIGGER IF EXISTS trg_tax_jurisdiction_identity ON tax_jurisdictions")
    op.execute("DROP TRIGGER IF EXISTS trg_tax_jurisdiction_cycle ON tax_jurisdictions")
    op.execute("DROP FUNCTION IF EXISTS guard_tax_version_child_immutable()")
    op.execute("DROP FUNCTION IF EXISTS guard_tax_version_immutable()")
    op.execute("DROP FUNCTION IF EXISTS guard_tax_jurisdiction_identity()")
    op.execute("DROP FUNCTION IF EXISTS guard_tax_jurisdiction_cycle()")

    for table_name in reversed(_TABLES):
        op.execute(f'DROP POLICY IF EXISTS {table_name}_company_isolation ON "{table_name}"')

    op.drop_table("tax_rule_scopes")
    op.drop_table("tax_rule_components")
    op.drop_table("tax_rule_set_versions")
    op.drop_table("tax_rule_sets")
    op.drop_table("tax_jurisdictions")

    op.execute(
        "DELETE FROM permissions WHERE code IN ('tax.view','tax.manage','tax.approve')"
    )
