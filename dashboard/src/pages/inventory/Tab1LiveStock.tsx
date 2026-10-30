import { AlertTriangle, RefreshCcw } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import {
  type LiveStockIndicator,
  type LiveStockStockState,
  type WarehouseProduct,
} from "./liveStock/contracts";
import { BatchDetailPanel } from "./liveStock/BatchDetailPanel";
import { LiveStockFilters } from "./liveStock/LiveStockFilters";
import { LiveStockMobileCards } from "./liveStock/LiveStockMobileCards";
import { LiveStockTable } from "./liveStock/LiveStockTable";
import { LiveStockWarehouseContext } from "./liveStock/LiveStockWarehouseContext";
import { getLiveStockCp7Copy } from "./liveStock/i18n";
import { useLiveStockBatchDetail } from "./liveStock/useLiveStockBatchDetail";

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
  indicators: LiveStockIndicator[];
  familyId: number | null;
  onLocationChange: (value: string) => void;
  onRefresh: () => void;
  onRetryPage: () => void;
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
  hasMore,
  stockState,
  indicators,
  familyId,
  onLocationChange,
  onRefresh,
  onRetryPage,
  onSearchChange,
  onStockStateChange,
  onIndicatorsChange,
  onFamilyChange,
  onLoadMore,
}: Props) {
  const { t, i18n } = useTranslation();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const detail = useLiveStockBatchDetail(
    locationId,
    t("inventoryLive.errors.batchLoadFailed"),
    getLiveStockCp7Copy(i18n.resolvedLanguage || i18n.language).staleBatchDetails,
  );

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
            indicators={indicators}
            familyId={familyId}
            onSearchChange={onSearchChange}
            onStockStateChange={onStockStateChange}
            onIndicatorsChange={onIndicatorsChange}
            onFamilyChange={onFamilyChange}
          />
          <LiveStockWarehouseContext
            locationId={locationId}
            locations={locations}
            stockTotal={stockTotal}
            lastSync={lastSync}
            isAuditLocked={isAuditLocked}
            loading={loading}
            onLocationChange={onLocationChange}
            onRefresh={refreshWithDetail}
          />
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

        {!pageError && summaryError ? (
          <div
            role="status"
            data-cp13-state="summary-unavailable"
            className="mx-3 mt-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] font-bold text-slate-600"
          >
            {t("inventoryLive.errors.summaryUnavailable")}
          </div>
        ) : null}

        <div
          ref={scrollRef}
          className="custom-scrollbar min-h-0 flex-1 overflow-x-hidden overflow-y-auto md:overflow-x-auto"
          data-cp13-stock-list="true"
        >
          {products.length > 0 ? (
            <>
              <LiveStockTable
                products={products}
                loading={loading}
                onOpen={detail.open}
              />
              <LiveStockMobileCards products={products} onOpen={detail.open} />
            </>
          ) : (
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
        hasMore={detail.page?.has_more ?? false}
        loading={detail.loading}
        error={detail.loadError}
        sourceByBatch={detail.sourceByBatch}
        sourceOpenId={detail.sourceOpenId}
        sourceLoadingId={detail.sourceLoadingId}
        sourceErrorId={detail.sourceErrorId}
        onClose={detail.close}
        onRetry={detail.retry}
        onLoadMore={detail.loadMore}
        onLoadSource={detail.loadSource}
        onRetrySource={detail.retrySource}
      />
    </div>
  );
}
