"""Use native trigram search for Simple Products under forced RLS.

Revision ID: c1f4e8a2d6b9
Revises: b6e3a1f9c4d2
"""

from __future__ import annotations

import os
import re

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import make_url


revision = "c1f4e8a2d6b9"
down_revision = "b6e3a1f9c4d2"
branch_labels = None
depends_on = None

FUNCTION_SIGNATURE = (
    "public.simple_products_search_variant_ids("
    "integer, text[], timestamp without time zone)"
)


def _assert_search_definer_role() -> None:
    bind = op.get_bind()
    role = bind.execute(
        text(
            """
            SELECT
                current_user AS current_user,
                role.rolsuper AS is_superuser,
                role.rolbypassrls AS bypass_rls
            FROM pg_roles AS role
            WHERE role.rolname = current_user
            """
        )
    ).mappings().one()

    if not (
        bool(role["is_superuser"])
        or bool(role["bypass_rls"])
    ):
        raise RuntimeError(
            "Simple Products search function owner must "
            "bypass RLS. Use DATABASE_URL_MIGRATION."
        )

    for table_name in (
        "product_variants",
        "products",
        "product_barcodes",
    ):
        can_select = bool(
            bind.execute(
                text(
                    "SELECT has_table_privilege("
                    "current_user, :table_name, 'SELECT')"
                ),
                {"table_name": f"public.{table_name}"},
            ).scalar_one()
        )
        if not can_select:
            raise RuntimeError(
                "Migration role must have SELECT on "
                f"public.{table_name}."
            )


def _runtime_role() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError(
            "DATABASE_URL is required to grant runtime "
            "function execution."
        )
    role = make_url(raw).username
    if (
        not role
        or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_$]*",
            role,
        )
    ):
        raise RuntimeError(
            "Runtime database role could not be resolved safely."
        )
    return role


def upgrade() -> None:
    _assert_search_definer_role()

    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            public.simple_products_search_variant_ids(
                expected_company_id integer,
                search_patterns text[],
                effective_at timestamp without time zone
            )
        RETURNS SETOF integer
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        SET row_security = off
        AS $simple_products_search$
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
                RAISE EXCEPTION
                    'Simple Products tenant context mismatch.'
                    USING ERRCODE = '42501';
            END IF;

            IF effective_at IS NULL THEN
                RAISE EXCEPTION
                    'Simple Products search timestamp is required.'
                    USING ERRCODE = '22023';
            END IF;

            IF search_patterns IS NULL
               OR pg_catalog.array_length(
                    search_patterns,
                    1
               ) IS NULL
               OR pg_catalog.array_length(
                    search_patterns,
                    1
               ) > 100
            THEN
                RAISE EXCEPTION
                    'Invalid Simple Products search patterns.'
                    USING ERRCODE = '22023';
            END IF;

            query_sql :=
                'SELECT pv.id '
                'FROM public.product_variants AS pv '
                'WHERE pv.company_id = $1';

            FOREACH search_pattern
                IN ARRAY search_patterns
            LOOP
                IF search_pattern IS NULL
                   OR pg_catalog.char_length(
                        search_pattern
                   ) < 3
                   OR pg_catalog.char_length(
                        search_pattern
                   ) > 202
                THEN
                    RAISE EXCEPTION
                        'Invalid Simple Products search pattern.'
                        USING ERRCODE = '22023';
                END IF;

                query_sql := query_sql
                    || pg_catalog.format(
                        ' AND ('
                        'pg_catalog.lower('
                        '(((pv.name)::text || '' ''::text) '
                        '|| (pv.sku)::text)'
                        ') LIKE %L '
                        'OR EXISTS ('
                        'SELECT 1 '
                        'FROM public.products AS p '
                        'WHERE p.company_id = $1 '
                        'AND p.id = pv.product_id '
                        'AND pg_catalog.lower('
                        '(p.name)::text'
                        ') LIKE %L'
                        ') '
                        'OR EXISTS ('
                        'SELECT 1 '
                        'FROM public.product_barcodes AS pb '
                        'WHERE pb.company_id = $1 '
                        'AND pb.product_variant_id = pv.id '
                        'AND pb.is_active IS TRUE '
                        'AND pb.valid_from <= $2 '
                        'AND ('
                        'pb.valid_to IS NULL '
                        'OR pb.valid_to > $2'
                        ') '
                        'AND pg_catalog.lower('
                        '(pb.barcode)::text'
                        ') LIKE %L'
                        ')'
                        ')',
                        search_pattern,
                        search_pattern,
                        search_pattern
                    );
            END LOOP;

            RETURN QUERY EXECUTE query_sql
                USING expected_company_id, effective_at;
        END;
        $simple_products_search$
        """
    )

    runtime_role = _runtime_role().replace('"', '""')
    quoted_runtime_role = f'"{runtime_role}"'
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"{FUNCTION_SIGNATURE} FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION "
        f"{FUNCTION_SIGNATURE} TO {quoted_runtime_role}"
    )


def downgrade() -> None:
    _assert_search_definer_role()
    op.execute(
        f"DROP FUNCTION IF EXISTS {FUNCTION_SIGNATURE}"
    )
