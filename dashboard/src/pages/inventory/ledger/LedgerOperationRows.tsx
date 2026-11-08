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
  const ar = language.toLowerCase().startsWith("ar");
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
  const lots = operationText(t, language, "copy5");

  const card = (item: LedgerOperation, index: number) => (
    <article key={item.group_key} data-ledger-virtual-index={virtual.first + index} data-ledger-operation-row="true"
      className="min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm md:rounded-none md:border-x-0 md:border-t-0 md:shadow-none">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-md bg-blue-50 px-2 py-1 font-bold text-blue-800">{ledgerOperationKindLabel(item.group_kind, t, language)}</span>
            {item.reference && <bdi dir="ltr" className="max-w-full truncate font-bold text-slate-700">{item.reference}</bdi>}
            {!item.reference && <span className="font-semibold text-slate-500">{operationText(t, language, "copy6")}</span>}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-700">
            <span>{count(item.product_variant_count)} {product}</span>
            <span>{count(item.batch_count)} {lots}</span>
            <span>{count(item.movement_count)} {movement}</span>
            {item.count_meaning === "POSTED_VARIANCE_MOVEMENTS" &&
              <span className="font-semibold text-amber-800">{operationText(t, language, "copy7")}</span>}
          </div>
          <div className="mt-1 flex flex-wrap gap-1">
            {item.stage_types.map((type) => (
              <span key={type} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">{stage(type)}</span>
            ))}
          </div>
          <div className="mt-1 text-[10px] text-slate-500">
            {item.source_location_name && <span>{operationText(t, language, "copy8")}: {item.source_location_name} · </span>}
            {item.destination_location_name && <span>{operationText(t, language, "copy9")}: {item.destination_location_name} · </span>}
            {item.latest_actor_name && <span>{item.latest_actor_name} · </span>}
            <time dateTime={item.latest_at} dir="ltr">{formatLedgerDate(item.latest_at, locale)}</time>
          </div>
        </div>
        <button type="button" onClick={(event) => onDetails(item, event.currentTarget)}
          disabled={!item.expandable}
          className="shrink-0 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-bold text-blue-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 disabled:opacity-50"
          aria-label={`${details}: ${item.reference || ledgerOperationKindLabel(item.group_kind, t, language)}`}>
          {details}
        </button>
      </div>
    </article>
  );
  return (
    <div ref={virtual.rootRef} onScroll={virtual.onScroll}
      data-ledger-operation-root="true" data-ledger-mounted={virtual.mounted}
      className="min-h-0 flex-1 overflow-y-auto bg-slate-50/40 p-1.5 md:p-0">
      {virtual.before > 0 && <div aria-hidden="true" style={{ height: virtual.before }} />}
      {visible.map(card)}
      {virtual.after > 0 && <div aria-hidden="true" style={{ height: virtual.after }} />}
      <div ref={virtual.markerRef} data-ledger-bottom="true" className="h-px" aria-hidden="true" />
    </div>
  );
}
