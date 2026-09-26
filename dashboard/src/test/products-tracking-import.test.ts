import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const readSource = (relativePath: string): string =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

const normalizeWhitespace = (value: string): string =>
  value.replace(/\s+/g, " ").trim();

describe("product import tracking workflow", () => {
  it("loads tenant defaults and sends an immutable import tracking snapshot", () => {
    const trackingQuery = normalizeWhitespace(
      readSource("../pages/products/tracking/useTrackingDefaultsQuery.ts"),
    );
    const importUpload = normalizeWhitespace(
      readSource("../pages/products/import/useImportProductUpload.ts"),
    );

    expect(trackingQuery).toContain(
      '"/simple-products/tracking/defaults"',
    );
    expect(importUpload).toContain(
      'form.append( "default_lot_control_mode", importLotControlMode );',
    );
    expect(importUpload).toContain(
      'form.append( "default_expiry_control_mode", importExpiryControlMode );',
    );
    expect(importUpload).toContain(
      '${fingerprint}:${importLotControlMode}:${importExpiryControlMode}',
    );
  });

  it("supports optional per-row tracking overrides in mapping and template", () => {
    const importFields = normalizeWhitespace(
      readSource("../pages/products/import/importFields.ts"),
    );
    const startPanel = normalizeWhitespace(
      readSource("../pages/products/import/ImportProductStartPanel.tsx"),
    );

    expect(importFields).toContain('"lot_control_mode"');
    expect(importFields).toContain('"expiry_control_mode"');
    expect(importFields).toContain(
      '"products.fields.lotControlMode"',
    );
    expect(importFields).toContain(
      '"products.fields.expiryControlMode"',
    );
    expect(startPanel).toContain("<ProductTrackingFields");
  });

  it("keeps import tracking compact by default and makes per-import overrides explicit", () => {
    const page = normalizeWhitespace(
      readSource("../pages/products/ProductsPage.tsx"),
    );
    const importStart = normalizeWhitespace(
      readSource("../pages/products/import/ImportProductStartPanel.tsx"),
    );
    const importHelpers = normalizeWhitespace(
      readSource("../pages/products/import/helpers.ts"),
    );
    const translations = readSource("../i18n/resources.ts");

    expect(importHelpers).toContain(
      "usesCompanyImportTrackingDefaults",
    );
    expect(importStart).toContain(
      "!trackingExpanded ?",
    );
    expect(importStart).toContain(
      '"products.importTrackingChange"',
    );
    expect(importStart).toContain(
      '"products.importTrackingReset"',
    );
    expect(importStart).toContain(
      '"products.importTrackingOnlyThisImport"',
    );

    expect(translations).toContain(
      'importTrackingCompanyScope:',
    );
    expect(translations).toContain(
      'importTrackingCustomScope:',
    );
    expect(translations).toContain(
      'importTrackingChange:',
    );
    expect(translations).toContain(
      'importTrackingReset:',
    );
  });

  it("uses localized tracking values in the downloadable template and guidance", () => {
    const page = normalizeWhitespace(
      readSource("../pages/products/ProductsPage.tsx"),
    );
    const importModal = normalizeWhitespace(
      readSource("../pages/products/import/ImportProductModal.tsx"),
    );
    const importDownloads = normalizeWhitespace(
      readSource("../pages/products/import/createImportDownloads.ts"),
    );
    const translations = readSource("../i18n/resources.ts");

    expect(importDownloads).toContain(
      '"products.tracking.importValues.REQUIRED"',
    );
    expect(importStart).toContain(
      '"products.importTrackingValueHint"',
    );
    expect(page).not.toContain(
      '"REQUIRED", "REQUIRED",',
    );

    expect(translations).toContain(
      'importValues: {',
    );
    expect(translations).toContain(
      'importTrackingValueHint:',
    );
  });

  it("keeps tracking mode values language-neutral and translates labels", () => {
    const controls = readSource(
      "../pages/products/tracking/ProductTrackingFields.tsx",
    );
    const picker = readSource(
      "../pages/products/tracking/ProductTrackingModePicker.tsx",
    );
    const contracts = readSource(
      "../pages/products/contracts.ts",
    );
    const translations = readSource("../i18n/resources.ts");

    expect(contracts).toContain(
      "export type ProductTrackingMode =",
    );
    expect(contracts).toContain('"NONE"');
    expect(contracts).toContain('"OPTIONAL"');
    expect(contracts).toContain('"REQUIRED"');
    expect(controls).toContain(
      "<ProductTrackingModePicker",
    );
    expect(picker).toContain(
      '"NONE"',
    );
    expect(picker).toContain(
      '"OPTIONAL"',
    );
    expect(picker).toContain(
      '"REQUIRED"',
    );
    expect(picker).toContain(
      "products.tracking.lotModes",
    );
    expect(picker).toContain(
      "products.tracking.expiryModes",
    );
    expect(picker).toContain(
      '"products.tracking.lotExample"',
    );
    expect(picker).toContain(
      '"products.tracking.expiryExample"',
    );

    expect(translations).toContain(
      'importTrackingTitle:',
    );
    expect(translations).toContain(
      'lotControlMode:',
    );
    expect(translations).toContain(
      'expiryControlMode:',
    );
  });
});
