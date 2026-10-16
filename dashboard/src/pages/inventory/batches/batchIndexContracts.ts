import type { BatchActionSnapshot, BatchDisposition } from "./contracts";

export type BatchIndexExpiryState =
  | "ALL"
  | "EXPIRED"
  | "EXPIRES_TODAY"
  | "EXPIRING_SOON"
  | "NO_EXPIRY";

export type BatchIndexSellability = "ALL" | "SELLABLE" | "NOT_SELLABLE";
export type BatchIndexDispositionFilter = "ALL" | BatchDisposition;
export type BatchIndexAttention =
  | "ALL"
  | "UNAVAILABLE"
  | "DAMAGED"
  | "DISPOSAL_PENDING";
export type BatchIndexSort =
  | "EXPIRY_ASC"
  | "EXPIRY_DESC"
  | "PRODUCT_ASC"
  | "PRODUCT_DESC"
  | "BATCH_IDENTITY_ASC"
  | "UNAVAILABLE_DESC";

export type BatchSellabilityReasonCode =
  | "BATCH_INACTIVE"
  | "DISPOSITION_NOT_RELEASED"
  | "PRODUCTION_DATE_IN_FUTURE"
  | "EXPIRY_REQUIRED_MISSING"
  | "EXPIRY_NOT_ALLOWED"
  | "EXPIRED"
  | "MINIMUM_REMAINING_SHELF_LIFE_NOT_MET";

export interface BatchIndexFilters {
  search: string;
  expiryState: BatchIndexExpiryState;
  sellability: BatchIndexSellability;
  disposition: BatchIndexDispositionFilter;
  attention: BatchIndexAttention;
  familyId: number | null;
  productVariantId: number | null;
  sort: BatchIndexSort;
}

export const DEFAULT_BATCH_INDEX_FILTERS: BatchIndexFilters = {
  search: "",
  expiryState: "ALL",
  sellability: "ALL",
  disposition: "ALL",
  attention: "ALL",
  familyId: null,
  productVariantId: null,
  sort: "EXPIRY_ASC",
};

export interface WarehouseBatchIndexItem extends BatchActionSnapshot {
  product_id: number;
  product_name: string;
  sku: string | null;
  family_name: string;
  product_variant_id: number;
  lot_control_mode: "NONE" | "OPTIONAL" | "REQUIRED";
  expiry_control_mode: "NONE" | "OPTIONAL" | "REQUIRED";
  minimum_remaining_shelf_life_days: number;
  sellability_state: "SELLABLE" | "NOT_SELLABLE";
  sellability_reason_codes: BatchSellabilityReasonCode[];
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  display_uom_id: number;
  display_uom_code: string;
  display_uom_name: string;
  display_factor_to_base: string;
  quantity_scale: number;
  quantity_step: string;
  on_hand_quantity: string;
  reserved_quantity: string;
  available_for_sale_quantity: string;
  unavailable_quantity: string;
  available_status_quantity: string;
  quarantined_quantity: string;
  blocked_quantity: string;
  recalled_quantity: string;
  damaged_quantity: string;
  disposal_pending_quantity: string;
}

export interface WarehouseBatchIndexCursorPage {
  location_id: number;
  as_of_date: string;
  items: WarehouseBatchIndexItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface WarehouseBatchIndexSummary {
  location_id: number;
  as_of_date: string;
  total_relevant_batches: number;
  expired_count: number;
  expiring_soon_count: number;
  non_sellable_count: number;
  quarantined_count: number;
  blocked_count: number;
  recalled_count: number;
  damaged_or_disposal_attention_count: number;
}

const INTERNAL_TOKEN = "WANASAH_NOLOT";
const MAX_CURSOR = 2048;

const invalid = (): never => {
  const error = new Error("BATCH_INDEX_RESPONSE_INVALID") as Error & { code: string };
  error.code = "BATCH_INDEX_RESPONSE_INVALID";
  throw error;
};

const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid();
  return value as Record<string, unknown>;
};

const integer = (value: unknown, minimum = 0): number => {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  ) {
    return invalid();
  }
  return value;
};

const text = (value: unknown, max = 200): string => {
  if (typeof value !== "string" || !value.trim() || value.length > max) return invalid();
  return value;
};

const nullableText = (value: unknown, max = 200): string | null =>
  value === null ? null : text(value, max);

const publicBatchNumber = (value: unknown): string | null => {
  if (value === null) return null;
  const parsed = text(value, 100);
  if (parsed.toUpperCase().includes(INTERNAL_TOKEN)) return invalid();
  return parsed;
};

const dateText = (value: unknown): string => {
  const parsed = text(value, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(parsed) || Number.isNaN(Date.parse(`${parsed}T00:00:00Z`))) {
    return invalid();
  }
  return parsed;
};

const nullableDate = (value: unknown): string | null =>
  value === null ? null : dateText(value);

const quantity = (value: unknown): string => {
  const parsed = text(value, 64);
  if (!/^\d+(?:\.\d+)?$/.test(parsed)) return invalid();
  return parsed;
};

const disposition = (value: unknown): BatchDisposition => {
  if (
    value !== "RELEASED" &&
    value !== "QUARANTINED" &&
    value !== "BLOCKED" &&
    value !== "RECALLED"
  ) {
    return invalid();
  }
  return value;
};

const trackingMode = (value: unknown): "NONE" | "OPTIONAL" | "REQUIRED" => {
  if (value !== "NONE" && value !== "OPTIONAL" && value !== "REQUIRED") return invalid();
  return value;
};

const REASON_CODES = new Set<BatchSellabilityReasonCode>([
  "BATCH_INACTIVE",
  "DISPOSITION_NOT_RELEASED",
  "PRODUCTION_DATE_IN_FUTURE",
  "EXPIRY_REQUIRED_MISSING",
  "EXPIRY_NOT_ALLOWED",
  "EXPIRED",
  "MINIMUM_REMAINING_SHELF_LIFE_NOT_MET",
]);

const reasonCodes = (value: unknown): BatchSellabilityReasonCode[] => {
  if (!Array.isArray(value) || value.length > REASON_CODES.size) return invalid();
  const parsed = value.map((item) => {
    if (typeof item !== "string" || !REASON_CODES.has(item as BatchSellabilityReasonCode)) {
      return invalid();
    }
    return item as BatchSellabilityReasonCode;
  });
  if (new Set(parsed).size !== parsed.length) return invalid();
  return parsed;
};

const allowedTargets = (value: unknown): BatchDisposition[] => {
  if (!Array.isArray(value) || value.length > 4) return invalid();
  const parsed = value.map(disposition);
  if (new Set(parsed).size !== parsed.length) return invalid();
  return parsed;
};

const parseItem = (value: unknown): WarehouseBatchIndexItem => {
  const row = record(value);
  const sellability = row.sellability_state;
  if (sellability !== "SELLABLE" && sellability !== "NOT_SELLABLE") return invalid();
  const reasons = reasonCodes(row.sellability_reason_codes);
  if ((sellability === "SELLABLE" && reasons.length !== 0) || (sellability === "NOT_SELLABLE" && reasons.length === 0)) {
    return invalid();
  }
  const batchDisposition = disposition(row.disposition);
  return {
    batch_id: integer(row.batch_id, 1),
    batch_number: publicBatchNumber(row.batch_number),
    production_date: nullableDate(row.production_date),
    expiry_date: nullableDate(row.expiry_date),
    disposition: batchDisposition,
    disposition_reason: nullableText(row.disposition_reason, 2000),
    disposition_revision: integer(row.disposition_revision, 1),
    allowed_disposition_targets: allowedTargets(row.allowed_disposition_targets),
    days_to_expiry: row.days_to_expiry === null ? null : integer(row.days_to_expiry, -1_000_000),
    product_id: integer(row.product_id, 1),
    product_variant_id: integer(row.product_variant_id, 1),
    product_name: text(row.product_name, 200),
    sku: nullableText(row.sku, 100),
    family_name: text(row.family_name, 150),
    lot_control_mode: trackingMode(row.lot_control_mode),
    expiry_control_mode: trackingMode(row.expiry_control_mode),
    minimum_remaining_shelf_life_days: integer(row.minimum_remaining_shelf_life_days),
    sellability_state: sellability,
    sellability_reason_codes: reasons,
    base_uom_id: integer(row.base_uom_id, 1),
    base_uom_code: text(row.base_uom_code, 20),
    base_uom_name: text(row.base_uom_name, 50),
    display_uom_id: integer(row.display_uom_id, 1),
    display_uom_code: text(row.display_uom_code, 20),
    display_uom_name: text(row.display_uom_name, 50),
    display_factor_to_base: quantity(row.display_factor_to_base),
    quantity_scale: integer(row.quantity_scale),
    quantity_step: quantity(row.quantity_step),
    on_hand_quantity: quantity(row.on_hand_quantity),
    reserved_quantity: quantity(row.reserved_quantity),
    available_for_sale_quantity: quantity(row.available_for_sale_quantity),
    unavailable_quantity: quantity(row.unavailable_quantity),
    available_status_quantity: quantity(row.available_status_quantity),
    quarantined_quantity: quantity(row.quarantined_quantity),
    blocked_quantity: quantity(row.blocked_quantity),
    recalled_quantity: quantity(row.recalled_quantity),
    damaged_quantity: quantity(row.damaged_quantity),
    disposal_pending_quantity: quantity(row.disposal_pending_quantity),
  };
};

export const parseBatchIndexCursorPage = (raw: unknown): WarehouseBatchIndexCursorPage => {
  const row = record(raw);
  if (!Array.isArray(row.items) || row.items.length > 100 || typeof row.has_more !== "boolean") {
    return invalid();
  }
  const nextCursor = row.next_cursor === null ? null : text(row.next_cursor, MAX_CURSOR);
  if (nextCursor?.toUpperCase().includes(INTERNAL_TOKEN)) return invalid();
  if (row.has_more !== (nextCursor !== null)) return invalid();
  const items = row.items.map(parseItem);
  if (new Set(items.map((item) => item.batch_id)).size !== items.length) return invalid();
  return {
    location_id: integer(row.location_id, 1),
    as_of_date: dateText(row.as_of_date),
    items,
    next_cursor: nextCursor,
    has_more: row.has_more,
  };
};

export const parseBatchIndexSummary = (raw: unknown): WarehouseBatchIndexSummary => {
  const row = record(raw);
  return {
    location_id: integer(row.location_id, 1),
    as_of_date: dateText(row.as_of_date),
    total_relevant_batches: integer(row.total_relevant_batches),
    expired_count: integer(row.expired_count),
    expiring_soon_count: integer(row.expiring_soon_count),
    non_sellable_count: integer(row.non_sellable_count),
    quarantined_count: integer(row.quarantined_count),
    blocked_count: integer(row.blocked_count),
    recalled_count: integer(row.recalled_count),
    damaged_or_disposal_attention_count: integer(row.damaged_or_disposal_attention_count),
  };
};

const setOptionalNumber = (params: URLSearchParams, key: string, value: number | null) => {
  if (value !== null) params.set(key, String(value));
};

export const buildBatchIndexCursorParams = (
  locationId: number,
  filters: BatchIndexFilters,
  expiryWarningDays: number,
  cursor: string | null = null,
  limit = 50,
): URLSearchParams => {
  const params = new URLSearchParams({
    location_id: String(locationId),
    limit: String(limit),
    expiry_state: filters.expiryState,
    sellability: filters.sellability,
    sort: filters.sort,
  });
  if (cursor) params.set("cursor", cursor);
  if (filters.search) params.set("search", filters.search);
  if (filters.expiryState === "EXPIRING_SOON") {
    params.set("expiry_warning_days", String(expiryWarningDays));
  }
  if (filters.disposition !== "ALL") params.set("disposition", filters.disposition);
  if (filters.attention === "UNAVAILABLE") params.set("has_unavailable", "true");
  if (filters.attention === "DAMAGED") params.set("has_damaged", "true");
  if (filters.attention === "DISPOSAL_PENDING") params.set("has_disposal_pending", "true");
  setOptionalNumber(params, "family_id", filters.familyId);
  setOptionalNumber(params, "product_variant_id", filters.productVariantId);
  return params;
};

export const buildBatchIndexSummaryParams = (
  locationId: number,
  filters: BatchIndexFilters,
  expiryWarningDays: number,
): URLSearchParams => {
  const params = new URLSearchParams({
    location_id: String(locationId),
    expiry_warning_days: String(expiryWarningDays),
  });
  if (filters.search) params.set("search", filters.search);
  setOptionalNumber(params, "family_id", filters.familyId);
  setOptionalNumber(params, "product_variant_id", filters.productVariantId);
  return params;
};

export const appendUniqueBatchItems = (
  current: WarehouseBatchIndexItem[],
  incoming: WarehouseBatchIndexItem[],
): WarehouseBatchIndexItem[] => {
  const seen = new Set(current.map((item) => item.batch_id));
  return [...current, ...incoming.filter((item) => !seen.has(item.batch_id))];
};

export const toBatchActionSnapshot = (item: WarehouseBatchIndexItem): BatchActionSnapshot => ({
  batch_id: item.batch_id,
  batch_number: item.batch_number,
  production_date: item.production_date,
  expiry_date: item.expiry_date,
  disposition: item.disposition,
  disposition_reason: item.disposition_reason,
  disposition_revision: item.disposition_revision,
  allowed_disposition_targets: item.allowed_disposition_targets,
  days_to_expiry: item.days_to_expiry,
});