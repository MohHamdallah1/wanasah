"""stage6h2b2b1 correction-safe immutable sales revisions

Revision ID: f4c8d2a7b6e3
Revises: e9a7c4d1b5f2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f4c8d2a7b6e3"
down_revision: Union[str, Sequence[str], None] = "e9a7c4d1b5f2"
branch_labels = None
depends_on = None


_TENANT_EXPR = (
    "company_id = NULLIF(current_setting('app.current_tenant', true), '')::integer"
)


def _assert_b2a_evidence_empty() -> None:
    """Fail before any B2B.1 DDL if live immutable evidence already exists."""
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
            OR EXISTS (SELECT 1 FROM sales_line_price_components)
            OR EXISTS (SELECT 1 FROM sales_line_adjustments)
            OR EXISTS (SELECT 1 FROM sales_line_tax_components)
            OR EXISTS (SELECT 1 FROM sales_reward_evidence)
            THEN
                RAISE EXCEPTION
                    'Stage 6H.2B.2B.1 requires the accepted empty B2A evidence baseline';
            END IF;
        END
        $$;
        """
    )


def _assert_b2b1_evidence_empty() -> None:
    """Downgrade is permitted only before the live driver cutover writes evidence."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM visits
                WHERE financial_evidence_version IS NOT NULL
                   OR current_sales_revision_id IS NOT NULL
            )
            OR EXISTS (
                SELECT 1 FROM visit_items
                WHERE financial_evidence_version IS NOT NULL
                   OR sales_revision_id IS NOT NULL
            )
            OR EXISTS (SELECT 1 FROM sales_line_price_components)
            OR EXISTS (SELECT 1 FROM sales_line_adjustments)
            OR EXISTS (SELECT 1 FROM sales_line_tax_components)
            OR EXISTS (SELECT 1 FROM sales_reward_evidence)
            OR EXISTS (SELECT 1 FROM sales_visit_revisions)
            THEN
                RAISE EXCEPTION
                    'Cannot downgrade Stage 6H.2B.2B.1 after immutable sales revision evidence exists';
            END IF;
        END
        $$;
        """
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


def _create_visit_item_shape(*, revision_required: bool) -> None:
    revision_open = (
        "AND sales_revision_id IS NULL"
        if revision_required
        else ""
    )
    revision_frozen = (
        "AND sales_revision_id IS NOT NULL"
        if revision_required
        else ""
    )
    op.create_check_constraint(
        "visit_item_financial_evidence_shape",
        "visit_items",
        f"""
        (
            financial_evidence_version IS NULL
            AND financial_evidence_frozen_at IS NULL
            AND commercial_context_id IS NULL
            {revision_open}
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
            financial_evidence_version = 4
            AND financial_evidence_frozen_at IS NOT NULL
            {revision_frozen}
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
            AND transaction_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
            AND functional_currency_code ~ '^[A-Z][A-Z0-9]{2,9}$'
            AND offer_snapshot IS NOT NULL
            AND jsonb_typeof(offer_snapshot) = 'object'
            AND tax_snapshot IS NOT NULL
            AND jsonb_typeof(tax_snapshot) = 'object'
        )
        """,
    )


def _install_revision_guards() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sales_visit_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'sales visit revision is append-only'
                    USING ERRCODE = '55000';
            END IF;

            IF OLD.frozen_at IS NOT NULL THEN
                RAISE EXCEPTION 'frozen sales visit revision is immutable'
                    USING ERRCODE = '55000';
            END IF;

            IF NOT (
                OLD.frozen_at IS NULL
                AND NEW.frozen_at IS NOT NULL
                AND NEW.company_id IS NOT DISTINCT FROM OLD.company_id
                AND NEW.visit_id IS NOT DISTINCT FROM OLD.visit_id
                AND NEW.revision_number IS NOT DISTINCT FROM OLD.revision_number
                AND NEW.supersedes_revision_id IS NOT DISTINCT FROM OLD.supersedes_revision_id
                AND NEW.evidence_schema_version IS NOT DISTINCT FROM OLD.evidence_schema_version
                AND NEW.commercial_calculated_at IS NOT DISTINCT FROM OLD.commercial_calculated_at
                AND NEW.commercial_context_id IS NOT DISTINCT FROM OLD.commercial_context_id
                AND NEW.transaction_currency_code IS NOT DISTINCT FROM OLD.transaction_currency_code
                AND NEW.functional_currency_code IS NOT DISTINCT FROM OLD.functional_currency_code
                AND NEW.rounding_policy_version IS NOT DISTINCT FROM OLD.rounding_policy_version
                AND NEW.rounding_precision IS NOT DISTINCT FROM OLD.rounding_precision
                AND NEW.rounding_mode IS NOT DISTINCT FROM OLD.rounding_mode
                AND NEW.price_publication_revision_ceiling IS NOT DISTINCT FROM OLD.price_publication_revision_ceiling
                AND NEW.assignment_revision_ceiling IS NOT DISTINCT FROM OLD.assignment_revision_ceiling
                AND NEW.offer_revision_ceiling IS NOT DISTINCT FROM OLD.offer_revision_ceiling
                AND NEW.tax_revision_ceiling IS NOT DISTINCT FROM OLD.tax_revision_ceiling
                AND NEW.gross_amount IS NOT DISTINCT FROM OLD.gross_amount
                AND NEW.discount_amount IS NOT DISTINCT FROM OLD.discount_amount
                AND NEW.post_offer_amount IS NOT DISTINCT FROM OLD.post_offer_amount
                AND NEW.taxable_amount IS NOT DISTINCT FROM OLD.taxable_amount
                AND NEW.tax_amount IS NOT DISTINCT FROM OLD.tax_amount
                AND NEW.line_total_amount IS NOT DISTINCT FROM OLD.line_total_amount
                AND NEW.rounding_adjustment IS NOT DISTINCT FROM OLD.rounding_adjustment
                AND NEW.final_amount IS NOT DISTINCT FROM OLD.final_amount
                AND NEW.offer_snapshot IS NOT DISTINCT FROM OLD.offer_snapshot
                AND NEW.created_at IS NOT DISTINCT FROM OLD.created_at
            ) THEN
                RAISE EXCEPTION 'sales visit revision may only transition once from open to frozen'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sales_visit_revision_immutable
        BEFORE UPDATE OR DELETE ON sales_visit_revisions
        FOR EACH ROW EXECUTE FUNCTION guard_sales_visit_revision()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ensure_sales_visit_revision_frozen()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_frozen_at timestamptz;
        BEGIN
            SELECT frozen_at
            INTO current_frozen_at
            FROM sales_visit_revisions
            WHERE company_id = NEW.company_id
              AND id = NEW.id;

            IF current_frozen_at IS NULL THEN
                RAISE EXCEPTION 'sales visit revision cannot commit while open'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_sales_visit_revision_must_freeze
        AFTER INSERT ON sales_visit_revisions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ensure_sales_visit_revision_frozen()
        """
    )


def _install_reward_revision_guards() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sales_reward_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_frozen_at timestamptz;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'sales reward evidence is insert-only'
                    USING ERRCODE = '55000';
            END IF;

            SELECT frozen_at
            INTO parent_frozen_at
            FROM sales_visit_revisions
            WHERE company_id = NEW.company_id
              AND visit_id = NEW.visit_id
              AND id = NEW.sales_revision_id
            FOR KEY SHARE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'sales reward evidence parent revision not found'
                    USING ERRCODE = '23503';
            END IF;
            IF parent_frozen_at IS NOT NULL THEN
                RAISE EXCEPTION 'cannot append reward evidence to a frozen sales revision'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ensure_sales_reward_parent_frozen()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_frozen_at timestamptz;
        BEGIN
            SELECT frozen_at
            INTO parent_frozen_at
            FROM sales_visit_revisions
            WHERE company_id = NEW.company_id
              AND visit_id = NEW.visit_id
              AND id = NEW.sales_revision_id;

            IF parent_frozen_at IS NULL THEN
                RAISE EXCEPTION 'sales reward evidence cannot commit without a frozen sales revision'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


def _install_visit_item_guard() -> None:
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
                OR NEW.sales_revision_id IS DISTINCT FROM OLD.sales_revision_id
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
        $$;
        """
    )


def _install_revision_reconciliation() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_sales_visit_revision_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_row sales_visit_revisions%ROWTYPE;
            line_count integer;
            frozen_line_count integer;
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
            SELECT *
            INTO current_row
            FROM sales_visit_revisions
            WHERE company_id = NEW.company_id
              AND id = NEW.id;

            IF current_row.frozen_at IS NULL THEN
                RAISE EXCEPTION 'sales visit revision is not frozen at commit'
                    USING ERRCODE = '23514';
            END IF;

            SELECT
                COUNT(*),
                COUNT(*) FILTER (WHERE financial_evidence_version = 4),
                COALESCE(SUM(gross_amount), 0),
                COALESCE(SUM(discount_amount), 0),
                COALESCE(SUM(post_offer_amount), 0),
                COALESCE(SUM(taxable_amount), 0),
                COALESCE(SUM(tax_amount), 0),
                COALESCE(SUM(net_amount), 0)
            INTO
                line_count, frozen_line_count, gross_total, discount_total,
                post_offer_total, taxable_total, tax_total, line_total
            FROM visit_items
            WHERE company_id = current_row.company_id
              AND visit_id = current_row.visit_id
              AND sales_revision_id = current_row.id;

            IF line_count <= 0 OR line_count <> frozen_line_count THEN
                RAISE EXCEPTION 'sales revision requires only frozen paid sale lines'
                    USING ERRCODE = '23514';
            END IF;

            IF gross_total <> current_row.gross_amount
               OR discount_total <> current_row.discount_amount
               OR post_offer_total <> current_row.post_offer_amount
               OR taxable_total <> current_row.taxable_amount
               OR tax_total <> current_row.tax_amount
               OR line_total <> current_row.line_total_amount
               OR current_row.final_amount
                    <> current_row.line_total_amount + current_row.rounding_adjustment
            THEN
                RAISE EXCEPTION 'sales revision header does not reconcile to frozen sale lines'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO reward_count
            FROM sales_reward_evidence
            WHERE company_id = current_row.company_id
              AND visit_id = current_row.visit_id
              AND sales_revision_id = current_row.id;

            snapshot_reward_count = jsonb_array_length(
                COALESCE(current_row.offer_snapshot -> 'free_goods', '[]'::jsonb)
            );
            IF reward_count <> snapshot_reward_count THEN
                RAISE EXCEPTION 'sales revision reward count does not reconcile to offer snapshot'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO reward_snapshot_mismatch
            FROM sales_reward_evidence reward
            WHERE reward.company_id = current_row.company_id
              AND reward.visit_id = current_row.visit_id
              AND reward.sales_revision_id = current_row.id
              AND NOT EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(
                      COALESCE(current_row.offer_snapshot -> 'free_goods', '[]'::jsonb)
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
                RAISE EXCEPTION 'sales revision reward evidence does not match offer snapshot'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_sales_visit_revision_reconcile
        AFTER INSERT OR UPDATE ON sales_visit_revisions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION validate_sales_visit_revision_evidence()
        """
    )


def _install_visit_projection_guard() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_visit_financial_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            revision sales_visit_revisions%ROWTYPE;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF EXISTS (
                    SELECT 1
                    FROM sales_visit_revisions
                    WHERE company_id = OLD.company_id
                      AND visit_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'visit with immutable sales revisions cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;

            IF NEW.current_sales_revision_id IS NULL THEN
                IF NEW.financial_evidence_version IS NOT NULL THEN
                    RAISE EXCEPTION 'visit commercial projection cannot be frozen without a current sales revision'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            SELECT *
            INTO revision
            FROM sales_visit_revisions
            WHERE company_id = NEW.company_id
              AND visit_id = NEW.id
              AND id = NEW.current_sales_revision_id;

            IF NOT FOUND OR revision.frozen_at IS NULL THEN
                RAISE EXCEPTION 'visit current sales revision is missing or open'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.financial_evidence_version IS DISTINCT FROM revision.evidence_schema_version
               OR NEW.financial_evidence_frozen_at IS DISTINCT FROM revision.frozen_at
               OR NEW.commercial_calculated_at IS DISTINCT FROM revision.commercial_calculated_at
               OR NEW.commercial_context_id IS DISTINCT FROM revision.commercial_context_id
               OR NEW.transaction_currency_code IS DISTINCT FROM revision.transaction_currency_code
               OR NEW.functional_currency_code IS DISTINCT FROM revision.functional_currency_code
               OR NEW.rounding_policy_version IS DISTINCT FROM revision.rounding_policy_version
               OR NEW.rounding_precision IS DISTINCT FROM revision.rounding_precision
               OR NEW.rounding_mode IS DISTINCT FROM revision.rounding_mode
               OR NEW.price_publication_revision_ceiling IS DISTINCT FROM revision.price_publication_revision_ceiling
               OR NEW.assignment_revision_ceiling IS DISTINCT FROM revision.assignment_revision_ceiling
               OR NEW.offer_revision_ceiling IS DISTINCT FROM revision.offer_revision_ceiling
               OR NEW.tax_revision_ceiling IS DISTINCT FROM revision.tax_revision_ceiling
               OR NEW.amount_before_tax_and_discount IS DISTINCT FROM revision.gross_amount
               OR NEW.discount_applied IS DISTINCT FROM revision.discount_amount
               OR NEW.post_offer_amount IS DISTINCT FROM revision.post_offer_amount
               OR NEW.taxable_amount IS DISTINCT FROM revision.taxable_amount
               OR NEW.tax_amount IS DISTINCT FROM revision.tax_amount
               OR NEW.line_total_amount IS DISTINCT FROM revision.line_total_amount
               OR NEW.rounding_adjustment IS DISTINCT FROM revision.rounding_adjustment
               OR NEW.final_amount_due IS DISTINCT FROM revision.final_amount
               OR NEW.offer_snapshot IS DISTINCT FROM revision.offer_snapshot
            THEN
                RAISE EXCEPTION 'visit commercial projection does not match immutable current sales revision'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_frozen_visit_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            revision_id integer;
            revision_frozen_at timestamptz;
        BEGIN
            revision_id = NEW.current_sales_revision_id;

            IF revision_id IS NULL THEN
                IF NEW.financial_evidence_version IS NOT NULL THEN
                    RAISE EXCEPTION 'visit evidence version exists without current sales revision'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            SELECT frozen_at
            INTO revision_frozen_at
            FROM sales_visit_revisions
            WHERE company_id = NEW.company_id
              AND visit_id = NEW.id
              AND id = revision_id;

            IF revision_frozen_at IS NULL THEN
                RAISE EXCEPTION 'visit current sales revision must be frozen'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )



def _restore_b2a_visit_guards() -> None:
    """Restore the exact one-shot Visit/VisitItem authority used by B2A."""
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
        $$;
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
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_frozen_visit_evidence()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
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
        $$;
        """
    )

def upgrade() -> None:
    _assert_b2a_evidence_empty()

    op.create_table(
        "sales_visit_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("visit_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("supersedes_revision_id", sa.Integer(), nullable=True),
        sa.Column("evidence_schema_version", sa.Integer(), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commercial_calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("commercial_context_id", sa.Integer(), nullable=False),
        sa.Column("transaction_currency_code", sa.String(10), nullable=False),
        sa.Column("functional_currency_code", sa.String(10), nullable=False),
        sa.Column("rounding_policy_version", sa.Integer(), nullable=False),
        sa.Column("rounding_precision", sa.Integer(), nullable=False),
        sa.Column("rounding_mode", sa.String(20), nullable=False),
        sa.Column("price_publication_revision_ceiling", sa.Integer(), nullable=False),
        sa.Column("assignment_revision_ceiling", sa.Integer(), nullable=False),
        sa.Column("offer_revision_ceiling", sa.Integer(), nullable=False),
        sa.Column("tax_revision_ceiling", sa.Integer(), nullable=False),
        sa.Column("gross_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("discount_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("post_offer_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("taxable_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("tax_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("line_total_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("rounding_adjustment", sa.Numeric(20, 6), nullable=False),
        sa.Column("final_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("offer_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="sales_visit_revision_number_positive",
        ),
        sa.CheckConstraint(
            "evidence_schema_version = 4",
            name="sales_visit_revision_schema_v4",
        ),
        sa.CheckConstraint(
            "rounding_policy_version > 0",
            name="sales_visit_revision_rounding_version_positive",
        ),
        sa.CheckConstraint(
            "rounding_precision BETWEEN 0 AND 6",
            name="sales_visit_revision_rounding_precision",
        ),
        sa.CheckConstraint(
            "rounding_mode IN ('HALF_UP','HALF_EVEN')",
            name="sales_visit_revision_rounding_mode",
        ),
        sa.CheckConstraint(
            "price_publication_revision_ceiling > 0",
            name="sales_visit_revision_price_revision_positive",
        ),
        sa.CheckConstraint(
            "assignment_revision_ceiling > 0",
            name="sales_visit_revision_assignment_revision_positive",
        ),
        sa.CheckConstraint(
            "offer_revision_ceiling >= 0",
            name="sales_visit_revision_offer_revision_nonnegative",
        ),
        sa.CheckConstraint(
            "tax_revision_ceiling > 0",
            name="sales_visit_revision_tax_revision_positive",
        ),
        sa.CheckConstraint(
            "gross_amount >= 0 AND discount_amount >= 0 "
            "AND post_offer_amount >= 0 AND taxable_amount >= 0 "
            "AND tax_amount >= 0 AND line_total_amount >= 0 "
            "AND final_amount >= 0",
            name="sales_visit_revision_money_nonnegative",
        ),
        sa.CheckConstraint(
            "post_offer_amount = gross_amount - discount_amount",
            name="sales_visit_revision_offer_reconcile",
        ),
        sa.CheckConstraint(
            "line_total_amount = taxable_amount + tax_amount",
            name="sales_visit_revision_tax_reconcile",
        ),
        sa.CheckConstraint(
            "final_amount = line_total_amount + rounding_adjustment",
            name="sales_visit_revision_final_reconcile",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(offer_snapshot) = 'object'",
            name="sales_visit_revision_offer_snapshot_object",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_visit_revision_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "visit_id"],
            ["visits.company_id", "visits.id"],
            ondelete="RESTRICT",
            name="fk_sales_visit_revision_tenant_visit",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "commercial_context_id"],
            ["route_commercial_contexts.company_id", "route_commercial_contexts.id"],
            ondelete="RESTRICT",
            name="fk_sales_visit_revision_tenant_context",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name="uq_sales_visit_revisions_company_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "visit_id",
            "id",
            name="uq_sales_visit_revisions_tenant_visit_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "visit_id",
            "revision_number",
            name="uq_sales_visit_revision_number",
        ),
    )
    op.create_foreign_key(
        "fk_sales_visit_revision_supersedes",
        "sales_visit_revisions",
        "sales_visit_revisions",
        ["company_id", "visit_id", "supersedes_revision_id"],
        ["company_id", "visit_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_sales_visit_revision_visit",
        "sales_visit_revisions",
        ["company_id", "visit_id", "revision_number"],
    )
    _harden_rls("sales_visit_revisions")

    op.add_column(
        "visits",
        sa.Column("current_sales_revision_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_visits_current_sales_revision_id",
        "visits",
        ["current_sales_revision_id"],
    )
    op.create_foreign_key(
        "fk_visit_tenant_current_sales_revision",
        "visits",
        "sales_visit_revisions",
        ["company_id", "id", "current_sales_revision_id"],
        ["company_id", "visit_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "visit_current_sales_revision_shape",
        "visits",
        """
        (
            current_sales_revision_id IS NULL
            AND financial_evidence_version IS NULL
        )
        OR
        (
            current_sales_revision_id IS NOT NULL
            AND financial_evidence_version = 4
        )
        """,
    )

    op.add_column(
        "visit_items",
        sa.Column("sales_revision_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_visit_items_sales_revision_id",
        "visit_items",
        ["sales_revision_id"],
    )
    op.create_foreign_key(
        "fk_visit_item_tenant_sales_revision",
        "visit_items",
        "sales_visit_revisions",
        ["company_id", "visit_id", "sales_revision_id"],
        ["company_id", "visit_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        op.f("ck_visit_items_visit_item_financial_evidence_shape"),
        "visit_items",
        type_="check",
    )
    _create_visit_item_shape(revision_required=True)

    op.add_column(
        "sales_reward_evidence",
        sa.Column("sales_revision_id", sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        "fk_sales_reward_evidence_tenant_revision",
        "sales_reward_evidence",
        "sales_visit_revisions",
        ["company_id", "visit_id", "sales_revision_id"],
        ["company_id", "visit_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_sales_reward_evidence_visit_sequence_product_uom",
        "sales_reward_evidence",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sales_reward_evidence_revision_sequence_product_uom",
        "sales_reward_evidence",
        [
            "company_id",
            "sales_revision_id",
            "sequence",
            "product_variant_id",
            "uom_id",
        ],
    )
    op.drop_index(
        "ix_sales_reward_evidence_visit",
        table_name="sales_reward_evidence",
    )
    op.create_index(
        "ix_sales_reward_evidence_visit",
        "sales_reward_evidence",
        ["company_id", "visit_id", "sales_revision_id", "sequence"],
    )

    _install_revision_guards()
    _install_reward_revision_guards()
    _install_visit_item_guard()
    _install_revision_reconciliation()
    _install_visit_projection_guard()


def downgrade() -> None:
    _assert_b2b1_evidence_empty()

    op.execute(
        "DROP TRIGGER IF EXISTS trg_sales_visit_revision_reconcile "
        "ON sales_visit_revisions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS validate_sales_visit_revision_evidence()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sales_visit_revision_must_freeze "
        "ON sales_visit_revisions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS ensure_sales_visit_revision_frozen()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_sales_visit_revision_immutable "
        "ON sales_visit_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_sales_visit_revision()")

    # Restore B2A reward-parent semantics (Visit itself was the one-shot parent).
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

    _restore_b2a_visit_guards()

    op.drop_index(
        "ix_sales_reward_evidence_visit",
        table_name="sales_reward_evidence",
    )
    op.create_index(
        "ix_sales_reward_evidence_visit",
        "sales_reward_evidence",
        ["company_id", "visit_id", "sequence"],
    )
    op.drop_constraint(
        "uq_sales_reward_evidence_revision_sequence_product_uom",
        "sales_reward_evidence",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sales_reward_evidence_visit_sequence_product_uom",
        "sales_reward_evidence",
        ["company_id", "visit_id", "sequence", "product_variant_id", "uom_id"],
    )
    op.drop_constraint(
        "fk_sales_reward_evidence_tenant_revision",
        "sales_reward_evidence",
        type_="foreignkey",
    )
    op.drop_column("sales_reward_evidence", "sales_revision_id")

    op.drop_constraint(
        op.f("ck_visit_items_visit_item_financial_evidence_shape"),
        "visit_items",
        type_="check",
    )
    _create_visit_item_shape(revision_required=False)
    op.drop_constraint(
        "fk_visit_item_tenant_sales_revision",
        "visit_items",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_visit_items_sales_revision_id",
        table_name="visit_items",
    )
    op.drop_column("visit_items", "sales_revision_id")

    op.drop_constraint(
        op.f("ck_visits_visit_current_sales_revision_shape"),
        "visits",
        type_="check",
    )
    op.drop_constraint(
        "fk_visit_tenant_current_sales_revision",
        "visits",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_visits_current_sales_revision_id",
        table_name="visits",
    )
    op.drop_column("visits", "current_sales_revision_id")

    op.execute(
        'DROP POLICY IF EXISTS stage6f_tenant_guard '
        'ON "sales_visit_revisions"'
    )
    op.execute(
        'DROP POLICY IF EXISTS stage6f_tenant_isolation '
        'ON "sales_visit_revisions"'
    )
    op.drop_table("sales_visit_revisions")
