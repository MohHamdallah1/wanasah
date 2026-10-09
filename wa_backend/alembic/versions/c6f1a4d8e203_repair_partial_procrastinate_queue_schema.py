"""Repair a partial Procrastinate 3.9 queue schema without risking queued jobs.

Revision ID: c6f1a4d8e203
Revises: a5d7c2e4f901
"""

from __future__ import annotations

import os
import re
from importlib import metadata, resources

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


revision = "c6f1a4d8e203"
down_revision = "a5d7c2e4f901"
branch_labels = None
depends_on = None

_EXPECTED_PROCRASTINATE_VERSION = "3.9.0"
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
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


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


def _queue_is_complete(conn: psycopg.Connection, schema_sql: str) -> bool:
    for table_name in _QUEUE_TABLES:
        exists = conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL",
            [f"public.{table_name}"],
        ).fetchone()[0]
        if not exists:
            return False

    for type_name in _QUEUE_TYPES:
        exists = conn.execute(
            "SELECT to_regtype(%s) IS NOT NULL",
            [f"public.{type_name}"],
        ).fetchone()[0]
        if not exists:
            return False

    required_signature = conn.execute(
        "SELECT to_regprocedure(%s) IS NOT NULL",
        [f"public.{_REQUIRED_FUNCTION}"],
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
            WHERE n.nspname = 'public'
              AND p.proname LIKE 'procrastinate_%'
            """
        ).fetchall()
    }
    return expected_functions.issubset(actual_functions)


def _queue_row_count(conn: psycopg.Connection) -> int:
    total = 0
    for table_name in _QUEUE_TABLES:
        exists = conn.execute(
            "SELECT to_regclass(%s) IS NOT NULL",
            [f"public.{table_name}"],
        ).fetchone()[0]
        if exists:
            total += int(
                conn.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(
                        sql.Identifier(table_name)
                    )
                ).fetchone()[0]
            )
    return total


def _drop_partial_queue(conn: psycopg.Connection) -> None:
    functions = conn.execute(
        """
        SELECT p.oid::regprocedure::text
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.proname LIKE 'procrastinate_%'
        ORDER BY p.oid
        """
    ).fetchall()
    for (signature,) in functions:
        conn.execute(
            sql.SQL("DROP FUNCTION IF EXISTS {} CASCADE").format(
                sql.SQL(str(signature))
            )
        )

    for table_name in reversed(_QUEUE_TABLES):
        conn.execute(
            sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                sql.Identifier(table_name)
            )
        )

    for type_name in _QUEUE_TYPES:
        conn.execute(
            sql.SQL("DROP TYPE IF EXISTS {} CASCADE").format(
                sql.Identifier(type_name)
            )
        )


def _grant_runtime_privileges(conn: psycopg.Connection, runtime_role: str) -> None:
    role = sql.Identifier(runtime_role)
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    conn.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(role))

    for table_name in _QUEUE_TABLES:
        conn.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}"
            ).format(sql.Identifier(table_name), role)
        )

    sequences = conn.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'S'
          AND c.relname LIKE 'procrastinate_%'
        """
    ).fetchall()
    for (sequence_name,) in sequences:
        conn.execute(
            sql.SQL("GRANT USAGE, SELECT, UPDATE ON SEQUENCE {} TO {}").format(
                sql.Identifier(str(sequence_name)), role
            )
        )

    functions = conn.execute(
        """
        SELECT p.oid::regprocedure::text
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.proname LIKE 'procrastinate_%'
        """
    ).fetchall()
    for (signature,) in functions:
        conn.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                sql.SQL(str(signature)), role
            )
        )

    for type_name in _QUEUE_TYPES:
        conn.execute(
            sql.SQL("GRANT USAGE ON TYPE {} TO {}").format(
                sql.Identifier(type_name), role
            )
        )


def upgrade() -> None:
    runtime_role, migration_dsn = _roles_and_dsn()
    schema_sql = _schema_sql()

    with psycopg.connect(migration_dsn) as conn:
        if not _queue_is_complete(conn, schema_sql):
            queued_rows = _queue_row_count(conn)
            if queued_rows:
                raise RuntimeError(
                    "Refusing to rebuild an incomplete Procrastinate schema while "
                    f"queue tables contain {queued_rows} rows. Drain or migrate the "
                    "queue explicitly before retrying."
                )
            _drop_partial_queue(conn)
            conn.execute(schema_sql)

        if not _queue_is_complete(conn, schema_sql):
            raise RuntimeError(
                "Procrastinate 3.9 queue repair did not produce a complete schema."
            )

        _grant_runtime_privileges(conn, runtime_role)


def downgrade() -> None:
    # Operational repair is intentionally non-destructive on downgrade: removing a
    # healthy worker queue would be more dangerous than retaining the repaired schema.
    pass
