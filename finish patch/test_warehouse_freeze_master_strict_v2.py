from __future__ import annotations

import ast
import os
import py_compile
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path.cwd().resolve()
BACKEND = ROOT / "wa_backend"
WAREHOUSE = BACKEND / "api" / "warehouse.py"
MODELS = BACKEND / "models.py"
SERVICES = BACKEND / "services.py"
SCHEMAS = BACKEND / "schemas.py"

REQUIRED_FILES = (WAREHOUSE, MODELS, SERVICES, SCHEMAS)

COMPONENT_TESTS = [
    (
        "test_warehouse_hardening_postgres.py",
        "WAREHOUSE_HARDENING_POSTGRES_OK",
    ),
    (
        "test_warehouse_request_idempotency_postgres.py",
        "WAREHOUSE_REQUEST_IDEMPOTENCY_POSTGRES_OK",
    ),
    (
        "test_warehouse_vehicle_recon_lifecycle_postgres_v3.py",
        "WAREHOUSE_VEHICLE_RECON_LIFECYCLE_POSTGRES_OK",
    ),
    (
        "test_warehouse_stage6_pagination_postgres_e2e.py",
        "WAREHOUSE_STAGE6_PAGINATION_POSTGRES_E2E_OK",
    ),
    (
        "test_warehouse_freeze_supplement_postgres_v2.py",
        "WAREHOUSE_FREEZE_SUPPLEMENT_POSTGRES_OK",
    ),
    (
        "test_warehouse_interwarehouse_postgres_e2e_v2.py",
        "WAREHOUSE_INTERWAREHOUSE_POSTGRES_E2E_STRICT_OK",
    ),
]

FATAL_OUTPUT_MARKERS = (
    "Traceback (most recent call last):",
    "Exception closing connection",
    "RuntimeWarning:",
    "DeprecationWarning:",
    "ResourceWarning:",
    "Task was destroyed but it is pending",
    "coroutine was never awaited",
)


def fail(message: str) -> None:
    raise AssertionError(message)


def static_audit() -> None:
    for path in REQUIRED_FILES:
        if not path.is_file():
            fail(f"Missing required file: {path}")
        py_compile.compile(str(path), doraise=True)

    warehouse_text = WAREHOUSE.read_text(encoding="utf-8")
    models_text = MODELS.read_text(encoding="utf-8")
    services_text = SERVICES.read_text(encoding="utf-8")
    schemas_text = SCHEMAS.read_text(encoding="utf-8")

    warehouse_ast = ast.parse(warehouse_text)
    models_ast = ast.parse(models_text)
    ast.parse(services_text)
    ast.parse(schemas_text)

    routes = []
    for node in warehouse_ast.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = []
        for decorator in node.decorator_list:
            try:
                value = ast.unparse(decorator)
            except Exception:
                value = ""
            if value.startswith("router."):
                decorators.append(value)
        if decorators:
            routes.append((node.name, decorators, ast.unparse(node.args)))

    if len(routes) != 22:
        fail(f"Warehouse route count drifted: {len(routes)} != 22")

    no_admin = [name for name, _, args in routes if "get_current_admin" not in args]
    if no_admin:
        fail(f"Warehouse routes without get_current_admin: {no_admin}")

    stale_routes = (
        '@router.get("/warehouse/alerts"',
        '@router.get("/warehouse/inventory"',
        '@router.get("/product_variants/simple"',
        '@router.get("/warehouse/ledger"',
    )
    for marker in stale_routes:
        if marker in warehouse_text:
            fail(f"Legacy unbounded route remains: {marker}")

    forbidden_route_writes = (
        "update(InventoryBalance)",
        "delete(InventoryBalance)",
        "InventoryBalance.on_hand_quantity =",
        "InventoryBalance.reserved_quantity =",
    )
    for marker in forbidden_route_writes:
        if marker in warehouse_text:
            fail(f"Route-level InventoryBalance mutation detected: {marker}")

    tenant_models = (
        "InventoryBalance", "InventoryMovement", "InventoryMovementImpact",
        "InventoryLocation", "InventoryStockPolicy", "InventoryTransferHeader",
        "InventoryTransferLine", "ProductVariant", "ProductBatch", "Driver",
        "DispatchRoute", "WorkSession", "StocktakeSession", "StocktakeLine",
        "StocktakeCountAttempt", "StocktakeCountAttemptLine", "InventoryLock",
        "OperationIdempotency",
    )
    for label, text_value in (
        ("warehouse.py", warehouse_text),
        ("services.py", services_text),
    ):
        for match in re.finditer(r"select\(([^\n\)]{0,160})", text_value):
            head = match.group(1)
            if not any(model in head for model in tenant_models):
                continue
            window = text_value[match.start(): match.start() + 700]
            if "company_id" not in window:
                line = text_value.count("\n", 0, match.start()) + 1
                fail(
                    f"Possible tenant-unscoped SELECT in "
                    f"{label}:{line}: {head.strip()}"
                )

    required_markers = {
        "models.py": (
            "class OperationIdempotency(Base):",
            "uq_operation_idempotency_request",
            "uq_inv_balance_core",
            "uq_inv_movement_idempotency",
            "fk_inv_movement_tenant_actor",
            "fk_inv_movement_variant_batch",
            "chk_inv_movement_shape",
            "chk_inv_movement_physical_preserves_status",
            "chk_inv_movement_attempt_requires_stocktake",
            "chk_work_session_settlement_requires_end",
            "uq_vehicle_recon_work_session",
            "ix_inv_movement_company_created_id",
            "ix_product_variant_company_name_id",
            "ix_transfer_header_transit_queue",
            "chk_transfer_header_session_scope",
            "chk_transfer_header_received_by_scope",
            "chk_transfer_header_separation_of_duties",
            "chk_transfer_header_transit_location_required",
        ),
        "services.py": (
            "apply_inventory_movements_batch",
            "allocate_fefo_inventory_batch",
            "post_approved_stocktake_adjustments",
            "begin_idempotent_operation",
            "complete_idempotent_operation",
            "validate_vehicle_recon_work_session",
            "pg_advisory_xact_lock",
            "with_for_update",
        ),
        "warehouse.py": (
            "WAREHOUSE_INBOUND",
            "WAREHOUSE_TRANSFER_DISPATCH",
            "WAREHOUSE_TRANSFER_RECEIVE",
            "WAREHOUSE_TRANSFER_CANCEL",
            "WAREHOUSE_TRANSFER_REJECT",
            "_ledger_cursor_scope_hash",
            "expected_scope=ledger_scope",
            "scope=ledger_scope",
            "_transfer_cursor_scope_hash",
            '"/warehouse/unified/transfers"',
            '"/warehouse/unified/transfers/{header_id}"',
            '"/warehouse/inventory/cursor"',
            '"/warehouse/ledger/cursor"',
            '"/product_variants/simple/cursor"',
            '"/product_variants/simple/resolve"',
            "DISCOVERED بحالة AVAILABLE يتطلب صنفاً ودفعة فعالين.",
            "validate_vehicle_recon_work_session",
        ),
        "schemas.py": (
            "request_id: UUID",
            "class WarehouseInventoryCursorPage(BaseModel):",
            "class WarehouseLedgerCursorPage(BaseModel):",
            "class SimpleProductVariantCursorPage(BaseModel):",
            "class ProductVariantResolveRequest(RequestModel):",
            "class UnifiedTransferDecisionRequest(RequestModel):",
            "class WarehouseTransferCursorPage(BaseModel):",
            "class WarehouseTransferDetail(BaseModel):",
        ),
    }

    sources = {
        "models.py": models_text,
        "services.py": services_text,
        "warehouse.py": warehouse_text,
        "schemas.py": schemas_text,
    }
    for name, markers in required_markers.items():
        for marker in markers:
            if marker not in sources[name]:
                fail(f"Missing freeze invariant in {name}: {marker}")

    if warehouse_text.count("request_id") < 8:
        fail("Request-level idempotency contract appears incomplete")

    if "date.today(" in warehouse_text or "date.today(" in services_text:
        fail(
            "Business inventory decisions must not use "
            "process-local date.today()"
        )

    table_names = []
    for node in models_ast.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "__tablename__"
                        and isinstance(item.value, ast.Constant)
                        and isinstance(item.value.value, str)
                    ):
                        table_names.append(item.value.value)

    explicit_table_names = set(table_names)
    for node in ast.walk(models_ast):
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name == "Table" and node.args:
                first = node.args[0]
                if (
                    isinstance(first, ast.Constant)
                    and isinstance(first.value, str)
                ):
                    explicit_table_names.add(first.value)

    if len(explicit_table_names) != 50:
        fail(
            f"Model table declaration count drifted: "
            f"{len(explicit_table_names)} != 50"
        )
    if len(table_names) != len(set(table_names)):
        fail("Duplicate __tablename__ declarations detected")

    print("WAREHOUSE_FREEZE_STATIC_AUDIT_OK")
    print("ROUTES=22_ALL_ADMIN_GUARDED")
    print("TENANT_QUERY_HEURISTIC=OK")
    print("ROUTE_LEVEL_BALANCE_WRITES=NONE")
    print("MODEL_TABLE_DECLARATIONS=50")
    print("LEDGER_CURSOR_SCOPE=TENANT_AND_FILTER_BOUND")
    print("TRANSFER_CURSOR_SCOPE=TENANT_AND_FILTER_BOUND")
    print("TRANSFER_TERMINAL_IDEMPOTENCY=STATICALLY_PRESENT")


def run_component(script_name: str, success_marker: str) -> float:
    script = ROOT / script_name
    if not script.is_file():
        fail(
            f"Missing {script_name}. Put all strict freeze test files "
            "in the project root before running the master."
        )

    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=300,
        env=os.environ.copy(),
    )
    elapsed = time.perf_counter() - started

    print(f"\n===== {script_name} =====")
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)

    if proc.returncode != 0:
        fail(
            f"{script_name} failed with exit code {proc.returncode}"
        )

    if proc.stderr.strip():
        fail(
            f"{script_name} emitted stderr under STRICT mode"
        )

    combined = f"{proc.stdout}\n{proc.stderr}"
    bad_markers = [
        marker
        for marker in FATAL_OUTPUT_MARKERS
        if marker in combined
    ]
    if bad_markers:
        fail(
            f"{script_name} emitted forbidden output markers: "
            f"{bad_markers}"
        )

    if success_marker not in proc.stdout:
        fail(
            f"{script_name} exited 0 but missing "
            f"success marker {success_marker}"
        )

    print(f"STRICT_COMPONENT=OK duration={elapsed:.3f}s")
    return elapsed


def main() -> None:
    total_started = time.perf_counter()

    static_audit()

    durations = []
    for script_name, marker in COMPONENT_TESTS:
        durations.append(
            (script_name, run_component(script_name, marker))
        )

    total_elapsed = time.perf_counter() - total_started

    print("\n===== STRICT FREEZE SUMMARY =====")
    for script_name, elapsed in durations:
        print(f"{script_name}={elapsed:.3f}s")

    print(f"TOTAL_STRICT_FREEZE_SECONDS={total_elapsed:.3f}")
    print("STRICT_STDERR=EMPTY_FOR_ALL_COMPONENTS")
    print("WAREHOUSE_FREEZE_MASTER_STRICT_POSTGRES_OK")
    print("TENANT_ISOLATION=VERIFIED_AT_API_DB_FK_RLS_LAYERS")
    print("INVENTORY_CONCURRENCY=VERIFIED")
    print("REQUEST_IDEMPOTENCY=VERIFIED")
    print("BATCH_FEFO_UOM=VERIFIED")
    print("STOCKTAKE_DISCOVERED=VERIFIED")
    print("VEHICLE_RECON_LIFECYCLE=VERIFIED")
    print("CURSOR_PAGINATION=VERIFIED")
    print("INTERWAREHOUSE_TRANSIT=VERIFIED")
    print("NO_STDERR_OR_TRACEBACK=VERIFIED")
    print("WAREHOUSE_READY_FOR_FINAL_FREEZE_VERDICT")


if __name__ == "__main__":
    main()
