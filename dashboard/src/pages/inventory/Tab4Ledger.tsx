import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import { Modal } from "@/components/ui/modal";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { resolveI18nLocale } from "@/lib/locale";
import { LedgerAdjustmentModal } from "./ledger/LedgerAdjustmentModal";
import { LedgerFilters } from "./ledger/LedgerFilters";
import { LedgerMobileCards } from "./ledger/LedgerMobileCards";
import { LedgerReferenceModal } from "./ledger/LedgerReferenceModal";
import { LedgerTable } from "./ledger/LedgerTable";
import type { LedgerEntry } from "./ledger/contracts";
import { ledgerText } from "./ledger/ledgerI18n";
import { useLedgerAdjustment } from "./ledger/useLedgerAdjustment";
import { useLedgerQuery } from "./ledger/useLedgerQuery";
import { useLedgerReference } from "./ledger/useLedgerReference";
import { parseStocktakeLedgerReferenceQuery } from "./ledger/stocktakeLedgerNavigation";

interface Props {
  active?: boolean;
  locationId: number;
  warehouseSelector?: ReactNode;
  refreshKey: number;
  onInventoryChanged: () => void;
}

export function Tab4Ledger({ active = true, locationId, warehouseSelector, refreshKey, onInventoryChanged }: Props) {
  const { t, i18n } = useTranslation();
  const language = i18n.resolvedLanguage || i18n.language || "en";
  const locale = resolveI18nLocale(i18n);
  const access = useInventoryAccess(locationId);
  const routeLocation = useLocation();
  const navigate = useNavigate();
  const lookup = parseStocktakeLedgerReferenceQuery(routeLocation.search);
  // The URL is only a read hint; never use it to override the admitted warehouse.
  // The server still enforces ledger.read, company isolation and RLS.
  const exactReference = lookup?.locationId === locationId ? lookup.reference : null;
  const clearExactReference = () => {
    const params = new URLSearchParams(routeLocation.search);
    params.delete("ledger_ref");
    params.delete("ledger_location");
    const search = params.toString();
    navigate({ pathname: routeLocation.pathname, search: search ? `?${search}` : "" },
      { replace: true, state: null });
  };
  const query = useLedgerQuery(locationId, refreshKey, active, exactReference);
  const reference = useLedgerReference(locationId, active);
  const adjustment = useLedgerAdjustment(locationId);
  const [noteEntry, setNoteEntry] = useState<LedgerEntry | null>(null);
  const accessAlertRef = useRef<HTMLDivElement>(null);

  const text = (key: Parameters<typeof ledgerText>[2], values: Record<string, unknown> = {}) =>
    ledgerText(t, language, key, values);
  const denied = reference.denied || query.denied || (access.isSuccess && !access.can("ledger.read"));
  useEffect(() => {
    if (denied) {
      setNoteEntry(null);
      adjustment.close();
      accessAlertRef.current?.focus();
    }
  }, [denied, adjustment.close]);
  const visibleEntries = denied ? [] : query.entries;
  const canAdjust = !denied && access.can("ledger.adjust");
  useEffect(() => {
    if (!canAdjust && adjustment.entry !== null) adjustment.close();
  }, [canAdjust, adjustment.entry, adjustment.close]);
  const total = denied || query.total === null
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
    entries: visibleEntries,
    canAdjust,
    onOpenReference: reference.open,
    onOpenNotes: (entry: LedgerEntry) => setNoteEntry(entry),
    onOpenAdjustment: openAdjustment,
    onNearBottom: query.loadMore,
    hasMore: query.hasMore,
    loadingMore: query.loadingMore || query.error,
  };

  return (
    <div
      dir={i18n.dir()}
      className="inventory-view inventory-ledger flex min-h-0 flex-1 flex-col pt-1"
      data-cp13-density="compact"
      data-cp13-surface="ledger"
    >
      <section className="inventory-surface inventory-data-panel flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {!denied && exactReference && (
          <div role="status" data-ledger-exact-reference="true"
            className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-100 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900">
            {warehouseSelector && <div className="flex min-w-0 items-center" data-ledger-warehouse-picker="true">{warehouseSelector}</div>}
            <span>{text("exactReferenceFilter")}: <bdi dir="ltr">{exactReference}</bdi></span>
            {total !== null && <span className="text-[10px] font-medium text-amber-800" title={text("movementCountHelp")}>{text("movementCount", { count: total })}</span>}
            <button type="button" onClick={clearExactReference}
              className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
              {text("clearReferenceFilter")}
            </button>
          </div>
        )}
        {!denied && !exactReference && <LedgerFilters
          warehouseSelector={warehouseSelector}
          t={t}
          language={language}
          search={query.searchInput}
          onSearchChange={query.setSearchInput}
          filterType={query.filterType}
          totalCount={total}
          onFilterTypeChange={query.setFilterType}
          availableTypes={query.availableTypes}
          loading={query.loading}
          onRefresh={query.refresh}
        />}

        {denied ? (
          <div ref={accessAlertRef} tabIndex={-1} role="alert" className="m-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-bold text-red-800">
            {text("referenceAccessChanged")}
          </div>
        ) : null}
        {!denied && query.error ? (
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

        {/* The desktop header must exist on the first frame, not appear after HTTP. */}
        <LedgerTable key={query.scopeKey} {...commonRows} loading={query.loading} error={query.error || denied} />
        <div className="min-h-0 flex-1 overflow-hidden md:hidden">
          {visibleEntries.length > 0 ? <LedgerMobileCards key={query.scopeKey} {...commonRows} /> : (
            !query.error && !denied && (
              <p role="status" data-cp13-state={query.loading ? "loading" : "empty"}
                className="p-8 text-center text-sm font-semibold text-slate-500">
                {text(query.loading ? "loading" : "empty")}
              </p>
            )
          )}
        </div>

        {!denied && query.loadingMore && <p role="status" className="border-t border-slate-100 px-3 py-1 text-center text-xs text-slate-500">{text("loading")}</p>}
      </section>

      <Modal
        isOpen={active && !denied && noteEntry !== null}
        onClose={() => setNoteEntry(null)}
        title={text("noteDetails")}
        maxWidth="max-w-md"
      >
        <p className="whitespace-pre-wrap rounded-xl border border-slate-100 bg-slate-50 p-4 text-sm leading-6 text-slate-700">
          {noteEntry?.notes ?? "—"}
        </p>
      </Modal>

      {active && !denied && <LedgerReferenceModal t={t} language={language} controller={reference} />}
      {active && !denied && <LedgerAdjustmentModal
        t={t}
        language={language}
        controller={adjustment}
        canAdjust={canAdjust}
        onChanged={() => {
          query.refresh();
          onInventoryChanged();
        }}
      />}
    </div>
  );
}
