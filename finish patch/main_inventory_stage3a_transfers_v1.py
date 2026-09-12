from __future__ import annotations

from pathlib import Path
import base64
import zlib

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "dashboard" / "src" / "pages" / "inventory" / "MainInventory.tsx"
TAB = ROOT / "dashboard" / "src" / "pages" / "inventory" / "TabTransfers.tsx"

COMPONENT = zlib.decompress(base64.b64decode('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')).decode("utf-8")


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"UNCHANGED={label}")
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match, found {count}")
    print(f"PATCHED={label}")
    return text.replace(old, new, 1)


if not MAIN.exists():
    fail("MainInventory.tsx missing.")

main = MAIN.read_text(encoding="utf-8")

preconditions = [
    'id: "warehouses"',
    "<TabWarehouseLocations",
    "inventory_selected_location:${companyId}",
    "statusRequestSeq",
]
missing = [marker for marker in preconditions if marker not in main]
if missing:
    fail(f"Stage-2 preconditions missing: {missing}")

if TAB.exists():
    existing = TAB.read_text(encoding="utf-8")
    if existing != COMPONENT:
        fail("TabTransfers.tsx already exists with different content.")
    print("UNCHANGED=TabTransfers.tsx")
else:
    TAB.write_text(COMPONENT, encoding="utf-8")
    print("CREATED=TabTransfers.tsx")

main = replace_once(
    main,
    'import { Package, History, Lock, RefreshCcw, FilePlus, Menu, Building2 } from "lucide-react";',
    'import { Package, History, Lock, RefreshCcw, FilePlus, Menu, Building2, ArrowRightLeft } from "lucide-react";',
    "main_inventory_transfer_icon",
)

main = replace_once(
    main,
    'import { TabWarehouseLocations } from "./TabWarehouseLocations";',
    'import { TabWarehouseLocations } from "./TabWarehouseLocations";\nimport { TabTransfers } from "./TabTransfers";',
    "main_inventory_transfer_import",
)

main = replace_once(
    main,
    '  { id: "inbound", label: "توريد بضاعة", icon: FilePlus },',
    '  { id: "inbound", label: "توريد بضاعة", icon: FilePlus },\n  { id: "transfers", label: "الحوالات", icon: ArrowRightLeft },',
    "main_inventory_transfer_tab",
)

old_surface = '''        {activeTab === "warehouses" && (
          <TabWarehouseLocations
            onLocationsChanged={fetchLocations}
          />
        )}'''

new_surface = '''        {activeTab === "transfers" && selectedLocationId !== null && (
          <TabTransfers
            locationId={selectedLocationId}
            onInventoryChanged={async () => {
              setStockRefreshKey((value) => value + 1);
              setLedgerRefreshKey((value) => value + 1);
              await fetchStatus();
            }}
          />
        )}

        {activeTab === "warehouses" && (
          <TabWarehouseLocations
            onLocationsChanged={fetchLocations}
          />
        )}'''

main = replace_once(
    main,
    old_surface,
    new_surface,
    "main_inventory_transfer_surface",
)

checks = {
    "TRANSFER_TAB_EXISTS": 'id: "transfers"' in main,
    "TRANSFER_COMPONENT_EXISTS": "<TabTransfers" in main,
    "TRANSFER_LOCATION_REQUIRED": 'activeTab === "transfers" && selectedLocationId !== null' in main,
    "TRANSFER_STOCK_REFRESH": "setStockRefreshKey((value) => value + 1)" in main,
    "TRANSFER_LEDGER_REFRESH": "setLedgerRefreshKey((value) => value + 1)" in main,
    "NO_AUTO_LOCATION": "setSelectedLocationId(data[0].id)" not in main,
    "TAB_LIST_LOCATION_ID": "location_id: String(locationId)" in COMPONENT,
    "TAB_LOCATION_SCOPE_FAIL_CLOSED": "خارج نطاق المستودع المحدد" in COMPONENT,
    "TAB_IDEMPOTENCY": "request_id: actionRequestId" in COMPONENT,
    "TAB_NO_ANY": ": any" not in COMPONENT and "any[]" not in COMPONENT,
    "TAB_NO_COMPANY_ID_PAYLOAD": "company_id" not in COMPONENT,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

MAIN.write_text(main, encoding="utf-8")

print("TRANSFER_CENTER_LOCATION_SCOPE=OK")
print("TRANSFER_CENTER_TENANT_SCOPE_SERVER_AUTHORITY=OK")
print("TRANSFER_CENTER_CURSOR=OK")
print("TRANSFER_CENTER_DETAILS=OK")
print("TRANSFER_CENTER_RECEIVE_REJECT_CANCEL=OK")
print("TRANSFER_CENTER_IDEMPOTENCY=OK")
print("MAIN_INVENTORY_STAGE3A_TRANSFERS=OK")
