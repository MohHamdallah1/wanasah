"""D6 opt-in worker SQLAlchemy/driver timing observer, NO business code changes.

Every measurement is one round-trip including driver, PostgreSQL execution,
possible lock time, and row transfer; it is NOT pure server CPU or SQL time.
Server-side pg_stat_statements is compared separately by the private runner.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys
import time

import psutil

if os.getenv("WANASAH_D6_DISPOSABLE_WORKER")!="1":
    raise RuntimeError("D6 profiling worker only runs in disposable runner.")
if "127.0.0.1:55445/d1_mix" not in os.getenv("DATABASE_URL",""):
    raise RuntimeError("D6 profiling worker DB identity mismatch.")
dest=Path(os.environ["WANASAH_D6_SQL_JSON"])
from sqlalchemy import event
from database import engine
from domains.simple_products.imports.infrastructure import worker_cli

stats=defaultdict(lambda:{"calls":0,"driver_wall_ms":0.0,"max_ms":0.0})
total_queries=0
total_wall_ms=0.0
worker_profile_start_cpu=time.process_time()
worker_profile_start_wall=time.perf_counter()
_worker_process=psutil.Process(os.getpid())
_worker_peak_rss=0


def tag(sql:str)->str:
    s=sql.lstrip().lower()
    first=s.split(None,1)[0] if s else "empty"
    target=re.search(
        r"\b(?:from|into|update|join)\s+(?:public\.)?([a-z_][a-z_0-9]*)",
        s,
    )
    return first+":"+(target.group(1) if target else "other")


@event.listens_for(engine.sync_engine,"before_cursor_execute")
def start_query(_conn,_cursor,statement,_parameters,context,_executemany):
    context._d6_monotonic_start=time.perf_counter()


@event.listens_for(engine.sync_engine,"after_cursor_execute")
def finish_query(_conn,_cursor,statement,_parameters,context,_executemany):
    global total_queries,total_wall_ms
    began=getattr(context,"_d6_monotonic_start",None)
    if began is None:return
    elapsed=(time.perf_counter()-began)*1000.0
    key=tag(statement)
    row=stats[key]
    row["calls"]+=1
    row["driver_wall_ms"]+=elapsed
    row["max_ms"]=max(row["max_ms"],elapsed)
    total_queries+=1
    total_wall_ms+=elapsed


def snapshot():
    global _worker_peak_rss
    _worker_peak_rss=max(
        _worker_peak_rss,
        int(_worker_process.memory_info().rss),
    )
    top=sorted(
        (
            {"group":group,"calls":row["calls"],
             "driver_wall_ms":round(row["driver_wall_ms"],3),
             "max_ms":round(row["max_ms"],3)}
            for group,row in stats.items()
        ),
        key=lambda x:x["driver_wall_ms"],
        reverse=True,
    )[:22]
    return {
        "statements":total_queries,
        "driver_roundtrip_sum_ms":round(total_wall_ms,3),
        "worker_process_cpu_seconds":round(
            time.process_time()-worker_profile_start_cpu,3
        ),
        "worker_process_wall_seconds":round(
            time.perf_counter()-worker_profile_start_wall,3
        ),
        "worker_peak_rss_mib":round(_worker_peak_rss/1024**2,2),
        "instrumented_pid":os.getpid(),
        "top_sql_groups":top,
        "note":"Per-query wall includes PG execution, lock waits, driver and transport; groups aggregate not mutually exclusive with process wall.",
    }


async def report_periodically():
    while True:
        await asyncio.sleep(.25)
        temp=dest.with_suffix(".tmp")
        temp.write_text(json.dumps(snapshot(),separators=(",",":")),
                        encoding="utf-8")
        os.replace(temp,dest)


async def run():
    reporter=asyncio.create_task(report_periodically())
    try:
        await worker_cli.run("execution")
    finally:
        reporter.cancel()
        temp=dest.with_suffix(".tmp")
        temp.write_text(json.dumps(snapshot()),encoding="utf-8")
        os.replace(temp,dest)


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.run(run(),loop_factory=asyncio.SelectorEventLoop)
    else:asyncio.run(run())
