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

describe("Products P9.4 desktop table", () => {
  it("uses one compact actions surface while preserving existing permission guards", () => {
    const row = read(
      "../pages/products/list/ProductTableRow.tsx",
    );
    const actions = read(
      "../pages/products/list/ProductRowActions.tsx",
    );

    expect(row).toContain(
      "<ProductRowActions",
    );
    expect(row).toContain(
      "canEditPrice={",
    );
    expect(row).toContain(
      "canEditTracking={",
    );
    expect(row).toContain(
      "canReassignFamily={",
    );
    expect(row).not.toContain(
      'className="rounded-xl border border-slate-200 bg-white px-3 py-2',
    );

    expect(actions).toContain(
      "canEditPrice &&",
    );
    expect(actions).toContain(
      "item.simple_compatible",
    );
    expect(actions).toContain(
      "{canEditTracking ? (",
    );
    expect(actions).toContain(
      "onOpenDetails(item)",
    );
    expect(actions).toContain(
      "onEditPrice(item)",
    );
    expect(actions).toContain(
      "products.familyReassign.action",
    );
    expect(actions).toContain(
      "onReassignFamily(item)",
    );
    expect(actions).toContain(
      '["ACTIVE", "RETIRING"]',
    );
    expect(actions).toContain(
      "onEditTracking(item)",
    );
  });

  it("makes Product identity the detail entry point and keeps scan density bounded", () => {
    const row = read(
      "../pages/products/list/ProductTableRow.tsx",
    );
    const results = read(
      "../pages/products/list/ProductsListResults.tsx",
    );

    expect(row).toContain(
      "onClick={() =>",
    );
    expect(row).toContain(
      "onOpenDetails(item)",
    );
    expect(row).toContain(
      '"px-4 py-2.5"',
    );
    expect(row).toContain(
      '"px-4 py-3"',
    );
    expect(row).toContain(
      "max-w-[220px]",
    );
    expect(row).toContain(
      "item.family_name",
    );
    expect(row).not.toContain(
      "item.sku",
    );
    expect(row).toContain(
      "justify-center",
    );
    expect(results).toContain(
      "text-start",
    );
    expect(results).toContain(
      "text-center",
    );
    expect(results).toContain(
      "index + 1",
    );
    expect(results).toContain(
      "rowNumber={",
    );
    expect(results).toContain(
      'min-w-[920px]',
    );
    expect(results).not.toContain(
      'min-w-[1050px]',
    );
  });

  it("keeps lifecycle and tracking meaning as text while using color only as support", () => {
    const row = read(
      "../pages/products/list/ProductTableRow.tsx",
    );

    expect(row).toContain(
      "products.tracking.shortModes.",
    );
    expect(row).toContain(
      "products.details.lifecycleModes.",
    );
    expect(row).toContain(
      "products.details.holdModes.",
    );
    expect(row).toContain(
      "bg-emerald-50",
    );
    expect(row).toContain(
      "bg-amber-50",
    );
  });
});
