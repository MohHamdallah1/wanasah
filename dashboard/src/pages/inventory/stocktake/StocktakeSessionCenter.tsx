import { Boxes, Car, ClipboardCheck } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { useTranslation } from "react-i18next";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { useStocktakeUiCopy } from "./uiCopy";
import type { StocktakeSessionSummary, StocktakeStatus } from "./types";

interface StocktakeSessionCenterProps {
  sessions: StocktakeSessionSummary[];
  total: number | null;
  loading: boolean;
  loadingMore: boolean;
  nextCursor: string | null;
  currentSessionId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canRead: boolean;
  onLoadMore: () => void;
  onOpenSession: (session: StocktakeSessionSummary) => void | Promise<void>;
}

const STATUS_CLASS: Record<StocktakeStatus, string> = {
  DRAFT: "bg-slate-100 text-slate-600",
  COUNTING: "bg-amber-50 text-amber-700",
  PENDING_REVIEW: "bg-blue-50 text-blue-700",
  RECOUNT_REQUIRED: "bg-red-50 text-red-700",
  APPROVED: "bg-emerald-50 text-emerald-700",
  POSTED: "bg-emerald-50 text-emerald-700",
  CANCELLED: "bg-slate-100 text-slate-500",
};

const canOpenSession = (status: StocktakeStatus): boolean =>
  status === "COUNTING" || status === "PENDING_REVIEW" || status === "RECOUNT_REQUIRED";

export function StocktakeSessionCenter({
  sessions, total, loading, loadingMore, nextCursor, currentSessionId,
  open, onOpenChange, canRead, onLoadMore, onOpenSession,
}: StocktakeSessionCenterProps) {
  const { t, i18n } = useTranslation();
  const { copy, dir } = useStocktakeUiCopy();
  const text = copy.sessions;

  const sessionScope = (session: StocktakeSessionSummary): string => {
    if (session.stocktake_type === "FULL_COUNT") return text.entireLocation;
    if (session.stocktake_type === "VEHICLE_RECON") {
      return session.related_work_session_id
        ? text.workSession(session.related_work_session_id)
        : text.unspecifiedWorkSession;
    }
    const product = session.scope_product_name || text.product(session.scope_product_variant_id ?? "—");
    return session.scope_batch_id !== null
      ? `${product} · ${text.batch} ${formatPublicBatchNumber(session.scope_batch_number, t("inventoryLive.noLotSupplied"))}`
      : product;
  };

  const count = total ?? sessions.length;
  // Reuse the existing AR/EN session noun from "Refresh sessions" rather than
  // hardcode copy or modify the separately owned translation catalog.
  const language = i18n.resolvedLanguage || i18n.language || "ar";
  const sessionNoun = text.refresh.trim().split(/\\s+/).at(-1) || text.title;
  const shortTitle = dir === "ltr"
    ? sessionNoun.replace(/^./u, (letter) => letter.toLocaleUpperCase(language))
    : sessionNoun;
  const triggerLabel = `${shortTitle} (${new Intl.NumberFormat(language).format(count)})`;

  return (
    <Dialog open={open && canRead} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <button
          type="button"
          data-stocktake-sessions-trigger="true"
          disabled={!canRead}
          aria-label={triggerLabel}
          className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-black text-slate-700 hover:border-blue-300 hover:text-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ClipboardCheck className="h-4 w-4" aria-hidden="true" />
          <span>{triggerLabel}</span>
        </button>
      </DialogTrigger>
      <DialogContent
        dir={dir}
        data-stocktake-sessions="dialog"
        className="flex max-h-[min(88vh,46rem)] w-[calc(100vw-1.5rem)] max-w-3xl flex-col gap-0 overflow-hidden rounded-xl bg-white p-0"
      >
        <DialogHeader className="shrink-0 border-b border-slate-200 px-4 py-4 pe-12 text-start">
          <DialogTitle className="text-base font-black text-slate-900">{text.title}</DialogTitle>
          <DialogDescription className="text-xs text-slate-500">
            {total !== null ? text.total(total) : text.sourceServer}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto" data-stocktake-session-list-container="true">
          {loading && sessions.length === 0 ? (
            <p role="status" className="px-4 py-5 text-sm text-slate-500">{text.loading}</p>
          ) : sessions.length === 0 ? (
            <p role="status" className="px-4 py-5 text-sm text-slate-500">{text.empty}</p>
          ) : (
            <div role="list" className="divide-y divide-slate-100" data-stocktake-session-list="true">
              {sessions.map((session) => {
                const selected = currentSessionId === session.id;
                const TypeIcon = session.stocktake_type === "VEHICLE_RECON" ? Car : Boxes;
                return (
                  <div
                    role="listitem"
                    key={session.id}
                    className={`flex min-w-0 flex-wrap items-center justify-between gap-3 px-4 py-3 sm:flex-nowrap ${selected ? "bg-blue-50/60" : "hover:bg-slate-50"}`}
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <TypeIcon className="h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-xs font-black text-slate-800">{text.types[session.stocktake_type]}</span>
                          <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${STATUS_CLASS[session.status]}`}>{text.statuses[session.status]}</span>
                          {session.pending_independent_recount_required && (
                            <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-bold text-red-700">{text.independent}</span>
                          )}
                        </div>
                        <p className="truncate text-[11px] text-slate-500" dir="auto">
                          {session.reference_number} · {sessionScope(session)} · {text.startedBy} {session.started_by_name}
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      disabled={!canOpenSession(session.status) || selected}
                      aria-current={selected ? "true" : undefined}
                      onClick={() => void onOpenSession(session)}
                      className="shrink-0 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-black text-slate-700 hover:border-blue-300 hover:text-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {selected ? text.opened : text.open}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        {nextCursor && (
          <div className="shrink-0 border-t border-slate-100 p-3">
            <button type="button" onClick={onLoadMore} disabled={loadingMore}
              className="w-full rounded-lg bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700 hover:bg-blue-100 disabled:opacity-50">
              {loadingMore ? text.loadingMore : text.loadMore}
            </button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
