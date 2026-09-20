from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "api" / "warehouse.py"
DEPENDENCIES = ROOT / "api" / "dependencies.py"
PROJECTION_SERVICE = ROOT / "domains" / "live_stock_projection" / "service.py"
DATABASE = ROOT / "database.py"
MAIN = ROOT / "main.py"
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
        "_require_live_stock_warehouse_read",
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
        "_require_live_stock_warehouse_read",
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

    warehouse_read_helper = function_block(
        source,
        "_require_live_stock_warehouse_read",
    )
    checks += 1
    if (
        'access.allows(' not in warehouse_read_helper
        or '"inventory.read"' not in warehouse_read_helper
        or "actor.is_admin" not in warehouse_read_helper
        or 'status_code=404' not in warehouse_read_helper
        or 'status_code=403' not in warehouse_read_helper
    ):
        failures.append(
            "WAREHOUSE_READ_AUTHORITY_HELPER_INCOMPLETE"
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
    dependency_source = DEPENDENCIES.read_text(encoding="utf-8")
    try:
        ast.parse(dependency_source)
    except SyntaxError as exc:
        failures.append(f"DEPENDENCIES_SYNTAX:{exc}")

    checks += 1
    auth_block = function_block(
        dependency_source,
        "get_current_driver",
    )
    if (
        "blacklisted_exists" not in auth_block
        or 'blacklisted_exists.label("is_blacklisted")' not in auth_block
        or "select(Driver," not in auth_block
        or "stmt_blacklisted" in auth_block
    ):
        failures.append("AUTH_BLACKLIST_DRIVER_READ_NOT_COLLAPSED")

    checks += 1
    if "set_config('app.current_tenant'" not in auth_block:
        failures.append("AUTH_TENANT_RLS_GUARD_MISSING")

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

    checks += 1
    for fn_name in (
        "get_warehouse_inventory_alert_summary",
        "get_warehouse_inventory_summary",
        "get_warehouse_inventory",
    ):
        block = function_block(source, fn_name)
        if 'access.require("inventory.read"' in block or "access.require('inventory.read'" in block:
            failures.append(
                f"DUPLICATE_LIVE_STOCK_ACCESS_REQUIRE:{fn_name}"
            )

    checks += 1
    cursor = function_block(source, "get_warehouse_inventory")
    if (
        "latest_purchase_page" not in cursor
        or "latest_purchase_by_variant" in cursor
    ):
        failures.append("LATEST_PURCHASE_NOT_COLLAPSED_INTO_DETAILS")

    checks += 1
    projection_source = PROJECTION_SERVICE.read_text(encoding="utf-8")
    readiness_start = projection_source.find(
        "async def assert_live_stock_projection_ready"
    )
    readiness_block = projection_source[readiness_start:]
    if (
        readiness_start < 0
        or 'due_transition_exists.label("has_due_transition")'
        not in readiness_block
        or readiness_block.count("await db.execute(") != 1
        or "await db.scalar(" in readiness_block
    ):
        failures.append("READINESS_NOT_COLLAPSED_TO_ONE_SQL_ROUND_TRIP")

    checks += 1
    database_source = DATABASE.read_text(encoding="utf-8")
    main_source = MAIN.read_text(encoding="utf-8")
    if (
        "async def warm_async_engine_pool(" not in database_source
        or "async def warm_database_pool(" not in database_source
        or "await warm_database_pool()" not in main_source
    ):
        failures.append("API_DB_POOL_PREWARM_MISSING")

    checks += 1
    if (
        "warm_async_engine_pool(" not in scale_source
        or "HTTP_POOL_PREWARM=" not in scale_source
        or "connections=HTTP_BENCH_POOL_SIZE" not in scale_source
    ):
        failures.append("HTTP_BENCHMARK_STEADY_POOL_PREWARM_MISSING")

    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL:{failure}")
    if failures:
        raise SystemExit(1)
    print("STAGE823_LIVE_STOCK_READ_MODEL_CORE_GATE=PASS")


if __name__ == "__main__":
    main()
