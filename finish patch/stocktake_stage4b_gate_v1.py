from __future__ import annotations

from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
INV = ROOT / "dashboard" / "src" / "pages" / "inventory"
STOCKTAKE = INV / "stocktake"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"
WAREHOUSE = ROOT / "wa_backend" / "api" / "warehouse.py"

FILES = {
    "tab": INV / "Tab3Stocktake.tsx",
    "types": STOCKTAKE / "types.ts",
    "parsers": STOCKTAKE / "parsers.ts",
    "sessions": STOCKTAKE / "hooks" / "useStocktakeSessions.ts",
    "cycle_hook": STOCKTAKE / "hooks" / "useCycleCountStart.ts",
    "cycle_modal": STOCKTAKE / "StocktakeCycleStartModal.tsx",
    "counting": STOCKTAKE / "hooks" / "useStocktakeCounting.ts",
    "review": STOCKTAKE / "hooks" / "useStocktakeReview.ts",
    "actions": STOCKTAKE / "hooks" / "useStocktakeActions.ts",
    "lifecycle": STOCKTAKE / "hooks" / "useStocktakeLifecycle.ts",
    "center": STOCKTAKE / "StocktakeSessionCenter.tsx",
}


def fail(label: str) -> None:
    raise SystemExit(f"STOCKTAKE_STAGE4B_GATE=FAIL\n{label}=FAIL")


def require(ok: bool, label: str) -> None:
    if not ok:
        fail(label)
    print(f"{label}=OK")


for name, path in FILES.items():
    require(path.exists(), f"FILE_{name.upper()}")
for path in (SCHEMAS, WAREHOUSE):
    require(path.exists(), f"FILE_{path.name}")

text = {
    name: path.read_text(encoding="utf-8").replace("\r\n", "\n")
    for name, path in FILES.items()
}
schemas = SCHEMAS.read_text(encoding="utf-8").replace("\r\n", "\n")
warehouse = WAREHOUSE.read_text(encoding="utf-8").replace("\r\n", "\n")
combined_frontend = "\n".join(text.values())

# Backend contract already existed and must remain authoritative.
require(
    'stocktake_type: Literal["FULL_COUNT", "CYCLE_COUNT", "VEHICLE_RECON"]' in schemas,
    "BACKEND_CYCLE_TYPE_CONTRACT",
)
require(
    'CYCLE_COUNT يتطلب product_variant_id.' in schemas,
    "BACKEND_CYCLE_PRODUCT_REQUIRED",
)
require(
    'batch_id يتطلب product_variant_id.' in schemas,
    "BACKEND_BATCH_REQUIRES_PRODUCT",
)

# New batch-picker boundary.
require(
    "class StocktakeCycleBatchCursorPage(BaseModel):" in schemas,
    "BACKEND_CYCLE_BATCH_SCHEMA",
)
require(
    "/warehouse/unified/stocktake/cycle-batches" in warehouse,
    "BACKEND_CYCLE_BATCH_ROUTE",
)
require(
    "InventoryLocation.company_id == company_id" in warehouse
    and "ProductVariant.company_id == company_id" in warehouse
    and "ProductBatch.company_id == company_id" in warehouse,
    "BACKEND_CYCLE_TENANT_SCOPE",
)
require(
    "InventoryBalance.location_id == location_id" in warehouse
    and "InventoryBalance.product_variant_id == product_variant_id" in warehouse
    and "InventoryBalance.on_hand_quantity > 0" in warehouse,
    "BACKEND_CYCLE_LOCATION_STOCK_SCOPE",
)
require(
    "_decode_stocktake_cycle_batch_cursor" in warehouse
    and "_encode_stocktake_cycle_batch_cursor" in warehouse,
    "BACKEND_CYCLE_BATCH_CURSOR_SCOPE",
)

# AST route uniqueness.
tree = ast.parse(warehouse)
route_paths: list[str] = []
for node in ast.walk(tree):
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name) or func.value.id != "router":
            continue
        if func.attr not in {"get", "post", "patch", "delete", "put"}:
            continue
        if not decorator.args:
            continue
        arg = decorator.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            route_paths.append(f"{func.attr.upper()} {arg.value}")

require(
    route_paths.count("GET /warehouse/unified/stocktake/cycle-batches") == 1,
    "BACKEND_CYCLE_BATCH_ROUTE_UNIQUE",
)
require(
    route_paths.count("POST /warehouse/unified/stocktake/start") == 1,
    "BACKEND_STOCKTAKE_START_ROUTE_UNIQUE",
)

cycle = text["cycle_hook"]
require(
    "/warehouse/inventory/cursor?" in cycle,
    "FRONTEND_CYCLE_PRODUCT_LOCATION_CURSOR",
)
require(
    "/warehouse/unified/stocktake/cycle-batches?" in cycle,
    "FRONTEND_CYCLE_BATCH_CURSOR",
)
require(
    'stocktake_type: "CYCLE_COUNT"' in cycle
    and "product_variant_id: selectedProduct.id" in cycle
    and "batch_id: selectedBatch?.id ?? null" in cycle,
    "FRONTEND_CYCLE_START_PAYLOAD",
)
require(
    "location_id: String(locationId)" in cycle,
    "FRONTEND_CYCLE_PRODUCT_LOCATION_SCOPE",
)
require(
    "parseCycleBatchPage(raw, selectedProduct.id)" in cycle,
    "FRONTEND_BATCH_PRODUCT_FAIL_CLOSED",
)
require(
    "productRequestSeq.current" in cycle
    and "batchRequestSeq.current" in cycle,
    "FRONTEND_CYCLE_RACE_GUARDS",
)
require(
    "loadCountSheet(sid)" in cycle
    and "/approve" not in cycle
    and "/recount" not in cycle
    and "/cancel" not in cycle,
    "FRONTEND_REUSES_STOCKTAKE_ENGINE",
)
require(
    "localStorage.setItem(sessionKey, sid)" in cycle
    and "localStorage.setItem(phaseKey, \"COUNTING\")" in cycle,
    "FRONTEND_CYCLE_SELECTED_SESSION_STATE",
)
require(
    "notifyStocktakeChanged" in cycle,
    "FRONTEND_SERVER_STATUS_AUTHORITY",
)

require(
    "useCycleCountStart({" in text["tab"]
    and "<StocktakeCycleStartModal" in text["tab"],
    "TAB_CYCLE_ORCHESTRATION",
)
require(
    "onStartCycle" in text["center"]
    and "cycleStartDisabled" in text["center"],
    "SESSION_CENTER_CYCLE_ENTRY",
)

# Existing legal flow must remain intact.
require(
    "stock_status: row.stock_status" in text["counting"],
    "COUNTING_STOCK_STATUS_PRESERVED",
)
require(
    text["actions"].count("review.latest_attempt.id") >= 2,
    "APPROVE_RECOUNT_CONCURRENCY_PRESERVED",
)
require(
    "data.location_id !== locationId" in text["review"],
    "REVIEW_LOCATION_FAIL_CLOSED_PRESERVED",
)
require(
    'stocktake_type:' in text["lifecycle"]
    and '"FULL_COUNT"' in text["lifecycle"],
    "FULL_COUNT_PATH_PRESERVED",
)

require("company_id" not in combined_frontend, "FRONTEND_NO_COMPANY_ID_PAYLOAD")
require(
    ": any" not in combined_frontend
    and "any[]" not in combined_frontend
    and "Promise<any>" not in combined_frontend,
    "FRONTEND_NO_EXPLICIT_ANY",
)

print("STOCKTAKE_STAGE4B_GATE=PASS")
