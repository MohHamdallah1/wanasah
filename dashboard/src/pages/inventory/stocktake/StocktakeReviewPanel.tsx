import { AlertTriangle, Info, RotateCcw, ShieldCheck } from "lucide-react";
import { absoluteQuantity, compareQuantity, formatQuantity } from "../quantity";
import { useTranslation } from "react-i18next";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { useStocktakeUiCopy } from "./uiCopy";
import type { StocktakeReview } from "./types";

interface StocktakeReviewPanelProps {
  warehouseName?: string | null;
  scopeProductName?: string | null;
  review: StocktakeReview;
  totals: { total: number; matched: number; shortage: number; overage: number; varianceItems: number };
  approvalBlocked: boolean;
  onVariance: () => void;
  canCancel: boolean;
  onCancel: () => void;
  canRecount: boolean;
  onRecount: () => void;
  canApprove: boolean;
  onApprove: () => void;
}

export function StocktakeReviewPanel({
  warehouseName, scopeProductName,
  review, totals, approvalBlocked, onVariance, canCancel, onCancel,
  canRecount, onRecount, canApprove, onApprove,
}: StocktakeReviewPanelProps) {
  const { t } = useTranslation();
  const { copy, dir } = useStocktakeUiCopy();
  const text = copy.review;
  const stages = [copy.workspace.countStep, copy.workspace.reviewStep, copy.workspace.approveStep];
  const typeLabel = copy.sessions.types[review.stocktake_type];
  const scopeLabel = scopeProductName || (review.stocktake_type === "CYCLE_COUNT" ? copy.workspace.productUnknown : copy.workspace.allProducts);

  // Preserve the timestamp and its original offset; do not infer a local timezone.
  const displayTimestamp = (value: string) => value.replace("T", " ").replace(/Z$/, " UTC");

  // Never let the bidirectional algorithm reverse a mixed Arabic unit and a
  // decimal/sign. The reading order is quantity then unit in both languages.
  const showQuantity = (quantity: string, unit: string, sign = "") => {
    const number = `${sign}${formatQuantity(quantity, "").trim()}`;
    return (
      <span dir={dir} className="inline-flex items-baseline justify-center gap-1 whitespace-nowrap"
        data-stocktake-review-quantity="true" aria-label={`${number} ${unit}`}>
        <bdi dir="ltr">{number}</bdi>
        <bdi dir="auto">{unit}</bdi>
      </span>
    );
  };

  return (
    <div dir={dir} className="glass-card inventory-data-panel flex h-full min-w-0 min-h-0 flex-1 flex-col overflow-hidden border border-slate-200 shadow-sm">
      <header className="shrink-0 border-b border-slate-700 bg-slate-900 px-3 py-2 text-white">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
            <h2 className="shrink-0 text-sm font-black">{typeLabel}</h2>
            <span className="min-w-0 truncate text-xs font-semibold text-slate-200"
              title={scopeLabel} aria-label={`${copy.workspace.scope}: ${scopeLabel}`}>
              {scopeLabel}
            </span>
            <span role="note" tabIndex={0} aria-label={text.reviewHelp} title={text.reviewHelp}
              className="inline-flex shrink-0 rounded p-0.5 text-slate-300 outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
              <Info className="h-3.5 w-3.5" aria-hidden="true" />
            </span>
          </div>
          <span className="shrink-0 text-[11px] font-bold text-slate-300" title={copy.workspace.reference}>
            <span dir="ltr">{review.reference_number}</span>
          </span>
          <span className="shrink-0 text-[11px] font-bold text-slate-300">
            {text.attempt} <span dir="ltr">#{review.latest_attempt.attempt_number}</span>
          </span>
          <ol aria-label={copy.workspace.stages}
            className="order-3 flex w-full items-center justify-center gap-1 text-[10px] font-bold sm:order-none sm:w-auto">
            {stages.map((stage, index) => (
              <li key={stage} aria-current={index === 1 ? "step" : undefined}
                className={`rounded px-1.5 py-0.5 ${index === 1 ? "bg-amber-400 text-slate-950" : "text-slate-300"}`}>
                {index + 1}. {stage}
              </li>
            ))}
          </ol>
        </div>
        <span className="sr-only">{copy.counting.warehouseContext}: <strong>{warehouseName || copy.counting.warehouseUnknown}</strong></span>
      </header>

      <details className="mx-3 mt-2 shrink-0 rounded-lg border border-slate-200 bg-slate-50 text-slate-700">
        <summary className="cursor-pointer px-3 py-1.5 text-xs font-bold focus-visible:ring-2 focus-visible:ring-blue-500">
          {text.historyTitle} (<span dir="ltr">{review.attempt_history.length}</span>)
        </summary>
        <ol aria-label={text.historyTitle} className="max-h-40 space-y-2 overflow-y-auto border-t border-slate-200 px-3 py-2 text-xs">
          {review.attempt_history.map((attempt) => (
            <li key={attempt.id} className="rounded-md bg-white px-3 py-2 border border-slate-100">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <strong>{text.attempt} <span dir="ltr">#{attempt.attempt_number}</span></strong>
                <span>{text.countedBy}: {attempt.counted_by_name} <span dir="ltr">#{attempt.counted_by}</span></span>
                {attempt.submitted_at && (
                  <span>{text.submittedAt}: <time dir="ltr" dateTime={attempt.submitted_at}>{displayTimestamp(attempt.submitted_at)}</time></span>
                )}
              </div>
              {attempt.authorized_by_name && (
                <div className="mt-1">{text.authorizedBy}: {attempt.authorized_by_name}
                  {attempt.authorized_by !== null && <span dir="ltr"> #{attempt.authorized_by}</span>}
                </div>
              )}
              {attempt.recount_reason && <div className="mt-1 break-words">{text.recountReason}: {attempt.recount_reason}</div>}
            </li>
          ))}
        </ol>
      </details>

      {approvalBlocked && (
        <div className="mx-4 mt-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-xs font-bold flex items-center gap-2" role="alert">
          <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
          {text.independentRequired}
        </div>
      )}

      <div className="md:hidden min-w-0 flex-1 min-h-0 overflow-y-auto overscroll-contain bg-slate-50 p-2 space-y-2">
        {review.lines.map((line) => {
          const variance = compareQuantity(line.variance_quantity, "0");
          return (
            <article key={line.attempt_line_id} className="rounded-xl border border-slate-200 bg-white p-3">
              <div className="font-bold text-slate-800">{line.product_name}</div>
              <div className="text-xs text-slate-500 mt-1">
                {formatPublicBatchNumber(line.batch_number, t("inventoryLive.noLotSupplied"))}
                <span className="ms-2">{text.expiry}: <span dir="ltr">{line.expiry_date ?? "—"}</span></span>
              </div>
              {line.line_origin === "DISCOVERED" && (
                <span className="mt-1 inline-flex rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-bold text-blue-700">{text.discovered}</span>
              )}
              <span className="mt-2 inline-flex rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[10px] font-black text-slate-700">
                {text.stockStatus}: {copy.stockStatuses[line.stock_status]}
              </span>
              <dl className="grid grid-cols-3 gap-2 mt-3 text-center">
                <div><dt className="text-[10px] text-slate-400 font-bold">{text.expected}</dt><dd className="text-sm font-black text-slate-700">{showQuantity(line.expected_quantity, line.base_uom_name)}</dd></div>
                <div><dt className="text-[10px] text-slate-400 font-bold">{text.counted}</dt><dd className="text-sm font-black text-blue-700">{showQuantity(line.actual_quantity, line.base_uom_name)}</dd></div>
                <div><dt className="text-[10px] text-slate-400 font-bold">{text.variance}</dt><dd className="text-sm font-black">{variance === 0 ? text.match : showQuantity(absoluteQuantity(line.variance_quantity), line.base_uom_name, variance > 0 ? "+" : "-")}</dd></div>
              </dl>
            </article>
          );
        })}
      </div>

      <div className="hidden md:block min-w-0 flex-1 min-h-0 overflow-auto overscroll-contain custom-scrollbar bg-white">
        <table className="w-full min-w-[850px] text-sm" aria-label={copy.workspace.reviewTable}>
          <thead className="bg-slate-50 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
            <tr>
              <th className="px-3 py-2 text-xs font-bold text-slate-500 text-start">{text.product}</th>
              <th className="px-3 py-2 text-xs font-bold text-slate-500 text-start">{text.batch}</th>
              <th className="px-3 py-2 text-xs font-bold text-slate-500 text-center">{text.stockStatus}</th>
              <th className="px-3 py-2 text-xs font-bold text-slate-500 text-center">{text.expected}</th>
              <th className="px-3 py-2 text-xs font-bold text-[#1e87bb] text-center">{text.countedFixed}</th>
              <th className="px-3 py-2 text-xs font-bold text-slate-500 text-center">{text.variance}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 bg-white">
            {review.lines.map((line) => {
              const variance = compareQuantity(line.variance_quantity, "0");
              return (
                <tr key={line.attempt_line_id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-3 py-2 font-bold text-slate-800">{line.product_name}</td>
                  <td className="px-3 py-2 text-xs text-slate-500 font-bold">
                    <div>{formatPublicBatchNumber(line.batch_number, t("inventoryLive.noLotSupplied"))}</div>
                    <div className="mt-1 font-normal">{text.expiry}: <span dir="ltr">{line.expiry_date ?? "—"}</span></div>
                    {line.line_origin === "DISCOVERED" && <span className="mt-1 inline-flex rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-bold text-blue-700">{text.discovered}</span>}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className="inline-flex rounded-full border border-slate-200 bg-slate-100 px-2 py-1 text-[10px] font-black text-slate-700">
                      {copy.stockStatuses[line.stock_status]}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-center font-black text-slate-700" dir="ltr">{showQuantity(line.expected_quantity, line.base_uom_name)}</td>
                  <td className="px-3 py-2 text-center font-black text-blue-700" dir="ltr">{showQuantity(line.actual_quantity, line.base_uom_name)}</td>
                  <td className="px-3 py-2 text-center">
                    {variance === 0 ? <span className="text-slate-500 font-bold">{text.match}</span> : (
                      <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-black ${variance > 0 ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>
                        {showQuantity(absoluteQuantity(line.variance_quantity), line.base_uom_name, variance > 0 ? "+" : "-")}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="bg-slate-900 text-white rounded-b-2xl overflow-hidden border-t border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 md:px-4">
          <div className="flex items-center gap-5">
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold">{text.matched}</span><span className="text-sm font-extrabold text-emerald-400" dir="ltr">{totals.matched}/{totals.total}</span></div>
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold">{text.varianceLines}</span><span className={`text-sm font-extrabold ${totals.varianceItems ? "text-red-400" : "text-slate-300"}`} dir="ltr">{totals.varianceItems}</span></div>
            {totals.varianceItems > 0 && <button type="button" onClick={onVariance} className="text-xs font-bold bg-red-500/20 text-red-300 hover:bg-red-500/30 px-3 py-2 rounded-xl border border-red-500/30 flex items-center gap-2"><AlertTriangle className="w-4 h-4" aria-hidden="true" />{text.varianceDetails}</button>}
          </div>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full sm:w-auto sm:min-w-[430px]">
            <button type="button" disabled={!canCancel} onClick={onCancel} className="flex-1 px-4 h-9 bg-slate-800 hover:bg-red-500/20 disabled:opacity-50 text-slate-300 hover:text-red-300 text-xs font-bold rounded-xl transition-all">{text.cancel}</button>
            <button type="button" disabled={!canRecount} onClick={onRecount} className="flex-1 px-4 h-9 bg-blue-500/15 hover:bg-blue-500/25 disabled:opacity-50 text-blue-300 border border-blue-500/20 text-xs font-black rounded-xl transition-all flex items-center justify-center gap-1.5"><RotateCcw className="w-4 h-4" aria-hidden="true" />{text.recount}</button>
            <button type="button" onClick={onApprove} disabled={approvalBlocked || !canApprove} className="flex-[1.5] px-4 h-9 bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-700 disabled:text-slate-400 disabled:cursor-not-allowed text-white text-sm font-black rounded-xl transition-all flex items-center justify-center gap-2"><ShieldCheck className="w-4 h-4" aria-hidden="true" />{text.approve}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
