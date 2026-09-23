import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  parsePackageUoms,
  parseProductFamilies,
  parseProductImportAccepted,
  parseProductImportErrorPage,
  parseProductImportState,
  parseSimpleProductPage,
} from "../pages/products/contracts";


const readSource = (relativePath: string): string =>
  readFileSync(
    new URL(relativePath, import.meta.url),
    "utf8",
  );

const normalizeWhitespace = (value: string): string =>
  value.replace(/\s+/g, " ").trim();

const baseItem = {
  id: 10,
  product_id: 4,
  name: "Sample",
  family_name: "Sample family",
  sku: "SKU-10",
  units_per_package: 1,
  base_uom_id: 1,
  package_uom_id: null,
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

  it("fails closed on contradictory product UOM identity", () => {
    expect(() =>
      parseSimpleProductPage({
        currency_code: "JOD",
        pricing_visible: false,
        items: [
          {
            ...baseItem,
            package_uom_id: 2,
            package_uom_code: null,
          },
        ],
        next_cursor: null,
        has_more: false,
      }),
    ).toThrow("SIMPLE_PRODUCTS_RESPONSE_INVALID");
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

  it("parses families and UOM reference responses strictly", () => {
    expect(
      parseProductFamilies({
        items: [
          {
            id: 1,
            name: "Lolo",
            version: 2,
            variant_count: 3,
          },
        ],
      }).items[0].variant_count,
    ).toBe(3);

    expect(
      parsePackageUoms({
        items: [
          {
            id: 2,
            code: "CARTON",
          },
        ],
      }).items[0].code,
    ).toBe("CARTON");

    expect(() =>
      parseProductFamilies({
        items: [
          {
            id: 1,
            name: "Lolo",
            version: 0,
            variant_count: 3,
          },
        ],
      }),
    ).toThrow("PRODUCT_FAMILIES_RESPONSE_INVALID");
  });

  it("parses import acceptance, status and error pages at the boundary", () => {
    const jobId =
      "123e4567-e89b-42d3-a456-426614174000";

    const accepted =
      parseProductImportAccepted({
        job_id: jobId,
        status: "QUEUED",
        replayed: false,
        default_lot_control_mode: "OPTIONAL",
        default_expiry_control_mode: "NONE",
      });
    expect(accepted.job_id).toBe(jobId);

    const state =
      parseProductImportState({
        job_id: jobId,
        status: "NEEDS_MAPPING",
        file_name: "products.csv",
        total_rows: 10,
        processed_rows: 0,
        valid_rows: 0,
        failed_rows: 0,
        detected_headers: ["name"],
        suggested_mapping: {
          name: "name",
        },
        column_mapping: {},
        default_lot_control_mode: "OPTIONAL",
        default_expiry_control_mode: "NONE",
        error_summary: {},
        errors: [],
      });
    expect(state.status).toBe("NEEDS_MAPPING");

    const errors =
      parseProductImportErrorPage({
        items: [
          {
            row_number: 2,
            code: "INVALID_NAME",
            message: "Invalid",
          },
        ],
        next_after_row: null,
      });
    expect(errors.items[0].row_number).toBe(2);

    expect(() =>
      parseProductImportState({
        job_id: jobId,
        status: "UNKNOWN",
        file_name: "products.csv",
        total_rows: 0,
        processed_rows: 0,
        valid_rows: 0,
        failed_rows: 0,
        detected_headers: [],
        suggested_mapping: {},
        column_mapping: {},
        default_lot_control_mode: "OPTIONAL",
        default_expiry_control_mode: "NONE",
        error_summary: {},
        errors: [],
      }),
    ).toThrow("PRODUCT_IMPORT_STATE_RESPONSE_INVALID");
  });

  it("allows catalog-only users to reach Products navigation and route", () => {
    const layout = normalizeWhitespace(
      readSource(
        "../components/operations/DashboardLayout.tsx",
      ),
    );
    const sidebar = normalizeWhitespace(
      readSource(
        "../components/operations/OperationsSidebar.tsx",
      ),
    );

    expect(layout).toContain(
      'location.pathname === "/products" && !access.canAny("catalog.read")',
    );
    expect(layout).not.toContain(
      'access.canAny("catalog.read") && access.canAny("pricing.view")',
    );
    expect(sidebar).toContain(
      'item.path === "/products" && access.canAny( "catalog.read" )',
    );
  });

  it("keeps dashboard caches tenant scoped and pricing UI permission aware", () => {
    const page = normalizeWhitespace(
      readSource(
        "../pages/ProductsDashboard.tsx",
      ),
    );

    expect(page).toContain(
      '"simple-products", companyId, search, cursor',
    );
    expect(page).toContain(
      '"simple-product-families", companyId',
    );
    expect(page).toContain(
      'access.canAny( "pricing.view" )',
    );
    expect(page).toContain(
      "page?.pricing_visible && canViewPricing",
    );
    expect(page).toContain(
      "{pricingVisible ? (",
    );
    expect(page).toContain(
      '"products.fields.sku"',
    );
    expect(page).toContain(
      "canEditSimplePrice && pricingVisible && item.simple_compatible",
    );
    expect(page).toContain(
      "setCursor(null); setHistory([]);",
    );
  });
});
