"""Use native pg_trgm for tenant-scoped Live Stock search.

Revision ID: d4a7c9e2f1b5
Revises: a6d1c8e4f2b7
"""

from __future__ import annotations

import os
import re

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import make_url


revision = "d4a7c9e2f1b5"
down_revision = "a6d1c8e4f2b7"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_product_variants_company_search_trgm"
FUNCTION_SIGNATURE = (
    "public.live_stock_search_variant_ids(integer, text[])"
)


def _assert_search_definer_role() -> None:
    bind = op.get_bind()
    row = bind.execute(
        text(
            """
            SELECT
                current_user AS current_user,
                role.rolsuper AS is_superuser,
                role.rolbypassrls AS bypass_rls,
                has_table_privilege(
                    current_user,
                    'public.product_variants',
                    'SELECT'
                ) AS can_select_variants
            FROM pg_roles AS role
            WHERE role.rolname = current_user
            """
        )
    ).mappings().one()

    if not (
        bool(row["is_superuser"]) or bool(row["bypass_rls"])
    ):
        raise RuntimeError(
            "Live Stock search function owner must bypass RLS. "
            "Use the privileged DATABASE_URL_MIGRATION role."
        )
    if not bool(row["can_select_variants"]):
        raise RuntimeError(
            "Migration role must have SELECT on public.product_variants."
        )


def _runtime_role() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError(
            "DATABASE_URL is required to grant runtime function execution."
        )
    role = make_url(raw).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError(
            "Runtime database role could not be resolved safely."
        )
    return role


def upgrade() -> None:
    _assert_search_definer_role()

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")

    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME}
            ON public.product_variants
            USING gin (
                company_id,
                lower(
                    ((name)::text || ' '::text) || (sku)::text
                ) gin_trgm_ops
            )
            """
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            public.live_stock_search_variant_ids(
                expected_company_id integer,
                search_patterns text[]
            )
        RETURNS SETOF integer
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        SET row_security = off
        AS $live_stock_search$
        DECLARE
            tenant_id integer;
            search_pattern text;
            query_sql text;
        BEGIN
            tenant_id := NULLIF(
                pg_catalog.current_setting(
                    'app.current_tenant',
                    true
                ),
                ''
            )::integer;

            IF tenant_id IS NULL
               OR expected_company_id IS NULL
               OR expected_company_id IS DISTINCT FROM tenant_id
            THEN
                RAISE EXCEPTION 'Live Stock tenant context mismatch.'
                    USING ERRCODE = '42501';
            END IF;

            IF search_patterns IS NULL
               OR pg_catalog.array_length(search_patterns, 1) IS NULL
               OR pg_catalog.array_length(search_patterns, 1) > 100
            THEN
                RAISE EXCEPTION 'Invalid Live Stock search patterns.'
                    USING ERRCODE = '22023';
            END IF;

            query_sql :=
                'SELECT pv.id '
                'FROM public.product_variants AS pv '
                'WHERE pv.company_id = $1';

            FOREACH search_pattern IN ARRAY search_patterns
            LOOP
                IF search_pattern IS NULL
                   OR pg_catalog.char_length(search_pattern) < 3
                   OR pg_catalog.char_length(search_pattern) > 202
                THEN
                    RAISE EXCEPTION
                        'Invalid Live Stock search pattern.'
                        USING ERRCODE = '22023';
                END IF;

                query_sql := query_sql || pg_catalog.format(
                    ' AND pg_catalog.lower('
                    '(((pv.name)::text || '' ''::text) || '
                    '(pv.sku)::text)'
                    ') LIKE %L',
                    search_pattern
                );
            END LOOP;

            RETURN QUERY EXECUTE query_sql
                USING expected_company_id;
        END;
        $live_stock_search$
        """
    )

    runtime_role = _runtime_role().replace('"', '""')
    quoted_runtime_role = f'"{runtime_role}"'
    op.execute(
        f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION {FUNCTION_SIGNATURE} "
        f"TO {quoted_runtime_role}"
    )

    op.execute("ANALYZE public.product_variants")


def downgrade() -> None:
    _assert_search_definer_role()

    op.execute(
        f"DROP FUNCTION IF EXISTS {FUNCTION_SIGNATURE}"
    )

    ctx = op.get_context()
    with ctx.autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS public.{INDEX_NAME}"
        )

    # Extensions are intentionally retained because they are shared
    # database capabilities and may be used by other objects.
