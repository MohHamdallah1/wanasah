"""B4 disposable ONLY: repeated catalog inserts -> deleted synthetic SKUs -> VACUUM -> refill.

This intentionally runs SQL deletion/reindex on an isolated throwaway PostgreSQL
16 clone with one synthetic tenant. It is a *physical storage experiment*,
NOT an authorized product delete API and NOT a production maintenance script.
Never run on velotrack_db, user/customer data, any remote server, or normal
application credentials. An outer runner destroys this DB and server afterward.
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
        WHERE n.nspname='public' AND t.relname IN ('products','product_variants')
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
    for table in ("products","product_variants"):
        await adm.execute(f"VACUUM (ANALYZE) public.{table}")
    write("B4_MANUAL_VACUUM_"+phase,{"seconds":round(perf_counter()-now,3)})


async def main():
    token=tenant_context.set(2)
    adm=None
    try:
        adm=await asyncpg.connect(
            host="127.0.0.1",port=55441,user="c2_temp_admin",
            database="b3_index_growth",
        )
        if await adm.fetchval("SELECT current_database()")!="b3_index_growth":
            raise RuntimeError("Unexpected clone name")
        await adm.execute("SET statement_timeout='35000ms'")
        # Disable only the clone's automatic vacuum; we measure a known vacuum
        # transition and then REINDEX only in the disposable DB.
        for table in ("products","product_variants"):
            await adm.execute(
                f"ALTER TABLE public.{table} SET (autovacuum_enabled=false)"
            )
        async for db in scoped_session():
            count=await db.scalar(text(
                "SELECT count(*) FROM product_variants WHERE company_id=2 "
                "AND name LIKE 'B3 Synthetic Product %'"
            ))
            if count!=COUNT:
                raise RuntimeError(f"Only {COUNT} generated test variants permitted: {count}")
            if await db.scalar(text(
                "SELECT count(*) FROM product_variants WHERE company_id=2"
            )) != COUNT+1:
                raise RuntimeError("Unexpected real data: abort B4")
            if await db.scalar(text(
                "SELECT count(*) FROM price_book_entries WHERE company_id=2"
            ))!=2*COUNT:
                raise RuntimeError("Missing original published price evidence")
            await db.rollback()
            initial=await index_snapshot(adm,"ORIGINAL_1000")
            await manual_vacuum(adm,"AFTER_INITIAL_INSERT")
            post_first_vacuum=await index_snapshot(adm,"AFTER_INSERT_VACUUM")

            # The original public product-delete workflow forbids deleting a
            # populated family; do NOT claim this as a real product deletion.
            # Restrict artificial physical churn to synthetic row names and
            # synthetic tenant 2 after precise fixture cardinality checks.
            started=perf_counter()
            sql_base="product_variant_id IN (SELECT id FROM product_variants WHERE company_id=2 AND name LIKE 'B3 Synthetic Product %')"
            await db.execute(text("SET LOCAL statement_timeout='35000ms'"))
            price=(await db.execute(text(
                "DELETE FROM price_book_entries WHERE company_id=2 AND "+sql_base
            ))).rowcount
            conv=(await db.execute(text(
                "DELETE FROM product_uom_conversions WHERE company_id=2 AND "+sql_base
            ))).rowcount
            products=(await db.execute(text(
                "DELETE FROM product_variants WHERE company_id=2 "
                "AND name LIKE 'B3 Synthetic Product %'"
            ))).rowcount
            masters=(await db.execute(text(
                "DELETE FROM products WHERE company_id=2 "
                "AND name LIKE 'B3 Synthetic Product %'"
            ))).rowcount
            if (price,conv,products,masters)!=(2*COUNT,COUNT,COUNT,COUNT):
                raise RuntimeError("Unexpected synthetic delete counts; rollback")
            await db.commit()
            assert await db.scalar(text(
                "SELECT count(*) FROM product_variants WHERE company_id=2"
            ))==1
            await db.rollback()
            write("B4_TEST_ONLY_SYNTHETIC_DELETE",{
                "price_entries":price,"uom_conversions":conv,
                "variants":products,"masters":masters,
                "seconds":round(perf_counter()-started,3),
                "note":"NOT A REAL PRODUCT DELETION WORKFLOW",
            })
            after_delete=await index_snapshot(adm,"AFTER_DELETE_BEFORE_VACUUM")
            await manual_vacuum(adm,"AFTER_SYNTHETIC_DELETE")
            post_delete_vacuum=await index_snapshot(adm,"AFTER_DELETE_VACUUM")

            actor=await db.scalar(select(Driver).where(
                Driver.company_id==2,Driver.is_admin.is_(True)
            ))
            if actor is None:
                raise RuntimeError("Synthetic actor missing")
            t=perf_counter()
            for batch in range(COUNT//100):
                n=batch*100
                specs=[
                    SimpleProductSpec(
                        name=f"B4 Refill Product {n+i+1:07d}",
                        units_per_package=24,package_uom_code="CARTON",
                        unit_price=Decimal("1"),package_price=Decimal("24"),
                        lot_control_mode="NONE",expiry_control_mode="NONE",
                    ) for i in range(100)
                ]
                rows=await create_products_and_prices(
                    db,actor=actor,request_id=uuid4(),specs=specs,
                )
                if len(rows)!=100:
                    raise RuntimeError("B4 refill incomplete")
                await db.commit()
            assert await db.scalar(text(
                "SELECT count(*) FROM product_variants WHERE company_id=2"
            ))==COUNT+1
            assert await db.scalar(text(
                "SELECT count(*) FROM price_book_entries WHERE company_id=2"
            ))==2*COUNT
            await db.rollback()
            write("B4_POST_VACUUM_REFILL",{
                "recreated_variants":COUNT,
                "seconds":round(perf_counter()-t,3),
            })
            after_reinsert=await index_snapshot(adm,"AFTER_REFILL")
            await manual_vacuum(adm,"AFTER_REFILL")
            after_reinsert_vacuum=await index_snapshot(adm,"AFTER_REFILL_VACUUM")

            # Comparison-only REINDEX on the isolated clone, never source.
            t=perf_counter()
            for table in ("products","product_variants"):
                await adm.execute(f"REINDEX TABLE public.{table}")
            after_reindex=await index_snapshot(adm,"AFTER_CLONE_REINDEX")
            write("B4_CHURN_CAUSAL_SUMMARY",{
                "generated_variants_per_wave":COUNT,
                "first_wave_index_bytes":initial["total_catalog_index_bytes"],
                "first_post_vacuum_bytes":post_first_vacuum["total_catalog_index_bytes"],
                "after_physical_delete_bytes":after_delete["total_catalog_index_bytes"],
                "after_delete_vacuum_bytes":post_delete_vacuum["total_catalog_index_bytes"],
                "after_refill_bytes":after_reinsert["total_catalog_index_bytes"],
                "after_refill_vacuum_bytes":after_reinsert_vacuum["total_catalog_index_bytes"],
                "after_throwaway_reindex_bytes":after_reindex["total_catalog_index_bytes"],
                "reindex_bytes_recovered_inside_disposable_only":(
                    after_reinsert_vacuum["total_catalog_index_bytes"]
                    -after_reindex["total_catalog_index_bytes"]
                ),
                "gin_pending_before_first_vacuum":initial["gin_pending_pages"],
                "gin_pending_after_first_vacuum":post_first_vacuum["gin_pending_pages"],
                "gin_pending_after_delete_vacuum":post_delete_vacuum["gin_pending_pages"],
                "reindex_seconds":round(perf_counter()-t,3),
                "scope":"small disposable 1000/live SKU churn, not active 217k-row catalog",
            })
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
