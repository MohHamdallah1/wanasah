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
import { emptyProductStatusEvidence, singleUnitProductDefaults } from "./fixtures/productRows";

const product = (
  id: number,
  name: string,
): SimpleProduct => ({
  ...singleUnitProductDefaults,
  ...emptyProductStatusEvidence,
  id,
  product_id: id,
  name,
  family_name: "Family",
  sku: `SKU-${id}`,
  version: 1,
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
    it("renders a cached first page synchronously, appends cursor pages, and never flashes a stale scope", async () => {
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

      expect(
        result.current.map(
          (item) => item.id,
        ),
      ).toEqual([1, 2]);

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

      expect(
        result.current,
      ).toEqual([]);

      const third = page(
        [
          product(9, "Nine"),
        ],
        null,
      );

      rerender({
        currentPage: third,
        cursor: null,
        scopeKey: "scope-c",
        pageReady: true,
      });

      expect(
        result.current.map(
          (item) => item.id,
        ),
      ).toEqual([9]);
    });
  },
);
