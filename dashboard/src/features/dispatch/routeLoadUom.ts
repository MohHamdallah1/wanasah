import {
  absoluteQuantity, compareQuantity, formatCommercialQuantity, formatQuantity,
  subtractQuantity, validateVariantQuantity,
  type Quantity,
} from "@/lib/quantity";

export interface RouteLoadUom {
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  quantity_scale: number;
  quantity_step: Quantity;
  display_uom_name: string | null;
  display_factor_to_base: Quantity | null;
}

export interface RouteLoadVehicleItem extends RouteLoadUom {
  product_id: string;
  current_base_quantity: Quantity;
}

export function parseRouteLoadUom(value: unknown): RouteLoadUom {
  if (!value || typeof value !== "object") throw new Error("DISPATCH_UOM_METADATA_INVALID");
  const row = value as Record<string, unknown>;
  if (!Number.isSafeInteger(row.base_uom_id) || Number(row.base_uom_id) <= 0 ||
      typeof row.base_uom_name !== "string" || !row.base_uom_name ||
      typeof row.base_uom_code !== "string" ||
      !Number.isInteger(row.quantity_scale) || Number(row.quantity_scale) < 0 ||
      Number(row.quantity_scale) > 6 ||
      typeof row.quantity_step !== "string") throw new Error("DISPATCH_UOM_METADATA_INVALID");
  const step = validateVariantQuantity(row.quantity_step, Number(row.quantity_scale), row.quantity_step);
  const name = row.display_uom_name;
  const factor = row.display_factor_to_base;
  if ((name !== null && typeof name !== "string") ||
      (factor !== null && (typeof factor !== "string" || !/^\d+$/.test(factor) || factor === "0")) ||
      ((name === null) !== (factor === null))) throw new Error("DISPATCH_UOM_METADATA_INVALID");
  return {
    base_uom_id: Number(row.base_uom_id),
    base_uom_code: String(row.base_uom_code),
    base_uom_name: String(row.base_uom_name),
    quantity_scale: Number(row.quantity_scale),
    quantity_step: step,
    display_uom_name: name,
    display_factor_to_base: factor,
  };
}

export function parseRouteLoadVehicleInventory(value: unknown): {
  current: Record<string, Quantity>;
  units: Record<string, RouteLoadUom>;
} {
  if (!Array.isArray(value)) throw new Error("DISPATCH_VEHICLE_INVENTORY_INVALID");
  const current: Record<string, Quantity> = {};
  const units: Record<string, RouteLoadUom> = {};
  for (const raw of value) {
    if (!raw || typeof raw !== "object") throw new Error("DISPATCH_VEHICLE_INVENTORY_INVALID");
    const row = raw as Record<string, unknown>;
    const id = row.product_id;
    if (typeof id !== "string" || !/^[1-9]\d*$/.test(id) || id in current ||
        typeof row.current_base_quantity !== "string") {
      throw new Error("DISPATCH_VEHICLE_INVENTORY_INVALID");
    }
    const unit = parseRouteLoadUom(raw);
    const quantity = validateVariantQuantity(
      row.current_base_quantity, unit.quantity_scale, unit.quantity_step,
    );
    current[id] = quantity;
    units[id] = unit;
  }
  return { current, units };
}

export function parseRouteLoadUomWindow(value: unknown): Record<string, RouteLoadUom> {
  if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("DISPATCH_UOM_METADATA_INVALID");
  return Object.fromEntries(Object.entries(value).map(([id, row]) => {
    if (!/^[1-9]\d*$/.test(id)) throw new Error("DISPATCH_UOM_METADATA_INVALID");
    return [id, parseRouteLoadUom(row)];
  }));
}

export function formatRouteLoadQuantity(value: Quantity, unit: RouteLoadUom): string {
  if (unit.display_uom_name && unit.display_factor_to_base) {
    return formatCommercialQuantity(
      value, unit.display_uom_name, unit.base_uom_name, unit.display_factor_to_base,
    ).primary;
  }
  return formatQuantity(value, unit.base_uom_name);
}

export function routeLoadReview(current: Quantity, target: Quantity, unit: RouteLoadUom) {
  const normalized = validateVariantQuantity(
    target, unit.quantity_scale, unit.quantity_step, "inventory_base", true,
  );
  const delta = subtractQuantity(normalized, current);
  const comparison = compareQuantity(delta, "0");
  return {
    delta,
    absoluteDelta: absoluteQuantity(delta),
    direction: comparison > 0 ? "ADD" as const :
      comparison < 0 ? "UNLOAD" as const : "UNCHANGED" as const,
  };
}

export function buildRouteLoadBaseTargets(
  targets: Record<string, Quantity>,
  units: Record<string, RouteLoadUom>,
): Record<string, Quantity> {
  const result: Record<string, Quantity> = {};
  for (const [id, raw] of Object.entries(targets)) {
    if (!units[id]) throw new Error("DISPATCH_UOM_METADATA_MISSING");
    const quantity = validateVariantQuantity(
      raw, units[id].quantity_scale, units[id].quantity_step,
      "inventory_base", true,
    );
    if (compareQuantity(quantity, "0") > 0) result[id] = quantity;
  }
  return result;
}
