import type { TFunction } from "i18next";
import { ArrowDownRight, ArrowUpRight, Eye, FileText, TriangleAlert } from "lucide-react";

import { compareQuantity } from "@/lib/quantity";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { formatLedgerDate, type LedgerEntry } from "./contracts";
import { ledgerBadgeClass, ledgerMovementLabel, ledgerText } from "./ledgerI18n";
import { ledgerLocationEvidence, ledgerSignedQuantity } from "./ledgerPresentation";

interface Props {
  t: TFunction;
  language: string;
  locale: string;
  entries: LedgerEntry[];
  canAdjust: boolean;
  onOpenReference: (entry: LedgerEntry) => void;
  onOpenNotes: (entry: LedgerEntry, trigger: HTMLButtonElement) => void;
  onOpenAdjustment: (entry: LedgerEntry) => void;
}

export function LedgerMobileCards({
  t,
  language,
  locale,
  entries,
  canAdjust,
  onOpenReference,
  onOpenNotes,
  onOpenAdjustment,
}: Props) {
  const text = (key: Parameters<typeof ledgerText>[2], values: Record<string, unknown> = {}) =>
    ledgerText(t, language, key, values);
  const unit = (code: string) => t(`uom.${code}`, { defaultValue: code });

  return (
    <div className="space-y-1.5 overflow-y-auto p-2 md:hidden" data-cp13-phone-list="true">
      {entries.map((entry) => {
        const locations = ledgerLocationEvidence(t, language, entry);
        const outgoing = compareQuantity(entry.quantity, "0") < 0;
        const DirectionIcon = outgoing ? ArrowDownRight : ArrowUpRight;
        return (
          <article key={entry.id} className="rounded-xl border border-slate-200 bg-white p-2.5 shadow-sm" data-cp13-ledger-card="compact">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-black ${ledgerBadgeClass(entry.type)}`}>
                  <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
                  {ledgerMovementLabel(t, language, entry.type)}
                </span>
                <h3 className="mt-1.5 truncate text-sm font-black text-slate-900">{entry.product_name}</h3>
                <p className="mt-0.5 text-[10px] font-semibold tabular-nums text-slate-500" dir="ltr">
                  #{entry.id} · {formatLedgerDate(entry.date, locale)}
                </p>
              </div>
              <div
                className={`inline-flex shrink-0 items-center gap-1 text-sm font-black tabular-nums ${outgoing ? "text-rose-700" : "text-emerald-700"}`}
                data-cp13-movement-direction={outgoing ? "out" : "in"}
              >
                <DirectionIcon aria-hidden="true" className="h-4 w-4" />
                <span dir="ltr">{ledgerSignedQuantity(entry, unit)}</span>
              </div>
            </div>

            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-slate-100 pt-2 text-[10px]">
              <div className="min-w-0">
                <dt className="font-bold text-slate-400">{text("batch")}</dt>
                <dd className="mt-0.5 truncate font-black text-slate-700">{formatPublicBatchNumber(entry.batch_number, text("noLot"))}</dd>
              </div>
              <div className="min-w-0">
                <dt className="font-bold text-slate-400">{text("actor")}</dt>
                <dd className="mt-0.5 truncate font-black text-slate-700">{entry.admin_name || text("unknown")}</dd>
              </div>
              <div className="min-w-0">
                <dt className="font-bold text-slate-400">{text("source")}</dt>
                <dd className="mt-0.5 truncate font-black text-slate-700">{locations.source}</dd>
              </div>
              <div className="min-w-0">
                <dt className="font-bold text-slate-400">{text("destination")}</dt>
                <dd className="mt-0.5 truncate font-black text-slate-700">{locations.destination}</dd>
              </div>
            </dl>

            <div className="mt-2 flex flex-wrap gap-1.5 border-t border-slate-100 pt-2">
              {entry.reference ? (
                <button
                  type="button"
                  onClick={() => onOpenReference(entry)}
                  aria-label={text("openReference", { reference: entry.reference })}
                  className="inline-flex min-w-0 items-center gap-1 rounded-lg border border-blue-100 bg-blue-50 px-2 py-1.5 text-[10px] font-black text-blue-700 outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
                  data-cp13-action-priority="secondary"
                >
                  <FileText aria-hidden="true" className="h-3.5 w-3.5" />
                  <span className="max-w-36 truncate">{entry.reference}</span>
                </button>
              ) : null}
              {entry.notes ? (
                <button
                  type="button"
                  onClick={(event) => onOpenNotes(entry, event.currentTarget)}
                  aria-label={text("openNotes", { id: entry.id })}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-600 outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
                  data-cp13-action-priority="secondary"
                >
                  <Eye aria-hidden="true" className="h-3.5 w-3.5" />
                </button>
              ) : null}
              {entry.type === "INBOUND_SUPPLIER" && canAdjust ? (
                <button
                  type="button"
                  onClick={() => onOpenAdjustment(entry)}
                  title={text("adjustmentMeaning")}
                  className="inline-flex items-center gap-1 rounded-lg border border-purple-200 bg-purple-50 px-2 py-1.5 text-[10px] font-black text-purple-800 outline-none focus-visible:ring-2 focus-visible:ring-purple-300"
                  data-cp13-ledger-correction="exceptional"
                  data-cp13-action-priority="exceptional"
                >
                  <TriangleAlert aria-hidden="true" className="h-3.5 w-3.5" />
                  {text("adjust")}
                </button>
              ) : null}
            </div>
          </article>
        );
      })}
    </div>
  );
}
