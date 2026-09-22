from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import event


def find_backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        Path.cwd() / "wa_backend",
        here.parent.parent / "wa_backend",
        here.parent.parent,
        here.parent,
    )
    for candidate in candidates:
        if (
            (candidate / "main.py").is_file()
            and (candidate / "database.py").is_file()
        ):
            return candidate.resolve()
    raise RuntimeError("wa_backend not found.")


BACKEND_ROOT = find_backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import api.warehouse.live_stock as live_stock  # noqa: E402
from context import tenant_context  # noqa: E402
from database import engine  # noqa: E402
from scripts.gate_inventory_batches_pagination_performance import (  # noqa: E402
    BASELINE_ENDPOINT,
    add_scale_fixture,
)
from scripts.gate_inventory_batches_roundtrip import (  # noqa: E402
    _sql_label,
    prepare_session,
    resolve_driver_id,
    resolve_target,
)


@dataclass(frozen=True)
class CapturedSQL:
    statement: str
    parameters: Any


CAPTURE_TARGET: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "inventory_batches_explain_capture_target",
    default=None,
)
CAPTURED: contextvars.ContextVar[CapturedSQL | None] = contextvars.ContextVar(
    "inventory_batches_explain_captured",
    default=None,
)


def capture_batch_sql(
    conn,
    cursor,
    statement,
    parameters,
    context,
    executemany,
):
    if CAPTURE_TARGET.get() != "batch_aggregate":
        return
    if _sql_label(statement) != "batch_aggregate":
        return
    if CAPTURED.get() is None:
        CAPTURED.set(
            CapturedSQL(
                statement=statement,
                parameters=parameters,
            )
        )


async def capture_endpoint_query(
    endpoint,
    *,
    target_label: str,
    db,
    driver,
    location_id: int,
    product_variant_id: int,
    paginated: bool,
) -> CapturedSQL:
    capture_token = CAPTURE_TARGET.set(target_label)
    captured_token = CAPTURED.set(None)
    try:
        if paginated:
            await endpoint(
                product_variant_id=product_variant_id,
                location_id=location_id,
                cursor=None,
                limit=100,
                db=db,
                current_admin=driver,
            )
        else:
            await endpoint(
                product_variant_id=product_variant_id,
                location_id=location_id,
                db=db,
                current_admin=driver,
            )
        captured = CAPTURED.get()
        if captured is None:
            raise RuntimeError("Could not capture batch aggregate SQL.")
        return captured
    finally:
        CAPTURED.reset(captured_token)
        CAPTURE_TARGET.reset(capture_token)


def normalize_parameters(parameters: Any) -> tuple[Any, ...]:
    if isinstance(parameters, tuple):
        return parameters
    if isinstance(parameters, list):
        if parameters and isinstance(parameters[0], (tuple, list, dict)):
            raise RuntimeError(
                "Unexpected executemany parameters for batch aggregate."
            )
        return tuple(parameters)
    if isinstance(parameters, dict):
        raise RuntimeError(
            "Named DBAPI parameters are not supported by this inspector."
        )
    if parameters is None:
        return ()
    return (parameters,)


async def explain(
    db,
    captured: CapturedSQL,
) -> dict[str, Any]:
    connection = await db.connection()
    raw = await connection.get_raw_connection()
    driver = raw.driver_connection

    sql = (
        "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) "
        + captured.statement
    )
    row = await driver.fetchrow(
        sql,
        *normalize_parameters(captured.parameters),
    )
    if row is None:
        raise RuntimeError("EXPLAIN returned no row.")

    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("Unexpected EXPLAIN JSON payload.")

    plan = payload[0]
    if not isinstance(plan, dict):
        raise RuntimeError("Unexpected EXPLAIN plan shape.")
    return plan


def walk_nodes(node: dict[str, Any]):
    yield node
    for child in node.get("Plans", []) or []:
        if isinstance(child, dict):
            yield from walk_nodes(child)


def important_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    root = plan.get("Plan")
    if not isinstance(root, dict):
        return []

    interesting = {
        "Sort",
        "Incremental Sort",
        "Seq Scan",
        "Index Scan",
        "Index Only Scan",
        "Bitmap Heap Scan",
        "Bitmap Index Scan",
        "Nested Loop",
        "Hash Join",
        "Merge Join",
        "Aggregate",
        "GroupAggregate",
        "HashAggregate",
        "Limit",
        "Subquery Scan",
    }

    rows = []
    for node in walk_nodes(root):
        node_type = node.get("Node Type")
        if node_type not in interesting:
            continue
        rows.append(
            {
                "node": node_type,
                "relation": node.get("Relation Name"),
                "index": node.get("Index Name"),
                "actual_rows": node.get("Actual Rows"),
                "loops": node.get("Actual Loops"),
                "actual_total_ms": node.get("Actual Total Time"),
                "rows_removed_filter": node.get("Rows Removed by Filter"),
                "sort_method": node.get("Sort Method"),
                "sort_space_kb": node.get("Sort Space Used"),
                "shared_hit": node.get("Shared Hit Blocks"),
                "shared_read": node.get("Shared Read Blocks"),
            }
        )
    return rows


def print_plan(label: str, plan: dict[str, Any]) -> None:
    root = plan.get("Plan") or {}
    print(
        f"{label}_SUMMARY "
        f"planning_ms={float(plan.get('Planning Time', 0)):.3f} "
        f"execution_ms={float(plan.get('Execution Time', 0)):.3f} "
        f"root={root.get('Node Type')} "
        f"rows={root.get('Actual Rows')} "
        f"shared_hit={root.get('Shared Hit Blocks', 0)} "
        f"shared_read={root.get('Shared Read Blocks', 0)}"
    )

    for index, node in enumerate(important_nodes(plan), start=1):
        fields = " ".join(
            f"{key}={value}"
            for key, value in node.items()
            if value is not None
        )
        print(f"{label}_NODE_{index} {fields}")


async def async_main(args: argparse.Namespace) -> None:
    driver_id = await resolve_driver_id(args.company_id, args.driver_id)
    location_id, product_variant_id = await resolve_target(
        args.company_id,
        args.location_id,
        args.product_variant_id,
    )

    db, driver, tenant_token = await prepare_session(
        args.company_id,
        driver_id,
    )
    try:
        await add_scale_fixture(
            db=db,
            company_id=args.company_id,
            location_id=location_id,
            product_variant_id=product_variant_id,
            count=args.fixture_batches,
        )

        baseline_sql = await capture_endpoint_query(
            BASELINE_ENDPOINT,
            target_label="batch_aggregate",
            db=db,
            driver=driver,
            location_id=location_id,
            product_variant_id=product_variant_id,
            paginated=False,
        )
        candidate_sql = await capture_endpoint_query(
            live_stock.get_warehouse_inventory_batches,
            target_label="batch_candidates",
            db=db,
            driver=driver,
            location_id=location_id,
            product_variant_id=product_variant_id,
            paginated=True,
        )
        paginated_sql = await capture_endpoint_query(
            live_stock.get_warehouse_inventory_batches,
            target_label="batch_aggregate",
            db=db,
            driver=driver,
            location_id=location_id,
            product_variant_id=product_variant_id,
            paginated=True,
        )

        baseline_plan = await explain(db, baseline_sql)
        candidate_plan = await explain(db, candidate_sql)
        paginated_plan = await explain(db, paginated_sql)

        print(
            "TARGET "
            f"company_id={args.company_id} "
            f"location_id={location_id} "
            f"product_variant_id={product_variant_id} "
            f"fixture_batches={args.fixture_batches}"
        )
        print_plan("BASELINE", baseline_plan)
        print_plan("CANDIDATES", candidate_plan)
        print_plan("PAGINATED", paginated_plan)
        print("INVENTORY_BATCHES_EXPLAIN=PASS fixtures_rolled_back=true")
    finally:
        await db.rollback()
        tenant_context.reset(tenant_token)
        await db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture the exact stable and paginated batch aggregate SQL "
            "and compare PostgreSQL EXPLAIN ANALYZE BUFFERS plans."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--driver-id", type=int)
    parser.add_argument("--location-id", type=int)
    parser.add_argument("--product-variant-id", type=int)
    parser.add_argument("--fixture-batches", type=int, default=205)
    args = parser.parse_args()
    if args.company_id <= 0:
        parser.error("--company-id must be positive")
    if args.fixture_batches < 200:
        parser.error("--fixture-batches must be >= 200")
    return args


async def _run() -> None:
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        capture_batch_sql,
    )
    try:
        await async_main(parse_args())
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            capture_batch_sql,
        )
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
