from __future__ import annotations

from pathlib import Path
import base64
import hashlib
import zlib

ROOT = Path(__file__).resolve().parent
INV = ROOT / "dashboard" / "src" / "pages" / "inventory"
TAB = INV / "Tab3Stocktake.tsx"
TYPES = INV / "stocktake" / "types.ts"
PARSERS = INV / "stocktake" / "parsers.ts"
CENTER = INV / "stocktake" / "StocktakeSessionCenter.tsx"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"
WAREHOUSE = ROOT / "wa_backend" / "api" / "warehouse.py"

BASELINE = {'Tab3Stocktake.tsx': '00dac8c968051efd3fbea2bcdda77329a21425eb', 'stocktake/types.ts': '0c326a0a62b64880505d408fa2f0b61d618e8a31', 'stocktake/parsers.ts': 'e5271ab413c2ccce48d92f552b763954ce3cbc15', 'stocktake/StocktakeSessionCenter.tsx': '6bf1f6c33102325bc8e52a6086c3201ce7251c25'}
PAYLOADS = {'stocktake/hooks/useCycleCountStart.ts': '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', 'stocktake/StocktakeCycleStartModal.tsx': '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'}


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def normalize_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"UNCHANGED={label}")
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected exactly 1 match, found {count}. No files changed.")
    print(f"PATCHED={label}")
    return text.replace(old, new, 1)


def decode(name: str) -> str:
    return zlib.decompress(base64.b64decode(PAYLOADS[name])).decode("utf-8")


for relative, expected in BASELINE.items():
    path = INV / relative
    if not path.exists():
        fail(f"Missing frontend baseline file: {relative}")
    actual = git_blob_sha(normalize_bytes(path))
    if actual != expected:
        fail(
            f"Frontend baseline mismatch for {relative}: "
            f"expected {expected}, got {actual}. No files changed."
        )

for path in (SCHEMAS, WAREHOUSE):
    if not path.exists():
        fail(f"Missing backend file: {path.relative_to(ROOT)}")

schemas = read(SCHEMAS)
warehouse = read(WAREHOUSE)
backend_prereqs = {
    "ACTIVE_SESSION_SCHEMA": "class StocktakeActiveSessionCursorPage(BaseModel):" in schemas,
    "ACTIVE_SESSION_IMPORT": "StocktakeActiveSessionCursorPage," in warehouse,
    "ACTIVE_SESSION_ROUTE": "/warehouse/unified/stocktakes/active" in warehouse,
    "STOCKTAKE_START_ROUTE": "/warehouse/unified/stocktake/start" in warehouse,
    "CYCLE_CONTRACT": "CYCLE_COUNT" in schemas and "product_variant_id" in schemas,
    "CYCLE_BATCH_ROUTE_NOT_PRESENT": "/warehouse/unified/stocktake/cycle-batches" not in warehouse,
}
missing = [name for name, ok in backend_prereqs.items() if not ok]
if missing:
    fail("Backend prerequisites failed: " + ", ".join(missing))

new_targets = {INV / relative: decode(relative) for relative in PAYLOADS}
for path, expected in new_targets.items():
    if path.exists():
        current = read(path)
        if current != expected:
            fail(
                "Refusing to overwrite existing different file: "
                f"{path.relative_to(ROOT)}. No files changed."
            )

schema_anchor = "class UnifiedStocktakeStartRequest(RequestModel):"
schema_block = '''class StocktakeCycleBatchItem(BaseModel):
    id: int
    product_variant_id: int
    batch_number: str
    production_date: Optional[date] = None
    expiry_date: date
    is_active: bool


class StocktakeCycleBatchCursorPage(BaseModel):
    items: List[StocktakeCycleBatchItem]
    next_cursor: Optional[str] = None
    has_more: bool
    total: Optional[int] = None


'''
if "class StocktakeCycleBatchItem(BaseModel):" not in schemas:
    if schemas.count(schema_anchor) != 1:
        fail("Could not locate unique UnifiedStocktakeStartRequest schema anchor.")
    schemas = schemas.replace(schema_anchor, schema_block + schema_anchor, 1)
    print("PATCHED=stocktake_cycle_batch_schemas")
else:
    print("UNCHANGED=stocktake_cycle_batch_schemas")

warehouse = replace_once(
    warehouse,
    "StocktakeActiveSessionCursorPage,\nUnifiedStocktakeCountRequest",
    "StocktakeActiveSessionCursorPage,\nStocktakeCycleBatchCursorPage,\nUnifiedStocktakeCountRequest",
    "stocktake_cycle_batch_schema_import",
)

endpoint_anchor = "_ACTIVE_STOCKTAKE_STATUSES = frozenset({"
endpoint_block = r'''def _stocktake_cycle_batch_cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _encode_stocktake_cycle_batch_cursor(batch_id: int, *, scope: str) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "stocktake-cycle-batch",
            "scope": _stocktake_cycle_batch_cursor_scope_hash(scope),
            "id": int(batch_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_stocktake_cycle_batch_cursor(cursor: str, *, expected_scope: str) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "stocktake-cycle-batch"
            or payload.get("scope")
            != _stocktake_cycle_batch_cursor_scope_hash(expected_scope)
        ):
            raise ValueError
        batch_id = payload.get("id")
        if type(batch_id) is not int or batch_id <= 0:
            raise ValueError
        return batch_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor دفعات الجرد الدوري غير صالح أو لا يطابق النطاق الحالي.",
        ) from exc


@router.get(
    "/warehouse/unified/stocktake/cycle-batches",
    response_model=StocktakeCycleBatchCursorPage,
    status_code=200,
)
async def list_stocktake_cycle_batches(
    location_id: int = Query(..., ge=1),
    product_variant_id: int = Query(..., ge=1),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id

    location_exists = (
        await db.execute(
            select(InventoryLocation.id).filter(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
                InventoryLocation.is_active.is_(True),
                InventoryLocation.location_type.in_(["WAREHOUSE", "VEHICLE"]),
            )
        )
    ).scalar_one_or_none()
    if location_exists is None:
        raise HTTPException(
            status_code=404,
            detail="موقع الجرد غير موجود أو غير فعال أو لا يتبع شركتك.",
        )

    variant_exists = (
        await db.execute(
            select(ProductVariant.id).filter(
                ProductVariant.company_id == company_id,
                ProductVariant.id == product_variant_id,
            )
        )
    ).scalar_one_or_none()
    if variant_exists is None:
        raise HTTPException(
            status_code=404,
            detail="الصنف غير موجود أو لا يتبع شركتك.",
        )

    clean_search = search.strip() if search else ""
    scope = f"{company_id}|{location_id}|{product_variant_id}|{clean_search}"
    stocked_batch_ids = select(InventoryBalance.batch_id).filter(
        InventoryBalance.company_id == company_id,
        InventoryBalance.location_id == location_id,
        InventoryBalance.product_variant_id == product_variant_id,
        InventoryBalance.batch_id.is_not(None),
        InventoryBalance.on_hand_quantity > 0,
        InventoryBalance.stock_status.in_(["AVAILABLE", "DAMAGED"]),
    ).distinct()

    filters = [
        ProductBatch.company_id == company_id,
        ProductBatch.product_variant_id == product_variant_id,
        ProductBatch.id.in_(stocked_batch_ids),
    ]
    if clean_search:
        escaped = _escape_like(clean_search)
        filters.append(
            ProductBatch.batch_number.ilike(f"%{escaped}%", escape="\\")
        )

    total = None
    if cursor is None:
        total = int(
            (
                await db.execute(
                    select(func.count(ProductBatch.id)).filter(*filters)
                )
            ).scalar_one()
        )

    stmt = select(
        ProductBatch.id,
        ProductBatch.product_variant_id,
        ProductBatch.batch_number,
        ProductBatch.production_date,
        ProductBatch.expiry_date,
        ProductBatch.is_active,
    ).filter(*filters)

    if cursor is not None:
        cursor_id = _decode_stocktake_cycle_batch_cursor(
            cursor,
            expected_scope=scope,
        )
        stmt = stmt.filter(ProductBatch.id < cursor_id)

    rows = (
        await db.execute(
            stmt.order_by(ProductBatch.id.desc()).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        next_cursor = _encode_stocktake_cycle_batch_cursor(
            int(page_rows[-1].id),
            scope=scope,
        )

    return {
        "items": [
            {
                "id": int(row.id),
                "product_variant_id": int(row.product_variant_id),
                "batch_number": str(row.batch_number),
                "production_date": row.production_date,
                "expiry_date": row.expiry_date,
                "is_active": bool(row.is_active),
            }
            for row in page_rows
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


'''
if "/warehouse/unified/stocktake/cycle-batches" not in warehouse:
    if warehouse.count(endpoint_anchor) != 1:
        fail("Could not locate unique active-stocktake endpoint anchor.")
    warehouse = warehouse.replace(endpoint_anchor, endpoint_block + endpoint_anchor, 1)
    print("PATCHED=stocktake_cycle_batch_endpoint")
else:
    print("UNCHANGED=stocktake_cycle_batch_endpoint")

types = read(TYPES)
types_anchor = "export interface StocktakeSessionCursorPage {"
types_block = '''export interface CycleProductOption {
  id: number;
  name: string;
  sku: string | null;
  packs_per_carton: number;
}

export interface CycleProductCursorPage {
  items: CycleProductOption[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

export interface CycleBatchOption {
  id: number;
  product_variant_id: number;
  batch_number: string;
  production_date: string | null;
  expiry_date: string;
  is_active: boolean;
}

export interface CycleBatchCursorPage {
  items: CycleBatchOption[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

'''
if "export interface CycleProductOption" not in types:
    if types.count(types_anchor) != 1:
        fail("Could not locate stocktake frontend types anchor.")
    types = types.replace(types_anchor, types_block + types_anchor, 1)
    print("PATCHED=cycle_count_frontend_types")
else:
    print("UNCHANGED=cycle_count_frontend_types")

parsers = read(PARSERS)
parsers = replace_once(
    parsers,
    "  CountSheetItem,\n  ReviewAttempt,",
    "  CountSheetItem,\n  CycleBatchCursorPage,\n  CycleBatchOption,\n  CycleProductCursorPage,\n  CycleProductOption,\n  ReviewAttempt,",
    "cycle_count_parser_type_imports",
)
parser_anchor = "export const parseCountSheet = ("
parser_block = '''export const parseCycleProductPage = (
  raw: unknown
): CycleProductCursorPage => {
  if (!isRecord(raw) || !Array.isArray(raw.items) || typeof raw.has_more !== "boolean") {
    throw new Error("استجابة أصناف الجرد الدوري غير صالحة.");
  }
  const items: CycleProductOption[] = raw.items.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`صنف الجرد الدوري #${index + 1} غير صالح.`);
    }
    return {
      id: positiveInt(item.id, "product.id"),
      name: requiredString(item.name, "product.name"),
      sku: optionalString(item.sku),
      packs_per_carton: positiveInt(item.packs_per_carton, "product.packs_per_carton"),
    };
  });
  return {
    items,
    next_cursor: typeof raw.next_cursor === "string" ? raw.next_cursor : null,
    has_more: raw.has_more,
    total: raw.total === null || raw.total === undefined ? null : nonNegativeInt(raw.total, "product.total"),
  };
};

export const parseCycleBatchPage = (
  raw: unknown,
  expectedProductId: number
): CycleBatchCursorPage => {
  if (!isRecord(raw) || !Array.isArray(raw.items) || typeof raw.has_more !== "boolean") {
    throw new Error("استجابة دفعات الجرد الدوري غير صالحة.");
  }
  const items: CycleBatchOption[] = raw.items.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`دفعة الجرد الدوري #${index + 1} غير صالحة.`);
    }
    const productVariantId = positiveInt(item.product_variant_id, "batch.product_variant_id");
    if (productVariantId !== expectedProductId) {
      throw new Error("مرفوض: السيرفر أعاد دفعة لا تتبع الصنف المختار.");
    }
    return {
      id: positiveInt(item.id, "batch.id"),
      product_variant_id: productVariantId,
      batch_number: requiredString(item.batch_number, "batch.batch_number"),
      production_date: optionalString(item.production_date),
      expiry_date: requiredString(item.expiry_date, "batch.expiry_date"),
      is_active: item.is_active === true,
    };
  });
  return {
    items,
    next_cursor: typeof raw.next_cursor === "string" ? raw.next_cursor : null,
    has_more: raw.has_more,
    total: raw.total === null || raw.total === undefined ? null : nonNegativeInt(raw.total, "batch.total"),
  };
};

'''
if "export const parseCycleProductPage" not in parsers:
    if parsers.count(parser_anchor) != 1:
        fail("Could not locate stocktake parser insertion anchor.")
    parsers = parsers.replace(parser_anchor, parser_block + parser_anchor, 1)
    print("PATCHED=cycle_count_frontend_parsers")
else:
    print("UNCHANGED=cycle_count_frontend_parsers")

center = read(CENTER)
center = replace_once(
    center,
    '''  onRefresh: () => void;
  onLoadMore: () => void;''',
    '''  onRefresh: () => void;
  onStartCycle: () => void;
  cycleStartDisabled: boolean;
  onLoadMore: () => void;''',
    "session_center_cycle_props",
)
center = replace_once(
    center,
    '''  onRefresh,
  onLoadMore,''',
    '''  onRefresh,
  onStartCycle,
  cycleStartDisabled,
  onLoadMore,''',
    "session_center_cycle_destructure",
)
center = replace_once(
    center,
    '''        <button
          type="button"
          onClick={onRefresh}''',
    '''        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onStartCycle}
            disabled={cycleStartDisabled}
            className="px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-black disabled:opacity-40 disabled:cursor-not-allowed"
            title={cycleStartDisabled ? "الجرد الدوري غير متاح أثناء القفل الشامل" : "بدء جرد دوري لصنف أو دفعة"}
          >
            + جرد دوري
          </button>

        <button
          type="button"
          onClick={onRefresh}''',
    "session_center_cycle_button",
)
center = replace_once(
    center,
    '''        </button>
      </div>

      {loading && sessions.length === 0 ? (''',
    '''        </button>
        </div>
      </div>

      {loading && sessions.length === 0 ? (''',
    "session_center_cycle_button_wrapper_close",
)

tab = read(TAB)
tab = replace_once(
    tab,
    'import { useStocktakeLifecycle } from "./stocktake/hooks/useStocktakeLifecycle";',
    'import { useStocktakeLifecycle } from "./stocktake/hooks/useStocktakeLifecycle";\nimport { useCycleCountStart } from "./stocktake/hooks/useCycleCountStart";',
    "tab_cycle_hook_import",
)
tab = replace_once(
    tab,
    'import { StocktakeSessionCenter } from "./stocktake/StocktakeSessionCenter";',
    'import { StocktakeSessionCenter } from "./stocktake/StocktakeSessionCenter";\nimport { StocktakeCycleStartModal } from "./stocktake/StocktakeCycleStartModal";',
    "tab_cycle_modal_import",
)
tab = replace_once(
    tab,
    '''  const [showCancelModal, setShowCancelModal] =
    useState(false);''',
    '''  const [showCancelModal, setShowCancelModal] =
    useState(false);
  const [showCycleModal, setShowCycleModal] =
    useState(false);''',
    "tab_cycle_modal_state",
)

workflow_anchor = '''  const actionWorkflow =
    useStocktakeActions({'''
workflow_block = '''  const cycleWorkflow =
    useCycleCountStart({
      locationId,
      enabled: showCycleModal,
      authenticatedFetch,
      sessionKey: stocktakeState.sessionKey,
      phaseKey: stocktakeState.phaseKey,
      setSessionId: stocktakeState.setSessionId,
      loadCountSheet: countingWorkflow.loadCountSheet,
      notifyStocktakeChanged,
    });

'''
if "useCycleCountStart({" not in tab:
    if tab.count(workflow_anchor) != 1:
        fail("Could not locate actionWorkflow anchor in Tab3Stocktake.")
    tab = tab.replace(workflow_anchor, workflow_block + workflow_anchor, 1)
    print("PATCHED=tab_cycle_workflow")
else:
    print("UNCHANGED=tab_cycle_workflow")

handler_anchor = '''  const start = async () => {
    if (
      await lifecycle.startStocktake()
    ) {
      setShowLockModal(false);
    }
  };
'''
handler_new = handler_anchor + '''
  const closeCycleModal = () => {
    if (cycleWorkflow.starting) return;
    setShowCycleModal(false);
    cycleWorkflow.resetForm();
  };

  const startCycle = async () => {
    if (await cycleWorkflow.startCycleCount()) {
      setShowCycleModal(false);
    }
  };
'''
tab = replace_once(tab, handler_anchor, handler_new, "tab_cycle_handlers")

tab = replace_once(
    tab,
    '''        onRefresh={refreshSessions}
        onLoadMore={loadMoreSessions}''',
    '''        onRefresh={refreshSessions}
        onStartCycle={() => setShowCycleModal(true)}
        cycleStartDisabled={isAuditLocked || sessionsLoading}
        onLoadMore={loadMoreSessions}''',
    "tab_session_center_cycle_wiring",
)
modal_anchor = '''      <StocktakeStartModal
        open={showLockModal}'''
modal_block = '''      <StocktakeCycleStartModal
        open={showCycleModal}
        controller={cycleWorkflow}
        onClose={closeCycleModal}
        onStart={startCycle}
      />

'''
if "<StocktakeCycleStartModal" not in tab:
    if tab.count(modal_anchor) != 1:
        fail("Could not locate start modal anchor in Tab3Stocktake.")
    tab = tab.replace(modal_anchor, modal_block + modal_anchor, 1)
    print("PATCHED=tab_cycle_modal_wiring")
else:
    print("UNCHANGED=tab_cycle_modal_wiring")

combined_frontend = "\n".join([tab, types, parsers, center, *new_targets.values()])
checks = {
    "BACKEND_SCHEMA": "class StocktakeCycleBatchCursorPage(BaseModel):" in schemas,
    "BACKEND_ROUTE": "/warehouse/unified/stocktake/cycle-batches" in warehouse,
    "BACKEND_TENANT_LOCATION": (
        "InventoryLocation.company_id == company_id" in endpoint_block
        and "ProductBatch.company_id == company_id" in endpoint_block
        and "ProductVariant.company_id == company_id" in endpoint_block
    ),
    "BACKEND_PRODUCT_SCOPE": "ProductBatch.product_variant_id == product_variant_id" in endpoint_block,
    "BACKEND_LOCATION_STOCK_SCOPE": (
        "InventoryBalance.location_id == location_id" in endpoint_block
        and "InventoryBalance.on_hand_quantity > 0" in endpoint_block
    ),
    "BACKEND_CURSOR_SCOPE": "_decode_stocktake_cycle_batch_cursor" in warehouse,
    "FRONTEND_PRODUCT_CURSOR": "/warehouse/inventory/cursor?" in combined_frontend,
    "FRONTEND_BATCH_CURSOR": "/warehouse/unified/stocktake/cycle-batches?" in combined_frontend,
    "CYCLE_START_PAYLOAD": (
        'stocktake_type: "CYCLE_COUNT"' in combined_frontend
        and "product_variant_id: selectedProduct.id" in combined_frontend
        and "batch_id: selectedBatch?.id ?? null" in combined_frontend
    ),
    "REUSE_EXISTING_ENGINE": (
        "loadCountSheet(sid)" in combined_frontend
        and '/count"' not in new_targets[INV / "stocktake/hooks/useCycleCountStart.ts"]
        and "/approve" not in new_targets[INV / "stocktake/hooks/useCycleCountStart.ts"]
        and "/recount" not in new_targets[INV / "stocktake/hooks/useCycleCountStart.ts"]
    ),
    "NO_COMPANY_ID_PAYLOAD": "company_id" not in combined_frontend,
    "NO_EXPLICIT_ANY": ": any" not in combined_frontend and "any[]" not in combined_frontend and "Promise<any>" not in combined_frontend,
    "SERVER_STATUS_AUTHORITY": "notifyStocktakeChanged" in new_targets[INV / "stocktake/hooks/useCycleCountStart.ts"],
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail("Static verification failed before writes: " + ", ".join(failed))

for path, content in new_targets.items():
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"UNCHANGED={path.relative_to(INV)}")
    else:
        path.write_text(content, encoding="utf-8")
        print(f"CREATED={path.relative_to(INV)}")

SCHEMAS.write_text(schemas, encoding="utf-8")
WAREHOUSE.write_text(warehouse, encoding="utf-8")
TYPES.write_text(types, encoding="utf-8")
PARSERS.write_text(parsers, encoding="utf-8")
CENTER.write_text(center, encoding="utf-8")
TAB.write_text(tab, encoding="utf-8")

print("STOCKTAKE_CYCLE_BATCH_ENDPOINT=OK")
print("STOCKTAKE_CYCLE_BATCH_CURSOR=OK")
print("STOCKTAKE_CYCLE_BATCH_TENANT_SCOPE=OK")
print("STOCKTAKE_CYCLE_PRODUCT_SEARCH=OK")
print("STOCKTAKE_CYCLE_PRODUCT_SCOPE=OK")
print("STOCKTAKE_CYCLE_BATCH_SCOPE=OK")
print("STOCKTAKE_CYCLE_REUSES_COUNT_REVIEW_ACTIONS=OK")
print("STOCKTAKE_CYCLE_SERVER_AUTHORITY=OK")
print("MAIN_INVENTORY_STAGE4B_CYCLE_COUNT=OK")
