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
        'lazy(() => import("./pages/products/AdvancedUomDashboard"))',
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

    it("keeps Advanced UOM usable while preserving the disabled Advanced Pricing roadmap control", () => {
      const products = compact(
        source(
          "../pages/products/ProductsPage.tsx",
        ),
      );

      expect(products).toContain(
        'navigate( "/products/advanced-uom" )',
      );
      expect(products).toContain(
        '"products.advancedUom.action"',
      );
      expect(products).toContain(
        '"products.advancedPricing"',
      );
      expect(products).toContain(
        '"products.advancedPricingHint"',
      );
      expect(products).toContain(
        "LockKeyhole",
      );
      expect(products).toMatch(
        /type="button" disabled title=\{t\( "products\.advancedPricingHint" \)\}/,
      );
    });

    it("offers deep-linked advanced UOM only for complex products in the detail drawer", () => {
      const drawer = compact(
        source(
          "../pages/products/ProductDetailDrawer.tsx",
        ),
      );
      const products = compact(
        source(
          "../pages/products/ProductsPage.tsx",
        ),
      );

      expect(drawer).toContain(
        "canManageAdvancedUom",
      );
      expect(drawer).toContain(
        "!product.simple_compatible",
      );
      expect(drawer).toContain(
        '"products.advancedUom.productAction"',
      );
      expect(products).toContain(
        'canManageAdvancedUom={ canManageCatalog }',
      );
      expect(products).toContain(
        "`/products/advanced-uom?variant=${product.id}`",
      );
    });
  },
);
