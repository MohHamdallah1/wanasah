import {
  readFileSync,
} from "node:fs";
import {
  describe,
  expect,
  it,
} from "vitest";

const readSource = (
  relativePath: string,
): string =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

const compact = (
  value: string,
): string =>
  value.replace(/\s+/g, " ").trim();

describe(
  "Products P6 generic import localization",
  () => {
    it("keeps locale aliases outside the import worker and shares canonical field IDs", () => {
      const worker = readSource(
        "../../wa_backend/product_import_worker.py",
      );
      const localization = readSource(
        "../../wa_backend/product_import_localization.py",
      );
      const api = readSource(
        "../../wa_backend/api/simple_products.py",
      );

      expect(localization).toContain(
        "class ImportLocalePack",
      );
      expect(localization).toContain(
        "IMPORT_LOCALE_PACKS",
      );
      expect(localization).toContain(
        "build_import_alias_registry",
      );

      expect(worker).toContain(
        "from product_import_localization import",
      );
      expect(worker).not.toContain(
        "_TRACKING_VALUE_ALIASES",
      );
      expect(worker).not.toContain(
        "_PACKAGE_VALUE_ALIASES",
      );
      expect(worker).not.toContain(
        "_ALIASES = {",
      );

      expect(api).toContain(
        "CANONICAL_IMPORT_FIELDS",
      );
      expect(api).toContain(
        "_CANONICAL_MAPPING_FIELDS = frozenset(",
      );
    });

    it("keeps explicit mapping as the fallback for unknown headers", () => {
      const page = compact(
        readSource(
          "../pages/ProductsDashboard.tsx",
        ),
      );

      expect(page).toContain(
        'status.status === "NEEDS_MAPPING"',
      );
      expect(page).toContain(
        "status.column_mapping",
      );
      expect(page).toContain(
        "status.suggested_mapping",
      );
      expect(page).toContain(
        "importStatus.detected_headers.map",
      );
      expect(page).toContain(
        'setMapping( ( current ) => ({ ...current, [field]: event .target .value, }) )',
      );
    });

    it("builds import templates from translated labels and values", () => {
      const page = readSource(
        "../pages/ProductsDashboard.tsx",
      );
      const start = page.indexOf(
        "const downloadTemplate",
      );
      const end = page.indexOf(
        "const cancelCreate",
        start,
      );
      expect(start).toBeGreaterThanOrEqual(
        0,
      );
      expect(end).toBeGreaterThan(start);

      const template = page.slice(
        start,
        end,
      );

      for (const key of [
        "products.fields.name",
        "products.fields.family",
        "products.fields.packageUom",
        "products.fields.unitsPerPackage",
        "products.fields.packagePrice",
        "products.fields.unitPrice",
        "products.fields.unitBarcode",
        "products.fields.packageBarcode",
        "products.fields.lotControlMode",
        "products.fields.expiryControlMode",
      ]) {
        expect(template).toContain(
          `"${key}"`,
        );
      }

      expect(template).toContain(
        '"products.tracking.importValues.REQUIRED"',
      );
    });

    it("localizes downloaded validation errors from stable codes instead of backend messages", () => {
      const page = readSource(
        "../pages/ProductsDashboard.tsx",
      );
      const start = page.indexOf(
        "const downloadErrorReport",
      );
      const end = page.indexOf(
        "const downloadTemplate",
        start,
      );
      expect(start).toBeGreaterThanOrEqual(
        0,
      );
      expect(end).toBeGreaterThan(start);

      const report = page.slice(
        start,
        end,
      );

      expect(report).toContain(
        "row.code",
      );
      expect(report).toContain(
        "i18n.exists(key)",
      );
      expect(report).not.toContain(
        "row.message",
      );
    });

    it("has translation keys for every import row validation code emitted by the worker", () => {
      const worker = readSource(
        "../../wa_backend/product_import_worker.py",
      );
      const translations = readSource(
        "../i18n/resources.ts",
      );
      const codes = new Set(
        Array.from(
          worker.matchAll(
            /["'](IMPORT_[A-Z0-9_]+)["']/g,
          ),
          (match) => match[1],
        ),
      );

      expect(codes.size).toBeGreaterThan(
        0,
      );
      for (const code of codes) {
        expect(
          translations.includes(
            `${code}:`,
          ) ||
            translations.includes(
              `"${code}"`,
            ),
        ).toBe(true);
      }
    });
  },
);
