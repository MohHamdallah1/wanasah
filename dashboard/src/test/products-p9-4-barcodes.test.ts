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

describe("Products P9.4 Barcode workspace", () => {
  it("keeps race, scope, durable create and durable deactivation authority in the manager", () => {
    const manager = read(
      "../pages/products/barcode/ProductBarcodeManager.tsx",
    );

    expect(manager).toContain(
      "<ProductBarcodeList",
    );
    expect(manager).toContain(
      "<ProductBarcodeCreatePanel",
    );
    expect(manager).toContain(
      "requestSequence.current",
    );
    expect(manager).toContain(
      "PRODUCT_BARCODES_SCOPE_MISMATCH",
    );
    expect(manager).toContain(
      "PRODUCT_BARCODES_CURSOR_DUPLICATE",
    );
    expect(manager).toContain(
      '"catalog-barcode-create-v2"',
    );
    expect(manager).toContain(
      '"catalog-barcode-update"',
    );
    expect(manager).toContain(
      "getOrCreateDurableCommand(",
    );
    expect(manager).toContain(
      "expected_version:",
    );
  });

  it("renders barcode history as a compact status-rich list with local loading/error/empty pagination", () => {
    const list = read(
      "../pages/products/barcode/ProductBarcodeList.tsx",
    );

    expect(list).toContain(
      '"products.barcodeManager.loadFailed"',
    );
    expect(list).toContain(
      '"products.barcodeManager.none"',
    );
    expect(list).toContain(
      '"products.barcodeManager.primary"',
    );
    expect(list).toContain(
      '"products.barcodeManager.inactive"',
    );
    expect(list).toContain(
      '"products.barcodeManager.loadMore"',
    );
    expect(list).toContain(
      "onDeactivate(item)",
    );
    expect(list).toContain(
      "break-all font-mono",
    );
  });

  it("keeps barcode creation compact while preserving target type primary and shared-package semantics", () => {
    const create = read(
      "../pages/products/barcode/ProductBarcodeCreatePanel.tsx",
    );

    expect(create).toContain(
      '"products.barcodeManager.scope"',
    );
    expect(create).toContain(
      '"products.barcodeManager.type"',
    );
    expect(create).toContain(
      '"products.barcodeManager.value"',
    );
    expect(create).toContain(
      '"products.barcodeManager.makePrimary"',
    );
    expect(create).toContain(
      '"products.barcodeManager.sharedPackageHint"',
    );
    expect(create).toContain(
      "pendingCreateBlocked",
    );
    expect(create).toContain(
      "targetUomId",
    );
  });

  it("keeps failed loading isolated from confirmed empty and barcode creation", () => {
    const manager = read(
      "../pages/products/barcode/ProductBarcodeManager.tsx",
    );
    const list = read(
      "../pages/products/barcode/ProductBarcodeList.tsx",
    );

    expect(manager).toContain(
      "loadReady &&",
    );
    expect(manager).toContain(
      "!loadError ? (",
    );
    expect(list).toContain(
      "if (loadError)",
    );
    expect(list).toContain(
      "loadReady &&",
    );
  });
});
