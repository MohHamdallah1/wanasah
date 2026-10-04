import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { BatchFocusIdentity } from "@/features/inventory/batchFocusNavigation";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import { BatchDispositionManager } from "./BatchDispositionManager";
import { BatchQuantityActions } from "./BatchQuantityActions";
import type { BatchSpecialTransferResult } from "./batchSpecialTransferContract";
import type { ReservationOwner } from "./batchStockSourcesContract";
import { useBatchStockSources } from "./useBatchStockSources";

/** Batch identity is independent of the Inventory shell's warehouse preference. */
export function BatchFocusWorkspace({ identity, onConsumed, onClose, onOpenTransfers, onOpenReservationOwner }: {
  identity: BatchFocusIdentity;
  onConsumed: () => void;
  onClose: () => void;
  onOpenTransfers: (transfer: BatchSpecialTransferResult) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
}) {
  const { t, i18n } = useTranslation();
  const access = useInventoryAccess();
  const query = useBatchStockSources(identity.batchId);
  const consumed = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const [editingDisposition, setEditingDisposition] = useState(false);
  // Never present a warm query-cache snapshot as destination authorization.
  const fresh = query.isFetchedAfterMount && access.isFetchedAfterMount;
  const data = fresh && !query.isError && !access.isError ? query.data : undefined;
  const mismatch = data !== undefined && (data.batch_id !== identity.batchId || data.product_variant_id !== identity.variantId);
  const ready = data !== undefined && !mismatch;
  const failed = access.isError || (fresh && query.isError) || mismatch;

  useEffect(() => {
    heading.current?.focus();
  }, []);
  useEffect(() => {
    if (consumed.current || (!ready && !failed)) return;
    consumed.current = true;
    onConsumed();
  }, [failed, onConsumed, ready]);

  const refresh = async () => { await query.refetch(); };
  const number = new Intl.NumberFormat(resolveI18nLocale(i18n));
  const date = (value: string | null) => value === null ? t("batchFocus.noExpiry") : new Intl.DateTimeFormat(
    resolveI18nLocale(i18n), { dateStyle: "medium", timeZone: "UTC" },
  ).format(new Date(`${value}T00:00:00Z`));
  const error = mismatch ? t("batchFocus.scopeMismatch") : apiErrorMessage(
    access.error ?? query.error, t("inventoryBatches.errors.focus"),
  );

  return <section className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-1" dir={i18n.dir()} aria-labelledby="batch-focus-heading">
    <header className="rounded-xl border border-slate-200 bg-white p-4">
      <h1 id="batch-focus-heading" ref={heading} tabIndex={-1} className="text-base font-black focus-visible:outline-none focus-visible:ring-2">
        {t("batchFocus.title")}
      </h1>
      <button type="button" onClick={onClose} className="mt-2 rounded-lg border px-3 py-2 text-sm focus-visible:ring-2">{t("batchFocus.back")}</button>
    </header>
    {failed ? <div role="alert" className="rounded-xl border border-rose-200 p-4">
      <p>{error}</p>
      <button type="button" onClick={() => void (access.isError ? access.refetch() : refresh())} disabled={query.isFetching} className="mt-2 rounded-lg border px-3 py-2 focus-visible:ring-2">{t("common.retry")}</button>
    </div> : !ready || !data ? <p role="status">{t("inventoryBatches.quantityActions.loading")}</p> : <>
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="font-bold">{data.batch.batch_number}</h2>
        <p>{t(`inventoryLive.batchDisposition.${data.batch.disposition}`)}</p>
        {data.batch.disposition_reason && <p>{t("inventoryBatches.disposition.reasonDisplay", { reason: data.batch.disposition_reason })}</p>}
        <p>{t("inventoryLive.expiryDate")}: {date(data.batch.expiry_date)}</p>
        <p className="mt-2 text-sm" role="status">{data.sources.length === 1
          ? t("batchFocus.singleSource", { source: data.sources[0].location_name })
          : data.sources.length > 1 ? t("batchFocus.multipleSources", { count: number.format(data.sources.length) })
            : t("batchFocus.noReadableStock")}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={() => void refresh()} disabled={query.isFetching} className="rounded-lg border px-3 py-2 text-sm focus-visible:ring-2">{t("common.refresh")}</button>
          {(access.isCompanyAdmin || access.can("batch.disposition")) && <button type="button" onClick={() => setEditingDisposition(true)} className="rounded-lg border px-3 py-2 text-sm focus-visible:ring-2">{t("batchFocus.changeDisposition")}</button>}
        </div>
      </div>
      <BatchQuantityActions batch={data.batch} productVariantId={data.product_variant_id} baseUomCode={data.base_uom_code}
        stockSources={data} onRefreshStockSources={refresh} onChanged={async () => {}} showTransferListLink={false}
        onOpenTransfers={(transfer) => { if (transfer) return onOpenTransfers(transfer); }} onOpenReservationOwner={onOpenReservationOwner} />
      {editingDisposition && <BatchDispositionManager batch={data.batch} productVariantId={data.product_variant_id}
        baseUomCode={data.base_uom_code} onClose={() => setEditingDisposition(false)} onChanged={refresh}
        showQuantityActions={false} onOpenTransfers={(transfer) => { if (transfer) return onOpenTransfers(transfer); }} onOpenReservationOwner={onOpenReservationOwner} />}
    </>}
  </section>;
}
