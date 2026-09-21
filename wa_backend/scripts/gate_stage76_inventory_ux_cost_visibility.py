from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
checks = []

def check(condition: bool, label: str) -> None:
    checks.append((bool(condition), label))

ledger_source = (ROOT / "wa_backend/api/warehouse/ledger.py").read_text(encoding="utf-8")
live_stock_source = (ROOT / "wa_backend/api/warehouse/live_stock.py").read_text(encoding="utf-8")
schemas = (ROOT / "wa_backend/schemas.py").read_text(encoding="utf-8")
inbound = (ROOT / "dashboard/src/pages/inventory/Tab2Inbound.tsx").read_text(encoding="utf-8")
contracts = (ROOT / "dashboard/src/pages/inventory/inbound/contracts.ts").read_text(encoding="utf-8")
live = (ROOT / "dashboard/src/pages/inventory/Tab1LiveStock.tsx").read_text(encoding="utf-8")
ledger = (ROOT / "dashboard/src/pages/inventory/Tab4Ledger.tsx").read_text(encoding="utf-8")
main_inventory = (ROOT / "dashboard/src/pages/inventory/MainInventory.tsx").read_text(encoding="utf-8")
operations = (ROOT / "dashboard/src/pages/OperationsDashboard.tsx").read_text(encoding="utf-8")
resources = (ROOT / "dashboard/src/i18n/resources.ts").read_text(encoding="utf-8")

check("documentDefaults" in inbound and "defaultBatchTitle" in inbound, "document batch default UI")
check(inbound.count("commercialUoms") >= 2 and "variantOptions?.uoms.filter" in inbound, "persisted inbound row uses commercial default safely")
check("defaults.batch_number" in contracts, "batch default resolved in payload builder")
check("seenBatchUoms" in contracts and "INBOUND_DUPLICATE_BATCH_UOM_LINE" in contracts, "same batch supports distinct UOM lines")
check(
    '"balance_scope": (' in ledger_source
    and '"PRODUCT_LOCATION"' in ledger_source
    and "aggregate_snapshot is not None" in ledger_source,
    "ledger balance is product/location scoped",
)
check("_ledger_product_location_snapshots" in ledger_source, "ledger reconstructs product/location totals")
check("InventoryCostEvent" in ledger_source and "InventoryCostState" in live_stock_source, "cost evidence and current state sources")
check("display_uom_code" in schemas and "display_factor_to_base" in schemas, "commercial display UOM contract")
check("formatCommercialQuantity" in live, "commercial quantity display")
check("defaultValue: p.display_uom_name" not in live, "live UOM labels cannot fall back to backend language")
check("formatQuantity(p.available_quantity, p.base_uom_name)" not in live, "live stock does not expose raw backend UOM names")
check("inventoryLedger.balanceBefore" in ledger and "inventoryLedger.balanceAfter" in ledger, "ledger labels total product balance")
check("locationAccess.isPending" in main_inventory and 't("common.loading")' in main_inventory, "warehouse switch has translated loading state")
check("parseDriverDataList(data)" in operations, "operations response validated before setState")
check(resources.count("OPERATIONS_RESPONSE_INVALID") >= 2, "operations error translated ar/en")
check(resources.count("defaultBatchTitle") >= 2, "batch-default UI translated ar/en")
check(
    resources.count("lastCompanyPurchaseHint") >= 2
    and resources.count("companyAverageHint") >= 2,
    "cost visibility translated ar/en",
)
check(resources.count("inventoryCommon") >= 2 and resources.count('unit: "') >= 2, "generic unit fallback translated ar/en")
check(resources.count("addReceiptLine") >= 2, "mixed-UOM add-line action translated ar/en")
check(resources.count("INBOUND_DUPLICATE_BATCH_UOM_LINE") >= 2, "mixed-UOM duplicate error translated ar/en")

failures = [label for ok, label in checks if not ok]
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
for label in failures:
    print(f"FAIL: {label}")
if failures:
    print("STAGE76_INVENTORY_UX_COST_VISIBILITY_GATE=FAIL")
    raise SystemExit(1)
print("STAGE76_INVENTORY_UX_COST_VISIBILITY_GATE=PASS")
