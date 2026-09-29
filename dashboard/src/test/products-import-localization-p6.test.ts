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
        "../../../wa_backend/domains/simple_products/imports/application/worker.py",
      );
      const localization = readSource(
        "../../../wa_backend/domains/simple_products/imports/domain/localization.py",
      );
      const api = readSource(
        "../../../wa_backend/domains/simple_products/imports/api/router.py",
      );
      const application = readSource(
        "../../../wa_backend/domains/simple_products/imports/application/api_service.py",
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
        "run_product_import_job",
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

      expect(localization).toContain(
        "CANONICAL_IMPORT_FIELDS",
      );
      expect(application).toContain(
        "CANONICAL_IMPORT_FIELDS",
      );
      expect(application).toContain(
        "_CANONICAL_MAPPING_FIELDS = frozenset(CANONICAL_IMPORT_FIELDS)",
      );
      expect(api).not.toContain(
        "_CANONICAL_MAPPING_FIELDS",
      );
    });

    it("explains base units and outer packaging in import and product creation", () => {
      const guide = readSource(
        "../pages/products/import/ImportProductQuickGuide.tsx",
      );
      const create = readSource(
        "../pages/products/create/CreateProductCommerceSection.tsx",
      );
      const glossary = readSource(
        "../pages/products/shared/ProductPackagingHelp.tsx",
      );
      const translations = readSource(
        "../i18n/resources.ts",
      );

      expect(guide).toContain("ProductPackagingHelp");
      expect(guide).toContain("products.importGuidePackagingRule");
      expect(create).toContain("ProductPackagingHelp compact");
      expect(glossary).toContain("TooltipTrigger");
      expect(glossary).toContain("aria-label");
      expect(glossary).toContain("products.packageGlossary.limits");
      expect(glossary).toContain("products.packageGlossary.examplesTitle");
      expect(glossary).toContain('<table');
      expect(glossary).toContain('scope="row"');
      expect(
        translations.split("packageGlossary:").length - 1,
      ).toBe(2);
    });

    it("keeps explicit mapping as the fallback for unknown headers", () => {
      const page = compact(
        readSource(
          "../pages/products/ProductsPage.tsx",
        ),
      );
      const mappingPanel = compact(
        readSource(
          "../pages/products/import/ImportProductMappingPanel.tsx",
        ),
      );
      const importPolling = compact(
        readSource(
          "../pages/products/import/useImportProductPolling.ts",
        ),
      );
      const importCommands = compact(
        readSource(
          "../pages/products/import/useImportProductCommands.ts",
        ),
      );

      expect(importPolling).toContain(
        'status.status === "NEEDS_MAPPING"',
      );
      expect(importPolling).toContain(
        "status.column_mapping",
      );
      expect(importPolling).toContain(
        "status.suggested_mapping",
      );
      expect(mappingPanel).toContain(
        "detectedHeaders.map",
      );
      expect(importCommands).toMatch(
        /const updateMapping = \( field: string, value: string, \) => setMapping\( \(current\) => \(\{ \.\.\.current, \[field\]: value,/,
      );
      expect(mappingPanel).toContain(
        "onMappingChange(",
      );
      expect(mappingPanel).toContain(
        "event.target.value",
      );
    });

    it("keeps workbook localization in the backend template and value guidance in the UI", () => {
      const template = readSource(
        "../../../wa_backend/domains/simple_products/imports/infrastructure/template.py",
      );
      const localization = readSource(
        "../../../wa_backend/domains/simple_products/imports/domain/localization.py",
      );
      const downloads = readSource(
        "../pages/products/import/createImportDownloads.ts",
      );
      const quickGuide = readSource(
        "../pages/products/import/ImportProductQuickGuide.tsx",
      );

      expect(template).toContain(
        "resolve_import_locale_pack(",
      );
      expect(template).toContain(
        "pack.rtl",
      );
      expect(template).toContain(
        "DataValidation(",
      );
      expect(template).toContain(
        "MAX_TEMPLATE_ROWS = 50_000",
      );
      expect(localization).toContain(
        '"استخدام الافتراضي"',
      );
      expect(localization).toContain(
        '"use default"',
      );
      expect(downloads).toContain(
        "/simple-products/import-template?locale=",
      );
      expect(downloads).toContain(
        "resolveI18nLocale(i18n)",
      );
      expect(downloads).toContain(
        "encodeURIComponent(locale)",
      );
      expect(downloads).not.toContain(
        '.split("-")[0] === "en"',
      );
      expect(localization).toContain(
        "resolve_import_locale_pack(",
      );
      expect(localization).toContain(
        "IMPORT_LOCALE_REGISTRY",
      );
      expect(quickGuide).toContain(
        "products.tracking.importValues.",
      );
      expect(quickGuide).toContain(
        "products.importGuideUseDefault",
      );
    });

    it("localizes downloaded validation errors from stable codes instead of backend messages", () => {
      const downloads = readSource(
        "../pages/products/import/createImportDownloads.ts",
      );
      const start = downloads.indexOf(
        "const downloadErrorReport",
      );
      const end = downloads.indexOf(
        "const downloadTemplate",
        start,
      );
      expect(start).toBeGreaterThanOrEqual(
        0,
      );
      expect(end).toBeGreaterThan(start);

      const report = downloads.slice(
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
      const validationSources = [
        "../../../wa_backend/domains/simple_products/imports/domain/normalization.py",
        "../../../wa_backend/domains/simple_products/imports/application/validation_service.py",
        "../../../wa_backend/domains/simple_products/imports/application/execution_service.py",
      ].map(readSource);
      const translations = readSource(
        "../i18n/resources.ts",
      );
      const codes = new Set(
        validationSources.flatMap(
          (source) =>
            Array.from(
              source.matchAll(
                /["'](IMPORT_[A-Z0-9_]+)["']/g,
              ),
              (match) => match[1],
            ),
        ),
      );

      expect(codes.size).toBeGreaterThan(
        0,
      );
      for (const code of codes) {
        const bare =
          translations.split(
            `${code}:`,
          ).length - 1;
        const quoted =
          translations.split(
            `"${code}"`,
          ).length - 1;
        expect(
          bare + quoted,
        ).toBeGreaterThanOrEqual(2);
      }
    });
  },
);
