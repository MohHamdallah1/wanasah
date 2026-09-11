import type { CatalogVariant } from "../catalog/contracts";
import { compareQuantity, parseQuantity, validateVariantQuantity, type Quantity } from "../quantity";

export const MAX_INBOUND_ITEMS = 5_000;
export interface InboundBatchDraft { row_id: string; quantity: string; batch_number: string; production_date: string; expiry_date: string }
export type InboundDraftMap = Record<string, InboundBatchDraft[]>;
export type DraftProductMap = Record<string, CatalogVariant>;
export interface InboundItemPayload { product_variant_id: number; quantity: Quantity; uom_id: number; batch_number: string; production_date: string | null; expiry_date: string }

export const emptyInboundBatch = (rowId: string): InboundBatchDraft => ({ row_id: rowId, quantity: "0", batch_number: "", production_date: "", expiry_date: "" });
const positiveId = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0 && value <= 2_147_483_647;
const isoDate = (value: string, optional: boolean): boolean => {
  if (!value) return optional;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value); if (!match) return false;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return date.getUTCFullYear() === Number(match[1]) && date.getUTCMonth() === Number(match[2]) - 1 && date.getUTCDate() === Number(match[3]);
};
export const inboundStorageKeys = (companyId: number, actorId: number, locationId: number) => {
  if (![companyId, actorId, locationId].every(positiveId)) throw new Error("نطاق مسودة التوريد غير صالح.");
  const prefix = `wanasah:inbound:v5:${companyId}:${actorId}:${locationId}`;
  return { drafts: `${prefix}:drafts`, products: `${prefix}:products`, reference: `${prefix}:reference`, notes: `${prefix}:notes`, requestId: `${prefix}:request-id`, fingerprint: `${prefix}:fingerprint` } as const;
};
export const parseInboundDrafts = (raw: string | null): InboundDraftMap => {
  if (!raw) return {}; let parsed: unknown; try { parsed = JSON.parse(raw); } catch { return {}; }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
  const result: InboundDraftMap = {}; let count = 0;
  for (const [key, unknownRows] of Object.entries(parsed)) {
    if (!positiveId(Number(key)) || !Array.isArray(unknownRows) || !unknownRows.length) return {};
    const rows: InboundBatchDraft[] = [];
    for (const item of unknownRows) {
      if (!item || typeof item !== "object") return {}; const row = item as Record<string, unknown>;
      if (typeof row.row_id !== "string" || !row.row_id || typeof row.quantity !== "string" || typeof row.batch_number !== "string" || typeof row.production_date !== "string" || typeof row.expiry_date !== "string") return {};
      try { parseQuantity(row.quantity, "quantity", { allowZero: true }); } catch { return {}; }
      if (!isoDate(row.production_date, true) || !isoDate(row.expiry_date, true)) return {};
      rows.push({ row_id: row.row_id, quantity: row.quantity, batch_number: row.batch_number, production_date: row.production_date, expiry_date: row.expiry_date });
      if (++count > MAX_INBOUND_ITEMS) return {};
    }
    result[key] = rows;
  }
  return result;
};
export const parseInboundDraftProducts = (_raw: string | null): DraftProductMap => ({});
export const inboundProductIds = (drafts: InboundDraftMap): number[] => Object.entries(drafts).filter(([, rows]) => rows.some((row) => {
  try { return compareQuantity(parseQuantity(row.quantity, "quantity", { allowZero: true }), "0") > 0; } catch { return false; }
})).map(([id]) => Number(id));
export const buildInboundItems = (drafts: InboundDraftMap, variants: Map<string, CatalogVariant>): InboundItemPayload[] => {
  const items: InboundItemPayload[] = []; const seen = new Set<string>();
  for (const productId of inboundProductIds(drafts)) {
    const variant = variants.get(String(productId)); if (!variant) throw new Error(`تعذر التحقق من الصنف رقم ${productId}.`);
    for (const row of drafts[String(productId)] ?? []) {
      const quantity = validateVariantQuantity(row.quantity, variant.quantity_scale, variant.quantity_step, "quantity", true);
      if (compareQuantity(quantity, "0") === 0) continue;
      const batch = row.batch_number.trim();
      if (!batch || batch.length > 100) throw new Error(`أدخل رقم دفعة صالحاً للصنف (${variant.name}).`);
      if (!isoDate(row.expiry_date, false) || !isoDate(row.production_date, true) || (row.production_date && row.production_date > row.expiry_date)) throw new Error(`تواريخ الدفعة (${batch}) غير صالحة.`);
      const key = `${variant.id}|${batch}`; if (seen.has(key)) throw new Error(`الدفعة (${batch}) مكررة للصنف (${variant.name}).`); seen.add(key);
      items.push({ product_variant_id: variant.id, quantity, uom_id: variant.base_uom.id, batch_number: batch, production_date: row.production_date || null, expiry_date: row.expiry_date });
      if (items.length > MAX_INBOUND_ITEMS) throw new Error(`فاتورة التوريد تتجاوز ${MAX_INBOUND_ITEMS} سطر.`);
    }
  }
  return items.sort((a,b) => a.product_variant_id - b.product_variant_id || a.batch_number.localeCompare(b.batch_number));
};
export const parseInboundResponse = (raw: unknown): { message: string } => {
  if (!raw || typeof raw !== "object" || typeof (raw as {message?: unknown}).message !== "string") throw new Error("استجابة التوريد غير صالحة.");
  return { message: (raw as {message: string}).message };
};
