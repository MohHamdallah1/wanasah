from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
WAREHOUSE = BACKEND / "api" / "warehouse.py"
SCHEMAS = BACKEND / "schemas.py"
LIVE = ROOT / "dashboard" / "src" / "pages" / "inventory" / "Tab1LiveStock.tsx"
MAIN = ROOT / "dashboard" / "src" / "pages" / "inventory" / "MainInventory.tsx"
CONTRACTS = ROOT / "dashboard" / "src" / "pages" / "inventory" / "liveStock" / "contracts.ts"

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(label)


warehouse = WAREHOUSE.read_text(encoding="utf-8")
schemas = SCHEMAS.read_text(encoding="utf-8")
live = LIVE.read_text(encoding="utf-8")
main = MAIN.read_text(encoding="utf-8")
contracts = CONTRACTS.read_text(encoding="utf-8")

for path, source in ((WAREHOUSE, warehouse), (SCHEMAS, schemas)):
    try:
        ast.parse(source)
    except SyntaxError as exc:
        failures.append(f"PYTHON_SYNTAX:{path.name}:{exc.lineno}:{exc.msg}")

check(
    "from typing import Literal" in warehouse
    or "from typing import Literal," in warehouse
    or ", Literal" in warehouse,
    "Live Stock filter type contract imports Literal at runtime",
)

check(
    'stock_state: Literal[' in warehouse
    and 'family_id: Optional[int] = None' in warehouse
    and 'has_reserved: bool = False' in warehouse
    and 'has_unavailable: bool = False' in warehouse
    and 'has_damaged: bool = False' in warehouse
    and 'has_recalled: bool = False' in warehouse
    and 'has_vehicle: bool = False' in warehouse
    and 'minimum_unset: bool = False' in warehouse,
    "server owns the full Live Stock filter contract",
)
check(
    "_live_stock_filtered_variant_ids_stmt(" in warehouse
    and "ProductVariant.id.in_(filtered_ids)" in warehouse,
    "filters are applied in SQL before page LIMIT",
)
check(
    "projection.warehouse_reserved" in warehouse
    and "projection.damaged_packs" in warehouse
    and "projection.recalled_packs" in warehouse
    and "projection.vehicle_packs" in warehouse,
    "filters reuse projection facts instead of reaggregating ledger rows",
)
check(
    "if company_wide_inventory_read:" in warehouse
    and "_readable_vehicle_locations_subquery(" in warehouse
    and "variant.id.in_(readable_vehicle_variants)" in warehouse,
    "vehicle filter remains permission-aware for restricted actors",
)
check(
    '"/warehouse/inventory/families"' in warehouse
    and "_require_live_stock_warehouse_read(" in warehouse,
    "family lookup is tenant/access scoped",
)
check(
    'sort: Literal["name_asc", "name_desc"]' in warehouse
    and 'if sort == "name_desc"' in warehouse
    and "cursor_key < cursor_value" in warehouse
    and "cursor_key > cursor_value" in warehouse,
    "sort direction is encoded into stable cursor seek semantics",
)
check(
    '"product_id": int(row["product_id"])' in warehouse
    and '"family_name": str(row["family_name"])' in warehouse
    and "product_id: PositiveDbInt" in schemas
    and "family_name:" in schemas,
    "Live Stock response carries authoritative family metadata",
)
check(
    'params.set("stock_state", stockState)' in main
    and 'params.set("family_id", String(stockFamilyId))' in main
    and 'params.set("has_damaged", "true")' in main
    and 'params.set("has_vehicle", "true")' in main,
    "Dashboard sends filters to the backend rather than filtering the current 50 rows",
)
check(
    'className="live-stock-number-cell"' in live
    and 'className="live-family-cell' in live
    and 't("inventoryLive.family")' in live,
    "number and family render as independent table columns",
)
check(
    "activeFilterCount" in live
    and "alertCount" in live
    and "filterLowStockCount" in live,
    "filter button count is active-filter count while low-stock count stays inside the menu",
)
check(
    "live-stock-filter-popover--compact" in live
    and "live-stock-family-popover" in live
    and live.index("live-stock-family-popover")
        > live.index("live-stock-filter-popover--compact"),
    "family selection is a separate compact control outside the stock filter menu",
)
check(
    "loadMoreSentinelRef" in live
    and "IntersectionObserver" in live
    and "onLoadMore()" in live
    and "handleStockLoadMore" in main
    and "...data.items.filter" in main,
    "cursor pages auto-load and append while scrolling instead of requiring manual next-page navigation",
)
check(
    "parseLiveStockFamilies" in contracts
    and "product_id: number;" in contracts
    and "family_name: string;" in contracts,
    "frontend response parser fails closed on family metadata",
)

print(f"CHECKS={checks}")
print(f"FAILURES={len(failures)}")
for failure in failures:
    print(f"FAIL: {failure}")

if failures:
    print("LIVE_STOCK_FILTER_CONTRACT_GATE=FAIL")
    sys.exit(1)

print("LIVE_STOCK_FILTER_CONTRACT_GATE=PASS")
