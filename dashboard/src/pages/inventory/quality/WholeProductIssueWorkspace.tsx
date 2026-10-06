import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import type { BatchSpecialTransferResult } from "../batches/batchSpecialTransferContract";
import type { ReservationOwner } from "../batches/batchStockSourcesContract";
import { useWholeProductIssueSources } from "./useWholeProductIssueSources";
import { WholeProductIssueBatchSection } from "./WholeProductIssueBatchSection";
import { ProductQualityReadiness } from "./ProductQualityReadiness";

/** Inventory-owned hierarchy; Catalog hold and actions come from fresh reads. */
export function WholeProductIssueWorkspace({ productVariantId, productName, onConsumed, onClose, onOpenQualitySettings, onOpenTransfers, onOpenReservationOwner }: {
  productVariantId: number;
  productName: string;
  onConsumed: () => void;
  onClose: () => void;
  onOpenQualitySettings: () => void;
  onOpenTransfers: (transfer: BatchSpecialTransferResult) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
}) {
  const { t, i18n } = useTranslation();
  const access = useInventoryAccess();
  const canManageQualitySettings =
    access.isCompanyAdmin || access.can("inventory.transfer_policy.manage");
  const query = useWholeProductIssueSources(productVariantId);
  const heading = useRef<HTMLHeadingElement>(null);
  const consumed = useRef(false);
  const fresh = access.isFetchedAfterMount && query.isFetchedAfterMount;
  const pages = fresh && !access.isError && !query.isError ? query.data?.pages : undefined;
  const mismatch = pages?.some((page) => page.product_variant_id !== productVariantId) ?? false;
  const failed = access.isError || (fresh && query.isError) || mismatch;
  const ready = pages !== undefined && pages.length > 0 && !mismatch;
  const batches = ready ? pages.flatMap((page) => page.batches) : [];
  const inventorySummary = ready ? pages[pages.length - 1]?.inventory_summary : undefined;
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
      <div className="flex flex-wrap items-center gap-2">
        {canManageQualitySettings ? (
          <button type="button" onClick={onOpenQualitySettings} className="rounded-lg border border-border px-3 py-2 text-xs focus-visible:ring-2 focus-visible:ring-ring">
            {t("productQualityWorkspace.configureDestinations")}
          </button>
        ) : null}
        <button type="button" onClick={onClose} className="rounded-lg border border-border px-3 py-2 text-xs focus-visible:ring-2 focus-visible:ring-ring">
          {t("batchFocus.back")}
        </button>
      </div>
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
      {inventorySummary ? (
        <section className="rounded-xl border border-border bg-card p-3 text-card-foreground" aria-labelledby="product-quality-inventory-summary">
          <h2 id="product-quality-inventory-summary" className="text-sm font-black">
            {t("productQualityWorkspace.inventorySummaryTitle")}
          </h2>
          <p className="mt-1 text-xs font-semibold text-slate-700">
            {t("productQualityWorkspace.inventorySummary", {
              onHand: inventorySummary.total_on_hand_quantity,
              reserved: inventorySummary.total_reserved_quantity,
              sources: String(inventorySummary.source_count),
              batches: String(inventorySummary.batch_count),
              unit: pages[pages.length - 1].base_uom_code,
            })}
          </p>
          {inventorySummary.locations_preview.length > 0 ? (
            <div className="mt-2 grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
              {inventorySummary.locations_preview.map((location) => (
                <p key={location.location_id} className="rounded-lg bg-muted/40 px-2.5 py-2 text-[11px] font-semibold text-muted-foreground">
                  {t("productQualityWorkspace.locationSummary", {
                    name: location.location_name,
                    onHand: location.on_hand_quantity,
                    reserved: location.reserved_quantity,
                    unit: pages[pages.length - 1].base_uom_code,
                  })}
                </p>
              ))}
            </div>
          ) : null}
          {inventorySummary.locations_truncated ? (
            <p className="mt-2 text-[11px] font-semibold text-muted-foreground">{t("productQualityWorkspace.moreLocations")}</p>
          ) : null}
          {inventorySummary.total_reserved_quantity !== "0" ? (
            <p className="mt-2 rounded-lg border border-sky-100 bg-sky-50/70 px-3 py-2 text-[11px] font-semibold leading-5 text-sky-950">
              {t("productQualityWorkspace.reservationMeaning")}
            </p>
          ) : null}
        </section>
      ) : null}
      {/* Each page carries a fresh company-wide check; use the latest response, not row totals. */}
      <ProductQualityReadiness evidence={pages[pages.length - 1]} checking={query.isFetching || access.isFetching} />
      <section aria-labelledby="product-quality-batches" className="space-y-3">
        <h2 id="product-quality-batches" className="text-sm font-bold">{t("productQualityWorkspace.batches", { count })}</h2>
        {batches.length === 0 && <p className="text-sm text-muted-foreground">{t("productQualityWorkspace.noVisibleStock")}</p>}
        {batches.map((batch) => <WholeProductIssueBatchSection key={batch.batch_id} batch={batch} onRefresh={refresh}
          onOpenTransfers={onOpenTransfers} onOpenReservationOwner={onOpenReservationOwner}
          onConfigureQualityDestinations={canManageQualitySettings ? onOpenQualitySettings : undefined} />)}
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
