import { Boxes, Car, ChevronDown, ClipboardCheck } from "lucide-react";
import { useId, useState } from "react";
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
  onLoadMore, onOpenSession,
}: StocktakeSessionCenterProps) {
  const { t } = useTranslation();
  const { copy, dir } = useStocktakeUiCopy();
  const text = copy.sessions;
  // Expanded by default so no actionable session is silently hidden.
  const [expanded, setExpanded] = useState(true);
  const listId = useId();

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

  return (
    <section dir={dir} data-stocktake-sessions="compact" aria-label={text.title}
      className="shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-white/90">
      <button type="button" aria-expanded={expanded} aria-controls={listId}
        onClick={() => setExpanded(value => !value)}
        className="flex min-h-10 w-full items-center gap-2 px-3 py-2 text-start hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
        <ClipboardCheck className="h-4 w-4 shrink-0 text-[#1e87bb]" aria-hidden="true" />
        <span className="text-xs font-black text-slate-800">{text.title}</span>
        <span className="min-w-0 truncate text-[11px] text-slate-500">
          {total !== null ? text.total(total) : text.sourceServer}
        </span>
        <ChevronDown className={`ms-auto h-4 w-4 shrink-0 text-slate-500 transition-transform ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>

      <div id={listId} hidden={!expanded} className="border-t border-slate-100">
        {loading && sessions.length === 0 ? (
          <p role="status" className="px-3 py-2 text-xs text-slate-500">{text.loading}</p>
        ) : sessions.length === 0 ? (
          <p className="px-3 py-2 text-xs text-slate-500">{text.empty}</p>
        ) : (
          <>
            <div role="list" className="max-h-40 overflow-y-auto divide-y divide-slate-100" data-stocktake-session-list="true">
              {sessions.map((session) => {
                const selected = currentSessionId === session.id;
                const TypeIcon = session.stocktake_type === "VEHICLE_RECON" ? Car : Boxes;
                return (
                  <div role="listitem" key={session.id}
                    className={`flex min-w-0 flex-wrap items-center justify-between gap-2 px-3 py-2 sm:flex-nowrap ${selected ? "bg-blue-50/60" : "hover:bg-slate-50"}`}>
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
                    <button type="button"
                      disabled={!canOpenSession(session.status) || selected}
                      aria-current={selected ? "true" : undefined}
                      onClick={() => void onOpenSession(session)}
                      className="shrink-0 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-black text-slate-700 hover:border-blue-300 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-40">
                      {selected ? text.opened : text.open}
                    </button>
                  </div>
                );
              })}
            </div>
            {nextCursor && (
              <div className="border-t border-slate-100 px-3 py-1.5">
                <button type="button" onClick={onLoadMore} disabled={loadingMore}
                  className="w-full rounded-lg bg-blue-50 px-2 py-1.5 text-xs font-bold text-blue-700 hover:bg-blue-100 disabled:opacity-50">
                  {loadingMore ? text.loadingMore : text.loadMore}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
