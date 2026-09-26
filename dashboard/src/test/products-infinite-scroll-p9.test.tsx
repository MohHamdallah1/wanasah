import {
  renderHook,
  waitFor,
} from "@testing-library/react";
import {
  describe,
  expect,
  it,
} from "vitest";

import type {
  SimpleProduct,
  SimpleProductPage,
} from "@/pages/products/contracts";
import {
  useProductsInfiniteRows,
} from "@/pages/products/list/useProductsInfiniteRows";

const product = (
  id: number,
  name: string,
): SimpleProduct => ({
  id,
  product_id: id,
  name,
  family_name: "Family",
  sku: `SKU-${id}`,
  units_per_package: 1,
  legacy_packs_per_carton: 1,
  base_uom_id: 1,
  package_uom_id: null,
  package_uom_code: null,
  currency_code: "JOD",
  package_price: null,
  unit_price: null,
  unit_barcode: null,
  package_barcode: null,
  package_uses_base_barcode: false,
  version: 1,
  lot_control_mode: "NONE",
  expiry_control_mode: "NONE",
  lifecycle_status: "ACTIVE",
  operational_hold: "NONE",
  simple_compatible: true,
});

const page = (
  items: SimpleProduct[],
  nextCursor: string | null,
): SimpleProductPage => ({
  currency_code: "JOD",
  pricing_visible: false,
  items,
  next_cursor: nextCursor,
  has_more:
    nextCursor !== null,
});

describe(
  "Products bounded infinite rows",
  () => {
    it("appends cursor pages, replaces duplicate rows, and resets on a new result scope", async () => {
      const first = page(
        [
          product(1, "One"),
          product(2, "Two"),
        ],
        "cursor-2",
      );
      const second = page(
        [
          product(
            2,
            "Two updated",
          ),
          product(3, "Three"),
        ],
        null,
      );

      const { result, rerender } =
        renderHook(
          ({
            currentPage,
            cursor,
            scopeKey,
            pageReady,
          }) =>
            useProductsInfiniteRows({
              page: currentPage,
              cursor,
              scopeKey,
              pageReady,
            }),
          {
            initialProps: {
              currentPage:
                first as
                  | SimpleProductPage
                  | undefined,
              cursor:
                null as
                  | string
                  | null,
              scopeKey: "scope-a",
              pageReady: true,
            },
          },
        );

      await waitFor(() => {
        expect(
          result.current.map(
            (item) => item.id,
          ),
        ).toEqual([1, 2]);
      });

      rerender({
        currentPage: first,
        cursor: "cursor-2",
        scopeKey: "scope-a",
        pageReady: false,
      });

      expect(
        result.current.map(
          (item) => item.id,
        ),
      ).toEqual([1, 2]);

      rerender({
        currentPage: second,
        cursor: "cursor-2",
        scopeKey: "scope-a",
        pageReady: true,
      });

      await waitFor(() => {
        expect(
          result.current.map(
            (item) => [
              item.id,
              item.name,
            ],
          ),
        ).toEqual([
          [1, "One"],
          [2, "Two updated"],
          [3, "Three"],
        ]);
      });

      rerender({
        currentPage: undefined,
        cursor: null,
        scopeKey: "scope-b",
        pageReady: false,
      });

      await waitFor(() => {
        expect(
          result.current,
        ).toEqual([]);
      });
    });
  },
);
