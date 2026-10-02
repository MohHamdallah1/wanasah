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

describe("Products barcode workspace", () => {
  it("keeps the everyday flow current-first and hides technical barcode metadata", () => {
    const manager = read(
      "../pages/products/barcode/ProductBarcodeManager.tsx",
    );
    const simple = read(
      "../pages/products/barcode/ProductBarcodeSimplePanel.tsx",
    );

    expect(manager).toContain(
      "<ProductBarcodeSimplePanel",
    );
    expect(manager).toContain(
      "<ProductBarcodeHistoryPanel",
    );
    expect(manager).toContain(
      '"products.barcodeManager.history"',
    );
    expect(manager).not.toContain(
      "<ProductBarcodeAdvancedPanel",
    );
    expect(manager).not.toContain(
      "<ProductBarcodeCreatePanel",
    );

    expect(simple).toContain(
      '"products.barcodeManager.unitBarcode"',
    );
    expect(simple).toContain(
      '"products.barcodeManager.packageBarcode"',
    );
    expect(simple).toContain(
      '"products.barcodeManager.change"',
    );
    expect(simple).toContain(
      '"products.barcodeManager.set"',
    );
    expect(simple).not.toContain(
      "barcodeType",
    );
    expect(simple).not.toContain(
      "isPrimary",
    );
    expect(simple).not.toContain(
      "barcode_type",
    );
    expect(simple).not.toContain(
      "restorePrevious",
    );
  });

  it("lets a shared package become independent through one atomic workflow", () => {
    const simple = read(
      "../pages/products/barcode/ProductBarcodeSimplePanel.tsx",
    );
    const hook = read(
      "../pages/products/barcode/useIndependentPackageBarcode.ts",
    );
    const api = read(
      "../../../wa_backend/api/catalog.py",
    );
    const domain = read(
      "../../../wa_backend/domains/barcode_identity.py",
    );

    expect(simple).toContain(
      '"products.barcodeManager.makePackageIndependent"',
    );
    expect(simple).toContain(
      "onAssignIndependentPackage",
    );
    expect(hook).toContain(
      '"catalog-package-barcode-independent-v1"',
    );
    expect(hook).toContain(
      '"/barcodes/package-independent"',
    );
    expect(hook).toContain(
      "expected_variant_version:",
    );

    expect(api).toContain(
      'operation="CATALOG_PACKAGE_BARCODE_INDEPENDENT"',
    );
    expect(api).toContain(
      "assign_independent_package_barcode(",
    );
    expect(domain).toContain(
      "variant.package_uses_base_barcode = False",
    );
    expect(domain).toContain(
      "replace_primary_barcode(",
    );
  });

  it("moves removal and reuse into explicit barcode history", () => {
    const history = read(
      "../pages/products/barcode/ProductBarcodeHistoryPanel.tsx",
    );
    const manager = read(
      "../pages/products/barcode/ProductBarcodeManager.tsx",
    );

    expect(history).toContain(
      '"products.barcodeManager.historyDescription"',
    );
    expect(history).toContain(
      '"products.barcodeManager.useAgain"',
    );
    expect(history).toContain(
      '"products.barcodeManager.removeFromProduct"',
    );
    expect(history).toContain(
      '"products.barcodeManager.removeConfirm"',
    );
    expect(history).toContain(
      "item.valid_from",
    );
    expect(history).toContain(
      "item.valid_to",
    );
    expect(history).not.toContain(
      "barcode_type",
    );
    expect(history).not.toContain(
      '"products.barcodeManager.primary"',
    );

    expect(manager).toContain(
      '"catalog-barcode-update"',
    );
    expect(manager).toContain(
      '"products.barcodeManager.removed"',
    );
  });

  it("keeps keyboard-first barcode editing", () => {
    const simple = read(
      "../pages/products/barcode/ProductBarcodeSimplePanel.tsx",
    );

    expect(simple).toContain(
      'event.key ===',
    );
    expect(simple).toContain(
      '"Enter"',
    );
    expect(simple).toContain(
      '"Escape"',
    );
    expect(simple).toContain(
      "autoFocus",
    );
  });

  it("keeps barcode loading race-safe and tenant-scoped", () => {
    const manager = read(
      "../pages/products/barcode/ProductBarcodeManager.tsx",
    );
    const replacement = read(
      "../pages/products/barcode/usePrimaryBarcodeReplacement.ts",
    );

    expect(manager).toContain(
      "requestSequence.current",
    );
    expect(manager).toContain(
      "PRODUCT_BARCODES_SCOPE_MISMATCH",
    );
    expect(manager).toContain(
      "PRODUCT_BARCODES_CURSOR_DUPLICATE",
    );
    expect(replacement).toContain(
      '"catalog-barcode-replace-primary-v1"',
    );
    expect(replacement).toContain(
      '"/barcodes/replace-primary"',
    );
  });
});
