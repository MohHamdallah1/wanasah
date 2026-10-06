import { parseQuantity } from "../quantity";

export type QualityBatchCandidateSource = {
  location_id: number;
  location_name: string;
  location_type: "WAREHOUSE" | "VEHICLE";
  on_hand_quantity: string;
  reserved_quantity: string;
};

export type QualityBatchCandidate = {
  batch_id: number;
  batch_number: string;
  production_date: string | null;
  expiry_date: string | null;
  disposition: "RELEASED" | "QUARANTINED" | "BLOCKED" | "RECALLED";
  disposition_reason: string | null;
  total_on_hand_quantity: string;
  total_reserved_quantity: string;
  source_count: number;
  sources_preview: QualityBatchCandidateSource[];
  sources_truncated: boolean;
};

export type QualityBatchCandidatePage = {
  product_variant_id: number;
  base_uom_id: number;
  base_uom_code: string;
  items: QualityBatchCandidate[];
  next_cursor: number | null;
  has_more: boolean;
};

const invalid = (): never => {
  const error = new Error("QUALITY_BATCH_CANDIDATES_RESPONSE_INVALID") as Error & { code: string };
  error.code = "QUALITY_BATCH_CANDIDATES_RESPONSE_INVALID";
  throw error;
};

const positiveInt = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) return invalid();
  return value;
};

const optionalDate = (value: unknown): string | null => {
  if (value === null) return null;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return invalid();
  return value;
};

const quantity = (value: unknown, field: string): string => {
  try {
    return parseQuantity(value, field, { allowZero: true });
  } catch {
    return invalid();
  }
};

const parseSource = (raw: unknown): QualityBatchCandidateSource => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  if (
    typeof row.location_name !== "string" ||
    !row.location_name.trim() ||
    row.location_name.length > 200 ||
    (row.location_type !== "WAREHOUSE" && row.location_type !== "VEHICLE")
  ) return invalid();
  return {
    location_id: positiveInt(row.location_id),
    location_name: row.location_name.trim(),
    location_type: row.location_type,
    on_hand_quantity: quantity(row.on_hand_quantity, "source_on_hand_quantity"),
    reserved_quantity: quantity(row.reserved_quantity, "source_reserved_quantity"),
  };
};

const parseItem = (raw: unknown): QualityBatchCandidate => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  if (
    typeof row.batch_number !== "string" ||
    !row.batch_number.trim() ||
    row.batch_number.length > 100 ||
    !["RELEASED", "QUARANTINED", "BLOCKED", "RECALLED"].includes(String(row.disposition)) ||
    (row.disposition_reason !== null && typeof row.disposition_reason !== "string") ||
    !Array.isArray(row.sources_preview) ||
    row.sources_preview.length > 6 ||
    typeof row.sources_truncated !== "boolean"
  ) return invalid();
  const sourceCount = positiveInt(row.source_count);
  const sources = row.sources_preview.map(parseSource);
  if (sources.length > sourceCount || (!row.sources_truncated && sources.length !== sourceCount)) return invalid();
  return {
    batch_id: positiveInt(row.batch_id),
    batch_number: row.batch_number.trim(),
    production_date: optionalDate(row.production_date),
    expiry_date: optionalDate(row.expiry_date),
    disposition: row.disposition as QualityBatchCandidate["disposition"],
    disposition_reason: row.disposition_reason as string | null,
    total_on_hand_quantity: quantity(row.total_on_hand_quantity, "total_on_hand_quantity"),
    total_reserved_quantity: quantity(row.total_reserved_quantity, "total_reserved_quantity"),
    source_count: sourceCount,
    sources_preview: sources,
    sources_truncated: row.sources_truncated,
  };
};

export function parseQualityBatchCandidatePage(raw: unknown): QualityBatchCandidatePage {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  if (
    typeof row.base_uom_code !== "string" ||
    !row.base_uom_code.trim() ||
    row.base_uom_code.length > 20 ||
    !Array.isArray(row.items) ||
    row.items.length > 50 ||
    typeof row.has_more !== "boolean"
  ) return invalid();
  const items = row.items.map(parseItem);
  const nextCursor = row.next_cursor === null ? null : positiveInt(row.next_cursor);
  if ((row.has_more && nextCursor === null) || (!row.has_more && nextCursor !== null)) return invalid();
  const ids = new Set(items.map((item) => item.batch_id));
  if (ids.size !== items.length) return invalid();
  return {
    product_variant_id: positiveInt(row.product_variant_id),
    base_uom_id: positiveInt(row.base_uom_id),
    base_uom_code: row.base_uom_code.trim(),
    items,
    next_cursor: nextCursor,
    has_more: row.has_more,
  };
}
