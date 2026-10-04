import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), "utf8");

describe("Products guided sales recovery", () => {
  it("uses clear restore-sales language and actionable blockers", () => {
    const panel = read("../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx");
    const actions = read("../features/catalog/lifecycle/CatalogLifecycleActions.tsx");
    const i18n = read("../i18n/resources.ts");
    expect(i18n).toContain('closeRecall: "السماح ببيع المنتج من جديد"');
    expect(i18n).toContain("recallBlockerActions");
    expect(panel).toContain("recallCompletionTitle");
    expect(panel).toContain("recallBlockerActions.${item.code}");
    expect(actions).toContain("recallCompletionRequired");
    expect(actions).toContain("setSelectedCommand(null)");
  });

  it("uses one commercial status instead of exposing backend lifecycle axes", () => {
    const panel = read("../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx");
    expect(panel).toContain("productCommercialStatus(");
    expect(panel).toContain("products.commercialStatus.label");
    expect(panel).not.toContain("products.details.lifecycleModes.${variant.lifecycle_status}");
    expect(panel).not.toContain("products.details.holdModes.${variant.operational_hold}");
  });
});
