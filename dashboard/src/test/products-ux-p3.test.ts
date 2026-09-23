import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  formatLocaleDecimal,
  formatLocaleMoney,
} from "../lib/localeNumbers";

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
      "canEditPrice && product.simple_compatible",
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
      "canEditPrice={ canEditSimplePrice }",
    );
  });

  it("keeps ordinary creation compact and moves supported exceptions to Advanced settings", () => {
    const page = compact(
      readSource(
        "../pages/ProductsDashboard.tsx",
      ),
    );
    const translations = readSource(
      "../i18n/resources.ts",
    );

    expect(page).toContain(
      "createAdvancedExpanded",
    );
    expect(page).toContain(
      '"products.quickCreate.advancedTitle"',
    );
    expect(page).toContain(
      '"products.quickCreate.trackingAdvancedHint"',
    );
    expect(page).toContain(
      '"products.quickCreate.systemManagedHint"',
    );
    expect(page).toContain(
      '"products.barcodeSection"',
    );
    expect(page).toContain(
      "setCreateAdvancedExpanded( false )",
    );
    expect(translations).toContain(
      'advancedTitle: "إعدادات متقدمة"',
    );
    expect(translations).toContain(
      'advancedTitle: "Advanced settings"',
    );
  });

  it("shows a distinct product-list failure with an in-page retry", () => {
    const page = compact(
      readSource(
        "../pages/ProductsDashboard.tsx",
      ),
    );

    expect(page).toContain(
      "{productsQuery.isError ? (",
    );
    expect(page).toContain(
      "void productsQuery.refetch()",
    );
    expect(page).toContain(
      "!productsQuery.isError && !page?.items.length",
    );
    expect(page).toContain(
      '"products.errors.listLoadTitle"',
    );
  });

  it("uses action-specific frontend capabilities instead of one coarse canManage flag", () => {
    const page = compact(
      readSource(
        "../pages/ProductsDashboard.tsx",
      ),
    );

    expect(page).toContain(
      "const canCreateSimpleProduct =",
    );
    expect(page).toContain(
      "const canImportProducts = canCreateSimpleProduct;",
    );
    expect(page).toContain(
      "const canManageFamilies = canManageCatalog;",
    );
    expect(page).toContain(
      "const canEditSimplePrice = canManagePricing;",
    );
    expect(page).toContain(
      "{canManageFamilies ? (",
    );
    expect(page).toContain(
      "{canImportProducts ? (",
    );
    expect(page).not.toContain(
      "const canManage =",
    );
  });

  it("manages barcodes through the authoritative catalog endpoints", () => {
    const page = compact(
      readSource(
        "../pages/ProductsDashboard.tsx",
      ),
    );
    const drawer = compact(
      readSource(
        "../pages/products/ProductDetailDrawer.tsx",
      ),
    );
    const manager = compact(
      readSource(
        "../pages/products/ProductBarcodeManager.tsx",
      ),
    );
    const catalogBackend = compact(
      readSource(
        "../../../wa_backend/api/catalog.py",
      ),
    );

    expect(page).toContain(
      "canManageBarcodes={ canManageCatalog }",
    );
    expect(page).toContain(
      "<ProductBarcodeManager",
    );
    expect(drawer).toContain(
      '"products.barcodeManager.action"',
    );
    expect(manager).toContain(
      '"/catalog/variants/" + product.id + "/barcodes"',
    );
    expect(manager).toContain(
      '"/catalog/barcodes/" + item.id',
    );
    expect(manager).toContain(
      "expected_version: item.version",
    );
    expect(manager).toContain(
      "is_active: false",
    );
    expect(manager).toContain(
      "valid_to: null",
    );
    expect(manager).toContain(
      "getOrCreateDurableRequestId",
    );
    expect(manager).toContain(
      "completeDurableOperation",
    );
    expect(manager).toContain(
      "durableScope",
    );
    expect(manager).not.toContain(
      "crypto.randomUUID()",
    );
    expect(manager).toContain(
      "new AbortController()",
    );
    expect(manager).toContain(
      "requestSequence.current",
    );
    expect(manager).toContain(
      "item.product_variant_id !== productId",
    );
    expect(manager).toContain(
      "loadReady && !loadError",
    );
    expect(manager).toContain(
      '"products.barcodeManager.added"',
    );
    expect(manager).toContain(
      '"products.barcodeManager.deactivated"',
    );
    expect(catalogBackend).toContain(
      "valid_from: Optional[datetime] = None",
    );
    expect(catalogBackend).toContain(
      "not payload.is_active and valid_to is None",
    );
  });

  it("formats P3 decimal and money values with locale-aware exact string presentation", () => {
    expect(
      formatLocaleDecimal(
        "1234.500000",
        "en-US",
        3,
        6,
      ),
    ).toBe("1,234.500");

    const arabic =
      formatLocaleDecimal(
        "1234.500000",
        "ar-JO",
        3,
        6,
      );
    expect(arabic).toContain("١");
    expect(arabic).toContain("٫");
    expect(
      formatLocaleMoney(
        "12.345000",
        "JOD",
        "en-US",
      ),
    ).toBe("12.345 JOD");
  });

  it("keeps the new P3 surface locale-driven and direction-aware", () => {
    const drawer = readSource(
      "../pages/products/ProductDetailDrawer.tsx",
    );
    const translations = readSource(
      "../i18n/resources.ts",
    );
    const modal = readSource(
      "../components/ui/modal.tsx",
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
    expect(drawer).toContain(
      "formatLocaleMoney",
    );
    expect(drawer).toContain(
      "formatLocaleDecimal",
    );
    expect(modal).toContain(
      "dir={i18n.dir()}",
    );
    expect(modal).toContain(
      'aria-label={t("common.close")}',
    );
    expect(translations).toContain(
      'open: "عرض التفاصيل"',
    );
    expect(translations).toContain(
      'open: "View details"',
    );
  });
});
