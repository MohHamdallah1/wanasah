import {
  addQuantity,
  compareQuantity,
  isZeroQuantity,
  subtractQuantity,
  type Quantity,
} from "@/lib/quantity";
import type {
  ProductQualityBatch,
  ProductQualityPage,
  QualityDispatchPurpose,
  QualityStockStatus,
  QualityTerminalAction,
} from "./wholeProductQualityContract";

export type QualityActionLine = {
  batchId: number;
  batchNumber: string;
  expiryDate: string | null;
  stockStatus: QualityStockStatus;
  eligibleQuantity: Quantity;
};

export type ProductQualityLocation = {
  locationId: number;
  locationName: string;
  locationType: "WAREHOUSE" | "VEHICLE";
  onHandQuantity: Quantity;
  reservedQuantity: Quantity;
  movableQuantity: Quantity;
  dispatch: Record<QualityDispatchPurpose, QualityActionLine[]>;
  terminal: Record<QualityTerminalAction, QualityActionLine[]>;
  setupRequired: Record<QualityDispatchPurpose, boolean>;
};

const zero = "0" as Quantity;

const total = (lines: QualityActionLine[]): Quantity =>
  lines.reduce((sum, line) => addQuantity(sum, line.eligibleQuantity), zero);

export const actionTotal = total;

export function aggregateProductQualityLocations(pages: ProductQualityPage[]): ProductQualityLocation[] {
  const map = new Map<number, ProductQualityLocation>();
  for (const page of pages) {
    for (const batch of page.batches) {
      for (const source of batch.sources) {
        let location = map.get(source.locationId);
        if (!location) {
          location = {
            locationId: source.locationId,
            locationName: source.locationName,
            locationType: source.locationType,
            onHandQuantity: zero,
            reservedQuantity: zero,
            movableQuantity: zero,
            dispatch: { DISPOSAL: [], RETURN_TO_VENDOR: [] },
            terminal: { CONFIRM_DISPOSAL: [], CONFIRM_VENDOR_HANDOVER: [] },
            setupRequired: { DISPOSAL: false, RETURN_TO_VENDOR: false },
          };
          map.set(source.locationId, location);
        }
        for (const status of source.statuses) {
          location.onHandQuantity = addQuantity(location.onHandQuantity, status.onHandQuantity);
          location.reservedQuantity = addQuantity(location.reservedQuantity, status.reservedQuantity);
          location.movableQuantity = addQuantity(location.movableQuantity, status.movableQuantity);
          for (const action of status.dispatchActions) {
            if (action.reasonCode === "NO_CONFIGURED_DESTINATION") {
              location.setupRequired[action.action] = true;
            }
            if (!action.allowed || isZeroQuantity(action.eligibleQuantity)) continue;
            location.dispatch[action.action].push({
              batchId: batch.batchId,
              batchNumber: batch.batchNumber,
              expiryDate: batch.expiryDate,
              stockStatus: status.stockStatus,
              eligibleQuantity: action.eligibleQuantity,
            });
          }
          for (const action of status.terminalActions) {
            if (!action.allowed || isZeroQuantity(action.eligibleQuantity)) continue;
            location.terminal[action.action].push({
              batchId: batch.batchId,
              batchNumber: batch.batchNumber,
              expiryDate: batch.expiryDate,
              stockStatus: status.stockStatus,
              eligibleQuantity: action.eligibleQuantity,
            });
          }
        }
      }
    }
  }
  return [...map.values()]
    .sort((a, b) => a.locationName.localeCompare(b.locationName, undefined, { numeric: true }));
}

const lineOrder = (left: QualityActionLine, right: QualityActionLine) => {
  const leftExpiry = left.expiryDate ?? "9999-12-31";
  const rightExpiry = right.expiryDate ?? "9999-12-31";
  return leftExpiry.localeCompare(rightExpiry) || left.batchId - right.batchId || left.stockStatus.localeCompare(right.stockStatus);
};

export function allocateRequestedQuantity(
  lines: QualityActionLine[],
  requested: Quantity,
): Array<QualityActionLine & { quantity: Quantity }> {
  if (compareQuantity(requested, "0") <= 0 || compareQuantity(requested, total(lines)) > 0) {
    throw new Error("QUALITY_ACTION_QUANTITY_OUT_OF_RANGE");
  }
  let remaining = requested;
  const allocations: Array<QualityActionLine & { quantity: Quantity }> = [];
  for (const line of [...lines].sort(lineOrder)) {
    if (isZeroQuantity(remaining)) break;
    const quantity = compareQuantity(line.eligibleQuantity, remaining) <= 0
      ? line.eligibleQuantity
      : remaining;
    allocations.push({ ...line, quantity });
    remaining = subtractQuantity(remaining, quantity);
  }
  if (!isZeroQuantity(remaining)) throw new Error("QUALITY_ACTION_ALLOCATION_INCOMPLETE");
  return allocations;
}

export function firstBaseIdentity(pages: ProductQualityPage[]): { baseUomId: number; baseUomCode: string } | null {
  const page = pages[0];
  return page ? { baseUomId: page.baseUomId, baseUomCode: page.baseUomCode } : null;
}
