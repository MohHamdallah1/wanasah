import { AlertTriangle, ChevronDown, RefreshCcw } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import {
  formatCommercialQuantity,
  type Quantity,
} from "@/lib/quantity";
import { resolveI18nLocale } from "@/lib/locale";
import type {
  WarehouseBatchInventoryItem,
  WarehouseProduct,
} from "./contracts";
import { getLiveStockCp7Copy } from "./i18n";
import type { LiveStockWarehouseSource } from "./sourceContract";

type Props = {
  product: WarehouseProduct | null;
  batches: WarehouseBatchInventoryItem[];
  hasMore: boolean;
  loading: boolean;
  error: { message: string; kind: "initial" | "continuation" } | null;
  sourceByBatch: Record<number, LiveStockWarehouseSource>;
  sourceOpenId?: number | null;
  sourceLoadingId: number | null;
  sourceErrorId: number | null;
  onClose: () => void;
  onRetry: () => void;
  onLoadMore: () => void;
  onLoadSource: (batchId: number) => void;
  onRetrySource?: (batchId: number) => void;
};

const dateText = (value: string | null, locale: string): string => {
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
};

export function BatchDetailPanel({
  product,
  batches,
  hasMore,
  loading,
  error,
  sourceByBatch,
  sourceOpenId = null,
  sourceLoadingId,
  sourceErrorId,
  onClose,
  onRetry,
  onLoadMore,
  onLoadSource,
  onRetrySource,
}: Props) {
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);
  const copy = getLiveStockCp7Copy(i18n.resolvedLanguage || i18n.language);

  const unitNames = useMemo(() => {
    if (!product) return null;
    return {
      display: t(`uom.${product.display_uom_code}`, {
        defaultValue: t("inventoryCommon.unit"),
      }),
      base: t(`uom.${product.base_uom_code}`, {
        defaultValue: t("inventoryCommon.unit"),
      }),
    };
  }, [product, t]);

  if (!product || !unitNames) return null;

  const quantity = (value: Quantity) =>
    formatCommercialQuantity(
      value,
      unitNames.display,
      unitNames.base,
      product.display_factor_to_base,
    );
  const quantityText = (value: Quantity) => quantity(value).primary;

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`${copy.batchDetails} — ${product.name}`}
      subtitle={product.sku ? `${product.sku} · ${product.family_name}` : product.family_name}
      maxWidth="max-w-5xl"
      bodyClassName="p-3 sm:p-5"
    >
      <div className="space-y-3" data-testid="live-stock-batch-detail">
        {loading && batches.length === 0 ? (
          <div className="flex min-h-40 items-center justify-center gap-2 text-sm font-bold text-slate-500">
            <RefreshCcw className="h-4 w-4 animate-spin" aria-hidden="true" />
            {copy.loadingBatches}
          </div>
        ) : null}

        {error?.kind === "initial" && batches.length === 0 ? (
          <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-4 text-red-900">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
              <p className="min-w-0 break-words text-sm font-bold">{error.message}</p>
            </div>
            <button
              type="button"
              onClick={onRetry}
              className="mt-3 rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-black"
            >
              {copy.retry}
            </button>
          </div>
        ) : null}

        {!loading && !error && batches.length === 0 ? (
          <p className="rounded-2xl border border-slate-200 bg-slate-50 p-6 text-center text-sm font-bold text-slate-500">
            {copy.noBatches}
          </p>
        ) : null}

        {batches.length > 0 && !loading ? (
          <p role="note" className="text-xs font-semibold text-slate-600">{copy.freshnessNotice}</p>
        ) : null}

        {batches.map((batch) => {
          const expanded = sourceOpenId === batch.batch_id;
          const source = expanded ? sourceByBatch[batch.batch_id] : undefined;
          const evidenceId = `live-stock-source-${product.id}-${batch.batch_id}`;
          return (
            <article
              key={batch.batch_id}
              className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-black text-slate-900">
                    {batch.batch_number ?? copy.noLot}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs font-semibold text-slate-500">
                    <span>{copy.production}: {dateText(batch.production_date, locale)}</span>
                    <span>{copy.expiry}: {dateText(batch.expiry_date, locale)}</span>
                  </div>
                </div>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-black text-slate-700">
                  {copy.dispositionLabels[batch.disposition]}
                </span>
              </div>

              <dl className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 xl:grid-cols-5">
                {[
                  [t("inventoryLive.onHand"), batch.on_hand_quantity],
                  [t("inventoryLive.reserved"), batch.reserved_quantity],
                  [t("inventoryLive.availableForSale"), batch.available_for_sale_quantity],
                  [t("inventoryLive.unavailable"), batch.unavailable_quantity],
                  [t("inventoryLive.indicatorDamaged"), batch.damaged_quantity],
                  [copy.stockStatusLabels.QUARANTINED, batch.quarantined_quantity],
                  [copy.stockStatusLabels.BLOCKED, batch.blocked_quantity],
                  [copy.stockStatusLabels.RECALLED, batch.recalled_quantity],
                  [copy.stockStatusLabels.DISPOSAL_PENDING, batch.disposal_pending_quantity],
                ].map(([label, value]) => {
                  const rendered = quantity(value as Quantity);
                  return (
                    <div key={String(label)} className="rounded-xl bg-slate-50 px-3 py-2">
                      <dt className="text-[10px] font-bold text-slate-500">{label}</dt>
                      <dd
                        className="mt-1 font-black tabular-nums text-slate-900"
                        dir="ltr"
                        title={rendered.secondary ?? undefined}
                      >
                        {rendered.primary}
                      </dd>
                    </div>
                  );
                })}
              </dl>

              <div className="mt-3 border-t border-slate-100 pt-3">
                <button
                  type="button"
                  onClick={() => onLoadSource(batch.batch_id)}
                  aria-expanded={expanded}
                  aria-controls={source ? evidenceId : undefined}
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-black text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                >
                  <ChevronDown className="h-4 w-4" aria-hidden="true" />
                  {copy.sourceEvidence}
                </button>

                {expanded && sourceLoadingId === batch.batch_id ? (
                  <p role="status" className="mt-2 text-xs font-bold text-slate-500">
                    {copy.sourceLoading}
                  </p>
                ) : null}
                {expanded && sourceErrorId === batch.batch_id ? (
                  <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 text-xs font-bold text-red-700">
                    <span>{copy.sourceUnavailable}</span>
                    <button
                      type="button"
                      onClick={() => (onRetrySource ?? onLoadSource)(batch.batch_id)}
                      className="rounded-md border border-red-200 bg-white px-2 py-1"
                    >
                      {copy.retry}
                    </button>
                  </div>
                ) : null}

                {source ? (
                  <div id={evidenceId} className="mt-3 space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
                    <p className="text-xs font-black text-slate-800">
                      {copy.sourceWarehouse}: {source.location_name}
                    </p>
                    {source.statuses.map((status) => (
                      <div key={status.stock_status} className="rounded-lg bg-white p-3 text-xs">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <strong>{copy.stockStatusLabels[status.stock_status]}</strong>
                          <span className="tabular-nums" dir="ltr">
                            {t("inventoryLive.onHand")}: {quantityText(status.on_hand_quantity)} · {t("inventoryLive.reserved")}: {quantityText(status.reserved_quantity)}
                          </span>
                        </div>
                        <div className="mt-2 text-[11px] font-semibold text-slate-600">
                          <span>{copy.reservationCoverage[status.reservation_evidence.coverage]}</span>
                          {status.reservation_evidence.owners.length > 0 ? (
                            <span className="ms-2">
                              {copy.reservationOwners}: {new Intl.NumberFormat(locale, { numberingSystem: "latn" }).format(status.reservation_evidence.owners.length)}
                            </span>
                          ) : null}
                          {status.reservation_evidence.unattributed_quantity !== "0" ? (
                            <span className="ms-2 tabular-nums" dir="ltr">
                              {copy.unattributedReservation}: {quantityText(status.reservation_evidence.unattributed_quantity)}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </article>
          );
        })}

        {error?.kind === "continuation" ? (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-bold text-amber-900">
            <span>{copy.continuationFailed}</span>
            <button type="button" onClick={onRetry} className="rounded-lg border border-amber-300 bg-white px-3 py-2">
              {copy.retry}
            </button>
          </div>
        ) : null}

        {hasMore && !error ? (
          <button
            type="button"
            onClick={onLoadMore}
            disabled={loading}
            className="mx-auto flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-black text-slate-700 disabled:opacity-50"
          >
            {loading ? <RefreshCcw className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            {copy.loadMore}
          </button>
        ) : null}
      </div>
    </Modal>
  );
}
