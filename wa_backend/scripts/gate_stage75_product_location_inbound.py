from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "wa_backend" / "api" / "warehouse" / "inbound.py"
PLAN = ROOT / "INVENTORY_COMMERCIAL_FOUNDATION_PLAN.md"
RULES = ROOT / ".rules"
SIMPLE_PRODUCTS = ROOT / "wa_backend" / "domains" / "simple_products" / "service.py"
I18N = ROOT / "dashboard" / "src" / "i18n" / "resources.ts"
MODEL = ROOT / "wa_backend" / "models.py"
STAGE3_GATE = ROOT / "wa_backend" / "scripts" / "gate_stage3_lifecycle.py"

checks: list[tuple[str, bool]] = []

def check(name: str, condition: bool) -> None:
    checks.append((name, bool(condition)))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")

warehouse = WAREHOUSE.read_text(encoding="utf-8")
plan = PLAN.read_text(encoding="utf-8")
rules = RULES.read_text(encoding="utf-8")
simple_products = SIMPLE_PRODUCTS.read_text(encoding="utf-8")
i18n = I18N.read_text(encoding="utf-8")
model = MODEL.read_text(encoding="utf-8")
stage3 = STAGE3_GATE.read_text(encoding="utf-8")

check("company-wide product authority recorded", "Product catalog identity is company-wide" in rules)
check("no mass product-to-warehouse provisioning", "Never mass-provision every product into every warehouse" in rules)
check("first successful inbound lifecycle recorded", "أول Inbound ناجح للمستودع المختار" in plan)
check("simple product service still has no ProductLocation writes", "ProductLocation(" not in simple_products and "product_locations" not in simple_products)
check("inbound helper exists", "async def _ensure_first_inbound_product_locations(" in warehouse)
check("lazy assignment uses unique conflict guard", '.on_conflict_do_nothing(\n                    constraint="uq_product_location_assignment"' in warehouse)
check("lazy assignment uses default operational flags", "dict(DEFAULT_PRODUCT_LOCATION_FLAGS)" in warehouse)
check("lazy assignment is audited", 'reason="AUTO_FIRST_INBOUND"' in warehouse and 'event_type="ProductLocationAssigned"' in warehouse)
check("selected inbound location permission remains explicit", "await access.require('inbound.create', payload.location_id)" in warehouse)
check("selected inbound target excludes system locations", "location_type='WAREHOUSE',\n                    is_system_managed=False,\n                    is_active=True" in warehouse)
check("variant lookup is company scoped", "ProductVariant.company_id == company_id" in warehouse)
check("missing/cross-tenant variants fail closed", '"INBOUND_VARIANT_UNAVAILABLE"' in warehouse and "found_variant_ids != requested_var_ids" in warehouse)
check("product location lookup is sparse outer join", ").outerjoin(\n                    ProductLocation," in warehouse)
check("existing disabled flag remains authoritative", "row.operational_flags is not None" in warehouse and '"PRODUCT_LOCATION_INBOUND_DISABLED"' in warehouse)
check("old hidden assignment blocker removed from inbound", "Every product must be assigned to the warehouse before inbound." not in warehouse)
check("helper called only by inbound workflow", warehouse.count("await _ensure_first_inbound_product_locations(") == 1)
permission_pos = warehouse.find("await access.require('inbound.create', payload.location_id)")
helper_pos = warehouse.find("await _ensure_first_inbound_product_locations(")
check("warehouse permission precedes lazy assignment", permission_pos != -1 and helper_pos != -1 and permission_pos < helper_pos)
check("Arabic inbound unavailable translation exists", 'INBOUND_VARIANT_UNAVAILABLE: "أحد المنتجات لم يعد فعالاً أو لا يتبع شركتك."' in i18n)
check("English inbound unavailable translation exists", 'INBOUND_VARIANT_UNAVAILABLE: "A product is no longer active or does not belong to your company."' in i18n)
check("tenant-safe unique product-location constraint exists", "uq_product_location_assignment" in model)
check("stage3 RLS gate covers product_locations", "RLS isolation on product_locations" in stage3)

failures = [name for name, passed in checks if not passed]
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
if failures:
    for name in failures:
        print(f"FAILED_CHECK={name}")
    raise SystemExit(1)
print("STAGE75_PRODUCT_LOCATION_INBOUND_GATE=PASS")
