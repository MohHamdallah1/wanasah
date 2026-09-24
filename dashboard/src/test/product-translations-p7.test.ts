import {
  readdirSync,
  readFileSync,
} from "node:fs";
import {
  join,
  resolve,
} from "node:path";
import {
  describe,
  expect,
  it,
} from "vitest";

import { resources } from "@/i18n/resources";

const flattenKeys = (
  value: unknown,
  prefix = "",
): string[] => {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return prefix ? [prefix] : [];
  }

  return Object.entries(
    value as Record<string, unknown>,
  ).flatMap(([key, child]) =>
    flattenKeys(
      child,
      prefix
        ? `${prefix}.${key}`
        : key,
    ),
  );
};

const arKeys = new Set(
  flattenKeys(
    resources.ar.translation,
  ),
);
const enKeys = new Set(
  flattenKeys(
    resources.en.translation,
  ),
);

const read = (...parts: string[]) =>
  readFileSync(
    resolve(
      process.cwd(),
      ...parts,
    ),
    "utf8",
  );

const productUiFiles = () => {
  const productRoot = resolve(
    process.cwd(),
    "src/pages/products",
  );
  return [
    resolve(
      process.cwd(),
      "src/pages/ProductsDashboard.tsx",
    ),
    ...readdirSync(productRoot)
      .filter((name) =>
        /\.tsx$/.test(name),
      )
      .map((name) =>
        join(productRoot, name),
      ),
  ];
};

const expectBilingualKey = (
  key: string,
) => {
  expect(
    arKeys.has(key),
    `Arabic translation missing: ${key}`,
  ).toBe(true);
  expect(
    enKeys.has(key),
    `English translation missing: ${key}`,
  ).toBe(true);
};

const collectCodes = (
  source: string,
  regex: RegExp,
) => {
  const codes = new Set<string>();
  for (
    const match of source.matchAll(
      regex,
    )
  ) {
    codes.add(match[1]);
  }
  return codes;
};

describe(
  "Products P7 translation coverage",
  () => {
    it("keeps Arabic and English resource trees in exact key parity", () => {
      expect(
        [...arKeys].sort(),
      ).toEqual(
        [...enKeys].sort(),
      );
    });

    it("covers every static Products translation reference bilingually", () => {
      const keys =
        new Set<string>();

      for (const filePath of productUiFiles()) {
        const source =
          readFileSync(
            filePath,
            "utf8",
          );

        for (const regex of [
          /\bt\(\s*["']([^"']+)["']/g,
          /\bt\(\s*`([^`$]+)`/g,
        ]) {
          for (
            const match of source.matchAll(
              regex,
            )
          ) {
            keys.add(match[1]);
          }
        }
      }

      for (const key of keys) {
        expectBilingualKey(key);
      }
    });

    it("covers all bounded dynamic Product label families", () => {
      const keys = [
        ...[
          "NONE",
          "LOT",
          "EXPIRY",
          "LOT_EXPIRY",
        ].map(
          (value) =>
            `products.filters.trackingTypes.${value}`,
        ),
        ...[
          "id",
          "name",
          "family",
          "sku",
          "lifecycle",
        ].map(
          (value) =>
            `products.filters.sortFields.${value}`,
        ),
        ...[
          "NONE",
          "OPTIONAL",
          "REQUIRED",
        ].flatMap((value) => [
          `products.tracking.lotModes.${value}`,
          `products.tracking.expiryModes.${value}`,
          `products.tracking.shortModes.${value}`,
        ]),
        ...[
          "DRAFT",
          "ACTIVE",
          "RETIRING",
          "ARCHIVED",
        ].map(
          (value) =>
            `products.details.lifecycleModes.${value}`,
        ),
        ...[
          "INTERNAL",
          "EAN8",
          "EAN13",
          "UPC_A",
          "GTIN14",
          "GS1_128",
        ].map(
          (value) =>
            `products.barcodeManager.types.${value}`,
        ),
        ...[
          "EACH",
          "CARTON",
          "CASE",
          "PACK",
          "BAG",
          "SACK",
          "TRAY",
          "CRATE",
          "BUNDLE",
          "PALLET",
          "NONE",
        ].map(
          (value) =>
            `uom.${value}`,
        ),
      ];

      for (const key of keys) {
        expectBilingualKey(key);
      }
    });

    it("maps Product-facing stable error codes to bilingual translations", () => {
      const backendRoot = resolve(
        process.cwd(),
        "..",
        "wa_backend",
      );
      const sources: Array<{
        source: string;
        regexes: RegExp[];
      }> = [
        {
          source: readFileSync(
            join(
              backendRoot,
              "domains/simple_products/service.py",
            ),
            "utf8",
          ),
          regexes: [
            /SimpleProductError\(\s*["']([A-Z][A-Z0-9_]+)["']/gs,
          ],
        },
        {
          source: readFileSync(
            join(
              backendRoot,
              "api/simple_products.py",
            ),
            "utf8",
          ),
          regexes: [
            /["']code["']\s*:\s*["']([A-Z][A-Z0-9_]+)["']/g,
            /\bcode\s*=\s*["']([A-Z][A-Z0-9_]+)["']/g,
          ],
        },
        {
          source: readFileSync(
            join(
              backendRoot,
              "api/catalog.py",
            ),
            "utf8",
          ),
          regexes: [
            /_error\(\s*\d+\s*,\s*["']([A-Z][A-Z0-9_]+)["']/gs,
          ],
        },
        {
          source: readFileSync(
            join(
              backendRoot,
              "domains/product_tracking.py",
            ),
            "utf8",
          ),
          regexes: [
            /ProductTrackingError\(\s*["']([A-Z][A-Z0-9_]+)["']/gs,
          ],
        },
        {
          source: readFileSync(
            join(
              backendRoot,
              "product_lifecycle.py",
            ),
            "utf8",
          ),
          regexes: [
            /ProductLifecycleTransitionError\(\s*["']([A-Z][A-Z0-9_]+)["']/gs,
          ],
        },
        ...[
          "core.py",
          "publishing.py",
          "resolver.py",
        ].map((name) => ({
          source: readFileSync(
            join(
              backendRoot,
              "domains/pricing",
              name,
            ),
            "utf8",
          ),
          regexes: [
            /PricingError\(\s*["']([A-Z][A-Z0-9_]+)["']/gs,
          ],
        })),
      ];

      const codes =
        new Set<string>();
      for (const item of sources) {
        for (
          const regex of item.regexes
        ) {
          for (
            const code of collectCodes(
              item.source,
              regex,
            )
          ) {
            codes.add(code);
          }
        }
      }

      const productsContracts =
        read(
          "src/pages/products/contracts.ts",
        );
      for (
        const code of collectCodes(
          productsContracts,
          /\bconst code = ["']([A-Z][A-Z0-9_]+)["']/g,
        )
      ) {
        codes.add(code);
      }

      for (const filePath of productUiFiles()) {
        const source =
          readFileSync(
            filePath,
            "utf8",
          );
        for (
          const code of collectCodes(
            source,
            /new Error\(\s*["']([A-Z][A-Z0-9_]+)["']/gs,
          )
        ) {
          codes.add(code);
        }
      }

      codes.add(
        "CATALOG_CONTRACT_INVALID",
      );

      for (const code of codes) {
        expectBilingualKey(
          `errors.codes.${code}`,
        );
      }
    });

    it("keeps Product UI copy behind translations instead of raw language or enums", () => {
      const offenders =
        productUiFiles().filter(
          (filePath) =>
            /[\u0600-\u06FF]/.test(
              readFileSync(
                filePath,
                "utf8",
              ),
            ),
        );
      expect(offenders).toEqual([]);

      const dashboard = read(
        "src/pages/ProductsDashboard.tsx",
      );
      expect(dashboard).not.toContain(
        '"Lolo Chips Cheese 20g"',
      );
      expect(dashboard).toContain(
        't("products.importTemplateSampleName")',
      );

      const advancedUom = read(
        "src/pages/products/AdvancedUomDashboard.tsx",
      );
      expect(advancedUom).toContain(
        "products.details.lifecycleModes.${item.lifecycle_status}",
      );
      expect(
        /(^|[^$])\{item\.lifecycle_status\}/m.test(
          advancedUom,
        ),
      ).toBe(false);

      const barcodeManager = read(
        "src/pages/products/ProductBarcodeManager.tsx",
      );
      expect(barcodeManager).toContain(
        "products.barcodeManager.types.${item.barcode_type}",
      );
      expect(barcodeManager).toContain(
        "products.barcodeManager.types.${value}",
      );
    });
  },
);
