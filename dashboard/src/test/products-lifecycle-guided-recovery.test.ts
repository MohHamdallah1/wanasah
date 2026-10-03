import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), "utf8");

describe("Products guided sales recovery", () => {
  it("uses clear restore-sales language and actionable blockers", () => {
    const panel = read("../pages/inventory/catalog/CatalogLifecycleSimplePanel.tsx");
    const actions = read("../pages/inventory/catalog/CatalogLifecycleActions.tsx");
    const i18n = read("../i18n/resources.ts");
    expect(i18n).toContain('closeRecall: "إعادة إتاحة البيع"');
    expect(i18n).toContain("recallBlockerActions");
    expect(panel).toContain("problemSaleStopTitle");
    expect(panel).toContain("recallCompletionTitle");
    expect(panel).toContain("recallBlockerActions.${item.code}");
    expect(actions).toContain("recallCompletionRequired");
    expect(actions).toContain("setSelectedCommand(null)");
  });

  it("explains both product and sales status axes in one simple panel", () => {
    const panel = read("../pages/inventory/catalog/CatalogLifecycleSimplePanel.tsx");
    expect(panel).toContain("products.details.lifecycleModes.${variant.lifecycle_status}");
    expect(panel).toContain("products.details.holdModes.${variant.operational_hold}");
  });
});
