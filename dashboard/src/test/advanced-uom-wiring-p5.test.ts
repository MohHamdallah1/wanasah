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
      const header = compact(
        source(
          "../pages/products/ProductsPageHeader.tsx",
        ),
      );

      expect(products).toContain(
        'navigate( "/products/advanced-uom" )',
      );
      expect(header).toContain(
        '"products.advancedUom.action"',
      );
      expect(header).toContain(
        '"products.advancedPricing"',
      );
      expect(header).toContain(
        '"products.advancedPricingHint"',
      );
      expect(header).toContain(
        "LockKeyhole",
      );
      expect(header).toMatch(
        /type="button" disabled title=\{t\( "products\.advancedPricingHint" \)\}/,
      );
    });

    it("offers deep-linked advanced UOM only for complex products in the detail drawer", () => {
      const drawer = compact(
        source(
          "../pages/products/ProductDetailDrawer.tsx",
        ),
      );
      const detailWorkflow = compact(
        source(
          "../pages/products/detail/useProductDetailWorkflow.ts",
        ),
      );
      const detailActions = compact(
        source(
          "../pages/products/detail/createProductDetailActions.ts",
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
      expect(detailWorkflow).toContain(
        "canManageAdvancedUom: canManageCatalog",
      );
      expect(detailActions).toContain(
        "`/products/advanced-uom?variant=${product.id}`",
      );
    });
  },
);
