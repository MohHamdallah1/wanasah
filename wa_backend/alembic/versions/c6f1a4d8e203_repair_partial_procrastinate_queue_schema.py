"""Repair partial Procrastinate 3.9 queue schemas without risking queued jobs.

Revision ID: c6f1a4d8e203
Revises: a5d7c2e4f901
"""

from __future__ import annotations

import os
import re
from importlib import metadata, resources

import psycopg
from alembic import op
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url


revision = "c6f1a4d8e203"
down_revision = "a5d7c2e4f901"
branch_labels = None
depends_on = None

_EXPECTED_PROCRASTINATE_VERSION = "3.9.0"
_QUEUE_SCHEMAS = ("public", "worker_queue")
_QUEUE_TABLES = (
    "procrastinate_workers",
    "procrastinate_jobs",
    "procrastinate_periodic_defers",
    "procrastinate_events",
)
_QUEUE_TYPES = (
    "procrastinate_job_status",
    "procrastinate_job_event_type",
    "procrastinate_job_to_defer_v1",
)
_REQUIRED_FUNCTION = "procrastinate_prune_stalled_workers_v1(double precision)"


def _plain_postgres_dsn(raw: str) -> str:
    url = make_url(raw)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("Procrastinate queue requires PostgreSQL.")
    return url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )


def _roles_and_dsn() -> tuple[str, str]:
    runtime_raw = os.getenv("DATABASE_URL")
    migration_raw = os.getenv("DATABASE_URL_MIGRATION")
    if not runtime_raw or not migration_raw:
        raise RuntimeError(
            "DATABASE_URL and DATABASE_URL_MIGRATION are required for queue repair."
        )

    runtime_url = make_url(runtime_raw)
    migration_url = make_url(migration_raw)
    runtime_role = runtime_url.username
    migration_role = migration_url.username
    if not runtime_role or not migration_role:
        raise RuntimeError("Database role names could not be resolved from the URLs.")
    if runtime_role == migration_role:
        raise RuntimeError(
            "Runtime and migration roles must remain separate for queue repair."
        )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", runtime_role):
        raise RuntimeError("Runtime database role could not be resolved safely.")
    return runtime_role, _plain_postgres_dsn(migration_raw)


def _schema_sql() -> str:
    installed = metadata.version("procrastinate")
    if installed != _EXPECTED_PROCRASTINATE_VERSION:
        raise RuntimeError(
            "This migration is pinned to Procrastinate "
            f"{_EXPECTED_PROCRASTINATE_VERSION}; installed={installed}."
        )
    return (
        resources.files("procrastinate")
        .joinpath("sql")
        .joinpath("schema.sql")
        .read_text(encoding="utf-8")
    )


def _expected_function_names(schema_sql: str) -> set[str]:
    return {
        name.lower()
        for name in re.findall(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(procrastinate_[A-Za-z0-9_]+)",
            schema_sql,
            flags=re.IGNORECASE,
        )
    }


def _set_search_path(conn: psycopg.Connection, schema_name: str) -> None:
    conn.execute(
        sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema_name))
    )


def _queue_is_complete(
    conn: psycopg.Connection,
    schema_sql: str,
    schema_name: str,
) -> bool:
    for table_name in _QUEUE_TABLES:
        exists = conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL",
            [f"{schema_name}.{table_name}"],
        ).fetchone()[0]
        if not exists:
            return False

    for type_name in _QUEUE_TYPES:
        exists = conn.execute(
            "SELECT to_regtype(%s) IS NOT NULL",
            [f"{schema_name}.{type_name}"],
        ).fetchone()[0]
        if not exists:
            return False

    required_signature = conn.execute(
        "SELECT to_regprocedure(%s) IS NOT NULL",
        [f"{schema_name}.{_REQUIRED_FUNCTION}"],
    ).fetchone()[0]
    if not required_signature:
        return False

    expected_functions = _expected_function_names(schema_sql)
    actual_functions = {
        str(row[0]).lower()
        for row in conn.execute(
            """
            SELECT p.proname
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = %s
              AND p.proname LIKE 'procrastinate_%%'
            """,
            [schema_name],
        ).fetchall()
    }
    return expected_functions.issubset(actual_functions)


def _queue_row_count(conn: psycopg.Connection, schema_name: str) -> int:
    total = 0
    for table_name in _QUEUE_TABLES:
        exists = conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL",
            [f"{schema_name}.{table_name}"],
        ).fetchone()[0]
        if exists:
            total += int(
                conn.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(schema_name),
                        sql.Identifier(table_name),
                    )
                ).fetchone()[0]
            )
    return total


def _drop_partial_queue(conn: psycopg.Connection, schema_name: str) -> None:
    _set_search_path(conn, schema_name)
    functions = conn.execute(
        """
        SELECT p.oid::regprocedure::text
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = %s
          AND p.proname LIKE 'procrastinate_%%'
        ORDER BY p.oid
        """,
        [schema_name],
    ).fetchall()
    for (signature,) in functions:
        conn.execute(
            sql.SQL("DROP FUNCTION IF EXISTS {} CASCADE").format(
                sql.SQL(str(signature))
            )
        )

    for table_name in reversed(_QUEUE_TABLES):
        conn.execute(
            sql.SQL("DROP TABLE IF EXISTS {}.{} CASCADE").format(
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
            )
        )

    for type_name in _QUEUE_TYPES:
        conn.execute(
            sql.SQL("DROP TYPE IF EXISTS {}.{} CASCADE").format(
                sql.Identifier(schema_name),
                sql.Identifier(type_name),
            )
        )


def _install_queue_schema(
    conn: psycopg.Connection,
    schema_sql: str,
    schema_name: str,
) -> None:
    _set_search_path(conn, schema_name)
    conn.execute(schema_sql)


def _repair_queue_structure(
    conn: psycopg.Connection,
    schema_sql: str,
    schema_name: str,
) -> None:
    if schema_name != "public":
        conn.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(schema_name)
            )
        )

    if not _queue_is_complete(conn, schema_sql, schema_name):
        queued_rows = _queue_row_count(conn, schema_name)
        if queued_rows:
            raise RuntimeError(
                f"Refusing to rebuild incomplete Procrastinate schema {schema_name!r} "
                f"while queue tables contain {queued_rows} rows. Drain or migrate "
                "that queue explicitly before retrying."
            )
        _drop_partial_queue(conn, schema_name)
        _install_queue_schema(conn, schema_sql, schema_name)

    if not _queue_is_complete(conn, schema_sql, schema_name):
        raise RuntimeError(
            f"Procrastinate 3.9 queue repair did not produce a complete {schema_name!r} schema."
        )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _grant_runtime_privileges(runtime_role: str, schema_name: str) -> None:
    """Grant queue privileges through Alembic's own transaction.

    The queue structure is installed with a privileged psycopg connection because
    Procrastinate ships its schema as multi-statement SQL.  Grants deliberately run
    through Alembic's current connection so a clean bootstrap never waits on locks
    held by earlier security migrations in the same Alembic transaction.
    """
    bind = op.get_bind()
    quoted_role = _quote_identifier(runtime_role)
    quoted_schema = _quote_identifier(schema_name)

    op.execute(f"GRANT USAGE ON SCHEMA {quoted_schema} TO {quoted_role}")
    op.execute(f"REVOKE CREATE ON SCHEMA {quoted_schema} FROM {quoted_role}")

    for table_name in _QUEUE_TABLES:
        quoted_table = _quote_identifier(table_name)
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            f"{quoted_schema}.{quoted_table} TO {quoted_role}"
        )

    sequences = bind.execute(
        text(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema_name
              AND c.relkind = 'S'
              AND c.relname LIKE 'procrastinate_%'
            ORDER BY c.relname
            """
        ),
        {"schema_name": schema_name},
    ).scalars().all()
    for sequence_name in sequences:
        quoted_sequence = _quote_identifier(str(sequence_name))
        op.execute(
            f"GRANT USAGE, SELECT, UPDATE ON SEQUENCE "
            f"{quoted_schema}.{quoted_sequence} TO {quoted_role}"
        )

    functions = bind.execute(
        text(
            """
            SELECT p.oid::regprocedure::text
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = :schema_name
              AND p.proname LIKE 'procrastinate_%'
            ORDER BY p.oid
            """
        ),
        {"schema_name": schema_name},
    ).scalars().all()
    for signature in functions:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {quoted_role}")

    for type_name in _QUEUE_TYPES:
        quoted_type = _quote_identifier(type_name)
        op.execute(
            f"GRANT USAGE ON TYPE {quoted_schema}.{quoted_type} TO {quoted_role}"
        )


def upgrade() -> None:
    runtime_role, migration_dsn = _roles_and_dsn()
    schema_sql = _schema_sql()

    # Structural repair uses the migration role and commits before Alembic grants
    # privileges.  Keeping role grants out of this side connection prevents lock
    # waits against the runtime-access migration during a fresh bootstrap.
    with psycopg.connect(migration_dsn) as conn:
        for schema_name in _QUEUE_SCHEMAS:
            _repair_queue_structure(conn, schema_sql, schema_name)

    for schema_name in _QUEUE_SCHEMAS:
        _grant_runtime_privileges(runtime_role, schema_name)


def downgrade() -> None:
    # Operational repair is intentionally non-destructive on downgrade: removing a
    # healthy worker queue would be more dangerous than retaining the repaired schema.
    pass
