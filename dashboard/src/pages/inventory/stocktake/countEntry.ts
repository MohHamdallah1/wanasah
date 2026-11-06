import { validateVariantQuantity } from "../quantity";
import type { StocktakeRow } from "../inventoryUtils";

/** Optional server-proven conversion: exact base units per one outer unit. */
export interface CountOuterUom {
  count_outer_uom_id: number;
  count_outer_uom_name: string;
  count_outer_uom_code: string;
  count_outer_factor_numerator: number;
  count_outer_factor_denominator: number;
}

const DECIMAL = /^\d+(?:\.\d{1,6})?$/;
const INTEGER = /^\d+$/;
const MILLION = 1_000_000n;

/** Never infer packaging from SKU, carton counts or legacy product fields. */
export function parseCountOuterUom(raw: Record<string, unknown>, baseUomId: number): CountOuterUom | null {
  const id = raw.count_outer_uom_id;
  const name = raw.count_outer_uom_name;
  const code = raw.count_outer_uom_code;
  const numerator = raw.count_outer_factor_numerator;
  const denominator = raw.count_outer_factor_denominator;
  if (
    typeof id !== "number" || !Number.isSafeInteger(id) || id <= 0 || id === baseUomId ||
    typeof name !== "string" || !name.trim() ||
    typeof code !== "string" || !code.trim() ||
    typeof numerator !== "number" || !Number.isSafeInteger(numerator) || numerator <= 0 ||
    typeof denominator !== "number" || !Number.isSafeInteger(denominator) || denominator <= 0
  ) return null;
  const n = BigInt(numerator);
  const d = BigInt(denominator);
  if (n % d !== 0n || n / d <= 1n) return null;
  return {
    count_outer_uom_id: id,
    count_outer_uom_name: name,
    count_outer_uom_code: code,
    count_outer_factor_numerator: numerator,
    count_outer_factor_denominator: denominator,
  };
}

export function countOuterFactor(row: StocktakeRow): bigint | null {
  const meta = parseCountOuterUom(row as unknown as Record<string, unknown>, row.base_uom_id);
  return meta ? BigInt(meta.count_outer_factor_numerator) / BigInt(meta.count_outer_factor_denominator) : null;
}

function scaled(value: string): bigint {
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * MILLION + BigInt(fraction.padEnd(6, "0"));
}
function formatted(value: bigint): string {
  const whole = value / MILLION;
  const fraction = (value % MILLION).toString().padStart(6, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole.toString();
}

export function validBaseCount(row: StocktakeRow, value: string): string | null {
  if (!DECIMAL.test(value)) return null;
  try {
    return validateVariantQuantity(value, row.quantity_scale, row.quantity_step, "actual_quantity", true);
  } catch {
    return null;
  }
}

/** Returns null for empty/invalid/implicit zero. Zero is asserted only via Confirm Zero. */
export function calculateCount(row: StocktakeRow, outer: string, base: string): string | null {
  const factor = countOuterFactor(row);
  if (factor === null) {
    const candidate = validBaseCount(row, base);
    return candidate && candidate !== "0" ? candidate : null;
  }
  if (!outer && !base) return null;
  if (outer && !INTEGER.test(outer)) return null;
  if (base && !DECIMAL.test(base)) return null;
  const quantity = (outer ? BigInt(outer) * factor * MILLION : 0n) +
    (base ? scaled(base) : 0n);
  if (quantity === 0n) return null;
  return validBaseCount(row, formatted(quantity));
}

/** Draft UI fields are derived from actual base stock, not accepted as business truth. */
export function splitCountForDisplay(row: StocktakeRow, actual: string): { outer: string; base: string } {
  const factor = countOuterFactor(row);
  if (factor === null || !validBaseCount(row, actual)) return { outer: "", base: actual };
  const units = scaled(actual);
  const factorScaled = factor * MILLION;
  return {
    outer: (units / factorScaled).toString(),
    base: formatted(units % factorScaled),
  };
}

/** Preserve exact draft decomposition only when it still matches the reauthorized server factor. */
export function restoreCountParts(
  current: StocktakeRow,
  saved: Partial<StocktakeRow>,
): { outer: string; base: string } {
  const actual = typeof saved.actual_quantity === "string" ? saved.actual_quantity : "";
  const factor = countOuterFactor(current);
  if (factor === null) return { outer: "", base: actual };
  if (
    saved.count_outer_uom_id === current.count_outer_uom_id &&
    saved.count_outer_factor_numerator === current.count_outer_factor_numerator &&
    saved.count_outer_factor_denominator === current.count_outer_factor_denominator &&
    typeof saved.count_outer_quantity === "string" &&
    typeof saved.count_base_quantity === "string"
  ) {
    const submitted = calculateCount(current, saved.count_outer_quantity, saved.count_base_quantity);
    const bounded = saved.count_outer_quantity.length <= 48 && saved.count_base_quantity.length <= 48;
    // Counted drafts must match one canonical base value. An unfinished, invalid
    // draft must retain both exact operator inputs without ever becoming counted.
    if (bounded && ((saved.counted === true && submitted === validBaseCount(current, actual)) ||
        saved.counted !== true)) {
      return { outer: saved.count_outer_quantity, base: saved.count_base_quantity };
    }
  }
  return validBaseCount(current, actual)
    ? splitCountForDisplay(current, actual)
    : { outer: "", base: actual };
}
