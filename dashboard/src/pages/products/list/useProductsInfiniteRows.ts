import {
  useEffect,
  useState,
} from "react";

import type {
  SimpleProduct,
  SimpleProductPage,
} from "@/pages/products/contracts";

type Params = {
  page: SimpleProductPage | undefined;
  cursor: string | null;
  scopeKey: string;
  pageReady: boolean;
};

type RowsState = {
  scopeKey: string;
  items: SimpleProduct[];
};

const mergeProductRows = (
  current: SimpleProduct[],
  incoming: SimpleProduct[],
): SimpleProduct[] => {
  const incomingById =
    new Map(
      incoming.map((item) => [
        item.id,
        item,
      ]),
    );
  const seen =
    new Set(
      current.map(
        (item) => item.id,
      ),
    );

  return [
    ...current.map(
      (item) =>
        incomingById.get(item.id) ??
        item,
    ),
    ...incoming.filter(
      (item) =>
        !seen.has(item.id),
    ),
  ];
};

const firstPageItems = (
  page: SimpleProductPage | undefined,
  cursor: string | null,
  pageReady: boolean,
): SimpleProduct[] =>
  cursor === null &&
  pageReady &&
  page
    ? page.items
    : [];

export function useProductsInfiniteRows({
  page,
  cursor,
  scopeKey,
  pageReady,
}: Params): SimpleProduct[] {
  const [
    rows,
    setRows,
  ] =
    useState<RowsState>(() => ({
      scopeKey,
      items: firstPageItems(
        page,
        cursor,
        pageReady,
      ),
    }));

  const visibleItems =
    rows.scopeKey === scopeKey
      ? rows.items
      : firstPageItems(
          page,
          cursor,
          pageReady,
        );

  useEffect(() => {
    if (
      !page ||
      !pageReady
    ) {
      if (
        rows.scopeKey !==
        scopeKey
      ) {
        setRows({
          scopeKey,
          items: [],
        });
      }
      return;
    }

    setRows((current) => {
      const currentItems =
        current.scopeKey ===
        scopeKey
          ? current.items
          : [];

      return {
        scopeKey,
        items:
          cursor === null
            ? page.items
            : mergeProductRows(
                currentItems,
                page.items,
              ),
      };
    });
  }, [
    cursor,
    page,
    pageReady,
    rows.scopeKey,
    scopeKey,
  ]);

  return visibleItems;
}
