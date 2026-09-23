import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { parseSimpleProductPage } from "../pages/products/contracts";


const readSource = (relativePath: string): string =>
  readFileSync(
    new URL(relativePath, import.meta.url),
    "utf8",
  );

const baseItem = {
  id: 10,
  product_id: 4,
  name: "Sample",
  family_name: "Sample family",
  sku: "SKU-10",
  units_per_package: 1,
  package_uom_code: null,
  currency_code: "JOD",
  package_price: null,
  unit_price: null,
  unit_barcode: null,
  package_barcode: null,
  package_uses_base_barcode: false,
  version: 3,
  lot_control_mode: "OPTIONAL",
  expiry_control_mode: "NONE",
  lifecycle_status: "ACTIVE",
  simple_compatible: true,
} as const;

describe("products P2 read contract", () => {
  it("parses catalog identity without pricing permission", () => {
    const page = parseSimpleProductPage({
      currency_code: "JOD",
      pricing_visible: false,
      items: [baseItem],
      next_cursor: null,
      has_more: false,
    });

    expect(page.pricing_visible).toBe(false);
    expect(page.items[0].sku).toBe("SKU-10");
    expect(page.items[0].lot_control_mode).toBe("OPTIONAL");
    expect(page.items[0].expiry_control_mode).toBe("NONE");
    expect(page.items[0].lifecycle_status).toBe("ACTIVE");
    expect(page.items[0].package_price).toBeNull();
    expect(page.items[0].unit_price).toBeNull();
  });

  it("fails closed if hidden pricing leaks into a catalog-only payload", () => {
    expect(() =>
      parseSimpleProductPage({
        currency_code: "JOD",
        pricing_visible: false,
        items: [
          {
            ...baseItem,
            unit_price: "0.200000",
          },
        ],
        next_cursor: null,
        has_more: false,
      }),
    ).toThrow("SIMPLE_PRODUCTS_RESPONSE_INVALID");
  });

  it("accepts exact decimal pricing when the server marks pricing visible", () => {
    const page = parseSimpleProductPage({
      currency_code: "JOD",
      pricing_visible: true,
      items: [
        {
          ...baseItem,
          package_price: "10.000000",
          unit_price: "0.200000",
        },
      ],
      next_cursor: null,
      has_more: false,
    });

    expect(page.pricing_visible).toBe(true);
    expect(page.items[0].package_price).toBe("10.000000");
    expect(page.items[0].unit_price).toBe("0.200000");
  });

  it("keeps dashboard caches tenant scoped and pricing UI permission aware", () => {
    const page = readSource(
      "../pages/ProductsDashboard.tsx",
    );

    expect(page).toContain(
      '"simple-products",\n        companyId,',
    );
    expect(page).toContain(
      '"simple-product-families",\n        companyId,',
    );
    expect(page).toContain(
      'access.canAny(\n      "pricing.view"',
    );
    expect(page).toContain(
      "page?.pricing_visible &&",
    );
    expect(page).toContain(
      "{pricingVisible ? (",
    );
    expect(page).toContain(
      '"products.fields.sku"',
    );
    expect(page).toContain(
      "pricingVisible &&\n                          item.simple_compatible",
    );
  });
});
