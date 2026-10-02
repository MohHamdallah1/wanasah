"""Add an RLS-safe exact family-name resolver and matching expression index.

Revision ID: d7c4a8e1f205
Revises: a9e2c7d4f610

The runtime app role is subject to FORCE RLS. PostgreSQL cannot reliably push
non-LEAKPROOF lower(name) predicates into an expression-index scan below the
security barrier, so exact family-name resolution uses a tightly-scoped
SECURITY DEFINER function that:
- verifies app.current_tenant matches the requested company,
- validates a bounded array of already-normalized names,
- disables row_security only inside the function,
- returns at most the first two Product ids per name (the existing ambiguity
  contract), and
- is executable only by the runtime DB role.

The supporting B-tree index is built CONCURRENTLY:
    (company_id, lower((name)::text), id)

Retry semantics mirror other online-index migrations: a matching VALID/READY
index is accepted; INVALID or conflicting same-name schema stops the migration
for explicit operator recovery. No existing index is removed.
"""
from __future__ import annotations

import os
import re

from alembic import context, op
from sqlalchemy import text
from sqlalchemy.engine import make_url

revision = "d7c4a8e1f205"
down_revision = "a9e2c7d4f610"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_product_company_lower_name_id"
FUNCTION_SIGNATURE = (
    "public.simple_products_family_match_ids(integer, text[])"
)


def _runtime_role() -> str:
    raw = os.getenv("DATABASE_URL")
    if not raw:
        raise RuntimeError(
            "DATABASE_URL is required to grant runtime family resolver execution."
        )
    role = make_url(raw).username
    if not role or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", role):
        raise RuntimeError("Runtime database role could not be resolved safely.")
    return role


def _assert_definer_role() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "Family resolver migration requires online PostgreSQL catalog checks."
        )
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Family resolver requires PostgreSQL.")
    role = bind.execute(
        text(
            """
            SELECT rol.rolsuper AS is_superuser,
                   rol.rolbypassrls AS bypass_rls
            FROM pg_catalog.pg_roles AS rol
            WHERE rol.rolname = current_user
            """
        )
    ).mappings().one()
    if not (bool(role["is_superuser"]) or bool(role["bypass_rls"])):
        raise RuntimeError(
            "Family resolver owner must bypass RLS. Use DATABASE_URL_MIGRATION."
        )
    if not bool(
        bind.execute(
            text(
                "SELECT has_table_privilege("
                "current_user, 'public.products', 'SELECT')"
            )
        ).scalar_one()
    ):
        raise RuntimeError("Migration role must have SELECT on public.products.")


def _catalog_indexes():
    _assert_definer_role()
    bind = op.get_bind()
    return bind.execute(
        text(
            """
            SELECT
                rel.relname AS name,
                idx.indisvalid AS valid,
                idx.indisready AS ready,
                idx.indislive AS live,
                (
                    rel.relkind = 'i'
                    AND idx.indrelid = pg_catalog.to_regclass('public.products')
                    AND am.amname = 'btree'
                    AND NOT idx.indisunique
                    AND NOT idx.indisprimary
                    AND NOT idx.indisexclusion
                    AND idx.indnatts = 3
                    AND idx.indnkeyatts = 3
                    AND idx.indpred IS NULL
                    AND idx.indkey[0] = company_column.attnum
                    AND idx.indkey[1] = 0
                    AND idx.indkey[2] = id_column.attnum
                    AND pg_catalog.pg_get_expr(
                        idx.indexprs, idx.indrelid
                    ) = 'lower((name)::text)'
                    AND NOT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_constraint AS constraint_row
                        WHERE constraint_row.conindid = rel.oid
                    )
                ) AS matches
            FROM pg_catalog.pg_class AS rel
            JOIN pg_catalog.pg_namespace AS ns
              ON ns.oid = rel.relnamespace
            LEFT JOIN pg_catalog.pg_index AS idx
              ON idx.indexrelid = rel.oid
            LEFT JOIN pg_catalog.pg_am AS am
              ON am.oid = rel.relam
            LEFT JOIN pg_catalog.pg_attribute AS company_column
              ON company_column.attrelid = idx.indrelid
             AND company_column.attname = 'company_id'
             AND NOT company_column.attisdropped
            LEFT JOIN pg_catalog.pg_attribute AS id_column
              ON id_column.attrelid = idx.indrelid
             AND id_column.attname = 'id'
             AND NOT id_column.attisdropped
            WHERE ns.nspname = 'public'
              AND (
                  rel.relname = :index_name
                  OR idx.indrelid = pg_catalog.to_regclass('public.products')
              )
            ORDER BY rel.relname
            """
        ),
        {"index_name": INDEX_NAME},
    ).mappings().all()


def _require_index_definition(row) -> None:
    if not bool(row["matches"]):
        raise RuntimeError(
            f"public.{INDEX_NAME} has an unexpected definition or dependency."
        )


def _require_index_usable(row) -> None:
    _require_index_definition(row)
    if not all(bool(row[key]) for key in ("valid", "ready", "live")):
        raise RuntimeError(
            f"public.{INDEX_NAME} is not valid, ready and live. "
            "Inspect/remove only the failed matching index concurrently, then retry."
        )


def _ensure_index() -> None:
    rows = _catalog_indexes()
    existing = next((row for row in rows if row["name"] == INDEX_NAME), None)
    if existing is not None:
        _require_index_usable(existing)
        return

    equivalent = next((row for row in rows if bool(row["matches"])), None)
    if equivalent is not None:
        raise RuntimeError(
            "An equivalent family lower-name index already exists under another "
            "name; reconcile naming explicitly before retrying."
        )

    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY {INDEX_NAME} "
            "ON public.products USING btree "
            "(company_id, lower((name)::text), id)"
        )

    created = next(
        (row for row in _catalog_indexes() if row["name"] == INDEX_NAME),
        None,
    )
    if created is None:
        raise RuntimeError("Family lower-name index is missing after build.")
    _require_index_usable(created)


def _create_function() -> None:
    _assert_definer_role()
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.simple_products_family_match_ids(
            expected_company_id integer,
            normalized_names text[]
        )
        RETURNS TABLE(id integer, normalized text)
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        SET row_security = off
        AS $family_match$
        DECLARE
            tenant_id integer;
            candidate text;
        BEGIN
            tenant_id := NULLIF(
                pg_catalog.current_setting('app.current_tenant', true),
                ''
            )::integer;

            IF tenant_id IS NULL
               OR expected_company_id IS NULL
               OR expected_company_id IS DISTINCT FROM tenant_id
            THEN
                RAISE EXCEPTION 'Simple Products family tenant context mismatch.'
                    USING ERRCODE = '42501';
            END IF;

            IF normalized_names IS NULL
               OR pg_catalog.array_length(normalized_names, 1) IS NULL
               OR pg_catalog.array_length(normalized_names, 1) > 200
            THEN
                RAISE EXCEPTION 'Invalid family-name batch.'
                    USING ERRCODE = '22023';
            END IF;

            FOREACH candidate IN ARRAY normalized_names
            LOOP
                IF candidate IS NULL
                   OR pg_catalog.char_length(candidate) < 1
                   OR pg_catalog.char_length(candidate) > 200
                   OR candidate IS DISTINCT FROM pg_catalog.lower(candidate)
                THEN
                    RAISE EXCEPTION 'Family resolver requires normalized names.'
                        USING ERRCODE = '22023';
                END IF;
            END LOOP;

            RETURN QUERY
            SELECT matched.id, matched.normalized
            FROM (
                SELECT DISTINCT requested_name AS normalized
                FROM pg_catalog.unnest(normalized_names) AS requested_name
            ) AS requested
            CROSS JOIN LATERAL (
                SELECT
                    p.id,
                    pg_catalog.lower((p.name)::text) AS normalized
                FROM public.products AS p
                WHERE p.company_id = expected_company_id
                  AND pg_catalog.lower((p.name)::text) = requested.normalized
                ORDER BY p.id ASC
                LIMIT 2
            ) AS matched
            ORDER BY matched.id ASC;
        END;
        $family_match$
        """
    )

    runtime_role = _runtime_role().replace('"', '""')
    quoted_runtime_role = f'"{runtime_role}"'
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION {FUNCTION_SIGNATURE} "
        f"TO {quoted_runtime_role}"
    )


def upgrade() -> None:
    _ensure_index()
    _create_function()


def downgrade() -> None:
    _assert_definer_role()
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_SIGNATURE}")

    existing = next(
        (row for row in _catalog_indexes() if row["name"] == INDEX_NAME),
        None,
    )
    if existing is None:
        return
    _require_index_definition(existing)
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY public.{INDEX_NAME}")
