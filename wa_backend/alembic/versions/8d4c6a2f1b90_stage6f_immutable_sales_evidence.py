"""stage6f immutable sales evidence

Revision ID: 8d4c6a2f1b90
Revises: 7c2a8b4d6e91
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8d4c6a2f1b90"
down_revision: Union[str, Sequence[str], None] = "7c2a8b4d6e91"
branch_labels = None
depends_on = None


_TENANT_EXPR = (
    "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
)


def _harden_rls(table_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'DROP POLICY IF EXISTS stage6f_tenant_isolation ON "{table_name}"'
    )
    op.execute(
        f"""
        CREATE POLICY stage6f_tenant_isolation
        ON "{table_name}"
        AS PERMISSIVE
        FOR ALL
        USING ({_TENANT_EXPR})
        WITH CHECK ({_TENANT_EXPR})
        """
    )
    op.execute(
        f'DROP POLICY IF EXISTS stage6f_tenant_guard ON "{table_name}"'
    )
    op.execute(
        f"""
        CREATE POLICY stage6f_tenant_guard
        ON "{table_name}"
        AS RESTRICTIVE
        FOR ALL
        USING ({_TENANT_EXPR})
        WITH CHECK ({_TENANT_EXPR})
        """
    )


def _drop_stage6f_policies(table_name: str) -> None:
    op.execute(
        f'DROP POLICY IF EXISTS stage6f_tenant_guard ON "{table_name}"'
    )
    op.execute(
        f'DROP POLICY IF EXISTS stage6f_tenant_isolation ON "{table_name}"'
    )


def upgrade() -> None:
    # Composite parent guards: evidence cannot mix a version with another definition/rule.
    op.create_unique_constraint(
        "uq_offer_versions_company_id_definition",
        "offer_versions",
        ["company_id", "id", "offer_definition_id"],
    )
    op.create_unique_constraint(
        "uq_tax_rule_set_versions_company_id_rule_set",
        "tax_rule_set_versions",
        ["company_id", "id", "tax_rule_set_id"],
    )
    op.create_unique_constraint(
        "uq_tax_rule_components_company_id_version",
        "tax_rule_components",
        ["company_id", "id", "tax_rule_set_version_id"],
    )

    # Existing aggregate/line money is widened before the new 20,6 evidence is written.
    for column_name in (
        "amount_before_tax_and_discount",
        "discount_applied",
        "tax_amount",
        "final_amount_due",
    ):
        op.alter_column(
            "visits",
            column_name,
            existing_type=sa.Numeric(12, 3),
            type_=sa.Numeric(20, 6),
            existing_nullable=True,
        )
    op.alter_column(
        "visit_items",
        "price_per_unit_at_sale",
        existing_type=sa.Numeric(12, 3),
        type_=sa.Numeric(20, 6),
        existing_nullable=False,
    )
    op.alter_column(
        "visit_items",
        "total_price",
        existing_type=sa.Numeric(12, 3),
        type_=sa.Numeric(20, 6),
        existing_nullable=False,
    )

    visit_columns = (
        sa.Column("financial_evidence_version", sa.Integer(), nullable=True),
        sa.Column("financial_evidence_frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commercial_calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commercial_context_id", sa.Integer(), nullable=True),
        sa.Column("transaction_currency_code", sa.String(10), nullable=True),
        sa.Column("functional_currency_code", sa.String(10), nullable=True),
        sa.Column("rounding_policy_version", sa.Integer(), nullable=True),
        sa.Column("rounding_precision", sa.Integer(), nullable=True),
        sa.Column("rounding_mode", sa.String(20), nullable=True),
        sa.Column("price_publication_revision_ceiling", sa.Integer(), nullable=True),
        sa.Column("assignment_revision_ceiling", sa.Integer(), nullable=True),
        sa.Column("offer_revision_ceiling", sa.Integer(), nullable=True),
        sa.Column("tax_revision_ceiling", sa.Integer(), nullable=True),
        sa.Column("post_offer_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("taxable_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("line_total_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("rounding_adjustment", sa.Numeric(20, 6), nullable=True),
        sa.Column("offer_snapshot", postgresql.JSONB(), nullable=True),
    )
    for column in visit_columns:
        op.add_column("visits", column)

    op.create_foreign_key(
        "fk_visit_tenant_commercial_context",
        "visits",
        "route_commercial_contexts",
        ["company_id", "commercial_context_id"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "visit_financial_evidence_shape",
        "visits",
        """
        (
            financial_evidence_version IS NULL
            AND financial_evidence_frozen_at IS NULL
            AND commercial_calculated_at IS NULL
            AND commercial_context_id IS NULL
            AND transaction_currency_code IS NULL
            AND functional_currency_code IS NULL
            AND rounding_policy_version IS NULL
            AND rounding_precision IS NULL
            AND rounding_mode IS NULL
            AND price_publication_revision_ceiling IS NULL
            AND assignment_revision_ceiling IS NULL
            AND offer_revision_ceiling IS NULL
            AND tax_revision_ceiling IS NULL
            AND post_offer_amount IS NULL
            AND taxable_amount IS NULL
            AND line_total_amount IS NULL
            AND rounding_adjustment IS NULL
            AND offer_snapshot IS NULL
        )
        OR
        (
            financial_evidence_version = 1
            AND financial_evidence_frozen_at IS NOT NULL
            AND commercial_calculated_at IS NOT NULL
            AND transaction_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
            AND functional_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
            AND rounding_policy_version > 0
            AND rounding_precision BETWEEN 0 AND 6
            AND rounding_mode IN ('HALF_UP','HALF_EVEN')
            AND price_publication_revision_ceiling > 0
            AND assignment_revision_ceiling > 0
            AND offer_revision_ceiling >= 0
            AND tax_revision_ceiling > 0
            AND amount_before_tax_and_discount >= 0
            AND discount_applied >= 0
            AND post_offer_amount >= 0
            AND taxable_amount >= 0
            AND tax_amount >= 0
            AND line_total_amount >= 0
            AND final_amount_due >= 0
            AND post_offer_amount = amount_before_tax_and_discount - discount_applied
            AND line_total_amount = taxable_amount + tax_amount
            AND final_amount_due = line_total_amount + rounding_adjustment
            AND offer_snapshot IS NOT NULL
            AND jsonb_typeof(offer_snapshot) = 'object'
        )
        """,
    )

    op.create_unique_constraint(
        "uq_visit_items_company_id",
        "visit_items",
        ["company_id", "id"],
    )
    item_columns = (
        sa.Column("financial_evidence_version", sa.Integer(), nullable=True),
        sa.Column("financial_evidence_frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commercial_context_id", sa.Integer(), nullable=True),
        sa.Column("base_uom_id", sa.Integer(), nullable=True),
        sa.Column("canonical_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("selected_price_entry_id", sa.Integer(), nullable=True),
        sa.Column("price_publication_revision", sa.Integer(), nullable=True),
        sa.Column("assignment_revision", sa.Integer(), nullable=True),
        sa.Column("gross_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("discount_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("post_offer_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("taxable_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("tax_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("net_amount", sa.Numeric(20, 6), nullable=True),
        sa.Column("transaction_currency_code", sa.String(10), nullable=True),
        sa.Column("functional_currency_code", sa.String(10), nullable=True),
        sa.Column("offer_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("tax_snapshot", postgresql.JSONB(), nullable=True),
    )
    for column in item_columns:
        op.add_column("visit_items", column)

    op.create_foreign_key(
        "fk_visit_item_tenant_commercial_context",
        "visit_items",
        "route_commercial_contexts",
        ["company_id", "commercial_context_id"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_visit_item_base_uom",
        "visit_items",
        "uom",
        ["base_uom_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_visit_item_tenant_price_entry",
        "visit_items",
        "price_book_entries",
        ["company_id", "selected_price_entry_id"],
        ["company_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "visit_item_sale_money_nonnegative",
        "visit_items",
        "price_per_unit_at_sale >= 0 AND total_price >= 0",
    )
    op.create_check_constraint(
        "visit_item_financial_evidence_shape",
        "visit_items",
        """
        (
            financial_evidence_version IS NULL
            AND financial_evidence_frozen_at IS NULL
            AND commercial_context_id IS NULL
            AND base_uom_id IS NULL
            AND canonical_quantity IS NULL
            AND selected_price_entry_id IS NULL
            AND price_publication_revision IS NULL
            AND assignment_revision IS NULL
            AND gross_amount IS NULL
            AND discount_amount IS NULL
            AND post_offer_amount IS NULL
            AND taxable_amount IS NULL
            AND tax_amount IS NULL
            AND net_amount IS NULL
            AND transaction_currency_code IS NULL
            AND functional_currency_code IS NULL
            AND offer_snapshot IS NULL
            AND tax_snapshot IS NULL
        )
        OR
        (
            financial_evidence_version = 1
            AND financial_evidence_frozen_at IS NOT NULL
            AND base_uom_id IS NOT NULL
            AND canonical_quantity > 0
            AND selected_price_entry_id IS NOT NULL
            AND price_publication_revision > 0
            AND assignment_revision > 0
            AND gross_amount >= 0
            AND discount_amount >= 0
            AND post_offer_amount >= 0
            AND taxable_amount >= 0
            AND tax_amount >= 0
            AND net_amount >= 0
            AND discount_amount <= gross_amount
            AND post_offer_amount = gross_amount - discount_amount
            AND net_amount = taxable_amount + tax_amount
            AND total_price = net_amount
            AND transaction_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
            AND functional_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
            AND offer_snapshot IS NOT NULL
            AND jsonb_typeof(offer_snapshot) = 'object'
            AND tax_snapshot IS NOT NULL
            AND jsonb_typeof(tax_snapshot) = 'object'
        )
        """,
    )

    op.create_table(
        "sales_line_adjustments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("visit_item_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("offer_version_id", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(40), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("basis_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("adjustment_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "metadata_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="sales_line_adjustment_sequence_positive",
        ),
        sa.CheckConstraint(
            "rule_version > 0",
            name="sales_line_adjustment_rule_version_positive",
        ),
        sa.CheckConstraint(
            "rule_type IN "
            "('PERCENTAGE_DISCOUNT','FIXED_DISCOUNT','BUY_X_GET_Y',"
            "'FREE_GOODS','QUANTITY_TIERS','BUNDLE')",
            name="sales_line_adjustment_rule_type_valid",
        ),
        sa.CheckConstraint(
            "basis_amount >= 0",
            name="sales_line_adjustment_basis_nonnegative",
        ),
        sa.CheckConstraint(
            "adjustment_amount >= 0",
            name="sales_line_adjustment_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata_snapshot) = 'object'",
            name="sales_line_adjustment_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_line_adjustment_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "visit_item_id"],
            ["visit_items.company_id", "visit_items.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_adjustment_tenant_line",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "offer_version_id", "rule_id"],
            [
                "offer_versions.company_id",
                "offer_versions.id",
                "offer_versions.offer_definition_id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_line_adjustment_tenant_offer",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "id",
            name="uq_sales_line_adjustments_company_id",
        ),
        sa.UniqueConstraint(
            "company_id", "visit_item_id", "sequence",
            name="uq_sales_line_adjustment_sequence",
        ),
    )
    op.create_index(
        "ix_sales_line_adjustment_line",
        "sales_line_adjustments",
        ["company_id", "visit_item_id", "sequence"],
    )

    op.create_table(
        "sales_line_tax_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("visit_item_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("tax_rule_set_id", sa.Integer(), nullable=False),
        sa.Column("tax_rule_set_version_id", sa.Integer(), nullable=False),
        sa.Column("tax_revision", sa.Integer(), nullable=False),
        sa.Column("tax_component_id", sa.Integer(), nullable=False),
        sa.Column("component_code", sa.String(100), nullable=False),
        sa.Column("tax_name", sa.String(150), nullable=False),
        sa.Column("rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("basis_mode", sa.String(40), nullable=False),
        sa.Column("taxable_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("tax_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("reporting_code", sa.String(100), nullable=True),
        sa.Column("matched_jurisdiction_id", sa.Integer(), nullable=True),
        sa.Column("jurisdiction_distance", sa.Integer(), nullable=True),
        sa.Column(
            "metadata_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="sales_line_tax_component_sequence_positive",
        ),
        sa.CheckConstraint(
            "tax_revision > 0",
            name="sales_line_tax_component_revision_positive",
        ),
        sa.CheckConstraint(
            "length(trim(component_code)) > 0",
            name="sales_line_tax_component_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(tax_name)) > 0",
            name="sales_line_tax_component_name_not_blank",
        ),
        sa.CheckConstraint(
            "rate >= 0",
            name="sales_line_tax_component_rate_nonnegative",
        ),
        sa.CheckConstraint(
            "basis_mode IN ('TAXABLE_BASE','TAXABLE_BASE_PLUS_PRIOR_TAX')",
            name="sales_line_tax_component_basis_mode_valid",
        ),
        sa.CheckConstraint(
            "taxable_amount >= 0",
            name="sales_line_tax_component_taxable_nonnegative",
        ),
        sa.CheckConstraint(
            "tax_amount >= 0",
            name="sales_line_tax_component_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "jurisdiction_distance IS NULL OR jurisdiction_distance >= 0",
            name="sales_line_tax_component_jurisdiction_distance",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata_snapshot) = 'object'",
            name="sales_line_tax_component_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_line_tax_component_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "visit_item_id"],
            ["visit_items.company_id", "visit_items.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_tax_component_tenant_line",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "tax_rule_set_version_id", "tax_rule_set_id"],
            [
                "tax_rule_set_versions.company_id",
                "tax_rule_set_versions.id",
                "tax_rule_set_versions.tax_rule_set_id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_line_tax_component_tenant_rule_version",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "tax_component_id", "tax_rule_set_version_id"],
            [
                "tax_rule_components.company_id",
                "tax_rule_components.id",
                "tax_rule_components.tax_rule_set_version_id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_line_tax_component_tenant_component",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "matched_jurisdiction_id"],
            ["tax_jurisdictions.company_id", "tax_jurisdictions.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_tax_component_tenant_jurisdiction",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "id",
            name="uq_sales_line_tax_components_company_id",
        ),
        sa.UniqueConstraint(
            "company_id", "visit_item_id", "sequence",
            name="uq_sales_line_tax_component_sequence",
        ),
    )
    op.create_index(
        "ix_sales_line_tax_component_line",
        "sales_line_tax_components",
        ["company_id", "visit_item_id", "sequence"],
    )

    # Parent and evidence tables are all protected. The restrictive policy means
    # an older permissive policy can never widen access beyond app.current_tenant.
    for table_name in (
        "visits",
        "visit_items",
        "sales_line_adjustments",
        "sales_line_tax_components",
    ):
        _harden_rls(table_name)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sales_line_child_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_version integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'sales line evidence is insert-only'
                    USING ERRCODE = '55000';
            END IF;

            SELECT financial_evidence_version
            INTO parent_version
            FROM visit_items
            WHERE company_id = NEW.company_id
              AND id = NEW.visit_item_id
            FOR KEY SHARE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'sales evidence parent line not found'
                    USING ERRCODE = '23503';
            END IF;
            IF parent_version IS NOT NULL THEN
                RAISE EXCEPTION 'cannot append evidence to a frozen sales line'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sales_line_adjustment_insert_only
        BEFORE INSERT OR UPDATE OR DELETE ON sales_line_adjustments
        FOR EACH ROW EXECUTE FUNCTION guard_sales_line_child_evidence()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sales_line_tax_component_insert_only
        BEFORE INSERT OR UPDATE OR DELETE ON sales_line_tax_components
        FOR EACH ROW EXECUTE FUNCTION guard_sales_line_child_evidence()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ensure_sales_line_parent_frozen()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_version integer;
        BEGIN
            SELECT financial_evidence_version
            INTO parent_version
            FROM visit_items
            WHERE company_id = NEW.company_id
              AND id = NEW.visit_item_id;

            IF parent_version IS NULL THEN
                RAISE EXCEPTION 'sales line evidence cannot commit without a frozen parent'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_sales_line_adjustment_parent_frozen
        AFTER INSERT ON sales_line_adjustments
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ensure_sales_line_parent_frozen()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_sales_line_tax_component_parent_frozen
        AFTER INSERT ON sales_line_tax_components
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ensure_sales_line_parent_frozen()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_visit_financial_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.financial_evidence_version IS NOT NULL THEN
                    RAISE EXCEPTION 'frozen visit financial evidence cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.financial_evidence_version IS NOT NULL AND (
                NEW.company_id IS DISTINCT FROM OLD.company_id
                OR NEW.driver_id IS DISTINCT FROM OLD.driver_id
                OR NEW.shop_id IS DISTINCT FROM OLD.shop_id
                OR NEW.work_session_id IS DISTINCT FROM OLD.work_session_id
                OR NEW.operational_date IS DISTINCT FROM OLD.operational_date
                OR NEW.financial_evidence_version IS DISTINCT FROM OLD.financial_evidence_version
                OR NEW.financial_evidence_frozen_at IS DISTINCT FROM OLD.financial_evidence_frozen_at
                OR NEW.commercial_calculated_at IS DISTINCT FROM OLD.commercial_calculated_at
                OR NEW.commercial_context_id IS DISTINCT FROM OLD.commercial_context_id
                OR NEW.transaction_currency_code IS DISTINCT FROM OLD.transaction_currency_code
                OR NEW.functional_currency_code IS DISTINCT FROM OLD.functional_currency_code
                OR NEW.rounding_policy_version IS DISTINCT FROM OLD.rounding_policy_version
                OR NEW.rounding_precision IS DISTINCT FROM OLD.rounding_precision
                OR NEW.rounding_mode IS DISTINCT FROM OLD.rounding_mode
                OR NEW.price_publication_revision_ceiling IS DISTINCT FROM OLD.price_publication_revision_ceiling
                OR NEW.assignment_revision_ceiling IS DISTINCT FROM OLD.assignment_revision_ceiling
                OR NEW.offer_revision_ceiling IS DISTINCT FROM OLD.offer_revision_ceiling
                OR NEW.tax_revision_ceiling IS DISTINCT FROM OLD.tax_revision_ceiling
                OR NEW.amount_before_tax_and_discount IS DISTINCT FROM OLD.amount_before_tax_and_discount
                OR NEW.discount_applied IS DISTINCT FROM OLD.discount_applied
                OR NEW.post_offer_amount IS DISTINCT FROM OLD.post_offer_amount
                OR NEW.taxable_amount IS DISTINCT FROM OLD.taxable_amount
                OR NEW.tax_amount IS DISTINCT FROM OLD.tax_amount
                OR NEW.line_total_amount IS DISTINCT FROM OLD.line_total_amount
                OR NEW.rounding_adjustment IS DISTINCT FROM OLD.rounding_adjustment
                OR NEW.final_amount_due IS DISTINCT FROM OLD.final_amount_due
                OR NEW.offer_snapshot IS DISTINCT FROM OLD.offer_snapshot
            ) THEN
                RAISE EXCEPTION 'visit financial evidence is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_visit_financial_evidence_immutable
        BEFORE UPDATE OR DELETE ON visits
        FOR EACH ROW EXECUTE FUNCTION guard_visit_financial_evidence()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_visit_item_financial_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.financial_evidence_version IS NOT NULL THEN
                    RAISE EXCEPTION 'frozen visit-item financial evidence cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.financial_evidence_version IS NOT NULL AND (
                NEW.company_id IS DISTINCT FROM OLD.company_id
                OR NEW.visit_id IS DISTINCT FROM OLD.visit_id
                OR NEW.product_variant_id IS DISTINCT FROM OLD.product_variant_id
                OR NEW.quantity IS DISTINCT FROM OLD.quantity
                OR NEW.packs_quantity IS DISTINCT FROM OLD.packs_quantity
                OR NEW.bonus_quantity IS DISTINCT FROM OLD.bonus_quantity
                OR NEW.sample_quantity IS DISTINCT FROM OLD.sample_quantity
                OR NEW.sample_packs_quantity IS DISTINCT FROM OLD.sample_packs_quantity
                OR NEW.sample_reason IS DISTINCT FROM OLD.sample_reason
                OR NEW.price_per_unit_at_sale IS DISTINCT FROM OLD.price_per_unit_at_sale
                OR NEW.total_price IS DISTINCT FROM OLD.total_price
                OR NEW.financial_evidence_version IS DISTINCT FROM OLD.financial_evidence_version
                OR NEW.financial_evidence_frozen_at IS DISTINCT FROM OLD.financial_evidence_frozen_at
                OR NEW.commercial_context_id IS DISTINCT FROM OLD.commercial_context_id
                OR NEW.base_uom_id IS DISTINCT FROM OLD.base_uom_id
                OR NEW.canonical_quantity IS DISTINCT FROM OLD.canonical_quantity
                OR NEW.selected_price_entry_id IS DISTINCT FROM OLD.selected_price_entry_id
                OR NEW.price_publication_revision IS DISTINCT FROM OLD.price_publication_revision
                OR NEW.assignment_revision IS DISTINCT FROM OLD.assignment_revision
                OR NEW.gross_amount IS DISTINCT FROM OLD.gross_amount
                OR NEW.discount_amount IS DISTINCT FROM OLD.discount_amount
                OR NEW.post_offer_amount IS DISTINCT FROM OLD.post_offer_amount
                OR NEW.taxable_amount IS DISTINCT FROM OLD.taxable_amount
                OR NEW.tax_amount IS DISTINCT FROM OLD.tax_amount
                OR NEW.net_amount IS DISTINCT FROM OLD.net_amount
                OR NEW.transaction_currency_code IS DISTINCT FROM OLD.transaction_currency_code
                OR NEW.functional_currency_code IS DISTINCT FROM OLD.functional_currency_code
                OR NEW.offer_snapshot IS DISTINCT FROM OLD.offer_snapshot
                OR NEW.tax_snapshot IS DISTINCT FROM OLD.tax_snapshot
            ) THEN
                RAISE EXCEPTION 'visit-item financial evidence is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_visit_item_financial_evidence_immutable
        BEFORE UPDATE OR DELETE ON visit_items
        FOR EACH ROW EXECUTE FUNCTION guard_visit_item_financial_evidence()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_frozen_visit_item_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            adjustment_total numeric(20,6);
            component_total numeric(20,6);
            component_count integer;
            min_sequence integer;
            max_sequence integer;
        BEGIN
            IF NEW.financial_evidence_version IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT COALESCE(SUM(adjustment_amount), 0)
            INTO adjustment_total
            FROM sales_line_adjustments
            WHERE company_id = NEW.company_id
              AND visit_item_id = NEW.id;

            IF adjustment_total <> NEW.discount_amount THEN
                RAISE EXCEPTION 'typed adjustments do not reconcile to line discount'
                    USING ERRCODE = '23514';
            END IF;

            SELECT
                COALESCE(SUM(tax_amount), 0),
                COUNT(*),
                MIN(sequence),
                MAX(sequence)
            INTO component_total, component_count, min_sequence, max_sequence
            FROM sales_line_tax_components
            WHERE company_id = NEW.company_id
              AND visit_item_id = NEW.id;

            IF component_count <= 0 THEN
                RAISE EXCEPTION 'frozen sales line requires typed tax evidence'
                    USING ERRCODE = '23514';
            END IF;
            IF min_sequence <> 1 OR max_sequence <> component_count THEN
                RAISE EXCEPTION 'tax component sequence must be contiguous from 1'
                    USING ERRCODE = '23514';
            END IF;
            IF component_total <> NEW.tax_amount THEN
                RAISE EXCEPTION 'typed tax components do not reconcile to line tax'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_visit_item_evidence_reconcile
        AFTER INSERT OR UPDATE ON visit_items
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_frozen_visit_item_evidence()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_frozen_visit_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            total_count integer;
            frozen_count integer;
            gross_total numeric(20,6);
            discount_total numeric(20,6);
            post_offer_total numeric(20,6);
            taxable_total numeric(20,6);
            tax_total numeric(20,6);
            line_total numeric(20,6);
        BEGIN
            IF NEW.financial_evidence_version IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT
                COUNT(*),
                COUNT(*) FILTER (WHERE financial_evidence_version IS NOT NULL),
                COALESCE(SUM(gross_amount), 0),
                COALESCE(SUM(discount_amount), 0),
                COALESCE(SUM(post_offer_amount), 0),
                COALESCE(SUM(taxable_amount), 0),
                COALESCE(SUM(tax_amount), 0),
                COALESCE(SUM(net_amount), 0)
            INTO
                total_count, frozen_count, gross_total, discount_total,
                post_offer_total, taxable_total, tax_total, line_total
            FROM visit_items
            WHERE company_id = NEW.company_id
              AND visit_id = NEW.id;

            IF total_count <= 0 OR total_count <> frozen_count THEN
                RAISE EXCEPTION 'all visit items must be frozen with the visit'
                    USING ERRCODE = '23514';
            END IF;
            IF gross_total <> NEW.amount_before_tax_and_discount
               OR discount_total <> NEW.discount_applied
               OR post_offer_total <> NEW.post_offer_amount
               OR taxable_total <> NEW.taxable_amount
               OR tax_total <> NEW.tax_amount
               OR line_total <> NEW.line_total_amount
               OR NEW.final_amount_due <> NEW.line_total_amount + NEW.rounding_adjustment
            THEN
                RAISE EXCEPTION 'visit header does not reconcile to frozen lines'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_visit_evidence_reconcile
        AFTER INSERT OR UPDATE ON visits
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_frozen_visit_evidence()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_visit_evidence_reconcile ON visits")
    op.execute("DROP FUNCTION IF EXISTS validate_frozen_visit_evidence()")
    op.execute("DROP TRIGGER IF EXISTS trg_visit_item_evidence_reconcile ON visit_items")
    op.execute("DROP FUNCTION IF EXISTS validate_frozen_visit_item_evidence()")
    op.execute("DROP TRIGGER IF EXISTS trg_visit_item_financial_evidence_immutable ON visit_items")
    op.execute("DROP FUNCTION IF EXISTS guard_visit_item_financial_evidence()")
    op.execute("DROP TRIGGER IF EXISTS trg_visit_financial_evidence_immutable ON visits")
    op.execute("DROP FUNCTION IF EXISTS guard_visit_financial_evidence()")
    op.execute("DROP TRIGGER IF EXISTS trg_sales_line_tax_component_parent_frozen ON sales_line_tax_components")
    op.execute("DROP TRIGGER IF EXISTS trg_sales_line_adjustment_parent_frozen ON sales_line_adjustments")
    op.execute("DROP FUNCTION IF EXISTS ensure_sales_line_parent_frozen()")
    op.execute("DROP TRIGGER IF EXISTS trg_sales_line_tax_component_insert_only ON sales_line_tax_components")
    op.execute("DROP TRIGGER IF EXISTS trg_sales_line_adjustment_insert_only ON sales_line_adjustments")
    op.execute("DROP FUNCTION IF EXISTS guard_sales_line_child_evidence()")

    for table_name in (
        "visits",
        "visit_items",
        "sales_line_adjustments",
        "sales_line_tax_components",
    ):
        _drop_stage6f_policies(table_name)

    op.drop_table("sales_line_tax_components")
    op.drop_table("sales_line_adjustments")

    op.drop_constraint("ck_visit_items_visit_item_financial_evidence_shape", "visit_items", type_="check")
    op.drop_constraint("ck_visit_items_visit_item_sale_money_nonnegative", "visit_items", type_="check")
    op.drop_constraint("fk_visit_item_tenant_price_entry", "visit_items", type_="foreignkey")
    op.drop_constraint("fk_visit_item_base_uom", "visit_items", type_="foreignkey")
    op.drop_constraint("fk_visit_item_tenant_commercial_context", "visit_items", type_="foreignkey")
    for column_name in (
        "tax_snapshot",
        "offer_snapshot",
        "functional_currency_code",
        "transaction_currency_code",
        "net_amount",
        "tax_amount",
        "taxable_amount",
        "post_offer_amount",
        "discount_amount",
        "gross_amount",
        "assignment_revision",
        "price_publication_revision",
        "selected_price_entry_id",
        "canonical_quantity",
        "base_uom_id",
        "commercial_context_id",
        "financial_evidence_frozen_at",
        "financial_evidence_version",
    ):
        op.drop_column("visit_items", column_name)
    op.drop_constraint("uq_visit_items_company_id", "visit_items", type_="unique")
    op.alter_column(
        "visit_items",
        "total_price",
        existing_type=sa.Numeric(20, 6),
        type_=sa.Numeric(12, 3),
        existing_nullable=False,
    )
    op.alter_column(
        "visit_items",
        "price_per_unit_at_sale",
        existing_type=sa.Numeric(20, 6),
        type_=sa.Numeric(12, 3),
        existing_nullable=False,
    )

    op.drop_constraint("ck_visits_visit_financial_evidence_shape", "visits", type_="check")
    op.drop_constraint("fk_visit_tenant_commercial_context", "visits", type_="foreignkey")
    for column_name in (
        "offer_snapshot",
        "rounding_adjustment",
        "line_total_amount",
        "taxable_amount",
        "post_offer_amount",
        "tax_revision_ceiling",
        "offer_revision_ceiling",
        "assignment_revision_ceiling",
        "price_publication_revision_ceiling",
        "rounding_mode",
        "rounding_precision",
        "rounding_policy_version",
        "functional_currency_code",
        "transaction_currency_code",
        "commercial_context_id",
        "commercial_calculated_at",
        "financial_evidence_frozen_at",
        "financial_evidence_version",
    ):
        op.drop_column("visits", column_name)
    for column_name in (
        "final_amount_due",
        "tax_amount",
        "discount_applied",
        "amount_before_tax_and_discount",
    ):
        op.alter_column(
            "visits",
            column_name,
            existing_type=sa.Numeric(20, 6),
            type_=sa.Numeric(12, 3),
            existing_nullable=True,
        )

    op.drop_constraint(
        "uq_tax_rule_components_company_id_version",
        "tax_rule_components",
        type_="unique",
    )
    op.drop_constraint(
        "uq_tax_rule_set_versions_company_id_rule_set",
        "tax_rule_set_versions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_offer_versions_company_id_definition",
        "offer_versions",
        type_="unique",
    )
