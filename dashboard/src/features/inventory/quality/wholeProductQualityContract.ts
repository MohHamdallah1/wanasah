import { parseQuantity, type Quantity } from "@/lib/quantity";

export type QualityStockStatus =
  | "AVAILABLE"
  | "QUARANTINED"
  | "BLOCKED"
  | "RECALLED"
  | "DAMAGED"
  | "DISPOSAL_PENDING";

export type QualityDispatchPurpose = "DISPOSAL" | "RETURN_TO_VENDOR";
export type QualityTerminalAction = "CONFIRM_DISPOSAL" | "CONFIRM_VENDOR_HANDOVER";

export type QualityActionAvailability<T extends string> = {
  action: T;
  allowed: boolean;
  eligibleQuantity: Quantity;
  reasonCode: string;
};

export type ProductQualityStatus = {
  stockStatus: QualityStockStatus;
  onHandQuantity: Quantity;
  reservedQuantity: Quantity;
  movableQuantity: Quantity;
  dispatchActions: QualityActionAvailability<QualityDispatchPurpose>[];
  terminalActions: QualityActionAvailability<QualityTerminalAction>[];
};

export type ProductQualitySource = {
  locationId: number;
  locationName: string;
  locationType: "WAREHOUSE" | "VEHICLE";
  statuses: ProductQualityStatus[];
};

export type ProductQualityBatch = {
  batchId: number;
  batchNumber: string;
  expiryDate: string | null;
  baseUomId: number;
  baseUomCode: string;
  sources: ProductQualitySource[];
};

export type ProductQualityPage = {
  productVariantId: number;
  baseUomId: number;
  baseUomCode: string;
  batches: ProductQualityBatch[];
  nextCursor: number | null;
  hasMore: boolean;
};

const invalid = (): never => {
  const error = new Error("PRODUCT_QUALITY_ACTIONS_RESPONSE_INVALID") as Error & { code: string };
  error.code = "PRODUCT_QUALITY_ACTIONS_RESPONSE_INVALID";
  throw error;
};

const positiveInt = (value: unknown): number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0
    ? value
    : invalid();

const text = (value: unknown, max: number): string =>
  typeof value === "string" && value.trim() && value.length <= max
    ? value.trim()
    : invalid();

const quantity = (value: unknown, field: string, allowZero = true): Quantity => {
  try {
    return parseQuantity(value, field, { allowZero });
  } catch {
    return invalid();
  }
};

const stockStatuses = new Set<QualityStockStatus>([
  "AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING",
]);
const dispatchPurposes = new Set<QualityDispatchPurpose>(["DISPOSAL", "RETURN_TO_VENDOR"]);
const terminalActions = new Set<QualityTerminalAction>(["CONFIRM_DISPOSAL", "CONFIRM_VENDOR_HANDOVER"]);

export function parseProductQualityPage(raw: unknown): ProductQualityPage {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  const productVariantId = positiveInt(row.product_variant_id);
  const baseUomId = positiveInt(row.base_uom_id);
  const baseUomCode = text(row.base_uom_code, 20);
  if (row.operational_hold !== "RECALL" || !Array.isArray(row.batches) || row.batches.length > 50 || typeof row.has_more !== "boolean") return invalid();

  const seenBatches = new Set<number>();
  const batches = row.batches.map((rawBatch) => {
    if (!rawBatch || typeof rawBatch !== "object" || Array.isArray(rawBatch)) return invalid();
    const batch = rawBatch as Record<string, unknown>;
    const batchId = positiveInt(batch.batch_id);
    if (seenBatches.has(batchId) || positiveInt(batch.product_variant_id) !== productVariantId || positiveInt(batch.base_uom_id) !== baseUomId || text(batch.base_uom_code, 20) !== baseUomCode || !Array.isArray(batch.sources) || batch.sources.length > 500) return invalid();
    seenBatches.add(batchId);
    const seenLocations = new Set<number>();
    const sources = batch.sources.map((rawSource) => {
      if (!rawSource || typeof rawSource !== "object" || Array.isArray(rawSource)) return invalid();
      const source = rawSource as Record<string, unknown>;
      const locationId = positiveInt(source.location_id);
      if (seenLocations.has(locationId) || (source.location_type !== "WAREHOUSE" && source.location_type !== "VEHICLE") || !Array.isArray(source.statuses) || source.statuses.length > 6) return invalid();
      seenLocations.add(locationId);
      const seenStatuses = new Set<string>();
      const statuses = source.statuses.map((rawStatus) => {
        if (!rawStatus || typeof rawStatus !== "object" || Array.isArray(rawStatus)) return invalid();
        const status = rawStatus as Record<string, unknown>;
        const stockStatus = status.stock_status as QualityStockStatus;
        if (!stockStatuses.has(stockStatus) || seenStatuses.has(stockStatus) || !Array.isArray(status.special_actions) || !Array.isArray(status.terminal_actions)) return invalid();
        seenStatuses.add(stockStatus);
        const dispatchActions = status.special_actions
          .filter((rawAction) => rawAction && typeof rawAction === "object" && !Array.isArray(rawAction) && dispatchPurposes.has((rawAction as Record<string, unknown>).purpose as QualityDispatchPurpose))
          .map((rawAction) => {
            const action = rawAction as Record<string, unknown>;
            if (typeof action.allowed !== "boolean" || typeof action.reason_code !== "string") return invalid();
            return {
              action: action.purpose as QualityDispatchPurpose,
              allowed: action.allowed,
              eligibleQuantity: quantity(action.eligible_quantity, "eligible_quantity"),
              reasonCode: action.reason_code,
            };
          });
        const terminal = status.terminal_actions
          .filter((rawAction) => rawAction && typeof rawAction === "object" && !Array.isArray(rawAction) && terminalActions.has((rawAction as Record<string, unknown>).action as QualityTerminalAction))
          .map((rawAction) => {
            const action = rawAction as Record<string, unknown>;
            if (typeof action.allowed !== "boolean" || typeof action.reason_code !== "string") return invalid();
            return {
              action: action.action as QualityTerminalAction,
              allowed: action.allowed,
              eligibleQuantity: quantity(action.eligible_quantity, "terminal_eligible_quantity"),
              reasonCode: action.reason_code,
            };
          });
        return {
          stockStatus,
          onHandQuantity: quantity(status.on_hand_quantity, "on_hand_quantity"),
          reservedQuantity: quantity(status.reserved_quantity, "reserved_quantity"),
          movableQuantity: quantity(status.movable_quantity, "movable_quantity"),
          dispatchActions,
          terminalActions: terminal,
        };
      });
      return {
        locationId,
        locationName: text(source.location_name, 200),
        locationType: source.location_type as ProductQualitySource["locationType"],
        statuses,
      };
    });
    const expiryDate = batch.expiry_date === null ? null : text(batch.expiry_date, 32);
    return {
      batchId,
      batchNumber: text(batch.batch_number, 100),
      expiryDate,
      baseUomId,
      baseUomCode,
      sources,
    };
  });

  const nextCursor = row.next_cursor === null ? null : positiveInt(row.next_cursor);
  if (row.has_more !== (nextCursor !== null)) return invalid();
  return { productVariantId, baseUomId, baseUomCode, batches, nextCursor, hasMore: row.has_more };
}
