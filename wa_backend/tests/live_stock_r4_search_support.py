"""R4 comparison helpers: immutable endpoint variants, emitted plans, one fixture."""
from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
from contextlib import contextmanager
from decimal import Decimal

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.warehouse import live_stock
from scripts import gate_r4_live_stock_perf_50k as r4

BASE_SHA = "2391bdd418ae53d585ba2ee27abec414bc9e4c8a"
OLD_FILTER = """            candidate_filters.append(
                ProductVariant.id.in_(search_variant_ids)
            )"""


def compile_endpoint(source, label):
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_warehouse_inventory")
    node.decorator_list = []
    namespace = vars(live_stock).copy()
    exec(compile(ast.Module(body=[node], type_ignores=[]),
                 f"<R4-{label}>", "exec"), namespace)
    return namespace["get_warehouse_inventory"]


def implementations():
    source = subprocess.check_output([
        "git", "show", BASE_SHA + ":wa_backend/api/warehouse/live_stock.py",
    ], text=True)
    assert source.count(OLD_FILTER) == 1
    ids_cte = source.replace(OLD_FILTER, """            search_matches = (
                search_variant_ids.cte("inventory_search_matches")
                .prefix_with("MATERIALIZED")
            )
            candidate_filters.append(
                ProductVariant.id.in_(select(search_matches.c[0]))
            )""")
    anchor = """                candidate_filters=candidate_filters,
                limit=limit,
                sort=sort,
            )

        # One statement snapshot"""
    assert source.count(anchor) == 1
    visible_cte = source.replace(anchor, """                candidate_filters=candidate_filters,
                limit=None if clean_search else limit,
                sort=sort,
            )

        if clean_search:
            search_matches = (
                candidate_stmt.order_by(None).limit(None)
                .cte("inventory_search_matches")
                .prefix_with("MATERIALIZED")
            )
            search_order = (
                (search_matches.c.variant_name.desc(), search_matches.c.id.desc())
                if sort == "name_desc"
                else (search_matches.c.variant_name.asc(), search_matches.c.id.asc())
            )
            candidate_stmt = (
                select(search_matches.c.id, search_matches.c.variant_name)
                .order_by(*search_order).limit(limit + 1)
            )

        # One statement snapshot""")
    return {
        "baseline": compile_endpoint(source, "accepted-main"),
        "scalar_array": live_stock.get_warehouse_inventory,
        "materialized_ids": compile_endpoint(ids_cte, "materialized-ids"),
        "materialized_visible": compile_endpoint(visible_cte, "materialized-visible"),
    }


@contextmanager
def endpoint(function, payloads=None):
    original = live_stock.get_warehouse_inventory
    async def recorded(**kwargs):
        payload = await function(**kwargs)
        if payloads is not None:
            payloads.append(payload)
        return payload
    live_stock.get_warehouse_inventory = recorded
    try:
        yield
    finally:
        live_stock.get_warehouse_inventory = original


def fingerprint(payload):
    return json.dumps(payload, sort_keys=True, default=str)


def page_plan(result):
    return next(p for p in result["plans"] if "inventory_page_candidates" in p["sql"])


def work_nodes(result):
    top = page_plan(result)["explain"]["plan"]["Plan"]
    return [{
        k: n.get(k) for k in (
            "Node Type", "Relation Name", "Index Name", "Actual Rows", "Actual Loops",
            "Rows Removed by Filter", "Plan Rows", "Group Key", "Index Cond")
    } for n in r4.plan_nodes(top)
      if n.get("Relation Name") == "product_variants"
      or (n.get("Node Type") == "Aggregate" and n.get("Actual Loops", 0) > 1)]


def relation_work(result):
    return max(
        ((n.get("Actual Rows") or 0) + (n.get("Rows Removed by Filter") or 0))
        * (n.get("Actual Loops") or 0)
        for n in work_nodes(result) if n["Relation Name"] == "product_variants"
    )


async def access_for(db, fixture, actor):
    key = "owner_backoffice_user_id" if actor == "owner" else "ordinary_backoffice_user_id"
    return (await r4.n1.load_backoffice_access(
        db, company_id=fixture["company_id"], backoffice_user_id=fixture[key],
        location_id=fixture["warehouse_id"]))[0]


def kwargs(db, fixture, access, **filters):
    values = r4.n1.inventory_page_kwargs(
        db=db, access=access, location_id=fixture["warehouse_id"],
        limit=50, cursor=None, search=None, only_alerts=False)
    values.update(filters)
    return values


async def set_reservation(admin_engine, fixture, variant_id, value):
    async with AsyncSession(admin_engine, expire_on_commit=False) as db:
        await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"),
                         {"c": str(fixture["company_id"])})
        await db.execute(text("""
            UPDATE inventory_balances SET reserved_quantity=:v
            WHERE company_id=:c AND location_id=:w AND product_variant_id=:p
                AND stock_status='AVAILABLE'
        """), {"v": Decimal(value), "c": fixture["company_id"],
               "w": fixture["warehouse_id"], "p": variant_id})
        await r4.refresh_live_stock_keys(db, company_id=fixture["company_id"],
            keys=[(fixture["warehouse_id"], variant_id)])
        await db.commit()


class PausedStatement:
    """Pause around the real one-statement read; never replace SQL/results."""
    def __init__(self, db, timing):
        self.db, self.timing = db, timing
        self.reached, self.release = asyncio.Event(), asyncio.Event()
    def __getattr__(self, name):
        return getattr(self.db, name)
    async def execute(self, statement, *args, **kwargs):
        combined = "inventory_page_candidates" in str(statement)
        if combined and self.timing == "before":
            self.reached.set()
            await asyncio.wait_for(self.release.wait(), 20)
        result = await self.db.execute(statement, *args, **kwargs)
        if combined and self.timing == "after":
            self.reached.set()
            await asyncio.wait_for(self.release.wait(), 20)
        return result
