import { parseQuantity, type Quantity } from "@/lib/quantity";

export type WholeProductCostingMethod = "MOVING_AVERAGE" | "FIFO";
export type WholeProductQualityPreviewLocationType = "WAREHOUSE" | "VEHICLE" | "IN_TRANSIT" | "SCRAP";

export type WholeProductQualityPreviewLocation = {
  locationId: number;
  locationName: string;
  locationType: WholeProductQualityPreviewLocationType;
  quantity: Quantity;
};

export type WholeProductQualityPreviewBatch = {
  batchId: number;
  batchNumber: string;
  quantity: Quantity;
};

export type WholeProductQualityValuationLine = {
  batchId: number;
  batchNumber: string;
  quantity: Quantity;
  unitCost: string;
  bookValue: string;
};

export type WholeProductQualityPreview = {
  productVariantId: number;
  issueReason: string | null;
  currencyCode: string;
  costingMethod: WholeProductCostingMethod | null;
  valuationAvailable: boolean;
  valuationReason: string | null;
  totalQuantity: Quantity;
  totalReservedQuantity: Quantity;
  totalBookValue: string | null;
  averageUnitCost: string | null;
  locations: WholeProductQualityPreviewLocation[];
  batches: WholeProductQualityPreviewBatch[];
  valuationLines: WholeProductQualityValuationLine[];
  blockerCodes: string[];
};

const MONEY_PATTERN = /^\d+(?:\.\d{1,6})?$/;
const locationTypes = new Set<WholeProductQualityPreviewLocationType>([
  "WAREHOUSE",
  "VEHICLE",
  "IN_TRANSIT",
  "SCRAP",
]);

const invalid = (): never => {
  const error = new Error("WHOLE_PRODUCT_QUALITY_PREVIEW_INVALID") as Error & { code: string };
  error.code = "WHOLE_PRODUCT_QUALITY_PREVIEW_INVALID";
  throw error;
};

const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : invalid();

const positiveInt = (value: unknown): number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0
    ? value
    : invalid();

const text = (value: unknown, max: number): string =>
  typeof value === "string" && value.trim().length > 0 && value.trim().length <= max
    ? value.trim()
    : invalid();

const optionalText = (value: unknown, max: number): string | null =>
  value === null ? null : text(value, max);

const quantity = (value: unknown, field: string): Quantity => {
  try {
    return parseQuantity(value, field, { allowZero: false });
  } catch {
    return invalid();
  }
};

const nonnegativeQuantity = (value: unknown, field: string): Quantity => {
  try {
    return parseQuantity(value, field, { allowZero: true });
  } catch {
    return invalid();
  }
};

const money = (value: unknown): string =>
  typeof value === "string" && MONEY_PATTERN.test(value)
    ? value
    : invalid();

export function parseWholeProductQualityPreview(raw: unknown): WholeProductQualityPreview {
  const row = record(raw);
  const productVariantId = positiveInt(row.product_variant_id);
  const issueReason = optionalText(row.issue_reason, 1000);
  const currencyCode = text(row.currency_code, 10).toUpperCase();
  const costingMethod = row.costing_method === null
    ? null
    : row.costing_method === "MOVING_AVERAGE" || row.costing_method === "FIFO"
      ? row.costing_method
      : invalid();
  if (typeof row.valuation_available !== "boolean") return invalid();
  const valuationAvailable = row.valuation_available;
  const valuationReason = row.valuation_reason === null
    ? null
    : text(row.valuation_reason, 100);
  const totalQuantity = quantity(row.total_quantity, "total_quantity");
  const totalReservedQuantity = nonnegativeQuantity(
    row.total_reserved_quantity,
    "total_reserved_quantity",
  );
  const totalBookValue = row.total_book_value === null ? null : money(row.total_book_value);
  const averageUnitCost = row.average_unit_cost === null ? null : money(row.average_unit_cost);

  if (!Array.isArray(row.locations) || row.locations.length === 0 || row.locations.length > 100) return invalid();
  const seenLocations = new Set<number>();
  const locations = row.locations.map((rawLocation) => {
    const location = record(rawLocation);
    const locationId = positiveInt(location.location_id);
    if (seenLocations.has(locationId)) return invalid();
    seenLocations.add(locationId);
    if (!locationTypes.has(location.location_type as WholeProductQualityPreviewLocationType)) return invalid();
    return {
      locationId,
      locationName: text(location.location_name, 200),
      locationType: location.location_type as WholeProductQualityPreviewLocationType,
      quantity: quantity(location.quantity, "location.quantity"),
    } satisfies WholeProductQualityPreviewLocation;
  });

  if (!Array.isArray(row.batches) || row.batches.length === 0 || row.batches.length > 5000) return invalid();
  const seenBatches = new Set<number>();
  const batches = row.batches.map((rawBatch) => {
    const batch = record(rawBatch);
    const batchId = positiveInt(batch.batch_id);
    if (seenBatches.has(batchId)) return invalid();
    seenBatches.add(batchId);
    return {
      batchId,
      batchNumber: text(batch.batch_number, 100),
      quantity: quantity(batch.quantity, "batch.quantity"),
    } satisfies WholeProductQualityPreviewBatch;
  });

  if (!Array.isArray(row.valuation_lines) || row.valuation_lines.length > 5000) return invalid();
  const seenValuationBatches = new Set<number>();
  const valuationLines = row.valuation_lines.map((rawLine) => {
    const line = record(rawLine);
    const batchId = positiveInt(line.batch_id);
    if (seenValuationBatches.has(batchId)) return invalid();
    seenValuationBatches.add(batchId);
    return {
      batchId,
      batchNumber: text(line.batch_number, 100),
      quantity: quantity(line.quantity, "valuation.quantity"),
      unitCost: money(line.unit_cost),
      bookValue: money(line.book_value),
    } satisfies WholeProductQualityValuationLine;
  });

  if (!Array.isArray(row.blocker_codes) || row.blocker_codes.length > 20) return invalid();
  const blockerCodes = row.blocker_codes.map((value) => text(value, 100));
  if (new Set(blockerCodes).size !== blockerCodes.length) return invalid();

  if (valuationAvailable) {
    if (
      costingMethod === null ||
      totalBookValue === null ||
      averageUnitCost === null ||
      valuationReason !== null ||
      valuationLines.length === 0
    ) return invalid();
  } else if (totalBookValue !== null || averageUnitCost !== null || valuationLines.length !== 0) {
    return invalid();
  }

  return {
    productVariantId,
    issueReason,
    currencyCode,
    costingMethod,
    valuationAvailable,
    valuationReason,
    totalQuantity,
    totalReservedQuantity,
    totalBookValue,
    averageUnitCost,
    locations,
    batches,
    valuationLines,
    blockerCodes,
  };
}
