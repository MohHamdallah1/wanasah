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
  const { copy } = useStocktakeUiCopy();

  return (
    <div className="glass-card inventory-data-panel flex-1 flex items-center justify-center border border-slate-200 shadow-sm p-8">
      <div className="max-w-xl text-center space-y-4">
        <div className="mx-auto w-16 h-16 rounded-2xl bg-red-50 border border-red-100 flex items-center justify-center">
          <ShieldCheck className="w-8 h-8 text-red-500" aria-hidden="true" />
        </div>
        <h3 className="text-xl font-black text-slate-800">
          {copy.independentWait.title}
        </h3>
        <p className="text-sm text-slate-600 leading-7 font-bold">
          {copy.independentWait.body}
        </p>
        <button
          type="button"
          disabled={!canCancel}
          onClick={onCancel}
          className="px-5 h-10 bg-slate-100 hover:bg-red-50 text-slate-600 hover:text-red-600 font-bold rounded-xl transition-colors"
        >
          {copy.independentWait.cancel}
        </button>
      </div>
    </div>
  );
}
