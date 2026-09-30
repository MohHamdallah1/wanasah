"""D1: guarded disposable PG16 real business operations under Product Import."""
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

ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts import run_c2_isolated_committed_gate as base
from scripts import run_product_import_d4_isolated_gate as d4

PORT=55445
DATABASE="d1_mix"
TEMPLATE="d1_template"


def env_for(database:str,root:pathlib.Path)->dict[str,str]:
    env=d4.child_env(database,root)
    env.update({
        "WANASAH_D1_DISPOSABLE_CHILD": "1",
        "WANASAH_D7_DISPOSABLE_CHILD": os.getenv("WANASAH_D7_BURST", "0"),
        "WANASAH_D_PROJECTION_DISPOSABLE_CHILD": os.getenv("WANASAH_D_PROJECTION_LOCK_GATE", "0"),
        "WANASAH_D7_REQUESTS": os.getenv("WANASAH_D7_REQUESTS", "100"),
        "WANASAH_D1_MATRIX_SAMPLES": os.getenv("WANASAH_D1_MATRIX_SAMPLES", "30"),
        "WANASAH_D1_LOG_DIR":str(root),
        "PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS":"2",
        "WANASAH_D1_IMPORT_ROWS":os.getenv("WANASAH_D1_IMPORT_ROWS","3000"),
    })
    return env


def main()->None:
    if os.getenv("WANASAH_D1_LOCAL_GATE")!="1":
        raise RuntimeError("D1 requires explicit WANASAH_D1_LOCAL_GATE=1")
    envfile=os.getenv("WANASAH_D1_SOURCE_ENV_FILE","")
    if not envfile or not pathlib.Path(envfile).is_file():
        raise RuntimeError("D1 requires existing developer .env file")
    if pathlib.Path.cwd().name!="wa_backend":
        raise RuntimeError("D1 must start from wa_backend")
    load_dotenv(envfile,override=False)
    source=base._assert_source_url()
    bins=pathlib.Path(r"C:\Program Files\PostgreSQL\16\bin")
    for name in ("initdb","pg_ctl","psql","createdb","pg_dump"):
        base._pg(bins,name)
    probe=socket.socket()
    try:
        if probe.connect_ex(("127.0.0.1",PORT))==0:
            raise RuntimeError("D1 private port occupied; refusing external listener")
    finally: probe.close()

    tmp=pathlib.Path(tempfile.mkdtemp(prefix="wanasah_d1_real_business_"))
    started=False
    try:
        base._run([
            base._pg(bins,"initdb"),"-D",str(tmp),"-U",d4.ADMIN,
            "-A","trust","-E","UTF8","--no-instructions",
        ])
        d6_profile = os.getenv("WANASAH_D6_PROFILE") == "1"
        startup_options = f"-p {PORT} -h 127.0.0.1"
        if d6_profile:
            startup_options += (
                " -c shared_preload_libraries=pg_stat_statements"
                " -c pg_stat_statements.track=all"
                " -c track_io_timing=on"
                " -c track_wal_io_timing=on"
            )
        base._run([
            base._pg(bins,"pg_ctl"),"-D",str(tmp),
            "-l",str(tmp/"postgres.log"),"-o",
            startup_options, "-w","start",
        ])
        started=True
        srcenv=os.environ.copy()
        srcenv["PGPASSWORD"]=source.password
        base._run([
            base._pg(bins,"pg_dump"),"-h",source.host,
            "-p",str(source.port or 5432),"-U",source.username,
            "-d",source.database,"--schema-only","--no-owner","--no-acl",
            "--no-tablespaces","-f",str(tmp/"schema.sql"),
        ],env=srcenv)

        # Reuse audited fixture copier, migration runner and owned-sequence resync.
        base._PORT=PORT
        base._TEMPLATE=TEMPLATE
        d4.PORT=PORT
        d4.TEMPLATE=TEMPLATE
        d4.psql(bins,"postgres",f"CREATE ROLE {d4.APP} LOGIN")
        base._run([base._pg(bins,"createdb"),"-h","127.0.0.1",
                   "-p",str(PORT),"-U",d4.ADMIN,TEMPLATE])
        base._run([base._pg(bins,"psql"),"-X","-h","127.0.0.1",
                   "-p",str(PORT),"-U",d4.ADMIN,"-d",TEMPLATE,
                   "-v","ON_ERROR_STOP=1","-q","-f",str(tmp/"schema.sql")])
        asyncio.run(base._copy_safe_synthetic_fixture(source))
        d4.reset_owned_sequences(bins)
        if os.getenv("WANASAH_D7_BURST") == "1" or os.getenv("WANASAH_D_PROJECTION_LOCK_GATE") == "1":
            # Tenant 3 is created ONLY inside this new disposable schema;
            # never copy existing tenant-3 customer business data.
            from scripts import run_product_import_d32_isolated_gate as d32
            d32.PORT, d32.TEMPLATE = PORT, TEMPLATE
            d32.clone_second_synthetic_tenant(bins)
        d4.seed_control_rows(
            bins, source_revision=d4.read_source_revision(source),
        )
        d4.run([sys.executable,"-m","alembic","upgrade","head"],
               env=env_for(TEMPLATE,tmp))
        if d6_profile:
            d4.psql(
                bins,TEMPLATE,
                "CREATE EXTENSION IF NOT EXISTS pg_stat_statements",
            )
        base._run([base._pg(bins,"createdb"),"-h","127.0.0.1",
                   "-p",str(PORT),"-U",d4.ADMIN,"-T",TEMPLATE,DATABASE])
        matrix = os.getenv("WANASAH_D1_MATRIX") == "1"
        d2_lock = os.getenv("WANASAH_D2_LOCK_MATRIX") == "1"
        d7_burst = os.getenv("WANASAH_D7_BURST") == "1"
        d_projection = os.getenv("WANASAH_D_PROJECTION_LOCK_GATE") == "1"
        if sum((bool(matrix),bool(d2_lock),bool(d6_profile),bool(d7_burst),bool(d_projection))) > 1:
            raise RuntimeError("D1, D2, D6, D7 and projection-lock private tests are mutually exclusive")
        child_module = (
            "scripts.product_import_d_projection_lock_child" if d_projection
            else "scripts.product_import_d7_burst_child" if d7_burst
            else "scripts.product_import_d6_disposable_profile" if d6_profile
            else "scripts.gate_product_import_d2_lock_matrix_child" if d2_lock
            else "scripts.product_import_d1_business_matrix" if matrix
            else "scripts.product_import_d1_real_business_child"
        )
        child=d4.run([
            sys.executable,"-m",child_module,
        ],env=env_for(DATABASE,tmp))
        print(child.stdout,end="",flush=True)
        if os.getenv("WANASAH_D1_DIAGNOSTIC_ONLY") == "1":
            if "D1_IMPORT_DIAGNOSTIC=" not in child.stdout:
                raise RuntimeError("D1 diagnostic signature missing")
            print("D1_IMPORT_DIAGNOSTIC_CAPTURED=PASS",flush=True)
        elif d_projection:
            if "PRODUCT_IMPORT_D_PROJECTION_LOCK_MATRIX=PASS" not in child.stdout:
                raise RuntimeError("D projection lock-order acceptance missing")
        elif d7_burst:
            if "PRODUCT_IMPORT_D7_LOCAL_BURST=PASS" not in child.stdout:
                raise RuntimeError("D7 local burst acceptance missing")
        elif d6_profile:
            if "PRODUCT_IMPORT_D6_PROFILE=PASS" not in child.stdout:
                raise RuntimeError("D6 measured runtime profile acceptance missing")
        elif d2_lock:
            if "PRODUCT_IMPORT_D2_LOCK_MATRIX=PASS" not in child.stdout:
                raise RuntimeError("D2 guarded lock matrix acceptance missing")
        elif matrix:
            if "PRODUCT_IMPORT_D1_BUSINESS_MATRIX=PASS" not in child.stdout:
                raise RuntimeError("D1 multi-sample matrix acceptance missing")
        elif "PRODUCT_IMPORT_D1_MIXED_BUSINESS=PASS" not in child.stdout:
            raise RuntimeError("D1 acceptance signature missing")
        asyncio.run(base._verify_source_still_empty(source))
        print("D1_DEVELOPER_SOURCE_UNMODIFIED=PASS",flush=True)
    finally:
        if started or (tmp/"postmaster.pid").exists():
            base._run([base._pg(bins,"pg_ctl"),"-D",str(tmp),
                       "-m","fast","-w","stop"])
            started=False
        if not started:
            shutil.rmtree(tmp)
            print("D1_PRIVATE_POSTGRES_REMOVED=PASS",flush=True)


if __name__=="__main__":
    main()
