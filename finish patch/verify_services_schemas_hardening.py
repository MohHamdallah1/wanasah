from __future__ import annotations

import ast
import importlib
import inspect
import py_compile
import sys
from pathlib import Path

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"
if not BACKEND.is_dir():
    raise SystemExit("ERROR: run this script from the wanasah repository root.")

services_path = BACKEND / "services.py"
schemas_path = BACKEND / "schemas.py"
models_path = BACKEND / "models.py"
for path in (services_path, schemas_path, models_path):
    if not path.is_file():
        raise SystemExit(f"ERROR: missing {path}")

py_compile.compile(str(models_path), doraise=True)
py_compile.compile(str(services_path), doraise=True)
py_compile.compile(str(schemas_path), doraise=True)

sys.path.insert(0, str(BACKEND))
models = importlib.import_module("models")
services = importlib.import_module("services")
schemas = importlib.import_module("schemas")

from sqlalchemy.orm import configure_mappers
from pydantic import BaseModel

configure_mappers()

for obj in vars(schemas).values():
    if (
        inspect.isclass(obj)
        and obj.__module__ == "schemas"
        and issubclass(obj, BaseModel)
    ):
        obj.model_json_schema()

services_source = services_path.read_text(encoding="utf-8")
for forbidden in (
    "adjust_inventory",
    "MainWarehouse",
    "WarehouseLedger",
    "SessionInventory",
    "InventoryLedger",
    "VehicleLoad",
):
    if forbidden in services_source:
        raise AssertionError(f"legacy inventory symbol remains in services.py: {forbidden}")

apply_params = inspect.signature(services.apply_inventory_movement).parameters
if "ignore_stocktake_session_id" in apply_params:
    raise AssertionError("generic mutation core still exposes stocktake lock bypass")
if "stocktake_session_id" in apply_params or "stocktake_count_attempt_id" in apply_params:
    raise AssertionError("generic mutation core still owns stocktake workflow fields")

if not hasattr(services, "post_approved_stocktake_adjustments"):
    raise AssertionError("missing batched stocktake posting service")

lock_params = inspect.signature(services.check_inventory_lock).parameters
if "ignore_stocktake_session_id" in lock_params:
    raise AssertionError("public lock guard still exposes privileged bypass")

module_ast = ast.parse(services_source)
post_fn = next(
    node
    for node in module_ast.body
    if isinstance(node, ast.AsyncFunctionDef)
    and node.name == "post_approved_stocktake_adjustments"
)
for loop in (node for node in ast.walk(post_fn) if isinstance(node, (ast.For, ast.While))):
    for node in ast.walk(loop):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
        ):
            raise AssertionError(
                f"DB execute found inside stocktake posting loop at line {node.lineno}"
            )

approval_fields = schemas.StocktakeApprovalRequest.model_fields
recount_fields = schemas.StocktakeRecountRequest.model_fields
settle_fields = schemas.SettleSessionRequest.model_fields
if "count_attempt_id" not in approval_fields or not approval_fields["count_attempt_id"].is_required():
    raise AssertionError("StocktakeApprovalRequest must require count_attempt_id")
if "count_attempt_id" not in recount_fields or not recount_fields["count_attempt_id"].is_required():
    raise AssertionError("StocktakeRecountRequest must require count_attempt_id")
if not settle_fields["actual_cash"].is_required():
    raise AssertionError("SettleSessionRequest.actual_cash must be explicit")

print("SERVICES_SCHEMAS_HARDENING_OK")
