import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), "utf8");

describe("Products guided lifecycle recovery", () => {
  it("uses clear return-to-circulation language and actionable blockers", () => {
    const panel = read("../pages/inventory/catalog/CatalogLifecycleSimplePanel.tsx");
    const actions = read("../pages/inventory/catalog/CatalogLifecycleActions.tsx");
    const i18n = read("../i18n/resources.ts");
    expect(i18n).toContain('closeRecall: "إعادة المنتج للتداول"');
    expect(i18n).toContain("recallBlockerActions");
    expect(panel).toContain("recallCurrentTitle");
    expect(panel).toContain("recallRecoverySteps.first");
    expect(panel).toContain("recallBlockerActions.${item.code}");
    expect(actions).toContain("recallCompletionRequired");
    expect(actions).toContain("setSelectedCommand(null)");
  });

  it("explains both product and sales status axes", () => {
    const rail = read("../pages/products/lifecycle/ProductLifecycleStatusRail.tsx");
    expect(rail).toContain("lifecycleStatusHints.${variant.lifecycle_status}");
    expect(rail).toContain("salesHints.${variant.operational_hold}");
  });
});
