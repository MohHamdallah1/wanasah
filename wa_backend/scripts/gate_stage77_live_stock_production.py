from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
checks = 0
failures: list[str] = []

def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(label)

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

warehouse = read("wa_backend/api/warehouse/live_stock.py")
schemas = read("wa_backend/schemas.py")
contracts = read("dashboard/src/pages/inventory/liveStock/contracts.ts")
live = read("dashboard/src/pages/inventory/Tab1LiveStock.tsx")
batches = read("dashboard/src/pages/inventory/TabBatches.tsx")
main = read("dashboard/src/pages/inventory/MainInventory.tsx")
resources = read("dashboard/src/i18n/resources.ts")
money = read("dashboard/src/lib/money.ts")

check(
    '"on_hand_quantity": canonical_quantity(' in warehouse
    and "warehouse_on_hand_total" in warehouse,
    "warehouse on-hand business field",
)
check(
    '"available_for_sale_quantity": canonical_quantity(' in warehouse
    and "free_quantity" in warehouse,
    "available-for-sale business field",
)
check("warehouse_on_hand_total - reserved - free_quantity" in warehouse, "business partition formula")
check('"recalled_quantity": canonical_quantity(recalled)' in warehouse, "recalled summary")
check("has_location_inventory = (" in warehouse, "cost visibility tied to selected location inventory")
check('InventoryCostEvent.event_type == "PURCHASE_IN"' in warehouse, "purchase evidence query")
check(
    "latest_purchase_one" in warehouse
    and '.lateral("inventory_latest_purchase_one")' in warehouse,
    "latest purchase mapping",
)
check('"/warehouse/inventory/{product_variant_id}/batches"' in warehouse, "lazy batch details endpoint")
check('await access.require("inventory.read", location_id)' in warehouse, "batch details location permission")
check("InventoryBalance.location_id == location_id" in warehouse, "batch details warehouse scope")
check("InventoryBalance.company_id == company_id" in warehouse, "batch details tenant scope")
check("restricted = unavailable - explicit_unavailable" in warehouse, "batch unavailable breakdown")
check("latest_purchase_by_batch" in warehouse and "purchase_count_by_batch" in warehouse, "batch purchase evidence")
check("class WarehouseInventoryBatchDetailResponse" in schemas, "batch response schema")
check("last_purchase_cost" in schemas and "recalled_quantity" in schemas, "live-stock schema cost/status fields")
check("parseBatchDetailResponse" in contracts, "batch frontend contract")
check("LIVE_STOCK_BATCH_RESPONSE_INVALID" in contracts, "language-neutral contract error")
check("product.sku" not in live, "SKU hidden from live table")
check("lastCompanyPurchase" in live and "companyAverage" in live, "two main cost concepts")
check("latestBatchPurchase" in batches, "batch cost concept")
check(
    "HeaderHelp" in live
    and "onHandHint" in live
    and "reservedHint" in live
    and "availableForSaleHint" in live
    and "unavailableHint" in live
    and "withVehiclesHint" in live
    and "lastCompanyPurchaseHint" in live
    and "companyAverageHint" in live,
    "header business tooltips",
)
check("onHandHint" in resources and "reservedHint" in resources, "warehouse balance terminology hints")
check(
    "batch.recalled_quantity" in batches
    and "batch.damaged_quantity" in batches
    and "batch.disposal_pending_quantity" in batches,
    "exceptional stock details",
)
check('numberingSystem: "latn"' in money, "latin-number money display")
check("apiErrorMessage" in main and 't("inventoryLive.errors.loadFailed")' in main, "localized live-stock load error")
check('batchPanelTitle:' in resources, "live-stock i18n")
check('LIVE_STOCK_RESPONSE_INVALID:' in resources and 'LIVE_STOCK_BATCH_RESPONSE_INVALID:' in resources, "contract error translations")

print(f"CHECKS={checks}")
print(f"FAILURES={len(failures)}")
if failures:
    for failure in failures:
        print(f"FAIL: {failure}")
    print("STAGE77_LIVE_STOCK_PRODUCTION_GATE=FAIL")
    sys.exit(1)

print("STAGE77_LIVE_STOCK_PRODUCTION_GATE=PASS")
