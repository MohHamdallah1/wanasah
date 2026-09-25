import {
  useEffect,
} from "react";

import type {
  ProductBooleanFilter,
} from "@/pages/products/list/types";

type Params = {
  searchInput: string;
  setSearch: (value: string) => void;
  familyFilterSearchInput: string;
  setFamilyFilterSearch: (
    value: string,
  ) => void;
  canViewPricing: boolean;
  priceFilter: ProductBooleanFilter;
  setPriceFilter: (
    value: ProductBooleanFilter,
  ) => void;
  setCursor: (
    value: string | null,
  ) => void;
  setHistory: (
    value:
      | Array<string | null>
      | ((
          current: Array<
            string | null
          >,
        ) => Array<string | null>),
  ) => void;
};

export function useProductsListDebounce({
  searchInput,
  setSearch,
  familyFilterSearchInput,
  setFamilyFilterSearch,
  canViewPricing,
  priceFilter,
  setPriceFilter,
  setCursor,
  setHistory,
}: Params) {
  useEffect(() => {
    const timer =
      window.setTimeout(() => {
        const clean =
          searchInput.trim();
        setSearch(
          clean.length >= 2
            ? clean
            : ""
        );
        setCursor(null);
        setHistory([]);
      }, 250);
    return () =>
      window.clearTimeout(
        timer
      );
  }, [searchInput]);

  useEffect(() => {
    const timer =
      window.setTimeout(() => {
        setFamilyFilterSearch(
          familyFilterSearchInput
            .trim()
            .slice(0, 100)
        );
      }, 250);
    return () =>
      window.clearTimeout(timer);
  }, [familyFilterSearchInput]);

  useEffect(() => {
    if (
      canViewPricing ||
      !priceFilter
    ) {
      return;
    }
    setPriceFilter("");
    setCursor(null);
    setHistory([]);
  }, [
    canViewPricing,
    priceFilter,
  ]);
}
