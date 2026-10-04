import {
  compareQuantity,
  parseQuantity,
  type Quantity,
} from "../quantity";

export type BatchStockStatus =
  | "AVAILABLE"
  | "QUARANTINED"
  | "BLOCKED"
  | "RECALLED"
  | "DAMAGED"
  | "DISPOSAL_PENDING";

export type BatchStockSourceStatus = {
  stock_status: BatchStockStatus;
  on_hand_quantity: Quantity;
  reserved_quantity: Quantity;
  movable_quantity: Quantity;
};

export type BatchStockSource = {
  location_id: number;
  location_name: string;
  location_type: "WAREHOUSE" | "VEHICLE";
  can_send: boolean;
  statuses: BatchStockSourceStatus[];
};

export type BatchStockSources = {
  batch_id: number;
  product_variant_id: number;
  base_uom_id: number;
  operational_hold: "NONE" | "SALES_HOLD" | "RECALL";
  sources: BatchStockSource[];
};

const invalid = (): never => {
  const error = new Error(
    "BATCH_STOCK_SOURCES_RESPONSE_INVALID",
  ) as Error & { code: string };
  error.code = "BATCH_STOCK_SOURCES_RESPONSE_INVALID";
  throw error;
};

const positiveInt = (value: unknown) =>
  typeof value === "number" &&
  Number.isSafeInteger(value) &&
  value > 0
    ? value
    : invalid();

const statuses = new Set<BatchStockStatus>([
  "AVAILABLE",
  "QUARANTINED",
  "BLOCKED",
  "RECALLED",
  "DAMAGED",
  "DISPOSAL_PENDING",
]);

export function parseBatchStockSources(
  raw: unknown,
): BatchStockSources {
  if (
    !raw ||
    typeof raw !== "object" ||
    Array.isArray(raw)
  ) {
    return invalid();
  }
  const row = raw as Record<string, unknown>;
  if (
    !Array.isArray(row.sources) ||
    row.sources.length > 500 ||
    (row.operational_hold !== "NONE" &&
      row.operational_hold !== "SALES_HOLD" &&
      row.operational_hold !== "RECALL")
  ) {
    return invalid();
  }

  const locationIds = new Set<number>();
  const parsedSources = row.sources.map((rawSource) => {
    if (
      !rawSource ||
      typeof rawSource !== "object" ||
      Array.isArray(rawSource)
    ) {
      return invalid();
    }
    const source = rawSource as Record<string, unknown>;
    const locationId = positiveInt(source.location_id);
    if (locationIds.has(locationId)) return invalid();
    locationIds.add(locationId);
    if (
      typeof source.location_name !== "string" ||
      !source.location_name.trim() ||
      source.location_name.length > 200 ||
      (source.location_type !== "WAREHOUSE" &&
        source.location_type !== "VEHICLE") ||
      typeof source.can_send !== "boolean" ||
      !Array.isArray(source.statuses) ||
      source.statuses.length > 6
    ) {
      return invalid();
    }

    const seenStatuses = new Set<BatchStockStatus>();
    const parsedStatuses = source.statuses.map((rawStatus) => {
      if (
        !rawStatus ||
        typeof rawStatus !== "object" ||
        Array.isArray(rawStatus)
      ) {
        return invalid();
      }
      const statusRow = rawStatus as Record<string, unknown>;
      const stockStatus = statusRow.stock_status as BatchStockStatus;
      if (
        !statuses.has(stockStatus) ||
        seenStatuses.has(stockStatus)
      ) {
        return invalid();
      }
      seenStatuses.add(stockStatus);

      let onHand: Quantity;
      let reserved: Quantity;
      let movable: Quantity;
      try {
        onHand = parseQuantity(
          statusRow.on_hand_quantity,
          "on_hand_quantity",
          { allowZero: true },
        );
        reserved = parseQuantity(
          statusRow.reserved_quantity,
          "reserved_quantity",
          { allowZero: true },
        );
        movable = parseQuantity(
          statusRow.movable_quantity,
          "movable_quantity",
          { allowZero: true },
        );
      } catch {
        return invalid();
      }
      if (
        compareQuantity(reserved, onHand) > 0 ||
        compareQuantity(movable, onHand) > 0
      ) {
        return invalid();
      }
      return {
        stock_status: stockStatus,
        on_hand_quantity: onHand,
        reserved_quantity: reserved,
        movable_quantity: movable,
      };
    });

    return {
      location_id: locationId,
      location_name: source.location_name,
      location_type: source.location_type,
      can_send: source.can_send,
      statuses: parsedStatuses,
    };
  });

  return {
    batch_id: positiveInt(row.batch_id),
    product_variant_id: positiveInt(row.product_variant_id),
    base_uom_id: positiveInt(row.base_uom_id),
    operational_hold: row.operational_hold,
    sources: parsedSources,
  };
}
