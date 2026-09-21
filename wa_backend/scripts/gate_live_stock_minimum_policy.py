from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(label)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


api = read("wa_backend/api/inventory_stock_policy.py")
main = read("wa_backend/main.py")
live = read("dashboard/src/pages/inventory/Tab1LiveStock.tsx")
quantity = read("dashboard/src/pages/inventory/quantity.ts")
manager = read("dashboard/src/pages/inventory/StockMinimumManager.tsx")
seed = read("wa_backend/scripts/seed_live_stock_demo.py")

check(
    "inventory_stock_policy" in main
    and "app.include_router(inventory_stock_policy.router" in main,
    "minimum-stock router is wired into the application",
)
check(
    '@router.put(\n    "/warehouse/inventory/{product_variant_id}/minimum-stock"' in api,
    "minimum-stock mutation has a dedicated endpoint",
)
check(
    "if not bool(current_admin.is_admin):" in api
    and "STOCK_MINIMUM_ADMIN_REQUIRED" in api,
    "only the company administrator can mutate the minimum",
)
check(
    'await access.require("inventory.read", int(payload.location_id))' in api,
    "mutation remains scoped to an accessible warehouse",
)
check(
    "ProductLocation.company_id == company_id" in api
    and "ProductLocation.location_id == int(payload.location_id)" in api
    and "ProductLocation.product_variant_id == int(product_variant_id)" in api,
    "threshold can only be set for a product assigned to the warehouse",
)
check(
    "ProductUomConversion.from_uom_id == int(uom_id)" in api
    and "ProductUomConversion.to_uom_id == int(base_uom_id)" in api
    and "validate_variant_quantity(" in api,
    "display-unit input is converted and validated against the product quantity authority",
)
check(
    "pg_advisory_xact_lock" in api
    and ".with_for_update()" in api,
    "create/update policy path is serialized",
)
check(
    "expected_minimum_quantity" in api
    and "STOCK_MINIMUM_VERSION_CONFLICT" in api,
    "minimum-stock updates reject stale page state",
)
check(
    "STOCK_MINIMUM_EXCEEDS_TARGET" in api
    and "policy.target_quantity" in api,
    "minimum stock cannot silently invalidate an existing target quantity",
)
check(
    'operation="LIVE_STOCK_MINIMUM_UPDATE"' in api
    and "complete_idempotent_operation" in api,
    "minimum-stock mutation is idempotent",
)
check(
    'action_type="LIVE_STOCK_MINIMUM_UPDATED"' in api
    and "SystemAuditLog(" in api,
    "minimum-stock changes are audited",
)
check(
    "await refresh_live_stock_keys(" in api,
    "projection and alert summary refresh transactionally after a threshold change",
)
check(
    "product.available_for_sale_quantity" in live
    and "product.minimum_quantity" in live
    and "bg-red-50/45" in live,
    "Live Stock still marks sellable quantity at/below minimum in red",
)
check(
    'className="live-stock-toolbar-search-group"' in live
    and live.index('className="live-stock-toolbar-search-group"')
        < live.index('className="live-stock-context-panel"'),
    "search/filter group is ordered before the warehouse context group",
)
check(
    "formatCommercialQuantity" in quantity
    and "remainder === 0n" in quantity,
    "Live Stock commercial quantity formatting preserves carton-plus-loose-unit remainders",
)
check(
    '"/warehouse/inventory/minimum-stock/bulk/preview"' in api
    and '"/warehouse/inventory/minimum-stock/bulk"' in api
    and 'operation="LIVE_STOCK_MINIMUM_BULK_UPDATE"' in api,
    "bulk minimum-stock workflow has preview, apply and idempotency",
)
check(
    'scope: Literal["ALL", "FAMILY", "PRODUCT"]' in api
    and 'family_ids: list[int]' in api
    and 'product_variant_ids: list[int]' in api
    and 'apply_mode: Literal["ONLY_UNSET", "OVERWRITE"]' in api
    and 'ProductVariant.product_id.in_(payload.family_ids)' in api
    and 'ProductVariant.id.in_(payload.product_variant_ids)' in api,
    "bulk minimum-stock scope supports safe multi-select family/product targeting",
)
check(
    "pg_advisory_xact_lock" in api
    and "LIVE_STOCK_MINIMUM_BULK_UPDATED" in api
    and "for offset in range(0, len(keys), 5000)" in api,
    "bulk updates serialize, audit and refresh projection keys in bounded chunks",
)
check(
    "StockMinimumManager" in live
    and "scopeAll" in manager
    and "scopeFamily" in manager
    and "scopeProduct" in manager
    and "familyIds" in manager
    and "productIds" in manager
    and "toggleId" in manager
    and "ONLY_UNSET" in manager
    and "OVERWRITE" in manager,
    "Live Stock exposes one centralized multi-select minimum-stock manager",
)
check(
    'if (!scopeReady || !quantityReady || applying || hasConflict) return;' in manager
    and '!plan ||' not in manager,
    "minimum-stock preview is optional and direct apply remains available",
)
check(
    "product.sku" not in live,
    "SKU stays available in contracts/search but is not rendered in Live Stock rows",
)
check(
    "2520" in seed
    and "DEMO_FAMILIES" in seed
    and "batch_count = 1 + (index % 3)" in seed
    and "index % 9 != 0" in seed,
    "rich demo data covers loose units, families, multiple batches and unset minimums",
)

print(f"CHECKS={checks}")
print(f"FAILURES={len(failures)}")
if failures:
    for failure in failures:
        print(f"FAIL: {failure}")
    print("LIVE_STOCK_MINIMUM_POLICY_GATE=FAIL")
    sys.exit(1)

print("LIVE_STOCK_MINIMUM_POLICY_GATE=PASS")
