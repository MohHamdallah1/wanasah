import {
  AlertTriangle,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import { formatQty } from "../inventoryUtils";
import type { StocktakeReview } from "./types";

interface StocktakeReviewPanelProps {
  review: StocktakeReview;
  totals: {
    total: number;
    matched: number;
    shortage: number;
    overage: number;
    varianceItems: number;
  };
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
  review,
  totals,
  approvalBlocked,
  onVariance,
  canCancel,
  onCancel,
  canRecount,
  onRecount,
  canApprove,
  onApprove,
}: StocktakeReviewPanelProps) {
  return (
    <div className="glass-card inventory-data-panel flex flex-col border border-slate-200 shadow-sm flex-1 min-h-0 pt-0 overflow-hidden">
      <div className="px-5 py-3 bg-slate-900 text-white flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span className="text-sm font-black">
            مراجعة محاولة #
            {review.latest_attempt.attempt_number}
          </span>
          <span className="text-xs text-slate-400">
            بواسطة {review.latest_attempt.counted_by_name}
          </span>
        </div>
        <div className="text-xs text-slate-300 font-bold">
          {review.attempt_history.length} محاولة محفوظة تاريخياً
        </div>
      </div>

      {approvalBlocked && (
        <div className="mx-4 mt-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-xs font-bold flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          هذا العجز مصنف مادياً، ولذلك الاعتماد النهائي محظور حتى ينفذ مستخدم مخول آخر Recount مستقلاً.
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-100 text-right sticky top-0 z-10 shadow-sm">
            <tr>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500">
                المنتج
              </th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500">
                الدفعة
              </th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">
                المتوقع
              </th>
              <th className="px-4 py-3.5 text-xs font-bold text-[#1e87bb] text-center">
                الفعلي المثبت
              </th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">
                الفرق
              </th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-50 bg-white">
            {review.lines.map((line) => (
              <tr
                key={line.attempt_line_id}
                className="hover:bg-slate-50 transition-colors"
              >
                <td className="px-4 py-3 font-bold text-slate-800">
                  {line.product_name}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500 font-bold">
                  {line.batch_number || "بدون دفعة"}
                </td>
                <td className="px-4 py-3 text-center font-black text-slate-700">
                  {formatQty(
                    line.expected_quantity,
                    line.packs_per_carton
                  )}
                </td>
                <td className="px-4 py-3 text-center font-black text-blue-700">
                  {formatQty(
                    line.actual_quantity,
                    line.packs_per_carton
                  )}
                </td>
                <td className="px-4 py-3 text-center">
                  {line.variance_quantity === 0 ? (
                    <span className="text-slate-400 font-bold">
                      مطابق
                    </span>
                  ) : (
                    <span
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-black ${
                        line.variance_quantity > 0
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-red-100 text-red-700"
                      }`}
                      dir="ltr"
                    >
                      {line.variance_quantity > 0
                        ? "+ "
                        : "- "}
                      {formatQty(
                        Math.abs(line.variance_quantity),
                        line.packs_per_carton
                      )}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-slate-900 text-white rounded-b-2xl overflow-hidden border-t border-slate-700">
        <div className="px-5 py-4 flex flex-wrap items-center justify-between gap-5">
          <div className="flex items-center gap-5">
            <div className="flex flex-col">
              <span className="text-[10px] text-slate-400 font-bold">
                مطابق
              </span>
              <span className="text-sm font-extrabold text-emerald-400">
                {totals.matched}/{totals.total}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="text-[10px] text-slate-400 font-bold">
                أسطر بفروقات
              </span>
              <span
                className={`text-sm font-extrabold ${
                  totals.varianceItems
                    ? "text-red-400"
                    : "text-slate-300"
                }`}
              >
                {totals.varianceItems}
              </span>
            </div>

            {totals.varianceItems > 0 && (
              <button
                onClick={onVariance}
                className="text-xs font-bold bg-red-500/20 text-red-400 hover:bg-red-500/30 px-4 py-2 rounded-xl border border-red-500/30 flex items-center gap-2"
              >
                <AlertTriangle className="w-4 h-4" />
                تفاصيل الفروقات
              </button>
            )}
          </div>

          <div className="flex items-center gap-2 min-w-[430px]">
            <button
              disabled={!canCancel}
              onClick={onCancel}
              className="flex-1 px-4 h-9 bg-slate-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 text-xs font-bold rounded-xl transition-all"
            >
              إلغاء
            </button>
            <button
              disabled={!canRecount}
              onClick={onRecount}
              className="flex-1 px-4 h-9 bg-blue-500/15 hover:bg-blue-500/25 text-blue-300 border border-blue-500/20 text-xs font-black rounded-xl transition-all flex items-center justify-center gap-1.5"
            >
              <RotateCcw className="w-4 h-4" />
              Recount جديد
            </button>
            <button
              onClick={onApprove}
              disabled={approvalBlocked || !canApprove}
              className="flex-[1.5] px-4 h-9 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-700 disabled:text-slate-400 disabled:cursor-not-allowed text-white text-sm font-black rounded-xl transition-all flex items-center justify-center gap-2"
            >
              <ShieldCheck className="w-4 h-4" />
              اعتماد نهائي
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
