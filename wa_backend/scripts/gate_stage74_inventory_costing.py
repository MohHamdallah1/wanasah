from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
checks = 0
failures: list[str] = []


def check(condition: bool, label: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(label)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


models = read("wa_backend/models.py")
services = read("wa_backend/services.py")
warehouse = read("wa_backend/api/warehouse/inbound.py")
driver = read("wa_backend/api/driver.py")
dispatch = read("wa_backend/api/dispatch.py")
platform = read("wa_backend/api/platform_manager.py")
access = read("wa_backend/inventory_access.py")
schemas = read("wa_backend/schemas.py")
costing = read("wa_backend/domains/inventory_costing/service.py")
migration = read("wa_backend/alembic/versions/fa7c9d3e1b24_stage74_inventory_costing.py")
inbound_ui = read("dashboard/src/pages/inventory/Tab2Inbound.tsx")
inbound_contract = read("dashboard/src/pages/inventory/inbound/contracts.ts")
i18n = read("dashboard/src/i18n/resources.ts")
rules = read(".rules")
agents = read("AGENTS.md")

for name in (
    "InventoryCostPolicy",
    "InventoryCostState",
    "InventoryCostEvent",
    "InventoryCostLayer",
    "InventoryCostAllocation",
):
    check(f"class {name}(Base):" in models, f"model missing: {name}")

check('revision = "fa7c9d3e1b24"' in migration, "migration revision")
check('down_revision = "f9d2b4c6a8e1"' in migration, "migration predecessor")
for table in (
    "inventory_cost_policies",
    "inventory_cost_states",
    "inventory_cost_events",
    "inventory_cost_layers",
    "inventory_cost_allocations",
):
    check(table in migration, f"migration table {table}")
check("ENABLE ROW LEVEL SECURITY" in migration and "FORCE ROW LEVEL SECURITY" in migration, "RLS force")
check("prevent_inventory_cost_history_mutation" in migration, "append-only cost history")
check("REVOKE UPDATE, DELETE, TRUNCATE" in migration, "runtime history grants")

check('COST_METHODS = frozenset({"MOVING_AVERAGE", "FIFO"})' in costing, "cost methods")
check("Physical FEFO batch" in costing, "physical/financial authority note")
check("Financial FIFO intentionally follows acquisition" in costing, "FIFO decoupling note")
check("InventoryCostLayer.product_variant_id.in_(consume_variant_ids)" in costing, "FIFO product-wide layer query")
check("InventoryCostLayer.batch_id.in_" not in costing, "FIFO not coupled to physical batch")
check("INVENTORY_COST_RECONCILIATION_FAILED" in costing, "cost/physical reconciliation")
check("ORIGINAL_REVERSAL" in costing and "cost_reversal_of_movement_id" in services, "exact reversal linkage")
check("validate_inventory_costing_replays" in services, "cost replay validation")
check("apply_inventory_costing_for_movements" in services, "cost engine wired to movement engine")

check("unit_cost: InventoryCostMoneyInput" in schemas, "inbound purchase cost schema")
check("class InboundOptionsRequest" in schemas, "bounded inbound options schema")
check("class InventoryCostPolicyUpdateRequest" in schemas, "cost policy schema")
check("/warehouse/inbound/options" in warehouse, "inbound UOM options endpoint")
check("/warehouse/costing-policy" in warehouse, "cost policy endpoints")
check("build_purchase_cost_input" in warehouse, "receipt cost normalization")
check("activate_costing_for_first_receipt" in warehouse, "first receipt locks method")
check(
    "seen_batch_uoms" in warehouse
    and "INBOUND_DUPLICATE_BATCH_UOM_LINE" in warehouse
    and "seen_batch_uoms.add(line_key)" in warehouse,
    "no silent duplicate batch/UOM aggregation",
)
check("ProductUomConversion" in warehouse, "purchase UOM conversion authority")

check('"VISIT_SAMPLE_OUT"' in driver, "sample movement type")
check('ctx["sale_base_quantity"]' in driver and 'ctx["sample_base_quantity"]' in driver, "sale/sample quantities split")
check('"VISIT_SAMPLE_OUT"' in dispatch, "dispatch projection includes samples")
check("VISIT_OUTBOUND_INVENTORY_REFERENCE_TYPES" in driver, "driver projection centralized outbound types")

check("create_price_book" in platform and "create_assignment" in platform, "new tenant default selling price authority")
check("provision_default_cost_policy" in platform, "new tenant default cost policy")
check('code="DEFAULT"' in platform, "empty default price book code")
check("create_draft_entry" not in platform, "no fake price entries on tenant creation")
check("inventory.costing.manage" in access, "cost method permission")

check("useTranslation" in inbound_ui and 'dir={i18n.dir()}' in inbound_ui, "inbound i18n/direction")
check("getOrCreateDurableRequestId" in inbound_ui, "durable cost-policy mutation")
check("unit_cost" in inbound_contract and "uom_id" in inbound_contract, "frontend cost/UOM contract")
check("inventoryInbound" in i18n and "COST_OPENING_BALANCE_REQUIRED" in i18n, "localized Stage 7.4 UX/errors")

check("Physical batch allocation and financial cost flow are separate authorities" in rules, "rules architecture invariant")
check("Physical batch allocation and financial cost flow are separate authorities" in agents, "agents architecture invariant")

print(f"CHECKS={checks}")
print(f"FAILURES={len(failures)}")
if failures:
    for failure in failures:
        print(f"FAIL: {failure}")
    print("STAGE74_INVENTORY_COSTING_GATE=FAIL")
    sys.exit(1)
print("STAGE74_INVENTORY_COSTING_GATE=PASS")
