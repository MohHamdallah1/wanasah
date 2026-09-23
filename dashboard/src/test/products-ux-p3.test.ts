import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";


const readSource = (relativePath: string): string =>
  readFileSync(
    new URL(relativePath, import.meta.url),
    "utf8",
  );

const compact = (value: string): string =>
  value.replace(/\s+/g, " ").trim();

describe("Products P3 detail foundation", () => {
  it("provides a canonical product detail drawer with identity and operational context", () => {
    const drawer = compact(
      readSource(
        "../pages/products/ProductDetailDrawer.tsx",
      ),
    );

    expect(drawer).toContain(
      'role="dialog"',
    );
    expect(drawer).toContain(
      'aria-modal="true"',
    );
    expect(drawer).toContain(
      "product.sku",
    );
    expect(drawer).toContain(
      "product.lifecycle_status",
    );
    expect(drawer).toContain(
      "product.lot_control_mode",
    );
    expect(drawer).toContain(
      "product.expiry_control_mode",
    );
    expect(drawer).toContain(
      "product.unit_barcode",
    );
    expect(drawer).toContain(
      "product.package_barcode",
    );
    expect(drawer).toContain(
      "product.simple_compatible",
    );
  });

  it("keeps pricing and mutation actions permission aware inside the drawer", () => {
    const drawer = compact(
      readSource(
        "../pages/products/ProductDetailDrawer.tsx",
      ),
    );

    expect(drawer).toContain(
      "{pricingVisible ? (",
    );
    expect(drawer).toContain(
      "canEditPrice && pricingVisible && product.simple_compatible",
    );
    expect(drawer).toContain(
      "{canEditTracking ? (",
    );
  });

  it("makes details available to catalog readers without requiring manage permissions", () => {
    const page = compact(
      readSource(
        "../pages/ProductsDashboard.tsx",
      ),
    );

    expect(page).toContain(
      "setDetailProduct( item )",
    );
    expect(page).toContain(
      '"products.details.open"',
    );
    expect(page).toContain(
      "canEditTracking={ canManageCatalog }",
    );
    expect(page).toContain(
      "canEditPrice={ canManage && pricingVisible }",
    );
  });

  it("keeps the new P3 surface locale-driven and direction-aware", () => {
    const drawer = readSource(
      "../pages/products/ProductDetailDrawer.tsx",
    );
    const translations = readSource(
      "../i18n/resources.ts",
    );

    expect(drawer).toContain(
      "dir={i18n.dir()}",
    );
    expect(drawer).not.toContain(
      'dir="rtl"',
    );
    expect(drawer).not.toContain(
      'dir="ltr"',
    );
    expect(translations).toContain(
      'open: "عرض التفاصيل"',
    );
    expect(translations).toContain(
      'open: "View details"',
    );
  });
});
