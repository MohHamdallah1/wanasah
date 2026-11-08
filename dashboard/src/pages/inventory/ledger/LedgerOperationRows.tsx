import type { TFunction } from "i18next";
import { formatLedgerDate } from "./contracts";
import { ledgerMovementLabel } from "./ledgerI18n";
import type { LedgerOperation } from "./operationContracts";
import { ledgerOperationKindLabel, operationText, abbreviatedOperationReference, operationLocationLabel } from "./operationI18n";
import { useLedgerWindow } from "./useLedgerWindow";

interface Props {
  t: TFunction;
  language: string;
  locale: string;
  items: LedgerOperation[];
  onDetails: (item: LedgerOperation, trigger: HTMLButtonElement) => void;
  onNearBottom: () => void;
  loadingMore: boolean;
  hasMore: boolean;
}

/**
 * One DOM row for each canonical server group at every breakpoint. The only
 * action on the summary is Details. Product names and Lot/cost evidence live
 * in the bounded child panel, not a misleading top-level product column.
 */
export function LedgerOperationRows({
  t, language, locale, items, onDetails, onNearBottom, loadingMore, hasMore,
}: Props) {
  const virtual = useLedgerWindow(items.length, 62, onNearBottom, hasMore, loadingMore);
  const visible = items.slice(virtual.first, virtual.last);
  const count = (value: number) => new Intl.NumberFormat(locale, { numberingSystem: "latn" }).format(value);
  const details = operationText(t, language, "copy2");
  const products = operationText(t, language, "copy4");
  const isArabic = language.toLowerCase().startsWith("ar");
  const movements = operationText(t, language, "copy3");
  const stage = (type: string) => {
    const label = ledgerMovementLabel(t, language, type);
    return label === type ? operationText(t, language, "copy1") : label;
  };
  const kind = (item: LedgerOperation) => item.group_kind === "MOVEMENT"
    ? stage(item.operation_type) : ledgerOperationKindLabel(item.group_kind, t, language);
  const route = (item: LedgerOperation) => {
    const locations = [item.source_location_name, item.destination_location_name]
      .filter((name): name is string => Boolean(name))
      .map(name => operationLocationLabel(name, language, t)).join(" → ");
    // Backend returns an alphabetically sorted set, NOT a chronological latest stage.
    const recordedStages = item.stage_types.map(stage).join(" / ");
    return [locations, recordedStages].filter(Boolean).join(" · ") || "—";
  };
  // Desktop header/body participate in one CSS table, guaranteeing a shared
  // seven-column track geometry; mobile retains one compact grid card per row.
  const desktopWidths = ["md:w-[14%]", "md:w-[18%]", "md:w-[15%]", "md:w-[25%]", "md:w-[10%]", "md:w-[10%]", "md:w-[8%]"] as const;
  const columns = [
    "columnType", "columnReference", "columnDate", "columnRoute",
    "columnProducts", "columnMovements", "columnAction",
  ] as const;
  return (
    <div ref={virtual.rootRef} onScroll={virtual.onScroll}
      data-ledger-operation-root="true" data-ledger-mounted={virtual.mounted}
      className="min-h-0 flex-1 overflow-y-auto bg-slate-50/40 p-1.5 md:p-0">
      <div role="table" aria-label={operationText(t, language, "copy25")} className="md:table md:table-fixed md:w-full">
        <div role="rowgroup" className="hidden border-b border-slate-200 bg-slate-50 md:table-header-group">
          <div role="row"
            className="md:table-row text-[11px] font-bold text-slate-600">
            {columns.map((column, index) => (
              <span key={column} role="columnheader" data-ledger-column={column}
                className={`min-w-0 truncate text-start md:table-cell md:border-b md:border-slate-200 md:px-2 md:py-2 ${desktopWidths[index]}`}>
                {operationText(t, language, column)}
              </span>
            ))}
          </div>
        </div>
        <div role="rowgroup" className="md:table-row-group">
          {virtual.before > 0 && <div aria-hidden="true" style={{ height: virtual.before }} />}
          {visible.map((item, index) => (
            <article key={item.group_key} role="row"
              data-ledger-virtual-index={virtual.first + index}
              data-ledger-operation-row="true"
              className={`mb-1.5 grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs shadow-sm md:mb-0 md:table-row md:rounded-none md:border-none md:p-0 md:shadow-none`}>
              <span role="cell" data-ledger-column="columnType" title={kind(item)} className="min-w-0 truncate font-bold text-slate-900 md:table-cell md:align-middle md:border-b md:border-slate-100 md:px-2 md:py-1.5">
                {kind(item)}
              </span>
              <span role="cell" data-ledger-column="columnReference"
                className="col-start-1 row-start-2 min-w-0 truncate text-start text-[11px] font-semibold text-slate-600 md:col-auto md:row-auto md:table-cell md:align-middle md:border-b md:border-slate-100 md:px-2 md:py-1.5">
                <bdi dir="ltr" tabIndex={item.reference ? 0 : undefined}
                  title={item.reference || undefined}
                  aria-label={item.reference || undefined}
                  className="inline-block max-w-full truncate align-bottom outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-600">
                  {abbreviatedOperationReference(item.reference) || operationText(t, language, "copy6")}
                </bdi>
              </span>
              <span role="cell" data-ledger-column="columnDate"
                className="col-start-1 row-start-3 min-w-0 truncate text-start text-[11px] text-slate-500 md:col-auto md:row-auto md:table-cell md:align-middle md:border-b md:border-slate-100 md:px-2 md:py-1.5">
                <time dateTime={item.latest_at} lang={isArabic ? "ar" : "en"} dir={isArabic ? "rtl" : "ltr"}
                  className="isolate block truncate text-start">
                  {formatLedgerDate(item.latest_at, locale)}
                </time>
              </span>
              <span role="cell" data-ledger-column="columnRoute" className="col-start-1 row-start-4 min-w-0 truncate text-[11px] text-slate-600 md:col-auto md:row-auto md:table-cell md:align-middle md:border-b md:border-slate-100 md:px-2 md:py-1.5"
                title={route(item)}>{route(item)}</span>
              <span role="cell" data-ledger-column="columnProducts"
                title={item.count_meaning === "POSTED_VARIANCE_MOVEMENTS" ? operationText(t, language, "copy7") : products}
                className="col-start-1 row-start-5 min-w-0 truncate whitespace-nowrap font-bold text-slate-800 md:col-auto md:row-auto md:table-cell md:align-middle md:border-b md:border-slate-100 md:px-2 md:py-1.5">
                {count(item.product_variant_count)} {item.count_meaning === "POSTED_VARIANCE_MOVEMENTS"
                  ? operationText(t, language, "varianceProducts")
                  : (item.product_variant_count === 1 ? operationText(t, language, "singularProduct") : products)}
              </span>
              <span role="cell" data-ledger-column="columnMovements" className="col-start-1 row-start-6 whitespace-nowrap text-[11px] text-slate-600 md:col-auto md:row-auto md:table-cell md:align-middle md:border-b md:border-slate-100 md:px-2 md:py-1.5">
                {count(item.movement_count)} {item.movement_count === 1 ? operationText(t, language, "singularMovement") : movements}
              </span>
              <span role="cell" data-ledger-column="columnAction" className="col-start-2 row-span-6 row-start-1 self-center md:col-auto md:row-auto md:table-cell md:align-middle md:border-b md:border-slate-100 md:px-2 md:py-1.5">
                <button type="button" onClick={event => onDetails(item, event.currentTarget)}
                  aria-label={`${details}: ${item.reference || kind(item)}`}
                  disabled={!item.expandable}
                  className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-bold text-blue-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 disabled:opacity-50">
                  {details}
                </button>
              </span>
            </article>
          ))}
          {virtual.after > 0 && <div aria-hidden="true" style={{ height: virtual.after }} />}
          <div ref={virtual.markerRef} data-ledger-bottom="true" className="h-px" aria-hidden="true" />
        </div>
      </div>
    </div>
  );
}
