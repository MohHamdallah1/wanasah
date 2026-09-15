"""stage6 financial snapshot authority hardening

Revision ID: c9f5a7b3d2e4
Revises: b8e4c6d2f1a3
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c9f5a7b3d2e4"
down_revision: Union[str, Sequence[str], None] = "b8e4c6d2f1a3"
branch_labels = None
depends_on = None


_OLD_VISIT_GUARD = r"""
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


_NEW_VISIT_GUARD = r"""
CREATE OR REPLACE FUNCTION guard_visit_financial_evidence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    revision sales_visit_revisions%ROWTYPE;
    latest_revision_id integer;
    has_history boolean;
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

    SELECT EXISTS (
        SELECT 1
        FROM sales_visit_revisions
        WHERE company_id = OLD.company_id
          AND visit_id = OLD.id
    )
    INTO has_history;

    IF has_history AND (
        NEW.company_id IS DISTINCT FROM OLD.company_id
        OR NEW.driver_id IS DISTINCT FROM OLD.driver_id
        OR NEW.shop_id IS DISTINCT FROM OLD.shop_id
        OR NEW.work_session_id IS DISTINCT FROM OLD.work_session_id
        OR NEW.operational_date IS DISTINCT FROM OLD.operational_date
    ) THEN
        RAISE EXCEPTION 'visit identity is immutable once sales revisions exist'
            USING ERRCODE = '55000';
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

    SELECT id
    INTO latest_revision_id
    FROM sales_visit_revisions
    WHERE company_id = NEW.company_id
      AND visit_id = NEW.id
    ORDER BY revision_number DESC, id DESC
    LIMIT 1;

    IF latest_revision_id IS DISTINCT FROM NEW.current_sales_revision_id THEN
        RAISE EXCEPTION 'visit current sales revision must be the latest immutable revision'
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


_REVISION_INSERT_GUARD = r"""
CREATE OR REPLACE FUNCTION validate_sales_visit_revision_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    visit_row visits%ROWTYPE;
    context_row route_commercial_contexts%ROWTYPE;
    latest_id integer;
    latest_number integer;
    latest_frozen_at timestamptz;
BEGIN
    SELECT *
    INTO visit_row
    FROM visits
    WHERE company_id = NEW.company_id
      AND id = NEW.visit_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'sales revision parent visit not found'
            USING ERRCODE = '23503';
    END IF;

    IF visit_row.current_sales_revision_id IS NOT NULL
       OR visit_row.financial_evidence_version IS NOT NULL
    THEN
        RAISE EXCEPTION 'visit must be reversed before a correction revision can be appended'
            USING ERRCODE = '55000';
    END IF;

    SELECT id, revision_number, frozen_at
    INTO latest_id, latest_number, latest_frozen_at
    FROM sales_visit_revisions
    WHERE company_id = NEW.company_id
      AND visit_id = NEW.visit_id
    ORDER BY revision_number DESC, id DESC
    LIMIT 1;

    IF latest_id IS NULL THEN
        IF NEW.revision_number <> 1
           OR NEW.supersedes_revision_id IS NOT NULL
        THEN
            RAISE EXCEPTION 'first sales revision must be revision 1 with no predecessor'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF latest_frozen_at IS NULL THEN
            RAISE EXCEPTION 'previous sales revision must be frozen before correction'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.revision_number <> latest_number + 1
           OR NEW.supersedes_revision_id IS DISTINCT FROM latest_id
        THEN
            RAISE EXCEPTION 'sales revision chain must append exactly to the latest revision'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    SELECT *
    INTO context_row
    FROM route_commercial_contexts
    WHERE company_id = NEW.company_id
      AND id = NEW.commercial_context_id
    FOR KEY SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'sales revision commercial context not found'
            USING ERRCODE = '23503';
    END IF;

    IF NEW.price_publication_revision_ceiling
            IS DISTINCT FROM context_row.price_publication_revision
       OR NEW.assignment_revision_ceiling
            IS DISTINCT FROM context_row.assignment_revision
       OR NEW.offer_revision_ceiling
            IS DISTINCT FROM context_row.offer_ruleset_version
       OR NEW.tax_revision_ceiling
            IS DISTINCT FROM context_row.tax_ruleset_version
       OR NEW.transaction_currency_code
            IS DISTINCT FROM upper(context_row.transaction_currency_code)
       OR NEW.functional_currency_code
            IS DISTINCT FROM upper(context_row.functional_currency_code)
       OR NEW.rounding_policy_version
            IS DISTINCT FROM context_row.rounding_policy_version
       OR NEW.commercial_calculated_at < context_row.pricing_locked_at
    THEN
        RAISE EXCEPTION 'sales revision does not match immutable route commercial context'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;
"""


_ASSERT_SNAPSHOT = r"""
CREATE OR REPLACE FUNCTION assert_sales_visit_revision_snapshot(
    p_company_id integer,
    p_revision_id integer
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    current_row sales_visit_revisions%ROWTYPE;
    context_row route_commercial_contexts%ROWTYPE;

    line_count integer;
    frozen_line_count integer;
    line_envelope_mismatch integer;
    gross_total numeric(20,6);
    discount_total numeric(20,6);
    post_offer_total numeric(20,6);
    taxable_total numeric(20,6);
    tax_total numeric(20,6);
    line_total numeric(20,6);

    price_semantic_mismatch integer;
    adjustment_source_mismatch integer;
    tax_source_mismatch integer;

    applied_offer_count integer;
    applied_offer_mismatch integer;

    reward_count integer;
    reward_snapshot_count integer;
    reward_snapshot_mismatch integer;
    reward_semantic_mismatch integer;
BEGIN
    SELECT *
    INTO current_row
    FROM sales_visit_revisions
    WHERE company_id = p_company_id
      AND id = p_revision_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'sales revision snapshot target not found'
            USING ERRCODE = '23503';
    END IF;

    IF current_row.frozen_at IS NULL THEN
        RAISE EXCEPTION 'sales visit revision is not frozen at commit'
            USING ERRCODE = '23514';
    END IF;

    SELECT *
    INTO context_row
    FROM route_commercial_contexts
    WHERE company_id = current_row.company_id
      AND id = current_row.commercial_context_id;

    IF NOT FOUND
       OR current_row.price_publication_revision_ceiling
            IS DISTINCT FROM context_row.price_publication_revision
       OR current_row.assignment_revision_ceiling
            IS DISTINCT FROM context_row.assignment_revision
       OR current_row.offer_revision_ceiling
            IS DISTINCT FROM context_row.offer_ruleset_version
       OR current_row.tax_revision_ceiling
            IS DISTINCT FROM context_row.tax_ruleset_version
       OR current_row.transaction_currency_code
            IS DISTINCT FROM upper(context_row.transaction_currency_code)
       OR current_row.functional_currency_code
            IS DISTINCT FROM upper(context_row.functional_currency_code)
       OR current_row.rounding_policy_version
            IS DISTINCT FROM context_row.rounding_policy_version
       OR current_row.commercial_calculated_at < context_row.pricing_locked_at
    THEN
        RAISE EXCEPTION 'sales revision snapshot does not match immutable route commercial context'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(current_row.offer_snapshot) <> 'object'
       OR (current_row.offer_snapshot ->> 'schema_version')::integer
            IS DISTINCT FROM current_row.evidence_schema_version
       OR (current_row.offer_snapshot ->> 'offer_revision_ceiling')::integer
            IS DISTINCT FROM current_row.offer_revision_ceiling
       OR jsonb_typeof(
            COALESCE(current_row.offer_snapshot -> 'applied_offers', '[]'::jsonb)
          ) <> 'array'
       OR jsonb_typeof(
            COALESCE(current_row.offer_snapshot -> 'free_goods', '[]'::jsonb)
          ) <> 'array'
    THEN
        RAISE EXCEPTION 'sales revision offer snapshot envelope is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT
        COUNT(*),
        COUNT(*) FILTER (WHERE financial_evidence_version = current_row.evidence_schema_version),
        COUNT(*) FILTER (
            WHERE financial_evidence_version IS DISTINCT FROM current_row.evidence_schema_version
               OR financial_evidence_frozen_at IS DISTINCT FROM current_row.frozen_at
               OR commercial_context_id IS DISTINCT FROM current_row.commercial_context_id
               OR transaction_currency_code IS DISTINCT FROM current_row.transaction_currency_code
               OR functional_currency_code IS DISTINCT FROM current_row.functional_currency_code
        ),
        COALESCE(SUM(gross_amount), 0),
        COALESCE(SUM(discount_amount), 0),
        COALESCE(SUM(post_offer_amount), 0),
        COALESCE(SUM(taxable_amount), 0),
        COALESCE(SUM(tax_amount), 0),
        COALESCE(SUM(net_amount), 0)
    INTO
        line_count,
        frozen_line_count,
        line_envelope_mismatch,
        gross_total,
        discount_total,
        post_offer_total,
        taxable_total,
        tax_total,
        line_total
    FROM visit_items
    WHERE company_id = current_row.company_id
      AND visit_id = current_row.visit_id
      AND sales_revision_id = current_row.id;

    IF line_count <= 0
       OR line_count <> frozen_line_count
       OR line_envelope_mismatch <> 0
    THEN
        RAISE EXCEPTION 'sales revision requires coherent frozen line envelopes'
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
    INTO price_semantic_mismatch
    FROM sales_line_price_components pc
    JOIN visit_items line
      ON line.company_id = pc.company_id
     AND line.id = pc.visit_item_id
    LEFT JOIN price_book_entries entry
      ON entry.company_id = pc.company_id
     AND entry.id = pc.price_entry_id
    LEFT JOIN price_publications publication
      ON publication.company_id = entry.company_id
     AND publication.id = entry.publication_id
     AND publication.price_book_id = entry.price_book_id
    LEFT JOIN price_book_assignments assignment
      ON assignment.company_id = pc.company_id
     AND assignment.revision = pc.assignment_revision
    LEFT JOIN price_books book
      ON book.company_id = entry.company_id
     AND book.id = entry.price_book_id
    WHERE line.company_id = current_row.company_id
      AND line.visit_id = current_row.visit_id
      AND line.sales_revision_id = current_row.id
      AND (
          entry.id IS NULL
          OR publication.id IS NULL
          OR assignment.id IS NULL
          OR book.id IS NULL
          OR entry.price_book_id IS DISTINCT FROM assignment.price_book_id
          OR entry.product_variant_id IS DISTINCT FROM line.product_variant_id
          OR entry.uom_id IS DISTINCT FROM pc.uom_id
          OR entry.amount IS DISTINCT FROM pc.unit_price
          OR entry.is_published IS DISTINCT FROM TRUE
          OR NOT (entry.effectivity @> current_row.commercial_calculated_at)
          OR publication.revision IS DISTINCT FROM pc.price_publication_revision
          OR publication.published_at IS NULL
          OR publication.published_at > current_row.commercial_calculated_at
          OR pc.price_publication_revision > current_row.price_publication_revision_ceiling
          OR pc.assignment_revision > current_row.assignment_revision_ceiling
          OR NOT (assignment.effectivity @> current_row.commercial_calculated_at)
          OR upper(book.currency_code)
                IS DISTINCT FROM current_row.transaction_currency_code
      );

    IF price_semantic_mismatch <> 0 THEN
        RAISE EXCEPTION 'typed price evidence does not match immutable pricing authority'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*)
    INTO adjustment_source_mismatch
    FROM sales_line_adjustments adjustment
    JOIN visit_items line
      ON line.company_id = adjustment.company_id
     AND line.id = adjustment.visit_item_id
    LEFT JOIN offer_versions offer
      ON offer.company_id = adjustment.company_id
     AND offer.id = adjustment.offer_version_id
     AND offer.offer_definition_id = adjustment.rule_id
    WHERE line.company_id = current_row.company_id
      AND line.visit_id = current_row.visit_id
      AND line.sales_revision_id = current_row.id
      AND (
          offer.id IS NULL
          OR adjustment.rule_version IS DISTINCT FROM offer.revision
          OR adjustment.rule_type IS DISTINCT FROM offer.offer_type
          OR offer.revision > current_row.offer_revision_ceiling
          OR offer.published_at IS NULL
          OR offer.published_at > current_row.commercial_calculated_at
          OR offer.effective_from > current_row.commercial_calculated_at
          OR (
              offer.effective_to IS NOT NULL
              AND offer.effective_to <= current_row.commercial_calculated_at
          )
          OR (
              offer.cancelled_at IS NOT NULL
              AND offer.cancelled_at <= current_row.commercial_calculated_at
          )
      );

    IF adjustment_source_mismatch <> 0 THEN
        RAISE EXCEPTION 'frozen adjustment source was not valid at calculation time'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*)
    INTO tax_source_mismatch
    FROM sales_line_tax_components tax_evidence
    JOIN visit_items line
      ON line.company_id = tax_evidence.company_id
     AND line.id = tax_evidence.visit_item_id
    LEFT JOIN tax_rule_set_versions tax_version
      ON tax_version.company_id = tax_evidence.company_id
     AND tax_version.id = tax_evidence.tax_rule_set_version_id
     AND tax_version.tax_rule_set_id = tax_evidence.tax_rule_set_id
    WHERE line.company_id = current_row.company_id
      AND line.visit_id = current_row.visit_id
      AND line.sales_revision_id = current_row.id
      AND (
          tax_version.id IS NULL
          OR tax_evidence.tax_revision IS DISTINCT FROM tax_version.revision
          OR tax_version.revision > current_row.tax_revision_ceiling
          OR tax_version.published_at IS NULL
          OR tax_version.published_at > current_row.commercial_calculated_at
          OR tax_version.effective_from > current_row.commercial_calculated_at
          OR (
              tax_version.effective_to IS NOT NULL
              AND tax_version.effective_to <= current_row.commercial_calculated_at
          )
          OR (
              tax_version.cancelled_at IS NOT NULL
              AND tax_version.cancelled_at <= current_row.commercial_calculated_at
          )
      );

    IF tax_source_mismatch <> 0 THEN
        RAISE EXCEPTION 'frozen tax source was not valid at calculation time'
            USING ERRCODE = '23514';
    END IF;

    applied_offer_count = jsonb_array_length(
        COALESCE(current_row.offer_snapshot -> 'applied_offers', '[]'::jsonb)
    );

    SELECT COUNT(*)
    INTO applied_offer_mismatch
    FROM jsonb_array_elements(
        COALESCE(current_row.offer_snapshot -> 'applied_offers', '[]'::jsonb)
    ) snapshot(value)
    LEFT JOIN offer_versions offer
      ON offer.company_id = current_row.company_id
     AND offer.id = (snapshot.value ->> 'offer_version_id')::integer
     AND offer.offer_definition_id
            = (snapshot.value ->> 'offer_definition_id')::integer
    WHERE offer.id IS NULL
       OR (snapshot.value ->> 'offer_revision')::integer
            IS DISTINCT FROM offer.revision
       OR snapshot.value ->> 'offer_type'
            IS DISTINCT FROM offer.offer_type
       OR offer.revision > current_row.offer_revision_ceiling
       OR offer.published_at IS NULL
       OR offer.published_at > current_row.commercial_calculated_at
       OR offer.effective_from > current_row.commercial_calculated_at
       OR (
            offer.effective_to IS NOT NULL
            AND offer.effective_to <= current_row.commercial_calculated_at
       )
       OR (
            offer.cancelled_at IS NOT NULL
            AND offer.cancelled_at <= current_row.commercial_calculated_at
       );

    IF applied_offer_mismatch <> 0 THEN
        RAISE EXCEPTION 'document offer snapshot references invalid historical offer authority'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*)
    INTO reward_count
    FROM sales_reward_evidence
    WHERE company_id = current_row.company_id
      AND visit_id = current_row.visit_id
      AND sales_revision_id = current_row.id;

    reward_snapshot_count = jsonb_array_length(
        COALESCE(current_row.offer_snapshot -> 'free_goods', '[]'::jsonb)
    );
    IF reward_count <> reward_snapshot_count THEN
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
            AND snapshot.value ->> 'offer_type' = reward.offer_type
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

    SELECT COUNT(*)
    INTO reward_semantic_mismatch
    FROM sales_reward_evidence reward
    LEFT JOIN offer_versions offer
      ON offer.company_id = reward.company_id
     AND offer.id = reward.offer_version_id
     AND offer.offer_definition_id = reward.offer_definition_id
    LEFT JOIN price_book_entries entry
      ON entry.company_id = reward.company_id
     AND entry.id = reward.price_entry_id
    LEFT JOIN price_publications publication
      ON publication.company_id = entry.company_id
     AND publication.id = entry.publication_id
     AND publication.price_book_id = entry.price_book_id
    LEFT JOIN price_book_assignments assignment
      ON assignment.company_id = reward.company_id
     AND assignment.revision = reward.assignment_revision
    LEFT JOIN price_books book
      ON book.company_id = entry.company_id
     AND book.id = entry.price_book_id
    WHERE reward.company_id = current_row.company_id
      AND reward.visit_id = current_row.visit_id
      AND reward.sales_revision_id = current_row.id
      AND (
          offer.id IS NULL
          OR entry.id IS NULL
          OR publication.id IS NULL
          OR assignment.id IS NULL
          OR book.id IS NULL
          OR reward.offer_revision IS DISTINCT FROM offer.revision
          OR reward.offer_type IS DISTINCT FROM offer.offer_type
          OR offer.revision > current_row.offer_revision_ceiling
          OR offer.published_at IS NULL
          OR offer.published_at > current_row.commercial_calculated_at
          OR offer.effective_from > current_row.commercial_calculated_at
          OR (
              offer.effective_to IS NOT NULL
              AND offer.effective_to <= current_row.commercial_calculated_at
          )
          OR (
              offer.cancelled_at IS NOT NULL
              AND offer.cancelled_at <= current_row.commercial_calculated_at
          )
          OR entry.product_variant_id IS DISTINCT FROM reward.product_variant_id
          OR entry.uom_id IS DISTINCT FROM reward.uom_id
          OR entry.amount IS DISTINCT FROM reward.unit_price
          OR entry.is_published IS DISTINCT FROM TRUE
          OR NOT (entry.effectivity @> current_row.commercial_calculated_at)
          OR publication.revision IS DISTINCT FROM reward.price_publication_revision
          OR publication.published_at IS NULL
          OR publication.published_at > current_row.commercial_calculated_at
          OR reward.price_publication_revision > current_row.price_publication_revision_ceiling
          OR entry.price_book_id IS DISTINCT FROM assignment.price_book_id
          OR reward.assignment_revision > current_row.assignment_revision_ceiling
          OR NOT (assignment.effectivity @> current_row.commercial_calculated_at)
          OR upper(book.currency_code)
                IS DISTINCT FROM current_row.transaction_currency_code
      );

    IF reward_semantic_mismatch <> 0 THEN
        RAISE EXCEPTION 'reward snapshot does not match immutable offer and pricing authority'
            USING ERRCODE = '23514';
    END IF;

    RETURN;
END;
$$;
"""


_NEW_REVISION_RECONCILE = r"""
CREATE OR REPLACE FUNCTION validate_sales_visit_revision_evidence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    latest_revision_id integer;
    visit_current_revision_id integer;
BEGIN
    PERFORM assert_sales_visit_revision_snapshot(
        NEW.company_id,
        NEW.id
    );

    SELECT id
    INTO latest_revision_id
    FROM sales_visit_revisions
    WHERE company_id = NEW.company_id
      AND visit_id = NEW.visit_id
    ORDER BY revision_number DESC, id DESC
    LIMIT 1;

    IF latest_revision_id = NEW.id THEN
        SELECT current_sales_revision_id
        INTO visit_current_revision_id
        FROM visits
        WHERE company_id = NEW.company_id
          AND id = NEW.visit_id;

        IF visit_current_revision_id IS DISTINCT FROM NEW.id THEN
            RAISE EXCEPTION 'latest frozen sales revision must be the visit current revision at commit'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;
"""


_OLD_REVISION_RECONCILE = r"""
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


def _validate_existing_history() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            tenant_id integer;
            revision_id integer;
            bad_visit integer;
        BEGIN
            FOR tenant_id IN SELECT id FROM companies ORDER BY id LOOP
                PERFORM set_config(
                    'app.current_tenant',
                    tenant_id::text,
                    true
                );

                SELECT visit_id
                INTO bad_visit
                FROM (
                    SELECT
                        r.visit_id,
                        r.id,
                        r.revision_number,
                        r.supersedes_revision_id,
                        row_number() OVER (
                            PARTITION BY r.visit_id
                            ORDER BY r.revision_number, r.id
                        ) AS expected_number,
                        lag(r.id) OVER (
                            PARTITION BY r.visit_id
                            ORDER BY r.revision_number, r.id
                        ) AS expected_predecessor
                    FROM sales_visit_revisions r
                    WHERE r.company_id = tenant_id
                ) chain
                WHERE chain.revision_number <> chain.expected_number
                   OR (
                        chain.expected_number = 1
                        AND chain.supersedes_revision_id IS NOT NULL
                   )
                   OR (
                        chain.expected_number > 1
                        AND chain.supersedes_revision_id
                            IS DISTINCT FROM chain.expected_predecessor
                   )
                LIMIT 1;

                IF bad_visit IS NOT NULL THEN
                    RAISE EXCEPTION
                        'existing sales revision chain is invalid for visit %',
                        bad_visit
                        USING ERRCODE = '23514';
                END IF;

                SELECT v.id
                INTO bad_visit
                FROM visits v
                WHERE v.company_id = tenant_id
                  AND v.current_sales_revision_id IS NOT NULL
                  AND v.current_sales_revision_id IS DISTINCT FROM (
                      SELECT r.id
                      FROM sales_visit_revisions r
                      WHERE r.company_id = v.company_id
                        AND r.visit_id = v.id
                      ORDER BY r.revision_number DESC, r.id DESC
                      LIMIT 1
                  )
                LIMIT 1;

                IF bad_visit IS NOT NULL THEN
                    RAISE EXCEPTION
                        'existing visit points to a stale sales revision: %',
                        bad_visit
                        USING ERRCODE = '23514';
                END IF;

                FOR revision_id IN
                    SELECT id
                    FROM sales_visit_revisions
                    WHERE company_id = tenant_id
                    ORDER BY visit_id, revision_number
                LOOP
                    PERFORM assert_sales_visit_revision_snapshot(
                        tenant_id,
                        revision_id
                    );
                END LOOP;
            END LOOP;

            PERFORM set_config(
                'app.current_tenant',
                '',
                true
            );
        END
        $$;
        """
    )


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_sales_visit_revisions_sales_visit_revision_chain_shape"),
        "sales_visit_revisions",
        """
        (
            revision_number = 1
            AND supersedes_revision_id IS NULL
        )
        OR
        (
            revision_number > 1
            AND supersedes_revision_id IS NOT NULL
        )
        """,
    )

    op.execute(_REVISION_INSERT_GUARD)
    op.execute(
        """
        CREATE TRIGGER trg_sales_visit_revision_insert_contract
        BEFORE INSERT ON sales_visit_revisions
        FOR EACH ROW EXECUTE FUNCTION validate_sales_visit_revision_insert()
        """
    )

    op.execute(_NEW_VISIT_GUARD)
    op.execute(_ASSERT_SNAPSHOT)
    op.execute(_NEW_REVISION_RECONCILE)

    _validate_existing_history()


def downgrade() -> None:
    op.execute(_OLD_REVISION_RECONCILE)
    op.execute("DROP FUNCTION IF EXISTS assert_sales_visit_revision_snapshot(integer, integer)")
    op.execute(_OLD_VISIT_GUARD)

    op.execute(
        "DROP TRIGGER IF EXISTS trg_sales_visit_revision_insert_contract "
        "ON sales_visit_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_sales_visit_revision_insert()")

    op.drop_constraint(
        op.f("ck_sales_visit_revisions_sales_visit_revision_chain_shape"),
        "sales_visit_revisions",
        type_="check",
    )
