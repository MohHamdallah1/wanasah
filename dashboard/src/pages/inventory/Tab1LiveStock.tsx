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
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const detail = useLiveStockBatchDetail(
    locationId,
    t("inventoryLive.errors.batchLoadFailed"),
  );

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
    <div className="inventory-view inventory-live-stock flex min-h-0 flex-1 flex-col gap-3">
      <div className="glass-card inventory-data-panel flex min-h-0 flex-1 flex-col overflow-hidden pt-0">
        <div className="live-stock-toolbar flex flex-wrap items-center gap-2">
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
            onRefresh={onRefresh}
          />
        </div>

        {pageError && pageReady ? (
          <div
            role="alert"
            className="mx-3 mt-3 flex flex-wrap items-start justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-950"
          >
            <div className="flex min-w-0 flex-1 items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" aria-hidden="true" />
              <div className="min-w-0">
                <p className="text-sm font-black">{t("inventoryLive.errors.updateTitle")}</p>
                <p className="mt-1 text-xs font-bold text-amber-800">
                  {t("inventoryLive.errors.staleData")}
                </p>
                <p className="mt-1 break-words text-xs text-amber-700">{pageError}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onRetryPage}
              disabled={loading}
              className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-black text-amber-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:opacity-60"
            >
              <RefreshCcw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              {t("common.retry")}
            </button>
          </div>
        ) : null}

        {!pageError && summaryError ? (
          <div role="status" className="mx-3 mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs font-bold text-slate-600">
            {t("inventoryLive.errors.summaryUnavailable")}
          </div>
        ) : null}

        <div
          ref={scrollRef}
          className="custom-scrollbar min-h-0 flex-1 overflow-x-hidden overflow-y-auto md:overflow-x-auto"
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
            <div className="flex min-h-48 items-center justify-center p-4 text-center text-sm font-bold text-slate-500">
              {pageError && !pageReady ? (
                <div role="alert" className="max-w-xl rounded-2xl border border-red-200 bg-red-50 p-5 text-red-900">
                  <AlertTriangle className="mx-auto h-7 w-7 text-red-600" aria-hidden="true" />
                  <p className="mt-2 text-sm font-black">{t("inventoryLive.errors.updateTitle")}</p>
                  <p className="mt-1 text-xs font-bold text-red-800">{t("inventoryLive.errors.noData")}</p>
                  <p className="mt-2 break-words text-xs text-red-700">{pageError}</p>
                  <button
                    type="button"
                    onClick={onRetryPage}
                    disabled={loading}
                    className="mt-3 rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                  >
                    {t("common.retry")}
                  </button>
                </div>
              ) : loading && !pageReady ? (
                <span className="inline-flex items-center gap-2">
                  <RefreshCcw className="h-4 w-4 animate-spin" aria-hidden="true" />
                  {t("common.loading")}
                </span>
              ) : (
                t("inventoryLive.noMatches")
              )}
            </div>
          )}

          <div
            ref={sentinelRef}
            className="live-stock-load-more-sentinel flex min-h-8 items-center justify-center text-xs font-bold text-slate-500"
            aria-hidden={!hasMore}
          >
            {hasMore && loading ? t("common.loading") : null}
          </div>
        </div>
      </div>

      <BatchDetailPanel
        product={detail.product}
        batches={detail.page?.batches ?? []}
        hasMore={detail.page?.has_more ?? false}
        loading={detail.loading}
        error={detail.loadError}
        sourceByBatch={detail.sourceByBatch}
        sourceLoadingId={detail.sourceLoadingId}
        sourceErrorId={detail.sourceErrorId}
        onClose={detail.close}
        onRetry={detail.retry}
        onLoadMore={detail.loadMore}
        onLoadSource={detail.loadSource}
      />
    </div>
  );
}
