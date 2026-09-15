"""stage6 return reversal from original lines

Revision ID: d2a6c8e4f1b7
Revises: c9f5a7b3d2e4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d2a6c8e4f1b7"
down_revision: Union[str, Sequence[str], None] = "c9f5a7b3d2e4"
branch_labels = None
depends_on = None


TABLES = (
    "sales_return_documents",
    "sales_return_lines",
    "sales_return_quantity_components",
    "sales_return_adjustments",
    "sales_return_tax_components",
)


def _rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY {table}_company_isolation
        ON {table}
        USING (
            company_id = NULLIF(
                current_setting('app.current_tenant', true),
                ''
            )::integer
        )
        WITH CHECK (
            company_id = NULLIF(
                current_setting('app.current_tenant', true),
                ''
            )::integer
        )
        """
    )


def upgrade() -> None:
    op.create_table(
        "sales_return_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("original_visit_id", sa.Integer(), nullable=False),
        sa.Column("original_sales_revision_id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="POSTED"),
        sa.Column("transaction_currency_code", sa.String(10), nullable=False),
        sa.Column("functional_currency_code", sa.String(10), nullable=False),
        sa.Column(
            "rounding_reversal",
            sa.Numeric(20, 6),
            nullable=False,
            server_default="0.000000",
        ),
        sa.Column("credit_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "evidence_schema_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "company_id", "id",
            name="uq_sales_return_documents_company_id",
        ),
        sa.UniqueConstraint(
            "company_id", "request_id",
            name="uq_sales_return_documents_request_id",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"],
            ondelete="CASCADE",
            name="fk_sales_return_document_company",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "original_visit_id"],
            ["visits.company_id", "visits.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_document_visit",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "original_visit_id", "original_sales_revision_id"],
            [
                "sales_visit_revisions.company_id",
                "sales_visit_revisions.visit_id",
                "sales_visit_revisions.id",
            ],
            ondelete="RESTRICT",
            name="fk_sales_return_document_revision",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "shop_id"],
            ["shops.company_id", "shops.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_document_shop",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "created_by"],
            ["drivers.company_id", "drivers.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_document_actor",
        ),
        sa.CheckConstraint("status = 'POSTED'", name="sales_return_document_status_posted"),
        sa.CheckConstraint(
            "credit_amount >= 0",
            name="sales_return_document_credit_nonnegative",
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 3 AND 1000",
            name="sales_return_document_reason_length",
        ),
        sa.CheckConstraint(
            "transaction_currency_code ~ '^[A-Z]{3,10}$'",
            name="sales_return_document_currency_shape",
        ),
        sa.CheckConstraint(
            "functional_currency_code ~ '^[A-Z]{3,10}$'",
            name="sales_return_document_functional_currency_shape",
        ),
    )
    op.create_index(
        "ix_sales_return_document_source",
        "sales_return_documents",
        ["company_id", "original_sales_revision_id", "id"],
    )
    op.create_index(
        "ix_sales_return_document_shop",
        "sales_return_documents",
        ["company_id", "shop_id", "id"],
    )

    op.create_table(
        "sales_return_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("sales_return_id", sa.Integer(), nullable=False),
        sa.Column("original_visit_item_id", sa.Integer(), nullable=False),
        sa.Column("product_variant_id", sa.Integer(), nullable=False),
        sa.Column("returned_base_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("gross_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column("discount_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column("post_offer_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column("taxable_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column("tax_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column("line_total_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column("credit_amount", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "evidence_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "company_id", "id",
            name="uq_sales_return_lines_company_id",
        ),
        sa.UniqueConstraint(
            "company_id", "sales_return_id", "original_visit_item_id",
            name="uq_sales_return_line_source_item",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "sales_return_id"],
            ["sales_return_documents.company_id", "sales_return_documents.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_line_document",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "original_visit_item_id"],
            ["visit_items.company_id", "visit_items.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_line_source_item",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_variant_id"],
            ["product_variants.company_id", "product_variants.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_line_variant",
        ),
        sa.CheckConstraint(
            "returned_base_quantity > 0",
            name="sales_return_line_qty_positive",
        ),
        sa.CheckConstraint(
            "gross_reversal >= 0 AND discount_reversal >= 0 "
            "AND post_offer_reversal >= 0 AND taxable_reversal >= 0 "
            "AND tax_reversal >= 0 AND line_total_reversal >= 0 "
            "AND credit_amount >= 0",
            name="sales_return_line_money_nonnegative",
        ),
        sa.CheckConstraint(
            "post_offer_reversal = gross_reversal - discount_reversal",
            name="sales_return_line_offer_reconcile",
        ),
        sa.CheckConstraint(
            "line_total_reversal = taxable_reversal + tax_reversal",
            name="sales_return_line_tax_reconcile",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'",
            name="sales_return_line_snapshot_object",
        ),
    )
    op.create_index(
        "ix_sales_return_line_source",
        "sales_return_lines",
        ["company_id", "original_visit_item_id", "id"],
    )

    op.create_table(
        "sales_return_quantity_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("sales_return_line_id", sa.Integer(), nullable=False),
        sa.Column("original_price_component_id", sa.Integer(), nullable=False),
        sa.Column("uom_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("base_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("gross_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "evidence_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "company_id", "id",
            name="uq_sales_return_quantity_components_company_id",
        ),
        sa.UniqueConstraint(
            "company_id", "sales_return_line_id", "original_price_component_id",
            name="uq_sales_return_quantity_source",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "sales_return_line_id"],
            ["sales_return_lines.company_id", "sales_return_lines.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_quantity_line",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "original_price_component_id"],
            ["sales_line_price_components.company_id", "sales_line_price_components.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_quantity_source_price",
        ),
        sa.ForeignKeyConstraint(
            ["uom_id"], ["uom.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_quantity_uom",
        ),
        sa.CheckConstraint("quantity > 0", name="sales_return_quantity_positive"),
        sa.CheckConstraint(
            "base_quantity > 0",
            name="sales_return_base_quantity_positive",
        ),
        sa.CheckConstraint(
            "gross_reversal >= 0",
            name="sales_return_quantity_gross_nonnegative",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'",
            name="sales_return_quantity_snapshot_object",
        ),
    )

    op.create_table(
        "sales_return_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("sales_return_line_id", sa.Integer(), nullable=False),
        sa.Column("original_adjustment_id", sa.Integer(), nullable=False),
        sa.Column("uom_id", sa.Integer(), nullable=False),
        sa.Column("adjustment_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "evidence_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "company_id", "id",
            name="uq_sales_return_adjustments_company_id",
        ),
        sa.UniqueConstraint(
            "company_id", "sales_return_line_id", "original_adjustment_id",
            name="uq_sales_return_adjustment_source",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "sales_return_line_id"],
            ["sales_return_lines.company_id", "sales_return_lines.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_adjustment_line",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "original_adjustment_id"],
            ["sales_line_adjustments.company_id", "sales_line_adjustments.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_adjustment_source",
        ),
        sa.ForeignKeyConstraint(
            ["uom_id"], ["uom.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_adjustment_uom",
        ),
        sa.CheckConstraint(
            "adjustment_reversal >= 0",
            name="sales_return_adjustment_nonnegative",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'",
            name="sales_return_adjustment_snapshot_object",
        ),
    )

    op.create_table(
        "sales_return_tax_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("sales_return_line_id", sa.Integer(), nullable=False),
        sa.Column("original_tax_component_id", sa.Integer(), nullable=False),
        sa.Column("taxable_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column("tax_reversal", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "evidence_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "company_id", "id",
            name="uq_sales_return_tax_components_company_id",
        ),
        sa.UniqueConstraint(
            "company_id", "sales_return_line_id", "original_tax_component_id",
            name="uq_sales_return_tax_source",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "sales_return_line_id"],
            ["sales_return_lines.company_id", "sales_return_lines.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_tax_line",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "original_tax_component_id"],
            ["sales_line_tax_components.company_id", "sales_line_tax_components.id"],
            ondelete="RESTRICT",
            name="fk_sales_return_tax_source",
        ),
        sa.CheckConstraint(
            "taxable_reversal >= 0 AND tax_reversal >= 0",
            name="sales_return_tax_nonnegative",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'",
            name="sales_return_tax_snapshot_object",
        ),
    )

    for table in TABLES:
        _rls(table)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sales_return_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'posted sales return evidence is immutable'
                USING ERRCODE = '55000';
        END;
        $$;
        """
    )
    for table in TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION guard_sales_return_immutable()
            """
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_sales_return_document(
            p_company_id integer,
            p_document_id integer
        )
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            doc sales_return_documents%ROWTYPE;
            bad_count integer;
            line_count integer;
            line_credit numeric(20,6);
        BEGIN
            SELECT *
            INTO doc
            FROM sales_return_documents
            WHERE company_id = p_company_id
              AND id = p_document_id;

            IF NOT FOUND THEN
                RETURN;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM visits source_visit
                JOIN sales_visit_revisions source_revision
                  ON source_revision.company_id = source_visit.company_id
                 AND source_revision.visit_id = source_visit.id
                 AND source_revision.id = doc.original_sales_revision_id
                WHERE source_visit.company_id = doc.company_id
                  AND source_visit.id = doc.original_visit_id
                  AND source_visit.current_sales_revision_id
                        = doc.original_sales_revision_id
                  AND source_visit.shop_id = doc.shop_id
                  AND source_visit.status = 'Completed'
                  AND source_visit.outcome = 'Sale'
                  AND source_revision.frozen_at IS NOT NULL
                  AND source_revision.transaction_currency_code
                        = doc.transaction_currency_code
                  AND source_revision.functional_currency_code
                        = doc.functional_currency_code
            ) THEN
                RAISE EXCEPTION 'sales return source must be the current frozen completed sale'
                    USING ERRCODE = '23514';
            END IF;

            IF (
                SELECT COALESCE(SUM(return_doc.credit_amount), 0)
                FROM sales_return_documents return_doc
                WHERE return_doc.company_id = doc.company_id
                  AND return_doc.original_sales_revision_id
                        = doc.original_sales_revision_id
            ) > (
                SELECT source_revision.final_amount
                FROM sales_visit_revisions source_revision
                WHERE source_revision.company_id = doc.company_id
                  AND source_revision.id = doc.original_sales_revision_id
            ) THEN
                RAISE EXCEPTION 'cumulative return credit exceeds original sale final amount'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*), COALESCE(SUM(credit_amount), 0)
            INTO line_count, line_credit
            FROM sales_return_lines
            WHERE company_id = p_company_id
              AND sales_return_id = p_document_id;

            IF line_count <= 0 THEN
                RAISE EXCEPTION 'posted sales return requires at least one line'
                    USING ERRCODE = '23514';
            END IF;

            IF doc.credit_amount <> line_credit + doc.rounding_reversal THEN
                RAISE EXCEPTION 'sales return header credit does not reconcile'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO bad_count
            FROM sales_return_lines line
            JOIN visit_items source_line
              ON source_line.company_id = line.company_id
             AND source_line.id = line.original_visit_item_id
            WHERE line.company_id = p_company_id
              AND line.sales_return_id = p_document_id
              AND (
                  source_line.visit_id IS DISTINCT FROM doc.original_visit_id
                  OR source_line.sales_revision_id
                        IS DISTINCT FROM doc.original_sales_revision_id
                  OR source_line.product_variant_id
                        IS DISTINCT FROM line.product_variant_id
                  OR source_line.financial_evidence_version IS DISTINCT FROM 4
                  OR source_line.is_cancelled IS TRUE
                  OR line.returned_base_quantity IS DISTINCT FROM (
                      SELECT COALESCE(SUM(q.base_quantity), 0)
                      FROM sales_return_quantity_components q
                      WHERE q.company_id = line.company_id
                        AND q.sales_return_line_id = line.id
                  )
                  OR line.gross_reversal IS DISTINCT FROM (
                      SELECT COALESCE(SUM(q.gross_reversal), 0)
                      FROM sales_return_quantity_components q
                      WHERE q.company_id = line.company_id
                        AND q.sales_return_line_id = line.id
                  )
                  OR line.discount_reversal IS DISTINCT FROM (
                      SELECT COALESCE(SUM(a.adjustment_reversal), 0)
                      FROM sales_return_adjustments a
                      WHERE a.company_id = line.company_id
                        AND a.sales_return_line_id = line.id
                  )
                  OR line.tax_reversal IS DISTINCT FROM (
                      SELECT COALESCE(SUM(t.tax_reversal), 0)
                      FROM sales_return_tax_components t
                      WHERE t.company_id = line.company_id
                        AND t.sales_return_line_id = line.id
                  )
              );

            IF bad_count <> 0 THEN
                RAISE EXCEPTION 'sales return line evidence does not reconcile to original frozen lines'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO bad_count
            FROM visit_items source_line
            JOIN (
                SELECT
                    line.original_visit_item_id,
                    SUM(line.returned_base_quantity) AS returned_base_quantity,
                    SUM(line.gross_reversal) AS gross_reversal,
                    SUM(line.discount_reversal) AS discount_reversal,
                    SUM(line.post_offer_reversal) AS post_offer_reversal,
                    SUM(line.taxable_reversal) AS taxable_reversal,
                    SUM(line.tax_reversal) AS tax_reversal,
                    SUM(line.credit_amount) AS credit_amount
                FROM sales_return_lines line
                JOIN sales_return_documents return_doc
                  ON return_doc.company_id = line.company_id
                 AND return_doc.id = line.sales_return_id
                WHERE return_doc.company_id = doc.company_id
                  AND return_doc.original_sales_revision_id
                        = doc.original_sales_revision_id
                GROUP BY line.original_visit_item_id
            ) returned
              ON returned.original_visit_item_id = source_line.id
            WHERE source_line.company_id = doc.company_id
              AND (
                  returned.returned_base_quantity > source_line.canonical_quantity
                  OR returned.gross_reversal > source_line.gross_amount
                  OR returned.discount_reversal > source_line.discount_amount
                  OR returned.post_offer_reversal > source_line.post_offer_amount
                  OR returned.taxable_reversal > source_line.taxable_amount
                  OR returned.tax_reversal > source_line.tax_amount
                  OR returned.credit_amount > source_line.net_amount
                  OR returned.taxable_reversal IS DISTINCT FROM (
                      CASE
                          WHEN source_line.post_offer_amount = 0
                              THEN 0::numeric
                          WHEN returned.post_offer_reversal
                                = source_line.post_offer_amount
                              THEN source_line.taxable_amount
                          ELSE round(
                              source_line.taxable_amount
                              * returned.post_offer_reversal
                              / source_line.post_offer_amount,
                              6
                          )
                      END
                  )
                  OR (
                      returned.post_offer_reversal = source_line.post_offer_amount
                      AND returned.credit_amount
                            IS DISTINCT FROM source_line.net_amount
                  )
              );

            IF bad_count <> 0 THEN
                RAISE EXCEPTION 'cumulative sales return line reversal does not match original line evidence'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO bad_count
            FROM sales_return_quantity_components q
            JOIN sales_return_lines line
              ON line.company_id = q.company_id
             AND line.id = q.sales_return_line_id
            JOIN sales_line_price_components source
              ON source.company_id = q.company_id
             AND source.id = q.original_price_component_id
            WHERE line.company_id = p_company_id
              AND line.sales_return_id = p_document_id
              AND (
                  source.visit_item_id IS DISTINCT FROM line.original_visit_item_id
                  OR source.uom_id IS DISTINCT FROM q.uom_id
              );

            IF bad_count <> 0 THEN
                RAISE EXCEPTION 'sales return quantity component does not match original price component'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO bad_count
            FROM sales_line_price_components source
            JOIN (
                SELECT
                    q.original_price_component_id,
                    SUM(q.quantity) AS returned_quantity,
                    SUM(q.base_quantity) AS returned_base_quantity,
                    SUM(q.gross_reversal) AS gross_reversal
                FROM sales_return_quantity_components q
                JOIN sales_return_lines line
                  ON line.company_id = q.company_id
                 AND line.id = q.sales_return_line_id
                JOIN sales_return_documents return_doc
                  ON return_doc.company_id = line.company_id
                 AND return_doc.id = line.sales_return_id
                WHERE return_doc.company_id = doc.company_id
                  AND return_doc.original_sales_revision_id
                        = doc.original_sales_revision_id
                GROUP BY q.original_price_component_id
            ) returned
              ON returned.original_price_component_id = source.id
            WHERE source.company_id = doc.company_id
              AND (
                  returned.returned_quantity > source.quantity
                  OR returned.returned_base_quantity IS DISTINCT FROM (
                      CASE
                          WHEN returned.returned_quantity = source.quantity
                              THEN source.base_quantity
                          ELSE round(
                              source.base_quantity
                              * returned.returned_quantity
                              / source.quantity,
                              6
                          )
                      END
                  )
                  OR returned.gross_reversal IS DISTINCT FROM (
                      CASE
                          WHEN returned.returned_quantity = source.quantity
                              THEN source.gross_amount
                          ELSE round(
                              source.gross_amount
                              * returned.returned_quantity
                              / source.quantity,
                              6
                          )
                      END
                  )
              );

            IF bad_count <> 0 THEN
                RAISE EXCEPTION 'cumulative return quantity reversal does not match original price evidence'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO bad_count
            FROM sales_line_price_components source
            WHERE source.company_id = p_company_id
              AND EXISTS (
                  SELECT 1
                  FROM sales_return_quantity_components q
                  JOIN sales_return_lines line
                    ON line.company_id = q.company_id
                   AND line.id = q.sales_return_line_id
                  JOIN sales_return_documents d
                    ON d.company_id = line.company_id
                   AND d.id = line.sales_return_id
                  WHERE q.company_id = p_company_id
                    AND q.original_price_component_id = source.id
                    AND d.original_sales_revision_id = doc.original_sales_revision_id
                  GROUP BY q.original_price_component_id
                  HAVING SUM(q.quantity) > source.quantity
              );

            IF bad_count <> 0 THEN
                RAISE EXCEPTION 'cumulative returned quantity exceeds original sold quantity'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO bad_count
            FROM sales_line_adjustments source_adjustment
            JOIN sales_line_price_components source_price
              ON source_price.company_id = source_adjustment.company_id
             AND source_price.visit_item_id = source_adjustment.visit_item_id
             AND source_price.uom_id = source_adjustment.uom_id
            JOIN (
                SELECT
                    q.original_price_component_id,
                    SUM(q.quantity) AS returned_quantity
                FROM sales_return_quantity_components q
                JOIN sales_return_lines line
                  ON line.company_id = q.company_id
                 AND line.id = q.sales_return_line_id
                JOIN sales_return_documents return_doc
                  ON return_doc.company_id = line.company_id
                 AND return_doc.id = line.sales_return_id
                WHERE return_doc.company_id = doc.company_id
                  AND return_doc.original_sales_revision_id
                        = doc.original_sales_revision_id
                GROUP BY q.original_price_component_id
            ) quantity_return
              ON quantity_return.original_price_component_id = source_price.id
            LEFT JOIN (
                SELECT
                    a.original_adjustment_id,
                    SUM(a.adjustment_reversal) AS adjustment_reversal
                FROM sales_return_adjustments a
                JOIN sales_return_lines line
                  ON line.company_id = a.company_id
                 AND line.id = a.sales_return_line_id
                JOIN sales_return_documents return_doc
                  ON return_doc.company_id = line.company_id
                 AND return_doc.id = line.sales_return_id
                WHERE return_doc.company_id = doc.company_id
                  AND return_doc.original_sales_revision_id
                        = doc.original_sales_revision_id
                GROUP BY a.original_adjustment_id
            ) adjustment_return
              ON adjustment_return.original_adjustment_id = source_adjustment.id
            WHERE source_adjustment.company_id = doc.company_id
              AND COALESCE(adjustment_return.adjustment_reversal, 0)
                    IS DISTINCT FROM (
                  CASE
                      WHEN quantity_return.returned_quantity = source_price.quantity
                          THEN source_adjustment.adjustment_amount
                      ELSE round(
                          source_adjustment.adjustment_amount
                          * quantity_return.returned_quantity
                          / source_price.quantity,
                          6
                      )
                  END
              );

            IF bad_count <> 0 THEN
                RAISE EXCEPTION 'cumulative adjustment reversal does not match original offer evidence'
                    USING ERRCODE = '23514';
            END IF;

            SELECT COUNT(*)
            INTO bad_count
            FROM sales_line_tax_components source_tax
            JOIN visit_items source_line
              ON source_line.company_id = source_tax.company_id
             AND source_line.id = source_tax.visit_item_id
            JOIN (
                SELECT
                    line.original_visit_item_id,
                    SUM(line.post_offer_reversal) AS post_offer_reversal
                FROM sales_return_lines line
                JOIN sales_return_documents return_doc
                  ON return_doc.company_id = line.company_id
                 AND return_doc.id = line.sales_return_id
                WHERE return_doc.company_id = doc.company_id
                  AND return_doc.original_sales_revision_id
                        = doc.original_sales_revision_id
                GROUP BY line.original_visit_item_id
            ) line_return
              ON line_return.original_visit_item_id = source_line.id
            LEFT JOIN (
                SELECT
                    t.original_tax_component_id,
                    SUM(t.taxable_reversal) AS taxable_reversal,
                    SUM(t.tax_reversal) AS tax_reversal
                FROM sales_return_tax_components t
                JOIN sales_return_lines line
                  ON line.company_id = t.company_id
                 AND line.id = t.sales_return_line_id
                JOIN sales_return_documents return_doc
                  ON return_doc.company_id = line.company_id
                 AND return_doc.id = line.sales_return_id
                WHERE return_doc.company_id = doc.company_id
                  AND return_doc.original_sales_revision_id
                        = doc.original_sales_revision_id
                GROUP BY t.original_tax_component_id
            ) tax_return
              ON tax_return.original_tax_component_id = source_tax.id
            WHERE source_tax.company_id = doc.company_id
              AND (
                  COALESCE(tax_return.taxable_reversal, 0) IS DISTINCT FROM (
                      CASE
                          WHEN source_line.post_offer_amount = 0
                              THEN 0::numeric
                          WHEN line_return.post_offer_reversal
                                = source_line.post_offer_amount
                              THEN source_tax.taxable_amount
                          ELSE round(
                              source_tax.taxable_amount
                              * line_return.post_offer_reversal
                              / source_line.post_offer_amount,
                              6
                          )
                      END
                  )
                  OR COALESCE(tax_return.tax_reversal, 0) IS DISTINCT FROM (
                      CASE
                          WHEN source_line.post_offer_amount = 0
                              THEN 0::numeric
                          WHEN line_return.post_offer_reversal
                                = source_line.post_offer_amount
                              THEN source_tax.tax_amount
                          ELSE round(
                              source_tax.tax_amount
                              * line_return.post_offer_reversal
                              / source_line.post_offer_amount,
                              6
                          )
                      END
                  )
              );

            IF bad_count <> 0 THEN
                RAISE EXCEPTION 'cumulative tax reversal does not match original tax evidence'
                    USING ERRCODE = '23514';
            END IF;

            RETURN;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION trigger_validate_sales_return_document()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            document_id integer;
        BEGIN
            IF TG_TABLE_NAME = 'sales_return_documents' THEN
                document_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'sales_return_lines' THEN
                document_id := NEW.sales_return_id;
            ELSE
                SELECT sales_return_id
                INTO document_id
                FROM sales_return_lines
                WHERE company_id = NEW.company_id
                  AND id = NEW.sales_return_line_id;
            END IF;

            PERFORM validate_sales_return_document(
                NEW.company_id,
                document_id
            );
            RETURN NEW;
        END;
        $$;
        """
    )
    for table in TABLES:
        op.execute(
            f"""
            CREATE CONSTRAINT TRIGGER trg_{table}_reconcile
            AFTER INSERT ON {table}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION trigger_validate_sales_return_document()
            """
        )


    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sales_return_source_visit()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM sales_return_documents return_doc
                WHERE return_doc.company_id = OLD.company_id
                  AND return_doc.original_visit_id = OLD.id
            ) AND (
                NEW.shop_id IS DISTINCT FROM OLD.shop_id
                OR NEW.status IS DISTINCT FROM OLD.status
                OR NEW.outcome IS DISTINCT FROM OLD.outcome
                OR NEW.current_sales_revision_id
                    IS DISTINCT FROM OLD.current_sales_revision_id
            ) THEN
                RAISE EXCEPTION 'sale with posted return evidence cannot change return authority'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_visit_sales_return_source_guard
        BEFORE UPDATE OF shop_id, status, outcome, current_sales_revision_id
        ON visits
        FOR EACH ROW EXECUTE FUNCTION guard_sales_return_source_visit()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION guard_sales_return_source_line()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM sales_return_lines return_line
                WHERE return_line.company_id = OLD.company_id
                  AND return_line.original_visit_item_id = OLD.id
            ) THEN
                RAISE EXCEPTION 'sale line with posted return evidence is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_visit_item_sales_return_source_guard
        BEFORE UPDATE OR DELETE ON visit_items
        FOR EACH ROW EXECUTE FUNCTION guard_sales_return_source_line()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_visit_item_sales_return_source_guard ON visit_items"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_sales_return_source_line()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_visit_sales_return_source_guard ON visits"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_sales_return_source_visit()")
    op.execute("DROP FUNCTION IF EXISTS trigger_validate_sales_return_document() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS validate_sales_return_document(integer, integer)")
    op.execute("DROP FUNCTION IF EXISTS guard_sales_return_immutable() CASCADE")

    for table in reversed(TABLES):
        op.drop_table(table)
