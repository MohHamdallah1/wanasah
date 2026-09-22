"""Add inventory batch page seek index.

Revision ID: a6d1c8e4f2b7
Revises: e4b7a2c9d310

The batch detail endpoint filters by tenant + variant and orders by
(expiry_date ASC NULLS LAST, id ASC).  The existing single-column variant
index cannot satisfy that ordered keyset walk, so PostgreSQL scans all batches
for the variant and performs a top-N sort before returning one bounded page.
"""

from __future__ import annotations

from alembic import op


revision = "a6d1c8e4f2b7"
down_revision = "e4b7a2c9d310"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_product_batches_batch_page_seek"


def upgrade() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME}
            ON product_batches (
                company_id,
                product_variant_id,
                expiry_date ASC NULLS LAST,
                id ASC
            )
            """
        )


def downgrade() -> None:
    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}"
        )
