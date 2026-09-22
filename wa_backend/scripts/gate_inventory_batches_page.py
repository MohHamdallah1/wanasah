from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "dashboard" / "src" / "pages" / "inventory" / "MainInventory.tsx"
LIVE = ROOT / "dashboard" / "src" / "pages" / "inventory" / "Tab1LiveStock.tsx"
BATCHES = ROOT / "dashboard" / "src" / "pages" / "inventory" / "TabBatches.tsx"
CONTRACTS = ROOT / "dashboard" / "src" / "pages" / "inventory" / "liveStock" / "contracts.ts"

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(label)


main = MAIN.read_text(encoding="utf-8")
live = LIVE.read_text(encoding="utf-8")
batches = BATCHES.read_text(encoding="utf-8")
contracts = CONTRACTS.read_text(encoding="utf-8")

check(
    '{ id: "batches", labelKey: "inventoryShell.tabs.batches"' in main
    and "batches: 'inventory.read'" in main
    and 'activeTab === "batches"' in main
    and "<TabBatches" in main,
    "dedicated batches page is wired and protected by inventory.read",
)

check(
    "/batches?location_id=" not in live
    and "loadBatchDetails" not in live
    and "openBatchDetails" not in live
    and "ChevronDown" not in live,
    "Live Stock no longer embeds batch-detail expansion",
)

check(
    "/batches?${params.toString()}" in batches
    and "limit: String(BATCH_PAGE_SIZE)" in batches
    and 'if (pageCursor) params.set("cursor", pageCursor)' in batches
    and "parseBatchDetailResponse" in batches
    and "parsed.location_id !== locationId" in batches
    and "parsed.product_variant_id !== selectedProduct.id" in batches,
    "batch page uses bounded cursor requests and validates warehouse/product scope",
)

check(
    "details.has_more && details.next_cursor" in batches
    and "inventoryBatches.loadMoreBatches" in batches
    and "current.batches.map" in batches
    and "next_cursor: string | null" in contracts
    and "has_more: boolean" in contracts
    and "page.has_more !== (nextCursor !== null)" in contracts,
    "batch page appends bounded pages with a fail-closed cursor contract",
)

check(
    "/warehouse/inventory/cursor?" in batches
    and "parseLiveStockPage" in batches
    and 'params.set("search", search)' in batches,
    "batch page product selector uses the existing server-side cursor/search path",
)

check(
    "restricted_quantity" in batches
    and "quarantined_quantity" in batches
    and "blocked_quantity" in batches
    and "recalled_quantity" in batches
    and "damaged_quantity" in batches
    and "disposal_pending_quantity" in batches,
    "batch page preserves current restriction-state visibility",
)

check(
    "latest_purchase_cost" in batches
    and "purchase_event_count" in batches
    and "days_to_expiry" in batches,
    "batch page preserves current purchase evidence and expiry logic",
)

check(
    "export function parseBatchDetailResponse" in contracts,
    "existing fail-closed batch response parser remains the shared contract",
)

print(f"CHECKS={checks}")
print(f"FAILURES={len(failures)}")
for failure in failures:
    print(f"FAIL: {failure}")

if failures:
    print("INVENTORY_BATCHES_PAGE_GATE=FAIL")
    sys.exit(1)

print("INVENTORY_BATCHES_PAGE_GATE=PASS")
