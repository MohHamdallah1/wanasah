import type { TFunction } from "i18next";
import { FileText, Eye } from "lucide-react";

import { formatLedgerDate, type LedgerEntry } from "./contracts";
import { ledgerBadgeClass, ledgerMovementLabel, ledgerText } from "./ledgerI18n";
import {
  ledgerBalance,
  ledgerLocationEvidence,
  ledgerMoney,
  ledgerSignedQuantity,
} from "./ledgerPresentation";
import { formatPublicBatchNumber } from "../publicBatchNumber";

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

export function LedgerTable({
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
    <div className="hidden min-h-0 flex-1 overflow-auto md:block">
      <table className="w-full min-w-[1260px] text-sm">
        <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50/95 text-start backdrop-blur">
          <tr>
            {(["movement", "product", "batch", "before", "quantity", "after", "evidence", "reference", "cost", "actor", "notes", "date"] as const).map((key) => (
              <th key={key} className="px-3 py-2 text-start text-[11px] font-black text-slate-500">{text(key)}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {entries.map((entry) => {
            const locations = ledgerLocationEvidence(t, language, entry);
            return (
              <tr key={entry.id} className="align-top hover:bg-slate-50/70">
                <td className="px-3 py-3">
                  <span className={`inline-flex rounded-md border px-2 py-1 text-[10px] font-black ${ledgerBadgeClass(entry.type)}`}>
                    {ledgerMovementLabel(t, language, entry.type)}
                  </span>
                  <div className="mt-1 text-[10px] font-semibold text-slate-400">#{entry.id}</div>
                </td>
                <td className="px-3 py-3 font-bold text-slate-800">{entry.product_name}</td>
                <td className="px-3 py-3 text-xs font-black text-slate-600">
                  {formatPublicBatchNumber(entry.batch_number, text("noLot"))}
                </td>
                <td className="px-3 py-3 text-xs font-semibold text-slate-500">{ledgerBalance(entry, entry.balance_before, unit)}</td>
                <td className="px-3 py-3 text-xs font-black text-slate-800">{ledgerSignedQuantity(entry, unit)}</td>
                <td className="px-3 py-3 text-xs font-black text-slate-700">{ledgerBalance(entry, entry.balance_after, unit)}</td>
                <td className="px-3 py-3 text-[10px] font-semibold leading-5 text-slate-600">
                  <div><span className="font-black">{text("source")}:</span> {locations.source}</div>
                  <div><span className="font-black">{text("destination")}:</span> {locations.destination}</div>
                </td>
                <td className="px-3 py-3">
                  {entry.reference ? (
                    <button
                      type="button"
                      onClick={() => onOpenReference(entry)}
                      aria-label={text("openReference", { reference: entry.reference })}
                      className="inline-flex max-w-48 items-center gap-1 rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-start text-[11px] font-bold text-blue-700 outline-none focus-visible:ring-2 focus-visible:ring-blue-300"
                    >
                      <FileText aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate">{entry.reference}</span>
                    </button>
                  ) : "—"}
                  {entry.supplier_name ? (
                    <div className="mt-1 text-[10px] font-semibold text-slate-500">
                      {text("supplier")}: {entry.supplier_name}{entry.supplier_code ? ` · ${entry.supplier_code}` : ""}
                    </div>
                  ) : null}
                </td>
                <td className="px-3 py-3 text-[10px] font-semibold leading-5 text-slate-600">
                  {entry.input_unit_cost ? (
                    <>
                      <div>{ledgerMoney(entry.input_unit_cost, entry.currency_code)} / {entry.input_uom_code ?? entry.base_uom_code}</div>
                      {entry.total_cost ? <div>{text("totalCost")}: {ledgerMoney(entry.total_cost, entry.currency_code)}</div> : null}
                      {entry.average_cost_after ? <div>{text("averageAfter")}: {ledgerMoney(entry.average_cost_after, entry.currency_code)}</div> : null}
                    </>
                  ) : "—"}
                </td>
                <td className="px-3 py-3 text-xs font-bold text-slate-600">{entry.admin_name || text("unknown")}</td>
                <td className="px-3 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    {entry.notes ? (
                      <button
                        type="button"
                        onClick={(event) => onOpenNotes(entry, event.currentTarget)}
                        aria-label={text("openNotes", { id: entry.id })}
                        className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-500 outline-none hover:text-slate-800 focus-visible:ring-2 focus-visible:ring-blue-300"
                      >
                        <Eye aria-hidden="true" className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                    {entry.type === "INBOUND_SUPPLIER" && canAdjust ? (
                      <button
                        type="button"
                        onClick={() => onOpenAdjustment(entry)}
                        className="rounded-lg border border-purple-100 bg-purple-50 px-2 py-1 text-[10px] font-black text-purple-700 outline-none focus-visible:ring-2 focus-visible:ring-purple-300"
                      >
                        {text("adjust")}
                      </button>
                    ) : null}
                  </div>
                </td>
                <td className="px-3 py-3 whitespace-nowrap text-[10px] font-semibold text-slate-500" dir="ltr">
                  {formatLedgerDate(entry.date, locale)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
