import { absoluteQuantity, addQuantity, compareQuantity, parseQuantity, validateVariantQuantity, type Quantity } from "@/lib/quantity";
import { parseRouteLoadUom, routeLoadReview, type RouteLoadUom } from "./routeLoadUom";

export interface AdjustLoadItem extends RouteLoadUom {
  product_id: string;
  product_name: string;
  current_base_quantity: Quantity;
  reserved_base_quantity: Quantity;
  pending_base_quantity: Quantity;
}
export interface AdjustLoadPayload { deltas: { product_id: number; delta_base: Quantity }[] }

export const adjustmentError = () => Object.assign(new Error(), { code: "DISPATCH_ADJUSTMENT_INVALID" });

export function parseAdjustLoadInventory(raw: unknown): AdjustLoadItem[] {
  if (!Array.isArray(raw)) throw adjustmentError();
  const seen = new Set<string>();
  return (raw as Record<string, unknown>[]).map((row) => {
    const id = String(row.product_id);
    if (typeof row.product_id !== "string" || !/^[1-9]\d*$/.test(id) || seen.has(id) ||
        !Number.isSafeInteger(Number(id)) || Number(id) > 2_147_483_647 ||
        typeof row.product_name !== "string") throw adjustmentError();
    seen.add(id);
    const unit = parseRouteLoadUom(row);
    const pending = parseQuantity(row.pending_base_quantity, "pending_base_quantity", { allowZero: true, allowNegative: true });
    validateVariantQuantity(absoluteQuantity(pending), unit.quantity_scale, unit.quantity_step, "pending_base_quantity", true);
    return {
      ...unit, product_id: id, product_name: row.product_name,
      current_base_quantity: validateVariantQuantity(row.current_base_quantity, unit.quantity_scale, unit.quantity_step, "current_base_quantity", true), pending_base_quantity: pending,
      reserved_base_quantity: validateVariantQuantity(row.reserved_base_quantity, unit.quantity_scale, unit.quantity_step, "reserved_base_quantity", true),
    };
  });
}

export function adjustmentReview(item: AdjustLoadItem, rawDelta: string) {
  try {
    const delta = parseQuantity(rawDelta || "0", "delta_base", { allowZero: true, allowNegative: true });
    validateVariantQuantity(absoluteQuantity(delta), item.quantity_scale, item.quantity_step, "delta_base", true);
    const projected = addQuantity(item.current_base_quantity, item.pending_base_quantity);
    if (compareQuantity(projected, "0") < 0) throw adjustmentError();
    const result = addQuantity(projected, delta);
    return { ...routeLoadReview(projected, result, item), result };
  } catch {
    throw adjustmentError();
  }
}

export function buildAdjustmentPayload(items: AdjustLoadItem[], drafts: Record<string, string>, sessionBound = false): AdjustLoadPayload {
  const byId = new Map(items.map((item) => [item.product_id, item]));
  const deltas: AdjustLoadPayload["deltas"] = [];
  for (const [id, raw] of Object.entries(drafts)) {
    const item = byId.get(id);
    if (!item) throw adjustmentError();
    const { delta } = adjustmentReview(item, raw);
    if (sessionBound && delta.includes(".")) {
      throw Object.assign(new Error(), { code: "DRIVER_MOBILE_QUANTITY_PRECISION_UNSUPPORTED" });
    }
    if (compareQuantity(delta, "0")) deltas.push({ product_id: Number(id), delta_base: delta });
  }
  return { deltas };
}

export function parseAdjustmentDraft(raw: string | null): Record<string, string> {
  if (!raw) return {};
  const parsed: unknown = JSON.parse(raw);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object" || Object.keys(parsed).length > 5000) throw adjustmentError();
  for (const [id, delta] of Object.entries(parsed)) {
    if (!/^[1-9]\d*$/.test(id) || typeof delta !== "string" || delta.length > 32) throw adjustmentError();
  }
  return parsed as Record<string, string>;
}
