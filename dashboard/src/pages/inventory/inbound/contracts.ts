import type { CatalogVariant } from "../catalog/contracts";
import {
  compareQuantity,
  parseQuantity,
  validateVariantQuantity,
  type Quantity,
} from "../quantity";

export const MAX_INBOUND_ITEMS = 5_000;

export interface InboundBatchDraft {
  row_id: string;
  quantity: string;
  uom_id: string;
  unit_cost: string;
  batch_number: string;
  production_date: string;
  expiry_date: string;
}

export type InboundDraftMap = Record<string, InboundBatchDraft[]>;

export interface InboundDocumentDefaults {
  batch_number: string;
}

export interface InboundUomOption {
  id: number;
  code: string;
  name: string;
  factor_to_base: string;
}

export interface InboundVariantOptions {
  product_variant_id: number;
  base_uom_id: number;
  uoms: InboundUomOption[];
}

export interface InboundOptionsResponse {
  currency_code: string;
  items: InboundVariantOptions[];
}

export interface CostPolicy {
  method: "MOVING_AVERAGE" | "FIFO";
  is_active: boolean;
  is_locked: boolean;
  locked_at: string | null;
  version: number;
  currency_code: string;
  can_change: boolean;
}

export interface InboundItemPayload {
  product_variant_id: number;
  quantity: Quantity;
  uom_id: number;
  unit_cost: string;
  batch_number: string;
  production_date: string | null;
  expiry_date: string | null;
}

type CodedError = Error & { code: string };
const codedError = (code: string): CodedError => {
  const error = new Error(code) as CodedError;
  error.code = code;
  return error;
};

const positiveId = (value: unknown): value is number =>
  typeof value === "number" &&
  Number.isSafeInteger(value) &&
  value > 0 &&
  value <= 2_147_483_647;

const validMoney = (value: string): string => {
  const clean = value.trim();
  if (!/^\d+(?:\.\d{1,6})?$/.test(clean)) {
    throw codedError("INBOUND_UNIT_COST_INVALID");
  }
  const [rawInteger] = clean.split(".");
  const integer = rawInteger.replace(/^0+/, "") || "0";
  if (integer.length > 14) {
    throw codedError("INBOUND_UNIT_COST_INVALID");
  }
  return clean;
};

const isoDate = (value: string, optional: boolean): boolean => {
  if (!value) return optional;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const date = new Date(
    Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  );
  return (
    date.getUTCFullYear() === Number(match[1]) &&
    date.getUTCMonth() === Number(match[2]) - 1 &&
    date.getUTCDate() === Number(match[3])
  );
};

export const emptyInboundBatch = (
  rowId: string,
  uomId = ""
): InboundBatchDraft => ({
  row_id: rowId,
  quantity: "0",
  uom_id: uomId,
  unit_cost: "",
  batch_number: "",
  production_date: "",
  expiry_date: "",
});

export const inboundStorageKeys = (
  companyId: number,
  actorId: number,
  locationId: number
) => {
  if (![companyId, actorId, locationId].every(positiveId)) {
    throw codedError("INBOUND_DRAFT_SCOPE_INVALID");
  }
  const prefix = `wanasah:inbound:v6:${companyId}:${actorId}:${locationId}`;
  return {
    drafts: `${prefix}:drafts`,
    reference: `${prefix}:reference`,
    notes: `${prefix}:notes`,
    requestId: `${prefix}:request-id`,
    fingerprint: `${prefix}:fingerprint`,
    batchDefault: `${prefix}:batch-default`,
  } as const;
};

export const parseInboundDrafts = (raw: string | null): InboundDraftMap => {
  if (!raw) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};

  const result: InboundDraftMap = {};
  let count = 0;
  for (const [key, unknownRows] of Object.entries(parsed)) {
    if (!positiveId(Number(key)) || !Array.isArray(unknownRows) || !unknownRows.length) {
      return {};
    }
    const rows: InboundBatchDraft[] = [];
    for (const item of unknownRows) {
      if (!item || typeof item !== "object") return {};
      const row = item as Record<string, unknown>;
      if (
        typeof row.row_id !== "string" ||
        !row.row_id ||
        typeof row.quantity !== "string" ||
        typeof row.uom_id !== "string" ||
        typeof row.unit_cost !== "string" ||
        typeof row.batch_number !== "string" ||
        typeof row.production_date !== "string" ||
        typeof row.expiry_date !== "string"
      ) {
        return {};
      }
      try {
        parseQuantity(row.quantity, "quantity", { allowZero: true });
        if (row.unit_cost.trim()) validMoney(row.unit_cost);
      } catch {
        return {};
      }
      if (!isoDate(row.production_date, true) || !isoDate(row.expiry_date, true)) {
        return {};
      }
      rows.push({
        row_id: row.row_id,
        quantity: row.quantity,
        uom_id: row.uom_id,
        unit_cost: row.unit_cost,
        batch_number: row.batch_number,
        production_date: row.production_date,
        expiry_date: row.expiry_date,
      });
      if (++count > MAX_INBOUND_ITEMS) return {};
    }
    result[key] = rows;
  }
  return result;
};

export const inboundProductIds = (drafts: InboundDraftMap): number[] =>
  Object.entries(drafts)
    .filter(([, rows]) =>
      rows.some((row) => {
        try {
          return compareQuantity(
            parseQuantity(row.quantity, "quantity", { allowZero: true }),
            "0"
          ) > 0;
        } catch {
          return false;
        }
      })
    )
    .map(([id]) => Number(id));

export const buildInboundItems = (
  drafts: InboundDraftMap,
  variants: Map<string, CatalogVariant>,
  options: Map<number, InboundVariantOptions>,
  defaults: InboundDocumentDefaults = { batch_number: "" }
): InboundItemPayload[] => {
  const items: InboundItemPayload[] = [];
  const seenBatchMetadata = new Map<string, string>();
  const seenBatchUoms = new Set<string>();

  for (const productId of inboundProductIds(drafts)) {
    const variant = variants.get(String(productId));
    const variantOptions = options.get(productId);
    if (!variant || !variantOptions) {
      throw codedError("INBOUND_VARIANT_UNAVAILABLE");
    }
    const allowedUoms = new Set(variantOptions.uoms.map((uom) => uom.id));

    for (const row of drafts[String(productId)] ?? []) {
      const rawQuantity = parseQuantity(row.quantity, "quantity", { allowZero: true });
      if (compareQuantity(rawQuantity, "0") === 0) continue;

      const uomId = Number(row.uom_id || variantOptions.base_uom_id);
      if (!positiveId(uomId) || !allowedUoms.has(uomId)) {
        throw codedError("INBOUND_UOM_REQUIRED");
      }
      if (uomId === variantOptions.base_uom_id) {
        validateVariantQuantity(
          rawQuantity,
          variant.quantity_scale,
          variant.quantity_step,
          "quantity"
        );
      }

      const unitCost = validMoney(row.unit_cost);
      const batch = row.batch_number.trim() || defaults.batch_number.trim();
      if (!batch || batch.length > 100) {
        throw codedError("INBOUND_BATCH_INVALID");
      }
      if (
        !isoDate(row.production_date, true) ||
        !isoDate(row.expiry_date, true) ||
        (row.production_date && row.expiry_date && row.production_date > row.expiry_date)
      ) {
        throw codedError("INBOUND_BATCH_DATES_INVALID");
      }
      if (variant.expiry_control_mode === "REQUIRED" && !row.expiry_date) {
        throw codedError("INBOUND_EXPIRY_REQUIRED");
      }
      if (variant.expiry_control_mode === "NONE" && row.expiry_date) {
        throw codedError("INBOUND_EXPIRY_NOT_ALLOWED");
      }

      const batchKey = `${variant.id}|${batch}`;
      const metadataKey = `${row.production_date}|${row.expiry_date}`;
      const existingMetadata = seenBatchMetadata.get(batchKey);
      if (existingMetadata !== undefined && existingMetadata !== metadataKey) {
        throw codedError("INBOUND_BATCH_METADATA_CONFLICT");
      }
      seenBatchMetadata.set(batchKey, metadataKey);

      const uomKey = `${batchKey}|${uomId}`;
      if (seenBatchUoms.has(uomKey)) {
        throw codedError("INBOUND_DUPLICATE_BATCH_UOM_LINE");
      }
      seenBatchUoms.add(uomKey);
      items.push({
        product_variant_id: variant.id,
        quantity: rawQuantity,
        uom_id: uomId,
        unit_cost: unitCost,
        batch_number: batch,
        production_date: row.production_date || null,
        expiry_date: row.expiry_date || null,
      });
      if (items.length > MAX_INBOUND_ITEMS) {
        throw codedError("INBOUND_TOO_MANY_LINES");
      }
    }
  }

  return items.sort(
    (a, b) =>
      a.product_variant_id - b.product_variant_id ||
      a.batch_number.localeCompare(b.batch_number) ||
      a.uom_id - b.uom_id
  );
};

export const parseInboundOptions = (raw: unknown): InboundOptionsResponse => {
  if (!raw || typeof raw !== "object") throw codedError("INBOUND_OPTIONS_INVALID");
  const value = raw as Record<string, unknown>;
  if (typeof value.currency_code !== "string" || !Array.isArray(value.items)) {
    throw codedError("INBOUND_OPTIONS_INVALID");
  }
  const items = value.items.map((unknownItem) => {
    if (!unknownItem || typeof unknownItem !== "object") {
      throw codedError("INBOUND_OPTIONS_INVALID");
    }
    const item = unknownItem as Record<string, unknown>;
    if (
      !positiveId(item.product_variant_id) ||
      !positiveId(item.base_uom_id) ||
      !Array.isArray(item.uoms)
    ) {
      throw codedError("INBOUND_OPTIONS_INVALID");
    }
    const uoms = item.uoms.map((unknownUom) => {
      if (!unknownUom || typeof unknownUom !== "object") {
        throw codedError("INBOUND_OPTIONS_INVALID");
      }
      const uom = unknownUom as Record<string, unknown>;
      if (
        !positiveId(uom.id) ||
        typeof uom.code !== "string" ||
        typeof uom.name !== "string" ||
        typeof uom.factor_to_base !== "string"
      ) {
        throw codedError("INBOUND_OPTIONS_INVALID");
      }
      return {
        id: uom.id,
        code: uom.code,
        name: uom.name,
        factor_to_base: uom.factor_to_base,
      };
    });
    return {
      product_variant_id: item.product_variant_id,
      base_uom_id: item.base_uom_id,
      uoms,
    };
  });
  return { currency_code: value.currency_code, items };
};

export const parseCostPolicy = (raw: unknown): CostPolicy => {
  if (!raw || typeof raw !== "object") {
    throw codedError("INVENTORY_COST_POLICY_INVALID");
  }
  const value = raw as Record<string, unknown>;
  if (
    !["MOVING_AVERAGE", "FIFO"].includes(String(value.method)) ||
    typeof value.is_active !== "boolean" ||
    typeof value.is_locked !== "boolean" ||
    typeof value.can_change !== "boolean" ||
    typeof value.version !== "number" ||
    !Number.isSafeInteger(value.version) ||
    value.version < 0 ||
    typeof value.currency_code !== "string"
  ) {
    throw codedError("INVENTORY_COST_POLICY_INVALID");
  }
  return {
    method: value.method as CostPolicy["method"],
    is_active: value.is_active,
    is_locked: value.is_locked,
    locked_at: value.locked_at === null ? null : String(value.locked_at),
    version: value.version,
    currency_code: value.currency_code,
    can_change: value.can_change,
  };
};

export const parseInboundResponse = (raw: unknown): void => {
  if (
    !raw ||
    typeof raw !== "object" ||
    typeof (raw as { message?: unknown }).message !== "string"
  ) {
    throw codedError("INBOUND_RESPONSE_INVALID");
  }
};
