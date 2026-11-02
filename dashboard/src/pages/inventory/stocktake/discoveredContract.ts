import type { StocktakeRow, StocktakeStockStatus } from "../inventoryUtils";
import { STOCKTAKE_STOCK_STATUSES } from "../inventoryUtils";
import { parseQuantity, validateVariantQuantity } from "../quantity";
import { parseCycleBatchPage, rowKey } from "./parsers";
import type { CycleBatchCursorPage } from "./types";

export type DiscoveredRow = StocktakeRow & { line_origin: "DISCOVERED" };

export type DiscoveredBatch = CycleBatchCursorPage["items"][number] & {
  product_name: string;
  sku: string | null;
  disposition: "RELEASED" | "QUARANTINED" | "BLOCKED" | "RECALLED";
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  quantity_scale: number;
  quantity_step: string;
};

export const isDiscoveredRow = (row: StocktakeRow): row is DiscoveredRow =>
  (row as DiscoveredRow).line_origin === "DISCOVERED";

const asRecord = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid discovered batch response.");
  }
  return value as Record<string, unknown>;
};

export function parseDiscoveredBatches(raw: unknown, productId?: number): {
  items: DiscoveredBatch[];
  next_cursor: string | null;
} {
  const response = asRecord(raw);
  if (!Array.isArray(response.items) || typeof response.has_more !== "boolean") {
    throw new Error("Invalid discovered batch list.");
  }
  // The canonical existing parser rejects mismatched product ownership.
  const verified = productId === undefined
    ? null
    : parseCycleBatchPage(raw, productId);
  const items = response.items.map((item, i) => {
    const r = asRecord(item);
    const variant = Number(r.product_variant_id);
    if (!Number.isSafeInteger(variant) || variant < 1) throw new Error("Invalid batch variant.");
    const parsed = verified ? verified.items[i] : parseCycleBatchPage({
      items: [r], has_more: false, next_cursor: null, total: null,
    }, variant).items[0];
    if (!["RELEASED", "QUARANTINED", "BLOCKED", "RECALLED"].includes(String(r.disposition)) ||
        typeof r.product_name !== "string" || !r.product_name.trim() ||
        !Number.isSafeInteger(r.base_uom_id) || Number(r.base_uom_id) < 1 ||
        typeof r.base_uom_code !== "string" || !r.base_uom_code ||
        typeof r.base_uom_name !== "string" || !r.base_uom_name ||
        !Number.isInteger(r.quantity_scale) || Number(r.quantity_scale) < 0 ||
        Number(r.quantity_scale) > 6) {
      throw new Error("Invalid discovered batch metadata.");
    }
    return {
      ...parsed,
      product_name: r.product_name,
      sku: typeof r.sku === "string" ? r.sku : null,
      disposition: r.disposition as DiscoveredBatch["disposition"],
      base_uom_id: r.base_uom_id as number,
      base_uom_code: r.base_uom_code,
      base_uom_name: r.base_uom_name,
      quantity_scale: r.quantity_scale as number,
      quantity_step: parseQuantity(r.quantity_step, "quantity_step"),
    };
  });
  return { items, next_cursor: verified?.next_cursor ?? (typeof response.next_cursor === "string" ? response.next_cursor : null) };
}

export function buildDiscoveredRow(
  batch: DiscoveredBatch,
  status: StocktakeStockStatus,
  actual: string,
): DiscoveredRow {
  if (!STOCKTAKE_STOCK_STATUSES.includes(status)) throw new Error("Invalid stock status.");
  return {
    line_origin: "DISCOVERED",
    row_key: rowKey(batch.product_variant_id, batch.id, status),
    product_variant_id: batch.product_variant_id,
    batch_id: batch.id,
    stock_status: status,
    product_name: batch.product_name,
    batch_number: batch.batch_number,
    expiry_date: batch.expiry_date,
    base_uom_id: batch.base_uom_id,
    base_uom_code: batch.base_uom_code,
    base_uom_name: batch.base_uom_name,
    quantity_scale: batch.quantity_scale,
    quantity_step: batch.quantity_step,
    actual_quantity: validateVariantQuantity(actual, batch.quantity_scale, batch.quantity_step),
    counted: true,
  };
}

/** Untrusted browser drafts cannot supply product or Batch identity.
 * Rebuild every discovered row from a fresh session-scoped server read.
 */
export function restoreDiscoveredRows(
  saved: unknown,
  authoritative: DiscoveredBatch[],
  snapshot: StocktakeRow[],
): DiscoveredRow[] {
  if (!Array.isArray(saved)) return [];
  const batchMap = new Map(authoritative.map((batch) => [batch.id, batch]));
  const reservedKeys = new Set(snapshot.map((row) => row.row_key));
  const restored: DiscoveredRow[] = [];
  for (const maybe of saved) {
    if (!maybe || typeof maybe !== "object") continue;
    const row = maybe as Partial<DiscoveredRow>;
    if (row.line_origin !== "DISCOVERED" ||
        !Number.isSafeInteger(row.batch_id) || row.batch_id! <= 0 ||
        !STOCKTAKE_STOCK_STATUSES.includes(row.stock_status as StocktakeStockStatus)) continue;
    const batch = batchMap.get(row.batch_id!);
    if (!batch || row.product_variant_id !== batch.product_variant_id) {
      throw new Error("Discovered stock draft does not match authorized session inventory.");
    }
    const key = rowKey(batch.product_variant_id, batch.id, row.stock_status!);
    if (row.row_key !== key || reservedKeys.has(key)) {
      throw new Error("Duplicate or altered discovered stock draft.");
    }
    reservedKeys.add(key);
    // An unfinished draft is retained, but cannot be counted until valid.
    try {
      restored.push(buildDiscoveredRow(batch, row.stock_status!, String(row.actual_quantity ?? "")));
    } catch {
      restored.push({
        ...buildDiscoveredRow(batch, row.stock_status!, batch.quantity_step),
        actual_quantity: String(row.actual_quantity ?? ""),
        counted: false,
      });
    }
  }
  return restored;
}
