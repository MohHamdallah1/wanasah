import {
  parseVehicleLoadMutationResult,
  parseVehicleLoadSnapshot,
  parseVehicleLoadSourcePage,
  parseVehicleLoadWarehousePage,
  type VehicleLoadAuthFetch,
  type VehicleLoadDirection,
  type VehicleLoadMutationPayload,
  type VehicleLoadMutationResult,
  type VehicleLoadSnapshot,
  type VehicleLoadSourcePage,
  type VehicleLoadWarehousePage,
} from "./contracts";

const jsonRequest = (value: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});

export async function getVehicleLoadSnapshot(
  authFetch: VehicleLoadAuthFetch,
  vehicleId: number,
  signal?: AbortSignal,
): Promise<VehicleLoadSnapshot> {
  return parseVehicleLoadSnapshot(
    await authFetch(`/vehicles/${vehicleId}/load`, { signal }),
  );
}

export async function getVehicleLoadWarehouses(
  authFetch: VehicleLoadAuthFetch,
  vehicleId: number,
  direction: VehicleLoadDirection,
  options: {
    search?: string;
    cursor?: string | null;
    limit?: number;
    signal?: AbortSignal;
  } = {},
): Promise<VehicleLoadWarehousePage> {
  const params = new URLSearchParams({
    direction,
    limit: String(options.limit ?? 50),
  });
  const search = (options.search ?? "").trim();
  if (search.length >= 2) params.set("search", search);
  if (options.cursor) params.set("cursor", options.cursor);
  return parseVehicleLoadWarehousePage(
    await authFetch(
      `/vehicles/${vehicleId}/load/warehouses?${params.toString()}`,
      { signal: options.signal },
    ),
  );
}

export async function getVehicleLoadSourceInventory(
  authFetch: VehicleLoadAuthFetch,
  vehicleId: number,
  warehouseId: number,
  options: {
    search?: string;
    cursor?: string | null;
    limit?: number;
    signal?: AbortSignal;
  } = {},
): Promise<VehicleLoadSourcePage> {
  const params = new URLSearchParams({
    warehouse_id: String(warehouseId),
    limit: String(options.limit ?? 50),
  });
  const search = (options.search ?? "").trim();
  if (search.length >= 2) params.set("search", search);
  if (options.cursor) params.set("cursor", options.cursor);
  return parseVehicleLoadSourcePage(
    await authFetch(
      `/vehicles/${vehicleId}/load/source-inventory?${params.toString()}`,
      { signal: options.signal },
    ),
  );
}

export async function mutateVehicleLoad(
  authFetch: VehicleLoadAuthFetch,
  vehicleId: number,
  direction: VehicleLoadDirection,
  payload: VehicleLoadMutationPayload,
  requestId: string,
): Promise<VehicleLoadMutationResult> {
  return parseVehicleLoadMutationResult(
    await authFetch(
      `/vehicles/${vehicleId}/load/${direction === "ADD" ? "add" : "unload"}`,
      jsonRequest({
        request_id: requestId,
        ...payload,
      }),
    ),
  );
}
