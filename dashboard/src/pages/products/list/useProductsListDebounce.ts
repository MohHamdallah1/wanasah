import {
  useEffect,
} from "react";

import type {
  ProductBooleanFilter,
} from "@/pages/products/list/types";
import type { ProductWarehouseFilterOption } from "@/pages/products/list/warehouseFilterContract";

type Params = {
  searchInput: string;
  setSearch: (value: string) => void;
  familyFilterSearchInput: string;
  setFamilyFilterSearch: (
    value: string,
  ) => void;
  warehouseFilterSearchInput: string;
  setWarehouseFilterSearch: (value: string) => void;
  canFilterByWarehouse: boolean;
  warehouseFilters: ProductWarehouseFilterOption[];
  setWarehouseFilters: (value: ProductWarehouseFilterOption[]) => void;
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
  warehouseFilterSearchInput,
  setWarehouseFilterSearch,
  canFilterByWarehouse,
  warehouseFilters,
  setWarehouseFilters,
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
  }, [
    searchInput,
    setCursor,
    setHistory,
    setSearch,
  ]);

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
  }, [
    familyFilterSearchInput,
    setFamilyFilterSearch,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = warehouseFilterSearchInput.trim().slice(0, 100);
      setWarehouseFilterSearch(clean.length >= 2 ? clean : "");
    }, 250);
    return () => window.clearTimeout(timer);
  }, [warehouseFilterSearchInput, setWarehouseFilterSearch]);

  useEffect(() => {
    if (canFilterByWarehouse || warehouseFilters.length === 0) {
      return;
    }
    setWarehouseFilters([]);
    setCursor(null);
    setHistory([]);
  }, [
    canFilterByWarehouse,
    warehouseFilters.length,
    setCursor,
    setHistory,
    setWarehouseFilters,
  ]);

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
    setCursor,
    setHistory,
    setPriceFilter,
  ]);
}
