// Strict transport boundary. Purchase reference is NOT Product sale pricing.
export interface PurchaseReference {
  product_variant_id: number;
  amount: string;
  purchase_uom_id: number;
  purchase_uom_code: string;
  base_uom_id: number;
  base_uom_code: string;
  currency_code: string;
  revision: number;
  source: "MANUAL_PRODUCT" | "SUPPLIER_INBOUND" | "PRODUCT_IMPORT";
}

export const parsePurchaseReference = (raw: unknown): PurchaseReference | null => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("PURCHASE_REFERENCE_RESPONSE_INVALID");
  }
  const value = (raw as { reference?: unknown }).reference;
  if (value === null) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("PURCHASE_REFERENCE_RESPONSE_INVALID");
  }
  const row = value as Record<string, unknown>;
  const validId = (id: unknown) =>
    typeof id === "number" && Number.isSafeInteger(id) && id > 0;
  if (
    !validId(row.product_variant_id) ||
    !validId(row.purchase_uom_id) ||
    !validId(row.base_uom_id) ||
    typeof row.revision !== "number" || !Number.isSafeInteger(row.revision) || row.revision < 1 ||
    typeof row.amount !== "string" || !/^(?:0|[0-9]+)(?:\.[0-9]{1,6})?$/.test(row.amount) ||
    typeof row.currency_code !== "string" || !/^[A-Z][A-Z0-9]{2,9}$/.test(row.currency_code) ||
    typeof row.purchase_uom_code !== "string" || !row.purchase_uom_code ||
    typeof row.base_uom_code !== "string" || !row.base_uom_code ||
    !["MANUAL_PRODUCT", "SUPPLIER_INBOUND", "PRODUCT_IMPORT"].includes(String(row.source))
  ) {
    throw new Error("PURCHASE_REFERENCE_RESPONSE_INVALID");
  }
  return row as unknown as PurchaseReference;
};

export interface PurchaseReferenceCommand {
  expected_revision: number;
  amount: string;
  purchase_uom_id: number;
  currency_code: string;
}
export const validateReferenceCommand = (
  draft: { amount: string; purchase_uom_id: number; currency_code: string },
  expectedRevision: number,
): PurchaseReferenceCommand => {
  const entered = draft.amount.trim();
  const amount = entered.replace(/^0+(?=[0-9])/, "");
  if (
    entered.length > 64 ||
    !/^[0-9]+(?:\.[0-9]{1,6})?$/.test(amount) ||
    amount.split(".")[0].replace(/^0+/, "").length > 14 ||
    !Number.isSafeInteger(draft.purchase_uom_id) || draft.purchase_uom_id <= 0 ||
    !Number.isSafeInteger(expectedRevision) || expectedRevision < 0 ||
    !/^[A-Z][A-Z0-9]{2,9}$/.test(draft.currency_code)
  ) {
    throw new Error("PURCHASE_REFERENCE_INPUT_INVALID");
  }
  return {
    amount, purchase_uom_id: draft.purchase_uom_id,
    currency_code: draft.currency_code, expected_revision: expectedRevision,
  };
};

/** Validate the immutable committed reply before clearing a durable request. */
export const assertReferenceSaved = (
  raw: unknown,
  command: PurchaseReferenceCommand,
  productVariantId: number,
): void => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("PURCHASE_REFERENCE_RESPONSE_INVALID");
  }
  const row = (raw as { reference?: unknown }).reference;
  if (!row || typeof row !== "object" || Array.isArray(row)) {
    throw new Error("PURCHASE_REFERENCE_RESPONSE_INVALID");
  }
  const ref = row as Record<string, unknown>;
  const parts = command.amount.split(".");
  const canonicalAmount = parts[0] + "." + (parts[1] ?? "").padEnd(6, "0");
  if (
    ref.product_variant_id !== productVariantId ||
    ref.amount !== canonicalAmount ||
    ref.purchase_uom_id !== command.purchase_uom_id ||
    ref.currency_code !== command.currency_code ||
    ref.revision !== command.expected_revision + 1
  ) {
    throw new Error("PURCHASE_REFERENCE_RESPONSE_INVALID");
  }
};
