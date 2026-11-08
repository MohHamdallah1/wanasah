import type { TFunction } from "i18next";
import { formatLedgerDate } from "./contracts";
import { ledgerMovementLabel } from "./ledgerI18n";
import type { LedgerOperation } from "./operationContracts";
import { operationText } from "./operationI18n";
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

export const ledgerOperationKindLabel = (kind: LedgerOperation["group_kind"], t: TFunction, language: string) =>
  operationText(t, language, ({
    TRANSFER: "kindTransfer", STOCKTAKE: "kindStocktake",
    RECEIPT: "kindReceipt", MOVEMENT: "kindMovement",
  } as const)[kind]);

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
  const movements = operationText(t, language, "copy3");
  const stage = (type: string) => {
    const label = ledgerMovementLabel(t, language, type);
    return label === type ? operationText(t, language, "copy1") : label;
  };
  const kind = (item: LedgerOperation) => ledgerOperationKindLabel(item.group_kind, t, language);
  const route = (item: LedgerOperation) => {
    const locations = [item.source_location_name, item.destination_location_name].filter(Boolean).join(" → ");
    const currentStage = item.stage_types.length ? stage(item.stage_types[item.stage_types.length - 1]) : "";
    return [locations, currentStage].filter(Boolean).join(" · ") || "—";
  };
  const columns = [
    "columnType", "columnReference", "columnDate", "columnRoute",
    "columnProducts", "columnMovements", "columnAction",
  ] as const;
  return (
    <div ref={virtual.rootRef} onScroll={virtual.onScroll}
      data-ledger-operation-root="true" data-ledger-mounted={virtual.mounted}
      className="min-h-0 flex-1 overflow-y-auto bg-slate-50/40 p-1.5 md:p-0">
      <div role="table" aria-label={operationText(t, language, "copy25")}>
        <div role="rowgroup" className="hidden border-b border-slate-200 bg-slate-50 md:block">
          <div role="row"
            className="grid grid-cols-[minmax(95px,1fr)_minmax(85px,1fr)_minmax(105px,.9fr)_minmax(130px,1.5fr)_minmax(77px,.7fr)_minmax(83px,.8fr)_auto] items-center gap-2 px-3 py-2 text-[11px] font-bold text-slate-600">
            {columns.map(column => (
              <span key={column} role="columnheader" className="min-w-0 truncate">
                {operationText(t, language, column)}
              </span>
            ))}
          </div>
        </div>
        <div role="rowgroup">
          {virtual.before > 0 && <div aria-hidden="true" style={{ height: virtual.before }} />}
          {visible.map((item, index) => (
            <article key={item.group_key} role="row"
              data-ledger-virtual-index={virtual.first + index}
              data-ledger-operation-row="true"
              className="mb-1.5 grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs shadow-sm md:mb-0 md:grid-cols-[minmax(95px,1fr)_minmax(85px,1fr)_minmax(105px,.9fr)_minmax(130px,1.5fr)_minmax(77px,.7fr)_minmax(83px,.8fr)_auto] md:gap-2 md:rounded-none md:border-x-0 md:border-t-0 md:px-3 md:py-1.5 md:shadow-none">
              <span role="cell" title={kind(item)} className="min-w-0 truncate font-bold text-slate-900">
                {kind(item)}
              </span>
              <bdi role="cell" dir="ltr" title={item.reference}
                className="col-start-1 row-start-2 min-w-0 truncate text-[11px] font-semibold text-slate-600 md:col-auto md:row-auto">
                {item.reference || operationText(t, language, "copy6")}
              </bdi>
              <time role="cell" dateTime={item.latest_at} dir="ltr"
                className="col-start-1 row-start-3 truncate text-[11px] text-slate-500 md:col-auto md:row-auto">
                {formatLedgerDate(item.latest_at, locale)}
              </time>
              <span role="cell" className="col-start-1 row-start-4 min-w-0 truncate text-[11px] text-slate-600 md:col-auto md:row-auto"
                title={route(item)}>{route(item)}</span>
              <span role="cell" className="col-start-1 row-start-5 whitespace-nowrap font-bold text-slate-800 md:col-auto md:row-auto">
                {count(item.product_variant_count)} {products}
              </span>
              <span role="cell" className="col-start-1 row-start-6 whitespace-nowrap text-[11px] text-slate-600 md:col-auto md:row-auto">
                {count(item.movement_count)} {movements}
              </span>
              <span role="cell" className="col-start-2 row-span-6 row-start-1 self-center md:col-auto md:row-auto">
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
