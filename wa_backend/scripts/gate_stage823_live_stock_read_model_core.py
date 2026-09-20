from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "api" / "warehouse.py"
SCALE_GATE = ROOT / "scripts" / "gate_live_stock_scale.py"


def function_block(source: str, name: str) -> str:
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            end = getattr(node, "end_lineno", None)
            if end is None:
                raise RuntimeError(f"Cannot resolve function end: {name}")
            return "\n".join(lines[node.lineno - 1:end])
    raise RuntimeError(f"Missing function: {name}")


def main() -> None:
    source = WAREHOUSE.read_text(encoding="utf-8")
    failures: list[str] = []
    checks = 0

    checks += 1
    try:
        ast.parse(source)
    except SyntaxError as exc:
        failures.append(f"WAREHOUSE_SYNTAX:{exc}")

    required_helpers = (
        "_require_live_stock_read_model_ready",
        "_readable_vehicle_locations_subquery",
        "_latest_readable_vehicle_sources_subquery",
        "_has_company_wide_inventory_read",
        "_build_visible_inventory_stmt",
        "_build_inventory_alert_variants_stmt",
    )
    for helper in required_helpers:
        checks += 1
        try:
            function_block(source, helper)
        except RuntimeError:
            failures.append(f"MISSING_HELPER:{helper}")

    visible = function_block(source, "_build_visible_inventory_stmt")
    checks += 1
    if (
        "InventoryLiveStockProjection" not in visible
        or "InventoryLiveStockProjection.has_warehouse_presence"
        not in visible
        or "_readable_vehicle_locations_subquery" not in visible
        or "InventoryBalance" not in visible
        or "company_wide_inventory_read" not in visible
        or "InventoryLiveStockProjection.has_vehicle_presence"
        not in visible
    ):
        failures.append("HYBRID_VISIBILITY_AUTHORITY_INCOMPLETE")

    checks += 1
    company_wide_helper = function_block(
        source,
        "_has_company_wide_inventory_read",
    )
    if (
        'access.allows("inventory.read")' not in company_wide_helper
        or "actor.is_admin" not in company_wide_helper
    ):
        failures.append("COMPANY_WIDE_PERMISSION_HELPER_INCOMPLETE")

    alert_builder = function_block(
        source,
        "_build_inventory_alert_variants_stmt",
    )
    checks += 1
    if (
        "InventoryLiveStockProjection.is_low_stock.is_(True)"
        not in alert_builder
        or "InventoryBalance" in alert_builder
        or "InventoryStockPolicy" in alert_builder
        or "ProductBatch" in alert_builder
        or "batch_sellability_predicate" in alert_builder
    ):
        failures.append("ALERT_READ_NOT_PROJECTION_BACKED")

    summary = function_block(source, "get_warehouse_inventory_summary")
    checks += 1
    required_summary = (
        "_require_live_stock_read_model_ready",
        "InventoryLiveStockCompanySummary.active_variant_count",
        "InventoryLiveStockWarehouseSummary.alert_count",
        "nonactive_visible_count",
        "_has_company_wide_inventory_read",
        "restricted_nonactive_visible",
        "_readable_vehicle_locations_subquery",
    )
    missing_summary = [
        token for token in required_summary if token not in summary
    ]
    if missing_summary:
        failures.append(
            "SUMMARY_READ_MODEL_INCOMPLETE:"
            + ",".join(missing_summary)
        )

    company_wide_helper = function_block(
        source,
        "_has_company_wide_inventory_read",
    )
    checks += 1
    if (
        'access.allows("inventory.read")' not in company_wide_helper
        or "actor.is_admin" not in company_wide_helper
    ):
        failures.append(
            "COMPANY_WIDE_INVENTORY_PERMISSION_HELPER_INCOMPLETE"
        )

    alert_summary = function_block(
        source,
        "get_warehouse_inventory_alert_summary",
    )
    checks += 1
    if (
        "_require_live_stock_read_model_ready" not in alert_summary
        or "InventoryLiveStockWarehouseSummary.alert_count"
        not in alert_summary
        or "_build_inventory_alert_variants_stmt" in alert_summary
    ):
        failures.append("ALERT_SUMMARY_NOT_O1_PROJECTION_READ")

    cursor = function_block(source, "get_warehouse_inventory")
    checks += 1
    required_cursor = (
        "_require_live_stock_read_model_ready",
        "InventoryLiveStockProjection",
        "_readable_vehicle_locations_subquery",
        "vehicles.get",
    )
    missing_cursor = [
        token for token in required_cursor if token not in cursor
    ]
    if missing_cursor:
        failures.append(
            "CURSOR_READ_MODEL_INCOMPLETE:"
            + ",".join(missing_cursor)
        )

    checks += 1
    forbidden_cursor = (
        "warehouse_inventory_stmt",
        "batch_is_sellable",
        "policy_subq",
        "InventoryStockPolicy.minimum_quantity",
    )
    offenders = [token for token in forbidden_cursor if token in cursor]
    if offenders:
        failures.append(
            "CURSOR_STILL_REAGGREGATES_WAREHOUSE:"
            + ",".join(offenders)
        )

    checks += 1
    if (
        "company_wide_inventory_read" not in cursor
        or "projection.vehicle_packs" not in cursor
        or "if not company_wide_inventory_read" not in cursor
        or "vehicles.get" not in cursor
    ):
        failures.append("VEHICLE_PERMISSION_FAST_PATH_NOT_GUARDED")

    checks += 1
    readiness = function_block(
        source,
        "_require_live_stock_read_model_ready",
    )
    if (
        "assert_live_stock_projection_ready" not in readiness
        or "status_code=503" not in readiness
        or "LIVE_STOCK_PROJECTION_NOT_READY" not in readiness
    ):
        failures.append("READINESS_FAIL_CLOSED_CONTRACT_MISSING")

    checks += 1
    if source.count("_require_live_stock_read_model_ready(") < 4:
        failures.append("READINESS_GUARD_NOT_APPLIED_TO_ALL_LIVE_STOCK_READS")

    checks += 1
    scale_source = SCALE_GATE.read_text(encoding="utf-8")
    if (
        "GlobalCountSession" not in scale_source
        or "DATABASE_URL_MIGRATION" not in scale_source
        or "global_count_engine" not in scale_source
    ):
        failures.append("GLOBAL_SCALE_COUNTS_NOT_RLS_INDEPENDENT")

    checks += 1
    if (
        "HTTP_BENCH_POOL_SIZE = 16" not in scale_source
        or "HTTP_BENCH_MAX_OVERFLOW = 4" not in scale_source
        or "HTTP_BENCH_DB_CAP != 20" not in scale_source
        or "http_benchmark_get_db" not in scale_source
        or "app.dependency_overrides" not in scale_source
        or '"pool_wait"' not in scale_source
    ):
        failures.append("HTTP_SCALE_GATE_NOT_MODELING_AGGREGATE_DB_BUDGET")

    checks += 1
    if (
        'parser.add_argument("--concurrency", type=int, default=20)'
        not in scale_source
        or 'parser.add_argument("--requests", type=int, default=100)'
        not in scale_source
        or 'parser.add_argument("--max-http-p95", type=float, default=500.0)'
        not in scale_source
    ):
        failures.append("HTTP_SCALE_GATE_THRESHOLDS_WEAKENED")

    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL:{failure}")
    if failures:
        raise SystemExit(1)
    print("STAGE823_LIVE_STOCK_READ_MODEL_CORE_GATE=PASS")


if __name__ == "__main__":
    main()
