import { AlertTriangle, ChevronDown, Info, RefreshCcw } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  compareQuantity,
  formatCommercialQuantity,
  subtractQuantity,
  type Quantity,
} from "@/lib/quantity";
import { resolveI18nLocale } from "@/lib/locale";
import type {
  WarehouseBatchInventoryItem,
  WarehouseProduct,
} from "./contracts";
import { getLiveStockCp7Copy } from "./i18n";
import type {
  LiveStockProductSaleGate,
  LiveStockWarehouseSource,
} from "./sourceContract";

type Props = {
  product: WarehouseProduct | null;
  batches: WarehouseBatchInventoryItem[];
  mode?: "details" | "unavailable";
  saleGate?: LiveStockProductSaleGate | null;
  saleGateLoading?: boolean;
  saleGateError?: boolean;
  hasMore: boolean;
  loading: boolean;
  error: { message: string; kind: "initial" | "continuation" } | null;
  sourceByBatch: Record<number, LiveStockWarehouseSource>;
  sourceOpenId?: number | null;
  sourceLoadingId: number | null;
  sourceErrorId: number | null;
  onClose: () => void;
  onRetry: () => void;
  onRefresh?: () => void;
  refreshing?: boolean;
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
  mode = "details",
  saleGate = null,
  saleGateLoading = false,
  saleGateError = false,
  hasMore,
  loading,
  error,
  sourceByBatch,
  sourceOpenId = null,
  sourceLoadingId,
  sourceErrorId,
  onClose,
  onRetry,
  onRefresh,
  refreshing = false,
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
  const displayedBatches =
    mode === "unavailable"
      ? batches.filter(
          (batch) => compareQuantity(batch.unavailable_quantity, "0") > 0,
        )
      : batches;
  const productGateText =
    saleGateLoading
      ? copy.productGateLoading
      : saleGateError || saleGate === null
        ? copy.productGateUnavailable
        : saleGate.operational_hold !== "NONE"
          ? copy.holdLabels[saleGate.operational_hold]
          : saleGate.lifecycle_status !== "ACTIVE"
            ? copy.lifecycleLabels[saleGate.lifecycle_status]
            : copy.productGateClear;

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`${mode === "unavailable" ? copy.unavailableBreakdown : copy.batchDetails} — ${product.name}`}
      subtitle={product.sku ? `${product.sku} · ${product.family_name}` : product.family_name}
      maxWidth="max-w-5xl"
      bodyClassName="p-3 sm:p-5"
    >
      <div
        className="space-y-3"
        data-testid="live-stock-batch-detail"
        data-live-stock-detail-mode={mode}
      >
        {onRefresh ? (
          <div className="flex justify-end">
            <button type="button" onClick={onRefresh} disabled={refreshing}
              aria-label={t("inventoryShell.refreshNow")}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold focus-visible:ring-2 focus-visible:ring-amber-400 disabled:opacity-60">
              <RefreshCcw className="h-4 w-4" aria-hidden="true" />
              {t("inventoryShell.refreshNow")}
            </button>
          </div>
        ) : null}
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
          <>
            <p role="note" className="text-xs font-semibold text-slate-600">{copy.freshnessNotice}</p>
            {mode === "unavailable" ? (
              <>
                <section
                  className="rounded-xl border border-rose-200 bg-rose-50/70 p-3"
                  data-live-stock-unavailable-summary="true"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <span className="text-xs font-black text-rose-950">
                      {copy.unavailableTotal}
                    </span>
                    <strong
                      className="tabular-nums text-sm text-rose-950"
                      dir="ltr"
                    >
                      {quantityText(product.unavailable_quantity)}
                    </strong>
                  </div>
                  <div className="mt-2 text-xs font-semibold text-rose-900">
                    <span className="font-black">{copy.productSaleGate}: </span>
                    <span>{productGateText}</span>
                  </div>
                </section>
                <p role="note" className="rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs font-semibold text-amber-950"
                  data-live-stock-unavailable-explanation="true">
                  {copy.unavailableBreakdownNote}
                </p>
              </>
            ) : null}
          </>
        ) : null}

        {mode === "unavailable" && batches.length > 0 &&
        displayedBatches.length === 0 && !loading ? (
          <p
            role="note"
            className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs font-semibold text-amber-900"
          >
            {copy.unavailableNoAffectedBatches}
          </p>
        ) : null}

        {displayedBatches.map((batch) => {
          const expanded = sourceOpenId === batch.batch_id;
          const source = expanded ? sourceByBatch[batch.batch_id] : undefined;
          const evidenceId = `live-stock-source-${product.id}-${batch.batch_id}`;
          const otherRestriction = subtractQuantity(
            batch.restricted_quantity,
            batch.expiry_unavailable_quantity,
          );
          const otherRestrictionLabel =
            saleGate?.operational_hold &&
            saleGate.operational_hold !== "NONE"
              ? copy.holdLabels[saleGate.operational_hold]
              : saleGate?.lifecycle_status &&
                  saleGate.lifecycle_status !== "ACTIVE"
                ? copy.lifecycleLabels[saleGate.lifecycle_status]
                : batch.disposition !== "RELEASED"
                  ? `${copy.disposition}: ${copy.dispositionLabels[batch.disposition]}`
                  : copy.otherSaleRestriction;
          const unavailableCauseCandidates: Array<[string, Quantity]> = [
            [copy.expiryUnavailable, batch.expiry_unavailable_quantity],
            [copy.stockStatusLabels.QUARANTINED, batch.quarantined_quantity],
            [copy.stockStatusLabels.BLOCKED, batch.blocked_quantity],
            [copy.stockStatusLabels.RECALLED, batch.recalled_quantity],
            [copy.stockStatusLabels.DAMAGED, batch.damaged_quantity],
            [copy.stockStatusLabels.DISPOSAL_PENDING, batch.disposal_pending_quantity],
            [otherRestrictionLabel, otherRestriction],
          ];
          const unavailableCauses = unavailableCauseCandidates.filter(
            ([, value]) => compareQuantity(value, "0") > 0,
          );
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
              {batch.disposition_reason ? (
                <p className="mt-2 break-words text-xs font-semibold text-amber-900">
                  {copy.dispositionReason}: {batch.disposition_reason}
                </p>
              ) : null}

              {mode === "unavailable" && unavailableCauses.length > 0 ? (
                <div className="mt-3 rounded-xl border border-rose-100 bg-rose-50/60 p-3">
                  <p className="text-[11px] font-black text-rose-900">
                    {copy.unavailableCauses}
                  </p>
                  <dl className="mt-2 grid gap-1.5 sm:grid-cols-2">
                    {unavailableCauses.map(([label, value]) => (
                      <div
                        key={label}
                        className="flex items-center justify-between gap-3 rounded-lg bg-white px-2.5 py-2"
                      >
                        <dt className="text-[11px] font-semibold text-slate-700">
                          {label}
                        </dt>
                        <dd className="shrink-0 text-xs font-black tabular-nums text-rose-900" dir="ltr">
                          {quantityText(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ) : null}

              <dl className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 xl:grid-cols-5">
                {[
                  [t("inventoryLive.onHand"), batch.on_hand_quantity],
                  [t("inventoryLive.reserved"), batch.reserved_quantity],
                  [t("inventoryLive.availableForSale"), batch.available_for_sale_quantity],
                  [t("inventoryLive.unavailable"), batch.unavailable_quantity],
                  [copy.restrictedQuantity, batch.restricted_quantity],
                  [copy.expiryUnavailable, batch.expiry_unavailable_quantity],
                  [t("inventoryLive.indicatorDamaged"), batch.damaged_quantity],
                  [copy.stockStatusLabels.QUARANTINED, batch.quarantined_quantity],
                  [copy.stockStatusLabels.BLOCKED, batch.blocked_quantity],
                  [copy.stockStatusLabels.RECALLED, batch.recalled_quantity],
                  [copy.stockStatusLabels.DISPOSAL_PENDING, batch.disposal_pending_quantity],
                ].map(([label, value]) => {
                  const rendered = quantity(value as Quantity);
                  return (
                    <div key={String(label)} className="rounded-xl bg-slate-50 px-3 py-2">
                      <dt className="text-[10px] font-bold text-slate-500">
                        {label}
                        {label === copy.restrictedQuantity ? (
                          <TooltipProvider delayDuration={180}>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <button type="button"
                                  className="ms-1 inline-flex h-5 w-5 items-center justify-center rounded-full align-middle text-slate-500 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                                  aria-label={copy.restrictedQuantityHelp}
                                >
                                  <Info className="h-3.5 w-3.5" aria-hidden="true" />
                                </button>
                              </TooltipTrigger>
                              <TooltipContent side="top" dir={i18n.dir()} className="max-w-xs text-xs leading-5">
                                {copy.restrictedQuantityHelp}
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        ) : null}
                      </dt>
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
                    <p role="note" className="text-[11px] font-semibold text-slate-600">
                      {copy.sourceScopeNotice}
                    </p>
                    <p className="text-xs font-black text-slate-800">
                      {copy.sourceWarehouse}: {source.location_name}
                    </p>
                    {source.statuses.map((status) => (
                      <div key={status.stock_status} className="rounded-lg bg-white p-3 text-xs">
                        <strong>{copy.stockStatusLabels[status.stock_status]}</strong>
                        <dl className="mt-2 grid grid-cols-1 gap-1.5 sm:grid-cols-3">
                          {[
                            [t("inventoryLive.onHand"), status.on_hand_quantity],
                            [t("inventoryLive.reserved"), status.reserved_quantity],
                            [copy.movableQuantity, status.movable_quantity],
                          ].map(([label, value]) => (
                            <div key={String(label)} className="rounded-md bg-slate-50 px-2 py-1.5">
                              <dt className="font-semibold text-slate-500">{label}</dt>
                              <dd className="mt-0.5 font-black tabular-nums text-slate-900" dir="ltr">
                                {quantityText(value as Quantity)}
                              </dd>
                            </div>
                          ))}
                        </dl>
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
                        {status.reservation_evidence.owners.length > 0 ? (
                          <ul
                            aria-label={copy.reservationOwners}
                            className="mt-2 space-y-1.5"
                          >
                            {status.reservation_evidence.owners.map((owner) => {
                              const amount = quantity(owner.quantity);
                              return (
                                <li
                                  key={owner.transfer_id}
                                  className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-md border border-slate-100 bg-slate-50 px-2.5 py-1.5"
                                >
                                  <span className="min-w-0 break-words font-semibold text-slate-700">
                                    {copy.reservationReference}: <bdi>{owner.reference_number}</bdi>
                                  </span>
                                  <span
                                    className="shrink-0 font-black tabular-nums text-slate-900"
                                    dir="auto"
                                    title={amount.secondary ?? undefined}
                                  >
                                    {amount.primary}
                                  </span>
                                </li>
                              );
                            })}
                          </ul>
                        ) : status.reservation_evidence.coverage !== "NONE" ? (
                          <p className="mt-2 text-[11px] font-semibold text-slate-500">
                            {copy.noKnownReservationOwners}
                          </p>
                        ) : null}
                        {status.reservation_evidence.owners_truncated ? (
                          <p role="note" className="mt-2 rounded-md bg-amber-50 px-2.5 py-2 text-[11px] font-semibold text-amber-900">
                            {copy.reservationOwnersTruncated}
                          </p>
                        ) : null}
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
