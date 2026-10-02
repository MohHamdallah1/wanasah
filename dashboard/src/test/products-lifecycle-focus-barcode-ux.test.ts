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
  it("focuses dialog content before the close control", () => {
    const source = read(
      "../hooks/useDialogFocusTrap.ts",
    );

    expect(source).toContain(
      '".app-modal-body, .app-modal-footer"',
    );
    expect(source).toContain(
      "firstInContent.focus();",
    );
    expect(source).toContain(
      "container.focus();",
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

  it("uses a simple commercial lifecycle surface without exposing the internal version", () => {
    const manager = read(
      "../pages/products/lifecycle/ProductLifecycleManager.tsx",
    );
    const rail = read(
      "../pages/products/lifecycle/ProductLifecycleStatusRail.tsx",
    );
    const actions = read(
      "../pages/inventory/catalog/CatalogLifecycleActions.tsx",
    );

    expect(manager).toContain(
      "simpleMode",
    );
    expect(rail).not.toContain(
      "variant.version",
    );
    expect(actions).toContain(
      "catalogLifecycle.simple.productStatusTitle",
    );
    expect(actions).toContain(
      "catalogLifecycle.simple.salesStatusTitle",
    );
    expect(actions).toContain(
      "selectedCommand",
    );
    expect(actions).toContain(
      'event.key ===',
    );
    expect(actions).toContain(
      '"Enter"',
    );
    expect(actions).toContain(
      '"Escape"',
    );
  });
});
