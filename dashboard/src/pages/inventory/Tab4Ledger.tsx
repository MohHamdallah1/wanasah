import { useState } from "react";
import { History } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/ui/modal";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { resolveI18nLocale } from "@/lib/locale";
import { LedgerAdjustmentModal } from "./ledger/LedgerAdjustmentModal";
import { LedgerFilters } from "./ledger/LedgerFilters";
import { LedgerMobileCards } from "./ledger/LedgerMobileCards";
import { LedgerPagination } from "./ledger/LedgerPagination";
import { LedgerReferenceModal } from "./ledger/LedgerReferenceModal";
import { LedgerTable } from "./ledger/LedgerTable";
import type { LedgerEntry } from "./ledger/contracts";
import { ledgerText } from "./ledger/ledgerI18n";
import { useLedgerAdjustment } from "./ledger/useLedgerAdjustment";
import { useLedgerQuery } from "./ledger/useLedgerQuery";
import { useLedgerReference } from "./ledger/useLedgerReference";

interface Props {
  locationId: number;
  refreshKey: number;
  onInventoryChanged: () => void;
}

export function Tab4Ledger({ locationId, refreshKey, onInventoryChanged }: Props) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage || i18n.language || "en";
  const locale = resolveI18nLocale(i18n);
  const access = useInventoryAccess(locationId);
  const query = useLedgerQuery(locationId, refreshKey);
  const reference = useLedgerReference(locationId);
  const adjustment = useLedgerAdjustment(locationId);
  const [noteEntry, setNoteEntry] = useState<LedgerEntry | null>(null);

  const text = (key: Parameters<typeof ledgerText>[2], values: Record<string, unknown> = {}) =>
    ledgerText(t, language, key, values);
  const canAdjust = access.can("ledger.adjust");
  const total = query.total === null
    ? null
    : new Intl.NumberFormat(locale, {
        maximumFractionDigits: 0,
        numberingSystem: "latn",
      }).format(query.total);

  const openAdjustment = (entry: LedgerEntry) => {
    if (!canAdjust) return;
    adjustment.open(entry);
  };

  const commonRows = {
    t,
    language,
    locale,
    entries: query.entries,
    canAdjust,
    onOpenReference: reference.open,
    onOpenNotes: (entry: LedgerEntry) => setNoteEntry(entry),
    onOpenAdjustment: openAdjustment,
  };

  return (
    <div
      dir={i18n.dir()}
      className="inventory-view inventory-ledger flex min-h-0 flex-1 flex-col pt-1"
      data-cp13-density="compact"
      data-cp13-surface="ledger"
    >
      <section className="inventory-surface inventory-data-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-3 py-2.5 sm:px-4">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-sm font-black text-slate-900">
              <History aria-hidden="true" className="h-4 w-4 text-blue-700" />
              {text("title")}
            </h2>
            {total !== null ? (
              <p className="mt-0.5 text-[10px] font-bold tabular-nums text-slate-400">{total}</p>
            ) : null}
          </div>
        </header>

        <LedgerFilters
          t={t}
          language={language}
          search={query.searchInput}
          onSearchChange={query.setSearchInput}
          filterType={query.filterType}
          onFilterTypeChange={query.setFilterType}
          availableTypes={query.availableTypes}
          loading={query.loading}
          onRefresh={query.refresh}
        />

        {query.error ? (
          <div
            role="alert"
            data-cp13-state={query.entries.length > 0 ? "stale" : "error"}
            className={`m-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2 text-xs font-bold ${
              query.entries.length > 0
                ? "border-amber-200 bg-amber-50 text-amber-900"
                : "border-red-200 bg-red-50 text-red-800"
            }`}
          >
            <span>{text("loadFailed")}</span>
            <button
              type="button"
              onClick={query.retry}
              className="rounded-lg border border-current/20 bg-white px-2.5 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
            >
              {text("retry")}
            </button>
          </div>
        ) : null}

        {query.loading && query.entries.length === 0 ? (
          <p role="status" data-cp13-state="loading" className="flex flex-1 items-center justify-center p-8 text-sm font-bold text-slate-400">
            {text("loading")}
          </p>
        ) : null}

        {!query.loading && !query.error && query.entries.length === 0 ? (
          <p data-cp13-state="empty" className="flex flex-1 items-center justify-center p-8 text-center text-sm font-semibold text-slate-400">
            {text("empty")}
          </p>
        ) : null}

        {query.entries.length > 0 ? (
          <>
            <LedgerTable {...commonRows} />
            <LedgerMobileCards {...commonRows} />
          </>
        ) : null}

        <LedgerPagination
          t={t}
          language={language}
          pageIndex={query.pageIndex}
          count={query.entries.length}
          canPrevious={query.canGoPrevious}
          canNext={query.hasMore}
          loading={query.loading}
          onPrevious={query.goPrevious}
          onNext={query.goNext}
        />
      </section>

      <Modal
        isOpen={noteEntry !== null}
        onClose={() => setNoteEntry(null)}
        title={text("noteDetails")}
        maxWidth="max-w-md"
      >
        <p className="whitespace-pre-wrap rounded-xl border border-slate-100 bg-slate-50 p-4 text-sm leading-6 text-slate-700">
          {noteEntry?.notes ?? "—"}
        </p>
      </Modal>

      <LedgerReferenceModal t={t} language={language} controller={reference} />
      <LedgerAdjustmentModal
        t={t}
        language={language}
        controller={adjustment}
        onChanged={() => {
          query.refresh();
          onInventoryChanged();
        }}
      />
    </div>
  );
}
