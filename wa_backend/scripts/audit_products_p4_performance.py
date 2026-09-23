from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import event, text


SCRIPTS = Path(__file__).resolve().parent
BACKEND = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(BACKEND))

import gate_products_read_contract_p2 as p2_gate
from api.simple_products import list_simple_products
from models import Driver


DEFAULT_ROWS = 5000
MIN_ROWS = 1000
MAX_ROWS = 20000
DEFAULT_RUNS = 3
MIN_RUNS = 2
MAX_RUNS = 7

RESULTS: list[tuple[str, bool, str]] = []

SEARCH_INDEXES = (
    "ix_product_variants_company_search_trgm",
    "ix_products_company_name_trgm",
    "ix_product_barcodes_company_active_barcode_trgm",
)


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail else "")
    )


def bounded_env_int(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(
            f"{name} must be between {minimum} and {maximum}."
        )
    return value


@dataclass(frozen=True)
class QuerySample:
    statement: str
    parameters: Any


class QueryProbe:
    def __init__(self) -> None:
        self.active = False
        self.samples: list[QuerySample] = []
        self._listener = self._before_cursor_execute

    def attach(self) -> None:
        event.listen(
            p2_gate.engine_app.sync_engine,
            "before_cursor_execute",
            self._listener,
        )

    def detach(self) -> None:
        event.remove(
            p2_gate.engine_app.sync_engine,
            "before_cursor_execute",
            self._listener,
        )

    def start(self) -> None:
        self.samples = []
        self.active = True

    def stop(self) -> list[QuerySample]:
        self.active = False
        return list(self.samples)

    def _before_cursor_execute(
        self,
        _conn,
        _cursor,
        statement,
        parameters,
        _context,
        _executemany,
    ) -> None:
        if not self.active:
            return
        self.samples.append(
            QuerySample(
                statement=str(statement),
                parameters=parameters,
            )
        )


async def inspect_search_indexes(session) -> None:
    extension_rows = list(
        (
            await session.execute(
                text(
                    "SELECT extname "
                    "FROM pg_extension "
                    "WHERE extname IN ('pg_trgm', 'btree_gin') "
                    "ORDER BY extname"
                )
            )
        ).scalars()
    )
    extensions = {str(value) for value in extension_rows}
    record(
        "trigram search extensions are installed",
        extensions == {"btree_gin", "pg_trgm"},
        "extensions=" + ",".join(sorted(extensions)),
    )

    rows = list(
        (
            await session.execute(
                text(
                    """
                    SELECT
                        idx.relname AS index_name,
                        i.indisvalid,
                        i.indisready,
                        pg_get_indexdef(i.indexrelid) AS index_def
                    FROM pg_index AS i
                    JOIN pg_class AS idx
                      ON idx.oid = i.indexrelid
                    WHERE idx.relname = ANY(:index_names)
                    ORDER BY idx.relname
                    """
                ),
                {"index_names": list(SEARCH_INDEXES)},
            )
        ).mappings()
    )
    by_name = {
        str(row["index_name"]): row
        for row in rows
    }
    for index_name in SEARCH_INDEXES:
        row = by_name.get(index_name)
        valid = (
            row is not None
            and bool(row["indisvalid"])
            and bool(row["indisready"])
        )
        definition = (
            str(row["index_def"])
            if row is not None
            else "MISSING"
        )
        print(
            "INDEX_STATE "
            f"name={index_name} "
            f"valid={valid} "
            f"definition={definition}"
        )
        record(
            f"search index {index_name} is installed and valid",
            valid,
        )


def normalized_sql(statement: str) -> str:
    return " ".join(statement.lower().split())


def main_product_query(
    samples: list[QuerySample],
) -> QuerySample | None:
    for sample in samples:
        normalized = normalized_sql(sample.statement)
        if (
            " from product_variants" in normalized
            and " order by " in normalized
            and " limit " in normalized
        ):
            return sample
    return None


def repeated_queries(
    samples: list[QuerySample],
) -> list[tuple[str, int]]:
    counts = Counter(
        (
            " ".join(sample.statement.split()),
            repr(sample.parameters),
        )
        for sample in samples
        if sample.statement.lstrip().upper().startswith("SELECT")
    )
    return sorted(
        (
            (
                f"{statement} PARAMS={parameters}",
                count,
            )
            for (statement, parameters), count
            in counts.items()
            if count > 1
        ),
        key=lambda item: (-item[1], item[0]),
    )


def walk_plan(node: dict[str, Any]):
    yield node
    for child in node.get("Plans", []) or []:
        if isinstance(child, dict):
            yield from walk_plan(child)


def summarize_plan(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    document = raw[0] if isinstance(raw, list) and raw else raw
    if not isinstance(document, dict):
        raise RuntimeError("EXPLAIN JSON document is invalid.")
    root = document.get("Plan")
    if not isinstance(root, dict):
        raise RuntimeError("EXPLAIN JSON plan root is missing.")

    scans: list[str] = []
    indexes: list[str] = []
    rows_removed = 0
    hot_nodes: list[dict[str, Any]] = []
    for node in walk_plan(root):
        node_type = str(node.get("Node Type", ""))
        relation = node.get("Relation Name")
        index_name = node.get("Index Name")
        loops = int(node.get("Actual Loops", 0) or 0)
        node_removed = 0
        if relation and "Scan" in node_type:
            scans.append(f"{node_type}:{relation}")
        if index_name:
            indexes.append(str(index_name))
        for key in (
            "Rows Removed by Filter",
            "Rows Removed by Index Recheck",
            "Rows Removed by Join Filter",
        ):
            value = node.get(key)
            if isinstance(value, (int, float)):
                removed = int(value)
                rows_removed += removed
                node_removed += removed
        if node_removed:
            hot_nodes.append(
                {
                    "node_type": node_type,
                    "relation": (
                        str(relation)
                        if relation is not None
                        else None
                    ),
                    "index": (
                        str(index_name)
                        if index_name is not None
                        else None
                    ),
                    "loops": loops,
                    "actual_rows": int(
                        node.get("Actual Rows", 0)
                        or 0
                    ),
                    "removed_per_loop": node_removed,
                    "estimated_total_removed": (
                        node_removed * max(loops, 1)
                    ),
                    "filter": str(
                        node.get("Filter", "")
                    )[:300],
                    "join_filter": str(
                        node.get("Join Filter", "")
                    )[:300],
                }
            )
    hot_nodes.sort(
        key=lambda item:
            int(item["estimated_total_removed"]),
        reverse=True,
    )

    return {
        "planning_ms": float(document.get("Planning Time", 0.0) or 0.0),
        "execution_ms": float(document.get("Execution Time", 0.0) or 0.0),
        "root_node": str(root.get("Node Type", "")),
        "plan_rows": int(root.get("Plan Rows", 0) or 0),
        "actual_rows": int(root.get("Actual Rows", 0) or 0),
        "shared_hit": int(root.get("Shared Hit Blocks", 0) or 0),
        "shared_read": int(root.get("Shared Read Blocks", 0) or 0),
        "temp_read": int(root.get("Temp Read Blocks", 0) or 0),
        "temp_written": int(root.get("Temp Written Blocks", 0) or 0),
        "rows_removed": rows_removed,
        "scans": sorted(set(scans)),
        "indexes": sorted(set(indexes)),
        "hot_nodes": hot_nodes[:8],
    }


async def explain_query(
    session,
    sample: QuerySample,
    *,
    seqscan_enabled: bool = True,
) -> dict[str, Any]:
    connection = await session.connection()
    if not seqscan_enabled:
        await connection.exec_driver_sql(
            "SET LOCAL enable_seqscan = off"
        )
    try:
        result = await connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            + sample.statement,
            sample.parameters,
        )
        return summarize_plan(result.scalar_one())
    finally:
        if not seqscan_enabled:
            await connection.exec_driver_sql(
                "SET LOCAL enable_seqscan = on"
            )


async def seed_committed_catalog(
    ids: dict[str, int],
    *,
    prefix: str,
    row_count: int,
) -> None:
    company_id = int(ids["company_id"])
    each_uom_id = int(ids["each_uom_id"])
    prefix_like = prefix + "-%"

    async with p2_gate.SessionSU() as su:
        await su.begin()

        await su.execute(
            text(
                "INSERT INTO products "
                "(company_id, code, name, version, created_at, updated_at) "
                "SELECT :company_id, "
                ":prefix || '-F-' || LPAD(gs::text, 6, '0'), "
                "CASE WHEN gs = 12 "
                "THEN 'P4PERF FAMILYHIT Family' "
                "ELSE 'P4PERF Family ' || LPAD(gs::text, 6, '0') END, "
                "1, NOW(), NOW() "
                "FROM generate_series(1, :row_count) AS gs"
            ),
            {
                "company_id": company_id,
                "prefix": prefix,
                "row_count": row_count,
            },
        )

        await su.execute(
            text(
                "WITH seeded AS ("
                "SELECT p.id AS product_id, RIGHT(p.code, 6)::integer AS n "
                "FROM products AS p "
                "WHERE p.company_id = :company_id "
                "AND p.code LIKE :prefix_like"
                ") "
                "INSERT INTO product_variants "
                "(company_id, product_id, base_uom_id, name, sku, "
                "quantity_scale, quantity_step, lot_control_mode, "
                "expiry_control_mode, lifecycle_status, operational_hold, "
                "lifecycle_revision, version, published_at, retired_at, "
                "archived_at, packs_per_carton, package_uses_base_barcode, "
                "default_max_samples_per_day, created_at, updated_at) "
                "SELECT :company_id, seeded.product_id, :uom_id, "
                "CASE WHEN seeded.n = 11 "
                "THEN 'P4PERF NAMEHIT Item' "
                "ELSE 'P4PERF Item ' || LPAD(seeded.n::text, 6, '0') END, "
                "CASE WHEN seeded.n = 13 "
                "THEN :prefix || '-SKU-HIT' "
                "ELSE :prefix || '-SKU-' || LPAD(seeded.n::text, 6, '0') END, "
                "0, 1, "
                "CASE WHEN seeded.n % 4 IN (0, 1) "
                "THEN 'REQUIRED' ELSE 'NONE' END, "
                "CASE WHEN seeded.n % 4 IN (1, 2) "
                "THEN 'REQUIRED' ELSE 'NONE' END, "
                "CASE WHEN seeded.n % 10 = 0 "
                "THEN 'RETIRING' ELSE 'ACTIVE' END, "
                "'NONE', 1, 1, NOW() - INTERVAL '2 days', "
                "CASE WHEN seeded.n % 10 = 0 "
                "THEN NOW() - INTERVAL '1 day' ELSE NULL END, "
                "NULL, 1, false, 0, NOW(), NOW() "
                "FROM seeded"
            ),
            {
                "company_id": company_id,
                "uom_id": each_uom_id,
                "prefix": prefix,
                "prefix_like": prefix_like,
            },
        )

        await su.execute(
            text(
                "WITH seeded AS ("
                "SELECT pv.id AS variant_id, RIGHT(p.code, 6)::integer AS n "
                "FROM product_variants AS pv "
                "JOIN products AS p "
                "ON p.company_id = pv.company_id AND p.id = pv.product_id "
                "WHERE pv.company_id = :company_id "
                "AND p.code LIKE :prefix_like"
                ") "
                "INSERT INTO product_barcodes "
                "(company_id, product_variant_id, uom_id, barcode, "
                "barcode_type, is_primary, valid_from, valid_to, "
                "is_active, version, created_at, updated_at) "
                "SELECT :company_id, seeded.variant_id, :uom_id, "
                "CASE WHEN seeded.n = 14 "
                "THEN :prefix || '-BARCODE-HIT' "
                "ELSE :prefix || '-BC-' || LPAD(seeded.n::text, 6, '0') END, "
                "'INTERNAL', true, NOW() - INTERVAL '1 day', NULL, "
                "true, 1, NOW(), NOW() "
                "FROM seeded WHERE seeded.n % 2 = 0"
            ),
            {
                "company_id": company_id,
                "uom_id": each_uom_id,
                "prefix": prefix,
                "prefix_like": prefix_like,
            },
        )

        await su.commit()

    async with p2_gate.SessionSU() as su:
        await su.begin()
        for table_name in (
            "products",
            "product_variants",
            "product_barcodes",
            "product_uom_conversions",
        ):
            await su.execute(text(f"ANALYZE {table_name}"))
        await su.commit()


async def seed_benchmark_prices(
    app,
    *,
    company_id: int,
    each_uom_id: int,
    prefix: str,
) -> None:
    book_id = int(
        (
            await app.execute(
                text(
                    "SELECT id FROM price_books "
                    "WHERE company_id = :company_id "
                    "ORDER BY id ASC LIMIT 1"
                ),
                {"company_id": company_id},
            )
        ).scalar_one()
    )
    publication_id = int(
        (
            await app.execute(
                text(
                    "SELECT id FROM price_publications "
                    "WHERE company_id = :company_id "
                    "AND price_book_id = :book_id "
                    "AND status = 'PUBLISHED' "
                    "ORDER BY revision DESC LIMIT 1"
                ),
                {
                    "company_id": company_id,
                    "book_id": book_id,
                },
            )
        ).scalar_one()
    )

    await app.execute(
        text(
            "WITH seeded AS ("
            "SELECT pv.id AS variant_id, RIGHT(p.code, 6)::integer AS n "
            "FROM product_variants AS pv "
            "JOIN products AS p "
            "ON p.company_id = pv.company_id AND p.id = pv.product_id "
            "WHERE pv.company_id = :company_id "
            "AND p.code LIKE :prefix_like"
            ") "
            "INSERT INTO price_book_entries "
            "(company_id, price_book_id, publication_id, "
            "product_variant_id, uom_id, amount, effectivity, priority, "
            "is_published, metadata, version, created_at, updated_at) "
            "SELECT :company_id, :book_id, :publication_id, "
            "seeded.variant_id, :uom_id, "
            "(1 + (seeded.n % 100))::numeric(20, 6), "
            "tstzrange(NOW() - INTERVAL '1 day', NULL, '[)'), "
            "0, true, '{\"managed_by\":\"p4_perf_audit\"}'::jsonb, "
            "1, NOW(), NOW() "
            "FROM seeded WHERE seeded.n % 2 = 0"
        ),
        {
            "company_id": company_id,
            "book_id": book_id,
            "publication_id": publication_id,
            "uom_id": each_uom_id,
            "prefix_like": prefix + "-%",
        },
    )


async def cleanup_committed_catalog(
    ids: dict[str, int],
    *,
    prefix: str,
) -> tuple[bool, str]:
    company_id = ids.get("company_id")
    try:
        if company_id is not None:
            async with p2_gate.SessionSU() as su:
                await su.begin()
                params = {
                    "company_id": int(company_id),
                    "prefix_like": prefix + "-%",
                }
                await su.execute(
                    text(
                        "DELETE FROM product_barcodes AS pb "
                        "USING product_variants AS pv, products AS p "
                        "WHERE pb.company_id = :company_id "
                        "AND pv.company_id = pb.company_id "
                        "AND pv.id = pb.product_variant_id "
                        "AND p.company_id = pv.company_id "
                        "AND p.id = pv.product_id "
                        "AND p.code LIKE :prefix_like"
                    ),
                    params,
                )
                await su.execute(
                    text(
                        "DELETE FROM product_variants AS pv "
                        "USING products AS p "
                        "WHERE pv.company_id = :company_id "
                        "AND p.company_id = pv.company_id "
                        "AND p.id = pv.product_id "
                        "AND p.code LIKE :prefix_like"
                    ),
                    params,
                )
                await su.execute(
                    text(
                        "DELETE FROM products "
                        "WHERE company_id = :company_id "
                        "AND code LIKE :prefix_like"
                    ),
                    params,
                )
                await su.commit()

        cleanup_ok, cleanup_detail = await p2_gate.cleanup(ids)

        async with p2_gate.SessionSU() as su:
            await su.begin()
            for table_name in (
                "products",
                "product_variants",
                "product_barcodes",
                "product_uom_conversions",
            ):
                await su.execute(text(f"ANALYZE {table_name}"))
            await su.commit()

        return cleanup_ok, cleanup_detail
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def endpoint_kwargs(**overrides) -> dict[str, Any]:
    values: dict[str, Any] = {
        "search": None,
        "cursor": None,
        "limit": 50,
        "family_id": None,
        "lifecycle": None,
        "tracking_type": None,
        "simple_compatible": None,
        "has_barcode": None,
        "has_price": None,
        "lot_tracked": None,
        "expiry_tracked": None,
        "sort_by": "id",
        "sort_dir": "asc",
    }
    values.update(overrides)
    return values


async def call_endpoint(
    app,
    actor: Driver,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    result = await list_simple_products(
        db=app,
        actor=actor,
        **kwargs,
    )
    if not isinstance(result, dict):
        raise RuntimeError("Product list did not return a mapping.")
    return result


async def measure_scenario(
    *,
    name: str,
    app,
    actor: Driver,
    probe: QueryProbe,
    kwargs: dict[str, Any],
    runs: int,
    explain: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    await call_endpoint(app, actor, kwargs)

    latencies: list[float] = []
    query_counts: list[int] = []
    representative: list[QuerySample] = []
    last_page: dict[str, Any] = {}

    for index in range(runs):
        probe.start()
        started = perf_counter()
        try:
            page = await call_endpoint(app, actor, kwargs)
        finally:
            samples = probe.stop()
        latencies.append((perf_counter() - started) * 1000.0)
        query_counts.append(len(samples))
        last_page = page
        if index == 0:
            representative = samples

    if len(set(query_counts)) != 1:
        raise RuntimeError(
            f"{name} query count changed across identical runs: "
            f"{query_counts}"
        )

    plan: dict[str, Any] = {}
    forced_index_plan: dict[str, Any] = {}
    if explain:
        captured = main_product_query(representative)
        if captured is None:
            raise RuntimeError(
                f"{name} main product query was not captured."
            )
        plan = await explain_query(app, captured)
        if name in {
            "name_search",
            "family_search",
            "sku_search",
            "barcode_search",
        }:
            forced_index_plan = await explain_query(
                app,
                captured,
                seqscan_enabled=False,
            )

    items = last_page.get("items")
    item_count = len(items) if isinstance(items, list) else -1
    metrics = {
        "latency_ms": statistics.median(latencies),
        "query_count": query_counts[0],
        "item_count": item_count,
        "repeated": repeated_queries(representative),
    }

    print(
        "METRIC "
        f"scenario={name} "
        f"latency_ms_median={metrics['latency_ms']:.3f} "
        f"query_count={metrics['query_count']} "
        f"items={item_count} "
        f"has_more={last_page.get('has_more')}"
    )
    if plan:
        print(
            "PLAN "
            f"scenario={name} "
            f"planning_ms={plan['planning_ms']:.3f} "
            f"execution_ms={plan['execution_ms']:.3f} "
            f"root={plan['root_node']} "
            f"plan_rows={plan['plan_rows']} "
            f"actual_rows={plan['actual_rows']} "
            f"shared_hit={plan['shared_hit']} "
            f"shared_read={plan['shared_read']} "
            f"temp_read={plan['temp_read']} "
            f"temp_written={plan['temp_written']} "
            f"rows_removed={plan['rows_removed']} "
            f"scans={'|'.join(plan['scans']) or '-'} "
            f"indexes={'|'.join(plan['indexes']) or '-'}"
        )
        for node in plan["hot_nodes"]:
            print(
                "PLAN_HOT_NODE "
                f"scenario={name} "
                f"node={node['node_type']} "
                f"relation={node['relation'] or '-'} "
                f"index={node['index'] or '-'} "
                f"loops={node['loops']} "
                f"actual_rows={node['actual_rows']} "
                f"removed_per_loop={node['removed_per_loop']} "
                f"estimated_total_removed="
                f"{node['estimated_total_removed']} "
                f"filter={node['filter'] or '-'} "
                f"join_filter={node['join_filter'] or '-'}"
            )
        if forced_index_plan:
            print(
                "FORCED_INDEX_PLAN "
                f"scenario={name} "
                f"execution_ms="
                f"{forced_index_plan['execution_ms']:.3f} "
                f"shared_hit={forced_index_plan['shared_hit']} "
                f"shared_read={forced_index_plan['shared_read']} "
                f"rows_removed={forced_index_plan['rows_removed']} "
                f"scans="
                f"{'|'.join(forced_index_plan['scans']) or '-'} "
                f"indexes="
                f"{'|'.join(forced_index_plan['indexes']) or '-'}"
            )

    for statement, count in metrics["repeated"]:
        print(
            "REPEATED_QUERY "
            f"scenario={name} count={count} "
            f"sql={statement[:220]}"
        )

    return metrics, last_page


def page_contains(
    page: dict[str, Any],
    field: str,
    marker: str,
) -> bool:
    items = page.get("items")
    return (
        isinstance(items, list)
        and any(
            isinstance(item, dict)
            and marker.lower()
            in str(item.get(field, "")).lower()
            for item in items
        )
    )


async def main() -> None:
    ids: dict[str, int] = {}
    prefix = "P4PERF" + uuid4().hex[:8].upper()
    row_count = bounded_env_int(
        "P4_PERF_ROWS",
        DEFAULT_ROWS,
        MIN_ROWS,
        MAX_ROWS,
    )
    runs = bounded_env_int(
        "P4_PERF_RUNS",
        DEFAULT_RUNS,
        MIN_RUNS,
        MAX_RUNS,
    )
    probe = QueryProbe()
    attached = False

    print(f"AUDIT_ROWS={row_count}")
    print(f"AUDIT_RUNS={runs}")

    try:
        ids = await p2_gate.bootstrap()
        await seed_committed_catalog(
            ids,
            prefix=prefix,
            row_count=row_count,
        )
        company_id = int(ids["company_id"])

        async with p2_gate.SessionApp() as app:
            await app.begin()
            await p2_gate.set_tenant(app, company_id)

            tenant_ids = await p2_gate.seed_tenant_transaction(app, ids)
            ids.update(tenant_ids)

            pricing_actor = await app.get(
                Driver,
                ids["pricing_driver_id"],
            )
            if pricing_actor is None:
                raise RuntimeError(
                    "Pricing benchmark actor is not visible."
                )

            await seed_benchmark_prices(
                app,
                company_id=company_id,
                each_uom_id=int(ids["each_uom_id"]),
                prefix=prefix,
            )

            await inspect_search_indexes(app)

            probe.attach()
            attached = True

            unfiltered, first_page = await measure_scenario(
                name="unfiltered_pricing",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(limit=50),
                runs=runs,
            )
            record(
                "unfiltered page is bounded",
                unfiltered["item_count"] == 50
                and first_page.get("has_more") is True,
                f"items={unfiltered['item_count']}",
            )

            _, name_page = await measure_scenario(
                name="name_search",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(
                    search="namehit",
                    limit=50,
                ),
                runs=runs,
            )
            record(
                "name search finds its marker",
                page_contains(name_page, "name", "NAMEHIT"),
            )

            _, family_page = await measure_scenario(
                name="family_search",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(
                    search="familyhit",
                    limit=50,
                ),
                runs=runs,
            )
            record(
                "family search finds its marker",
                page_contains(
                    family_page,
                    "family_name",
                    "FAMILYHIT",
                ),
            )

            _, sku_page = await measure_scenario(
                name="sku_search",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(
                    search="sku-hit",
                    limit=50,
                ),
                runs=runs,
            )
            record(
                "SKU search finds its marker",
                page_contains(sku_page, "sku", "SKU-HIT"),
            )

            _, barcode_page = await measure_scenario(
                name="barcode_search",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(
                    search="barcode-hit",
                    limit=50,
                ),
                runs=runs,
            )
            record(
                "barcode search finds its marker",
                page_contains(
                    barcode_page,
                    "unit_barcode",
                    "BARCODE-HIT",
                ),
            )

            filters, filters_page = await measure_scenario(
                name="common_filters",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(
                    lifecycle="ACTIVE",
                    tracking_type="LOT",
                    simple_compatible=True,
                    has_barcode=True,
                    lot_tracked=True,
                    expiry_tracked=False,
                    sort_by="name",
                    sort_dir="asc",
                    limit=50,
                ),
                runs=runs,
            )
            filter_items = filters_page.get("items")
            filters_valid = (
                isinstance(filter_items, list)
                and bool(filter_items)
                and all(
                    isinstance(item, dict)
                    and item.get("lifecycle_status") == "ACTIVE"
                    and item.get("lot_control_mode") != "NONE"
                    and item.get("expiry_control_mode") == "NONE"
                    and item.get("unit_barcode") is not None
                    and item.get("simple_compatible") is True
                    for item in filter_items
                )
            )
            record(
                "common filters stay coherent",
                filters_valid,
                f"items={filters['item_count']}",
            )

            prices, price_page = await measure_scenario(
                name="has_price_filter",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(
                    has_price=True,
                    limit=50,
                ),
                runs=runs,
            )
            price_items = price_page.get("items")
            price_valid = (
                isinstance(price_items, list)
                and bool(price_items)
                and all(
                    isinstance(item, dict)
                    and item.get("unit_price") is not None
                    for item in price_items
                )
            )
            record(
                "price filter returns priced rows",
                price_valid,
                f"items={prices['item_count']}",
            )

            next_cursor = first_page.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                raise RuntimeError(
                    "Unfiltered benchmark did not return a cursor."
                )

            continuation, second_page = await measure_scenario(
                name="page_continuation",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(
                    cursor=next_cursor,
                    limit=50,
                ),
                runs=runs,
            )
            first_ids = {
                item["id"]
                for item in first_page.get("items", [])
                if isinstance(item, dict)
                and isinstance(item.get("id"), int)
            }
            second_ids = {
                item["id"]
                for item in second_page.get("items", [])
                if isinstance(item, dict)
                and isinstance(item.get("id"), int)
            }
            record(
                "page continuation stays disjoint",
                bool(first_ids)
                and bool(second_ids)
                and first_ids.isdisjoint(second_ids),
                f"queries={continuation['query_count']}",
            )

            q10, _ = await measure_scenario(
                name="bounded_limit_10",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(limit=10),
                runs=runs,
                explain=False,
            )
            q100, _ = await measure_scenario(
                name="bounded_limit_100",
                app=app,
                actor=pricing_actor,
                probe=probe,
                kwargs=endpoint_kwargs(limit=100),
                runs=runs,
                explain=False,
            )
            delta = int(q100["query_count"]) - int(q10["query_count"])
            record(
                "query count stays bounded as page size grows 10x",
                delta <= 2,
                f"q10={q10['query_count']} "
                f"q100={q100['query_count']} delta={delta}",
            )

            await app.rollback()

        print(
            "PERFORMANCE_NOTE="
            "No latency threshold or index is assumed. "
            "Review measured plans, scans, buffers, and query counts."
        )
        print("INDEX_DECISION=PENDING_MEASURED_REVIEW")

    except Exception as exc:
        record(
            "P4 performance audit completed without unexpected exception",
            False,
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        if attached:
            probe.detach()

        cleanup_ok, cleanup_detail = await cleanup_committed_catalog(
            ids,
            prefix=prefix,
        )
        record(
            "performance audit removes benchmark data",
            cleanup_ok,
            cleanup_detail,
        )
        await p2_gate.engine_app.dispose()
        await p2_gate.engine_su.dispose()

    failures = [
        name
        for name, ok, _ in RESULTS
        if not ok
    ]
    print()
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_CHECK={failure}")

    if failures:
        print("PRODUCTS_P4_PERFORMANCE_AUDIT=FAIL")
        raise SystemExit(1)

    print("PRODUCTS_P4_PERFORMANCE_AUDIT=MEASURED")


if __name__ == "__main__":
    asyncio.run(main())
