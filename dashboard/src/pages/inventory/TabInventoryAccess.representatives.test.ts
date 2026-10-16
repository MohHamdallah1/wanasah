import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { permissionLabel } from "./access/permissionLabels";

const rolePanel = readFileSync(
  resolve(process.cwd(), "src/pages/inventory/access/RoleAccessPanel.tsx"),
  "utf8",
);
const adminHook = readFileSync(
  resolve(process.cwd(), "src/pages/inventory/access/useInventoryAccessAdmin.ts"),
  "utf8",
);

const representativeCodes = [
  "representative.read",
  "representative.manage",
  "representative.credentials.reset",
] as const;

describe("Representative permission provisioning UI", () => {
  it("maps all Representative capability codes to bilingual operator labels", () => {
    for (const code of representativeCodes) {
      expect(permissionLabel(code, "ar")).not.toBe(code);
      expect(permissionLabel(code, "en")).not.toBe(code);
    }
    expect(permissionLabel("representative.read", "ar")).toBe("عرض المندوبين");
    expect(permissionLabel("representative.manage", "en")).toBe("Manage representatives");
    expect(permissionLabel("representative.credentials.reset", "en")).toBe("Reset representative credentials");
  });

  it("preserves role select, save and reload plumbing after modularization", () => {
    expect(rolePanel).toContain("checked={codes.includes(code)}");
    expect(rolePanel).toContain("setCodes(role.permissions)");
    expect(adminHook).toContain("invalidateQueries({ queryKey: ['inventory-access-admin'] })");
    expect(adminHook).toContain("invalidateQueries({ queryKey: ['inventory-access'] })");
  });
});
