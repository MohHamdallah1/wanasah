import { TriangleAlert } from "lucide-react";
import { useTransferTranslation as useTranslation, formatTransferNumber } from "./i18n";
import { formatTransferDateOnly } from "./utils";
import { formatPublicBatchNumber } from "../publicBatchNumber";

import type {
  FefoMode,
  TransferDraftItem,
  TransferOverrideOptions,
} from "./types";

interface FefoOverrideEditorProps {
  canOverride: boolean;
  item: TransferDraftItem;
  draftItems: TransferDraftItem[];
  options: TransferOverrideOptions | undefined;
  loading: boolean;
  onModeChange: (draftKey: string, mode: FefoMode) => void | Promise<void>;
  onBatchChange: (draftKey: string, batchId: number | null) => void;
  onReasonChange: (draftKey: string, reasonId: number | null) => void;
  onAddBatchLine: (productId: number) => void | Promise<void>;
}

export function FefoOverrideEditor({
  canOverride,
  item,
  draftItems,
  options,
  loading,
  onModeChange,
  onBatchChange,
  onReasonChange,
  onAddBatchLine,
}: FefoOverrideEditorProps) {
  const { t } = useTranslation();
  const selectedBatch =
    item.override_batch_id !== null
      ? options?.batches.find(
          (batch) => batch.id === item.override_batch_id
        ) ?? null
      : null;

  const firstProductLineKey = draftItems.find(
    (candidate) =>
      candidate.product_variant_id === item.product_variant_id
  )?.draft_key;

  if (item.fefo_mode !== "override") return null;

  return (
    <div className="mt-2 space-y-2 rounded-xl border border-amber-200 bg-amber-50/35 p-3" data-cp13-fefo-override="exceptional">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-start gap-2 text-[11px] font-bold text-amber-900">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{t("inventoryTransfers.specificBatchHint")}</span>
        </div>
        {item.draft_key === firstProductLineKey ? (
          <button
            type="button"
            onClick={() => void onModeChange(item.draft_key, "auto")}
            className="shrink-0 text-[10px] font-black text-blue-700 underline underline-offset-2"
          >
            {t("inventoryTransfers.useAutomaticBatch")}
          </button>
        ) : null}
      </div>

      {loading ? (
        <div className="text-xs text-slate-500">{t("inventoryTransfers.overrideLoading")}</div>
      ) : null}

      {!loading && options ? (
        <>
          <div>
            <label className="text-[10px] font-bold text-slate-500">{t("inventoryTransfers.selectedBatch")}</label>
            <select
              aria-label={t("inventoryTransfers.selectedBatch")}
              aria-required="true"
              value={item.override_batch_id ?? ""}
              onChange={(event) => {
                const value = event.target.value;
                onBatchChange(item.draft_key, value ? Number(value) : null);
              }}
              className="mt-1 h-8 w-full rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
            >
              <option value="">{t("inventoryTransfers.chooseBatch")}</option>
              {options.batches
                .filter(
                  (batch) =>
                    batch.id === item.override_batch_id ||
                    !draftItems.some(
                      (candidate) =>
                        candidate.draft_key !== item.draft_key &&
                        candidate.product_variant_id === item.product_variant_id &&
                        candidate.override_batch_id === batch.id
                    )
                )
                .map((batch) => (
                  <option key={batch.id} value={batch.id}>
                    {formatPublicBatchNumber(batch.batch_number, t("inventoryLive.noLotSupplied"))} — {t("inventoryTransfers.expiry")}{" "}
                    {formatTransferDateOnly(batch.expiry_date)} — {t("inventoryTransfers.available")}{" "}
                    {formatTransferNumber(batch.available_quantity)}
                    {batch.is_fefo_head ? t("inventoryTransfers.currentFefo") : ""}
                  </option>
                ))}
            </select>
          </div>

          <div>
            <label className="text-[10px] font-bold text-slate-500">{t("inventoryTransfers.overrideReason")}</label>
            <select
              aria-label={t("inventoryTransfers.overrideReason")}
              aria-required="true"
              value={item.override_reason_id ?? ""}
              onChange={(event) => {
                const value = event.target.value;
                onReasonChange(item.draft_key, value ? Number(value) : null);
              }}
              className="mt-1 h-8 w-full rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
            >
              <option value="">{t("inventoryTransfers.chooseReason")}</option>
              {options.reasons.map((reason) => (
                <option key={reason.id} value={reason.id}>
                  {reason.description || reason.code}
                </option>
              ))}
            </select>
          </div>

          {selectedBatch ? (
            <div className="text-[10px] text-slate-600">
              {t("inventoryTransfers.batchAvailable")}{" "}
              <span className="font-bold">
                {formatTransferNumber(selectedBatch.available_quantity)} {item.base_uom_name}
              </span>
              {selectedBatch.is_fefo_head ? (
                <span className="text-amber-700"> {t("inventoryTransfers.headHint")}</span>
              ) : null}
            </div>
          ) : null}

          {item.draft_key === firstProductLineKey ? (
            <button
              type="button"
              onClick={() => void onAddBatchLine(item.product_variant_id)}
              className="rounded-md text-xs font-bold text-amber-800 outline-none hover:text-amber-950 focus-visible:ring-2 focus-visible:ring-amber-300"
            >
              {t("inventoryTransfers.splitBatch")}
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
