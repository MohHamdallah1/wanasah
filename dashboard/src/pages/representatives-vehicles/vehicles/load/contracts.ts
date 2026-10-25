import type { Quantity } from "@/lib/quantity";

export type VehicleLoadMode = "DIRECT" | "ROUTE" | "SETTLEMENT_REQUIRED";
export type VehicleLoadStockStatus =
  | "AVAILABLE"
  | "QUARANTINED"
  | "BLOCKED"
  | "RECALLED"
  | "DAMAGED"
  | "DISPOSAL_PENDING";

export type VehicleLoadDirection = "ADD" | "UNLOAD";

export interface VehicleLoadItem {
  product_variant_id: number;
  product_name: string;
  sku: string | null;
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  quantity_scale: number;
  quantity_step: Quantity;
  stock_status: VehicleLoadStockStatus;
  on_hand_quantity: Quantity;
  reserved_quantity: Quantity;
  available_quantity: Quantity;
}

export interface VehicleLoadSnapshot {
  vehicle_id: number;
  mode: VehicleLoadMode;
  route_id: number | null;
  work_session_id: number | null;
  vehicle_operational: boolean;
  can_add: boolean;
  can_unload: boolean;
  items: VehicleLoadItem[];
}

export interface VehicleLoadWarehouse {
  id: number;
  name: string;
  code: string;
}

export interface VehicleLoadWarehousePage {
  items: VehicleLoadWarehouse[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface VehicleLoadSourceItem {
  product_variant_id: number;
  product_name: string;
  sku: string | null;
  base_uom_id: number;
  base_uom_code: string;
  base_uom_name: string;
  quantity_scale: number;
  quantity_step: Quantity;
  available_quantity: Quantity;
}

export interface VehicleLoadSourcePage {
  items: VehicleLoadSourceItem[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface VehicleLoadMutationItem {
  product_variant_id: number;
  quantity: Quantity;
  stock_status?: VehicleLoadStockStatus;
}

export interface VehicleLoadMutationPayload {
  warehouse_id: number;
  items: VehicleLoadMutationItem[];
}

export interface VehicleLoadMutationResult {
  vehicle_id: number;
  warehouse_id: number;
  direction: VehicleLoadDirection;
  movement_count: number;
  message: string;
}

export type VehicleLoadAuthFetch = (
  path: string,
  options?: RequestInit,
) => Promise<unknown>;

export class VehicleLoadContractError extends Error {
  readonly code = "VEHICLE_LOAD_RESPONSE_INVALID";

  constructor() {
    super("VEHICLE_LOAD_RESPONSE_INVALID");
    this.name = "VehicleLoadContractError";
  }
}

const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new VehicleLoadContractError();
  }
  return value as Record<string, unknown>;
};

const positiveInt = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) {
    throw new VehicleLoadContractError();
  }
  return value;
};

const nullablePositiveInt = (value: unknown): number | null =>
  value === null ? null : positiveInt(value);

const stringValue = (value: unknown): string => {
  if (typeof value !== "string") throw new VehicleLoadContractError();
  return value;
};

const nullableString = (value: unknown): string | null =>
  value === null ? null : stringValue(value);

const quantity = (value: unknown): Quantity => {
  if (typeof value !== "string" || !/^-?\d+(?:\.\d{1,6})?$/.test(value)) {
    throw new VehicleLoadContractError();
  }
  return value;
};

const stockStatus = (value: unknown): VehicleLoadStockStatus => {
  if (
    value !== "AVAILABLE" &&
    value !== "QUARANTINED" &&
    value !== "BLOCKED" &&
    value !== "RECALLED" &&
    value !== "DAMAGED" &&
    value !== "DISPOSAL_PENDING"
  ) {
    throw new VehicleLoadContractError();
  }
  return value;
};

export const parseVehicleLoadSnapshot = (value: unknown): VehicleLoadSnapshot => {
  const row = record(value);
  if (
    row.mode !== "DIRECT" &&
    row.mode !== "ROUTE" &&
    row.mode !== "SETTLEMENT_REQUIRED"
  ) {
    throw new VehicleLoadContractError();
  }
  if (
    typeof row.vehicle_operational !== "boolean" ||
    typeof row.can_add !== "boolean" ||
    typeof row.can_unload !== "boolean" ||
    !Array.isArray(row.items)
  ) {
    throw new VehicleLoadContractError();
  }
  return {
    vehicle_id: positiveInt(row.vehicle_id),
    mode: row.mode,
    route_id: nullablePositiveInt(row.route_id),
    work_session_id: nullablePositiveInt(row.work_session_id),
    vehicle_operational: row.vehicle_operational,
    can_add: row.can_add,
    can_unload: row.can_unload,
    items: row.items.map((raw) => {
      const item = record(raw);
      const scale = item.quantity_scale;
      if (typeof scale !== "number" || !Number.isInteger(scale) || scale < 0 || scale > 6) {
        throw new VehicleLoadContractError();
      }
      return {
        product_variant_id: positiveInt(item.product_variant_id),
        product_name: stringValue(item.product_name),
        sku: nullableString(item.sku),
        base_uom_id: positiveInt(item.base_uom_id),
        base_uom_code: stringValue(item.base_uom_code),
        base_uom_name: stringValue(item.base_uom_name),
        quantity_scale: scale,
        quantity_step: quantity(item.quantity_step),
        stock_status: stockStatus(item.stock_status),
        on_hand_quantity: quantity(item.on_hand_quantity),
        reserved_quantity: quantity(item.reserved_quantity),
        available_quantity: quantity(item.available_quantity),
      };
    }),
  };
};

export const parseVehicleLoadWarehousePage = (value: unknown): VehicleLoadWarehousePage => {
  const row = record(value);
  if (!Array.isArray(row.items) || typeof row.has_more !== "boolean") {
    throw new VehicleLoadContractError();
  }
  if (row.next_cursor !== null && typeof row.next_cursor !== "string") {
    throw new VehicleLoadContractError();
  }
  return {
    items: row.items.map((raw) => {
      const item = record(raw);
      return {
        id: positiveInt(item.id),
        name: stringValue(item.name),
        code: stringValue(item.code),
      };
    }),
    next_cursor: row.next_cursor as string | null,
    has_more: row.has_more,
  };
};

export const parseVehicleLoadSourcePage = (value: unknown): VehicleLoadSourcePage => {
  const row = record(value);
  if (!Array.isArray(row.items) || typeof row.has_more !== "boolean") {
    throw new VehicleLoadContractError();
  }
  if (row.next_cursor !== null && typeof row.next_cursor !== "string") {
    throw new VehicleLoadContractError();
  }
  return {
    items: row.items.map((raw) => {
      const item = record(raw);
      const scale = item.quantity_scale;
      if (typeof scale !== "number" || !Number.isInteger(scale) || scale < 0 || scale > 6) {
        throw new VehicleLoadContractError();
      }
      return {
        product_variant_id: positiveInt(item.product_variant_id),
        product_name: stringValue(item.product_name),
        sku: nullableString(item.sku),
        base_uom_id: positiveInt(item.base_uom_id),
        base_uom_code: stringValue(item.base_uom_code),
        base_uom_name: stringValue(item.base_uom_name),
        quantity_scale: scale,
        quantity_step: quantity(item.quantity_step),
        available_quantity: quantity(item.available_quantity),
      };
    }),
    next_cursor: row.next_cursor as string | null,
    has_more: row.has_more,
  };
};

export const parseVehicleLoadMutationResult = (value: unknown): VehicleLoadMutationResult => {
  const row = record(value);
  if (
    (row.direction !== "ADD" && row.direction !== "UNLOAD") ||
    typeof row.message !== "string"
  ) {
    throw new VehicleLoadContractError();
  }
  return {
    vehicle_id: positiveInt(row.vehicle_id),
    warehouse_id: positiveInt(row.warehouse_id),
    direction: row.direction,
    movement_count: positiveInt(row.movement_count),
    message: row.message,
  };
};
