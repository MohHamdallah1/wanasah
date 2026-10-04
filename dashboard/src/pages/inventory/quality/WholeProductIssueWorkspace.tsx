import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import type { BatchSpecialTransferResult } from "../batches/batchSpecialTransferContract";
import type { ReservationOwner } from "../batches/batchStockSourcesContract";
import { useWholeProductIssueSources } from "./useWholeProductIssueSources";
import { WholeProductIssueBatchSection } from "./WholeProductIssueBatchSection";

/** Inventory-owned hierarchy; Catalog hold and actions come from fresh reads. */
export function WholeProductIssueWorkspace({ productVariantId, productName, onConsumed, onClose, onOpenTransfers, onOpenReservationOwner }: {
  productVariantId: number;
  productName: string;
  onConsumed: () => void;
  onClose: () => void;
  onOpenTransfers: (transfer: BatchSpecialTransferResult) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
}) {
  const { t, i18n } = useTranslation();
  const access = useInventoryAccess();
  const query = useWholeProductIssueSources(productVariantId);
  const heading = useRef<HTMLHeadingElement>(null);
  const consumed = useRef(false);
  const fresh = access.isFetchedAfterMount && query.isFetchedAfterMount;
  const pages = fresh && !access.isError && !query.isError ? query.data?.pages : undefined;
  const mismatch = pages?.some((page) => page.product_variant_id !== productVariantId) ?? false;
  const failed = access.isError || (fresh && query.isError) || mismatch;
  const ready = pages !== undefined && pages.length > 0 && !mismatch;
  const batches = ready ? pages.flatMap((page) => page.batches) : [];
  const refresh = async () => { await query.refetch(); };
  const count = new Intl.NumberFormat(resolveI18nLocale(i18n)).format(batches.length);

  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => {
    if (consumed.current || (!ready && !failed)) return;
    consumed.current = true;
    onConsumed();
  }, [failed, onConsumed, ready]);

  return <section aria-labelledby="product-quality-heading" dir={i18n.dir()} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-1">
    <header className="flex flex-wrap items-start justify-between gap-2 rounded-xl border border-border bg-card p-3 text-card-foreground">
      <h1 id="product-quality-heading" ref={heading} tabIndex={-1} className="text-base font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {t("productQualityWorkspace.title")}
      </h1>
      <button type="button" onClick={onClose} className="rounded-lg border border-border px-3 py-2 text-xs focus-visible:ring-2 focus-visible:ring-ring">
        {t("batchFocus.back")}
      </button>
    </header>
    {failed ? <div role="alert" className="rounded-xl border border-destructive p-3 text-sm">
      <p>{mismatch ? t("productQualityWorkspace.scopeMismatch") : apiErrorMessage(access.error ?? query.error, t("inventoryQualityIssue.errors.load"))}</p>
      <button type="button" onClick={() => void (access.isError ? access.refetch() : refresh())} disabled={query.isFetching}
        className="mt-2 rounded-lg border border-border px-3 py-2 focus-visible:ring-2 focus-visible:ring-ring">{t("common.retry")}</button>
    </div> : !ready ? <p role="status">{t("inventoryQualityIssue.loading")}</p> : <>
      <div className="space-y-1 rounded-xl border border-border bg-card p-3 text-card-foreground">
        <h2 className="text-sm font-bold">{t("productQualityWorkspace.product", { name: productName })}</h2>
        <p className="text-sm font-semibold">{t("inventoryQualityIssue.companyHoldTitle")}</p>
        <p className="text-xs text-muted-foreground">{t("productQualityWorkspace.catalogContext")}</p>
      </div>
      <section aria-labelledby="product-quality-batches" className="space-y-3">
        <h2 id="product-quality-batches" className="text-sm font-bold">{t("productQualityWorkspace.batches", { count })}</h2>
        {batches.length === 0 && <p className="text-sm text-muted-foreground">{t("productQualityWorkspace.noVisibleStock")}</p>}
        {batches.map((batch) => <WholeProductIssueBatchSection key={batch.batch_id} batch={batch} onRefresh={refresh}
          onOpenTransfers={onOpenTransfers} onOpenReservationOwner={onOpenReservationOwner} />)}
      </section>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => void refresh()} disabled={query.isFetching}
          className="rounded-lg border border-border px-3 py-2 text-xs focus-visible:ring-2 focus-visible:ring-ring">{t("common.refresh")}</button>
        {query.hasNextPage && <button type="button" onClick={() => void query.fetchNextPage()} disabled={query.isFetching}
          className="rounded-lg border border-border px-3 py-2 text-xs focus-visible:ring-2 focus-visible:ring-ring">
          {query.isFetchingNextPage ? t("common.loading") : t("inventoryQualityIssue.loadMore")}
        </button>}
      </div>
    </>}
  </section>;
}
