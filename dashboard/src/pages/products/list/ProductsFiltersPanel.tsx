import {
  useState,
} from "react";
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
  compatibilityFilter,
  barcodeFilter,
  canViewPricing,
  priceFilter,
  lotFilter,
  expiryFilter,
  sortBy,
  sortDir,
  onFamilySearchInputChange,
  onFamilyFilterChange,
  onRetryFamilyOptions,
  onLifecycleFilterChange,
  onTrackingTypeFilterChange,
  onCompatibilityFilterChange,
  onBarcodeFilterChange,
  onPriceFilterChange,
  onLotFilterChange,
  onExpiryFilterChange,
  onSortByChange,
  onSortDirChange,
}: Props) {
  const { t } = useTranslation();
  const [
    advancedFiltersOpen,
    setAdvancedFiltersOpen,
  ] = useState(false);

  const advancedCriteriaActive =
    Boolean(
      compatibilityFilter ||
        barcodeFilter ||
        priceFilter ||
        lotFilter ||
        expiryFilter,
    );
  const showAdvancedFilters =
    advancedFiltersOpen ||
    advancedCriteriaActive;
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
    <div className="space-y-3">
      <div className="grid gap-x-3 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
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
                    `products.filters.PRODUCT_SORT_OPTIONS.${option.key}`
                  )}
                </option>
              )
            )}
          </select>
        </label>
      </div>

      <button
        type="button"
        aria-expanded={
          showAdvancedFilters
        }
        onClick={() =>
          setAdvancedFiltersOpen(
            (current) =>
              !current
          )
        }
        className="text-[11px] font-black text-slate-500 underline decoration-slate-300 underline-offset-4 transition hover:text-slate-900"
      >
        {t(
          showAdvancedFilters
            ? "products.filters.hideMore"
            : "products.filters.more"
        )}
      </button>

      {showAdvancedFilters ? (
        <div className="grid gap-x-3 gap-y-3 border-t border-slate-100 pt-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          <label className="space-y-1">
            <span className="text-[11px] font-black text-slate-500">
              {t(
                "products.filters.compatibility"
              )}
            </span>
            <select
              value={
                compatibilityFilter
              }
              onChange={(event) =>
                onCompatibilityFilterChange(
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
                  "products.filters.simple"
                )}
              </option>
              <option value="false">
                {t(
                  "products.filters.advanced"
                )}
              </option>
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

          {canViewPricing ? (
            <label className="space-y-1">
              <span className="text-[11px] font-black text-slate-500">
                {t(
                  "products.filters.price"
                )}
              </span>
              <select
                value={priceFilter}
                onChange={(event) =>
                  onPriceFilterChange(
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
                    "products.filters.pricePresent"
                  )}
                </option>
                <option value="false">
                  {t(
                    "products.filters.priceMissing"
                  )}
                </option>
              </select>
            </label>
          ) : null}

          <label className="space-y-1">
            <span className="text-[11px] font-black text-slate-500">
              {t(
                "products.filters.lot"
              )}
            </span>
            <select
              value={lotFilter}
              onChange={(event) =>
                onLotFilterChange(
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
                  "products.filters.tracked"
                )}
              </option>
              <option value="false">
                {t(
                  "products.filters.notTracked"
                )}
              </option>
            </select>
          </label>

          <label className="space-y-1">
            <span className="text-[11px] font-black text-slate-500">
              {t(
                "products.filters.expiry"
              )}
            </span>
            <select
              value={expiryFilter}
              onChange={(event) =>
                onExpiryFilterChange(
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
                  "products.filters.tracked"
                )}
              </option>
              <option value="false">
                {t(
                  "products.filters.notTracked"
                )}
              </option>
            </select>
          </label>
        </div>
      ) : null}
    </div>
  );
}
