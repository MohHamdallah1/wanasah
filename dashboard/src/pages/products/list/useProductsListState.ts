import {
  useState,
} from "react";

import type {
  ProductBooleanFilter,
  ProductLifecycleFilter,
  ProductSortDirection,
  ProductSortField,
  ProductTrackingTypeFilter,
} from "@/pages/products/list/types";

export function useProductsListState() {
  const [
    searchInput,
    setSearchInput,
  ] = useState("");
  const [
    search,
    setSearch,
  ] = useState("");
  const [
    cursor,
    setCursor,
  ] = useState<string | null>(
    null
  );
  const [
    history,
    setHistory,
  ] = useState<
    Array<string | null>
  >([]);
  const [
    filtersOpen,
    setFiltersOpen,
  ] = useState(false);
  const [
    familyFilterSearchInput,
    setFamilyFilterSearchInput,
  ] = useState("");
  const [
    familyFilterSearch,
    setFamilyFilterSearch,
  ] = useState("");
  const [
    familyFilterId,
    setFamilyFilterId,
  ] = useState("");
  const [
    familyFilterName,
    setFamilyFilterName,
  ] = useState("");
  const [
    lifecycleFilter,
    setLifecycleFilter,
  ] =
    useState<ProductLifecycleFilter>(
      ""
    );
  const [
    trackingTypeFilter,
    setTrackingTypeFilter,
  ] =
    useState<ProductTrackingTypeFilter>(
      ""
    );
  const [
    compatibilityFilter,
    setCompatibilityFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    barcodeFilter,
    setBarcodeFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    priceFilter,
    setPriceFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    lotFilter,
    setLotFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    expiryFilter,
    setExpiryFilter,
  ] =
    useState<ProductBooleanFilter>(
      ""
    );
  const [
    sortBy,
    setSortBy,
  ] =
    useState<ProductSortField>(
      "id"
    );
  const [
    sortDir,
    setSortDir,
  ] =
    useState<ProductSortDirection>(
      "asc"
    );

  const resetProductPagination = () => {
    setCursor(null);
    setHistory([]);
  };

  return {
    searchInput,
    setSearchInput,
    search,
    setSearch,
    cursor,
    setCursor,
    history,
    setHistory,
    filtersOpen,
    setFiltersOpen,
    familyFilterSearchInput,
    setFamilyFilterSearchInput,
    familyFilterSearch,
    setFamilyFilterSearch,
    familyFilterId,
    setFamilyFilterId,
    familyFilterName,
    setFamilyFilterName,
    lifecycleFilter,
    setLifecycleFilter,
    trackingTypeFilter,
    setTrackingTypeFilter,
    compatibilityFilter,
    setCompatibilityFilter,
    barcodeFilter,
    setBarcodeFilter,
    priceFilter,
    setPriceFilter,
    lotFilter,
    setLotFilter,
    expiryFilter,
    setExpiryFilter,
    sortBy,
    setSortBy,
    sortDir,
    setSortDir,
    resetProductPagination,
  };
}
