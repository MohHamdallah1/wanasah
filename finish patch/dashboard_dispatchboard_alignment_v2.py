from __future__ import annotations

from pathlib import Path
import base64
import hashlib
import re
import zlib

ROOT = Path(__file__).resolve().parent
BOARD = ROOT / "dashboard" / "src" / "pages" / "DispatchBoard.tsx"
SCHEDULE = ROOT / "dashboard" / "src" / "components" / "dispatch" / "ScheduleModal.tsx"
TYPES = ROOT / "dashboard" / "src" / "types" / "dispatch.ts"
SCHEMAS = ROOT / "wa_backend" / "schemas.py"
DISPATCH = ROOT / "wa_backend" / "api" / "dispatch.py"

BOARD_INPUT_SHA256 = 'a53abc94008b83f7672fd2b6e434675756df647f40abc24d49e38aa7ea05cfb8'
BOARD_OUTPUT_SHA256 = '2b44cf3a499254d16f1c2842be62390f5634550c589a5c7fabf70d0293e2861c'
BOARD_ZLIB_B64 = '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'

SCHEDULE_OLD_FORM = '  schedulingForm: {\n    frequency: string;\n    visitDay: string;\n    startDate: string;\n  };\n  onSchedulingFormChange: (form: { frequency: string; visitDay: string; startDate: string }) => void;\n'
SCHEDULE_NEW_FORM = '  schedulingForm: {\n    frequency: string;\n    startDate: string;\n  };\n  onSchedulingFormChange: (form: { frequency: string; startDate: string }) => void;\n'
SCHEDULE_OLD_VISIT = '          <div className="grid grid-cols-2 gap-4">\n            <div className="space-y-1.5">\n              <span className="text-xs font-bold text-slate-500">يوم الزيارة</span>\n              <select\n                value={schedulingForm.visitDay}\n                onChange={e => onSchedulingFormChange({ ...schedulingForm, visitDay: e.target.value })}\n                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"\n              >\n                <option>السبت</option>\n                <option>الأحد</option>\n                <option>الاثنين</option>\n                <option>الثلاثاء</option>\n                <option>الأربعاء</option>\n                <option>الخميس</option>\n              </select>\n            </div>\n            <div className="space-y-1.5">\n              <span className="text-xs font-bold text-slate-500">تاريخ البدء</span>\n              <input\n                type="date"\n                min={new Date().toISOString().split(\'T\')[0]}\n                value={schedulingForm.startDate}\n                onChange={e => onSchedulingFormChange({ ...schedulingForm, startDate: e.target.value })}\n                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"\n              />\n            </div>\n          </div>\n'
SCHEDULE_NEW_VISIT = '          <div className="space-y-1.5">\n            <span className="text-xs font-bold text-slate-500">تاريخ البدء</span>\n            <input\n              type="date"\n              value={schedulingForm.startDate}\n              onChange={e => onSchedulingFormChange({ ...schedulingForm, startDate: e.target.value })}\n              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-[#1e87bb]/20"\n            />\n          </div>\n'


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"UNCHANGED={label}")
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match, found {count}")
    print(f"PATCHED={label}")
    return text.replace(old, new, 1)


for path in (BOARD, SCHEDULE, TYPES, SCHEMAS, DISPATCH):
    if not path.exists():
        fail(f"Missing file: {path.relative_to(ROOT)}")


# 1) DispatchBoard exact repair from the user-supplied current file.
board_now = BOARD.read_text(encoding="utf-8")
board_sha = sha256_text(board_now)
board_target = zlib.decompress(base64.b64decode(BOARD_ZLIB_B64)).decode("utf-8")

if board_sha == BOARD_OUTPUT_SHA256:
    print("UNCHANGED=dashboard/src/pages/DispatchBoard.tsx")
elif board_sha == BOARD_INPUT_SHA256:
    BOARD.write_text(board_target, encoding="utf-8")
    print("PATCHED=dashboard/src/pages/DispatchBoard.tsx")
else:
    fail(
        "DispatchBoard.tsx differs from the exact uploaded version. "
        f"Current SHA256={board_sha}"
    )


# 2) ScheduleModal: frozen backend stores intervalDays + startDate, not visitDay.
schedule = SCHEDULE.read_text(encoding="utf-8")
schedule = replace_once(
    schedule,
    'import { Search, Calendar } from "lucide-react";',
    'import { Search } from "lucide-react";',
    "schedule_remove_unused_calendar",
)
schedule = replace_once(
    schedule,
    SCHEDULE_OLD_FORM,
    SCHEDULE_NEW_FORM,
    "schedule_form_contract",
)
schedule = schedule.replace(
    '<option>أسبوعي (مرة في الأسبوع)</option>',
    '<option>كل 7 أيام</option>',
)
schedule = schedule.replace(
    '<option>كل أسبوعين (مرة كل 14 يوم)</option>',
    '<option>كل 14 يوم</option>',
)
schedule = schedule.replace(
    '<option>شهري (مرة في الشهر)</option>',
    '<option>كل 30 يوم</option>',
)
schedule = replace_once(
    schedule,
    SCHEDULE_OLD_VISIT,
    SCHEDULE_NEW_VISIT,
    "schedule_remove_legacy_visit_day",
)
SCHEDULE.write_text(schedule, encoding="utf-8")


# 3) Frontend shared types aligned with frozen response contracts.
types = TYPES.read_text(encoding="utf-8")
types, count = re.subn(
    r'export type ScheduleStatus = .*?;',
    'export type ScheduleStatus = "overdue" | "today" | "upcoming" | "null";',
    types,
    count=1,
)
if count != 1:
    fail("ScheduleStatus declaration not found")
print("PATCHED=dispatch_types_schedule_status")

types = types.replace('  sessionEnded?: boolean;', '  sessionEnded: boolean;')

if "  productId: string;" not in types:
    types = replace_once(
        types,
        'export interface Shortage {\n  id: string;\n',
        'export interface Shortage {\n  id: string;\n  productId: string;\n',
        "dispatch_types_shortage_product_id",
    )

types = types.replace('  waitTime?: string;', '  waitTime?: string | null;')
types = types.replace('  createdAt?: string;', '  createdAt?: string | null;')

if "  intervalDays: number | null;" not in types:
    types = replace_once(
        types,
        '  startDate: string;\n',
        '  startDate: string;\n  intervalDays: number | null;\n',
        "dispatch_types_interval_days",
    )

types = types.replace(
    '  status: "pending" | "accepted" | "rejected";',
    '  status: "pending" | "accepted" | "rejected" | "cancelled";',
)
types = types.replace('  created_at: string;', '  created_at: string | null;')
TYPES.write_text(types, encoding="utf-8")


# 4) Additive read contract: shortage response returns canonical product ID.
schemas = SCHEMAS.read_text(encoding="utf-8")
if "class ShortageResponseItem(BaseModel):\n    id: str\n    productId: str\n" not in schemas:
    schemas = replace_once(
        schemas,
        'class ShortageResponseItem(BaseModel):\n    id: str\n',
        'class ShortageResponseItem(BaseModel):\n    id: str\n    productId: str\n',
        "schemas_shortage_product_id",
    )
SCHEMAS.write_text(schemas, encoding="utf-8")


dispatch = DISPATCH.read_text(encoding="utf-8")

# Recycle-bin read contract, still strictly tenant-scoped.
shops_start = dispatch.find('@router.get("/dispatch/shops"')
shops_end = dispatch.find("# PATCH: DISPATCH_CONCURRENCY_EMERGENCY_INTEGRITY", shops_start)
if shops_start == -1 or shops_end == -1:
    fail("Could not locate /dispatch/shops endpoint")
shops_block = dispatch[shops_start:shops_end]
if "Shop.company_id == current_admin.company_id" not in shops_block:
    fail("/dispatch/shops lost tenant scope")

if "Shop.is_archived == False" in shops_block:
    shops_block = shops_block.replace("    Shop.is_archived == False\n", "", 1)
    dispatch = dispatch[:shops_start] + shops_block + dispatch[shops_end:]
    print("PATCHED=backend_archived_shops_read_contract")
else:
    print("UNCHANGED=backend_archived_shops_read_contract")

# Canonical product identity in shortage response.
shortage_start = dispatch.find('@router.get("/dispatch/shortages"')
shortage_end = dispatch.find('@router.post("/dispatch/shortages"', shortage_start)
if shortage_start == -1 or shortage_end == -1:
    fail("Could not locate shortages GET endpoint")
shortage_block = dispatch[shortage_start:shortage_end]
if '"productId": str(s.product_variant_id),' not in shortage_block:
    shortage_block = replace_once(
        shortage_block,
        '        "id": str(s.id),\n',
        '        "id": str(s.id),\n        "productId": str(s.product_variant_id),\n',
        "backend_shortage_product_id",
    )
    dispatch = dispatch[:shortage_start] + shortage_block + dispatch[shortage_end:]
else:
    print("UNCHANGED=backend_shortage_product_id")

DISPATCH.write_text(dispatch, encoding="utf-8")


# Final static gates.
board = BOARD.read_text(encoding="utf-8")
schedule = SCHEDULE.read_text(encoding="utf-8")
types = TYPES.read_text(encoding="utf-8")
schemas = SCHEMAS.read_text(encoding="utf-8")
dispatch = DISPATCH.read_text(encoding="utf-8")

shops_start = dispatch.find('@router.get("/dispatch/shops"')
shops_end = dispatch.find("# PATCH: DISPATCH_CONCURRENCY_EMERGENCY_INTEGRITY", shops_start)

checks = {
    "BOARD_EXACT_TARGET": sha256_text(board) == BOARD_OUTPUT_SHA256,
    "NO_EXPLICIT_ANY": re.search(r"\bany\b", board) is None,
    "SOURCE_WAREHOUSE_SELECTOR": 'label="مستودع المصدر"' in board,
    "SOURCE_WAREHOUSE_PAYLOAD": "source_location_id: Number(selectedSourceWarehouseId)" in board,
    "NO_LEGACY_SCHEDULE_PAYLOAD": (
        "frequency: schedulingForm.frequency" not in board
        and "visitDay: schedulingForm" not in board
        and "customDays: schedulingForm" not in board
    ),
    "NUMERIC_SCHEDULE_PAYLOAD": "intervalDays," in board,
    "NO_ZONE_VISIT_DAY_LOGIC": "zone.visitDay" not in board,
    "WS_ALERT_BURST_GUARD": "queueWorkerAlert" in board and "workerAlerts" in board,
    "WS_LATEST_TOKEN": 'localStorage.getItem("admin_token")' in board,
    "VEHICLE_ABORT_GUARD": "return () => controller.abort();" in board,
    "HOOK_DEPS_HARDENED": (
        "[authenticatedFetch, fetchInitialData, selectedZoneIdForZones, shops]" in board
        and "[authenticatedFetch]);" in board
    ),
    "SHORTAGE_STRICT_PAYLOAD": (
        "productId: Number(item.productId)" in board
        and "zoneName:" not in board[board.find("const newShortages"):board.find("try {", board.find("const newShortages"))]
    ),
    "SHORTAGE_CANONICAL_PRODUCT_ID": "productId: s.productId" in board,
    "SCHEDULE_MODAL_NO_VISIT_DAY": "visitDay" not in schedule,
    "SCHEDULE_MODAL_NUMERIC_LABELS": (
        "كل 7 أيام" in schedule and "كل 14 يوم" in schedule and "كل 30 يوم" in schedule
    ),
    "TYPE_INTERVAL_DAYS": "intervalDays: number | null;" in types,
    "TYPE_TRANSFER_CANCELLED": '"cancelled"' in types,
    "TYPE_SHORTAGE_PRODUCT_ID": "productId: string;" in types,
    "SCHEMA_SHORTAGE_PRODUCT_ID": "class ShortageResponseItem(BaseModel):\n    id: str\n    productId: str" in schemas,
    "BACKEND_SHOPS_TENANT_SCOPE": "Shop.company_id == current_admin.company_id" in dispatch[shops_start:shops_end],
    "BACKEND_SHOPS_INCLUDE_ARCHIVED": "Shop.is_archived == False" not in dispatch[shops_start:shops_end],
    "BACKEND_SHORTAGE_PRODUCT_ID": '"productId": str(s.product_variant_id),' in dispatch,
    "NO_OLD_WAREHOUSE_ENGINE_NAMES": "MainWarehouse" not in board and "WarehouseLedger" not in board,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

print("DISPATCHBOARD_LINT_ANY_GATE=OK")
print("DISPATCHBOARD_TENANT_SCOPE_CONTRACT=OK")
print("DISPATCHBOARD_SOURCE_WAREHOUSE_CONTRACT=OK")
print("DISPATCHBOARD_NUMERIC_SCHEDULING_CONTRACT=OK")
print("DISPATCHBOARD_REALTIME_BURST_GUARD=OK")
print("DISPATCHBOARD_SHORTAGE_ID_CONTRACT=OK")
print("DISPATCHBOARD_ARCHIVE_READ_CONTRACT=OK")
print("DASHBOARD_DISPATCHBOARD_ALIGNMENT_V2=OK")
