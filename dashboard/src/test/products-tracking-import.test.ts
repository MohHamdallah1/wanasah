import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const readSource = (relativePath: string): string =>
  readFileSync(new URL(relativePath, import.meta.url), "utf8");

const normalizeWhitespace = (value: string): string =>
  value.replace(/\s+/g, " ").trim();

describe("product import tracking workflow", () => {
  it("loads tenant defaults only when the selected file needs a fallback", () => {
    const workflow = normalizeWhitespace(
      readSource("../pages/products/import/useImportProductWorkflow.ts"),
    );
    const sync = normalizeWhitespace(
      readSource("../pages/products/import/useImportTrackingDefaultsSync.ts"),
    );
    const importUpload = normalizeWhitespace(
      readSource("../pages/products/import/useImportProductUpload.ts"),
    );

    expect(workflow).toContain(
      'filePreflight.result.tracking.status !== "NOT_NEEDED"',
    );
    expect(workflow).toContain(
      "enabled: trackingFallbackRequired",
    );
    expect(sync).toContain(
      "!enabled || !importOpen",
    );
    expect(importUpload).toContain(
      'if ( importLotControlMode ) { form.append( "default_lot_control_mode", importLotControlMode ); }',
    );
    expect(importUpload).toContain(
      'if ( importExpiryControlMode ) { form.append( "default_expiry_control_mode", importExpiryControlMode ); }',
    );
    expect(importUpload).toContain(
      'importLotControlMode ?? "SERVER_DEFAULT"',
    );
    expect(importUpload).toContain(
      'importExpiryControlMode ?? "SERVER_DEFAULT"',
    );
  });

  it("supports optional per-row tracking overrides and shows fallback controls only contextually", () => {
    const importFields = normalizeWhitespace(
      readSource("../pages/products/import/importFields.ts"),
    );
    const startPanel = normalizeWhitespace(
      readSource("../pages/products/import/ImportProductStartPanel.tsx"),
    );
    const fallbackPanel = normalizeWhitespace(
      readSource("../pages/products/import/ImportTrackingFallbackPanel.tsx"),
    );

    expect(importFields).toContain('"lot_control_mode"');
    expect(importFields).toContain('"expiry_control_mode"');
    expect(importFields).toContain(
      '"products.fields.lotControlMode"',
    );
    expect(importFields).toContain(
      '"products.fields.expiryControlMode"',
    );
    expect(startPanel).not.toContain(
      "<ProductTrackingSimpleControls",
    );
    expect(startPanel).toContain(
      "trackingAnalysis.status !== \"NOT_NEEDED\"",
    );
    expect(fallbackPanel).toContain(
      "<ProductTrackingSimpleControls",
    );
  });

  it("keeps the basic upload surface free of blank-cell default controls", () => {
    const importStart = normalizeWhitespace(
      readSource("../pages/products/import/ImportProductStartPanel.tsx"),
    );
    const quickGuide = normalizeWhitespace(
      readSource("../pages/products/import/ImportProductQuickGuide.tsx"),
    );
    const translations = readSource("../i18n/resources.ts");

    expect(importStart).toContain(
      "<ImportProductQuickGuide",
    );
    expect(importStart).toContain(
      "<ImportTrackingFallbackPanel",
    );
    expect(importStart).not.toContain(
      '"products.importTrackingChange"',
    );
    expect(importStart).not.toContain(
      '"products.importTrackingTitle"',
    );
    expect(quickGuide).not.toContain(
      '"products.importGuideFallbackCompany"',
    );
    expect(quickGuide).not.toContain(
      '"products.importGuideFallbackImport"',
    );

    expect(translations).toContain(
      'importTrackingNoFallback:',
    );
    expect(translations).toContain(
      'importTrackingFallbackNeededTitle:',
    );
    expect(translations).toContain(
      'importTrackingFallbackUnknownTitle:',
    );
  });

  it("inspects the selected file before upload instead of asking for defaults up front", () => {
    const preflight = normalizeWhitespace(
      readSource("../pages/products/import/productImportFilePreflight.ts"),
    );
    const hook = normalizeWhitespace(
      readSource("../pages/products/import/useImportProductFilePreflight.ts"),
    );
    const startPanel = normalizeWhitespace(
      readSource("../pages/products/import/ImportProductStartPanel.tsx"),
    );

    expect(preflight).toContain(
      '"NOT_NEEDED" | "NEEDED" | "UNKNOWN"',
    );
    expect(preflight).toContain(
      '"استخدام الافتراضي"',
    );
    expect(preflight).toContain(
      '"use default"',
    );
    expect(hook).toContain(
      "inspectProductImportFile",
    );
    expect(startPanel).toContain(
      "filePreflightLoading",
    );
    expect(startPanel).toContain(
      '"products.importTrackingInspectingFile"',
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

    expect(translations).toContain(
      'lotControlMode:',
    );
    expect(translations).toContain(
      'expiryControlMode:',
    );
  });
});
