from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import math
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from sqlalchemy import event, select, text


def find_backend_root() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        Path.cwd() / "wa_backend",
        here.parent.parent / "wa_backend",
        here.parent.parent,
        here.parent,
    )
    for candidate in candidates:
        if (candidate / "main.py").is_file() and (candidate / "database.py").is_file():
            return candidate.resolve()
    raise RuntimeError(
        "wa_backend not found. Run from repository root or place this file in wa_backend/scripts/."
    )


BACKEND_ROOT = find_backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from context import tenant_context  # noqa: E402
from database import AsyncSessionLocal, engine  # noqa: E402
from models import Driver  # noqa: E402
from api.warehouse import (  # noqa: E402
    get_warehouse_inventory,
    get_warehouse_inventory_alert_summary,
    get_warehouse_inventory_summary,
)

CAPTURE: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "live_stock_explain_capture",
    default=None,
)


def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    bucket = CAPTURE.get()
    if bucket is not None:
        context._live_stock_explain_started = time.perf_counter()


def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    bucket = CAPTURE.get()
    started = getattr(context, "_live_stock_explain_started", None)
    if bucket is None or started is None:
        return
    sql = " ".join(str(statement).split())
    bucket.append(
        {
            "duration_ms": (time.perf_counter() - started) * 1000,
            "statement": str(statement),
            "statement_one_line": sql,
            "parameters": parameters,
            "executemany": bool(executemany),
        }
    )


def clean_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    return repr(value)


def walk_plan(node: dict[str, Any], *, findings: list[dict[str, Any]]) -> None:
    actual_rows = float(node.get("Actual Rows", 0) or 0)
    loops = float(node.get("Actual Loops", 0) or 0)
    plan_rows = float(node.get("Plan Rows", 0) or 0)
    node_type = str(node.get("Node Type", ""))
    relation = node.get("Relation Name")
    sort_method = node.get("Sort Method")
    temp_read = node.get("Temp Read Blocks", 0) or 0
    temp_written = node.get("Temp Written Blocks", 0) or 0

    flags: list[str] = []
    if node_type == "Seq Scan":
        flags.append("SEQ_SCAN")
    if node_type == "Nested Loop" and loops * max(actual_rows, 1) > 10000:
        flags.append("HEAVY_NESTED_LOOP")
    if plan_rows > 0 and actual_rows > 0:
        ratio = max(actual_rows / plan_rows, plan_rows / actual_rows)
        if ratio >= 10:
            flags.append("CARDINALITY_MISESTIMATE")
    if sort_method and "external" in str(sort_method).lower():
        flags.append("DISK_SORT")
    if temp_read or temp_written:
        flags.append("TEMP_IO")

    if flags:
        findings.append(
            {
                "node_type": node_type,
                "relation": relation,
                "flags": flags,
                "actual_rows": actual_rows,
                "actual_loops": loops,
                "plan_rows": plan_rows,
                "actual_total_time_ms": node.get("Actual Total Time"),
                "shared_hit_blocks": node.get("Shared Hit Blocks"),
                "shared_read_blocks": node.get("Shared Read Blocks"),
                "temp_read_blocks": temp_read,
                "temp_written_blocks": temp_written,
                "sort_method": sort_method,
            }
        )

    for child in node.get("Plans", []) or []:
        walk_plan(child, findings=findings)


async def load_driver(db, company_id: int, driver_id: int) -> Driver:
    driver = await db.scalar(
        select(Driver).where(
            Driver.id == driver_id,
            Driver.company_id == company_id,
            Driver.is_active.is_(True),
        )
    )
    if driver is None:
        raise RuntimeError("Active benchmark driver not found.")
    return driver


async def run_scenario(
    *,
    db,
    driver: Driver,
    scenario: str,
    location_id: int,
    limit: int,
    search: str,
    cursor: str | None,
) -> dict[str, Any]:
    if scenario == "live":
        return await get_warehouse_inventory(
            location_id=location_id,
            cursor=cursor,
            limit=limit,
            search=None,
            only_alerts=False,
            db=db,
            current_admin=driver,
        )
    if scenario == "alerts":
        return await get_warehouse_inventory_alert_summary(
            location_id=location_id,
            db=db,
            current_admin=driver,
        )
    if scenario == "summary":
        return await get_warehouse_inventory_summary(
            location_id=location_id,
            db=db,
            current_admin=driver,
        )
    if scenario == "only-alerts":
        return await get_warehouse_inventory(
            location_id=location_id,
            cursor=cursor,
            limit=limit,
            search=None,
            only_alerts=True,
            db=db,
            current_admin=driver,
        )
    if scenario == "search":
        return await get_warehouse_inventory(
            location_id=location_id,
            cursor=cursor,
            limit=limit,
            search=search,
            only_alerts=False,
            db=db,
            current_admin=driver,
        )
    raise RuntimeError(f"Unsupported scenario: {scenario}")


async def explain_statement(db, statement: str, parameters: Any) -> dict[str, Any]:
    stripped = statement.lstrip().upper()
    if not stripped.startswith(("SELECT", "WITH")):
        return {"skipped": "NON_SELECT"}

    explain_sql = (
        "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) "
        + statement
    )
    conn = await db.connection()
    started = time.perf_counter()
    result = await conn.exec_driver_sql(explain_sql, parameters)
    elapsed_ms = (time.perf_counter() - started) * 1000
    row = result.scalar_one()
    plan_doc = row if isinstance(row, list) else json.loads(row)
    top = plan_doc[0]
    findings: list[dict[str, Any]] = []
    walk_plan(top["Plan"], findings=findings)
    return {
        "explain_wall_ms": elapsed_ms,
        "planning_time_ms": top.get("Planning Time"),
        "execution_time_ms": top.get("Execution Time"),
        "settings": top.get("Settings", {}),
        "findings": findings,
        "plan": top,
    }


async def async_main(args: argparse.Namespace) -> None:
    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    event.listen(engine.sync_engine, "after_cursor_execute", after_cursor_execute)

    tenant_token = tenant_context.set(args.company_id)
    report: dict[str, Any] = {
        "company_id": args.company_id,
        "driver_id": args.driver_id,
        "location_id": args.location_id,
        "scenario": args.scenario,
        "limit": args.limit,
        "search": args.search,
    }

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant', :c, false)"),
                {"c": str(args.company_id)},
            )
            driver = await load_driver(db, args.company_id, args.driver_id)

            server_info = {}
            for key in (
                "server_version",
                "shared_buffers",
                "work_mem",
                "effective_cache_size",
                "random_page_cost",
                "seq_page_cost",
                "jit",
                "track_io_timing",
            ):
                try:
                    server_info[key] = str(
                        (await db.execute(text(f"SHOW {key}"))).scalar_one()
                    )
                except Exception as exc:
                    server_info[key] = f"UNAVAILABLE:{type(exc).__name__}"
            report["postgres"] = server_info

            cursor = None
            if args.cursor_page == 2:
                first = await get_warehouse_inventory(
                    location_id=args.location_id,
                    cursor=None,
                    limit=args.limit,
                    search=None if args.scenario != "search" else args.search,
                    only_alerts=args.scenario == "only-alerts",
                    db=db,
                    current_admin=driver,
                )
                cursor = first.get("next_cursor")
                if not cursor:
                    raise RuntimeError("No second-page cursor available.")

            bucket: list[dict[str, Any]] = []
            capture_token = CAPTURE.set(bucket)
            try:
                started = time.perf_counter()
                payload = await run_scenario(
                    db=db,
                    driver=driver,
                    scenario=args.scenario,
                    location_id=args.location_id,
                    limit=args.limit,
                    search=args.search,
                    cursor=cursor,
                )
                endpoint_ms = (time.perf_counter() - started) * 1000
            finally:
                CAPTURE.reset(capture_token)

            statements = [
                item
                for item in bucket
                if str(item["statement"]).lstrip().upper().startswith(("SELECT", "WITH"))
                and "SET_CONFIG" not in str(item["statement"]).upper()
            ]
            statements.sort(key=lambda item: item["duration_ms"], reverse=True)

            report["endpoint_ms"] = endpoint_ms
            report["payload_items"] = (
                len(payload.get("items", []))
                if isinstance(payload, dict) and isinstance(payload.get("items"), list)
                else None
            )
            report["sql_statement_count"] = len(statements)
            report["captured_sql"] = [
                {
                    "rank": i + 1,
                    "duration_ms": row["duration_ms"],
                    "statement": row["statement_one_line"],
                    "parameters": clean_json(row["parameters"]),
                }
                for i, row in enumerate(statements)
            ]

            explanations = []
            for rank, row in enumerate(statements[: args.top], 1):
                try:
                    explained = await explain_statement(
                        db,
                        str(row["statement"]),
                        row["parameters"],
                    )
                    explanations.append(
                        {
                            "rank": rank,
                            "original_duration_ms": row["duration_ms"],
                            "statement": row["statement_one_line"],
                            "parameters": clean_json(row["parameters"]),
                            **explained,
                        }
                    )
                except Exception as exc:
                    await db.rollback()
                    await db.execute(
                        text("SELECT set_config('app.current_tenant', :c, false)"),
                        {"c": str(args.company_id)},
                    )
                    explanations.append(
                        {
                            "rank": rank,
                            "original_duration_ms": row["duration_ms"],
                            "statement": row["statement_one_line"],
                            "parameters": clean_json(row["parameters"]),
                            "plan_error": f"{type(exc).__name__}: {exc}",
                        }
                    )

            report["explanations"] = explanations

            pgss = {"available": False}
            try:
                exists = await db.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_stat_statements')"
                    )
                )
                pgss["available"] = bool(exists)
                if exists:
                    pgss["note"] = (
                        "pg_stat_statements is installed; use it for long-run production-style "
                        "query frequency/latency tracking."
                    )
            except Exception as exc:
                pgss["error"] = f"{type(exc).__name__}: {exc}"
            report["pg_stat_statements"] = pgss

    finally:
        tenant_context.reset(tenant_token)
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
        event.remove(engine.sync_engine, "after_cursor_execute", after_cursor_execute)

    reports_dir = BACKEND_ROOT / "perf_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"live_stock_explain_{args.scenario}_"
        f"limit{args.limit}_page{args.cursor_page}.json"
    )
    report_path = reports_dir / filename
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"ENDPOINT_MS={report['endpoint_ms']:.1f}")
    print(f"SQL_STATEMENTS={report['sql_statement_count']}")
    print(f"REPORT={report_path}")
    for item in report["explanations"]:
        if "plan_error" in item:
            print(
                f"RANK={item['rank']} ORIGINAL_MS={item['original_duration_ms']:.1f} "
                f"EXPLAIN=ERROR {item['plan_error']}"
            )
            continue
        print(
            f"RANK={item['rank']} ORIGINAL_MS={item['original_duration_ms']:.1f} "
            f"PLAN_MS={float(item.get('execution_time_ms') or 0):.1f} "
            f"FINDINGS={len(item.get('findings') or [])}"
        )
        for finding in (item.get("findings") or [])[:8]:
            print(
                "  "
                + ",".join(finding["flags"])
                + f" node={finding['node_type']}"
                + (
                    f" relation={finding['relation']}"
                    if finding.get("relation")
                    else ""
                )
                + f" rows={finding['actual_rows']:.0f}"
                + f" loops={finding['actual_loops']:.0f}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deep Live Stock PostgreSQL profiler using EXPLAIN ANALYZE + BUFFERS "
            "on the exact slow statements emitted by the endpoint."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--driver-id", type=int, required=True)
    parser.add_argument("--location-id", type=int, required=True)
    parser.add_argument(
        "--scenario",
        choices=("live", "alerts", "summary", "only-alerts", "search"),
        default="live",
    )
    parser.add_argument("--limit", type=int, choices=(50, 100, 200), default=50)
    parser.add_argument("--cursor-page", type=int, choices=(1, 2), default=1)
    parser.add_argument("--search", default="PERF Live Product 0001")
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.top <= 8:
        parser.error("--top must be between 1 and 8")
    if args.scenario in {"alerts", "summary"} and args.cursor_page != 1:
        parser.error("summary scenarios have no cursor pages")
    return args


def main() -> None:
    asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    main()
