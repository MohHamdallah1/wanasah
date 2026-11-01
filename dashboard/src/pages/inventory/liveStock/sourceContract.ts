import { compareQuantity, parseQuantity, type Quantity } from "@/lib/quantity";

export type LiveStockSourceStatusName =
  | "AVAILABLE"
  | "QUARANTINED"
  | "BLOCKED"
  | "RECALLED"
  | "DAMAGED"
  | "DISPOSAL_PENDING";

export type LiveStockReservationCoverage =
  | "NONE"
  | "COMPLETE"
  | "PARTIAL"
  | "UNRESOLVED";

export type LiveStockReservationOwner = {
  transfer_id: number;
  reference_number: string;
  quantity: Quantity;
};

export type LiveStockReservationEvidence = {
  coverage: LiveStockReservationCoverage;
  owners: LiveStockReservationOwner[];
  unattributed_quantity: Quantity;
  owners_truncated: boolean;
};

export type LiveStockWarehouseSourceStatus = {
  stock_status: LiveStockSourceStatusName;
  on_hand_quantity: Quantity;
  reserved_quantity: Quantity;
  movable_quantity: Quantity;
  reservation_evidence: LiveStockReservationEvidence;
};

export type LiveStockProductSaleGate = {
  location_id: number;
  product_variant_id: number;
  lifecycle_status: "DRAFT" | "ACTIVE" | "RETIRING" | "ARCHIVED";
  operational_hold: "NONE" | "SALES_HOLD" | "RECALL";
  lifecycle_revision: number;
};

export type LiveStockWarehouseSource = {
  location_id: number;
  location_name: string;
  product_variant_id: number;
  batch_id: number;
  statuses: LiveStockWarehouseSourceStatus[];
};

const invalid = (): never => {
  const error = new Error("LIVE_STOCK_SOURCE_RESPONSE_INVALID") as Error & {
    code: string;
  };
  error.code = "LIVE_STOCK_SOURCE_RESPONSE_INVALID";
  throw error;
};

const positiveInt = (value: unknown): number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0
    ? value
    : invalid();

const statuses = new Set<LiveStockSourceStatusName>([
  "AVAILABLE",
  "QUARANTINED",
  "BLOCKED",
  "RECALLED",
  "DAMAGED",
  "DISPOSAL_PENDING",
]);
const coverages = new Set<LiveStockReservationCoverage>([
  "NONE",
  "COMPLETE",
  "PARTIAL",
  "UNRESOLVED",
]);

export function parseLiveStockProductSaleGate(
  raw: unknown,
): LiveStockProductSaleGate {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  const lifecycle = row.lifecycle_status;
  const hold = row.operational_hold;
  if (
    lifecycle !== "DRAFT" &&
    lifecycle !== "ACTIVE" &&
    lifecycle !== "RETIRING" &&
    lifecycle !== "ARCHIVED"
  ) {
    return invalid();
  }
  if (hold !== "NONE" && hold !== "SALES_HOLD" && hold !== "RECALL") {
    return invalid();
  }
  return {
    location_id: positiveInt(row.location_id),
    product_variant_id: positiveInt(row.product_variant_id),
    lifecycle_status: lifecycle,
    operational_hold: hold,
    lifecycle_revision: positiveInt(row.lifecycle_revision),
  };
}


export function parseLiveStockWarehouseSource(
  raw: unknown,
): LiveStockWarehouseSource {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return invalid();
  const row = raw as Record<string, unknown>;
  if (
    typeof row.location_name !== "string" ||
    !row.location_name.trim() ||
    row.location_name.length > 200 ||
    !Array.isArray(row.statuses) ||
    row.statuses.length > 6
  ) {
    return invalid();
  }

  const seen = new Set<LiveStockSourceStatusName>();
  const parsedStatuses = row.statuses.map((rawStatus) => {
    if (!rawStatus || typeof rawStatus !== "object" || Array.isArray(rawStatus)) {
      return invalid();
    }
    const status = rawStatus as Record<string, unknown>;
    const name = status.stock_status as LiveStockSourceStatusName;
    if (!statuses.has(name) || seen.has(name)) return invalid();
    seen.add(name);

    let onHand: Quantity;
    let reserved: Quantity;
    let movable: Quantity;
    try {
      onHand = parseQuantity(status.on_hand_quantity, "on_hand_quantity", {
        allowZero: true,
      });
      reserved = parseQuantity(status.reserved_quantity, "reserved_quantity", {
        allowZero: true,
      });
      movable = parseQuantity(status.movable_quantity, "movable_quantity", {
        allowZero: true,
      });
    } catch {
      return invalid();
    }
    if (
      compareQuantity(reserved, onHand) > 0 ||
      compareQuantity(movable, onHand) > 0
    ) {
      return invalid();
    }

    const evidenceRaw = status.reservation_evidence;
    if (!evidenceRaw || typeof evidenceRaw !== "object" || Array.isArray(evidenceRaw)) {
      return invalid();
    }
    const evidence = evidenceRaw as Record<string, unknown>;
    const coverage = evidence.coverage as LiveStockReservationCoverage;
    if (
      !coverages.has(coverage) ||
      !Array.isArray(evidence.owners) ||
      evidence.owners.length > 20 ||
      typeof evidence.owners_truncated !== "boolean"
    ) {
      return invalid();
    }
    let unattributed: Quantity;
    try {
      unattributed = parseQuantity(
        evidence.unattributed_quantity,
        "unattributed_quantity",
        { allowZero: true },
      );
    } catch {
      return invalid();
    }
    if (compareQuantity(unattributed, reserved) > 0) return invalid();

    const ownerIds = new Set<number>();
    const owners = evidence.owners.map((rawOwner) => {
      if (!rawOwner || typeof rawOwner !== "object" || Array.isArray(rawOwner)) {
        return invalid();
      }
      const owner = rawOwner as Record<string, unknown>;
      const transferId = positiveInt(owner.transfer_id);
      if (ownerIds.has(transferId)) return invalid();
      ownerIds.add(transferId);
      if (
        typeof owner.reference_number !== "string" ||
        !owner.reference_number.trim() ||
        owner.reference_number.length > 100
      ) {
        return invalid();
      }
      let quantity: Quantity;
      try {
        quantity = parseQuantity(owner.quantity, "reservation_owner_quantity");
      } catch {
        return invalid();
      }
      return {
        transfer_id: transferId,
        reference_number: owner.reference_number.trim(),
        quantity,
      };
    });

    return {
      stock_status: name,
      on_hand_quantity: onHand,
      reserved_quantity: reserved,
      movable_quantity: movable,
      reservation_evidence: {
        coverage,
        owners,
        unattributed_quantity: unattributed,
        owners_truncated: evidence.owners_truncated as boolean,
      },
    };
  });

  return {
    location_id: positiveInt(row.location_id),
    location_name: row.location_name.trim(),
    product_variant_id: positiveInt(row.product_variant_id),
    batch_id: positiveInt(row.batch_id),
    statuses: parsedStatuses,
  };
}
