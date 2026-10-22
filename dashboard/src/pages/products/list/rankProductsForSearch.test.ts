import { describe, expect, it } from "vitest";

import type { SimpleProduct } from "@/pages/products/contracts";
import { rankProductsForSearch } from "@/pages/products/list/rankProductsForSearch";

const product = (
  id: number,
  name: string,
  sku = "",
): SimpleProduct =>
  ({
    id,
    name,
    sku,
    family_name: "",
    unit_barcode: null,
    package_barcode: null,
  }) as SimpleProduct;

describe("rankProductsForSearch", () => {
  it("pins the exact full-name match before broader partial matches", () => {
    const rows = [
      product(1, "???? ????? ????"),
      product(2, "???? ?????"),
      product(3, "??? ???? ?????"),
    ];

    expect(
      rankProductsForSearch(rows, "???? ?????").map((row) => row.id),
    ).toEqual([2, 1, 3]);
  });

  it("keeps broad results while prioritizing exact code matches", () => {
    const rows = [
      product(1, "???? ABC ?????", "ABC-2"),
      product(2, "???? ???", "ABC"),
    ];

    expect(
      rankProductsForSearch(rows, "ABC").map((row) => row.id),
    ).toEqual([2, 1]);
  });
});
