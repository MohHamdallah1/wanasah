import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { representativesVehicles } from "@/i18n/representativesVehicles";

const source = readFileSync(
  fileURLToPath(new URL("./TabInventoryAccess.tsx", import.meta.url)),
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
      expect(source).toContain(`'${code}': 'representativesVehicles.representatives.permissionCatalog.`);
    }

    expect(representativesVehicles.ar.representatives.permissionCatalog).toEqual({
      read: "عرض بيانات المندوبين",
      manage: "إدارة المندوبين",
      credentialsReset: "إعادة تعيين كلمات مرور المندوبين",
    });
    expect(representativesVehicles.en.representatives.permissionCatalog).toEqual({
      read: "View representatives",
      manage: "Manage representatives",
      credentialsReset: "Reset representative passwords",
    });
  });

  it("preserves the existing role select, save and reload plumbing", () => {
    expect(source).toContain("checked={codes.includes(code)}");
    expect(source).toContain("setCodes(role.permissions)");
    expect(source).toContain("{name, permissions:codes}");
    expect(source).toContain("invalidateQueries({queryKey: ['inventory-access-admin']})");
    expect(source).toContain("invalidateQueries({queryKey: ['inventory-access']})");
  });
});