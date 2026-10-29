import {
  describe,
  expect,
  it,
} from "vitest";

import {
  inspectProductImportFile,
} from "@/pages/products/import/productImportFilePreflight";

const csvFile = (
  lines: string[],
  name = "products.csv",
) =>
  new File(
    [lines.join("\n")],
    name,
    {
      type: "text/csv",
    },
  );

describe("Product Import tracking fallback preflight", () => {
  it("does not request a fallback when every tracking cell is explicit", async () => {
    const file = csvFile([
      [
        "اسم المنتج",
        "تتبع التشغيلة",
        "تتبع الصلاحية",
      ].join(","),
      [
        "منتج 1",
        "إلزامي",
        "اختياري",
      ].join(","),
      [
        "منتج 2",
        "بدون",
        "إلزامي",
      ].join(","),
    ]);

    const result =
      await inspectProductImportFile(
        file,
      );

    expect(
      result.hasDataRows,
    ).toBe(true);
    expect(
      result.tracking,
    ).toEqual({
      status: "NOT_NEEDED",
      dataRows: 2,
      lotFallbackRows: 0,
      expiryFallbackRows: 0,
    });
  });

  it("counts only blank and use-default tracking cells", async () => {
    const file = csvFile([
      [
        "Name",
        "Lot Tracking",
        "Expiry Tracking",
      ].join(","),
      [
        "Product 1",
        "",
        "Optional",
      ].join(","),
      [
        "Product 2",
        "Use default",
        "",
      ].join(","),
      [
        "Product 3",
        "Required",
        "None",
      ].join(","),
    ]);

    const result =
      await inspectProductImportFile(
        file,
      );

    expect(
      result.tracking,
    ).toEqual({
      status: "NEEDED",
      dataRows: 3,
      lotFallbackRows: 2,
      expiryFallbackRows: 1,
    });
  });

  it("fails safe when tracking columns cannot be identified before backend mapping", async () => {
    const file = csvFile(
      [
        "Name,Custom Tracking",
        "Product 1,Something",
      ],
      "external.csv",
    );

    const result =
      await inspectProductImportFile(
        file,
      );

    expect(
      result.hasDataRows,
    ).toBe(true);
    expect(
      result.tracking.status,
    ).toBe("UNKNOWN");
    expect(
      result.tracking.dataRows,
    ).toBe(1);
    expect(
      result.tracking.lotFallbackRows,
    ).toBeNull();
    expect(
      result.tracking.expiryFallbackRows,
    ).toBeNull();
  });

  it("does not reinterpret an explicit invalid value as a blank fallback", async () => {
    const file = csvFile(
      [
        [
          "اسم المنتج",
          "تتبع التشغيلة",
          "تتبع الصلاحية",
        ].join(","),
        [
          "منتج 1",
          "قيمة غير معروفة",
          "اختياري",
        ].join(","),
      ],
      "invalid-value.csv",
    );

    const result =
      await inspectProductImportFile(
        file,
      );

    expect(
      result.tracking.status,
    ).toBe("NOT_NEEDED");
    expect(
      result.tracking.lotFallbackRows,
    ).toBe(0);
  });
});
