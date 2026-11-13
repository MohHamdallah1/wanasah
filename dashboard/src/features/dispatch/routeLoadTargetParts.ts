/** Route Launch: exact largest display unit + base remainder presentation.
 * Product inventory, launch payload and all ledger movements remain BASE UOM.
 * display_factor_to_base comes only from the backend's unique largest UOM.
 * A missing/ambiguous display factor means a single base-unit input.
 */
import {
  addQuantity, compareQuantity, multiplyQuantity, splitBaseQuantityByUom,
  validateVariantQuantity, type Quantity,
} from "@/lib/quantity";

export type RouteLoadTargetUnit = {
  quantity_scale: number;
  quantity_step: Quantity;
  display_factor_to_base: Quantity | null;
};

export type RouteLoadTargetParts = {
  displayQuantity: Quantity;
  baseRemainder: Quantity;
  hasDisplayUnit: boolean;
};

const MAX_INVENTORY_BASE = "99999999999999.999999"; // Backend NUMERIC(20,6).

function displayFactor(unit: RouteLoadTargetUnit): Quantity | null {
  const raw = unit.display_factor_to_base;
  if (raw === null) return null;
  if (typeof raw !== "string" || raw.length > 20 || !/^\d+$/.test(raw)) {
    throw new Error("DISPATCH_DISPLAY_FACTOR_INVALID");
  }
  const factor = validateVariantQuantity(raw, 0, "1", "display_factor", false);
  if (compareQuantity(factor, MAX_INVENTORY_BASE) > 0) {
    throw new Error("DISPATCH_DISPLAY_FACTOR_INVALID");
  }
  // Same as base UOM: a single input, not two identical unit controls.
  return compareQuantity(factor, "1") === 0 ? null : factor;
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

/** Round-trip real signed stock and existing BASE drafts, without reinterpreting. */
export function splitRouteLoadTargetBase(
  base: Quantity,
  unit: RouteLoadTargetUnit,
): RouteLoadTargetParts {
  const quantity = validBase(base, unit);
  const factor = displayFactor(unit);
  if (!factor) return { displayQuantity: "0", baseRemainder: quantity, hasDisplayUnit: false };
  const parts = splitBaseQuantityByUom(quantity, factor);
  if (!parts) throw new Error("DISPATCH_DISPLAY_SPLIT_INVALID");
  return {
    displayQuantity: parts.displayQuantity,
    baseRemainder: parts.baseRemainder,
    hasDisplayUnit: true,
  };
}

/** Both inputs mean the desired total stock in the vehicle, NOT a stock delta. */
export function composeRouteLoadTargetBase(
  displayDraft: string,
  remainderDraft: string,
  unit: RouteLoadTargetUnit,
): Quantity {
  const display = displayDraft.trim() || "0";
  const remainder = remainderDraft.trim() || "0";
  const factor = displayFactor(unit);
  if (display.length > 20 || remainder.length > 32) {
    throw new Error("DISPATCH_TARGET_BASE_OVERFLOW");
  }
  if (!factor) {
    if (!/^0+$/.test(display)) throw new Error("DISPATCH_DISPLAY_UOM_UNAVAILABLE");
    return validBase(remainder, unit);
  }
  if (!/^\d+$/.test(display)) throw new Error("DISPATCH_DISPLAY_COUNT_INVALID");
  const displayCount = validateVariantQuantity(display, 0, "1", "display_count", true);
  const loose = validBase(remainder, unit);
  if (compareQuantity(loose, factor) >= 0) {
    throw new Error("DISPATCH_DISPLAY_REMAINDER_TOO_LARGE");
  }
  return validBase(addQuantity(multiplyQuantity(displayCount, factor), loose), unit);
}
