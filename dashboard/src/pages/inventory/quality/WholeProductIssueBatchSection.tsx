import { useTranslation } from "react-i18next";

import { resolveI18nLocale } from "@/lib/locale";
import { BatchQuantityActions } from "../batches/BatchQuantityActions";
import type { BatchSpecialTransferResult } from "../batches/batchSpecialTransferContract";
import type { BatchStockSources, ReservationOwner } from "../batches/batchStockSourcesContract";

/** Present the existing source/action projection, without a per-batch read. */
export function WholeProductIssueBatchSection({ batch, onRefresh, onOpenTransfers, onOpenReservationOwner, onConfigureQualityDestinations }: {
  batch: BatchStockSources;
  onRefresh: () => Promise<void>;
  onOpenTransfers: (transfer: BatchSpecialTransferResult) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
  onConfigureQualityDestinations?: () => void;
}) {
  const { t, i18n } = useTranslation();
  const titleId = `whole-product-batch-${batch.batch_id}`;
  const expiry = batch.batch.expiry_date;
  const date = expiry ? new Intl.DateTimeFormat(resolveI18nLocale(i18n), { dateStyle: "medium", timeZone: "UTC" })
    .format(new Date(`${expiry}T00:00:00Z`)) : t("batchFocus.noExpiry");
  return <section aria-labelledby={titleId} className="space-y-3 rounded-xl border border-border bg-card p-3 text-card-foreground">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div>
        <h3 id={titleId} className="text-sm font-bold">{t("inventoryQualityIssue.batchTitle", { batch: batch.batch.batch_number })}</h3>
        <p className="text-xs text-muted-foreground">{t(`inventoryQualityIssue.dispositions.${batch.batch.disposition}`)}</p>
        {batch.batch.disposition !== "RELEASED" && batch.batch.disposition_reason ? (
          <p className="text-xs">
            {t("inventoryBatches.disposition.reasonDisplay", { reason: batch.batch.disposition_reason })}
          </p>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">{t("inventoryQualityIssue.expiry", { date })}</p>
    </div>
    <BatchQuantityActions batch={batch.batch} productVariantId={batch.product_variant_id} baseUomCode={batch.base_uom_code}
      stockSources={batch} onRefreshStockSources={onRefresh} onChanged={async () => {}} showTransferListLink={false}
      header={<div>
        <h4 className="text-xs font-bold">{t("productQualityWorkspace.sources")}</h4>
        <p className="text-xs text-muted-foreground">{t("productQualityWorkspace.sourceScope")}</p>
      </div>}
      onOpenTransfers={(transfer) => { if (transfer) return onOpenTransfers(transfer); }}
      onOpenReservationOwner={onOpenReservationOwner} onConfigureQualityDestinations={onConfigureQualityDestinations} />
  </section>;
}
