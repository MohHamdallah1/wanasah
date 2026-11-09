import type { Shop } from "@/types/dispatch";

/** Metadata is a separate authority from opening receivables and credit limits. */
export interface ShopFormState {
  name: string;
  owner: string;
  phone: string;
  mapLink: string;
  zoneId: string;
  initialDebt: string;
  maxDebtLimit: string;
  /** UI-only original phone; never part of the server metadata allowlist. */
  originalPhone?: string;
}

export type ShopMetadataPayload = Pick<ShopFormState,
  "name" | "owner" | "phone" | "mapLink"> & { zoneId: number };
export type ShopCreatePayload = ShopMetadataPayload & {
  initialDebt: string;
  maxDebtLimit: string;
  force_save: boolean;
};
export type ShopFinanceReadback = {
  initialDebt: string;
  maxDebtLimit: string;
};

export const emptyShopForm = (zoneId: string): ShopFormState => ({
  name: "", owner: "", phone: "", mapLink: "", zoneId,
  initialDebt: "0.000", maxDebtLimit: "0.000",
});
export const existingShopForm = (shop: Shop): ShopFormState => ({
  name: shop.name, owner: shop.owner, phone: shop.phone, mapLink: shop.mapLink,
  zoneId: shop.zoneId,
  // These are never sent in EDIT, even if stale.
  initialDebt: String(shop.initialDebt), maxDebtLimit: String(shop.maxDebtLimit),
  originalPhone: shop.phone,
});

export class ShopFormInputError extends Error {
  constructor(public readonly field: "metadata" | "money" | "phone") {
    super("SHOP_FORM_INPUT_INVALID");
  }
}

const validMoney = (value: string): string => {
  const clean = value.trim();
  if (!/^(?:0|[1-9]\d{0,8})(?:\.\d{1,3})?$/.test(clean)) {
    throw new ShopFormInputError("money"); // Same Numeric(12,3) bounds as backend.
  }
  const [whole, fractional = ""] = clean.split(".");
  const normalized = `${whole}.${fractional.padEnd(3, "0")}`;
  if (Number(normalized) > 999999999.999) throw new ShopFormInputError("money");
  return normalized;
};

export function metadataPayload(form: ShopFormState): ShopMetadataPayload {
  const name = form.name.trim();
  const zoneId = Number(form.zoneId);
  if (form.originalPhone?.trim() && !form.phone.trim()) {
    // Canonical backend deliberately ignores an empty phone on EDIT.
    // Do not claim a number was cleared when the server would retain it.
    throw new ShopFormInputError("phone");
  }
  if (name.length < 2 || name.length > 150 ||
    !Number.isSafeInteger(zoneId) || zoneId <= 0 || zoneId > 2147483647 ||
    form.owner.length > 100 || form.phone.length > 20 || form.mapLink.length > 500) {
    throw new ShopFormInputError("metadata");
  }
  // Explicit allowlist: no initialDebt/maxDebtLimit, aliases, or archived/sequence.
  return {
    name, owner: form.owner.trim(), phone: form.phone.trim(),
    mapLink: form.mapLink.trim(), zoneId,
  };
}

export function createPayload(form: ShopFormState, force_save = false): ShopCreatePayload {
  return {
    ...metadataPayload(form),
    initialDebt: validMoney(form.initialDebt),
    maxDebtLimit: validMoney(form.maxDebtLimit),
    force_save,
  };
}

/** Read-only balances from an authorized Shop GET may be signed; creation input may not. */
const readMoney = (value: unknown): string => {
  if (typeof value !== "string" && typeof value !== "number") throw new Error("SHOP_FINANCE_INVALID");
  const clean = String(value);
  if (!/^-?(?:0|[1-9]\d{0,8})(?:\.\d{1,3})?$/.test(clean)) {
    throw new Error("SHOP_FINANCE_INVALID");
  }
  const [whole, fractional = ""] = clean.split(".");
  return `${whole}.${fractional.padEnd(3, "0")}`;
};

export function financeReadback(rows: unknown, id: string): ShopFinanceReadback | null {
  if (!Array.isArray(rows)) return null;
  const shop = rows.find(row => row && typeof row === "object" &&
    String((row as { id?: unknown }).id) === id) as Record<string, unknown> | undefined;
  if (!shop || !["string", "number"].includes(typeof shop.initialDebt) ||
    !["string", "number"].includes(typeof shop.maxDebtLimit)) return null;
  try {
    return { initialDebt: readMoney(shop.initialDebt),
      maxDebtLimit: readMoney(shop.maxDebtLimit) };
  } catch {
    return null;
  }
}

export function metadataVerified(rows: unknown, id: string, submitted: ShopMetadataPayload): boolean {
  if (!Array.isArray(rows)) return false;
  const row = rows.find(shop => shop && typeof shop === "object" &&
    String((shop as { id?: unknown }).id) === id) as Record<string, unknown> | undefined;
  return !!row && row.name === submitted.name &&
    String(row.owner ?? "") === submitted.owner &&
    String(row.phone ?? "") === submitted.phone &&
    String(row.mapLink ?? "") === submitted.mapLink &&
    String(row.zoneId ?? "") === String(submitted.zoneId);
}

export function createdShopVerified(rows: unknown, id: string, submitted: ShopCreatePayload): boolean {
  const actual = financeReadback(rows, id);
  return metadataVerified(rows, id, submitted) &&
    actual?.initialDebt === submitted.initialDebt &&
    actual?.maxDebtLimit === submitted.maxDebtLimit;
}
