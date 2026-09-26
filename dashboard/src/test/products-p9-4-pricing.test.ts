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

describe("Products P9.4 pricing interaction", () => {
  it("reuses the existing exact-money derivation as presentation data", () => {
    const state = read(
      "../pages/products/pricing/usePriceEditState.ts",
    );
    const workflow = read(
      "../pages/products/pricing/usePriceEditWorkflow.ts",
    );
    const modal = read(
      "../pages/products/pricing/PriceEditModal.tsx",
    );

    expect(state).toContain(
      "deriveExactMoneyPair(",
    );
    expect(workflow).toContain(
      "derivedPackagePrice:",
    );
    expect(workflow).toContain(
      "derivedUnitPrice:",
    );
    expect(modal).toContain(
      "derivedPackagePrice",
    );
    expect(modal).toContain(
      "derivedUnitPrice",
    );
    expect(modal).not.toContain(
      "parseFloat(",
    );
    expect(modal).not.toContain(
      "Number(",
    );
    expect(modal).not.toContain(
      "toFixed(",
    );
  });

  it("keeps direct-versus-derived pricing visible in a compact preview", () => {
    const modal = read(
      "../pages/products/pricing/PriceEditModal.tsx",
    );

    expect(modal).toContain(
      '"products.priceHelp"',
    );
    expect(modal).toContain(
      '"products.independentPrices"',
    );
    expect(modal).toContain(
      '"products.derivedPrice"',
    );
    expect(modal).toContain(
      "independentPrices",
    );
    expect(modal).toContain(
      "hasPreview",
    );
    expect(modal).toContain(
      "tabular-nums",
    );
  });

  it("preserves exact existing field errors focus refs and one save action", () => {
    const modal = read(
      "../pages/products/pricing/PriceEditModal.tsx",
    );
    const mutation = read(
      "../pages/products/pricing/usePriceEditMutation.ts",
    );

    for (const id of [
      "edit-package-price-error",
      "edit-unit-price-error",
    ]) {
      expect(modal).toContain(
        id,
      );
    }
    expect(modal).toContain(
      "packagePriceRef",
    );
    expect(modal).toContain(
      "unitPriceRef",
    );
    expect(modal).toContain(
      "onClick={onSubmit}",
    );

    expect(mutation).toContain(
      "editPackagePriceRef",
    );
    expect(mutation).toContain(
      "editUnitPriceRef",
    );
    expect(mutation).toContain(
      ".current?.focus()",
    );
  });

  it("leaves price mutation durability and endpoint authority unchanged", () => {
    const mutation = read(
      "../pages/products/pricing/usePriceEditMutation.ts",
    );

    expect(mutation).toContain(
      "getOrCreateDurableCommand(",
    );
    expect(mutation).toContain(
      "completeDurableOperation(",
    );
    expect(mutation).toContain(
      "abandonDurableOperation(",
    );
    expect(mutation).toContain(
      "isAmbiguousRequestError(",
    );
    expect(mutation).toContain(
      "/simple-products/${priceEdit.id}/price",
    );
  });
});
