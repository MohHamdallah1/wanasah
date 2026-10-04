export type ArchiveOwnerTarget =
  | { kind: "capability-gap"; reason: "PRODUCT_LOCATION_REFERENCES" | "INVENTORY_SOURCE" | "TRANSIT_STATE" | "STOCKTAKE_STATE" }
  | { kind: "batch"; operation_id: number; location_id: number; batch_id: number }
  | { kind: "transfer"; operation_id: number; location_id: number; reference: string }
  | { kind: "stocktake" | "product-location"; operation_id: number; location_id: number }
  | { kind: "route-load" | "handshake"; operation_id: number; route_id: number }
  | { kind: "shortage" | "settlement"; operation_id: number };

const positiveId = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;

/** Fail closed for absent/new/malformed navigation hints, never infer authority. */
export function parseArchiveOwnerTarget(raw: unknown): ArchiveOwnerTarget | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  if (row.kind === "capability-gap" && typeof row.reason === "string" && ["PRODUCT_LOCATION_REFERENCES", "INVENTORY_SOURCE", "TRANSIT_STATE", "STOCKTAKE_STATE"].includes(row.reason)) {
    return { kind: row.kind, reason: row.reason as Extract<ArchiveOwnerTarget, { kind: "capability-gap" }>["reason"] };
  }
  if (!positiveId(row.operation_id)) return null;
  const operation_id = row.operation_id;
  if (row.kind === "shortage" || row.kind === "settlement") return { kind: row.kind, operation_id };
  if (row.kind === "route-load" || row.kind === "handshake") {
    return positiveId(row.route_id) ? { kind: row.kind, operation_id, route_id: row.route_id } : null;
  }
  if (!positiveId(row.location_id)) return null;
  const location_id = row.location_id;
  if (row.kind === "stocktake" || row.kind === "product-location") return { kind: row.kind, operation_id, location_id };
  if (row.kind === "batch" && positiveId(row.batch_id)) return { kind: row.kind, operation_id, location_id, batch_id: row.batch_id };
  if (row.kind === "transfer" && typeof row.reference === "string" && row.reference.length > 0 && row.reference.length <= 100) {
    return { kind: row.kind, operation_id, location_id, reference: row.reference };
  }
  return null;
}
