import type { TFunction } from "i18next";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { ledgerText } from "./ledgerI18n";

interface Props {
  t: TFunction;
  language: string;
  pageIndex: number;
  count: number;
  canPrevious: boolean;
  canNext: boolean;
  loading: boolean;
  onPrevious: () => void;
  onNext: () => void;
}

export function LedgerPagination({
  t,
  language,
  pageIndex,
  count,
  canPrevious,
  canNext,
  loading,
  onPrevious,
  onNext,
}: Props) {
  const text = (key: Parameters<typeof ledgerText>[2], values: Record<string, unknown> = {}) =>
    ledgerText(t, language, key, values);
  if (!canPrevious && !canNext) return null;
  return (
    <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50 px-3 py-2">
      <span className="text-[11px] font-bold text-slate-500">
        {text("page", { page: new Intl.NumberFormat("en-US").format(pageIndex + 1), count: new Intl.NumberFormat("en-US").format(count) })}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onPrevious}
          disabled={!canPrevious || loading}
          aria-label={text("previous")}
          className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-600 outline-none disabled:opacity-30 focus-visible:ring-2 focus-visible:ring-blue-300"
        >
          <ChevronRight aria-hidden="true" className="h-4 w-4 rtl:hidden" />
          <ChevronLeft aria-hidden="true" className="hidden h-4 w-4 rtl:block" />
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!canNext || loading}
          aria-label={text("next")}
          className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-600 outline-none disabled:opacity-30 focus-visible:ring-2 focus-visible:ring-blue-300"
        >
          <ChevronLeft aria-hidden="true" className="h-4 w-4 rtl:hidden" />
          <ChevronRight aria-hidden="true" className="hidden h-4 w-4 rtl:block" />
        </button>
      </div>
    </div>
  );
}
