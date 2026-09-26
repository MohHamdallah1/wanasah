import {
  ArrowDownAZ,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ProductDisplaySortDirection,
  ProductDisplaySortField,
} from "@/lib/productDisplayPreferences";
import type {
  ProductBooleanFilter,
  ProductLifecycleFilter,
  ProductSortDirection,
  ProductSortField,
  ProductTrackingTypeFilter,
} from "@/pages/products/list/types";

type Props = {
  familyFilterId: string;
  familyFilterName: string;
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
  defaultSortBy: ProductDisplaySortField;
  defaultSortDir: ProductDisplaySortDirection;
  onFamilyFilterChange: (value: string) => void;
  onLifecycleFilterChange: (value: ProductLifecycleFilter) => void;
  onTrackingTypeFilterChange: (value: ProductTrackingTypeFilter) => void;
  onCompatibilityFilterChange: (value: ProductBooleanFilter) => void;
  onBarcodeFilterChange: (value: ProductBooleanFilter) => void;
  onPriceFilterChange: (value: ProductBooleanFilter) => void;
  onLotFilterChange: (value: ProductBooleanFilter) => void;
  onExpiryFilterChange: (value: ProductBooleanFilter) => void;
  onSortByChange: (value: ProductSortField) => void;
  onSortDirChange: (value: ProductSortDirection) => void;
  onClearControls: () => void;
};

type ChipProps = {
  label: string;
  onRemove: () => void;
};

function FilterChip({
  label,
  onRemove,
}: ChipProps) {
  const { t } = useTranslation();

  return (
    <span className="inline-flex min-h-7 max-w-full items-center gap-1.5 rounded-lg bg-slate-100 px-2 py-1 text-[10px] font-black text-slate-700 ring-1 ring-inset ring-slate-200">
      <span className="min-w-0 break-words">
        {label}
      </span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={t(
          "products.filters.remove",
          { filter: label },
        )}
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-slate-400 transition hover:bg-white hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

const booleanLabelKey = (
  value: ProductBooleanFilter,
  trueKey: string,
  falseKey: string,
) =>
  value === "true"
    ? trueKey
    : falseKey;

export function ProductsActiveFilters({
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
  defaultSortBy,
  defaultSortDir,
  onFamilyFilterChange,
  onLifecycleFilterChange,
  onTrackingTypeFilterChange,
  onCompatibilityFilterChange,
  onBarcodeFilterChange,
  onPriceFilterChange,
  onLotFilterChange,
  onExpiryFilterChange,
  onSortByChange,
  onSortDirChange,
  onClearControls,
}: Props) {
  const { t } = useTranslation();

  const hasSortOverride =
    sortBy !== defaultSortBy ||
    sortDir !== defaultSortDir;

  const hasFilters = Boolean(
    familyFilterId ||
      lifecycleFilter ||
      trackingTypeFilter ||
      compatibilityFilter ||
      barcodeFilter ||
      (canViewPricing && priceFilter) ||
      lotFilter ||
      expiryFilter ||
      hasSortOverride,
  );

  if (!hasFilters) {
    return null;
  }

  const label = (
    key: string,
    value: string,
  ) => `${t(key)}: ${value}`;

  return (
    <div
      className="mt-2 flex flex-wrap items-center gap-1.5"
      aria-label={t(
        "products.filters.active",
      )}
    >
      {familyFilterId ? (
        <FilterChip
          label={label(
            "products.filters.family",
            familyFilterName ||
              familyFilterId,
          )}
          onRemove={() =>
            onFamilyFilterChange("")
          }
        />
      ) : null}

      {lifecycleFilter ? (
        <FilterChip
          label={label(
            "products.filters.lifecycle",
            t(
              `products.details.lifecycleModes.${lifecycleFilter}`,
            ),
          )}
          onRemove={() =>
            onLifecycleFilterChange("")
          }
        />
      ) : null}

      {trackingTypeFilter ? (
        <FilterChip
          label={label(
            "products.filters.trackingType",
            t(
              `products.filters.trackingTypes.${trackingTypeFilter}`,
            ),
          )}
          onRemove={() =>
            onTrackingTypeFilterChange("")
          }
        />
      ) : null}

      {compatibilityFilter ? (
        <FilterChip
          label={label(
            "products.filters.compatibility",
            t(
              compatibilityFilter === "true"
                ? "products.filters.simple"
                : "products.filters.advanced",
            ),
          )}
          onRemove={() =>
            onCompatibilityFilterChange("")
          }
        />
      ) : null}

      {barcodeFilter ? (
        <FilterChip
          label={label(
            "products.filters.barcode",
            t(
              booleanLabelKey(
                barcodeFilter,
                "products.filters.present",
                "products.filters.missing",
              ),
            ),
          )}
          onRemove={() =>
            onBarcodeFilterChange("")
          }
        />
      ) : null}

      {canViewPricing &&
      priceFilter ? (
        <FilterChip
          label={label(
            "products.filters.price",
            t(
              booleanLabelKey(
                priceFilter,
                "products.filters.present",
                "products.filters.missing",
              ),
            ),
          )}
          onRemove={() =>
            onPriceFilterChange("")
          }
        />
      ) : null}

      {lotFilter ? (
        <FilterChip
          label={label(
            "products.filters.lot",
            t(
              booleanLabelKey(
                lotFilter,
                "products.filters.tracked",
                "products.filters.notTracked",
              ),
            ),
          )}
          onRemove={() =>
            onLotFilterChange("")
          }
        />
      ) : null}

      {expiryFilter ? (
        <FilterChip
          label={label(
            "products.filters.expiry",
            t(
              booleanLabelKey(
                expiryFilter,
                "products.filters.tracked",
                "products.filters.notTracked",
              ),
            ),
          )}
          onRemove={() =>
            onExpiryFilterChange("")
          }
        />
      ) : null}

      {hasSortOverride ? (
        <FilterChip
          label={label(
            "products.filters.sortBy",
            `${t(
              `products.filters.sortFields.${sortBy}`,
            )} · ${t(
              sortDir === "asc"
                ? "products.filters.ascending"
                : "products.filters.descending",
            )}`,
          )}
          onRemove={() => {
            onSortByChange(
              defaultSortBy,
            );
            onSortDirChange(
              defaultSortDir,
            );
          }}
        />
      ) : null}

      <button
        type="button"
        onClick={onClearControls}
        className="inline-flex min-h-7 items-center gap-1.5 rounded-lg px-2 text-[10px] font-black text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
      >
        <ArrowDownAZ className="h-3.5 w-3.5" />
        {t(
          "products.filters.clear",
        )}
      </button>
    </div>
  );
}
