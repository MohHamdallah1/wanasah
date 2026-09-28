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
      'maxWidth="max-w-5xl"',
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
    const familyCombobox = read(
      "../pages/products/family/ProductFamilyCombobox.tsx",
    );

    expect(identity).toContain(
      '"products.productName"',
    );
    expect(identity).toContain(
      '"products.familyModeLabel"',
    );
    expect(identity).toContain(
      "<ProductFamilyCombobox",
    );
    expect(identity).toContain(
      "familyOptions",
    );
    expect(familyCombobox).toContain(
      "options.map(",
    );
    expect(familyCombobox).toContain(
      'role="combobox"',
    );
    expect(familyCombobox).toContain(
      "createPortal(",
    );
    expect(identity).toContain(
      "onFamilySearchChange(",
    );
    expect(familyCombobox).toContain(
      "aria-controls={",
    );
    expect(identity).toContain(
      "placeholder:text-sm placeholder:font-normal placeholder:text-slate-400",
    );
    expect(identity).not.toContain(
      '{t("products.family")} {" · "} {t("common.optional")}',
    );
    expect(identity).not.toContain(
      "<Tags",
    );
    expect(identity).toContain(
      "border border-slate-200 bg-white px-3",
    );

    expect(commerce).toContain(
      "onHasPackageChange",
    );
    expect(commerce).not.toContain(
      "<PackageOpen",
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
    expect(commerce).toContain(
      "placeholder:text-sm placeholder:font-normal placeholder:text-slate-400",
    );
    expect(commerce).not.toContain(
      't("common.optional")',
    );
    expect(commerce).not.toContain(
      '<p className="mt-0.5 text-[11px] font-semibold text-slate-500"> {t("products.unitPrice")} </p>',
    );
  });

  it("keeps tracking overrides deliberate and barcodes in their dedicated section", () => {
    const advanced = read(
      "../pages/products/create/CreateProductAdvancedSection.tsx",
    );
    const barcode = read(
      "../pages/products/create/CreateProductBarcodeSection.tsx",
    );

    expect(advanced).toContain(
      'aria-expanded={',
    );
    expect(advanced).toContain(
      "createAdvancedExpanded",
    );
    expect(advanced).toContain(
      '"products.tracking.createChange"',
    );
    expect(advanced).toContain(
      "<ProductTrackingFields",
    );
    expect(advanced).toContain(
      "!trackingUsesCompanyDefaults ?",
    );
    expect(barcode).toContain(
      '"products.barcodeSection"',
    );
    expect(barcode).toContain(
      "onUnitBarcodeChange",
    );
    expect(barcode).toContain(
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
