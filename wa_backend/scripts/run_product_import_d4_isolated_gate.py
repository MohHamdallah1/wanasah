"""Guarded disposable PostgreSQL runner for Product Import D4 recovery."""
from __future__ import annotations

import asyncio
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

PORT = 55443
ADMIN = "c2_temp_admin"
APP = "wanasah_app"
TEMPLATE = "d4_template"
DATABASE = "d4_recovery"


def pg(bin_dir: pathlib.Path, name: str) -> str:
    return base._pg(bin_dir, name)


def run(arguments: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=420,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"D4 command failed: {pathlib.Path(arguments[0]).name}; "
            + ((result.stdout or "") + "\n" + (result.stderr or ""))[-5000:]
        )
    return result


def psql(bin_dir: pathlib.Path, database: str, sql: str) -> None:
    run([
        pg(bin_dir, "psql"), "-X", "-h", "127.0.0.1", "-p", str(PORT),
        "-U", ADMIN, "-d", database, "-v", "ON_ERROR_STOP=1", "-q", "-c", sql,
    ])


def reset_owned_sequences(bin_dir: pathlib.Path) -> None:
    """Synchronize all public owned sequences after explicit fixture-ID copies."""
    psql(bin_dir, TEMPLATE, """
        DO $d4$
        DECLARE
            rec record;
            max_value bigint;
        BEGIN
            FOR rec IN
                SELECT
                    seq_ns.nspname AS seq_schema,
                    seq.relname AS seq_name,
                    tbl_ns.nspname AS table_schema,
                    tbl.relname AS table_name,
                    attr.attname AS column_name
                FROM pg_class AS seq
                JOIN pg_namespace AS seq_ns ON seq_ns.oid = seq.relnamespace
                JOIN pg_depend AS dep
                  ON dep.classid = 'pg_class'::regclass
                 AND dep.objid = seq.oid
                 AND dep.refclassid = 'pg_class'::regclass
                 AND dep.deptype IN ('a','i')
                JOIN pg_class AS tbl ON tbl.oid = dep.refobjid
                JOIN pg_namespace AS tbl_ns ON tbl_ns.oid = tbl.relnamespace
                JOIN pg_attribute AS attr
                  ON attr.attrelid = tbl.oid
                 AND attr.attnum = dep.refobjsubid
                WHERE seq.relkind = 'S'
                  AND seq_ns.nspname = 'public'
                  AND tbl_ns.nspname = 'public'
            LOOP
                EXECUTE format(
                    'SELECT max(%I) FROM %I.%I',
                    rec.column_name, rec.table_schema, rec.table_name
                ) INTO max_value;
                IF max_value IS NULL THEN
                    PERFORM setval(
                        format('%I.%I', rec.seq_schema, rec.seq_name)::regclass,
                        1,
                        false
                    );
                ELSE
                    PERFORM setval(
                        format('%I.%I', rec.seq_schema, rec.seq_name)::regclass,
                        max_value,
                        true
                    );
                END IF;
            END LOOP;
        END
        $d4$;
    """)


def seed_control_rows(bin_dir: pathlib.Path) -> None:
    psql(bin_dir, TEMPLATE, """
        INSERT INTO product_import_global_source_capacity(
            id, live_bytes, high_water_bytes, updated_at
        ) VALUES (1,0,0,CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO NOTHING;
        INSERT INTO alembic_version(version_num)
        VALUES ('d31c7a940e62')
        ON CONFLICT (version_num) DO NOTHING;
    """)


def child_env(database: str, root: pathlib.Path) -> dict[str, str]:
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
        "WANASAH_D4_DISPOSABLE_CHILD": "1",
        "WANASAH_D4_LOG_DIR": str(root),
        "PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS": "1",
        "PRODUCT_IMPORT_CONTROL_WORKER_SLOTS": "1",
        "PRODUCT_IMPORT_MAINTENANCE_WORKER_SLOTS": "1",
        "PRODUCT_IMPORT_QUEUE_POOL_MIN": "1",
        "PRODUCT_IMPORT_QUEUE_POOL_MAX": "2",
        "PRODUCT_IMPORT_DB_CONNECTION_BUDGET": "16",
        "DB_DEPLOYMENT_CONNECTION_BUDGET": "60",
        "WANASAH_RELEASE_COMMIT": run(
            ["git", "rev-parse", "HEAD"], env=os.environ.copy()
        ).stdout.strip(),
    })
    return env


def main() -> None:
    if os.environ.get("WANASAH_D4_LOCAL_GATE") != "1":
        raise RuntimeError("Explicit WANASAH_D4_LOCAL_GATE=1 is required.")
    source_env = os.environ.get("WANASAH_D4_SOURCE_ENV_FILE", "")
    if not source_env or not pathlib.Path(source_env).is_file():
        raise RuntimeError("Explicit developer .env path is required.")
    if pathlib.Path.cwd().name != "wa_backend":
        raise RuntimeError("Run D4 gate from wa_backend.")

    load_dotenv(source_env, override=False)
    source = base._assert_source_url()
    bin_dir = pathlib.Path(r"C:\Program Files\PostgreSQL\16\bin")
    for name in ("initdb", "pg_ctl", "psql", "createdb", "pg_dump"):
        pg(bin_dir, name)

    probe = socket.socket()
    probe.settimeout(1.0)
    try:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError("Port 55443 occupied; refusing existing server.")
    finally:
        probe.close()

    root = pathlib.Path(tempfile.mkdtemp(prefix="wanasah_d4_gate_"))
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
        reset_owned_sequences(bin_dir)
        seed_control_rows(bin_dir)

        migration_env = child_env(TEMPLATE, root)
        run([sys.executable, "-m", "alembic", "upgrade", "head"], env=migration_env)

        base._run([
            pg(bin_dir, "createdb"), "-h", "127.0.0.1", "-p", str(PORT),
            "-U", ADMIN, "-T", TEMPLATE, DATABASE,
        ])

        env = child_env(DATABASE, root)
        child = run([
            sys.executable, "-m", "scripts.product_import_d4_isolated_child"
        ], env=env)
        print(child.stdout, end="")

        asyncio.run(base._verify_source_still_empty(source))
        print("ORIGINAL_DEV_TENANT_UNMODIFIED=PASS")
        if "PRODUCT_IMPORT_D4_ISOLATED_GATE=PASS" not in child.stdout:
            raise RuntimeError("D4 child did not report PASS.")
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
