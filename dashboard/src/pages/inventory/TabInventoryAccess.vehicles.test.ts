import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(resolve(process.cwd(), "src/pages/inventory/TabInventoryAccess.tsx"), "utf8");

describe("Vehicle permission provisioning UI", () => {
  it("provides business labels for both Vehicle capabilities", () => {
    expect(source).toContain("'vehicle.read': 'representativesVehicles.vehicles.permissionCatalog.read'");
    expect(source).toContain("'vehicle.manage': 'representativesVehicles.vehicles.permissionCatalog.manage'");
    expect(source).toContain("MANAGEMENT_PERMISSION_LABEL_KEYS[code]");
  });
});
