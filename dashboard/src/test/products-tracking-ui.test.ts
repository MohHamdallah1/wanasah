import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  parseProductTrackingDefaults,
  parseProductTrackingMutation,
  parseSimpleProductPage,
} from "../pages/products/contracts";

const readSource = (relativePath: string): string =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

const normalizeWhitespace = (value: string): string =>
  value.replace(/\s+/g, " ").trim();

describe("products tracking UI contracts", () => {
  it("parses strict company defaults and rejects unknown tracking values", () => {
    expect(
      parseProductTrackingDefaults({
        lot_control_mode: "OPTIONAL",
        expiry_control_mode: "REQUIRED",
        lot_control_source: "COMPANY",
        expiry_control_source: "PLATFORM_FALLBACK",
      }),
    ).toEqual({
      lot_control_mode: "OPTIONAL",
      expiry_control_mode: "REQUIRED",
      lot_control_source: "COMPANY",
      expiry_control_source: "PLATFORM_FALLBACK",
    });

    expect(() =>
      parseProductTrackingDefaults({
        lot_control_mode: "MAYBE",
        expiry_control_mode: "REQUIRED",
        lot_control_source: "COMPANY",
        expiry_control_source: "COMPANY",
      }),
    ).toThrow("PRODUCT_TRACKING_DEFAULTS_RESPONSE_INVALID");
  });

  it("parses versioned product rows and tracking mutation responses", () => {
    const page = parseSimpleProductPage({
      currency_code: "JOD",
      pricing_visible: true,
      items: [
        {
          id: 10,
          product_id: 4,
          name: "Sample",
          family_name: "Sample",
          sku: "SKU-10",
          units_per_package: 50,
          legacy_packs_per_carton: 50,
          base_uom_id: 1,
          package_uom_id: 2,
          package_uom_code: "CARTON",
          currency_code: "JOD",
          package_price: "10.000000",
          unit_price: "0.200000",
          unit_barcode: null,
          package_barcode: null,
          package_uses_base_barcode: false,
          version: 3,
          lot_control_mode: "REQUIRED",
          expiry_control_mode: "REQUIRED",
          lifecycle_status: "ACTIVE",
          operational_hold: "NONE",
          simple_compatible: true,
        },
      ],
      next_cursor: null,
      has_more: false,
    });

    expect(page.items[0].version).toBe(3);
    expect(page.items[0].lot_control_mode).toBe("REQUIRED");

    expect(
      parseProductTrackingMutation({
        product_variant_id: 10,
        version: 4,
        lot_control_mode: "OPTIONAL",
        expiry_control_mode: "REQUIRED",
        changed: true,
      }),
    ).toEqual({
      product_variant_id: 10,
      version: 4,
      lot_control_mode: "OPTIONAL",
      expiry_control_mode: "REQUIRED",
      changed: true,
    });
  });

  it("uses explicit tracking in create, company defaults, and per-product editing", () => {
    const page = normalizeWhitespace(
      readSource("../pages/ProductsDashboard.tsx"),
    );

    expect(page).toContain(
      "wanasah:product-draft:v2:",
    );
    expect(page).toContain(
      "lot_control_mode: draft.lot_control_mode",
    );
    expect(page).toContain(
      "expiry_control_mode: draft.expiry_control_mode",
    );
    expect(page).toContain(
      "parseSimpleProductPage(",
    );
    expect(page).toContain(
      "parseProductTrackingDefaults(",
    );
    expect(page).toContain(
      "parseProductTrackingMutation(",
    );
    expect(page).toContain(
      "<ProductTrackingSettings",
    );
    expect(page).toContain(
      "<ProductTrackingEditor",
    );
    expect(page).toContain(
      "expected_version: trackingEdit.version",
    );
  });

  it("keeps quick create simple while preserving explicit per-product tracking overrides", () => {
    const page = normalizeWhitespace(
      readSource("../pages/ProductsDashboard.tsx"),
    );
    const translations = readSource("../i18n/resources.ts");

    expect(page).toContain(
      "createTrackingUsesCompanyDefaults",
    );
    expect(page).toContain(
      "!createTrackingExpanded ?",
    );
    expect(page).toContain(
      '"products.tracking.createChange"',
    );
    expect(page).toContain(
      '"products.tracking.createReset"',
    );
    expect(page).toContain(
      '"products.tracking.createOnlyThisProduct"',
    );

    expect(translations).toContain(
      "createCompanyScope:",
    );
    expect(translations).toContain(
      "createCustomScope:",
    );
    expect(translations).toContain(
      "createChange:",
    );
    expect(translations).toContain(
      "createReset:",
    );
  });

  it("does not submit an unchanged tracking edit", () => {
    const editor = normalizeWhitespace(
      readSource("../pages/products/ProductTrackingEditor.tsx"),
    );

    expect(editor).toContain(
      "const changed = product !== null &&",
    );
    expect(editor).toContain(
      "product.lot_control_mode",
    );
    expect(editor).toContain(
      "product.expiry_control_mode",
    );
    expect(editor).toContain(
      "product === null || !changed",
    );
  });

  it("keeps the touched tracking UI locale-driven", () => {
    const files = [
      readSource("../pages/ProductsDashboard.tsx"),
      readSource("../pages/products/ProductTrackingFields.tsx"),
      readSource("../pages/products/ProductTrackingSettings.tsx"),
      readSource("../pages/products/ProductTrackingEditor.tsx"),
    ];

    for (const source of files) {
      expect(source).not.toContain('dir="rtl"');
      expect(source).not.toContain('dir="ltr"');
    }
  });

  it("keeps tracking management on catalog.manage instead of pricing permissions", () => {
    const page = normalizeWhitespace(
      readSource("../pages/ProductsDashboard.tsx"),
    );
    const row = normalizeWhitespace(
      readSource("../pages/products/ProductTableRow.tsx"),
    );

    expect(page).toContain(
      'const canManageCatalog = access.isCompanyAdmin || access.canAny( "catalog.manage" );',
    );
    expect(page).toContain(
      "canEditTracking={ canManageCatalog }",
    );
    expect(page).toContain(
      "onEditTracking={ openTrackingEditor }",
    );
    expect(row).toContain(
      "{canEditTracking ? (",
    );
    expect(row).toContain(
      "onEditTracking(item)",
    );
  });

  it("uses translated, plain-language guidance and lock errors", () => {
    const translations = readSource("../i18n/resources.ts");

    expect(translations).toContain(
      'lotLabel: "رقم الدفعة / التشغيلة من المصنع"',
    );
    expect(translations).toContain(
      'expiryLabel: "تاريخ انتهاء الصلاحية"',
    );
    expect(translations).toContain(
      'action: "افتراضيات التتبع"',
    );
    expect(translations).toContain(
      'title: "افتراضيات تتبع المنتجات الجديدة"',
    );
    expect(translations).toContain(
      "لا تغيّر أي منتج موجود",
    );
    expect(translations).toContain(
      "PRODUCT_TRACKING_LOCKED:",
    );
    expect(translations).toContain(
      "PRODUCT_TRACKING_VERSION_CONFLICT:",
    );
    expect(translations).toContain(
      "PRODUCT_TRACKING_DEFAULTS_RESPONSE_INVALID:",
    );
  });
});
