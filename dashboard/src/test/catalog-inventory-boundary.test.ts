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
      batchId: 41,
      productName: "Test product",
    });
    expect(parseInventoryNavigationState(batchState)).toEqual({
      version: 1,
      kind: "batch-focus",
      tab: "batches",
      variantId: 118,
      batchId: 41,
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
          variantId: 118,
          batchId: -1,
          productName: "Bad",
          locationId: null,
        },
      }),
    ).toBeNull();
  });

  it("keeps exact batch focus as a read-only navigation hint resolved by Inventory", () => {
    const statusBadges = read(
      "../pages/products/list/ProductStatusBadges.tsx",
    );
    const batches = read("../pages/inventory/TabBatches.tsx");

    expect(statusBadges).toContain(
      "restrictions.representative_reason?.batch_id",
    );
    expect(statusBadges).toContain(
      "createInventoryBatchFocusNavigationState",
    );
    expect(statusBadges).not.toContain("authFetch(");
    expect(batches).toContain(
      "`/warehouse/batches/${focus.batchId}/stock-sources`",
    );
    expect(batches).toContain(
      "setSelectedBatchContext({",
    );
    expect(batches).toContain("batch: sources.batch");
    expect(batches).toContain("baseUomCode: sources.base_uom_code");
    expect(batches).not.toContain("focusBatchId");
    expect(batches).not.toContain("batchIssueFocus");
  });

  it("follows the exact special-transfer operation inside Inventory without a storage workflow bridge", () => {
    const quantityActions = read(
      "../pages/inventory/batches/BatchQuantityActions.tsx",
    );
    const mainInventory = read("../pages/inventory/MainInventory.tsx");
    const transferList = read(
      "../pages/inventory/transfers/hooks/useTransferList.ts",
    );
    const transfersTab = read("../pages/inventory/TabTransfers.tsx");

    expect(quantityActions).toContain("setLastTransfer(result)");
    expect(mainInventory).toContain("headerId: transfer.header_id");
    expect(mainInventory).toContain(
      "parseInventoryLocationCapabilities",
    );
    expect(mainInventory).toContain("'transfer.read'");
    expect(transferList).toContain(
      "`/warehouse/unified/transfers/${headerId}`",
    );
    expect(transfersTab).toContain("setSearchInput(focus.reference)");
    expect(mainInventory).not.toContain("localStorage.setItem(\"transfer");
  });

  it("routes reservation-owner handling back to Dispatch authority", () => {
    const quantityActions = read(
      "../pages/inventory/batches/BatchQuantityActions.tsx",
    );
    const mainInventory = read("../pages/inventory/MainInventory.tsx");
    const dispatchBoard = read("../pages/DispatchBoard.tsx");
    const radar = read("../components/dispatch/TransfersRadarModal.tsx");

    expect(quantityActions).toContain("onOpenReservationOwner(owner)");
    expect(mainInventory).toContain("createDispatchReservationFocusState");
    expect(dispatchBoard).toContain("parseDispatchNavigationState");
    expect(dispatchBoard).toContain("setRadarFocusTransferId(dispatchFocus.transferId)");
    expect(radar).toContain("focusTransferId");
    expect(radar).toContain("openForceCancel(target)");
    expect(radar).toContain(
      "`/dispatch/transfers/${cancelTarget.transfer_id}/force_cancel`",
    );
    expect(quantityActions).not.toContain("/force_cancel");
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
