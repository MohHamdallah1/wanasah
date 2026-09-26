import type {
  ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import { createProductsListActions } from "@/pages/products/list/createProductsListActions";
import { deriveProductsListViewState } from "@/pages/products/list/deriveProductsListViewState";
import { useProductsListDebounce } from "@/pages/products/list/useProductsListDebounce";
import { useProductsListParams } from "@/pages/products/list/useProductsListParams";
import { useProductsListQueries } from "@/pages/products/list/useProductsListQueries";
import { useProductsListState } from "@/pages/products/list/useProductsListState";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  companyId: number | null;
  authFetch: AuthFetch;
  canViewPricing: boolean;
  displayPreferences:
    ProductDisplayPreferences;
};

export function useProductsListWorkflow({
  companyId,
  authFetch,
  canViewPricing,
  displayPreferences,
}: Params) {
  const {
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
  } = useProductsListState();

  useProductsListDebounce({
    searchInput,
    setSearch,
    familyFilterSearchInput,
    setFamilyFilterSearch,
    canViewPricing,
    priceFilter,
    setPriceFilter,
    setCursor,
    setHistory,
  });

  const {
    params,
    familyFilterParams,
  } = useProductsListParams({
    search,
    cursor,
    familyFilterId,
    lifecycleFilter,
    trackingTypeFilter,
    compatibilityFilter,
    barcodeFilter,
    canViewPricing,
    priceFilter,
    lotFilter,
    expiryFilter,
    sortBy,
    sortDir,
    familyFilterSearch,
  });

  const {
    productsQuery,
    familyFilterOptionsQuery,
  } = useProductsListQueries({
    companyId,
    params,
    filtersOpen,
    familyFilterSearch,
    familyFilterParams,
    authFetch,
  });

  const page =
    productsQuery.data;
  const familyFilterOptions =
    familyFilterOptionsQuery.data
      ?.items ?? [];

  const {
    pricingVisible,
    visibleColumns,
    productTableColumnCount,
    tableHeaderSpacing,
    hasProductListControls,
  } = deriveProductsListViewState({
    page,
    canViewPricing,
    displayPreferences,
    familyFilterId,
    lifecycleFilter,
    trackingTypeFilter,
    compatibilityFilter,
    barcodeFilter,
    priceFilter,
    lotFilter,
    expiryFilter,
    sortBy,
    sortDir,
  });

  const {
    toggleFilters,
    clearControls,
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
  } = createProductsListActions({
    familyFilterOptions,
    displayPreferences,
    cursor,
    history,
    setFiltersOpen,
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
  });

  return {
    isFetching:
      productsQuery.isFetching,
    refresh: () =>
      void productsQuery.refetch(),
    pricingVisible,
    identityScope: {
      setCursor,
      setHistory,
      setFiltersOpen,
      setFamilyFilterSearchInput,
      setFamilyFilterSearch,
      setFamilyFilterId,
      setFamilyFilterName,
      setLifecycleFilter,
      setTrackingTypeFilter,
      setCompatibilityFilter,
      setBarcodeFilter,
      setPriceFilter,
      setLotFilter,
      setExpiryFilter,
      setSortBy,
      setSortDir,
    },
    paginationScope: {
      setCursor,
      setHistory,
    },
    displayPreferenceScope: {
      setSortBy,
      setSortDir,
      resetProductPagination,
    },
    section: {
      filtersOpen,
      toolbar: {
        searchInput,
        filtersOpen,
        hasActiveControls:
          hasProductListControls,
        onSearchInputChange:
          setSearchInput,
        onToggleFilters:
          toggleFilters,
      },
      activeFilters: {
        familyFilterId,
        familyFilterName,
        lifecycleFilter,
        trackingTypeFilter,
        compatibilityFilter,
        barcodeFilter,
        canViewPricing,
        priceFilter,
        lotFilter,
        expiryFilter,
        sortBy,
        sortDir,
        defaultSortBy:
          displayPreferences.defaultSort
            .field,
        defaultSortDir:
          displayPreferences.defaultSort
            .direction,
        onFamilyFilterChange:
          selectFamily,
        onLifecycleFilterChange:
          updateLifecycleFilter,
        onTrackingTypeFilterChange:
          updateTrackingTypeFilter,
        onCompatibilityFilterChange:
          updateCompatibilityFilter,
        onBarcodeFilterChange:
          updateBarcodeFilter,
        onPriceFilterChange:
          updatePriceFilter,
        onLotFilterChange:
          updateLotFilter,
        onExpiryFilterChange:
          updateExpiryFilter,
        onSortByChange:
          updateSortBy,
        onSortDirChange:
          updateSortDir,
        onClearControls:
          clearControls,
      },
      filters: {
        familyFilterSearchInput,
        familyFilterId,
        familyFilterName,
        familyFilterOptions,
        familyOptionsError:
          familyFilterOptionsQuery.isError,
        lifecycleFilter,
        trackingTypeFilter,
        compatibilityFilter,
        barcodeFilter,
        canViewPricing,
        priceFilter,
        lotFilter,
        expiryFilter,
        sortBy,
        sortDir,
        onFamilySearchInputChange:
          setFamilyFilterSearchInput,
        onFamilyFilterChange:
          selectFamily,
        onRetryFamilyOptions: () =>
          void familyFilterOptionsQuery.refetch(),
        onLifecycleFilterChange:
          updateLifecycleFilter,
        onTrackingTypeFilterChange:
          updateTrackingTypeFilter,
        onCompatibilityFilterChange:
          updateCompatibilityFilter,
        onBarcodeFilterChange:
          updateBarcodeFilter,
        onPriceFilterChange:
          updatePriceFilter,
        onLotFilterChange:
          updateLotFilter,
        onExpiryFilterChange:
          updateExpiryFilter,
        onSortByChange:
          updateSortBy,
        onSortDirChange:
          updateSortDir,
      },
      results: {
        items:
          page?.items ?? [],
        isLoading:
          productsQuery.isLoading,
        isError:
          productsQuery.isError,
        isFetching:
          productsQuery.isFetching,
        pricingVisible,
        columns:
          visibleColumns,
        density:
          displayPreferences.density,
        tableHeaderSpacing,
        tableColumnCount:
          productTableColumnCount,
        hasPrevious:
          history.length > 0,
        hasNext:
          Boolean(
            page?.next_cursor
          ),
        onRetry: () =>
          void productsQuery.refetch(),
        onPrevious:
          goPrevious,
        onNext: () =>
          goNext(
            page?.next_cursor ??
              null
          ),
      },
    },
  };
}
