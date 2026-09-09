from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
TAB = ROOT / "dashboard" / "src" / "pages" / "inventory" / "TabTransfers.tsx"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"
WAREHOUSE = ROOT / "wa_backend" / "api" / "warehouse.py"


def fail(message: str) -> None:
    raise SystemExit(f"TRANSFER_FINAL_GATE=FAIL\n{message}")


def require(condition: bool, label: str) -> None:
    if not condition:
        fail(f"{label}=FAIL")
    print(f"{label}=OK")


def route_block(source: str, path: str) -> str:
    marker = f'"{path}"'
    idx = source.find(marker)
    if idx < 0:
        fail(f"ROUTE_MISSING={path}")

    start = source.rfind("@router.", 0, idx)
    if start < 0:
        fail(f"ROUTE_DECORATOR_MISSING={path}")

    end = source.find("\n@router.", idx + len(marker))
    if end < 0:
        end = len(source)

    return source[start:end]


def async_function_block(source: str, name: str) -> str:
    marker = f"async def {name}("
    start = source.find(marker)
    if start < 0:
        fail(f"FUNCTION_MISSING={name}")

    candidates = [
        pos
        for pos in (
            source.find("\nasync def ", start + len(marker)),
            source.find("\n@router.", start + len(marker)),
        )
        if pos >= 0
    ]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


for path in (TAB, SCHEMAS, WAREHOUSE):
    if not path.exists():
        fail(f"MISSING_FILE={path.relative_to(ROOT)}")

tab = TAB.read_text(encoding="utf-8").replace("\r\n", "\n")
schemas = SCHEMAS.read_text(encoding="utf-8").replace("\r\n", "\n")
warehouse = WAREHOUSE.read_text(encoding="utf-8").replace("\r\n", "\n")

# Python syntax gate. This is read-only.
try:
    compile(schemas, str(SCHEMAS), "exec")
    compile(warehouse, str(WAREHOUSE), "exec")
except SyntaxError as exc:
    fail(f"PYTHON_SYNTAX=FAIL {exc}")

print("PYTHON_SYNTAX=OK")

# ------------------------------------------------------------------
# Frontend: tenant/location identity + transport contracts
# ------------------------------------------------------------------
require("company_id" not in tab, "FRONTEND_NO_COMPANY_ID")
require(": any" not in tab and "any[]" not in tab, "FRONTEND_NO_EXPLICIT_ANY")
require("location_id: String(locationId)" in tab, "TRANSFER_LIST_LOCATION_ID_REQUIRED")
require(
    "transfer.source_location_id !== expectedLocationId" in tab
    and "transfer.destination_location_id !== expectedLocationId" in tab,
    "TRANSFER_DETAIL_LOCATION_SCOPE_FAIL_CLOSED",
)
require(
    'transfer.status !== "IN_TRANSIT"' in tab,
    "TRANSFER_ACTION_STATUS_GATE",
)
require(
    'nextAction === "cancel" && !isSource' in tab
    and '(nextAction === "receive" || nextAction === "reject")' in tab
    and "!isDestination" in tab,
    "TRANSFER_ACTION_ROLE_GATE",
)

# ------------------------------------------------------------------
# Frontend: idempotent dispatch + FEFO
# ------------------------------------------------------------------
require(
    "request_id: createRequestId" in tab
    and "source_location_id: sourceLocationId" in tab
    and "destination_location_id: destinationLocationId" in tab,
    "TRANSFER_DISPATCH_IDEMPOTENT_LOCATION_IDS",
)
require(
    "request_id: actionRequestId" in tab,
    "TRANSFER_DECISION_IDEMPOTENCY",
)
require(
    'type FefoMode = "auto" | "override"' in tab
    and "is_fefo_override: true" in tab
    and "override_batch_id:" in tab
    and "override_reason_id:" in tab,
    "FEFO_OVERRIDE_PAYLOAD_CONTRACT",
)
require(
    "لا يجوز خلط FEFO التلقائي وتجاوز FEFO لنفس الصنف." in tab,
    "FEFO_NO_MIXED_MODE_PER_PRODUCT",
)
require(
    "/warehouse/unified/transfer/override-options?" in tab
    and "location_id: String(sourceLocationId)" in tab
    and "product_variant_id: String(productId)" in tab,
    "FEFO_OVERRIDE_OPTIONS_LOCATION_PRODUCT_SCOPE",
)
require(
    "options.location_id !== sourceLocationId" in tab
    and "options.product_variant_id !== item.product_variant_id" in tab,
    "FEFO_OVERRIDE_OPTIONS_REVALIDATED",
)
require(
    "addOverrideBatchLine" in tab,
    "FEFO_MULTI_BATCH_OVERRIDE_SUPPORTED",
)

# ------------------------------------------------------------------
# Frontend scalability / race safety
# ------------------------------------------------------------------
require(
    "sourceProductsNextCursor" in tab
    and 'params.set("cursor", pageCursor)' in tab
    and "تحميل المزيد" in tab,
    "SOURCE_INVENTORY_CURSOR_CONSUMED",
)
require(
    "new Map<number, TransferSourceInventoryItem>()" in tab,
    "SOURCE_INVENTORY_CURSOR_DEDUP",
)
require(
    "sourceProductsRequestSeq.current" in tab,
    "SOURCE_INVENTORY_RACE_GUARD",
)
require(
    "transferLocationSearchInput" in tab
    and 'params.set("search", transferLocationSearch)' in tab,
    "TRANSFER_LOCATION_SERVER_SEARCH",
)
require(
    "transferLocationsRequestSeq.current" in tab
    and "new Map<number, TransferLocationOption>()" in tab,
    "TRANSFER_LOCATION_SEARCH_RACE_DEDUP",
)
require(
    "void fetchSourceProducts(null, false);" in tab,
    "SOURCE_PRODUCT_FIRST_PAGE_EXPLICIT",
)

# ------------------------------------------------------------------
# Schema contracts
# ------------------------------------------------------------------
for class_name in (
    "UnifiedDispatchRequest",
    "UnifiedReceiveRequest",
    "UnifiedTransferDecisionRequest",
    "WarehouseTransferCursorPage",
    "WarehouseTransferDetail",
    "UnifiedTransferLocationItem",
    "UnifiedTransferSourceInventoryCursorPage",
    "UnifiedTransferOverrideOptionsResponse",
):
    require(
        f"class {class_name}" in schemas,
        f"SCHEMA_{class_name.upper()}",
    )

# ------------------------------------------------------------------
# Backend route uniqueness
# ------------------------------------------------------------------
paths = (
    "/warehouse/unified/transfer/locations",
    "/warehouse/unified/transfer/source-inventory",
    "/warehouse/unified/transfer/override-options",
    "/warehouse/unified/transfers",
    "/warehouse/unified/transfers/{transfer_id}",
    "/warehouse/unified/transfer/dispatch",
    "/warehouse/unified/transfer/receive",
    "/warehouse/unified/transfer/{header_id}/cancel",
    "/warehouse/unified/transfer/{header_id}/reject",
)
for path in paths:
    require(
        warehouse.count(f'"{path}"') == 1,
        f"ROUTE_UNIQUE_{path}",
    )

location_route = route_block(
    warehouse,
    "/warehouse/unified/transfer/locations",
)
source_route = route_block(
    warehouse,
    "/warehouse/unified/transfer/source-inventory",
)
override_route = route_block(
    warehouse,
    "/warehouse/unified/transfer/override-options",
)
list_route = route_block(
    warehouse,
    "/warehouse/unified/transfers",
)
detail_route = route_block(
    warehouse,
    "/warehouse/unified/transfers/{transfer_id}",
)
dispatch_route = route_block(
    warehouse,
    "/warehouse/unified/transfer/dispatch",
)
receive_route = route_block(
    warehouse,
    "/warehouse/unified/transfer/receive",
)
cancel_route = route_block(
    warehouse,
    "/warehouse/unified/transfer/{header_id}/cancel",
)
reject_route = route_block(
    warehouse,
    "/warehouse/unified/transfer/{header_id}/reject",
)

# ------------------------------------------------------------------
# Backend tenant isolation / bounded reads
# ------------------------------------------------------------------
require(
    "current_admin: Driver = Depends(get_current_admin)" in location_route
    and "InventoryLocation.company_id == company_id" in location_route
    and "InventoryLocation.is_active.is_(True)" in location_route
    and "['WAREHOUSE', 'VEHICLE']" in location_route,
    "LOCATION_OPTIONS_TENANT_ACTIVE_TYPE_SCOPE",
)
require(
    "limit: int = Query(default=50, ge=1, le=100)" in location_route
    and ".limit(limit)" in location_route
    and "search: Optional[str]" in location_route
    and "func.lower(InventoryLocation.name).like" in location_route
    and "func.lower(InventoryLocation.code).like" in location_route,
    "LOCATION_OPTIONS_BOUNDED_SEARCHABLE",
)

require(
    "location_id: int = Query(..., ge=1)" in source_route
    and "InventoryLocation.company_id == company_id" in source_route
    and "InventoryLocation.id == location_id" in source_route,
    "SOURCE_INVENTORY_LOCATION_TENANT_SCOPE",
)
require(
    "ProductVariant.company_id == company_id" in source_route
    and "InventoryBalance.company_id == company_id" in source_route
    and "InventoryBalance.location_id == location_id" in source_route,
    "SOURCE_INVENTORY_PRODUCT_BALANCE_TENANT_SCOPE",
)
require(
    "ProductBatch.is_active.is_(True)" in source_route
    and "ProductBatch.expiry_date >= as_of_date" in source_route
    and "ProductBatch.production_date <= as_of_date" in source_route,
    "SOURCE_INVENTORY_BATCH_ELIGIBILITY",
)
require(
    "~active_lock_exists" in source_route,
    "SOURCE_INVENTORY_STOCKTAKE_LOCK_AWARE",
)
require(
    "cursor: Optional[str]" in source_route
    and "_decode_variant_cursor(" in source_route
    and "_encode_variant_cursor(" in source_route
    and ".limit(limit + 1)" in source_route,
    "SOURCE_INVENTORY_CURSOR_BACKEND",
)

require(
    "location_id: int = Query(..., ge=1)" in override_route
    and "product_variant_id: int = Query(..., ge=1)" in override_route,
    "OVERRIDE_OPTIONS_LOCATION_PRODUCT_REQUIRED",
)
require(
    "InventoryLocation.company_id == company_id" in override_route
    and "ProductVariant.company_id == company_id" in override_route
    and "ProductBatch.company_id == company_id" in override_route
    and "InventoryBalance.company_id == company_id" in override_route
    and "OverrideReason.company_id == company_id" in override_route,
    "OVERRIDE_OPTIONS_FULL_TENANT_SCOPE",
)
require(
    "OverrideReason.is_active.is_(True)" in override_route
    and "ProductBatch.is_active.is_(True)" in override_route
    and "~active_lock_exists" in override_route,
    "OVERRIDE_OPTIONS_ACTIVE_LOCK_SCOPE",
)
require(
    "ProductBatch.expiry_date.asc()" in override_route
    and "ProductBatch.id.asc()" in override_route,
    "OVERRIDE_OPTIONS_FEFO_ORDER",
)

# ------------------------------------------------------------------
# Existing transfer reads must stay location-scoped.
# ------------------------------------------------------------------
require(
    "location_id: int = Query(..., ge=1)" in list_route
    and "InventoryTransferHeader.company_id == company_id" in list_route,
    "TRANSFER_LIST_BACKEND_TENANT_LOCATION_SCOPE",
)
require(
    "InventoryTransferHeader.company_id == company_id" in detail_route,
    "TRANSFER_DETAIL_BACKEND_TENANT_SCOPE",
)

# ------------------------------------------------------------------
# Mutations: company isolation + SSOT movement engine + idempotency
# ------------------------------------------------------------------
for name, block, operation in (
    ("DISPATCH", dispatch_route, "WAREHOUSE_TRANSFER_DISPATCH"),
    ("RECEIVE", receive_route, "WAREHOUSE_TRANSFER_RECEIVE"),
    ("CANCEL", cancel_route, "WAREHOUSE_TRANSFER_CANCEL"),
    ("REJECT", reject_route, "WAREHOUSE_TRANSFER_REJECT"),
):
    require(
        "company_id = current_admin.company_id" in block,
        f"{name}_COMPANY_CONTEXT",
    )
    require(
        operation in block
        and "begin_idempotent_operation(" in block
        and "request_id=str(payload.request_id)" in block,
        f"{name}_IDEMPOTENCY_BACKEND",
    )

move_from_transit = async_function_block(
    warehouse,
    "_move_transfer_lines_from_transit",
)

require(
    "apply_inventory_movements_batch(" in dispatch_route,
    "DISPATCH_USES_UNIFIED_MOVEMENT_ENGINE",
)
require(
    "_move_transfer_lines_from_transit(" in receive_route,
    "RECEIVE_USES_TRANSIT_MOVE_HELPER",
)
require(
    "_move_transfer_lines_from_transit(" in cancel_route,
    "CANCEL_USES_TRANSIT_MOVE_HELPER",
)
require(
    "_move_transfer_lines_from_transit(" in reject_route,
    "REJECT_USES_TRANSIT_MOVE_HELPER",
)
require(
    "apply_inventory_movements_batch(" in move_from_transit
    and "company_id=company_id" in move_from_transit,
    "TRANSIT_MOVE_HELPER_USES_UNIFIED_MOVEMENT_ENGINE",
)

require(
    "InventoryLocation.company_id == company_id" in dispatch_route,
    "DISPATCH_LOCATION_TENANT_SCOPE",
)
require(
    "ProductVariant.company_id == company_id" in dispatch_route,
    "DISPATCH_PRODUCT_TENANT_SCOPE",
)
require(
    "OverrideReason.company_id == company_id" in dispatch_route
    and "ProductBatch.company_id == company_id" in dispatch_route,
    "DISPATCH_OVERRIDE_REASON_BATCH_TENANT_SCOPE",
)
require(
    "allocate_fefo_inventory_batch(" in dispatch_route,
    "DISPATCH_AUTO_FEFO_ENGINE",
)

# Direct InventoryBalance writes are forbidden in the transfer mutation blocks.
for name, block in (
    ("DISPATCH", dispatch_route),
    ("RECEIVE", receive_route),
    ("CANCEL", cancel_route),
    ("REJECT", reject_route),
):
    direct_write_patterns = (
        "InventoryBalance.on_hand_quantity =",
        "InventoryBalance.reserved_quantity =",
        "update(InventoryBalance)",
    )
    require(
        not any(pattern in block for pattern in direct_write_patterns),
        f"{name}_NO_DIRECT_INVENTORYBALANCE_WRITE",
    )

print("TRANSFER_FINAL_GATE=PASS")
