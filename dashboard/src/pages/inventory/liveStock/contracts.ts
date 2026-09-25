import { parseQuantity, type Quantity } from "../quantity";

type CodedContractError = Error & { code: string };

const contractError = (code: string): never => {
  const error = new Error(code) as CodedContractError;
  error.code = code;
  throw error;
};

const record = (
  value: unknown,
  code: string,
): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return contractError(code);
  }
  return value as Record<string, unknown>;
};

const int = (
  value: unknown,
  code: string,
  min = 0,
): number => {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < min
  ) {
    return contractError(code);
  }
  return value;
};

const str = (
  value: unknown,
  code: string,
  max = 200,
): string => {
  if (
    typeof value !== "string" ||
    !value.trim() ||
    value.length > max
  ) {
    return contractError(code);
  }
  return value;
};

const nullableStr = (
  value: unknown,
  code: string,
  max = 200,
): string | null =>
  value === null ? null : str(value, code, max);

const isoDateOrNull = (
  value: unknown,
  code: string,
): string | null => {
  if (value === null) return null;
  const text = str(value, code, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return contractError(code);
  }
  return text;
};

const moneyOrNull = (
  value: unknown,
  code: string,
): string | null => {
  if (value === null) return null;
  const text = str(value, code, 64);
  if (!/^\d+(?:\.\d{1,6})?$/.test(text)) {
    return contractError(code);
  }
  return text;
};

const nullableCount = (
  value: unknown,
  code: string,
): number | null =>
  value === null ? null : int(value, code);

export type LiveStockStockState =
  | "all"
  | "on_hand"
  | "sellable"
  | "out_of_stock"
  | "low_stock";

export type LiveStockIndicator =
  | "reserved"
  | "unavailable"
  | "damaged"
  | "recalled"
  | "vehicle"
  | "minimum_unset";

export type LiveStockSort = "name_asc" | "name_desc";

export interface LiveStockFamilyOption {
  id: number;
  name: string;
  code: string;
}

export interface WarehouseProduct {
  id: number;
  name: string;
  sku: string | null;
  product_id: number;
  family_name: string;

  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;

  display_uom_id: number;
  display_uom_code: string;
  display_uom_name: string;
  display_factor_to_base: Quantity;

  currency_code: string;
  average_cost_display: string | null;
  last_purchase_cost: string | null;
  last_purchase_uom_code: string | null;
  last_purchase_date: string | null;

  quantity_scale: number;
  quantity_step: Quantity;

  on_hand_quantity: Quantity;
  reserved_quantity: Quantity;
  available_for_sale_quantity: Quantity;
  unavailable_quantity: Quantity;
  vehicle_quantity: Quantity;
  recalled_quantity: Quantity;

  // Backward-compatible response fields kept while older consumers migrate.
  available_quantity: Quantity;
  blocked_quantity: Quantity;
  total_quantity: Quantity;
  damaged_quantity: Quantity;
  minimum_quantity: Quantity;
}

export interface WarehouseBatchProductOption {
  id: number;
  name: string;
  sku: string | null;
  family_name: string;
  base_uom_code: string;
  display_uom_code: string;
  display_factor_to_base: Quantity;
  currency_code: string;
}

export interface WarehouseBatchProductCursorPage {
  items: WarehouseBatchProductOption[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface WarehouseInventoryCursorPage {
  items: WarehouseProduct[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
  alert_count: number | null;
  alert_samples: string[];
}

export interface WarehouseInventorySummary {
  stock_total: number;
  alert_count: number;
}

export interface WarehouseInventoryAlertSummary {
  alert_count: number;
}

export type MinimumStockScope = "ALL" | "FAMILY" | "PRODUCT";
export type MinimumStockApplyMode = "ONLY_UNSET" | "OVERWRITE";

export interface BulkMinimumStockPlan {
  location_id: number;
  scope: MinimumStockScope;
  family_ids: number[];
  product_variant_ids: number[];
  minimum_quantity: Quantity;
  unit_mode: "DISPLAY_UOM_PER_PRODUCT";
  apply_mode: MinimumStockApplyMode;
  matched_count: number;
  affected_count: number;
  skipped_existing_count: number;
  inactive_conflict_count: number;
  target_conflict_count: number;
  invalid_quantity_count: number;
  conflict_samples: {
    inactive: number[];
    target: number[];
    invalid_quantity: number[];
  };
  changed?: boolean;
}

export function parseBulkMinimumStockPlan(raw: unknown): BulkMinimumStockPlan {
  const code = "STOCK_MINIMUM_BULK_RESPONSE_INVALID";
  const row = record(raw, code);
  const scope = str(row.scope, code, 20);
  const applyMode = str(row.apply_mode, code, 20);
  const unitMode = str(row.unit_mode, code, 40);

  if (!["ALL", "FAMILY", "PRODUCT"].includes(scope)) {
    return contractError(code);
  }
  if (!["ONLY_UNSET", "OVERWRITE"].includes(applyMode)) {
    return contractError(code);
  }
  if (unitMode !== "DISPLAY_UOM_PER_PRODUCT") {
    return contractError(code);
  }

  const samples = record(row.conflict_samples, code);
  const parseIds = (value: unknown): number[] => {
    if (!Array.isArray(value) || value.length > 10) {
      return contractError(code);
    }
    return value.map((item) => int(item, code, 1));
  };

  const parseSelectionIds = (value: unknown): number[] => {
    if (!Array.isArray(value) || value.length > 200) {
      return contractError(code);
    }
    const ids = value.map((item) => int(item, code, 1));
    if (new Set(ids).size !== ids.length) {
      return contractError(code);
    }
    return ids;
  };

  return {
    location_id: int(row.location_id, code, 1),
    scope: scope as MinimumStockScope,
    family_ids: parseSelectionIds(row.family_ids),
    product_variant_ids: parseSelectionIds(row.product_variant_ids),
    minimum_quantity: parseQuantity(
      row.minimum_quantity,
      "minimum_quantity",
      { allowZero: true },
    ),
    unit_mode: "DISPLAY_UOM_PER_PRODUCT",
    apply_mode: applyMode as MinimumStockApplyMode,
    matched_count: int(row.matched_count, code),
    affected_count: int(row.affected_count, code),
    skipped_existing_count: int(row.skipped_existing_count, code),
    inactive_conflict_count: int(row.inactive_conflict_count, code),
    target_conflict_count: int(row.target_conflict_count, code),
    invalid_quantity_count: int(row.invalid_quantity_count, code),
    conflict_samples: {
      inactive: parseIds(samples.inactive),
      target: parseIds(samples.target),
      invalid_quantity: parseIds(samples.invalid_quantity),
    },
    changed:
      row.changed === undefined
        ? undefined
        : typeof row.changed === "boolean"
          ? row.changed
          : contractError(code),
  };
}

export interface WarehouseBatchInventoryItem {
  batch_id: number;
  batch_number: string;
  production_date: string | null;
  expiry_date: string | null;
  disposition: "RELEASED" | "QUARANTINED" | "BLOCKED" | "RECALLED";
  days_to_expiry: number | null;

  on_hand_quantity: Quantity;
  reserved_quantity: Quantity;
  available_for_sale_quantity: Quantity;
  unavailable_quantity: Quantity;
  restricted_quantity: Quantity;

  quarantined_quantity: Quantity;
  blocked_quantity: Quantity;
  recalled_quantity: Quantity;
  damaged_quantity: Quantity;
  disposal_pending_quantity: Quantity;

  latest_purchase_cost: string | null;
  latest_purchase_uom_code: string | null;
  latest_purchase_date: string | null;
  purchase_event_count: number;
}

export interface WarehouseBatchDetailResponse {
  location_id: number;
  product_variant_id: number;
  currency_code: string;
  batches: WarehouseBatchInventoryItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export function parseLiveStockPage(
  raw: unknown,
): WarehouseInventoryCursorPage {
  const code = "LIVE_STOCK_RESPONSE_INVALID";
  const page = record(raw, code);
  if (
    !Array.isArray(page.items) ||
    page.items.length > 200 ||
    typeof page.has_more !== "boolean"
  ) {
    return contractError(code);
  }

  const ids = new Set<number>();
  const items = page.items.map((rawItem) => {
    const row = record(rawItem, code);
    const id = int(row.id, code, 1);
    if (ids.has(id)) return contractError(code);
    ids.add(id);

    const scale = int(row.quantity_scale, code);
    if (scale > 6) return contractError(code);

    const lastPurchaseCost = moneyOrNull(row.last_purchase_cost, code);
    const lastPurchaseUomCode = nullableStr(
      row.last_purchase_uom_code,
      code,
      20,
    );
    const lastPurchaseDate = isoDateOrNull(
      row.last_purchase_date,
      code,
    );
    if (
      (lastPurchaseCost === null) !==
        (lastPurchaseUomCode === null) ||
      (lastPurchaseCost === null) !==
        (lastPurchaseDate === null)
    ) {
      return contractError(code);
    }

    return {
      id,
      name: str(row.name, code),
      sku: nullableStr(row.sku, code, 100),
      product_id: int(row.product_id, code, 1),
      family_name: str(row.family_name, code, 150),
      base_uom_id: int(row.base_uom_id, code, 1),
      base_uom_code: str(row.base_uom_code, code, 20),
      base_uom_name: str(row.base_uom_name, code, 50),
      display_uom_id: int(row.display_uom_id, code, 1),
      display_uom_code: str(row.display_uom_code, code, 20),
      display_uom_name: str(row.display_uom_name, code, 50),
      display_factor_to_base: parseQuantity(
        row.display_factor_to_base,
        "display_factor_to_base",
      ),
      currency_code: str(row.currency_code, code, 10),
      average_cost_display: moneyOrNull(
        row.average_cost_display,
        code,
      ),
      last_purchase_cost: lastPurchaseCost,
      last_purchase_uom_code: lastPurchaseUomCode,
      last_purchase_date: lastPurchaseDate,
      quantity_scale: scale,
      quantity_step: parseQuantity(
        row.quantity_step,
        "quantity_step",
      ),
      on_hand_quantity: parseQuantity(
        row.on_hand_quantity,
        "on_hand_quantity",
        { allowZero: true },
      ),
      reserved_quantity: parseQuantity(
        row.reserved_quantity,
        "reserved_quantity",
        { allowZero: true },
      ),
      available_for_sale_quantity: parseQuantity(
        row.available_for_sale_quantity,
        "available_for_sale_quantity",
        { allowZero: true },
      ),
      unavailable_quantity: parseQuantity(
        row.unavailable_quantity,
        "unavailable_quantity",
        { allowZero: true },
      ),
      vehicle_quantity: parseQuantity(
        row.vehicle_quantity,
        "vehicle_quantity",
        { allowZero: true },
      ),
      recalled_quantity: parseQuantity(
        row.recalled_quantity,
        "recalled_quantity",
        { allowZero: true },
      ),
      available_quantity: parseQuantity(
        row.available_quantity,
        "available_quantity",
        { allowZero: true },
      ),
      blocked_quantity: parseQuantity(
        row.blocked_quantity,
        "blocked_quantity",
        { allowZero: true },
      ),
      total_quantity: parseQuantity(
        row.total_quantity,
        "total_quantity",
        { allowZero: true },
      ),
      damaged_quantity: parseQuantity(
        row.damaged_quantity,
        "damaged_quantity",
        { allowZero: true },
      ),
      minimum_quantity: parseQuantity(
        row.minimum_quantity,
        "minimum_quantity",
        { allowZero: true },
      ),
    };
  });

  const next =
    page.next_cursor === null
      ? null
      : str(page.next_cursor, code, 1024);
  if (page.has_more !== (next !== null)) {
    return contractError(code);
  }

  const samples = page.alert_samples;
  if (
    !Array.isArray(samples) ||
    !samples.every(
      (value) =>
        typeof value === "string" && value.length <= 200,
    )
  ) {
    return contractError(code);
  }

  return {
    items,
    next_cursor: next,
    has_more: page.has_more,
    total: nullableCount(page.total, code),
    alert_count: nullableCount(page.alert_count, code),
    alert_samples: [...samples] as string[],
  };
}

export function parseLiveStockFamilies(
  raw: unknown,
): { items: LiveStockFamilyOption[]; has_more: boolean } {
  const code = "LIVE_STOCK_FAMILIES_INVALID";
  const payload = record(raw, code);
  if (!Array.isArray(payload.items) || typeof payload.has_more !== "boolean") {
    return contractError(code);
  }
  const items = payload.items.map((value) => {
    const row = record(value, code);
    return {
      id: int(row.id, code, 1),
      name: str(row.name, code, 150),
      code: str(row.code, code, 100),
    };
  });
  return { items, has_more: payload.has_more };
}

export function parseLiveStockSummary(
  raw: unknown,
): WarehouseInventorySummary {
  const code = "LIVE_STOCK_RESPONSE_INVALID";
  const payload = record(raw, code);
  return {
    stock_total: int(payload.stock_total, code),
    alert_count: int(payload.alert_count, code),
  };
}

export function parseLiveStockAlertSummary(
  raw: unknown,
): WarehouseInventoryAlertSummary {
  const code = "LIVE_STOCK_ALERT_SUMMARY_INVALID";
  const payload = record(raw, code);
  return {
    alert_count: int(payload.alert_count, code),
  };
}

export function parseBatchProductPage(
  raw: unknown,
): WarehouseBatchProductCursorPage {
  const code = "INVENTORY_BATCH_PRODUCT_RESPONSE_INVALID";
  const page = record(raw, code);
  if (
    !Array.isArray(page.items) ||
    page.items.length > 200 ||
    typeof page.has_more !== "boolean"
  ) {
    return contractError(code);
  }

  const ids = new Set<number>();
  const items = page.items.map((rawItem) => {
    const row = record(rawItem, code);
    const id = int(row.id, code, 1);
    if (ids.has(id)) return contractError(code);
    ids.add(id);

    return {
      id,
      name: str(row.name, code),
      sku: nullableStr(row.sku, code, 100),
      family_name: str(row.family_name, code, 150),
      base_uom_code: str(row.base_uom_code, code, 20),
      display_uom_code: str(row.display_uom_code, code, 20),
      display_factor_to_base: parseQuantity(
        row.display_factor_to_base,
        "display_factor_to_base",
      ),
      currency_code: str(row.currency_code, code, 10),
    };
  });

  const nextCursor =
    page.next_cursor === null
      ? null
      : str(page.next_cursor, code, 1024);
  if (page.has_more !== (nextCursor !== null)) {
    return contractError(code);
  }

  return {
    items,
    next_cursor: nextCursor,
    has_more: page.has_more,
  };
}


export function parseBatchDetailResponse(
  raw: unknown,
): WarehouseBatchDetailResponse {
  const code = "LIVE_STOCK_BATCH_RESPONSE_INVALID";
  const page = record(raw, code);
  if (
    !Array.isArray(page.batches) ||
    page.batches.length > 200 ||
    typeof page.has_more !== "boolean"
  ) {
    return contractError(code);
  }

  const batchIds = new Set<number>();
  const batches = page.batches.map((rawBatch) => {
    const row = record(rawBatch, code);
    const batchId = int(row.batch_id, code, 1);
    if (batchIds.has(batchId)) return contractError(code);
    batchIds.add(batchId);

    const disposition = str(row.disposition, code, 20);
    if (
      !["RELEASED", "QUARANTINED", "BLOCKED", "RECALLED"].includes(
        disposition,
      )
    ) {
      return contractError(code);
    }

    const latestPurchaseCost = moneyOrNull(
      row.latest_purchase_cost,
      code,
    );
    const latestPurchaseUomCode = nullableStr(
      row.latest_purchase_uom_code,
      code,
      20,
    );
    const latestPurchaseDate = isoDateOrNull(
      row.latest_purchase_date,
      code,
    );
    if (
      (latestPurchaseCost === null) !==
        (latestPurchaseUomCode === null) ||
      (latestPurchaseCost === null) !==
        (latestPurchaseDate === null)
    ) {
      return contractError(code);
    }

    const daysToExpiry =
      row.days_to_expiry === null
        ? null
        : typeof row.days_to_expiry === "number" &&
            Number.isSafeInteger(row.days_to_expiry)
          ? row.days_to_expiry
          : contractError(code);

    return {
      batch_id: batchId,
      batch_number: str(row.batch_number, code, 100),
      production_date: isoDateOrNull(
        row.production_date,
        code,
      ),
      expiry_date: isoDateOrNull(row.expiry_date, code),
      disposition: disposition as WarehouseBatchInventoryItem["disposition"],
      days_to_expiry: daysToExpiry,
      on_hand_quantity: parseQuantity(
        row.on_hand_quantity,
        "on_hand_quantity",
        { allowZero: true },
      ),
      reserved_quantity: parseQuantity(
        row.reserved_quantity,
        "reserved_quantity",
        { allowZero: true },
      ),
      available_for_sale_quantity: parseQuantity(
        row.available_for_sale_quantity,
        "available_for_sale_quantity",
        { allowZero: true },
      ),
      unavailable_quantity: parseQuantity(
        row.unavailable_quantity,
        "unavailable_quantity",
        { allowZero: true },
      ),
      restricted_quantity: parseQuantity(
        row.restricted_quantity,
        "restricted_quantity",
        { allowZero: true },
      ),
      quarantined_quantity: parseQuantity(
        row.quarantined_quantity,
        "quarantined_quantity",
        { allowZero: true },
      ),
      blocked_quantity: parseQuantity(
        row.blocked_quantity,
        "blocked_quantity",
        { allowZero: true },
      ),
      recalled_quantity: parseQuantity(
        row.recalled_quantity,
        "recalled_quantity",
        { allowZero: true },
      ),
      damaged_quantity: parseQuantity(
        row.damaged_quantity,
        "damaged_quantity",
        { allowZero: true },
      ),
      disposal_pending_quantity: parseQuantity(
        row.disposal_pending_quantity,
        "disposal_pending_quantity",
        { allowZero: true },
      ),
      latest_purchase_cost: latestPurchaseCost,
      latest_purchase_uom_code: latestPurchaseUomCode,
      latest_purchase_date: latestPurchaseDate,
      purchase_event_count: int(
        row.purchase_event_count,
        code,
      ),
    };
  });

  const nextCursor =
    page.next_cursor === null
      ? null
      : str(page.next_cursor, code, 1024);
  if (page.has_more !== (nextCursor !== null)) {
    return contractError(code);
  }

  return {
    location_id: int(page.location_id, code, 1),
    product_variant_id: int(
      page.product_variant_id,
      code,
      1,
    ),
    currency_code: str(page.currency_code, code, 10),
    batches,
    next_cursor: nextCursor,
    has_more: page.has_more,
  };
}
