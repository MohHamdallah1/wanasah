import { AlertTriangle, RotateCcw, ShieldCheck } from "lucide-react";
import { absoluteQuantity, compareQuantity, formatQuantity } from "../quantity";
import { useTranslation } from "react-i18next";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { useStocktakeUiCopy } from "./uiCopy";
import type { StocktakeReview } from "./types";

interface StocktakeReviewPanelProps {
  review: StocktakeReview;
  totals: { total: number; matched: number; shortage: number; overage: number; varianceItems: number };
  approvalBlocked: boolean;
  onVariance: () => void;
  canCancel: boolean;
  onCancel: () => void;
  canRecount: boolean;
  onRecount: () => void;
  canApprove: boolean;
  onApprove: () => void;
}

export function StocktakeReviewPanel({
  review, totals, approvalBlocked, onVariance, canCancel, onCancel,
  canRecount, onRecount, canApprove, onApprove,
}: StocktakeReviewPanelProps) {
  const { t } = useTranslation();
  const { copy, dir } = useStocktakeUiCopy();
  const text = copy.review;

  return (
    <div dir={dir} className="glass-card inventory-data-panel flex flex-col border border-slate-200 shadow-sm flex-1 min-h-0 pt-0 overflow-hidden">
      <div className="px-5 py-3 bg-slate-900 text-white flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-emerald-400" aria-hidden="true" />
          <span className="text-sm font-black">{text.attempt} <span dir="ltr">#{review.latest_attempt.attempt_number}</span></span>
          <span className="text-xs text-slate-400">{text.by} {review.latest_attempt.counted_by_name}</span>
        </div>
        <div className="text-xs text-slate-300 font-bold"><span dir="ltr">{review.attempt_history.length}</span> {text.history}</div>
      </div>

      {approvalBlocked && (
        <div className="mx-4 mt-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-xs font-bold flex items-center gap-2" role="alert">
          <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
          {text.independentRequired}
        </div>
      )}

      <div className="md:hidden flex-1 min-h-0 overflow-y-auto bg-slate-50 p-3 space-y-3">
        {review.lines.map((line) => {
          const variance = compareQuantity(line.variance_quantity, "0");
          return (
            <article key={line.attempt_line_id} className="rounded-xl border border-slate-200 bg-white p-3">
              <div className="font-bold text-slate-800">{line.product_name}</div>
              <div className="text-xs text-slate-500 mt-1">{formatPublicBatchNumber(line.batch_number, t("inventoryLive.noLotSupplied"))}</div>
              <dl className="grid grid-cols-3 gap-2 mt-3 text-center">
                <div><dt className="text-[10px] text-slate-400 font-bold">{text.expected}</dt><dd className="text-sm font-black text-slate-700" dir="ltr">{formatQuantity(line.expected_quantity, line.base_uom_name)}</dd></div>
                <div><dt className="text-[10px] text-slate-400 font-bold">{text.counted}</dt><dd className="text-sm font-black text-blue-700" dir="ltr">{formatQuantity(line.actual_quantity, line.base_uom_name)}</dd></div>
                <div><dt className="text-[10px] text-slate-400 font-bold">{text.variance}</dt><dd className="text-sm font-black" dir="ltr">{variance === 0 ? text.match : `${variance > 0 ? "+" : "-"}${formatQuantity(absoluteQuantity(line.variance_quantity), line.base_uom_name)}`}</dd></div>
              </dl>
            </article>
          );
        })}
      </div>

      <div className="hidden md:block flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
            <tr>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-start">{text.product}</th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-start">{text.batch}</th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">{text.expected}</th>
              <th className="px-4 py-3.5 text-xs font-bold text-[#1e87bb] text-center">{text.countedFixed}</th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">{text.variance}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 bg-white">
            {review.lines.map((line) => {
              const variance = compareQuantity(line.variance_quantity, "0");
              return (
                <tr key={line.attempt_line_id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-bold text-slate-800">{line.product_name}</td>
                  <td className="px-4 py-3 text-xs text-slate-500 font-bold">{formatPublicBatchNumber(line.batch_number, t("inventoryLive.noLotSupplied"))}</td>
                  <td className="px-4 py-3 text-center font-black text-slate-700" dir="ltr">{formatQuantity(line.expected_quantity, line.base_uom_name)}</td>
                  <td className="px-4 py-3 text-center font-black text-blue-700" dir="ltr">{formatQuantity(line.actual_quantity, line.base_uom_name)}</td>
                  <td className="px-4 py-3 text-center">
                    {variance === 0 ? <span className="text-slate-500 font-bold">{text.match}</span> : (
                      <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-black ${variance > 0 ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`} dir="ltr">
                        {variance > 0 ? "+ " : "- "}{formatQuantity(absoluteQuantity(line.variance_quantity), line.base_uom_name)}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="bg-slate-900 text-white rounded-b-2xl overflow-hidden border-t border-slate-700">
        <div className="px-4 md:px-5 py-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-5">
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold">{text.matched}</span><span className="text-sm font-extrabold text-emerald-400" dir="ltr">{totals.matched}/{totals.total}</span></div>
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold">{text.varianceLines}</span><span className={`text-sm font-extrabold ${totals.varianceItems ? "text-red-400" : "text-slate-300"}`} dir="ltr">{totals.varianceItems}</span></div>
            {totals.varianceItems > 0 && <button type="button" onClick={onVariance} className="text-xs font-bold bg-red-500/20 text-red-300 hover:bg-red-500/30 px-3 py-2 rounded-xl border border-red-500/30 flex items-center gap-2"><AlertTriangle className="w-4 h-4" aria-hidden="true" />{text.varianceDetails}</button>}
          </div>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full sm:w-auto sm:min-w-[430px]">
            <button type="button" disabled={!canCancel} onClick={onCancel} className="flex-1 px-4 h-9 bg-slate-800 hover:bg-red-500/20 disabled:opacity-50 text-slate-300 hover:text-red-300 text-xs font-bold rounded-xl transition-all">{text.cancel}</button>
            <button type="button" disabled={!canRecount} onClick={onRecount} className="flex-1 px-4 h-9 bg-blue-500/15 hover:bg-blue-500/25 disabled:opacity-50 text-blue-300 border border-blue-500/20 text-xs font-black rounded-xl transition-all flex items-center justify-center gap-1.5"><RotateCcw className="w-4 h-4" aria-hidden="true" />{text.recount}</button>
            <button type="button" onClick={onApprove} disabled={approvalBlocked || !canApprove} className="flex-[1.5] px-4 h-9 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-700 disabled:text-slate-400 disabled:cursor-not-allowed text-white text-sm font-black rounded-xl transition-all flex items-center justify-center gap-2"><ShieldCheck className="w-4 h-4" aria-hidden="true" />{text.approve}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
