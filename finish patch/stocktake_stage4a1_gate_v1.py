from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "dashboard" / "src" / "pages" / "inventory" / "MainInventory.tsx"
TAB = ROOT / "dashboard" / "src" / "pages" / "inventory" / "Tab3Stocktake.tsx"
UTILS = ROOT / "dashboard" / "src" / "pages" / "inventory" / "inventoryUtils.ts"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"
WAREHOUSE = ROOT / "wa_backend" / "api" / "warehouse.py"


def fail(label: str) -> None:
    raise SystemExit(f"STOCKTAKE_STAGE4A1_GATE=FAIL\n{label}=FAIL")


def require(condition: bool, label: str) -> None:
    if not condition:
        fail(label)
    print(f"{label}=OK")


for path in (MAIN, TAB, UTILS, SCHEMAS, WAREHOUSE):
    require(path.exists(), f"FILE_{path.name}")

main = MAIN.read_text(encoding="utf-8").replace("\r\n", "\n")
tab = TAB.read_text(encoding="utf-8").replace("\r\n", "\n")
utils = UTILS.read_text(encoding="utf-8").replace("\r\n", "\n")
schemas = SCHEMAS.read_text(encoding="utf-8").replace("\r\n", "\n")
warehouse = WAREHOUSE.read_text(encoding="utf-8").replace("\r\n", "\n")

require(": any" not in tab and "Promise<any>" not in tab, "TAB_NO_EXPLICIT_ANY")
require("companyId={companyId}" in main, "MAIN_COMPANY_SCOPE_PROP")
require(
    'unified_stocktake_session:${companyScope}:${locationId}' in tab
    and 'unified_stocktake_phase:${companyScope}:${locationId}' in tab
    and 'wanasah_audit_draft:${companyScope}:${locationId}:${sessionId}' in tab,
    "TENANT_SCOPED_LOCAL_STORAGE",
)
require(
    'export type StocktakeStockStatus = "AVAILABLE" | "DAMAGED";' in utils
    and "stock_status: StocktakeStockStatus;" in utils,
    "STOCKTAKE_ROW_STATUS_TYPE",
)
require(
    "stockStatus: StocktakeStockStatus" in tab
    and '`${productVariantId}:${batchId ?? "NO_BATCH"}:${stockStatus}`' in tab,
    "ROW_KEY_INCLUDES_STOCK_STATUS",
)
require(
    "stock_status: row.stock_status" in tab,
    "COUNT_PAYLOAD_STOCK_STATUS",
)
require(
    tab.count("count_attempt_id: review.latest_attempt.id") == 2,
    "APPROVE_RECOUNT_ATTEMPT_IDS",
)
require(
    "parseStocktakeReview(raw)" in tab
    and "data.location_id !== locationId" in tab,
    "REVIEW_LOCATION_FAIL_CLOSED",
)
require(
    "maxLength={4000}" in tab
    and tab.count("maxLength={500}") >= 3
    and "maxLength={80}" in tab,
    "SCHEMA_TEXT_LIMITS_MIRRORED",
)

# Backend contract existence.
require(
    'stock_status: Literal["AVAILABLE", "DAMAGED"]' in schemas,
    "BACKEND_COUNT_STATUS_REQUIRED",
)
require(
    "class StocktakeApprovalRequest" in schemas
    and "count_attempt_id: PositiveDbInt" in schemas,
    "BACKEND_APPROVAL_ATTEMPT_REQUIRED",
)
require(
    "class StocktakeRecountRequest" in schemas
    and schemas.count("count_attempt_id: PositiveDbInt") >= 2,
    "BACKEND_RECOUNT_ATTEMPT_REQUIRED",
)
require(
    '"stock_status": line.stock_status' in warehouse,
    "BACKEND_COUNT_SHEET_RETURNS_STATUS",
)
require(
    "latest_attempt.id != payload.count_attempt_id" in warehouse,
    "BACKEND_OPTIMISTIC_CONCURRENCY",
)

print("STOCKTAKE_STAGE4A1_GATE=PASS")
