"""Phase 19: opt-in REAL HTTP/PG/worker acceptance on disposable PG16.

Never sends synthetic writes to the existing developer database. Clones only the
preapproved empty tenant-2 fixture from a read-only source; creates tenant-3
solely inside its new throwaway cluster. Does not inspect users' import files.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

from dotenv import load_dotenv
from scripts import run_c2_isolated_committed_gate as base
from scripts import run_product_import_d4_isolated_gate as d4
from scripts import run_product_import_d32_isolated_gate as d32

ROOT = Path(__file__).resolve().parents[1]
PORT = 55446
API_PORT = 18046
TEMPLATE = "p19_http_template"
DATABASE = "p19_http_synthetic"
MARKER = "PRODUCT_IMPORT_PHASE19_REAL_HTTP_ISOLATED=PASS"


def _ensure_free(port: int) -> None:
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Isolated port {port} is in use. Refusing to touch its service.")


def main() -> None:
    if os.environ.get("WANASAH_P19_HTTP_LOCAL_GATE") != "1":
        raise RuntimeError("Set WANASAH_P19_HTTP_LOCAL_GATE=1 for an explicit synthetic-only run.")
    source_file = Path(os.environ.get("WANASAH_P19_HTTP_SOURCE_ENV_FILE", ""))
    if not source_file.is_file() or Path.cwd() != ROOT:
        raise RuntimeError("Run from wa_backend with a real developer .env path.")
    load_dotenv(source_file, override=False)
    source = base._assert_source_url()
    revision = d4.read_source_revision(source)
    bins = Path(r"C:\Program Files\PostgreSQL\16\bin")
    for name in ("initdb", "pg_ctl", "psql", "createdb", "pg_dump"):
        base._pg(bins, name)
    _ensure_free(PORT)
    _ensure_free(API_PORT)
    variant = os.environ.get("WANASAH_P19_HTTP_CASE", "small")
    if variant not in {"small", "medium", "final50k", "cancelstall", "edges", "workerfaults", "realbrowser", "contention"}:
        raise RuntimeError("Unknown P19 HTTP rehearsal case.")
    if variant == "medium" and os.environ.get("WANASAH_P19_INTERMEDIATE_ROWS") not in {"5000", "10000"}:
        raise RuntimeError("Medium rehearsal requires an explicit 5000 or 10000 row count.")
    if variant == "final50k" and (
        os.environ.get("WANASAH_P19_INTERMEDIATE_ROWS") != "50000" or
        os.environ.get("WANASAH_P19_FINAL_50K_CONFIRM") != "ISOLATED_SYNTHETIC_ONLY"
    ):
        raise RuntimeError("50k requires explicit disposable synthetic-only opt-in.")
    if variant == "cancelstall" and os.environ.get("WANASAH_P19_CANCEL_STALL_CONFIRM") != "ISOLATED_LOCK_ONLY":
        raise RuntimeError("Locked staging cancellation requires explicit disposable-only opt-in.")
    if variant == "edges" and os.environ.get("WANASAH_P19_EDGES_CONFIRM") != "ISOLATED_SYNTHETIC_ONLY":
        raise RuntimeError("Edge-size rehearsal requires explicit disposable-only opt-in.")
    if variant == "contention" and os.environ.get("WANASAH_P19_CONTENTION_CONFIRM") != "ISOLATED_SYNTHETIC_ONLY":
        raise RuntimeError("Tenant contention proof requires explicit disposable-only opt-in.")
    if variant == "workerfaults":
        if os.environ.get("WANASAH_P19_WORKER_FAULT_CONFIRM") != "ISOLATED_SYNTHETIC_ONLY":
            raise RuntimeError("Worker fault proof requires explicit disposable-only opt-in.")
        _ensure_free(55447)
    if variant == "realbrowser":
        if os.environ.get("WANASAH_P19_REAL_BROWSER_CONFIRM") != "DISPOSABLE_PG16_ONLY":
            raise RuntimeError("Real browser proof requires explicit disposable-only opt-in.")
        _ensure_free(5188)
        _ensure_free(19226)
    root = Path(tempfile.mkdtemp(prefix="wanasah_p19_http_disposable_"))
    started = False
    try:
        base._run([
            base._pg(bins, "initdb"), "-D", str(root), "-U", d4.ADMIN,
            "-A", "trust", "-E", "UTF8", "--no-instructions",
        ])
        base._run([
            base._pg(bins, "pg_ctl"), "-D", str(root),
            "-l", str(root / "postgres.log"),
            "-o", f"-p {PORT} -h 127.0.0.1", "-w", "start",
        ])
        started = True

        source_env = os.environ.copy()
        source_env["PGPASSWORD"] = source.password
        base._run([
            base._pg(bins, "pg_dump"), "-h", source.host,
            "-p", str(source.port or 5432), "-U", source.username,
            "-d", source.database, "--schema-only", "--no-owner",
            "--no-acl", "--no-tablespaces", "-f", str(root / "schema.sql"),
        ], env=source_env)

        # These mutable module globals are only for this isolated orchestrator
        # process; they point all bootstrap helpers at the same disposable port.
        base._PORT = PORT
        base._TEMPLATE = TEMPLATE
        d4.PORT = PORT
        d4.TEMPLATE = TEMPLATE
        d32.PORT = PORT
        d32.TEMPLATE = TEMPLATE
        d4.psql(bins, "postgres", f"CREATE ROLE {d4.APP} LOGIN")
        base._run([
            base._pg(bins, "createdb"), "-h", "127.0.0.1", "-p", str(PORT),
            "-U", d4.ADMIN, TEMPLATE,
        ])
        base._run([
            base._pg(bins, "psql"), "-X", "-h", "127.0.0.1",
            "-p", str(PORT), "-U", d4.ADMIN, "-d", TEMPLATE,
            "-v", "ON_ERROR_STOP=1", "-q", "-f", str(root / "schema.sql"),
        ])
        asyncio.run(base._copy_safe_synthetic_fixture(source))
        d32.clone_second_synthetic_tenant(bins)
        d4.reset_owned_sequences(bins)
        d4.seed_control_rows(bins, source_revision=revision)
        env = d4.child_env(TEMPLATE, root)
        env.update({
            "WANASAH_P19_HTTP_DISPOSABLE_CHILD": "1",
            "WANASAH_P19_HTTP_LOG_DIR": str(root),
            "WANASAH_P19_HTTP_API_PORT": str(API_PORT),
            "SENTRY_DSN": "",
            "ENVIRONMENT": "development",
        })
        d4.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        base._run([
            base._pg(bins, "createdb"), "-h", "127.0.0.1", "-p", str(PORT),
            "-U", d4.ADMIN, "-T", TEMPLATE, DATABASE,
        ])

        env = d4.child_env(DATABASE, root)
        env.update({
            "WANASAH_P19_HTTP_DISPOSABLE_CHILD": "1",
            "WANASAH_P19_HTTP_LOG_DIR": str(root),
            "WANASAH_P19_HTTP_API_PORT": str(API_PORT),
            "SENTRY_DSN": "",
            "ENVIRONMENT": "development",
        })
        if variant == "contention":
            # Production-default execution bound; small admission bound in this fixture only.
            env["PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS"] = "2"
            env["PRODUCT_IMPORT_MAX_ACTIVE_JOBS_PER_TENANT"] = "2"
        child_module = (
            "scripts.product_import_phase19_http_isolated_child" if variant == "small"
            else "scripts.product_import_phase19_http_cancel_stall_child" if variant == "cancelstall"
            else "scripts.product_import_phase19_edge_isolated_child" if variant == "edges"
            else "scripts.product_import_phase19_contention_child" if variant == "contention"
            else "scripts.product_import_phase19_worker_fault_child" if variant == "workerfaults"
            else "scripts.product_import_phase19_real_browser_child" if variant == "realbrowser"
            else "scripts.product_import_phase19_medium_isolated_child"
        )
        if variant in {"small", "cancelstall", "edges", "workerfaults", "realbrowser", "contention"}:
            child = d4.run([sys.executable, "-m", child_module], env=env)
        else:
            # The final50k case has a separate explicit opt-in and a bounded
            # larger time budget. It NEVER writes to the source developer DB.
            child = subprocess.run(
                [sys.executable, "-m", child_module],
                cwd=ROOT, env=env, capture_output=True, text=True,
                timeout=3600 if variant == "final50k" else 1250, check=False,
            )
            if child.returncode:
                # Do not replay private child traceback/SQL/DSN from stderr.
                # Keep any still-running owned worker cleanup in child finally.
                print("P19_INTERMEDIATE_CHILD_EXIT_NONZERO=" + str(child.returncode), flush=True)
                raise RuntimeError("Real intermediate queue gate did not complete.")
        # Children emit aggregate counts/timings, never bearer/JWT or source cells.
        print(child.stdout, end="", flush=True)
        expected_marker = (
            MARKER if variant == "small" else
            "PRODUCT_IMPORT_P19_REAL_HTTP_LOCK_CANCEL=PASS" if variant == "cancelstall" else
            "PRODUCT_IMPORT_P19_REAL_HTTP_EDGES=PASS" if variant == "edges" else
            "PRODUCT_IMPORT_P19_REAL_CONTENTION=PASS" if variant == "contention" else
            "PRODUCT_IMPORT_P19_REAL_WORKER_FAULTS=PASS" if variant == "workerfaults" else
            "PRODUCT_IMPORT_P19_REAL_BROWSER_BACKEND=PASS" if variant == "realbrowser" else
            "P19_REAL_QUEUE_" + os.environ["WANASAH_P19_INTERMEDIATE_ROWS"] + "_SYNTHETIC=PASS"
        )
        if expected_marker not in child.stdout:
            raise RuntimeError("Real isolated rehearsal did not emit its PASS marker.")
        asyncio.run(base._verify_source_still_empty(source))
        print("P19_HTTP_SOURCE_DEVELOPER_UNMODIFIED=PASS", flush=True)
    finally:
        if started or (root / "postmaster.pid").exists():
            try:
                base._run([
                    base._pg(bins, "pg_ctl"), "-D", str(root),
                    "-m", "fast", "-w", "stop",
                ])
                started = False
            except Exception:
                print("ISOLATED_PG_CLEANUP_BLOCKED: stop the owned temp cluster manually.", file=sys.stderr)
                raise
        if not started:
            shutil.rmtree(root)
            print("P19_HTTP_DISPOSABLE_CLUSTER_REMOVED=PASS", flush=True)


if __name__ == "__main__":
    main()
