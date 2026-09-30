"""D6 guarded real-worker CPU, SQL/driver, DB execution, wait and WAL profile."""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import os
import pathlib
import selectors
import subprocess
import sys
import time
from uuid import uuid4

import psutil
import psycopg

ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
if (
    os.getenv("WANASAH_D1_DISPOSABLE_CHILD")!="1"
    or os.getenv("WANASAH_D6_PROFILE")!="1"
    or "127.0.0.1:55445/d1_mix" not in os.getenv("DATABASE_URL","")
):
    raise RuntimeError("D6 profile refuses all non-disposable databases.")

from database import engine
from scripts import product_import_d1_real_business_child as d1
from scripts.product_import_d6_price_probe import run_probe as d6_pricing_probe
from scripts.product_import_business_integrity_gate import (
    _assert_business_evidence,
)

ROWS=int(os.getenv("WANASAH_D1_IMPORT_ROWS","3000"))
if ROWS<1000 or ROWS>5000:
    raise RuntimeError("D6 represents bounded 1,000..5,000 rows only")


def server_snapshot(admin):
    wal=int(admin.execute(
        "SELECT wal_bytes FROM pg_stat_wal"
    ).fetchone()[0])
    stats=admin.execute("""
        SELECT coalesce(sum(calls),0),
               coalesce(sum(total_exec_time),0),
               coalesce(sum(blk_read_time+blk_write_time),0),
               coalesce(sum(wal_bytes),0),
               coalesce(sum(shared_blks_hit),0),
               coalesce(sum(shared_blks_read),0)
        FROM pg_stat_statements
        WHERE dbid=(SELECT oid FROM pg_database
                    WHERE datname=current_database())
          AND userid=(SELECT oid FROM pg_roles WHERE rolname='wanasah_app')
    """).fetchone()
    return wal, [float(x) for x in stats]


def server_top_queries(admin):
    return [{
        "query_class":tag(str(q)),
        "calls":int(calls),
        "server_exec_ms":round(float(ms),2),
        "shared_hit_blocks":int(hit),
        "shared_read_blocks":int(read),
        "wal_bytes":int(wal),
    } for q,calls,ms,hit,read,wal in admin.execute("""
        SELECT left(query,800), calls,total_exec_time,
               shared_blks_hit,shared_blks_read,wal_bytes
        FROM pg_stat_statements
        WHERE dbid=(SELECT oid FROM pg_database
                    WHERE datname=current_database())
          AND userid=(SELECT oid FROM pg_roles WHERE rolname='wanasah_app')
        ORDER BY total_exec_time DESC LIMIT 18
    """).fetchall()]


def tag(statement:str):
    import re
    sql=re.sub(r"\s+"," ",statement.strip().lower())
    first=sql.split(" ",1)[0] if sql else "other"
    m=re.search(
        r"\b(?:from|into|update|join)\s+(?:public\.)?([a-z_][a-z_0-9]*)",
        sql,
    )
    return first+":"+(m.group(1) if m else "other")


def active_waits(admin):
    rows=admin.execute("""
        SELECT COALESCE(wait_event_type,''),COALESCE(wait_event,''),
               cardinality(pg_blocking_pids(pid))
        FROM pg_stat_activity
        WHERE datname=current_database()
          AND pid<>pg_backend_pid()
          AND state='active'
    """).fetchall()
    return rows


def read_pricing_predecessor_plan(admin):
    """Read-only planner proof on the actual last 100-SKU import publication.

    The query is copied from pricing/publishing.py; no production index may
    be changed merely because an isolated plan identifies a plausible cost.
    """
    last=admin.execute("""
        SELECT id,price_book_id
        FROM price_publications
        WHERE company_id=2 AND status='PUBLISHED'
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    if last is None:
        raise RuntimeError("No published pricing revision for D6 proof")
    publication_id,price_book_id=map(int,last)
    with admin.transaction():
        admin.execute("SET LOCAL statement_timeout = '3000ms'")
        row=admin.execute("""
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            WITH fresh_pairs AS MATERIALIZED (
                SELECT DISTINCT product_variant_id, uom_id
                FROM price_book_entries
                WHERE company_id = %s
                  AND price_book_id = %s
                  AND publication_id = %s
            )
            SELECT EXISTS (
                SELECT 1 FROM fresh_pairs AS fresh
                WHERE EXISTS (
                    SELECT 1 FROM price_book_entries AS old
                    WHERE old.company_id = %s
                      AND old.price_book_id = %s
                      AND old.product_variant_id = fresh.product_variant_id
                      AND old.uom_id = fresh.uom_id
                      AND old.publication_id <> %s
                      AND old.is_published IS TRUE
                )
            )
        """,(2,price_book_id,publication_id,2,price_book_id,publication_id)).fetchone()[0]
    if isinstance(row,str):row=json.loads(row)
    top=row[0] if isinstance(row,list) else row
    nodes=[]
    def walk(node):
        if not isinstance(node,dict):return
        nodes.append({
            "type":node.get("Node Type"),
            "relation":node.get("Relation Name"),
            "index":node.get("Index Name"),
            "actual_rows":node.get("Actual Rows"),
            "loops":node.get("Actual Loops"),
            "hit_blocks":node.get("Shared Hit Blocks"),
            "filtered_rows":node.get("Rows Removed by Filter"),
        })
        for child in node.get("Plans",[]):walk(child)
    walk(top["Plan"])
    indices=admin.execute("""
        SELECT indexrelid::regclass::text,
               pg_relation_size(indexrelid)
        FROM pg_index
        WHERE indrelid='price_book_entries'::regclass
        ORDER BY pg_relation_size(indexrelid) DESC
        LIMIT 12
    """).fetchall()
    return {
        "executed_on":"disposable 3k tenant2 final publication",
        "total_execution_ms":round(float(top.get("Execution Time",0)),3),
        "total_shared_hit_blocks":top["Plan"].get("Shared Hit Blocks"),
        "nodes":nodes[:25],
        "pricing_index_bytes":{
            str(name):int(size) for name,size in indices
        },
        "warning":"EXPLAIN is for the final publication only, not an exact reconstruction of each earlier incremental batch."
    }


async def main():
    # Business setup before stats reset, so sample observes just import worker.
    await d1.setup_committed_business()
    admin=psycopg.connect(
        d1.dsn("DATABASE_URL_MIGRATION"),autocommit=True
    )
    worker=None
    log_file=None
    try:
        admin.execute("SELECT pg_stat_statements_reset()")
        admin.execute("SELECT pg_stat_reset_shared('wal')")
        job_id=await d1.submit_import()
        wal_before,stats_before=server_snapshot(admin)

        root=pathlib.Path(os.environ["WANASAH_D1_LOG_DIR"])
        log=root/"d6_profile_worker.log"
        sql_json=root/"d6_sql.json"
        env=os.environ.copy()
        env.update({
            "WANASAH_D6_DISPOSABLE_WORKER":"1",
            "WANASAH_D6_SQL_JSON":str(sql_json),
        })
        log_file=log.open("w",encoding="utf-8")
        worker=subprocess.Popen([
            sys.executable,
            "-m","scripts.product_import_d6_profile_worker",
        ],cwd=ROOT,env=env,stdout=log_file,stderr=subprocess.STDOUT,
            text=True)
        monitor=psutil.Process(worker.pid)
        wall_begin=time.perf_counter()
        cpu_begin=None
        cpu_end=0.0
        peak_rss=0
        peak_connections=0
        blocked_samples=0
        active_wait_types=Counter()
        stage_first={}
        last=None
        samples=0
        deadline=wall_begin+150
        while time.perf_counter()<deadline:
            if worker.poll() is not None:
                raise RuntimeError(
                    "D6 worker exited before job settled. Last status="+str(last)
                )
            now=time.perf_counter()
            last=d1.status(admin,job_id)
            if last is None:raise RuntimeError("D6 durable job missing")
            phase=str(last[0])
            stage_first.setdefault(phase,round(now-wall_begin,3))
            try:
                cpu=monitor.cpu_times()
                current_cpu=float(cpu.user+cpu.system)
                if cpu_begin is None:cpu_begin=current_cpu
                cpu_end=current_cpu
                peak_rss=max(peak_rss,int(monitor.memory_info().rss))
            except psutil.Error:pass

            wait_rows=active_waits(admin)
            for typ,event,blocker_count in wait_rows:
                if typ in ("Lock","IO","LWLock","BufferPin"):
                    active_wait_types[typ+":"+event]+=1
                if int(blocker_count)>0:blocked_samples+=1
            peak_connections=max(peak_connections,int(admin.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname=current_database()"
            ).fetchone()[0]))
            samples+=1
            if phase in d1.TERMINAL:
                break
            await asyncio.sleep(.06)
        else:
            raise RuntimeError(
                "D6 worker import exceeded bounded profile wall limit; "
                "last="+str(last)
            )

        active_delivery=0
        for _ in range(100):
            active_delivery=int(admin.execute(
                """
                SELECT count(*) FROM procrastinate_jobs
                WHERE task_name='wanasah.process_product_import'
                  AND args->>'job_id'=%s AND status IN ('todo','doing')
                """,
                (job_id,)
            ).fetchone()[0])
            if active_delivery==0:break
            await asyncio.sleep(.08)
        if active_delivery:
            raise RuntimeError("D6 import task did not reach terminal queue state")
        # Give in-process instrumentation observer its next checkpoint.
        await asyncio.sleep(.3)

        elapsed=time.perf_counter()-wall_begin
        wal_after,stats_after=server_snapshot(admin)
        top=server_top_queries(admin)
        if not sql_json.exists():
            raise RuntimeError("D6 real worker SQLAlchemy timing file missing")
        observed=json.loads(sql_json.read_text(encoding="utf-8"))
        expected=ROWS-ROWS//100
        if (
            str(last[0])!="COMPLETED_WITH_ERRORS"
            or int(last[1])!=expected
            or int(last[2])!=ROWS//100
        ):
            raise RuntimeError("D6 finished with unexpected job counters: "+str(last))
        evidence=_assert_business_evidence(admin,job_id,expected)
        if evidence["import_failed"]:
            raise RuntimeError("D6 execution contained failed valid rows")
        cpu_elapsed=float(observed["worker_process_cpu_seconds"])
        peak_rss_mib=float(observed["worker_peak_rss_mib"])
        if (
            cpu_elapsed<=0
            or peak_rss_mib<20
            or int(observed.get("instrumented_pid",0)) == worker.pid
            and peak_rss_mib<25
        ):
            raise RuntimeError(
                "D6 worker CPU/RSS fingerprint invalid; Windows launcher "
                f"must not be mistaken for Python execution: {observed}"
            )
        # PostgreSQL query/server time is aggregated for the private app role.
        # Concurrent queue/health queries may be included; do not conflate
        # summed SQL durations with critical-path import wall time.
        predecessor_plan=read_pricing_predecessor_plan(admin)
        price_sql_parity=d6_pricing_probe(admin)
        profile={
            "price_predecessor_explain":predecessor_plan,
            "price_candidate_sql_parity":price_sql_parity,
            "rows_total":ROWS,
            "rows_imported":expected,
            "job_status":str(last[0]),
            "elapsed_wall_seconds":round(elapsed,3),
            "worker_cpu_seconds":round(cpu_elapsed,3),
            "worker_cpu_percent_of_one_core":round(100*cpu_elapsed/max(elapsed,.01),1),
            "worker_peak_rss_mib":peak_rss_mib,
            "worker_profile_wall_seconds":observed["worker_process_wall_seconds"],
            "worker_instrumented_pid":int(observed["instrumented_pid"]),
            "sqlalchemy_statements":observed["statements"],
            "sqlalchemy_driver_roundtrip_sum_seconds":round(
                observed["driver_roundtrip_sum_ms"]/1000,3
            ),
            "top_sqlalchemy_groups":observed["top_sql_groups"][:12],
            "pg_stat_statements_total_calls_delta":int(stats_after[0]-stats_before[0]),
            "pg_stat_statements_total_exec_seconds_delta":round(
                (stats_after[1]-stats_before[1])/1000,3
            ),
            "pg_stat_statements_block_io_time_s_delta":round(
                (stats_after[2]-stats_before[2])/1000,3
            ),
            "pg_stat_statements_wal_bytes_delta":int(
                stats_after[3]-stats_before[3]
            ),
            "pg_stat_statements_shared_hit_delta":int(
                stats_after[4]-stats_before[4]
            ),
            "pg_stat_statements_shared_read_delta":int(
                stats_after[5]-stats_before[5]
            ),
            "private_cluster_global_wal_bytes_delta":int(wal_after-wal_before),
            "sample_count":samples,
            "db_blocking_samples":blocked_samples,
            "db_wait_type_samples":dict(active_wait_types),
            "max_connections_in_private_db":peak_connections,
            "observed_status_transition_offsets_s":stage_first,
            "top_pg_server_statements":top,
            "product_price_audit_outbox":evidence,
            "caveat":"PG SQL/server sums include same private app role health queries and may overlap; global WAL includes private cluster background work; CPU sampled per worker process only.",
        }
        print("D6_PROFILE="+json.dumps(
            profile,ensure_ascii=True,separators=(",",":")
        ),flush=True)
        print("PRODUCT_IMPORT_D6_PROFILE=PASS",flush=True)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
        if log_file:log_file.close()
        admin.close()
        await engine.dispose()


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.run(main(),loop_factory=lambda:asyncio.SelectorEventLoop(
            selectors.SelectSelector()
        ))
    else:asyncio.run(main())
