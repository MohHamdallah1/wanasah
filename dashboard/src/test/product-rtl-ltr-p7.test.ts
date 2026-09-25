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

  const collectTsxFiles = (
    directory: string,
  ): string[] =>
    readdirSync(
      directory,
      {
        withFileTypes: true,
      },
    ).flatMap((entry) => {
      const path = join(
        directory,
        entry.name,
      );
      if (entry.isDirectory()) {
        return collectTsxFiles(path);
      }
      return /\.tsx$/.test(
        entry.name,
      )
        ? [path]
        : [];
    });

  return [
    resolve(
      process.cwd(),
      "src/pages/products/ProductsPage.tsx",
    ),
    ...collectTsxFiles(
      productRoot,
    ),
  ];
};

describe(
  "Products P7 RTL/LTR contracts",
  () => {
    it("derives document direction from i18next instead of language-specific branching", () => {
      const source = read(
        "src/i18n/index.ts",
      ).replace(/\s+/g, " ");

      expect(source).toContain(
        "document.documentElement.dir = i18n.dir(language);",
      );
      expect(source).not.toMatch(
        /language\.(?:startsWith|includes)\(\s*["']ar["']\s*\)/,
      );
      expect(source).not.toMatch(
        /language\s*===\s*["']ar["']/,
      );
    });

    it("keeps Product shells and Product modal portals on i18n direction authority", () => {
      const dashboard = read(
        "src/pages/products/ProductsPage.tsx",
      );
      const drawer = read(
        "src/pages/products/ProductDetailDrawer.tsx",
      );
      const modal = read(
        "src/components/ui/modal.tsx",
      );

      expect(dashboard).toContain(
        "dir={i18n.dir()}",
      );
      expect(drawer).toContain(
        "dir={i18n.dir()}",
      );
      expect(modal).toContain(
        "dir={i18n.dir()}",
      );

      for (const filePath of productUiFiles()) {
        const source = readFileSync(
          filePath,
          "utf8",
        );
        expect(
          source,
          `hardcoded direction in ${filePath}`,
        ).not.toMatch(
          /dir\s*=\s*["'](?:rtl|ltr)["']/,
        );
      }
    });

    it("uses logical edge utilities throughout Product UI", () => {
      const physicalUtility =
        /(?:^|[\s"'`])(?:m[lr]|p[lr]|left|right|border-[lr]|rounded-[lr]|text-(?:left|right)|space-x)-[^\s"'`}>]+/gm;
      const offenders: Array<{
        filePath: string;
        matches: string[];
      }> = [];

      for (const filePath of productUiFiles()) {
        const source = readFileSync(
          filePath,
          "utf8",
        );
        const matches = [
          ...source.matchAll(
            physicalUtility,
          ),
        ].map((match) =>
          match[0].trim(),
        );

        if (matches.length > 0) {
          offenders.push({
            filePath,
            matches,
          });
        }
      }

      expect(offenders).toEqual([]);
    });

    it("mirrors Product pagination and back navigation icons by direction", () => {
      const listResults = read(
        "src/pages/products/list/ProductsListResults.tsx",
      );
      const advancedUom = read(
        "src/pages/products/AdvancedUomDashboard.tsx",
      );

      expect(listResults).toContain(
        '<ChevronLeft className="h-4 w-4 rtl:rotate-180" />',
      );
      expect(listResults).toContain(
        '<ChevronRight className="h-4 w-4 rtl:rotate-180" />',
      );
      expect(listResults).not.toContain(
        '<ChevronLeft className="h-4 w-4" />',
      );
      expect(listResults).not.toContain(
        '<ChevronRight className="h-4 w-4" />',
      );

      expect(advancedUom).toContain(
        '<ArrowLeft className="h-4 w-4 rtl:rotate-180" />',
      );
      expect(advancedUom).not.toContain(
        '<ArrowLeft className="h-4 w-4" />',
      );
    });
  },
);
