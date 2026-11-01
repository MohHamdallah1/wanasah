import {
  parseInventoryLocationCapabilities,
  useInventoryAccess,
} from "@/hooks/useInventoryAccess";
import { TabInventoryAccess } from "./TabInventoryAccess";
import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { Package, History, Lock, RefreshCcw, FilePlus, Building2, ArrowRightLeft, Layers3 } from "lucide-react";
import { toast } from "sonner";
import { apiErrorMessage } from "@/lib/apiErrors";
import { parseInventoryNavigationState } from "@/features/inventory/navigation";
import { createDispatchReservationFocusState } from "@/features/dispatch/navigation";
import { resolveI18nLocale } from "@/lib/locale";
import { Tab1LiveStock } from "./Tab1LiveStock";
import { TabBatches } from "./TabBatches";
import { Tab2Inbound } from "./Tab2Inbound";
import { Tab3Stocktake } from "./Tab3Stocktake";
import { Tab4Ledger } from "./Tab4Ledger";
import { TabWarehouseLocations } from "./TabWarehouseLocations";
import { TabTransfers } from "./TabTransfers";
import { ArchiveOwnerWorkspace } from "./archive/ArchiveOwnerWorkspace";
import type { TransferFocus } from "./transfers/types";
import type { BatchSpecialTransferResult } from "./batches/batchSpecialTransferContract";
import type { ReservationOwner } from "./batches/batchStockSourcesContract";
import { InventoryTopDock } from "./InventoryTopDock";
import "./inventory.css";
import {
  parseLiveStockSummary,
  parseLiveStockPage,
  type LiveStockIndicator,
  type LiveStockStockState,
  type LiveStockSort,
  type LiveStockView,
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
  status: "ACTIVE" | "AUDIT_LOCK";
  stocktake_session_id: number | null;
  stocktake_reference: string | null;
  stocktake_status: string | null;
}

const parseWarehouseStatusPayload = (value: unknown): WarehouseStatusPayload => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    inventoryContractError("WAREHOUSE_STATUS_RESPONSE_INVALID");
  }
  const raw = value as Record<string, unknown>;
  if (raw.status !== "ACTIVE" && raw.status !== "AUDIT_LOCK") {
    inventoryContractError("WAREHOUSE_STATUS_RESPONSE_INVALID");
  }
  const sessionId = raw.stocktake_session_id;
  const reference = raw.stocktake_reference;
  const stocktakeStatus = raw.stocktake_status;
  if (
    sessionId !== null && sessionId !== undefined &&
    (!Number.isInteger(sessionId) || Number(sessionId) <= 0)
  ) {
    inventoryContractError("WAREHOUSE_STATUS_RESPONSE_INVALID");
  }
  if (
    reference !== null && reference !== undefined &&
    (typeof reference !== "string" || !reference.trim() || reference.length > 100)
  ) {
    inventoryContractError("WAREHOUSE_STATUS_RESPONSE_INVALID");
  }
  if (
    stocktakeStatus !== null && stocktakeStatus !== undefined &&
    (typeof stocktakeStatus !== "string" || !stocktakeStatus.trim() || stocktakeStatus.length > 50)
  ) {
    inventoryContractError("WAREHOUSE_STATUS_RESPONSE_INVALID");
  }
  if (
    raw.status === "AUDIT_LOCK" &&
    (
      typeof sessionId !== "number" ||
      typeof reference !== "string" ||
      typeof stocktakeStatus !== "string"
    )
  ) {
    inventoryContractError("WAREHOUSE_STATUS_RESPONSE_INVALID");
  }
  if (
    raw.status === "ACTIVE" &&
    (
      sessionId !== null && sessionId !== undefined ||
      reference !== null && reference !== undefined ||
      stocktakeStatus !== null && stocktakeStatus !== undefined
    )
  ) {
    inventoryContractError("WAREHOUSE_STATUS_RESPONSE_INVALID");
  }
  return {
    status: raw.status,
    stocktake_session_id: typeof sessionId === "number" ? sessionId : null,
    stocktake_reference: typeof reference === "string" ? reference.trim() : null,
    stocktake_status: typeof stocktakeStatus === "string" ? stocktakeStatus.trim() : null,
  };
};

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
  selected?: WarehouseLocationOption | null;
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

  let selected: WarehouseLocationOption | null | undefined;
  if ("selected" in page) {
    if (page.selected === null) {
      selected = null;
    } else {
      const parsedSelected = parseWarehouseLocationPage({
        items: [page.selected],
        next_cursor: null,
        has_more: false,
        total: null,
      });
      selected = parsedSelected.items[0];
    }
  }

  return {
    items,
    next_cursor: nextCursor,
    has_more: hasMore as boolean,
    total,
    selected,
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


// Keep the workspace geometry stable while an authorized list is pending.
// This surface never renders cached inventory, permissions or protected data.
function InventoryPendingSurface({ label, live = false }: { label: string; live?: boolean }) {
  // Keep the live-stock table geometry present while the new mount validates
  // server authority. Never show a warm inventory row/cost as current here.
  // The prior centered loading message caused an unnecessary full-page flash.
  if (live) {
    return (
      <div className="inventory-view inventory-live-stock flex min-h-0 flex-1 flex-col gap-2"
        data-inventory-pending-surface="true" data-live-verification-shell="true">
        <section className="glass-card inventory-data-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl pt-0">
          <div className="live-stock-toolbar flex items-center gap-2 border-b border-slate-100 bg-slate-50/70 px-3 py-2"
            data-cp13-controls="stock-list" aria-hidden="true">
            <span className="h-9 min-w-32 flex-1 rounded-xl bg-slate-100" />
            <span className="h-9 w-16 shrink-0 rounded-xl bg-slate-100" />
            <span className="h-9 w-24 shrink-0 rounded-xl bg-slate-100" />
            <span className="h-9 w-28 shrink-0 rounded-xl bg-slate-100" />
            <span className="h-9 w-44 shrink-0 rounded-xl bg-slate-100" />
          </div>
          <div className="custom-scrollbar min-h-0 flex-1 overflow-auto" aria-hidden="true">
            <div className="flex h-10 items-center gap-4 border-b border-slate-200 bg-slate-50/95 px-4">
              <span className="h-3 w-1/4 rounded bg-slate-200" />
              <span className="h-3 w-1/5 rounded bg-slate-200" />
              <span className="h-3 w-1/5 rounded bg-slate-200" />
            </div>
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index} className="flex h-14 items-center gap-4 border-b border-slate-100 px-4">
                <span className="h-3 w-1/4 rounded bg-slate-100" />
                <span className="h-3 w-1/5 rounded bg-slate-100" />
                <span className="h-3 w-1/6 rounded bg-slate-100" />
              </div>
            ))}
          </div>
          <span className="sr-only" role="status" aria-live="polite">{label}</span>
        </section>
      </div>
    );
  }
  return (
    <div className="inventory-view flex min-h-0 flex-1 flex-col" data-inventory-pending-surface="true">
      <section className="inventory-surface inventory-data-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div aria-hidden="true" className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-100 px-4">
          <span className="h-5 w-32 animate-pulse rounded-md bg-slate-100" />
          <span className="h-8 w-44 max-w-[35%] animate-pulse rounded-md bg-slate-100" />
        </div>
        <div className="relative min-h-0 flex-1">
          <div aria-hidden="true" className="flex h-10 items-center gap-4 border-b border-slate-200 bg-slate-50/95 px-4">
            <span className="h-3 w-1/4 rounded bg-slate-200" />
            <span className="h-3 w-1/5 rounded bg-slate-200" />
            <span className="h-3 w-1/5 rounded bg-slate-200" />
          </div>
          <div role="status" aria-live="polite" className="absolute inset-x-0 top-12 flex items-center justify-center gap-2 px-4 py-5 text-sm font-semibold text-slate-500">
            <RefreshCcw aria-hidden="true" className="h-4 w-4 animate-spin" />
            {label}
          </div>
        </div>
      </section>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function MainInventory() {
  const authFetch = useAuthFetch();
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);
  const routeLocation = useLocation();
  const routeNavigate = useNavigate();
  const inventoryRouteActive = routeLocation.pathname === "/inventory";
  const inventoryRouteActiveRef = useRef(inventoryRouteActive);
  inventoryRouteActiveRef.current = inventoryRouteActive;
  const previousInventoryRouteActiveRef = useRef(inventoryRouteActive);
  const returningToInventory =
    inventoryRouteActive && !previousInventoryRouteActiveRef.current;
  useEffect(() => {
    previousInventoryRouteActiveRef.current = inventoryRouteActive;
  }, [inventoryRouteActive]);
  const initialNavigationIntentRef = useRef(
    parseInventoryNavigationState(routeLocation.state),
  );
  const initialNavigationIntent = initialNavigationIntentRef.current;
  const [archiveOwnerFocus, setArchiveOwnerFocus] = useState(
    initialNavigationIntent?.kind === "owner-focus" ? initialNavigationIntent : null,
  );

  // UI preference only. Server token + RLS remain the security authority.
  const companyId = localStorage.getItem("company_id") || "";
  const activeTabStorageKey = companyId
    ? `inventory_active_tab:${companyId}`
    : "inventory_active_tab:anonymous";
  const selectedLocationStorageKey = companyId
    ? `inventory_selected_location:${companyId}`
    : "inventory_selected_location:anonymous";

  const backofficeUserId = localStorage.getItem("backoffice_user_id") || "";
  const principalId = localStorage.getItem("principal_id") || "";
  const warmScopeKey = inventoryWarmScopeKey(companyId, backofficeUserId, principalId);
  const mountedScopeKey = useRef(warmScopeKey);
  const [identityChanged, setIdentityChanged] = useState(false);
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
    if (initialNavigationIntent && isTabId(initialNavigationIntent.tab)) {
      return initialNavigationIntent.tab;
    }
    const saved = localStorage.getItem(activeTabStorageKey);
    return isTabId(saved) ? saved : "live";
  });
  const [batchTabVisited, setBatchTabVisited] = useState(
    activeTab === "batches",
  );
  useEffect(() => {
    if (activeTab === "batches") setBatchTabVisited(true);
  }, [activeTab]);

  const [batchNavigationFocus, setBatchNavigationFocus] = useState(
    initialNavigationIntent?.kind === "batch-focus"
      ? initialNavigationIntent
      : null,
  );
  const [transferFocus, setTransferFocus] =
    useState<TransferFocus | null>(null);

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
  const [
    permissionRevalidationFloor,
    setPermissionRevalidationFloor,
  ] = useState<{ global: number; location: number } | null>(null);

  useEffect(() => {
    const markPermissionRevalidation = () => {
      setPermissionRevalidationFloor({
        global: Number(access.dataUpdatedAt ?? 0),
        location: Number(locationAccess.dataUpdatedAt ?? 0),
      });
    };
    window.addEventListener(
      "inventory-permission-denied",
      markPermissionRevalidation,
    );
    return () => window.removeEventListener(
      "inventory-permission-denied",
      markPermissionRevalidation,
    );
  }, [access.dataUpdatedAt, locationAccess.dataUpdatedAt]);

  // A cached React Query success is not a fresh canonical admission. Once a
  // same-session scope has been freshly admitted, however, an ordinary
  // background refetch from another mounted dashboard page must not revoke
  // that admission just because React Query toggled isFetching. A real 403
  // signal still fails closed until strictly newer access reads complete.
  const matchesSession = (data: typeof access.data) =>
    !!data &&
    data.company_id === Number(companyId) &&
    data.principal_id === Number(principalId) &&
    data.backoffice_user_id === Number(backofficeUserId) &&
    localStorage.getItem("company_id") === companyId &&
    localStorage.getItem("principal_id") === principalId &&
    localStorage.getItem("backoffice_user_id") === backofficeUserId &&
    mountedScopeKey.current === warmScopeKey &&
    warmScopeKey !== null && !identityChanged;

  const globalAccessMatches =
    access.isSuccess && !access.isError && matchesSession(access.data);
  const globalAccessFresh =
    globalAccessMatches && access.isFetchedAfterMount && !access.isFetching;
  const admittedGlobalAccessScope = useRef<string | null>(null);
  if (globalAccessFresh) {
    admittedGlobalAccessScope.current = warmScopeKey;
  }
  const globalAccessVerified =
    permissionRevalidationFloor === null &&
    globalAccessMatches &&
    (
      globalAccessFresh ||
      (
        access.isFetching &&
        admittedGlobalAccessScope.current === warmScopeKey
      )
    );

  const locationAccessMatches =
    locationAccess.isSuccess && !locationAccess.isError &&
    matchesSession(locationAccess.data) &&
    locationAccess.data?.location_id === selectedLocationId;
  const locationAccessFresh =
    locationAccessMatches &&
    locationAccess.isFetchedAfterMount &&
    !locationAccess.isFetching;
  const locationAccessScope =
    warmScopeKey !== null && selectedLocationId !== null
      ? `${warmScopeKey}:${selectedLocationId}`
      : null;
  const admittedLocationAccessScope = useRef<string | null>(null);
  if (locationAccessFresh) {
    admittedLocationAccessScope.current = locationAccessScope;
  }
  const locationAccessVerified =
    globalAccessVerified &&
    permissionRevalidationFloor === null &&
    locationAccessMatches &&
    (
      locationAccessFresh ||
      (
        locationAccess.isFetching &&
        admittedLocationAccessScope.current === locationAccessScope
      )
    );

  useEffect(() => {
    if (permissionRevalidationFloor === null) return;
    const globalReadAdvanced =
      globalAccessFresh &&
      Number(access.dataUpdatedAt ?? 0) > permissionRevalidationFloor.global;
    const locationReadAdvanced =
      selectedLocationId === null ||
      (
        locationAccessFresh &&
        Number(locationAccess.dataUpdatedAt ?? 0) >
          permissionRevalidationFloor.location
      );
    if (globalReadAdvanced && locationReadAdvanced) {
      setPermissionRevalidationFloor(null);
    }
  }, [
    access.dataUpdatedAt,
    globalAccessFresh,
    locationAccess.dataUpdatedAt,
    locationAccessFresh,
    permissionRevalidationFloor,
    selectedLocationId,
  ]);

  const globalAdmissionEpoch = useRef(0);
  const priorGlobalAdmission = useRef(false);
  if (priorGlobalAdmission.current && !globalAccessVerified) {
    globalAdmissionEpoch.current += 1;
  }
  priorGlobalAdmission.current = globalAccessVerified;
  const [serverVerifiedLocationId, setServerVerifiedLocationId] =
    useState<number | null>(null);
  const [selectorAdmissionEpoch, setSelectorAdmissionEpoch] =
    useState<number | null>(null);
  const liveAuthorityVerified =
    locationAccessVerified && selectedLocationId !== null &&
    serverVerifiedLocationId === selectedLocationId &&
    selectorAdmissionEpoch === globalAdmissionEpoch.current &&
    locationAccess.can("inventory.read");
  const liveAdmissionEpoch = useRef(0);
  const priorLiveAdmission = useRef(false);
  if (priorLiveAdmission.current && !liveAuthorityVerified) {
    liveAdmissionEpoch.current += 1;
  }
  priorLiveAdmission.current = liveAuthorityVerified;
  // Retain the canonical capability predicate and enforce fresh admission
  // separately; a cached capability alone never exposes the read model.
  const canReadStock = locationAccess.can('inventory.read');
  const canReadStatus = locationAccessVerified && locationAccess.can("location.read");
  const authorityRef = useRef({ admitted: false, scope: warmScopeKey, location: selectedLocationId });
  authorityRef.current = {
    admitted: liveAuthorityVerified,
    scope: warmScopeKey,
    location: selectedLocationId,
  };
  const requestStillAuthorized = (scope: string | null, location: number) =>
    authorityRef.current.admitted && authorityRef.current.scope === scope &&
    authorityRef.current.location === location &&
    localStorage.getItem("company_id") === companyId &&
    localStorage.getItem("principal_id") === principalId &&
    localStorage.getItem("backoffice_user_id") === backofficeUserId;
  const { isCompanyOwner, canAny, can } = access;
  const { can: canAtLocation } = locationAccess;
  const tabAllowed = useCallback((id: TabId) => {
    if (id === 'permissions') return isCompanyOwner;
    if (id === 'warehouses') return canAny('location.read') || can('branch.read');
    if (id === 'transfers') return canAny('transfer.read');
    if (selectedLocationId === null) return canAny(TAB_PERMISSION[id]);
    if (id === 'inbound') return canAtLocation('inbound.create') && canAtLocation('catalog.read');
    return canAtLocation(TAB_PERMISSION[id]);
  }, [isCompanyOwner, canAny, can, canAtLocation, selectedLocationId]);
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
  const accessDenied =
    identityChanged || [access, locationAccess].some((entry) =>
      entry.isError && [401, 403, 404].includes(
        Number((entry.error as { status?: unknown } | null)?.status),
      ),
    ) || (locationAccessVerified && !locationAccess.can("inventory.read"));
  useEffect(() => {
    if (!accessDenied || selectedLocationId === null) return;
    stockRequestSeq.current += 1;
    stockAbortRef.current?.abort();
    stockSummaryRequestSeq.current += 1;
    stockSummaryAbortRef.current?.abort();
    dropLiveStockWarmSnapshot(warmScopeKey, selectedLocationId);
    stockItemsRef.current = [];
    setStockItems([]);
    setStockPageReady(false);
    setStockCursor(null);
    setStockNextCursor(null);
    setStockMatchingTotal(null);
    setStockTotal(null);
    setStockAlertCount(null);
    setLastSync(null);
    setDeniedAdmissionEpoch(liveAdmissionEpoch.current);
    setLiveReadPhase("denied");
  }, [accessDenied, selectedLocationId, warmScopeKey]);

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
  
  // A cached page is not a newly verified inventory read. Keep warm data
  // internal only; never mount its rows while returning to this workspace.
  const [stockItems, setStockItems] = useState<WarehouseProduct[]>([]);
  const stockItemsRef = useRef<WarehouseProduct[]>(stockItems);
  const [stockPageReady, setStockPageReady] = useState(false);
  type LiveReadPhase = "initial" | "warm" | "fresh" | "failed" | "denied";
  const [liveReadPhase, setLiveReadPhase] = useState<LiveReadPhase>("initial");
  const [freshPageAdmissionEpoch, setFreshPageAdmissionEpoch] =
    useState<number | null>(null);
  const [freshSummaryAdmissionEpoch, setFreshSummaryAdmissionEpoch] =
    useState<number | null>(null);
  const [deniedAdmissionEpoch, setDeniedAdmissionEpoch] =
    useState<number | null>(null);
  useEffect(() => {
    stockItemsRef.current = stockItems;
  }, [stockItems]);
  const [stockTotal, setStockTotal] = useState<number | null>(null);
  const [stockMatchingTotal, setStockMatchingTotal] = useState<number | null>(null);
  const [stockAlertCount, setStockAlertCount] = useState<number | null>(null);
  const [stockCursor, setStockCursor] = useState<string | null>(null);
  const [stockNextCursor, setStockNextCursor] = useState<string | null>(null);
  const [stockSearch, setStockSearch] = useState("");
  const [stockState, setStockState] =
    useState<LiveStockStockState>("all");
  const [stockSort, setStockSort] = useState<LiveStockSort>("stock_first");
  const [stockView, setStockView] = useState<LiveStockView>("warehouse");
  const [stockIndicators, setStockIndicators] =
    useState<LiveStockIndicator[]>([]);
  const [stockFamilyId, setStockFamilyId] =
    useState<number | null>(null);
  const [stockRefreshKey, setStockRefreshKey] = useState(0);
  const [stockPageRetryKey, setStockPageRetryKey] = useState(0);
  const [stockPageError, setStockPageError] = useState<string | null>(null);
  const [stockSummaryError, setStockSummaryError] = useState<string | null>(null);
  const stockRequestSeq = useRef(0);
  const stockAbortRef = useRef<AbortController | null>(null);
  const stockSummaryRequestSeq = useRef(0);
  const stockSummaryAbortRef = useRef<AbortController | null>(null);
  // Another tab may switch the principal/company while this workspace is
  // mounted. Revoke disclosure and in-flight readers on the storage event.
  useEffect(() => {
    const checkSessionScope = () => {
      const scopeNow = inventoryWarmScopeKey(
        localStorage.getItem("company_id") || "",
        localStorage.getItem("backoffice_user_id") || "",
        localStorage.getItem("principal_id") || "",
      );
      if (scopeNow === mountedScopeKey.current) return;
      authorityRef.current.admitted = false;
      stockRequestSeq.current += 1;
      stockAbortRef.current?.abort();
      stockSummaryRequestSeq.current += 1;
      stockSummaryAbortRef.current?.abort();
      clearInventoryWarmScope(mountedScopeKey.current);
      setIdentityChanged(true);
    };
    window.addEventListener("storage", checkSessionScope);
    window.addEventListener("focus", checkSessionScope);
    return () => {
      window.removeEventListener("storage", checkSessionScope);
      window.removeEventListener("focus", checkSessionScope);
    };
  }, []);

  const locationRequestSeq = useRef(0);
  const locationAbortRef = useRef<AbortController | null>(null);
  const [warehouseSearchInput, setWarehouseSearchInput] = useState("");
  const [warehouseSearch, setWarehouseSearch] = useState("");
  const [warehouseCursorTrail, setWarehouseCursorTrail] = useState<Array<string | null>>([null]);
  const [warehouseNextCursor, setWarehouseNextCursor] = useState<string | null>(null);
  const warehouseCursor = warehouseCursorTrail[warehouseCursorTrail.length - 1] ?? null;
  useEffect(() => {
    const clean = warehouseSearchInput.trim();
    if (clean.length === 1) return;
    const timer = window.setTimeout(() => {
      const next = clean.length >= 2 ? clean : "";
      if (next !== warehouseSearch) {
        setWarehouseCursorTrail([null]);
        setWarehouseSearch(next);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [warehouseSearchInput, warehouseSearch]);
  const statusRequestSeq = useRef(0);

  const [ledgerRefreshKey, setLedgerRefreshKey] = useState(0);
  const [batchRefreshKey, setBatchRefreshKey] = useState(0);
  const [auditLockState, setAuditLockState] = useState<boolean | null>(
    initialLiveSnapshot?.hasStatus
      ? initialLiveSnapshot.auditLocked
      : null,
  );
  const [auditLockReference, setAuditLockReference] = useState<string | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [verifiedStatusLocationId, setVerifiedStatusLocationId] =
    useState<number | null>(null);
  const [loadingStock, setLoadingStock] = useState(
    initialSelectedLocationId !== null,
  );
  const [lastSync, setLastSync] = useState<Date | null>(null);

  useEffect(() => {
    if (!liveAuthorityVerified || liveReadPhase !== "denied" ||
        deniedAdmissionEpoch === liveAdmissionEpoch.current) return;
    setLiveReadPhase("initial");
    setStockPageRetryKey((value) => value + 1);
  }, [liveAuthorityVerified, liveReadPhase, deniedAdmissionEpoch]);

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

      // Warm snapshots may help remember the shell/status, but neither
      // cached list rows nor cached totals may masquerade as live stock.
      // On location changes, wait for independent authorized HTTP reads.
      stockItemsRef.current = [];
      setStockItems([]);
      setStockPageReady(false);
      setLiveReadPhase("initial");
      setFreshPageAdmissionEpoch(null);
      setFreshSummaryAdmissionEpoch(null);
      setStockMatchingTotal(null);
      setStockNextCursor(null);
      setLastSync(null);
      setStockTotal(null);
      setStockAlertCount(null);

      setAuditLockState(
        snapshot?.hasStatus
          ? snapshot.auditLocked
          : null,
      );
      setAuditLockReference(null);
      setLoadingStock(locationId !== null);
    },
    [warmScopeKey],
  );

  const prepareLocationChange = useCallback(
    (locationId: number | null) => {
      statusRequestSeq.current += 1;
      setVerifiedStatusLocationId(null);
      setAuditLockReference(null);
      stockRequestSeq.current += 1;
      stockAbortRef.current?.abort();
      stockAbortRef.current = null;
      stockSummaryRequestSeq.current += 1;
      stockSummaryAbortRef.current?.abort();
      stockSummaryAbortRef.current = null;

      setStockSearch("");
      setStockState("all");
      setStockSort("stock_first");
      setStockView("warehouse");
      setStockIndicators([]);
      setStockFamilyId(null);
      setStockCursor(null);
      setStockPageError(null);
      setStockSummaryError(null);
      setServerVerifiedLocationId(null);
      setSelectorAdmissionEpoch(null);
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
    if (!globalAccessVerified || (!canAny('inventory.read') && !canAny('location.read'))) return;
    const requestSeq = ++locationRequestSeq.current;
    locationAbortRef.current?.abort();
    const controller = new AbortController();
    locationAbortRef.current = controller;
    setLoadingLocations(true);
    setLocationError(false);
    setServerVerifiedLocationId(null);
    setSelectorAdmissionEpoch(null);
    const requestAccessEpoch = globalAdmissionEpoch.current;

    const savedRaw = localStorage.getItem(selectedLocationStorageKey);
    const savedId = savedRaw ? Number(savedRaw) : null;
    const currentId = selectedLocationIdRef.current;
    const preferredId = (
      savedId !== null && Number.isSafeInteger(savedId) && savedId > 0
        ? savedId
        : currentId
    );
    const params = new URLSearchParams({ limit: "100" });
    if (warehouseSearch) params.set("search", warehouseSearch);
    if (warehouseCursor) params.set("cursor", warehouseCursor);
    if (preferredId !== null) {
      params.set("selected_location_id", String(preferredId));
    }

    try {
      const [locationsRaw, setupRaw] = await Promise.all([
        authFetch(`/warehouse/locations/selection?${params.toString()}`, {
          signal: controller.signal,
        }),
        canAny('location.read')
          ? authFetch("/warehouse/setup-status", { signal: controller.signal })
          : Promise.resolve(null),
      ]);
      if (requestSeq !== locationRequestSeq.current ||
          requestAccessEpoch !== globalAdmissionEpoch.current ||
          !globalAccessVerified ||
          localStorage.getItem("company_id") !== companyId ||
          localStorage.getItem("principal_id") !== principalId ||
          localStorage.getItem("backoffice_user_id") !== backofficeUserId) return;

      const page = parseWarehouseLocationPage(locationsRaw);
      // The company-wide setup contract is management-only. Its location.read
      // count is not interchangeable with this inventory-accessible selector.
      const setup = setupRaw === null ? null : parseWarehouseSetupStatus(setupRaw);
      const selected = page.selected?.id === preferredId ? page.selected : null;
      const options = selected && !page.items.some((item) => item.id === selected.id)
        ? [selected, ...page.items]
        : page.items;

      setLocations(options);
      setWarehouseSetup(setup);
      setLocationsTruncated(page.has_more);
      setWarehouseNextCursor(page.next_cursor);

      const nextLocationId = selected?.id ?? page.items[0]?.id ?? null;
      if (nextLocationId !== currentId) {
        prepareLocationChange(nextLocationId);
        selectedLocationIdRef.current = nextLocationId;
        setSelectedLocationId(nextLocationId);
      }
      // The backend selector response, not the warm shell, authorizes
      // offering this warehouse to the user for the current request.
      setServerVerifiedLocationId(nextLocationId);
      setSelectorAdmissionEpoch(requestAccessEpoch);
      if (nextLocationId !== null) {
        localStorage.setItem(selectedLocationStorageKey, String(nextLocationId));
      } else {
        localStorage.removeItem(selectedLocationStorageKey);
      }
    } catch (error: unknown) {
      if (requestSeq !== locationRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      const rejected = (error as { status?: number } | null)?.status === 403;
      if (rejected || (selectedLocationIdRef.current === null && warehouseSetupRef.current === null)) {
        if (rejected) clearInventoryWarmScope(warmScopeKey);
        setLocations([]);
        setWarehouseSetup(null);
        setLocationsTruncated(false);
        setWarehouseNextCursor(null);
        prepareLocationChange(null);
        selectedLocationIdRef.current = null;
        setSelectedLocationId(null);
        localStorage.removeItem(selectedLocationStorageKey);
        setLocationError(true);
      } else {
        // A failed selector refresh cannot attest current warehouse admission.
        setLocationError(true);
      }
      toast.error(
        apiErrorMessage(error, t("inventoryShell.errors.locationsLoadFailed")),
      );
    } finally {
      if (locationAbortRef.current === controller) locationAbortRef.current = null;
      if (requestSeq === locationRequestSeq.current) setLoadingLocations(false);
    }
  }, [
    authFetch, canAny, globalAccessVerified, prepareLocationChange, selectedLocationStorageKey,
    t, warehouseCursor, warehouseSearch, warmScopeKey, companyId, principalId, backofficeUserId,
  ]);

  const fetchLocationsRef = useRef(fetchLocations);
  fetchLocationsRef.current = fetchLocations;
  const selectorRefreshDeferredRef = useRef(false);
  const canDiscoverInventory = canAny("inventory.read");
  const canDiscoverLocations = canAny("location.read");

  useEffect(() => {
    if (!globalAccessVerified) {
      if (!inventoryRouteActiveRef.current) {
        selectorRefreshDeferredRef.current = true;
      }
      return;
    }

    if (!canDiscoverInventory && !canDiscoverLocations) {
      locationRequestSeq.current += 1;
      locationAbortRef.current?.abort();
      clearInventoryWarmScope(warmScopeKey);
      setLocations([]);
      setWarehouseSetup(null);
      setLocationsTruncated(false);
      setWarehouseNextCursor(null);
      setLocationError(false);
      setLoadingLocations(false);

      if (accessDenied) {
        // The denial path already purged stock/cost evidence. Preserve only
        // the numeric selected-location state long enough to render the
        // explicit access-changed disclosure; do not reset "denied" to
        // "initial" through prepareLocationChange().
        return;
      }

      prepareLocationChange(null);
      selectedLocationIdRef.current = null;
      setSelectedLocationId(null);
      return;
    }

    if (!inventoryRouteActiveRef.current) {
      // A hidden, already-admitted workspace must not re-run selector reads
      // merely because Router changed callback identities. Genuine authority,
      // search or pagination changes are remembered and refreshed on return.
      selectorRefreshDeferredRef.current = true;
      return;
    }

    selectorRefreshDeferredRef.current = false;
    void fetchLocationsRef.current();
  }, [
    globalAccessVerified,
    canDiscoverInventory,
    canDiscoverLocations,
    warehouseCursor,
    warehouseSearch,
    warmScopeKey,
  ]);

  useEffect(() => {
    if (
      !returningToInventory ||
      !selectorRefreshDeferredRef.current ||
      !globalAccessVerified
    ) {
      return;
    }
    selectorRefreshDeferredRef.current = false;
    void fetchLocationsRef.current();
  }, [globalAccessVerified, returningToInventory]);

  const handleLocationChange = useCallback(
    (value: string) => {
      const nextId = Number(value);

      if (
        !Number.isInteger(nextId) ||
        !globalAccessVerified ||
        selectorAdmissionEpoch !== globalAdmissionEpoch.current ||
        serverVerifiedLocationId === null ||
        !locations.some((location) => location.id === nextId)
      ) {
        return;
      }

      prepareLocationChange(nextId);
      setServerVerifiedLocationId(nextId);
      setSelectorAdmissionEpoch(globalAdmissionEpoch.current);
      selectedLocationIdRef.current = nextId;
      setSelectedLocationId(nextId);
      localStorage.setItem(selectedLocationStorageKey, String(nextId));
    },
    [locations, globalAccessVerified, selectorAdmissionEpoch, serverVerifiedLocationId,
      prepareLocationChange, selectedLocationStorageKey]
  );
  useEffect(() => {
    if (routeLocation.pathname !== "/inventory") return;
    const intent = parseInventoryNavigationState(routeLocation.state);
    if (!intent) return;

    if (
      intent.locationId !== null &&
      intent.locationId !== selectedLocationId
    ) {
      if (!locations.some((location) => location.id === intent.locationId)) {
        return;
      }
      handleLocationChange(String(intent.locationId));
      if (selectedLocationIdRef.current !== intent.locationId) {
        return;
      }
    }

    setActiveTab(intent.tab);
    if (intent.kind === "owner-focus") {
      setArchiveOwnerFocus(intent);
      setBatchNavigationFocus(null);
    } else if (intent.kind === "batch-focus") {
      setArchiveOwnerFocus(null);
      setBatchNavigationFocus(intent);
    } else {
      setArchiveOwnerFocus(null);
      setBatchNavigationFocus(null);
    }

    routeNavigate(
      `${routeLocation.pathname}${routeLocation.search}`,
      { replace: true, state: null },
    );
  }, [
    handleLocationChange,
    locations,
    routeLocation.pathname,
    routeLocation.search,
    routeLocation.state,
    routeNavigate,
    selectedLocationId,
  ]);

  const handleOpenTransfers = useCallback(
    async (transfer?: BatchSpecialTransferResult) => {
      if (!transfer) {
        setTransferFocus(null);
        setActiveTab("transfers");
        return;
      }

      const relatedIds = [
        ...new Set([
          transfer.source_location_id,
          transfer.destination_location_id,
        ]),
      ].filter((id) => locations.some((location) => location.id === id));

      try {
        const capabilities = parseInventoryLocationCapabilities(
          await authFetch('/inventory/access/locations/capabilities', {
            method: 'POST',
            body: JSON.stringify({ location_ids: relatedIds }),
          }),
          relatedIds,
        );
        const canReadTransfer = (id: number) =>
          capabilities[id]?.includes('transfer.read') === true;
        const preferredLocationId =
          selectedLocationId !== null &&
          relatedIds.includes(selectedLocationId) &&
          canReadTransfer(selectedLocationId)
            ? selectedLocationId
            : relatedIds.find(canReadTransfer) ?? null;

        if (preferredLocationId === null) {
          toast.error(
            t("inventoryBatches.quantityActions.errors.followUnavailable", {
              reference: transfer.transfer_reference,
            }),
          );
          return;
        }

        if (preferredLocationId !== selectedLocationId) {
          handleLocationChange(String(preferredLocationId));
        }
        setTransferFocus({
          headerId: transfer.header_id,
          reference: transfer.transfer_reference,
        });
        setActiveTab("transfers");
      } catch (error: unknown) {
        toast.error(
          apiErrorMessage(
            error,
            t("inventoryBatches.quantityActions.errors.followUnavailable", {
              reference: transfer.transfer_reference,
            }),
          ),
        );
      }
    },
    [authFetch, handleLocationChange, locations, selectedLocationId, t],
  );
  const handleOpenReservationOwner = useCallback(
    (owner: ReservationOwner) => {
      routeNavigate("/dispatch", {
        state: createDispatchReservationFocusState({
          routeId: owner.route_id,
          transferId: owner.transfer_id,
          openCancel: owner.action === "FORCE_CANCEL_HANDSHAKE",
        }),
      });
    },
    [routeNavigate],
  );
  // A denied subordinate read revokes the same warehouse disclosure as a
  // denied list. Abort both readers so a late success cannot restore old costs.
  const rejectLiveStockEvidence = useCallback(() => {
    if (selectedLocationId === null) return;
    stockRequestSeq.current += 1;
    stockAbortRef.current?.abort();
    stockSummaryRequestSeq.current += 1;
    stockSummaryAbortRef.current?.abort();
    dropLiveStockWarmSnapshot(warmScopeKey, selectedLocationId);
    stockItemsRef.current = [];
    setStockItems([]);
    setStockPageReady(false);
    setStockNextCursor(null);
    setStockMatchingTotal(null);
    setStockTotal(null);
    setStockAlertCount(null);
    setLastSync(null);
    setLoadingStock(false);
    setDeniedAdmissionEpoch(liveAdmissionEpoch.current);
    setLiveReadPhase("denied");
  }, [selectedLocationId, warmScopeKey]);

  // ── fetchers ────────────────────────────────────────────────────────────────
  const fetchStock = useCallback(async () => {
    if (selectedLocationId === null || !canReadStock) return;
    if (!liveAuthorityVerified) return;

    const requestLocationId = selectedLocationId;
    const requestCursor = stockCursor;
    // Low/out-of-stock investigation must include zero-stock company SKUs,
    // even while the operator's ordinary view remains warehouse-only.
    const requestedView =
      stockState === "low_stock" || stockState === "out_of_stock" ||
      stockIndicators.includes("minimum_unset")
        ? "catalog"
        : stockView;
    const defaultView =
      !stockSearch &&
      stockState === "all" &&
      stockSort === "stock_first" &&
      stockView === "warehouse" &&
      stockIndicators.length === 0 &&
      stockFamilyId === null;

    const requestSeq = ++stockRequestSeq.current;
    const requestAdmissionEpoch = liveAdmissionEpoch.current;
    stockAbortRef.current?.abort();
    const requestController = new AbortController();
    stockAbortRef.current = requestController;
    setStockPageError(null);
    setLoadingStock(true);

    try {
      const params = new URLSearchParams({
        location_id: String(requestLocationId),
        limit: String(LIVE_STOCK_PAGE_SIZE),
        sort: stockSort,
        view: requestedView,
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
      if (requestAdmissionEpoch !== liveAdmissionEpoch.current) return;
      if (!requestStillAuthorized(warmScopeKey, requestLocationId)) return;
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
      setLiveReadPhase("fresh");
      setFreshPageAdmissionEpoch(requestAdmissionEpoch);
      if (defaultView && requestCursor === null) {
        patchLiveStockWarmSnapshot(
          warmScopeKey,
          requestLocationId,
          {
            hasPage: true,
            items: nextItems,
            nextCursor: data.next_cursor,
            lastSyncMs: syncedAt.getTime(),
            matchingTotal: data.total,
          },
        );
      }
      setStockNextCursor(data.next_cursor);

      setStockMatchingTotal(data.total);
      setLastSync(syncedAt);
    } catch (error: unknown) {
      if (requestSeq !== stockRequestSeq.current ||
          requestAdmissionEpoch !== liveAdmissionEpoch.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      if (!requestStillAuthorized(warmScopeKey, requestLocationId)) return;
      if ([401, 403, 404].includes(Number((error as { status?: unknown } | null)?.status))) {
        rejectLiveStockEvidence();
      } else {
        setLiveReadPhase("failed");
      }
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
    stockSort,
    stockView,
    stockIndicators,
    stockFamilyId,
    canReadStock,
    liveAuthorityVerified,
    t,
    warmScopeKey,
    rejectLiveStockEvidence,
  ]);

  const fetchStockSummary = useCallback(async () => {
    if (selectedLocationId === null || !canReadStock || !liveAuthorityVerified) {
      setStockTotal(null);
      setStockAlertCount(null);
      return;
    }

    const requestLocationId = selectedLocationId;
    setFreshSummaryAdmissionEpoch(null);
    const requestSeq = ++stockSummaryRequestSeq.current;
    const requestAdmissionEpoch = liveAdmissionEpoch.current;
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

      if (requestSeq !== stockSummaryRequestSeq.current ||
          requestAdmissionEpoch !== liveAdmissionEpoch.current ||
          !requestStillAuthorized(warmScopeKey, requestLocationId)) return;
      const data = parseLiveStockSummary(raw);
      setStockTotal(data.stock_total);
      setStockAlertCount(data.alert_count);
      setFreshSummaryAdmissionEpoch(requestAdmissionEpoch);
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
      if (requestSeq !== stockSummaryRequestSeq.current ||
          requestAdmissionEpoch !== liveAdmissionEpoch.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      if (!requestStillAuthorized(warmScopeKey, requestLocationId)) return;
      if ([401, 403, 404].includes(Number((error as { status?: unknown } | null)?.status))) {
        rejectLiveStockEvidence();
        return;
      }
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
    liveAuthorityVerified,
    t,
    warmScopeKey,
    rejectLiveStockEvidence,
  ]);

  const resetStockPagination = useCallback(() => {
    stockItemsRef.current = [];
    setStockItems([]);
    setStockPageReady(false);
    setStockCursor(null);
    setStockNextCursor(null);
    setStockMatchingTotal(null);
    setLiveReadPhase("initial");
  }, []);

  const refreshStock = useCallback(() => {
    stockRequestSeq.current += 1;
    stockAbortRef.current?.abort();
    stockAbortRef.current = null;
    stockSummaryRequestSeq.current += 1;
    stockSummaryAbortRef.current?.abort();
    stockSummaryAbortRef.current = null;
    // Explicit refresh must obey the same rule as returning to the page:
    // no stale row or total appears without a fresh authorized response.
    stockItemsRef.current = [];
    setStockItems([]);
    setStockPageReady(false);
    setStockNextCursor(null);
    setStockMatchingTotal(null);
    setStockTotal(null);
    setStockAlertCount(null);
    setLastSync(null);
    setFreshPageAdmissionEpoch(null);
    setFreshSummaryAdmissionEpoch(null);
    setStockCursor(null);
    setStockPageError(null);
    setStockSummaryError(null);
    setLoadingStock(selectedLocationId !== null);
    setLiveReadPhase("initial");
    setStockRefreshKey((value) => value + 1);
  }, [selectedLocationId]);

  const retryStockPage = useCallback(() => {
    if (selectedLocationId === null || loadingStock) return;
    setStockPageError(null);
    setStockPageRetryKey((value) => value + 1);
  }, [loadingStock, selectedLocationId]);

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

  const handleStockViewChange = useCallback(
    (value: LiveStockView) => {
      resetStockPagination();
      setStockView(value);
    },
    [resetStockPagination],
  );

  const handleStockSortChange = useCallback(
    (value: LiveStockSort) => {
      resetStockPagination();
      setStockSort(value);
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
      setAuditLockReference(null);
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
      setAuditLockReference(null);
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
      const data = parseWarehouseStatusPayload(raw);
      const locked = data.status === "AUDIT_LOCK";
      setAuditLockState(locked);
      setAuditLockReference(locked ? data.stocktake_reference : null);
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
      setAuditLockReference(null);
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

  // ── on mount / meaningful read triggers ──────────────────────────────────
  const fetchStatusRef = useRef(fetchStatus);
  fetchStatusRef.current = fetchStatus;
  const fetchStockRef = useRef(fetchStock);
  fetchStockRef.current = fetchStock;
  const fetchStockSummaryRef = useRef(fetchStockSummary);
  fetchStockSummaryRef.current = fetchStockSummary;

  useEffect(() => {
    if (!inventoryRouteActiveRef.current) return;
    void fetchStatusRef.current();
  }, [
    selectedLocationId,
    canReadStatus,
    locationAccess.isPending,
  ]);

  useEffect(() => {
    return () => {
      locationRequestSeq.current += 1;
      locationAbortRef.current?.abort();
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
    if (
      !inventoryRouteActiveRef.current ||
      activeTab !== "live" ||
      selectedLocationId === null
    ) {
      return;
    }
    void fetchStockRef.current();
  }, [
    activeTab,
    selectedLocationId,
    stockCursor,
    stockSearch,
    stockState,
    stockSort,
    stockView,
    stockIndicators,
    stockFamilyId,
    canReadStock,
    liveAuthorityVerified,
    stockRefreshKey,
    stockPageRetryKey,
  ]);

  useEffect(() => {
    if (
      !inventoryRouteActiveRef.current ||
      activeTab !== "live" ||
      selectedLocationId === null
    ) {
      return;
    }
    void fetchStockSummaryRef.current();
  }, [
    activeTab,
    selectedLocationId,
    canReadStock,
    liveAuthorityVerified,
    stockRefreshKey,
  ]);

  useEffect(() => {
    if (!returningToInventory) return;

    // Same-session re-entry keeps the verified rows mounted, then refreshes
    // the first page and summary in the background. This preserves freshness
    // without a blank/skeleton transition. A stale selector/authority takes
    // the fail-closed path above instead.
    void fetchStatusRef.current();
    if (
      activeTab === "live" &&
      selectedLocationId !== null &&
      stockPageReady &&
      liveAuthorityVerified
    ) {
      setStockCursor(null);
      setStockRefreshKey((value) => value + 1);
    }
  }, [returningToInventory]);

  const requiresFirstWarehouse =
    !loadingLocations &&
    !locationError &&
    locations.length === 0 &&
    warehouseSetup?.warehouse_ready === false &&
    warehouseSetup.can_create;

  useEffect(() => {
    if (requiresFirstWarehouse && activeTab !== "warehouses") {
      setActiveTab("warehouses");
    }
  }, [activeTab, requiresFirstWarehouse]);

  const liveVisible = liveAuthorityVerified && !accessDenied && !locationError &&
    liveReadPhase !== "denied";
  const livePageFresh =
    liveReadPhase === "fresh" &&
    freshPageAdmissionEpoch === liveAdmissionEpoch.current;
  const liveSummaryFresh = liveVisible && !stockSummaryError &&
    freshSummaryAdmissionEpoch === liveAdmissionEpoch.current;
  const liveDisclosureKey = accessDenied || liveReadPhase === "denied"
    ? "accessChanged"
    : access.isError || locationAccess.isError
      ? "accessRefreshFailed"
    : !liveVisible
      ? "loadingVerification"
      : liveReadPhase === "failed" || stockPageError || stockSummaryError
        ? "refreshFailed"
        : livePageFresh && liveSummaryFresh
          ? "verifiedFresh"
          : "loadingVerification";

  if (archiveOwnerFocus) {
    return <ArchiveOwnerWorkspace intent={archiveOwnerFocus} onClose={() => setArchiveOwnerFocus(null)}
      onOpenTransfers={handleOpenTransfers} onOpenReservationOwner={handleOpenReservationOwner}
      onInventoryChanged={async () => {
        setStockRefreshKey((value) => value + 1);
        setLedgerRefreshKey((value) => value + 1);
        await fetchStatus();
      }} />;
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
    <div
      data-live-view={activeTab === "live"}
      data-inbound-view={activeTab === "inbound"}
      className="inventory-workspace flex flex-col gap-4 w-full h-full flex-1 min-h-0"
    >

      <InventoryTopDock
        loading={access.isPending || (selectedLocationId !== null && locationAccess.isPending)}
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
          if (!isTabId(id)) return;
          if (requiresFirstWarehouse && id !== "warehouses") {
            toast.info(t("inventoryShell.createWarehouseFirstNotice"));
            return;
          }
          setActiveTab(id);
        }}
      />

      {activeTab !== "live" && activeTab !== "warehouses" && activeTab !== "inbound" && activeTab !== "transfers" && (
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
                <span className="text-sm font-black" title={t("inventoryShell.summaryVariantCountHint")}>
                  {t("inventoryShell.liveStockCount")}{" "}
                  <span
                    className="inventory-shared-context-count"
                    aria-label={!livePageFresh || !liveSummaryFresh || stockTotal === null
                      ? t("inventoryShell.countNotVerified")
                      : undefined}
                  >
                    {!livePageFresh || !liveSummaryFresh || stockTotal === null
                      ? "—"
                      : new Intl.NumberFormat(
                          locale,
                          { numberingSystem: "latn" },
                        ).format(stockTotal)}
                  </span>
                  <span className="sr-only">{t("inventoryShell.summaryVariantCountHint")}</span>
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
                  {liveVisible && livePageFresh && lastSync
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
                    : <span aria-label={t("inventoryShell.fetchTimeUnknown")}>—</span>}
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

      {(locationsTruncated || warehouseCursorTrail.length > 1 || warehouseSearchInput.length > 0) && (
        <div className="inventory-alert-banner flex flex-wrap items-center gap-2 px-4 py-2 text-sm font-bold">
          <label className="flex min-w-[180px] flex-1 items-center gap-2">
            <span>{t("inventoryShell.warehouseSearch")}</span>
            <input
              type="search"
              value={warehouseSearchInput}
              onChange={(event) => setWarehouseSearchInput(event.target.value)}
              maxLength={100}
              aria-label={t("inventoryShell.warehouseSearch")}
              className="min-w-0 flex-1 rounded-lg border px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            disabled={loadingLocations || warehouseCursorTrail.length <= 1}
            onClick={() => setWarehouseCursorTrail((trail) => trail.slice(0, -1))}
            className="rounded-lg border px-2 py-1 disabled:opacity-50"
          >
            {t("inventoryShell.previousWarehouses")}
          </button>
          <button
            type="button"
            disabled={loadingLocations || !warehouseNextCursor}
            onClick={() => {
              if (warehouseNextCursor) {
                setWarehouseCursorTrail((trail) => [...trail, warehouseNextCursor]);
              }
            }}
            className="rounded-lg border px-2 py-1 disabled:opacity-50"
          >
            {t("inventoryShell.nextWarehouses")}
          </button>
          {locationsTruncated ? (
            <span role="status">{t("inventoryShell.locationsTruncated")}</span>
          ) : null}
        </div>
      )}
      {locationAccess.isError && selectedLocationId !== null && (
        <p role="alert" className="inventory-alert-banner flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm font-bold">
          {t(`inventoryShell.${accessDenied ? "accessChanged" : "accessRefreshFailed"}`)}
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
        {((selectedLocationId === null && loadingLocations) ||
          (selectedLocationId !== null && activeTab === "live" && !liveVisible && !accessDenied && !locationAccess.isError) ||
          (selectedLocationId !== null && activeTab !== "live" &&
            activeTab !== "transfers" && activeTab !== "warehouses" &&
            activeTab !== "permissions" && locationAccess.isPending)) && (
          <InventoryPendingSurface label={t("common.loading")} live={activeTab === "live"} />
        )}
        {selectedLocationId === null && liveReadPhase === "denied" && activeTab === "live" && (
          <div
            role="alert"
            aria-live="assertive"
            data-live-authority="accessChanged"
            className="inventory-alert-banner px-4 py-2 text-sm font-semibold"
          >
            {t("inventoryShell.accessChanged")}
            <button
              type="button"
              className="ms-3 rounded-lg border px-2 py-1"
              onClick={() => {
                void access.refetch();
                void fetchLocations();
              }}
            >
              {t("inventoryShell.refreshAccess")}
            </button>
          </div>
        )}
        {selectedLocationId === null && liveReadPhase !== "denied" && !loadingLocations && activeTab !== "warehouses" && activeTab !== "permissions" && (
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

        {activeTab === "live" && selectedLocationId !== null &&
          liveDisclosureKey !== "verifiedFresh" && liveDisclosureKey !== "loadingVerification" && (
          <div
            role={accessDenied && !locationAccess.isError ? "alert" : "status"}
            aria-live={accessDenied || liveReadPhase === "denied" ? "assertive" : "polite"}
            dir={i18n.dir()}
            data-live-authority={liveDisclosureKey}
            className="inventory-alert-banner px-4 py-2 text-sm font-semibold"
          >
            {t(`inventoryShell.${liveDisclosureKey}`)}
            {(liveDisclosureKey === "refreshFailed" ||
              liveDisclosureKey === "accessRefreshFailed") && (
              <button type="button" onClick={() => {
                if (liveDisclosureKey === "accessRefreshFailed") {
                  void access.refetch();
                  void locationAccess.refetch();
                  void fetchLocations();
                } else if (stockPageError) {
                  retryStockPage();
                } else if (stockSummaryError) {
                  void fetchStockSummary();
                } else {
                  retryStockPage();
                }
              }}
                className="ms-3 rounded-lg border px-2 py-1"
                aria-label={t("inventoryShell.retry")}>
                {t("inventoryShell.retry")}
              </button>
            )}
          </div>
        )}
        {activeTab === "live" && selectedLocationId !== null &&
          liveVisible && tabAllowed("live") && (
          <Tab1LiveStock
            locationId={selectedLocationId}
            locations={locations}
            stockTotal={liveSummaryFresh ? stockTotal : null}
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
            onRetryPage={retryStockPage}
            onRetrySummary={() => { void fetchStockSummary(); }}
            onReadDenied={rejectLiveStockEvidence}
            alertCount={liveSummaryFresh ? stockAlertCount : null}
            matchingTotal={stockMatchingTotal}
            hasMore={!!stockNextCursor}
            stockState={stockState}
            sort={stockSort}
            onSortChange={handleStockSortChange}
            view={stockView}
            onViewChange={handleStockViewChange}
            indicators={stockIndicators}
            familyId={stockFamilyId}
            onSearchChange={handleStockSearchChange}
            onStockStateChange={handleStockStateChange}
            onIndicatorsChange={handleStockIndicatorsChange}
            onFamilyChange={handleStockFamilyChange}
            onLoadMore={handleStockLoadMore}
          />
        )}
        {(batchTabVisited || activeTab === "batches") &&
          !locationAccess.isPending &&
          tabAllowed("batches") &&
          selectedLocationId !== null && (
          <div
            hidden={activeTab !== "batches"}
            className={activeTab === "batches" ? "contents" : "hidden"}
            data-inventory-tab-cache="batches"
          >
            <TabBatches
              key={`${warmScopeKey ?? "invalid"}:${selectedLocationId}`}
              active={activeTab === "batches"}
              refreshKey={batchRefreshKey}
              locationId={selectedLocationId}
              focus={batchNavigationFocus}
              onFocusConsumed={() => setBatchNavigationFocus(null)}
              onOpenTransfers={handleOpenTransfers}
              onOpenReservationOwner={handleOpenReservationOwner}
              onInventoryChanged={async () => {
                refreshStock();
                setLedgerRefreshKey((value) => value + 1);
              }}
            />
          </div>
        )}
        {!locationAccess.isPending && activeTab === "inbound" && tabAllowed("inbound") && selectedLocationId !== null && locationAccess.data && (
          <Tab2Inbound
            key={`${locationAccess.data.company_id}:${locationAccess.data.backoffice_user_id}:${selectedLocationId}`}
            companyId={locationAccess.data.company_id}
            actorId={locationAccess.data.backoffice_user_id}
            locationId={selectedLocationId}
            locations={locations}
            onLocationChange={handleLocationChange}
            isAuditLocked={displayAuditLocked && auditLockReference !== null}
            auditLockReference={auditLockReference}
            authenticatedFetch={authFetch}
            onSuccess={async () => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
              setBatchRefreshKey((value) => value + 1);
            }}
          />
        )}
        {!locationAccess.isPending && activeTab === "stocktake" && tabAllowed("stocktake") && selectedLocationId !== null && locationAccess.data && (
          <Tab3Stocktake
            key={`${locationAccess.data.company_id}:${locationAccess.data.backoffice_user_id}:${selectedLocationId}`}
            locationId={selectedLocationId} // +++ سحق ملاحظة P1: تمرير الموقع للمحرك המوحد +++
            companyId={`${locationAccess.data.company_id}:${locationAccess.data.backoffice_user_id}`}
            isAuditLocked={effectiveAuditLocked}
            authenticatedFetch={authFetch}
            onStocktakeChanged={async () => {
              refreshStock();
              setLedgerRefreshKey((value) => value + 1);
              setBatchRefreshKey((value) => value + 1);
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

        {activeTab === "transfers" && tabAllowed("transfers") && (
          <TabTransfers
            focus={transferFocus}
            onFocusConsumed={() => setTransferFocus(null)}
            onInventoryChanged={async () => {
              setStockRefreshKey((value) => value + 1);
              setLedgerRefreshKey((value) => value + 1);
              setBatchRefreshKey((value) => value + 1);
              if (selectedLocationId !== null) await fetchStatus();
            }}
          />
        )}

        {activeTab === "permissions" && access.isCompanyOwner && <TabInventoryAccess />}
        {activeTab === "warehouses" && tabAllowed("warehouses") && (
          <TabWarehouseLocations
            selectedLocationId={selectedLocationId}
            onLocationsChanged={fetchLocations}
            onMinimumApplied={refreshStock}
          />
        )}
      </div>
    </div>
  );
}
