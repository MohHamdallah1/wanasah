import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string) =>
  readFileSync(resolve(process.cwd(), path), "utf8");

describe("Products V1 density polish", () => {
  it("keeps family as a dedicated column and compacts the row number/package cells", () => {
    const row = read("src/pages/products/list/ProductTableRow.tsx");
    const results = read("src/pages/products/list/ProductsListResults.tsx");

    expect(row).toContain("w-12 min-w-12");
    expect(row).toContain("min-w-[320px]");
    expect(row).toContain("title={item.family_name}");
    expect(row).toContain("{item.family_name}");
    expect(row).toContain("whitespace-nowrap text-center text-xs font-bold");
    expect(results).toContain('products.columns.family');
    expect(results).toContain('w-[112px] whitespace-nowrap text-start');
    expect(results).toContain('w-[96px] whitespace-nowrap text-center');
  });

  it("keeps search, filters, and catalog summary in one desktop toolbar row", () => {
    const toolbar = read("src/pages/products/list/ProductsListToolbar.tsx");
    const section = read("src/pages/products/list/ProductsListSection.tsx");
    const summary = read("src/pages/products/list/ProductsCatalogSummary.tsx");

    expect(toolbar).toContain("summaryContent?: ReactNode");
    expect(toolbar).toContain('products.filters.button');
    expect(toolbar).toContain("xl:flex-row xl:items-center");
    expect(section).toContain("summaryContent={");
    expect(summary).not.toContain('products.summary.scope');
  });

  it("leaves advanced ProductLocation control visible but disabled for V1", () => {
    const actions = read("src/pages/products/list/ProductRowActions.tsx");

    expect(actions).toContain("catalogLifecycle.assignments.title");
    expect(actions).toContain("products.productLocationsV1Disabled");
    expect(actions).toContain("disabled");
    expect(actions).not.toContain("onManageProductLocations(");
  });
});
