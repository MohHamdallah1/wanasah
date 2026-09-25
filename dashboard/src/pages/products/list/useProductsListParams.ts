import {
  useMemo,
} from "react";

import type {
  ProductBooleanFilter,
  ProductLifecycleFilter,
  ProductSortDirection,
  ProductSortField,
  ProductTrackingTypeFilter,
} from "@/pages/products/list/types";

type Params = {
  search: string;
  cursor: string | null;
  familyFilterId: string;
  lifecycleFilter: ProductLifecycleFilter;
  trackingTypeFilter: ProductTrackingTypeFilter;
  compatibilityFilter: ProductBooleanFilter;
  barcodeFilter: ProductBooleanFilter;
  canViewPricing: boolean;
  priceFilter: ProductBooleanFilter;
  lotFilter: ProductBooleanFilter;
  expiryFilter: ProductBooleanFilter;
  sortBy: ProductSortField;
  sortDir: ProductSortDirection;
  familyFilterSearch: string;
};

export function useProductsListParams({
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
}: Params) {
  const params = useMemo(
    () => {
      const value =
        new URLSearchParams({
          limit: "100",
          sort_by: sortBy,
          sort_dir: sortDir,
        });
      if (search) {
        value.set(
          "search",
          search
        );
      }
      if (cursor) {
        value.set(
          "cursor",
          cursor
        );
      }
      if (familyFilterId) {
        value.set(
          "family_id",
          familyFilterId
        );
      }
      if (lifecycleFilter) {
        value.set(
          "lifecycle",
          lifecycleFilter
        );
      }
      if (trackingTypeFilter) {
        value.set(
          "tracking_type",
          trackingTypeFilter
        );
      }
      if (compatibilityFilter) {
        value.set(
          "simple_compatible",
          compatibilityFilter
        );
      }
      if (barcodeFilter) {
        value.set(
          "has_barcode",
          barcodeFilter
        );
      }
      if (
        canViewPricing &&
        priceFilter
      ) {
        value.set(
          "has_price",
          priceFilter
        );
      }
      if (lotFilter) {
        value.set(
          "lot_tracked",
          lotFilter
        );
      }
      if (expiryFilter) {
        value.set(
          "expiry_tracked",
          expiryFilter
        );
      }
      return value.toString();
    },
    [
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
    ]
  );

  const familyFilterParams =
    useMemo(
      () => {
        const value =
          new URLSearchParams({
            limit: "50",
          });
        if (familyFilterSearch) {
          value.set(
            "search",
            familyFilterSearch
          );
        }
        return value.toString();
      },
      [familyFilterSearch]
    );

  return {
    params,
    familyFilterParams,
  };
}
