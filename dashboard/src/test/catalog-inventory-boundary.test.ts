import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  createInventoryBatchFocusNavigationState,
  createInventoryTabNavigationState,
  parseInventoryNavigationState,
} from "@/features/inventory/navigation";

const here = dirname(fileURLToPath(import.meta.url));
const read = (path: string) =>
  readFileSync(resolve(here, path), "utf8");

describe("Catalog / Inventory frontend boundary", () => {
  it("uses typed route state instead of storage as the Product to Inventory workflow bridge", () => {
    const batchState = createInventoryBatchFocusNavigationState({
      variantId: 118,
      productName: "Test product",
    });
    expect(parseInventoryNavigationState(batchState)).toEqual({
      version: 1,
      kind: "batch-focus",
      tab: "batches",
      variantId: 118,
      productName: "Test product",
      locationId: null,
    });

    expect(
      parseInventoryNavigationState(
        createInventoryTabNavigationState("transfers"),
      ),
    ).toEqual({
      version: 1,
      kind: "tab",
      tab: "transfers",
      locationId: null,
    });

    expect(
      parseInventoryNavigationState({
        inventoryNavigation: {
          version: 1,
          kind: "batch-focus",
          tab: "batches",
          variantId: -1,
          productName: "Bad",
          locationId: null,
        },
      }),
    ).toBeNull();
  });

  it("keeps Product lifecycle independent from Inventory page internals", () => {
    const lifecycle = read(
      "../pages/products/lifecycle/ProductLifecycleManager.tsx",
    );
    expect(lifecycle).not.toContain("@/pages/inventory/");
    expect(lifecycle).not.toContain("prepareBatchIssueNavigation");
    expect(lifecycle).not.toContain("localStorage.setItem");
    expect(lifecycle).toContain(
      "createInventoryBatchFocusNavigationState",
    );
    expect(lifecycle).toContain(
      "createInventoryTabNavigationState",
    );
  });

  it("owns Catalog lifecycle implementation outside page folders", () => {
    const actions = read(
      "../features/catalog/lifecycle/CatalogLifecycleActions.tsx",
    );
    const panel = read(
      "../features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx",
    );
    const contracts = read("../features/catalog/contracts.ts");

    expect(actions).not.toContain("@/pages/");
    expect(panel).not.toContain("@/pages/");
    expect(contracts).not.toContain("@/pages/");
    expect(contracts).toContain("@/lib/quantity");
  });
});
