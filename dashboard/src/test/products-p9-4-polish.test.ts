import {
  readFileSync,
} from "node:fs";
import {
  readdirSync,
  statSync,
} from "node:fs";
import {
  join,
} from "node:path";
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

const presentationSources = [
  "../pages/products/ProductsPage.tsx",
  "../pages/products/ProductsPageHeader.tsx",
  "../pages/products/header/ProductsCatalogToolsMenu.tsx",
  "../pages/products/header/ProductsAddAction.tsx",
  "../pages/products/list/ProductsListSection.tsx",
  "../pages/products/list/ProductsListToolbar.tsx",
  "../pages/products/list/ProductsActiveFilters.tsx",
  "../pages/products/list/ProductsListResults.tsx",
  "../pages/products/list/ProductsListState.tsx",
  "../pages/products/list/ProductTableRow.tsx",
  "../pages/products/list/ProductMobileCard.tsx",
  "../pages/products/detail/ProductDetailDrawer.tsx",
  "../pages/products/create/CreateProductModal.tsx",
  "../pages/products/pricing/PriceEditModal.tsx",
  "../pages/products/import/ImportProductModal.tsx",
];

const walkTsLogicFiles = (
  directory: string,
): string[] => {
  const result: string[] = [];

  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    const stat = statSync(path);

    if (stat.isDirectory()) {
      result.push(
        ...walkTsLogicFiles(path),
      );
    } else if (
      name.endsWith(".ts") &&
      !name.endsWith(".test.ts")
    ) {
      result.push(path);
    }
  }

  return result;
};

describe(
  "Products P9.4 visual polish contracts",
  () => {
    it("keeps the primary hierarchy compact and free of the legacy card-heavy shell", () => {
      const header = read(
        "../pages/products/ProductsPageHeader.tsx",
      );
      const section = read(
        "../pages/products/list/ProductsListSection.tsx",
      );
      const rowActions = read(
        "../pages/products/list/ProductRowActions.tsx",
      );

      for (const source of [
        header,
        section,
      ]) {
        expect(source).not.toContain(
          "rounded-[26px]",
        );
        expect(source).not.toContain(
          "backdrop-blur-xl",
        );
      }

      expect(header).toContain(
        "<ProductsCatalogToolsMenu",
      );
      expect(header).toContain(
        "<ProductsAddAction",
      );
      expect(header).toContain(
        "onOpenCreateProduct",
      );
      expect(rowActions).toContain(
        "<MoreHorizontal",
      );
      expect(rowActions).toContain(
        "onOpenDetails(item)",
      );
      expect(rowActions).toContain(
        "onEditPrice(item)",
      );
      expect(rowActions).toContain(
        "onEditTracking(item)",
      );
    });

    it("uses logical RTL/LTR-safe spacing on the redesigned Product surfaces", () => {
      const physicalDirectionClass =
        /(?:^|\s)(?:left|right|ml|mr|pl|pr)-[\d[]/m;

      for (const path of presentationSources) {
        expect(
          read(path),
          path,
        ).not.toMatch(
          physicalDirectionClass,
        );
      }

      const page = read(
        "../pages/products/ProductsPage.tsx",
      );
      const catalogTools = read(
        "../pages/products/header/ProductsCatalogToolsMenu.tsx",
      );

      expect(page).toContain(
        "dir={i18n.dir()}",
      );
      expect(catalogTools).toContain(
        "dir={direction}",
      );
      expect(catalogTools).toContain(
        "text-start",
      );
    });

    it("keeps icon choice in presentation files instead of Product workflow authority", () => {
      const productRoot =
        join(
          process.cwd(),
          "src",
          "pages",
          "products",
        );
      const logicFiles =
        walkTsLogicFiles(productRoot);

      expect(
        logicFiles.length,
      ).toBeGreaterThan(0);

      for (const path of logicFiles) {
        const source =
          readFileSync(path, "utf8");
        expect(
          source,
          path,
        ).not.toContain(
          "lucide-react",
        );
      }
    });

    it("preserves independent mobile presentation and configurable display preferences", () => {
      const results = read(
        "../pages/products/list/ProductsListResults.tsx",
      );
      const mobileCard = read(
        "../pages/products/list/ProductMobileCard.tsx",
      );
      const tableRow = read(
        "../pages/products/list/ProductTableRow.tsx",
      );
      const detailDrawer = read(
        "../pages/products/detail/ProductDetailDrawer.tsx",
      );

      expect(results).toContain(
        "isNarrowViewport ? (",
      );
      expect(results).toContain(
        "<ProductMobileCard",
      );
      expect(results).toContain(
        "<ProductTableRow",
      );

      expect(mobileCard).toContain(
        "visibleColumns",
      );
      expect(mobileCard).toContain(
        "density",
      );
      expect(tableRow).toContain(
        "visibleColumns",
      );
      expect(tableRow).toContain(
        "density",
      );
      expect(detailDrawer).toContain(
        "detailSections",
      );
    });

    it("keeps keyboard/focus affordances on the redesigned Product command surfaces", () => {
      const header = read(
        "../pages/products/ProductsPageHeader.tsx",
      );
      const toolbar = read(
        "../pages/products/list/ProductsListToolbar.tsx",
      );
      const filters = read(
        "../pages/products/list/ProductsActiveFilters.tsx",
      );
      const states = read(
        "../pages/products/list/ProductsListState.tsx",
      );

      for (const [label, source] of [
        ["header", header],
        ["toolbar", toolbar],
        ["filters", filters],
        ["states", states],
      ] as const) {
        expect(
          source,
          label,
        ).toContain(
          "focus-visible:",
        );
      }

      expect(toolbar).toContain(
        "aria-expanded={",
      );
      expect(toolbar).toContain(
        "absolute start-3",
      );
      expect(toolbar).toContain(
        "bg-white py-2.5 pe-3 ps-10 text-sm font-normal",
      );
      expect(toolbar).not.toContain(
        "bg-slate-50/70",
      );
      expect(filters).toContain(
        "aria-label={t(",
      );
      expect(states).toContain(
        'aria-live=',
      );
    });
  },
);
