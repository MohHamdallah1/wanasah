import { History, ChevronLeft, ChevronRight } from "lucide-react";
import { useStocktakeUiCopy } from "./uiCopy";
import { parseQuantity } from "../quantity";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import type { StocktakeAuthFetch } from "./types";
import { useStocktakeHistory } from "./hooks/useStocktakeHistory";


// Locale-aware decimal rendering without converting canonical quantities to floating-point.
const formatHistoryQuantity = (value: string, arabic: boolean): string => {
  const parsed = parseQuantity(value, "history.quantity", { allowZero: true, allowNegative: true });
  const [integer, decimals] = parsed.split(".");
  const locale = arabic ? "ar-QA" : "en-GB";
  const whole = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(BigInt(integer));
  if (!decimals) return whole;
  const symbols = new Intl.NumberFormat(locale, { minimumFractionDigits: 1 }).formatToParts(1.1);
  const separator = symbols.find(part => part.type === "decimal")?.value ?? ".";
  const digits = decimals.replace(/[0-9]/g, digit =>
    new Intl.NumberFormat(locale, { useGrouping: false }).format(Number(digit)));
  return `${whole}${separator}${digits}`;
};

type Props = {
  open: boolean; onOpenChange: (next: boolean) => void; locationId: number;
  enabled: boolean; authenticatedFetch: StocktakeAuthFetch;
};
export function StocktakeHistoryDialog({ open, onOpenChange, locationId, enabled, authenticatedFetch }: Props) {
  const { copy, dir, isArabic: isAr } = useStocktakeUiCopy();
  const t = copy.history;
  const history = useStocktakeHistory({ enabled: enabled && open, locationId, authenticatedFetch });
  const detail = history.detail;
  const format = (value: string | null | undefined) => value
    ? new Date(value).toLocaleString(isAr ? "ar-QA" : "en-GB") : "—";
  return (
    <Dialog open={open && enabled} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <button type="button" disabled={!enabled} data-stocktake-history-trigger="true"
          className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-black text-slate-700 hover:border-blue-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 disabled:opacity-40">
          <History className="h-4 w-4" aria-hidden="true" />{t.title}
        </button>
      </DialogTrigger>
      <DialogContent dir={dir}
        data-stocktake-history="dialog"
        className="flex max-h-[90vh] w-[calc(100vw-1rem)] max-w-5xl flex-col gap-0 overflow-hidden rounded-xl bg-white p-0">
        <DialogHeader className="shrink-0 border-b px-4 py-3 pe-12 text-start">
          <DialogTitle className="text-base font-black">{t.title}</DialogTitle>
          <DialogDescription className="text-xs">{t.desc}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
          {detail && (
            <button type="button" onClick={history.back}
              className="mb-3 inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-bold">
              {isAr ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}{t.back}
            </button>
          )}
          {history.error && <p role="alert" className="mb-3 rounded bg-red-50 p-3 text-sm text-red-700">{t.error}</p>}
          {history.busy && <p role="status" className="mb-2 text-xs text-slate-500">{t.loading}</p>}
          {!detail ? (
            <div className="space-y-2">
              {!history.busy && history.history.length === 0 && !history.error &&
                <p role="status" className="p-4 text-sm text-slate-500">{t.empty}</p>}
              {history.history.map(item => (
                <article key={item.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <strong dir="ltr" className="text-slate-900">{item.reference_number}</strong>
                        <span className={item.status === "POSTED" ? "rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800" : "rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700"}>
                          {item.status === "POSTED" ? t.posted : t.cancelled}
                        </span>
                        <span className="text-xs">{item.stocktake_type === "FULL_COUNT" ? t.full : t.product}{item.scope_product_name ? ` · ${item.scope_product_name}` : ""}</span>
                      </div>
                      {item.cancelled_after_count && <p className="text-xs font-black text-amber-800">{t.after}</p>}
                      <p className="text-xs text-slate-600">
                        {t.created}: {format(item.created_at)} · {t.finished}: {format(item.finished_at)}
                      </p>
                      <p className="text-xs text-slate-600">
                        {t.startedBy}: {item.started_by_name || "—"} · {t.counter}: {item.counted_by_name || "—"} ·
                        {item.status === "POSTED" ? t.approvedBy : t.cancelledBy}: {item.approved_by_name || item.cancelled_by_name || "—"}
                      </p>
                      {item.cancellation_reason && <p className="text-xs">{t.reason}: {item.cancellation_reason}</p>}
                    </div>
                    <button type="button" disabled={history.busy} onClick={() => void history.loadDetails(item.id)}
                      className="rounded-lg border border-blue-200 px-3 py-2 text-xs font-bold text-blue-800 disabled:opacity-40">
                      {t.open}
                    </button>
                  </div>
                </article>
              ))}
              {history.nextCursor &&
                <button type="button" disabled={history.busy} onClick={() => void history.moreHistory()}
                  className="w-full rounded-lg bg-blue-50 px-3 py-2 text-xs font-bold text-blue-800 disabled:opacity-40">
                  {t.more}
                </button>}
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-lg bg-slate-50 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <strong dir="ltr">{detail.reference_number}</strong>
                  <span>{detail.status === "POSTED" ? t.posted : t.cancelled}</span>
                  {detail.cancelled_after_count && <strong className="text-amber-800">{t.after}</strong>}
                </div>
                <p className="mt-1 text-xs">{t.created}: {format(detail.created_at)} · {t.finished}: {format(detail.finished_at)}</p>
                <p className="mt-1 text-xs">{t.startedBy}: {detail.started_by_name || "—"} · {t.approvedBy}: {detail.approved_by_name || "—"} · {t.cancelledBy}: {detail.cancelled_by_name || "—"}</p>
                {detail.cancellation_reason && <p className="mt-1 text-xs">{t.reason}: {detail.cancellation_reason}</p>}
                {detail.notes && <p className="mt-1 text-xs">{t.note}: {detail.notes}</p>}
              </div>
              <section aria-label={t.attempts}>
                <h3 className="mb-2 font-bold">{t.attempts}</h3>
                {detail.attempts.length === 0 && <p className="text-xs text-slate-500">{t.noAttempts}</p>}
                <div className="space-y-2">
                  {detail.attempts.map(attempt => (
                    <div key={attempt.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-2 text-xs">
                      <div>
                        <strong>{t.attempt} {attempt.attempt_number}</strong> · {t.counter}: {attempt.counted_by_name || "—"}
                        <p>{format(attempt.submitted_at)}{attempt.authorized_by_name ? ` · ${attempt.authorized_by_name}` : ""}</p>
                        {attempt.recount_reason && <p>{t.recountReason}: {attempt.recount_reason}</p>}
                      </div>
                      <button type="button" disabled={history.busy} onClick={() => void history.loadLines(attempt.id)}
                        className="rounded-lg border px-3 py-2 font-bold disabled:opacity-40">{t.showLines}</button>
                    </div>
                  ))}
                </div>
                {detail.next_cursor && <button type="button" disabled={history.busy}
                  onClick={() => void history.moreAttempts()} className="mt-2 rounded border px-3 py-2 text-xs font-bold">
                  {t.more}
                </button>}
              </section>
              {history.selectedAttemptId !== null &&
                <section aria-label={t.lines} className="rounded-lg border border-slate-200">
                  <h3 className="border-b bg-slate-50 px-3 py-2 font-bold">{t.lines} · {t.attempt} {detail.attempts.find(a => a.id === history.selectedAttemptId)?.attempt_number}</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[660px] text-start text-xs">
                      <thead><tr className="border-b bg-slate-50">
                        {[t.productCol, t.batch, t.status, t.expected, t.actual, t.variance].map(col => <th key={col} scope="col" className="p-2 text-start">{col}</th>)}
                      </tr></thead>
                      <tbody>{history.lines.map(line => (
                        <tr key={line.id} className="border-b">
                          <td className="p-2">{line.product_name}</td>
                          <td className="p-2">{line.batch_number || `#${line.batch_id}`}</td>
                          <td className="p-2">{copy.stockStatuses[line.stock_status as keyof typeof copy.stockStatuses] || line.stock_status}</td>
                          {[line.expected_quantity, line.actual_quantity, line.variance_quantity].map((number, idx) => (
                            <td key={idx} className="p-2"><bdi dir="ltr">{formatHistoryQuantity(number, isAr)}</bdi> <bdi dir="auto">{line.base_uom_name}</bdi></td>
                          ))}
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>
                  {history.lineCursor && <button type="button" disabled={history.busy}
                    onClick={() => void history.loadLines(history.selectedAttemptId!, history.lineCursor!)}
                    className="m-2 rounded border px-3 py-2 text-xs font-bold">{t.more}</button>}
                </section>}
              <section aria-label={t.audit}>
                <h3 className="mb-2 font-bold">{t.audit}</h3>
                <ol className="space-y-1">{detail.audit.map(event => (
                  <li key={event.id} className="rounded bg-slate-50 p-2 text-xs">
                    {format(event.at)} · <strong>{t.auditActions[event.action_type as keyof typeof t.auditActions] || event.action_type}</strong> · {event.actor_name || "—"}
                    {event.old_value && <p className="break-words text-slate-500">{event.old_value}</p>}
                    {event.new_value && <p className="break-words text-slate-500">{event.new_value}</p>}
                  </li>
                ))}</ol>
              </section>
            </div>
          )}
        </div>
        <p className="shrink-0 border-t px-4 py-2 text-xs text-slate-500">{t.readOnly}</p>
      </DialogContent>
    </Dialog>
  );
}
