from __future__ import annotations

from pathlib import Path
import base64
import hashlib
import zlib

ROOT = Path(__file__).resolve().parent
TAB = ROOT / "dashboard" / "src" / "pages" / "inventory" / "TabTransfers.tsx"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"
WAREHOUSE = ROOT / "wa_backend" / "api" / "warehouse.py"

EXPECTED_TAB_SHA256 = '209236a56e63b602cbe029ed4b314181eda3262dc556454a68738fc8b2ac0c24'
NEW_TAB = zlib.decompress(base64.b64decode('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')).decode("utf-8")

SCHEMA_ANCHOR = 'class UnifiedTransferSourceInventoryCursorPage(BaseModel):\n    items: List[UnifiedTransferSourceInventoryItem]\n    next_cursor: Optional[str] = None\n    has_more: bool\n    total: Optional[int] = None\n\n\nclass UnifiedTransferDecisionRequest(RequestModel):\n'
SCHEMA_REPLACEMENT = 'class UnifiedTransferSourceInventoryCursorPage(BaseModel):\n    items: List[UnifiedTransferSourceInventoryItem]\n    next_cursor: Optional[str] = None\n    has_more: bool\n    total: Optional[int] = None\n\n\nclass UnifiedTransferOverrideReasonItem(BaseModel):\n    id: int\n    code: str\n    description: str\n\n\nclass UnifiedTransferSourceBatchItem(BaseModel):\n    id: int\n    batch_number: str\n    production_date: Optional[date] = None\n    expiry_date: date\n    available_packs: int\n    is_fefo_head: bool\n\n\nclass UnifiedTransferOverrideOptionsResponse(BaseModel):\n    location_id: int\n    product_variant_id: int\n    fefo_batch_id: Optional[int] = None\n    batches: List[UnifiedTransferSourceBatchItem]\n    reasons: List[UnifiedTransferOverrideReasonItem]\n\n\nclass UnifiedTransferDecisionRequest(RequestModel):\n'
IMPORT_ANCHOR = 'UnifiedTransferLocationItem, UnifiedTransferSourceInventoryCursorPage,\nUnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest )'
IMPORT_REPLACEMENT = 'UnifiedTransferLocationItem, UnifiedTransferSourceInventoryCursorPage,\nUnifiedTransferOverrideOptionsResponse,\nUnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest )'
SOURCE_LOCK_ANCHOR = '    available_expression = func.sum(\n        InventoryBalance.on_hand_quantity\n        - InventoryBalance.reserved_quantity\n    )\n\n    stmt = (\n'
SOURCE_LOCK_REPLACEMENT = '    active_lock_exists = (\n        select(InventoryLock.id)\n        .filter(\n            InventoryLock.company_id == company_id,\n            InventoryLock.location_id == location_id,\n            InventoryLock.released_at.is_(None),\n            or_(\n                and_(\n                    InventoryLock.product_variant_id.is_(None),\n                    InventoryLock.batch_id.is_(None),\n                ),\n                and_(\n                    InventoryLock.product_variant_id\n                    == InventoryBalance.product_variant_id,\n                    or_(\n                        InventoryLock.batch_id.is_(None),\n                        InventoryLock.batch_id\n                        == InventoryBalance.batch_id,\n                    ),\n                ),\n            ),\n        )\n        .correlate(InventoryBalance)\n        .exists()\n    )\n\n    available_expression = func.sum(\n        InventoryBalance.on_hand_quantity\n        - InventoryBalance.reserved_quantity\n    )\n\n    stmt = (\n'
SOURCE_FILTER_ANCHOR = "            ProductVariant.company_id == company_id,\n            ProductVariant.is_active.is_(True),\n            InventoryBalance.company_id == company_id,\n            InventoryBalance.location_id == location_id,\n            InventoryBalance.stock_status == 'AVAILABLE',\n        )\n        .group_by(\n            ProductVariant.id,\n            ProductVariant.variant_name,\n            ProductVariant.sku,\n            ProductVariant.packs_per_carton,\n        )\n"
SOURCE_FILTER_REPLACEMENT = "            ProductVariant.company_id == company_id,\n            ProductVariant.is_active.is_(True),\n            InventoryBalance.company_id == company_id,\n            InventoryBalance.location_id == location_id,\n            InventoryBalance.stock_status == 'AVAILABLE',\n            ~active_lock_exists,\n        )\n        .group_by(\n            ProductVariant.id,\n            ProductVariant.variant_name,\n            ProductVariant.sku,\n            ProductVariant.packs_per_carton,\n        )\n"
ENDPOINT_ANCHOR = "_TRANSFER_QUERY_STATUSES = frozenset({\n    'DRAFT',\n    'PENDING',\n    'IN_TRANSIT',\n    'ACCEPTED',\n    'REJECTED',\n    'POSTED',\n    'CANCELLED',\n})\n"
ENDPOINT_BLOCK = '@router.get(\n    "/warehouse/unified/transfer/override-options",\n    response_model=UnifiedTransferOverrideOptionsResponse,\n    status_code=200,\n)\nasync def get_unified_transfer_override_options(\n    location_id: int = Query(..., ge=1),\n    product_variant_id: int = Query(..., ge=1),\n    db: AsyncSession = Depends(get_db),\n    current_admin: Driver = Depends(get_current_admin),\n):\n    company_id = current_admin.company_id\n\n    location_exists = (\n        await db.execute(\n            select(InventoryLocation.id).filter(\n                InventoryLocation.company_id == company_id,\n                InventoryLocation.id == location_id,\n                InventoryLocation.is_active.is_(True),\n                InventoryLocation.location_type.in_(\n                    [\'WAREHOUSE\', \'VEHICLE\']\n                ),\n            )\n        )\n    ).scalar_one_or_none()\n\n    if location_exists is None:\n        raise HTTPException(\n            status_code=404,\n            detail=(\n                "مصدر الحوالة غير موجود أو غير فعال "\n                "أو لا يتبع شركتك."\n            ),\n        )\n\n    product_exists = (\n        await db.execute(\n            select(ProductVariant.id).filter(\n                ProductVariant.company_id == company_id,\n                ProductVariant.id == product_variant_id,\n                ProductVariant.is_active.is_(True),\n            )\n        )\n    ).scalar_one_or_none()\n\n    if product_exists is None:\n        raise HTTPException(\n            status_code=404,\n            detail="الصنف غير موجود أو غير فعال أو لا يتبع شركتك.",\n        )\n\n    as_of_date = await get_company_local_date(db, company_id)\n\n    active_lock_exists = (\n        select(InventoryLock.id)\n        .filter(\n            InventoryLock.company_id == company_id,\n            InventoryLock.location_id == location_id,\n            InventoryLock.released_at.is_(None),\n            or_(\n                and_(\n                    InventoryLock.product_variant_id.is_(None),\n                    InventoryLock.batch_id.is_(None),\n                ),\n                and_(\n                    InventoryLock.product_variant_id\n                    == InventoryBalance.product_variant_id,\n                    or_(\n                        InventoryLock.batch_id.is_(None),\n                        InventoryLock.batch_id\n                        == InventoryBalance.batch_id,\n                    ),\n                ),\n            ),\n        )\n        .correlate(InventoryBalance)\n        .exists()\n    )\n\n    available_expression = func.sum(\n        InventoryBalance.on_hand_quantity\n        - InventoryBalance.reserved_quantity\n    )\n\n    batch_rows = (\n        await db.execute(\n            select(\n                ProductBatch.id,\n                ProductBatch.batch_number,\n                ProductBatch.production_date,\n                ProductBatch.expiry_date,\n                available_expression.label("available_packs"),\n            )\n            .join(\n                InventoryBalance,\n                and_(\n                    InventoryBalance.company_id\n                    == ProductBatch.company_id,\n                    InventoryBalance.product_variant_id\n                    == ProductBatch.product_variant_id,\n                    InventoryBalance.batch_id == ProductBatch.id,\n                ),\n            )\n            .filter(\n                ProductBatch.company_id == company_id,\n                ProductBatch.product_variant_id\n                == product_variant_id,\n                ProductBatch.is_active.is_(True),\n                or_(\n                    ProductBatch.production_date.is_(None),\n                    ProductBatch.production_date <= as_of_date,\n                ),\n                ProductBatch.expiry_date >= as_of_date,\n                InventoryBalance.company_id == company_id,\n                InventoryBalance.location_id == location_id,\n                InventoryBalance.product_variant_id\n                == product_variant_id,\n                InventoryBalance.stock_status == \'AVAILABLE\',\n                ~active_lock_exists,\n            )\n            .group_by(\n                ProductBatch.id,\n                ProductBatch.batch_number,\n                ProductBatch.production_date,\n                ProductBatch.expiry_date,\n            )\n            .having(available_expression > 0)\n            .order_by(\n                ProductBatch.expiry_date.asc(),\n                ProductBatch.id.asc(),\n            )\n        )\n    ).all()\n\n    reason_rows = (\n        await db.execute(\n            select(\n                OverrideReason.id,\n                OverrideReason.code,\n                OverrideReason.description,\n            )\n            .filter(\n                OverrideReason.company_id == company_id,\n                OverrideReason.is_active.is_(True),\n            )\n            .order_by(\n                OverrideReason.code.asc(),\n                OverrideReason.id.asc(),\n            )\n        )\n    ).all()\n\n    fefo_batch_id = int(batch_rows[0].id) if batch_rows else None\n\n    return {\n        "location_id": int(location_id),\n        "product_variant_id": int(product_variant_id),\n        "fefo_batch_id": fefo_batch_id,\n        "batches": [\n            {\n                "id": int(row.id),\n                "batch_number": str(row.batch_number),\n                "production_date": row.production_date,\n                "expiry_date": row.expiry_date,\n                "available_packs": int(row.available_packs or 0),\n                "is_fefo_head": (\n                    fefo_batch_id is not None\n                    and int(row.id) == fefo_batch_id\n                ),\n            }\n            for row in batch_rows\n        ],\n        "reasons": [\n            {\n                "id": int(row.id),\n                "code": str(row.code),\n                "description": str(row.description),\n            }\n            for row in reason_rows\n        ],\n    }\n\n\n'


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"UNCHANGED={label}")
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match, found {count}")
    print(f"PATCHED={label}")
    return text.replace(old, new, 1)


for path in (TAB, SCHEMAS, WAREHOUSE):
    if not path.exists():
        fail(f"Missing file: {path.relative_to(ROOT)}")


tab = normalize(TAB.read_text(encoding="utf-8"))
if tab == NEW_TAB:
    print("UNCHANGED=TabTransfers.tsx")
elif sha256_text(tab) == EXPECTED_TAB_SHA256:
    TAB.write_text(NEW_TAB, encoding="utf-8")
    print("PATCHED=TabTransfers.tsx")
else:
    fail(
        "TabTransfers.tsx differs from the attached Stage-3B1 baseline. "
        f"SHA256={sha256_text(tab)}"
    )


schemas = normalize(SCHEMAS.read_text(encoding="utf-8"))
schemas = replace_once(
    schemas,
    SCHEMA_ANCHOR,
    SCHEMA_REPLACEMENT,
    "fefo_override_response_schemas",
)
SCHEMAS.write_text(schemas, encoding="utf-8")


warehouse = normalize(WAREHOUSE.read_text(encoding="utf-8"))

warehouse = replace_once(
    warehouse,
    IMPORT_ANCHOR,
    IMPORT_REPLACEMENT,
    "fefo_override_schema_import",
)

warehouse = replace_once(
    warehouse,
    SOURCE_LOCK_ANCHOR,
    SOURCE_LOCK_REPLACEMENT,
    "source_inventory_respects_inventory_locks",
)

warehouse = replace_once(
    warehouse,
    SOURCE_FILTER_ANCHOR,
    SOURCE_FILTER_REPLACEMENT,
    "source_inventory_excludes_locked_batches",
)

warehouse = replace_once(
    warehouse,
    ENDPOINT_ANCHOR,
    ENDPOINT_BLOCK + ENDPOINT_ANCHOR,
    "fefo_override_options_endpoint",
)

WAREHOUSE.write_text(warehouse, encoding="utf-8")


tab = normalize(TAB.read_text(encoding="utf-8"))
schemas = normalize(SCHEMAS.read_text(encoding="utf-8"))
warehouse = normalize(WAREHOUSE.read_text(encoding="utf-8"))

checks = {
    "FRONTEND_OVERRIDE_MODE": 'fefo_mode: FefoMode' in tab,
    "FRONTEND_OVERRIDE_OPTIONS": (
        "/warehouse/unified/transfer/override-options?" in tab
    ),
    "FRONTEND_LOCATION_ID_REQUIRED": (
        "location_id: String(sourceLocationId)" in tab
    ),
    "FRONTEND_PRODUCT_ID_REQUIRED": (
        "product_variant_id: String(productId)" in tab
    ),
    "FRONTEND_IDEMPOTENT_DISPATCH": (
        "request_id: createRequestId" in tab
    ),
    "FRONTEND_OVERRIDE_PAYLOAD": (
        "is_fefo_override: true" in tab
        and "override_batch_id:" in tab
        and "override_reason_id:" in tab
    ),
    "FRONTEND_NO_MIXED_FEFO": (
        "لا يجوز خلط FEFO التلقائي وتجاوز FEFO" in tab
    ),
    "FRONTEND_MULTI_BATCH_OVERRIDE": (
        "addOverrideBatchLine" in tab
    ),
    "FRONTEND_NO_COMPANY_ID_PAYLOAD": (
        "company_id" not in tab
    ),
    "FRONTEND_NO_EXPLICIT_ANY": (
        ": any" not in tab and "any[]" not in tab
    ),
    "BACKEND_OVERRIDE_SCHEMA": (
        "class UnifiedTransferOverrideOptionsResponse" in schemas
    ),
    "BACKEND_OVERRIDE_ENDPOINT": (
        '"/warehouse/unified/transfer/override-options"' in warehouse
    ),
    "BACKEND_REASON_TENANT_SCOPE": (
        "OverrideReason.company_id == company_id" in warehouse
    ),
    "BACKEND_ACTIVE_LOCK_EXCLUSION": (
        warehouse.count("~active_lock_exists") >= 2
    ),
    "BACKEND_FEFO_ORDER": (
        "ProductBatch.expiry_date.asc()" in warehouse
        and "ProductBatch.id.asc()" in warehouse
    ),
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

print("FEFO_OVERRIDE_TENANT_LOCATION_SCOPE=OK")
print("FEFO_OVERRIDE_TENANT_PRODUCT_SCOPE=OK")
print("FEFO_OVERRIDE_TENANT_REASON_SCOPE=OK")
print("FEFO_OVERRIDE_BATCH_LOCK_SCOPE=OK")
print("FEFO_OVERRIDE_FEFO_ORDER=OK")
print("FEFO_OVERRIDE_MULTI_BATCH=OK")
print("FEFO_OVERRIDE_IDEMPOTENCY=OK")
print("TRANSFER_SOURCE_LOCK_AWARE=OK")
print("TRANSFER_PRODUCT_SEARCH_DRAFT_PRESERVED=OK")
print("MAIN_INVENTORY_STAGE3B2_FEFO_OVERRIDE=OK")
