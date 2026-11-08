import { operationText } from "./operationI18n";
import type { TFunction } from "i18next";
import { formatLedgerDate } from "./contracts";
import type { LedgerOperation } from "./operationContracts";
import { ledgerMovementLabel } from "./ledgerI18n";
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

export function LedgerOperationRows({
  t, language, locale, items, onDetails, onNearBottom, loadingMore, hasMore,
}: Props) {
  const virtual = useLedgerWindow(items.length, 146, onNearBottom, hasMore, loadingMore);
  const visible = items.slice(virtual.first, virtual.last);
  const stage = (value: string) => {
    const copy = ledgerMovementLabel(t, language, value);
    // An unknown producer is not permission to show unlocalized raw enum codes.
    return copy === value ? (operationText(t, language, "copy1")) : copy;
  };
  const count = (n: number) => new Intl.NumberFormat(locale, { numberingSystem: "latn" }).format(n);
  const details = operationText(t, language, "copy2");
  const movement = operationText(t, language, "copy3");
  const product = operationText(t, language, "copy4");

  const kind = (item: LedgerOperation) => ledgerOperationKindLabel(item.group_kind, t, language);
  const formattedTime = (item: LedgerOperation) => formatLedgerDate(item.latest_at, locale);
  const direction = (item: LedgerOperation) => [item.source_location_name, item.destination_location_name]
    .filter((name): name is string => Boolean(name)).join(" → ");
  const label = (item: LedgerOperation) => `${details}: ${item.reference || kind(item)}`;
  const detailsButton = (item: LedgerOperation) => (
    <button type="button" onClick={(event) => onDetails(item, event.currentTarget)}
      disabled={!item.expandable}
      className="shrink-0 rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-bold text-blue-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 disabled:opacity-50"
      aria-label={label(item)}>{details}</button>
  );

  const card = (item: LedgerOperation, index: number) => (
    <article key={item.group_key} data-ledger-virtual-index={virtual.first + index}
      data-ledger-operation-row="true"
      className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 shadow-sm md:hidden">
      <div className="flex min-w-0 items-center justify-between gap-2">
        <div className="min-w-0 text-xs font-bold text-slate-900">
          <span>{kind(item)}</span>
          {item.reference && <bdi dir="ltr" className="ms-2 text-slate-600">{item.reference}</bdi>}
        </div>
        {detailsButton(item)}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-600">
        <b>{count(item.product_variant_count)} {product}</b>
        <span>{count(item.movement_count)} {movement}</span>
        <time dateTime={item.latest_at} dir="ltr">{formattedTime(item)}</time>
      </div>
      {(direction(item) || item.stage_types.length > 0) && (
        <p className="mt-1 truncate text-[11px] text-slate-500"
          title={item.stage_types.map(stage).join(" · ")}>
          {direction(item) || stage(item.stage_types[0])}
        </p>
      )}
      {item.count_meaning === "POSTED_VARIANCE_MOVEMENTS" && (
        <span className="text-[10px] text-amber-800">{operationText(t, language, "copy7")}</span>
      )}
    </article>
  );
  const desktopRow = (item: LedgerOperation, index: number) => (
    <div key={item.group_key} data-ledger-virtual-index={virtual.first + index}
      data-ledger-operation-row="true" role="row"
      className="hidden min-h-11 items-center gap-3 border-b border-slate-100 bg-white px-3 py-1.5 text-xs hover:bg-slate-50 md:grid md:grid-cols-[minmax(105px,1fr)_minmax(90px,1fr)_minmax(104px,1fr)_minmax(0,1.5fr)_minmax(64px,.65fr)_minmax(74px,.65fr)_auto]">
      <span role="cell" className="truncate font-semibold text-slate-900" title={kind(item)}>{kind(item)}</span>
      <bdi role="cell" dir="ltr" className="truncate font-semibold text-slate-600" title={item.reference}>
        {item.reference || operationText(t, language, "copy6")}
      </bdi>
      <time role="cell" dateTime={item.latest_at} dir="ltr" className="truncate text-[11px] text-slate-500">{formattedTime(item)}</time>
      <span role="cell" className="truncate text-slate-600"
        title={[direction(item), ...item.stage_types.map(stage)].filter(Boolean).join(" · ")}>
        {direction(item) || (item.stage_types[0] ? stage(item.stage_types[0]) : "—")}
      </span>
      <span role="cell" className="whitespace-nowrap font-bold">{count(item.product_variant_count)} {product}</span>
      <span role="cell" className="whitespace-nowrap text-slate-600">{count(item.movement_count)} {movement}</span>
      <span role="cell">{detailsButton(item)}</span>
    </div>
  );
  return (
    <div ref={virtual.rootRef} onScroll={virtual.onScroll}
      data-ledger-operation-root="true" data-ledger-mounted={virtual.mounted}
      className="min-h-0 flex-1 overflow-y-auto bg-slate-50/40 p-1.5 md:p-0">
      {virtual.before > 0 && <div aria-hidden="true" style={{ height: virtual.before }} />}
      <div className="space-y-1.5 md:hidden">{visible.map(card)}</div>
      <div role="table" aria-label={operationText(t, language, "copy25")} className="hidden md:block">
        <div role="rowgroup">{visible.map(desktopRow)}</div>
      </div>
      {virtual.after > 0 && <div aria-hidden="true" style={{ height: virtual.after }} />}
      <div ref={virtual.markerRef} data-ledger-bottom="true" className="h-px" aria-hidden="true" />
    </div>
  );
}
