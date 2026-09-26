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

describe("Products P9.4 Families workspace", () => {
  it("keeps durable family authority in the manager while composing split presentation", () => {
    const manager = read(
      "../pages/products/family/ProductFamiliesManager.tsx",
    );

    expect(manager).toContain(
      "<ProductFamiliesToolbar",
    );
    expect(manager).toContain(
      "<ProductFamiliesList",
    );
    expect(manager).toContain(
      'subtitle={t(',
    );
    expect(manager).toContain(
      '"products.familiesDescription"',
    );
    expect(manager).toContain(
      'bodyClassName="p-0"',
    );
    expect(manager).toContain(
      'limit: "50"',
    );
    expect(manager).toContain(
      "getOrCreateDurableCommand(",
    );
    expect(manager).toContain(
      "readDurableCommand<unknown>(",
    );
    expect(manager).toContain(
      "parseProductFamilyMutation(",
    );
    expect(manager).toContain(
      "expected_version:",
    );
    expect(manager).toContain(
      '"family-create"',
    );
    expect(manager).toContain(
      '"family-rename"',
    );
  });

  it("separates family search from creation in one compact accessible toolbar", () => {
    const toolbar = read(
      "../pages/products/family/ProductFamiliesToolbar.tsx",
    );

    expect(toolbar).toContain(
      "sticky top-0",
    );
    expect(toolbar).toContain(
      "absolute start-3",
    );
    expect(toolbar).not.toContain(
      "lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]",
    );
    expect(toolbar).toContain(
      '"products.familySearchPlaceholder"',
    );
    expect(toolbar).toContain(
      '"products.newFamilyPlaceholder"',
    );
    expect(toolbar).toContain(
      "product-family-name-error",
    );
    expect(toolbar).toContain(
      "createCommandPending",
    );
    expect(toolbar).toContain(
      "createCommandBlocked",
    );
  });

  it("uses dense inline family rows without weakening rename guards", () => {
    const row = read(
      "../pages/products/family/ProductFamilyRow.tsx",
    );

    expect(row).toContain(
      "editingFamilyName",
    );
    expect(row).toContain(
      "renameCommandPending",
    );
    expect(row).toContain(
      "renameCommandBlocked",
    );
    expect(row).toContain(
      "updatePending",
    );
    expect(row).toContain(
      "onSave",
    );
    expect(row).toContain(
      "onCancelEdit",
    );
    expect(row).toContain(
      "family.variant_count",
    );
  });

  it("keeps loading error empty and cursor navigation local without nested scrolling", () => {
    const list = read(
      "../pages/products/family/ProductFamiliesList.tsx",
    );

    expect(list).toContain(
      '"products.errors.familiesLoad"',
    );
    expect(list).toContain(
      '"products.noMatchingFamilies"',
    );
    expect(list).toContain(
      '"products.noFamilies"',
    );
    expect(list).toContain(
      "onRetry",
    );
    expect(list).toContain(
      "hasPrevious",
    );
    expect(list).toContain(
      "hasNext",
    );
    expect(list).toContain(
      "i18n.dir()",
    );
    expect(list).not.toContain(
      "max-h-[480px]",
    );
    expect(list).not.toContain(
      "overflow-auto",
    );
  });
});
