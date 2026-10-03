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

describe("Products lifecycle, focus, and barcode UX", () => {
  it("focuses app-modal content before the close control without changing generic dialogs", () => {
    const trap = read(
      "../hooks/useDialogFocusTrap.ts",
    );
    const modal = read(
      "../components/ui/modal.tsx",
    );

    expect(trap).toContain(
      '".app-modal-body"',
    );
    expect(trap).toContain(
      "firstInBody.focus();",
    );
    expect(trap).toContain(
      "modalBody.focus();",
    );
    expect(trap).toContain(
      "focusableWithin(container)[0]",
    );
    expect(modal).toContain(
      "tabIndex={-1}",
    );
  });

  it("keeps create-product barcode inputs aligned while preserving copy", () => {
    const source = read(
      "../pages/products/create/CreateProductBarcodeSection.tsx",
    );

    expect(source).toContain(
      'className="flex h-8 items-center justify-between gap-2"',
    );
    expect(source).toContain(
      "onClick={onCopyBarcode}",
    );
    expect(source).not.toContain(
      'className="mb-1.5 inline-flex h-8',
    );
  });

  it("offers unit-barcode copy when editing or assigning a package barcode", () => {
    const source = read(
      "../pages/products/barcode/ProductBarcodeSimplePanel.tsx",
    );

    expect(source).toContain(
      "allowCopyUnitBarcode",
    );
    expect(source).toContain(
      't("products.copyBarcode")',
    );
    expect(source).toContain(
      'target === "package"',
    );
    expect(source).toContain(
      '"packageIndependent"',
    );
    expect(source).toContain(
      "baseCurrent?.barcode",
    );
  });

  it("uses one commercial lifecycle status without exposing the backend state machine", () => {
    const manager = read(
      "../pages/products/lifecycle/ProductLifecycleManager.tsx",
    );
    const actions = read(
      "../pages/inventory/catalog/CatalogLifecycleActions.tsx",
    );
    const simplePanel = read(
      "../pages/inventory/catalog/CatalogLifecycleSimplePanel.tsx",
    );

    expect(manager).toContain(
      "simpleMode",
    );
    expect(manager).not.toContain(
      "ProductLifecycleStatusRail",
    );
    expect(actions).toContain(
      "<CatalogLifecycleSimplePanel",
    );
    expect(simplePanel).toContain(
      "productCommercialStatus",
    );
    expect(simplePanel).toContain(
      "products.commercialStatus.label",
    );
    expect(simplePanel).not.toContain(
      "catalogLifecycle.simple.productStatusTitle",
    );
    expect(simplePanel).not.toContain(
      "catalogLifecycle.simple.salesStatusTitle",
    );
    expect(simplePanel).not.toContain(
      "products.details.lifecycleModes.",
    );
    expect(simplePanel).not.toContain(
      "products.details.holdModes.",
    );
    expect(simplePanel).toContain(
      "selectedCommand",
    );
    expect(simplePanel).toContain(
      'event.key ===',
    );
    expect(simplePanel).toContain(
      '"Enter"',
    );
    expect(simplePanel).toContain(
      '"Escape"',
    );
  });
});
