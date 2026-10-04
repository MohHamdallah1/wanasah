import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  createInventoryBatchFocusNavigationState,
  createInventoryTabNavigationState,
  parseInventoryNavigationState,
} from "@/features/inventory/navigation";
import {
  parseProductLocations,
} from "@/features/inventory/productLocations/contracts";

const here = dirname(fileURLToPath(import.meta.url));
const read = (path: string) =>
  readFileSync(resolve(here, path), "utf8");

const sourceFiles = (root: string): string[] => {
  const absolute = resolve(here, root);
  const output: string[] = [];
  const visit = (directory: string) => {
    for (const name of readdirSync(directory)) {
      const path = resolve(directory, name);
      if (statSync(path).isDirectory()) {
        visit(path);
      } else if (path.endsWith(".ts") || path.endsWith(".tsx")) {
        output.push(path);
      }
    }
  };
  visit(absolute);
  return output;
};

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

  it("prevents direct Products and Inventory page-internal imports in both directions", () => {
    const productSources = sourceFiles("../pages/products");
    const inventorySources = sourceFiles("../pages/inventory");

    for (const path of productSources) {
      expect(readFileSync(path, "utf8"), path).not.toContain(
        "@/pages/inventory/",
      );
    }
    for (const path of inventorySources) {
      expect(readFileSync(path, "utf8"), path).not.toContain(
        "@/pages/products/",
      );
    }
  });

  it("keeps product-location DTOs and parsing under Inventory ownership", () => {
    expect(
      read("../features/catalog/contracts.ts"),
    ).not.toContain("ProductLocationAssignment");

    const page = parseProductLocations({
      items: [
        {
          id: 9,
          location: {
            id: 3,
            code: "WH-3",
            name: "Warehouse 3",
            location_type: "WAREHOUSE",
          },
          product_variant: {
            id: 118,
            sku: "SKU-118",
            name: "Product 118",
            lifecycle_status: "ACTIVE",
          },
          operational_flags: {
            inbound_enabled: true,
            outbound_enabled: false,
          },
          version: 2,
          created_by: 7,
          created_at: "2026-10-04T00:00:00Z",
          updated_at: "2026-10-04T00:00:00Z",
        },
      ],
      next_cursor: null,
      has_more: false,
    });

    expect(page.items[0].product_variant.id).toBe(118);
    expect(page.items[0].location.id).toBe(3);
    expect(page.items[0].operational_flags.outbound_enabled).toBe(false);
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
