import {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  AlertTriangle,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FilterX,
  Info,
  ListFilter,
  PackageOpen,
  Pencil,
  RefreshCcw,
  Search,
  ShieldAlert,
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
  parseBatchDetailResponse,
  parseLiveStockFamilies,
  type LiveStockFamilyOption,
  type LiveStockIndicator,
  type LiveStockSort,
  type LiveStockStockState,
  type WarehouseBatchDetailResponse,
  type WarehouseBatchInventoryItem,
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
  pageNumber: number;
  pageSize: number;
  hasMore: boolean;
  hasPrevious: boolean;
  stockState: LiveStockStockState;
  indicators: LiveStockIndicator[];
  familyId: number | null;
  sort: LiveStockSort;
  canManageMinimum: boolean;
  onLocationChange: (value: string) => void;
  onRefresh: () => void;
  onSearchChange: (search: string) => void;
  onStockStateChange: (value: LiveStockStockState) => void;
  onIndicatorsChange: (value: LiveStockIndicator[]) => void;
  onFamilyChange: (value: number | null) => void;
  onSortChange: (value: LiveStockSort) => void;
  onNext: () => void;
  onPrevious: () => void;
}

type MinimumStockEditor = {
  product: WarehouseProduct;
  uomId: number;
  uomCode: string;
  value: string;
  requestId: string;
};

const statusTone = (
  status: WarehouseBatchInventoryItem["disposition"],
): string => {
  switch (status) {
    case "RECALLED":
      return "border-red-200 bg-red-50 text-red-700";
    case "BLOCKED":
      return "border-orange-200 bg-orange-50 text-orange-700";
    case "QUARANTINED":
      return "border-amber-200 bg-amber-50 text-amber-700";
    default:
      return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
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
  pageNumber,
  pageSize,
  hasMore,
  hasPrevious,
  stockState,
  indicators,
  familyId,
  sort,
  canManageMinimum,
  onLocationChange,
  onRefresh,
  onSearchChange,
  onStockStateChange,
  onIndicatorsChange,
  onFamilyChange,
  onSortChange,
  onNext,
  onPrevious,
}: Props) {
  const authFetch = useAuthFetch();
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage || i18n.language || "en";

  const [searchInput, setSearchInput] = useState("");
  const [expandedProductId, setExpandedProductId] =
    useState<number | null>(null);
  const [batchDetails, setBatchDetails] = useState<
    Record<number, WarehouseBatchDetailResponse>
  >({});
  const [batchLoadingId, setBatchLoadingId] =
    useState<number | null>(null);
  const [batchErrorId, setBatchErrorId] =
    useState<number | null>(null);
  const [minimumEditor, setMinimumEditor] =
    useState<MinimumStockEditor | null>(null);
  const [savingMinimum, setSavingMinimum] = useState(false);
  const [familySearch, setFamilySearch] = useState("");
  const [familyOptions, setFamilyOptions] =
    useState<LiveStockFamilyOption[]>([]);
  const [familyLoading, setFamilyLoading] = useState(false);

  const batchRequestSeq = useRef(0);
  const batchAbortRef = useRef<AbortController | null>(null);
  const tableScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setSearchInput("");
    setExpandedProductId(null);
    setBatchDetails({});
    setBatchLoadingId(null);
    setBatchErrorId(null);
    setMinimumEditor(null);
    setSavingMinimum(false);
    setFamilySearch("");
    setFamilyOptions([]);
    setFamilyLoading(false);
    batchRequestSeq.current += 1;
    batchAbortRef.current?.abort();
    batchAbortRef.current = null;

    return () => {
      batchRequestSeq.current += 1;
      batchAbortRef.current?.abort();
      batchAbortRef.current = null;
    };
  }, [locationId]);

  useEffect(() => {
    const handler = window.setTimeout(() => {
      const clean = searchInput.trim();
      onSearchChange(clean.length >= 2 ? clean : "");
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
    tableScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [pageNumber]);

  const formatDate = useCallback(
    (value: string | null): string => {
      if (!value) return "—";
      try {
        return new Intl.DateTimeFormat(locale, {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          numberingSystem: "latn",
          timeZone: "UTC",
        }).format(new Date(`${value}T00:00:00Z`));
      } catch {
        return value;
      }
    },
    [locale],
  );

  const loadBatchDetails = useCallback(
    async (product: WarehouseProduct) => {
      if (expandedProductId === product.id) {
        batchRequestSeq.current += 1;
        batchAbortRef.current?.abort();
        batchAbortRef.current = null;
        setExpandedProductId(null);
        setBatchLoadingId(null);
        setBatchErrorId(null);
        return;
      }

      setExpandedProductId(product.id);
      setBatchErrorId(null);

      if (batchDetails[product.id]) {
        return;
      }

      const requestSeq = ++batchRequestSeq.current;
      batchAbortRef.current?.abort();
      const controller = new AbortController();
      batchAbortRef.current = controller;
      setBatchLoadingId(product.id);

      try {
        const raw = await authFetch(
          `/warehouse/inventory/${encodeURIComponent(
            String(product.id),
          )}/batches?location_id=${encodeURIComponent(
            String(locationId),
          )}`,
          { signal: controller.signal },
        );

        if (requestSeq !== batchRequestSeq.current) return;

        const parsed = parseBatchDetailResponse(raw);
        if (
          parsed.location_id !== locationId ||
          parsed.product_variant_id !== product.id ||
          parsed.currency_code.toUpperCase() !==
            product.currency_code.toUpperCase()
        ) {
          const error = new Error(
            "LIVE_STOCK_BATCH_RESPONSE_INVALID",
          ) as Error & { code: string };
          error.code = "LIVE_STOCK_BATCH_RESPONSE_INVALID";
          throw error;
        }

        setBatchDetails((current) => ({
          ...current,
          [product.id]: parsed,
        }));
      } catch (error: unknown) {
        if (requestSeq !== batchRequestSeq.current) return;
        if (
          error instanceof Error &&
          error.name === "AbortError"
        ) {
          return;
        }

        setBatchErrorId(product.id);
        toast.error(
          apiErrorMessage(
            error,
            t("inventoryLive.errors.batchLoadFailed"),
          ),
        );
      } finally {
        if (batchAbortRef.current === controller) {
          batchAbortRef.current = null;
        }
        if (requestSeq === batchRequestSeq.current) {
          setBatchLoadingId(null);
        }
      }
    },
    [
      authFetch,
      batchDetails,
      expandedProductId,
      locationId,
      t,
    ],
  );

  const retryBatchDetails = useCallback(
    (product: WarehouseProduct) => {
      setBatchDetails((current) => {
        const next = { ...current };
        delete next[product.id];
        return next;
      });
      setExpandedProductId(null);
      queueMicrotask(() => {
        void loadBatchDetails(product);
      });
    },
    [loadBatchDetails],
  );

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
    (stockState !== "all" ? 1 : 0) +
    indicators.length +
    (familyId !== null ? 1 : 0);

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
    onFamilyChange(null);
    setFamilySearch("");
  };

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
                className="live-stock-filter-popover live-stock-filter-popover--wide"
              >
                <div className="live-stock-filter-header">
                  <div>
                    <div className="live-stock-filter-title">
                      {t("inventoryLive.filterTitle")}
                    </div>
                    <div className="live-stock-filter-subtitle">
                      {t("inventoryLive.filterSubtitle")}
                    </div>
                  </div>
                  {activeFilterCount > 0 && (
                    <button
                      type="button"
                      className="live-stock-filter-reset"
                      onClick={clearFilters}
                    >
                      <FilterX className="h-3.5 w-3.5" />
                      {t("inventoryLive.filterReset")}
                    </button>
                  )}
                </div>

                <div className="live-stock-filter-section">
                  <div className="live-stock-filter-section-title">
                    {t("inventoryLive.stockStateTitle")}
                  </div>
                  <div className="live-stock-filter-choice-grid">
                    {(
                      [
                        ["all", "filterAll", "filterAllHint"],
                        ["on_hand", "filterOnHand", "filterOnHandHint"],
                        ["sellable", "filterSellable", "filterSellableHint"],
                        ["out_of_stock", "filterOutOfStock", "filterOutOfStockHint"],
                        ["low_stock", "filterLowStock", "filterLowStockHint"],
                      ] as const
                    ).map(([value, labelKey, hintKey]) => (
                      <button
                        key={value}
                        type="button"
                        className="live-stock-filter-option"
                        data-active={stockState === value}
                        disabled={value === "low_stock" && alertCount === 0}
                        onClick={() => onStockStateChange(value)}
                      >
                        <span>
                          <strong>{t(`inventoryLive.${labelKey}`)}</strong>
                          <small>
                            {value === "low_stock" && alertCount !== null
                              ? t("inventoryLive.filterLowStockCount", {
                                  count: alertCount,
                                })
                              : t(`inventoryLive.${hintKey}`)}
                          </small>
                        </span>
                        {stockState === value && <Check className="h-4 w-4" />}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="live-stock-filter-section">
                  <div className="live-stock-filter-section-title">
                    {t("inventoryLive.indicatorsTitle")}
                  </div>
                  <div className="live-stock-filter-chip-grid">
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
                </div>

                <div className="live-stock-filter-section">
                  <div className="live-stock-filter-section-title">
                    {t("inventoryLive.familyTitle")}
                  </div>
                  <input
                    type="search"
                    value={familySearch}
                    onChange={(event) => setFamilySearch(event.target.value)}
                    placeholder={t("inventoryLive.familySearch")}
                    className="live-stock-family-search"
                  />
                  <div className="live-stock-family-list custom-scrollbar">
                    <button
                      type="button"
                      className="live-stock-family-option"
                      data-active={familyId === null}
                      onClick={() => onFamilyChange(null)}
                    >
                      {t("inventoryLive.allFamilies")}
                      {familyId === null && <Check className="h-3.5 w-3.5" />}
                    </button>
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
                </div>

                <div className="live-stock-filter-section live-stock-sort-section">
                  <div className="live-stock-filter-section-title">
                    {t("inventoryLive.sortTitle")}
                  </div>
                  <select
                    value={sort}
                    onChange={(event) =>
                      onSortChange(event.target.value as LiveStockSort)
                    }
                    className="live-stock-sort-select"
                    aria-label={t("inventoryLive.sortTitle")}
                  >
                    <option value="name_asc">
                      {t("inventoryLive.sortNameAsc")}
                    </option>
                    <option value="name_desc">
                      {t("inventoryLive.sortNameDesc")}
                    </option>
                  </select>
                </div>
              </PopoverContent>
            </Popover>>
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
                <th scope="col" className="live-product-heading">
                  {t("inventoryLive.product")}
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
                    colSpan={8}
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

                const expanded =
                  expandedProductId === product.id;
                const details =
                  batchDetails[product.id];
                const loadingBatches =
                  batchLoadingId === product.id;
                const batchFailed =
                  batchErrorId === product.id;

                return (
                  <Fragment key={product.id}>
                    <tr
                      className={`live-stock-row border-b border-slate-100/80 transition-colors ${
                        expanded
                          ? "bg-sky-50/45"
                          : isAlert
                            ? "bg-red-50/45 hover:bg-red-50/75"
                            : "bg-white hover:bg-slate-50/65"
                      }`}
                    >
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-2">
                          <span
                            className="live-stock-row-number tabular-nums"
                            aria-label={t("inventoryLive.rowNumber", {
                              number:
                                (pageNumber - 1) * pageSize +
                                index +
                                1,
                            })}
                          >
                            {new Intl.NumberFormat(locale, {
                              numberingSystem: "latn",
                            }).format(
                              (pageNumber - 1) * pageSize +
                                index +
                                1,
                            )}
                          </span>
                          <button
                            type="button"
                            onClick={() =>
                              void loadBatchDetails(product)
                            }
                            className={`grid h-8 w-8 shrink-0 place-items-center rounded-xl border transition-all ${
                              expanded
                                ? "border-sky-200 bg-sky-100 text-sky-700"
                                : "border-slate-200 bg-white text-slate-500 hover:border-sky-200 hover:text-sky-700"
                            }`}
                            aria-expanded={expanded}
                            aria-label={t(
                              expanded
                                ? "inventoryLive.closeBatchDetails"
                                : "inventoryLive.openBatchDetails",
                            )}
                            title={t(
                              expanded
                                ? "inventoryLive.closeBatchDetails"
                                : "inventoryLive.openBatchDetails",
                            )}
                          >
                            <ChevronDown
                              className={`h-4 w-4 transition-transform ${
                                expanded
                                  ? "rotate-180"
                                  : ""
                              }`}
                            />
                          </button>

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
                            <div className="mt-0.5 text-[10px] font-bold text-slate-400">
                              {t(
                                "inventoryLive.batchDetailsHint",
                              )}
                            </div>
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

                    {expanded && (
                      <tr className="border-b border-sky-100 bg-[linear-gradient(135deg,rgba(240,249,255,0.92),rgba(248,250,252,0.96))]">
                        <td colSpan={8} className="live-batch-panel p-0">
                          <div className="px-5 py-4">
                            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <div className="flex items-center gap-2 text-sm font-black text-slate-800">
                                  <PackageOpen className="h-4 w-4 text-sky-700" />
                                  {t(
                                    "inventoryLive.batchPanelTitle",
                                  )}
                                </div>
                                <p className="mt-1 max-w-3xl text-[11px] font-semibold leading-5 text-slate-500">
                                  {t(
                                    "inventoryLive.batchPanelHint",
                                  )}
                                </p>
                              </div>
                            </div>

                            {loadingBatches && (
                              <div className="flex min-h-28 items-center justify-center gap-2 rounded-2xl border border-sky-100 bg-white/75 text-sm font-bold text-slate-500">
                                <RefreshCcw className="h-4 w-4 animate-spin" />
                                {t(
                                  "inventoryLive.loadingBatches",
                                )}
                              </div>
                            )}

                            {!loadingBatches &&
                              batchFailed && (
                                <div className="flex min-h-28 flex-col items-center justify-center gap-3 rounded-2xl border border-red-100 bg-red-50/60 px-4 text-center">
                                  <span className="text-sm font-black text-red-700">
                                    {t(
                                      "inventoryLive.errors.batchLoadFailed",
                                    )}
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      retryBatchDetails(
                                        product,
                                      )
                                    }
                                    className="inline-flex items-center gap-1.5 rounded-xl border border-red-200 bg-white px-3 py-2 text-xs font-black text-red-700"
                                  >
                                    <RefreshCcw className="h-3.5 w-3.5" />
                                    {t("common.retry")}
                                  </button>
                                </div>
                              )}

                            {!loadingBatches &&
                              !batchFailed &&
                              details &&
                              details.batches.length ===
                                0 && (
                                <div className="flex min-h-28 items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white/70 text-sm font-bold text-slate-400">
                                  {t(
                                    "inventoryLive.noBatchesInWarehouse",
                                  )}
                                </div>
                              )}

                            {!loadingBatches &&
                              !batchFailed &&
                              details &&
                              details.batches.length >
                                0 && (
                                <div className="grid gap-3 xl:grid-cols-2">
                                  {details.batches.map(
                                    (batch) => {
                                      const batchOnHand =
                                        renderQuantity(
                                          batch.on_hand_quantity,
                                        );
                                      const batchReserved =
                                        renderQuantity(
                                          batch.reserved_quantity,
                                        );
                                      const batchAvailable =
                                        renderQuantity(
                                          batch.available_for_sale_quantity,
                                        );
                                      const batchUnavailable =
                                        renderQuantity(
                                          batch.unavailable_quantity,
                                        );

                                      const statusChips = [
                                        {
                                          key: "restricted",
                                          value:
                                            batch.restricted_quantity,
                                          label: t(
                                            "inventoryLive.restricted",
                                          ),
                                          tone: "border-amber-200 bg-amber-50 text-amber-700",
                                        },
                                        {
                                          key: "quarantined",
                                          value:
                                            batch.quarantined_quantity,
                                          label: t(
                                            "inventoryLive.quarantined",
                                          ),
                                          tone: "border-yellow-200 bg-yellow-50 text-yellow-700",
                                        },
                                        {
                                          key: "blocked",
                                          value:
                                            batch.blocked_quantity,
                                          label: t(
                                            "inventoryLive.blocked",
                                          ),
                                          tone: "border-orange-200 bg-orange-50 text-orange-700",
                                        },
                                        {
                                          key: "recalled",
                                          value:
                                            batch.recalled_quantity,
                                          label: t(
                                            "inventoryLive.recalled",
                                          ),
                                          tone: "border-red-200 bg-red-50 text-red-700",
                                        },
                                        {
                                          key: "damaged",
                                          value:
                                            batch.damaged_quantity,
                                          label: t(
                                            "inventoryLive.damaged",
                                          ),
                                          tone: "border-rose-200 bg-rose-50 text-rose-700",
                                        },
                                        {
                                          key: "disposal",
                                          value:
                                            batch.disposal_pending_quantity,
                                          label: t(
                                            "inventoryLive.disposalPending",
                                          ),
                                          tone: "border-slate-300 bg-slate-100 text-slate-700",
                                        },
                                      ].filter(
                                        (item) =>
                                          compareQuantity(
                                            item.value,
                                            "0",
                                          ) > 0,
                                      );

                                      const batchCostUom =
                                        batch.latest_purchase_uom_code
                                          ? t(
                                              `uom.${batch.latest_purchase_uom_code}`,
                                              {
                                                defaultValue:
                                                  t(
                                                    "inventoryCommon.unit",
                                                  ),
                                              },
                                            )
                                          : null;

                                      return (
                                        <article
                                          key={
                                            batch.batch_id
                                          }
                                          className="overflow-hidden rounded-2xl border border-slate-200 bg-white/90 shadow-[0_14px_32px_-28px_rgba(15,31,54,0.75)]"
                                        >
                                          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
                                            <div>
                                              <div className="text-[10px] font-black uppercase tracking-[0.12em] text-slate-400">
                                                {t(
                                                  "inventoryLive.batchNumber",
                                                )}
                                              </div>
                                              <div className="mt-0.5 font-black text-slate-900">
                                                {
                                                  batch.batch_number
                                                }
                                              </div>
                                            </div>

                                            <span
                                              className={`rounded-full border px-2.5 py-1 text-[10px] font-black ${statusTone(
                                                batch.disposition,
                                              )}`}
                                            >
                                              {t(
                                                `inventoryLive.batchDisposition.${batch.disposition}`,
                                              )}
                                            </span>
                                          </div>

                                          <div className="grid gap-3 px-4 py-3 md:grid-cols-[1.05fr_1fr]">
                                            <div className="space-y-3">
                                              <div className="grid grid-cols-2 gap-2 text-[11px]">
                                                <div className="rounded-xl bg-slate-50 px-3 py-2">
                                                  <div className="flex items-center gap-1 font-black text-slate-500">
                                                    <CalendarDays className="h-3.5 w-3.5" />
                                                    {t(
                                                      "inventoryLive.productionDate",
                                                    )}
                                                  </div>
                                                  <div className="mt-1 font-black tabular-nums text-slate-800">
                                                    {formatDate(
                                                      batch.production_date,
                                                    )}
                                                  </div>
                                                </div>

                                                <div className="rounded-xl bg-slate-50 px-3 py-2">
                                                  <div className="flex items-center gap-1 font-black text-slate-500">
                                                    <CalendarDays className="h-3.5 w-3.5" />
                                                    {t(
                                                      "inventoryLive.expiryDate",
                                                    )}
                                                  </div>
                                                  <div className="mt-1 font-black tabular-nums text-slate-800">
                                                    {formatDate(
                                                      batch.expiry_date,
                                                    )}
                                                  </div>
                                                  {batch.days_to_expiry !==
                                                    null && (
                                                    <div
                                                      className={`mt-1 text-[10px] font-black ${
                                                        batch.days_to_expiry <
                                                        0
                                                          ? "text-red-600"
                                                          : batch.days_to_expiry ===
                                                              0
                                                            ? "text-orange-600"
                                                            : "text-slate-400"
                                                      }`}
                                                    >
                                                      {batch.days_to_expiry <
                                                      0
                                                        ? t(
                                                            "inventoryLive.expiredSince",
                                                            {
                                                              count:
                                                                Math.abs(
                                                                  batch.days_to_expiry,
                                                                ),
                                                            },
                                                          )
                                                        : batch.days_to_expiry ===
                                                            0
                                                          ? t(
                                                              "inventoryLive.expiresToday",
                                                            )
                                                          : t(
                                                              "inventoryLive.daysRemaining",
                                                              {
                                                                count:
                                                                  batch.days_to_expiry,
                                                              },
                                                            )}
                                                    </div>
                                                  )}
                                                </div>
                                              </div>

                                              <div className="grid grid-cols-3 overflow-hidden rounded-xl border border-slate-200 bg-slate-50/80 text-center">
                                                <div className="border-e border-slate-200 px-2 py-2">
                                                  <div className="text-[9px] font-black text-slate-400">
                                                    {t(
                                                      "inventoryLive.onHand",
                                                    )}
                                                  </div>
                                                  <div className="mt-0.5 text-xs font-black text-slate-800">
                                                    {
                                                      batchOnHand.primary
                                                    }
                                                  </div>
                                                </div>
                                                <div className="border-e border-slate-200 px-2 py-2">
                                                  <div className="text-[9px] font-black text-slate-400">
                                                    {t(
                                                      "inventoryLive.reserved",
                                                    )}
                                                  </div>
                                                  <div className="mt-0.5 text-xs font-black text-violet-700">
                                                    {
                                                      batchReserved.primary
                                                    }
                                                  </div>
                                                </div>
                                                <div className="px-2 py-2">
                                                  <div className="text-[9px] font-black text-slate-400">
                                                    {t(
                                                      "inventoryLive.availableForSale",
                                                    )}
                                                  </div>
                                                  <div className="mt-0.5 text-xs font-black text-emerald-700">
                                                    {
                                                      batchAvailable.primary
                                                    }
                                                  </div>
                                                </div>
                                              </div>
                                            </div>

                                            <div className="flex flex-col gap-3">
                                              <div className="rounded-xl border border-cyan-100 bg-cyan-50/55 px-3 py-2.5">
                                                <div className="text-[10px] font-black text-cyan-700">
                                                  {t(
                                                    "inventoryLive.latestBatchPurchase",
                                                  )}
                                                </div>
                                                <div className="mt-1 font-black tabular-nums text-slate-900">
                                                  {batch.latest_purchase_cost &&
                                                  batchCostUom
                                                    ? formatMoneyExact(
                                                        batch.latest_purchase_cost,
                                                        details.currency_code,
                                                        locale,
                                                      )
                                                    : "—"}
                                                </div>
                                                {batch.latest_purchase_cost &&
                                                  batchCostUom && (
                                                    <div className="mt-0.5 text-[10px] font-bold text-slate-500">
                                                      {t(
                                                        "inventoryLive.perUnit",
                                                        {
                                                          unit: batchCostUom,
                                                        },
                                                      )}
                                                      {batch.latest_purchase_date
                                                        ? ` · ${formatDate(
                                                            batch.latest_purchase_date,
                                                          )}`
                                                        : ""}
                                                    </div>
                                                  )}
                                                <div className="mt-1 text-[10px] font-bold text-slate-400">
                                                  {batch.purchase_event_count >
                                                  0
                                                    ? t(
                                                        "inventoryLive.batchPurchaseEvents",
                                                        {
                                                          count:
                                                            batch.purchase_event_count,
                                                        },
                                                      )
                                                    : t(
                                                        "inventoryLive.noBatchPurchaseEvidence",
                                                      )}
                                                </div>
                                              </div>

                                              <div className="rounded-xl border border-slate-200 bg-slate-50/75 px-3 py-2.5">
                                                <div className="flex items-center justify-between gap-2">
                                                  <span className="text-[10px] font-black text-slate-500">
                                                    {t(
                                                      "inventoryLive.unavailable",
                                                    )}
                                                  </span>
                                                  <span className="text-xs font-black tabular-nums text-amber-700">
                                                    {
                                                      batchUnavailable.primary
                                                    }
                                                  </span>
                                                </div>

                                                {statusChips.length >
                                                0 ? (
                                                  <div className="mt-2 flex flex-wrap gap-1.5">
                                                    {statusChips.map(
                                                      (
                                                        item,
                                                      ) => (
                                                        <span
                                                          key={
                                                            item.key
                                                          }
                                                          className={`rounded-full border px-2 py-0.5 text-[9px] font-black ${item.tone}`}
                                                        >
                                                          {
                                                            item.label
                                                          }
                                                          :{" "}
                                                          {
                                                            renderQuantity(
                                                              item.value,
                                                            )
                                                              .primary
                                                          }
                                                        </span>
                                                      ),
                                                    )}
                                                  </div>
                                                ) : (
                                                  <div className="mt-2 text-[10px] font-bold text-slate-400">
                                                    {t(
                                                      "inventoryLive.noRestrictedStock",
                                                    )}
                                                  </div>
                                                )}
                                              </div>
                                            </div>
                                          </div>
                                        </article>
                                      );
                                    },
                                  )}
                                </div>
                              )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        {(hasPrevious || hasMore) && (
          <div className="live-stock-pagination">
            <span className="live-stock-pagination-page">
              {t("inventoryLive.page", {
                page: pageNumber,
              })}
            </span>
            <div className="live-stock-pagination-actions">
              <button
                type="button"
                onClick={onPrevious}
                disabled={!hasPrevious || loading}
                className="live-stock-pagination-button"
              >
                <ChevronRight className="h-4 w-4 rtl:block ltr:hidden" />
                <ChevronLeft className="hidden h-4 w-4 ltr:block" />
                <span>{t("inventoryLive.previousPage")}</span>
              </button>
              <button
                type="button"
                onClick={onNext}
                disabled={!hasMore || loading}
                className="live-stock-pagination-button"
              >
                <span>{t("inventoryLive.nextPage")}</span>
                <ChevronLeft className="h-4 w-4 rtl:block ltr:hidden" />
                <ChevronRight className="hidden h-4 w-4 ltr:block" />
              </button>
            </div>
          </div>
        )}
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
