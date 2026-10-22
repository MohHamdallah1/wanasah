import { describe, expect, it } from "vitest";
import type { InfiniteData } from "@tanstack/react-query";
import type { Vehicle, VehicleListResult } from "./contracts";
import { notesForVehicle } from "./vehiclePresentation";
import { replaceVehicleInInfiniteData } from "./vehicleCache";

const oldVehicle: Vehicle = {
  id: 7, plate_number: "TEST-7", vehicle_type: null, current_mileage: 100,
  next_oil_change: null, license_expiry_date: null, next_maintenance_date: "2000-01-01",
  maintenance_status: "Active", is_active: true, version: 1, custody_ready: true,
};

describe("vehicle list cache refresh", () => {
  it("replaces an overdue maintenance row immediately with the PATCH response", () => {
    const cached: InfiniteData<VehicleListResult> = {
      pages: [{ items: [oldVehicle], next_cursor: null, has_more: false }],
      pageParams: [null],
    };
    expect(notesForVehicle(oldVehicle).some((note) => note.kind === "maintenance")).toBe(true);

    const updated: Vehicle = {
      ...oldVehicle, next_maintenance_date: "2999-01-01", version: 2,
    };
    const next = replaceVehicleInInfiniteData(cached, updated)!;
    const row = next.pages[0].items[0];

    expect(row.next_maintenance_date).toBe("2999-01-01");
    expect(notesForVehicle(row).some((note) => note.kind === "maintenance")).toBe(false);
  });
});
