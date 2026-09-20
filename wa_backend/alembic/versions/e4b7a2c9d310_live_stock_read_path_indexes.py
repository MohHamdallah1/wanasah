"""Add Live Stock hot read-path indexes.

Revision ID: e4b7a2c9d310
Revises: d8f2a6c4b190
"""
from __future__ import annotations

from alembic import op


revision = "e4b7a2c9d310"
down_revision = "d8f2a6c4b190"
branch_labels = None
depends_on = None


INDEXES = (
    (
        "ix_product_variant_live_active_seek",
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS
            ix_product_variant_live_active_seek
        ON product_variants (company_id, name, id)
        WHERE lifecycle_status = 'ACTIVE'
        """,
    ),
    (
        "ix_inventory_cost_event_purchase_latest",
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS
            ix_inventory_cost_event_purchase_latest
        ON inventory_cost_events
            (company_id, product_variant_id, created_at DESC, id DESC)
        INCLUDE (input_unit_cost, input_uom_id)
        WHERE event_type = 'PURCHASE_IN'
        """,
    ),
    (
        "ix_product_uom_conversion_display_seek",
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS
            ix_product_uom_conversion_display_seek
        ON product_uom_conversions
            (company_id, product_variant_id, to_uom_id)
        INCLUDE (from_uom_id, numerator, denominator)
        WHERE numerator > denominator
        """,
    ),
)


def upgrade() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        for _name, sql in INDEXES:
            op.execute(sql)


def downgrade() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        for name, _sql in reversed(INDEXES):
            op.execute(
                f"DROP INDEX CONCURRENTLY IF EXISTS {name}"
            )
