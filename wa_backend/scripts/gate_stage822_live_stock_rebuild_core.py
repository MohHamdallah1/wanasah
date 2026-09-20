from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "service": ROOT / "domains" / "live_stock_projection" / "service.py",
    "warehouse": ROOT / "api" / "warehouse.py",
    "foundation_gate": ROOT / "scripts" / "gate_stage82_live_stock_projection_foundation.py",
}


def _read(name: str) -> str:
    return FILES[name].read_text(encoding="utf-8")


def _tree(source: str) -> ast.AST:
    return ast.parse(source)


def _function(source: str, name: str):
    for node in ast.walk(_tree(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _calls(node: ast.AST | None) -> set[str]:
    result: set[str] = set()
    if node is None:
        return result
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            result.add(func.id)
        elif isinstance(func, ast.Attribute):
            result.add(func.attr)
    return result


def main() -> None:
    checks = 0
    failures: list[str] = []
    sources = {name: _read(name) for name in FILES}

    for name, source in sources.items():
        checks += 1
        try:
            _tree(source)
        except SyntaxError as exc:
            failures.append(f"SYNTAX:{name}:{exc}")

    service = sources["service"]
    required_functions = (
        "rebuild_live_stock_warehouse",
        "rebuild_live_stock_company",
        "reconcile_live_stock_company",
        "remove_live_stock_warehouse_projection",
        "mark_live_stock_projection_degraded",
        "assert_live_stock_projection_ready",
        "_projection_snapshot_for_keys",
        "_warehouse_candidate_variant_query",
    )
    for name in required_functions:
        checks += 1
        if _function(service, name) is None:
            failures.append(f"MISSING_FUNCTION:{name}")

    checks += 1
    company_rebuild = _function(service, "rebuild_live_stock_company")
    company_calls = _calls(company_rebuild)
    if (
        "_acquire_company_projection_guard" not in company_calls
        or "_ensure_company_summary_exact" not in company_calls
    ):
        failures.append("COMPANY_REBUILD_GUARD_OR_SUMMARY_MISSING")

    checks += 1
    warehouse_rebuild = _function(service, "_rebuild_live_stock_warehouse_locked")
    warehouse_calls = _calls(warehouse_rebuild)
    if (
        "_projection_snapshot_for_keys" not in warehouse_calls
        or "refresh_live_stock_keys" not in warehouse_calls
        or "_set_warehouse_summary_exact" not in warehouse_calls
    ):
        failures.append("WAREHOUSE_REBUILD_EXACT_RECONCILIATION_MISSING")

    checks += 1
    if (
        "state=\"BUILDING\"" not in service
        or "state=\"READY\"" not in service
        or "state=\"DEGRADED\"" not in service
        or "last_rebuilt_at" not in service
        or "last_verified_at" not in service
    ):
        failures.append("PROJECTION_HEALTH_STATE_MACHINE_INCOMPLETE")

    checks += 1
    candidate_source = service[
        service.find("async def _candidate_keys_for_variants"):
        service.find("async def refresh_live_stock_variants")
    ]
    if ".in_(variant_ids)" in candidate_source:
        failures.append("UNBOUNDED_VARIANT_CANDIDATE_PARAMETERS")

    warehouse = sources["warehouse"]
    lifecycle_expectations = (
        (
            "create_warehouse_location",
            "rebuild_live_stock_warehouse",
            "WAREHOUSE_CREATE_REBUILD_MISSING",
        ),
        (
            "activate_warehouse_location",
            "rebuild_live_stock_warehouse",
            "WAREHOUSE_ACTIVATE_REBUILD_MISSING",
        ),
        (
            "deactivate_warehouse_location",
            "remove_live_stock_warehouse_projection",
            "WAREHOUSE_DEACTIVATE_PROJECTION_CLEANUP_MISSING",
        ),
    )
    for fn, callee, failure in lifecycle_expectations:
        checks += 1
        if callee not in _calls(_function(warehouse, fn)):
            failures.append(failure)

    checks += 1
    if "except LiveStockProjectionError" not in warehouse:
        failures.append("WAREHOUSE_PROJECTION_FAILURE_NOT_FAIL_CLOSED")

    foundation = sources["foundation_gate"]
    checks += 1
    if (
        "FOUNDATION_REVISION" not in foundation
        or "walk_revisions(" not in foundation
        or "FOUNDATION_REVISION_NOT_ANCESTOR" not in foundation
        or "EXPECTED_REVISION" in foundation
    ):
        failures.append("FOUNDATION_GATE_STILL_HEAD_PINNED")

    checks += 1
    if "batch_size > _MAX_PROJECTOR_KEYS" not in service:
        failures.append("REBUILD_BATCH_BOUND_MISSING")

    checks += 1
    if "dropped_inactive_warehouses" not in service:
        failures.append("INACTIVE_WAREHOUSE_RECONCILIATION_MISSING")

    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL:{failure}")
    if failures:
        raise SystemExit(1)
    print("STAGE822_LIVE_STOCK_REBUILD_CORE_GATE=PASS")


if __name__ == "__main__":
    main()
