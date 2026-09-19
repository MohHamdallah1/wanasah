import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { TabInventoryAccess } from "./TabInventoryAccess";
import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Package, History, Lock, RefreshCcw, FilePlus, Building2, ArrowRightLeft } from "lucide-react";
import { toast } from "sonner";
import { apiErrorMessage } from "@/lib/apiErrors";
import { Tab1LiveStock } from "./Tab1LiveStock";
import { Tab2Inbound } from "./Tab2Inbound";
import { Tab3Stocktake } from "./Tab3Stocktake";
import { Tab4Ledger } from "./Tab4Ledger";
import { TabWarehouseLocations } from "./TabWarehouseLocations";
import { TabTransfers } from "./TabTransfers";
import { InventoryTopDock } from "./InventoryTopDock";
import "./inventory.css";
import {
  parseLiveStockAlertSummary,
  parseLiveStockPage,
  type WarehouseProduct,
} from "./liveStock/contracts";

import { useAuthFetch } from "@/hooks/useAuthFetch"; // +++ استدعاء الدستور الموحد +++

// ─── Tab config ───────────────────────────────────────────────────────────────
const TABS = [
  { id: "live", labelKey: "inventoryShell.tabs.live", icon: Package },
  { id: "inbound", labelKey: "inventoryShell.tabs.inbound", icon: FilePlus },
  { id: "transfers", labelKey: "inventoryShell.tabs.transfers", icon: ArrowRightLeft },
  { id: "ledger", labelKey: "inventoryShell.tabs.ledger", icon: History },
  { id: "stocktake", labelKey: "inventoryShell.tabs.stocktake", icon: Lock },
  { id: "warehouses", labelKey: "inventoryShell.tabs.warehouses", icon: Building2 },
  { id: "permissions", labelKey: "inventoryShell.tabs.permissions", icon: Lock },
] as const;

type TabId = typeof TABS[number]["id"];
const TAB_PERMISSION: Record<TabId, string> = {
  live: 'inventory.read', inbound: 'inbound.create', transfers: 'transfer.read',
  ledger: 'ledger.read', stocktake: 'stocktake.read', warehouses: 'location.read', permissions: '',
};

interface WarehouseLocationOption {
  id: number;
  name: string;
  code: string;
}

interface WarehouseStatusPayload {
  status: string;
}

interface WarehouseSetupStatus {
  warehouse_ready: boolean;
  active_warehouse_count: number;
  accessible_warehouse_count: number;
  can_create: boolean;
}

interface WarehouseLocationPage {
  items: WarehouseLocationOption[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

const parseWarehouseLocationPage = (value: unknown): WarehouseLocationPage => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("تنسيق صفحة المستودعات غير صالح.");
  }
  const page = value as Record<string, unknown>;
  if (!Array.isArray(page.items) || page.items.length > 200) {
    throw new Error("قائمة المستودعات غير صالحة.");
  }
  const items = page.items.map((item) => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) {
      throw new Error("عنصر مستودع غير صالح.");
    }
    const row = item as Record<string, unknown>;
    if (
      typeof row.id !== "number" || !Number.isSafeInteger(row.id) || row.id <= 0 ||
      typeof row.name !== "string" || !row.name.trim() ||
      typeof row.code !== "string" || !row.code.trim()
    ) {
      throw new Error("بيانات مستودع غير مكتملة.");
    }
    return { id: row.id, name: row.name, code: row.code };
  });
  const nextCursor = typeof page.next_cursor === "string" ? page.next_cursor : null;
  if (typeof page.has_more !== "boolean" || page.has_more !== (nextCursor !== null)) {
    throw new Error("ترقيم صفحة المستودعات غير متسق.");
  }
  const total = page.total === null
    ? null
    : typeof page.total === "number" && Number.isSafeInteger(page.total) && page.total >= 0
      ? page.total
      : (() => { throw new Error("إجمالي المستودعات غير صالح."); })();
  return { items, next_cursor: nextCursor, has_more: page.has_more, total };
};

const parseWarehouseSetupStatus = (value: unknown): WarehouseSetupStatus => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("حالة إعداد المستودعات غير صالحة.");
  }
  const row = value as Record<string, unknown>;
  if (
    typeof row.warehouse_ready !== "boolean" ||
    typeof row.can_create !== "boolean" ||
    typeof row.active_warehouse_count !== "number" ||
    !Number.isSafeInteger(row.active_warehouse_count) || row.active_warehouse_count < 0 ||
    typeof row.accessible_warehouse_count !== "number" ||
    !Number.isSafeInteger(row.accessible_warehouse_count) || row.accessible_warehouse_count < 0 ||
    row.accessible_warehouse_count > row.active_warehouse_count ||
    row.warehouse_ready !== (row.active_warehouse_count > 0)
  ) {
    throw new Error("حالة إعداد المستودعات غير متسقة.");
  }
  return {
    warehouse_ready: row.warehouse_ready,
    active_warehouse_count: row.active_warehouse_count,
    accessible_warehouse_count: row.accessible_warehouse_count,
    can_create: row.can_create,
  };
};

const isTabId = (value: string | null): value is TabId =>
  TABS.some((tab) => tab.id === value);

const getErrorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "حدث خطأ غير متوقع";

// ─── Main Component ───────────────────────────────────────────────────────────
export default function MainInventory() {
  const authFetch = useAuthFetch();
  const { t, i18n } = useTranslation();

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
  const selectedLocationIdRef = useRef<number | null>(null);
  useEffect(() => { selectedLocationIdRef.current = selectedLocationId; }, [selectedLocationId]);
  const access = useInventoryAccess();
  const locationAccess = useInventoryAccess(selectedLocationId);
  const canReadStock = locationAccess.can('inventory.read');
  const canReadStatus = locationAccess.can('location.read');
  const { isCompanyAdmin, canAny } = access;
  const { can: canAtLocation } = locationAccess;
  const tabAllowed = useCallback((id: TabId) => {
    if (id === 'permissions') return isCompanyAdmin;
    if (id === 'warehouses' || selectedLocationId === null) return canAny(TAB_PERMISSION[id]);
    if (id === 'inbound') return canAtLocation('inbound.create') && canAtLocation('catalog.read');
    return canAtLocation(TAB_PERMISSION[id]);
  }, [isCompanyAdmin, canAny, canAtLocation, selectedLocationId]);
  useEffect(() => {
    if (
      !access.isSuccess ||
      (selectedLocationId !== null && !locationAccess.isSuccess)
    ) {
      return;
    }

    if (!tabAllowed(activeTab)) {
      const first = TABS.find((tab) => tabAllowed(tab.id));
      if (first) setActiveTab(first.id);
    }
  }, [access.isSuccess,locationAccess.isSuccess,selectedLocationId,activeTab,tabAllowed,]);
  const [locationError, setLocationError] = useState(false);
  const [loadingLocations, setLoadingLocations] = useState(true);
  const [warehouseSetup, setWarehouseSetup] = useState<WarehouseSetupStatus | null>(null);
  const [locationsTruncated, setLocationsTruncated] = useState(false);
  
  const [stockItems, setStockItems] = useState<WarehouseProduct[]>([]);
  const [stockTotal, setStockTotal] = useState<number | null>(null);
  const [stockMatchingTotal, setStockMatchingTotal] = useState<number | null>(null);
  const [stockAlertCount, setStockAlertCount] = useState<number | null>(null);
  const [stockCursor, setStockCursor] = useState<string | null>(null);
  const [stockCursorHistory, setStockCursorHistory] = useState<Array<string | null>>([]);
  const [stockNextCursor, setStockNextCursor] = useState<string | null>(null);
  const [stockSearch, setStockSearch] = useState("");
  const [stockOnlyAlerts, setStockOnlyAlerts] = useState(false);
  const [stockRefreshKey, setStockRefreshKey] = useState(0);
  const stockRequestSeq = useRef(0);
  const stockAbortRef = useRef<AbortController | null>(null);
  const stockAlertRequestSeq = useRef(0);
  const stockAlertAbortRef = useRef<AbortController | null>(null);
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
      const [locationsRaw, setupRaw] = await Promise.all([
        authFetch("/warehouse/locations?include_inactive=false&limit=200"),
        authFetch("/warehouse/setup-status"),
      ]);
      if (requestSeq !== locationRequestSeq.current) return;

      const page = parseWarehouseLocationPage(locationsRaw);
      const setup = parseWarehouseSetupStatus(setupRaw);
      if (page.items.length !== setup.accessible_warehouse_count && !page.has_more) {
        throw new Error("عدد المستودعات المتاحة لا يطابق حالة الإعداد.");
      }

      setLocations(page.items);
      setWarehouseSetup(setup);
      setLocationsTruncated(page.has_more);

      const savedRaw = localStorage.getItem(selectedLocationStorageKey);
      const savedId = savedRaw ? Number(savedRaw) : null;
      const currentId = selectedLocationIdRef.current;
      const savedIsValid =
        savedId !== null &&
        Number.isInteger(savedId) &&
        page.items.some((location) => location.id === savedId);
      const currentIsValid =
        currentId !== null &&
        page.items.some((location) => location.id === currentId);

      if (savedIsValid) {
        setSelectedLocationId(savedId);
      } else if (currentIsValid) {
        localStorage.setItem(selectedLocationStorageKey, String(currentId));
      } else if (page.items.length === 1) {
        const onlyLocationId = page.items[0].id;

        setSelectedLocationId(onlyLocationId);
        localStorage.setItem(
          selectedLocationStorageKey,
          String(onlyLocationId),
        );
      } else {
        if (savedRaw !== null) localStorage.removeItem(selectedLocationStorageKey);
        setSelectedLocationId(null);
      }
    } catch (error: unknown) {
      if (requestSeq !== locationRequestSeq.current) return;

      setLocations([]);
      setWarehouseSetup(null);
      setLocationsTruncated(false);
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
    if (!access.isSuccess) return;

    if (!canAny('location.read')) {
      locationRequestSeq.current += 1;
      setLocations([]);
      setWarehouseSetup(null);
      setLocationsTruncated(false);
      setSelectedLocationId(null);
      setLocationError(false);
      setLoadingLocations(false);
      return;
    }

    void fetchLocations();
  }, [access.isSuccess, canAny, fetchLocations]);

  const handleLocationChange = useCallback(
    (value: string) => {
      const nextId = Number(value);

      if (
        !Number.isInteger(nextId) ||
        !locations.some((location) => location.id === nextId)
      ) {
        return;
      }

      setSelectedLocationId(nextId);
      localStorage.setItem(selectedLocationStorageKey, String(nextId));
    },
    [locations, selectedLocationStorageKey]
  );

  // ── fetchers ────────────────────────────────────────────────────────────────
  const fetchStock = useCallback(async () => {
    if (selectedLocationId === null || !canReadStock) return;

    const requestSeq = ++stockRequestSeq.current;
    stockAbortRef.current?.abort();
    const requestController = new AbortController();
    stockAbortRef.current = requestController;
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
        `/warehouse/inventory/cursor?${params.toString()}`,
        { signal: requestController.signal }
      );

      if (requestSeq !== stockRequestSeq.current) return;
      const data = parseLiveStockPage(raw);
      setStockItems(data.items);
      setStockNextCursor(data.next_cursor);

      if (typeof data.total === "number") {
        setStockMatchingTotal(data.total);

        if (!stockSearch && !stockOnlyAlerts && stockCursor === null) {
          setStockTotal(data.total);
        }
      }

      setLastSync(new Date());
    } catch (error: unknown) {
      if (requestSeq !== stockRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryLive.errors.loadFailed"),
        ),
      );
      setStockItems([]);
      setStockNextCursor(null);
      setStockMatchingTotal(null);
    } finally {
      if (stockAbortRef.current === requestController) {
        stockAbortRef.current = null;
      }
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
    canReadStock,
    t,
  ]);

  const fetchStockAlerts = useCallback(async () => {
    if (selectedLocationId === null || !canReadStock) {
      setStockAlertCount(null);
      return;
    }

    const requestSeq = ++stockAlertRequestSeq.current;
    stockAlertAbortRef.current?.abort();
    const requestController = new AbortController();
    stockAlertAbortRef.current = requestController;

    try {
      const raw = await authFetch(
        `/warehouse/inventory/alerts/summary?location_id=${encodeURIComponent(
          String(selectedLocationId),
        )}`,
        { signal: requestController.signal },
      );

      if (requestSeq !== stockAlertRequestSeq.current) return;
      const data = parseLiveStockAlertSummary(raw);
      setStockAlertCount(data.alert_count);
    } catch (error: unknown) {
      if (requestSeq !== stockAlertRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      setStockAlertCount(null);
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryLive.errors.loadFailed"),
        ),
      );
    } finally {
      if (stockAlertAbortRef.current === requestController) {
        stockAlertAbortRef.current = null;
      }
    }
  }, [
    authFetch,
    selectedLocationId,
    canReadStock,
    t,
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

    if (selectedLocationId === null || !canReadStatus) {
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
  }, [authFetch, selectedLocationId, canReadStatus]);

  // ── on mount ────────────────────────────────────────────────────────────────
  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    stockRequestSeq.current += 1;
    stockAbortRef.current?.abort();
    stockAbortRef.current = null;
    setStockItems([]);
    setStockTotal(null);
    setStockMatchingTotal(null);
    setStockAlertCount(null);
    stockAlertRequestSeq.current += 1;
    stockAlertAbortRef.current?.abort();
    stockAlertAbortRef.current = null;
    setStockSearch("");
    setStockOnlyAlerts(false);
    setStockCursor(null);
    setStockCursorHistory([]);
    setStockNextCursor(null);
    setLastSync(null);

    return () => {
      stockRequestSeq.current += 1;
      stockAbortRef.current?.abort();
      stockAbortRef.current = null;
      stockAlertRequestSeq.current += 1;
      stockAlertAbortRef.current?.abort();
      stockAlertAbortRef.current = null;
    };
  }, [selectedLocationId, canReadStock]);

  useEffect(() => {
    if (selectedLocationId !== null) {
      void fetchStock();
    }
  }, [selectedLocationId, fetchStock, stockRefreshKey]);

  useEffect(() => {
    if (selectedLocationId !== null) {
      void fetchStockAlerts();
    }
  }, [selectedLocationId, fetchStockAlerts, stockRefreshKey]);

  useEffect(() => {
    if (
      !loadingLocations &&
      !locationError &&
      locations.length === 0 &&
      warehouseSetup?.warehouse_ready === false &&
      warehouseSetup.can_create &&
      activeTab !== "warehouses"
    ) {
      setActiveTab("warehouses");
    }
  }, [activeTab, loadingLocations, locationError, locations.length, warehouseSetup]);

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
    <div data-live-view={activeTab === "live"} className="inventory-workspace flex flex-col gap-4 w-full h-full flex-1 min-h-0 animate-in fade-in duration-200">

      <InventoryTopDock
        items={TABS.filter((tab) => tabAllowed(tab.id)).map(
          ({ id, labelKey, icon }) => ({
            id,
            label: t(labelKey),
            icon,
          }),
        )}
        activeId={activeTab}
        ariaLabel={t("inventoryShell.tabsLabel")}
        onChange={(id) => {
          if (isTabId(id)) {
            setActiveTab(id);
          }
        }}
      />

      {activeTab !== "live" && (
        <div className="inventory-shared-context-row">
          <div className="inventory-context-bar flex flex-wrap items-center gap-3 px-3 py-2">
            {locations.length > 0 && (
              <label className="inventory-location-field">
                <span className="inventory-location-label">
                  {t("inventoryShell.warehouseSelectLabel")}
                </span>
                <select
                  aria-label={t("inventoryShell.warehouseSelectLabel")}
                  className="inventory-location-select px-3 py-2 text-sm font-bold"
                  value={selectedLocationId ?? ""}
                  onChange={(e) => handleLocationChange(e.target.value)}
                >
                  <option value="" disabled>
                    {t("inventoryShell.chooseWarehouse")}
                  </option>
                  {locations.map((loc) => (
                    <option key={loc.id} value={loc.id}>
                      {loc.name}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <div className="inventory-sync flex min-w-fit flex-col items-start justify-center border-e pe-3">
              <div className="flex items-center gap-2">
                <span className="text-sm font-black">
                  {t("inventoryShell.liveStockCount")}{" "}
                  <span className="inventory-shared-context-count">
                    {stockTotal === null
                      ? "—"
                      : new Intl.NumberFormat(
                          i18n.resolvedLanguage ||
                            i18n.language,
                          { numberingSystem: "latn" },
                        ).format(stockTotal)}
                  </span>
                </span>
                {isAuditLocked && (
                  <span className="inventory-shared-lock-chip">
                    {t("inventoryShell.locked")}
                  </span>
                )}
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 text-xs font-bold">
                <span>
                  {t("inventoryShell.lastUpdated")}:{" "}
                  {lastSync
                    ? new Intl.DateTimeFormat(
                        i18n.resolvedLanguage ||
                          i18n.language ||
                          "en",
                        {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                          hour12: false,
                          numberingSystem: "latn",
                        },
                      ).format(lastSync)
                    : "—"}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    refreshStock();
                    void fetchStatus();
                  }}
                  disabled={loadingStock}
                  className="inventory-shared-refresh"
                  title={t("inventoryShell.refreshNow")}
                  aria-label={t("inventoryShell.refreshNow")}
                >
                  <RefreshCcw
                    className={`h-3.5 w-3.5 ${
                      loadingStock ? "animate-spin" : ""
                    }`}
                  />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {locationsTruncated && <p role="status" className="inventory-alert-banner flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm font-bold">يعرض محدد التشغيل أول 200 مستودع متاح. استخدم إدارة المستودعات للبحث عن موقع آخر.</p>}
      {locationAccess.isError && selectedLocationId !== null && <p role="alert" className="inventory-alert-banner flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm font-bold">الموقع غير متاح أو تغيرت صلاحياتك. <button type="button" className="rounded-lg bg-orange-100 px-3 py-1.5 text-orange-800" onClick={() => { void fetchLocations(); void locationAccess.refetch(); }}>تحديث المواقع والصلاحيات</button></p>}
      {/* ═══ Tab Content ═══ */}
      <div className="inventory-content flex-1 min-h-0 flex flex-col">
        {selectedLocationId !== null && locationAccess.isPending && (
          <div className="inventory-empty-state flex flex-1 items-center justify-center gap-2 px-6 text-center font-bold text-slate-500">
            <RefreshCcw className="h-5 w-5 animate-spin" />
            {t("common.loading")}
          </div>
        )}
        {selectedLocationId === null && activeTab !== "warehouses" && activeTab !== "permissions" && (
          <div className="inventory-empty-state flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center font-bold">
            <p>
              {warehouseSetup?.warehouse_ready === false
                ? "لم تُنشئ الشركة مستودعاً فعالاً بعد. أنشئ المستودع من شاشة إدارة المستودعات أولاً."
                : warehouseSetup?.accessible_warehouse_count === 0
                  ? "توجد مستودعات فعالة للشركة، لكن حسابك لا يملك وصولاً إلى أي منها."
                  : "لا يوجد مستودع محدد لهذه العملية. اختر مستودعاً فعالاً."}
            </p>
            {locations.length > 0 && (
              <select aria-label={t("inventoryShell.warehouseSelectLabel")} className="inventory-location-select px-3 py-2 text-sm font-bold" value="" onChange={(e) => handleLocationChange(e.target.value)}>
                <option value="" disabled>{t("inventoryShell.chooseWarehouse")}</option>
                {locations.map((loc) => <option key={loc.id} value={loc.id}>{loc.name}</option>)}
              </select>
            )}
            {warehouseSetup?.warehouse_ready === false && warehouseSetup.can_create && tabAllowed("warehouses") && (
              <button type="button" onClick={() => setActiveTab("warehouses")} className="rounded-xl bg-blue-600 px-4 py-2 text-white">
                فتح إدارة المستودعات
              </button>
            )}
          </div>
        )}

        {!locationAccess.isPending && activeTab === "live" && tabAllowed("live") && selectedLocationId !== null && (
          <Tab1LiveStock
            locationId={selectedLocationId}
            locations={locations}
            stockTotal={stockTotal}
            lastSync={lastSync}
            isAuditLocked={isAuditLocked}
            products={stockItems}
            loading={loadingStock}
            onLocationChange={handleLocationChange}
            onRefresh={() => {
              refreshStock();
              void fetchStatus();
            }}
            alertCount={stockAlertCount}
            matchingTotal={stockMatchingTotal}
            pageNumber={stockCursorHistory.length + 1}
            hasMore={!!stockNextCursor}
            hasPrevious={stockCursorHistory.length > 0}
            onlyAlerts={stockOnlyAlerts}
            onSearchChange={handleStockSearchChange}
            onOnlyAlertsChange={handleStockAlertsChange}
            onNext={handleStockNext}
            onPrevious={handleStockPrevious}
          />
        )}
        {!locationAccess.isPending && activeTab === "inbound" && tabAllowed("inbound") && selectedLocationId !== null && locationAccess.data && (
          <Tab2Inbound
            key={`${locationAccess.data.company_id}:${locationAccess.data.driver_id}:${selectedLocationId}`}
            companyId={locationAccess.data.company_id}
            actorId={locationAccess.data.driver_id}
            locationId={selectedLocationId} // +++ تمرير الموقع لعملية الإدخال +++
            isAuditLocked={isAuditLocked}
            authenticatedFetch={authFetch}
            onSuccess={async () => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
            }}
          />
        )}
        {!locationAccess.isPending && activeTab === "stocktake" && tabAllowed("stocktake") && selectedLocationId !== null && locationAccess.data && (
          <Tab3Stocktake
            key={`${locationAccess.data.company_id}:${locationAccess.data.driver_id}:${selectedLocationId}`}
            locationId={selectedLocationId} // +++ سحق ملاحظة P1: تمرير الموقع للمحرك המوحد +++
            companyId={`${locationAccess.data.company_id}:${locationAccess.data.driver_id}`}
            isAuditLocked={isAuditLocked}
            authenticatedFetch={authFetch}
            onStocktakeChanged={async () => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
              await fetchStatus();
            }}
          />
        )}
        {!locationAccess.isPending && activeTab === "ledger" && tabAllowed("ledger") && selectedLocationId !== null && (
          <Tab4Ledger
            key={selectedLocationId}
            locationId={selectedLocationId}
            refreshKey={ledgerRefreshKey}
            onInventoryChanged={() => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
            }}
          />
        )}

        {!locationAccess.isPending && activeTab === "transfers" && tabAllowed("transfers") && selectedLocationId !== null && (
          <TabTransfers
            locationId={selectedLocationId}
            onInventoryChanged={async () => {
              setStockRefreshKey((value) => value + 1);
              setLedgerRefreshKey((value) => value + 1);
              await fetchStatus();
            }}
          />
        )}

        {activeTab === "permissions" && access.isCompanyAdmin && <TabInventoryAccess />}
        {activeTab === "warehouses" && tabAllowed("warehouses") && (
          <TabWarehouseLocations
            onLocationsChanged={fetchLocations}
          />
        )}
      </div>
    </div>
  );
}
