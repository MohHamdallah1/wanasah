"""stage6 sales line evidence semantic hardening

Revision ID: b8e4c6d2f1a3
Revises: a7d3e5f1c9b2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8e4c6d2f1a3"
down_revision: Union[str, Sequence[str], None] = "a7d3e5f1c9b2"
branch_labels = None
depends_on = None


_OLD_VALIDATOR = r"""
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


_NEW_VALIDATOR = r"""
CREATE OR REPLACE FUNCTION validate_frozen_visit_item_evidence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    parent_revision sales_visit_revisions%ROWTYPE;

    adjustment_total numeric(20,6);
    adjustment_count integer;
    adjustment_semantic_mismatch integer;
    adjustment_snapshot_count integer;
    adjustment_snapshot_mismatch integer;

    price_gross_total numeric(20,6);
    price_base_total numeric(20,6);
    price_count integer;
    price_min_sequence integer;
    price_max_sequence integer;

    component_total numeric(20,6);
    component_count integer;
    min_sequence integer;
    max_sequence integer;
    tax_identity_count integer;
    tax_jurisdiction_count integer;
    tax_distance_count integer;
    tax_semantic_mismatch integer;
    tax_snapshot_count integer;
    tax_snapshot_mismatch integer;
BEGIN
    IF NEW.financial_evidence_version IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT *
    INTO parent_revision
    FROM sales_visit_revisions
    WHERE company_id = NEW.company_id
      AND visit_id = NEW.visit_id
      AND id = NEW.sales_revision_id;

    IF NOT FOUND OR parent_revision.frozen_at IS NULL THEN
        RAISE EXCEPTION 'frozen sales line requires a frozen sales revision'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.offer_snapshot IS NULL
       OR jsonb_typeof(NEW.offer_snapshot) <> 'object'
       OR (NEW.offer_snapshot ->> 'schema_version')::integer
            IS DISTINCT FROM NEW.financial_evidence_version
       OR (NEW.offer_snapshot ->> 'offer_revision_ceiling')::integer
            IS DISTINCT FROM parent_revision.offer_revision_ceiling
    THEN
        RAISE EXCEPTION 'line offer snapshot envelope is invalid'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.tax_snapshot IS NULL
       OR jsonb_typeof(NEW.tax_snapshot) <> 'object'
       OR (NEW.tax_snapshot ->> 'schema_version')::integer
            IS DISTINCT FROM NEW.financial_evidence_version
       OR (NEW.tax_snapshot ->> 'tax_revision_ceiling')::integer
            IS DISTINCT FROM parent_revision.tax_revision_ceiling
    THEN
        RAISE EXCEPTION 'line tax snapshot envelope is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT
        COALESCE(SUM(adjustment_amount), 0),
        COUNT(*)
    INTO adjustment_total, adjustment_count
    FROM sales_line_adjustments
    WHERE company_id = NEW.company_id
      AND visit_item_id = NEW.id;

    IF adjustment_total <> NEW.discount_amount THEN
        RAISE EXCEPTION 'typed adjustments do not reconcile to line discount'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*)
    INTO adjustment_semantic_mismatch
    FROM sales_line_adjustments adjustment
    JOIN offer_versions offer
      ON offer.company_id = adjustment.company_id
     AND offer.id = adjustment.offer_version_id
     AND offer.offer_definition_id = adjustment.rule_id
    WHERE adjustment.company_id = NEW.company_id
      AND adjustment.visit_item_id = NEW.id
      AND (
          adjustment.rule_version IS DISTINCT FROM offer.revision
          OR adjustment.rule_type IS DISTINCT FROM offer.offer_type
          OR offer.revision > parent_revision.offer_revision_ceiling
          OR offer.published_at IS NULL
          OR offer.published_at > parent_revision.commercial_calculated_at
          OR offer.effective_from > parent_revision.commercial_calculated_at
          OR (
              offer.effective_to IS NOT NULL
              AND offer.effective_to <= parent_revision.commercial_calculated_at
          )
          OR NOT EXISTS (
              SELECT 1
              FROM sales_line_price_components price_component
              WHERE price_component.company_id = adjustment.company_id
                AND price_component.visit_item_id = adjustment.visit_item_id
                AND price_component.uom_id = adjustment.uom_id
          )
          OR NOT (adjustment.metadata_snapshot ? 'target_uom_id')
          OR NOT (adjustment.metadata_snapshot ? 'unrounded_basis_amount')
          OR NOT (adjustment.metadata_snapshot ? 'unrounded_adjustment_amount')
          OR (adjustment.metadata_snapshot ->> 'target_uom_id')::integer
                IS DISTINCT FROM adjustment.uom_id
          OR (adjustment.metadata_snapshot ->> 'unrounded_basis_amount')::numeric < 0
          OR (adjustment.metadata_snapshot ->> 'unrounded_adjustment_amount')::numeric < 0
          OR (adjustment.metadata_snapshot ->> 'unrounded_adjustment_amount')::numeric
                > (adjustment.metadata_snapshot ->> 'unrounded_basis_amount')::numeric
      );

    IF adjustment_semantic_mismatch <> 0 THEN
        RAISE EXCEPTION 'typed adjustment semantics do not match immutable offer evidence'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(COALESCE(NEW.offer_snapshot -> 'adjustments', '[]'::jsonb))
       <> 'array'
    THEN
        RAISE EXCEPTION 'line offer snapshot adjustments must be an array'
            USING ERRCODE = '23514';
    END IF;

    adjustment_snapshot_count = jsonb_array_length(
        COALESCE(NEW.offer_snapshot -> 'adjustments', '[]'::jsonb)
    );
    IF adjustment_snapshot_count <> adjustment_count THEN
        RAISE EXCEPTION 'typed adjustment count does not match line offer snapshot'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*)
    INTO adjustment_snapshot_mismatch
    FROM sales_line_adjustments adjustment
    WHERE adjustment.company_id = NEW.company_id
      AND adjustment.visit_item_id = NEW.id
      AND NOT EXISTS (
          SELECT 1
          FROM jsonb_array_elements(
              COALESCE(NEW.offer_snapshot -> 'adjustments', '[]'::jsonb)
          ) snapshot(value)
          WHERE (snapshot.value ->> 'sequence')::integer = adjustment.sequence
            AND (snapshot.value ->> 'offer_version_id')::integer
                = adjustment.offer_version_id
            AND (snapshot.value ->> 'offer_definition_id')::integer
                = adjustment.rule_id
            AND (snapshot.value ->> 'offer_revision')::integer
                = adjustment.rule_version
            AND snapshot.value ->> 'offer_type' = adjustment.rule_type
            AND (snapshot.value ->> 'uom_id')::integer = adjustment.uom_id
            AND (snapshot.value ->> 'basis_amount')::numeric
                = (adjustment.metadata_snapshot ->> 'unrounded_basis_amount')::numeric
            AND (snapshot.value ->> 'discount_amount')::numeric
                = (adjustment.metadata_snapshot ->> 'unrounded_adjustment_amount')::numeric
      );

    IF adjustment_snapshot_mismatch <> 0 THEN
        RAISE EXCEPTION 'typed adjustments do not match line offer snapshot'
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
        MAX(sequence),
        COUNT(DISTINCT (
            tax_rule_set_id,
            tax_rule_set_version_id,
            tax_revision
        )),
        COUNT(DISTINCT COALESCE(matched_jurisdiction_id, -1)),
        COUNT(DISTINCT COALESCE(jurisdiction_distance, -1))
    INTO
        component_total,
        component_count,
        min_sequence,
        max_sequence,
        tax_identity_count,
        tax_jurisdiction_count,
        tax_distance_count
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
    IF tax_identity_count <> 1
       OR tax_jurisdiction_count <> 1
       OR tax_distance_count <> 1
    THEN
        RAISE EXCEPTION 'one sales line must use one coherent tax resolution'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*)
    INTO tax_semantic_mismatch
    FROM sales_line_tax_components tax_evidence
    JOIN tax_rule_set_versions tax_version
      ON tax_version.company_id = tax_evidence.company_id
     AND tax_version.id = tax_evidence.tax_rule_set_version_id
     AND tax_version.tax_rule_set_id = tax_evidence.tax_rule_set_id
    JOIN tax_rule_components tax_component
      ON tax_component.company_id = tax_evidence.company_id
     AND tax_component.id = tax_evidence.tax_component_id
     AND tax_component.tax_rule_set_version_id
            = tax_evidence.tax_rule_set_version_id
    WHERE tax_evidence.company_id = NEW.company_id
      AND tax_evidence.visit_item_id = NEW.id
      AND (
          tax_evidence.tax_revision IS DISTINCT FROM tax_version.revision
          OR tax_evidence.sequence IS DISTINCT FROM tax_component.sequence
          OR tax_evidence.component_code IS DISTINCT FROM tax_component.component_code
          OR tax_evidence.tax_name IS DISTINCT FROM tax_component.name
          OR tax_evidence.rate IS DISTINCT FROM tax_component.rate
          OR tax_evidence.basis_mode IS DISTINCT FROM tax_component.basis_mode
          OR tax_evidence.reporting_code IS DISTINCT FROM tax_component.reporting_code
          OR tax_version.revision > parent_revision.tax_revision_ceiling
          OR tax_version.published_at IS NULL
          OR tax_version.published_at > parent_revision.commercial_calculated_at
          OR tax_version.effective_from > parent_revision.commercial_calculated_at
          OR (
              tax_version.effective_to IS NOT NULL
              AND tax_version.effective_to <= parent_revision.commercial_calculated_at
          )
          OR NOT (tax_evidence.metadata_snapshot ? 'scope_types')
          OR NOT (tax_evidence.metadata_snapshot ? 'definition_version')
          OR NOT (tax_evidence.metadata_snapshot ? 'unrounded_basis_amount')
          OR NOT (tax_evidence.metadata_snapshot ? 'unrounded_tax_amount')
          OR NOT (tax_evidence.metadata_snapshot ? 'resolved_at')
          OR (tax_evidence.metadata_snapshot ->> 'definition_version')::integer
                IS DISTINCT FROM tax_version.definition_version
      );

    IF tax_semantic_mismatch <> 0 THEN
        RAISE EXCEPTION 'typed tax semantics do not match immutable tax configuration'
            USING ERRCODE = '23514';
    END IF;

    IF jsonb_typeof(COALESCE(NEW.tax_snapshot -> 'components', '[]'::jsonb))
       <> 'array'
    THEN
        RAISE EXCEPTION 'line tax snapshot components must be an array'
            USING ERRCODE = '23514';
    END IF;

    tax_snapshot_count = jsonb_array_length(
        COALESCE(NEW.tax_snapshot -> 'components', '[]'::jsonb)
    );
    IF tax_snapshot_count <> component_count THEN
        RAISE EXCEPTION 'typed tax component count does not match line tax snapshot'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*)
    INTO tax_snapshot_mismatch
    FROM sales_line_tax_components tax_evidence
    JOIN tax_rule_set_versions tax_version
      ON tax_version.company_id = tax_evidence.company_id
     AND tax_version.id = tax_evidence.tax_rule_set_version_id
     AND tax_version.tax_rule_set_id = tax_evidence.tax_rule_set_id
    WHERE tax_evidence.company_id = NEW.company_id
      AND tax_evidence.visit_item_id = NEW.id
      AND (
          (NEW.tax_snapshot ->> 'tax_rule_set_id')::integer
                IS DISTINCT FROM tax_evidence.tax_rule_set_id
          OR (NEW.tax_snapshot ->> 'tax_rule_set_version_id')::integer
                IS DISTINCT FROM tax_evidence.tax_rule_set_version_id
          OR (NEW.tax_snapshot ->> 'tax_revision')::integer
                IS DISTINCT FROM tax_evidence.tax_revision
          OR (NEW.tax_snapshot ->> 'definition_version')::integer
                IS DISTINCT FROM tax_version.definition_version
          OR NEW.tax_snapshot ->> 'price_mode'
                IS DISTINCT FROM tax_version.price_mode
          OR (NEW.tax_snapshot ->> 'matched_jurisdiction_id')::integer
                IS DISTINCT FROM tax_evidence.matched_jurisdiction_id
          OR (NEW.tax_snapshot ->> 'jurisdiction_distance')::integer
                IS DISTINCT FROM tax_evidence.jurisdiction_distance
          OR NEW.tax_snapshot -> 'scope_types'
                IS DISTINCT FROM tax_evidence.metadata_snapshot -> 'scope_types'
          OR NEW.tax_snapshot ->> 'resolved_at'
                IS DISTINCT FROM tax_evidence.metadata_snapshot ->> 'resolved_at'
          OR (NEW.tax_snapshot ->> 'resolved_at')::timestamptz
                IS DISTINCT FROM parent_revision.commercial_calculated_at
          OR NOT EXISTS (
              SELECT 1
              FROM jsonb_array_elements(
                  COALESCE(NEW.tax_snapshot -> 'components', '[]'::jsonb)
              ) snapshot(value)
              WHERE (snapshot.value ->> 'tax_component_id')::integer
                        = tax_evidence.tax_component_id
                AND snapshot.value ->> 'component_code'
                        = tax_evidence.component_code
                AND snapshot.value ->> 'name' = tax_evidence.tax_name
                AND (snapshot.value ->> 'sequence')::integer
                        = tax_evidence.sequence
                AND (snapshot.value ->> 'rate')::numeric
                        = tax_evidence.rate
                AND snapshot.value ->> 'basis_mode'
                        = tax_evidence.basis_mode
                AND (snapshot.value ->> 'reporting_code')
                        IS NOT DISTINCT FROM tax_evidence.reporting_code
                AND (snapshot.value ->> 'unrounded_basis_amount')::numeric
                        = (
                            tax_evidence.metadata_snapshot
                            ->> 'unrounded_basis_amount'
                        )::numeric
                AND (snapshot.value ->> 'unrounded_tax_amount')::numeric
                        = (
                            tax_evidence.metadata_snapshot
                            ->> 'unrounded_tax_amount'
                        )::numeric
                AND (snapshot.value ->> 'tax_amount')::numeric
                        = tax_evidence.tax_amount
          )
      );

    IF tax_snapshot_mismatch <> 0 THEN
        RAISE EXCEPTION 'typed tax evidence does not match line tax snapshot'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;
"""


def _validate_existing_frozen_lines() -> None:
    bind = op.get_bind()
    company_ids = [
        int(row[0])
        for row in bind.execute(
            sa.text("SELECT id FROM companies ORDER BY id")
        ).all()
    ]
    for company_id in company_ids:
        bind.execute(
            sa.text(
                "SELECT set_config('app.current_tenant', :tenant_id, true)"
            ),
            {"tenant_id": str(company_id)},
        )
        bind.execute(
            sa.text(
                """
                UPDATE visit_items
                SET id = id
                WHERE company_id = :company_id
                  AND financial_evidence_version IS NOT NULL
                """
            ),
            {"company_id": company_id},
        )
        bind.execute(
            sa.text(
                "SET CONSTRAINTS trg_visit_item_evidence_reconcile IMMEDIATE"
            )
        )
        bind.execute(
            sa.text(
                "SET CONSTRAINTS trg_visit_item_evidence_reconcile DEFERRED"
            )
        )

    bind.execute(
        sa.text(
            "SELECT set_config('app.current_tenant', '', true)"
        )
    )


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_sales_line_tax_components_sales_line_tax_component_jurisdiction_shape"),
        "sales_line_tax_components",
        """
        (
            matched_jurisdiction_id IS NULL
            AND jurisdiction_distance IS NULL
        )
        OR
        (
            matched_jurisdiction_id IS NOT NULL
            AND jurisdiction_distance IS NOT NULL
        )
        """,
    )
    op.execute(_NEW_VALIDATOR)
    _validate_existing_frozen_lines()


def downgrade() -> None:
    op.execute(_OLD_VALIDATOR)
    op.drop_constraint(
        op.f("ck_sales_line_tax_components_sales_line_tax_component_jurisdiction_shape"),
        "sales_line_tax_components",
        type_="check",
    )
