import { useState, useEffect, useCallback, useRef } from "react";
import { Package, History, Lock, RefreshCcw, FilePlus, Menu, Building2, ArrowRightLeft } from "lucide-react";
import { toast } from "sonner";
import { Tab1LiveStock } from "./Tab1LiveStock";
import { Tab2Inbound } from "./Tab2Inbound";
import { Tab3Stocktake } from "./Tab3Stocktake";
import { Tab4Ledger } from "./Tab4Ledger";
import { TabWarehouseLocations } from "./TabWarehouseLocations";
import { TabTransfers } from "./TabTransfers";
import type {
  WarehouseInventoryCursorPage,
  WarehouseProduct,
} from "./inventoryUtils";

import { useAuthFetch } from "@/hooks/useAuthFetch"; // +++ استدعاء الدستور الموحد +++

// ─── Tab config ───────────────────────────────────────────────────────────────
const TABS = [
  { id: "live", label: "الرصيد الحي", icon: Package },
  { id: "inbound", label: "توريد بضاعة", icon: FilePlus },
  { id: "transfers", label: "الحوالات", icon: ArrowRightLeft },
  { id: "ledger", label: "سجل الحركات", icon: History },
  { id: "stocktake", label: "جرد وتسوية", icon: Lock },
  { id: "warehouses", label: "إدارة المستودعات", icon: Building2 },
] as const;

type TabId = typeof TABS[number]["id"];

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
  error instanceof Error ? error.message : "حدث خطأ غير متوقع";

// ─── Main Component ───────────────────────────────────────────────────────────
export default function MainInventory() {
  const authFetch = useAuthFetch();

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
  }, [activeTab, activeTabStorageKey]);
  
  // +++ حالة اختيار المستودع +++
  const [locations, setLocations] = useState<WarehouseLocationOption[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<number | null>(null);
  const [locationError, setLocationError] = useState(false);
  const [loadingLocations, setLoadingLocations] = useState(true);
  
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
  const locationRequestSeq = useRef(0);
  const statusRequestSeq = useRef(0);

  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [isAuditLocked, setIsAuditLocked] = useState(true);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [loadingStock, setLoadingStock] = useState(false);
  const [lastSync, setLastSync] = useState<Date | null>(null);

  const fetchLocations = useCallback(async () => {
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

  // ── fetchers ────────────────────────────────────────────────────────────────
  const fetchStock = useCallback(async () => {
    if (selectedLocationId === null) return;

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

      const raw = await authFetch(
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
    } catch (error: unknown) {
      if (requestSeq !== stockRequestSeq.current) return;
      toast.error(getErrorMessage(error));
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

  // حالة القفل مرتبطة دائماً بالمستودع المحدد.
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
    setLastSync(null);
  }, [selectedLocationId]);

  useEffect(() => {
    if (selectedLocationId !== null) {
      void fetchStock();
    }
  }, [selectedLocationId, fetchStock, stockRefreshKey]);

  useEffect(() => {
    if (
      !loadingLocations &&
      !locationError &&
      locations.length === 0 &&
      activeTab !== "warehouses"
    ) {
      setActiveTab("warehouses");
    }
  }, [activeTab, loadingLocations, locationError, locations.length]);

  if (loadingLocations) {
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
              value={selectedLocationId ?? ""}
              onChange={(e) => handleLocationChange(e.target.value)}
            >
              <option value="" disabled>
                اختر المستودع
              </option>
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
              آخر تحديث: {lastSync ? lastSync.toLocaleTimeString("ar-EG") : "—"}
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
        {selectedLocationId === null && activeTab !== "warehouses" && (
          <div className="flex-1 flex items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white/50 text-slate-500 font-bold">
            لا يوجد مستودع محدد لهذه العملية. اختر مستودعاً فعالاً أو افتح إدارة المستودعات.
          </div>
        )}

        {activeTab === "live" && selectedLocationId !== null && (
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
        {activeTab === "inbound" && selectedLocationId !== null && (
          <Tab2Inbound
            locationId={selectedLocationId} // +++ تمرير الموقع لعملية الإدخال +++
            authenticatedFetch={authFetch}
            onSuccess={async () => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
            }}
          />
        )}
        {activeTab === "stocktake" && selectedLocationId !== null && (
          <Tab3Stocktake
            locationId={selectedLocationId} // +++ سحق ملاحظة P1: تمرير الموقع للمحرك המوحد +++
            companyId={companyId}
            isAuditLocked={isAuditLocked}
            authenticatedFetch={authFetch}
            onStocktakeChanged={async () => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
              await fetchStatus();
            }}
          />
        )}
        {activeTab === "ledger" && selectedLocationId !== null && (
          <Tab4Ledger
            locationId={selectedLocationId}
            refreshKey={ledgerRefreshKey}
          />
        )}

        {activeTab === "transfers" && selectedLocationId !== null && (
          <TabTransfers
            locationId={selectedLocationId}
            onInventoryChanged={async () => {
              setStockRefreshKey((value) => value + 1);
              setLedgerRefreshKey((value) => value + 1);
              await fetchStatus();
            }}
          />
        )}

        {activeTab === "warehouses" && (
          <TabWarehouseLocations
            onLocationsChanged={fetchLocations}
          />
        )}
      </div>
    </div>
  );
}
