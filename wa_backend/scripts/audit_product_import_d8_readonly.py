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

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
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

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--scope", choices=("developer", "staging"), required=True)
    args = parser.parse_args()
    if not args.env_file.is_file():
        raise RuntimeError("Explicit environment file missing")
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
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relkind IN ('r','p') AND relname = ANY(%s)
            ORDER BY relname
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
        role_names = tuple(("execution", "control", "maintenance"))
        running_roles = [
            role for role in role_names
            if any(role in name for name in roles)
        ]
        if args.scope == "staging" and len(running_roles) < 3:
            failures.append("Staging missing active worker role connections")
        elif len(running_roles) < 3:
            warnings.append("Developer worker roles are not all connected")
        print("WORKER_ROLES_OBSERVED=" + ",".join(running_roles or ("none",)))

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
