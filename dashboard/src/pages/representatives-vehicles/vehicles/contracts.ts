export type VehicleMaintenanceStatus = "Active" | "In_Maintenance";
export type VehicleStatusFilter = "all" | "ready" | "maintenance" | "inactive";

export interface Vehicle {
  id: number;
  plate_number: string;
  vehicle_type: string | null;
  current_mileage: number;
  next_oil_change: number | null;
  license_expiry_date: string | null;
  next_maintenance_date: string | null;
  maintenance_status: VehicleMaintenanceStatus;
  is_active: boolean;
  version: number;
  custody_ready: boolean;
}

export interface VehicleListResult {
  items: Vehicle[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface CreateVehicleInput {
  plate_number: string;
  vehicle_type?: string | null;
  current_mileage?: number;
  next_oil_change?: number | null;
  license_expiry_date?: string | null;
  next_maintenance_date?: string | null;
  maintenance_status?: VehicleMaintenanceStatus;
}

export type UpdateVehicleInput = Partial<
  Pick<
    Vehicle,
    | "plate_number"
    | "vehicle_type"
    | "current_mileage"
    | "next_oil_change"
    | "license_expiry_date"
    | "next_maintenance_date"
    | "maintenance_status"
  >
>;

export type VehicleAuthFetch = (
  path: string,
  options?: RequestInit,
) => Promise<unknown>;

export class VehicleContractError extends Error {
  readonly code = "VEHICLE_RESPONSE_INVALID";

  constructor(message = "VEHICLE_RESPONSE_INVALID") {
    super(message);
    this.name = "VehicleContractError";
  }
}

const asRecord = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new VehicleContractError();
  }
  return value as Record<string, unknown>;
};

const asOptionalString = (value: unknown): string | null => {
  if (value === null) return null;
  if (typeof value !== "string") throw new VehicleContractError();
  return value;
};

const asNonnegativeInt = (value: unknown): number => {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < 0
  ) {
    throw new VehicleContractError();
  }
  return value;
};

const asOptionalNonnegativeInt = (value: unknown): number | null =>
  value === null ? null : asNonnegativeInt(value);

export function parseVehicle(value: unknown): Vehicle {
  const row = asRecord(value);
  if (
    typeof row.id !== "number" ||
    !Number.isSafeInteger(row.id) ||
    row.id <= 0 ||
    typeof row.plate_number !== "string" ||
    !row.plate_number.trim() ||
    typeof row.is_active !== "boolean" ||
    typeof row.version !== "number" ||
    !Number.isSafeInteger(row.version) ||
    row.version <= 0 ||
    typeof row.custody_ready !== "boolean" ||
    (row.maintenance_status !== "Active" && row.maintenance_status !== "In_Maintenance")
  ) {
    throw new VehicleContractError();
  }

  return {
    id: row.id,
    plate_number: row.plate_number,
    vehicle_type: asOptionalString(row.vehicle_type),
    current_mileage: asNonnegativeInt(row.current_mileage),
    next_oil_change: asOptionalNonnegativeInt(row.next_oil_change),
    license_expiry_date: asOptionalString(row.license_expiry_date),
    next_maintenance_date: asOptionalString(row.next_maintenance_date),
    maintenance_status: row.maintenance_status,
    is_active: row.is_active,
    version: row.version,
    custody_ready: row.custody_ready,
  };
}

export function parseVehicleList(value: unknown): VehicleListResult {
  const envelope = asRecord(value);
  if (
    !Array.isArray(envelope.items) ||
    typeof envelope.has_more !== "boolean" ||
    !(
      envelope.next_cursor === null ||
      (typeof envelope.next_cursor === "string" && envelope.next_cursor.length <= 512)
    )
  ) {
    throw new VehicleContractError();
  }
  return {
    items: envelope.items.map(parseVehicle),
    next_cursor: envelope.next_cursor as string | null,
    has_more: envelope.has_more,
  };
}

export function normalizeVehicleText(value: string): string {
  return value.trim();
}

export function parseOptionalNonnegativeInteger(value: string): number | null | undefined {
  const normalized = value.trim();
  if (!normalized) return null;
  if (!/^\d+$/.test(normalized)) return undefined;
  const parsed = Number(normalized);
  return Number.isSafeInteger(parsed) && parsed >= 0 && parsed <= 2_147_483_647
    ? parsed
    : undefined;
}
