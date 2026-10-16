import { AlertTriangle, Ban, Clock3, PackageSearch, RefreshCcw, ShieldAlert, Siren, TimerReset } from "lucide-react";
import type { TFunction } from "i18next";

import type { WarehouseBatchIndexSummary } from "./batchIndexContracts";
import { batchIndexText } from "./batchIndexI18n";

interface Props {
  t: TFunction;
  language: string;
  locale: string;
  summary: WarehouseBatchIndexSummary | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}

export function BatchIndexSummary({
  t,
  language,
  locale,
  summary,
  loading,
  error,
  onRetry,
}: Props) {
  const text = (key: Parameters<typeof batchIndexText>[2]) =>
    batchIndexText(t, language, key);
  const number = (value: number) =>
    new Intl.NumberFormat(locale, {
      numberingSystem: "latn",
      maximumFractionDigits: 0,
    }).format(value);

  if (error && !summary) {
    return (
      <div className="flex min-h-16 items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900">
        <span>{text("summaryError")}</span>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 font-bold outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
          {text("retry")}
        </button>
      </div>
    );
  }

  const cards = summary
    ? [
        ["total", summary.total_relevant_batches, PackageSearch],
        ["expired", summary.expired_count, TimerReset],
        ["expiringSoon", summary.expiring_soon_count, Clock3],
        ["nonSellable", summary.non_sellable_count, Ban],
        ["quarantined", summary.quarantined_count, ShieldAlert],
        ["blocked", summary.blocked_count, AlertTriangle],
        ["recalled", summary.recalled_count, Siren],
        ["damagedOrDisposal", summary.damaged_or_disposal_attention_count, RefreshCcw],
      ] as const
    : [];

  return (
    <section aria-live="polite" className="relative">
      {loading && (
        <span className="absolute end-1 top-1 z-10 inline-flex items-center gap-1 rounded-full bg-white/90 px-2 py-1 text-[9px] font-semibold text-slate-500 shadow-sm">
          <RefreshCcw className="h-3 w-3 animate-spin" />
          {text("summaryLoading")}
        </span>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
        {cards.map(([key, value, Icon]) => (
          <div key={key} className="min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-[10px] font-bold text-slate-500">{text(key)}</span>
              <Icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            </div>
            <strong className="mt-1 block text-lg font-black tabular-nums text-slate-900">
              {number(value)}
            </strong>
          </div>
        ))}
      </div>
    </section>
  );
}