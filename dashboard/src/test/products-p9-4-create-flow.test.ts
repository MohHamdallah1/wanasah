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

describe("Products P9.4 create flow", () => {
  it("keeps the modal as a thin composition layer over ordinary and advanced sections", () => {
    const modal = read(
      "../pages/products/create/CreateProductModal.tsx",
    );

    expect(modal).toContain(
      "<CreateProductIdentitySection",
    );
    expect(modal).toContain(
      "<CreateProductCommerceSection",
    );
    expect(modal).toContain(
      "<CreateProductAdvancedSection",
    );
    expect(modal).toContain(
      'maxWidth="max-w-4xl"',
    );
    expect(modal).toContain(
      "const saveDisabled =",
    );
    expect(modal).toContain(
      "!draft.lot_control_mode",
    );
    expect(modal).toContain(
      "!draft.expiry_control_mode",
    );
    expect(modal).not.toContain(
      "<ProductTrackingFields",
    );
  });

  it("keeps the ordinary flow focused on identity, package structure, and price", () => {
    const identity = read(
      "../pages/products/create/CreateProductIdentitySection.tsx",
    );
    const commerce = read(
      "../pages/products/create/CreateProductCommerceSection.tsx",
    );

    expect(identity).toContain(
      '"products.productName"',
    );
    expect(identity).toContain(
      '"products.familyModeLabel"',
    );
    expect(identity).toContain(
      "familyOptions.map",
    );

    expect(commerce).toContain(
      "onHasPackageChange",
    );
    expect(commerce).toContain(
      '"products.unitsPerPackage"',
    );
    expect(commerce).toContain(
      '"products.packagePrice"',
    );
    expect(commerce).toContain(
      '"products.unitPrice"',
    );
    expect(commerce).toContain(
      '"products.derivedPrice"',
    );
  });

  it("keeps tracking overrides and barcodes deliberate behind one advanced disclosure", () => {
    const advanced = read(
      "../pages/products/create/CreateProductAdvancedSection.tsx",
    );

    expect(advanced).toContain(
      'aria-expanded={',
    );
    expect(advanced).toContain(
      "createAdvancedExpanded",
    );
    expect(advanced).toContain(
      '"products.quickCreate.advancedTitle"',
    );
    expect(advanced).toContain(
      "<ProductTrackingFields",
    );
    expect(advanced).toContain(
      "!createTrackingExpanded ?",
    );
    expect(advanced).toContain(
      '"products.barcodeSection"',
    );
    expect(advanced).toContain(
      "onUnitBarcodeChange",
    );
    expect(advanced).toContain(
      "onPackageBarcodeChange",
    );
  });

  it("does not move create authority out of the existing workflow and mutation modules", () => {
    const workflow = read(
      "../pages/products/create/useCreateProductWorkflow.ts",
    );
    const mutation = read(
      "../pages/products/create/useCreateProductMutation.ts",
    );
    const command = read(
      "../pages/products/create/productCreateCommand.ts",
    );

    expect(workflow).toContain(
      "createProductDraftActions({",
    );
    expect(workflow).toContain(
      "useCreateProductMutation({",
    );
    expect(mutation).toContain(
      "productCreateRequestBody(",
    );
    expect(command).toContain(
      "export const productCreateRequestBody",
    );
  });
});
