import { useTranslation } from "react-i18next";

import { resolveI18nLocale } from "@/lib/locale";
import { BatchQuantityActions } from "../batches/BatchQuantityActions";
import type { BatchSpecialTransferResult } from "../batches/batchSpecialTransferContract";
import type { BatchStockSources, ReservationOwner } from "../batches/batchStockSourcesContract";

/** Present the existing server-owned source/action projection without another navigation layer. */
export function WholeProductIssueBatchSection({ batch, onRefresh, onOpenTransfers, onOpenReservationOwner, onConfigureQualityDestinations, suppressDestinationSetupPrompt }: {
  batch: BatchStockSources;
  onRefresh: () => Promise<void>;
  onOpenTransfers: (transfer: BatchSpecialTransferResult) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
  onConfigureQualityDestinations?: () => void;
  suppressDestinationSetupPrompt?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const titleId = `whole-product-batch-${batch.batch_id}`;
  const expiry = batch.batch.expiry_date;
  const date = expiry ? new Intl.DateTimeFormat(resolveI18nLocale(i18n), { dateStyle: "medium", timeZone: "UTC" })
    .format(new Date(`${expiry}T00:00:00Z`)) : t("batchFocus.noExpiry");

  return <section aria-labelledby={titleId} className="space-y-2 rounded-xl border border-border bg-card p-3 text-card-foreground">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h3 id={titleId} className="text-xs font-black">{t("inventoryQualityIssue.batchTitle", { batch: batch.batch.batch_number })}</h3>
        {batch.batch.disposition !== "RELEASED" ? (
          <span className="text-[10px] font-bold text-amber-800">
            {t(`inventoryQualityIssue.dispositions.${batch.batch.disposition}`)}
          </span>
        ) : null}
        {batch.batch.disposition !== "RELEASED" && batch.batch.disposition_reason ? (
          <span className="text-[10px] text-muted-foreground">
            {t("inventoryBatches.disposition.reasonDisplay", { reason: batch.batch.disposition_reason })}
          </span>
        ) : null}
      </div>
      <p className="text-[10px] text-muted-foreground">{t("inventoryQualityIssue.expiry", { date })}</p>
    </div>

    <BatchQuantityActions batch={batch.batch} productVariantId={batch.product_variant_id} baseUomCode={batch.base_uom_code}
      stockSources={batch} onRefreshStockSources={onRefresh} onChanged={async () => {}} showTransferListLink={false}
      header={<h4 className="text-xs font-black">{t("productQualityWorkspace.actionsTitle")}</h4>}
      onOpenTransfers={(transfer) => { if (transfer) return onOpenTransfers(transfer); }}
      onOpenReservationOwner={onOpenReservationOwner} onConfigureQualityDestinations={onConfigureQualityDestinations}
      suppressDestinationSetupPrompt={suppressDestinationSetupPrompt} />
  </section>;
}
