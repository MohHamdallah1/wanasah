import { useTranslation } from "react-i18next";

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

  return (
    <div className="mt-3 grid gap-3 rounded-2xl border border-slate-100 bg-slate-50/70 p-3 sm:grid-cols-2 xl:grid-cols-4">
      <label className="space-y-1">
        <span className="text-[11px] font-black text-slate-500">
          {t(
            "products.filters.family"
          )}
        </span>
        <input
          type="search"
          value={
            familyFilterSearchInput
          }
          maxLength={100}
          onChange={(event) =>
            onFamilySearchInputChange(
              event.target.value
            )
          }
          placeholder={t(
            "products.filters.familySearch"
          )}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold outline-none focus:border-slate-400"
        />
        <select
          value={familyFilterId}
          onChange={(event) =>
            onFamilyFilterChange(
              event.target.value
            )
          }
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold outline-none focus:border-slate-400"
        >
          <option value="">
            {t(
              "products.filters.all"
            )}
          </option>
          {familyFilterId &&
          !familyFilterOptions.some(
            (item) =>
              String(item.id) ===
              familyFilterId
          ) ? (
            <option
              value={
                familyFilterId
              }
            >
              {familyFilterName ||
                familyFilterId}
            </option>
          ) : null}
          {familyFilterOptions.map(
            (
              family: ProductFamily
            ) => (
              <option
                key={family.id}
                value={String(
                  family.id
                )}
              >
                {family.name}
              </option>
            )
          )}
        </select>
        {familyOptionsError ? (
          <button
            type="button"
            onClick={
              onRetryFamilyOptions
            }
            className="text-[11px] font-black text-rose-700"
          >
            {t(
              "products.filters.familyLoadFailed"
            )}
          </button>
        ) : null}
      </label>

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
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
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
        </select>
      </label>

      <label className="space-y-1">
        <span className="text-[11px] font-black text-slate-500">
          {t(
            "products.filters.trackingType"
          )}
        </span>
        <select
          value={trackingTypeFilter}
          onChange={(event) =>
            onTrackingTypeFilterChange(
              event.target
                .value as ProductTrackingTypeFilter
            )
          }
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
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
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
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
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
        >
          <option value="">
            {t(
              "products.filters.all"
            )}
          </option>
          <option value="true">
            {t(
              "products.filters.present"
            )}
          </option>
          <option value="false">
            {t(
              "products.filters.missing"
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
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
          >
            <option value="">
              {t(
                "products.filters.all"
              )}
            </option>
            <option value="true">
              {t(
                "products.filters.present"
              )}
            </option>
            <option value="false">
              {t(
                "products.filters.missing"
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
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
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
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
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
            "products.filters.sortBy"
          )}
        </span>
        <select
          value={sortBy}
          onChange={(event) =>
            onSortByChange(
              event.target
                .value as ProductSortField
            )
          }
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
        >
          {(
            [
              "id",
              "name",
              "family",
              "sku",
              "lifecycle",
            ] as const
          ).map((value) => (
            <option
              key={value}
              value={value}
            >
              {t(
                `products.filters.sortFields.${value}`
              )}
            </option>
          ))}
        </select>
      </label>

      <label className="space-y-1">
        <span className="text-[11px] font-black text-slate-500">
          {t(
            "products.filters.sortDirection"
          )}
        </span>
        <select
          value={sortDir}
          onChange={(event) =>
            onSortDirChange(
              event.target
                .value as ProductSortDirection
            )
          }
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-bold"
        >
          <option value="asc">
            {t(
              "products.filters.ascending"
            )}
          </option>
          <option value="desc">
            {t(
              "products.filters.descending"
            )}
          </option>
        </select>
      </label>
    </div>
  );
}
