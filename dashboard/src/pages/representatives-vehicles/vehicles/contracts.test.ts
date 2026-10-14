import { describe, expect, it, vi } from "vitest";

import { listVehicles, updateVehicle } from "./api";
import { parseVehicle, parseVehicleList } from "./contracts";

const row = {
  id: 7,
  plate_number: "12-34567",
  vehicle_type: "Van",
  current_mileage: 12500,
  next_oil_change: 15000,
  license_expiry_date: "2027-05-01",
  next_maintenance_date: "2026-12-15",
  maintenance_status: "Active",
  is_active: true,
  version: 3,
  custody_ready: true,
} as const;

describe("Vehicle dashboard contract", () => {
  it("parses the frozen public Vehicle view and rejects invalid versions", () => {
    expect(parseVehicle(row)).toEqual(row);
    expect(() => parseVehicle({ ...row, version: 0 })).toThrow();
    expect(parseVehicleList({ items: [row], next_cursor: null, has_more: false }).items).toHaveLength(1);
  });

  it("maps ready and maintenance filters to server-side query parameters", async () => {
    const authFetch = vi.fn(async () => ({ items: [row], next_cursor: null, has_more: false }));
    await listVehicles(authFetch, { search: "12", status: "ready" });
    expect(String(authFetch.mock.calls[0]?.[0])).toContain("active=true");
    expect(String(authFetch.mock.calls[0]?.[0])).toContain("maintenance_status=Active");

    await listVehicles(authFetch, { search: "", status: "maintenance" });
    expect(String(authFetch.mock.calls[1]?.[0])).toContain("maintenance_status=In_Maintenance");
  });

  it("sends optimistic expected_version on updates", async () => {
    const authFetch = vi.fn(async () => ({ ...row, current_mileage: 13000, version: 4 }));
    await updateVehicle(authFetch, 7, { current_mileage: 13000 }, "8f48b351-8440-48d9-a8db-e0ff2964af6b", 3);
    const request = authFetch.mock.calls[0];
    expect(request?.[0]).toBe("/vehicles/7");
    expect(String((request?.[1] as RequestInit).body)).toContain('"expected_version":3');
  });
});
