from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "wa_backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    print(("[PASS] " if condition else "[FAIL] ") + label)
    if not condition:
        failures.append(label)


def main() -> int:
    from api.simple_products import derive_unit_price

    sidebar = (
        ROOT
        / "dashboard/src/components/operations/OperationsSidebar.tsx"
    ).read_text(encoding="utf-8")
    app = (ROOT / "dashboard/src/App.tsx").read_text(encoding="utf-8")
    inventory = (
        ROOT / "dashboard/src/pages/inventory/MainInventory.tsx"
    ).read_text(encoding="utf-8")
    page = (
        ROOT / "dashboard/src/pages/ProductsDashboard.tsx"
    ).read_text(encoding="utf-8")
    backend = (
        BACKEND / "api/simple_products.py"
    ).read_text(encoding="utf-8")
    main_py = (BACKEND / "main.py").read_text(encoding="utf-8")
    db_manager = (BACKEND / "db_manager.py").read_text(encoding="utf-8")

    check(
        derive_unit_price(
            Decimal("17.500"),
            50,
        ) == Decimal("0.350000"),
        "Carton-only input derives exact six-decimal unit price",
    )
    check(
        derive_unit_price(
            Decimal("10"),
            3,
        ) == Decimal("3.333333"),
        "Non-divisible carton price uses the pricing money authority",
    )
    check(
        'label: "المنتجات"' in sidebar
        and 'path: "/products"' in sidebar
        and 'label: "التسعير التجاري"' not in sidebar,
        "Sidebar exposes Products and hides advanced pricing",
    )
    check(
        '<Route path="/products" element={<ProductsDashboard />} />'
        in app
        and '<Route path="/pricing" element={<Navigate to="/products" replace />} />'
        in app
        and "PricingDashboard" not in app,
        "Legacy pricing route is frozen behind Products",
    )
    check(
        'id: "catalog"' not in inventory
        and "TabProductCatalog" not in inventory,
        "Technical catalog is hidden from Inventory",
    )
    check(
        "حفظ المنتج والسعر" in page
        and "استيراد CSV" in page
        and "سعر الحبة المحسوب" in page,
        "Visible workflow is one-step product plus carton price",
    )
    check(
        'UOM.code.in_(("EACH", "CARTON"))' in backend
        and "packs_per_carton=int(item.units_per_carton)" in backend
        and "from_uom_id=int(carton.id)" in backend
        and "to_uom_id=int(each.id)" in backend,
        "Simple creation writes exact EACH/CARTON packaging authority",
    )
    check(
        "create_publication(" in backend
        and "create_draft_entry(" in backend
        and "publish_publication(" in backend
        and "carton_price" in backend
        and "derived_from" in backend,
        "Simple API preserves temporal pricing instead of live price columns",
    )
    check(
        "SIMPLE_PRODUCTS_ADVANCED_PRICING_ACTIVE" in backend
        and "SIMPLE_PRODUCTS_FUTURE_PRICING_ACTIVE" in backend,
        "Simple mode fails closed when advanced pricing is active",
    )
    check(
        "MAX_IMPORT_ROWS = 200" in backend
        and 'operation="SIMPLE_PRODUCT_CSV_IMPORT"' in backend,
        "CSV import is bounded and idempotent",
    )
    check(
        "simple_products" in main_py
        and "app.include_router(simple_products.router)" in main_py,
        "Simple Products API is registered",
    )
    check(
        "allow_offers=True" in db_manager,
        "Development seed remains compatible with assignment policy",
    )

    print()
    print(f"CHECKS={checks}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL: {failure}")

    if failures:
        print("STAGE7_SIMPLE_PRODUCTS_GATE=FAIL")
        return 1

    print("STAGE7_SIMPLE_PRODUCTS_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
