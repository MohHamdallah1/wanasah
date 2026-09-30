"""Read-only V1 Product Import deploy inventory, not a production sign-off.

This never migrates, recovers, publishes, deletes, or starts workers.
Only report non-secret configuration and aggregate job metadata.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values, load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
import psycopg

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_RLS_TABLES = (
    "product_import_jobs",
    "product_import_rows",
    "product_import_sources",
    "product_import_schedule_candidates",
    "product_variants",
    "price_book_entries",
)


def _database_endpoint(raw: str, *, name: str) -> tuple[str, int, str]:
    """Compare staging DB identity without comparing or printing passwords."""
    try:
        url = make_url(raw)
        if (
            not url.drivername.startswith("postgresql")
            or not url.host
            or not url.database
        ):
            raise ValueError("incomplete PostgreSQL target")
        return (url.host.lower().rstrip("."), int(url.port or 5432), url.database)
    except (ValueError, ArgumentError):
        raise RuntimeError(
            f"{name} must identify a PostgreSQL host, port and database"
        ) from None


def _bind_env_file_db_target(env_file: Path, *, scope: str) -> None:
    """Refuse staging target ambiguity before opening a database connection.

    dotenv normally prefers inherited variables over --env-file values.
    An operator-supplied staging file must explicitly bind both DB URLs;
    silently following a different inherited URL could inspect the wrong DB.
    Never include a URL or credential in a diagnostic exception.
    """
    declared = dotenv_values(env_file, interpolate=False)
    for name in ("DATABASE_URL_MIGRATION", "DATABASE_URL"):
        value = declared.get(name)
        if scope == "staging" and not value:
            raise RuntimeError(
                f"Staging env file must explicitly declare {name}"
            )
        if not value:
            continue
        if "${" in value:
            raise RuntimeError(
                f"{name} in staging env file must be a literal URL"
            )
        inherited = os.environ.get(name)
        if inherited is not None and inherited != value:
            raise RuntimeError(
                f"Inherited {name} conflicts with explicit env file target"
            )
    if scope == "staging":
        migration = _database_endpoint(
            declared["DATABASE_URL_MIGRATION"], name="DATABASE_URL_MIGRATION"
        )
        runtime = _database_endpoint(
            declared["DATABASE_URL"], name="DATABASE_URL"
        )
        if migration != runtime:
            raise RuntimeError(
                "Staging migration/runtime targets disagree on host, port or database"
            )


def _observed_import_roles(role_counts: dict[str, int]) -> list[str]:
    # The worker entrypoint sets PGAPPNAME to this exact value. Prefix or
    # substring matches can misreport an unrelated observer as a worker.
    return [
        role for role in ("execution", "control", "maintenance")
        if role_counts.get(f"wanasah-product-import-{role}", 0) > 0
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--scope", choices=("developer", "staging"), required=True)
    args = parser.parse_args()
    if not args.env_file.is_file():
        raise RuntimeError("Explicit environment file missing")
    _bind_env_file_db_target(args.env_file, scope=args.scope)
    load_dotenv(args.env_file, override=False)
    if args.scope == "staging" and os.environ.get(
        "WANASAH_STAGING_READONLY_ACK"
    ) != "ISOLATED_SYNTHETIC_STAGING":
        raise RuntimeError(
            "Staging verification requires explicit isolated-staging acknowledgement"
        )

    url = make_url(os.environ["DATABASE_URL_MIGRATION"])
    if args.scope == "developer" and url.database != "velotrack_db":
        raise RuntimeError("Developer inventory refuses unexpected database")
    if args.scope == "staging" and url.database == "velotrack_db":
        raise RuntimeError("Staging inventory refuses developer database")
    dsn = url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    warnings = []
    failures = []

    with psycopg.connect(dsn, connect_timeout=5) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        actual = {
            x[0] for x in connection.execute(
                "SELECT version_num FROM alembic_version"
            )
        }
        heads = subprocess.run(
            [sys.executable, "-m", "alembic", "heads"],
            cwd=ROOT, check=True, text=True,
            capture_output=True, timeout=20,
        ).stdout.strip().splitlines()
        wanted = {
            line.split()[0] for line in heads if line.strip()
        }
        if not actual or actual != wanted:
            failures.append("Alembic DB revision differs from repository head")
        print("ALEMBIC_MATCH=" + ("PASS" if actual == wanted else "FAIL"))

        rows = connection.execute(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r','p') AND c.relname = ANY(%s)
            ORDER BY c.relname
            """,
            (list(REQUIRED_RLS_TABLES),),
        ).fetchall()
        rls = {
            name: (enabled, forced) for name, enabled, forced in rows
        }
        for name in REQUIRED_RLS_TABLES:
            if name not in rls or not all(rls[name]):
                failures.append("Missing tenant FORCE RLS on " + name)
        print("IMPORT_FORCE_RLS=" + (
            "PASS" if len(rls) == len(REQUIRED_RLS_TABLES)
            and all(all(x) for x in rls.values()) else "FAIL"
        ))

        conn_total = int(
            connection.execute("SHOW max_connections").fetchone()[0]
        )
        reserved = int(
            connection.execute(
                "SHOW superuser_reserved_connections"
            ).fetchone()[0]
        )
        from config import Config
        envelope = (
            int(Config.WEB_CONCURRENCY) *
            (int(Config.DB_POOL_SIZE) + int(Config.DB_MAX_OVERFLOW))
            + int(Config.DB_OPERATIONAL_RESERVED_CONNECTIONS)
            + int(Config.PRODUCT_IMPORT_DB_CONNECTION_BUDGET)
        )
        contract = int(Config.DB_DEPLOYMENT_CONNECTION_BUDGET)
        budget_ok = envelope <= contract and contract < conn_total - reserved
        if not budget_ok:
            failures.append("Connection envelope exceeds PostgreSQL headroom")
        print(
            "DB_CONNECTION_ENVELOPE="
            + ("PASS" if budget_ok else "FAIL")
            + f" envelope={envelope} budget={contract} max={conn_total}"
        )

        roles = {
            app: int(count)
            for app, count in connection.execute(
                """
                SELECT application_name, count(*)
                FROM pg_stat_activity
                WHERE application_name LIKE 'wanasah-product-import-%'
                GROUP BY application_name
                ORDER BY application_name
                """
            )
        }
        # Worker names are connection identities; no tokens or SQL literals.
        running_roles = _observed_import_roles(roles)
        if args.scope == "staging" and len(running_roles) < 3:
            failures.append("Staging missing active worker role connections")
        elif len(running_roles) < 3:
            warnings.append("Developer worker roles are not all connected")
        print("WORKER_ROLES_OBSERVED=" + ",".join(running_roles or ("none",)))

        # E: one bounded, read-only server-side aggregate. Do not retrieve
        # pg_stat_activity.query, credentials, SQL parameters, tenant IDs, or
        # per-session PIDs. This snapshot is only the present instant, NOT a
        # p95 latency estimate or proof about past contention.
        has_stats_role = bool(connection.execute(
            """
            SELECT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
                   OR pg_has_role(current_user, 'pg_read_all_stats', 'USAGE')
            """
        ).fetchone()[0])
        if not has_stats_role:
            notice = "DB observer lacks pg_read_all_stats; activity may be incomplete"
            (failures if args.scope == "staging" else warnings).append(notice)
        print("DB_ACTIVITY_OBSERVER=" + (
            "FULL" if has_stats_role else "LIMITED"
        ))

        activity_fields = (
            "clients", "idle_transactions", "old_idle_transactions",
            "old_transactions", "max_xact_seconds",
            "max_idle_xact_seconds", "blocked_edges",
            "lock_waiting_clients",
        )
        current_activity = connection.execute(
            """
            SELECT
              count(*) AS clients,
              count(*) FILTER (
                WHERE state='idle in transaction'
              ) AS idle_transactions,
              count(*) FILTER (
                WHERE state='idle in transaction'
                  AND state_change < clock_timestamp() - interval '30 seconds'
              ) AS old_idle_transactions,
              count(*) FILTER (
                WHERE xact_start IS NOT NULL
                  AND xact_start < clock_timestamp() - interval '60 seconds'
              ) AS old_transactions,
              max(GREATEST(0,EXTRACT(EPOCH FROM
                  clock_timestamp()-xact_start)))
                  FILTER (WHERE xact_start IS NOT NULL) AS max_xact_seconds,
              max(GREATEST(0,EXTRACT(EPOCH FROM
                  clock_timestamp()-state_change)))
                  FILTER (WHERE state='idle in transaction')
                    AS max_idle_xact_seconds,
              sum(cardinality(pg_blocking_pids(pid)))
                    AS blocked_edges,
              count(*) FILTER (
                WHERE wait_event_type='Lock'
              ) AS lock_waiting_clients
            FROM pg_stat_activity
            WHERE datname=current_database()
              AND backend_type='client backend'
            """
        ).fetchone()
        if current_activity is None:
            raise RuntimeError("Database activity aggregate missing")
        activity = {
            key: (
                round(float(value or 0), 2)
                if key.endswith("_seconds")
                else int(value or 0)
            )
            for key, value in zip(activity_fields, current_activity, strict=True)
        }
        # The operator sees aggregate measurements only; never pg_stat_activity
        # query text, SQL credentials, company IDs or customer data.
        print("DB_ACTIVITY_SNAPSHOT=" + str(activity))
        if activity["clients"] >= conn_total - reserved:
            failures.append("PostgreSQL connections exhausted nonreserved slots")
        if activity["clients"] > contract:
            (failures if args.scope == "staging" else warnings).append(
                "Observed DB client connections exceed deployment budget"
            )
        if activity["old_idle_transactions"]:
            (failures if args.scope == "staging" else warnings).append(
                "Transactions idle over 30 seconds require owner diagnosis"
            )
        if activity["old_transactions"] and args.scope == "staging":
            warnings.append(
                "Transactions active over 60 seconds require workload attribution"
            )
        if activity["blocked_edges"] and args.scope == "staging":
            warnings.append(
                "Blocked DB lock edges observed; correlate with named business operations"
            )

        queue_rows = connection.execute(
            """
            SELECT queue_name,status,count(*) AS jobs,
              max(GREATEST(0,EXTRACT(EPOCH FROM
                  clock_timestamp()-scheduled_at))) AS oldest_age_seconds
            FROM procrastinate_jobs
            WHERE queue_name IN (
                'product-import',
                'product-import-control',
                'product-import-maintenance'
            ) AND status IN ('todo','doing')
            GROUP BY queue_name,status
            ORDER BY queue_name,status
            """
        ).fetchall()
        print("IMPORT_QUEUE_ACTIVITY=" + str([
            {
                "queue":str(queue), "status":str(status),
                "jobs":int(number),
                "oldest_scheduled_age_seconds":round(float(oldest or 0), 1),
            }
            for queue,status,number,oldest in queue_rows
        ]))
        # Queue timestamps include purposeful scheduling delays and cannot be
        # interpreted as time-in-ready-state without a deeper delivery trace.

        if args.scope == "developer":
            # The hardcoded IDs are known ONLY in the developer database.
            # Never probe arbitrary tenant IDs or call them synthetic on staging.
            old_tests = connection.execute(
                """
                SELECT count(*) FROM product_import_jobs
                WHERE company_id BETWEEN 2393 AND 2398
                  AND status IN ('QUEUED','PARSING','VALIDATING','IMPORTING','RETRYING')
                """
            ).fetchone()[0]
            if int(old_tests):
                warnings.append(
                    "Historical synthetic test jobs remain nonterminal; "
                    "DO NOT start recovery blindly on developer source"
                )
            print("HISTORICAL_SYNTHETIC_ACTIVE=" + str(old_tests))

        print("READ_ONLY_SCHEMA_INVENTORY=PASS")
    print("WARNINGS=" + str(len(warnings)))
    for notice in warnings:
        print("WARN: " + notice)
    print("FAILURES=" + str(len(failures)))
    for notice in failures:
        print("FAIL: " + notice)
    print("STAGING_RELEASE_SIGNOFF=OPEN")
    if failures:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
