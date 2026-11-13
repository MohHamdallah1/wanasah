/** Exact, presentation-only carton + base-remainder arithmetic for Route Launch.
 * The backend remains the sole authority for which SKU has a valid CARTON UOM.
 * Never use display_factor_to_base here: it can represent a PALLET.
 * The resulting quantity remains canonical inventory_base, NOT cartons.
 */
import {
  addQuantity, compareQuantity, multiplyQuantity, splitBaseQuantityByUom,
  validateVariantQuantity, type Quantity,
} from "@/lib/quantity";

export type RouteLoadTargetUnit = {
  quantity_scale: number;
  quantity_step: Quantity;
  /** Unique, backend-verified carton conversion; null means no trusted carton. */
  carton_factor_to_base: Quantity | null;
};

export type RouteLoadTargetParts = {
  cartons: Quantity;
  baseRemainder: Quantity;
  hasCarton: boolean;
};

const MAX_INVENTORY_BASE = "99999999999999.999999"; // Backend NUMERIC(20,6).

function cartonFactor(unit: RouteLoadTargetUnit): Quantity | null {
  const raw = unit.carton_factor_to_base;
  if (raw === null) return null;
  if (typeof raw !== "string" || raw.length > 20 || !/^\d+$/.test(raw)) {
    throw new Error("DISPATCH_CARTON_FACTOR_INVALID");
  }
  const factor = validateVariantQuantity(raw, 0, "1", "carton_factor", false);
  if (compareQuantity(factor, "1") <= 0 || compareQuantity(factor, MAX_INVENTORY_BASE) > 0) {
    throw new Error("DISPATCH_CARTON_FACTOR_INVALID");
  }
  return factor;
}

function validBase(raw: string, unit: RouteLoadTargetUnit): Quantity {
  if (raw.length > 32) throw new Error("DISPATCH_TARGET_BASE_OVERFLOW");
  const quantity = validateVariantQuantity(
    raw, unit.quantity_scale, unit.quantity_step, "inventory_base", true,
  );
  if (compareQuantity(quantity, MAX_INVENTORY_BASE) > 0) {
    throw new Error("DISPATCH_TARGET_BASE_OVERFLOW");
  }
  return quantity;
}

/** Round-trip existing signed stock or a saved canonical draft; never infer UOM. */
export function splitRouteLoadTargetBase(
  base: Quantity,
  unit: RouteLoadTargetUnit,
): RouteLoadTargetParts {
  const quantity = validBase(base, unit);
  const factor = cartonFactor(unit);
  if (!factor) return { cartons: "0", baseRemainder: quantity, hasCarton: false };
  const parts = splitBaseQuantityByUom(quantity, factor);
  if (!parts) throw new Error("DISPATCH_CARTON_SPLIT_INVALID");
  return {
    cartons: parts.displayQuantity,
    baseRemainder: parts.baseRemainder,
    hasCarton: true,
  };
}

/** Both fields together are the desired vehicle total, not an additive delta. */
export function composeRouteLoadTargetBase(
  cartonDraft: string,
  remainderDraft: string,
  unit: RouteLoadTargetUnit,
): Quantity {
  const cartons = cartonDraft.trim() || "0";
  const remainder = remainderDraft.trim() || "0";
  const factor = cartonFactor(unit);
  if (cartons.length > 20 || remainder.length > 32) {
    throw new Error("DISPATCH_TARGET_BASE_OVERFLOW");
  }
  if (!factor) {
    if (cartons !== "0") throw new Error("DISPATCH_CARTON_UOM_UNAVAILABLE");
    return validBase(remainder, unit);
  }
  if (!/^\d+$/.test(cartons)) throw new Error("DISPATCH_CARTON_COUNT_INVALID");
  const cartonCount = validateVariantQuantity(cartons, 0, "1", "carton_count", true);
  const loose = validBase(remainder, unit);
  if (compareQuantity(loose, factor) >= 0) {
    throw new Error("DISPATCH_CARTON_REMAINDER_TOO_LARGE");
  }
  return validBase(addQuantity(multiplyQuantity(cartonCount, factor), loose), unit);
}
