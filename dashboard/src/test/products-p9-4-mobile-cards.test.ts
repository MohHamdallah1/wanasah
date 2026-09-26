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

describe("Products P9.4 mobile cards", () => {
  it("uses a mobile-first Product identity surface instead of shrinking desktop actions", () => {
    const card = read(
      "../pages/products/list/ProductMobileCard.tsx",
    );

    expect(card).toContain(
      "onOpenDetails(item)",
    );
    expect(card).toContain(
      "<ProductRowActions",
    );
    expect(card).toContain(
      'aria-label={t(',
    );
    expect(card).not.toContain(
      "mt-4 grid grid-cols-1 gap-2",
    );
    expect(card).not.toContain(
      '"products.editPrice"',
    );
    expect(card).not.toContain(
      '"products.trackingEditor.action"',
    );
  });

  it("keeps lifecycle tracking package barcode and pricing semantics visible when configured", () => {
    const card = read(
      "../pages/products/list/ProductMobileCard.tsx",
    );

    for (const contract of [
      "visibleColumns.lifecycle",
      "item.operational_hold",
      "visibleColumns.tracking",
      "item.lot_control_mode",
      "item.expiry_control_mode",
      "visibleColumns.package",
      "visibleColumns.unitsPerPackage",
      "visibleColumns.unitBarcode",
      "visibleColumns.packageBarcode",
      "pricingVisible &&",
      "visibleColumns.packagePrice",
      "visibleColumns.unitPrice",
    ]) {
      expect(card).toContain(
        contract,
      );
    }

    expect(card).toContain(
      "formatLocaleDecimal",
    );
    expect(card).not.toContain(
      "Number(",
    );
  });

  it("renders mobile Products as one compact list surface rather than stacked floating cards", () => {
    const card = read(
      "../pages/products/list/ProductMobileCard.tsx",
    );
    const results = read(
      "../pages/products/list/ProductsListResults.tsx",
    );

    expect(card).toContain(
      "border-b border-slate-100",
    );
    expect(card).not.toContain(
      "shadow-sm",
    );
    expect(card).not.toContain(
      "rounded-2xl",
    );

    expect(results).toContain(
      "overflow-hidden rounded-xl border border-slate-200 bg-white",
    );
    expect(results).toContain(
      "bg-slate-50/50 p-2",
    );
  });
});
