from __future__ import annotations

import ast
import importlib
import inspect
import py_compile
import sys
from pathlib import Path

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"

required_files = {
    "models": BACKEND / "models.py",
    "schemas": BACKEND / "schemas.py",
    "services": BACKEND / "services.py",
    "warehouse": BACKEND / "api" / "warehouse.py",
}

if not BACKEND.is_dir():
    raise SystemExit("ERROR: شغّل السكربت من جذر مشروع wanasah.")

for name, path in required_files.items():
    if not path.is_file():
        raise SystemExit(f"ERROR: الملف مفقود ({name}): {path}")

# 1) Syntax.
for path in required_files.values():
    py_compile.compile(str(path), doraise=True)

# 2) Import the real project modules together.
sys.path.insert(0, str(BACKEND))

models = importlib.import_module("models")
schemas = importlib.import_module("schemas")
services = importlib.import_module("services")
warehouse = importlib.import_module("api.warehouse")

from sqlalchemy.orm import configure_mappers
from pydantic import BaseModel

configure_mappers()

# Force Pydantic schema construction; catches broken refs/validators.
for obj in vars(schemas).values():
    if (
        inspect.isclass(obj)
        and obj.__module__ == "schemas"
        and issubclass(obj, BaseModel)
    ):
        obj.model_json_schema()

# 3) Frozen model contract needed by warehouse stocktake.
expected_model_fields = {
    "StocktakeSession": {
        "company_id", "location_id", "reference_number", "stocktake_type",
        "status", "scope_product_variant_id", "scope_batch_id",
        "related_work_session_id", "snapshot_cutoff_at", "started_by",
        "approved_by", "approved_at", "posted_at", "cancelled_by",
        "cancelled_at", "cancellation_reason",
        "pending_recount_authorized_by", "pending_recount_reason",
        "pending_independent_recount_required",
    },
    "StocktakeLine": {
        "company_id", "stocktake_session_id", "product_variant_id", "batch_id",
        "stock_status", "line_origin", "expected_quantity",
        "discovered_by", "discovered_at",
    },
    "StocktakeCountAttempt": {
        "company_id", "stocktake_session_id", "attempt_number",
        "recount_of_attempt_id", "counted_by", "authorized_by",
        "recount_reason", "requires_independent_recount", "submitted_at",
    },
    "StocktakeCountAttemptLine": {
        "company_id", "stocktake_session_id", "count_attempt_id",
        "stocktake_line_id", "expected_quantity", "actual_quantity",
        "variance_quantity",
    },
    "InventoryLock": {
        "company_id", "stocktake_session_id", "location_id",
        "product_variant_id", "batch_id", "created_by",
        "released_by", "released_at", "release_reason",
    },
}

for class_name, fields in expected_model_fields.items():
    cls = getattr(models, class_name, None)
    if cls is None:
        raise AssertionError(f"missing model: {class_name}")
    missing = sorted(field for field in fields if not hasattr(cls, field))
    if missing:
        raise AssertionError(f"{class_name} missing fields: {missing}")

# 4) Frozen schema contract.
expected_schema_fields = {
    "UnifiedStocktakeStartRequest": {
        "location_id", "stocktake_type", "product_variant_id", "batch_id",
        "related_work_session_id", "notes",
    },
    "UnifiedStocktakeCountRequest": {"items", "notes"},
    "StocktakeRecountRequest": {
        "count_attempt_id", "reason",
        "authorizer_username", "authorizer_password",
    },
    "StocktakeApprovalRequest": {"count_attempt_id", "password", "notes"},
    "StocktakeCancelRequest": {"password", "reason"},
}

for class_name, fields in expected_schema_fields.items():
    cls = getattr(schemas, class_name, None)
    if cls is None:
        raise AssertionError(f"missing schema: {class_name}")
    actual = set(cls.model_fields)
    missing = sorted(fields - actual)
    if missing:
        raise AssertionError(f"{class_name} missing fields: {missing}")

count_item = getattr(schemas, "StocktakeCountItem", None)
if count_item is None:
    raise AssertionError("missing schema: StocktakeCountItem")
if not {"product_variant_id", "batch_id", "stock_status", "actual_quantity"} <= set(count_item.model_fields):
    raise AssertionError("StocktakeCountItem contract is incomplete.")

# 5) Service contract.
post_fn = getattr(services, "post_approved_stocktake_adjustments", None)
if post_fn is None:
    raise AssertionError("missing service: post_approved_stocktake_adjustments")

post_params = inspect.signature(post_fn).parameters
for param in (
    "db_session",
    "company_id",
    "stocktake_session_id",
    "stocktake_count_attempt_id",
    "performed_by",
):
    if param not in post_params:
        raise AssertionError(
            f"post_approved_stocktake_adjustments missing param: {param}"
        )

guard_fn = getattr(services, "acquire_inventory_location_guard", None)
if guard_fn is None:
    raise AssertionError("missing service: acquire_inventory_location_guard")
if "exclusive" not in inspect.signature(guard_fn).parameters:
    raise AssertionError("inventory location guard does not support exclusive mode.")

# 6) Warehouse source audit.
warehouse_path = required_files["warehouse"]
source = warehouse_path.read_text(encoding="utf-8")

for forbidden in (
    "_reconcile_cycle_count_movements",
    "_upsert_inventory_balance",
    "_allocate_fefo_batches",
    "MainWarehouse",
    "WarehouseLedger.",
    "VehicleLoad",
    "SessionInventory",
    "DamagedItemLog",
    "InventoryTransfer(",
):
    if forbidden in source:
        raise AssertionError(f"legacy inventory logic remains: {forbidden}")

# The API must not mutate balances/movements manually anymore.
for forbidden in (
    "pg_insert(InventoryBalance)",
    "InventoryBalance.on_hand_quantity +",
    "InventoryMovement(",
):
    if forbidden in source:
        raise AssertionError(f"warehouse bypasses unified inventory engine: {forbidden}")

stocktake_marker = "# [المرحلة السادسة] محرك الجرد القانوني (Stocktake Engine)"
if stocktake_marker not in source:
    raise AssertionError("stocktake section marker missing")

stocktake_source = source[source.index(stocktake_marker):]
if "apply_inventory_movement(" in stocktake_source:
    raise AssertionError(
        "stocktake endpoint is using generic movement core directly; "
        "posting must go through the stocktake domain service."
    )
if "post_approved_stocktake_adjustments(" not in stocktake_source:
    raise AssertionError("stocktake posting service is not used.")

for required in (
    "exclusive=True",
    "line_origin='SNAPSHOT'",
    "line_origin='DISCOVERED'",
    "stock_status=balance.stock_status",
    "stocktake_line_id=line.id",
    "pending_independent_recount_required",
    "snapshot_cutoff_at = cutoff",
):
    if required not in stocktake_source:
        raise AssertionError(f"required stocktake hardening missing: {required}")

# 7) AST function/route uniqueness.
tree = ast.parse(source)
function_names = []
routes = []

for node in tree.body:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue

    function_names.append(node.name)

    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "router"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
        ):
            routes.append(
                (
                    decorator.func.attr.upper(),
                    decorator.args[0].value,
                    node.name,
                )
            )

if len(function_names) != len(set(function_names)):
    duplicates = sorted(
        name for name in set(function_names)
        if function_names.count(name) > 1
    )
    raise AssertionError(f"duplicate functions: {duplicates}")

route_keys = [(method, path) for method, path, _ in routes]
if len(route_keys) != len(set(route_keys)):
    duplicates = sorted(
        key for key in set(route_keys)
        if route_keys.count(key) > 1
    )
    raise AssertionError(f"duplicate routes: {duplicates}")

expected_routes = {
    ("GET", "/warehouse/locations"),
    ("POST", "/warehouse/inbound"),
    ("GET", "/warehouse/alerts"),
    ("GET", "/warehouse/inventory"),
    ("GET", "/warehouse/ledger"),
    ("GET", "/warehouse/status"),
    ("GET", "/product_variants/simple"),
    ("POST", "/warehouse/product_variants"),
    ("POST", "/warehouse/ledger/{entry_id}/adjust"),
    ("POST", "/warehouse/unified/transfer/dispatch"),
    ("POST", "/warehouse/unified/transfer/receive"),
    ("POST", "/warehouse/unified/transfer/{header_id}/cancel"),
    ("POST", "/warehouse/unified/transfer/{header_id}/reject"),
    ("POST", "/warehouse/unified/stocktake/start"),
    ("GET", "/warehouse/unified/stocktake/{session_id}/count-sheet"),
    ("POST", "/warehouse/unified/stocktake/{session_id}/count"),
    ("GET", "/warehouse/unified/stocktake/{session_id}/review"),
    ("POST", "/warehouse/unified/stocktake/{session_id}/approve"),
    ("POST", "/warehouse/unified/stocktake/{session_id}/recount"),
    ("POST", "/warehouse/unified/stocktake/{session_id}/cancel"),
}

actual_routes = set(route_keys)
if actual_routes != expected_routes:
    missing = sorted(expected_routes - actual_routes)
    extra = sorted(actual_routes - expected_routes)
    raise AssertionError(f"route contract changed. missing={missing}, extra={extra}")

# 8) Verify the imported FastAPI router sees the same route count.
runtime_route_keys = set()
for route in warehouse.router.routes:
    for method in (route.methods or set()):
        if method in {"HEAD", "OPTIONS"}:
            continue
        runtime_route_keys.add((method, route.path))

if runtime_route_keys != expected_routes:
    missing = sorted(expected_routes - runtime_route_keys)
    extra = sorted(runtime_route_keys - expected_routes)
    raise AssertionError(
        f"runtime FastAPI route contract changed. missing={missing}, extra={extra}"
    )

print("WAREHOUSE_ARCHITECTURE_AUDIT_OK")
print(f"Functions: {len(function_names)}")
print(f"Routes: {len(actual_routes)}")
print("Legacy inventory logic: NONE")
print("Manual InventoryBalance/InventoryMovement writes in warehouse.py: NONE")
print("models + schemas + services + warehouse import contract: OK")
