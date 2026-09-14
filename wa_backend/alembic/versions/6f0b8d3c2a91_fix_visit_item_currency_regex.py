"""stage6h2b2b2 fix visit-item currency regex after f-string expansion

Revision ID: 6f0b8d3c2a91
Revises: f4c8d2a7b6e3
"""

from typing import Sequence, Union

from alembic import op


revision: str = "6f0b8d3c2a91"
down_revision: Union[str, Sequence[str], None] = "f4c8d2a7b6e3"
branch_labels = None
depends_on = None


_CORRECT_VISIT_ITEM_SHAPE = r"""
(
    financial_evidence_version IS NULL
    AND financial_evidence_frozen_at IS NULL
    AND commercial_context_id IS NULL
    AND sales_revision_id IS NULL
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
    AND sales_revision_id IS NOT NULL
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
"""


# Exact schema produced by f4c8d2a7b6e3 before this corrective migration.
_BROKEN_PRIOR_VISIT_ITEM_SHAPE = r"""
(
    financial_evidence_version IS NULL
    AND financial_evidence_frozen_at IS NULL
    AND commercial_context_id IS NULL
    AND sales_revision_id IS NULL
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
    AND sales_revision_id IS NOT NULL
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
    AND transaction_currency_code ~ '^[A-Z][A-Z0-9](2, 9)$'
    AND functional_currency_code ~ '^[A-Z][A-Z0-9](2, 9)$'
    AND offer_snapshot IS NOT NULL
    AND jsonb_typeof(offer_snapshot) = 'object'
    AND tax_snapshot IS NOT NULL
    AND jsonb_typeof(tax_snapshot) = 'object'
)
"""


def _replace_visit_item_shape(definition: str) -> None:
    op.drop_constraint(
        op.f("ck_visit_items_visit_item_financial_evidence_shape"),
        "visit_items",
        type_="check",
    )
    op.create_check_constraint(
        "visit_item_financial_evidence_shape",
        "visit_items",
        definition,
    )


def upgrade() -> None:
    _replace_visit_item_shape(_CORRECT_VISIT_ITEM_SHAPE)


def downgrade() -> None:
    # Downgrade restores the exact f4c8d2a7b6e3 schema. Once live evidence exists,
    # that historical broken regex would reject valid ISO-like currency codes, so
    # fail closed instead of corrupting or stranding immutable evidence.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM visit_items
                WHERE financial_evidence_version IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade currency-regex correction after frozen visit-item evidence exists';
            END IF;
        END
        $$;
        """
    )
    _replace_visit_item_shape(_BROKEN_PRIOR_VISIT_ITEM_SHAPE)
