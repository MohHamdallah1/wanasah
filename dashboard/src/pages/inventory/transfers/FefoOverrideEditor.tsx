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
      <div className="mt-3">
        <label className="text-[10px] font-bold text-slate-500">
          سياسة اختيار الدفعة
        </label>
        <select
          value={item.fefo_mode}
          onChange={(event) => {
            const mode = event.target.value;
            if (mode === "auto" || mode === "override") {
              void onModeChange(item.draft_key, mode);
            }
          }}
          className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs"
        >
          <option value="auto">
            FEFO تلقائي — الموصى به
          </option>
          <option value="override" disabled={!canOverride}>
            تجاوز FEFO موثّق
          </option>
        </select>
      </div>

      {item.fefo_mode === "override" && (
        <div className="mt-3 rounded-xl border border-amber-200 bg-white p-3 space-y-3">
          <div className="text-[11px] font-bold text-amber-800">
            تجاوز FEFO استثناء رقابي. يجب تحديد
            دفعة وسبب معتمد، وسيتم تسجيل المشرف
            والسبب في سجل التدقيق.
          </div>

          {loading && (
            <div className="text-xs text-slate-400">
              جاري جلب دفعات المصدر وأسباب التجاوز...
            </div>
          )}

          {!loading && options && (
            <>
              <div>
                <label className="text-[10px] font-bold text-slate-500">
                  الدفعة المختارة
                </label>
                <select
                  value={item.override_batch_id ?? ""}
                  onChange={(event) => {
                    const value = event.target.value;
                    onBatchChange(
                      item.draft_key,
                      value ? Number(value) : null
                    );
                  }}
                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs"
                >
                  <option value="">
                    اختر دفعة
                  </option>
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
                        {batch.batch_number} — صلاحية{" "}
                        {batch.expiry_date} — متاح{" "}
                        {batch.available_packs}
                        {batch.is_fefo_head
                          ? " — FEFO الحالي"
                          : ""}
                      </option>
                    ))}
                </select>
              </div>

              <div>
                <label className="text-[10px] font-bold text-slate-500">
                  سبب التجاوز
                </label>
                <select
                  value={item.override_reason_id ?? ""}
                  onChange={(event) => {
                    const value = event.target.value;
                    onReasonChange(
                      item.draft_key,
                      value ? Number(value) : null
                    );
                  }}
                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs"
                >
                  <option value="">
                    اختر سبباً معتمداً
                  </option>
                  {options.reasons.map((reason) => (
                    <option
                      key={reason.id}
                      value={reason.id}
                    >
                      {reason.code} —{" "}
                      {reason.description}
                    </option>
                  ))}
                </select>
              </div>

              {selectedBatch && (
                <div className="text-[10px] text-slate-500">
                  المتاح في الدفعة المختارة:{" "}
                  <span className="font-bold">
                    {selectedBatch.available_packs} حبة
                  </span>
                  {selectedBatch.is_fefo_head && (
                    <span className="text-amber-700">
                      {" "}
                      — هذه الدفعة هي FEFO الحالية؛
                      التجاوز غير ضروري عادةً.
                    </span>
                  )}
                </div>
              )}

              {item.draft_key === firstProductLineKey && (
                <button
                  type="button"
                  onClick={() =>
                    void onAddBatchLine(
                      item.product_variant_id
                    )
                  }
                  className="text-xs font-bold text-amber-700 hover:text-amber-900"
                >
                  + تقسيم نفس الصنف على دفعة أخرى
                </button>
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}
