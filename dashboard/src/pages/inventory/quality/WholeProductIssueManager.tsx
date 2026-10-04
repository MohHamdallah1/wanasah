import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  RefreshCcw,
  ShieldAlert,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import { apiErrorMessage } from "@/lib/apiErrors";
import type { BatchSpecialTransferResult } from "../batches/batchSpecialTransferContract";
import type { ReservationOwner } from "../batches/batchStockSourcesContract";
import { BatchQuantityActions } from "../batches/BatchQuantityActions";
import { useWholeProductIssueSources } from "./useWholeProductIssueSources";

type Props = {
  isOpen: boolean;
  productVariantId: number | null;
  productName: string;
  onClose: () => void;
  onOpenTransfers: (
    transfer?: BatchSpecialTransferResult,
  ) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
};

const dispositionKey = (
  value: "RELEASED" | "QUARANTINED" | "BLOCKED" | "RECALLED",
) => `inventoryQualityIssue.dispositions.${value}`;

export function WholeProductIssueManager({
  isOpen,
  productVariantId,
  productName,
  onClose,
  onOpenTransfers,
  onOpenReservationOwner,
}: Props) {
  const { t } = useTranslation();
  const query = useWholeProductIssueSources(
    isOpen ? productVariantId : null,
  );
  const pages = query.data?.pages ?? [];
  const batches = pages.flatMap((page) => page.batches);
  const firstPage = pages[0] ?? null;

  const refresh = async () => {
    await query.refetch();
  };

  return (
    <Modal
      isOpen={isOpen && productVariantId !== null}
      onClose={onClose}
      title={t("inventoryQualityIssue.title", { name: productName })}
      maxWidth="max-w-5xl"
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
          <p className="text-[11px] font-black text-slate-950">
            {t("inventoryQualityIssue.companyHoldTitle")}
          </p>
          <p className="mt-1 text-[10px] font-semibold leading-5 text-slate-600">
            {t("inventoryQualityIssue.companyHoldHint")}
          </p>
        </div>

        {firstPage ? (
          <div
            className={`rounded-xl border p-3 ${
              firstPage.ready_to_resume_sales
                ? "border-emerald-200 bg-emerald-50/70"
                : "border-amber-200 bg-amber-50/70"
            }`}
          >
            <div className="flex items-start gap-2">
              {firstPage.ready_to_resume_sales ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" />
              ) : (
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
              )}
              <div>
                <p className="text-[11px] font-black text-slate-950">
                  {t(
                    firstPage.ready_to_resume_sales
                      ? "inventoryQualityIssue.readiness.readyTitle"
                      : "inventoryQualityIssue.readiness.pendingTitle",
                  )}
                </p>
                <p className="mt-1 text-[9px] font-semibold leading-4 text-slate-600">
                  {t(
                    firstPage.ready_to_resume_sales
                      ? "inventoryQualityIssue.readiness.readyHint"
                      : "inventoryQualityIssue.readiness.pendingHint",
                  )}
                </p>
              </div>
            </div>
          </div>
        ) : null}

        {query.isLoading ? (
          <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-200 p-8 text-xs font-bold text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("inventoryQualityIssue.loading")}
          </div>
        ) : null}

        {query.isError ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50/70 p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose-700" />
              <p className="text-[10px] font-bold leading-5 text-rose-800">
                {apiErrorMessage(
                  query.error,
                  t("inventoryQualityIssue.errors.load"),
                )}
              </p>
            </div>
            <button
              type="button"
              onClick={() => void refresh()}
              className="mt-2 inline-flex items-center gap-1.5 text-[10px] font-black text-rose-800 underline underline-offset-4"
            >
              <RefreshCcw className="h-3.5 w-3.5" />
              {t("common.retry")}
            </button>
          </div>
        ) : null}

        {!query.isLoading && !query.isError && batches.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-5 text-center">
            <p className="text-[11px] font-black text-slate-800">
              {t("inventoryQualityIssue.noVisibleQuantityTitle")}
            </p>
            <p className="mt-1 text-[9px] font-semibold leading-4 text-slate-500">
              {t(
                firstPage?.ready_to_resume_sales
                  ? "inventoryQualityIssue.noVisibleQuantityReady"
                  : "inventoryQualityIssue.noVisibleQuantityPending",
              )}
            </p>
          </div>
        ) : null}

        {batches.length > 0 ? (
          <div className="space-y-3">
            {batches.map((batch) => (
              <section
                key={batch.batch_id}
                className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm"
              >
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 pb-3">
                  <div>
                    <p className="text-xs font-black text-slate-950">
                      {t("inventoryQualityIssue.batchTitle", {
                        batch: batch.batch.batch_number,
                      })}
                    </p>
                    <p className="mt-1 text-[9px] font-semibold leading-4 text-slate-500">
                      {t(dispositionKey(batch.batch.disposition))}
                      {batch.batch.disposition_reason
                        ? ` · ${batch.batch.disposition_reason}`
                        : ""}
                    </p>
                  </div>
                  {batch.batch.expiry_date ? (
                    <span className="rounded-lg bg-slate-100 px-2 py-1 text-[9px] font-bold text-slate-600">
                      {t("inventoryQualityIssue.expiry", {
                        date: batch.batch.expiry_date,
                      })}
                    </span>
                  ) : null}
                </div>

                <BatchQuantityActions
                  batch={batch.batch}
                  productVariantId={batch.product_variant_id}
                  baseUomCode={batch.base_uom_code}
                  stockSources={batch}
                  onRefreshStockSources={refresh}
                  onChanged={async () => undefined}
                  onOpenTransfers={async (transfer) => {
                    onClose();
                    await onOpenTransfers(transfer);
                  }}
                  onOpenReservationOwner={(owner) => {
                    onClose();
                    onOpenReservationOwner(owner);
                  }}
                />
              </section>
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={query.isFetching}
            className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-[10px] font-black text-slate-700 disabled:opacity-50"
          >
            <RefreshCcw
              className={`h-3.5 w-3.5 ${query.isFetching ? "animate-spin" : ""}`}
            />
            {t("common.refresh")}
          </button>

          {query.hasNextPage ? (
            <button
              type="button"
              onClick={() => void query.fetchNextPage()}
              disabled={query.isFetchingNextPage}
              className="min-h-9 rounded-lg bg-slate-950 px-4 text-[10px] font-black text-white disabled:opacity-50"
            >
              {query.isFetchingNextPage
                ? t("common.loading")
                : t("inventoryQualityIssue.loadMore")}
            </button>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}
