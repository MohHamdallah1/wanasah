import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (path: string) =>
  readFileSync(resolve(process.cwd(), "src", path), "utf8");

describe("Live Stock ownership boundary", () => {
  it("keeps Live Stock read-only and moves minimum-stock mutation to warehouse management", () => {
    const live = read("pages/inventory/Tab1LiveStock.tsx");
    const warehouses = read("pages/inventory/TabWarehouseLocations.tsx");
    expect(live).not.toContain("StockMinimumManager");
    expect(warehouses).toContain("StockMinimumManager");
  });

  it("never falls back from a blocker action to Live Stock", () => {
    const manager = read("pages/products/lifecycle/ProductLifecycleManager.tsx");
    const panel = read("features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx");
    expect(manager).not.toContain('return "live"');
    expect(panel).toContain("recallBlockerHasOwnerAction");
  });
});
