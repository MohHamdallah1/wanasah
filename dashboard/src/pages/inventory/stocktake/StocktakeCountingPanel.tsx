import { Check, Info, Scan } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useRef, type KeyboardEvent } from "react";
import { countOuterFactor, splitCountForDisplay } from "./countEntry";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import { isDiscoveredRow } from "./discoveredContract";
import type { StocktakeRow } from "../inventoryUtils";
import type { StocktakeType } from "./types";
import { useStocktakeUiCopy } from "./uiCopy";

interface StocktakeCountingPanelProps {
  warehouseName?: string | null;
  scopeProductName?: string | null;
  stocktakeType?: StocktakeType | null;
  rows: StocktakeRow[];
  progress: {
    total: number;
    counted: number;
    remaining: number;
  };
  onUpdateRow: (key: string, value: string) => void;
  onConfirmZero: (key: string) => void;
  onUndoCount?: (key: string) => void;
  onUpdatePart?: (key: string, part: "outer" | "base", value: string) => void;
  onAddDiscovered: () => void;
  onRemoveDiscovered: (key: string) => void;
  canCancel: boolean;
  onCancel: () => void;
  onSubmit: () => void;
}

export function StocktakeCountingPanel({
  warehouseName,
  scopeProductName,
  stocktakeType,
  rows,
  progress,
  onUpdateRow,
  onConfirmZero,
  onUndoCount,
  onUpdatePart,
  onAddDiscovered,
  onRemoveDiscovered,
  canCancel,
  onCancel,
  onSubmit,
}: StocktakeCountingPanelProps) {
  const { t, i18n } = useTranslation();
  const { copy, dir } = useStocktakeUiCopy();
  const panelRef = useRef<HTMLDivElement>(null);
  const text = copy.counting;
  // FULL_COUNT and CYCLE_COUNT share this exact counting surface. The
  // product name comes from the already-authorized session summary.
  const typeLabel = stocktakeType
    ? copy.sessions.types[stocktakeType]
    : scopeProductName ? copy.sessions.types.CYCLE_COUNT : copy.sessions.types.FULL_COUNT;
  const scopeLabel = scopeProductName || (stocktakeType === "CYCLE_COUNT" ? copy.workspace.productUnknown : copy.workspace.allProducts);
  const stages = [copy.workspace.countStep, copy.workspace.reviewStep, copy.workspace.approveStep];


  const handleCountNavigation = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!["Enter", "ArrowDown", "ArrowUp"].includes(event.key)) return;
    const inputs = Array.from(
      panelRef.current?.querySelectorAll<HTMLInputElement>("[data-stocktake-count-input='true']") ?? [],
    ).filter(input => !input.disabled && input.getClientRects().length > 0);
    const index = inputs.indexOf(event.currentTarget);
    if (index < 0) return;
    // Enter NEVER submits, even at the last input of a fully counted sheet.
    if (event.key === "Enter") event.preventDefault();
    const target = event.key === "ArrowUp" ? inputs[index - 1] : inputs[index + 1];
    if (!target) return;
    event.preventDefault();
    target.focus();
    target.select();
  };

  const countInput = (row: StocktakeRow, part: "outer" | "base" = "base") => {
    const dual = countOuterFactor(row) !== null && Boolean(onUpdatePart);
    const parts = dual
      ? row.count_outer_quantity !== undefined && row.count_base_quantity !== undefined
        ? { outer: row.count_outer_quantity, base: row.count_base_quantity }
        : splitCountForDisplay(row, row.actual_quantity)
      : { outer: "", base: row.actual_quantity };
    const value = part === "outer" ? parts.outer : parts.base;
    const unitName = part === "outer" ? row.count_outer_uom_name : row.base_uom_name;
    const invalid = value !== "" && (
      part === "outer" ? !/^\d+$/.test(value) : !/^\d+(?:\.\d{1,6})?$/.test(value)
    );
    return (
      <input
        data-stocktake-count-input="true"
        data-stocktake-part={part}
        data-stocktake-row={row.row_key}
        inputMode={part === "outer" ? "numeric" : "decimal"}
        maxLength={48}
        aria-invalid={invalid}
        aria-label={`${text.actualFor(row.product_name)} — ${formatPublicBatchNumber(row.batch_number, t("inventoryLive.noLotSupplied"))} — ${copy.stockStatuses[row.stock_status]} — ${unitName}`}
        value={value}
        onChange={(event) => dual
          ? onUpdatePart?.(row.row_key, part, event.target.value)
          : onUpdateRow(row.row_key, event.target.value)}
        onKeyDown={handleCountNavigation}
        className="w-24 max-w-full rounded-lg border border-slate-300 p-2 text-center font-bold focus-visible:ring-2 focus-visible:ring-blue-500"
        dir="ltr"
      />
    );
  };

  const countEntry = (row: StocktakeRow) => {
    const factor = countOuterFactor(row);
    const dual = factor !== null && Boolean(onUpdatePart);
    return (
      <div className="flex min-w-0 flex-wrap items-center gap-2" data-stocktake-count-controls={row.row_key}>
        {dual && <label className="flex items-center gap-1.5 text-xs font-bold text-slate-600">
          {row.count_outer_uom_name} {countInput(row, "outer")}
        </label>}
        <label className="flex items-center gap-1.5 text-xs font-bold text-slate-600">
          {row.base_uom_name} {countInput(row)}
        </label>
        {dual && factor !== null && <span className="text-[10px] text-slate-500" dir="auto">
          {text.unitFactor(
            row.count_outer_uom_name!,
            new Intl.NumberFormat(i18n.resolvedLanguage || i18n.language || "ar", {
              numberingSystem: dir === "rtl" ? "arab" : "latn",
              useGrouping: false,
            }).format(factor),
            row.base_uom_name,
          )}
        </span>}
      </div>
    );
  };

  const zeroButton = (row: StocktakeRow) => row.counted ? (
    <div className="inline-flex flex-wrap items-center justify-center gap-1.5">
      <span className="inline-flex items-center gap-1 px-2 py-1.5 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-100 text-xs font-black">
        <Check className="h-3.5 w-3.5" aria-hidden="true" />{text.counted}
      </span>
      {onUndoCount && <button type="button" onClick={() => onUndoCount(row.row_key)}
        className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-100"
        aria-label={`${text.undoCount} — ${row.product_name} — ${formatPublicBatchNumber(row.batch_number, t("inventoryLive.noLotSupplied"))}`}>
        {text.undoCount}
      </button>}
    </div>
  ) : (
    <button
      type="button"
      onClick={() => onConfirmZero(row.row_key)}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-100 hover:bg-amber-50 text-slate-500 hover:text-amber-700 border border-slate-200 hover:border-amber-200 rounded-lg text-xs font-black transition-colors"
      title={text.zeroHint}
      aria-label={`${text.confirmZeroFor(row.product_name)} — ${formatPublicBatchNumber(row.batch_number, t("inventoryLive.noLotSupplied"))} — ${copy.stockStatuses[row.stock_status]}`}
    >
      {text.confirmZero}
    </button>
  );

  return (
    <div ref={panelRef} dir={dir} className="glass-card inventory-data-panel flex h-full min-w-0 min-h-0 flex-1 flex-col overflow-hidden border border-slate-200 shadow-sm">
      <header className="shrink-0 border-b border-slate-700 bg-slate-900 px-3 py-2 text-white">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <Scan className="h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
            <h2 className="shrink-0 text-sm font-black">{typeLabel}</h2>
            <span className="min-w-0 truncate text-xs font-semibold text-slate-200"
              title={scopeLabel} aria-label={`${copy.workspace.scope}: ${scopeLabel}`}>
              {scopeLabel}
            </span>
            <span role="note" tabIndex={0} title={text.hidden} aria-label={text.hidden}
              className="inline-flex shrink-0 rounded p-0.5 text-slate-300 outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
              <Info className="h-3.5 w-3.5" aria-hidden="true" />
            </span>
          </div>
          <ol aria-label={copy.workspace.stages}
            className="order-3 flex w-full items-center justify-center gap-1 text-[10px] font-bold sm:order-none sm:w-auto">
            {stages.map((stage, index) => (
              <li key={stage} aria-current={index === 0 ? "step" : undefined}
                className={`rounded px-1.5 py-0.5 ${index === 0 ? "bg-amber-400 text-slate-950" : "text-slate-300"}`}>
                {index + 1}. {stage}
              </li>
            ))}
          </ol>
          {rows.length > 0 && (
            <button type="button" onClick={onAddDiscovered}
              className="ms-auto shrink-0 rounded-md bg-white px-2.5 py-1.5 text-xs font-bold text-slate-900 focus-visible:ring-2 focus-visible:ring-amber-400">
              {copy.discovered.add}
            </button>
          )}
        </div>
        <span className="sr-only">{text.active}</span>
        <span className="sr-only">{text.warehouseContext}: <strong>{warehouseName || text.warehouseUnknown}</strong></span>
      </header>

      {rows.length === 0 && (
        <div role="status" className="flex min-h-0 flex-1 flex-col items-start justify-center gap-2 overflow-y-auto bg-slate-50 px-4 py-5 text-sm text-slate-800">
          <p className="font-bold">{text.zeroRows}</p>
          <p className="text-xs text-slate-600">{text.noRowsSubmit}</p>
          <button type="button" onClick={onAddDiscovered}
            className="rounded-lg bg-blue-700 px-3 py-2 text-xs font-bold text-white focus-visible:ring-2 focus-visible:ring-blue-400">
            {copy.discovered.add}
          </button>
        </div>
      )}

      {rows.length > 0 && (
        <>
      <div className="md:hidden min-w-0 flex-1 min-h-0 overflow-y-auto overscroll-contain custom-scrollbar bg-slate-50 p-2 space-y-2">
        {rows.map((row) => (
          <article key={row.row_key} className="rounded-xl border border-slate-200 bg-white p-3 space-y-2">
            <div>
              <div className="font-bold text-slate-800 text-sm">{row.product_name}</div>
              <div className="text-xs text-slate-500 mt-1">
                {formatPublicBatchNumber(row.batch_number, t("inventoryLive.noLotSupplied"))} · {row.expiry_date || "-"}
                {isDiscoveredRow(row) && <span className="ms-2 text-blue-700 font-bold">{copy.discovered.discoveredLabel}</span>}
              </div>
              <span className="mt-2 inline-flex rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[10px] font-black text-slate-700">
                {text.stockStatus}: {copy.stockStatuses[row.stock_status]}
              </span>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                {countEntry(row)}
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                {zeroButton(row)}
                {isDiscoveredRow(row) && <button type="button" onClick={() => onRemoveDiscovered(row.row_key)}
                  className="text-xs text-red-600 underline">{copy.discovered.remove}</button>}
              </div>
            </div>
            <div className="text-[11px] text-slate-400">{text.quantityStep}: <span dir="ltr">{row.quantity_step}</span></div>
          </article>
        ))}
      </div>

      <div className="hidden md:block min-w-0 flex-1 min-h-0 overflow-auto overscroll-contain custom-scrollbar bg-white">
        <table className="w-full min-w-[790px] text-sm" aria-label={copy.workspace.countTable}>
          <thead className="bg-slate-50 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
            <tr>
              <th className="px-3 py-2 text-xs font-bold text-slate-500 text-start">{text.product}</th>
              <th className="px-3 py-2 text-xs font-bold text-slate-500 text-start">{text.batchExpiry}</th>
              <th className="px-3 py-2 text-xs font-bold text-slate-500 text-center">{text.stockStatus}</th>
              <th className="px-3 py-2 text-xs font-bold text-[#1e87bb] text-center">{text.actualBase}</th>
              <th className="px-3 py-2 text-xs font-bold text-slate-500 text-center">{text.countStatus}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 bg-white">
            {rows.map((row) => (
              <tr key={row.row_key} className="hover:bg-slate-50 transition-colors">
                <td className="px-3 py-2 font-bold text-slate-800">{row.product_name}
                  {isDiscoveredRow(row) && <span className="ms-2 text-xs text-blue-700">{copy.discovered.discoveredLabel}</span>}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs font-bold text-slate-700">{formatPublicBatchNumber(row.batch_number, t("inventoryLive.noLotSupplied"))}</span>
                    <span className="text-[11px] text-slate-400">{row.expiry_date || "-"}</span>
                  </div>
                </td>
                <td className="px-3 py-2 text-center">
                  <span className="inline-flex rounded-full border border-slate-200 bg-slate-100 px-2 py-1 text-[10px] font-black text-slate-700">
                    {copy.stockStatuses[row.stock_status]}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center justify-center gap-2">
                    {countEntry(row)}
                    <span className="text-[10px] text-slate-400">{text.step} <span dir="ltr">{row.quantity_step}</span></span>
                  </div>
                </td>
                <td className="px-3 py-2 text-center">
                  <div className="flex items-center justify-center gap-2">
                    {zeroButton(row)}
                    {isDiscoveredRow(row) && <button type="button" onClick={() => onRemoveDiscovered(row.row_key)}
                      className="text-xs text-red-600 underline">{copy.discovered.remove}</button>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

        </>
      )}

      <footer className="shrink-0 overflow-hidden rounded-b-2xl border-t border-slate-700 bg-slate-900 text-white">
        <div role="progressbar" aria-label={copy.workspace.progress} aria-valuemin={0}
          aria-valuemax={Math.max(progress.total, 1)} aria-valuenow={progress.counted}
          className="h-1 w-full bg-slate-700">
          <div className="h-full bg-amber-400"
            style={{ width: `${progress.total > 0 ? Math.min(100, Math.max(0, progress.counted / progress.total * 100)) : 0}%` }} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 md:px-4">
          <div className="flex items-center gap-4">
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold uppercase">{text.total}</span><span className="text-sm font-extrabold"><span dir="ltr">{progress.total}</span> {text.lines}</span></div>
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold uppercase">{text.countedTotal}</span><span className="text-sm font-extrabold text-emerald-400" dir="ltr">{progress.counted}</span></div>
            <div className="flex flex-col"><span className="text-[10px] text-slate-400 font-bold uppercase">{text.remaining}</span><span className={`text-sm font-extrabold ${progress.remaining > 0 ? "text-amber-400" : "text-emerald-400"}`} dir="ltr">{progress.remaining}</span></div>
          </div>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full sm:w-auto sm:min-w-[300px]">
            <button type="button" disabled={!canCancel} onClick={onCancel} className="flex-1 px-4 h-9 bg-slate-800 hover:bg-red-500/20 disabled:opacity-50 text-slate-300 hover:text-red-300 border border-transparent hover:border-red-500/30 text-xs font-bold rounded-xl transition-all">
              {text.cancel}
            </button>
            <button type="button" onClick={onSubmit} disabled={progress.total === 0 || progress.remaining > 0} className="flex-[2.5] px-4 h-9 bg-amber-500 hover:bg-amber-600 disabled:bg-slate-600 disabled:text-slate-300 text-slate-900 text-sm font-black rounded-xl shadow-lg transition-all flex items-center justify-center gap-2">
              <Check className="w-5 h-5" aria-hidden="true" />
              {text.finish}
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
}
