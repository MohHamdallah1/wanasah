export type InventoryTargetTab =
  | "live"
  | "batches"
  | "inbound"
  | "transfers"
  | "ledger"
  | "stocktake"
  | "warehouses"
  | "permissions";

export type InventoryTabIntent = {
  version: 1;
  kind: "tab";
  tab: InventoryTargetTab;
  locationId: number | null;
};

export type InventoryBatchFocusIntent = {
  version: 1;
  kind: "batch-focus";
  tab: "batches";
  variantId: number;
  batchId: number | null;
  productName: string;
  locationId: number | null;
};

export type InventoryOwnerFocusIntent = {
  version: 1;
  kind: "owner-focus";
  tab: "batches" | "transfers" | "stocktake" | "warehouses";
  flow: "batch" | "transfer" | "stocktake" | "product-location";
  variantId: number;
  operationId: number;
  locationId: number;
  reference: string;
};

export type InventoryNavigationIntent =
  | InventoryTabIntent
  | InventoryBatchFocusIntent
  | InventoryOwnerFocusIntent;

const OWNER_TABS = {
  batch: "batches",
  transfer: "transfers",
  stocktake: "stocktake",
  "product-location": "warehouses",
} as const;

export function createInventoryOwnerFocusState(
  input: Omit<InventoryOwnerFocusIntent, "version" | "kind" | "tab">,
): InventoryNavigationState {
  return {
    inventoryNavigation: {
      ...input,
      version: 1,
      kind: "owner-focus",
      tab: OWNER_TABS[input.flow],
    },
  };
}

export type InventoryNavigationState = {
  inventoryNavigation: InventoryNavigationIntent;
};

const TABS: readonly InventoryTargetTab[] = [
  "live",
  "batches",
  "inbound",
  "transfers",
  "ledger",
  "stocktake",
  "warehouses",
  "permissions",
];

const validLocationId = (value: unknown): value is number | null =>
  value === null ||
  (typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value > 0);

export function createInventoryTabNavigationState(
  tab: InventoryTargetTab,
  locationId: number | null = null,
): InventoryNavigationState {
  return {
    inventoryNavigation: {
      version: 1,
      kind: "tab",
      tab,
      locationId,
    },
  };
}

export function createInventoryBatchFocusNavigationState({
  variantId,
  batchId = null,
  productName,
  locationId = null,
}: {
  variantId: number;
  batchId?: number | null;
  productName: string;
  locationId?: number | null;
}): InventoryNavigationState {
  return {
    inventoryNavigation: {
      version: 1,
      kind: "batch-focus",
      tab: "batches",
      variantId,
      batchId,
      productName,
      locationId,
    },
  };
}

export function parseInventoryNavigationState(
  value: unknown,
): InventoryNavigationIntent | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const envelope = value as Record<string, unknown>;
  const raw = envelope.inventoryNavigation;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return null;
  }
  const row = raw as Record<string, unknown>;
  if (
    row.version !== 1 ||
    typeof row.tab !== "string" ||
    !TABS.includes(row.tab as InventoryTargetTab) ||
    !validLocationId(row.locationId)
  ) {
    return null;
  }

  if (row.kind === "tab") {
    return {
      version: 1,
      kind: "tab",
      tab: row.tab as InventoryTargetTab,
      locationId: row.locationId as number | null,
    };
  }

  if (
    row.kind === "owner-focus" &&
    typeof row.flow === "string" &&
    Object.prototype.hasOwnProperty.call(OWNER_TABS, row.flow)
  ) {
    const flow = row.flow as InventoryOwnerFocusIntent["flow"];
    if (
      row.tab !== OWNER_TABS[flow] ||
      row.locationId === null ||
      !validLocationId(row.variantId) || row.variantId === null ||
      !validLocationId(row.operationId) || row.operationId === null ||
      typeof row.reference !== "string" || row.reference.length > 100
    ) return null;
    return {
      version: 1,
      kind: "owner-focus",
      tab: OWNER_TABS[flow],
      flow,
      variantId: row.variantId,
      operationId: row.operationId,
      locationId: row.locationId as number,
      reference: row.reference,
    };
  }

  if (
    row.kind === "batch-focus" &&
    row.tab === "batches" &&
    typeof row.variantId === "number" &&
    Number.isSafeInteger(row.variantId) &&
    row.variantId > 0 &&
    typeof row.productName === "string" &&
    row.productName.trim().length > 0 &&
    row.productName.length <= 200
  ) {
    if (!validLocationId(row.batchId)) return null;
    return {
      version: 1,
      kind: "batch-focus",
      tab: "batches",
      variantId: row.variantId,
      batchId: row.batchId as number | null,
      productName: row.productName.trim(),
      locationId: row.locationId as number | null,
    };
  }

  return null;
}
