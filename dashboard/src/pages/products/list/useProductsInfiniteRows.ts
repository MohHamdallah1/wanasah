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

export function useProductsInfiniteRows({
  page,
  cursor,
  scopeKey,
  pageReady,
}: Params): SimpleProduct[] {
  const [
    items,
    setItems,
  ] =
    useState<SimpleProduct[]>(
      [],
    );

  useEffect(() => {
    setItems([]);
  }, [scopeKey]);

  useEffect(() => {
    if (
      !page ||
      !pageReady
    ) {
      return;
    }

    if (cursor === null) {
      setItems(page.items);
      return;
    }

    setItems((current) =>
      mergeProductRows(
        current,
        page.items,
      ),
    );
  }, [
    cursor,
    page,
    pageReady,
    scopeKey,
  ]);

  return items;
}
