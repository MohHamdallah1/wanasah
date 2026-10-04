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

export type InventoryWholeProductIssueIntent = {
  version: 1;
  kind: "quality-issue";
  tab: "batches";
  variantId: number;
  productName: string;
  locationId: number | null;
};

export type InventoryNavigationIntent =
  | InventoryTabIntent
  | InventoryBatchFocusIntent
  | InventoryWholeProductIssueIntent;

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

export function createInventoryWholeProductIssueNavigationState({
  variantId,
  productName,
  locationId = null,
}: {
  variantId: number;
  productName: string;
  locationId?: number | null;
}): InventoryNavigationState {
  return {
    inventoryNavigation: {
      version: 1,
      kind: "quality-issue",
      tab: "batches",
      variantId,
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
    (row.kind === "batch-focus" || row.kind === "quality-issue") &&
    row.tab === "batches" &&
    typeof row.variantId === "number" &&
    Number.isSafeInteger(row.variantId) &&
    row.variantId > 0 &&
    typeof row.productName === "string" &&
    row.productName.trim().length > 0 &&
    row.productName.length <= 200
  ) {
    if (row.kind === "quality-issue") {
      return {
        version: 1,
        kind: "quality-issue",
        tab: "batches",
        variantId: row.variantId,
        productName: row.productName.trim(),
        locationId: row.locationId as number | null,
      };
    }
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
