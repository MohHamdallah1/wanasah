from __future__ import annotations

import ast
from pathlib import Path


def _backend_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parents[1], here.parents[2]):
        if (candidate / "services.py").is_file() and (candidate / "models.py").is_file():
            return candidate
    raise RuntimeError("wa_backend not found.")


ROOT = _backend_root()
FILES = {
    "services": ROOT / "services.py",
    "catalog": ROOT / "api" / "catalog.py",
    "dispatch": ROOT / "api" / "dispatch.py",
    "simple_products": ROOT / "domains" / "simple_products" / "service.py",
    "rules": ROOT / "domains" / "inventory_rules.py",
    "projector": ROOT / "domains" / "live_stock_projection" / "service.py",
    "cost_guard_migration": (
        ROOT
        / "alembic"
        / "versions"
        / "c7d4a91e6f32_cost_history_guard_exactness.py"
    ),
}


def _read(name: str) -> str:
    return FILES[name].read_text(encoding="utf-8")


def _tree(source: str) -> ast.AST:
    return ast.parse(source)


def _function_node(source: str, function_name: str):
    for node in ast.walk(_tree(source)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == function_name:
            return node
    return None


def _call_names(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    names: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.append(func.id)
        elif isinstance(func, ast.Attribute):
            names.append(func.attr)
    return names


def _caught_exception_names(node: ast.AST | None) -> set[str]:
    result: set[str] = set()
    if node is None:
        return result
    for child in ast.walk(node):
        if not isinstance(child, ast.ExceptHandler) or child.type is None:
            continue
        targets = child.type.elts if isinstance(child.type, ast.Tuple) else [child.type]
        for target in targets:
            if isinstance(target, ast.Name):
                result.add(target.id)
            elif isinstance(target, ast.Attribute):
                result.add(target.attr)
    return result


def _has_call(source: str, function_name: str, callee_name: str) -> bool:
    return callee_name in _call_names(_function_node(source, function_name))


def main() -> None:
    checks = 0
    failures: list[str] = []

    sources = {name: _read(name) for name in FILES}

    for name, source in sources.items():
        checks += 1
        try:
            ast.parse(source)
        except SyntaxError as exc:
            failures.append(f"SYNTAX:{name}:{exc.lineno}:{exc.msg}")

    checks += 1
    migration = sources["cost_guard_migration"]
    if (
        'revision = "c7d4a91e6f32"' not in migration
        or 'down_revision = "b3e91c7a4d20"' not in migration
        or "FOR EACH ROW" not in migration
        or "BEFORE TRUNCATE" not in migration
        or "FOR EACH STATEMENT" not in migration
    ):
        failures.append("COST_HISTORY_GUARD_EXACTNESS_MIGRATION_INVALID")

    checks += 1
    if "def batch_sellability_predicate(" in sources["services"]:
        failures.append("DUPLICATE_BATCH_SELLABILITY_AUTHORITY")

    checks += 1
    if "from domains.inventory_rules import batch_sellability_predicate" not in sources["services"]:
        failures.append("SERVICES_SHARED_SELLABILITY_IMPORT_MISSING")

    expected_hooks = (
        ("services", "apply_inventory_movements_batch", "refresh_live_stock_from_movement_specs", "INVENTORY_MOVEMENT_PROJECTOR_HOOK_MISSING"),
        ("services", "change_product_batch_disposition", "refresh_live_stock_variants", "BATCH_DISPOSITION_PROJECTOR_HOOK_MISSING"),
        ("catalog", "_run_variant_state_command", "refresh_live_stock_variants", "LIFECYCLE_PROJECTOR_HOOK_MISSING"),
        ("catalog", "_run_variant_state_command", "apply_live_stock_active_variant_delta", "ACTIVE_VARIANT_SUMMARY_HOOK_MISSING"),
        ("simple_products", "create_product_structures", "apply_live_stock_active_variant_delta", "SIMPLE_PRODUCT_ACTIVE_SUMMARY_HOOK_MISSING"),
        ("dispatch", "dispatch_route", "refresh_live_stock_vehicle_attribution", "DISPATCH_CREATE_ATTRIBUTION_HOOK_MISSING"),
        ("dispatch", "update_route_status", "refresh_live_stock_vehicle_attribution", "DISPATCH_UPDATE_ATTRIBUTION_HOOK_MISSING"),
    )
    for source_name, function_name, callee_name, failure in expected_hooks:
        checks += 1
        if not _has_call(sources[source_name], function_name, callee_name):
            failures.append(failure)

    checks += 1
    lifecycle_catches = _caught_exception_names(
        _function_node(sources["catalog"], "_run_variant_state_command")
    )
    if "LiveStockProjectionError" not in lifecycle_catches:
        failures.append("LIFECYCLE_PROJECTOR_ROLLBACK_HANDLER_MISSING")

    checks += 1
    create_product_calls = set(
        _call_names(_function_node(sources["catalog"], "create_product"))
    )
    if {
        "refresh_live_stock_variants",
        "apply_live_stock_active_variant_delta",
    } & create_product_calls:
        failures.append("UNRELATED_CREATE_PRODUCT_PROJECTOR_HOOK")

    checks += 1
    create_product_catches = _caught_exception_names(
        _function_node(sources["catalog"], "create_product")
    )
    if "LiveStockProjectionError" in create_product_catches:
        failures.append("MISPLACED_CREATE_PRODUCT_PROJECTOR_HANDLER")

    for function_name, failure in (
        ("dispatch_route", "DISPATCH_CREATE_EARLY_VEHICLE_GUARD"),
        ("update_route_status", "DISPATCH_UPDATE_EARLY_VEHICLE_GUARD"),
    ):
        checks += 1
        if _has_call(
            sources["dispatch"],
            function_name,
            "acquire_live_stock_vehicle_guards",
        ):
            failures.append(failure)

    checks += 1
    services_tree = _tree(sources["services"])
    if "LiveStockProjectionError" not in {
        node.id for node in ast.walk(services_tree) if isinstance(node, ast.Name)
    }:
        failures.append("SERVICES_PROJECTOR_FAIL_CLOSED_MISSING")

    checks += 1
    simple_tree = _tree(sources["simple_products"])
    if "LiveStockProjectionError" not in {
        node.id for node in ast.walk(simple_tree) if isinstance(node, ast.Name)
    }:
        failures.append("SIMPLE_PRODUCT_PROJECTOR_FAIL_CLOSED_MISSING")

    required_projector_functions = {
        "refresh_live_stock_keys",
        "refresh_live_stock_variants",
        "refresh_live_stock_from_movement_specs",
        "refresh_live_stock_vehicle_attribution",
        "refresh_due_live_stock_transitions",
        "apply_live_stock_active_variant_delta",
    }
    projector_tree = _tree(sources["projector"])
    projector_functions = {
        node.name
        for node in ast.walk(projector_tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }
    checks += 1
    missing = sorted(required_projector_functions - projector_functions)
    if missing:
        failures.append(f"PROJECTOR_FUNCTIONS_MISSING:{missing}")

    checks += 1
    projector_source = sources["projector"]
    if (
        "_COARSE_GUARD_THRESHOLD = 256" not in projector_source
        or "async def _acquire_company_projection_guard(" not in projector_source
        or 'f"live-stock-company:{company_id}"' not in projector_source
        or "_force_coarse_guard" not in projector_source
    ):
        failures.append("HIERARCHICAL_PROJECTOR_GUARDS_MISSING")

    checks += 1
    if (
        "def _projection_key_scope(" not in projector_source
        or "func.unnest(" not in projector_source
        or "ARRAY(Integer)" not in projector_source
        or "def _array_membership(" not in projector_source
        or "any_(" not in projector_source
    ):
        failures.append("BOUNDED_PROJECTOR_SQL_PARAMETERIZATION_MISSING")

    checks += 1
    forbidden_bulk_parameter_patterns = (
        "tuple_(",
        ".in_(active_keys)",
        ".in_(normalized_keys)",
        ".in_(variant_ids)",
        ".in_(warehouse_ids)",
    )
    found_forbidden = [
        pattern
        for pattern in forbidden_bulk_parameter_patterns
        if pattern in projector_source
    ]
    if found_forbidden:
        failures.append(
            "UNBOUNDED_PROJECTOR_SQL_PARAMETERS:"
            + ",".join(found_forbidden)
        )

    checks += 1
    refresh_keys_source = projector_source[
        projector_source.find("async def refresh_live_stock_keys"):
        projector_source.find("async def _candidate_keys_for_variants")
    ]
    if "_acquire_variant_guards(" in refresh_keys_source:
        failures.append("REDUNDANT_HOT_PATH_VARIANT_GUARD_PRESENT")
    if "_acquire_projection_key_guards(" not in refresh_keys_source:
        failures.append("PROJECTION_KEY_GUARD_MISSING")

    checks += 1
    movement_source = sources["projector"]
    movement_start = movement_source.find(
        "async def refresh_live_stock_from_movement_specs"
    )
    movement_end = movement_source.find(
        "async def refresh_live_stock_vehicle_attribution", movement_start
    )
    movement_block = movement_source[movement_start:movement_end]
    if "_acquire_variant_guards(" in movement_block:
        failures.append("REDUNDANT_MOVEMENT_VARIANT_GUARD_PRESENT")
    if "acquire_live_stock_vehicle_guards(" not in movement_block:
        failures.append("MOVEMENT_VEHICLE_GUARD_MISSING")

    checks += 1
    attribution_source = movement_source[
        movement_source.find("async def refresh_live_stock_vehicle_attribution"):
        movement_source.find("async def apply_live_stock_active_variant_delta")
    ]
    if "_acquire_variant_guards(" in attribution_source:
        failures.append("REDUNDANT_ATTRIBUTION_VARIANT_GUARD_PRESENT")
    if "acquire_live_stock_vehicle_guards(" not in attribution_source:
        failures.append("ATTRIBUTION_VEHICLE_GUARD_MISSING")

    checks += 1
    variant_refresh_source = projector_source[
        projector_source.find("async def refresh_live_stock_variants"):
        projector_source.find("async def refresh_live_stock_from_movement_specs")
    ]
    if "_acquire_variant_guards(" not in variant_refresh_source:
        failures.append("VARIANT_DISCOVERY_GUARD_MISSING")

    checks += 1
    if (
        'summary_warehouse_id' not in refresh_keys_source
        or "InventoryLiveStockProjection," not in refresh_keys_source
        or "missing_summary_warehouses" not in refresh_keys_source
    ):
        failures.append("HOT_PATH_READ_COLLAPSE_MISSING")

    checks += 1
    if "pg_advisory_xact_lock" not in sources["projector"]:
        failures.append("PROJECTOR_ADVISORY_LOCKS_MISSING")

    for model_name, failure in (
        ("InventoryLiveStockProjection", "PROJECTION_MODEL_NOT_USED"),
        ("InventoryLiveStockWarehouseSummary", "WAREHOUSE_SUMMARY_MODEL_NOT_USED"),
        ("InventoryLiveStockCompanySummary", "COMPANY_SUMMARY_MODEL_NOT_USED"),
    ):
        checks += 1
        if model_name not in sources["projector"]:
            failures.append(failure)

    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL:{failure}")
    if failures:
        raise SystemExit(1)
    print("STAGE821_LIVE_STOCK_PROJECTOR_CORE_GATE=PASS")


if __name__ == "__main__":
    main()
