"""Add tenant-scoped trigram indexes for Simple Products identity search.

Revision ID: b6e3a1f9c4d2
Revises: e7a1c4d9b2f6
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "b6e3a1f9c4d2"
down_revision = "e7a1c4d9b2f6"
branch_labels = None
depends_on = None


FAMILY_INDEX = "ix_products_company_name_trgm"
BARCODE_INDEX = (
    "ix_product_barcodes_company_active_barcode_trgm"
)


def _assert_ddl_role() -> None:
    bind = op.get_bind()
    for table_name in (
        "products",
        "product_barcodes",
    ):
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
                  AND rel.relname = :table_name
                  AND rel.relkind = 'r'
                """
            ),
            {"table_name": table_name},
        ).mappings().one()

        if (
            str(row["current_user"])
            != str(row["table_owner"])
            and not bool(row["is_superuser"])
        ):
            raise RuntimeError(
                "Migration requires the table owner or a "
                "superuser. Use DATABASE_URL_MIGRATION; "
                "do not grant DDL privileges to the "
                "runtime application role."
            )


def _assert_trigram_extensions() -> None:
    bind = op.get_bind()
    installed = set(
        bind.execute(
            text(
                """
                SELECT extname
                FROM pg_extension
                WHERE extname IN ('pg_trgm', 'btree_gin')
                """
            )
        ).scalars()
    )
    missing = {
        "pg_trgm",
        "btree_gin",
    } - installed
    if missing:
        raise RuntimeError(
            "Required search extensions are missing: "
            + ", ".join(sorted(missing))
            + ". The d4a7c9e2f1b5 migration must be "
            "applied before this migration."
        )


def upgrade() -> None:
    _assert_ddl_role()
    _assert_trigram_extensions()

    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
                {FAMILY_INDEX}
            ON public.products
            USING gin (
                company_id,
                lower((name)::text) gin_trgm_ops
            )
            """
        )
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
                {BARCODE_INDEX}
            ON public.product_barcodes
            USING gin (
                company_id,
                lower((barcode)::text) gin_trgm_ops
            )
            WHERE is_active IS TRUE
            """
        )

    op.execute("ANALYZE public.products")
    op.execute("ANALYZE public.product_barcodes")


def downgrade() -> None:
    _assert_ddl_role()

    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS "
            f"public.{BARCODE_INDEX}"
        )
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS "
            f"public.{FAMILY_INDEX}"
        )
