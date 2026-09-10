import type { SimpleProductVariant } from "../catalog/contracts";

const DB_INT_MAX = 2_147_483_647;
export const MAX_INBOUND_ITEMS = 5_000;

export interface InboundBatchDraft {
  row_id: string;
  cartons: number;
  loose_packs: number;
  batch_number: string;
  production_date: string;
  expiry_date: string;
}

export type InboundDraftMap = Record<string, InboundBatchDraft[]>;
export type DraftProductMap = Record<string, SimpleProductVariant>;

export interface InboundItemPayload {
  product_variant_id: number;
  quantity_packs: number;
  batch_number: string;
  production_date: string | null;
  expiry_date: string;
}

export function emptyInboundBatch(rowId: string): InboundBatchDraft {
  return {
    row_id: rowId,
    cartons: 0,
    loose_packs: 0,
    batch_number: "",
    production_date: "",
    expiry_date: "",
  };
}

function positiveDbId(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0 && Number(value) <= DB_INT_MAX;
}

function nonNegativeDbInt(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= DB_INT_MAX;
}

function isIsoDate(value: string, optional: boolean): boolean {
  if (!value) return optional;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export function inboundStorageKeys(companyId: number, actorId: number, locationId: number) {
  if (![companyId, actorId, locationId].every(positiveDbId)) {
    throw new Error("نطاق مسودة التوريد غير صالح.");
  }
  const prefix = `wanasah:inbound:v4:${companyId}:${actorId}:${locationId}`;
  return {
    drafts: `${prefix}:drafts`,
    products: `${prefix}:products`,
    reference: `${prefix}:reference`,
    notes: `${prefix}:notes`,
    requestId: `${prefix}:request-id`,
    fingerprint: `${prefix}:fingerprint`,
  } as const;
}

export function parseInboundDrafts(raw: string | null): InboundDraftMap {
  if (!raw) return {};
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return {}; }
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result: InboundDraftMap = {};
  let lineCount = 0;
  for (const [productKey, unknownRows] of Object.entries(value)) {
    const productId = Number(productKey);
    if (!positiveDbId(productId) || !Array.isArray(unknownRows) || unknownRows.length === 0) return {};
    const rows: InboundBatchDraft[] = [];
    for (const unknownRow of unknownRows) {
      if (!unknownRow || typeof unknownRow !== "object") return {};
      const row = unknownRow as Record<string, unknown>;
      if (typeof row.row_id !== "string" || !row.row_id || row.row_id.length > 100 ||
          !nonNegativeDbInt(row.cartons) || !nonNegativeDbInt(row.loose_packs) ||
          typeof row.batch_number !== "string" || row.batch_number.length > 100 ||
          typeof row.production_date !== "string" || !isIsoDate(row.production_date, true) ||
          typeof row.expiry_date !== "string" || !isIsoDate(row.expiry_date, true)) return {};
      rows.push({
        row_id: row.row_id,
        cartons: row.cartons,
        loose_packs: row.loose_packs,
        batch_number: row.batch_number,
        production_date: row.production_date,
        expiry_date: row.expiry_date,
      });
      lineCount += 1;
      if (lineCount > MAX_INBOUND_ITEMS) return {};
    }
    result[String(productId)] = rows;
  }
  return result;
}

export function parseInboundDraftProducts(raw: string | null): DraftProductMap {
  if (!raw) return {};
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return {}; }
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result: DraftProductMap = {};
  for (const [productKey, unknownProduct] of Object.entries(value)) {
    if (!unknownProduct || typeof unknownProduct !== "object") return {};
    const product = unknownProduct as Record<string, unknown>;
    const productId = Number(productKey);
    if (!positiveDbId(productId) || product.id !== productId || typeof product.name !== "string" ||
        !(product.sku === null || typeof product.sku === "string") ||
        !positiveDbId(product.packs_per_carton)) return {};
    result[productKey] = {
      id: productId,
      name: product.name,
      sku: product.sku as string | null,
      packs_per_carton: product.packs_per_carton,
    };
  }
  return result;
}

export function inboundProductIds(drafts: InboundDraftMap): number[] {
  return Object.entries(drafts)
    .filter(([, rows]) => rows.some(row => row.cartons > 0 || row.loose_packs > 0))
    .map(([productId]) => Number(productId));
}

export function buildInboundItems(
  drafts: InboundDraftMap,
  freshProducts: Map<string, SimpleProductVariant>,
): InboundItemPayload[] {
  const items: InboundItemPayload[] = [];
  const seen = new Set<string>();
  for (const productId of inboundProductIds(drafts)) {
    const product = freshProducts.get(String(productId));
    if (!product) throw new Error(`تعذر التحقق من الصنف رقم ${productId}.`);
    for (const row of drafts[String(productId)] ?? []) {
      if (row.cartons === 0 && row.loose_packs === 0) continue;
      if (!nonNegativeDbInt(row.cartons) || !nonNegativeDbInt(row.loose_packs)) {
        throw new Error(`كمية الصنف (${product.name}) غير صالحة.`);
      }
      if (row.loose_packs >= product.packs_per_carton) {
        throw new Error(`خطأ في (${product.name}): الحبات يجب أن تكون أقل من ${product.packs_per_carton}.`);
      }
      const quantity = row.cartons * product.packs_per_carton + row.loose_packs;
      if (!positiveDbId(quantity)) throw new Error(`كمية الصنف (${product.name}) تتجاوز الحد الآمن.`);
      const batchNumber = row.batch_number.trim();
      if (!batchNumber || batchNumber.length > 100) throw new Error(`أدخل رقم دفعة صالحاً للصنف (${product.name}).`);
      if (!isIsoDate(row.expiry_date, false)) throw new Error(`أدخل تاريخ الصلاحية للصنف (${product.name}) — الدفعة ${batchNumber}.`);
      if (!isIsoDate(row.production_date, true)) throw new Error(`تاريخ إنتاج الدفعة (${batchNumber}) غير صالح.`);
      if (row.production_date && row.production_date > row.expiry_date) {
        throw new Error(`تاريخ الإنتاج بعد الصلاحية للصنف (${product.name}) — الدفعة ${batchNumber}.`);
      }
      const key = `${product.id}|${batchNumber}`;
      if (seen.has(key)) throw new Error(`الدفعة (${batchNumber}) مكررة للصنف (${product.name}). اجمع الكمية في سطر واحد.`);
      seen.add(key);
      items.push({
        product_variant_id: product.id,
        quantity_packs: quantity,
        batch_number: batchNumber,
        production_date: row.production_date || null,
        expiry_date: row.expiry_date,
      });
      if (items.length > MAX_INBOUND_ITEMS) throw new Error(`فاتورة التوريد تتجاوز ${MAX_INBOUND_ITEMS} سطر.`);
    }
  }
  return items.sort((a, b) => a.product_variant_id - b.product_variant_id || a.batch_number.localeCompare(b.batch_number));
}

export function parseInboundResponse(raw: unknown): { message: string } {
  if (!raw || typeof raw !== "object" || typeof (raw as { message?: unknown }).message !== "string" ||
      !(raw as { message: string }).message.trim()) throw new Error("استجابة التوريد غير صالحة.");
  return { message: (raw as { message: string }).message };
}
