"""Audit D: real private-Postgres lock-order and Live Stock rebuild matrix.

Never run directly against developer/customer DB; parent runner verifies private
PG16 on 127.0.0.1:55445/d1_mix and destroys it after execution.
"""
from __future__ import annotations

import asyncio
import json
import os
import selectors
import sys
import time

from sqlalchemy import func, select, text

if os.environ.get("WANASAH_D_PROJECTION_DISPOSABLE_CHILD") != "1":
    raise RuntimeError("Private projection-lock child must be expressly enabled")
if "127.0.0.1:55445/d1_mix" not in os.environ.get("DATABASE_URL", ""):
    raise RuntimeError("Projection-lock test refuses non-private DB")

from context import tenant_context
from database import AsyncSessionLocal, engine
from domains.live_stock_projection.service import (
    _acquire_company_projection_guard,
    apply_live_stock_active_variant_delta,
    rebuild_live_stock_company,
    refresh_live_stock_variants,
)
from models import InventoryLiveStockCompanySummary, ProductVariant


async def tenant_session(company_id: int):
    token = tenant_context.set(company_id)
    db = AsyncSessionLocal()
    try:
        await db.execute(
            text("SELECT set_config('app.current_tenant', :c, false)"),
            {"c": str(company_id)},
        )
    except BaseException:
        await db.close()
        tenant_context.reset(token)
        raise
    return token, db


async def release_session(token, db):
    try:
        await db.close()
    finally:
        tenant_context.reset(token)


async def one_read(company_id: int, query):
    token, db = await tenant_session(company_id)
    try:
        value = await db.scalar(query)
        await db.rollback()
        return value
    finally:
        await release_session(token, db)


async def first_lock_order(variant_id: int):
    got_catalog_summary = asyncio.Event()
    release_catalog = asyncio.Event()
    rebuild_company_guard = asyncio.Event()
    abort_catalog = {"value": False}
    measured = {}

    async def catalog_path():
        token, db = await tenant_session(2)
        try:
            await db.execute(text("SET LOCAL lock_timeout = '4500ms'"))
            await apply_live_stock_active_variant_delta(
                db, company_id=2, delta=0,
            )
            got_catalog_summary.set()
            await release_catalog.wait()
            if abort_catalog["value"]:
                await db.rollback()
                return
            # Real lifecycle path touches the same company projection key
            # after it has updated/locked the company summary.
            await refresh_live_stock_variants(
                db, company_id=2, variant_ids=[variant_id],
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
        finally:
            got_catalog_summary.set()
            await release_session(token, db)

    async def rebuild_path():
        token, db = await tenant_session(2)
        try:
            await db.execute(text("SET LOCAL lock_timeout = '4500ms'"))
            started = time.perf_counter()
            await _acquire_company_projection_guard(
                db, company_id=2, exclusive=True,
            )
            measured["rebuild_company_guard_wait_ms"] = round(
                (time.perf_counter() - started) * 1000, 2,
            )
            rebuild_company_guard.set()
            report = await rebuild_live_stock_company(
                db, company_id=2, batch_size=500,
            )
            measured["rebuilt_candidate_keys"] = report.candidate_keys
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
        finally:
            rebuild_company_guard.set()
            await release_session(token, db)

    a = asyncio.create_task(catalog_path())
    b = None
    try:
        await asyncio.wait_for(got_catalog_summary.wait(), 5)
        if a.done():
            await a
            raise AssertionError("Catalog delta failed before acquiring guard")
        b = asyncio.create_task(rebuild_path())
        await asyncio.sleep(0.22)
        if rebuild_company_guard.is_set():
            # Fail closed rather than manufacturing the deadlock: it proves
            # the rebuild held the company lock while catalog still owned
            # the summary lock. Release catalog without its follow-up refresh
            # to let the private DB unwind safely.
            abort_catalog["value"] = True
            release_catalog.set()
            await asyncio.wait_for(asyncio.gather(a, b), 9)
            raise AssertionError(
                "DEADLOCK_RISK: rebuild grabbed company EXCLUSIVE while "
                "catalog owned company-summary; inversion is reproducible"
            )
        # Company 3 must remain independently schedulable while company 2
        # holds a shared guard.
        token3, db3 = await tenant_session(3)
        try:
            await asyncio.wait_for(
                _acquire_company_projection_guard(
                    db3, company_id=3, exclusive=True,
                ),
                1.5,
            )
            await db3.rollback()
            measured["other_tenant_independent"] = True
        finally:
            await release_session(token3, db3)
        release_catalog.set()
        await asyncio.wait_for(asyncio.gather(a, b), 18)
        if not measured.get("rebuild_company_guard_wait_ms", 0) >= 180:
            raise AssertionError("Rebuild did not wait for catalog's shared guard")
        return measured
    finally:
        release_catalog.set()
        for task in (a, b):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(
            *(t for t in (a, b) if t is not None),
            return_exceptions=True,
        )


async def reverse_lock_order():
    got_rebuild = asyncio.Event()
    release_rebuild = asyncio.Event()
    got_delta = asyncio.Event()
    observed = {}

    async def rebuild_first():
        token, db = await tenant_session(2)
        try:
            await db.execute(text("SET LOCAL lock_timeout = '4500ms'"))
            await _acquire_company_projection_guard(
                db, company_id=2, exclusive=True,
            )
            got_rebuild.set()
            await release_rebuild.wait()
            await db.rollback()
        except BaseException:
            await db.rollback()
            raise
        finally:
            got_rebuild.set()
            await release_session(token, db)

    async def delta_second():
        token, db = await tenant_session(2)
        try:
            await db.execute(text("SET LOCAL lock_timeout = '4500ms'"))
            started = time.perf_counter()
            await apply_live_stock_active_variant_delta(
                db, company_id=2, delta=0,
            )
            observed["catalog_delta_guard_wait_ms"] = round(
                (time.perf_counter() - started) * 1000, 2
            )
            got_delta.set()
            await db.rollback()
        except BaseException:
            await db.rollback()
            raise
        finally:
            got_delta.set()
            await release_session(token, db)

    a = asyncio.create_task(rebuild_first())
    b = None
    try:
        await asyncio.wait_for(got_rebuild.wait(), 5)
        if a.done():
            await a
            raise AssertionError("Exclusive guard failed to acquire")
        b = asyncio.create_task(delta_second())
        await asyncio.sleep(.22)
        if got_delta.is_set():
            await b
            raise AssertionError(
                "DEADLOCK_RISK: catalog delta acquired summary before "
                "rebuild's company-exclusive lock was released"
            )
        release_rebuild.set()
        await asyncio.wait_for(asyncio.gather(a, b), 10)
        if observed.get("catalog_delta_guard_wait_ms", 0) < 180:
            raise AssertionError("Catalog did not wait for company exclusive")
        return observed
    finally:
        release_rebuild.set()
        for task in (a, b):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(
            *(t for t in (a, b) if t is not None),
            return_exceptions=True,
        )


async def main():
    variant_id = await one_read(
        2,
        select(ProductVariant.id).where(
            ProductVariant.company_id == 2,
            ProductVariant.lifecycle_status == "ACTIVE",
        ).limit(1),
    )
    if variant_id is None:
        raise RuntimeError("Private company 2 active-variant fixture missing")
    first = await first_lock_order(int(variant_id))
    second = await reverse_lock_order()
    expected = int(
        await one_read(
            2,
            select(func.count(ProductVariant.id)).where(
                ProductVariant.company_id == 2,
                ProductVariant.lifecycle_status == "ACTIVE",
            ),
        )
    )
    actual = await one_read(
        2,
        select(InventoryLiveStockCompanySummary.active_variant_count).where(
            InventoryLiveStockCompanySummary.company_id == 2,
        ),
    )
    if actual is None or int(actual) != expected:
        raise AssertionError(
            "Company summary changed under guarded rebuild: "
            + str((actual, expected))
        )
    print("D_LOCK_MATRIX=" + json.dumps({
        "catalog_then_rebuild":first,
        "rebuild_then_catalog":second,
        "active_variant_summary":int(actual),
        "expected_active_variants":expected,
        "tenant3_independent":bool(first.get("other_tenant_independent")),
        "deadlocks":0,
    }, separators=(",",":"), sort_keys=True),flush=True)
    print("PRODUCT_IMPORT_D_PROJECTION_LOCK_MATRIX=PASS",flush=True)


async def guarded_main():
    try:
        await main()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(
            guarded_main(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(guarded_main())
