import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { TabInventoryAccess } from "./TabInventoryAccess";
import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Package, History, Lock, RefreshCcw, FilePlus, Building2, ArrowRightLeft, Layers3 } from "lucide-react";
import { toast } from "sonner";
import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import { Tab1LiveStock } from "./Tab1LiveStock";
import { TabBatches } from "./TabBatches";
import { Tab2Inbound } from "./Tab2Inbound";
import { Tab3Stocktake } from "./Tab3Stocktake";
import { Tab4Ledger } from "./Tab4Ledger";
import { TabWarehouseLocations } from "./TabWarehouseLocations";
import { TabTransfers } from "./TabTransfers";
import { InventoryTopDock } from "./InventoryTopDock";
import "./inventory.css";
import {
  parseLiveStockSummary,
  parseLiveStockPage,
  type LiveStockIndicator,
  type LiveStockStockState,
  type WarehouseProduct,
} from "./liveStock/contracts";
import {
  clearInventoryWarmScope,
  dropLiveStockWarmSnapshot,
  inventoryWarmScopeKey,
  patchLiveStockWarmSnapshot,
  readInventoryShellWarmSnapshot,
  readLiveStockWarmSnapshot,
  writeInventoryShellWarmSnapshot,
} from "./inventorySessionCache";

import { useAuthFetch } from "@/hooks/useAuthFetch"; // +++ استدعاء الدستور الموحد +++

// ─── Tab config ───────────────────────────────────────────────────────────────
const TABS = [
  { id: "live", labelKey: "inventoryShell.tabs.live", icon: Package },
  { id: "batches", labelKey: "inventoryShell.tabs.batches", icon: Layers3 },
  { id: "inbound", labelKey: "inventoryShell.tabs.inbound", icon: FilePlus },
  { id: "transfers", labelKey: "inventoryShell.tabs.transfers", icon: ArrowRightLeft },
  { id: "ledger", labelKey: "inventoryShell.tabs.ledger", icon: History },
  { id: "stocktake", labelKey: "inventoryShell.tabs.stocktake", icon: Lock },
  { id: "warehouses", labelKey: "inventoryShell.tabs.warehouses", icon: Building2 },
  { id: "permissions", labelKey: "inventoryShell.tabs.permissions", icon: Lock },
] as const;

const LIVE_STOCK_PAGE_SIZE = 50;

type TabId = typeof TABS[number]["id"];
const TAB_PERMISSION: Record<TabId, string> = {
  live: 'inventory.read', batches: 'inventory.read', inbound: 'inbound.create', transfers: 'transfer.read',
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

type InventoryContractError = Error & { code: string };

const inventoryContractError = (code: string): never => {
  const error = new Error(code) as InventoryContractError;
  error.code = code;
  throw error;
};

const parseWarehouseLocationPage = (value: unknown): WarehouseLocationPage => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    inventoryContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  }
  const page = value as Record<string, unknown>;
  const rawItems: unknown[] =
    Array.isArray(page.items)
      ? page.items
      : inventoryContractError(
          "WAREHOUSE_LOCATION_RESPONSE_INVALID"
        );
  if (rawItems.length > 200) {
    inventoryContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  }

  const items: WarehouseLocationOption[] = rawItems.map((item) => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) {
      inventoryContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
    }
    const row = item as Record<string, unknown>;
    const id = row.id;
    const name = row.name;
    const code = row.code;
    if (
      typeof id !== "number" ||
      !Number.isSafeInteger(id) ||
      id <= 0 ||
      typeof name !== "string" ||
      !name.trim() ||
      typeof code !== "string" ||
      !code.trim()
    ) {
      inventoryContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
    }
    return {
      id: id as number,
      name: name as string,
      code: code as string,
    };
  });

  const nextCursor =
    typeof page.next_cursor === "string"
      ? page.next_cursor
      : page.next_cursor === null
        ? null
        : inventoryContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  const hasMore = page.has_more;
  if (
    typeof hasMore !== "boolean" ||
    hasMore !== (nextCursor !== null)
  ) {
    inventoryContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");
  }
  const total = page.total === null
    ? null
    : typeof page.total === "number" &&
        Number.isSafeInteger(page.total) &&
        page.total >= 0
      ? page.total
      : inventoryContractError("WAREHOUSE_LOCATION_RESPONSE_INVALID");

  return {
    items,
    next_cursor: nextCursor,
    has_more: hasMore as boolean,
    total,
  };
};

const parseWarehouseSetupStatus = (value: unknown): WarehouseSetupStatus => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    inventoryContractError("WAREHOUSE_SETUP_RESPONSE_INVALID");
  }
  const row = value as Record<string, unknown>;
  const warehouseReady = row.warehouse_ready;
  const activeWarehouseCount = row.active_warehouse_count;
  const accessibleWarehouseCount = row.accessible_warehouse_count;
  const canCreate = row.can_create;

  if (
    typeof warehouseReady !== "boolean" ||
    typeof canCreate !== "boolean" ||
    typeof activeWarehouseCount !== "number" ||
    !Number.isSafeInteger(activeWarehouseCount) ||
    activeWarehouseCount < 0 ||
    typeof accessibleWarehouseCount !== "number" ||
    !Number.isSafeInteger(accessibleWarehouseCount) ||
    accessibleWarehouseCount < 0 ||
    accessibleWarehouseCount > activeWarehouseCount ||
    warehouseReady !== (activeWarehouseCount > 0)
  ) {
    inventoryContractError("WAREHOUSE_SETUP_RESPONSE_INVALID");
  }

  return {
    warehouse_ready: warehouseReady as boolean,
    active_warehouse_count: activeWarehouseCount as number,
    accessible_warehouse_count: accessibleWarehouseCount as number,
    can_create: canCreate as boolean,
  };
};

const isTabId = (value: string | null): value is TabId =>
  TABS.some((tab) => tab.id === value);


// ─── Main Component ───────────────────────────────────────────────────────────
export default function MainInventory() {
  const authFetch = useAuthFetch();
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);

  // UI preference only. Server token + RLS remain the security authority.
  const companyId = localStorage.getItem("company_id") || "";
  const activeTabStorageKey = companyId
    ? `inventory_active_tab:${companyId}`
    : "inventory_active_tab:anonymous";
  const selectedLocationStorageKey = companyId
    ? `inventory_selected_location:${companyId}`
    : "inventory_selected_location:anonymous";

  const driverId = localStorage.getItem("driver_id") || "";
  const warmScopeKey = inventoryWarmScopeKey(companyId, driverId);
  const [initialWarmShell] = useState(() =>
    readInventoryShellWarmSnapshot(warmScopeKey),
  );
  const [initialSelectedLocationId] = useState<number | null>(() => {
    const cachedLocations = initialWarmShell?.locations ?? [];
    const savedRaw = localStorage.getItem(selectedLocationStorageKey);
    const savedId = savedRaw ? Number(savedRaw) : null;
    if (
      savedId !== null &&
      Number.isSafeInteger(savedId) &&
      cachedLocations.some((location) => location.id === savedId)
    ) {
      return savedId;
    }

    const cachedId = initialWarmShell?.selectedLocationId ?? null;
    if (
      cachedId !== null &&
      cachedLocations.some((location) => location.id === cachedId)
    ) {
      return cachedId;
    }

    return cachedLocations[0]?.id ?? null;
  });
  const [initialLiveSnapshot] = useState(() =>
    readLiveStockWarmSnapshot(
      warmScopeKey,
      initialSelectedLocationId,
    ),
  );

  const [activeTab, setActiveTab] = useState<TabId>(() => {
    const saved = localStorage.getItem(activeTabStorageKey);
    return isTabId(saved) ? saved : "live";
  });

  useEffect(() => {
    localStorage.removeItem("inventory_active_tab");
    localStorage.setItem(activeTabStorageKey, activeTab);
  }, [activeTab, activeTabStorageKey]);
  
  // +++ حالة اختيار المستودع +++
  const [locations, setLocations] = useState<WarehouseLocationOption[]>(
    initialWarmShell?.locations ?? [],
  );
  const [selectedLocationId, setSelectedLocationId] =
    useState<number | null>(initialSelectedLocationId);
  const selectedLocationIdRef =
    useRef<number | null>(initialSelectedLocationId);
  useEffect(() => {
    selectedLocationIdRef.current = selectedLocationId;
  }, [selectedLocationId]);
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
  useEffect(() => {
    if (
      !locationAccess.isError ||
      selectedLocationId === null
    ) {
      return;
    }
    const error = locationAccess.error as
      | { status?: unknown }
      | null;
    if (error?.status === 403) {
      dropLiveStockWarmSnapshot(
        warmScopeKey,
        selectedLocationId,
      );
    }
  }, [
    locationAccess.error,
    locationAccess.isError,
    selectedLocationId,
    warmScopeKey,
  ]);

  const [locationError, setLocationError] = useState(false);
  const [loadingLocations, setLoadingLocations] = useState(
    initialWarmShell === null,
  );
  const [warehouseSetup, setWarehouseSetup] =
    useState<WarehouseSetupStatus | null>(
      initialWarmShell?.setup ?? null,
    );
  const [locationsTruncated, setLocationsTruncated] = useState(
    initialWarmShell?.locationsTruncated ?? false,
  );
  const warehouseSetupRef = useRef<WarehouseSetupStatus | null>(
    initialWarmShell?.setup ?? null,
  );
  useEffect(() => {
    warehouseSetupRef.current = warehouseSetup;
  }, [warehouseSetup]);
  
  const [stockItems, setStockItems] = useState<WarehouseProduct[]>(
    initialLiveSnapshot?.hasPage
      ? initialLiveSnapshot.items
      : [],
  );
  const stockItemsRef = useRef<WarehouseProduct[]>(stockItems);
  const [stockPageReady, setStockPageReady] = useState(
    initialLiveSnapshot?.hasPage === true,
  );
  useEffect(() => {
    stockItemsRef.current = stockItems;
  }, [stockItems]);
  const [stockTotal, setStockTotal] = useState<number | null>(
    initialLiveSnapshot?.hasSummary
      ? initialLiveSnapshot.stockTotal
      : null,
  );
  const [stockMatchingTotal, setStockMatchingTotal] =
    useState<number | null>(
      initialLiveSnapshot?.hasPage
        ? initialLiveSnapshot.matchingTotal
        : null,
    );
  const [stockAlertCount, setStockAlertCount] =
    useState<number | null>(
      initialLiveSnapshot?.hasSummary
        ? initialLiveSnapshot.alertCount
        : null,
    );
  const [stockCursor, setStockCursor] = useState<string | null>(null);
  const [stockNextCursor, setStockNextCursor] =
    useState<string | null>(
      initialLiveSnapshot?.hasPage
        ? initialLiveSnapshot.nextCursor
        : null,
    );
  const [stockSearch, setStockSearch] = useState("");
  const [stockState, setStockState] =
    useState<LiveStockStockState>("all");
  const [stockIndicators, setStockIndicators] =
    useState<LiveStockIndicator[]>([]);
  const [stockFamilyId, setStockFamilyId] =
    useState<number | null>(null);
  const [stockRefreshKey, setStockRefreshKey] = useState(0);
  const [stockPageError, setStockPageError] = useState<string | null>(null);
  const [stockSummaryError, setStockSummaryError] = useState<string | null>(null);
  const stockRequestSeq = useRef(0);
  const stockAbortRef = useRef<AbortController | null>(null);
  const stockSummaryRequestSeq = useRef(0);
  const stockSummaryAbortRef = useRef<AbortController | null>(null);
  const locationRequestSeq = useRef(0);
  const statusRequestSeq = useRef(0);

  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [auditLockState, setAuditLockState] = useState<boolean | null>(
    initialLiveSnapshot?.hasStatus
      ? initialLiveSnapshot.auditLocked
      : null,
  );
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [verifiedStatusLocationId, setVerifiedStatusLocationId] =
    useState<number | null>(null);
  const [loadingStock, setLoadingStock] = useState(
    initialSelectedLocationId !== null &&
      initialLiveSnapshot?.hasPage !== true,
  );
  const [lastSync, setLastSync] = useState<Date | null>(
    initialLiveSnapshot?.lastSyncMs
      ? new Date(initialLiveSnapshot.lastSyncMs)
      : null,
  );

  const displayAuditLocked =
    canReadStatus && auditLockState === true;
  // Warm status is visual only. Mutation safety requires a fresh status
  // response for the currently selected warehouse before treating it
  // as unlocked.
  const effectiveAuditLocked =
    canReadStatus
      ? verifiedStatusLocationId !== selectedLocationId ||
        auditLockState !== false
      : false;

  const hydrateDefaultLiveStock = useCallback(
    (locationId: number | null) => {
      const snapshot = readLiveStockWarmSnapshot(
        warmScopeKey,
        locationId,
      );

      if (snapshot?.hasPage) {
        stockItemsRef.current = snapshot.items;
        setStockItems(snapshot.items);
        setStockPageReady(true);
        setStockMatchingTotal(snapshot.matchingTotal);
        setStockNextCursor(snapshot.nextCursor);
        setLastSync(
          snapshot.lastSyncMs
            ? new Date(snapshot.lastSyncMs)
            : null,
        );
      } else {
        stockItemsRef.current = [];
        setStockItems([]);
        setStockPageReady(false);
        setStockMatchingTotal(null);
        setStockNextCursor(null);
        setLastSync(null);
      }

      if (snapshot?.hasSummary) {
        setStockTotal(snapshot.stockTotal);
        setStockAlertCount(snapshot.alertCount);
      } else {
        setStockTotal(null);
        setStockAlertCount(null);
      }

      setAuditLockState(
        snapshot?.hasStatus
          ? snapshot.auditLocked
          : null,
      );
      setLoadingStock(
        locationId !== null && snapshot?.hasPage !== true,
      );
    },
    [warmScopeKey],
  );

  const prepareLocationChange = useCallback(
    (locationId: number | null) => {
      statusRequestSeq.current += 1;
      setVerifiedStatusLocationId(null);
      stockRequestSeq.current += 1;
      stockAbortRef.current?.abort();
      stockAbortRef.current = null;
      stockSummaryRequestSeq.current += 1;
      stockSummaryAbortRef.current?.abort();
      stockSummaryAbortRef.current = null;

      setStockSearch("");
      setStockState("all");
      setStockIndicators([]);
      setStockFamilyId(null);
      setStockCursor(null);
      setStockPageError(null);
      setStockSummaryError(null);
      hydrateDefaultLiveStock(locationId);
    },
    [hydrateDefaultLiveStock],
  );

  useEffect(() => {
    if (!warmScopeKey || warehouseSetup === null) return;
    writeInventoryShellWarmSnapshot(warmScopeKey, {
      locations,
      setup: warehouseSetup,
      locationsTruncated,
      selectedLocationId,
    });
  }, [
    locations,
    locationsTruncated,
    selectedLocationId,
    warehouseSetup,
    warmScopeKey,
  ]);

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
        inventoryContractError("WAREHOUSE_SETUP_RESPONSE_INVALID");
      }

      setLocations(page.items);
      setWarehouseSetup(setup);
      setLocationsTruncated(page.has_more);

      const savedRaw = localStorage.getItem(selectedLocationStorageKey);
      const savedId = savedRaw ? Number(savedRaw) : null;
      const currentId = selectedLocationIdRef.current;
      const savedIsValid =
        savedId !== null &&
        Number.isSafeInteger(savedId) &&
        page.items.some((location) => location.id === savedId);
      const currentIsValid =
        currentId !== null &&
        page.items.some((location) => location.id === currentId);

      const nextLocationId = savedIsValid
        ? savedId
        : currentIsValid
          ? currentId
          : page.items[0]?.id ?? null;

      if (nextLocationId !== currentId) {
        prepareLocationChange(nextLocationId);
        selectedLocationIdRef.current = nextLocationId;
        setSelectedLocationId(nextLocationId);
      }

      if (nextLocationId !== null) {
        localStorage.setItem(
          selectedLocationStorageKey,
          String(nextLocationId),
        );
      } else if (savedRaw !== null) {
        localStorage.removeItem(selectedLocationStorageKey);
      }
    } catch (error: unknown) {
      if (requestSeq !== locationRequestSeq.current) return;

      if (warehouseSetupRef.current === null) {
        setLocations([]);
        setWarehouseSetup(null);
        setLocationsTruncated(false);
        prepareLocationChange(null);
        selectedLocationIdRef.current = null;
        setSelectedLocationId(null);
        setLocationError(true);
      } else {
        // Background revalidation must not destroy a valid warm view.
        setLocationError(false);
      }
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryShell.errors.locationsLoadFailed"),
        ),
      );
    } finally {
      if (requestSeq === locationRequestSeq.current) {
        setLoadingLocations(false);
      }
    }
  }, [authFetch, prepareLocationChange, selectedLocationStorageKey, t]);

  useEffect(() => {
    if (!access.isSuccess) return;

    if (!canAny('location.read')) {
      locationRequestSeq.current += 1;
      clearInventoryWarmScope(warmScopeKey);
      setLocations([]);
      setWarehouseSetup(null);
      setLocationsTruncated(false);
      prepareLocationChange(null);
      selectedLocationIdRef.current = null;
      setSelectedLocationId(null);
      setLocationError(false);
      setLoadingLocations(false);
      return;
    }

    void fetchLocations();
  }, [
    access.isSuccess,
    canAny,
    fetchLocations,
    prepareLocationChange,
    warmScopeKey,
  ]);

  const handleLocationChange = useCallback(
    (value: string) => {
      const nextId = Number(value);

      if (
        !Number.isInteger(nextId) ||
        !locations.some((location) => location.id === nextId)
      ) {
        return;
      }

      prepareLocationChange(nextId);
      selectedLocationIdRef.current = nextId;
      setSelectedLocationId(nextId);
      localStorage.setItem(selectedLocationStorageKey, String(nextId));
    },
    [locations, prepareLocationChange, selectedLocationStorageKey]
  );

  // ── fetchers ────────────────────────────────────────────────────────────────
  const fetchStock = useCallback(async () => {
    if (selectedLocationId === null || !canReadStock) return;

    const requestLocationId = selectedLocationId;
    const requestCursor = stockCursor;
    const defaultView =
      !stockSearch &&
      stockState === "all" &&
      stockIndicators.length === 0 &&
      stockFamilyId === null;

    const requestSeq = ++stockRequestSeq.current;
    stockAbortRef.current?.abort();
    const requestController = new AbortController();
    stockAbortRef.current = requestController;
    setStockPageError(null);
    setLoadingStock(true);

    try {
      const params = new URLSearchParams({
        location_id: String(requestLocationId),
        limit: String(LIVE_STOCK_PAGE_SIZE),
      });

      if (stockCursor) params.set("cursor", stockCursor);
      if (stockSearch) params.set("search", stockSearch);
      if (stockState !== "all") params.set("stock_state", stockState);
      if (stockFamilyId !== null) {
        params.set("family_id", String(stockFamilyId));
      }
      if (stockIndicators.includes("reserved")) {
        params.set("has_reserved", "true");
      }
      if (stockIndicators.includes("unavailable")) {
        params.set("has_unavailable", "true");
      }
      if (stockIndicators.includes("damaged")) {
        params.set("has_damaged", "true");
      }
      if (stockIndicators.includes("recalled")) {
        params.set("has_recalled", "true");
      }
      if (stockIndicators.includes("vehicle")) {
        params.set("has_vehicle", "true");
      }
      if (stockIndicators.includes("minimum_unset")) {
        params.set("minimum_unset", "true");
      }

      const raw = await authFetch(
        `/warehouse/inventory/cursor?${params.toString()}`,
        { signal: requestController.signal }
      );

      if (requestSeq !== stockRequestSeq.current) return;
      const data = parseLiveStockPage(raw);
      const syncedAt = new Date();
      const nextItems = !requestCursor
        ? data.items
        : (() => {
            const seen = new Set(
              stockItemsRef.current.map((item) => item.id),
            );
            return [
              ...stockItemsRef.current,
              ...data.items.filter(
                (item) => !seen.has(item.id),
              ),
            ];
          })();

      stockItemsRef.current = nextItems;
      setStockItems(nextItems);
      setStockPageReady(true);
      if (defaultView && requestCursor === null) {
        patchLiveStockWarmSnapshot(
          warmScopeKey,
          requestLocationId,
          {
            hasPage: true,
            items: nextItems,
            nextCursor: data.next_cursor,
            lastSyncMs: syncedAt.getTime(),
            ...(typeof data.total === "number"
              ? { matchingTotal: data.total }
              : {}),
          },
        );
      }
      setStockNextCursor(data.next_cursor);

      if (typeof data.total === "number") {
        setStockMatchingTotal(data.total);
      }

      setLastSync(syncedAt);
    } catch (error: unknown) {
      if (requestSeq !== stockRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      setStockPageError(
        apiErrorMessage(
          error,
          t("inventoryLive.errors.loadFailed"),
        ),
      );
      const hasVisibleRows = stockItemsRef.current.length > 0;
      const warmSnapshot = defaultView
        ? readLiveStockWarmSnapshot(
            warmScopeKey,
            requestLocationId,
          )
        : null;
      if (!hasVisibleRows && warmSnapshot?.hasPage !== true) {
        stockItemsRef.current = [];
        setStockItems([]);
        setStockPageReady(false);
        setStockNextCursor(null);
        setStockMatchingTotal(null);
      }
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
    stockState,
    stockIndicators,
    stockFamilyId,
    canReadStock,
    t,
    warmScopeKey,
  ]);

  const fetchStockSummary = useCallback(async () => {
    if (selectedLocationId === null || !canReadStock) {
      setStockTotal(null);
      setStockAlertCount(null);
      return;
    }

    const requestLocationId = selectedLocationId;
    const requestSeq = ++stockSummaryRequestSeq.current;
    stockSummaryAbortRef.current?.abort();
    const requestController = new AbortController();
    stockSummaryAbortRef.current = requestController;
    setStockSummaryError(null);

    try {
      const raw = await authFetch(
        `/warehouse/inventory/summary?location_id=${encodeURIComponent(
          String(requestLocationId),
        )}`,
        { signal: requestController.signal },
      );

      if (requestSeq !== stockSummaryRequestSeq.current) return;
      const data = parseLiveStockSummary(raw);
      setStockTotal(data.stock_total);
      setStockAlertCount(data.alert_count);
      patchLiveStockWarmSnapshot(
        warmScopeKey,
        requestLocationId,
        {
          hasSummary: true,
          stockTotal: data.stock_total,
          alertCount: data.alert_count,
        },
      );
    } catch (error: unknown) {
      if (requestSeq !== stockSummaryRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      const warmSnapshot = readLiveStockWarmSnapshot(
        warmScopeKey,
        requestLocationId,
      );
      if (warmSnapshot?.hasSummary !== true) {
        setStockTotal(null);
        setStockAlertCount(null);
      }
      setStockSummaryError(
        apiErrorMessage(
          error,
          t("inventoryLive.errors.loadFailed"),
        ),
      );
    } finally {
      if (stockSummaryAbortRef.current === requestController) {
        stockSummaryAbortRef.current = null;
      }
    }
  }, [
    authFetch,
    selectedLocationId,
    canReadStock,
    t,
    warmScopeKey,
  ]);

  const resetStockPagination = useCallback(() => {
    stockItemsRef.current = [];
    setStockItems([]);
    setStockPageReady(false);
    setStockCursor(null);
    setStockNextCursor(null);
    setStockMatchingTotal(null);
  }, []);

  const refreshStock = useCallback(() => {
    stockRequestSeq.current += 1;
    stockAbortRef.current?.abort();
    stockAbortRef.current = null;
    stockSummaryRequestSeq.current += 1;
    stockSummaryAbortRef.current?.abort();
    stockSummaryAbortRef.current = null;
    setStockCursor(null);
    setStockPageError(null);
    setStockSummaryError(null);
    setLoadingStock(selectedLocationId !== null);
    setStockRefreshKey((value) => value + 1);
  }, [selectedLocationId]);

  const handleStockSearchChange = useCallback((value: string) => {
    if (value === stockSearch) return;
    resetStockPagination();
    setStockSearch(value);
  }, [resetStockPagination, stockSearch]);

  const handleStockStateChange = useCallback(
    (value: LiveStockStockState) => {
      resetStockPagination();
      setStockState(value);
    },
    [resetStockPagination],
  );

  const handleStockIndicatorsChange = useCallback(
    (value: LiveStockIndicator[]) => {
      resetStockPagination();
      setStockIndicators(value);
    },
    [resetStockPagination],
  );

  const handleStockFamilyChange = useCallback(
    (value: number | null) => {
      resetStockPagination();
      setStockFamilyId(value);
    },
    [resetStockPagination],
  );

  const handleStockLoadMore = useCallback(() => {
    if (!stockNextCursor || loadingStock) return;
    setStockCursor(stockNextCursor);
  }, [loadingStock, stockNextCursor]);

  // حالة القفل مرتبطة دائماً بالمستودع المحدد.
  const fetchStatus = useCallback(async () => {
    const requestSeq = ++statusRequestSeq.current;

    if (selectedLocationId === null) {
      setAuditLockState(false);
      setVerifiedStatusLocationId(null);
      setLoadingStatus(false);
      return;
    }
    if (locationAccess.isPending) {
      setLoadingStatus(true);
      return;
    }
    if (!canReadStatus) {
      setAuditLockState(false);
      setVerifiedStatusLocationId(null);
      setLoadingStatus(false);
      return;
    }

    const requestLocationId = selectedLocationId;
    setVerifiedStatusLocationId(null);
    setLoadingStatus(true);

    try {
      const raw = await authFetch(
        `/warehouse/status?location_id=${encodeURIComponent(
          String(requestLocationId)
        )}`
      );

      if (requestSeq !== statusRequestSeq.current) return;
      if (typeof raw !== "object" || raw === null || !("status" in raw)) {
        inventoryContractError("WAREHOUSE_STATUS_RESPONSE_INVALID");
      }

      const data = raw as WarehouseStatusPayload;
      const locked = data.status === "AUDIT_LOCK";
      setAuditLockState(locked);
      setVerifiedStatusLocationId(requestLocationId);
      patchLiveStockWarmSnapshot(
        warmScopeKey,
        requestLocationId,
        {
          hasStatus: true,
          auditLocked: locked,
        },
      );
    } catch (error: unknown) {
      if (requestSeq !== statusRequestSeq.current) return;

      toast.error(
        apiErrorMessage(
          error,
          t("inventoryShell.errors.statusCheckFailed"),
        ),
      );
      setAuditLockState(true);
    } finally {
      if (requestSeq === statusRequestSeq.current) {
        setLoadingStatus(false);
      }
    }
  }, [
    authFetch,
    selectedLocationId,
    canReadStatus,
    locationAccess.isPending,
    t,
    warmScopeKey,
  ]);

  // ── on mount ────────────────────────────────────────────────────────────────
  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    return () => {
      statusRequestSeq.current += 1;
      stockRequestSeq.current += 1;
      stockAbortRef.current?.abort();
      stockAbortRef.current = null;
      stockSummaryRequestSeq.current += 1;
      stockSummaryAbortRef.current?.abort();
      stockSummaryAbortRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (selectedLocationId !== null) {
      void fetchStock();
    }
  }, [selectedLocationId, fetchStock, stockRefreshKey]);

  useEffect(() => {
    if (selectedLocationId !== null) {
      void fetchStockSummary();
    }
  }, [selectedLocationId, fetchStockSummary, stockRefreshKey]);

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

  const canShowWarmLiveDuringAccessRefresh =
    activeTab === "live" &&
    selectedLocationId !== null &&
    locationAccess.isPending &&
    stockPageReady &&
    !locationAccess.isError;

  if (loadingLocations && warehouseSetup === null) {
    return (
      <div className="flex items-center justify-center h-full w-full text-slate-500 font-bold">
        <RefreshCcw className="w-5 h-5 ml-2 animate-spin" />
        {t("inventoryShell.loadingWarehouses")}
      </div>
    );
  }

  if (locationError) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full bg-slate-50/50 rounded-3xl border border-red-200 p-8 text-center">
        <Package className="w-10 h-10 text-red-500 mb-4" />
        <h2 className="text-xl font-black text-slate-800 mb-2">
          {t("inventoryShell.locationsLoadTitle")}
        </h2>
        <p className="text-slate-500 font-bold max-w-md">
          {t("inventoryShell.locationsLoadGuard")}
        </p>
        <button
          onClick={() => void fetchLocations()}
          className="mt-6 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg transition-all active:scale-95 flex items-center gap-2"
        >
          <RefreshCcw className="w-5 h-5" /> {t("inventoryShell.retry")}
        </button>
      </div>
    );
  }

  // ─── UI ─────────────────────────────────────────────────────────────────────
  return (
    <div data-live-view={activeTab === "live"} className="inventory-workspace flex flex-col gap-4 w-full h-full flex-1 min-h-0">

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
                          locale,
                          { numberingSystem: "latn" },
                        ).format(stockTotal)}
                  </span>
                </span>
                {displayAuditLocked && (
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
                        locale,
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

      {locationsTruncated && (
        <p role="status" className="inventory-alert-banner flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm font-bold">
          {t("inventoryShell.locationsTruncated")}
        </p>
      )}
      {locationAccess.isError && selectedLocationId !== null && (
        <p role="alert" className="inventory-alert-banner flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm font-bold">
          {t("inventoryShell.accessChanged")}
          <button
            type="button"
            className="rounded-lg bg-orange-100 px-3 py-1.5 text-orange-800"
            onClick={() => {
              void fetchLocations();
              void locationAccess.refetch();
            }}
          >
            {t("inventoryShell.refreshAccess")}
          </button>
        </p>
      )}
      {/* ═══ Tab Content ═══ */}
      <div className="inventory-content flex-1 min-h-0 flex flex-col">
        {selectedLocationId !== null &&
          locationAccess.isPending &&
          !canShowWarmLiveDuringAccessRefresh && (
          <div className="inventory-empty-state flex flex-1 items-center justify-center gap-2 px-6 text-center font-bold text-slate-500">
            <RefreshCcw className="h-5 w-5 animate-spin" />
            {t("common.loading")}
          </div>
        )}
        {selectedLocationId === null && activeTab !== "warehouses" && activeTab !== "permissions" && (
          <div className="inventory-empty-state flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center font-bold">
            <p>
              {warehouseSetup?.warehouse_ready === false
                ? t("inventoryShell.noWarehouseCreated")
                : warehouseSetup?.accessible_warehouse_count === 0
                  ? t("inventoryShell.noAccessibleWarehouse")
                  : t("inventoryShell.noWarehouseSelected")}
            </p>
            {locations.length > 0 && (
              <select aria-label={t("inventoryShell.warehouseSelectLabel")} className="inventory-location-select px-3 py-2 text-sm font-bold" value="" onChange={(e) => handleLocationChange(e.target.value)}>
                <option value="" disabled>{t("inventoryShell.chooseWarehouse")}</option>
                {locations.map((loc) => <option key={loc.id} value={loc.id}>{loc.name}</option>)}
              </select>
            )}
            {warehouseSetup?.warehouse_ready === false && warehouseSetup.can_create && tabAllowed("warehouses") && (
              <button type="button" onClick={() => setActiveTab("warehouses")} className="rounded-xl bg-blue-600 px-4 py-2 text-white">
                {t("inventoryShell.openWarehouseManagement")}
              </button>
            )}
          </div>
        )}

        {activeTab === "live" &&
          selectedLocationId !== null &&
          !locationAccess.isError &&
          (
            canShowWarmLiveDuringAccessRefresh ||
            (!locationAccess.isPending && tabAllowed("live"))
          ) && (
          <Tab1LiveStock
            locationId={selectedLocationId}
            locations={locations}
            stockTotal={stockTotal}
            lastSync={lastSync}
            isAuditLocked={displayAuditLocked}
            products={stockItems}
            loading={loadingStock}
            pageReady={stockPageReady}
            pageError={stockPageError}
            summaryError={stockSummaryError}
            onLocationChange={handleLocationChange}
            onRefresh={() => {
              refreshStock();
              void fetchStatus();
            }}
            alertCount={stockAlertCount}
            matchingTotal={stockMatchingTotal}
            hasMore={!!stockNextCursor}
            stockState={stockState}
            indicators={stockIndicators}
            familyId={stockFamilyId}
            canManageMinimum={isCompanyAdmin}
            onSearchChange={handleStockSearchChange}
            onStockStateChange={handleStockStateChange}
            onIndicatorsChange={handleStockIndicatorsChange}
            onFamilyChange={handleStockFamilyChange}
            onLoadMore={handleStockLoadMore}
          />
        )}
        {!locationAccess.isPending && activeTab === "batches" && tabAllowed("batches") && selectedLocationId !== null && (
          <TabBatches
            key={selectedLocationId}
            locationId={selectedLocationId}
          />
        )}
        {!locationAccess.isPending && activeTab === "inbound" && tabAllowed("inbound") && selectedLocationId !== null && locationAccess.data && (
          <Tab2Inbound
            key={`${locationAccess.data.company_id}:${locationAccess.data.driver_id}:${selectedLocationId}`}
            companyId={locationAccess.data.company_id}
            actorId={locationAccess.data.driver_id}
            locationId={selectedLocationId} // +++ تمرير الموقع لعملية الإدخال +++
            isAuditLocked={effectiveAuditLocked}
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
            isAuditLocked={effectiveAuditLocked}
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
