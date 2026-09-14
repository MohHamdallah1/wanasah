"""stage6h2b2a typed reward evidence and auxiliary-line freeze semantics

Revision ID: e9a7c4d1b5f2
Revises: d7e4b2c9a6f1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9a7c4d1b5f2"
down_revision: Union[str, Sequence[str], None] = "d7e4b2c9a6f1"
branch_labels = None
depends_on = None


_TENANT_EXPR = (
    "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
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
            OR EXISTS (SELECT 1 FROM sales_line_price_components)
            THEN
                RAISE EXCEPTION
                    'Stage 6H.2B.2A requires the approved disposable pre-cutover evidence baseline';
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


def _create_visit_item_shape(version: int) -> None:
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
            AND selected_price_entry_id IS NULL
            AND price_publication_revision IS NULL
            AND assignment_revision IS NULL
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


def _harden_rls(table_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
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
        f"""
        CREATE POLICY stage6f_tenant_guard
        ON "{table_name}"
        AS RESTRICTIVE
        FOR ALL
        USING ({_TENANT_EXPR})
        WITH CHECK ({_TENANT_EXPR})
        """
    )


def _create_visit_reconciliation_function(*, allow_auxiliary: bool) -> None:
    if allow_auxiliary:
        body = """
        DECLARE
            sale_count integer;
            frozen_sale_count integer;
            auxiliary_frozen_count integer;
            gross_total numeric(20,6);
            discount_total numeric(20,6);
            post_offer_total numeric(20,6);
            taxable_total numeric(20,6);
            tax_total numeric(20,6);
            line_total numeric(20,6);
            reward_count integer;
            snapshot_reward_count integer;
            reward_snapshot_mismatch integer;
        BEGIN
            IF NEW.financial_evidence_version IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT
                COUNT(*) FILTER (
                    WHERE NOT is_cancelled
                      AND (quantity > 0 OR packs_quantity > 0)
                ),
                COUNT(*) FILTER (
                    WHERE NOT is_cancelled
                      AND (quantity > 0 OR packs_quantity > 0)
                      AND financial_evidence_version IS NOT NULL
                ),
                COUNT(*) FILTER (
                    WHERE NOT is_cancelled
                      AND quantity = 0
                      AND packs_quantity = 0
                      AND financial_evidence_version IS NOT NULL
                ),
                COALESCE(SUM(gross_amount) FILTER (
                    WHERE NOT is_cancelled
                      AND (quantity > 0 OR packs_quantity > 0)
                ), 0),
                COALESCE(SUM(discount_amount) FILTER (
                    WHERE NOT is_cancelled
                      AND (quantity > 0 OR packs_quantity > 0)
                ), 0),
                COALESCE(SUM(post_offer_amount) FILTER (
                    WHERE NOT is_cancelled
                      AND (quantity > 0 OR packs_quantity > 0)
                ), 0),
                COALESCE(SUM(taxable_amount) FILTER (
                    WHERE NOT is_cancelled
                      AND (quantity > 0 OR packs_quantity > 0)
                ), 0),
                COALESCE(SUM(tax_amount) FILTER (
                    WHERE NOT is_cancelled
                      AND (quantity > 0 OR packs_quantity > 0)
                ), 0),
                COALESCE(SUM(net_amount) FILTER (
                    WHERE NOT is_cancelled
                      AND (quantity > 0 OR packs_quantity > 0)
                ), 0)
            INTO
                sale_count, frozen_sale_count, auxiliary_frozen_count,
                gross_total, discount_total, post_offer_total,
                taxable_total, tax_total, line_total
            FROM visit_items
            WHERE company_id = NEW.company_id
              AND visit_id = NEW.id;

            IF sale_count <= 0 OR sale_count <> frozen_sale_count THEN
                RAISE EXCEPTION 'all active sale lines must be frozen with the visit'
                    USING ERRCODE = '23514';
            END IF;
            IF auxiliary_frozen_count <> 0 THEN
                RAISE EXCEPTION 'sample-only auxiliary lines must not carry financial evidence'
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
                RAISE EXCEPTION 'visit header does not reconcile to active frozen sale lines'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO reward_count
            FROM sales_reward_evidence
            WHERE company_id = NEW.company_id
              AND visit_id = NEW.id;

            snapshot_reward_count = jsonb_array_length(
                COALESCE(NEW.offer_snapshot -> 'free_goods', '[]'::jsonb)
            );
            IF reward_count <> snapshot_reward_count THEN
                RAISE EXCEPTION 'typed reward evidence count does not reconcile to offer snapshot'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO reward_snapshot_mismatch
            FROM sales_reward_evidence reward
            WHERE reward.company_id = NEW.company_id
              AND reward.visit_id = NEW.id
              AND NOT EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(
                      COALESCE(NEW.offer_snapshot -> 'free_goods', '[]'::jsonb)
                  ) AS snapshot(value)
                  WHERE (snapshot.value ->> 'sequence')::integer = reward.sequence
                    AND (snapshot.value ->> 'offer_version_id')::integer = reward.offer_version_id
                    AND (snapshot.value ->> 'offer_definition_id')::integer = reward.offer_definition_id
                    AND (snapshot.value ->> 'offer_revision')::integer = reward.offer_revision
                    AND (snapshot.value ->> 'product_variant_id')::integer = reward.product_variant_id
                    AND (snapshot.value ->> 'uom_id')::integer = reward.uom_id
                    AND (snapshot.value ->> 'quantity')::numeric = reward.quantity
                    AND (snapshot.value ->> 'base_quantity')::numeric = reward.base_quantity
                    AND (snapshot.value ->> 'price_entry_id')::integer = reward.price_entry_id
                    AND (snapshot.value ->> 'price_publication_revision')::integer
                        = reward.price_publication_revision
                    AND (snapshot.value ->> 'assignment_revision')::integer
                        = reward.assignment_revision
                    AND (snapshot.value ->> 'unit_price')::numeric = reward.unit_price
                    AND (snapshot.value ->> 'reward_value')::numeric = reward.reward_value
              );

            IF reward_snapshot_mismatch <> 0 THEN
                RAISE EXCEPTION 'typed reward evidence does not match offer snapshot'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        """
    else:
        body = """
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
        """

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION validate_frozen_visit_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        {body}
        $$;
        """
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
    _create_visit_shape(4)
    _create_visit_item_shape(4)

    op.create_table(
        "sales_reward_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("visit_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("offer_version_id", sa.Integer(), nullable=False),
        sa.Column("offer_definition_id", sa.Integer(), nullable=False),
        sa.Column("offer_revision", sa.Integer(), nullable=False),
        sa.Column("offer_type", sa.String(40), nullable=False),
        sa.Column("product_variant_id", sa.Integer(), nullable=False),
        sa.Column("uom_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("base_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("price_entry_id", sa.Integer(), nullable=False),
        sa.Column("price_publication_revision", sa.Integer(), nullable=False),
        sa.Column("assignment_revision", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("reward_value", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="sales_reward_evidence_sequence_positive",
        ),
        sa.CheckConstraint(
            "offer_revision > 0",
            name="sales_reward_evidence_offer_revision_positive",
        ),
        sa.CheckConstraint(
            "offer_type IN "
            "('PERCENTAGE_DISCOUNT','FIXED_DISCOUNT','BUY_X_GET_Y',"
            "'FREE_GOODS','QUANTITY_TIERS','BUNDLE')",
            name="sales_reward_evidence_offer_type_valid",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="sales_reward_evidence_quantity_positive",
        ),
        sa.CheckConstraint(
            "base_quantity > 0",
            name="sales_reward_evidence_base_quantity_positive",
        ),
        sa.CheckConstraint(
            "price_publication_revision > 0",
            name="sales_reward_evidence_publication_revision_positive",
        ),
        sa.CheckConstraint(
            "assignment_revision > 0",
            name="sales_reward_evidence_assignment_revision_positive",
        ),
        sa.CheckConstraint(
            "unit_price >= 0",
            name="sales_reward_evidence_unit_price_nonnegative",
        ),
        sa.CheckConstraint(
            "reward_value >= 0",
            name="sales_reward_evidence_value_nonnegative",
        ),
        sa.CheckConstraint(
            "reward_value = round(quantity * unit_price, 6)",
            name="sales_reward_evidence_value_exact",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_reward_evidence_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "visit_id"],
            ["visits.company_id", "visits.id"],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_tenant_visit",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "offer_version_id", "offer_definition_id"],
            [
                "offer_versions.company_id",
                "offer_versions.id",
                "offer_versions.offer_definition_id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_tenant_offer",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_variant_id"],
            ["product_variants.company_id", "product_variants.id"],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_tenant_variant",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "price_entry_id"],
            ["price_book_entries.company_id", "price_book_entries.id"],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_tenant_price_entry",
        ),
        sa.ForeignKeyConstraint(
            ["uom_id"],
            ["uom.id"],
            ondelete="RESTRICT",
            name="fk_sales_reward_evidence_uom",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name="uq_sales_reward_evidence_company_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "visit_id",
            "sequence",
            "product_variant_id",
            "uom_id",
            name="uq_sales_reward_evidence_visit_sequence_product_uom",
        ),
    )
    op.create_index(
        "ix_sales_reward_evidence_visit",
        "sales_reward_evidence",
        ["company_id", "visit_id", "sequence"],
    )
    _harden_rls("sales_reward_evidence")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sales_reward_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_version integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'sales reward evidence is insert-only'
                    USING ERRCODE = '55000';
            END IF;

            SELECT financial_evidence_version
            INTO parent_version
            FROM visits
            WHERE company_id = NEW.company_id
              AND id = NEW.visit_id
            FOR KEY SHARE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'sales reward evidence parent visit not found'
                    USING ERRCODE = '23503';
            END IF;
            IF parent_version IS NOT NULL THEN
                RAISE EXCEPTION 'cannot append reward evidence to a frozen visit'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sales_reward_evidence_insert_only
        BEFORE INSERT OR UPDATE OR DELETE ON sales_reward_evidence
        FOR EACH ROW EXECUTE FUNCTION guard_sales_reward_evidence()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ensure_sales_reward_parent_frozen()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_version integer;
        BEGIN
            SELECT financial_evidence_version
            INTO parent_version
            FROM visits
            WHERE company_id = NEW.company_id
              AND id = NEW.visit_id;

            IF parent_version IS NULL THEN
                RAISE EXCEPTION 'sales reward evidence cannot commit without a frozen visit'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_sales_reward_evidence_parent_frozen
        AFTER INSERT ON sales_reward_evidence
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ensure_sales_reward_parent_frozen()
        """
    )

    _create_visit_reconciliation_function(allow_auxiliary=True)


def downgrade() -> None:
    _assert_no_frozen_evidence()

    _create_visit_reconciliation_function(allow_auxiliary=False)

    op.execute(
        "DROP TRIGGER IF EXISTS trg_sales_reward_evidence_parent_frozen "
        "ON sales_reward_evidence"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sales_reward_evidence_insert_only "
        "ON sales_reward_evidence"
    )
    op.execute("DROP FUNCTION IF EXISTS ensure_sales_reward_parent_frozen()")
    op.execute("DROP FUNCTION IF EXISTS guard_sales_reward_evidence()")
    op.execute(
        'DROP POLICY IF EXISTS stage6f_tenant_guard '
        'ON "sales_reward_evidence"'
    )
    op.execute(
        'DROP POLICY IF EXISTS stage6f_tenant_isolation '
        'ON "sales_reward_evidence"'
    )
    op.drop_table("sales_reward_evidence")

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
    _create_visit_shape(3)
    _create_visit_item_shape(3)
