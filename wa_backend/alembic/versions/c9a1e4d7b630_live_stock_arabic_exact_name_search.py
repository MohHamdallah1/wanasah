"""Indexed exact Arabic orthographic matching for Live Stock names.

Revision ID: c9a1e4d7b630
Revises: a6f9c3d7e210
"""

import os
import re

from alembic import op
from sqlalchemy.engine import make_url

revision = "c9a1e4d7b630"
down_revision = "a6f9c3d7e210"
branch_labels = None
depends_on = None

_INDEX = "ix_product_variants_company_arabic_name_trgm"


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION public.live_stock_normalize_arabic(value text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE STRICT PARALLEL SAFE
        SET search_path = pg_catalog, pg_temp
        AS $live_stock_arabic$
          SELECT pg_catalog.translate(
            pg_catalog.translate(
              pg_catalog.lower(value),
              'أإآٱىؤئ', 'اااايوي'
            ),
            'ًٌٍَُِّْـ', ''
          )
        $live_stock_arabic$
    """)
    runtime_url = os.getenv("DATABASE_URL")
    if not runtime_url:
        raise RuntimeError("DATABASE_URL required for Arabic search function grant")
    role = make_url(runtime_url).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Unsafe runtime database role")
    op.execute("REVOKE ALL ON FUNCTION public.live_stock_normalize_arabic(text) FROM PUBLIC")
    op.execute(
        f'GRANT EXECUTE ON FUNCTION public.live_stock_normalize_arabic(text) TO "{role}"'
    )
    with op.get_context().autocommit_block():
        op.execute(f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX}
            ON public.product_variants
            USING gin (
                company_id,
                public.live_stock_normalize_arabic((name)::text) gin_trgm_ops
            )
        """)
    # Exactly the original tenant-checked, row-security guarded definer.
    op.execute("""
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
            arabic_search boolean := false;
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

                IF search_pattern ~ '[ء-ي]' THEN
                    arabic_search := true;
                END IF;
            END LOOP;

            FOREACH search_pattern IN ARRAY search_patterns
            LOOP
                IF arabic_search THEN
                    query_sql := query_sql || pg_catalog.format(
                        ' AND public.live_stock_normalize_arabic((pv.name)::text) LIKE %L',
                        search_pattern
                    );
                    -- Exact numeric size: 2 must not accidentally match 12/20.
                    IF pg_catalog.btrim(search_pattern, '%') ~ '^[0-9]+$' THEN
                        query_sql := query_sql || pg_catalog.format(
                            ' AND public.live_stock_normalize_arabic((pv.name)::text) ~ %L',
                            '(^|[^[:alnum:]])' ||
                            pg_catalog.btrim(search_pattern, '%') ||
                            '([^[:alnum:]]|$)'
                        );
                    END IF;
                ELSE
                    query_sql := query_sql || pg_catalog.format(
                        ' AND pg_catalog.lower('
                        '(((pv.name)::text || '' ''::text) || '
                        '(pv.sku)::text)'
                        ') LIKE %L',
                        search_pattern
                    );
                END IF;
            END LOOP;

            RETURN QUERY EXECUTE query_sql
                USING expected_company_id;
        END;
        $live_stock_search$
    """)
    op.execute("ANALYZE public.product_variants")


def downgrade() -> None:
    op.execute("""
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
    """)
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS public.{_INDEX}")
    op.execute("DROP FUNCTION IF EXISTS public.live_stock_normalize_arabic(text)")
