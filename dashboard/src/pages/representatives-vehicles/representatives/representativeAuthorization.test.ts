import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const tabSource = readFileSync(
  resolve(process.cwd(), "src/pages/representatives-vehicles/representatives/RepresentativesTab.tsx"),
  "utf8",
);
const sidebarSource = readFileSync(
  resolve(process.cwd(), "src/components/operations/OperationsSidebar.tsx"),
  "utf8",
);

describe("representative company-only capability UX", () => {
  it("uses company capability checks and never canAny for representative capabilities", () => {
    expect(tabSource).toContain('access.can("representative.manage")');
    expect(tabSource).toContain('access.can("representative.credentials.reset")');
    expect(sidebarSource).toContain('access.can("representative.read")');
    expect(`${tabSource}\n${sidebarSource}`).not.toMatch(
      /canAny\(\s*["']representative\./,
    );
  });
});
