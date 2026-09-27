import {
  useRef,
  useState,
} from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";

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
  const [
    familyPickerOpen,
    setFamilyPickerOpen,
  ] = useState(false);
  const familyInputRef =
    useRef<HTMLInputElement | null>(
      null
    );

  const familyInputValue =
    familyPickerOpen
      ? familyFilterSearchInput
      : familyFilterName ||
        familyFilterSearchInput;

  const clearFamily = () => {
    onFamilyFilterChange("");
    onFamilySearchInputChange("");
    setFamilyPickerOpen(true);
    queueMicrotask(() =>
      familyInputRef.current?.focus()
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

        <Popover
          open={familyPickerOpen}
          onOpenChange={
            setFamilyPickerOpen
          }
        >
          <div className="relative">
            <PopoverAnchor asChild>
              <input
                ref={familyInputRef}
                type="text"
                value={familyInputValue}
                maxLength={100}
                onFocus={() => {
                  if (
                    familyFilterId &&
                    !familyFilterSearchInput
                  ) {
                    onFamilySearchInputChange(
                      familyFilterName
                    );
                  }
                  setFamilyPickerOpen(
                    true
                  );
                }}
                onChange={(event) => {
                  const value =
                    event.target.value;
                  if (familyFilterId) {
                    onFamilyFilterChange(
                      ""
                    );
                  }
                  onFamilySearchInputChange(
                    value
                  );
                  setFamilyPickerOpen(
                    true
                  );
                }}
                onKeyDown={(event) => {
                  if (
                    event.key ===
                    "ArrowDown"
                  ) {
                    setFamilyPickerOpen(
                      true
                    );
                  }
                }}
                placeholder={t(
                  "products.filters.familySearch"
                )}
                aria-expanded={
                  familyPickerOpen
                }
                className="h-9 w-full rounded-lg border border-slate-200 bg-white pe-9 ps-2.5 text-xs font-bold outline-none transition placeholder:font-normal placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
              />
            </PopoverAnchor>

            {familyInputValue ? (
              <button
                type="button"
                onClick={clearFamily}
                aria-label={t(
                  "products.quickCreate.clearFamilySearch"
                )}
                className="absolute end-1.5 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>

          <PopoverContent
            side="bottom"
            align="start"
            sideOffset={5}
            avoidCollisions={false}
            onOpenAutoFocus={(event) =>
              event.preventDefault()
            }
            onCloseAutoFocus={(event) =>
              event.preventDefault()
            }
            onInteractOutside={(event) => {
              if (
                event.target ===
                familyInputRef.current
              ) {
                event.preventDefault();
              }
            }}
            className="z-[70] w-[var(--radix-popover-anchor-width)] overflow-hidden rounded-xl border-slate-200 bg-white p-1.5 shadow-xl"
          >
            <Command shouldFilter={false}>
              <CommandList className="max-h-64">
                <CommandGroup>
                  <CommandItem
                    value="__all__"
                    onSelect={() => {
                      onFamilyFilterChange(
                        ""
                      );
                      onFamilySearchInputChange(
                        ""
                      );
                      setFamilyPickerOpen(
                        false
                      );
                    }}
                    className="rounded-lg px-3 py-2.5 text-start font-bold"
                  >
                    {t(
                      "products.filters.all"
                    )}
                  </CommandItem>

                  {familyFilterOptions.map(
                    (
                      family: ProductFamily
                    ) => (
                      <CommandItem
                        key={family.id}
                        value={family.name}
                        onSelect={() => {
                          onFamilyFilterChange(
                            String(
                              family.id
                            )
                          );
                          onFamilySearchInputChange(
                            ""
                          );
                          setFamilyPickerOpen(
                            false
                          );
                        }}
                        className="gap-3 rounded-lg px-3 py-2.5 text-start"
                      >
                        <span className="min-w-0 flex-1 truncate font-bold">
                          {family.name}
                        </span>
                        <span className="shrink-0 text-[10px] font-semibold text-slate-400">
                          {t(
                            "products.variantCount",
                            {
                              count:
                                family.variant_count,
                            }
                          )}
                        </span>
                      </CommandItem>
                    )
                  )}
                </CommandGroup>

                {!familyOptionsError &&
                familyFilterOptions.length ===
                  0 &&
                familyFilterSearchInput ? (
                  <div className="px-3 py-4 text-center text-[11px] font-bold text-slate-400">
                    {t(
                      "products.noMatchingFamilies"
                    )}
                  </div>
                ) : null}

                {familyOptionsError ? (
                  <div className="px-3 py-4 text-center">
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
                  </div>
                ) : null}
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
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
          className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
          value={trackingTypeFilter}
          onChange={(event) =>
            onTrackingTypeFilterChange(
              event.target
                .value as ProductTrackingTypeFilter
            )
          }
          className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
          className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
          className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
            className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
          className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
          className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
          className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
          className="h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
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
