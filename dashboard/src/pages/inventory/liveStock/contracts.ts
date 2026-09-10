const MAX_CURSOR_LENGTH = 1024;
const MAX_PAGE_SIZE = 200;
const MAX_PRODUCT_NAME_LENGTH = 200;
const MAX_SKU_LENGTH = 100;

export interface WarehouseProduct {
  id: number;
  name: string;
  sku: string | null;
  packs_per_carton: number;
  available_packs: number;
  reserved_packs: number;
  blocked_packs: number;
  total_packs: number;
  damaged_packs: number;
  available_cartons: number;
  available_loose_packs: number;
  min_threshold: number;
}

export interface WarehouseInventoryCursorPage {
  items: WarehouseProduct[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
  alert_count: number | null;
  alert_samples: string[];
}

function asRecord(value: unknown, message: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(message);
  }
  return value as Record<string, unknown>;
}

function safeInteger(value: unknown, field: string, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) {
    throw new Error(`حقل ${field} في عقد الرصيد الحي غير صالح.`);
  }
  return value;
}

function nullableCount(value: unknown, field: string): number | null {
  return value === null ? null : safeInteger(value, field);
}

function nullableString(value: unknown, field: string, maximumLength: number): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || !value || value.length > maximumLength) {
    throw new Error(`حقل ${field} في عقد الرصيد الحي غير صالح.`);
  }
  return value;
}

function parseProduct(raw: unknown, seenIds: Set<number>): WarehouseProduct {
  const value = asRecord(raw, "عنصر الرصيد الحي غير صالح.");
  const id = safeInteger(value.id, "id", 1);
  if (seenIds.has(id)) {
    throw new Error("عقد الرصيد الحي يحتوي صنفاً مكرراً.");
  }
  seenIds.add(id);

  const name = value.name;
  if (
    typeof name !== "string" ||
    !name.trim() ||
    name.length > MAX_PRODUCT_NAME_LENGTH
  ) {
    throw new Error("اسم الصنف في عقد الرصيد الحي غير صالح.");
  }
  const sku = value.sku === "" ? "" : nullableString(value.sku, "sku", MAX_SKU_LENGTH);

  const packsPerCarton = safeInteger(value.packs_per_carton, "packs_per_carton", 1);
  const availablePacks = safeInteger(value.available_packs, "available_packs");
  const availableCartons = safeInteger(value.available_cartons, "available_cartons");
  const availableLoosePacks = safeInteger(value.available_loose_packs, "available_loose_packs");

  if (
    availableCartons !== Math.floor(availablePacks / packsPerCarton) ||
    availableLoosePacks !== availablePacks % packsPerCarton
  ) {
    throw new Error("تفصيل كراتين الرصيد الحي لا يطابق الكمية الأساسية.");
  }

  return {
    id,
    name,
    sku,
    packs_per_carton: packsPerCarton,
    available_packs: availablePacks,
    reserved_packs: safeInteger(value.reserved_packs, "reserved_packs"),
    blocked_packs: safeInteger(value.blocked_packs, "blocked_packs"),
    total_packs: safeInteger(value.total_packs, "total_packs"),
    damaged_packs: safeInteger(value.damaged_packs, "damaged_packs"),
    available_cartons: availableCartons,
    available_loose_packs: availableLoosePacks,
    min_threshold: safeInteger(value.min_threshold, "min_threshold"),
  };
}

export function parseLiveStockPage(raw: unknown): WarehouseInventoryCursorPage {
  const value = asRecord(raw, "تنسيق صفحة المخزون غير صالح.");
  if (!Array.isArray(value.items) || value.items.length > MAX_PAGE_SIZE) {
    throw new Error("قائمة صفحة المخزون غير صالحة.");
  }
  if (typeof value.has_more !== "boolean") {
    throw new Error("حالة ترقيم صفحة المخزون غير صالحة.");
  }

  const nextCursor = nullableString(value.next_cursor, "next_cursor", MAX_CURSOR_LENGTH);
  if (value.has_more !== (nextCursor !== null)) {
    throw new Error("عقد ترقيم صفحة المخزون غير متسق.");
  }

  const seenIds = new Set<number>();
  const items = value.items.map((item) => parseProduct(item, seenIds));
  const total = nullableCount(value.total, "total");
  if (total !== null && total < items.length) {
    throw new Error("إجمالي نتائج المخزون أصغر من الصفحة الحالية.");
  }

  const alertCount = nullableCount(value.alert_count, "alert_count");
  const alertSamples = value.alert_samples;
  if (
    !Array.isArray(alertSamples) ||
    alertSamples.length > 3 ||
    !alertSamples.every(
      (sample) =>
        typeof sample === "string" &&
        Boolean(sample.trim()) &&
        sample.length <= MAX_PRODUCT_NAME_LENGTH
    )
  ) {
    throw new Error("عينات تنبيهات المخزون غير صالحة.");
  }
  if (alertCount !== null && alertCount < alertSamples.length) {
    throw new Error("عدد تنبيهات المخزون لا يطابق العينات.");
  }

  return {
    items,
    next_cursor: nextCursor,
    has_more: value.has_more,
    total,
    alert_count: alertCount,
    alert_samples: [...alertSamples],
  };
}
