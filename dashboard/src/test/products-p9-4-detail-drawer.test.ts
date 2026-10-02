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

describe("Products P9.4 detail drawer", () => {
  it("is closed by page state and supports bounded compact and expanded desktop widths", () => {
    const drawer = read(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );

    expect(drawer).toContain(
      "if (!product)",
    );
    expect(drawer).toContain(
      "sm:w-[min(36vw,520px)]",
    );
    expect(drawer).toContain(
      "sm:w-[min(60vw,860px)]",
    );
    expect(drawer).toContain(
      "sm:inset-y-4",
    );
    expect(drawer).toContain(
      "sm:end-4",
    );
    expect(drawer).toContain(
      "sm:rounded-2xl",
    );
    const hero = read(
      "../pages/products/detail/ProductDetailHero.tsx",
    );

    expect(hero).toContain(
      "aria-pressed={",
    );
    expect(hero).toContain(
      '"products.details.expand"',
    );
    expect(hero).toContain(
      '"products.details.compact"',
    );
  });

  it("resets expansion on close and stays full width on narrow screens", () => {
    const drawer = read(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );

    expect(drawer).toContain(
      "setExpanded(false);",
    );
    expect(drawer).toContain(
      "onClick={handleClose}",
    );
    expect(drawer).toContain(
      "flex w-full flex-col",
    );
    const hero = read(
      "../pages/products/detail/ProductDetailHero.tsx",
    );

    expect(hero).toContain(
      "sm:inline-flex",
    );
  });

  it("uses a fixed hero plus accessible tabs instead of one long details stack", () => {
    const drawer = read(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );
    const tabs = read(
      "../pages/products/detail/ProductDetailTabs.tsx",
    );
    const panel = read(
      "../pages/products/detail/ProductDetailTabPanel.tsx",
    );

    expect(drawer).toContain(
      "<ProductDetailTabs",
    );
    expect(drawer).toContain(
      "<ProductDetailTabPanel",
    );
    expect(drawer).toContain(
      'activeTab',
    );
    expect(tabs).toContain(
      'role="tablist"',
    );
    expect(tabs).toContain(
      'role="tab"',
    );
    expect(tabs).toContain(
      'aria-selected={',
    );
    expect(tabs).toContain(
      '"ArrowRight"',
    );
    expect(tabs).toContain(
      '"ArrowLeft"',
    );
    expect(panel).toContain(
      'role="tabpanel"',
    );
  });

  it("keeps details strictly view-only and centralizes mutations in the locale-driven row actions menu", () => {
    const drawer = read(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );
    const hero = read(
      "../pages/products/detail/ProductDetailHero.tsx",
    );
    const actions = read(
      "../pages/products/list/ProductRowActions.tsx",
    );
    const primitives = read(
      "../pages/products/detail/ProductDetailPrimitives.tsx",
    );

    expect(drawer).toContain(
      "<ProductDetailHero",
    );
    expect(hero).not.toContain(
      "ProductDetailActionsMenu",
    );
    expect(hero).not.toContain(
      "<Box",
    );
    expect(drawer).not.toContain(
      "canEditPrice",
    );
    expect(drawer).not.toContain(
      "canManageBarcodes",
    );

    expect(actions).toContain(
      "i18n.dir()",
    );
    expect(actions).toContain(
      "dir={direction}",
    );
    expect(actions).toContain(
      '"products.rename.action"',
    );
    expect(actions).toContain(
      '"products.familyReassign.action"',
    );
    expect(actions).toContain(
      '"products.editPrice"',
    );
    expect(actions).toContain(
      '"products.trackingEditor.action"',
    );
    expect(actions).toContain(
      '"products.barcodeManager.action"',
    );
    expect(actions).toContain(
      '"products.lifecycleManager.action"',
    );
    expect(actions).not.toContain(
      "canManageAdvancedUom",
    );

    expect(primitives).toContain(
      "border-b border-slate-100",
    );
  });
});
