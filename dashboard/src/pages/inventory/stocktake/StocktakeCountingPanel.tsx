import { Check, Scan } from "lucide-react";
import { QuantityInput } from "@/components/ui/quantity-input";
import type { StocktakeRow } from "../inventoryUtils";

interface StocktakeCountingPanelProps {
  rows: StocktakeRow[];
  progress: {
    total: number;
    counted: number;
    remaining: number;
  };
  onUpdateRow: (
    key: string,
    field: "actual_cartons" | "actual_loose_packs",
    value: number
  ) => void;
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
  return (
    <div className="glass-card inventory-data-panel flex flex-col border border-slate-200 shadow-sm flex-1 min-h-0 pt-0 overflow-hidden">
      <div className="px-5 py-3 bg-slate-900 text-white flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Scan className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-black">
            عد أعمى نشط
          </span>
        </div>
        <span className="text-xs text-slate-300 font-bold">
          المتوقع والفروقات مخفية حتى تثبيت المحاولة
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-100 text-right sticky top-0 z-10 shadow-sm">
            <tr>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500">
                المنتج
              </th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500">
                الدفعة / الصلاحية
              </th>
              <th className="px-4 py-3.5 text-xs font-bold text-[#1e87bb] text-center">
                الجرد الفعلي (كرتونة / حبة)
              </th>
              <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">
                حالة العد
              </th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-50 bg-white">
            {rows.map((row) => (
              <tr
                key={row.row_key}
                className="hover:bg-slate-50 transition-colors"
              >
                <td className="px-4 py-3 font-bold text-slate-800">
                  {row.product_name}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs font-bold text-slate-700">
                      {row.batch_number || "بدون دفعة"}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      {row.expiry_date || "-"}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-center gap-4">
                    <div className="flex items-center gap-1.5">
                      <QuantityInput
                        value={row.actual_cartons}
                        onChange={(value) =>
                          onUpdateRow(
                            row.row_key,
                            "actual_cartons",
                            value
                          )
                        }
                        min={0}
                      />
                      <span className="text-xs font-bold text-slate-500">
                        ك
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <QuantityInput
                        value={row.actual_loose_packs}
                        onChange={(value) =>
                          onUpdateRow(
                            row.row_key,
                            "actual_loose_packs",
                            value
                          )
                        }
                        min={-1}
                      />
                      <span className="text-xs font-bold text-slate-500">
                        ح
                      </span>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 text-center">
                  {row.counted ? (
                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 text-emerald-700 border border-emerald-100 rounded-lg text-xs font-black">
                      <Check className="w-3.5 h-3.5" />
                      تم العد
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() =>
                        onConfirmZero(row.row_key)
                      }
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-amber-50 text-slate-500 hover:text-amber-700 border border-slate-200 hover:border-amber-200 rounded-lg text-xs font-black transition-colors"
                      title="استخدم هذا الزر فقط إذا تم العد فعلياً وكانت الكمية صفر"
                    >
                      تأكيد صفر
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-slate-900 text-white rounded-b-2xl overflow-hidden border-t border-slate-700">
        <div className="px-5 py-4 flex flex-wrap items-center justify-between gap-6">
          <div className="flex items-center gap-6">
            <div className="flex flex-col">
              <span className="text-[10px] text-slate-400 font-bold uppercase">
                الإجمالي
              </span>
              <span className="text-sm font-extrabold">
                {progress.total} سطر
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] text-slate-400 font-bold uppercase">
                تم عده
              </span>
              <span className="text-sm font-extrabold text-emerald-400">
                {progress.counted}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] text-slate-400 font-bold uppercase">
                متبقي
              </span>
              <span
                className={`text-sm font-extrabold ${
                  progress.remaining > 0
                    ? "text-amber-400"
                    : "text-emerald-400"
                }`}
              >
                {progress.remaining}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 min-w-[300px]">
            <button
              disabled={!canCancel}
              onClick={onCancel}
              className="flex-1 px-4 h-9 bg-slate-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 border border-transparent hover:border-red-500/30 text-xs font-bold rounded-xl transition-all"
            >
              إلغاء الجرد
            </button>
            <button
              onClick={onSubmit}
              className="flex-[2.5] px-4 h-9 bg-amber-500 hover:bg-amber-600 text-slate-900 text-sm font-black rounded-xl shadow-lg transition-all flex items-center justify-center gap-2"
            >
              <Check className="w-5 h-5" />
              إنهاء العد وتثبيت المحاولة
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
