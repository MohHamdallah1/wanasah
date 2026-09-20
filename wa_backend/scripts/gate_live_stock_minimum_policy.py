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
    "convertBaseQuantityToUom" in quantity
    and "numerator % factorScaled !== 0n" in quantity,
    "minimum editor converts base quantity to display UOM without floating-point rounding",
)

print(f"CHECKS={checks}")
print(f"FAILURES={len(failures)}")
if failures:
    for failure in failures:
        print(f"FAIL: {failure}")
    print("LIVE_STOCK_MINIMUM_POLICY_GATE=FAIL")
    sys.exit(1)

print("LIVE_STOCK_MINIMUM_POLICY_GATE=PASS")
