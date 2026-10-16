import {
  compareQuantity,
  parseQuantity,
  subtractQuantity,
  validateVariantQuantity,
  type Quantity,
} from "../quantity";

export interface LedgerEntry {
  id: number;
  product_variant_id: number;
  product_name: string;
  base_uom_id: number;
  base_uom_code: string;
  quantity_scale: number;
  quantity_step: Quantity;
  type: string;
  reference_type: string;
  movement_kind: string | null;
  quantity: Quantity;
  balance_before: Quantity | null;
  balance_after: Quantity | null;
  balance_scope: "PRODUCT_LOCATION" | null;
  batch_id: number | null;
  batch_number: string | null;
  source_location_id: number | null;
  source_location_name: string | null;
  destination_location_id: number | null;
  destination_location_name: string | null;
  source_stock_status: string | null;
  destination_stock_status: string | null;
  display_uom_id: number;
  display_uom_code: string;
  display_uom_name: string;
  display_factor_to_base: Quantity;
  currency_code: string;
  cost_method: "MOVING_AVERAGE" | "FIFO" | null;
  input_quantity: Quantity | null;
  input_uom_code: string | null;
  input_uom_name: string | null;
  input_unit_cost: string | null;
  total_cost: string | null;
  average_cost_after: string | null;
  average_cost_uom_code: string | null;
  average_cost_uom_name: string | null;
  admin_name: string;
  reference: string | null;
  notes: string | null;
  date: string;
  supplier_name?: string | null;
  supplier_code?: string | null;
  supplier_id?: number | null;
}

export interface LedgerCursorPage {
  items: LedgerEntry[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
  available_types: string[];
}

export interface LedgerAdjustmentState {
  entry_id: number;
  reference: string;
  product_variant_id: number;
  batch_id: number | null;
  warehouse_location_id: number;
  current_total_quantity: Quantity;
  base_uom_id: number;
  base_uom_code: string;
}

const INTERNAL_NO_LOT_PREFIX = "__WANASAH_NOLOT__";

const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("LEDGER_CONTRACT_INVALID");
  }
  return value as Record<string, unknown>;
};

const int = (value: unknown, field: string, min = 0): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min) {
    throw new Error(`LEDGER_FIELD_INVALID:${field}`);
  }
  return value;
};

const optionalInt = (value: unknown, field: string): number | null =>
  value === null || value === undefined ? null : int(value, field, 1);

const str = (value: unknown, field: string, max = 4000): string => {
  if (typeof value !== "string" || !value.trim() || value.length > max) {
    throw new Error(`LEDGER_FIELD_INVALID:${field}`);
  }
  return value;
};

const optional = (value: unknown, field: string): string | null =>
  value === null || value === undefined ? null : str(value, field);

const publicBatch = (value: unknown): string | null => {
  const parsed = optional(value, "batch_number");
  if (parsed?.startsWith(INTERNAL_NO_LOT_PREFIX)) {
    throw new Error("LEDGER_INTERNAL_NO_LOT_LEAK");
  }
  return parsed;
};

const moneyOrNull = (value: unknown, field: string): string | null => {
  if (value === null || value === undefined) return null;
  const text = str(value, field, 64);
  if (!/^\d+(?:\.\d{1,6})?$/.test(text)) {
    throw new Error(`LEDGER_FIELD_INVALID:${field}`);
  }
  return text;
};

export function parseLedgerPage(raw: unknown): LedgerCursorPage {
  const page = record(raw);
  if (!Array.isArray(page.items) || page.items.length > 200 || typeof page.has_more !== "boolean") {
    throw new Error("LEDGER_PAGE_INVALID");
  }

  const ids = new Set<number>();
  const items = page.items.map((item): LedgerEntry => {
    const row = record(item);
    const id = int(row.id, "id", 1);
    if (ids.has(id)) throw new Error("LEDGER_DUPLICATE_MOVEMENT");
    ids.add(id);

    const scale = int(row.quantity_scale, "quantity_scale");
    if (scale > 6) throw new Error("LEDGER_QUANTITY_SCALE_INVALID");
    const quantity = parseQuantity(row.quantity, "quantity", { allowNegative: true });
    const before = row.balance_before === null
      ? null
      : parseQuantity(row.balance_before, "balance_before", { allowZero: true });
    const after = row.balance_after === null
      ? null
      : parseQuantity(row.balance_after, "balance_after", { allowZero: true });
    if ((before === null) !== (after === null)) throw new Error("LEDGER_BALANCE_SNAPSHOT_INCOMPLETE");
    if (before !== null && after !== null && (compareQuantity(before, "0") < 0 || compareQuantity(after, "0") < 0)) {
      throw new Error("LEDGER_BALANCE_SNAPSHOT_INVALID");
    }

    const date = str(row.date, "date", 64);
    if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(date) || !Number.isFinite(Date.parse(date))) {
      throw new Error("LEDGER_DATE_INVALID");
    }

    const type = str(row.type, "type", 50);
    return {
      id,
      product_variant_id: int(row.product_variant_id, "product_variant_id", 1),
      product_name: str(row.product_name, "product_name", 200),
      base_uom_id: int(row.base_uom_id, "base_uom_id", 1),
      base_uom_code: str(row.base_uom_code, "base_uom_code", 20),
      quantity_scale: scale,
      quantity_step: parseQuantity(row.quantity_step, "quantity_step"),
      type,
      reference_type: row.reference_type === undefined ? type : str(row.reference_type, "reference_type", 50),
      movement_kind: optional(row.movement_kind, "movement_kind"),
      quantity,
      balance_before: before,
      balance_after: after,
      balance_scope: row.balance_scope === null
        ? null
        : row.balance_scope === "PRODUCT_LOCATION"
          ? "PRODUCT_LOCATION"
          : (() => { throw new Error("LEDGER_BALANCE_SCOPE_INVALID"); })(),
      batch_id: optionalInt(row.batch_id, "batch_id"),
      batch_number: publicBatch(row.batch_number),
      source_location_id: optionalInt(row.source_location_id, "source_location_id"),
      source_location_name: optional(row.source_location_name, "source_location_name"),
      destination_location_id: optionalInt(row.destination_location_id, "destination_location_id"),
      destination_location_name: optional(row.destination_location_name, "destination_location_name"),
      source_stock_status: optional(row.source_stock_status, "source_stock_status"),
      destination_stock_status: optional(row.destination_stock_status, "destination_stock_status"),
      display_uom_id: int(row.display_uom_id, "display_uom_id", 1),
      display_uom_code: str(row.display_uom_code, "display_uom_code", 20),
      display_uom_name: str(row.display_uom_name, "display_uom_name", 50),
      display_factor_to_base: parseQuantity(row.display_factor_to_base, "display_factor_to_base"),
      currency_code: str(row.currency_code, "currency_code", 10),
      cost_method: row.cost_method === null
        ? null
        : row.cost_method === "MOVING_AVERAGE" || row.cost_method === "FIFO"
          ? row.cost_method
          : (() => { throw new Error("LEDGER_COST_METHOD_INVALID"); })(),
      input_quantity: row.input_quantity === null ? null : parseQuantity(row.input_quantity, "input_quantity"),
      input_uom_code: optional(row.input_uom_code, "input_uom_code"),
      input_uom_name: optional(row.input_uom_name, "input_uom_name"),
      input_unit_cost: moneyOrNull(row.input_unit_cost, "input_unit_cost"),
      total_cost: moneyOrNull(row.total_cost, "total_cost"),
      average_cost_after: moneyOrNull(row.average_cost_after, "average_cost_after"),
      average_cost_uom_code: optional(row.average_cost_uom_code, "average_cost_uom_code"),
      average_cost_uom_name: optional(row.average_cost_uom_name, "average_cost_uom_name"),
      admin_name: str(row.admin_name, "admin_name", 120),
      reference: optional(row.reference, "reference"),
      notes: optional(row.notes, "notes"),
      supplier_name: optional(row.supplier_name, "supplier_name"),
      supplier_code: optional(row.supplier_code, "supplier_code"),
      supplier_id: optionalInt(row.supplier_id, "supplier_id"),
      date,
    };
  });

  const next = page.next_cursor === null ? null : str(page.next_cursor, "next_cursor", 512);
  if (page.has_more !== (next !== null)) throw new Error("LEDGER_PAGINATION_INVALID");
  if (!Array.isArray(page.available_types) || !page.available_types.every((value) => typeof value === "string")) {
    throw new Error("LEDGER_TYPES_INVALID");
  }

  return {
    items,
    next_cursor: next,
    has_more: page.has_more,
    total: page.total === null ? null : int(page.total, "total"),
    available_types: [...page.available_types] as string[],
  };
}

export const formatLedgerDate = (value: string, locale: string): string =>
  new Date(value).toLocaleString(locale, {
    dateStyle: "short",
    timeStyle: "short",
    numberingSystem: "latn",
  });

export function buildLedgerAdjustmentPayload(
  quantity: string,
  entry: LedgerEntry,
  password: string,
): { password: string; new_total_quantity: Quantity; uom_id: number } {
  if (!password || new TextEncoder().encode(password).length > 72) {
    throw new Error("LEDGER_ADJUSTMENT_PASSWORD_INVALID");
  }
  return {
    password,
    new_total_quantity: validateVariantQuantity(
      quantity,
      entry.quantity_scale,
      entry.quantity_step,
      "new_total_quantity",
      true,
    ),
    uom_id: entry.base_uom_id,
  };
}

export function parseLedgerAdjustmentState(raw: unknown): LedgerAdjustmentState {
  const row = record(raw);
  return {
    entry_id: int(row.entry_id, "entry_id", 1),
    reference: str(row.reference, "reference", 100),
    product_variant_id: int(row.product_variant_id, "product_variant_id", 1),
    batch_id: optionalInt(row.batch_id, "batch_id"),
    warehouse_location_id: int(row.warehouse_location_id, "warehouse_location_id", 1),
    current_total_quantity: parseQuantity(row.current_total_quantity, "current_total_quantity", { allowZero: true }),
    base_uom_id: int(row.base_uom_id, "base_uom_id", 1),
    base_uom_code: str(row.base_uom_code, "base_uom_code", 20),
  };
}

export function adjustmentDelta(newTotal: Quantity, currentTotal: Quantity): Quantity {
  return subtractQuantity(newTotal, currentTotal);
}

export function parseLedgerMutationResponse(raw: unknown): { message: string } {
  return { message: str(record(raw).message, "message", 1000) };
}
