"""D2 lock contract: pricing Company mutex, FK compatibility, Live Stock guard.

Only run on a disposable localhost PG16 schema from the D1 harness.
Exercises real domain lock services, actual Route Launch, and exact
PostgreSQL lock modes with bounded liveness/tenant isolation checks.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import selectors
import sys
import time
from decimal import Decimal
from uuid import uuid4

import psycopg
from sqlalchemy import select, text

ROOT=pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
if (
    os.getenv("WANASAH_D1_DISPOSABLE_CHILD")!="1"
    or os.getenv("WANASAH_D2_LOCK_MATRIX")!="1"
    or "127.0.0.1:55445/d1_mix" not in os.getenv("DATABASE_URL","")
):
    raise RuntimeError("D2 lock matrix requires guarded private PG16 only")

from database import engine
from domains.pricing.core import acquire_pricing_company_lock
from domains.simple_products.imports.infrastructure.repository import (
    open_tenant_session, close_tenant_session,
)
from domains.live_stock_projection.service import (
    apply_live_stock_active_variant_delta,
)
from scripts import product_import_d1_real_business_child as d1


def sql_probes(admin:psycopg.Connection, statement:str):
    with admin.transaction():
        admin.execute("SET LOCAL lock_timeout='250ms'")
        return admin.execute(statement).fetchall()


def try_guard(company:int)->bool:
    with psycopg.connect(d1.dsn("DATABASE_URL_MIGRATION")) as other:
        return bool(other.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))",
            (f"live-stock-company-summary:{company}",)
        ).fetchone()[0])


def try_company(company:int, *, mode:str):
    if mode not in ("FOR KEY SHARE NOWAIT","FOR NO KEY UPDATE NOWAIT"):
        raise RuntimeError("Unsupported test lock mode")
    try:
        with psycopg.connect(d1.dsn("DATABASE_URL_MIGRATION")) as other:
            row=other.execute(
                "SELECT id FROM companies WHERE id=%s "+mode,(company,)
            ).fetchone()
            return {"ok":int(row[0])==company}
    except psycopg.Error as exc:
        return {"ok":False,"sqlstate":exc.sqlstate}


async def blocked_route_watcher(route_task:asyncio.Task, *, seconds=3.0):
    """Confirm Route Launch actually waits on the Company holder, not a timer."""
    with psycopg.connect(
        d1.dsn("DATABASE_URL_MIGRATION"),autocommit=True
    ) as inspector:
        stop=time.monotonic()+seconds
        while time.monotonic()<stop:
            if route_task.done():
                raise RuntimeError(
                    "D2 Route Launch completed despite held Company mutex"
                )
            blocked=inspector.execute(
                """
                SELECT count(*) FROM pg_stat_activity
                WHERE datname=current_database()
                  AND cardinality(pg_blocking_pids(pid)) > 0
                """
            ).fetchone()[0]
            if int(blocked)>=1:
                return int(blocked)
            await asyncio.sleep(0.025)
        raise RuntimeError("D2 Route Launch never reached a blocked PG lock")


async def main():
    ident=await d1.setup_committed_business()
    with psycopg.connect(
        d1.dsn("DATABASE_URL_MIGRATION"),autocommit=True,
    ) as admin:
        admin.execute(
            """
            INSERT INTO companies(
                id,name,company_code,is_active,subscription_status,
                currency_code,timezone,created_at
            )
            SELECT 3, name || ' D2',
                company_code || '-D2',
                is_active,subscription_status,
                currency_code,timezone,created_at
            FROM companies WHERE id=2
            """
        )
        company_price={}
        token,db=await open_tenant_session(2)
        try:
            await acquire_pricing_company_lock(db,2)
            fk=try_company(2,mode="FOR KEY SHARE NOWAIT")
            competing=try_company(2,mode="FOR NO KEY UPDATE NOWAIT")
            other=try_company(3,mode="FOR NO KEY UPDATE NOWAIT")
            if not fk["ok"] or competing.get("sqlstate")!="55P03" or not other["ok"]:
                raise RuntimeError(
                    f"D2 Company row mutex violated: {fk}, {competing}, {other}"
                )

            route_task=asyncio.create_task(d1.real_route_launch(ident))
            blocked=0
            try:
                blocked=await blocked_route_watcher(route_task)
            finally:
                # Release before awaiting route; never leave test blocked.
                await db.rollback()
            route=await asyncio.wait_for(route_task,timeout=8)
            if not route.get("commercial_context"):
                raise RuntimeError("D2 Route Launch lost commercial context")
            company_price={
                "fk_key_share_allowed":fk["ok"],
                "same_company_competing_pricing_sqlstate":competing["sqlstate"],
                "other_company_pricing_independent":other["ok"],
                "blocked_route_sessions":blocked,
                "released_route_id":int(route["route_id"]),
                "route_revision":int(
                    route["commercial_context"]["price_publication_revision"]
                ),
            }
        finally:
            await close_tenant_session(token,db)

        token,db=await open_tenant_session(2)
        try:
            await apply_live_stock_active_variant_delta(
                db,company_id=2,delta=0,
            )
            company2=try_guard(2)
            company3=try_guard(3)
            price_root=try_company(2,mode="FOR NO KEY UPDATE NOWAIT")
            if company2 or not company3 or not price_root["ok"]:
                raise RuntimeError(
                    "D2 Live Stock summary lock cross-domain contract failed: "
                    f"same={company2} other={company3} price={price_root}"
                )
            await db.rollback()
            released=try_guard(2)
            if not released:
                raise RuntimeError("D2 summary advisory lock leaked after rollback")
            projection={
                "same_company_summary_serialized":not company2,
                "other_company_summary_independent":company3,
                "pricing_mutex_independent_of_summary":price_root["ok"],
                "summary_released_after_rollback":released,
            }
        finally:
            await close_tenant_session(token,db)

        old_context=admin.execute(
            """
            SELECT price_publication_revision
            FROM route_commercial_contexts
            WHERE company_id=2
              AND dispatch_route_id=(SELECT id FROM dispatch_routes
                  WHERE company_id=2 AND driver_id=1 LIMIT 1)
            """
        ).fetchone()
        if old_context is None or int(old_context[0])!=1:
            raise RuntimeError("D2 historical route revision was rewritten")

        result={
            "company_price":company_price,
            "live_stock":projection,
            "original_immutable_route_revision":int(old_context[0]),
        }
        print("D2_LOCK_MATRIX="+json.dumps(result,separators=(",",":")),
              flush=True)
        print("PRODUCT_IMPORT_D2_LOCK_MATRIX=PASS",flush=True)
    await engine.dispose()


if __name__=="__main__":
    if sys.platform=="win32":
        asyncio.run(
            main(),
            loop_factory=lambda:asyncio.SelectorEventLoop(
                selectors.SelectSelector(),
            ),
        )
    else:asyncio.run(main())
