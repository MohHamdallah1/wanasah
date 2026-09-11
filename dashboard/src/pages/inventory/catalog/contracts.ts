const DB_INT_MAX = 2_147_483_647n;
const MONEY_12_3_MAX_SCALED = 999_999_999_999n;
const MAX_CURSOR_LENGTH = 1024;

export interface SimpleProductVariant {
  id: number;
  name: string;
  sku: string | null;
  packs_per_carton: number;
}

export interface SimpleProductVariantCursorPage {
  items: SimpleProductVariant[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
}

export interface ProductVariantCreateDraft {
  variant_name: string;
  sku: string;
  price_per_carton: string;
  packs_per_carton: string;
  price_per_pack: string;
  max_samples: string;
}

export interface ProductVariantCreatePayload {
  variant_name: string;
  sku: string | null;
  price_per_carton: string;
  packs_per_carton: number;
  price_per_pack: string | null;
  max_samples: number;
}

function asRecord(value: unknown, message: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(message);
  }
  return value as Record<string, unknown>;
}

function positiveId(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0 || value > Number(DB_INT_MAX)) {
    throw new Error(`حقل ${field} في عقد الكتالوج غير صالح.`);
  }
  return value;
}

function parseNonNegativeDbInt(raw: string, field: string, minimum = 0): number {
  const value = raw.trim();
  if (!/^\d+$/.test(value)) throw new Error(`${field} يجب أن يكون عدداً صحيحاً.`);
  const parsed = BigInt(value);
  if (parsed < BigInt(minimum) || parsed > DB_INT_MAX) {
    throw new Error(`${field} خارج النطاق المسموح.`);
  }
  return Number(parsed);
}

function parseMoney(raw: string, field: string, optional: boolean): string | null {
  const value = raw.trim();
  if (!value) {
    if (optional) return null;
    throw new Error(`${field} مطلوب.`);
  }
  const match = /^(\d+)(?:\.(\d{1,3}))?$/.exec(value);
  if (!match) throw new Error(`${field} يجب أن يكون رقماً غير سالب بثلاث منازل عشرية كحد أقصى.`);
  const integerPart = BigInt(match[1]);
  const fraction = (match[2] || "").padEnd(3, "0");
  const scaled = (integerPart * 1000n) + BigInt(fraction || "0");
  if (scaled > MONEY_12_3_MAX_SCALED) throw new Error(`${field} يتجاوز السعة المالية.`);
  return `${integerPart}.${fraction}`;
}

export function parseCatalogItems(raw: unknown): SimpleProductVariant[] {
  if (!Array.isArray(raw) || raw.length > 5000) throw new Error("قائمة الأصناف غير صالحة.");
  const seen = new Set<number>();
  return raw.map((value) => {
    const row = asRecord(value, "بيانات الصنف غير صالحة.");
    const id = positiveId(row.id, "id");
    if (seen.has(id)) throw new Error("قائمة الأصناف تحتوي معرفاً مكرراً.");
    seen.add(id);
    if (typeof row.name !== "string" || !row.name.trim() || row.name.length > 200) {
      throw new Error("اسم الصنف في عقد الكتالوج غير صالح.");
    }
    let sku: string | null;
    if (row.sku === null) {
      sku = null;
    } else if (typeof row.sku === "string" && row.sku.length <= 100) {
      sku = row.sku;
    } else {
      throw new Error("SKU الصنف في عقد الكتالوج غير صالح.");
    }
    return {
      id,
      name: row.name,
      sku,
      packs_per_carton: positiveId(row.packs_per_carton, "packs_per_carton"),
    };
  });
}

export function parseCatalogPage(raw: unknown): SimpleProductVariantCursorPage {
  const row = asRecord(raw, "صفحة الأصناف غير صالحة.");
  if (!Array.isArray(row.items) || row.items.length > 200) {
    throw new Error("حجم صفحة الأصناف غير صالح.");
  }
  if (typeof row.has_more !== "boolean") throw new Error("حالة ترقيم صفحة الأصناف غير صالحة.");
  let nextCursor: string | null;
  if (row.next_cursor === null) {
    nextCursor = null;
  } else if (
    typeof row.next_cursor === "string"
    && row.next_cursor.length > 0
    && row.next_cursor.length <= MAX_CURSOR_LENGTH
  ) {
    nextCursor = row.next_cursor;
  } else {
    throw new Error("Cursor صفحة الأصناف غير صالح.");
  }
  if (row.has_more !== (nextCursor !== null)) throw new Error("ترقيم صفحة الأصناف غير متسق.");
  let total: number | null;
  if (row.total === null) {
    total = null;
  } else if (
    typeof row.total === "number"
    && Number.isSafeInteger(row.total)
    && row.total >= 0
  ) {
    total = row.total;
  } else {
    throw new Error("إجمالي صفحة الأصناف غير صالح.");
  }
  const items = parseCatalogItems(row.items);
  if (total !== null && total < items.length) throw new Error("إجمالي الكتالوج أصغر من الصفحة الحالية.");
  return { items, next_cursor: nextCursor, has_more: row.has_more, total };
}

export function buildProductVariantCreatePayload(draft: ProductVariantCreateDraft): ProductVariantCreatePayload {
  const name = draft.variant_name.trim();
  if (name.length < 2 || name.length > 200 || name.includes("\0")) {
    throw new Error("اسم المنتج يجب أن يكون بين حرفين و200 حرف.");
  }
  const sku = draft.sku.trim();
  if (sku.length > 100 || sku.includes("\0")) throw new Error("SKU غير صالح أو يتجاوز 100 حرف.");
  const pricePerCarton = parseMoney(draft.price_per_carton, "سعر الكرتونة", false);
  if (pricePerCarton === null) throw new Error("سعر الكرتونة مطلوب.");
  return {
    variant_name: name,
    sku: sku || null,
    price_per_carton: pricePerCarton,
    packs_per_carton: parseNonNegativeDbInt(draft.packs_per_carton, "عدد الحبات في الكرتونة", 1),
    price_per_pack: parseMoney(draft.price_per_pack, "سعر الحبة", true),
    max_samples: parseNonNegativeDbInt(draft.max_samples || "0", "حد العينات"),
  };
}

export function parseProductVariantMutationResponse(raw: unknown): { message: string; product_id: number } {
  const value = asRecord(raw, "استجابة إنشاء المنتج غير صالحة.");
  if (typeof value.message !== "string" || !value.message.trim() || value.message.length > 1000) {
    throw new Error("رسالة إنشاء المنتج غير صالحة.");
  }
  return { message: value.message, product_id: positiveId(value.product_id, "product_id") };
}
