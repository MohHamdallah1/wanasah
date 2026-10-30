import { Check, FilterX, ListFilter, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorCode, apiErrorMessage, apiErrorRequestId, apiErrorStatus } from "@/lib/apiErrors";
import {
  parseLiveStockFamilies,
  type LiveStockFamilyOption,
  type LiveStockIndicator,
  type LiveStockStockState,
} from "./contracts";

type Props = {
  locationId: number;
  alertCount: number | null;
  stockState: LiveStockStockState;
  indicators: LiveStockIndicator[];
  familyId: number | null;
  onSearchChange: (search: string) => void;
  onStockStateChange: (value: LiveStockStockState) => void;
  onIndicatorsChange: (value: LiveStockIndicator[]) => void;
  onFamilyChange: (value: number | null) => void;
};

export function LiveStockFilters({
  locationId,
  alertCount,
  stockState,
  indicators,
  familyId,
  onSearchChange,
  onStockStateChange,
  onIndicatorsChange,
  onFamilyChange,
}: Props) {
  const authFetch = useAuthFetch();
  const { t, i18n } = useTranslation();
  const [searchInput, setSearchInput] = useState("");
  const [familySearch, setFamilySearch] = useState("");
  const [families, setFamilies] = useState<LiveStockFamilyOption[]>([]);
  const [familyLoading, setFamilyLoading] = useState(false);
  const [familyError, setFamilyError] = useState<string | null>(null);
  const [familyRetryKey, setFamilyRetryKey] = useState(0);
  const [selectedFamilyOption, setSelectedFamilyOption] = useState<LiveStockFamilyOption | null>(null);
  const emittedSearch = useRef("");

  useEffect(() => {
    setSearchInput("");
    setFamilySearch("");
    setFamilies([]);
    setSelectedFamilyOption(null);
    emittedSearch.current = "";
  }, [locationId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      const next = clean.length >= 2 ? clean : "";
      if (next === emittedSearch.current) return;
      emittedSearch.current = next;
      onSearchChange(next);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [onSearchChange, searchInput]);

  useEffect(() => {
    if (familyId === null) setSelectedFamilyOption(null);
  }, [familyId]);

  useEffect(() => {
    if (alertCount === 0 && stockState === "low_stock") {
      onStockStateChange("all");
    }
  }, [alertCount, onStockStateChange, stockState]);

  useEffect(() => {
    const clean = familySearch.trim();
    setFamilies([]);
    setFamilyError(null);
    if (clean.length === 1) {
      setFamilyLoading(false);
      return;
    }

    const controller = new AbortController();
    setFamilyLoading(true);
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({
        location_id: String(locationId),
        limit: "50",
      });
      if (clean.length >= 2) params.set("search", clean);
      void authFetch(`/warehouse/inventory/families?${params.toString()}`, {
        signal: controller.signal,
      })
        .then((raw) => {
          if (!controller.signal.aborted) {
            setFamilies(parseLiveStockFamilies(raw).items);
          }
        })
        .catch((error: unknown) => {
          if (
            !controller.signal.aborted &&
            !(error instanceof Error && error.name === "AbortError")
          ) {
            const fallback = t("inventoryLive.errors.familyLoadFailed");
            // Raw browser/network errors have no stable localized reason.
            // Preserve structured server reasons, codes and request references.
            setFamilyError(
              error instanceof Error &&
              !apiErrorCode(error) &&
              !apiErrorRequestId(error) &&
              apiErrorStatus(error) === undefined
                ? fallback
                : apiErrorMessage(error, fallback),
            );
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setFamilyLoading(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [authFetch, familySearch, familyRetryKey, locationId, t]);

  const activeFilterCount = (stockState !== "all" ? 1 : 0) + indicators.length;
  const selectedFamily =
    familyId === null
      ? null
      : families.find((item) => item.id === familyId) ??
        (selectedFamilyOption?.id === familyId ? selectedFamilyOption : null);

  const toggleIndicator = (value: LiveStockIndicator) => {
    onIndicatorsChange(
      indicators.includes(value)
        ? indicators.filter((item) => item !== value)
        : [...indicators, value],
    );
  };

  return (
    <div className="live-stock-toolbar-search-group flex min-w-0 flex-1 flex-wrap items-center gap-2">
      <div className="live-stock-search relative min-w-[180px] flex-1">
        <Search className="absolute start-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" aria-hidden="true" />
        <input
          type="search"
          aria-label={t("inventoryLive.searchPlaceholder")}
          placeholder={t("inventoryLive.searchPlaceholder")}
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          maxLength={100}
          className="w-full rounded-xl border border-slate-200 bg-white py-2 pe-4 ps-9 text-xs shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        />
      </div>

      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={`live-stock-filter-button ${activeFilterCount ? "live-stock-filter-button--active" : ""}`}
            aria-label={t("inventoryLive.filterButton")}
          >
            <ListFilter className="h-4 w-4" aria-hidden="true" />
            <span>{t("inventoryLive.filterButton")}</span>
            {activeFilterCount > 0 ? (
              <span className="live-stock-filter-count tabular-nums">{activeFilterCount}</span>
            ) : null}
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" sideOffset={8} dir={i18n.dir()} className="live-stock-filter-popover live-stock-filter-popover--compact">
          <div className="live-stock-filter-choice-grid live-stock-filter-choice-grid--compact">
            {(
              [
                ["all", "filterAll"],
                ["on_hand", "filterOnHand"],
                ["sellable", "filterSellable"],
                ["out_of_stock", "filterOutOfStock"],
                ["low_stock", "filterLowStock"],
              ] as const
            ).map(([value, key]) => (
              <button
                key={value}
                type="button"
                className="live-stock-filter-option live-stock-filter-option--compact"
                data-active={stockState === value}
                aria-pressed={stockState === value}
                disabled={value === "low_stock" && alertCount === 0}
                onClick={() => onStockStateChange(value)}
              >
                <span>{t(`inventoryLive.${key}`)}</span>
                {stockState === value ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : null}
              </button>
            ))}
          </div>
          <div className="live-stock-filter-chip-grid live-stock-filter-chip-grid--compact">
            {(
              [
                ["reserved", "indicatorReserved"],
                ["unavailable", "indicatorUnavailable"],
                ["damaged", "indicatorDamaged"],
                ["recalled", "indicatorRecalled"],
                ["vehicle", "indicatorVehicle"],
                ["minimum_unset", "indicatorMinimumUnset"],
              ] as const
            ).map(([value, key]) => (
              <button
                key={value}
                type="button"
                className="live-stock-filter-chip"
                data-active={indicators.includes(value)}
                aria-pressed={indicators.includes(value)}
                onClick={() => toggleIndicator(value)}
              >
                {indicators.includes(value) ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : null}
                {t(`inventoryLive.${key}`)}
              </button>
            ))}
          </div>
          {activeFilterCount > 0 ? (
            <button
              type="button"
              className="live-stock-filter-reset live-stock-filter-reset--compact"
              onClick={() => {
                onStockStateChange("all");
                onIndicatorsChange([]);
              }}
            >
              <FilterX className="h-3.5 w-3.5" aria-hidden="true" />
              {t("inventoryLive.filterReset")}
            </button>
          ) : null}
        </PopoverContent>
      </Popover>

      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={`live-stock-family-button ${familyId !== null ? "live-stock-family-button--active" : ""}`}
            aria-label={selectedFamily
              ? t("inventoryLive.selectedFamilyLabel", { name: selectedFamily.name })
              : t("inventoryLive.familyTitle")
            }
          >
            <span className="live-stock-family-button-label">
              {selectedFamily?.name ?? t("inventoryLive.familyTitle")}
            </span>
            {familyId !== null ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : null}
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" sideOffset={8} dir={i18n.dir()} className="live-stock-family-popover">
          <div className="live-stock-family-search-row">
            <input
              type="search"
              value={familySearch}
              onChange={(event) => setFamilySearch(event.target.value)}
              placeholder={t("inventoryLive.familySearch")}
              aria-label={t("inventoryLive.familySearch")}
              className="live-stock-family-search"
            />
            {familyId !== null ? (
              <button
                type="button"
                className="live-stock-family-clear"
                onClick={() => {
                  setSelectedFamilyOption(null);
                  onFamilyChange(null);
                }}
                aria-label={t("inventoryLive.clearFamily")}
              >
                <FilterX className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            ) : null}
          </div>
          <div className="live-stock-family-list custom-scrollbar">
            {familyLoading ? (
              <div className="live-stock-family-empty" role="status">{t("common.loading")}</div>
            ) : familyError ? (
              <div className="live-stock-family-empty" role="alert">
                <p>{familyError}</p>
                <button
                  type="button"
                  className="live-stock-family-option"
                  onClick={() => setFamilyRetryKey((value) => value + 1)}
                >
                  {t("common.retry")}
                </button>
              </div>
            ) : familySearch.trim().length === 1 ? null : families.length === 0 ? (
              <div className="live-stock-family-empty">{t("inventoryLive.familyNoMatches")}</div>
            ) : (
              families.map((family) => (
                <button
                  key={family.id}
                  type="button"
                  className="live-stock-family-option"
                  data-active={familyId === family.id}
                  aria-pressed={familyId === family.id}
                  onClick={() => {
                    setSelectedFamilyOption(family);
                    onFamilyChange(family.id);
                  }}
                >
                  <span>
                    <strong>{family.name}</strong>
                    <small>{family.code}</small>
                  </span>
                  {familyId === family.id ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : null}
                </button>
              ))
            )}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
