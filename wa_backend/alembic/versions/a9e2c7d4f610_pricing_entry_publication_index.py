"""Add the Pricing publication lookup index without blocking ordinary writes.

Revision ID: a9e2c7d4f610
Revises: a42c9f17e6b3

Deploy online with DATABASE_URL_MIGRATION and one schema migration runner.
Commit the upgrade to the parent revision separately before applying this
revision: env.py uses a transaction for the migration run, and Alembic's
autocommit_block commits that transaction before concurrent DDL. A concurrent
build is durable independently of the later Alembic version-table update.

Recovery: a matching valid index is accepted on retry if the build succeeded
but version recording failed. An INVALID/not-ready index, a name collision, or
an equivalent index under another name stops the upgrade; IF NOT EXISTS alone
cannot establish correctness. No existing index is removed or renamed here.
After the failed builder has exited, an operator must inspect the definition
and dependencies, remove ONLY this revision's matching failed index with
DROP INDEX CONCURRENTLY public.ix_price_book_entry_company_publication outside
a transaction, and retry this revision. Resolve unrelated drift separately.

Rollback drops only this revision's matching index, concurrently and without
CASCADE. A missing index permits retry after a successful drop but lost version
update. Preserve earlier indexes, constraints, triggers, RLS and pricing data.
Concurrent DDL can wait for old transactions and adds CPU/I/O, disk and WAL
load. Use an appropriate maintenance window and existing session timeouts;
cancellation/timeouts follow the same failed-build recovery above.
"""
from __future__ import annotations

from alembic import context, op
from sqlalchemy import text


revision = "a9e2c7d4f610"
down_revision = "a42c9f17e6b3"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_price_book_entry_company_publication"


def _catalog_indexes():
    if context.is_offline_mode():
        raise RuntimeError(
            "Pricing publication index migration requires online PostgreSQL "
            "catalog checks; offline --sql mode is not supported."
        )
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Pricing publication index requires PostgreSQL.")

    # Read catalog metadata only, never tenant-owned pricing rows. Include any
    # public object occupying our name, even when it is not an index on our table.
    return bind.execute(text("""
        SELECT
            rel.relname AS name,
            idx.indisvalid AS valid,
            idx.indisready AS ready,
            idx.indislive AS live,
            (
                rel.relkind = 'i'
                AND idx.indrelid =
                    pg_catalog.to_regclass('public.price_book_entries')
                AND tab.relkind = 'r'
                AND am.amname = 'btree'
                AND NOT idx.indisunique
                AND NOT idx.indisprimary
                AND NOT idx.indisexclusion
                AND idx.indnatts = 2
                AND idx.indnkeyatts = 2
                AND idx.indpred IS NULL
                AND idx.indexprs IS NULL
                AND idx.indkey[0] = company_column.attnum
                AND idx.indkey[1] = publication_column.attnum
                AND idx.indoption[0] = 0
                AND idx.indoption[1] = 0
                AND idx.indcollation[0] = company_column.attcollation
                AND idx.indcollation[1] = publication_column.attcollation
                AND idx.indclass[0] = (
                    SELECT opc.oid FROM pg_catalog.pg_opclass AS opc
                    WHERE opc.opcmethod = rel.relam
                      AND opc.opcintype = company_column.atttypid
                      AND opc.opcdefault
                )
                AND idx.indclass[1] = (
                    SELECT opc.oid FROM pg_catalog.pg_opclass AS opc
                    WHERE opc.opcmethod = rel.relam
                      AND opc.opcintype = publication_column.atttypid
                      AND opc.opcdefault
                )
                AND NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_constraint AS constraint_row
                    WHERE constraint_row.conindid = rel.oid
                )
            ) AS matches
        FROM pg_catalog.pg_class AS rel
        JOIN pg_catalog.pg_namespace AS ns ON ns.oid = rel.relnamespace
        LEFT JOIN pg_catalog.pg_index AS idx ON idx.indexrelid = rel.oid
        LEFT JOIN pg_catalog.pg_class AS tab ON tab.oid = idx.indrelid
        LEFT JOIN pg_catalog.pg_am AS am ON am.oid = rel.relam
        LEFT JOIN pg_catalog.pg_attribute AS company_column
          ON company_column.attrelid = idx.indrelid
         AND company_column.attname = 'company_id'
         AND NOT company_column.attisdropped
        LEFT JOIN pg_catalog.pg_attribute AS publication_column
          ON publication_column.attrelid = idx.indrelid
         AND publication_column.attname = 'publication_id'
         AND NOT publication_column.attisdropped
        WHERE ns.nspname = 'public'
          AND (
              rel.relname = :index_name
              OR idx.indrelid =
                  pg_catalog.to_regclass('public.price_book_entries')
          )
        ORDER BY rel.relname
    """), {"index_name": INDEX_NAME}).mappings().all()


def _require_definition(row) -> None:
    if not bool(row["matches"]):
        raise RuntimeError(
            f"public.{INDEX_NAME} has an unexpected definition or dependency; "
            "resolve schema drift explicitly. No object was replaced."
        )


def _require_usable(row) -> None:
    _require_definition(row)
    if not all(bool(row[key]) for key in ("valid", "ready", "live")):
        raise RuntimeError(
            f"public.{INDEX_NAME} is not valid, ready and live. "
            "Wait for any builder to exit, inspect the failed index, then "
            "follow this revision's recovery instructions before retrying."
        )


def upgrade() -> None:
    rows = _catalog_indexes()
    existing = next((row for row in rows if row["name"] == INDEX_NAME), None)
    if existing is not None:
        _require_usable(existing)
        return

    equivalent = next((row for row in rows if bool(row["matches"])), None)
    if equivalent is not None:
        raise RuntimeError(
            "An equivalent publication index already exists under another "
            "name; reconcile naming explicitly before retrying. "
            "No duplicate index was created or existing index changed."
        )

    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY {INDEX_NAME} "
            "ON public.price_book_entries USING btree "
            "(company_id, publication_id)"
        )

    # Verify before Alembic advances the revision. No silent acceptance of an
    # invalid build, or a mismatched same-name object on a later retry.
    created = next(
        (row for row in _catalog_indexes() if row["name"] == INDEX_NAME),
        None,
    )
    if created is None:
        raise RuntimeError("Pricing publication index is missing after build.")
    _require_usable(created)


def downgrade() -> None:
    existing = next(
        (row for row in _catalog_indexes() if row["name"] == INDEX_NAME),
        None,
    )
    if existing is None:
        return
    # A matching failed/interrupted index may also need removal. Do not require
    # validity here, but never drop a different object or use CASCADE.
    _require_definition(existing)
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY public.{INDEX_NAME}")
