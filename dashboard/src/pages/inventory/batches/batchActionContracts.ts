import {
  compareQuantity,
  parseQuantity,
  type Quantity,
} from "@/lib/quantity";
import type { BatchStockStatus } from "./batchStockSourcesContract";

export type StatusChangeDestination =
  | "AVAILABLE"
  | "QUARANTINED"
  | "BLOCKED"
  | "RECALLED";

export type StatusChangeReasonCode =
  | "ALLOWED"
  | "PERMISSION_REQUIRED"
  | "NO_ELIGIBLE_QUANTITY"
  | "BATCH_NOT_SELLABLE";

export type StatusChangeAvailability = {
  destination_status: StatusChangeDestination;
  allowed: boolean;
  eligible_quantity: Quantity;
  reason_code: StatusChangeReasonCode;
};

export type WarehouseBatchActionSourceStatus = {
  stock_status: BatchStockStatus;
  on_hand_quantity: Quantity;
  reserved_quantity: Quantity;
  movable_quantity: Quantity;
  status_change_actions: StatusChangeAvailability[];
};

export type WarehouseBatchActionSource = {
  location_id: number;
  location_name: string;
  product_variant_id: number;
  batch_id: number;
  base_uom_id: number;
  base_uom_code: string;
  quantity_scale: number;
  quantity_step: Quantity;
  statuses: WarehouseBatchActionSourceStatus[];
};

const invalid = (): never => {
  const error = new Error("BATCH_ACTION_SOURCE_RESPONSE_INVALID") as Error & {
    code: string;
  };
  error.code = "BATCH_ACTION_SOURCE_RESPONSE_INVALID";
  throw error;
};

const positiveInt = (value: unknown): number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0
    ? value
    : invalid();

const text = (value: unknown, max: number): string =>
  typeof value === "string" && value.trim() && value.length <= max
    ? value
    : invalid();

const stockStatuses = new Set<BatchStockStatus>([
  "AVAILABLE",
  "QUARANTINED",
  "BLOCKED",
  "RECALLED",
  "DAMAGED",
  "DISPOSAL_PENDING",
]);
const destinations = new Set<StatusChangeDestination>([
  "AVAILABLE",
  "QUARANTINED",
  "BLOCKED",
  "RECALLED",
]);
const reasons = new Set<StatusChangeReasonCode>([
  "ALLOWED",
  "PERMISSION_REQUIRED",
  "NO_ELIGIBLE_QUANTITY",
  "BATCH_NOT_SELLABLE",
]);

export const parseWarehouseBatchActionSource = (
  raw: unknown,
  expected: {
    locationId: number;
    productVariantId: number;
    batchId: number;
  },
): WarehouseBatchActionSource => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  const locationId = positiveInt(row.location_id);
  const productVariantId = positiveInt(row.product_variant_id);
  const batchId = positiveInt(row.batch_id);
  const quantityScale = row.quantity_scale;
  if (
    locationId !== expected.locationId ||
    productVariantId !== expected.productVariantId ||
    batchId !== expected.batchId ||
    typeof quantityScale !== "number" ||
    !Number.isInteger(quantityScale) ||
    quantityScale < 0 ||
    quantityScale > 6 ||
    !Array.isArray(row.statuses) ||
    row.statuses.length > 6
  ) {
    return invalid();
  }

  let quantityStep: Quantity;
  try {
    quantityStep = parseQuantity(row.quantity_step, "quantity_step");
  } catch {
    return invalid();
  }

  const seenStatuses = new Set<BatchStockStatus>();
  const statuses = row.statuses.map((rawStatus) => {
    if (!rawStatus || typeof rawStatus !== "object" || Array.isArray(rawStatus)) {
      return invalid();
    }
    const status = rawStatus as Record<string, unknown>;
    const stockStatus = status.stock_status as BatchStockStatus;
    if (!stockStatuses.has(stockStatus) || seenStatuses.has(stockStatus)) return invalid();
    seenStatuses.add(stockStatus);

    let onHand: Quantity;
    let reserved: Quantity;
    let movable: Quantity;
    try {
      onHand = parseQuantity(status.on_hand_quantity, "on_hand_quantity", { allowZero: true });
      reserved = parseQuantity(status.reserved_quantity, "reserved_quantity", { allowZero: true });
      movable = parseQuantity(status.movable_quantity, "movable_quantity", { allowZero: true });
    } catch {
      return invalid();
    }
    if (compareQuantity(reserved, onHand) > 0 || compareQuantity(movable, onHand) > 0) {
      return invalid();
    }
    if (!Array.isArray(status.status_change_actions) || status.status_change_actions.length > 3) {
      return invalid();
    }
    const seenDestinations = new Set<StatusChangeDestination>();
    const actions = status.status_change_actions.map((rawAction) => {
      if (!rawAction || typeof rawAction !== "object" || Array.isArray(rawAction)) return invalid();
      const action = rawAction as Record<string, unknown>;
      const destination = action.destination_status as StatusChangeDestination;
      const reason = action.reason_code as StatusChangeReasonCode;
      if (
        !destinations.has(destination) ||
        seenDestinations.has(destination) ||
        typeof action.allowed !== "boolean" ||
        !reasons.has(reason) ||
        action.allowed !== (reason === "ALLOWED")
      ) {
        return invalid();
      }
      seenDestinations.add(destination);
      let eligible: Quantity;
      try {
        eligible = parseQuantity(action.eligible_quantity, "eligible_quantity", { allowZero: true });
      } catch {
        return invalid();
      }
      if (compareQuantity(eligible, movable) > 0) return invalid();
      return {
        destination_status: destination,
        allowed: action.allowed as boolean,
        eligible_quantity: eligible,
        reason_code: reason,
      };
    });
    return {
      stock_status: stockStatus,
      on_hand_quantity: onHand,
      reserved_quantity: reserved,
      movable_quantity: movable,
      status_change_actions: actions,
    };
  });

  return {
    location_id: locationId,
    location_name: text(row.location_name, 200),
    product_variant_id: productVariantId,
    batch_id: batchId,
    base_uom_id: positiveInt(row.base_uom_id),
    base_uom_code: text(row.base_uom_code, 20),
    quantity_scale: quantityScale,
    quantity_step: quantityStep,
    statuses,
  };
};

export type InventoryStatusChangeResponse = {
  movement_id: number;
  source_status: BatchStockStatus;
  destination_status: BatchStockStatus;
};

export const parseInventoryStatusChangeResponse = (
  raw: unknown,
  expected: { source: BatchStockStatus; destination: BatchStockStatus },
): InventoryStatusChangeResponse => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  const source = row.source_status as BatchStockStatus;
  const destination = row.destination_status as BatchStockStatus;
  if (
    !stockStatuses.has(source) ||
    !stockStatuses.has(destination) ||
    source !== expected.source ||
    destination !== expected.destination
  ) {
    return invalid();
  }
  return {
    movement_id: positiveInt(row.movement_id),
    source_status: source,
    destination_status: destination,
  };
};
