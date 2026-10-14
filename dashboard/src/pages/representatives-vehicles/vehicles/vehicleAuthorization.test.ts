import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const vehicleTab = readFileSync(resolve(process.cwd(), "src/pages/representatives-vehicles/vehicles/VehiclesTab.tsx"), "utf8");
const page = readFileSync(resolve(process.cwd(), "src/pages/representatives-vehicles/RepresentativesVehiclesPage.tsx"), "utf8");
const sidebar = readFileSync(resolve(process.cwd(), "src/components/operations/OperationsSidebar.tsx"), "utf8");
const form = readFileSync(resolve(process.cwd(), "src/pages/representatives-vehicles/vehicles/VehicleForm.tsx"), "utf8");
const errors = readFileSync(resolve(process.cwd(), "src/pages/representatives-vehicles/vehicles/vehicleErrorMessage.ts"), "utf8");

describe("Vehicle company-only capability UX", () => {
  it("uses vehicle.read/manage without canAny shortcuts", () => {
    expect(page).toContain('access.can("vehicle.read")');
    expect(vehicleTab).toContain('access.can("vehicle.manage")');
    expect(sidebar).toContain('access.can("vehicle.read")');
    expect(`${page}
${vehicleTab}
${sidebar}`).not.toMatch(/canAny\(\s*["']vehicle\./);
  });

  it("does not expose V1 warehouse, representative, or raw InventoryLocation inputs", () => {
    expect(form).not.toContain("warehouse_id");
    expect(form).not.toContain("location_id");
    expect(form).not.toContain("representative_id");
    expect(form).not.toContain("InventoryLocation");
  });
  it("maps the exact backend custody error codes", () => {
    expect(errors).toContain("VEHICLE_CUSTODY_LOCATION_MISSING");
    expect(errors).toContain("VEHICLE_CUSTODY_LOCATION_AMBIGUOUS");
    expect(errors).toContain("VEHICLE_CUSTODY_LOCATION_INCONSISTENT");
    expect(errors).not.toMatch(/VEHICLE_CUSTODY_MISSING:/);
    expect(errors).not.toMatch(/VEHICLE_CUSTODY_AMBIGUOUS:/);
  });

});
