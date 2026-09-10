const DB_INT_MAX = 2_147_483_647;
const MAX_LEDGER_PAGE_SIZE = 200;
const MAX_CURSOR_LENGTH = 512;

export interface LedgerEntry {
  id: number;
  product_variant_id: number;
  product_name: string;
  packs_per_carton: number;
  type: string;
  quantity_packs: number;
  balance_before: number | null;
  balance_after: number | null;
  admin_name: string;
  reference: string | null;
  notes: string | null;
  date: string;
}

export interface LedgerCursorPage {
  items: LedgerEntry[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
  available_types: string[];
}

function asRecord(value: unknown, message: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(message);
  }
  return value as Record<string, unknown>;
}

function integer(value: unknown, field: string, minimum?: number): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    (minimum !== undefined && value < minimum)
  ) {
    throw new Error(`حقل ${field} في عقد سجل الحركات غير صالح.`);
  }
  return value;
}

function requiredString(value: unknown, field: string, maximumLength: number): string {
  if (
    typeof value !== "string" ||
    !value.trim() ||
    value.length > maximumLength
  ) {
    throw new Error(`حقل ${field} في عقد سجل الحركات غير صالح.`);
  }
  return value;
}

function nullableString(value: unknown, field: string, maximumLength?: number): string | null {
  if (value === null) return null;
  if (
    typeof value !== "string" ||
    (maximumLength !== undefined && value.length > maximumLength)
  ) {
    throw new Error(`حقل ${field} في عقد سجل الحركات غير صالح.`);
  }
  return value;
}

function nullableBalance(value: unknown, field: string): number | null {
  return value === null ? null : integer(value, field, 0);
}

function parseEntry(raw: unknown, ids: Set<number>): LedgerEntry {
  const value = asRecord(raw, "عنصر سجل الحركات غير صالح.");
  const id = integer(value.id, "id", 1);
  if (ids.has(id)) throw new Error("صفحة سجل الحركات تحتوي حركة مكررة.");
  ids.add(id);

  const quantity = integer(value.quantity_packs, "quantity_packs");
  if (quantity === 0) throw new Error("حركة المخزون لا يمكن أن تحمل كمية صفرية.");

  const balanceBefore = nullableBalance(value.balance_before, "balance_before");
  const balanceAfter = nullableBalance(value.balance_after, "balance_after");
  if ((balanceBefore === null) !== (balanceAfter === null)) {
    throw new Error("لقطة الرصيد قبل وبعد الحركة غير مكتملة.");
  }
  if (
    balanceBefore !== null &&
    balanceAfter !== null &&
    balanceAfter - balanceBefore !== quantity
  ) {
    throw new Error("كمية الحركة لا تطابق لقطة الرصيد قبل وبعد.");
  }

  const date = requiredString(value.date, "date", 64);
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(date) || !Number.isFinite(Date.parse(date))) {
    throw new Error("توقيت حركة المخزون غير صالح أو لا يحمل منطقة زمنية.");
  }

  return {
    id,
    product_variant_id: integer(value.product_variant_id, "product_variant_id", 1),
    product_name: requiredString(value.product_name, "product_name", 200),
    packs_per_carton: integer(value.packs_per_carton, "packs_per_carton", 1),
    type: requiredString(value.type, "type", 50),
    quantity_packs: quantity,
    balance_before: balanceBefore,
    balance_after: balanceAfter,
    admin_name: requiredString(value.admin_name, "admin_name", 120),
    reference: nullableString(value.reference, "reference", 100),
    notes: nullableString(value.notes, "notes"),
    date,
  };
}

export function parseLedgerPage(raw: unknown): LedgerCursorPage {
  const value = asRecord(raw, "استجابة سجل الحركات غير صالحة.");
  if (!Array.isArray(value.items) || value.items.length > MAX_LEDGER_PAGE_SIZE) {
    throw new Error("قائمة سجل الحركات غير صالحة.");
  }
  if (typeof value.has_more !== "boolean") {
    throw new Error("حالة ترقيم سجل الحركات غير صالحة.");
  }

  const nextCursor = nullableString(value.next_cursor, "next_cursor", MAX_CURSOR_LENGTH);
  if (value.has_more !== (nextCursor !== null) || nextCursor === "") {
    throw new Error("Cursor سجل الحركات غير متسق.");
  }

  const ids = new Set<number>();
  const items = value.items.map((item) => parseEntry(item, ids));
  const total = value.total === null ? null : integer(value.total, "total", 0);
  if (total !== null && total < items.length) {
    throw new Error("إجمالي سجل الحركات أصغر من الصفحة الحالية.");
  }

  if (
    !Array.isArray(value.available_types) ||
    value.available_types.length > MAX_LEDGER_PAGE_SIZE ||
    !value.available_types.every(
      (type) => typeof type === "string" && Boolean(type.trim()) && type.length <= 50
    ) ||
    new Set(value.available_types).size !== value.available_types.length
  ) {
    throw new Error("قائمة أنواع حركات المخزون غير صالحة.");
  }

  return {
    items,
    next_cursor: nextCursor,
    has_more: value.has_more,
    total,
    available_types: [...value.available_types],
  };
}

export function formatLedgerDate(value: string): string {
  return new Date(value).toLocaleString("ar-EG", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

export function buildLedgerAdjustmentPayload(
  cartons: number,
  loosePacks: number,
  packsPerCarton: number,
  password: string,
): { password: string; new_total_packs: number } {
  const cartonsValue = integer(cartons, "cartons", 0);
  const looseValue = integer(loosePacks, "loose_packs", 0);
  const cartonSize = integer(packsPerCarton, "packs_per_carton", 1);
  if (looseValue >= cartonSize) {
    throw new Error(`عدد الحبات يجب أن يكون أقل من ${cartonSize}.`);
  }
  if (!password || new TextEncoder().encode(password).length > 72) {
    throw new Error("كلمة المرور مطلوبة ويجب ألا تتجاوز 72 بايت.");
  }

  const total = (cartonsValue * cartonSize) + looseValue;
  if (!Number.isSafeInteger(total) || total > DB_INT_MAX) {
    throw new Error("الكمية الجديدة تتجاوز سعة المخزون المسموحة.");
  }
  return { password, new_total_packs: total };
}

export function parseLedgerMutationResponse(raw: unknown): { message: string } {
  const value = asRecord(raw, "استجابة تعديل السجل غير صالحة.");
  return { message: requiredString(value.message, "message", 1000) };
}
