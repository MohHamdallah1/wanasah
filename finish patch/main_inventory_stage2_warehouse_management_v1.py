from __future__ import annotations

from pathlib import Path
import base64
import zlib

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "dashboard" / "src" / "pages" / "inventory" / "MainInventory.tsx"
NEW = ROOT / "dashboard" / "src" / "pages" / "inventory" / "TabWarehouseLocations.tsx"
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
    fail("MainInventory.tsx missing")

main = MAIN.read_text(encoding="utf-8")

preconditions = [
    "inventory_selected_location:${companyId}",
    "const fetchLocations = useCallback(async () => {",
    "selectedLocationId === null && (",
    "statusRequestSeq",
]
missing = [marker for marker in preconditions if marker not in main]
if missing:
    fail(f"MainInventory Stage-1 preconditions missing: {missing}")

if NEW.exists():
    existing = NEW.read_text(encoding="utf-8")
    if existing != COMPONENT:
        fail("TabWarehouseLocations.tsx already exists with different content.")
    print("UNCHANGED=TabWarehouseLocations.tsx")
else:
    NEW.write_text(COMPONENT, encoding="utf-8")
    print("CREATED=TabWarehouseLocations.tsx")

main = replace_once(
    main,
    'import { Package, History, Lock, RefreshCcw, FilePlus, Menu } from "lucide-react";',
    'import { Package, History, Lock, RefreshCcw, FilePlus, Menu, Building2 } from "lucide-react";',
    "main_inventory_warehouse_icon",
)

main = replace_once(
    main,
    'import { Tab4Ledger } from "./Tab4Ledger";',
    'import { Tab4Ledger } from "./Tab4Ledger";\nimport { TabWarehouseLocations } from "./TabWarehouseLocations";',
    "main_inventory_warehouse_tab_import",
)

main = replace_once(
    main,
    '  { id: "stocktake", label: "جرد وتسوية", icon: Lock },',
    '  { id: "stocktake", label: "جرد وتسوية", icon: Lock },\n  { id: "warehouses", label: "إدارة المستودعات", icon: Building2 },',
    "main_inventory_warehouse_tab_config",
)

empty_block = """  if (locations.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full bg-slate-50/50 rounded-3xl border border-slate-200 p-8 text-center">
        <div className="w-24 h-24 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mb-6 shadow-inner">
          <Package className="w-10 h-10" />
        </div>
        <h2 className="text-2xl font-black text-slate-800 mb-2">
          لا يوجد مستودع فعال
        </h2>
        <p className="text-slate-500 font-bold max-w-md">
          الشركة الحالية لا تملك مستودعاً فعالاً يمكن تنفيذ عمليات المخزون عليه.
        </p>
      </div>
    );
  }
"""

replacement = """  useEffect(() => {
    if (
      !loadingLocations &&
      !locationError &&
      locations.length === 0 &&
      activeTab !== "warehouses"
    ) {
      setActiveTab("warehouses");
    }
  }, [activeTab, loadingLocations, locationError, locations.length]);

"""

main = replace_once(
    main,
    empty_block,
    replacement,
    "warehouse_management_reachable_without_active_location",
)

main = replace_once(
    main,
    """        {selectedLocationId === null && (
          <div className="flex-1 flex items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white/50 text-slate-500 font-bold">
            اختر مستودعاً صراحةً قبل عرض أو تنفيذ أي عملية مخزنية.
          </div>
        )}""",
    """        {selectedLocationId === null && activeTab !== "warehouses" && (
          <div className="flex-1 flex items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white/50 text-slate-500 font-bold">
            لا يوجد مستودع محدد لهذه العملية. اختر مستودعاً فعالاً أو افتح إدارة المستودعات.
          </div>
        )}""",
    "warehouse_tab_bypasses_location_gate",
)

main = replace_once(
    main,
    """        {activeTab === "ledger" && selectedLocationId !== null && (
          <Tab4Ledger
            locationId={selectedLocationId}
            refreshKey={ledgerRefreshKey}
          />
        )}""",
    """        {activeTab === "ledger" && selectedLocationId !== null && (
          <Tab4Ledger
            locationId={selectedLocationId}
            refreshKey={ledgerRefreshKey}
          />
        )}

        {activeTab === "warehouses" && (
          <TabWarehouseLocations
            onLocationsChanged={fetchLocations}
          />
        )}""",
    "warehouse_management_tab_surface",
)

checks = {
    "WAREHOUSE_TAB_EXISTS": 'id: "warehouses"' in main,
    "WAREHOUSE_TAB_COMPONENT": "<TabWarehouseLocations" in main,
    "NO_ACTIVE_LOCATION_REQUIRED_FOR_MANAGEMENT": 'activeTab !== "warehouses"' in main,
    "ZERO_ACTIVE_AUTO_MANAGEMENT": 'setActiveTab("warehouses")' in main,
    "LOCATION_LIST_SERVER_DRIVEN": 'authFetch("/warehouse/locations")' in main,
    "NO_AUTO_FIRST_LOCATION": "setSelectedLocationId(data[0].id)" not in main,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

MAIN.write_text(main, encoding="utf-8")

print("WAREHOUSE_MANAGEMENT_SURFACE=OK")
print("WAREHOUSE_MANAGEMENT_ZERO_ACTIVE_RECOVERY=OK")
print("WAREHOUSE_MANAGEMENT_IDEMPOTENCY=OK")
print("WAREHOUSE_MANAGEMENT_LOCATION_ID_ACTIONS=OK")
print("MAIN_INVENTORY_STAGE2_WAREHOUSE_MANAGEMENT=OK")
