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

describe("Products quick keyboard UX", () => {
  it("keeps package barcode copy obvious and one-click", () => {
    const source = read(
      "../pages/products/create/CreateProductBarcodeSection.tsx",
    );

    expect(source).toContain(
      '"products.copyBarcode"',
    );
    expect(source).toContain(
      "onClick={onCopyBarcode}",
    );
    expect(source).toContain(
      "!draft.unit_barcode.trim()",
    );
    expect(source.indexOf(
      "onClick={onCopyBarcode}",
    )).toBeLessThan(
      source.indexOf(
        "draft.package_barcode",
      ),
    );
  });

  it("submits price editing with Enter", () => {
    const source = read(
      "../pages/products/pricing/PriceEditModal.tsx",
    );

    expect(source).toContain(
      'event.key === "Enter"',
    );
    expect(source).toContain(
      "event.preventDefault();",
    );
    expect(source).toContain(
      "onSubmit();",
    );
  });

  it("submits product rename with Enter only when the edit is valid", () => {
    const source = read(
      "../pages/products/rename/ProductRenameDialog.tsx",
    );

    expect(source).toContain(
      'event.key === "Enter"',
    );
    expect(source).toContain(
      "!inputLocked",
    );
    expect(source).toContain(
      "isOnline",
    );
    expect(source).toContain(
      "cleanName",
    );
    expect(source).toContain(
      "!unchanged",
    );
    expect(source).toContain(
      "void save();",
    );
  });
});
