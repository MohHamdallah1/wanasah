import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const readSource = (relativePath: string): string =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

const normalizeWhitespace = (value: string): string =>
  value.replace(/\s+/g, " ").trim();

describe("product import tracking workflow", () => {
  it("loads tenant defaults and sends an immutable import tracking snapshot", () => {
    const page = normalizeWhitespace(
      readSource("../pages/ProductsDashboard.tsx"),
    );

    expect(page).toContain(
      '"/simple-products/tracking/defaults"',
    );
    expect(page).toContain(
      'form.append( "default_lot_control_mode", importLotControlMode );',
    );
    expect(page).toContain(
      'form.append( "default_expiry_control_mode", importExpiryControlMode );',
    );
    expect(page).toContain(
      '${fingerprint}:${importLotControlMode}:${importExpiryControlMode}',
    );
  });

  it("supports optional per-row tracking overrides in mapping and template", () => {
    const page = normalizeWhitespace(
      readSource("../pages/ProductsDashboard.tsx"),
    );

    expect(page).toContain('"lot_control_mode"');
    expect(page).toContain('"expiry_control_mode"');
    expect(page).toContain(
      '"products.fields.lotControlMode"',
    );
    expect(page).toContain(
      '"products.fields.expiryControlMode"',
    );
    expect(page).toContain("<ProductTrackingFields");
  });

  it("keeps import tracking compact by default and makes per-import overrides explicit", () => {
    const page = normalizeWhitespace(
      readSource("../pages/ProductsDashboard.tsx"),
    );
    const translations = readSource("../i18n/resources.ts");

    expect(page).toContain(
      "importTrackingUsesCompanyDefaults",
    );
    expect(page).toContain(
      "!importTrackingExpanded ?",
    );
    expect(page).toContain(
      '"products.importTrackingChange"',
    );
    expect(page).toContain(
      '"products.importTrackingReset"',
    );
    expect(page).toContain(
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
      readSource("../pages/ProductsDashboard.tsx"),
    );
    const translations = readSource("../i18n/resources.ts");

    expect(page).toContain(
      '"products.tracking.importValues.REQUIRED"',
    );
    expect(page).toContain(
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
      "../pages/products/ProductTrackingFields.tsx",
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
      'products.tracking.lotModes.${mode}',
    );
    expect(controls).toContain(
      'products.tracking.expiryModes.${mode}',
    );
    expect(controls).toContain(
      'products.tracking.lotExample',
    );
    expect(controls).toContain(
      'products.tracking.expiryExample',
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
