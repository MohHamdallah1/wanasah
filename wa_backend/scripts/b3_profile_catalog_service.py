"""Disposable-only catalog creation + price publishing profiling (Phase B3).

This is NOT the full HTTP/File/Queue import benchmark and does NOT clone real
customer rows. Parent runner configures an ephemeral PostgreSQL database,
installs pgstattuple there ONLY and supplies an explicitly named local URL.
Runs real simple_products.create_products_and_prices with batches of 100,
real RLS/constraints/publications, and reports the exact service/SQL cost.
"""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from decimal import Decimal
import json
import os
import pathlib
import re
import selectors
import sys
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

import asyncpg
from dotenv import load_dotenv
from sqlalchemy import event, func, select, text

if os.environ.get("WANASAH_B3_DISPOSABLE_CHILD") != "1":
    raise RuntimeError("Opt-in required: never execute benchmark against source DB.")
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv(os.environ["WANASAH_B3_SOURCE_ENV_FILE"], override=False)
os.environ["DATABASE_URL"] = os.environ["WANASAH_B3_TEMP_DB_URL"]

from context import tenant_context
from database import AsyncSessionLocal, engine
from models import Driver, Product, ProductVariant
from domains.simple_products import service as simple_service

METHODS = ("btree", "gin")


def report(label, data):
    print(label + " " + json.dumps(data, default=str, ensure_ascii=True, separators=(",", ":")), flush=True)


async def physical_snapshot(label, superuser):
    rows = await superuser.fetch(
        """
        SELECT t.relname AS table_name,
         i.relname AS index_name, am.amname AS method,
         pg_relation_size(i.oid)::bigint AS index_bytes
        FROM pg_class t
        JOIN pg_namespace n ON n.oid=t.relnamespace
        JOIN pg_index ix ON ix.indrelid=t.oid
        JOIN pg_class i ON i.oid=ix.indexrelid
        JOIN pg_am am ON am.oid=i.relam
        WHERE n.nspname='public' AND t.relname IN ('products','product_variants')
        ORDER BY t.relname,i.relname
        """
    )
    details = {}
    total = 0
    for row in rows:
        name = str(row["index_name"])
        size = int(row["index_bytes"])
        total += size
        metric = {"table":str(row["table_name"]),"method":str(row["method"]),"bytes":size}
        if row["method"] == "btree":
            data = await superuser.fetchrow("SELECT * FROM pgstatindex($1::regclass)",name)
            metric.update({
                "leaf_density":round(float(data["avg_leaf_density"]),2),
                "empty_pages":int(data["empty_pages"]),
                "deleted_pages":int(data["deleted_pages"]),
                "leaf_pages":int(data["leaf_pages"]),
                "leaf_fragmentation":round(float(data["leaf_fragmentation"]),2),
            })
        elif row["method"] == "gin":
            data = await superuser.fetchrow("SELECT * FROM pgstatginindex($1::regclass)",name)
            metric.update({"pending_pages":int(data["pending_pages"]),"pending_tuples":int(data["pending_tuples"])})
        details[name]=metric
    table_stat = await superuser.fetch("""
      SELECT c.relname AS name,
        pg_relation_size(c.oid)::bigint AS heap_bytes,
        pg_indexes_size(c.oid)::bigint AS index_bytes,
        s.n_tup_ins,s.n_tup_upd,s.n_tup_del,s.n_tup_hot_upd,s.n_dead_tup
      FROM pg_class c JOIN pg_stat_all_tables s ON s.relid=c.oid
      WHERE c.oid IN ('products'::regclass,'product_variants'::regclass)
    """)
    wal=await superuser.fetchrow("SELECT wal_bytes FROM pg_stat_wal")
    snapshot={"total_index_bytes":total,"index_count":len(details),
      "indexes":details,"tables":[dict(t) for t in table_stat],
      "cluster_wal_bytes":int(wal["wal_bytes"])}
    report("B3_PHYSICAL_"+label,snapshot)
    return snapshot


async def main():
    url=os.environ["WANASAH_B3_TEMP_DB_URL"]
    assert "127.0.0.1:55441/b3_index_growth" in url, "Refusing non-disposable DB"
    maximum=int(os.environ.get("WANASAH_B3_MAX_ROWS","1000"))
    if maximum not in (100,1000):
        raise RuntimeError("Only tested sample sizes 100 or 1000 allowed")
    admin=await asyncpg.connect(host="127.0.0.1",port=55441,user="c2_temp_admin",database="b3_index_growth")
    token=tenant_context.set(2)
    timings=defaultdict(float)
    counts=Counter()
    sql_durations=defaultdict(float)
    sql_buckets=Counter()
    bucket_durations=defaultdict(float)
    sql_times=[]

    def sql_bucket(statement):
        # Query family only, never show bind values or tenant-sensitive params.
        normalized = statement.lower()
        op=normalized.lstrip().split(" ",1)[0].upper()
        if "pg_advisory_xact_lock" in normalized:
            return "SELECT:family_name_advisory_lock"
        if op=="SELECT":
            match=re.search(r'\bfrom\s+([a-z0-9_."]+)',normalized)
            return "SELECT:"+(match.group(1).replace('"','') if match else "other")
        if op=="WITH":
            return "WITH:other"
        match=re.search(r'\b(?:insert\s+into|update|delete\s+from)\s+([a-z0-9_."]+)',normalized)
        return op+":"+(match.group(1).replace('"','') if match else "other")
    def before(_conn,_cursor,statement,_parameters,context,_executemany):
        context._b3_t0=perf_counter()
    def after(_conn,_cursor,statement,_parameters,context,_executemany):
        elapsed=perf_counter()-context._b3_t0
        op=statement.lstrip().split(" ",1)[0].upper()
        counts[op]+=1
        sql_durations[op]+=elapsed
        bucket=sql_bucket(statement)
        sql_buckets[bucket]+=1
        bucket_durations[bucket]+=elapsed
        if len(sql_times)<200:
            sql_times.append(elapsed)
    event.listen(engine.sync_engine,"before_cursor_execute",before)
    event.listen(engine.sync_engine,"after_cursor_execute",after)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT set_config('app.current_tenant','2',false)"))
            actual=await db.scalar(text("SELECT current_database()"))
            assert actual=="b3_index_growth"
            actor=await db.scalar(select(Driver).where(Driver.company_id==2,Driver.is_admin.is_(True)))
            assert actor is not None
            before_count=await db.scalar(select(func.count(ProductVariant.id)).where(ProductVariant.company_id==2))
            assert before_count==1,("Unsafe fixture: nonempty clone",before_count)
            start=await physical_snapshot("T0",admin)
            stage={"structure":0.0,"pricing":0.0,"price_policy":0.0}
            orig_struct=simple_service.create_product_structures
            orig_prices=simple_service.publish_prices
            orig_shape=simple_service._load_shape_for_spec
            orig_prepare_families=simple_service._prefetch_batch_families
            # Same real resolver + same rows, but restore its former per-SKU
            # lock/SELECT behavior in this disposable benchmark only.
            if os.environ.get("WANASAH_B3_TEST_DISABLE_FAMILY_BATCH") == "1":
                async def legacy_family_lookup(db, *, actor, specs):
                    return simple_service._BatchFamilyLookup(frozenset(), {})
                simple_service._prefetch_batch_families=legacy_family_lookup
            # Paired A/B uses identical running source code and identical
            # synthetic clone fixture. Only this test wrapper bypasses the
            # per-batch UOM memo (does not mutate the production code).
            if os.environ.get("WANASAH_B3_TEST_DISABLE_UOM_CACHE") == "1":
                async def uncached_shape(db, *, spec, batch_cache=None):
                    return await orig_shape(db, spec=spec, batch_cache=None)
                simple_service._load_shape_for_spec=uncached_shape
            async def time_struct(*args,**kwargs):
                t0=perf_counter()
                try:return await orig_struct(*args,**kwargs)
                finally:stage["structure"]+=perf_counter()-t0
            async def time_prices(*args,**kwargs):
                t0=perf_counter()
                try:return await orig_prices(*args,**kwargs)
                finally:stage["pricing"]+=perf_counter()-t0
            simple_service.create_product_structures=time_struct
            simple_service.publish_prices=time_prices
            complete=0
            family_scenario=os.environ.get("WANASAH_B3_FAMILY_SCENARIO","UNIQUE")
            if family_scenario not in ("UNIQUE","SHARED50"):
                raise RuntimeError("Only UNIQUE or SHARED50 synthetic family scenarios allowed")
            t_all=perf_counter()
            try:
                while complete<maximum:
                    n=min(100,maximum-complete)
                    specs=[
                        simple_service.SimpleProductSpec(
                            name=f"B3 Synthetic Product {complete+i+1:07d}",
                            family_name=(
                                "B37 Shared Family "+str((complete+i)%50+1).zfill(3)
                                if family_scenario=="SHARED50" else None
                            ),
                            units_per_package=24,
                            package_uom_code="CARTON",
                            package_price=Decimal("24"),
                            unit_price=Decimal("1"),
                            lot_control_mode="NONE",
                            expiry_control_mode="NONE",
                        ) for i in range(n)
                    ]
                    wall_start=perf_counter()
                    before_sql=sum(counts.values())
                    created=await simple_service.create_products_and_prices(
                        db,actor=actor,request_id=uuid4(),specs=specs)
                    assert len(created)==n
                    await db.commit()
                    complete+=n
                    batch_time=perf_counter()-wall_start
                    elapsed=perf_counter()-t_all
                    report("B3_BATCH",{"batch":complete//100,"created":n,"cumulative":complete,
                         "batch_seconds":round(batch_time,3),"sql_statements":sum(counts.values())-before_sql,
                         "cumulative_seconds":round(elapsed,3),"stage_struct_s":round(stage["structure"],3),
                         "stage_pricing_s":round(stage["pricing"],3)})
                    if complete==100:
                        await asyncio.sleep(0.15)
                        snap100=await physical_snapshot("100",admin)
                        if batch_time>65 and maximum>100:
                            report("B3_EARLY_STOP",{"reason":"A first 100 took >65s; no unbounded 1000-row run permitted"})
                            break
                final_count=await db.scalar(select(func.count(ProductVariant.id)).where(ProductVariant.company_id==2))
                assert final_count==1+complete,("Variant conservation failed",final_count,complete)
                if family_scenario=="SHARED50":
                    family_total=await db.scalar(text(
                        "SELECT count(*) FROM products WHERE company_id=2 "
                        "AND name LIKE 'B37 Shared Family %'"
                    ))
                    assert family_total==50, ("Expected 50 shared masters",family_total)
                    report("B37_50_SHARED_FAMILY_CONSERVATION",{
                        "unique_families":family_total,"sellable_skus":complete,
                    })
                price_count = await db.scalar(text(
                    "SELECT COUNT(*) FROM price_book_entries "
                    "WHERE company_id=2 AND is_published IS TRUE"
                ))
                publication_rows = (await db.execute(text(
                    "SELECT status, version FROM price_publications "
                    "WHERE company_id=2 ORDER BY id"
                ))).all()
                assert price_count == 2*complete, (
                    "Published EACH+CARTON entries missing or duplicated",
                    price_count, complete,
                )
                assert len(publication_rows) == complete//100, publication_rows
                assert all(
                    (status=="PUBLISHED" and version==202)
                    or (status=="SUPERSEDED" and version==203)
                    for status,version in publication_rows
                ), publication_rows
                report("B3_FINANCIAL_PUBLISHED_INVARIANTS", {
                    "variants": complete,
                    "published_price_entries": price_count,
                    "publications": len(publication_rows),
                    "published_version": 202, "superseded_version": 203,
                    "validated": True,
                })
            finally:
                simple_service.create_product_structures=orig_struct
                simple_service.publish_prices=orig_prices
                simple_service._load_shape_for_spec=orig_shape
                simple_service._prefetch_batch_families=orig_prepare_families
            await asyncio.sleep(0.15)
            ending=await physical_snapshot("END",admin)
            growth=[]
            for key,item in ending["indexes"].items():
                first=start["indexes"][key]
                growth.append({"index":key,"method":item["method"],
                               "delta_bytes":item["bytes"]-first["bytes"],
                               "leaf_density_initial":first.get("leaf_density"),
                               "leaf_density_after":item.get("leaf_density"),
                               "pending_initial":first.get("pending_tuples"),
                               "pending_after":item.get("pending_tuples")})
            growth.sort(key=lambda x:x["delta_bytes"],reverse=True)
            report("B3_SQL_HOTSPOTS",{
                "by_frequency":[{
                    "bucket":name,
                    "calls":count,
                    "db_seconds":round(bucket_durations[name],3),
                } for name,count in sql_buckets.most_common(24)],
                "by_database_time":[{
                    "bucket":name,
                    "calls":sql_buckets[name],
                    "db_seconds":round(total,3),
                } for name,total in sorted(
                    bucket_durations.items(),key=lambda x:x[1],reverse=True,
                )[:14]],
            })
            report("B3_GATE",{"source":"disposable_postgresql16_only","scope":"core_catalog_product_create_and_price_publish_not_full_file_import",
                 "real_created_variants":complete,"total_seconds":round(perf_counter()-t_all,3),
                 "cached_uom":os.environ.get("WANASAH_B3_TEST_DISABLE_UOM_CACHE") != "1",
                 "family_scenario":family_scenario,
                 "batched_families":os.environ.get("WANASAH_B3_TEST_DISABLE_FAMILY_BATCH") != "1",
                 "sql_statements":sum(counts.values()),"sql_by_type":dict(counts),
                 "sql_elapsed_seconds":{k:round(v,3) for k,v in sql_durations.items()},
                 "stage_seconds":{k:round(v,3) for k,v in stage.items()},
                 "index_delta_bytes":ending["total_index_bytes"]-start["total_index_bytes"],
                 "index_growth":growth})
            assert complete>=100
            print("B3_CATALOG_CORE_BENCHMARK=PASS",flush=True)
    finally:
        event.remove(engine.sync_engine,"before_cursor_execute",before)
        event.remove(engine.sync_engine,"after_cursor_execute",after)
        tenant_context.reset(token)
        await admin.close()
        await engine.dispose()


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
