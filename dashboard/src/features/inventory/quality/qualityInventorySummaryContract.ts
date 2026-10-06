import { parseQuantity } from "@/lib/quantity";

export type QualityInventoryLocationSummary = {
  location_id: number;
  location_name: string;
  location_type: "WAREHOUSE" | "VEHICLE";
  on_hand_quantity: string;
  reserved_quantity: string;
};

export type QualityInventorySummary = {
  total_on_hand_quantity: string;
  total_reserved_quantity: string;
  batch_count: number;
  source_count: number;
  locations_preview: QualityInventoryLocationSummary[];
  locations_truncated: boolean;
};

const invalid = (): never => {
  const error = new Error("INVENTORY_QUALITY_SUMMARY_INVALID") as Error & { code: string };
  error.code = "INVENTORY_QUALITY_SUMMARY_INVALID";
  throw error;
};

const positiveInt = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) return invalid();
  return value;
};

const nonnegativeInt = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) return invalid();
  return value;
};

const nonnegativeQuantity = (value: unknown, field: string): string => {
  try {
    return parseQuantity(value, field, { allowZero: true });
  } catch {
    return invalid();
  }
};

export function parseQualityInventorySummary(raw: unknown): QualityInventorySummary {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  if (
    !Array.isArray(row.locations_preview) ||
    row.locations_preview.length > 8 ||
    typeof row.locations_truncated !== "boolean"
  ) return invalid();

  const locations = row.locations_preview.map((rawLocation) => {
    if (!rawLocation || typeof rawLocation !== "object" || Array.isArray(rawLocation)) return invalid();
    const location = rawLocation as Record<string, unknown>;
    if (
      typeof location.location_name !== "string" ||
      !location.location_name.trim() ||
      location.location_name.length > 200 ||
      (location.location_type !== "WAREHOUSE" && location.location_type !== "VEHICLE")
    ) return invalid();
    return {
      location_id: positiveInt(location.location_id),
      location_name: location.location_name.trim(),
      location_type: location.location_type,
      on_hand_quantity: nonnegativeQuantity(location.on_hand_quantity, "location_on_hand_quantity"),
      reserved_quantity: nonnegativeQuantity(location.reserved_quantity, "location_reserved_quantity"),
    };
  });

  const sourceCount = nonnegativeInt(row.source_count);
  if (locations.length > sourceCount || (!row.locations_truncated && locations.length !== sourceCount)) {
    return invalid();
  }
  return {
    total_on_hand_quantity: nonnegativeQuantity(row.total_on_hand_quantity, "total_on_hand_quantity"),
    total_reserved_quantity: nonnegativeQuantity(row.total_reserved_quantity, "total_reserved_quantity"),
    batch_count: nonnegativeInt(row.batch_count),
    source_count: sourceCount,
    locations_preview: locations,
    locations_truncated: row.locations_truncated,
  };
}
