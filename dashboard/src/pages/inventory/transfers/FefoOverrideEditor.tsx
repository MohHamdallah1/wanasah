import { ShieldCheck, TriangleAlert } from "lucide-react";
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

  return (
    <>
      <div className="mt-3" data-cp13-fefo-mode={item.fefo_mode}>
        <label className="text-[10px] font-bold text-slate-500">{t("inventoryTransfers.batchPolicy")}</label>
        <div className="mt-1 flex items-center gap-2">
          <span
            className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border ${
              item.fefo_mode === "override"
                ? "border-amber-200 bg-amber-50 text-amber-700"
                : "border-emerald-200 bg-emerald-50 text-emerald-700"
            }`}
            aria-hidden="true"
          >
            {item.fefo_mode === "override" ? <TriangleAlert className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
          </span>
          <select
            aria-label={t("inventoryTransfers.batchPolicy")}
            value={item.fefo_mode}
            onChange={(event) => {
              const mode = event.target.value;
              if (mode === "auto" || mode === "override") {
                void onModeChange(item.draft_key, mode);
              }
            }}
            className="h-8 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 text-xs font-bold outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
          >
            <option value="auto">{t("inventoryTransfers.fefoRecommended")}</option>
            <option value="override" disabled={!canOverride}>{t("inventoryTransfers.fefoOverride")}</option>
          </select>
        </div>
      </div>

      {item.fefo_mode === "override" && (
        <div className="mt-2 space-y-2 rounded-xl border border-amber-200 bg-amber-50/35 p-3" data-cp13-fefo-override="exceptional">
          <div className="flex items-start gap-2 text-[11px] font-bold text-amber-900">
            <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>{t("inventoryTransfers.overrideHint")}</span>
          </div>

          {loading && (
            <div className="text-xs text-slate-500">{t("inventoryTransfers.overrideLoading")}</div>
          )}

          {!loading && options && (
            <>
              <div>
                <label className="text-[10px] font-bold text-slate-500">{t("inventoryTransfers.selectedBatch")}</label>
                <select
                  aria-label={t("inventoryTransfers.selectedBatch")}
                  aria-required="true"
                  value={item.override_batch_id ?? ""}
                  onChange={(event) => {
                    const value = event.target.value;
                    onBatchChange(
                      item.draft_key,
                      value ? Number(value) : null
                    );
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
                            candidate.product_variant_id ===
                              item.product_variant_id &&
                            candidate.override_batch_id === batch.id
                        )
                    )
                    .map((batch) => (
                      <option
                        key={batch.id}
                        value={batch.id}
                      >
                        {formatPublicBatchNumber(batch.batch_number, t("inventoryLive.noLotSupplied"))} — {t("inventoryTransfers.expiry")}{" "}
                        {formatTransferDateOnly(batch.expiry_date)} — {t("inventoryTransfers.available")}{" "}
                        {formatTransferNumber(batch.available_quantity)}
                        {batch.is_fefo_head
                          ? t("inventoryTransfers.currentFefo")
                          : ""}
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
                    onReasonChange(
                      item.draft_key,
                      value ? Number(value) : null
                    );
                  }}
                  className="mt-1 h-8 w-full rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
                >
                  <option value="">{t("inventoryTransfers.chooseReason")}</option>
                  {options.reasons.map((reason) => (
                    <option
                      key={reason.id}
                      value={reason.id}
                    >
                      {reason.code} — {reason.description}
                    </option>
                  ))}
                </select>
              </div>

              {selectedBatch && (
                <div className="text-[10px] text-slate-600">
                  {t("inventoryTransfers.batchAvailable")}{" "}
                  <span className="font-bold">
                    {formatTransferNumber(selectedBatch.available_quantity)} {item.base_uom_name}
                  </span>
                  {selectedBatch.is_fefo_head && (
                    <span className="text-amber-700">
                      {" "}
                      {t("inventoryTransfers.headHint")}
                    </span>
                  )}
                </div>
              )}

              {item.draft_key === firstProductLineKey && (
                <button
                  type="button"
                  onClick={() => void onAddBatchLine(item.product_variant_id)}
                  className="rounded-md text-xs font-bold text-amber-800 outline-none hover:text-amber-950 focus-visible:ring-2 focus-visible:ring-amber-300"
                >
                  {t("inventoryTransfers.splitBatch")}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}
