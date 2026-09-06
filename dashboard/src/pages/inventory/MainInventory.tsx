import { useState, useEffect, useCallback, useRef } from "react";
import { Package, History, Lock, RefreshCcw, FilePlus, Menu } from "lucide-react";
import { toast } from "sonner";
import { Tab1LiveStock } from "./Tab1LiveStock";
import { Tab2Inbound } from "./Tab2Inbound";
import { Tab3Stocktake } from "./Tab3Stocktake";
import { Tab4Ledger } from "./Tab4Ledger";
import type { WarehouseProduct } from "./inventoryUtils";

import { useAuthFetch } from "@/hooks/useAuthFetch"; // +++ استدعاء الدستور الموحد +++

// ─── Tab config ───────────────────────────────────────────────────────────────
const TABS = [
  { id: "live", label: "الرصيد الحي", icon: Package },
  { id: "inbound", label: "توريد بضاعة", icon: FilePlus },
  { id: "ledger", label: "سجل الحركات", icon: History },
  { id: "stocktake", label: "جرد وتسوية", icon: Lock },
] as const;

type TabId = typeof TABS[number]["id"];

// ─── Main Component ───────────────────────────────────────────────────────────
export default function MainInventory() {
  const authFetch = useAuthFetch();

  const [activeTab, setActiveTab] = useState<TabId>(() => (localStorage.getItem("inventory_active_tab") as TabId) || "live");
  useEffect(() => { localStorage.setItem("inventory_active_tab", activeTab); }, [activeTab]);
  
  // +++ حالة اختيار المستودع +++
  const [locations, setLocations] = useState<{ id: number, name: string, code: string }[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(null);
  const [locationError, setLocationError] = useState<boolean>(false); // +++ التفرقة بين فشل الشبكة والمستودع الفارغ +++
  
  const [stockItems, setStockItems] = useState<WarehouseProduct[]>([]);
  const [stockTotal, setStockTotal] = useState<number | null>(null);
  const [stockMatchingTotal, setStockMatchingTotal] = useState<number | null>(null);
  const [stockAlertCount, setStockAlertCount] = useState(0);
  const [stockAlertSamples, setStockAlertSamples] = useState<string[]>([]);
  const [stockCursor, setStockCursor] = useState<string | null>(null);
  const [stockCursorHistory, setStockCursorHistory] = useState<Array<string | null>>([]);
  const [stockNextCursor, setStockNextCursor] = useState<string | null>(null);
  const [stockSearch, setStockSearch] = useState("");
  const [stockOnlyAlerts, setStockOnlyAlerts] = useState(false);
  const [stockRefreshKey, setStockRefreshKey] = useState(0);
  const stockRequestSeq = useRef(0);

  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [isAuditLocked, setIsAuditLocked] = useState<boolean>(true);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingStock, setLoadingStock] = useState(false);
  const [lastSync, setLastSync] = useState<Date>(new Date());

  // جلب المستودعات المتاحة للشركة عند الدخول
  useEffect(() => {
    const fetchLocations = async () => {
      try {
        setLocationError(false);
        const data = await authFetch("/warehouse/locations");
        if (Array.isArray(data) && data.length > 0) {
          setLocations(data);
          setSelectedLocationId(data[0].id); // التحديد التلقائي لأول مستودع متاح
        }
      } catch (e: any) {
        setLocationError(true);
        toast.error("فشل الاتصال بالخادم لجلب المستودعات.");
      }
    };
    fetchLocations();
  }, [authFetch]);

  // ── fetchers ────────────────────────────────────────────────────────────────
  const fetchStock = useCallback(async () => {
    if (!selectedLocationId) return;

    const requestSeq = ++stockRequestSeq.current;
    setLoadingStock(true);

    try {
      const params = new URLSearchParams({
        location_id: String(selectedLocationId),
        limit: "50",
      });

      if (stockCursor) params.set("cursor", stockCursor);
      if (stockSearch) params.set("search", stockSearch);
      if (stockOnlyAlerts) params.set("only_alerts", "true");

      const data = await authFetch(
        `/warehouse/inventory/cursor?${params.toString()}`
      );

      if (requestSeq !== stockRequestSeq.current) return;
      if (!data || !Array.isArray(data.items)) {
        throw new Error("تنسيق صفحة المخزون غير صالح");
      }

      setStockItems(data.items);
      setStockNextCursor(data.next_cursor || null);

      if (typeof data.total === "number") {
        setStockMatchingTotal(data.total);

        if (!stockSearch && !stockOnlyAlerts && stockCursor === null) {
          setStockTotal(data.total);
        }
      }

      if (!stockSearch && !stockOnlyAlerts && stockCursor === null) {
        if (typeof data.alert_count === "number") {
          setStockAlertCount(data.alert_count);
        }
        if (Array.isArray(data.alert_samples)) {
          setStockAlertSamples(data.alert_samples);
        }
      }

      setLastSync(new Date());
    } catch (e: any) {
      if (requestSeq !== stockRequestSeq.current) return;
      toast.error(e?.message || "خطأ حرج في جلب المخزون");
      setStockItems([]);
      setStockNextCursor(null);
      setStockMatchingTotal(null);
    } finally {
      if (requestSeq === stockRequestSeq.current) {
        setLoadingStock(false);
      }
    }
  }, [
    authFetch,
    selectedLocationId,
    stockCursor,
    stockSearch,
    stockOnlyAlerts,
    stockRefreshKey,
  ]);

  const resetStockPagination = useCallback(() => {
    setStockCursor(null);
    setStockCursorHistory([]);
    setStockNextCursor(null);
    setStockMatchingTotal(null);
  }, []);

  const refreshStock = useCallback(() => {
    resetStockPagination();
    setStockRefreshKey((value) => value + 1);
  }, [resetStockPagination]);

  const handleStockSearchChange = useCallback((value: string) => {
    resetStockPagination();
    setStockSearch(value);
  }, [resetStockPagination]);

  const handleStockAlertsChange = useCallback((value: boolean) => {
    resetStockPagination();
    setStockOnlyAlerts(value);
  }, [resetStockPagination]);

  const handleStockNext = useCallback(() => {
    if (!stockNextCursor) return;
    setStockCursorHistory((prev) => [...prev, stockCursor]);
    setStockCursor(stockNextCursor);
  }, [stockCursor, stockNextCursor]);

  const handleStockPrevious = useCallback(() => {
    if (stockCursorHistory.length === 0) return;
    const previousCursor = stockCursorHistory[stockCursorHistory.length - 1] ?? null;
    setStockCursorHistory((prev) => prev.slice(0, -1));
    setStockCursor(previousCursor);
  }, [stockCursorHistory]);

  // جلب حالة القفل للمستودع المحدد فقط دون التأثير على باقي المستودعات.
  const fetchStatus = useCallback(async () => {
    if (!selectedLocationId) {
      setIsAuditLocked(false);
      return;
    }

    setLoadingStatus(true);

    try {
      const data = await authFetch(
        `/warehouse/status?location_id=${selectedLocationId}`
      );

      if (data) {
        setIsAuditLocked(data.status === "AUDIT_LOCK");
      }
    } catch (e: any) {
      toast.error(
        "خطأ حرج: تعذر التأكد من حالة قفل المستودع المحدد."
      );
      setIsAuditLocked(true);
    } finally {
      setLoadingStatus(false);
    }
  }, [authFetch, selectedLocationId]);

  // ── on mount ────────────────────────────────────────────────────────────────
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    stockRequestSeq.current += 1;
    setStockItems([]);
    setStockTotal(null);
    setStockMatchingTotal(null);
    setStockAlertCount(0);
    setStockAlertSamples([]);
    setStockSearch("");
    setStockOnlyAlerts(false);
    setStockCursor(null);
    setStockCursorHistory([]);
    setStockNextCursor(null);
  }, [selectedLocationId]);

  useEffect(() => {
    if (selectedLocationId) fetchStock();
  }, [selectedLocationId, fetchStock]);

  // +++ الدرع المعماري (P2 Fixed): حماية الشاشة البيضاء في حال انعدام المواقع (مع استثناء فشل الشبكة) +++
  if (!loadingStatus && locations.length === 0 && !locationError) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full bg-slate-50/50 rounded-3xl border border-slate-200 p-8 text-center animate-in fade-in duration-500">
        <div className="w-24 h-24 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mb-6 shadow-inner">
          <Package className="w-10 h-10" />
        </div>
        <h2 className="text-2xl font-black text-slate-800 mb-2">لا توجد مستودعات متاحة</h2>
        <p className="text-slate-500 font-bold max-w-md">
          لم يتم العثور على أي مستودعات فعالة لشركتك. يرجى التواصل مع الدعم الفني أو تحديث الصفحة لتوليد المستودع الرئيسي تلقائياً.
        </p>
        <button onClick={() => window.location.reload()} className="mt-8 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg transition-all active:scale-95 flex items-center gap-2">
          <RefreshCcw className="w-5 h-5" /> تحديث النظام
        </button>
      </div>
    );
  }

  // ─── UI ─────────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4 w-full h-full flex-1 min-h-0 animate-in fade-in duration-200">

      {/* ═══ Tab Bar ═══ */}
      {/* +++ الكي الجراحي: إضافة الارتفاع h-16 md:h-20 وتدوير الزوايا rounded-2xl ليطابق البار الرئيسي +++ */}
      <nav className="glass-card h-16 md:h-20 rounded-2xl px-3 md:px-6 py-2 flex items-center justify-between gap-1">
        <div className="flex items-center gap-1">
          {TABS.map(({ id, label, icon: Icon }) => {
            const active = activeTab === id;
            return (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all ${active
                  ? "bg-blue-500 text-white shadow-md shadow-blue-500/20"
                  : "text-slate-600 hover:text-slate-800 hover:bg-white/60"
                  }`}
              >
                <Icon className="w-4 h-4" />
                <span className="hidden sm:inline">{label}</span>
              </button>
            );
          })}
        </div>

        {/* +++ الحقن المعماري: نقل معلومات الرصيد الحي، وقت التحديث، وزر التحديث الكامل للبار العلوي +++ */}
        <div className="flex items-center gap-4 px-2">
          {/* +++ محدد المستودعات +++ */}
          {locations.length > 0 && (
            <select
              className="bg-slate-50 border border-slate-200 text-slate-700 text-xs font-bold rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
              value={selectedLocationId || ""}
              onChange={(e) => setSelectedLocationId(Number(e.target.value))}
            >
              {locations.map(loc => (
                <option key={loc.id} value={loc.id}>
                  {loc.name}
                </option>
              ))}
            </select>
          )}

          <div className="flex flex-col items-end border-l border-slate-200 pl-4 justify-center">
            <div className="flex items-center gap-2">
              <Package className="w-4 h-4 text-[#1e87bb]" />
              <span className="text-sm font-black text-slate-700">
                الرصيد الحي — <span className="text-[#1e87bb]">{stockTotal ?? "—"}</span> صنف
              </span>
              {isAuditLocked && (
                <span className="text-[10px] font-bold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-md border border-amber-200">
                  مقفل 🔒
                </span>
              )}
            </div>
            <span className="text-[10px] font-bold text-slate-400 mt-0.5">
              آخر تحديث: {lastSync.toLocaleTimeString("ar-EG")}
            </span>
          </div>
          <button
            onClick={() => { refreshStock(); fetchStatus(); }}
            disabled={loadingStock}
            className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 text-xs font-bold text-slate-600 rounded-xl hover:bg-slate-50 hover:text-[#1e87bb] hover:border-[#1e87bb]/30 transition-all shadow-sm disabled:opacity-50 active:scale-95"
          >
            <RefreshCcw className={`w-3.5 h-3.5 ${loadingStock ? "animate-spin" : ""}`} />
            تحديث
          </button>
        </div>
      </nav>

      {/* ═══ Tab Content ═══ */}
      <div className="flex-1 min-h-0 flex flex-col">
        {activeTab === "live" && selectedLocationId && (
          <Tab1LiveStock
            locationId={selectedLocationId}
            products={stockItems}
            loading={loadingStock}
            alertCount={stockAlertCount}
            alertSamples={stockAlertSamples}
            matchingTotal={stockMatchingTotal}
            pageNumber={stockCursorHistory.length + 1}
            hasMore={!!stockNextCursor}
            hasPrevious={stockCursorHistory.length > 0}
            onlyAlerts={stockOnlyAlerts}
            onSearchChange={handleStockSearchChange}
            onOnlyAlertsChange={handleStockAlertsChange}
            onNext={handleStockNext}
            onPrevious={handleStockPrevious}
            onRefresh={refreshStock}
          />
        )}
        {activeTab === "inbound" && selectedLocationId && (
          <Tab2Inbound
            locationId={selectedLocationId} // +++ تمرير الموقع لعملية الإدخال +++
            authenticatedFetch={authFetch}
            onSuccess={async () => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
            }}
          />
        )}
        {activeTab === "stocktake" && selectedLocationId && (
          <Tab3Stocktake
            locationId={selectedLocationId} // +++ سحق ملاحظة P1: تمرير الموقع للمحرك המوحد +++
            isAuditLocked={isAuditLocked}
            authenticatedFetch={authFetch}
            onLockChange={async (locked) => {
              setIsAuditLocked(locked);
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
            }}
          />
        )}
        {activeTab === "ledger" && selectedLocationId && (
          <Tab4Ledger
            locationId={selectedLocationId}
            refreshKey={ledgerRefreshKey}
          />
        )}
      </div>
    </div>
  );
}
