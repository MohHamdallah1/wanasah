import type {
  ProductDisplayPreferences,
} from "@/lib/productDisplayPreferences";
import type {
  SimpleProductPage,
} from "@/pages/products/contracts";
import type {
  ProductBooleanFilter,
  ProductLifecycleFilter,
  ProductSortDirection,
  ProductSortField,
  ProductTrackingTypeFilter,
} from "@/pages/products/list/types";

type Params = {
  page: SimpleProductPage | undefined;
  canViewPricing: boolean;
  displayPreferences: ProductDisplayPreferences;
  search: string;
  familyFilterId: string;
  lifecycleFilter: ProductLifecycleFilter;
  trackingTypeFilter: ProductTrackingTypeFilter;
  compatibilityFilter: ProductBooleanFilter;
  barcodeFilter: ProductBooleanFilter;
  priceFilter: ProductBooleanFilter;
  lotFilter: ProductBooleanFilter;
  expiryFilter: ProductBooleanFilter;
  sortBy: ProductSortField;
  sortDir: ProductSortDirection;
};

export function deriveProductsListViewState({
  page,
  canViewPricing,
  displayPreferences,
  search,
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
}: Params) {
  const pricingVisible =
    Boolean(
      page?.pricing_visible &&
        canViewPricing
    );
  const visibleColumns =
    displayPreferences.columns;
  const productTableColumnCount =
    2 +
    Number(
      visibleColumns.package
    ) +
    Number(
      visibleColumns.unitsPerPackage
    ) +
    Number(
      visibleColumns.tracking
    ) +
    Number(
      visibleColumns.lifecycle
    ) +
    Number(
      visibleColumns.unitBarcode
    ) +
    Number(
      visibleColumns.packageBarcode
    ) +
    Number(
      pricingVisible &&
        visibleColumns.packagePrice
    ) +
    Number(
      pricingVisible &&
        visibleColumns.unitPrice
    );
  const tableHeaderSpacing =
    displayPreferences.density ===
    "compact"
      ? "px-4 py-2"
      : "px-5 py-3";
  const hasResultCriteria =
    Boolean(
      search ||
        familyFilterId ||
        lifecycleFilter ||
        trackingTypeFilter ||
        compatibilityFilter ||
        barcodeFilter ||
        (
          canViewPricing &&
          priceFilter
        ) ||
        lotFilter ||
        expiryFilter
    );

  const hasProductListControls =
    Boolean(
      familyFilterId ||
        lifecycleFilter ||
        trackingTypeFilter ||
        compatibilityFilter ||
        barcodeFilter ||
        (canViewPricing &&
          priceFilter) ||
        lotFilter ||
        expiryFilter ||
        sortBy !==
          displayPreferences.defaultSort
            .field ||
        sortDir !==
          displayPreferences.defaultSort
            .direction
    );

  return {
    pricingVisible,
    visibleColumns,
    productTableColumnCount,
    tableHeaderSpacing,
    hasProductListControls,
    hasResultCriteria,
  };
}
