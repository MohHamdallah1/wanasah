"""stage6h2b1 immutable mixed-uom price evidence

Revision ID: d7e4b2c9a6f1
Revises: c3f8a1d6e2b4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e4b2c9a6f1"
down_revision: Union[str, Sequence[str], None] = "c3f8a1d6e2b4"
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


def _assert_no_frozen_evidence() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM visits
                WHERE financial_evidence_version IS NOT NULL
            )
            OR EXISTS (
                SELECT 1 FROM visit_items
                WHERE financial_evidence_version IS NOT NULL
            )
            OR EXISTS (SELECT 1 FROM sales_line_adjustments)
            OR EXISTS (SELECT 1 FROM sales_line_tax_components)
            THEN
                RAISE EXCEPTION
                    'Stage 6H.2B.1 requires the approved disposable pre-cutover evidence baseline';
            END IF;
        END
        $$;
        """
    )


def _create_visit_shape(version: int) -> None:
    op.create_check_constraint(
        "visit_financial_evidence_shape",
        "visits",
        f"""
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
            financial_evidence_version = {int(version)}
            AND financial_evidence_frozen_at IS NOT NULL
            AND commercial_calculated_at IS NOT NULL
            AND transaction_currency_code ~ '^[A-Z][A-Z0-9]{{2,9}}$'
            AND functional_currency_code ~ '^[A-Z][A-Z0-9]{{2,9}}$'
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


def _create_visit_item_shape(version: int, *, mixed_price_authority: bool) -> None:
    if mixed_price_authority:
        selected_shape = """
            AND selected_price_entry_id IS NULL
            AND price_publication_revision IS NULL
            AND assignment_revision IS NULL
        """
    else:
        selected_shape = """
            AND selected_price_entry_id IS NOT NULL
            AND price_publication_revision > 0
            AND assignment_revision > 0
        """

    op.create_check_constraint(
        "visit_item_financial_evidence_shape",
        "visit_items",
        f"""
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
            financial_evidence_version = {int(version)}
            AND financial_evidence_frozen_at IS NOT NULL
            AND base_uom_id IS NOT NULL
            AND canonical_quantity > 0
            {selected_shape}
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
            AND transaction_currency_code ~ '^[A-Z][A-Z0-9]{{2,9}}$'
            AND functional_currency_code ~ '^[A-Z][A-Z0-9]{{2,9}}$'
            AND offer_snapshot IS NOT NULL
            AND jsonb_typeof(offer_snapshot) = 'object'
            AND tax_snapshot IS NOT NULL
            AND jsonb_typeof(tax_snapshot) = 'object'
        )
        """,
    )


def upgrade() -> None:
    _assert_no_frozen_evidence()

    op.drop_constraint(
        op.f("ck_visits_visit_financial_evidence_shape"),
        "visits",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_visit_items_visit_item_financial_evidence_shape"),
        "visit_items",
        type_="check",
    )
    _create_visit_shape(3)
    _create_visit_item_shape(3, mixed_price_authority=True)

    op.add_column(
        "sales_line_adjustments",
        sa.Column("uom_id", sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        "fk_sales_line_adjustment_uom",
        "sales_line_adjustments",
        "uom",
        ["uom_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_sales_line_adjustment_sequence",
        "sales_line_adjustments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sales_line_adjustment_sequence_uom",
        "sales_line_adjustments",
        ["company_id", "visit_item_id", "sequence", "uom_id"],
    )

    op.create_table(
        "sales_line_price_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("visit_item_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("uom_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("base_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("price_entry_id", sa.Integer(), nullable=False),
        sa.Column("price_publication_revision", sa.Integer(), nullable=False),
        sa.Column("assignment_revision", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("gross_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="sales_line_price_component_sequence_positive",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="sales_line_price_component_quantity_positive",
        ),
        sa.CheckConstraint(
            "base_quantity > 0",
            name="sales_line_price_component_base_quantity_positive",
        ),
        sa.CheckConstraint(
            "price_publication_revision > 0",
            name="sales_line_price_component_publication_revision_positive",
        ),
        sa.CheckConstraint(
            "assignment_revision > 0",
            name="sales_line_price_component_assignment_revision_positive",
        ),
        sa.CheckConstraint(
            "unit_price >= 0",
            name="sales_line_price_component_unit_price_nonnegative",
        ),
        sa.CheckConstraint(
            "gross_amount >= 0",
            name="sales_line_price_component_gross_nonnegative",
        ),
        sa.CheckConstraint(
            "gross_amount = round(quantity * unit_price, 6)",
            name="sales_line_price_component_gross_exact",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_line_price_component_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "visit_item_id"],
            ["visit_items.company_id", "visit_items.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_price_component_tenant_line",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "price_entry_id"],
            ["price_book_entries.company_id", "price_book_entries.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_price_component_tenant_price_entry",
        ),
        sa.ForeignKeyConstraint(
            ["uom_id"],
            ["uom.id"],
            ondelete="RESTRICT",
            name="fk_sales_line_price_component_uom",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name="uq_sales_line_price_components_company_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "visit_item_id",
            "sequence",
            name="uq_sales_line_price_component_sequence",
        ),
        sa.UniqueConstraint(
            "company_id",
            "visit_item_id",
            "uom_id",
            name="uq_sales_line_price_component_uom",
        ),
    )
    op.create_index(
        "ix_sales_line_price_component_line",
        "sales_line_price_components",
        ["company_id", "visit_item_id", "sequence"],
    )
    _harden_rls("sales_line_price_components")

    op.execute(
        """
        CREATE TRIGGER trg_sales_line_price_component_insert_only
        BEFORE INSERT OR UPDATE OR DELETE ON sales_line_price_components
        FOR EACH ROW EXECUTE FUNCTION guard_sales_line_child_evidence()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_sales_line_price_component_parent_frozen
        AFTER INSERT ON sales_line_price_components
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ensure_sales_line_parent_frozen()
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
            price_gross_total numeric(20,6);
            price_base_total numeric(20,6);
            price_count integer;
            price_min_sequence integer;
            price_max_sequence integer;
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
                COALESCE(SUM(gross_amount), 0),
                COALESCE(SUM(base_quantity), 0),
                COUNT(*),
                MIN(sequence),
                MAX(sequence)
            INTO
                price_gross_total,
                price_base_total,
                price_count,
                price_min_sequence,
                price_max_sequence
            FROM sales_line_price_components
            WHERE company_id = NEW.company_id
              AND visit_item_id = NEW.id;

            IF price_count <= 0 THEN
                RAISE EXCEPTION 'frozen sales line requires typed price evidence'
                    USING ERRCODE = '23514';
            END IF;
            IF price_min_sequence <> 1 OR price_max_sequence <> price_count THEN
                RAISE EXCEPTION 'price component sequence must be contiguous from 1'
                    USING ERRCODE = '23514';
            END IF;
            IF price_base_total <> NEW.canonical_quantity THEN
                RAISE EXCEPTION 'typed price components do not reconcile to canonical quantity'
                    USING ERRCODE = '23514';
            END IF;
            IF price_gross_total <> NEW.gross_amount THEN
                RAISE EXCEPTION 'typed price components do not reconcile to line gross'
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
        $$;
        """
    )


def downgrade() -> None:
    _assert_no_frozen_evidence()

    op.execute(
        "DROP TRIGGER IF EXISTS trg_sales_line_price_component_parent_frozen "
        "ON sales_line_price_components"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sales_line_price_component_insert_only "
        "ON sales_line_price_components"
    )
    op.execute(
        'DROP POLICY IF EXISTS stage6f_tenant_guard '
        'ON "sales_line_price_components"'
    )
    op.execute(
        'DROP POLICY IF EXISTS stage6f_tenant_isolation '
        'ON "sales_line_price_components"'
    )
    op.drop_table("sales_line_price_components")

    op.drop_constraint(
        "uq_sales_line_adjustment_sequence_uom",
        "sales_line_adjustments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sales_line_adjustment_sequence",
        "sales_line_adjustments",
        ["company_id", "visit_item_id", "sequence"],
    )
    op.drop_constraint(
        "fk_sales_line_adjustment_uom",
        "sales_line_adjustments",
        type_="foreignkey",
    )
    op.drop_column(
        "sales_line_adjustments",
        "uom_id",
    )

    op.drop_constraint(
        op.f("ck_visit_items_visit_item_financial_evidence_shape"),
        "visit_items",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_visits_visit_financial_evidence_shape"),
        "visits",
        type_="check",
    )
    _create_visit_item_shape(1, mixed_price_authority=False)
    _create_visit_shape(1)

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
        $$;
        """
    )
