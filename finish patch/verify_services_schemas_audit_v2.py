from __future__ import annotations

import ast
import importlib
import inspect
import py_compile
import sys
from pathlib import Path

ROOT = Path.cwd()
BACKEND = ROOT / "wa_backend"
for name in ("models.py", "services.py", "schemas.py"):
    path = BACKEND / name
    if not path.is_file():
        raise SystemExit(f"ERROR: missing {path}")

models_path = BACKEND / "models.py"
services_path = BACKEND / "services.py"
schemas_path = BACKEND / "schemas.py"

for path in (models_path, services_path, schemas_path):
    py_compile.compile(str(path), doraise=True)

sys.path.insert(0, str(BACKEND))
models = importlib.import_module("models")
services = importlib.import_module("services")
schemas = importlib.import_module("schemas")

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.dialects import postgresql

configure_mappers()

# Every Pydantic model must be able to publish its OpenAPI/JSON contract.
for obj in vars(schemas).values():
    if (
        inspect.isclass(obj)
        and obj.__module__ == "schemas"
        and issubclass(obj, BaseModel)
    ):
        obj.model_json_schema()

# Compile PostgreSQL DDL for every finalized model/index without touching a database.
dialect = postgresql.dialect()
for table in models.Base.metadata.sorted_tables:
    str(CreateTable(table).compile(dialect=dialect))
    for index in table.indexes:
        str(CreateIndex(index).compile(dialect=dialect))

services_source = services_path.read_text(encoding="utf-8")
schemas_source = schemas_path.read_text(encoding="utf-8")

for forbidden in (
    "adjust_inventory",
    "MainWarehouse",
    "WarehouseLedger",
    "SessionInventory",
    "InventoryLedger",
    "VehicleLoad",
):
    if forbidden in services_source:
        raise AssertionError(f"legacy inventory symbol remains: {forbidden}")

apply_params = inspect.signature(services.apply_inventory_movement).parameters
for forbidden_param in (
    "ignore_stocktake_session_id",
    "stocktake_session_id",
    "stocktake_count_attempt_id",
):
    if forbidden_param in apply_params:
        raise AssertionError(
            f"generic movement core still owns stocktake workflow: {forbidden_param}"
        )

if not hasattr(services, "post_approved_stocktake_adjustments"):
    raise AssertionError("missing batched stocktake posting service")
if not hasattr(services, "_bulk_ensure_inventory_balances"):
    raise AssertionError("missing safe bulk balance upsert helper")
if not (1 <= services._SQL_BULK_CHUNK_SIZE <= 1000):
    raise AssertionError("unsafe stocktake SQL bulk chunk size")
if services._MAX_STOCKTAKE_POST_LINES != 10_000:
    raise AssertionError("unexpected stocktake posting safety bound")

reserved = {"AUDIT_ADJUSTMENT", "DRIVER_SHORTAGE", "DRIVER_SURPLUS"}
if not reserved.issubset(set(services._STOCKTAKE_ONLY_REFERENCE_TYPES)):
    raise AssertionError("stocktake-only references are not reserved from generic core")

module_ast = ast.parse(services_source)
post_fn = next(
    node for node in module_ast.body
    if isinstance(node, ast.AsyncFunctionDef)
    and node.name == "post_approved_stocktake_adjustments"
)
post_source = ast.get_source_segment(services_source, post_fn) or ""
if "_bulk_ensure_inventory_balances" not in post_source:
    raise AssertionError("stocktake posting does not use bounded bulk balance upsert")
if "stocktake_session_id == session.id" not in post_source:
    raise AssertionError("stocktake posting does not scan all attempt movements")

# No database awaits are allowed inside per-stocktake-line loops.
for loop in (
    node for node in ast.walk(post_fn)
    if isinstance(node, (ast.For, ast.While, ast.AsyncFor))
):
    for node in ast.walk(loop):
        if isinstance(node, ast.Await):
            raise AssertionError(
                f"await found inside stocktake per-line loop at line {node.lineno}"
            )

# Schema boundary tests.
def must_reject(factory, label: str) -> None:
    try:
        factory()
    except (ValidationError, ValueError):
        return
    raise AssertionError(f"schema accepted invalid input: {label}")

must_reject(
    lambda: schemas.VisitUpdateRequest(outcome="NoSale", notes="x" * 201),
    "NoSale reason > Visit.no_sale_reason(200)",
)
must_reject(
    lambda: schemas.VisitUpdateRequest(outcome="Postponed", notes="x" * 201),
    "Postponed reason > Visit.no_sale_reason(200)",
)
schemas.VisitUpdateRequest(outcome="NoSale", notes="x" * 200)

must_reject(
    lambda: schemas.UpdateRouteStatusRequest(
        inventory={str(i + 1): 0 for i in range(5001)}
    ),
    "route inventory map > 5000",
)
schemas.UpdateRouteStatusRequest(
    inventory={str(i + 1): 0 for i in range(5000)}
)

must_reject(
    lambda: schemas.UpgradedInboundRequest(
        location_id=1,
        items=[
            {
                "product_variant_id": 1,
                "quantity_packs": 1,
                "batch_number": "B1",
                "expiry_date": "2030-01-01",
            },
            {
                "product_variant_id": 1,
                "quantity_packs": 2,
                "batch_number": "B1",
                "expiry_date": "2030-01-01",
            },
        ],
    ),
    "duplicate inbound product/batch line",
)

must_reject(
    lambda: schemas.LoginRequest(
        company_code="ACME\x00X",
        username="admin",
        password="abcd",
    ),
    "NUL in required database text",
)

approval_fields = schemas.StocktakeApprovalRequest.model_fields
recount_fields = schemas.StocktakeRecountRequest.model_fields
settle_fields = schemas.SettleSessionRequest.model_fields
if not approval_fields["count_attempt_id"].is_required():
    raise AssertionError("approval must require count_attempt_id")
if not recount_fields["count_attempt_id"].is_required():
    raise AssertionError("recount must require count_attempt_id")
if not settle_fields["actual_cash"].is_required():
    raise AssertionError("settlement actual_cash must be explicit")

# No trailing whitespace in the two hardened files.
for path, source in ((services_path, services_source), (schemas_path, schemas_source)):
    dirty = [
        i for i, line in enumerate(source.splitlines(), 1)
        if line.rstrip(" \t") != line
    ]
    if dirty:
        raise AssertionError(f"trailing whitespace in {path.name}: {dirty[:10]}")

print("SERVICES_SCHEMAS_AUDIT_V2_OK")
