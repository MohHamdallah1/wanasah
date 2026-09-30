"""D3.2 disposable A/B gate for bounded cross-tenant Product Import concurrency.

Creates a private PostgreSQL 16 cluster on 127.0.0.1:55442, copies schema plus
only the preapproved empty synthetic tenant-2 fixture, creates one second
synthetic tenant inside the throwaway cluster, runs slots=1 then slots=2, and
removes the cluster. The source developer database is read-only.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile

from dotenv import load_dotenv
from sqlalchemy.engine import URL

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_c2_isolated_committed_gate as base

PORT = 55442
ADMIN = "c2_temp_admin"
APP = "wanasah_app"
TEMPLATE = "d32_template"
DATABASES = ((1, "d32_serial"), (2, "d32_concurrent"))
LONG_ROWS = int(os.environ.get("WANASAH_D32_LONG_ROWS", "1000"))
SHORT_ROWS = int(os.environ.get("WANASAH_D32_SHORT_ROWS", "100"))


def pg(bin_dir: pathlib.Path, name: str) -> str:
    return base._pg(bin_dir, name)


def run(arguments: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        arguments,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=260,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"D3.2 command failed: {pathlib.Path(arguments[0]).name}; "
            + (result.stderr or result.stdout)[-1200:]
        )
    return result
def psql(bin_dir: pathlib.Path, database: str, sql: str) -> None:
    run([
        pg(bin_dir, "psql"), "-X", "-h", "127.0.0.1", "-p", str(PORT),
        "-U", ADMIN, "-d", database, "-v", "ON_ERROR_STOP=1", "-q",
        "-c", sql,
    ])


def clone_second_synthetic_tenant(bin_dir: pathlib.Path) -> None:
    # pg_dump --schema-only intentionally excludes singleton control rows that
    # were seeded by historical data migrations. Recreate only the Product
    # Import global-capacity singleton inside this disposable database.
    psql(bin_dir, TEMPLATE, """
        INSERT INTO product_import_global_source_capacity(
            id, live_bytes, high_water_bytes, updated_at
        ) VALUES (1,0,0,CURRENT_TIMESTAMP);
    """)
    psql(bin_dir, TEMPLATE, """
        INSERT INTO companies(
            id,name,company_code,is_active,subscription_status,
            currency_code,timezone,created_at
        )
        SELECT 3,name || ' D32',company_code || '-D32',is_active,
               subscription_status,currency_code,timezone,created_at
        FROM companies WHERE id=2;

        INSERT INTO drivers(
            id,company_id,username,password_hash,full_name,phone_number,
            is_active,is_admin,can_allow_debt,max_debt_limit,created_at
        )
        SELECT 2,3,username || '-d32',password_hash,full_name || ' D32',NULL,
               is_active,is_admin,can_allow_debt,max_debt_limit,created_at
        FROM drivers WHERE company_id=2;
    """)
    psql(bin_dir, TEMPLATE, """
        DO $d32$ DECLARE t text; seq_name text; max_id bigint;
        BEGIN
          FOREACH t IN ARRAY ARRAY[
            'uom','companies','drivers','products','product_variants',
            'inventory_locations','product_uom_conversions'
          ] LOOP
            SELECT pg_get_serial_sequence('public.'||t,'id') INTO seq_name;
            IF seq_name IS NOT NULL THEN
              EXECUTE format('SELECT COALESCE(MAX(id),0) FROM public.%I',t)
                INTO max_id;
              PERFORM setval(seq_name::regclass,GREATEST(max_id,1),true);
            END IF;
          END LOOP;
        END $d32$;
    """)
def child_env(source_env: str, database: str, slots: int, root: pathlib.Path) -> dict[str, str]:
    env = os.environ.copy()
    app_url = URL.create(
        "postgresql+asyncpg", username=APP,
        host="127.0.0.1", port=PORT, database=database,
    ).render_as_string(hide_password=False)
    admin_url = URL.create(
        "postgresql+asyncpg", username=ADMIN,
        host="127.0.0.1", port=PORT, database=database,
    ).render_as_string(hide_password=False)
    env.update({
        "DATABASE_URL": app_url,
        "DATABASE_URL_MIGRATION": admin_url,
        "WANASAH_D32_DISPOSABLE_CHILD": "1",
        "WANASAH_D32_LONG_ROWS": str(LONG_ROWS),
        "WANASAH_D32_SHORT_ROWS": str(SHORT_ROWS),
        "WANASAH_D32_SOURCE_ENV_FILE": source_env,
        "PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS": str(slots),
        "PRODUCT_IMPORT_CONTROL_WORKER_SLOTS": "1",
        "PRODUCT_IMPORT_MAINTENANCE_WORKER_SLOTS": "1",
        "PRODUCT_IMPORT_QUEUE_POOL_MIN": "1",
        "PRODUCT_IMPORT_QUEUE_POOL_MAX": "2",
        "PRODUCT_IMPORT_DB_CONNECTION_BUDGET": "16",
        "WANASAH_RELEASE_COMMIT": run(
            ["git", "rev-parse", "HEAD"], env=os.environ.copy()
        ).stdout.strip(),
        "WANASAH_D32_WORKER_LOG": str(root / f"worker-s{slots}.log"),
    })
    return env


def parse_result(output: str) -> dict:
    for line in output.splitlines():
        if line.startswith("D32_RESULT="):
            return json.loads(line.split("=", 1)[1])
    raise RuntimeError("D3.2 child did not emit D32_RESULT.")
def main() -> None:
    if os.environ.get("WANASAH_D32_LOCAL_GATE") != "1":
        raise RuntimeError("Explicit WANASAH_D32_LOCAL_GATE=1 is required.")
    source_env = os.environ.get("WANASAH_D32_SOURCE_ENV_FILE", "")
    if not source_env or not pathlib.Path(source_env).is_file():
        raise RuntimeError("Explicit developer .env path is required.")
    if pathlib.Path.cwd().name != "wa_backend":
        raise RuntimeError("Run D3.2 gate from wa_backend.")

    load_dotenv(source_env, override=False)
    source = base._assert_source_url()
    bin_dir = pathlib.Path(r"C:\Program Files\PostgreSQL\16\bin")
    for name in ("initdb", "pg_ctl", "psql", "createdb", "pg_dump"):
        pg(bin_dir, name)

    probe = socket.socket()
    probe.settimeout(1.0)
    try:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError("Port 55442 occupied; refusing existing server.")
    finally:
        probe.close()

    root = pathlib.Path(tempfile.mkdtemp(prefix="wanasah_d32_gate_"))
    started = False
    try:
        base._run([
            pg(bin_dir, "initdb"), "-D", str(root),
            "-U", ADMIN, "-A", "trust", "-E", "UTF8", "--no-instructions",
        ])
        base._run([
            pg(bin_dir, "pg_ctl"), "-D", str(root),
            "-l", str(root / "postgres.log"),
            "-o", f"-p {PORT} -h 127.0.0.1", "-w", "start",
        ])
        started = True
        src_env = os.environ.copy()
        src_env["PGPASSWORD"] = source.password
        base._run([
            pg(bin_dir, "pg_dump"), "-h", source.host,
            "-p", str(source.port or 5432), "-U", source.username,
            "-d", source.database, "--schema-only", "--no-owner", "--no-acl",
            "--no-tablespaces", "-f", str(root / "schema.sql"),
        ], env=src_env)
        psql(bin_dir, "postgres", f"CREATE ROLE {APP} LOGIN")
        base._run([
            pg(bin_dir, "createdb"), "-h", "127.0.0.1", "-p", str(PORT),
            "-U", ADMIN, TEMPLATE,
        ])
        base._run([
            pg(bin_dir, "psql"), "-X", "-h", "127.0.0.1", "-p", str(PORT),
            "-U", ADMIN, "-d", TEMPLATE, "-v", "ON_ERROR_STOP=1", "-q",
            "-f", str(root / "schema.sql"),
        ])

        base._PORT = PORT
        base._TEMPLATE = TEMPLATE
        asyncio.run(base._copy_safe_synthetic_fixture(source))
        clone_second_synthetic_tenant(bin_dir)

        results: dict[int, dict] = {}
        for slots, database in DATABASES:
            base._run([
                pg(bin_dir, "createdb"), "-h", "127.0.0.1", "-p", str(PORT),
                "-U", ADMIN, "-T", TEMPLATE, database,
            ])
            env = child_env(source_env, database, slots, root)
            child = run([
                sys.executable, "-m", "scripts.product_import_d32_isolated_child"
            ], env=env)
            print(child.stdout, end="")
            results[slots] = parse_result(child.stdout)

        serial = results[1]
        concurrent = results[2]
        if concurrent["max_doing"] < 2 or not concurrent["cross_company_overlap"]:
            raise RuntimeError("D3.2 failed to prove independent-company overlap.")
        if concurrent["same_company_double"]:
            raise RuntimeError("D3.2 violated same-company serialization.")
        if not concurrent["same_company_waited_while_other_company_ran"]:
            raise RuntimeError("D3.2 fairness/lock proof missing.")
        if not concurrent["short_finished_before_second_long"]:
            raise RuntimeError(
                "D3.2 short independent-tenant work was starved behind long work."
            )
        if concurrent["during_p95_ms"] > max(100.0, concurrent["baseline_p95_ms"] * 10):
            raise RuntimeError("D3.2 interactive catalog-read p95 exceeded local gate.")
        if concurrent["elapsed_s"] > serial["elapsed_s"] * 1.35:
            raise RuntimeError("Two-slot execution regressed total wall time beyond 35%.")
        if concurrent["wal_delta_bytes"] > serial["wal_delta_bytes"] * 1.35:
            raise RuntimeError("Two-slot execution amplified WAL beyond 35%.")
        if concurrent["max_app_connections"] > 16:
            raise RuntimeError("D3.2 exceeded explicit Product Import connection budget.")

        asyncio.run(base._verify_source_still_empty(source))
        print("D32_SERIAL=" + json.dumps(serial, separators=(",", ":")))
        print("D32_CONCURRENT=" + json.dumps(concurrent, separators=(",", ":")))
        print("PRODUCT_IMPORT_D32_ISOLATED_GATE=PASS")
    finally:
        if started or (root / "postmaster.pid").exists():
            base._run([
                pg(bin_dir, "pg_ctl"), "-D", str(root),
                "-m", "fast", "-w", "stop",
            ])
            started = False
        if not started:
            shutil.rmtree(root, ignore_errors=False)


if __name__ == "__main__":
    main()
