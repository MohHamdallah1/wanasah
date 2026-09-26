import type {
  Dispatch,
  SetStateAction,
} from "react";

import type {
  ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import type {
  ProductFamily,
} from "@/pages/products/contracts";
import type {
  ProductBooleanFilter,
  ProductLifecycleFilter,
  ProductSortDirection,
  ProductSortField,
  ProductTrackingTypeFilter,
} from "@/pages/products/list/types";

type Params = {
  familyFilterOptions: ProductFamily[];
  displayPreferences: ProductDisplayPreferences;
  cursor: string | null;
  history: Array<string | null>;
  setFiltersOpen: Dispatch<
    SetStateAction<boolean>
  >;
  setSearchInput: Dispatch<
    SetStateAction<string>
  >;
  setSearch: Dispatch<
    SetStateAction<string>
  >;
  setFamilyFilterId: Dispatch<
    SetStateAction<string>
  >;
  setFamilyFilterName: Dispatch<
    SetStateAction<string>
  >;
  setFamilyFilterSearchInput: Dispatch<
    SetStateAction<string>
  >;
  setLifecycleFilter: Dispatch<
    SetStateAction<ProductLifecycleFilter>
  >;
  setTrackingTypeFilter: Dispatch<
    SetStateAction<ProductTrackingTypeFilter>
  >;
  setCompatibilityFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setBarcodeFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setPriceFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setLotFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setExpiryFilter: Dispatch<
    SetStateAction<ProductBooleanFilter>
  >;
  setSortBy: Dispatch<
    SetStateAction<ProductSortField>
  >;
  setSortDir: Dispatch<
    SetStateAction<ProductSortDirection>
  >;
  setCursor: Dispatch<
    SetStateAction<string | null>
  >;
  setHistory: Dispatch<
    SetStateAction<
      Array<string | null>
    >
  >;
  resetProductPagination: () => void;
};

export function createProductsListActions({
  familyFilterOptions,
  displayPreferences,
  cursor,
  history,
  setFiltersOpen,
  setSearchInput,
  setSearch,
  setFamilyFilterId,
  setFamilyFilterName,
  setFamilyFilterSearchInput,
  setLifecycleFilter,
  setTrackingTypeFilter,
  setCompatibilityFilter,
  setBarcodeFilter,
  setPriceFilter,
  setLotFilter,
  setExpiryFilter,
  setSortBy,
  setSortDir,
  setCursor,
  setHistory,
  resetProductPagination,
}: Params) {
  const toggleFilters = () =>
    setFiltersOpen(
      (current) => !current
    );

  const clearControls = () => {
    setFamilyFilterId("");
    setFamilyFilterName("");
    setFamilyFilterSearchInput("");
    setLifecycleFilter("");
    setTrackingTypeFilter("");
    setCompatibilityFilter("");
    setBarcodeFilter("");
    setPriceFilter("");
    setLotFilter("");
    setExpiryFilter("");
    setSortBy(
      displayPreferences.defaultSort
        .field
    );
    setSortDir(
      displayPreferences.defaultSort
        .direction
    );
    resetProductPagination();
  };

  const clearAllCriteria = () => {
    setSearchInput("");
    setSearch("");
    clearControls();
  };

  const selectFamily = (
    nextId: string
  ) => {
    const selected =
      familyFilterOptions.find(
        (item) =>
          String(item.id) ===
          nextId
      );
    setFamilyFilterId(
      nextId
    );
    setFamilyFilterName(
      selected?.name ?? ""
    );
    resetProductPagination();
  };

  const updateLifecycleFilter = (
    value: ProductLifecycleFilter
  ) => {
    setLifecycleFilter(value);
    resetProductPagination();
  };

  const updateTrackingTypeFilter = (
    value: ProductTrackingTypeFilter
  ) => {
    setTrackingTypeFilter(value);
    resetProductPagination();
  };

  const updateCompatibilityFilter = (
    value: ProductBooleanFilter
  ) => {
    setCompatibilityFilter(value);
    resetProductPagination();
  };

  const updateBarcodeFilter = (
    value: ProductBooleanFilter
  ) => {
    setBarcodeFilter(value);
    resetProductPagination();
  };

  const updatePriceFilter = (
    value: ProductBooleanFilter
  ) => {
    setPriceFilter(value);
    resetProductPagination();
  };

  const updateLotFilter = (
    value: ProductBooleanFilter
  ) => {
    setLotFilter(value);
    resetProductPagination();
  };

  const updateExpiryFilter = (
    value: ProductBooleanFilter
  ) => {
    setExpiryFilter(value);
    resetProductPagination();
  };

  const updateSortBy = (
    value: ProductSortField
  ) => {
    setSortBy(value);
    resetProductPagination();
  };

  const updateSortDir = (
    value: ProductSortDirection
  ) => {
    setSortDir(value);
    resetProductPagination();
  };

  const goPrevious = () => {
    const previous =
      history.at(-1) ?? null;
    setHistory(
      (current) =>
        current.slice(
          0,
          -1
        )
    );
    setCursor(previous);
  };

  const goNext = (
    nextCursor: string | null
  ) => {
    if (!nextCursor) {
      return;
    }
    setHistory(
      (current) => [
        ...current,
        cursor,
      ]
    );
    setCursor(nextCursor);
  };

  return {
    toggleFilters,
    clearControls,
    clearAllCriteria,
    selectFamily,
    updateLifecycleFilter,
    updateTrackingTypeFilter,
    updateCompatibilityFilter,
    updateBarcodeFilter,
    updatePriceFilter,
    updateLotFilter,
    updateExpiryFilter,
    updateSortBy,
    updateSortDir,
    goPrevious,
    goNext,
  };
}
