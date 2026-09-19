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
}


def _read(name: str) -> str:
    return FILES[name].read_text(encoding="utf-8")


def _has_async_call(source: str, function_name: str, callee_name: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == function_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Name) and func.id == callee_name:
                        return True
                    if isinstance(func, ast.Attribute) and func.attr == callee_name:
                        return True
    return False


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
    if "def batch_sellability_predicate(" in sources["services"]:
        failures.append("DUPLICATE_BATCH_SELLABILITY_AUTHORITY")

    checks += 1
    if "from domains.inventory_rules import batch_sellability_predicate" not in sources["services"]:
        failures.append("SERVICES_SHARED_SELLABILITY_IMPORT_MISSING")

    checks += 1
    if not _has_async_call(
        sources["services"],
        "apply_inventory_movements_batch",
        "refresh_live_stock_from_movement_specs",
    ):
        failures.append("INVENTORY_MOVEMENT_PROJECTOR_HOOK_MISSING")

    checks += 1
    if not _has_async_call(
        sources["services"],
        "change_product_batch_disposition",
        "refresh_live_stock_variants",
    ):
        failures.append("BATCH_DISPOSITION_PROJECTOR_HOOK_MISSING")

    checks += 1
    if not _has_async_call(
        sources["catalog"],
        "_run_variant_state_command",
        "refresh_live_stock_variants",
    ):
        failures.append("LIFECYCLE_PROJECTOR_HOOK_MISSING")

    checks += 1
    if not _has_async_call(
        sources["catalog"],
        "_run_variant_state_command",
        "apply_live_stock_active_variant_delta",
    ):
        failures.append("ACTIVE_VARIANT_SUMMARY_HOOK_MISSING")

    checks += 1
    if not _has_async_call(
        sources["simple_products"],
        "create_product_structures",
        "apply_live_stock_active_variant_delta",
    ):
        failures.append("SIMPLE_PRODUCT_ACTIVE_SUMMARY_HOOK_MISSING")

    checks += 1
    if not _has_async_call(
        sources["dispatch"],
        "dispatch_route",
        "refresh_live_stock_vehicle_attribution",
    ):
        failures.append("DISPATCH_CREATE_ATTRIBUTION_HOOK_MISSING")

    checks += 1
    if not _has_async_call(
        sources["dispatch"],
        "update_route_status",
        "refresh_live_stock_vehicle_attribution",
    ):
        failures.append("DISPATCH_UPDATE_ATTRIBUTION_HOOK_MISSING")

    required_projector_functions = {
        "refresh_live_stock_keys",
        "refresh_live_stock_variants",
        "refresh_live_stock_from_movement_specs",
        "refresh_live_stock_vehicle_attribution",
        "refresh_due_live_stock_transitions",
        "apply_live_stock_active_variant_delta",
    }
    projector_tree = ast.parse(sources["projector"])
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
    movement_source = sources["projector"]
    movement_start = movement_source.find("async def refresh_live_stock_from_movement_specs")
    movement_end = movement_source.find(
        "async def refresh_live_stock_vehicle_attribution", movement_start
    )
    movement_block = movement_source[movement_start:movement_end]
    vehicle_pos = movement_block.find("acquire_live_stock_vehicle_guards")
    variant_pos = movement_block.find("_acquire_variant_guards")
    if vehicle_pos < 0 or variant_pos < 0 or vehicle_pos > variant_pos:
        failures.append("PROJECTOR_LOCK_ORDER_INVALID")

    checks += 1
    if "pg_advisory_xact_lock" not in sources["projector"]:
        failures.append("PROJECTOR_ADVISORY_LOCKS_MISSING")

    checks += 1
    if "InventoryLiveStockProjection" not in sources["projector"]:
        failures.append("PROJECTION_MODEL_NOT_USED")

    checks += 1
    if "InventoryLiveStockWarehouseSummary" not in sources["projector"]:
        failures.append("WAREHOUSE_SUMMARY_MODEL_NOT_USED")

    checks += 1
    if "InventoryLiveStockCompanySummary" not in sources["projector"]:
        failures.append("COMPANY_SUMMARY_MODEL_NOT_USED")

    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL:{failure}")
    if failures:
        raise SystemExit(1)
    print("STAGE821_LIVE_STOCK_PROJECTOR_CORE_GATE=PASS")


if __name__ == "__main__":
    main()
