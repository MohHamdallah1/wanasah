import { ShieldCheck } from "lucide-react";
import { useStocktakeUiCopy } from "./uiCopy";

interface StocktakeIndependentWaitProps {
  canCancel: boolean;
  onCancel: () => void;
}

export function StocktakeIndependentWait({
  canCancel,
  onCancel,
}: StocktakeIndependentWaitProps) {
  const { copy, dir } = useStocktakeUiCopy();

  return (
    <div className="glass-card inventory-data-panel flex-1 flex items-center justify-center border border-slate-200 shadow-sm p-4 md:p-6" dir={dir}>
      <div className="max-w-xl text-center space-y-3">
        <div className="mx-auto w-12 h-12 rounded-xl bg-red-50 border border-red-100 flex items-center justify-center">
          <ShieldCheck className="w-6 h-6 text-red-500" aria-hidden="true" />
        </div>
        <ol aria-label={copy.workspace.stages} className="flex flex-wrap items-center justify-center gap-1 text-xs font-bold text-slate-600">
          {[copy.workspace.countStep, copy.workspace.reviewStep, copy.workspace.approveStep].map((stage, index) => (
            <li key={stage} aria-current={index === 1 ? "step" : undefined}
              className={`rounded-md px-2 py-1 ${index === 1 ? "bg-amber-100 text-amber-900" : "bg-slate-100"}`}>
              {index + 1}. {stage}
            </li>
          ))}
        </ol>
        <h3 className="text-lg font-black text-slate-800">
          {copy.independentWait.title}
        </h3>
        <p className="text-sm text-slate-600 leading-6 font-medium">
          {copy.independentWait.body}
        </p>
        <button
          type="button"
          disabled={!canCancel}
          onClick={onCancel}
          className="px-4 h-9 bg-slate-100 hover:bg-red-50 text-slate-600 hover:text-red-600 font-bold rounded-xl transition-colors"
        >
          {copy.independentWait.cancel}
        </button>
      </div>
    </div>
  );
}
