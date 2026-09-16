"""Install Procrastinate 3.9 queue schema through the privileged migration role.

Revision ID: f8c4e6a2b1d9
Revises: f7a1c3d5e9b2
"""

from __future__ import annotations

import os
from importlib import metadata, resources

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


revision = "f8c4e6a2b1d9"
down_revision = "f7a1c3d5e9b2"
branch_labels = None
depends_on = None

_EXPECTED_PROCRASTINATE_VERSION = "3.9.0"
_QUEUE_TABLES = (
    "procrastinate_workers",
    "procrastinate_jobs",
    "procrastinate_periodic_defers",
    "procrastinate_events",
)


def _plain_postgres_dsn(raw: str) -> str:
    url = make_url(raw)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("Procrastinate queue requires PostgreSQL.")
    return url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )


def _roles_and_dsn() -> tuple[str, str, str]:
    runtime_raw = os.getenv("DATABASE_URL")
    migration_raw = os.getenv("DATABASE_URL_MIGRATION")
    if not runtime_raw:
        raise RuntimeError(
            "DATABASE_URL is required so the migration can grant the runtime role "
            "only the queue privileges it needs."
        )
    if not migration_raw:
        raise RuntimeError(
            "DATABASE_URL_MIGRATION is required. Queue DDL must not run through "
            "the restricted runtime DATABASE_URL."
        )

    runtime_url = make_url(runtime_raw)
    migration_url = make_url(migration_raw)
    runtime_role = runtime_url.username
    migration_role = migration_url.username
    if not runtime_role or not migration_role:
        raise RuntimeError("Database role names could not be resolved from the URLs.")
    if runtime_role == migration_role:
        raise RuntimeError(
            "DATABASE_URL and DATABASE_URL_MIGRATION must use different roles. "
            "The runtime role must remain restricted from schema DDL."
        )
    return (
        runtime_role,
        migration_role,
        _plain_postgres_dsn(migration_raw),
    )


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


def _partial_queue_objects(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT object_name
        FROM (
            SELECT c.relname AS object_name
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname LIKE 'procrastinate_%'

            UNION

            SELECT p.proname AS object_name
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
              AND p.proname LIKE 'procrastinate_%'

            UNION

            SELECT t.typname AS object_name
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE n.nspname = 'public'
              AND t.typname LIKE 'procrastinate_%'
        ) q
        ORDER BY object_name
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _grant_runtime_privileges(
    conn: psycopg.Connection,
    runtime_role: str,
) -> None:
    role = sql.Identifier(runtime_role)

    exists = conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s",
        [runtime_role],
    ).fetchone()
    if exists is None:
        raise RuntimeError(
            f"Runtime database role {runtime_role!r} does not exist."
        )

    conn.execute(
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role)
    )
    conn.execute(
        sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(role)
    )

    for table_name in _QUEUE_TABLES:
        conn.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}"
            ).format(
                sql.Identifier(table_name),
                role,
            )
        )

    sequences = conn.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'S'
          AND c.relname LIKE 'procrastinate_%'
        ORDER BY c.relname
        """
    ).fetchall()
    for (sequence_name,) in sequences:
        conn.execute(
            sql.SQL(
                "GRANT USAGE, SELECT, UPDATE ON SEQUENCE {} TO {}"
            ).format(
                sql.Identifier(str(sequence_name)),
                role,
            )
        )

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
            sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                sql.SQL(str(signature)),
                role,
            )
        )

    types = conn.execute(
        """
        SELECT t.typname
        FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public'
          AND t.typname IN (
              'procrastinate_job_status',
              'procrastinate_job_event_type',
              'procrastinate_job_to_defer_v1'
          )
        ORDER BY t.typname
        """
    ).fetchall()
    for (type_name,) in types:
        conn.execute(
            sql.SQL("GRANT USAGE ON TYPE {} TO {}").format(
                sql.Identifier(str(type_name)),
                role,
            )
        )


def upgrade() -> None:
    runtime_role, _migration_role, migration_dsn = _roles_and_dsn()
    schema_sql = _schema_sql()

    with psycopg.connect(migration_dsn) as conn:
        queue_table = conn.execute(
            "SELECT to_regclass('public.procrastinate_jobs')"
        ).fetchone()[0]

        if queue_table is None:
            partial = _partial_queue_objects(conn)
            if partial:
                raise RuntimeError(
                    "Refusing to install over a partial Procrastinate schema: "
                    + ", ".join(partial[:20])
                )
            conn.execute(schema_sql)

        missing = [
            table_name
            for table_name in _QUEUE_TABLES
            if conn.execute(
                "SELECT to_regclass(%s)",
                [f"public.{table_name}"],
            ).fetchone()[0]
            is None
        ]
        if missing:
            raise RuntimeError(
                "Procrastinate schema installation incomplete: "
                + ", ".join(missing)
            )

        _grant_runtime_privileges(conn, runtime_role)


def downgrade() -> None:
    _runtime_role, _migration_role, migration_dsn = _roles_and_dsn()

    with psycopg.connect(migration_dsn) as conn:
        jobs = conn.execute(
            "SELECT to_regclass('public.procrastinate_jobs')"
        ).fetchone()[0]
        if jobs is None:
            return

        count = conn.execute(
            "SELECT count(*) FROM procrastinate_jobs"
        ).fetchone()[0]
        if int(count or 0) != 0:
            raise RuntimeError(
                "Refusing destructive downgrade: Procrastinate contains jobs."
            )

        functions = conn.execute(
            """
            SELECT p.oid::regprocedure::text
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
              AND p.proname LIKE 'procrastinate_%'
            ORDER BY p.oid DESC
            """
        ).fetchall()
        for (signature,) in functions:
            conn.execute(
                sql.SQL("DROP FUNCTION IF EXISTS {} CASCADE").format(
                    sql.SQL(str(signature))
                )
            )

        for table_name in (
            "procrastinate_events",
            "procrastinate_periodic_defers",
            "procrastinate_jobs",
            "procrastinate_workers",
        ):
            conn.execute(
                sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                    sql.Identifier(table_name)
                )
            )

        for type_name in (
            "procrastinate_job_to_defer_v1",
            "procrastinate_job_event_type",
            "procrastinate_job_status",
        ):
            conn.execute(
                sql.SQL("DROP TYPE IF EXISTS {} CASCADE").format(
                    sql.Identifier(type_name)
                )
            )
