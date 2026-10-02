import {
  readFileSync,
} from "node:fs";
import {
  describe,
  expect,
  it,
} from "vitest";

const source = (
  relativePath: string,
) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

const compact = (
  value: string,
) =>
  value.replace(/\s+/g, " ").trim();

describe(
  "Products P5 advanced UOM wiring",
  () => {
    it("routes only the focused advanced UOM surface and does not revive the legacy catalog tab", () => {
      const app = compact(
        source("../App.tsx"),
      );
      const inventory = compact(
        source(
          "../pages/inventory/MainInventory.tsx",
        ),
      );

      expect(app).toContain(
        'lazy(() => import("./pages/products/advanced-uom/AdvancedUomDashboard"))',
      );
      expect(app).toContain(
        'path="/products/advanced-uom"',
      );
      expect(app).not.toContain(
        "TabProductCatalog",
      );
      expect(inventory).not.toContain(
        "TabProductCatalog",
      );
    });

    it("keeps Advanced UOM code available while deferring its normal V1 UI entry alongside Advanced Pricing", () => {
      const products = compact(
        source(
          "../pages/products/ProductsPage.tsx",
        ),
      );
      const tools = compact(
        source(
          "../pages/products/header/ProductsCatalogToolsMenu.tsx",
        ),
      );

      expect(products).not.toContain(
        'navigate( "/products/advanced-uom" )',
      );
      expect(tools).toContain(
        '"products.advancedUom.action"',
      );
      expect(tools).toContain(
        '"products.advancedUom.deferredHint"',
      );
      expect(tools).toContain(
        '"products.advancedPricing"',
      );
      expect(tools).toContain(
        '"products.advancedPricingHint"',
      );
      expect(tools).toContain(
        "LockKeyhole",
      );
      expect(tools).toMatch(
        /disabled\s+title=\{t\(\s*"products\.advancedPricingHint"/,
      );
      expect(tools).toMatch(
        /disabled\s+title=\{t\(\s*"products\.advancedUom\.deferredHint"/,
      );
    });

    it("does not expose Advanced UOM from normal V1 Product detail actions", () => {
      const drawer = compact(
        source(
          "../pages/products/detail/ProductDetailDrawer.tsx",
        ),
      );
      const actionMenu = compact(
        source(
          "../pages/products/list/ProductRowActions.tsx",
        ),
      );
      const detailWorkflow = compact(
        source(
          "../pages/products/detail/useProductDetailWorkflow.ts",
        ),
      );
      expect(drawer).not.toContain(
        "canManageAdvancedUom",
      );
      expect(actionMenu).not.toContain(
        '"products.advancedUom.productAction"',
      );
      expect(detailWorkflow).not.toContain(
        "canManageAdvancedUom",
      );
    });
  },
);
