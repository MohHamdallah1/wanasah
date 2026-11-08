import { operationText, operationFailureText, LEDGER_OPERATION_REFERENCE_TYPES } from "./ledger/operationI18n";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import { Modal } from "@/components/ui/modal";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { resolveI18nLocale } from "@/lib/locale";
import { LedgerAdjustmentModal } from "./ledger/LedgerAdjustmentModal";
import { LedgerFilters } from "./ledger/LedgerFilters";
import { LedgerMobileCards } from "./ledger/LedgerMobileCards";
import { LedgerOperationRows } from "./ledger/LedgerOperationRows";
import { LedgerOperationDetails } from "./ledger/LedgerOperationDetails";
import { useLedgerOperations } from "./ledger/useLedgerOperations";
import type { LedgerOperation } from "./ledger/operationContracts";
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
  const [mode, setMode] = useState<"operations" | "movements">("operations");
  const query = useLedgerQuery(locationId, refreshKey, active && mode === "movements", exactReference);
  const operations = useLedgerOperations(locationId, refreshKey, active && mode === "operations",
    query.searchInput, query.filterType, exactReference);
  const [selectedOperation, setSelectedOperation] = useState<LedgerOperation | null>(null);
  const [selectedScope, setSelectedScope] = useState<string | null>(null);
  const [groupDeniedAt, setGroupDeniedAt] = useState<{ scope: string; proofSequence: number } | null>(null);
  const detailsTrigger = useRef<HTMLButtonElement | null>(null);
  const closeOperation = () => {
    setSelectedOperation(null);
    const trigger = detailsTrigger.current;
    if (trigger?.isConnected) trigger.focus();
    detailsTrigger.current = null;
  };
  const reference = useLedgerReference(locationId, active);
  const adjustment = useLedgerAdjustment(locationId);
  const [noteEntry, setNoteEntry] = useState<LedgerEntry | null>(null);
  const accessAlertRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // A former warehouse/search/session must not retain an open child panel.
    if (selectedScope !== null && selectedScope !== operations.visibleScope) setSelectedOperation(null);
  }, [operations.visibleScope, selectedScope]);
  // Use every canonical backend producer type, not a selective 13-item UI list.
  const operationTypes = [...new Set([...LEDGER_OPERATION_REFERENCE_TYPES,
    ...operations.items.flatMap(group => group.stage_types),
    ...(query.filterType !== "ALL" ? [query.filterType] : []),
  ])];
    const text = (key: Parameters<typeof ledgerText>[2], values: Record<string, unknown> = {}) =>
    ledgerText(t, language, key, values);
  // Only a new authorized parent read of this exact warehouse/filter scope
  // may release a child 403/404 denial. Cached pages or other scopes cannot.
  const childDenied = groupDeniedAt?.scope === operations.visibleScope && !(
    operations.authorizedProof?.scope === groupDeniedAt.scope &&
    operations.authorizedProof.sequence > groupDeniedAt.proofSequence
  );
  const denied = reference.denied || query.denied || operations.denied || childDenied || (access.isSuccess && !access.can("ledger.read"));
  useEffect(() => {
    if (denied) {
      setNoteEntry(null);
      adjustment.close();
      accessAlertRef.current?.focus();
    }
  }, [denied, adjustment.close]);
  const visibleEntries = denied ? [] : query.entries;
  const visibleOperations = denied ? [] : operations.items;
  const operationOpen = selectedOperation !== null && selectedScope === operations.visibleScope && !denied && mode === "operations" && active;
  const canAdjust = !denied && access.can("ledger.adjust");
  useEffect(() => {
    if (!canAdjust && adjustment.entry !== null) adjustment.close();
  }, [canAdjust, adjustment.entry, adjustment.close]);
  const total = mode !== "movements" || denied || query.total === null
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
          availableTypes={mode === "operations" ? operationTypes : query.availableTypes}
          loading={mode === "operations" ? operations.loading : query.loading}
          onRefresh={mode === "operations" ? operations.refresh : query.refresh}
        />}

        <nav aria-label={operationText(t, language, "copy24")} className="flex gap-1 border-b border-slate-100 bg-white px-3 py-1.5">
          <button type="button" aria-pressed={mode === "operations"} onClick={() => setMode("operations")} className={`rounded-lg px-3 py-1.5 text-xs font-bold ${mode === "operations" ? "bg-blue-50 text-blue-800" : "text-slate-600"}`}>{operationText(t, language, "copy25")}</button>
          <button type="button" aria-pressed={mode === "movements"} onClick={() => setMode("movements")} className={`rounded-lg px-3 py-1.5 text-xs font-bold ${mode === "movements" ? "bg-blue-50 text-blue-800" : "text-slate-600"}`}>{operationText(t, language, "copy26")}</button>
          {mode === "operations" && !denied && <span className="ms-auto self-center text-[10px] text-slate-500">{visibleOperations.length} {operationText(t, language, "copy27")}</span>}
        </nav>
        {denied ? (
          <div ref={accessAlertRef} tabIndex={-1} role="alert" className="m-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs font-bold text-red-800">
            {text("referenceAccessChanged")}
          </div>
        ) : null}
        {!denied && (mode === "operations" ? operations.error : query.error) ? (
          <div
            role="alert"
            data-cp13-state={(mode === "operations" ? visibleOperations.length : query.entries.length) > 0 ? "stale" : "error"}
            className={`m-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2 text-xs font-bold ${
              (mode === "operations" ? visibleOperations.length : query.entries.length) > 0
                ? "border-amber-200 bg-amber-50 text-amber-900"
                : "border-red-200 bg-red-50 text-red-800"
            }`}
          >
            <span className="min-w-0 break-words">
              {mode === "operations" && operations.failure
                ? operationFailureText(t, language, operations.failure) : text("loadFailed")}
              {mode === "operations" && operations.failure?.code &&
                operations.failure.status >= 400 && operations.failure.status < 500 && (
                  <span className="ms-2">{operationText(t, language, "errorCode")}: <bdi dir="ltr">{operations.failure.code}</bdi></span>
                )}
              {mode === "operations" && operations.failure?.context && <span className="ms-2">{operations.failure.context}</span>}
              {mode === "operations" && operations.failure?.requestId && (
                <span className="ms-2">{operationText(t, language, "requestId")}: <bdi dir="ltr">{operations.failure.requestId}</bdi></span>
              )}
            </span>
            <button
              type="button"
              onClick={mode === "operations" ? operations.retry : query.retry}
              className="rounded-lg border border-current/20 bg-white px-2.5 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
            >
              {text("retry")}
            </button>
          </div>
        ) : null}

        <div className={`${mode === "operations" ? "flex" : "hidden"} min-h-0 flex-1 flex-col`} data-ledger-view="operations">
          {!denied && (visibleOperations.length > 0 || operations.hasMore) ? (
            <LedgerOperationRows key={operations.visibleScope} t={t} language={language} locale={locale}
              items={visibleOperations} onNearBottom={operations.loadMore} hasMore={operations.hasMore}
              loadingMore={operations.loadingMore}
              onDetails={(item, trigger) => {
                detailsTrigger.current = trigger;
                setSelectedScope(operations.visibleScope);
                setSelectedOperation(item);
              }} />
          ) : !denied && !operations.error && (
            <p role="status" className="p-8 text-center text-sm text-slate-500">
              {operations.loading ? text("loading") : text("empty")}
            </p>
          )}
        </div>
        <div className={`${mode === "movements" ? "flex" : "hidden"} min-h-0 flex-1 flex-col`} data-ledger-view="movements">
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
        </div>
        {!denied && (mode === "operations" ? operations.loadingMore : query.loadingMore) &&
          <p role="status" className="border-t border-slate-100 px-3 py-1 text-center text-xs text-slate-500">
            {text("loading")}
          </p>}
      </section>

      {operationOpen && selectedOperation && (
        <LedgerOperationDetails key={selectedOperation.group_key} operation={selectedOperation}
          locationId={locationId} language={language} locale={locale} t={t}
          search={query.searchInput} filterType={query.filterType} exactReference={exactReference}
          onClose={closeOperation}
          onDenied={() => {
            setGroupDeniedAt({ scope: operations.visibleScope,
              proofSequence: operations.authorizedProof?.sequence ?? 0 });
            setSelectedOperation(null);
            // Recheck current bearer authorization after a rejected child read.
            // Failed parent revalidation preserves the fail-closed guard.
            operations.refresh();
          }}
          onOpenReference={(entry) => { closeOperation(); reference.open(entry); }}
          onAdjust={(entry) => { closeOperation(); openAdjustment(entry); }} canAdjust={canAdjust} />
      )}
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
          operations.refresh();
          onInventoryChanged();
        }}
      />}
    </div>
  );
}
