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

/** A live receivable is NOT immutable opening debt: field collections can change it
 * immediately after POST. The accepted create write/body and canonical PG16
 * financial event supply opening-money evidence; fresh GET verifies identity
 * and metadata only, without rewriting/guessing historical balances.
 */
export function createdShopVerified(rows: unknown, id: string, submitted: ShopCreatePayload): boolean {
  return metadataVerified(rows, id, submitted);
}

/** Resolve a lost create response only using a pre-POST authorized ID snapshot.
 * No id or multiple matching NEW ids means outcome is still uncertain.
 */
export function findCreatedShopAfterUnknownWrite(
  rows: unknown, knownIds: readonly string[], submitted: ShopCreatePayload,
): string | null {
  if (!Array.isArray(rows)) return null;
  const existing = new Set(knownIds);
  const candidates = rows.filter(row => {
    if (!row || typeof row !== "object") return false;
    const id = String((row as { id?: unknown }).id ?? "");
    return /^\d+$/.test(id) && !existing.has(id) &&
      createdShopVerified(rows, id, submitted);
  }).map(row => String((row as { id: unknown }).id));
  return candidates.length === 1 ? candidates[0] : null;
}

/** The header X, Escape, backdrop and Cancel share the same closure fence. */
export const canCloseShopForm = (saving: boolean, needsVerification: boolean): boolean =>
  !saving && !needsVerification;

/** A Shop form cannot steal the shared ShopOrder draft authority. */
export const canOpenShopForm = (dirtyOrder: boolean, pendingOrder: boolean): boolean =>
  !dirtyOrder && !pendingOrder;

/** Keep only authorized fresh Shop IDs; preserve unsaved local sequence/archive edits. */
export function preserveUnsavedShopOrder(
  local: readonly Shop[], authorized: readonly Shop[],
): Shop[] {
  const previous = new Map(local.map(row => [row.id, row]));
  return authorized.map(row => {
    const draft = previous.get(row.id);
    return draft ? { ...row, sequence: draft.sequence, archived: draft.archived } : row;
  });
}

/** Persists across the canonical logout storage clear, but never belongs to
 * another company/principal. This is an operator reminder, NOT a backend receipt.
 */
export type ShopCreateAttempt = {
  kind: "SHOP_CREATE_UNCERTAIN_V1";
  submitted: ShopCreatePayload;
  draft: ShopFormState;
  baselineIds: string[];
};

const SHOP_CREATE_RECOVERY_PREFIX = "wanasah:backoffice-identity:shop-create-attempt:v1";
const safeIdentityPart = (value: string | null): string | null =>
  value && /^(?:0|[1-9]\d{0,15})$/.test(value) && value !== "0" ? value : null;

/** Requires all three authoritative backoffice identity fields; never use a
 * global/shared key, company-only fallback or a login-generation-only key.
 */
export function shopCreateAttemptScope(): string | null {
  try {
    const parts = ["company_id", "principal_id", "backoffice_user_id"]
      .map(key => safeIdentityPart(localStorage.getItem(key)));
    return parts.every((part): part is string => part !== null)
      ? `${SHOP_CREATE_RECOVERY_PREFIX}:${parts.join(":")}` : null;
  } catch {
    return null;
  }
}

/** A durable command is untrusted local state: validate it before showing
 * money or rehydrating a form. GET/POST still require real authorized Bearer.
 */
export function isShopCreateAttempt(value: unknown): value is ShopCreateAttempt {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const attempt = value as Partial<ShopCreateAttempt>;
  if (attempt.kind !== "SHOP_CREATE_UNCERTAIN_V1" || !Array.isArray(attempt.baselineIds) ||
    !attempt.baselineIds.every(id => typeof id === "string" && /^\d+$/.test(id)) ||
    !attempt.draft || typeof attempt.draft !== "object" ||
    !attempt.submitted || typeof attempt.submitted !== "object") return false;
  try {
    const expected = createPayload(attempt.draft as ShopFormState,
      attempt.submitted.force_save);
    const actual = attempt.submitted as unknown as Record<string, unknown>;
    return typeof actual.force_save === "boolean" &&
      Object.keys(actual).length === Object.keys(expected).length &&
      (Object.keys(expected) as Array<keyof ShopCreatePayload>)
        .every(key => actual[key] === expected[key]);
  } catch {
    return false;
  }
}

const safeTrackingId = (value: string): boolean => /^[A-Za-z0-9._:-]{1,100}$/.test(value);

/** A server request ID can help an administrator search logs. It is never
 * operation confirmation. Keep it separate from immutable durable payload.
 */
export function saveShopAttemptServerReference(scope: string, localId: string, reference?: string): void {
  if (!reference || !safeTrackingId(reference)) return;
  try {
    localStorage.setItem(`${scope}:server-ref`, JSON.stringify({ localId, reference }));
  } catch { /* The immutable pending command stays authoritative. */ }
}

export function readShopAttemptServerReference(scope: string, localId: string): string | null {
  try {
    const raw = localStorage.getItem(`${scope}:server-ref`);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const value = parsed as { localId?: unknown; reference?: unknown };
    return value.localId === localId && typeof value.reference === "string" &&
      safeTrackingId(value.reference) ? value.reference : null;
  } catch {
    return null;
  }
}
export function clearShopAttemptServerReference(scope: string): void {
  try { localStorage.removeItem(`${scope}:server-ref`); } catch { /* No claim of success. */ }
}
