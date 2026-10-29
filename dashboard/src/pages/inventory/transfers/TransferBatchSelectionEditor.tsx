import { useTransferTranslation as useTranslation, formatTransferNumber } from "./i18n";
import { formatTransferDateOnly } from "./utils";
import { formatTransferCommercialQuantity } from "./transferQuantity";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import type {
  TransferBatchMode,
  TransferBatchOptions,
  TransferDraftItem,
} from "./types";

interface TransferBatchSelectionEditorProps {
  item: TransferDraftItem;
  draftItems: TransferDraftItem[];
  options: TransferBatchOptions | undefined;
  loading: boolean;
  onModeChange: (
    draftKey: string,
    mode: TransferBatchMode,
  ) => void | Promise<void>;
  onBatchChange: (
    draftKey: string,
    batchId: number | null,
  ) => void;
  onAddBatchLine: (
    productId: number,
  ) => void | Promise<void>;
}

export function TransferBatchSelectionEditor({
  item,
  draftItems,
  options,
  loading,
  onModeChange,
  onBatchChange,
  onAddBatchLine,
}: TransferBatchSelectionEditorProps) {
  const { t } = useTranslation();
  const baseUomName = t(`uom.${item.base_uom_code}`, {
    defaultValue: item.base_uom_name,
  });
  const displayUomName = t(`uom.${item.display_uom_code}`, {
    defaultValue: item.display_uom_name,
  });
  const selectedBatch =
    item.batch_id !== null
      ? options?.batches.find(
          (batch) => batch.id === item.batch_id,
        ) ?? null
      : null;

  const productLines = draftItems.filter(
    (candidate) =>
      candidate.product_variant_id === item.product_variant_id,
  );
  const firstProductLineKey = productLines[0]?.draft_key;
  const selectedBatchIds = new Set(
    productLines
      .map((candidate) => candidate.batch_id)
      .filter((id): id is number => id !== null),
  );
  const allProductLinesSelected = productLines.every(
    (candidate) =>
      candidate.batch_mode === "exact" &&
      candidate.batch_id !== null,
  );
  const hasAnotherBatch = Boolean(
    options?.batches.some(
      (batch) => !selectedBatchIds.has(batch.id),
    ),
  );
  const formatBatchQuantity = (quantity: string) =>
    formatTransferCommercialQuantity(
      item,
      quantity,
      displayUomName,
      baseUomName,
    ).primary;

  if (item.batch_mode !== "exact") return null;

  return (
    <div className="mt-1.5 rounded-lg border border-blue-100 bg-blue-50/25 p-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[10px] font-bold text-slate-600">
          {t("inventoryTransfers.exactBatchHint")}
        </span>
        {item.draft_key === firstProductLineKey ? (
          <button
            type="button"
            onClick={() =>
              void onModeChange(item.draft_key, "auto")
            }
            title={t("inventoryTransfers.exactBatchButtonHint")}
            className="text-[10px] font-black text-blue-700 underline underline-offset-2"
          >
            {t("inventoryTransfers.useAutomaticBatch")}
          </button>
        ) : null}
      </div>

      {loading ? (
        <div className="mt-2 text-xs text-slate-500">
          {t("inventoryTransfers.batchOptionsLoading")}
        </div>
      ) : null}

      {!loading && options ? (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <label className="min-w-56 flex-1">
            <span className="text-[10px] font-bold text-slate-500">
              {t("inventoryTransfers.selectedBatch")}
            </span>
            <select
              aria-label={t("inventoryTransfers.selectedBatch")}
              aria-required="true"
              value={item.batch_id ?? ""}
              onChange={(event) => {
                const value = event.target.value;
                onBatchChange(
                  item.draft_key,
                  value ? Number(value) : null,
                );
              }}
              className="mt-1 h-8 w-full rounded-lg border border-slate-200 bg-white px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-blue-200"
            >
              <option value="">
                {t("inventoryTransfers.chooseBatch")}
              </option>
              {options.batches
                .filter(
                  (batch) =>
                    batch.id === item.batch_id ||
                    !draftItems.some(
                      (candidate) =>
                        candidate.draft_key !== item.draft_key &&
                        candidate.product_variant_id
                          === item.product_variant_id &&
                        candidate.batch_id === batch.id,
                    ),
                )
                .map((batch) => (
                  <option key={batch.id} value={batch.id}>
                    {formatPublicBatchNumber(
                      batch.batch_number,
                      t("inventoryLive.noLotSupplied"),
                    )}
                    {" — "}
                    {t("inventoryTransfers.production")}{" "}
                    {formatTransferDateOnly(batch.production_date)}
                    {" — "}
                    {t("inventoryTransfers.expiry")}{" "}
                    {formatTransferDateOnly(batch.expiry_date)}
                    {" — "}
                    {t("inventoryTransfers.available")}{" "}
                    {formatBatchQuantity(batch.available_quantity)}
                    {batch.id === options.recommended_batch_id
                      ? t("inventoryTransfers.recommendedBatch")
                      : ""}
                  </option>
                ))}
            </select>
          </label>

          {selectedBatch ? (
            <span className="text-[10px] font-bold text-slate-600">
              {t("inventoryTransfers.batchAvailable")}{" "}
              {formatBatchQuantity(
                selectedBatch.available_quantity,
              )}
            </span>
          ) : null}

          {item.draft_key === firstProductLineKey &&
          allProductLinesSelected &&
          hasAnotherBatch ? (
            <button
              type="button"
              onClick={() =>
                void onAddBatchLine(item.product_variant_id)
              }
              className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-[10px] font-black text-slate-700"
            >
              {t("inventoryTransfers.splitBatch")}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
