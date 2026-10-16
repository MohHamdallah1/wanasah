import { Check, Scan } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { KeyboardEvent } from "react";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import type { StocktakeRow } from "../inventoryUtils";
import { useStocktakeCopy } from "./copy";

interface StocktakeCountingPanelProps {
  rows: StocktakeRow[];
  progress: {
    total: number;
    counted: number;
    remaining: number;
  };
  onUpdateRow: (key: string, value: string) => void;
  onConfirmZero: (key: string) => void;
  canCancel: boolean;
  onCancel: () => void;
  onSubmit: () => void;
}

export function StocktakeCountingPanel({
  rows,
  progress,
  onUpdateRow,
  onConfirmZero,
  canCancel,
  onCancel,
  onSubmit,
}: StocktakeCountingPanelProps) {
  const { t } = useTranslation();
  const { isArabic, dir } = useStocktakeCopy();
  const text = <T,>(arabic: T, english: T) => (isArabic ? arabic : english);

  const handleCountEnter = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" || event.currentTarget.value.trim() === "") return;
    event.preventDefault();
    const inputs = Array.from(document.querySelectorAll<HTMLInputElement>("[data-stocktake-count-input='true']"));
    const index = inputs.indexOf(event.currentTarget);
    const next = inputs[index + 1];
    if (next) {
      next.focus();
      next.select();
      return;
    }
    if (progress.remaining === 0) onSubmit();
  };

  const countInput = (row: StocktakeRow, autoFocus = false) => (
    <input
      data-stocktake-count-input="true"
      inputMode="decimal"
      autoFocus={autoFocus}
      aria-label={text(`الكمية الفعلية لـ ${row.product_name}`, `Actual quantity for ${row.product_name}`)}
      value={row.actual_quantity}
      onChange={(event) => onUpdateRow(row.row_key, event.target.value)}
      onKeyDown={handleCountEnter}
      className="w-28 max-w-full rounded-lg border border-slate-300 p-2 text-center font-bold"
      dir="ltr"
    />
  );

  const zeroButton = (row: StocktakeRow) => row.counted ? (
    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 text-emerald-700 border border-emerald-100 rounded-lg text-xs font-black">
      <Check className="w-3.5 h-3.5" aria-hidden="true" />
      {text("تم العد", "Counted")}
    </span>
  ) : (
    <button
      type="button"
      onClick={() => onConfirmZero(row.row_key)}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-amber-50 text-slate-500 hover:text-amber-700 border border-slate-200 hover:border-amber-200 rounded-lg text-xs font-black transition-colors"
      title={text("استخدم هذا الزر فقط إذا تم العد فعلياً وكانت الكمية صفر", "Use only after a physical count confirms zero quantity")}
      aria-label={text(`تأكيد صفر لـ ${row.product_name}`, `Confirm zero for ${row.product_name}`)}
    >
      {text("تأكيد صفر", "Confirm zero")}
    </button>
  );

  return (
    <div dir={dir} className="glass-card inventory-data-panel flex flex-col border border-slate-200 shadow-sm flex-1 min-h-0 pt-0 overflow-hidden">
      <div className="px-5 py-3 bg-slate-900 text-white flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Scan className="w-4 h-4 text-amber-400" aria-hidden="true" />
          <span className="text-sm font-black">{text("عد أعمى نشط", "Blind count in progress")}</span>
        </div>
        <span className="text-xs text-slate-300 font-bold">
          {text("المتوقع والفروقات مخفية حتى تثبيت المحاولة", "Expected quantities and variances stay hidden until submission")}
        </span>
      </div>

      <div className="md:hidden flex-1 min-h-0 overflow-y-auto custom-scrollbar bg-slate-50 p-3 space-y-3">
        {rows.map((row, index) => (
          <article key={row.row_key} className="rounded-xl border border-slate-200 bg-white p-3 space-y-3">
            <div>
              <div className="font-bold text-slate-800 text-sm">{row.product_name}</div>
              <div className="text-xs text-slate-500 mt-1">
                {formatPublicBatchNumber(row.batch_number, t("inventoryLive.noLotSupplied"))} · {row.expiry_date || "-"}
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                {countInput(row, index === 0)}
                <span className="text-xs font-bold text-slate-500">{row.base_uom_name}</span>
              </div>
              {zeroButton(row)}
            </div>
            <div className="text-[11px] text-slate-400">{text("خطوة الكمية", "Quantity step")}: <span dir="ltr">{row.quantity_step}</span></div>
          </article>
        ))}
      </div>

      <div className="hidden md:block flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
            <tr>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-start">{text("المنتج", "Product")}</th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-start">{text("الدفعة / الصلاحية", "Batch / expiry")}</th>
              <th className="px-4 py-3.5 text-xs font-bold text-[#1e87bb] text-center">{text("الجرد الفعلي بوحدة الأساس", "Actual count in base UOM")}</th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">{text("حالة العد", "Count status")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 bg-white">
            {rows.map((row, index) => (
              <tr key={row.row_key} className="hover:bg-slate-50 transition-colors">
                <td className="px-4 py-3 font-bold text-slate-800">{row.product_name}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs font-bold text-slate-700">{formatPublicBatchNumber(row.batch_number, t("inventoryLive.noLotSupplied"))}</span>
                    <span className="text-[11px] text-slate-400">{row.expiry_date || "-"}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-center gap-2">
                    {countInput(row, index === 0)}
                    <span className="text-xs font-bold text-slate-500">{row.base_uom_name}</span>
                    <span className="text-[10px] text-slate-400">{text("خطوة", "Step")} <span dir="ltr">{row.quantity_step}</span></span>
                  </div>
                </td>
                <td className="px-4 py-3 text-center">{zeroButton(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-slate-900 text-white rounded-b-2xl overflow-hidden border-t border-slate-700">
        <div className="px-4 md:px-5 py-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-5">
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold uppercase">{text("الإجمالي", "Total")}</span><span className="text-sm font-extrabold"><span dir="ltr">{progress.total}</span> {text("سطر", "lines")}</span></div>
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold uppercase">{text("تم عده", "Counted")}</span><span className="text-sm font-extrabold text-emerald-400" dir="ltr">{progress.counted}</span></div>
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold uppercase">{text("متبقي", "Remaining")}</span><span className={`text-sm font-extrabold ${progress.remaining > 0 ? "text-amber-400" : "text-emerald-400"}`} dir="ltr">{progress.remaining}</span></div>
          </div>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full sm:w-auto sm:min-w-[300px]">
            <button type="button" disabled={!canCancel} onClick={onCancel} className="flex-1 px-4 h-9 bg-slate-800 hover:bg-red-500/20 disabled:opacity-50 text-slate-300 hover:text-red-300 border border-transparent hover:border-red-500/30 text-xs font-bold rounded-xl transition-all">
              {text("إلغاء الجرد", "Cancel stocktake")}
            </button>
            <button type="button" onClick={onSubmit} disabled={progress.remaining > 0} className="flex-[2.5] px-4 h-9 bg-amber-500 hover:bg-amber-600 disabled:bg-slate-600 disabled:text-slate-300 text-slate-900 text-sm font-black rounded-xl shadow-lg transition-all flex items-center justify-center gap-2">
              <Check className="w-5 h-5" aria-hidden="true" />
              {text("إنهاء العد وتثبيت المحاولة", "Finish count and submit attempt")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
