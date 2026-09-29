"""B3.7 independent COMMITTED family-name concurrency in throwaway PG16 only.

Requires source wrapper to set WANASAH_B3_DISPOSABLE_CHILD and run a fresh
b3_index_growth clone. No customer data, no production writes, no bypassed
product life-cycle, no name uniqueness migration or trigger disables.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import select, text

_ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0,str(_ROOT))
if (
    os.environ.get("WANASAH_B37_RACE_GATE")!="1"
    or os.environ.get("WANASAH_B3_DISPOSABLE_CHILD")!="1"
    or "127.0.0.1:55441/b3_index_growth"
    not in os.environ.get("WANASAH_B3_TEMP_DB_URL","")
):
    raise RuntimeError("B3.7 durable races require approved disposable localhost DB")
load_dotenv(os.environ["WANASAH_B3_SOURCE_ENV_FILE"],override=False)
os.environ["DATABASE_URL"]=os.environ["WANASAH_B3_TEMP_DB_URL"]

from context import tenant_context
from database import AsyncSessionLocal, engine
from domains.simple_products.service import (
    SimpleProductError,
    SimpleProductSpec,
    _prefetch_batch_families,
    _resolve_family,
)
from models import Driver,Product


def spec(name, *, explicit_new=False):
    return SimpleProductSpec(
        name=name+" SKU",
        family_name=name,
        family_mode="new" if explicit_new else None,
        units_per_package=1,
        package_uom_code=None,
        unit_price=1,
    )


async def run_batch(label, specs, *, ready=None, unlock_after=None, signaled=None):
    token=tenant_context.set(2)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT set_config('app.current_tenant','2',false)"))
            await db.execute(text("SET LOCAL lock_timeout='3000ms'"))
            await db.execute(text("SET LOCAL statement_timeout='7000ms'"))
            assert await db.scalar(text("SELECT current_database()"))=="b3_index_growth"
            actor=await db.scalar(select(Driver).where(
                Driver.company_id==2,Driver.is_admin.is_(True),
            ))
            assert actor is not None
            if ready is not None:
                await ready.wait()
            if signaled is not None:
                signaled.set()
            lookup=await _prefetch_batch_families(
                db,actor=actor,specs=specs,
            )
            ids=[]
            for i,item in enumerate(specs,1):
                family=await _resolve_family(
                    db,actor=actor,spec=item,request_id=uuid4(),
                    index=i,batch_lookup=lookup,
                )
                ids.append(int(family.id))
            if unlock_after is not None:
                unlock_after.set()
                # Other transaction attempts the same advisory name lock and
                # waits until our genuinely durable transaction commits.
                await asyncio.sleep(.20)
            await db.commit()
            return ids
    finally:
        tenant_context.reset(token)


async def committed_count(names):
    token=tenant_context.set(2)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT set_config('app.current_tenant','2',false)"))
            rows=(await db.execute(
                select(Product.id,Product.name).where(
                    Product.company_id==2,
                    Product.name.in_(names),
                ).order_by(Product.name,Product.id)
            )).all()
            await db.rollback()
            return rows
    finally:
        tenant_context.reset(token)


async def main():
    first_name="B37-ONE-"+uuid4().hex[:12]
    release=asyncio.Event()
    requested=asyncio.Event()
    async def holder():
        return await run_batch(
            "holder",[spec(first_name)],unlock_after=release,
        )
    async def waiter():
        await release.wait()
        return await run_batch(
            "waiter",[spec(first_name)],signaled=requested,
        )
    async with asyncio.TaskGroup() as tg:
        a=tg.create_task(holder())
        b=tg.create_task(waiter())
    a_ids=a.result()
    b_ids=b.result()
    assert a_ids==b_ids
    rows=await committed_count([first_name])
    assert len(rows)==1 and int(rows[0].id)==a_ids[0]
    print("B37_INDEPENDENT_COMMITTED_SAME_NAME_REUSED=PASS",flush=True)

    # Adversarial different request order: sorted lock acquisition must give
    # a single global name order, unlike per-row unordered locking.
    a_name="B37-SORT-A-"+uuid4().hex[:12]
    b_name="B37-SORT-B-"+uuid4().hex[:12]
    barrier=asyncio.Event()
    async with asyncio.TaskGroup() as tg:
        first=tg.create_task(run_batch(
            "AB",[spec(a_name),spec(b_name)],
            unlock_after=barrier,
        ))
        async def reversed_batch():
            await barrier.wait()
            return await run_batch("BA",[spec(b_name),spec(a_name)])
        second=tg.create_task(reversed_batch())
    ids_a=first.result()
    ids_b=second.result()
    assert ids_a==list(reversed(ids_b)),(ids_a,ids_b)
    rows=await committed_count([a_name,b_name])
    assert len(rows)==2
    print("B37_INDEPENDENT_COMMITTED_REVERSED_NAMES_NO_DEADLOCK=PASS",flush=True)

    # Explicit "new" is NOT an UPSERT. Second worker must reject the
    # concurrently inserted name, even if it resolves to a legitimate parent.
    new_name="B37-NEW-"+uuid4().hex[:12]
    released=asyncio.Event()
    async def new_holder():
        return await run_batch(
            "new-holder",[spec(new_name,explicit_new=True)],
            unlock_after=released,
        )
    async def new_waiter():
        await released.wait()
        try:
            await run_batch(
                "new-waiter",[spec(new_name,explicit_new=True)],
            )
        except SimpleProductError as err:
            assert err.code=="SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT",err.code
            return "CONFLICT"
        raise AssertionError("Duplicate explicit new family was silently reused")
    async with asyncio.TaskGroup() as tg:
        a=tg.create_task(new_holder())
        b=tg.create_task(new_waiter())
    assert b.result()=="CONFLICT"
    rows=await committed_count([new_name])
    assert len(rows)==1 and int(rows[0].id)==a.result()[0]
    print("B37_INDEPENDENT_COMMITTED_EXPLICIT_NEW_COLLISION=PASS",flush=True)
    print("B37_DURABLE_FAMILY_RACE_GATE=PASS",flush=True)
    await engine.dispose()


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
