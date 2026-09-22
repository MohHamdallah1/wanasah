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
from sqlalchemy import text


revision = "a6d1c8e4f2b7"
down_revision = "e4b7a2c9d310"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_product_batches_batch_page_seek"


def _assert_ddl_role() -> None:
    bind = op.get_bind()
    row = bind.execute(
        text(
            """
            SELECT
                current_user AS current_user,
                owner.rolname AS table_owner,
                current_setting('is_superuser') = 'on' AS is_superuser
            FROM pg_class AS rel
            JOIN pg_namespace AS ns
              ON ns.oid = rel.relnamespace
            JOIN pg_roles AS owner
              ON owner.oid = rel.relowner
            WHERE ns.nspname = current_schema()
              AND rel.relname = 'product_batches'
              AND rel.relkind = 'r'
            """
        )
    ).mappings().one()

    if (
        str(row["current_user"]) != str(row["table_owner"])
        and not bool(row["is_superuser"])
    ):
        raise RuntimeError(
            "Migration requires the product_batches table owner or a "
            "superuser. Use DATABASE_URL_MIGRATION; do not grant DDL "
            "privileges to the runtime application role."
        )


def upgrade() -> None:
    _assert_ddl_role()
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
