import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { parseWarehouseFilterPage } from "@/pages/products/list/warehouseFilterContract";

const source = (relative: string) =>
  readFileSync(resolve(process.cwd(), "src", relative), "utf8");

describe("Products status flow and warehouse-presence filter", () => {
  it("keeps the lifecycle dialog on one user step at a time", () => {
    const panel = source("features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx");
    const manager = source("pages/products/lifecycle/ProductLifecycleManager.tsx");

    expect(manager).toContain("subtitle={commercial ?");
    expect(manager).toContain("t(commercial.stateKey)");
    expect(manager).not.toContain("t(commercial.hintKey)");
    expect(manager).not.toContain("t(commercial.reasonKey)");
    expect(panel).not.toContain("products.commercialStatus.label");
    expect(panel).toContain("!issueScopeOpen && !selectedCommand");
    expect(panel).toContain("showAvailableStopOptions && canHold && !selectedCommand");
    expect(panel).toContain("onCancel();");
    expect(panel).toContain("setIssueScopeOpen(true);");
    expect(panel).toContain("setIssueScopeOpen(false);");
    expect(panel).not.toContain("bg-rose-50/30");
  });

  it("parses bounded warehouse choices and rejects duplicates", () => {
    expect(
      parseWarehouseFilterPage({
        items: [
          { id: 3, name: "Warehouse A", code: "WA" },
          { id: 7, name: "Warehouse B", code: "WB" },
        ],
        has_more: false,
      }),
    ).toEqual({
      items: [
        { id: 3, name: "Warehouse A", code: "WA" },
        { id: 7, name: "Warehouse B", code: "WB" },
      ],
      has_more: false,
    });

    expect(() =>
      parseWarehouseFilterPage({
        items: [
          { id: 3, name: "Warehouse A", code: "WA" },
          { id: 3, name: "Warehouse A", code: "WA" },
        ],
        has_more: false,
      }),
    ).toThrow("WAREHOUSE_FILTER_RESPONSE_INVALID");
  });

  it("sends every selected warehouse to the server instead of filtering browser rows", () => {
    const params = source("pages/products/list/useProductsListParams.ts");
    const component = source("pages/products/list/ProductsWarehouseFilter.tsx");

    expect(params).toContain('value.append("warehouse_id", String(warehouse.id))');
    expect(params).toContain("[...warehouseFilters].sort((a, b) => a.id - b.id)");
    expect(component).toContain("warehouseIntersectionHint");
    expect(component).toContain('role="checkbox"');
    expect(component).toContain("selected.length >= 20");
  });
});
