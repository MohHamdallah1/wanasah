import type {
  ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import { createProductsListActions } from "@/pages/products/list/createProductsListActions";
import { deriveProductsListViewState } from "@/pages/products/list/deriveProductsListViewState";
import { useProductsInfiniteRows } from "@/pages/products/list/useProductsInfiniteRows";
import { useProductsListDebounce } from "@/pages/products/list/useProductsListDebounce";
import { useProductsListParams } from "@/pages/products/list/useProductsListParams";
import { useProductsListQueries } from "@/pages/products/list/useProductsListQueries";
import { useProductsListState } from "@/pages/products/list/useProductsListState";
import { useProductCatalogSummary } from "@/pages/products/list/useProductCatalogSummary";

type AuthFetch = (
  path: string,
  opts?: RequestInit,
) => Promise<unknown>;

type Params = {
  companyId: number | null;
  driverId: number | null;
  authFetch: AuthFetch;
  canViewPricing: boolean;
  canFilterByWarehouse: boolean;
  displayPreferences:
    ProductDisplayPreferences;
  online: boolean;
};

export function useProductsListWorkflow({
  companyId,
  driverId,
  authFetch,
  canViewPricing,
  canFilterByWarehouse,
  displayPreferences,
  online,
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
    warehouseFilterSearchInput,
    setWarehouseFilterSearchInput,
    warehouseFilterSearch,
    setWarehouseFilterSearch,
    warehouseFilters,
    setWarehouseFilters,
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
  });

  const {
    params,
    resultScopeKey,
    familyFilterParams,
  } = useProductsListParams({
    search,
    cursor,
    familyFilterId,
    warehouseFilters,
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
    warehouseFilterOptionsQuery,
  } = useProductsListQueries({
    companyId,
    params,
    cursor,
    filtersOpen,
    familyFilterSearch,
    familyFilterParams,
    canFilterByWarehouse,
    warehouseFilterSearch,
    authFetch,
  });

  const page =
    productsQuery.data;
  const summaryQuery = useProductCatalogSummary({ companyId, driverId, authFetch });
  const accumulatedItems =
    useProductsInfiniteRows({
      page,
      cursor,
      scopeKey:
        resultScopeKey,
      pageReady:
        !productsQuery.isPlaceholderData,
    });
  const familyFilterOptions =
    familyFilterOptionsQuery.data
      ?.items ?? [];

  const {
    pricingVisible,
    visibleColumns,
    tableHeaderSpacing,
    hasProductListControls,
    hasResultCriteria,
  } = deriveProductsListViewState({
    page,
    search,
    canViewPricing,
    displayPreferences,
    familyFilterId,
    warehouseFilters,
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
    clearControls,
    clearAllCriteria,
    selectFamily,
    updateWarehouseFilters,
    updateLifecycleFilter,
    updateTrackingTypeFilter,
    updateCompatibilityFilter,
    updateBarcodeFilter,
    updatePriceFilter,
    updateLotFilter,
    updateExpiryFilter,
    updateSortBy,
    updateSortDir,
    goNext,
  } = createProductsListActions({
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
    setWarehouseFilterSearchInput,
    setWarehouseFilters,
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
      productsQuery.isFetching || summaryQuery.isFetching,
    refresh: () => {
      void productsQuery.refetch();
      void summaryQuery.refetch();
    },
    pricingVisible,
    identityScope: {
      setCursor,
      setHistory,
      setFiltersOpen,
      setFamilyFilterSearchInput,
      setFamilyFilterSearch,
      setFamilyFilterId,
      setFamilyFilterName,
      setWarehouseFilterSearchInput,
      setWarehouseFilterSearch,
      setWarehouseFilters,
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
      summary: {
        data: summaryQuery.data,
        isFetching: summaryQuery.isFetching,
        error: summaryQuery.error,
        lifecycleFilter,
        onLifecycleFilterChange: updateLifecycleFilter,
        onRetry: () => { void summaryQuery.refetch(); },
      },
      toolbar: {
        searchInput,
        filtersOpen,
        hasActiveControls:
          hasProductListControls,
        onSearchInputChange:
          setSearchInput,
        onFiltersOpenChange:
          setFiltersOpen,
      },
      activeFilters: {
        familyFilterId,
        familyFilterName,
        warehouseFilters,
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
        onWarehouseFiltersChange:
          updateWarehouseFilters,
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
        canFilterByWarehouse,
        warehouseFilterSearchInput,
        warehouseFilterOptions: warehouseFilterOptionsQuery.data?.items ?? [],
        warehouseFilters,
        warehouseOptionsLoading: warehouseFilterOptionsQuery.isLoading,
        warehouseOptionsError: warehouseFilterOptionsQuery.isError,
        warehouseOptionsHasMore: warehouseFilterOptionsQuery.data?.has_more ?? false,
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
        onWarehouseFilterSearchInputChange:
          setWarehouseFilterSearchInput,
        onWarehouseFiltersChange:
          updateWarehouseFilters,
        onRetryWarehouseOptions: () =>
          void warehouseFilterOptionsQuery.refetch(),
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
        canReset:
          hasProductListControls,
        onClearControls:
          clearControls,
      },
      results: {
        items:
          accumulatedItems,
        isLoading:
          productsQuery.isLoading,
        isError:
          productsQuery.isError,
        isFetching:
          productsQuery.isFetching,
        error:
          productsQuery.error,
        online,
        hasResultCriteria,
        pricingVisible,
        columns:
          visibleColumns,
        density:
          displayPreferences.density,
        tableHeaderSpacing,
        hasNext:
          !productsQuery
            .isPlaceholderData &&
          Boolean(
            page?.next_cursor
          ),
        onLoadMore: () =>
          goNext(
            productsQuery
              .isPlaceholderData
              ? null
              : page?.next_cursor ??
                  null
          ),
        onRetry: () =>
          void productsQuery.refetch(),
        onClearCriteria:
          clearAllCriteria,
      },
    },
  };
}
