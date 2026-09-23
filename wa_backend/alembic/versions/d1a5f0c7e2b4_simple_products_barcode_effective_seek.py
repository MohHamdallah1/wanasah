"""Add active effective-barcode seek index for Simple Products filters.

Revision ID: d1a5f0c7e2b4
Revises: c1f4e8a2d6b9
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "d1a5f0c7e2b4"
down_revision = "c1f4e8a2d6b9"
branch_labels = None
depends_on = None

INDEX_NAME = (
    "ix_product_barcodes_company_variant_active_validity"
)


def _assert_ddl_role() -> None:
    bind = op.get_bind()
    row = bind.execute(
        text(
            """
            SELECT
                current_user AS current_user,
                owner.rolname AS table_owner,
                current_setting('is_superuser') = 'on'
                    AS is_superuser
            FROM pg_class AS rel
            JOIN pg_namespace AS ns
              ON ns.oid = rel.relnamespace
            JOIN pg_roles AS owner
              ON owner.oid = rel.relowner
            WHERE ns.nspname = current_schema()
              AND rel.relname = 'product_barcodes'
              AND rel.relkind = 'r'
            """
        )
    ).mappings().one()

    if (
        str(row["current_user"])
        != str(row["table_owner"])
        and not bool(row["is_superuser"])
    ):
        raise RuntimeError(
            "Migration requires the product_barcodes "
            "table owner or a superuser. "
            "Use DATABASE_URL_MIGRATION."
        )


def upgrade() -> None:
    _assert_ddl_role()

    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
                {INDEX_NAME}
            ON public.product_barcodes (
                company_id,
                product_variant_id,
                valid_from,
                valid_to
            )
            WHERE is_active IS TRUE
            """
        )

    op.execute("ANALYZE public.product_barcodes")


def downgrade() -> None:
    _assert_ddl_role()

    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS "
            f"public.{INDEX_NAME}"
        )
