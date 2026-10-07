import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (relativePath: string) =>
  readFileSync(resolve(process.cwd(), "src/test", relativePath), "utf8");

const sourceFiles = (relativeDir: string): string[] => {
  const root = resolve(process.cwd(), "src/test", relativeDir);
  const walk = (dir: string): string[] => readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return walk(path);
    return /\.(ts|tsx)$/.test(path) ? [path] : [];
  });
  return walk(root);
};

describe("Catalog / Inventory boundary", () => {
  it("keeps product catalogue pages free of direct Inventory mutation authority", () => {
    const productSources = sourceFiles("../pages/products");
    for (const path of productSources) {
      const source = readFileSync(path, "utf8");
      expect(source).not.toContain("/warehouse/unified/transfer/");
      expect(source).not.toContain("/warehouse/quality/stage");
      expect(source).not.toContain("/warehouse/quality/disposal/confirm");
      expect(source).not.toContain("/warehouse/quality/vendor-return/confirm");
      expect(source).not.toContain("apply_inventory_movements");
    }
  });

  it("keeps product lifecycle states independent from stock statuses", () => {
    const lifecycle = read("../features/catalog/lifecycle/CatalogLifecycleActions.tsx");
    expect(lifecycle).toContain("lifecycle_status");
    expect(lifecycle).toContain("operational_hold");
    expect(lifecycle).not.toContain('stock_status: "AVAILABLE"');
    expect(lifecycle).not.toContain('stock_status: "DAMAGED"');
    expect(lifecycle).not.toContain('stock_status: "DISPOSAL_PENDING"');
  });

  it("keeps batch issue navigation as typed route state rather than browser storage", () => {
    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    expect(manager).toContain("createInventoryBatchFocusNavigationState");
    expect(manager).not.toContain("localStorage.setItem");
    expect(manager).not.toContain("sessionStorage.setItem");
  });

  it("keeps Inventory page ownership behind shared feature contracts", () => {
    const manager = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    expect(manager).not.toContain("@/pages/inventory/");
    expect(manager).toContain("@/features/inventory/");
  });

  it("keeps inventory action availability backend-authoritative", () => {
    const contract = read("../features/inventory/quality/wholeProductQualityContract.ts");
    expect(contract).toContain("dispatchActions");
    expect(contract).toContain("terminalActions");
    expect(contract).not.toContain("Date.now()");
    expect(contract).not.toContain("new Date(");
  });

  it("keeps lifecycle state commands durable without using storage as a command bus", () => {
    const lifecycle = read("../features/catalog/lifecycle/CatalogLifecycleActions.tsx");
    expect(lifecycle).toContain("getOrCreateDurableCommand");
    expect(lifecycle).toContain("readDurableCommand");
    expect(lifecycle).not.toContain("localStorage.setItem");
    expect(lifecycle).not.toContain("sessionStorage.setItem");
  });

  it("keeps archive blocker navigation typed and explicit", () => {
    const actions = read("../features/catalog/archive/ArchiveBlockerList.tsx");
    expect(actions).toContain("onOpenBlocker");
    expect(actions).not.toContain("window.location");
    expect(actions).not.toContain("localStorage");
  });

  it("keeps dispatch force-cancel authority inside Dispatch rather than quantity actions", () => {
    const dispatchBoard = read("../pages/dispatch/DispatchBoard.tsx");
    const radar = read("../pages/dispatch/DispatchRadar.tsx");
    const quantityActions = read("../features/inventory/quality/useProductQualityCommands.ts");
    expect(dispatchBoard).toContain("setRadarFocusTransferId(intent.transferId)");
    expect(radar).toContain("focusTransferId");
    expect(radar).toContain("openForceCancel(target)");
    expect(radar).toContain(
      "`/dispatch/transfers/${cancelTarget.transfer_id}/force_cancel`",
    );
    expect(quantityActions).not.toContain("/force_cancel");
  });

  it("keeps whole-product physical handling Inventory-owned while Products only hosts the shared feature", () => {
    const lifecycle = read("../pages/products/lifecycle/ProductLifecycleManager.tsx");
    const inline = read("../features/inventory/quality/WholeProductQualityActionsPanel.tsx");
    const commands = read("../features/inventory/quality/useProductQualityCommands.ts");

    expect(lifecycle).toContain("WholeProductQualityActionsPanel");
    expect(lifecycle).not.toContain("/warehouse/unified/transfer/special/dispatch");
    expect(lifecycle).not.toContain("/warehouse/quality/disposal/confirm");
    expect(lifecycle).not.toContain("/warehouse/quality/vendor-return/confirm");
    expect(inline).toContain("useProductQualityCommands");
    expect(commands).toContain("/warehouse/quality/products/${productVariantId}/resolve-all");
    expect(commands).not.toContain("/warehouse/quality/stage");
    expect(commands).not.toContain("/warehouse/quality/disposal/confirm");
    expect(commands).not.toContain("/warehouse/quality/vendor-return/confirm");
    expect(commands).not.toContain("source_location_id");
    expect(commands).not.toContain("batch_id");
    expect(commands).not.toContain("close-recall");
    expect(commands).not.toContain("cancel-recall");
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

  it("keeps future fleet and representative internals out of Products ownership", () => {
    const productSources = sourceFiles("../pages/products");

    for (const path of productSources) {
      const source = readFileSync(path, "utf8");
      expect(source).not.toContain("/dispatch/routes/");
      expect(source).not.toContain("/driver/");
      expect(source).not.toContain("DispatchRadar");
    }
  });
});
