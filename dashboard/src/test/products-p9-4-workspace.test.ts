import {
  readFileSync,
} from "node:fs";
import {
  describe,
  expect,
  it,
} from "vitest";

const read = (relativePath: string) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

describe("Products P9.4 workspace foundation", () => {
  it("keeps one primary Product action and moves secondary catalog actions behind one tools surface", () => {
    const header = read(
      "../pages/products/ProductsPageHeader.tsx",
    );
    const tools = read(
      "../pages/products/header/ProductsCatalogToolsMenu.tsx",
    );
    const addAction = read(
      "../pages/products/header/ProductsAddAction.tsx",
    );

    expect(header).toContain(
      "<ProductsCatalogToolsMenu",
    );
    expect(addAction).toContain(
      "bg-amber-400",
    );
    expect(header).toContain(
      "<ProductsAddAction",
    );
    expect(header).toContain(
      "onOpenCreateProduct",
    );
    expect(header).not.toContain(
      "onClick={onOpenImport}",
    );
    expect(header).not.toContain(
      "onClick={onOpenFamilies}",
    );

    expect(tools).toMatch(
      /onSelect=\{\s*onOpenDisplayPreferences\s*\}/,
    );
    expect(tools).toMatch(
      /onSelect=\{\s*onOpenFamilies\s*\}/,
    );
    expect(tools).not.toContain(
      "onOpenImport",
    );
    expect(addAction).toMatch(
      /onSelect=\{\s*onOpenImport\s*\}/,
    );
    expect(tools).toMatch(
      /onSelect=\{\s*onOpenTrackingDefaults\s*\}/,
    );
    expect(tools).toMatch(
      /onSelect=\{\s*onOpenAdvancedUom\s*\}/,
    );
    expect(tools).toContain(
      "<DropdownMenuItem",
    );
    expect(tools).toContain(
      "disabled",
    );
    expect(tools).toContain(
      '"products.advancedPricing"',
    );
    expect(
      tools.indexOf(
        '"products.trackingSettings.action"',
      ),
    ).toBeLessThan(
      tools.indexOf(
        '"products.displayPreferences.action"',
      ),
    );
    expect(
      tools.indexOf(
        '"products.displayPreferences.action"',
      ),
    ).toBeLessThan(
      tools.indexOf(
        '"products.advancedUom.action"',
      ),
    );
  });

  it("shares one reusable top-bar surface between Inventory and Products", () => {
    const sharedBar = read(
      "../components/dashboard/WorkspaceTopBar.tsx",
    );
    const inventoryDock = read(
      "../pages/inventory/InventoryTopDock.tsx",
    );
    const header = read(
      "../pages/products/ProductsPageHeader.tsx",
    );
    const topBarStyles = read(
      "../components/dashboard/WorkspaceTopBar.css",
    );

    expect(sharedBar).toContain(
      "workspace-top-bar-frame",
    );
    expect(sharedBar).toContain(
      "workspace-top-bar",
    );
    expect(inventoryDock).toContain(
      "<WorkspaceTopBar",
    );
    expect(header).toContain(
      "<WorkspaceTopBar",
    );
    expect(header).toContain(
      'variant="page"',
    );
    expect(header).toContain(
      'className="shrink-0"',
    );
    expect(header).not.toContain(
      "<Boxes",
    );
    expect(topBarStyles).toContain(
      ".workspace-top-bar:dir(rtl)",
    );
    expect(topBarStyles).not.toContain(
      "inset 0 1px",
    );

    const page = read(
      "../pages/products/ProductsPage.tsx",
    );
    expect(page).toContain(
      "flex-col gap-2 overflow-visible",
    );
    expect(page).not.toContain(
      "products-a11y-scope flex min-h-0 flex-1 flex-col overflow-hidden",
    );
  });

  it("uses a dense workspace surface instead of stacked glass cards", () => {
    const header = read(
      "../pages/products/ProductsPageHeader.tsx",
    );
    const section = read(
      "../pages/products/list/ProductsListSection.tsx",
    );
    const toolbar = read(
      "../pages/products/list/ProductsListToolbar.tsx",
    );

    expect(header).not.toContain(
      "backdrop-blur-xl",
    );
    expect(header).not.toContain(
      "rounded-[26px]",
    );
    expect(section).not.toContain(
      "backdrop-blur-xl",
    );
    expect(section).toContain(
      "rounded-2xl",
    );
    expect(toolbar).toContain(
      "relative min-w-0 flex-1",
    );
    expect(toolbar).not.toContain(
      "sm:max-w-md",
    );
    expect(toolbar).toContain(
      "PopoverContent",
    );
    expect(toolbar).toContain(
      "aria-expanded={",
    );
    expect(toolbar).toContain(
      "onOpenChange={",
    );
  });

  it("keeps the new command hierarchy translated in Arabic and English", () => {
    const translations = read(
      "../i18n/resources.ts",
    );

    expect(
      translations.match(
        /catalogTools:/g,
      ),
    ).toHaveLength(2);
    expect(translations).toContain(
      'catalogTools: "أدوات الكتالوج"',
    );
    expect(translations).toContain(
      'catalogTools: "Catalog tools"',
    );
  });
});
