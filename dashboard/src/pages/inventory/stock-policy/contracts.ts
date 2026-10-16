export type ShelfLifePolicySource =
  | "EXACT_ACTIVE_POLICY"
  | "NO_ACTIVE_POLICY";

export interface EffectiveShelfLifePolicy {
  location_id: number;
  product_variant_id: number;
  minimum_remaining_shelf_life_days: number;
  requirement_applies: boolean;
  source: ShelfLifePolicySource;
  management_mode: "READ_ONLY_V1";
}

const invalid = (): never => {
  const error = new Error("STOCK_POLICY_RESPONSE_INVALID") as Error & {
    code: string;
  };
  error.code = "STOCK_POLICY_RESPONSE_INVALID";
  throw error;
};

const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return invalid();
  }
  return value as Record<string, unknown>;
};

const positiveInteger = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) {
    return invalid();
  }
  return value;
};

const nonNegativeInteger = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    return invalid();
  }
  return value;
};

export const parseEffectiveShelfLifePolicy = (
  raw: unknown,
): EffectiveShelfLifePolicy => {
  const row = record(raw);
  if (typeof row.requirement_applies !== "boolean") return invalid();
  if (
    row.source !== "EXACT_ACTIVE_POLICY" &&
    row.source !== "NO_ACTIVE_POLICY"
  ) {
    return invalid();
  }
  if (row.management_mode !== "READ_ONLY_V1") return invalid();

  const minimum = nonNegativeInteger(row.minimum_remaining_shelf_life_days);
  if (row.requirement_applies !== (minimum > 0)) return invalid();

  return {
    location_id: positiveInteger(row.location_id),
    product_variant_id: positiveInteger(row.product_variant_id),
    minimum_remaining_shelf_life_days: minimum,
    requirement_applies: row.requirement_applies,
    source: row.source,
    management_mode: row.management_mode,
  };
};
