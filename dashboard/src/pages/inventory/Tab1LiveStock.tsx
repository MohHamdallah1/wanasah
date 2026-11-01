import { AlertTriangle, RefreshCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useMediaQuery } from "@/hooks/useMediaQuery";

import {
  type LiveStockIndicator,
  type LiveStockStockState,
  type LiveStockSort,
  type LiveStockView,
  type WarehouseProduct,
} from "./liveStock/contracts";
import { BatchDetailPanel } from "./liveStock/BatchDetailPanel";
import { LiveStockFilters } from "./liveStock/LiveStockFilters";
import { LiveStockMobileCards } from "./liveStock/LiveStockMobileCards";
import { LiveStockTable } from "./liveStock/LiveStockTable";
import { LiveStockWarehouseContext } from "./liveStock/LiveStockWarehouseContext";
import { getLiveStockCp7Copy } from "./liveStock/i18n";
import { useLiveStockBatchDetail } from "./liveStock/useLiveStockBatchDetail";

const LIVE_STOCK_OVERSCAN_ROWS = 12;
const LIVE_STOCK_FALLBACK_DESKTOP_ROW_PX = 64;
const LIVE_STOCK_FALLBACK_MOBILE_CARD_PX = 126;
const LIVE_STOCK_FALLBACK_VIEWPORT_PX = 720;

interface Props {
  locationId: number;
  locations: Array<{ id: number; name: string }>;
  stockTotal: number | null;
  lastSync: Date | null;
  isAuditLocked: boolean;
  products: WarehouseProduct[];
  loading: boolean;
  pageReady: boolean;
  pageError: string | null;
  summaryError: string | null;
  alertCount: number | null;
  matchingTotal: number | null;
  hasMore: boolean;
  stockState: LiveStockStockState;
  sort: LiveStockSort;
  onSortChange: (value: LiveStockSort) => void;
  view: LiveStockView;
  onViewChange: (value: LiveStockView) => void;
  indicators: LiveStockIndicator[];
  familyId: number | null;
  onLocationChange: (value: string) => void;
  onRefresh: () => void;
  onRetryPage: () => void;
  onRetrySummary?: () => void;
  onReadDenied?: () => void;
  onSearchChange: (search: string) => void;
  onStockStateChange: (value: LiveStockStockState) => void;
  onIndicatorsChange: (value: LiveStockIndicator[]) => void;
  onFamilyChange: (value: number | null) => void;
  onLoadMore: () => void;
}

export function Tab1LiveStock({
  locationId,
  locations,
  stockTotal,
  lastSync,
  isAuditLocked,
  products,
  loading,
  pageReady,
  pageError,
  summaryError,
  alertCount,
  matchingTotal,
  hasMore,
  stockState,
  sort,
  onSortChange,
  view,
  onViewChange,
  indicators,
  familyId,
  onLocationChange,
  onRefresh,
  onRetryPage,
  onRetrySummary = onRetryPage,
  onReadDenied,
  onSearchChange,
  onStockStateChange,
  onIndicatorsChange,
  onFamilyChange,
  onLoadMore,
}: Props) {
  const { t, i18n } = useTranslation();
  const isNarrowViewport = useMediaQuery("(max-width: 767px)");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const focusedProductIdRef = useRef<number | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(
    LIVE_STOCK_FALLBACK_VIEWPORT_PX,
  );
  const measuredItemExtentsRef = useRef<Map<number, number>>(new Map());
  const [measurementRevision, setMeasurementRevision] = useState(0);
  const [viewportWidthBucket, setViewportWidthBucket] = useState(0);
  const fallbackItemExtent = isNarrowViewport
    ? LIVE_STOCK_FALLBACK_MOBILE_CARD_PX
    : LIVE_STOCK_FALLBACK_DESKTOP_ROW_PX;

  useEffect(() => {
    measuredItemExtentsRef.current.clear();
    setMeasurementRevision((revision) => revision + 1);
  }, [
    fallbackItemExtent,
    viewportWidthBucket,
    i18n.language,
    i18n.resolvedLanguage,
  ]);

  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;

    let frame = 0;
    const syncViewport = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        setScrollTop(root.scrollTop);
        setViewportHeight(
          root.clientHeight > 0
            ? root.clientHeight
            : LIVE_STOCK_FALLBACK_VIEWPORT_PX,
        );
        setViewportWidthBucket(
          Math.round(Math.max(0, root.clientWidth) / 32),
        );
      });
    };

    syncViewport();
    root.addEventListener("scroll", syncViewport, { passive: true });
    const resizeObserver =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(syncViewport)
        : null;
    resizeObserver?.observe(root);

    return () => {
      if (frame) cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      root.removeEventListener("scroll", syncViewport);
    };
  }, []);

  const renderedWindow = useMemo(() => {
    const count = products.length;
    if (count === 0) {
      return {
        start: 0,
        end: 0,
        products: [] as WarehouseProduct[],
        topSpacerHeight: 0,
        bottomSpacerHeight: 0,
      };
    }

    const measured = measuredItemExtentsRef.current;
    const offsets = new Array<number>(count + 1);
    offsets[0] = 0;
    for (let index = 0; index < count; index += 1) {
      const measuredExtent = measured.get(products[index].id);
      offsets[index + 1] =
        offsets[index] +
        (measuredExtent && measuredExtent >= 24
          ? measuredExtent
          : fallbackItemExtent);
    }

    const itemAtOffset = (offset: number) => {
      const target = Math.max(0, offset);
      let low = 0;
      let high = count;
      while (low < high) {
        const middle = Math.floor((low + high) / 2);
        if (offsets[middle + 1] <= target) low = middle + 1;
        else high = middle;
      }
      return Math.min(count - 1, low);
    };

    const firstVisible = itemAtOffset(scrollTop);
    const lastVisible = itemAtOffset(scrollTop + viewportHeight);
    const start = Math.max(0, firstVisible - LIVE_STOCK_OVERSCAN_ROWS);
    const end = Math.min(
      count,
      lastVisible + 1 + LIVE_STOCK_OVERSCAN_ROWS,
    );

    return {
      start,
      end,
      products: products.slice(start, end),
      topSpacerHeight: offsets[start],
      bottomSpacerHeight: offsets[count] - offsets[end],
    };
  }, [
    fallbackItemExtent,
    measurementRevision,
    products,
    scrollTop,
    viewportHeight,
  ]);

  const handleItemMeasure = useCallback(
    (productId: number, nextExtent: number) => {
      if (!Number.isFinite(nextExtent) || nextExtent < 24) return;
      const previous = measuredItemExtentsRef.current.get(productId);
      if (previous !== undefined && Math.abs(previous - nextExtent) < 1) {
        return;
      }
      measuredItemExtentsRef.current.set(productId, nextExtent);
      setMeasurementRevision((revision) => revision + 1);
    },
    [],
  );

  const resetRenderWindow = useCallback(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    setScrollTop(0);
  }, []);

  const handleProductFocus = useCallback((productId: number) => {
    focusedProductIdRef.current = productId;
  }, []);

  const handleProductBlur = useCallback((nextTarget: EventTarget | null) => {
    if (
      nextTarget instanceof Element &&
      nextTarget.closest("[data-live-stock-product-open]")
    ) {
      return;
    }
    if (nextTarget !== null) focusedProductIdRef.current = null;
  }, []);

  useEffect(() => {
    const productId = focusedProductIdRef.current;
    if (productId === null) return;
    requestAnimationFrame(() => {
      const selector =
        `[data-live-stock-product-open="${productId}"]`;
      const target = scrollRef.current?.querySelector<HTMLElement>(selector);
      target?.focus({ preventScroll: true });
    });
  }, [isNarrowViewport]);

  const detail = useLiveStockBatchDetail(
    locationId,
    t("inventoryLive.errors.batchLoadFailed"),
    getLiveStockCp7Copy(i18n.resolvedLanguage || i18n.language).staleBatchDetails,
    onReadDenied,
  );
  const [detailMode, setDetailMode] = useState<"batches" | "unavailable">("batches");
  const openBatchDetails = useCallback((product: WarehouseProduct) => {
    setDetailMode("batches");
    detail.open(product);
  }, [detail.open]);
  const openUnavailableBreakdown = useCallback((product: WarehouseProduct) => {
    setDetailMode("unavailable");
    detail.open(product);
  }, [detail.open]);

  const closeDetailWithFocusReturn = useCallback(() => {
    const selectedId = detail.product?.id;
    const selectedMode = detailMode;
    detail.close();
    if (selectedId === undefined) return;

    // A manual refresh replaces the entire inventory row while the modal is
    // open. Restore the exact trigger kind when it still exists.
    window.requestAnimationFrame(() => {
      const selector = selectedMode === "unavailable"
        ? `[data-live-stock-unavailable-open="${selectedId}"]`
        : `[data-live-stock-product-open="${selectedId}"]`;
      const target = scrollRef.current?.querySelector<HTMLElement>(selector)
        ?? scrollRef.current?.querySelector<HTMLElement>(
          `[data-live-stock-product-open="${selectedId}"]`,
        )
        ?? document.querySelector<HTMLElement>(
          '[data-cp13-surface="live-stock"] .live-stock-search input',
        );
      target?.focus({ preventScroll: true });
    });
  }, [detail.close, detail.product?.id, detailMode]);

  const pendingManualRefresh = useRef<{ locationId: number; syncedAt: number | null } | null>(null);
  const selectionRead = useRef<{
    locationId: number; productId: number | null;
    syncedAt: number | null; wasVisible: boolean;
  }>({ locationId, productId: null, syncedAt: null, wasVisible: false });
  const listSelected = detail.product
    ? products.find((item) => item.id === detail.product?.id)
    : undefined;

  const refreshWithDetail = () => {
    if (detail.product) {
      pendingManualRefresh.current = {
        locationId,
        syncedAt: lastSync?.getTime() ?? null,
      };
      // Invalidate immediately. Old batch/source evidence must not look newly
      // verified while the stock list refresh is pending or fails.
      detail.invalidate();
    }
    onRefresh();
  };

  useEffect(() => {
    const current = detail.product;
    const stamp = lastSync?.getTime() ?? null;
    const prior = selectionRead.current;
    if (!current) {
      pendingManualRefresh.current = null;
      selectionRead.current = {
        locationId, productId: null, syncedAt: stamp, wasVisible: false,
      };
      return;
    }
    if (prior.locationId !== locationId || prior.productId !== current.id) {
      selectionRead.current = {
        locationId, productId: current.id,
        syncedAt: stamp, wasVisible: Boolean(listSelected),
      };
    }

    const pending = pendingManualRefresh.current;
    if (pending) {
      if (pending.locationId !== locationId) {
        pendingManualRefresh.current = null;
        return;
      }
      if (pageError && !loading) {
        // Preserve the explicit stale/retry state instead of showing old data.
        pendingManualRefresh.current = null;
        return;
      }
      if (!loading && stamp !== pending.syncedAt && stamp !== null) {
        pendingManualRefresh.current = null;
        selectionRead.current = {
          locationId, productId: current.id,
          syncedAt: stamp, wasVisible: Boolean(listSelected),
        };
        detail.refresh(listSelected ?? current);
      }
      return;
    }

    // An unrelated re-render and cursor append never refresh an open batch.
    // Revalidate once when a newly fetched list changes (or drops) its
    // previously visible selected row, without repeatedly fetching on later pages.
    const previous = selectionRead.current;
    if (!loading && !pageError && stamp !== previous.syncedAt) {
      selectionRead.current = {
        locationId, productId: current.id,
        syncedAt: stamp, wasVisible: Boolean(listSelected),
      };
      if (
        (listSelected && listSelected !== current) ||
        (!listSelected && previous.wasVisible)
      ) {
        detail.refresh(listSelected ?? current);
      }
    }
  }, [detail.product, detail.refresh, lastSync, listSelected, locationId, loading, pageError]);

  useEffect(() => {
    const root = scrollRef.current;
    const target = sentinelRef.current;
    if (!root || !target || pageError) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (
          entries.some((entry) => entry.isIntersecting) &&
          hasMore &&
          !loading
        ) {
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
  }, [hasMore, loading, onLoadMore, pageError]);

  return (
    <div
      className="inventory-view inventory-live-stock flex min-h-0 flex-1 flex-col gap-2"
      data-cp13-density="compact"
      data-cp13-surface="live-stock"
    >
      <section className="glass-card inventory-data-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl pt-0">
        <div
          className="live-stock-toolbar flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50/70 px-3 py-2"
          data-cp13-controls="stock-list"
        >
          <LiveStockFilters
            locationId={locationId}
            alertCount={alertCount}
            stockState={stockState}
            view={view}
            onViewChange={(value) => {
              resetRenderWindow();
              onViewChange(value);
            }}
            indicators={indicators}
            familyId={familyId}
            onSearchChange={(value) => {
              resetRenderWindow();
              onSearchChange(value);
            }}
            onStockStateChange={(value) => {
              resetRenderWindow();
              onStockStateChange(value);
            }}
            onIndicatorsChange={(value) => {
              resetRenderWindow();
              onIndicatorsChange(value);
            }}
            onFamilyChange={(value) => {
              resetRenderWindow();
              onFamilyChange(value);
            }}
          />
          <label className="live-stock-sort flex min-w-0 items-center gap-2 text-xs font-semibold text-slate-700">
            <span className="whitespace-nowrap">{t("inventoryLive.sortLabel")}</span>
            <select
              aria-label={t("inventoryLive.sortLabel")}
              value={sort}
              onChange={(event) => {
                resetRenderWindow();
                onSortChange(event.target.value as LiveStockSort);
              }}
              className="min-w-0 max-w-[11rem] rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              <option value="stock_first">{t("inventoryLive.sortStockFirst")}</option>
              <option value="low_stock_first">{t("inventoryLive.sortLowFirst")}</option>
              <option value="name_asc">{t("inventoryLive.sortName")}</option>
            </select>
          </label>
          <LiveStockWarehouseContext
            locationId={locationId}
            locations={locations}
            stockTotal={stockTotal}
            lastSync={pageReady ? lastSync : null}
            isAuditLocked={isAuditLocked}
            loading={loading}
            onLocationChange={(value) => {
              resetRenderWindow();
              onLocationChange(value);
            }}
            onRefresh={refreshWithDetail}
          />
        </div>

        <div
          role="status"
          aria-live="polite"
          dir={i18n.dir()}
          data-live-count-kind={pageReady ? "loaded" : "unverified"}
          className="sr-only"
        >
          {pageReady ? (
            <>
              <span data-testid="live-loaded-count">
                {t("inventoryLive.loadedVariants", {
                  count: new Intl.NumberFormat(
                    i18n.resolvedLanguage || i18n.language,
                    { numberingSystem: "latn" },
                  ).format(products.length),
                })}
              </span>
              {matchingTotal !== null ? (
                <span data-testid="live-matching-total">
                  {t("inventoryLive.exactMatchingVariants", {
                    count: new Intl.NumberFormat(
                      i18n.resolvedLanguage || i18n.language,
                      { numberingSystem: "latn" },
                    ).format(matchingTotal),
                  })}
                </span>
              ) : hasMore ? (
                <span data-testid="live-unknown-total">
                  {t("inventoryLive.loadedMoreAvailable")}
                </span>
              ) : null}
            </>
          ) : (
            <span data-testid="live-count-unverified">
              {t("inventoryLive.loadedCountUnverified")}
            </span>
          )}
        </div>

        {pageError && pageReady ? (
          <div
            role="alert"
            aria-live="polite"
            data-cp13-state="stale"
            className="mx-3 mt-2 flex flex-wrap items-start justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-amber-950"
          >
            <div className="flex min-w-0 flex-1 items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden="true" />
              <div className="min-w-0">
                <p className="text-xs font-black">{t("inventoryLive.errors.updateTitle")}</p>
                <p className="mt-0.5 text-[11px] font-bold text-amber-800">
                  {t("inventoryLive.errors.staleData")}
                </p>
                <p className="mt-0.5 break-words text-[11px] text-amber-700">{pageError}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onRetryPage}
              disabled={loading}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-300 bg-white px-2.5 py-1.5 text-[11px] font-black text-amber-900 outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:opacity-60"
            >
              <RefreshCcw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              {t("common.retry")}
            </button>
          </div>
        ) : null}

        {summaryError ? (
          <div
            role="status"
            data-cp13-state="summary-unavailable"
            className="mx-3 mt-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] font-bold text-slate-600"
          >
            {t("inventoryLive.errors.summaryUnavailable")}
            <button type="button" onClick={onRetrySummary}
              className="ms-3 rounded-lg border px-2 py-1 focus-visible:ring-2 focus-visible:ring-amber-400">
              {t("common.retry")}
            </button>
          </div>
        ) : null}

        <div
          ref={scrollRef}
          className="custom-scrollbar min-h-0 flex-1 overflow-x-hidden overflow-y-auto md:overflow-x-auto"
          data-cp13-stock-list="true"
        >
          {/* On desktop the real table header is always mounted, including
              initial loading, empty and failure states. No header jump. */}
          {!isNarrowViewport && (
            <LiveStockTable
              products={renderedWindow.products}
              totalCount={products.length}
              startIndex={renderedWindow.start}
              topSpacerHeight={renderedWindow.topSpacerHeight}
              bottomSpacerHeight={renderedWindow.bottomSpacerHeight}
              onItemMeasure={handleItemMeasure}
              onProductFocus={handleProductFocus}
              onProductBlur={handleProductBlur}
              loading={loading}
              onOpen={openBatchDetails}
              onOpenUnavailable={openUnavailableBreakdown}
            />
          )}
          {isNarrowViewport && products.length > 0 && (
            <LiveStockMobileCards
              products={renderedWindow.products}
              totalCount={products.length}
              startIndex={renderedWindow.start}
              topSpacerHeight={renderedWindow.topSpacerHeight}
              bottomSpacerHeight={renderedWindow.bottomSpacerHeight}
              onItemMeasure={handleItemMeasure}
              onProductFocus={handleProductFocus}
              onProductBlur={handleProductBlur}
              onOpen={openBatchDetails}
              onOpenUnavailable={openUnavailableBreakdown}
            />
          )}
          {products.length === 0 && (
            <div className="flex min-h-40 items-center justify-center p-4 text-center text-sm font-bold text-slate-500">
              {pageError && !pageReady ? (
                <div
                  role="alert"
                  data-cp13-state="error"
                  className="max-w-xl rounded-xl border border-red-200 bg-red-50 p-4 text-red-900"
                >
                  <AlertTriangle className="mx-auto h-6 w-6 text-red-600" aria-hidden="true" />
                  <p className="mt-2 text-sm font-black">{t("inventoryLive.errors.updateTitle")}</p>
                  <p className="mt-1 text-xs font-bold text-red-800">{t("inventoryLive.errors.noData")}</p>
                  <p className="mt-2 break-words text-xs text-red-700">{pageError}</p>
                  <button
                    type="button"
                    onClick={onRetryPage}
                    disabled={loading}
                    className="mt-3 rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-black outline-none focus-visible:ring-2 focus-visible:ring-red-300 disabled:opacity-60"
                  >
                    {t("common.retry")}
                  </button>
                </div>
              ) : loading && !pageReady ? (
                <span data-cp13-state="loading" role="status" className="inline-flex items-center gap-2">
                  <RefreshCcw className="h-4 w-4 animate-spin" aria-hidden="true" />
                  {t("common.loading")}
                </span>
              ) : (
                <span data-cp13-state="empty">{t("inventoryLive.noMatches")}</span>
              )}
            </div>
          )}

          <div
            ref={sentinelRef}
            className="live-stock-load-more-sentinel flex min-h-7 items-center justify-center text-[11px] font-bold text-slate-500"
            aria-hidden={!hasMore}
            data-cp13-continuation="cursor"
          >
            {hasMore && loading ? t("common.loading") : null}
          </div>
        </div>
      </section>

      <BatchDetailPanel
        product={detail.product}
        batches={detail.page?.batches ?? []}
        mode={detailMode}
        lifecycleStatus={detail.page?.lifecycle_status ?? null}
        operationalHold={detail.page?.operational_hold ?? null}
        hasMore={detail.page?.has_more ?? false}
        loading={detail.loading}
        error={detail.loadError}
        sourceByBatch={detail.sourceByBatch}
        sourceOpenId={detail.sourceOpenId}
        sourceLoadingId={detail.sourceLoadingId}
        sourceErrorId={detail.sourceErrorId}
        onClose={closeDetailWithFocusReturn}
        onRefresh={refreshWithDetail}
        refreshing={loading || detail.loading}
        onRetry={detail.retry}
        onLoadMore={detail.loadMore}
        onLoadSource={detail.loadSource}
        onRetrySource={detail.retrySource}
      />
    </div>
  );
}
