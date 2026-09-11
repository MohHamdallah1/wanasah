export const QUANTITY_SCALE = 6;
const QUANTITY_PATTERN = /^-?\d+(?:\.\d{1,6})?$/;

export type Quantity = string;

function scaled(value: unknown, field = "quantity"): bigint {
  if (typeof value !== "string" || !QUANTITY_PATTERN.test(value)) {
    throw new Error(`حقل ${field} يجب أن يكون كمية عشرية بنص دقيق.`);
  }
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction = ""] = unsigned.split(".");
  const result = (BigInt(whole) * 1_000_000n) + BigInt(fraction.padEnd(6, "0"));
  return negative ? -result : result;
}

function canonicalFromScaled(value: bigint): Quantity {
  const negative = value < 0n;
  const absolute = negative ? -value : value;
  const whole = absolute / 1_000_000n;
  const fraction = (absolute % 1_000_000n).toString().padStart(6, "0").replace(/0+$/, "");
  const rendered = fraction ? `${whole}.${fraction}` : whole.toString();
  return negative && absolute !== 0n ? `-${rendered}` : rendered;
}

export function parseQuantity(
  value: unknown,
  field = "quantity",
  options: { allowNegative?: boolean; allowZero?: boolean } = {},
): Quantity {
  const parsed = scaled(value, field);
  if (!options.allowNegative && parsed < 0n) throw new Error(`حقل ${field} لا يمكن أن يكون سالباً.`);
  if (!options.allowZero && parsed === 0n) throw new Error(`حقل ${field} يجب أن يكون أكبر من صفر.`);
  return canonicalFromScaled(parsed);
}

export function validateVariantQuantity(
  value: unknown,
  scale: number,
  step: Quantity,
  field = "quantity",
  allowZero = false,
): Quantity {
  if (!Number.isInteger(scale) || scale < 0 || scale > QUANTITY_SCALE) {
    throw new Error("دقة كمية الصنف غير صالحة.");
  }
  const quantity = parseQuantity(value, field, { allowZero });
  const quantityScaled = scaled(quantity, field);
  const stepScaled = scaled(parseQuantity(step, "quantity_step"), "quantity_step");
  const precisionUnit = 10n ** BigInt(QUANTITY_SCALE - scale);
  if (quantityScaled % precisionUnit !== 0n) {
    throw new Error(`حقل ${field} يتجاوز دقة الصنف (${scale}).`);
  }
  if (quantityScaled % stepScaled !== 0n) {
    throw new Error(`حقل ${field} لا يطابق خطوة الصنف (${step}).`);
  }
  return quantity;
}

export const compareQuantity = (left: Quantity, right: Quantity): number => {
  const a = scaled(left);
  const b = scaled(right);
  return a === b ? 0 : a < b ? -1 : 1;
};

export const addQuantity = (left: Quantity, right: Quantity): Quantity =>
  canonicalFromScaled(scaled(left) + scaled(right));

export const subtractQuantity = (left: Quantity, right: Quantity): Quantity =>
  canonicalFromScaled(scaled(left) - scaled(right));

export const absoluteQuantity = (value: Quantity): Quantity => {
  const parsed = scaled(value);
  return canonicalFromScaled(parsed < 0n ? -parsed : parsed);
};

export const isZeroQuantity = (value: Quantity): boolean => scaled(value) === 0n;

export const formatQuantity = (value: Quantity, uomName: string): string =>
  `${canonicalFromScaled(scaled(value))} ${uomName}`;
