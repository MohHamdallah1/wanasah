import { readFileSync } from "node:fs";

import {
  describe,
  expect,
  it,
} from "vitest";

import {
  parseSimpleProductPage,
} from "../pages/products/contracts";

const source = (
  relativePath: string,
) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  )
    .replace(/\s+/g, " ")
    .trim();

describe("Products P9 package and unit structure", () => {
  it("keeps the authoritative base UOM code in the Simple Products read contract", () => {
    const page = parseSimpleProductPage({
      currency_code: "JOD",
      pricing_visible: true,
      items: [
        {
          id: 11,
          product_id: 4,
          name: "Packaged Product",
          family_name: "Snacks",
          sku: "PKG-11",
          units_per_package: 50,
          legacy_packs_per_carton: 50,
          base_uom_id: 1,
          base_uom_code: "EACH",
          package_uom_id: 2,
          package_uom_code: "CARTON",
          currency_code: "JOD",
          package_price: "13.500000",
          unit_price: "0.270000",
          unit_barcode: null,
          package_barcode: null,
          package_uses_base_barcode: false,
          version: 5,
          lot_control_mode: "OPTIONAL",
          expiry_control_mode: "NONE",
          lifecycle_status: "ACTIVE",
          operational_hold: "NONE",
          simple_compatible: true,
        },
      ],
      next_cursor: null,
      has_more: false,
    });

    expect(
      page.items[0]?.base_uom_code,
    ).toBe("EACH");
  });

  it("returns base UOM code from the existing SaleShape instead of inventing frontend conversion data", () => {
    const backend = source(
      "../../../wa_backend/api/simple_products.py",
    );

    expect(backend).toContain(
      '"base_uom_code": ( str(shape.base_uom.code) if shape is not None else None )',
    );
  });

  it("shows package controls only when the user explicitly enables an outer package", () => {
    const modal = source(
      "../pages/products/create/CreateProductModal.tsx",
    );

    expect(modal).toContain(
      "{draft.has_package ? (",
    );
    expect(modal).toContain(
      '"products.packageType"',
    );
    expect(modal).toContain(
      '"products.unitsPerPackage"',
    );
    expect(modal).toContain(
      '"products.packagePrice"',
    );
    expect(modal).toContain(
      '"products.packageBarcode"',
    );
    expect(modal).toContain(
      '"products.noOuterPackage"',
    );
  });

  it("shows the base unit and a plain-language package conversion in Product Details", () => {
    const drawer = source(
      "../pages/products/detail/ProductDetailDrawer.tsx",
    );

    expect(drawer).toContain(
      '"products.details.baseUnit"',
    );
    expect(drawer).toContain(
      '"products.details.packageConversion"',
    );
    expect(drawer).toContain(
      '"products.details.unitOnlyStructure"',
    );
    expect(drawer).toContain(
      '"products.details.packageStructureLockedPublished"',
    );
    expect(drawer).toContain(
      "product.base_uom_code",
    );
  });

  it("keeps published structural edits locked while Advanced UOM edits only DRAFT conversions", () => {
    const advanced = source(
      "../pages/products/advanced-uom/AdvancedUomDashboard.tsx",
    );

    expect(advanced).toContain(
      'lifecycle_status !== "DRAFT"',
    );
    expect(advanced).toContain(
      '"UOM_STRUCTURE_LOCKED"',
    );
  });

  it("keeps simple package and barcode creation backend-authoritative without React conversion writes", () => {
    const mutation = source(
      "../pages/products/create/useCreateProductMutation.ts",
    );

    expect(mutation).toContain(
      'authFetch( "/simple-products/"',
    );
    expect(mutation).toContain(
      "package_uom_code:",
    );
    expect(mutation).toContain(
      "units_per_package:",
    );
    expect(mutation).toContain(
      "unit_barcode:",
    );
    expect(mutation).toContain(
      "package_barcode:",
    );
    expect(mutation).not.toContain(
      "/conversions",
    );
  });
});
