"""Add warehouse-scoped Live Stock transition seek index.

Revision ID: d8f2a6c4b190
Revises: c7d4a91e6f32

The existing transition index is optimized for company-wide maintenance scans:
(company_id, next_transition_date, warehouse_location_id, product_variant_id).

Readiness checks filter one warehouse first and then a transition-date range,
so they need the warehouse before the range key to avoid scanning due rows
from every warehouse in the tenant.
"""
from __future__ import annotations

from alembic import op


revision = "d8f2a6c4b190"
down_revision = "c7d4a91e6f32"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_live_stock_projection_warehouse_transition"


def upgrade() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME}
            ON inventory_live_stock_projection
                (
                    company_id,
                    warehouse_location_id,
                    next_transition_date,
                    product_variant_id
                )
            WHERE next_transition_date IS NOT NULL
            """
        )


def downgrade() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}"
        )
