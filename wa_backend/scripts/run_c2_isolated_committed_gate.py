"""Reproducible, fail-closed C2 independently committed receipt race gate.

Run ONLY against the approved localhost developer database with an explicit
opt-in and the developer .env path, for example:

  WANASAH_C2_LOCAL_COMMIT_GATE=1
  WANASAH_C2_SOURCE_ENV_FILE=<absolute path to developer wa_backend/.env>
  python scripts/run_c2_isolated_committed_gate.py

Requires PostgreSQL 16 CLI binaries, asyncpg, SQLAlchemy, python-dotenv.
Never copies real customer data: the SOURCE tenant must be the existing
empty synthetic development fixture, company 2 (1 test actor, 1 product
master, 1 SKU and 1 empty warehouse). This script dumps SCHEMA ONLY, copies
only those synthetic fixture rows + global UOM reference rows to a local
ephemeral PostgreSQL 16 cluster bound to 127.0.0.1:55439, and tests both
FIFO and moving average in distinct disposable databases.

It intentionally permits ACTUAL committed test stock only inside the
throwaway cluster, which is shut down and deleted in finally. It makes no
source writes, edits, schema migrations or data cleanup in development DB.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

import asyncpg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


_TEMP_USER = "c2_temp_admin"
_APP_ROLE = "wanasah_app"
_PORT = 55439
_TEMPLATE = "c2_commit_db"
_DB_METHODS = (
    ("FIFO", "c2_commit_fifo"),
    ("MOVING_AVERAGE", "c2_commit_average"),
)
_SEED_TABLES = (
    "uom",
    "companies",
    "drivers",
    "products",
    "product_variants",
    "inventory_locations",
    "product_uom_conversions",
)
_EMPTY_TENANT_TABLES = (
    "shops",
    "vehicles",
    "route_commercial_contexts",
    "price_books",
    "price_book_assignments",
    "price_publications",
    "tax_rule_sets",
    "tax_jurisdictions",
    "inventory_cost_policies",
    "inventory_cost_events",
    "inventory_movements",
    "inventory_balances",
    "operation_idempotency",
)


def _run(arguments: list[str], *, env: dict[str, str] | None = None) -> None:
    # Do not log raw arguments: the SOURCE password is carried only via
    # PGPASSWORD. It must never appear in command output.
    result = subprocess.run(
        arguments, env=env, capture_output=True, text=True, timeout=110,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Test-only PostgreSQL command failed: {pathlib.Path(arguments[0]).name} "
            f"(exit {result.returncode}); {result.stderr[-700:]}"
        )


def _pg(bin_dir: pathlib.Path, name: str) -> str:
    executable = bin_dir / (name + (".exe" if os.name == "nt" else ""))
    if not executable.is_file():
        raise RuntimeError(f"PostgreSQL binary not installed: {name}")
    return str(executable)


def _assert_source_url():
    from config import Config

    url = make_url(Config.SQLALCHEMY_DATABASE_URI)
    if (
        url.database != "velotrack_db"
        or url.host not in ("localhost", "127.0.0.1")
        or url.username != _APP_ROLE
    ):
        raise RuntimeError(
            "Refusing committed gate: only local velotrack_db with "
            "wanasah_app developer role is supported."
        )
    if not url.password:
        raise RuntimeError("Developer source credential unavailable.")
    return url


async def _copy_safe_synthetic_fixture(url) -> None:
    src = await asyncpg.connect(
        host=url.host, port=url.port or 5432, user=url.username,
        password=url.password, database=url.database,
    )
    dest = await asyncpg.connect(
        host="127.0.0.1", port=_PORT, user=_TEMP_USER,
        database=_TEMPLATE,
    )
    try:
        await src.execute("SELECT set_config('app.current_tenant','2',false)")
        if await src.fetchval("SELECT current_database()") != "velotrack_db":
            raise RuntimeError("Wrong developer database.")
        for table in _EMPTY_TENANT_TABLES:
            count = await src.fetchval(
                "SELECT COUNT(*) FROM " + table + " WHERE company_id=2"
            )
            if count != 0:
                raise RuntimeError(
                    f"Source test tenant is no longer empty in {table}; "
                    "refusing to copy business/customer data."
                )
        counts = {
            "companies": 1,
            "drivers": 1,
            "products": 1,
            "product_variants": 1,
            "inventory_locations": 1,
        }
        for table, expected in counts.items():
            condition = "id=2" if table == "companies" else "company_id=2"
            actual = await src.fetchval(
                "SELECT COUNT(*) FROM " + table + " WHERE " + condition
            )
            if actual != expected:
                raise RuntimeError(
                    f"Expected {expected} preapproved synthetic {table} "
                    f"fixtures, found {actual}; refusing unsafe seed."
                )
        for table in _SEED_TABLES:
            condition = (
                "" if table == "uom"
                else (" WHERE id=2" if table == "companies" else " WHERE company_id=2")
            )
            records = await src.fetch("SELECT * FROM " + table + condition)
            generated_columns = {
                row["column_name"] for row in await dest.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=$1 "
                    "AND is_generated<>'NEVER'",
                    table,
                )
            }
            for record in records:
                values = {
                    key: value for key, value in dict(record).items()
                    if key not in generated_columns
                }
                fields = list(values)
                sql = (
                    "INSERT INTO " + table
                    + " (" + ",".join('"' + c + '"' for c in fields) + ") "
                    + "VALUES (" + ",".join(
                        "$" + str(index + 1) for index in range(len(fields))
                    ) + ")"
                )
                await dest.execute(sql, *(values[name] for name in fields))
            print(f"SEEDED_SYNTHETIC_{table.upper()}={len(records)}")
        await dest.execute(
            "GRANT USAGE ON SCHEMA public TO " + _APP_ROLE
        )
        for category in ("TABLES", "SEQUENCES"):
            await dest.execute(
                "GRANT ALL ON ALL " + category
                + " IN SCHEMA public TO " + _APP_ROLE
            )
        await dest.execute(
            "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO " + _APP_ROLE
        )
    finally:
        await src.close()
        await dest.close()


async def _verify_source_still_empty(url) -> None:
    conn = await asyncpg.connect(
        host=url.host, port=url.port or 5432, user=url.username,
        password=url.password, database=url.database,
    )
    try:
        await conn.execute("SELECT set_config('app.current_tenant','2',false)")
        for table in _EMPTY_TENANT_TABLES:
            assert (
                await conn.fetchval(
                    "SELECT COUNT(*) FROM " + table + " WHERE company_id=2"
                )
            ) == 0, f"Developer tenant changed unexpectedly: {table}"
        print("ORIGINAL_DEV_TENANT_UNMODIFIED=PASS")
    finally:
        await conn.close()


def _run_committed_tests() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    os.environ["WANASAH_C2_COMMITTED_DB_GATE"] = "1"
    for method, database in _DB_METHODS:
        os.environ["WANASAH_C2_COMMITTED_METHOD"] = method
        os.environ["WANASAH_C2_COMMITTED_DB"] = database
        suite = unittest.TestLoader().discover(
            "tests", pattern="test_committed_costed_inbound_race_c2_isolated.py",
        )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful() or result.skipped or result.testsRun != 1:
            raise RuntimeError(f"Committed C2 gate FAILED for {method}")
        print(f"ISOLATED_COMMITTED_RACE_{method}=PASS")


def main() -> None:
    if os.environ.get("WANASAH_C2_LOCAL_COMMIT_GATE") != "1":
        raise RuntimeError("Explicit WANASAH_C2_LOCAL_COMMIT_GATE=1 is required.")
    env_path = os.environ.get("WANASAH_C2_SOURCE_ENV_FILE", "")
    if not env_path or not pathlib.Path(env_path).is_file():
        raise RuntimeError("Explicit valid developer env file path required.")
    if pathlib.Path.cwd().name != "wa_backend":
        raise RuntimeError("Start the gate in the isolated worktree wa_backend.")
    load_dotenv(env_path, override=False)
    source_url = _assert_source_url()

    if os.name == "nt":
        bin_dir = pathlib.Path(r"C:\Program Files\PostgreSQL\16\bin")
    else:
        bin_dir = pathlib.Path(os.environ.get("WANASAH_PG16_BIN_DIR", "/usr/bin"))
    for name in ("initdb", "pg_ctl", "psql", "createdb", "pg_dump"):
        _pg(bin_dir, name)
    probe = socket.socket()
    probe.settimeout(1.0)
    try:
        if probe.connect_ex(("127.0.0.1", _PORT)) == 0:
            raise RuntimeError(
                "Refusing test: port 55439 already has a listener."
            )
    finally:
        probe.close()

    test_root = pathlib.Path(tempfile.mkdtemp(prefix="wanasah_c2_commit_gate_"))
    cluster_started = False
    try:
        _run([
            _pg(bin_dir, "initdb"), "-D", str(test_root),
            "-U", _TEMP_USER, "-A", "trust", "-E", "UTF8",
            "--no-instructions",
        ])
        _run([
            _pg(bin_dir, "pg_ctl"), "-D", str(test_root),
            "-l", str(test_root / "postgres.log"),
            "-o", f"-p {_PORT} -h 127.0.0.1",
            "-w", "start",
        ])
        cluster_started = True

        source_env = os.environ.copy()
        source_env["PGPASSWORD"] = source_url.password
        _run([
            _pg(bin_dir, "pg_dump"),
            "-h", source_url.host,
            "-p", str(source_url.port or 5432),
            "-U", source_url.username,
            "-d", source_url.database,
            "--schema-only", "--no-owner", "--no-acl", "--no-tablespaces",
            "-f", str(test_root / "schema.sql"),
        ], env=source_env)
        _run([
            _pg(bin_dir, "psql"), "-X",
            "-h", "127.0.0.1", "-p", str(_PORT),
            "-U", _TEMP_USER, "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-q",
            "-c", "CREATE ROLE " + _APP_ROLE + " LOGIN",
        ])
        _run([
            _pg(bin_dir, "createdb"),
            "-h", "127.0.0.1", "-p", str(_PORT),
            "-U", _TEMP_USER, _TEMPLATE,
        ])
        _run([
            _pg(bin_dir, "psql"), "-X",
            "-h", "127.0.0.1", "-p", str(_PORT),
            "-U", _TEMP_USER, "-d", _TEMPLATE,
            "-v", "ON_ERROR_STOP=1", "-q",
            "-f", str(test_root / "schema.sql"),
        ])
        asyncio.run(_copy_safe_synthetic_fixture(source_url))
        for _, name in _DB_METHODS:
            _run([
                _pg(bin_dir, "createdb"),
                "-h", "127.0.0.1", "-p", str(_PORT),
                "-U", _TEMP_USER, "-T", _TEMPLATE, name,
            ])

        _run_committed_tests()
        asyncio.run(_verify_source_still_empty(source_url))
        print("C2_COMMITTED_METHODS_AND_SOURCE_ISOLATION=PASS")
    finally:
        # Explicitly NEVER clean/remove a cluster until PostgreSQL confirms
        # it stopped. Its only data was created in our guarded unique tempdir.
        if cluster_started:
            try:
                _run([
                    _pg(bin_dir, "pg_ctl"), "-D", str(test_root),
                    "-m", "fast", "-w", "stop",
                ])
                cluster_started = False
            except Exception:
                print(
                    "TEMP_DB_CLEANUP_BLOCKED: PostgreSQL still running at "
                    + str(test_root),
                    file=sys.stderr,
                )
                raise
        if not cluster_started:
            shutil.rmtree(test_root)
            print("DISPOSABLE_PG16_CLUSTER_REMOVED=PASS")


if __name__ == "__main__":
    main()
