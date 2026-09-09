from __future__ import annotations

from pathlib import Path
import base64
import zlib

ROOT = Path(__file__).resolve().parent
INV = ROOT / "dashboard" / "src" / "pages" / "inventory"
TAB = INV / "Tab3Stocktake.tsx"
MAIN = INV / "MainInventory.tsx"
UTILS = INV / "inventoryUtils.ts"
STOCKTAKE_DIR = INV / "stocktake"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"
WAREHOUSE = ROOT / "wa_backend" / "api" / "warehouse.py"

PAYLOADS = {'types.ts': 'eNq9Vltv2jAUfudXWDxtUrW9w9oKhXSNhICRXjRNk2WSQ7FI7NQ+bsu6/vfZSQMxCVVf1pco5+LP5/Kdk/C8kAoJbgsgzz1CYpTJBtkGFvLxpCmXLzEyNPqk90JWSuak/+XLVy4eQKBU22vkme4Pez142kPujl856dQC/iX9i+vJhAaz6+lVv1IEP4NJ6GluwsvI6RZhMJseBa3CqWHHi9HFDtFhRdPvr+I8nI6tZOFuovD2VemwrZdV/riOFuH4VT2azxezm504n8VXOyEYTYNwMrHysZDma6Z3iR5E4d1+O4qciUbTcejCC23ux0BHBtcXgMmanJJP9rhR2YBoVFzcuR7JAvX5gCzg3oDGSHDsfSanZ2Rue8Q1fDNiI+SjONvDc4GgViwBEkgjMF4DYISQlxQolExNgvSBKc4EUp4OiDD5EtTQWpfMxtHQ2VyEyTJn0i5eqsumDDqZM2zAC5ZDnUWpZ8lG0wIUTZhCKdqXVnJ9pnGxzYqrLU0ZQsv60pH0Ah44PE64qDjP0KZeIM2s4iDb/1yL8kap+B236fbj6WgeX86u+iWboziwNFyUXPvwqpVWSBBSem9s4hy3TWSWoGFZp6mqVAKdRiERHFXf3aNR1ZqyTX7t66bV6e0tiaO0DXy57da2asjseNkm/PHONErh2b3TDScF5Q1UrmgdGk/PO9BqRwVMu351IN0brkBTLlIowD5K7/LUgCylzICJkmNmmXN0STF8V033y70sbllVDVpzKQ6YrWAFClwbffrsqO1QqNtSA3/HVw4t1u8ILxOG7es6MqXaOuoVh9TLObNs1ViXeODTpMmLNdfuq3Tg8et3PXZ60FgDTv1mweKqSrHJc6a2HXT84ILpRBZAj2+n5ibyXI+wt3J6a581HI5uFAWuPSl9lMruvhaxvPVot1VrRvfa9p6z7LCvXTNBXwfGJ4oWrNBriTQxKFerrhGxS8EOoT8/TmuKtKV9DzsCo7RUc3ZXfVa4ZZzXVI9DFRMFPLkI3bmO8Oy/BM2lAi8xlMiyVklf/F+HZ+9HjrwMe/8ATVhuCw==', 'parsers.ts': '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', 'hooks/useStocktakeSessions.ts': 'eNqlVs2O2zYQvvspGKMHChHkXHqx4y2CIAECZIsg25yMRcJII5tYWXJIah1jV4cCQV8lbRGgKBqgr6J9m5JD/ZC2lEVbHyyJnPnm4/xx+HZXCEVuSCnhKcuy9yy+Cs3HszSFWOHra0jxeaGYAlKRVBRbMhXAYjVdTHiLoAomVbctizwH4exPCFmDeiZEIc5BSraGUC/tmDDARXyl2BVc6A1e5K9ws0WKohlKCdmjqcMOELJTfVKqzXNQ8SZ0VxvAi3K7ZeLgYRoIgzjhuQKRshjIm1Mq8olYS7SUFTFTeuVFMid5uX0PYqFXmTYLueJ6DxK0Px/gtJhUkwl8ROppmccGx3r0yBr1LYWDFvQx5qNcAyQb6y9FVrLZCIkE1UpdkmUXzcdadtRdq0u9e0ZXl8Gih1SFYhni/WTePDDrFnKr/ZNlZ9T8u6o5fFRPSyELgfo/dp8aBHl0QFIJnq9HgbKCJXofUV7ad5cHTVkmYUDhvBDgKpnv+xWfM55B0unZz2+qCfhQgtQO/2CldAHRR3q/E0hNGNt4WJm2+Ch6gslDHhP7rpXQS3PiuUWrmUfYyLDdDvJELyIZXAzI8gyzATHQsERKDx/2DCMNLnR+ITvz4ymhFizolMmR06gSpT2w+VUEtMlBYV+Q+D50/Nbt9knRRx1ttPSUODiW7Kl0e2Bb48cc9uTN65cXwES8eYWrtBfuK+stT0yZGm/SvtqC0BXlW67mZPr9o2m/XDlkjZ9sYIKGQKT506ldm4ZN1ILOsV12sL2myvaMq4Hipg6Hd7M9E7ApdHrMypynHJKZbGtVznT/5dfww3c3jXlVNEcKqncdimvfUDYZ8GC5JKcZEOg1VYr8hPBOt2PNeLRVu5T14cIBh79IBgk5XYnSnYBrL2Vbyg/adLT8kE/EFWylA9WS3YJYQ9LkwjnbPXYkSNO4Q29tpPs5MmfUiTshaSF06NGaYUGKlFjuNx6uZYJJYcQirnuIefGwqntwu6P+b/TGeasoihrda5bpFKDB5cJL8JFyRCqmhb/tEtsNEm7j5YDphcXrUW5vDEfSgai6XqITJt4QCmZQmJMyv8qLfe5C/ess9nLoiFKXfs0td8LW60L3NKnTDnfU/qqeFE5LEZ7SrZ+jEYl6MUdpP3mndz/XX+8+kfrL3af6V/v4q/5c/07qz/r1S/1n/Qe+3v1Sf63/rn+Lpo5+4FZlG4CU5/ouOgx4fDni8eOCHfL1yRVy3PwH7pGju2RA4zR/8FlZJ60GZienJZnxxuZ7N+9S6nSgwfQYSozRlLgueOJf9rgbkv4oVUhWnoTH0B0aBKQC5NjY4BL/L2Y9U2bsMUH6hg0sqn6iI7e3xJmy+ioc4+PMgl2RGFKo4DtkYm+SfoTDBQdBfzf0mybXxs8FsIPrgGqHPWLImQEntpF6ceiFWpXKjPv/AM1LEvg=', 'StocktakeSessionCenter.tsx': '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'}
SCHEMA_BLOCK = 'class StocktakeActiveSessionItem(BaseModel):\n    id: int\n    reference_number: str\n    stocktake_type: Literal["FULL_COUNT", "CYCLE_COUNT", "VEHICLE_RECON"]\n    status: Literal["DRAFT", "COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED", "APPROVED"]\n    location_id: int\n    scope_product_variant_id: Optional[int] = None\n    scope_product_name: Optional[str] = None\n    scope_batch_id: Optional[int] = None\n    scope_batch_number: Optional[str] = None\n    related_work_session_id: Optional[int] = None\n    started_by: int\n    started_by_name: str\n    pending_independent_recount_required: bool\n    snapshot_cutoff_at: Optional[datetime] = None\n    created_at: datetime\n    updated_at: datetime\n\n\nclass StocktakeActiveSessionCursorPage(BaseModel):\n    items: List[StocktakeActiveSessionItem]\n    next_cursor: Optional[str] = None\n    has_more: bool\n    total: Optional[int] = None\n\n\n'
CURSOR_BLOCK = 'def _stocktake_cursor_scope_hash(scope: str) -> str:\n    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]\n\n\ndef _encode_stocktake_cursor(\n    session_id: int,\n    *,\n    scope: str,\n) -> str:\n    raw = json.dumps(\n        {\n            "v": 1,\n            "kind": "stocktake-active-session",\n            "scope": _stocktake_cursor_scope_hash(scope),\n            "id": int(session_id),\n        },\n        sort_keys=True,\n        separators=(",", ":"),\n    ).encode("utf-8")\n    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")\n\n\ndef _decode_stocktake_cursor(\n    cursor: str,\n    *,\n    expected_scope: str,\n) -> int:\n    try:\n        padding = "=" * (-len(cursor) % 4)\n        raw = base64.urlsafe_b64decode(\n            (cursor + padding).encode("ascii")\n        )\n        payload = json.loads(raw.decode("utf-8"))\n\n        if (\n            not isinstance(payload, dict)\n            or payload.get("v") != 1\n            or payload.get("kind") != "stocktake-active-session"\n            or payload.get("scope")\n            != _stocktake_cursor_scope_hash(expected_scope)\n        ):\n            raise ValueError\n\n        session_id = payload.get("id")\n        if type(session_id) is not int or session_id <= 0:\n            raise ValueError\n\n        return session_id\n    except Exception as exc:\n        raise HTTPException(\n            status_code=400,\n            detail=(\n                "Cursor جلسات الجرد غير صالح "\n                "أو لا يطابق الموقع الحالي."\n            ),\n        ) from exc\n\n\n'
ACTIVE_ENDPOINT = '_ACTIVE_STOCKTAKE_STATUSES = frozenset({\n    "DRAFT",\n    "COUNTING",\n    "PENDING_REVIEW",\n    "RECOUNT_REQUIRED",\n    "APPROVED",\n})\n\n\n@router.get(\n    "/warehouse/unified/stocktakes/active",\n    response_model=StocktakeActiveSessionCursorPage,\n    status_code=200,\n)\nasync def list_active_stocktake_sessions(\n    location_id: int = Query(..., ge=1),\n    cursor: Optional[str] = Query(default=None, max_length=1024),\n    limit: int = Query(default=50, ge=1, le=200),\n    db: AsyncSession = Depends(get_db),\n    current_admin: Driver = Depends(get_current_admin),\n):\n    company_id = current_admin.company_id\n\n    location_exists = (\n        await db.execute(\n            select(InventoryLocation.id).filter(\n                InventoryLocation.company_id == company_id,\n                InventoryLocation.id == location_id,\n                InventoryLocation.is_active.is_(True),\n                InventoryLocation.location_type.in_(["WAREHOUSE", "VEHICLE"]),\n            )\n        )\n    ).scalar_one_or_none()\n\n    if location_exists is None:\n        raise HTTPException(\n            status_code=404,\n            detail=(\n                "موقع الجرد غير موجود أو غير فعال "\n                "أو لا يتبع شركتك."\n            ),\n        )\n\n    scope = f"{company_id}|{location_id}|active"\n\n    base_filters = (\n        StocktakeSession.company_id == company_id,\n        StocktakeSession.location_id == location_id,\n        StocktakeSession.status.in_(_ACTIVE_STOCKTAKE_STATUSES),\n    )\n\n    stmt = (\n        select(\n            StocktakeSession.id,\n            StocktakeSession.reference_number,\n            StocktakeSession.stocktake_type,\n            StocktakeSession.status,\n            StocktakeSession.location_id,\n            StocktakeSession.scope_product_variant_id,\n            ProductVariant.variant_name.label("scope_product_name"),\n            StocktakeSession.scope_batch_id,\n            ProductBatch.batch_number.label("scope_batch_number"),\n            StocktakeSession.related_work_session_id,\n            StocktakeSession.started_by,\n            Driver.full_name.label("started_by_name"),\n            StocktakeSession.pending_independent_recount_required,\n            StocktakeSession.snapshot_cutoff_at,\n            StocktakeSession.created_at,\n            StocktakeSession.updated_at,\n        )\n        .outerjoin(\n            ProductVariant,\n            and_(\n                ProductVariant.company_id == StocktakeSession.company_id,\n                ProductVariant.id == StocktakeSession.scope_product_variant_id,\n            ),\n        )\n        .outerjoin(\n            ProductBatch,\n            and_(\n                ProductBatch.company_id == StocktakeSession.company_id,\n                ProductBatch.product_variant_id\n                == StocktakeSession.scope_product_variant_id,\n                ProductBatch.id == StocktakeSession.scope_batch_id,\n            ),\n        )\n        .join(\n            Driver,\n            and_(\n                Driver.company_id == StocktakeSession.company_id,\n                Driver.id == StocktakeSession.started_by,\n            ),\n        )\n        .filter(*base_filters)\n    )\n\n    total = None\n    if cursor is None:\n        total = int(\n            (\n                await db.execute(\n                    select(func.count(StocktakeSession.id))\n                    .filter(*base_filters)\n                )\n            ).scalar_one()\n        )\n\n    if cursor is not None:\n        cursor_id = _decode_stocktake_cursor(\n            cursor,\n            expected_scope=scope,\n        )\n        stmt = stmt.filter(StocktakeSession.id < cursor_id)\n\n    rows = (\n        await db.execute(\n            stmt.order_by(StocktakeSession.id.desc())\n            .limit(limit + 1)\n        )\n    ).all()\n\n    has_more = len(rows) > limit\n    page_rows = rows[:limit]\n\n    next_cursor = None\n    if has_more and page_rows:\n        next_cursor = _encode_stocktake_cursor(\n            int(page_rows[-1].id),\n            scope=scope,\n        )\n\n    return {\n        "items": [\n            {\n                "id": int(row.id),\n                "reference_number": str(row.reference_number),\n                "stocktake_type": str(row.stocktake_type),\n                "status": str(row.status),\n                "location_id": int(row.location_id),\n                "scope_product_variant_id": (\n                    int(row.scope_product_variant_id)\n                    if row.scope_product_variant_id is not None\n                    else None\n                ),\n                "scope_product_name": row.scope_product_name,\n                "scope_batch_id": (\n                    int(row.scope_batch_id)\n                    if row.scope_batch_id is not None\n                    else None\n                ),\n                "scope_batch_number": row.scope_batch_number,\n                "related_work_session_id": (\n                    int(row.related_work_session_id)\n                    if row.related_work_session_id is not None\n                    else None\n                ),\n                "started_by": int(row.started_by),\n                "started_by_name": str(row.started_by_name),\n                "pending_independent_recount_required": bool(\n                    row.pending_independent_recount_required\n                ),\n                "snapshot_cutoff_at": row.snapshot_cutoff_at,\n                "created_at": row.created_at,\n                "updated_at": row.updated_at,\n            }\n            for row in page_rows\n        ],\n        "next_cursor": next_cursor,\n        "has_more": has_more,\n        "total": total,\n    }\n\n\n'


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


def decode(name: str) -> str:
    return zlib.decompress(
        base64.b64decode(PAYLOADS[name])
    ).decode("utf-8")


def replace_once(
    text: str,
    old: str,
    new: str,
    label: str,
) -> str:
    if new in text:
        print(f"UNCHANGED={label}")
        return text
    count = text.count(old)
    if count != 1:
        fail(
            f"{label}: expected exactly 1 match, found {count}. "
            "No files changed."
        )
    print(f"PATCHED={label}")
    return text.replace(old, new, 1)


for path in (TAB, MAIN, UTILS, SCHEMAS, WAREHOUSE):
    if not path.exists():
        fail(f"Missing file: {path.relative_to(ROOT)}")

tab = normalize(TAB.read_text(encoding="utf-8"))
main = normalize(MAIN.read_text(encoding="utf-8"))
utils = normalize(UTILS.read_text(encoding="utf-8"))
schemas = normalize(SCHEMAS.read_text(encoding="utf-8"))
warehouse = normalize(WAREHOUSE.read_text(encoding="utf-8"))

# ------------------------------------------------------------------
# 0) Exact Stage-4A1 prerequisite gate.
# ------------------------------------------------------------------
prerequisites = {
    "STAGE4A1_COMPANY_PROP": "companyId: string;" in tab,
    "STAGE4A1_UNKNOWN_FETCH": "Promise<unknown>" in tab,
    "STAGE4A1_STOCK_STATUS": "stock_status: row.stock_status" in tab,
    "STAGE4A1_APPROVE_ATTEMPT": (
        "count_attempt_id: review.latest_attempt.id" in tab
    ),
    "STAGE4A1_TENANT_SESSION_KEY": (
        "unified_stocktake_session:${companyScope}:${locationId}"
        in tab
    ),
    "STAGE4A1_DEP_COMPANY_SCOPE": (
        "[authenticatedFetch, companyScope, locationId, phaseKey]"
        in tab
    ),
    "STAGE4A1_DEP_REVIEW_LOCATION": (
        "[authenticatedFetch, locationId, phaseKey]"
        in tab
    ),
    "STAGE4A1_NO_ANY": (
        ": any" not in tab and "Promise<any>" not in tab
    ),
    "BACKEND_NO_ACTIVE_CENTER_YET": (
        "/warehouse/unified/stocktakes/active"
        not in warehouse
    ),
}
missing = [name for name, ok in prerequisites.items() if not ok]
if missing:
    fail(
        "Stage-4A1/current-backend prerequisites failed: "
        + ", ".join(missing)
    )

# ------------------------------------------------------------------
# 1) New frontend domain files — refuse overwrite if different.
# ------------------------------------------------------------------
new_files = {
    STOCKTAKE_DIR / "types.ts": decode("types.ts"),
    STOCKTAKE_DIR / "parsers.ts": decode("parsers.ts"),
    STOCKTAKE_DIR / "hooks" / "useStocktakeSessions.ts":
        decode("hooks/useStocktakeSessions.ts"),
    STOCKTAKE_DIR / "StocktakeSessionCenter.tsx":
        decode("StocktakeSessionCenter.tsx"),
}

for path, expected in new_files.items():
    if path.exists():
        current = normalize(path.read_text(encoding="utf-8"))
        if current != expected:
            fail(
                "Refusing to overwrite existing different file: "
                f"{path.relative_to(ROOT)}"
            )

# ------------------------------------------------------------------
# 2) Backend response contracts.
# ------------------------------------------------------------------
schema_anchor = "class UnifiedStocktakeStartRequest(RequestModel):"
if "class StocktakeActiveSessionItem(BaseModel):" not in schemas:
    count = schemas.count(schema_anchor)
    if count != 1:
        fail(
            "stocktake_active_session_schemas: "
            f"expected 1 anchor, found {count}"
        )
    schemas = schemas.replace(
        schema_anchor,
        SCHEMA_BLOCK + schema_anchor,
        1,
    )
    print("PATCHED=stocktake_active_session_schemas")
else:
    print("UNCHANGED=stocktake_active_session_schemas")

# ------------------------------------------------------------------
# 3) Backend import + scoped opaque cursor helpers.
# ------------------------------------------------------------------
warehouse = replace_once(
    warehouse,
    '''UnifiedTransferOverrideOptionsResponse,
UnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest )''',
    '''UnifiedTransferOverrideOptionsResponse,
StocktakeActiveSessionCursorPage,
UnifiedStocktakeCountRequest, StocktakeRecountRequest, StocktakeApprovalRequest, StocktakeCancelRequest )''',
    "stocktake_active_session_schema_import",
)

cursor_anchor = '''# التحقق من بيانات مشرف مخول داخل نفس الشركة دون كشف سبب فشل المصادقة.
async def _verify_stocktake_admin_credentials(
'''

warehouse = replace_once(
    warehouse,
    cursor_anchor,
    CURSOR_BLOCK + cursor_anchor,
    "stocktake_active_session_cursor_helpers",
)

# ------------------------------------------------------------------
# 4) Server-driven active-session center endpoint.
# ------------------------------------------------------------------
start_marker = '@router.post("/warehouse/unified/stocktake/start"'
if start_marker not in warehouse:
    fail(
        "Stocktake start route marker not found. "
        "No files changed."
    )

if "/warehouse/unified/stocktakes/active" not in warehouse:
    idx = warehouse.find(start_marker)
    warehouse = warehouse[:idx] + ACTIVE_ENDPOINT + warehouse[idx:]
    print("PATCHED=stocktake_active_sessions_endpoint")
else:
    print("UNCHANGED=stocktake_active_sessions_endpoint")

# ------------------------------------------------------------------
# 5) Frontend: extract domain contracts/parsers.
# ------------------------------------------------------------------
tab = replace_once(
    tab,
    '''import type {
  StocktakeRow,
  StocktakeStockStatus,
} from "./inventoryUtils";
import { toTotalPacks, formatQty } from "./inventoryUtils";''',
    '''import type { StocktakeRow } from "./inventoryUtils";
import { toTotalPacks, formatQty } from "./inventoryUtils";
import type {
  StocktakeAuthFetch,
  StocktakePhase,
  StocktakeReview,
  StocktakeSessionSummary,
} from "./stocktake/types";
import {
  getErrorMessage,
  parseCountSheet,
  parseRecountRequiresIndependent,
  parseStartSessionId,
  parseStocktakeReview,
  readMessage,
  rowKey,
} from "./stocktake/parsers";
import { useStocktakeSessions } from "./stocktake/hooks/useStocktakeSessions";
import { StocktakeSessionCenter } from "./stocktake/StocktakeSessionCenter";''',
    "stocktake_domain_imports",
)

types_start = tab.find(
    'type StocktakePhase = "COUNTING" | "REVIEW" | "WAITING_INDEPENDENT";'
)
helpers_start = tab.find("const isRecord = (value: unknown)")
export_start = tab.find("export function Tab3Stocktake({")

if (
    types_start < 0
    or helpers_start < 0
    or export_start < 0
    or not (types_start < helpers_start < export_start)
):
    fail(
        "Could not locate exact Stage-4A1 local "
        "type/parser boundaries."
    )

type_segment = tab[types_start:helpers_start]
if not all(
    marker in type_segment
    for marker in (
        "interface CountSheetItem",
        "interface ReviewLine",
        "interface ReviewAttempt",
        "interface StocktakeReview",
    )
):
    fail("Unexpected stocktake local type segment.")

helper_segment = tab[helpers_start:export_start]
if not all(
    marker in helper_segment
    for marker in (
        "const parseCountSheet",
        "const parseStocktakeReview",
        "const parseStartSessionId",
        "const parseRecountRequiresIndependent",
        "const rowKey",
    )
):
    fail("Unexpected stocktake local parser segment.")

tab = tab[:types_start] + tab[export_start:]
print("PATCHED=stocktake_types_parsers_extracted")

# Props use shared transport contract and server-refresh callback.
tab = replace_once(
    tab,
    '''  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<unknown>;
  onLockChange: (locked: boolean) => void;''',
    '''  authenticatedFetch: StocktakeAuthFetch;
  onStocktakeChanged: () => void | Promise<void>;''',
    "stocktake_server_authority_callback_contract",
)

tab = replace_once(
    tab,
    '''  authenticatedFetch,
  onLockChange,
}: Props) {''',
    '''  authenticatedFetch,
  onStocktakeChanged,
}: Props) {''',
    "stocktake_server_authority_callback_destructure",
)

# ------------------------------------------------------------------
# 6) Add server-driven session state.
# ------------------------------------------------------------------
state_anchor = '''  const [submitting, setSubmitting] = useState(false);
  const [locking, setLocking] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
'''

state_block = state_anchor + '''
  const {
    sessions: activeSessions,
    total: activeSessionsTotal,
    nextCursor: activeSessionsNextCursor,
    loading: sessionsLoading,
    loadingMore: sessionsLoadingMore,
    loadFailed: sessionsLoadFailed,
    refreshSessions,
    loadMore: loadMoreSessions,
  } = useStocktakeSessions({
    locationId,
    authenticatedFetch,
  });

  const notifyStocktakeChanged = useCallback(async () => {
    await onStocktakeChanged();
    refreshSessions();
  }, [onStocktakeChanged, refreshSessions]);
'''

tab = replace_once(
    tab,
    state_anchor,
    state_block,
    "stocktake_session_center_state",
)

# ------------------------------------------------------------------
# 7) Open any active server session without relying on global lock.
# ------------------------------------------------------------------
recovery_anchor = '''  // استعادة حالة جلسة الجرد بعد تحديث الصفحة دون كشف المتوقع أثناء مرحلة العد.
  useEffect(() => {
'''

open_session_block = '''  const openServerSession = useCallback(
    async (session: StocktakeSessionSummary) => {
      const sid = String(session.id);

      try {
        if (session.status === "PENDING_REVIEW") {
          localStorage.setItem(sessionKey, sid);
          await loadReview(sid);
          return;
        }

        if (
          session.status === "COUNTING" ||
          session.status === "RECOUNT_REQUIRED"
        ) {
          localStorage.setItem(sessionKey, sid);
          await loadCountSheet(sid);
          return;
        }

        toast.info(
          `الجلسة بحالة (${session.status}) ولا يمكن فتحها في شاشة العد الحالية.`
        );
      } catch (error: unknown) {
        toast.error(
          getErrorMessage(
            error,
            "تعذر فتح جلسة الجرد."
          )
        );
      }
    },
    [loadCountSheet, loadReview, sessionKey]
  );

''' + recovery_anchor

tab = replace_once(
    tab,
    recovery_anchor,
    open_session_block,
    "stocktake_open_server_session",
)

old_recovery_start = '''  useEffect(() => {
    if (!isAuditLocked) {
      setRows([]);
      setReview(null);
      setSessionId(null);
      setPhase("COUNTING");
      return;
    }

    const sid = localStorage.getItem(sessionKey);
    if (!sid) {
      toast.error("جلسة الجرد النشطة غير موجودة محلياً. أعد تحميل الصفحة أو راجع المسؤول.");
      return;
    }
'''

new_recovery_start = '''  useEffect(() => {
    const sid = localStorage.getItem(sessionKey);
    if (!sid) {
      setRows([]);
      setReview(null);
      setSessionId(null);
      setPhase("COUNTING");
      return;
    }
'''

tab = replace_once(
    tab,
    old_recovery_start,
    new_recovery_start,
    "stocktake_recovery_not_global_lock_bound",
)

error_anchor = '''        toast.error(
          getErrorMessage(
            error,
            "تعذر استعادة جلسة الجرد الحالية."
          )
        );'''

error_replacement = '''        localStorage.removeItem(sessionKey);
        localStorage.removeItem(phaseKey);
        setSessionId(null);
        setRows([]);
        setReview(null);
        setPhase("COUNTING");
        toast.error(
          getErrorMessage(
            error,
            "تعذر استعادة جلسة الجرد الحالية."
          )
        );'''

tab = replace_once(
    tab,
    error_anchor,
    error_replacement,
    "stocktake_stale_local_selection_cleanup",
)

old_dep = '''      }, [
      isAuditLocked,
      sessionKey,
      phaseKey,
      authenticatedFetch,
      loadCountSheet,
      locationId,
    ]);'''

new_dep = '''      }, [
      sessionKey,
      phaseKey,
      authenticatedFetch,
      loadCountSheet,
      locationId,
    ]);'''

tab = replace_once(
    tab,
    old_dep,
    new_dep,
    "stocktake_recovery_dependency_scope",
)

# ------------------------------------------------------------------
# 8) Full count may not start over any active scoped session.
# ------------------------------------------------------------------
start_anchor = '''  const startStocktake = async () => {
    setLocking(true);
'''

start_replacement = '''  const startStocktake = async () => {
    if (sessionsLoading || sessionsLoadFailed) {
      toast.error(
        "لا يمكن بدء جرد شامل قبل التحقق من جلسات الجرد النشطة على السيرفر."
      );
      return;
    }

    if ((activeSessionsTotal ?? activeSessions.length) > 0) {
      toast.error(
        "يوجد جرد نشط في هذا الموقع. أغلق الجلسات النشطة قبل بدء جرد شامل."
      );
      return;
    }

    setLocking(true);
'''

tab = replace_once(
    tab,
    start_anchor,
    start_replacement,
    "full_count_blocks_on_active_scoped_sessions",
)

if tab.count("onLockChange(true);") != 1:
    fail(
        "Expected exactly one onLockChange(true) before refactor."
    )
if tab.count("onLockChange(false);") != 2:
    fail(
        "Expected exactly two onLockChange(false) before refactor."
    )

tab = tab.replace(
    "onLockChange(true);",
    "await notifyStocktakeChanged();",
)
tab = tab.replace(
    "onLockChange(false);",
    "await notifyStocktakeChanged();",
)
print("PATCHED=stocktake_server_status_refresh_calls")

if tab.count('isAuditLocked && phase ===') != 3:
    fail(
        "Expected exactly three global-lock workflow gates."
    )
tab = tab.replace(
    'isAuditLocked && phase ===',
    'sessionId !== null && phase ===',
)
print("PATCHED=stocktake_selected_session_workflow_gates")

tab = replace_once(
    tab,
    '''      {!isAuditLocked && (''',
    '''      {sessionId === null && !isAuditLocked && (''',
    "stocktake_full_count_idle_gate",
)

# ------------------------------------------------------------------
# 9) Render Session Center at top.
# ------------------------------------------------------------------
root_anchor = '''  return (
    <div className="flex flex-col gap-4 h-full flex-1 min-h-0 pt-1">
'''

root_replacement = root_anchor + '''      <StocktakeSessionCenter
        sessions={activeSessions}
        total={activeSessionsTotal}
        loading={sessionsLoading}
        loadingMore={sessionsLoadingMore}
        nextCursor={activeSessionsNextCursor}
        currentSessionId={
          sessionId ? Number(sessionId) : null
        }
        onRefresh={refreshSessions}
        onLoadMore={loadMoreSessions}
        onOpenSession={openServerSession}
      />

'''

tab = replace_once(
    tab,
    root_anchor,
    root_replacement,
    "stocktake_session_center_surface",
)

# ------------------------------------------------------------------
# 10) Parent callback: server status is authority.
# ------------------------------------------------------------------
main = replace_once(
    main,
    '''            onLockChange={async (locked) => {
              setIsAuditLocked(locked);
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
            }}''',
    '''            onStocktakeChanged={async () => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
              await fetchStatus();
            }}''',
    "main_stocktake_server_status_authority",
)

# ------------------------------------------------------------------
# 11) In-memory gates before writes.
# ------------------------------------------------------------------
combined_new = "\n".join(new_files.values())

checks = {
    "DOMAIN_TYPES": (
        "export interface StocktakeSessionSummary"
        in combined_new
    ),
    "DOMAIN_PARSER": (
        "parseStocktakeSessionPage" in combined_new
    ),
    "SESSION_HOOK": (
        "/warehouse/unified/stocktakes/active?"
        in combined_new
    ),
    "SESSION_CENTER": (
        "export function StocktakeSessionCenter"
        in combined_new
    ),
    "TAB_NO_LOCAL_PARSERS": (
        "const parseCountSheet =" not in tab
        and "interface StocktakeReview" not in tab
    ),
    "TAB_SESSION_CENTER": (
        "<StocktakeSessionCenter" in tab
    ),
    "TAB_SERVER_CALLBACK": (
        "onStocktakeChanged" in tab
        and "onLockChange" not in tab
    ),
    "TAB_CYCLE_RENDER_CAPABLE": (
        'sessionId !== null && phase === "COUNTING"'
        in tab
    ),
    "TAB_RECOVERY_NOT_LOCK_BOUND": (
        "if (!isAuditLocked)" not in tab
    ),
    "MAIN_SERVER_STATUS": (
        "await fetchStatus();" in main
        and "onStocktakeChanged" in main
    ),
    "BACKEND_ACTIVE_ROUTE": (
        "/warehouse/unified/stocktakes/active"
        in warehouse
    ),
    "BACKEND_TENANT_SCOPE": (
        "StocktakeSession.company_id == company_id"
        in ACTIVE_ENDPOINT
        and "StocktakeSession.location_id == location_id"
        in ACTIVE_ENDPOINT
    ),
    "BACKEND_CURSOR_SCOPE": (
        "_decode_stocktake_cursor" in warehouse
        and "_encode_stocktake_cursor" in warehouse
    ),
    "FULL_LOCK_STATUS_UNCHANGED": (
        "InventoryLock.product_variant_id.is_(None)"
        in warehouse
        and "InventoryLock.batch_id.is_(None)"
        in warehouse
    ),
    "STAGE4A1_COUNT_STATUS_PRESERVED": (
        "stock_status: row.stock_status" in tab
    ),
    "STAGE4A1_ATTEMPT_IDS_PRESERVED": (
        tab.count(
            "count_attempt_id: review.latest_attempt.id"
        ) == 2
    ),
    "NO_FRONTEND_ANY": (
        ": any" not in tab
        and ": any" not in combined_new
        and "Promise<any>" not in tab
    ),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(
        "Static verification failed before writes: "
        + ", ".join(failed)
    )

# ------------------------------------------------------------------
# 12) Write only after every gate passed.
# ------------------------------------------------------------------
for path, content in new_files.items():
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"UNCHANGED={path.relative_to(INV)}")
    else:
        path.write_text(content, encoding="utf-8")
        print(f"CREATED={path.relative_to(INV)}")

SCHEMAS.write_text(schemas, encoding="utf-8")
WAREHOUSE.write_text(warehouse, encoding="utf-8")
TAB.write_text(tab, encoding="utf-8")
MAIN.write_text(main, encoding="utf-8")

print("STOCKTAKE_ACTIVE_SESSION_ENDPOINT=OK")
print("STOCKTAKE_ACTIVE_SESSION_CURSOR=OK")
print("STOCKTAKE_ACTIVE_SESSION_TENANT_SCOPE=OK")
print("STOCKTAKE_SERVER_DRIVEN_RECOVERY=OK")
print("STOCKTAKE_CYCLE_SESSION_RENDERING_FOUNDATION=OK")
print("STOCKTAKE_SERVER_STATUS_AUTHORITY=OK")
print("STOCKTAKE_DOMAIN_BOUNDARY=OK")
print("STOCKTAKE_SESSION_CENTER=OK")
print("MAIN_INVENTORY_STAGE4A2A_SESSION_CENTER=OK")
