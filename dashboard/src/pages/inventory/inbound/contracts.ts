import type { CatalogVariant } from "@/features/catalog/contracts";
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

export interface InboundPurchaseCostReference {
  amount: string;
  purchase_uom_id: number;
  currency_code: string;
  revision: number;
}

export interface InboundVariantOptions {
  product_variant_id: number;
  base_uom_id: number;
  uoms: InboundUomOption[];
  purchase_cost_reference: InboundPurchaseCostReference | null;
}

export interface InboundOptionsResponse {
  currency_code: string;
  items: InboundVariantOptions[];
}

export type CostMethod = "MOVING_AVERAGE" | "FIFO";

export interface CostPolicy {
  // A provisioned inactive default is not an actual choice.
  method: CostMethod | null;
  is_selected: boolean;
  selection_status: "UNSELECTED" | "SELECTED" | "LEGACY_ACTIVE";
  selected_at: string | null;
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
  batch_number: string | null;
  production_date: string | null;
  expiry_date: string | null;
}

export type InboundField =
  | "quantity"
  | "uom_id"
  | "unit_cost"
  | "batch_number"
  | "production_date"
  | "expiry_date";

export class InboundRowValidationError extends Error {
  readonly code: string;
  readonly row_id: string;
  readonly field: InboundField;

  constructor(code: string, rowId: string, field: InboundField) {
    super(code);
    this.name = "InboundRowValidationError";
    this.code = code;
    this.row_id = rowId;
    this.field = field;
  }
}

export const isInboundRowValidationError = (
  error: unknown
): error is InboundRowValidationError =>
  error instanceof InboundRowValidationError;

const inboundRowError = (
  code: string,
  rowId: string,
  field: InboundField): InboundRowValidationError =>
  new InboundRowValidationError(code, rowId, field);

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
          const entered = row.quantity.trim();
          return entered !== "" && entered !== "0";
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
  const seenBatchMetadata = new Map<
    string,
    { production_date: string; expiry_date: string }
  >();
  const seenBatchUoms = new Set<string>();

  for (const productId of inboundProductIds(drafts)) {
    const variant = variants.get(String(productId));
    const variantOptions = options.get(productId);
    if (!variant || !variantOptions) {
      throw codedError("INBOUND_VARIANT_UNAVAILABLE");
    }
    const allowedUoms = new Set(variantOptions.uoms.map((uom) => uom.id));

    for (const row of drafts[String(productId)] ?? []) {
      let rawQuantity: Quantity;
      try {
        rawQuantity = parseQuantity(row.quantity, "quantity", {
          allowZero: true,
        });
      } catch {
        throw inboundRowError(
          "INBOUND_QUANTITY_CONVERSION_INVALID",
          row.row_id,
          "quantity"
        );
      }
      if (compareQuantity(rawQuantity, "0") === 0) continue;

      const uomId = Number(row.uom_id || variantOptions.base_uom_id);
      if (!positiveId(uomId) || !allowedUoms.has(uomId)) {
        throw inboundRowError(
          "INBOUND_UOM_REQUIRED",
          row.row_id,
          "uom_id"
        );
      }
      if (uomId === variantOptions.base_uom_id) {
        try {
          validateVariantQuantity(
            rawQuantity,
            variant.quantity_scale,
            variant.quantity_step,
            "quantity"
          );
        } catch {
          throw inboundRowError(
            "INBOUND_QUANTITY_CONVERSION_INVALID",
            row.row_id,
            "quantity"
          );
        }
      }

      let unitCost: string;
      try {
        unitCost = validMoney(row.unit_cost);
      } catch {
        throw inboundRowError(
          "INBOUND_UNIT_COST_INVALID",
          row.row_id,
          "unit_cost"
        );
      }

      const enteredLot = row.batch_number.trim();
      let batch: string | null = null;
      if (variant.lot_control_mode === "REQUIRED") {
        const requiredLot =
          enteredLot || defaults.batch_number.trim();
        if (!requiredLot) {
          throw inboundRowError(
            "INBOUND_LOT_REQUIRED",
            row.row_id,
            "batch_number"
          );
        }
        if (requiredLot.length > 100) {
          throw inboundRowError(
            "INBOUND_BATCH_INVALID",
            row.row_id,
            "batch_number"
          );
        }
        batch = requiredLot;
      } else if (variant.lot_control_mode === "OPTIONAL") {
        if (enteredLot.length > 100) {
          throw inboundRowError(
            "INBOUND_BATCH_INVALID",
            row.row_id,
            "batch_number"
          );
        }
        batch = enteredLot || null;
      }

      const trackingVisible =
        variant.lot_control_mode !== "NONE" ||
        variant.expiry_control_mode !== "NONE";
      const productionDate = trackingVisible
        ? row.production_date
        : "";
      const expiryDate =
        variant.expiry_control_mode === "NONE"
          ? ""
          : row.expiry_date;

      if (!isoDate(productionDate, true)) {
        throw inboundRowError(
          "INBOUND_BATCH_DATES_INVALID",
          row.row_id,
          "production_date"
        );
      }
      if (!isoDate(expiryDate, true)) {
        throw inboundRowError(
          "INBOUND_BATCH_DATES_INVALID",
          row.row_id,
          "expiry_date"
        );
      }
      if (
        productionDate &&
        expiryDate &&
        productionDate > expiryDate
      ) {
        throw inboundRowError(
          "INBOUND_BATCH_DATES_INVALID",
          row.row_id,
          "expiry_date"
         );
      }
      if (
        variant.expiry_control_mode === "REQUIRED" &&
        !expiryDate
      ) {
        throw inboundRowError(
          "INBOUND_EXPIRY_REQUIRED",
          row.row_id,
          "expiry_date"
        );
      }

      if (batch !== null) {
        const batchKey = `${variant.id}|${batch}`;
        const metadata = {
          production_date: productionDate,
          expiry_date: expiryDate,
        };
        const existingMetadata =
          seenBatchMetadata.get(batchKey);
        if (
          existingMetadata !== undefined &&
          (existingMetadata.production_date !==
            metadata.production_date ||
            existingMetadata.expiry_date !==
              metadata.expiry_date)
        ) {
          throw inboundRowError(
            "INBOUND_BATCH_METADATA_CONFLICT",
            row.row_id,
            existingMetadata.production_date !==
              metadata.production_date
              ? "production_date"
              : "expiry_date"
          );
        }
        seenBatchMetadata.set(batchKey, metadata);

        const uomKey = `${batchKey}|${uomId}`;
        if (seenBatchUoms.has(uomKey)) {
          throw inboundRowError(
            "INBOUND_DUPLICATE_BATCH_UOM_LINE",
            row.row_id,
            "uom_id"
          );
        }
        seenBatchUoms.add(uomKey);
      }

      items.push({
        product_variant_id: variant.id,
        quantity: rawQuantity,
        uom_id: uomId,
        unit_cost: unitCost,
        batch_number: batch,
        production_date: productionDate || null,
        expiry_date: expiryDate || null,
      });
      if (items.length > MAX_INBOUND_ITEMS) {
        throw codedError("INBOUND_TOO_MANY_LINES");
      }
    }
  }

  return items.sort((a, b) => {
    const variantOrder =
      a.product_variant_id - b.product_variant_id;
    if (variantOrder !== 0) return variantOrder;
    const batchOrder = (a.batch_number ?? "").localeCompare(
      b.batch_number ?? ""
    );
    if (batchOrder !== 0) return batchOrder;
    return a.uom_id - b.uom_id;
  });
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
    const rawReference = item.purchase_cost_reference;
    let purchaseCostReference: InboundPurchaseCostReference | null = null;
    if (rawReference !== null && rawReference !== undefined) {
      if (typeof rawReference !== "object" || Array.isArray(rawReference)) {
        throw codedError("INBOUND_OPTIONS_INVALID");
      }
      const ref = rawReference as Record<string, unknown>;
      if (
        typeof ref.amount !== "string" ||
        !/^\d+(?:\.\d{1,6})?$/.test(ref.amount) ||
        typeof ref.currency_code !== "string" ||
        ref.currency_code !== value.currency_code ||
        !positiveId(ref.purchase_uom_id) ||
        !uoms.some((uom) => uom.id === ref.purchase_uom_id) ||
        typeof ref.revision !== "number" ||
        !Number.isSafeInteger(ref.revision) || ref.revision < 1
      ) {
        throw codedError("INBOUND_OPTIONS_INVALID");
      }
      purchaseCostReference = {
        amount: validMoney(ref.amount),
        currency_code: ref.currency_code,
        purchase_uom_id: ref.purchase_uom_id,
        revision: ref.revision,
      };
    }
    return {
      product_variant_id: item.product_variant_id,
      base_uom_id: item.base_uom_id,
      uoms,
      purchase_cost_reference: purchaseCostReference,
    };
  });
  return { currency_code: value.currency_code, items };
};

export const parseCostPolicy = (raw: unknown): CostPolicy => {
  if (!raw || typeof raw !== "object") {
    throw codedError("INVENTORY_COST_POLICY_INVALID");
  }
  const value = raw as Record<string, unknown>;
  const methodValid =
    value.method === null ||
    value.method === "MOVING_AVERAGE" ||
    value.method === "FIFO";
  const statusValid = [
    "UNSELECTED",
    "SELECTED",
    "LEGACY_ACTIVE",
  ].includes(String(value.selection_status));
  if (
    !methodValid ||
    !statusValid ||
    typeof value.is_selected !== "boolean" ||
    (value.is_selected !== (value.method !== null)) ||
    (value.selection_status === "UNSELECTED") !== (value.method === null) ||
    (value.selection_status === "UNSELECTED" && value.selected_at !== null) ||
    (typeof value.is_active === "boolean" &&
      typeof value.is_locked === "boolean" &&
      value.is_active !== value.is_locked) ||
    (typeof value.is_locked === "boolean" &&
      (value.locked_at === null) === value.is_locked) ||
    (value.is_active === true &&
      (value.is_selected !== true || value.can_change !== false)) ||
    (value.selection_status === "LEGACY_ACTIVE" &&
      (!value.is_active || !value.is_locked || value.selected_at !== null)) ||
    (value.selection_status === "SELECTED" &&
      (typeof value.selected_at !== "string" || !value.selected_at.trim())) ||
    (value.selected_at !== null && typeof value.selected_at !== "string") ||
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
    is_selected: value.is_selected as boolean,
    selection_status: value.selection_status as CostPolicy["selection_status"],
    selected_at: value.selected_at as string | null,
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

export interface InboundReferenceSelection {
  product_variant_id: number;
  uom_id: number;
  unit_cost: string;
}

/** Explicit selection is only needed when one variant has multiple native cost/UOM pairs. */
export function inboundReferenceChoices(items: InboundItemPayload[]): Map<number, InboundReferenceSelection[]> {
  const pairs = new Map<number, Map<string, InboundReferenceSelection>>();
  for (const item of items) {
    const unitCost = validMoney(item.unit_cost);
    // Canonicalize decimals as strings; never calculate financial values in JS floats.
    const parts = unitCost.split(".");
    const canonical = (parts[0].replace(/^0+/, "") || "0") + "." + (parts[1] ?? "").padEnd(6, "0");
    const pair: InboundReferenceSelection = {
      product_variant_id: item.product_variant_id,
      uom_id: item.uom_id,
      unit_cost: canonical,
    };
    if (!pairs.has(item.product_variant_id)) pairs.set(item.product_variant_id, new Map());
    pairs.get(item.product_variant_id)!.set(pair.uom_id + "|" + pair.unit_cost, pair);
  }
  return new Map([...pairs]
    .filter(([, alternatives]) => alternatives.size > 1)
    .map(([id, alternatives]) => [
      id,
      [...alternatives.values()].sort((a, b) => (a.uom_id - b.uom_id) || a.unit_cost.localeCompare(b.unit_cost)),
    ]));
}

export const prefilledInboundRow = (
  rowId: string,
  defaultUomId: string,
  option: InboundVariantOptions | undefined,
): InboundBatchDraft => {
  const ref = option?.purchase_cost_reference;
  if (!ref) return emptyInboundBatch(rowId, defaultUomId);
  // Only synthetically untouched rows receive a default. Never overwrite stored drafts.
  return {
    ...emptyInboundBatch(rowId, String(ref.purchase_uom_id)),
    unit_cost: ref.amount,
  };
};
