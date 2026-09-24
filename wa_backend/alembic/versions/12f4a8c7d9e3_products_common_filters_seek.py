"""Add a targeted seek index for Simple Products common filters.

Revision ID: 12f4a8c7d9e3
Revises: d1a5f0c7e2b4
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "12f4a8c7d9e3"
down_revision = "d1a5f0c7e2b4"
branch_labels = None
depends_on = None

INDEX_NAME = (
    "ix_product_variant_simple_common_filters_seek"
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
              AND rel.relname = 'product_variants'
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
            "Migration requires the product_variants "
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
            ON public.product_variants (
                company_id,
                base_uom_id,
                lower((name)::text),
                id
            )
            WHERE lifecycle_status = 'ACTIVE'
              AND lot_control_mode <> 'NONE'
              AND expiry_control_mode = 'NONE'
              AND packs_per_carton > 0
            """
        )

    op.execute("ANALYZE public.product_variants")


def downgrade() -> None:
    _assert_ddl_role()

    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS "
            f"public.{INDEX_NAME}"
        )
