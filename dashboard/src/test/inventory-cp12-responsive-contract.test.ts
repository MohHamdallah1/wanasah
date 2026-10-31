import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

const inventoryFiles = {
  shell: "src/pages/inventory/MainInventory.tsx",
  live: "src/pages/inventory/Tab1LiveStock.tsx",
  inbound: "src/pages/inventory/Tab2Inbound.tsx",
  transfers: "src/pages/inventory/TabTransfers.tsx",
  stocktake: "src/pages/inventory/Tab3Stocktake.tsx",
  ledger: "src/pages/inventory/Tab4Ledger.tsx",
  warehouses: "src/pages/inventory/TabWarehouseLocations.tsx",
  access: "src/pages/inventory/TabInventoryAccess.tsx",
} as const;

describe("CP12 Inventory responsive and RTL/LTR contracts", () => {
  it("keeps the shared dialog viewport-safe, direction-aware, focus-trapped and keyboard closable", () => {
    const modal = read("src/components/ui/modal.tsx");
    const focusTrap = read("src/hooks/useDialogFocusTrap.ts");

    expect(modal).toContain("max-h-[calc(100dvh-1rem)]");
    expect(modal).toContain("dir={i18n.dir()}");
    expect(modal).toContain("useDialogFocusTrap");
    expect(focusTrap).toContain('event.key === "Escape"');
    expect(focusTrap).toContain('event.key !== "Tab"');
    expect(focusTrap).toContain("restore.focus()");
  });

  it("keeps dense inbound/branch tables scrollable and warehouse cards responsive without squeezing fields", () => {
    const inbound = read(inventoryFiles.inbound);
    const warehouses = read(inventoryFiles.warehouses);
    const branches = read("src/pages/inventory/warehouse-locations/BranchManagementModal.tsx");

    // Scrolling and column sizing moved from utility classes to Inventory CSS.
    // Bind the real table to its real scroll owner, then check both width rules.
    const css = read("src/pages/inventory/inventory.css");
    expect(inbound).toMatch(/className="inventory-inbound-table-wrap"[\s\S]*?<table className="inventory-inbound-table">/);
    expect(inbound.match(/<col className="inventory-inbound-col-/g)).toHaveLength(7);
    expect(inbound.match(/<th scope="col"/g)).toHaveLength(7);
    expect(css).toMatch(/\.inventory-inbound-table-wrap\s*\{[^}]*overflow:\s*auto;/);
    expect(css).toMatch(/\.inventory-inbound-table\s*\{[^}]*min-width:\s*1120px;[^}]*table-layout:\s*fixed;/);
    expect(css).toMatch(/@media\s*\(max-width:\s*1100px\)\s*\{\s*\.inventory-inbound-table\s*\{\s*min-width:\s*1050px;/);
    // Warehouses intentionally become stacked cards on phones; the desktop
    // table keeps its minimum width inside the shared scroll container.
    expect(warehouses).toMatch(/className="min-h-0 flex-1 overflow-auto" data-cp13-phone-list="true"[\s\S]*?<table className=\{\x60w-full min-w-0 text-sm md:min-w-\[760px\]/);
    expect(warehouses).toContain('className="hidden bg-slate-50/95 md:table-header-group"');
    expect(warehouses).toContain('className="grid gap-2 p-2 md:table-row-group');
    expect(warehouses).toMatch(/className=\{\x60block rounded-xl border p-2 md:table-row/);
    expect(branches).toContain("overflow-x-auto");
    expect(branches).toContain("min-w-[620px]");
  });

  it("keeps Warehouse/Branch labels usable at phone width with logical RTL/LTR spacing", () => {
    const warehouses = read(inventoryFiles.warehouses);
    const branches = read("src/pages/inventory/warehouse-locations/BranchManagementModal.tsx");
    const selector = read("src/pages/inventory/warehouse-locations/BranchSelector.tsx");

    expect(warehouses).toContain("flex-wrap");
    expect(warehouses).toContain("break-words");
    expect(warehouses).toContain("ps-10");
    expect(branches).toContain("flex-col gap-3 sm:flex-row");
    expect(branches).toContain("start-3");
    expect(branches).toContain("ps-10");
    expect(selector).toContain("start-3");
    expect(selector).toContain("ps-10 pe-3");
  });

  it("keeps global direction authoritative while direction-sensitive Inventory surfaces inherit or declare it deliberately", () => {
    const i18nRuntime = read("src/i18n/index.ts");
    const topDock = read("src/pages/inventory/InventoryTopDock.tsx");
    const stocktake = read(inventoryFiles.stocktake);
    const warehouses = read(inventoryFiles.warehouses);
    const access = read(inventoryFiles.access);

    expect(i18nRuntime.replace(/\s+/g, " ")).toContain("document.documentElement.dir = i18n.dir(language);");
    expect(topDock).toContain('closest<HTMLElement>("[dir]")');
    expect(topDock).toContain('event.key === "ArrowRight"');
    expect(topDock).toContain('event.key === "ArrowLeft"');
    expect(stocktake).toContain("dir={dir}");
    expect(warehouses).toContain("dir={dir}");
    expect(access).toContain("dir={i18n.dir()}");
  });

  it("keeps status meaning textual and icon-only Warehouse/Branch controls named", () => {
    const warehouseCopy = read("src/pages/inventory/warehouse-locations/i18n.ts");
    const warehouses = read(inventoryFiles.warehouses);
    const branches = read("src/pages/inventory/warehouse-locations/BranchManagementModal.tsx");

    expect(warehouseCopy).toContain('active: "Active"');
    expect(warehouseCopy).toContain('inactive: "Inactive"');
    expect(warehouseCopy).toContain('active: "فعال"');
    expect(warehouseCopy).toContain('inactive: "متوقف"');
    expect(warehouses).toContain("aria-label={copy.refresh}");
    expect(warehouses).toContain("aria-label={`${copy.editAction}: ${location.name}`}");
    expect(branches).toContain("aria-label={copy.refresh}");
    expect(branches).toContain("aria-label={`${copy.editAction}: ${branch.name}`}");
  });

  it("keeps every major surface connected to translation/presentation resources without changing business contracts", () => {
    const sources = Object.fromEntries(
      Object.entries(inventoryFiles).map(([name, path]) => [name, read(path)]),
    ) as Record<keyof typeof inventoryFiles, string>;

    expect(sources.shell).toContain("useTranslation");
    expect(sources.live).toContain("useTranslation");
    expect(sources.inbound).toContain("useTranslation");
    expect(sources.transfers).toContain("useTransferTranslation");
    expect(sources.stocktake).toContain("useStocktakeCopy");
    expect(sources.ledger).toContain("ledgerText");
    expect(sources.ledger).toContain("ledgerI18n");
    expect(sources.warehouses).toContain("warehouseLocationsCopy");
    expect(sources.access).toContain("inventoryAccessCopy");
    expect(sources.access).toContain("./access/copy");

    const combined = Object.values(sources).join("\n");
    expect(combined).not.toMatch(/fetch\([^)]*translated/i);
  });
});
