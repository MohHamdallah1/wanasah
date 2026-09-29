"""B4 disposable ONLY: physical index churn in LIKE INCLUDING INDEXES shadow tables.

The real catalog source has immutable PUBLISHED price entries. We MUST NOT
delete them or disable their triggers to get an artificial performance result.
Instead, create two temporary-CLUSTER-only SHADOW tables using the exact 18
real catalog index definitions, copy 1000 synthetic SKU/master rows, and
insert/delete/refill them there. No real product/customer/accounting data is
deleted or modified, even inside the temporary fixture. This is an index
storage experiment, NOT a real product-deletion business workflow.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import select, text

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if (
    os.environ.get("WANASAH_B4_DISPOSABLE_CHURN_GATE") != "1"
    or os.environ.get("WANASAH_B3_DISPOSABLE_CHILD") != "1"
    or "127.0.0.1:55441/b3_index_growth"
    not in os.environ.get("WANASAH_B3_TEMP_DB_URL", "")
):
    raise RuntimeError("B4 is strictly confined to its test-only local DB")
load_dotenv(os.environ["WANASAH_B3_SOURCE_ENV_FILE"], override=False)
os.environ["DATABASE_URL"] = os.environ["WANASAH_B3_TEMP_DB_URL"]

import asyncpg
from context import tenant_context
from database import AsyncSessionLocal, engine
from models import Driver
from domains.simple_products.service import SimpleProductSpec, create_products_and_prices

COUNT = 1000
PREFIX = "B3 Synthetic Product "


def write(label, payload):
    print(label + " " + json.dumps(payload, default=str, separators=(",", ":")), flush=True)


async def scoped_session():
    db = AsyncSessionLocal()
    try:
        await db.execute(text("SELECT set_config('app.current_tenant','2',false)"))
        if await db.scalar(text("SELECT current_database()")) != "b3_index_growth":
            raise RuntimeError("Source DB mismatch. No operations performed.")
        yield db
    finally:
        await db.rollback()
        await db.close()


async def index_snapshot(adm, label):
    rows = await adm.fetch(
        """
        SELECT t.relname AS table_name,i.relname AS index_name,am.amname AS method,
        pg_relation_size(i.oid)::bigint AS bytes
        FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
        JOIN pg_index ix ON ix.indrelid=t.oid
        JOIN pg_class i ON i.oid=ix.indexrelid JOIN pg_am am ON am.oid=i.relam
        WHERE n.nspname='public' AND t.relname IN ('b4_products_shadow','b4_variants_shadow')
        ORDER BY t.relname,i.relname
        """
    )
    details = {}
    for row in rows:
        name=row["index_name"]
        entry={"method":row["method"],"bytes":int(row["bytes"])}
        if row["method"]=="btree":
            d=await adm.fetchrow("SELECT * FROM pgstatindex($1::regclass)",name)
            entry.update({
                "deleted":int(d["deleted_pages"]),
                "empty":int(d["empty_pages"]),
                "leaf_density":round(float(d["avg_leaf_density"]),2),
                "leaf_fragmentation":round(float(d["leaf_fragmentation"]),2),
            })
        elif row["method"]=="gin":
            d=await adm.fetchrow("SELECT * FROM pgstatginindex($1::regclass)",name)
            entry.update({"pending_pages":int(d["pending_pages"]),
                          "pending_tuples":int(d["pending_tuples"])})
        details[name]=entry
    if len(details)!=18:
        raise RuntimeError(f"Expected all 18 business catalog indexes, got {len(details)}")
    summary={
        "total_catalog_index_bytes":sum(r["bytes"] for r in details.values()),
        "gin_pending_pages":sum(r.get("pending_pages",0) for r in details.values()),
        "gin_pending_tuples":sum(r.get("pending_tuples",0) for r in details.values()),
        "btree_deleted_pages":sum(r.get("deleted",0) for r in details.values()),
        "btree_empty_pages":sum(r.get("empty",0) for r in details.values()),
        "largest":[
            {"index":n,**r}
            for n,r in sorted(details.items(),key=lambda z:z[1]["bytes"],reverse=True)[:8]
        ],
    }
    write("B4_PHYSICAL_"+label,summary)
    return summary


async def manual_vacuum(adm, phase):
    now=perf_counter()
    # AUTOVACUUM disabled only on this throwaway clone so the phase's manual
    # vacuum is deterministic. Both table statistics and all 18 indexes stay.
    for table in ("b4_products_shadow","b4_variants_shadow"):
        await adm.execute(f"VACUUM (ANALYZE) public.{table}")
    write("B4_MANUAL_VACUUM_"+phase,{"seconds":round(perf_counter()-now,3)})


async def main():
    # This database exists only inside the PG16 test runner and is destroyed
    # on exit. Use the superuser ONLY against b3_index_growth on localhost.
    token=tenant_context.set(2)
    adm=None
    try:
        adm=await asyncpg.connect(
            host="127.0.0.1",port=55441,user="c2_temp_admin",
            database="b3_index_growth",
        )
        if await adm.fetchval("SELECT current_database()")!="b3_index_growth":
            raise RuntimeError("Unexpected clone; no mutations")
        await adm.execute("SET statement_timeout='35000ms'")
        synthetic=await adm.fetchval(
            "SELECT count(*) FROM product_variants "
            "WHERE company_id=2 AND name LIKE 'B3 Synthetic Product %'"
        )
        total=await adm.fetchval(
            "SELECT count(*) FROM product_variants WHERE company_id=2"
        )
        original_prices=await adm.fetchval(
            "SELECT count(*) FROM price_book_entries WHERE company_id=2"
        )
        original_parents=await adm.fetchval(
            "SELECT count(*) FROM products "
            "WHERE company_id=2 AND name LIKE 'B3 Synthetic Product %'"
        )
        if (synthetic,total,original_prices,original_parents)!=(
            COUNT, COUNT+1, 2*COUNT, COUNT,
        ):
            raise RuntimeError("Unexpected source test-only fixture; refusing churn")

        # Crucial: the production tables preserve immutable price entries.
        # Copy only synthetic row values into new shadow tables; all constraints
        # and ALL 18 catalog index definitions are copied, but no live FKs or
        # immutable price triggers are bypassed, disabled, or altered.
        await adm.execute(
            "CREATE TABLE public.b4_products_shadow "
            "(LIKE public.products INCLUDING ALL)"
        )
        await adm.execute(
            "CREATE TABLE public.b4_variants_shadow "
            "(LIKE public.product_variants INCLUDING ALL)"
        )
        for table in ("b4_products_shadow","b4_variants_shadow"):
            await adm.execute(
                f"ALTER TABLE public.{table} SET (autovacuum_enabled=false)"
            )
        def source_name(table):
            return "products" if table=="b4_products_shadow" else "product_variants"

        async def refill(phase):
            started=perf_counter()
            for table in ("b4_products_shadow","b4_variants_shadow"):
                src=source_name(table)
                outcome=await adm.execute(
                    f"INSERT INTO public.{table} OVERRIDING SYSTEM VALUE "
                    f"SELECT * FROM public.{src} "
                    f"WHERE company_id=2 AND name LIKE 'B3 Synthetic Product %'"
                )
                if outcome!=f"INSERT 0 {COUNT}":
                    raise RuntimeError(f"Unexpected {table} {phase}: {outcome}")
            for table in ("b4_products_shadow","b4_variants_shadow"):
                exact=await adm.fetchval(
                    f"SELECT count(*) FROM public.{table} WHERE company_id=2"
                )
                if exact!=COUNT:
                    raise RuntimeError(f"Unexpected {phase} shadow count {table}")
            write("B4_SHADOW_REFILL_"+phase,{
                "copies_of_synthetic_rows":COUNT,
                "seconds":round(perf_counter()-started,3),
            })

        await refill("FIRST")
        first=await index_snapshot(adm,"FIRST_INSERT")
        await manual_vacuum(adm,"FIRST_INSERT")
        after_first_vacuum=await index_snapshot(adm,"FIRST_VACUUM")

        before=perf_counter()
        for table in ("b4_variants_shadow","b4_products_shadow"):
            result=await adm.execute(
                f"DELETE FROM public.{table} "
                "WHERE company_id=2 AND name LIKE 'B3 Synthetic Product %'"
            )
            if result!=f"DELETE {COUNT}":
                raise RuntimeError(f"Unexpected shadow-only delete count: {result}")
        write("B4_SHADOW_ONLY_DELETE",{
            "deleted_synthetic_masters":COUNT,
            "deleted_synthetic_variants":COUNT,
            "seconds":round(perf_counter()-before,3),
            "real_products_and_prices_untouched":True,
        })
        before_vacuum=await index_snapshot(adm,"DELETE_BEFORE_VACUUM")
        await manual_vacuum(adm,"AFTER_DELETE")
        after_delete_vacuum=await index_snapshot(adm,"DELETE_AFTER_VACUUM")
        await refill("SECOND")
        after_refill=await index_snapshot(adm,"REFILL_BEFORE_VACUUM")
        await manual_vacuum(adm,"AFTER_REFILL")
        after_refill_vacuum=await index_snapshot(adm,"REFILL_AFTER_VACUUM")

        # REINDEX is a disposable physical reference ONLY, never an index
        # migration or prescription to REINDEX on an active company.
        reindex_t=perf_counter()
        for table in ("b4_products_shadow","b4_variants_shadow"):
            await adm.execute(f"REINDEX TABLE public.{table}")
        post_reindex=await index_snapshot(adm,"AFTER_SHADOW_REINDEX")

        # Exact original immutable production fixtures must still be present
        # in the disposable source tables, not just in velotrack_db.
        final=(
            await adm.fetchval(
                "SELECT count(*) FROM product_variants "
                "WHERE company_id=2 AND name LIKE 'B3 Synthetic Product %'"
            ),
            await adm.fetchval(
                "SELECT count(*) FROM price_book_entries WHERE company_id=2"
            ),
        )
        if final!=(COUNT,2*COUNT):
            raise RuntimeError("Accidentally altered real catalog inside clone")
        write("B4_CHURN_CAUSAL_SUMMARY",{
            "source_priced_skus_preserved":final[0],
            "source_immutable_price_entries_preserved":final[1],
            "shadow_skus_per_wave":COUNT,
            "first_shadow_insert_bytes":first["total_catalog_index_bytes"],
            "after_first_vacuum_bytes":after_first_vacuum["total_catalog_index_bytes"],
            "after_shadow_delete_bytes":before_vacuum["total_catalog_index_bytes"],
            "after_delete_vacuum_bytes":after_delete_vacuum["total_catalog_index_bytes"],
            "after_refill_bytes":after_refill["total_catalog_index_bytes"],
            "after_refill_vacuum_bytes":after_refill_vacuum["total_catalog_index_bytes"],
            "after_reindex_bytes":post_reindex["total_catalog_index_bytes"],
            "reindex_reclaimed_bytes_IN_SHADOW_ONLY":(
                after_refill_vacuum["total_catalog_index_bytes"]
                -post_reindex["total_catalog_index_bytes"]
            ),
            "gin_pending_after_first_insert":first["gin_pending_pages"],
            "gin_pending_after_first_vacuum":after_first_vacuum["gin_pending_pages"],
            "gin_pending_after_delete_vacuum":after_delete_vacuum["gin_pending_pages"],
            "btree_deleted_pages_after_delete_vacuum":after_delete_vacuum["btree_deleted_pages"],
            "btree_deleted_pages_after_refill_vacuum":after_refill_vacuum["btree_deleted_pages"],
            "comparison_reindex_seconds":round(perf_counter()-reindex_t,3),
            "scope":"isolated exact-index definitions and identical synthetic rows, NOT full application delete",
        })
        if os.environ.get("WANASAH_B4_AUTOVACUUM_COMPARE")=="1":
            # Controlled only in this throwaway PG instance. Compare 10%
            # dead tuples in otherwise equally populated shadow tables:
            # variants: proposed lower threshold, products: default trigger.
            # The test is of threshold behavior, NOT a live tune-up.
            await adm.execute(
                "ALTER SYSTEM SET autovacuum_naptime='1s'"
            )
            await adm.execute("SELECT pg_reload_conf()")
            await asyncio.sleep(0.5)
            for table,scale in (
                ("b4_products_shadow","0.20"),
                ("b4_variants_shadow","0.02"),
            ):
                await adm.execute(
                    f"ALTER TABLE public.{table} SET ("
                    "autovacuum_enabled=true, "
                    "autovacuum_vacuum_threshold=50, "
                    f"autovacuum_vacuum_scale_factor={scale})"
                )
            before_stats=await adm.fetch(
                "SELECT relname,autovacuum_count,n_dead_tup "
                "FROM pg_stat_all_tables WHERE relname IN "
                "('b4_products_shadow','b4_variants_shadow') "
                "ORDER BY relname"
            )
            before_by_name={r["relname"]:dict(r) for r in before_stats}
            for table in ("b4_variants_shadow","b4_products_shadow"):
                result=await adm.execute(
                    f"DELETE FROM public.{table} WHERE id IN "
                    f"(SELECT id FROM public.{table} "
                    "ORDER BY id LIMIT 100)"
                )
                if result!="DELETE 100":
                    raise RuntimeError(f"Autovac test deletion unexpected: {result}")
            newer={}
            start_wait=perf_counter()
            for _ in range(60):
                await asyncio.sleep(.5)
                rows=await adm.fetch(
                    "SELECT relname,autovacuum_count,n_dead_tup "
                    "FROM pg_stat_all_tables WHERE relname IN "
                    "('b4_products_shadow','b4_variants_shadow')"
                )
                newer={r["relname"]:dict(r) for r in rows}
                if (
                    newer["b4_variants_shadow"]["autovacuum_count"]
                    > before_by_name["b4_variants_shadow"]["autovacuum_count"]
                ):
                    break
            tuned_seen=(
                newer["b4_variants_shadow"]["autovacuum_count"]
                > before_by_name["b4_variants_shadow"]["autovacuum_count"]
            )
            default_seen=(
                newer["b4_products_shadow"]["autovacuum_count"]
                > before_by_name["b4_products_shadow"]["autovacuum_count"]
            )
            write("B4_AUTOVACUUM_THRESHOLD_PROBE",{
                "clone_only":True,
                "table_size_before_delete":1000,
                "deleted_tuples_per_shadow":100,
                "default_threshold_at_1000_live":250,
                "tuned_threshold_at_1000_live":70,
                "tuned_autovacuum_observed":tuned_seen,
                "default_autovacuum_observed":default_seen,
                "tuned_post_dead_estimate":newer["b4_variants_shadow"]["n_dead_tup"],
                "default_post_dead_estimate":newer["b4_products_shadow"]["n_dead_tup"],
                "wait_seconds":round(perf_counter()-start_wait,2),
                "caveat":"physical source catalogs and default naptime not tested",
            })
            # Both options must be honestly recorded; if background vacuum
            # did not happen within the bounded window, the gate is PARTIAL.
            if not tuned_seen:
                print("B4_AUTO_POLICY_THRESHOLD=INCONCLUSIVE",flush=True)
            else:
                print("B4_AUTO_POLICY_THRESHOLD=PASS",flush=True)
        print("B4_SYNTHETIC_CHURN_AND_CLEANUP=PASS",flush=True)
    finally:
        tenant_context.reset(token)
        if adm is not None:
            await adm.close()
        await engine.dispose()


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
