import { useTranslation } from "react-i18next";

import type {
  ProductFamily,
} from "@/pages/products/contracts";
import { ProductFamilyCombobox } from "@/pages/products/family/ProductFamilyCombobox";
import { PRODUCT_SORT_OPTIONS } from "@/pages/products/list/productSortOptions";
import type {
  ProductBooleanFilter,
  ProductLifecycleFilter,
  ProductSortDirection,
  ProductSortField,
  ProductTrackingTypeFilter,
} from "@/pages/products/list/types";

type Props = {
  familyFilterSearchInput: string;
  familyFilterId: string;
  familyFilterName: string;
  familyFilterOptions: ProductFamily[];
  familyOptionsError: boolean;
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
  onFamilySearchInputChange: (
    value: string,
  ) => void;
  onFamilyFilterChange: (
    value: string,
  ) => void;
  onRetryFamilyOptions: () => void;
  onLifecycleFilterChange: (
    value: ProductLifecycleFilter,
  ) => void;
  onTrackingTypeFilterChange: (
    value: ProductTrackingTypeFilter,
  ) => void;
  onCompatibilityFilterChange: (
    value: ProductBooleanFilter,
  ) => void;
  onBarcodeFilterChange: (
    value: ProductBooleanFilter,
  ) => void;
  onPriceFilterChange: (
    value: ProductBooleanFilter,
  ) => void;
  onLotFilterChange: (
    value: ProductBooleanFilter,
  ) => void;
  onExpiryFilterChange: (
    value: ProductBooleanFilter,
  ) => void;
  onSortByChange: (
    value: ProductSortField,
  ) => void;
  onSortDirChange: (
    value: ProductSortDirection,
  ) => void;
};

const selectClassName =
  "h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100";

export function ProductsFiltersPanel({
  familyFilterSearchInput,
  familyFilterId,
  familyFilterName,
  familyFilterOptions,
  familyOptionsError,
  lifecycleFilter,
  trackingTypeFilter,
  barcodeFilter,
  sortBy,
  sortDir,
  onFamilySearchInputChange,
  onFamilyFilterChange,
  onRetryFamilyOptions,
  onLifecycleFilterChange,
  onTrackingTypeFilterChange,
  onBarcodeFilterChange,
  onSortByChange,
  onSortDirChange,
}: Props) {
  const { t } = useTranslation();
  const sortValue =
    `${sortBy}:${sortDir}`;

  const applySort = (
    value: string,
  ) => {
    const option =
      PRODUCT_SORT_OPTIONS.find(
        (item) =>
          `${item.field}:${item.direction}` ===
          value,
      );
    if (!option) {
      return;
    }
    onSortByChange(
      option.field,
    );
    onSortDirChange(
      option.direction,
    );
  };

  return (
    <div className="grid gap-x-3 gap-y-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      <div className="space-y-1">
        <span className="text-[11px] font-black text-slate-500">
          {t(
            "products.filters.family"
          )}
        </span>

        <ProductFamilyCombobox
          selectedName={
            familyFilterId
              ? familyFilterName
              : ""
          }
          searchValue={
            familyFilterSearchInput
          }
          options={
            familyFilterOptions
          }
          placeholder={t(
            "products.filters.familySearch"
          )}
          clearLabel={t(
            "products.quickCreate.clearFamilySearch"
          )}
          emptyLabel={t(
            "products.noMatchingFamilies"
          )}
          error={
            familyOptionsError
          }
          errorLabel={t(
            "products.filters.familyLoadFailed"
          )}
          retryLabel={t(
            "common.retry"
          )}
          onRetry={
            onRetryFamilyOptions
          }
          allOptionLabel={t(
            "products.filters.all"
          )}
          onSelectAll={() => {
            onFamilyFilterChange(
              ""
            );
            onFamilySearchInputChange(
              ""
            );
          }}
          onSearchChange={(
            value
          ) => {
            if (
              familyFilterId
            ) {
              onFamilyFilterChange(
                ""
              );
            }
            onFamilySearchInputChange(
              value
            );
          }}
          onSelect={(
            family
          ) => {
            onFamilyFilterChange(
              String(
                family.id
              )
            );
            onFamilySearchInputChange(
              ""
            );
          }}
          onClear={() => {
            onFamilyFilterChange(
              ""
            );
            onFamilySearchInputChange(
              ""
            );
          }}
          formatOptionMeta={(
            family
          ) =>
            t(
              "products.variantCount",
              {
                count:
                  family.variant_count,
              }
            )
          }
          inputClassName="h-9 w-full rounded-lg border border-slate-200 bg-white pe-9 ps-2.5 text-xs font-bold outline-none transition placeholder:font-normal placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
        />
      </div>

      <label className="space-y-1">
        <span className="text-[11px] font-black text-slate-500">
          {t(
            "products.filters.lifecycle"
          )}
        </span>
        <select
          value={lifecycleFilter}
          onChange={(event) =>
            onLifecycleFilterChange(
              event.target
                .value as ProductLifecycleFilter
            )
          }
          className={
            selectClassName
          }
        >
          <option value="">
            {t(
              "products.filters.all"
            )}
          </option>
          <option value="ACTIVE">
            {t(
              "products.details.lifecycleModes.ACTIVE"
            )}
          </option>
          <option value="RETIRING">
            {t(
              "products.details.lifecycleModes.RETIRING"
            )}
          </option>
          <option value="ARCHIVED">
            {t(
              "products.details.lifecycleModes.ARCHIVED"
            )}
          </option>
        </select>
      </label>

      <label className="space-y-1">
        <span className="text-[11px] font-black text-slate-500">
          {t(
            "products.filters.trackingType"
          )}
        </span>
        <select
          value={
            trackingTypeFilter
          }
          onChange={(event) =>
            onTrackingTypeFilterChange(
              event.target
                .value as ProductTrackingTypeFilter
            )
          }
          className={
            selectClassName
          }
        >
          <option value="">
            {t(
              "products.filters.all"
            )}
          </option>
          {(
            [
              "NONE",
              "LOT",
              "EXPIRY",
              "LOT_EXPIRY",
            ] as const
          ).map((value) => (
            <option
              key={value}
              value={value}
            >
              {t(
                `products.filters.trackingTypes.${value}`
              )}
            </option>
          ))}
        </select>
      </label>

      <label className="space-y-1">
        <span className="text-[11px] font-black text-slate-500">
          {t(
            "products.filters.barcode"
          )}
        </span>
        <select
          value={barcodeFilter}
          onChange={(event) =>
            onBarcodeFilterChange(
              event.target
                .value as ProductBooleanFilter
            )
          }
          className={
            selectClassName
          }
        >
          <option value="">
            {t(
              "products.filters.all"
            )}
          </option>
          <option value="true">
            {t(
              "products.filters.barcodePresent"
            )}
          </option>
          <option value="false">
            {t(
              "products.filters.barcodeMissing"
            )}
          </option>
        </select>
      </label>

      <label className="space-y-1">
        <span className="text-[11px] font-black text-slate-500">
          {t(
            "products.filters.sort"
          )}
        </span>
        <select
          value={sortValue}
          onChange={(event) =>
            applySort(
              event.target.value
            )
          }
          className={
            selectClassName
          }
        >
          {PRODUCT_SORT_OPTIONS.map(
            (option) => (
              <option
                key={
                  option.key
                }
                value={`${option.field}:${option.direction}`}
              >
                {t(
                  `products.filters.sortOptions.${option.key}`
                )}
              </option>
            )
          )}
        </select>
      </label>
    </div>
  );
}
