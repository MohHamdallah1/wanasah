from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
WAREHOUSE = BACKEND / "api" / "warehouse" / "live_stock.py"
SCHEMAS = BACKEND / "schemas.py"
LIVE = ROOT / "dashboard" / "src" / "pages" / "inventory" / "Tab1LiveStock.tsx"
MAIN = ROOT / "dashboard" / "src" / "pages" / "inventory" / "MainInventory.tsx"
LIVE_STOCK_DIR = ROOT / "dashboard" / "src" / "pages" / "inventory" / "liveStock"
FILTERS = LIVE_STOCK_DIR / "LiveStockFilters.tsx"
TABLE = LIVE_STOCK_DIR / "LiveStockTable.tsx"
MOBILE = LIVE_STOCK_DIR / "LiveStockMobileCards.tsx"
CONTRACTS = LIVE_STOCK_DIR / "contracts.ts"

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(label)


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return ast.unparse(node)
    raise AssertionError(f"Missing function: {name}")


def vehicle_filter_v2_contract(filter_source: str, scope_source: str) -> bool:
    required_filter = (
        "if has_vehicle:",
        "_readable_vehicle_locations_subquery(",
        "InventoryBalance.product_variant_id",
        "InventoryBalance.location_id",
        "InventoryBalance.company_id == company_id",
        "InventoryBalance.on_hand_quantity > 0",
        "readable_vehicle_variants",
    )
    required_scope = (
        "InventoryLocation.company_id == company_id",
        "InventoryLocation.location_type == 'VEHICLE'",
        "InventoryLocation.is_active.is_(True)",
        "InventoryLocation.vehicle_id.isnot(None)",
        "access.location_filter('inventory.read')",
    )
    forbidden = (
        "DispatchRoute",
        "_latest_readable_vehicle_sources_subquery",
        "projection.vehicle_packs",
    )
    return (
        all(token in filter_source for token in required_filter)
        and all(token in scope_source for token in required_scope)
        and not any(token in filter_source for token in forbidden)
        and not any(token in scope_source for token in forbidden)
    )


warehouse = WAREHOUSE.read_text(encoding="utf-8")
schemas = SCHEMAS.read_text(encoding="utf-8")
live = LIVE.read_text(encoding="utf-8")
main = MAIN.read_text(encoding="utf-8")
filters = FILTERS.read_text(encoding="utf-8")
table = TABLE.read_text(encoding="utf-8")
mobile = MOBILE.read_text(encoding="utf-8")
contracts = CONTRACTS.read_text(encoding="utf-8")
SEARCH_MIGRATION = (
    BACKEND
    / "alembic"
    / "versions"
    / "d4a7c9e2f1b5_live_stock_native_trgm_search.py"
)
search_migration = SEARCH_MIGRATION.read_text(encoding="utf-8")

filter_contract = function_source(
    warehouse,
    "_live_stock_filtered_variant_ids_stmt",
)
vehicle_scope_contract = function_source(
    warehouse,
    "_readable_vehicle_locations_subquery",
)

for path, source in (
    (WAREHOUSE, warehouse),
    (SCHEMAS, schemas),
    (SEARCH_MIGRATION, search_migration),
):
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
    "projection.warehouse_on_hand" in filter_contract
    and "projection.warehouse_reserved" in filter_contract
    and "projection.warehouse_sellable_on_hand" in filter_contract
    and "projection.warehouse_sellable_reserved" in filter_contract
    and "projection.damaged_packs" in filter_contract
    and "projection.recalled_packs" in filter_contract
    and "projection.vehicle_packs" not in filter_contract,
    "Warehouse filters reuse selected-warehouse physical projection facts only",
)
check(
    vehicle_filter_v2_contract(filter_contract, vehicle_scope_contract),
    "Vehicle filter uses authorized physical VEHICLE InventoryBalance, never route attribution",
)

# Minimal gate selftests: current v2 source is the positive case; mutating the
# exact filter back toward the superseded route-source design must be rejected.
route_regression = filter_contract.replace(
    "_readable_vehicle_locations_subquery(",
    "_latest_readable_vehicle_sources_subquery(",
) + "\nDispatchRoute.source_location_id"
check(
    not vehicle_filter_v2_contract(route_regression, vehicle_scope_contract),
    "gate selftest rejects restored route-based Vehicle attribution",
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
    'className="live-stock-number-cell' in table
    and 'className="live-family-cell' in table
    and 't("inventoryLive.family")' in table,
    "number and family render as independent table columns",
)
check(
    "const activeFilterCount =" in filters
    and 'className="live-stock-filter-count tabular-nums">{activeFilterCount}' in filters
    and 'disabled={value === "low_stock" && alertCount === 0}' in filters,
    "filter button badge counts active filters while alert count only gates low-stock selection",
)
check(
    "live-stock-filter-popover--compact" in filters
    and "live-stock-family-popover" in filters
    and filters.index("live-stock-family-popover")
        > filters.index("live-stock-filter-popover--compact"),
    "family selection is a separate compact control outside the stock filter menu",
)
check(
    "sentinelRef" in live
    and "IntersectionObserver" in live
    and "onLoadMore()" in live
    and "handleStockLoadMore" in main
    and "...data.items.filter" in main,
    "cursor pages auto-load and append while scrolling instead of requiring manual next-page navigation",
)
check(
    "if (value === stockSearch) return;" in main
    and 'const emittedSearch = useRef("");' in filters
    and "if (next === emittedSearch.current) return;" in filters,
    "unchanged empty search cannot clear a freshly loaded Live Stock page",
)
check(
    "const nextLocationId = selected?.id ?? page.items[0]?.id ?? null;" in main
    and "setSelectedLocationId(nextLocationId);" in main
    and "setServerVerifiedLocationId(nextLocationId);" in main,
    "Live Stock automatically selects the server-verified warehouse or first accessible warehouse",
)
check(
    'search_patterns = [' in warehouse
    and 'f"%{_escape_like(token)}%"' in warehouse
    and 'func.public.live_stock_search_variant_ids(' in warehouse
    and 'ProductVariant.id.in_(search_variant_ids)' in warehouse,
    "Live Stock search delegates exact escaped substring matching to the tenant-scoped native search function",
)
check(
    'USING gin (' in search_migration
    and 'company_id,' in search_migration
    and 'gin_trgm_ops' in search_migration
    and 'SECURITY DEFINER' in search_migration
    and 'SET search_path = pg_catalog, pg_temp' in search_migration
    and 'SET row_security = off' in search_migration
    and "'app.current_tenant'" in search_migration
    and 'expected_company_id IS DISTINCT FROM tenant_id' in search_migration
    and 'REVOKE ALL ON FUNCTION' in search_migration
    and 'GRANT EXECUTE ON FUNCTION' in search_migration,
    "native trigram search function is tenant-bound and security-definer hardened",
)
check(
    'ProductVariant.company_id == company_id' in warehouse
    and 'InventoryLiveStockProjection.company_id' in warehouse
    and '== ProductVariant.company_id' in warehouse
    and 'InventoryLiveStockProjection.warehouse_location_id' in warehouse
    and '== location_id' in warehouse,
    "Live Stock outer query keeps explicit tenant and selected-warehouse isolation",
)
check(
    "LIVE_STOCK_SEARCH_TOO_SHORT" in warehouse
    and "LIVE_STOCK_FAMILY_SEARCH_TOO_SHORT" in warehouse
    and "LIVE_STOCK_FAMILY_INVALID" in warehouse,
    "Live Stock validation errors use stable localizable error codes",
)
check(
    '[product.available_for_sale_quantity, "text-emerald-700", "available"]' in table
    and '["availableForSale", product.available_for_sale_quantity, "text-emerald-700", "available"]' in mobile,
    "available-for-sale quantity keeps explicit desktop/mobile visual emphasis",
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
