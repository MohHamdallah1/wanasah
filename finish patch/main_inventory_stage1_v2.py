
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "dashboard" / "src" / "pages" / "inventory" / "MainInventory.tsx"


def fail(message: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"UNCHANGED={label}")
        return text
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match, found {count}")
    print(f"PATCHED={label}")
    return text.replace(old, new, 1)


if not TARGET.exists():
    fail(f"Missing file: {TARGET.relative_to(ROOT)}")

text = TARGET.read_text(encoding="utf-8")

text = replace_once(
    text,
    'import type { WarehouseProduct } from "./inventoryUtils";',
    '''import type {
  WarehouseInventoryCursorPage,
  WarehouseProduct,
} from "./inventoryUtils";''',
    "inventory_page_type_import",
)

text = replace_once(
    text,
    'type TabId = typeof TABS[number]["id"];',
    '''type TabId = typeof TABS[number]["id"];

interface WarehouseLocationOption {
  id: number;
  name: string;
  code: string;
}

interface WarehouseStatusPayload {
  status: string;
}

const isTabId = (value: string | null): value is TabId =>
  TABS.some((tab) => tab.id === value);

const getErrorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "حدث خطأ غير متوقع";''',
    "inventory_local_contracts",
)

text = replace_once(
    text,
    '''  const authFetch = useAuthFetch();

  const [activeTab, setActiveTab] = useState<TabId>(() => (localStorage.getItem("inventory_active_tab") as TabId) || "live");
  useEffect(() => { localStorage.setItem("inventory_active_tab", activeTab); }, [activeTab]);''',
    '''  const authFetch = useAuthFetch();

  // UI preference only. Server token + RLS remain the security authority.
  const companyId = localStorage.getItem("company_id") || "";
  const activeTabStorageKey = companyId
    ? `inventory_active_tab:${companyId}`
    : "inventory_active_tab:anonymous";
  const selectedLocationStorageKey = companyId
    ? `inventory_selected_location:${companyId}`
    : "inventory_selected_location:anonymous";

  const [activeTab, setActiveTab] = useState<TabId>(() => {
    const saved = localStorage.getItem(activeTabStorageKey);
    return isTabId(saved) ? saved : "live";
  });

  useEffect(() => {
    localStorage.removeItem("inventory_active_tab");
    localStorage.setItem(activeTabStorageKey, activeTab);
  }, [activeTab, activeTabStorageKey]);''',
    "tenant_scoped_active_tab",
)

text = replace_once(
    text,
    '''  const [locations, setLocations] = useState<{ id: number, name: string, code: string }[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(null);
  const [locationError, setLocationError] = useState<boolean>(false); // +++ التفرقة بين فشل الشبكة والمستودع الفارغ +++''',
    '''  const [locations, setLocations] = useState<WarehouseLocationOption[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(null);
  const [locationError, setLocationError] = useState(false);
  const [loadingLocations, setLoadingLocations] = useState(true);''',
    "typed_location_state",
)

text = replace_once(
    text,
    '''  const [stockRefreshKey, setStockRefreshKey] = useState(0);
  const stockRequestSeq = useRef(0);

  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [isAuditLocked, setIsAuditLocked] = useState<boolean>(true);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingStock, setLoadingStock] = useState(false);
  const [lastSync, setLastSync] = useState<Date>(new Date());''',
    '''  const [stockRefreshKey, setStockRefreshKey] = useState(0);
  const stockRequestSeq = useRef(0);
  const locationRequestSeq = useRef(0);
  const statusRequestSeq = useRef(0);

  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [isAuditLocked, setIsAuditLocked] = useState(true);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [loadingStock, setLoadingStock] = useState(false);
  const [lastSync, setLastSync] = useState<Date | null>(null);''',
    "inventory_request_guards",
)

pattern = re.compile(
    r'''  // جلب المستودعات المتاحة للشركة عند الدخول\n'''
    r'''  useEffect\(\(\) => \{\n'''
    r'''    const fetchLocations = async \(\) => \{\n'''
    r'''      try \{\n'''
    r'''        setLocationError\(false\);\n'''
    r'''        const data = await authFetch\("/warehouse/locations"\);\n'''
    r'''        if \(Array\.isArray\(data\) && data\.length > 0\) \{\n'''
    r'''          setLocations\(data\);\n'''
    r'''          setSelectedLocationId\(data\[0\]\.id\);[^\n]*\n'''
    r'''        \}\n'''
    r'''      \} catch \(e: any\) \{\n'''
    r'''        setLocationError\(true\);\n'''
    r'''        toast\.error\("فشل الاتصال بالخادم لجلب المستودعات\."\);\n'''
    r'''      \}\n'''
    r'''    \};\n'''
    r'''    fetchLocations\(\);\n'''
    r'''  \}, \[authFetch\]\);\n'''
)

new_loader = '''  const fetchLocations = useCallback(async () => {
    const requestSeq = ++locationRequestSeq.current;
    setLoadingLocations(true);
    setLocationError(false);

    try {
      const raw = await authFetch("/warehouse/locations");
      if (requestSeq !== locationRequestSeq.current) return;

      if (!Array.isArray(raw)) {
        throw new Error("تنسيق قائمة المستودعات غير صالح.");
      }

      const parsed: WarehouseLocationOption[] = raw.map((item: unknown) => {
        if (typeof item !== "object" || item === null) {
          throw new Error("عنصر مستودع غير صالح.");
        }

        const row = item as Record<string, unknown>;
        if (
          typeof row.id !== "number" ||
          !Number.isInteger(row.id) ||
          row.id <= 0 ||
          typeof row.name !== "string" ||
          typeof row.code !== "string"
        ) {
          throw new Error("بيانات مستودع غير مكتملة.");
        }

        return {
          id: row.id,
          name: row.name,
          code: row.code,
        };
      });

      setLocations(parsed);

      const savedRaw = localStorage.getItem(selectedLocationStorageKey);
      const savedId = savedRaw ? Number(savedRaw) : null;
      const savedIsValid =
        savedId !== null &&
        Number.isInteger(savedId) &&
        parsed.some((location) => location.id === savedId);

      if (savedIsValid) {
        setSelectedLocationId(savedId);
      } else {
        localStorage.removeItem(selectedLocationStorageKey);
        setSelectedLocationId(null);
      }
    } catch (error: unknown) {
      if (requestSeq !== locationRequestSeq.current) return;

      setLocations([]);
      setSelectedLocationId(null);
      setLocationError(true);
      toast.error("فشل جلب مستودعات الشركة: " + getErrorMessage(error));
    } finally {
      if (requestSeq === locationRequestSeq.current) {
        setLoadingLocations(false);
      }
    }
  }, [authFetch, selectedLocationStorageKey]);

  useEffect(() => {
    void fetchLocations();
  }, [fetchLocations]);

  const handleLocationChange = useCallback(
    (value: string) => {
      const nextId = Number(value);

      if (
        !Number.isInteger(nextId) ||
        !locations.some((location) => location.id === nextId)
      ) {
        setSelectedLocationId(null);
        localStorage.removeItem(selectedLocationStorageKey);
        return;
      }

      setSelectedLocationId(nextId);
      localStorage.setItem(selectedLocationStorageKey, String(nextId));
    },
    [locations, selectedLocationStorageKey]
  );
'''

if "setSelectedLocationId(data[0].id)" in text:
    text, count = pattern.subn(new_loader, text, count=1)
    if count != 1:
        fail("warehouse_location_loader: current block did not match")
    print("PATCHED=warehouse_location_loader")
elif "const fetchLocations = useCallback(async () => {" in text:
    print("UNCHANGED=warehouse_location_loader")
else:
    fail("warehouse_location_loader: neither old nor new block found")

text = replace_once(
    text,
    '''  const fetchStock = useCallback(async () => {
    if (!selectedLocationId) return;''',
    '''  const fetchStock = useCallback(async () => {
    if (selectedLocationId === null) return;''',
    "stock_explicit_location_guard",
)

text = replace_once(
    text,
    '''      const data = await authFetch(
        `/warehouse/inventory/cursor?${params.toString()}`
      );

      if (requestSeq !== stockRequestSeq.current) return;
      if (!data || !Array.isArray(data.items)) {
        throw new Error("تنسيق صفحة المخزون غير صالح");
      }

      setStockItems(data.items);''',
    '''      const raw = await authFetch(
        `/warehouse/inventory/cursor?${params.toString()}`
      );

      if (requestSeq !== stockRequestSeq.current) return;
      if (
        typeof raw !== "object" ||
        raw === null ||
        !("items" in raw) ||
        !Array.isArray((raw as { items?: unknown }).items)
      ) {
        throw new Error("تنسيق صفحة المخزون غير صالح");
      }

      const data = raw as WarehouseInventoryCursorPage;
      setStockItems(data.items);''',
    "typed_stock_cursor_response",
)

text = replace_once(
    text,
    '''    } catch (e: any) {
      if (requestSeq !== stockRequestSeq.current) return;
      toast.error(e?.message || "خطأ حرج في جلب المخزون");''',
    '''    } catch (error: unknown) {
      if (requestSeq !== stockRequestSeq.current) return;
      toast.error(getErrorMessage(error));''',
    "stock_unknown_error",
)

text = replace_once(
    text,
    '''    stockSearch,
    stockOnlyAlerts,
    stockRefreshKey,
  ]);''',
    '''    stockSearch,
    stockOnlyAlerts,
  ]);''',
    "remove_fake_callback_dependency",
)

status_pattern = re.compile(
    r'''  // جلب حالة القفل للمستودع المحدد فقط دون التأثير على باقي المستودعات\.\n'''
    r'''  const fetchStatus = useCallback\(async \(\) => \{\n'''
    r'''    if \(!selectedLocationId\) \{\n'''
    r'''      setIsAuditLocked\(false\);\n'''
    r'''      return;\n'''
    r'''    \}\n\n'''
    r'''    setLoadingStatus\(true\);\n\n'''
    r'''    try \{\n'''
    r'''      const data = await authFetch\(\n'''
    r'''        `/warehouse/status\?location_id=\$\{selectedLocationId\}`\n'''
    r'''      \);\n\n'''
    r'''      if \(data\) \{\n'''
    r'''        setIsAuditLocked\(data\.status === "AUDIT_LOCK"\);\n'''
    r'''      \}\n'''
    r'''    \} catch \(e: any\) \{\n'''
    r'''      toast\.error\(\n'''
    r'''        "خطأ حرج: تعذر التأكد من حالة قفل المستودع المحدد\."\n'''
    r'''      \);\n'''
    r'''      setIsAuditLocked\(true\);\n'''
    r'''    \} finally \{\n'''
    r'''      setLoadingStatus\(false\);\n'''
    r'''    \}\n'''
    r'''  \}, \[authFetch, selectedLocationId\]\);\n'''
)

new_status = '''  // حالة القفل مرتبطة دائماً بالمستودع المحدد.
  const fetchStatus = useCallback(async () => {
    const requestSeq = ++statusRequestSeq.current;

    if (selectedLocationId === null) {
      setIsAuditLocked(false);
      setLoadingStatus(false);
      return;
    }

    setLoadingStatus(true);

    try {
      const raw = await authFetch(
        `/warehouse/status?location_id=${encodeURIComponent(
          String(selectedLocationId)
        )}`
      );

      if (requestSeq !== statusRequestSeq.current) return;
      if (typeof raw !== "object" || raw === null || !("status" in raw)) {
        throw new Error("تنسيق حالة المستودع غير صالح.");
      }

      const data = raw as WarehouseStatusPayload;
      setIsAuditLocked(data.status === "AUDIT_LOCK");
    } catch (error: unknown) {
      if (requestSeq !== statusRequestSeq.current) return;

      toast.error(
        "خطأ حرج: تعذر التأكد من حالة قفل المستودع المحدد: " +
          getErrorMessage(error)
      );
      setIsAuditLocked(true);
    } finally {
      if (requestSeq === statusRequestSeq.current) {
        setLoadingStatus(false);
      }
    }
  }, [authFetch, selectedLocationId]);
'''

if "catch (e: any)" in text and "/warehouse/status?location_id=${selectedLocationId}" in text:
    text, count = status_pattern.subn(new_status, text, count=1)
    if count != 1:
        fail("warehouse_status_loader: current block did not match")
    print("PATCHED=warehouse_status_loader")
elif "const requestSeq = ++statusRequestSeq.current;" in text:
    print("UNCHANGED=warehouse_status_loader")
else:
    fail("warehouse_status_loader: neither old nor new block found")

text = replace_once(
    text,
    '''    setStockCursorHistory([]);
    setStockNextCursor(null);
  }, [selectedLocationId]);''',
    '''    setStockCursorHistory([]);
    setStockNextCursor(null);
    setLastSync(null);
  }, [selectedLocationId]);''',
    "reset_location_bound_sync_state",
)

text = replace_once(
    text,
    '''  useEffect(() => {
    if (selectedLocationId) fetchStock();
  }, [selectedLocationId, fetchStock]);''',
    '''  useEffect(() => {
    if (selectedLocationId !== null) {
      void fetchStock();
    }
  }, [selectedLocationId, fetchStock, stockRefreshKey]);''',
    "stock_refresh_effect",
)

empty_pattern = re.compile(
    r'''  // \+\+\+ الدرع المعماري \(P2 Fixed\): حماية الشاشة البيضاء في حال انعدام المواقع \(مع استثناء فشل الشبكة\) \+\+\+\n'''
    r'''  if \(!loadingStatus && locations\.length === 0 && !locationError\) \{\n'''
    r'''    return \(\n'''
    r'''      <div className="flex flex-col items-center justify-center h-full w-full bg-slate-50/50 rounded-3xl border border-slate-200 p-8 text-center animate-in fade-in duration-500">\n'''
    r'''        <div className="w-24 h-24 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mb-6 shadow-inner">\n'''
    r'''          <Package className="w-10 h-10" />\n'''
    r'''        </div>\n'''
    r'''        <h2 className="text-2xl font-black text-slate-800 mb-2">لا توجد مستودعات متاحة</h2>\n'''
    r'''        <p className="text-slate-500 font-bold max-w-md">\n'''
    r'''          لم يتم العثور على أي مستودعات فعالة لشركتك\. يرجى التواصل مع الدعم الفني أو تحديث الصفحة لتوليد المستودع الرئيسي تلقائياً\.\n'''
    r'''        </p>\n'''
    r'''        <button onClick=\{\(\) => window\.location\.reload\(\)\} className="mt-8 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg transition-all active:scale-95 flex items-center gap-2">\n'''
    r'''          <RefreshCcw className="w-5 h-5" /> تحديث النظام\n'''
    r'''        </button>\n'''
    r'''      </div>\n'''
    r'''    \);\n'''
    r'''  \}\n'''
)

new_empty = '''  if (loadingLocations) {
    return (
      <div className="flex items-center justify-center h-full w-full text-slate-500 font-bold">
        <RefreshCcw className="w-5 h-5 ml-2 animate-spin" />
        جاري جلب مستودعات الشركة...
      </div>
    );
  }

  if (locationError) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full bg-slate-50/50 rounded-3xl border border-red-200 p-8 text-center">
        <Package className="w-10 h-10 text-red-500 mb-4" />
        <h2 className="text-xl font-black text-slate-800 mb-2">
          تعذر جلب مستودعات الشركة
        </h2>
        <p className="text-slate-500 font-bold max-w-md">
          تم إيقاف واجهة المخزون احترازياً حتى نتأكد من المواقع التابعة للشركة الحالية.
        </p>
        <button
          onClick={() => void fetchLocations()}
          className="mt-6 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg transition-all active:scale-95 flex items-center gap-2"
        >
          <RefreshCcw className="w-5 h-5" /> إعادة المحاولة
        </button>
      </div>
    );
  }

  if (locations.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full bg-slate-50/50 rounded-3xl border border-slate-200 p-8 text-center">
        <div className="w-24 h-24 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mb-6 shadow-inner">
          <Package className="w-10 h-10" />
        </div>
        <h2 className="text-2xl font-black text-slate-800 mb-2">
          لا يوجد مستودع فعال
        </h2>
        <p className="text-slate-500 font-bold max-w-md">
          الشركة الحالية لا تملك مستودعاً فعالاً يمكن تنفيذ عمليات المخزون عليه.
        </p>
      </div>
    );
  }
'''

if "if (!loadingStatus && locations.length === 0 && !locationError)" in text:
    text, count = empty_pattern.subn(new_empty, text, count=1)
    if count != 1:
        fail("location_empty_state: current block did not match")
    print("PATCHED=location_empty_state")
elif "if (loadingLocations)" in text:
    print("UNCHANGED=location_empty_state")
else:
    fail("location_empty_state: neither old nor new block found")

text = replace_once(
    text,
    '''              value={selectedLocationId || ""}
              onChange={(e) => setSelectedLocationId(Number(e.target.value))}
            >
              {locations.map(loc => (''',
    '''              value={selectedLocationId ?? ""}
              onChange={(e) => handleLocationChange(e.target.value)}
            >
              <option value="" disabled>
                اختر المستودع
              </option>
              {locations.map(loc => (''',
    "explicit_location_selector",
)

text = replace_once(
    text,
    '              آخر تحديث: {lastSync.toLocaleTimeString("ar-EG")}',
    '              آخر تحديث: {lastSync ? lastSync.toLocaleTimeString("ar-EG") : "—"}',
    "nullable_last_sync",
)

text = replace_once(
    text,
    '''      {/* ═══ Tab Content ═══ */}
      <div className="flex-1 min-h-0 flex flex-col">
        {activeTab === "live" && selectedLocationId && (''',
    '''      {/* ═══ Tab Content ═══ */}
      <div className="flex-1 min-h-0 flex flex-col">
        {selectedLocationId === null && (
          <div className="flex-1 flex items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white/50 text-slate-500 font-bold">
            اختر مستودعاً صراحةً قبل عرض أو تنفيذ أي عملية مخزنية.
          </div>
        )}

        {activeTab === "live" && selectedLocationId !== null && (''',
    "no_location_operation_gate",
)

text = text.replace(
    '{activeTab === "inbound" && selectedLocationId && (',
    '{activeTab === "inbound" && selectedLocationId !== null && (',
)
text = text.replace(
    '{activeTab === "stocktake" && selectedLocationId && (',
    '{activeTab === "stocktake" && selectedLocationId !== null && (',
)
text = text.replace(
    '{activeTab === "ledger" && selectedLocationId && (',
    '{activeTab === "ledger" && selectedLocationId !== null && (',
)

checks = {
    "NO_AUTO_FIRST_LOCATION": "setSelectedLocationId(data[0].id)" not in text,
    "TENANT_SCOPED_TAB": "inventory_active_tab:${companyId}" in text,
    "TENANT_SCOPED_LOCATION": "inventory_selected_location:${companyId}" in text,
    "SAVED_LOCATION_REVALIDATED": "parsed.some((location) => location.id === savedId)" in text,
    "LOCATION_ID_ON_STATUS": "/warehouse/status?location_id=" in text,
    "STATUS_RACE_GUARD": "statusRequestSeq" in text,
    "STOCK_RACE_GUARD": "stockRequestSeq" in text,
    "NO_EXPLICIT_ANY": ": any" not in text and "catch (e: any)" not in text,
    "REFRESH_KEY_EFFECT": "[selectedLocationId, fetchStock, stockRefreshKey]" in text,
    "NO_REFRESH_KEY_CALLBACK_HACK": "stockOnlyAlerts,\n    stockRefreshKey," not in text,
    "EXPLICIT_LOCATION_PLACEHOLDER": "اختر المستودع" in text,
    "FAIL_CLOSED_LOCATION_ERROR": "تم إيقاف واجهة المخزون احترازياً" in text,
    "NO_CHILD_WITHOUT_LOCATION": "selectedLocationId === null && (" in text,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

TARGET.write_text(text, encoding="utf-8")

print("MAIN_INVENTORY_NO_AUTO_LOCATION=OK")
print("MAIN_INVENTORY_TENANT_UI_SCOPE=OK")
print("MAIN_INVENTORY_LOCATION_ID_GATE=OK")
print("MAIN_INVENTORY_STATUS_RACE_GUARD=OK")
print("MAIN_INVENTORY_FAIL_CLOSED=OK")
print("MAIN_INVENTORY_ESLINT_ANY_GATE=OK")
print("MAIN_INVENTORY_STAGE1_V2=OK")
