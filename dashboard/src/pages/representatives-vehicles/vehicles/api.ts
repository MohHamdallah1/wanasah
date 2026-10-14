import {
  parseVehicle,
  parseVehicleList,
  type CreateVehicleInput,
  type UpdateVehicleInput,
  type Vehicle,
  type VehicleAuthFetch,
  type VehicleListResult,
  type VehicleStatusFilter,
} from "./contracts";

const jsonRequest = (method: string, value: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});

export async function listVehicles(
  authFetch: VehicleAuthFetch,
  options: {
    search: string;
    status: VehicleStatusFilter;
    cursor?: string | null;
    limit?: number;
    signal?: AbortSignal;
  },
): Promise<VehicleListResult> {
  const params = new URLSearchParams();
  if (options.search.length >= 2) params.set("search", options.search);
  if (options.status === "ready") {
    params.set("active", "true");
    params.set("maintenance_status", "Active");
  } else if (options.status === "maintenance") {
    params.set("active", "true");
    params.set("maintenance_status", "In_Maintenance");
  } else if (options.status === "inactive") {
    params.set("active", "false");
  }
  if (options.cursor) params.set("cursor", options.cursor);
  params.set("limit", String(options.limit ?? 30));
  return parseVehicleList(
    await authFetch(`/vehicles?${params.toString()}`, { signal: options.signal }),
  );
}

export async function createVehicle(
  authFetch: VehicleAuthFetch,
  input: CreateVehicleInput,
  requestId: string,
): Promise<Vehicle> {
  return parseVehicle(
    await authFetch(
      "/vehicles",
      jsonRequest("POST", { request_id: requestId, ...input }),
    ),
  );
}

export async function updateVehicle(
  authFetch: VehicleAuthFetch,
  vehicleId: number,
  input: UpdateVehicleInput,
  requestId: string,
  expectedVersion: number,
): Promise<Vehicle> {
  return parseVehicle(
    await authFetch(
      `/vehicles/${vehicleId}`,
      jsonRequest("PATCH", {
        request_id: requestId,
        expected_version: expectedVersion,
        ...input,
      }),
    ),
  );
}

export async function deactivateVehicle(
  authFetch: VehicleAuthFetch,
  vehicleId: number,
  requestId: string,
  expectedVersion: number,
): Promise<void> {
  await authFetch(
    `/vehicles/${vehicleId}/deactivate`,
    jsonRequest("POST", {
      request_id: requestId,
      expected_version: expectedVersion,
    }),
  );
}

export async function reactivateVehicle(
  authFetch: VehicleAuthFetch,
  vehicleId: number,
  requestId: string,
  expectedVersion: number,
): Promise<void> {
  await authFetch(
    `/vehicles/${vehicleId}/reactivate`,
    jsonRequest("POST", {
      request_id: requestId,
      expected_version: expectedVersion,
    }),
  );
}
