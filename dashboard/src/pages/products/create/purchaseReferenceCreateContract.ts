export type PurchaseReferenceCreateInput = {
  amount: string;
  purchase_uom_id: number;
  currency_code: string;
};

export type PurchaseReferenceCreateOptions = {
  can_manage: boolean;
  currency_code: string | null;
  uoms: Array<{ id: number; code: string }>;
};

export function isPurchaseReferenceCreateInput(value: unknown): value is PurchaseReferenceCreateInput {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join(",") !== "amount,currency_code,purchase_uom_id") return false;
  return typeof row.amount === "string" && row.amount.length <= 100
    && /^\d+(?:\.\d{1,6})?$/.test(row.amount)
    && row.amount.split(".")[0].replace(/^0+/, "").length <= 14
    && typeof row.purchase_uom_id === "number" && Number.isSafeInteger(row.purchase_uom_id)
    && row.purchase_uom_id > 0
    && typeof row.currency_code === "string" && /^[A-Z][A-Z0-9]{2,9}$/.test(row.currency_code);
}

export function parsePurchaseReferenceCreateOptions(value: unknown): PurchaseReferenceCreateOptions {
  const fail = (): never => { throw Object.assign(new Error(), { code: "PRODUCT_CREATE_REFERENCE_OPTIONS_INVALID" }); };
  if (!value || typeof value !== "object" || Array.isArray(value)) return fail();
  const row = value as Record<string, unknown>;
  if (typeof row.can_manage !== "boolean" || !Array.isArray(row.uoms)) return fail();
  if (!row.can_manage) {
    if (row.currency_code !== null || row.uoms.length !== 0) return fail();
    return { can_manage: false, currency_code: null, uoms: [] };
  }
  if (typeof row.currency_code !== "string" || !/^[A-Z][A-Z0-9]{2,9}$/.test(row.currency_code)) return fail();
  const uoms = row.uoms.map((item: unknown) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return fail();
    const uom = item as Record<string, unknown>;
    if (typeof uom.id !== "number" || !Number.isSafeInteger(uom.id) || uom.id <= 0
      || typeof uom.code !== "string" || !/^[A-Z][A-Z0-9_]{1,29}$/.test(uom.code)) return fail();
    return { id: uom.id, code: uom.code };
  });
  if (!uoms.some((item) => item.code === "EACH")
    || new Set(uoms.map((item) => item.id)).size !== uoms.length
    || new Set(uoms.map((item) => item.code)).size !== uoms.length) return fail();
  return { can_manage: true, currency_code: row.currency_code, uoms };
}
