import {
  addQuantity,
  compareQuantity,
  formatCommercialQuantity,
  multiplyQuantity,
  parseQuantity,
  splitBaseQuantityByUom,
  validateVariantQuantity,
  type Quantity,
} from "../quantity";
import type { TransferSourceInventoryItem } from "./types";

const precisionStep = (scale: number): Quantity =>
  scale === 0 ? "1" : `0.${"0".repeat(scale - 1)}1`;

export const supportsMixedTransferQuantity = (
  product: TransferSourceInventoryItem,
): boolean =>
  product.display_uom_id !== product.base_uom_id &&
  splitBaseQuantityByUom("0", product.display_factor_to_base) !== null;

export const splitTransferQuantity = (
  product: TransferSourceInventoryItem,
  quantity: Quantity,
): { displayQuantity: Quantity; baseRemainder: Quantity } | null =>
  supportsMixedTransferQuantity(product)
    ? splitBaseQuantityByUom(quantity, product.display_factor_to_base)
    : null;

export function composeTransferQuantity(
  product: TransferSourceInventoryItem,
  displayInput: string,
  baseInput: string,
): Quantity {
  const display = validateVariantQuantity(
    displayInput.trim() || "0",
    product.display_quantity_scale,
    precisionStep(product.display_quantity_scale),
    "display_quantity",
    true,
  );
  const remainder = validateVariantQuantity(
    baseInput.trim() || "0",
    product.quantity_scale,
    product.quantity_step,
    "base_remainder",
    true,
  );

  if (compareQuantity(remainder, product.display_factor_to_base) >= 0) {
    throw new Error("TRANSFER_REMAINDER_TOO_LARGE");
  }

  const total = addQuantity(
    multiplyQuantity(display, product.display_factor_to_base),
    remainder,
  );
  return validateVariantQuantity(
    total,
    product.quantity_scale,
    product.quantity_step,
    "quantity",
    true,
  );
}

export const formatTransferCommercialQuantity = (
  product: TransferSourceInventoryItem,
  quantity: Quantity,
  displayUomName: string,
  baseUomName: string,
): { primary: string; secondary: string | null } =>
  formatCommercialQuantity(
    parseQuantity(quantity, "quantity", { allowZero: true }),
    displayUomName,
    baseUomName,
    product.display_factor_to_base,
  );
