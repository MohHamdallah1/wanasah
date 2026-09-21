import type { WarehouseProduct } from "./liveStock/contracts";

export interface InventoryWarmLocation {
  id: number;
  name: string;
  code: string;
}

export interface InventoryWarmSetup {
  warehouse_ready: boolean;
  active_warehouse_count: number;
  accessible_warehouse_count: number;
  can_create: boolean;
}

export interface InventoryShellWarmSnapshot {
  locations: InventoryWarmLocation[];
  setup: InventoryWarmSetup;
  locationsTruncated: boolean;
  selectedLocationId: number | null;
}

export interface LiveStockWarmSnapshot {
  hasPage: boolean;
  items: WarehouseProduct[];
  nextCursor: string | null;
  matchingTotal: number | null;
  hasSummary: boolean;
  stockTotal: number | null;
  alertCount: number | null;
  lastSyncMs: number | null;
  hasStatus: boolean;
  auditLocked: boolean | null;
}

type LiveStockWarmPatch = Partial<
  Omit<LiveStockWarmSnapshot, "items">
> & {
  items?: WarehouseProduct[];
};

interface InventoryScopeWarmCache {
  shell: InventoryShellWarmSnapshot | null;
  liveByLocation: Map<number, LiveStockWarmSnapshot>;
}

const MAX_SCOPES = 8;
const MAX_LOCATIONS_PER_SCOPE = 64;
const CACHE = new Map<string, InventoryScopeWarmCache>();

const emptyLiveSnapshot = (): LiveStockWarmSnapshot => ({
  hasPage: false,
  items: [],
  nextCursor: null,
  matchingTotal: null,
  hasSummary: false,
  stockTotal: null,
  alertCount: null,
  lastSyncMs: null,
  hasStatus: false,
  auditLocked: null,
});

const cloneShell = (
  value: InventoryShellWarmSnapshot,
): InventoryShellWarmSnapshot => ({
  ...value,
  locations: value.locations.map((location) => ({ ...location })),
});

const cloneLive = (
  value: LiveStockWarmSnapshot,
): LiveStockWarmSnapshot => ({
  ...value,
  items: [...value.items],
});

const touchScope = (
  scopeKey: string,
): InventoryScopeWarmCache => {
  const existing = CACHE.get(scopeKey);
  if (existing) {
    CACHE.delete(scopeKey);
    CACHE.set(scopeKey, existing);
    return existing;
  }

  const created: InventoryScopeWarmCache = {
    shell: null,
    liveByLocation: new Map(),
  };
  CACHE.set(scopeKey, created);

  while (CACHE.size > MAX_SCOPES) {
    const oldest = CACHE.keys().next().value;
    if (typeof oldest !== "string") break;
    CACHE.delete(oldest);
  }
  return created;
};

export const inventoryWarmScopeKey = (
  companyId: string,
  driverId: string,
): string | null => {
  const company = companyId.trim();
  const driver = driverId.trim();
  if (!company || !driver) return null;
  return `${company}:${driver}`;
};

export const readInventoryShellWarmSnapshot = (
  scopeKey: string | null,
): InventoryShellWarmSnapshot | null => {
  if (!scopeKey) return null;
  const entry = CACHE.get(scopeKey);
  if (!entry?.shell) return null;
  touchScope(scopeKey);
  return cloneShell(entry.shell);
};

export const writeInventoryShellWarmSnapshot = (
  scopeKey: string | null,
  snapshot: InventoryShellWarmSnapshot,
): void => {
  if (!scopeKey) return;
  const entry = touchScope(scopeKey);
  entry.shell = cloneShell(snapshot);
};

export const readLiveStockWarmSnapshot = (
  scopeKey: string | null,
  locationId: number | null,
): LiveStockWarmSnapshot | null => {
  if (!scopeKey || locationId === null) return null;
  const entry = CACHE.get(scopeKey);
  const snapshot = entry?.liveByLocation.get(locationId);
  if (!snapshot) return null;
  touchScope(scopeKey);
  return cloneLive(snapshot);
};

export const patchLiveStockWarmSnapshot = (
  scopeKey: string | null,
  locationId: number,
  patch: LiveStockWarmPatch,
): LiveStockWarmSnapshot | null => {
  if (!scopeKey || !Number.isSafeInteger(locationId) || locationId <= 0) {
    return null;
  }

  const entry = touchScope(scopeKey);
  const current =
    entry.liveByLocation.get(locationId) ?? emptyLiveSnapshot();
  const next: LiveStockWarmSnapshot = {
    ...current,
    ...patch,
    items:
      patch.items === undefined
        ? current.items
        : [...patch.items],
  };

  entry.liveByLocation.delete(locationId);
  entry.liveByLocation.set(locationId, next);

  while (entry.liveByLocation.size > MAX_LOCATIONS_PER_SCOPE) {
    const oldest = entry.liveByLocation.keys().next().value;
    if (typeof oldest !== "number") break;
    entry.liveByLocation.delete(oldest);
  }

  return cloneLive(next);
};

export const clearInventoryWarmScope = (
  scopeKey: string | null,
): void => {
  if (!scopeKey) return;
  CACHE.delete(scopeKey);
};
