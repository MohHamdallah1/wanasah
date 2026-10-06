import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import type { BatchSpecialTransferResult } from "../batches/batchSpecialTransferContract";
import type { ReservationOwner } from "../batches/batchStockSourcesContract";
import { useWholeProductIssueSources } from "./useWholeProductIssueSources";
import { WholeProductIssueBatchSection } from "./WholeProductIssueBatchSection";

/** Inventory owns physical handling; this workspace exposes the next valid action directly. */
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
  const refresh = async () => { await query.refetch(); };
  const needsDestinationSetup = batches.some((batch) =>
    batch.sources.some((source) =>
      source.statuses.some((status) =>
        status.special_actions.some(
          (action) => action.reason_code === "NO_CONFIGURED_DESTINATION",
        ),
      ),
    ),
  );

  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => {
    if (consumed.current || (!ready && !failed)) return;
    consumed.current = true;
    onConsumed();
  }, [failed, onConsumed, ready]);

  return <section aria-labelledby="product-quality-heading" dir={i18n.dir()} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-1">
    <header className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-border bg-card p-3 text-card-foreground">
      <div className="min-w-0">
        <h1 id="product-quality-heading" ref={heading} tabIndex={-1} className="text-base font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {t("productQualityWorkspace.title")}
        </h1>
        <p className="mt-1 truncate text-xs font-semibold text-muted-foreground">
          {t("productQualityWorkspace.product", { name: productName })}
        </p>
      </div>
      <button type="button" onClick={onClose} className="rounded-lg border border-border px-3 py-2 text-xs font-bold focus-visible:ring-2 focus-visible:ring-ring">
        {t("batchFocus.back")}
      </button>
    </header>

    {failed ? <div role="alert" className="rounded-xl border border-destructive p-3 text-sm">
      <p>{mismatch ? t("productQualityWorkspace.scopeMismatch") : apiErrorMessage(access.error ?? query.error, t("inventoryQualityIssue.errors.load"))}</p>
      <button type="button" onClick={() => void (access.isError ? access.refetch() : refresh())} disabled={query.isFetching}
        className="mt-2 rounded-lg border border-border px-3 py-2 focus-visible:ring-2 focus-visible:ring-ring">{t("common.retry")}</button>
    </div> : !ready ? <p role="status">{t("inventoryQualityIssue.loading")}</p> : <>
      {needsDestinationSetup ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50/70 px-3 py-2.5 text-amber-950">
          <p className="text-[10px] font-bold leading-5">
            {t("productQualityWorkspace.setupOnce")}
          </p>
          {canManageQualitySettings ? (
            <button type="button" onClick={onOpenQualitySettings}
              className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-[9px] font-black focus-visible:ring-2 focus-visible:ring-amber-300">
              {t("productQualityWorkspace.configureDestinations")}
            </button>
          ) : null}
        </div>
      ) : null}

      {batches.length === 0 ? (
        <p className="rounded-xl border border-border bg-card p-3 text-sm text-muted-foreground">
          {t("productQualityWorkspace.noVisibleStock")}
        </p>
      ) : (
        <div className="space-y-3">
          {batches.map((batch) => <WholeProductIssueBatchSection key={batch.batch_id} batch={batch} onRefresh={refresh}
            onOpenTransfers={onOpenTransfers} onOpenReservationOwner={onOpenReservationOwner}
            onConfigureQualityDestinations={canManageQualitySettings ? onOpenQualitySettings : undefined}
            suppressDestinationSetupPrompt={needsDestinationSetup} />)}
        </div>
      )}

      {query.hasNextPage ? (
        <button type="button" onClick={() => void query.fetchNextPage()} disabled={query.isFetching}
          className="self-start rounded-lg border border-border px-3 py-2 text-xs font-bold focus-visible:ring-2 focus-visible:ring-ring">
          {query.isFetchingNextPage ? t("common.loading") : t("inventoryQualityIssue.loadMore")}
        </button>
      ) : null}
    </>}
  </section>;
}
