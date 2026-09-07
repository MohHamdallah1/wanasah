from __future__ import annotations

import ast
import importlib
import inspect
import py_compile
import sys
from pathlib import Path

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"
FILES = {
    "models": BACKEND / "models.py",
    "services": BACKEND / "services.py",
    "warehouse": BACKEND / "api" / "warehouse.py",
}

if not BACKEND.is_dir():
    raise SystemExit("ERROR: شغّل السكربت من جذر مشروع wanasah.")

for path in FILES.values():
    if not path.is_file():
        raise SystemExit(f"ERROR: الملف مفقود: {path}")
    py_compile.compile(str(path), doraise=True)

sys.path.insert(0, str(BACKEND))
models = importlib.import_module("models")
services = importlib.import_module("services")
warehouse = importlib.import_module("api.warehouse")

from sqlalchemy.orm import configure_mappers
configure_mappers()

# Service contracts.
for fn_name, required_params in {
    "apply_inventory_movements_batch": {"db_session", "company_id", "performed_by", "movements"},
    "allocate_fefo_inventory_batch": {"db_session", "company_id", "location_id", "requests", "as_of_date"},
    "get_company_local_date": {"db_session", "company_id"},
}.items():
    fn = getattr(services, fn_name, None)
    if fn is None:
        raise AssertionError(f"missing service: {fn_name}")
    params = set(inspect.signature(fn).parameters)
    missing = required_params - params
    if missing:
        raise AssertionError(f"{fn_name} missing params: {sorted(missing)}")

# Single-item wrappers still exist for compatibility.
if not hasattr(services, "apply_inventory_movement"):
    raise AssertionError("single movement wrapper missing")
if not hasattr(services, "allocate_fefo_inventory"):
    raise AssertionError("single FEFO wrapper missing")

# Model index required by latest-route lookup.
route_indexes = {idx.name for idx in models.DispatchRoute.__table__.indexes}
if "ix_dispatch_route_company_vehicle_latest" not in route_indexes:
    raise AssertionError("DispatchRoute latest vehicle compound index missing from model metadata")

warehouse_source = FILES["warehouse"].read_text(encoding="utf-8")
services_source = FILES["services"].read_text(encoding="utf-8")

# No dead FEFO RBAC branch.
for forbidden in (
    "_check_fefo_override_permission",
    "latest_vehicle_route_subq",
    "Role, Permission, UserRole, role_permissions",
):
    if forbidden in warehouse_source:
        raise AssertionError(f"warehouse hardening incomplete: {forbidden}")

# Transfer and inbound must use batch core.
if warehouse_source.count("apply_inventory_movements_batch(") < 3:
    raise AssertionError("warehouse is not using batch movement core for inbound/dispatch/receive")
if warehouse_source.count("allocate_fefo_inventory_batch(") < 2:
    raise AssertionError("dispatch is not using bulk FEFO")

inbound_slice = warehouse_source[
    warehouse_source.index('@router.post("/warehouse/inbound"'):
    warehouse_source.index("# 2. إشعارات النواقص")
]
if "await apply_inventory_movement(" in inbound_slice:
    raise AssertionError("Inbound still applies movement one-by-one")

transfer_slice = warehouse_source[
    warehouse_source.index('@router.post("/warehouse/unified/transfer/dispatch"'):
    warehouse_source.index("# [المرحلة السادسة] محرك الجرد القانوني")
]
if "for line in lines:\n        await apply_inventory_movement(" in transfer_slice:
    raise AssertionError("Transfer receive still has N+1 movement application")

# Empty stocktake must not be rejected by posting service.
if 'جلسة الجرد لا تحتوي على أسطر قابلة للترحيل.' in services_source:
    raise AssertionError("empty stocktake is still rejected")

# Stocktake release must be set-based.
if 'for lock in own_locks:\n        lock.released_by' in services_source:
    raise AssertionError("stocktake posting still updates lock ORM rows one-by-one")
if 'for lock in active_locks:\n            lock.released_by' in warehouse_source:
    raise AssertionError("stocktake cancel still updates lock ORM rows one-by-one")

# No accidental route contract change.
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
runtime_routes = set()
for route in warehouse.router.routes:
    for method in route.methods or set():
        if method not in {"HEAD", "OPTIONS"}:
            runtime_routes.add((method, route.path))

if runtime_routes != expected_routes:
    raise AssertionError(
        f"warehouse route contract changed: missing={sorted(expected_routes-runtime_routes)}, "
        f"extra={sorted(runtime_routes-expected_routes)}"
    )

# AST uniqueness.
tree = ast.parse(warehouse_source)
funcs = [
    node.name for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
]
if len(funcs) != len(set(funcs)):
    raise AssertionError("duplicate top-level functions found in warehouse.py")

print("WAREHOUSE_HARDENING_ARCHITECTURE_OK")
print(f"Routes: {len(runtime_routes)}")
print(f"Functions: {len(funcs)}")
print("Bulk movement core: OK")
print("Bulk FEFO: OK")
print("Empty stocktake: OK")
print("Dead FEFO RBAC: NONE")
print("Latest vehicle lookup model index: OK")
print("Route contract changed: NO")
