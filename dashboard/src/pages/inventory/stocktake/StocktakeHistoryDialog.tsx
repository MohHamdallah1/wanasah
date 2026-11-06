import { useEffect, useRef, useState } from "react";
import { Archive, ArrowLeft, ArrowRight, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import type { StocktakeAuthFetch } from "./types";
import { useStocktakeHistory, type HistorySession } from "./hooks/useStocktakeHistory";

interface Props {
  active: boolean;
  locationId: number;
  canRead: boolean;
  canReview: boolean;
  authenticatedFetch: StocktakeAuthFetch;
}
const words = {
  ar: {
    history: "سجل الجرد", caption: "الجرد المعتمد والملغى في المستودع المحدد فقط",
    loading: "جاري تحميل سجل الجرد…", empty: "لا توجد جردات معتمدة أو ملغاة لهذا المستودع.",
    unavailable: "تعذر تحميل السجل. أعد المحاولة.", retry: "إعادة المحاولة",
    denied: "لا تملك صلاحية مراجعة تفاصيل الجرد.",
    posted: "معتمد ومُرحّل", cancelled: "ملغى",
    full: "جرد شامل", product: "جرد صنف", review: "التفاصيل",
    start: "بدأ", end: "انتهى", startedBy: "بدأه", countedBy: "عدّه",
    approvedBy: "اعتمده", cancelledBy: "ألغاه", attempt: "محاولة العد",
    reason: "سبب الإلغاء", afterCount: "تم الإلغاء بعد تثبيت العد",
    beforeCount: "أُلغي قبل تثبيت العد", loadMore: "تحميل المزيد",
    back: "العودة للسجل", note: "ملاحظات الجرد", attempts: "محاولات العد",
    audit: "سجل الإجراءات", noAttempts: "لم تُثبّت أي محاولة عد.",
    noAudit: "لا توجد أحداث تدقيق إضافية.", noLines: "لا توجد أسطر عد.",
    actual: "الكمية الفعلية", expected: "الكمية المسجلة", variance: "الفرق",
    stockStatus: "الحالة", batch: "التشغيلة", submitted: "ثُبّت في",
    recountReason: "سبب إعادة العد", discovered: "بضاعة غير مدرجة سابقًا",
    movement: "قيود تسوية مخزنية معتمدة", noMovement: "الإلغاء لا يُنشئ قيد مخزون",
    auditPrefix: "إجراء", current: "المحدد",
    "STOCKTAKE_COUNT_SUBMITTED": "تثبيت العد",
    "STOCKTAKE_RECOUNT_AUTHORIZED": "تفويض إعادة العد",
    "STOCKTAKE_CANCELLED": "إلغاء الجرد",
    "STOCKTAKE_APPROVED_AND_POSTED": "الاعتماد والترحيل",
    "STOCKTAKE_APPROVAL_REJECTED": "رفض محاولة اعتماد",
    "STOCKTAKE_CANCEL_REJECTED": "رفض محاولة إلغاء",
    "AVAILABLE": "متاح", "QUARANTINED": "معزول", "BLOCKED": "موقوف",
    "RECALLED": "مسحوب", "DAMAGED": "تالف", "DISPOSAL_PENDING": "بانتظار الإتلاف",
  },
  en: {
    history: "Stocktake history", caption: "Posted and cancelled stocktakes for the selected warehouse only",
    loading: "Loading stocktake history…", empty: "No posted or cancelled stocktakes in this warehouse.",
    unavailable: "Unable to load history. Please try again.", retry: "Retry",
    denied: "You do not have permission to review stocktake details.",
    posted: "Posted", cancelled: "Cancelled",
    full: "Full count", product: "Product count", review: "Details",
    start: "Started", end: "Finished", startedBy: "Started by", countedBy: "Counted by",
    approvedBy: "Approved by", cancelledBy: "Cancelled by", attempt: "Count attempt",
    reason: "Cancellation reason", afterCount: "Cancelled after count submission",
    beforeCount: "Cancelled before count submission", loadMore: "Load more",
    back: "Back to history", note: "Stocktake notes", attempts: "Count attempts",
    audit: "Audit events", noAttempts: "No count attempt was submitted.",
    noAudit: "No additional audit events.", noLines: "No count lines.",
    actual: "Physical count", expected: "Recorded stock", variance: "Difference",
    stockStatus: "Status", batch: "Batch", submitted: "Submitted",
    recountReason: "Recount reason", discovered: "Previously unlisted stock",
    movement: "Posted adjustment movements", noMovement: "Cancellation does not create an inventory movement",
    auditPrefix: "Action", current: "Selected",
    "STOCKTAKE_COUNT_SUBMITTED": "Count submitted",
    "STOCKTAKE_RECOUNT_AUTHORIZED": "Recount authorized",
    "STOCKTAKE_CANCELLED": "Stocktake cancelled",
    "STOCKTAKE_APPROVED_AND_POSTED": "Approved and posted",
    "STOCKTAKE_APPROVAL_REJECTED": "Approval attempt rejected",
    "STOCKTAKE_CANCEL_REJECTED": "Cancellation attempt rejected",
    "AVAILABLE": "Available", "QUARANTINED": "Quarantined", "BLOCKED": "Blocked",
    "RECALLED": "Recalled", "DAMAGED": "Damaged", "DISPOSAL_PENDING": "Pending disposal",
  },
} as const;

export function StocktakeHistoryDialog({ active, locationId, canRead, canReview, authenticatedFetch }: Props) {
  const { i18n } = useTranslation();
  const lang = (i18n.resolvedLanguage || i18n.language || "ar").startsWith("ar") ? "ar" : "en";
  const text = words[lang];
  const dir = lang === "ar" ? "rtl" : "ltr";
  const [open, setOpen] = useState(false);
  const formerLocation = useRef(locationId);
  const enabled = active && canRead && open;
  const history = useStocktakeHistory({ enabled, locationId, authenticatedFetch });
  // A retained Stocktake tab never keeps a history portal visible across a
  // warehouse switch or a revoked capability, even during in-flight fetches.
  useEffect(() => {
    if (!active || !canRead || formerLocation.current !== locationId) setOpen(false);
    formerLocation.current = locationId;
  }, [active, canRead, locationId]);
  useEffect(() => {
    if (!canReview) history.back();
  }, [canReview, history.back]);
  const time = (v: string | null | undefined) => {
    if (!v) return "—";
    const date = new Date(v);
    return Number.isNaN(date.getTime()) ? v : new Intl.DateTimeFormat(
      lang === "ar" ? "ar" : "en", { dateStyle: "short", timeStyle: "short" }
    ).format(date);
  };
  const scope = (entry: HistorySession) => entry.stocktake_type === "FULL_COUNT"
    ? text.full
    : (entry.scope_product_name || text.product) +
      (entry.scope_batch_number ? " · " + entry.scope_batch_number : "");
  const current = history.detail?.session;
  const selectedAttempt = history.detail?.attempts.items.find(item => item.id === history.attemptId);
  const itemButton = "rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 hover:border-blue-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 disabled:opacity-40";
  return (
    <Dialog open={enabled} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button type="button" disabled={!active || !canRead}
          data-stocktake-history-trigger="true" className={itemButton + " inline-flex min-h-9 shrink-0 items-center gap-1.5"}>
          <Archive className="h-4 w-4" aria-hidden="true" />
          {text.history}
        </button>
      </DialogTrigger>
      <DialogContent dir={dir} data-stocktake-history="dialog"
        className="flex max-h-[min(92vh,55rem)] w-[calc(100vw-1.5rem)] max-w-4xl flex-col gap-0 overflow-hidden rounded-xl bg-white p-0">
        <DialogHeader className="shrink-0 border-b border-slate-200 px-4 py-3 pe-12 text-start">
          <DialogTitle className="text-base font-black text-slate-900">{text.history}</DialogTitle>
          <DialogDescription className="text-xs text-slate-500">{text.caption}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3 sm:p-4">
          {history.error && (
            <div role="alert" className="mb-3 flex items-center justify-between gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              <span>{text.unavailable}: {history.error}</span>
              <button className={itemButton} onClick={() => {
                if (history.detail) void history.selectSession(history.detail.session.id);
                else void history.fetchList();
              }}>{text.retry}</button>
            </div>
          )}
          {history.loadingDetail && <p role="status" className="p-4 text-sm">{text.loading}</p>}
          {current && (
            <section aria-label={current.reference_number} className="space-y-3">
              <button type="button" onClick={history.back} className={itemButton + " inline-flex items-center gap-1.5"}>
                {lang === "ar" ? <ArrowRight className="h-3.5 w-3.5" /> : <ArrowLeft className="h-3.5 w-3.5" />}
                {text.back}
              </button>
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <strong dir="ltr" className="text-sm">{current.reference_number}</strong>
                  <span className="rounded bg-white px-2 py-1 font-bold">{current.status === "POSTED" ? text.posted : text.cancelled}</span>
                  <span>{current.stocktake_type === "FULL_COUNT" ? text.full : current.scope_product_name || text.product}</span>
                  {current.scope_batch_number && <span>{current.scope_batch_number}</span>}
                </div>
                <div className="mt-2 grid gap-1 sm:grid-cols-2">
                  <span>{text.start}: {time(current.created_at)}</span>
                  <span>{text.end}: {time(current.finished_at)}</span>
                  <span>{text.movement}: <strong dir="ltr">{current.adjustment_movement_count}</strong></span>
                  {current.status === "CANCELLED" && <strong className="text-amber-800">
                    {current.cancelled_after_count ? text.afterCount : text.beforeCount}
                  </strong>}
                </div>
                {current.cancellation_reason && <p className="mt-2">{text.reason}: {current.cancellation_reason}</p>}
                {current.notes && <p className="mt-1">{text.note}: {current.notes}</p>}
                {current.status === "CANCELLED" && <p className="mt-1 font-semibold text-slate-600">{text.noMovement}</p>}
              </div>
              {current.status === "POSTED" && history.detail && (
                <section aria-label={text.movement} className="rounded-lg border border-slate-200 p-3 text-xs">
                  <h3 className="mb-1 font-black">{text.movement} · <span dir="ltr">{current.adjustment_movement_count}</span></h3>
                  <ul className="space-y-1">
                    {history.detail.movements.items.map(item => (
                      <li key={item.id} className="flex flex-wrap gap-2 text-slate-700">
                        <span dir="ltr">#{item.id}</span>
                        <span dir="ltr">{item.reference_id}</span>
                        <span dir="ltr">{item.quantity}</span>
                      </li>
                    ))}
                  </ul>
                  {history.detail.movements.next_cursor && (
                    <button type="button" className={itemButton + " mt-2"}
                      disabled={history.loadingMore} onClick={() => void history.loadDetailPage("movements")}>
                      {text.loadMore}
                    </button>
                  )}
                </section>
              )}
              <section aria-label={text.attempts}>
                <h3 className="mb-2 text-xs font-black text-slate-900">{text.attempts}</h3>
                {history.detail?.attempts.items.length === 0 && <p className="text-xs text-slate-500">{text.noAttempts}</p>}
                <div className="flex flex-wrap gap-2">
                  {history.detail?.attempts.items.map(attempt => (
                    <button type="button" key={attempt.id}
                      aria-pressed={attempt.id === history.attemptId}
                      className={itemButton + (attempt.id === history.attemptId ? " border-blue-500 bg-blue-50 text-blue-800" : "")}
                      onClick={() => void history.selectAttempt(current.id, attempt.id)}>
                      {text.attempt} <span dir="ltr">#{attempt.attempt_number}</span> · {attempt.counted_by_name}
                    </button>
                  ))}
                </div>
                {history.detail?.attempts.next_cursor && (
                  <button type="button" className={itemButton + " mt-2"} disabled={history.loadingMore}
                    onClick={() => void history.loadDetailPage("attempts")}>{text.loadMore}</button>
                )}
              </section>
              {selectedAttempt && (
                <section aria-label={text.actual} className="space-y-2">
                  <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                    {text.submitted}: {time(selectedAttempt.submitted_at)}
                    {selectedAttempt.recount_reason && <span className="ms-2">
                      {text.recountReason}: {selectedAttempt.recount_reason}
                    </span>}
                  </div>
                  {history.loadingLines && <p role="status" className="text-xs">{text.loading}</p>}
                  {!history.loadingLines && history.lines.length === 0 && <p className="text-xs">{text.noLines}</p>}
                  <div role="list" className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                    {history.lines.map(line => (
                      <article role="listitem" key={line.id} className="p-3 text-xs">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-semibold">
                          <span>{line.product_name}</span>
                          <span>{text.batch}: {line.batch_number || "—"}</span>
                          <span>{text.stockStatus}: {text[line.stock_status as keyof typeof text] || line.stock_status}</span>
                          {line.line_origin === "DISCOVERED" && <span className="text-blue-700">{text.discovered}</span>}
                        </div>
                        <div className="mt-2 grid grid-cols-3 gap-2">
                          <div><span className="block text-[10px] text-slate-500">{text.expected}</span><strong dir="ltr">{line.expected_quantity} {line.base_uom_name}</strong></div>
                          <div><span className="block text-[10px] text-slate-500">{text.actual}</span><strong dir="ltr">{line.actual_quantity} {line.base_uom_name}</strong></div>
                          <div><span className="block text-[10px] text-slate-500">{text.variance}</span><strong dir="ltr">{line.variance_quantity} {line.base_uom_name}</strong></div>
                        </div>
                      </article>
                    ))}
                  </div>
                  {history.linesNext && <button type="button" className={itemButton}
                    disabled={history.loadingLines} onClick={history.loadMoreLines}>{text.loadMore}</button>}
                </section>
              )}
              <section aria-label={text.audit} className="space-y-2 border-t border-slate-200 pt-3">
                <h3 className="text-xs font-black">{text.audit}</h3>
                {history.detail?.audit.items.length === 0 && <p className="text-xs">{text.noAudit}</p>}
                <ol className="space-y-1">
                  {history.detail?.audit.items.map(event => (
                    <li key={event.id} className="rounded-lg bg-slate-50 p-2 text-xs">
                      <strong>{text[event.action_type as keyof typeof text] || text.auditPrefix}</strong>
                      <span className="ms-2 text-slate-600">{time(event.timestamp)} · {event.actor_name || "—"}</span>
                      {event.details.reason && <p>{text.reason}: {String(event.details.reason)}</p>}
                      {event.details.attempt_number && <p>{text.attempt} #{String(event.details.attempt_number)}</p>}
                    </li>
                  ))}
                </ol>
                {history.detail?.audit.next_cursor && <button type="button" className={itemButton}
                  disabled={history.loadingMore} onClick={() => void history.loadDetailPage("audit")}>{text.loadMore}</button>}
              </section>
            </section>
          )}
          {!current && !history.loadingDetail && (
            <section aria-label={text.history}>
              {history.loading && <p role="status" className="p-4 text-sm">{text.loading}</p>}
              {!history.loading && history.sessions.length === 0 && !history.error && (
                <p role="status" className="rounded-lg bg-slate-50 p-4 text-sm">{text.empty}</p>
              )}
              <div role="list" className="divide-y divide-slate-100">
                {history.sessions.map(entry => (
                  <article role="listitem" key={entry.id} className="flex flex-wrap items-center justify-between gap-3 py-3 sm:flex-nowrap">
                    <div className="min-w-0 flex-1 space-y-1 text-xs text-slate-600">
                      <div className="flex flex-wrap items-center gap-2">
                        <strong className="text-sm text-slate-900" dir="ltr">{entry.reference_number}</strong>
                        <span className={entry.status === "POSTED" ? "text-emerald-700" : "text-slate-500"}>
                          {entry.status === "POSTED" ? text.posted : text.cancelled}
                        </span>
                        <span>{scope(entry)}</span>
                      </div>
                      <p>{text.start}: {time(entry.created_at)} · {text.end}: {time(entry.finished_at)}</p>
                      <p>{text.startedBy}: {entry.started_by_name}
                        {entry.counted_by_name && " · " + text.countedBy + ": " + entry.counted_by_name}
                        {entry.approved_by_name && " · " + text.approvedBy + ": " + entry.approved_by_name}
                        {entry.cancelled_by_name && " · " + text.cancelledBy + ": " + entry.cancelled_by_name}
                      </p>
                      {entry.status === "CANCELLED" && <p className="font-bold text-amber-800">
                        {entry.cancelled_after_count ? text.afterCount : text.beforeCount}
                        {entry.cancellation_reason && " · " + text.reason + ": " + entry.cancellation_reason}
                      </p>}
                    </div>
                    <button type="button" className={itemButton} disabled={!canReview}
                      title={!canReview ? text.denied : undefined}
                      onClick={() => void history.selectSession(entry.id)}>{text.review}</button>
                  </article>
                ))}
              </div>
              {history.next && <button type="button" className={itemButton + " mt-3 w-full"}
                disabled={history.loadingMore} onClick={history.loadMoreSessions}>
                {history.loadingMore ? text.loading : text.loadMore}
              </button>}
              {!canReview && history.sessions.length > 0 &&
                <p className="mt-2 text-xs text-slate-500">{text.denied}</p>}
            </section>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
