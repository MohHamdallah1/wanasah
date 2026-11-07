import { createInventoryTabNavigationState } from "@/features/inventory/navigation";

// A canonical stocktake reference lookup is a read-only URL hint. The typed
// Inventory tab navigation already selects an admitted warehouse; the Ledger
// reader enforces company + location + ledger.read on every API request.
const validReference = (value: unknown): value is string =>
  typeof value === "string" &&
  /^STK-[A-Za-z0-9_-]+$/.test(value) && value.length <= 100;

const validLocationId = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;

export const createStocktakeLedgerReferenceTarget = ({
  locationId, reference,
}: { locationId: number; reference: string }) => {
  if (!validLocationId(locationId) || !validReference(reference)) {
    throw new Error("LEDGER_STOCKTAKE_REFERENCE_INVALID");
  }
  const params = new URLSearchParams({
    ledger_ref: reference,
    ledger_location: String(locationId),
  });
  return {
    pathname: "/inventory",
    search: `?${params.toString()}`,
    state: createInventoryTabNavigationState("ledger", locationId),
  };
};

export const parseStocktakeLedgerReferenceQuery = (search: string): {
  locationId: number; reference: string;
} | null => {
  const params = new URLSearchParams(search);
  if (params.getAll("ledger_ref").length !== 1 ||
      params.getAll("ledger_location").length !== 1) return null;
  const reference = params.get("ledger_ref");
  const rawLocationId = params.get("ledger_location");
  if (!validReference(reference) || !rawLocationId ||
      !/^[1-9][0-9]*$/.test(rawLocationId)) return null;
  const locationId = Number(rawLocationId);
  return validLocationId(locationId) ? { locationId, reference } : null;
};
