from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "service": ROOT / "domains" / "live_stock_projection" / "service.py",
    "warehouse": ROOT / "api" / "warehouse" / "locations.py",
    "foundation_gate": ROOT / "scripts" / "gate_stage82_live_stock_projection_foundation.py",
    "worker_app": ROOT / "workers" / "app.py",
    "worker_maintenance": ROOT / "workers" / "tasks" / "maintenance.py",
    "worker_live_stock": ROOT / "workers" / "tasks" / "live_stock.py",
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
        "refresh_live_stock_policy_changes",
        "refresh_due_live_stock_transitions",
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

    checks += 1
    readiness_node = _function(
        service,
        "assert_live_stock_projection_ready",
    )
    readiness_calls = _calls(readiness_node)
    readiness_source = service[
        service.find("async def assert_live_stock_projection_ready"):
    ]
    if (
        readiness_node is None
        or "select" not in readiness_calls
        or "exists" not in readiness_calls
        or "next_transition_date.is_not(None)" not in readiness_source
        or "has_due_transition" not in readiness_source
        or "must be refreshed" not in readiness_source
    ):
        failures.append("STALE_TRANSITION_READINESS_GUARD_MISSING")

    checks += 1
    policy_hook = _function(service, "refresh_live_stock_policy_changes")
    if "refresh_live_stock_keys" not in _calls(policy_hook):
        failures.append("POLICY_CHANGE_PROJECTOR_HOOK_INCOMPLETE")

    checks += 1
    unhooked_policy_writers: list[str] = []
    excluded_parts = {
        "scripts",
        "alembic",
        "perf_reports",
        "__pycache__",
    }
    writer_tokens = (
        "db.add(InventoryStockPolicy",
        "update(InventoryStockPolicy",
        "delete(InventoryStockPolicy",
        "pg_insert(InventoryStockPolicy",
        "INSERT INTO inventory_stock_policies",
        "UPDATE inventory_stock_policies",
        "DELETE FROM inventory_stock_policies",
    )
    for path in ROOT.rglob("*.py"):
        if any(part in excluded_parts for part in path.parts):
            continue
        if path == FILES["service"]:
            continue
        source = path.read_text(encoding="utf-8")
        if not any(token in source for token in writer_tokens):
            continue
        if "refresh_live_stock_policy_changes" not in source:
            unhooked_policy_writers.append(
                str(path.relative_to(ROOT)).replace("\\", "/")
            )
    if unhooked_policy_writers:
        failures.append(
            "UNHOOKED_INVENTORY_STOCK_POLICY_WRITERS:"
            + ",".join(sorted(unhooked_policy_writers))
        )

    checks += 1
    worker_app = sources["worker_app"]
    if '"workers.tasks.live_stock"' not in worker_app:
        failures.append("LIVE_STOCK_WORKER_NOT_REGISTERED")

    checks += 1
    worker_source = sources["worker_live_stock"]
    required_worker_tokens = (
        '@app.periodic(cron="2,17,32,47 * * * *")',
        "COMPANY_SCAN_PAGE = 1000",
        "TRANSITION_BATCH = 5000",
        "MAX_BATCHES_PER_RUN = 20",
        "Company.id > after_company_id",
        "refresh_due_live_stock_transitions(",
        "acquire_tenant_job_lock(",
        "mark_live_stock_projection_degraded(",
        'event="LIVE_STOCK_PROJECTION_DEGRADED"',
    )
    missing_worker_tokens = [
        token for token in required_worker_tokens
        if token not in worker_source
    ]
    if missing_worker_tokens:
        failures.append(
            "LIVE_STOCK_TEMPORAL_WORKER_INCOMPLETE:"
            + ",".join(missing_worker_tokens)
        )
    if "except BaseException" in worker_source:
        failures.append("LIVE_STOCK_WORKER_CATCHES_BASE_EXCEPTION")

    checks += 1
    retry_source = sources["worker_maintenance"]
    if (
        '"wanasah.scan_all_live_stock_transitions"' not in retry_source
        or '"wanasah.refresh_company_live_stock_transitions"' not in retry_source
    ):
        failures.append("LIVE_STOCK_WORKER_SAFE_RETRY_ALLOWLIST_MISSING")

    checks += 1
    forbidden_unbounded_projector_binds = (
        ".id.in_(location_ids)",
        ".location_id.in_(",
        ".product_variant_id.in_(variant_ids)",
    )
    offenders = [
        token
        for token in forbidden_unbounded_projector_binds
        if token in service
    ]
    if offenders:
        failures.append(
            "UNBOUNDED_PROJECTOR_LIST_BINDS:" + ",".join(offenders)
        )

    checks += 1
    worker_source = sources["worker_live_stock"]
    if (
        "async def run_company_live_stock_transition_maintenance(" 
        not in worker_source
        or "reconcile_live_stock_company(" not in worker_source
        or 'state == "DEGRADED"' not in worker_source
        or "Persist DEGRADED independently" not in worker_source
    ):
        failures.append("LIVE_STOCK_WORKER_SELF_HEAL_OR_FAIL_CLOSED_MISSING")

    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL:{failure}")
    if failures:
        raise SystemExit(1)
    print("STAGE822_LIVE_STOCK_REBUILD_CORE_GATE=PASS")


if __name__ == "__main__":
    main()
