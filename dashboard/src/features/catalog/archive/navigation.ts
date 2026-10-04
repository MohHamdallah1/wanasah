import type { ArchiveBlocker } from "../contracts";
import { createInventoryOwnerFocusState } from "@/features/inventory/navigation";
import { createDispatchOwnerFocusState, createDispatchReservationFocusState } from "@/features/dispatch/navigation";
import { createSettlementOwnerState } from "@/features/operations/navigation";

const expectedKinds: Record<string, readonly string[]> = {
  INVENTORY_BALANCE: ["batch"], OPEN_TRANSFER: ["transfer", "handshake"],
  OPEN_STOCKTAKE: ["stocktake"], ACTIVE_INVENTORY_LOCK: ["stocktake"],
  PRODUCT_LOCATION: ["product-location"], ACTIVE_ROUTE_LOAD: ["route-load"], OPEN_SHORTAGE: ["shortage"],
  OPEN_CUSTODY: ["settlement"],
};

export function archiveOwnerNavigation(blocker: ArchiveBlocker, variantId: number) {
  const target = blocker.owner_target;
  if (!target || !expectedKinds[blocker.code]?.includes(target.kind)) return null;
  switch (target.kind) {
    case "capability-gap": return null;
    case "batch":
    case "transfer":
    case "stocktake":
    case "product-location":
      return { path: "/inventory", label: target.kind, state: createInventoryOwnerFocusState({
        flow: target.kind, variantId, operationId: target.kind === "batch" ? target.batch_id : target.operation_id,
        locationId: target.location_id, reference: target.kind === "transfer" ? target.reference : "",
      }) };
    case "handshake":
      return { path: "/dispatch", label: target.kind, state: createDispatchReservationFocusState({
        routeId: target.route_id, transferId: target.operation_id,
      }) };
    case "route-load":
      return { path: "/dispatch", label: target.kind, state: createDispatchOwnerFocusState({ version: 1, kind: "route-load", routeId: target.route_id }) };
    case "shortage":
      return { path: "/dispatch", label: target.kind, state: createDispatchOwnerFocusState({ version: 1, kind: "shortage-owner", shortageId: target.operation_id }) };
    case "settlement":
      return { path: "/", label: target.kind, state: createSettlementOwnerState(target.operation_id) };
  }
}

export function archiveOwnerGap(blocker: ArchiveBlocker): string {
  const code = blocker.code;
  if (blocker.owner_target?.kind === "capability-gap") {
    const gaps = { PRODUCT_LOCATION_REFERENCES: "history", INVENTORY_SOURCE: "inventorySource", TRANSIT_STATE: "transitState", STOCKTAKE_STATE: "stocktakeState" };
    return gaps[blocker.owner_target.reason];
  }
  if (code === "STOCK_POLICY") return "policy";
  if (code === "ACTIVE_OFFER") return "legacyOffer";
  if (code === "OPEN_CUSTODY") return "custody";
  return "unavailable";
}
