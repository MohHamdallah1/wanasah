import { describe, expect, it } from "vitest";
import { permissionLabel } from "./access/permissionLabels";

describe("Vehicle permission provisioning UI", () => {
  it("provides bilingual business labels for both Vehicle capabilities", () => {
    expect(permissionLabel("vehicle.read", "ar")).toBe("عرض المركبات");
    expect(permissionLabel("vehicle.read", "en")).toBe("View vehicles");
    expect(permissionLabel("vehicle.manage", "ar")).toBe("إدارة المركبات");
    expect(permissionLabel("vehicle.manage", "en")).toBe("Manage vehicles");
  });
});
