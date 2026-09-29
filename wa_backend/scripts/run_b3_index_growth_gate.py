"""Fail-closed disposable PostgreSQL 16 Phase-B3 catalog profiling wrapper.

Only a schema-only copy plus known synthetic company-2 fixtures are copied
from authorized local velotrack_db. No customer rows, production data or
active source database writes. pgstattuple is activated ONLY inside
b3_index_growth on the throwaway PostgreSQL cluster, never on source.

Commands, benchmark outputs and postmaster status are bounded. Native pg_ctl
stdio uses DEVNULL to avoid detached Windows handle inheritance deadlocks.
Usage from clean hardening worktree wa_backend:
  WANASAH_B3_LOCAL_INDEX_GATE=1
  WANASAH_B3_SOURCE_ENV_FILE=<absolute authorized developer .env>
  python scripts/run_b3_index_growth_gate.py
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
import time

from dotenv import load_dotenv
from sqlalchemy.engine import URL

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import run_c2_isolated_committed_gate as base

_PORT = 55441
_ADMIN = "c2_temp_admin"
_TEMPLATE = "b3_index_template"
_BENCH = "b3_index_growth"
_TEMP_PREFIX = "wanasah_b3_index_gate_"


def _check_environment():
    if os.environ.get("WANASAH_B3_LOCAL_INDEX_GATE") != "1":
        raise RuntimeError("B3 benchmark requires explicit local opt-in.")
    if pathlib.Path.cwd().resolve() != _PROJECT_ROOT.resolve():
        raise RuntimeError("Run B3 only from the hardening wa_backend checkout.")
    if pathlib.Path.cwd().parent.name != "wanasah-hardening":
        raise RuntimeError("Refusing to run B3 outside clean hardening worktree.")
    source_env = os.environ.get("WANASAH_B3_SOURCE_ENV_FILE", "")
    if not source_env or not pathlib.Path(source_env).is_file():
        raise RuntimeError("Existing authorized local developer .env required.")
    load_dotenv(source_env, override=False)
    url = base._assert_source_url()
    count = int(os.environ.get("WANASAH_B3_MAX_ROWS","1000"))
    if count not in (100,1000):
        raise RuntimeError("Controlled B3 allows only 100 or 1000 variants.")
    if os.name != "nt":
        raise RuntimeError("This isolated runner has only been checked on Windows.")
    return url, source_env, count


def _bin(path,name):
    return base._pg(path,name)


def main() -> None:
    source,source_env,row_count=_check_environment()
    pg_bin=pathlib.Path(r"C:\Program Files\PostgreSQL\16\bin")
    for item in ("initdb","pg_ctl","psql","createdb","dropdb","pg_dump"):
        _bin(pg_bin,item)
    base._PORT = _PORT
    base._TEMPLATE = _TEMPLATE
    connection=socket.socket()
    connection.settimeout(1.0)
    try:
        if connection.connect_ex(("127.0.0.1",_PORT))==0:
            raise RuntimeError("Port 55441 occupied; refusing to touch an existing server.")
    finally:
        connection.close()

    directory=pathlib.Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX))
    started=False
    try:
        base._run([
            _bin(pg_bin,"initdb"),"-D",str(directory),
            "-U",_ADMIN,"-A","trust","-E","UTF8",
            "--no-instructions",
        ])
        base._run([
            _bin(pg_bin,"pg_ctl"),"-D",str(directory),
            "-l",str(directory/"postgres.log"),
            "-o",f"-p {_PORT} -h 127.0.0.1",
            "-w","start",
        ])
        started=True
        pg_env=os.environ.copy()
        pg_env["PGPASSWORD"]=source.password
        base._run([
            _bin(pg_bin,"pg_dump"),
            "-h",source.host,"-p",str(source.port or 5432),
            "-U",source.username,"-d",source.database,
            "--schema-only","--no-owner","--no-acl","--no-tablespaces",
            "-f",str(directory/"schema.sql"),
        ],env=pg_env)
        def cmd(db,*sql):
            return [
                _bin(pg_bin,"psql"),"-X","-h","127.0.0.1",
                "-p",str(_PORT),"-U",_ADMIN,"-d",db,
                "-v","ON_ERROR_STOP=1","-q",
                *sql,
            ]
        base._run(cmd("postgres","-c","CREATE ROLE wanasah_app LOGIN"))
        base._run([
            _bin(pg_bin,"createdb"),"-h","127.0.0.1",
            "-p",str(_PORT),"-U",_ADMIN,_TEMPLATE,
        ])
        base._run(cmd(_TEMPLATE,"-f",str(directory/"schema.sql")))
        asyncio.run(base._copy_safe_synthetic_fixture(source))
        # Explicitly seeded fixture PKs do not advance SERIAL/IDENTITY sequences.
        # Advance sequences on the TEMPORARY template only, before creating
        # real product masters, SKUs and active price publications.
        base._run(cmd(_TEMPLATE,"-c", """
        DO $b3$ DECLARE t text; seq_name text; max_id bigint;
        BEGIN
          FOREACH t IN ARRAY ARRAY[
            'uom','companies','drivers','products',
            'product_variants','inventory_locations','product_uom_conversions'
          ] LOOP
            SELECT pg_get_serial_sequence('public.'||t,'id') INTO seq_name;
            IF seq_name IS NOT NULL THEN
              EXECUTE format('SELECT COALESCE(MAX(id),0) FROM public.%I',t)
                INTO max_id;
              PERFORM setval(seq_name::regclass,GREATEST(max_id,1),true);
            END IF;
          END LOOP;
        END $b3$;
        """))
        paired = os.environ.get("WANASAH_B3_PAIRED_UOM") == "1"
        modes = (("uncached", True), ("cached", False)) if paired else (("single", False),)
        for label, without_cache in modes:
            base._run([
                _bin(pg_bin,"createdb"),"-h","127.0.0.1",
                "-p",str(_PORT),"-U",_ADMIN,"-T",_TEMPLATE,_BENCH,
            ])
            base._run(cmd(_BENCH,"-c","CREATE EXTENSION pgstattuple"))
            print("B3_PGSTAT_TUPLE_INSTALLED=DISPOSABLE_CLONE_ONLY",flush=True)
            # A/B control: strip ONLY non-unique GIN search indexes in the
            # disposable clone. It cannot affect source and is not production
            # guidance to drop any index.
            if os.environ.get("WANASAH_B3_DROP_GIN_ONLY_DISPOSABLE") == "1":
                if paired:
                    raise RuntimeError("GIN-off and paired UOM modes cannot mix.")
                base._run(cmd(_BENCH, "-c", """
                DROP INDEX public.ix_product_variants_company_search_trgm;
                DROP INDEX public.ix_products_company_name_trgm;
                """))
                print("B3_DISPOSABLE_COMPARISON=GIN_SEARCH_INDEXES_ABSENT_ONLY_IN_CLONE",flush=True)
            isolated=URL.create(
                "postgresql+asyncpg",
                username=source.username,
                host="127.0.0.1",port=_PORT,database=_BENCH,
            )
            child_env=os.environ.copy()
            child_env["WANASAH_B3_DISPOSABLE_CHILD"]="1"
            child_env["WANASAH_B3_SOURCE_ENV_FILE"]=source_env
            child_env["WANASAH_B3_TEMP_DB_URL"]=isolated.render_as_string(hide_password=False)
            child_env["WANASAH_B3_MAX_ROWS"]=str(row_count)
            child_env["WANASAH_B3_TEST_DISABLE_UOM_CACHE"]="1" if without_cache else "0"
            child_env["DATABASE_URL"]=isolated.render_as_string(hide_password=False)
            print("B3_CORE_PROFILE_START",{"row_limit":row_count,"database":_BENCH,
                "mode":label},flush=True)
            child=subprocess.run([
                sys.executable,str(_PROJECT_ROOT/"scripts"/"b3_profile_catalog_service.py"),
            ],env=child_env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
              text=True,encoding="utf-8",errors="replace",timeout=420,check=False)
            if child.stdout:
                for line in child.stdout.splitlines():
                    if line.startswith("B3_GATE "):
                        import json
                        result = json.loads(line.removeprefix("B3_GATE ").replace("NaN","null"))
                        brief = {key: result[key] for key in (
                            "real_created_variants","total_seconds","cached_uom",
                            "sql_statements","sql_by_type","sql_elapsed_seconds",
                            "stage_seconds","index_delta_bytes"
                        )}
                        print("B3_PAIRED_RUN_RESULT "+label+" "+json.dumps(brief,separators=(",",":")),flush=True)
                    elif line.startswith(("B3_EARLY_STOP","B3_CATALOG_CORE_BENCHMARK","B3_SQL_HOTSPOTS")):
                        print(line,flush=True)
            if child.returncode:
                raise RuntimeError(
                    "Disposable catalog profile failed (exit "
                    +str(child.returncode)+"): "+child.stderr[-2100:]
                )
            if "B3_CATALOG_CORE_BENCHMARK=PASS" not in child.stdout:
                raise RuntimeError("B3 child success marker missing.")
            if paired:
                # The child always closes its engine and superuser connection.
                # Drop ONLY this temporary bench DB before recreating a
                # byte-for-byte identical template for the second run.
                base._run([
                    _bin(pg_bin,"dropdb"),"-h","127.0.0.1",
                    "-p",str(_PORT),"-U",_ADMIN,_BENCH,
                ])
        if paired:
            print("B3_PAIRED_SAME_CLUSTER_RUNS=PASS",flush=True)
        asyncio.run(base._verify_source_still_empty(source))
        print("B3_DISPOSABLE_CATALOG_AND_SOURCE_ISOLATION=PASS",flush=True)
    finally:
        if started or (directory/"postmaster.pid").exists():
            try:
                base._run([
                    _bin(pg_bin,"pg_ctl"),"-D",str(directory),
                    "-m","fast","-w","stop",
                ])
                started=False
            except Exception:
                print("B3_STOP_UNCONFIRMED_PRESERVING_TEMP="+str(directory),file=sys.stderr,flush=True)
                raise
        if not started:
            for attempt in range(4):
                try:
                    shutil.rmtree(directory)
                    break
                except PermissionError:
                    if attempt==3:
                        raise
                    time.sleep(0.25)
            print("B3_DISPOSABLE_PG16_CLUSTER_REMOVED=PASS",flush=True)


if __name__=="__main__":
    main()
