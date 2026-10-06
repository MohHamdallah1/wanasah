import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import { BatchDispositionManager } from "../batches/BatchDispositionManager";
import type { BatchSpecialTransferResult } from "../batches/batchSpecialTransferContract";
import type { ReservationOwner } from "../batches/batchStockSourcesContract";
import { useBatchStockSources } from "../batches/useBatchStockSources";
import { useQualityBatchCandidates } from "./useQualityBatchCandidates";

export function QualityBatchPickerWorkspace({
  productVariantId,
  productName,
  onConsumed,
  onClose,
  onOpenTransfers,
  onOpenReservationOwner,
  onConfigureQualityDestinations,
}: {
  productVariantId: number;
  productName: string;
  onConsumed: () => void;
  onClose: () => void;
  onOpenTransfers: (
    transfer?: BatchSpecialTransferResult,
  ) => void | Promise<void>;
  onOpenReservationOwner: (owner: ReservationOwner) => void;
  onConfigureQualityDestinations: () => void;
}) {
  const { t, i18n } = useTranslation();
  const access = useInventoryAccess();
  const query = useQualityBatchCandidates(productVariantId);
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null);
  const selectedBatchQuery = useBatchStockSources(
    selectedBatchId,
    selectedBatchId !== null,
  );
  const heading = useRef<HTMLHeadingElement>(null);
  const consumed = useRef(false);
  const ready = query.data !== undefined;
  const failed = query.isError;
  const pages = query.data?.pages ?? [];
  const items = pages.flatMap((page) => page.items);
  const unit = pages[0]?.base_uom_code ?? "";
  const selectedBatch = selectedBatchQuery.data;
  const selectedBatchMismatch =
    selectedBatch !== undefined &&
    selectedBatch.product_variant_id !== productVariantId;
  const selectedBatchFailed =
    selectedBatchId !== null &&
    (selectedBatchQuery.isError || selectedBatchMismatch);
  const canConfigureQualityDestinations =
    access.isCompanyAdmin || access.can("inventory.transfer_policy.manage");

  useEffect(() => {
    heading.current?.focus();
  }, []);

  useEffect(() => {
    if (consumed.current || (!ready && !failed)) return;
    consumed.current = true;
    onConsumed();
  }, [failed, onConsumed, ready]);

  return (
    <section
      aria-labelledby="quality-batch-picker-heading"
      dir={i18n.dir()}
      className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-1"
    >
      <header className="rounded-xl border border-border bg-card p-4 text-card-foreground">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1
              id="quality-batch-picker-heading"
              ref={heading}
              tabIndex={-1}
              className="text-base font-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("productQualityWorkspace.batchPicker.title")}
            </h1>
            <p className="mt-1 text-xs font-semibold text-muted-foreground">
              {t("productQualityWorkspace.batchPicker.product", {
                name: productName,
              })}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {canConfigureQualityDestinations ? (
              <button
                type="button"
                onClick={onConfigureQualityDestinations}
                className="rounded-lg border border-border px-3 py-2 text-xs font-bold focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("productQualityWorkspace.configureDestinations")}
              </button>
            ) : null}
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border px-3 py-2 text-xs font-bold focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("batchFocus.back")}
            </button>
          </div>
        </div>
        <p className="mt-3 max-w-4xl text-xs leading-5 text-muted-foreground">
          {t("productQualityWorkspace.batchPicker.hint")}
        </p>
      </header>

      {failed ? (
        <div role="alert" className="rounded-xl border border-destructive p-3 text-sm">
          <p>
            {apiErrorMessage(
              query.error,
              t("productQualityWorkspace.batchPicker.error"),
            )}
          </p>
          <button
            type="button"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
            className="mt-2 rounded-lg border border-border px-3 py-2 text-xs font-bold"
          >
            {t("common.retry")}
          </button>
        </div>
      ) : !ready ? (
        <p role="status" className="rounded-xl border border-border bg-card p-4 text-sm">
          {t("productQualityWorkspace.batchPicker.loading")}
        </p>
      ) : items.length === 0 ? (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          {t("productQualityWorkspace.batchPicker.noBatches")}
        </p>
      ) : (
        <div className="space-y-3">
          {items.map((item) => {
            const opening =
              selectedBatchId === item.batch_id && selectedBatchQuery.isFetching;
            return (
              <article
                key={item.batch_id}
                className="rounded-xl border border-border bg-card p-4 text-card-foreground"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-black">
                      {t("productQualityWorkspace.batchPicker.batch", {
                        batch: item.batch_number,
                      })}
                    </h2>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span>
                        {t("productQualityWorkspace.batchPicker.quantity", {
                          quantity: item.total_on_hand_quantity,
                          unit,
                        })}
                      </span>
                      {item.total_reserved_quantity !== "0" ? (
                        <span>
                          {t("productQualityWorkspace.batchPicker.reserved", {
                            quantity: item.total_reserved_quantity,
                            unit,
                          })}
                        </span>
                      ) : null}
                      <span>
                        {t("productQualityWorkspace.batchPicker.currentStatus", {
                          status: t(
                            `inventoryQualityIssue.dispositions.${item.disposition}`,
                          ),
                        })}
                      </span>
                    </div>
                    <p
                      className={`mt-2 text-[11px] font-bold ${
                        item.source_count > 1
                          ? "text-amber-800"
                          : "text-slate-600"
                      }`}
                    >
                      {item.source_count > 1
                        ? t("productQualityWorkspace.batchPicker.distributed", {
                            count: String(item.source_count),
                          })
                        : t("productQualityWorkspace.batchPicker.sourceCount", {
                            count: String(item.source_count),
                          })}
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={opening}
                    onClick={() => setSelectedBatchId(item.batch_id)}
                    className="rounded-lg bg-slate-950 px-3 py-2 text-xs font-black text-white transition hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-slate-400 disabled:opacity-50"
                  >
                    {opening
                      ? t("productQualityWorkspace.batchPicker.opening")
                      : t("productQualityWorkspace.batchPicker.open")}
                  </button>
                </div>

                <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {item.sources_preview.map((source) => (
                    <div
                      key={source.location_id}
                      className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs"
                    >
                      <p className="font-bold text-foreground">
                        {t("productQualityWorkspace.batchPicker.source", {
                          name: source.location_name,
                          quantity: source.on_hand_quantity,
                          unit,
                        })}
                      </p>
                      {source.reserved_quantity !== "0" ? (
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {t("productQualityWorkspace.batchPicker.reserved", {
                            quantity: source.reserved_quantity,
                            unit,
                          })}
                        </p>
                      ) : null}
                    </div>
                  ))}
                </div>

                {item.sources_truncated ? (
                  <p className="mt-2 text-[11px] font-semibold text-muted-foreground">
                    {t("productQualityWorkspace.batchPicker.moreSources")}
                  </p>
                ) : null}
              </article>
            );
          })}
        </div>
      )}

      {selectedBatchFailed ? (
        <div role="alert" className="rounded-xl border border-destructive p-3 text-sm">
          <p>{t("productQualityWorkspace.batchPicker.batchLoadError")}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void selectedBatchQuery.refetch()}
              disabled={selectedBatchQuery.isFetching}
              className="rounded-lg border border-border px-3 py-2 text-xs font-bold"
            >
              {t("common.retry")}
            </button>
            <button
              type="button"
              onClick={() => setSelectedBatchId(null)}
              className="rounded-lg px-3 py-2 text-xs font-bold"
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {query.hasNextPage ? (
        <button
          type="button"
          onClick={() => void query.fetchNextPage()}
          disabled={query.isFetchingNextPage}
          className="self-start rounded-lg border border-border px-3 py-2 text-xs font-bold"
        >
          {query.isFetchingNextPage
            ? t("common.loading")
            : t("productQualityWorkspace.batchPicker.loadMore")}
        </button>
      ) : null}

      {selectedBatchId !== null &&
      selectedBatch !== undefined &&
      !selectedBatchMismatch ? (
        <BatchDispositionManager
          batch={selectedBatch.batch}
          productVariantId={selectedBatch.product_variant_id}
          baseUomCode={selectedBatch.base_uom_code}
          onClose={() => setSelectedBatchId(null)}
          onChanged={async () => {
            await selectedBatchQuery.refetch();
            await query.refetch();
          }}
          onOpenTransfers={onOpenTransfers}
          onOpenReservationOwner={onOpenReservationOwner}
        />
      ) : null}
    </section>
  );
}
