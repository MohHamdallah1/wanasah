import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  AlertTriangle,
  Check,
  FilterX,
  Info,
  ListFilter,
  Pencil,
  RefreshCcw,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { apiErrorMessage } from "@/lib/apiErrors";
import { formatMoneyDisplay, formatMoneyExact } from "@/lib/money";
import {
  parseLiveStockFamilies,
  type LiveStockFamilyOption,
  type LiveStockIndicator,
  type LiveStockStockState,
  type WarehouseProduct,
} from "./liveStock/contracts";
import {
  compareQuantity,
  convertBaseQuantityToUom,
  formatCommercialQuantity,
} from "./quantity";

interface Props {
  locationId: number;
  locations: Array<{ id: number; name: string }>;
  stockTotal: number | null;
  lastSync: Date | null;
  isAuditLocked: boolean;
  products: WarehouseProduct[];
  loading: boolean;
  alertCount: number | null;
  matchingTotal: number | null;
  hasMore: boolean;
  stockState: LiveStockStockState;
  indicators: LiveStockIndicator[];
  familyId: number | null;
  canManageMinimum: boolean;
  onLocationChange: (value: string) => void;
  onRefresh: () => void;
  onSearchChange: (search: string) => void;
  onStockStateChange: (value: LiveStockStockState) => void;
  onIndicatorsChange: (value: LiveStockIndicator[]) => void;
  onFamilyChange: (value: number | null) => void;
  onLoadMore: () => void;
}

type MinimumStockEditor = {
  product: WarehouseProduct;
  uomId: number;
  uomCode: string;
  value: string;
  requestId: string;
};

function HeaderHelp({
  text,
}: {
  text: string;
}) {
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button type="button" className="live-header-help" aria-label={text}>
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content sideOffset={8} collisionPadding={16} className="live-help-content">
            {text}
            <Tooltip.Arrow className="fill-slate-900" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

export function Tab1LiveStock({
  locationId,
  locations,
  stockTotal,
  lastSync,
  isAuditLocked,
  products,
  loading,
  alertCount,
  hasMore,
  stockState,
  indicators,
  familyId,
  canManageMinimum,
  onLocationChange,
  onRefresh,
  onSearchChange,
  onStockStateChange,
  onIndicatorsChange,
  onFamilyChange,
  onLoadMore,
}: Props) {
  const authFetch = useAuthFetch();
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage || i18n.language || "en";

  const [searchInput, setSearchInput] = useState("");
  const [minimumEditor, setMinimumEditor] =
    useState<MinimumStockEditor | null>(null);
  const [savingMinimum, setSavingMinimum] = useState(false);
  const [familySearch, setFamilySearch] = useState("");
  const [familyOptions, setFamilyOptions] =
    useState<LiveStockFamilyOption[]>([]);
  const [familyLoading, setFamilyLoading] = useState(false);

  const tableScrollRef = useRef<HTMLDivElement | null>(null);
  const loadMoreSentinelRef = useRef<HTMLDivElement | null>(null);
  const emittedSearchRef = useRef("");

  useEffect(() => {
    setSearchInput("");
    setMinimumEditor(null);
    setSavingMinimum(false);
    setFamilySearch("");
    setFamilyOptions([]);
    setFamilyLoading(false);
    emittedSearchRef.current = "";

    return () => {
          };
  }, [locationId]);

  useEffect(() => {
    const handler = window.setTimeout(() => {
      const clean = searchInput.trim();
      const nextSearch = clean.length >= 2 ? clean : "";
      if (nextSearch === emittedSearchRef.current) return;
      emittedSearchRef.current = nextSearch;
      onSearchChange(nextSearch);
    }, 300);
    return () => window.clearTimeout(handler);
  }, [searchInput, onSearchChange]);

  useEffect(() => {
    if (alertCount === 0 && stockState === "low_stock") {
      onStockStateChange("all");
    }
  }, [alertCount, onStockStateChange, stockState]);

  useEffect(() => {
    const clean = familySearch.trim();
    if (clean.length === 1) {
      setFamilyOptions([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setFamilyLoading(true);
      const params = new URLSearchParams({
        location_id: String(locationId),
        limit: "50",
      });
      if (clean.length >= 2) params.set("search", clean);

      void authFetch(
        `/warehouse/inventory/families?${params.toString()}`,
        { signal: controller.signal },
      )
        .then((raw) => {
          if (!controller.signal.aborted) {
            setFamilyOptions(parseLiveStockFamilies(raw).items);
          }
        })
        .catch((error: unknown) => {
          if (
            !controller.signal.aborted &&
            !(error instanceof Error && error.name === "AbortError")
          ) {
            setFamilyOptions([]);
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
  }, [authFetch, familySearch, locationId]);

  useEffect(() => {
    const root = tableScrollRef.current;
    const target = loadMoreSentinelRef.current;
    if (!root || !target) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting) && hasMore && !loading) {
          onLoadMore();
        }
      },
      {
        root,
        rootMargin: "0px 0px 320px 0px",
        threshold: 0.01,
      },
    );

    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loading, onLoadMore]);

  const openMinimumEditor = useCallback(
    (product: WarehouseProduct) => {
      const converted = convertBaseQuantityToUom(
        product.minimum_quantity,
        product.display_factor_to_base,
      );
      const useDisplayUom =
        product.display_uom_id !== product.base_uom_id &&
        converted !== null;

      setMinimumEditor({
        product,
        uomId: useDisplayUom
          ? product.display_uom_id
          : product.base_uom_id,
        uomCode: useDisplayUom
          ? product.display_uom_code
          : product.base_uom_code,
        value: useDisplayUom
          ? converted
          : product.minimum_quantity,
        requestId: crypto.randomUUID(),
      });
    },
    [],
  );

  const saveMinimumStock = useCallback(async () => {
    if (!minimumEditor || savingMinimum) return;

    const value = minimumEditor.value.trim();
    if (!/^\d+(?:\.\d{1,6})?$/.test(value)) {
      toast.error(t("inventoryLive.minimumStockInvalid"));
      return;
    }

    setSavingMinimum(true);
    try {
      await authFetch(
        `/warehouse/inventory/${encodeURIComponent(
          String(minimumEditor.product.id),
        )}/minimum-stock`,
        {
          method: "PUT",
          body: JSON.stringify({
            request_id: minimumEditor.requestId,
            location_id: locationId,
            uom_id: minimumEditor.uomId,
            minimum_quantity: value,
            expected_minimum_quantity:
              minimumEditor.product.minimum_quantity,
          }),
        },
      );

      toast.success(t("inventoryLive.minimumStockSaved"));
      setMinimumEditor(null);
      onRefresh();
    } catch (error: unknown) {
      toast.error(
        apiErrorMessage(
          error,
          t("inventoryLive.minimumStockSaveFailed"),
        ),
      );
    } finally {
      setSavingMinimum(false);
    }
  }, [
    authFetch,
    locationId,
    minimumEditor,
    onRefresh,
    savingMinimum,
    t,
  ]);

  const activeFilterCount =
    (stockState !== "all" ? 1 : 0) + indicators.length;

  const toggleIndicator = (indicator: LiveStockIndicator) => {
    onIndicatorsChange(
      indicators.includes(indicator)
        ? indicators.filter((item) => item !== indicator)
        : [...indicators, indicator],
    );
  };

  const clearFilters = () => {
    onStockStateChange("all");
    onIndicatorsChange([]);
  };

  const selectedFamily =
    familyId === null
      ? null
      : familyOptions.find((family) => family.id === familyId) ?? null;

  return (
    <div className="inventory-view inventory-live-stock flex min-h-0 flex-1 flex-col gap-3">
      <div className="glass-card inventory-data-panel flex min-h-0 flex-1 flex-col overflow-hidden pt-0">
        <div className="live-stock-toolbar">
          <div className="live-stock-toolbar-search-group">
            <div className="live-stock-search">
              <Search className="absolute start-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                aria-label={t("inventoryLive.searchPlaceholder")}
                placeholder={t("inventoryLive.searchPlaceholder")}
                value={searchInput}
                onChange={(event) =>
                  setSearchInput(event.target.value)
                }
                maxLength={100}
                className="w-full rounded-xl border border-slate-200 bg-white py-2 pe-4 ps-9 text-xs shadow-sm outline-none transition-all"
              />
            </div>

            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className={`live-stock-filter-button ${
                    activeFilterCount > 0
                      ? "live-stock-filter-button--active"
                      : ""
                  }`}
                  aria-label={t("inventoryLive.filterButton")}
                  title={t("inventoryLive.filterButton")}
                >
                  <ListFilter className="h-4 w-4" />
                  <span>{t("inventoryLive.filterButton")}</span>
                  {activeFilterCount > 0 && (
                    <span className="live-stock-filter-count tabular-nums">
                      {activeFilterCount}
                    </span>
                  )}
                </button>
              </PopoverTrigger>
              <PopoverContent
                align="start"
                sideOffset={8}
                dir={i18n.dir()}
                className="live-stock-filter-popover live-stock-filter-popover--compact"
              >
                <div className="live-stock-filter-choice-grid live-stock-filter-choice-grid--compact">
                  {(
                    [
                      ["all", "filterAll"],
                      ["on_hand", "filterOnHand"],
                      ["sellable", "filterSellable"],
                      ["out_of_stock", "filterOutOfStock"],
                      ["low_stock", "filterLowStock"],
                    ] as const
                  ).map(([value, labelKey]) => (
                    <button
                      key={value}
                      type="button"
                      className="live-stock-filter-option live-stock-filter-option--compact"
                      data-active={stockState === value}
                      disabled={value === "low_stock" && alertCount === 0}
                      onClick={() => onStockStateChange(value)}
                    >
                      <span>
                        <strong>{t(`inventoryLive.${labelKey}`)}</strong>
                        {value === "low_stock" && alertCount !== null && (
                          <small>
                            {t("inventoryLive.filterLowStockCount", {
                              count: alertCount,
                            })}
                          </small>
                        )}
                      </span>
                      {stockState === value && <Check className="h-3.5 w-3.5" />}
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
                  ).map(([value, labelKey]) => {
                    const active = indicators.includes(value);
                    return (
                      <button
                        key={value}
                        type="button"
                        className="live-stock-filter-chip"
                        data-active={active}
                        onClick={() => toggleIndicator(value)}
                      >
                        {active && <Check className="h-3.5 w-3.5" />}
                        {t(`inventoryLive.${labelKey}`)}
                      </button>
                    );
                  })}
                </div>

                {activeFilterCount > 0 && (
                  <button
                    type="button"
                    className="live-stock-filter-reset live-stock-filter-reset--compact"
                    onClick={clearFilters}
                  >
                    <FilterX className="h-3.5 w-3.5" />
                    {t("inventoryLive.filterReset")}
                  </button>
                )}
              </PopoverContent>
            </Popover>

            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className={`live-stock-family-button ${
                    familyId !== null ? "live-stock-family-button--active" : ""
                  }`}
                  title={t("inventoryLive.familyTitle")}
                  aria-label={t("inventoryLive.familyTitle")}
                >
                  <span className="live-stock-family-button-label">
                    {selectedFamily?.name ?? t("inventoryLive.familyTitle")}
                  </span>
                  {familyId !== null && <Check className="h-3.5 w-3.5" />}
                </button>
              </PopoverTrigger>
              <PopoverContent
                align="start"
                sideOffset={8}
                dir={i18n.dir()}
                className="live-stock-family-popover"
              >
                <div className="live-stock-family-search-row">
                  <input
                    type="search"
                    value={familySearch}
                    onChange={(event) => setFamilySearch(event.target.value)}
                    placeholder={t("inventoryLive.familySearch")}
                    className="live-stock-family-search"
                  />
                  {familyId !== null && (
                    <button
                      type="button"
                      className="live-stock-family-clear"
                      onClick={() => onFamilyChange(null)}
                      title={t("inventoryLive.clearFamily")}
                      aria-label={t("inventoryLive.clearFamily")}
                    >
                      <FilterX className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <div className="live-stock-family-list custom-scrollbar">
                  {familyLoading ? (
                    <div className="live-stock-family-empty">
                      {t("common.loading")}
                    </div>
                  ) : (
                    familyOptions.map((family) => (
                      <button
                        key={family.id}
                        type="button"
                        className="live-stock-family-option"
                        data-active={familyId === family.id}
                        onClick={() => onFamilyChange(family.id)}
                      >
                        <span>
                          <strong>{family.name}</strong>
                          <small>{family.code}</small>
                        </span>
                        {familyId === family.id && (
                          <Check className="h-3.5 w-3.5" />
                        )}
                      </button>
                    ))
                  )}
                </div>
              </PopoverContent>
            </Popover>
          </div>

          <div className="live-stock-context-panel">
            <label className="live-stock-context-location">
              <span className="live-stock-context-label">
                {t("inventoryShell.warehouseSelectLabel")}
              </span>
              <select
                aria-label={t("inventoryShell.warehouseSelectLabel")}
                value={locationId}
                onChange={(event) =>
                  onLocationChange(event.target.value)
                }
                className="live-stock-context-select"
              >
                {locations.map((location) => (
                  <option key={location.id} value={location.id}>
                    {location.name}
                  </option>
                ))}
              </select>
            </label>

            <div
              className="live-stock-context-separator"
              aria-hidden="true"
            />

            <div className="live-stock-context-status">
              <div className="live-stock-context-count">
                <span>{t("inventoryShell.liveStockCount")}</span>
                <strong>
                  {stockTotal === null
                    ? "—"
                    : new Intl.NumberFormat(locale, {
                        numberingSystem: "latn",
                      }).format(stockTotal)}
                </strong>
                {isAuditLocked && (
                  <span className="live-stock-lock-chip">
                    {t("inventoryShell.locked")}
                  </span>
                )}
              </div>

              <div className="live-stock-context-sync">
                <span>
                  {t("inventoryShell.lastUpdated")}:{" "}
                  {lastSync
                    ? new Intl.DateTimeFormat(locale, {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                        hour12: false,
                        numberingSystem: "latn",
                      }).format(lastSync)
                    : "—"}
                </span>
                <button
                  type="button"
                  onClick={onRefresh}
                  disabled={loading}
                  className="live-stock-context-refresh"
                  title={t("inventoryShell.refreshNow")}
                  aria-label={t("inventoryShell.refreshNow")}
                >
                  <RefreshCcw
                    className={`h-3.5 w-3.5 ${
                      loading ? "animate-spin" : ""
                    }`}
                  />
                </button>
              </div>
            </div>
          </div>
        </div>

        <div
          ref={tableScrollRef}
          className={`custom-scrollbar min-h-0 flex-1 overflow-x-auto overflow-y-auto transition-all duration-300 ${
            loading
              ? "pointer-events-none select-none opacity-50 grayscale-[20%]"
              : "opacity-100"
          }`}
        >
          <table className="live-stock-table" aria-label={t("inventoryShell.tabs.live")} aria-busy={loading}>
            <thead>
              <tr className="live-stock-columns">
                <th scope="col" className="live-stock-number-heading">
                  #
                </th>
                <th scope="col" className="live-product-heading">
                  {t("inventoryLive.product")}
                </th>
                <th scope="col" className="live-family-heading">
                  {t("inventoryLive.family")}
                </th>

                <th scope="col">
                  <div className="flex items-center justify-center gap-1.5">
                    <span>{t("inventoryLive.onHand")}</span>
                    <HeaderHelp text={t("inventoryLive.onHandHint")} />
                  </div>
                </th>

                <th scope="col">
                  <div className="flex items-center justify-center gap-1.5">
                    <span>{t("inventoryLive.reserved")}</span>
                    <HeaderHelp text={t("inventoryLive.reservedHint")} />
                  </div>
                </th>

                <th scope="col">
                  <div className="flex items-center justify-center gap-1.5">
                    <span>{t("inventoryLive.availableForSale")}</span>
                    <HeaderHelp
                      text={t("inventoryLive.availableForSaleHint")}
                    />
                  </div>
                </th>

                <th scope="col">
                  <div className="flex items-center justify-center gap-1.5">
                    <span>{t("inventoryLive.unavailable")}</span>
                    <HeaderHelp text={t("inventoryLive.unavailableHint")} />
                  </div>
                </th>

                <th scope="col">
                  <div className="flex items-center justify-center gap-1.5">
                    <span>{t("inventoryLive.withVehicles")}</span>
                    <HeaderHelp text={t("inventoryLive.withVehiclesHint")} />
                  </div>
                </th>

                <th scope="col">
                  <div className="flex items-center justify-center gap-1.5">
                    <span>{t("inventoryLive.lastCompanyPurchase")}</span>
                    <HeaderHelp
                      text={t("inventoryLive.lastCompanyPurchaseHint")}
                    />
                  </div>
                </th>

                <th scope="col">
                  <div className="flex items-center justify-center gap-1.5">
                    <span>{t("inventoryLive.companyAverage")}</span>
                    <HeaderHelp
                      text={t("inventoryLive.companyAverageHint")}
                    />
                  </div>
                </th>
              </tr>
            </thead>

            <tbody>
              {products.length === 0 && (
                <tr>
                  <td
                    colSpan={10}
                    className="py-14 text-center text-sm font-bold text-slate-400"
                  >
                    {loading
                      ? t("common.loading")
                      : t("inventoryLive.noMatches")}
                  </td>
                </tr>
              )}

              {products.map((product, index) => {
                const isAlert =
                  compareQuantity(
                    product.minimum_quantity,
                    "0",
                  ) > 0 &&
                  compareQuantity(
                    product.available_for_sale_quantity,
                    product.minimum_quantity,
                  ) <= 0;

                const displayName = t(
                  `uom.${product.display_uom_code}`,
                  {
                    defaultValue: t(
                      "inventoryCommon.unit",
                    ),
                  },
                );
                const baseName = t(
                  `uom.${product.base_uom_code}`,
                  {
                    defaultValue: t(
                      "inventoryCommon.unit",
                    ),
                  },
                );
                const renderQuantity = (
                  value: typeof product.on_hand_quantity,
                ) =>
                  formatCommercialQuantity(
                    value,
                    displayName,
                    baseName,
                    product.display_factor_to_base,
                  );

                const onHand = renderQuantity(
                  product.on_hand_quantity,
                );
                const reserved = renderQuantity(
                  product.reserved_quantity,
                );
                const available = renderQuantity(
                  product.available_for_sale_quantity,
                );
                const vehicles = renderQuantity(
                  product.vehicle_quantity,
                );
                const unavailable = renderQuantity(
                  product.unavailable_quantity,
                );
                const lastPurchaseUom =
                  product.last_purchase_uom_code
                    ? t(
                        `uom.${product.last_purchase_uom_code}`,
                        {
                          defaultValue: t(
                            "inventoryCommon.unit",
                          ),
                        },
                      )
                    : null;

                return (
                  <tr
                      key={product.id}
                      className={`live-stock-row border-b border-slate-100/80 transition-colors ${
                        isAlert
                          ? "bg-red-50/45 hover:bg-red-50/75"
                          : "bg-white hover:bg-slate-50/65"
                      }`}
                    >
                      <td className="live-stock-number-cell">
                        <span
                          className="live-stock-row-number tabular-nums"
                          aria-label={t("inventoryLive.rowNumber", {
                            number: index + 1,
                          })}
                        >
                          {new Intl.NumberFormat(locale, {
                            numberingSystem: "latn",
                          }).format(index + 1)}
                        </span>
                      </td>

                      <td className="live-product-cell px-4 py-3.5">
                        <div className="flex items-center gap-2">

                          <div className="min-w-0">
                            <div className="flex items-center gap-2 font-black text-slate-800">
                              {isAlert && (
                                <span
                                  title={t(
                                    "inventoryLive.atMinimum",
                                  )}
                                >
                                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-red-500" />
                                </span>
                              )}
                              <span className="live-product-name">
                                {product.name}
                              </span>
                            </div>
                            {product.sku && (
                              <div className="mt-0.5 text-[10px] font-bold text-slate-400">
                                {product.sku}
                              </div>
                            )}
                            <div className="live-stock-minimum-row">
                              <span>
                                {t("inventoryLive.minimumStockLabel")}:{" "}
                                {compareQuantity(
                                  product.minimum_quantity,
                                  "0",
                                ) > 0
                                  ? renderQuantity(
                                      product.minimum_quantity,
                                    ).primary
                                  : t(
                                      "inventoryLive.minimumStockUnset",
                                    )}
                              </span>
                              {canManageMinimum && (
                                <button
                                  type="button"
                                  className="live-stock-minimum-edit"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    openMinimumEditor(product);
                                  }}
                                  title={t(
                                    "inventoryLive.editMinimumStock",
                                  )}
                                  aria-label={t(
                                    "inventoryLive.editMinimumStock",
                                  )}
                                >
                                  <Pencil className="h-3 w-3" />
                                  {t(
                                    "inventoryLive.editMinimumStock",
                                  )}
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>

                      <td className="live-family-cell px-3 py-3.5">
                        <div className="live-family-name" title={product.family_name}>
                          {product.family_name}
                        </div>
                      </td>

                      <td className="px-4 py-3.5 text-center font-black tabular-nums text-slate-800">
                        {onHand.primary}
                      </td>

                      <td className="px-4 py-3.5 text-center font-black tabular-nums text-violet-700">
                        {reserved.primary}
                      </td>

                      <td className="px-4 py-3.5 text-center font-black tabular-nums text-emerald-700">
                        {available.primary}
                      </td>

                      <td className="px-4 py-3.5 text-center font-black tabular-nums">
                        {compareQuantity(
                          product.unavailable_quantity,
                          "0",
                        ) > 0 ? (
                          <span className="text-amber-700">
                            {unavailable.primary}
                          </span>
                        ) : (
                          <span className="text-slate-300">
                            —
                          </span>
                        )}
                      </td>

                      <td className="px-4 py-3.5 text-center font-black tabular-nums text-sky-700">
                        {compareQuantity(
                          product.vehicle_quantity,
                          "0",
                        ) > 0
                          ? vehicles.primary
                          : "—"}
                      </td>

                      <td className="px-4 py-3.5 text-center">
                        <div
                          className="font-black tabular-nums text-slate-900"
                          title={
                            product.last_purchase_cost &&
                            lastPurchaseUom
                              ? `${formatMoneyExact(
                                  product.last_purchase_cost,
                                  product.currency_code,
                                  locale,
                                )} · ${t(
                                  "inventoryLive.perUnit",
                                  { unit: lastPurchaseUom },
                                )}${
                                  product.last_purchase_date
                                    ? ` · ${formatDate(
                                        product.last_purchase_date,
                                      )}`
                                    : ""
                                }`
                              : undefined
                          }
                        >
                          {product.last_purchase_cost
                            ? formatMoneyDisplay(
                                product.last_purchase_cost,
                                product.currency_code,
                                locale,
                              )
                            : "—"}
                        </div>
                      </td>

                      <td className="px-4 py-3.5 text-center">
                        <div
                          className="font-black tabular-nums text-slate-900"
                          title={
                            product.average_cost_display
                              ? `${formatMoneyExact(
                                  product.average_cost_display,
                                  product.currency_code,
                                  locale,
                                )} · ${t(
                                  "inventoryLive.perUnit",
                                  { unit: displayName },
                                )}`
                              : undefined
                          }
                        >
                          {product.average_cost_display
                            ? formatMoneyDisplay(
                                product.average_cost_display,
                                product.currency_code,
                                locale,
                              )
                            : "—"}
                        </div>
                      </td>


                    </tr>
                );
              })}
            </tbody>
          </table>
          <div
            ref={loadMoreSentinelRef}
            className="live-stock-load-more-sentinel"
            aria-hidden={!hasMore}
          >
            {hasMore && loading && (
              <span>{t("common.loading")}</span>
            )}
          </div>
        </div>
      </div>

      <Dialog
        open={minimumEditor !== null}
        onOpenChange={(open) => {
          if (!open && !savingMinimum) {
            setMinimumEditor(null);
          }
        }}
      >
        <DialogContent
          dir={i18n.dir()}
          className="live-stock-minimum-dialog sm:max-w-md"
        >
          <DialogHeader>
            <DialogTitle>
              {t("inventoryLive.minimumStockDialogTitle")}
            </DialogTitle>
            <DialogDescription>
              {t("inventoryLive.minimumStockDialogDescription", {
                product: minimumEditor?.product.name ?? "",
              })}
            </DialogDescription>
          </DialogHeader>

          {minimumEditor && (
            <div className="grid gap-3">
              <label className="grid gap-1.5 text-xs font-black text-slate-700">
                <span>
                  {t("inventoryLive.minimumStockInputLabel", {
                    unit: t(
                      `uom.${minimumEditor.uomCode}`,
                      {
                        defaultValue:
                          minimumEditor.uomCode,
                      },
                    ),
                  })}
                </span>
                <input
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  maxLength={24}
                  value={minimumEditor.value}
                  onChange={(event) =>
                    setMinimumEditor((current) =>
                      current
                        ? {
                            ...current,
                            value: event.target.value,
                            requestId: crypto.randomUUID(),
                          }
                        : current,
                    )
                  }
                  className="h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm font-black tabular-nums outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
                />
              </label>
              <p className="text-[11px] font-semibold leading-5 text-slate-500">
                {t("inventoryLive.minimumStockZeroHint")}
              </p>
            </div>
          )}

          <DialogFooter className="gap-2 sm:space-x-0">
            <button
              type="button"
              disabled={savingMinimum}
              onClick={() => setMinimumEditor(null)}
              className="h-10 rounded-xl border border-slate-200 bg-white px-4 text-xs font-black text-slate-600 disabled:opacity-50"
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              disabled={savingMinimum || minimumEditor === null}
              onClick={() => void saveMinimumStock()}
              className="h-10 rounded-xl bg-sky-700 px-4 text-xs font-black text-white shadow-sm hover:bg-sky-800 disabled:opacity-50"
            >
              {savingMinimum
                ? t("common.saving")
                : t("inventoryLive.minimumStockSave")}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
