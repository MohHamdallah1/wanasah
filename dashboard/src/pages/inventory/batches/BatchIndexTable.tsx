import { AlertTriangle, RefreshCcw } from "lucide-react";
import type { TFunction } from "i18next";

import { compareQuantity } from "@/lib/quantity";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import type { WarehouseBatchIndexItem } from "./batchIndexContracts";
import { batchIndexText } from "./batchIndexI18n";
import { DEFAULT_BATCH_EXPIRY_WARNING_DAYS } from "./batchDisplayPreferences";
import { BatchExpirySignal, BatchSellabilitySignal } from "./BatchIndexSignals";
import { batchQuantityView } from "./batchPresentation";

interface Props {
  t: TFunction;
  language: string;
  locale: string;
  items: WarehouseBatchIndexItem[];
  loading: boolean;
  error: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  continuationError: boolean;
  canManageDisposition: boolean;
  expiryWarningDays?: number;
  onRetry: () => void;
  onLoadMore: () => void;
  onManage: (item: WarehouseBatchIndexItem) => void;
}

const dispositionTone = (value: WarehouseBatchIndexItem["disposition"]): string => {
  switch (value) {
    case "RECALLED":
      return "border-red-200 bg-red-50 text-red-700";
    case "BLOCKED":
      return "border-orange-200 bg-orange-50 text-orange-700";
    case "QUARANTINED":
      return "border-amber-200 bg-amber-50 text-amber-700";
    default:
      return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
};

export function BatchIndexTable({
  t,
  language,
  locale,
  items,
  loading,
  error,
  hasMore,
  loadingMore,
  continuationError,
  canManageDisposition,
  expiryWarningDays = DEFAULT_BATCH_EXPIRY_WARNING_DAYS,
  onRetry,
  onLoadMore,
  onManage,
}: Props) {
  const text = (
    key: Parameters<typeof batchIndexText>[2],
    values: Record<string, unknown> = {},
  ) => batchIndexText(t, language, key, values);
  const number = (value: number) =>
    new Intl.NumberFormat(locale, { numberingSystem: "latn", maximumFractionDigits: 0 }).format(value);
  const quantityBlock = (item: WarehouseBatchIndexItem) => (
    <div className="space-y-0.5 text-[10px] leading-4">
      {([["onHand", item.on_hand_quantity], ["available", item.available_for_sale_quantity]] as const).map(([key, value]) => {
        const rendered = batchQuantityView(t, item, value);
        return (
          <div key={key} className="flex items-baseline justify-between gap-2">
            <span className="text-slate-500">{text(key)}</span>
            <span className="text-end font-bold tabular-nums text-slate-800" title={rendered.secondary ?? undefined}>{rendered.primary}</span>
          </div>
        );
      })}
    </div>
  );
  const attentionBadges = (item: WarehouseBatchIndexItem) => {
    const values = [
      ["stock_QUARANTINED", item.quarantined_quantity],
      ["stock_BLOCKED", item.blocked_quantity],
      ["stock_RECALLED", item.recalled_quantity],
      ["attention_DAMAGED", item.damaged_quantity],
      ["attention_DISPOSAL_PENDING", item.disposal_pending_quantity],
    ] as const;
    const active = values.filter(([, value]) => compareQuantity(value, "0") > 0);
    if (active.length === 0) return null;
    return (
      <div className="mt-1 flex flex-wrap gap-1" aria-label={text("stockStatusColumn")}>
        {active.map(([key]) => (
          <span key={key} className="rounded border border-slate-200 bg-slate-50 px-1 text-[9px] font-semibold text-slate-600">{text(key)}</span>
        ))}
      </div>
    );
  };
  const sellability = (item: WarehouseBatchIndexItem) => (
    <BatchSellabilitySignal t={t} language={language} locale={locale} item={item} />
  );
  const expiry = (item: WarehouseBatchIndexItem) => (
    <BatchExpirySignal t={t} language={language} locale={locale} item={item} warningDays={expiryWarningDays} />
  );
  const actionButton = (item: WarehouseBatchIndexItem) => (
    <button
      type="button"
      onClick={() => onManage(item)}
      className="min-h-8 whitespace-nowrap rounded-lg border border-slate-200 bg-white px-2 py-1 text-[10px] font-bold text-slate-700 outline-none transition hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-slate-500"
    >
      {text(canManageDisposition ? "manageStatus" : "viewDetails")}
    </button>
  );

  if (loading) {
    return (
      <div role="status" aria-busy="true" className="flex min-h-24 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white text-sm font-semibold text-slate-500">
        <RefreshCcw className="h-4 w-4 animate-spin" />
        {text("loading")}
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="flex min-h-24 flex-col items-center justify-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-center text-sm font-semibold text-red-800">
        <AlertTriangle className="h-6 w-6" />
        <span>{text("loadError")}</span>
        <button type="button" onClick={onRetry} className="rounded-lg border border-red-200 bg-white px-3 py-2 font-bold outline-none focus-visible:ring-2 focus-visible:ring-red-300">
          {text("retry")}
        </button>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div role="status" className="flex min-h-24 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white px-4 text-center text-sm font-semibold text-slate-500">
        {text("noRows")}
      </div>
    );
  }

  return (
    <section aria-label={text("loadedCount", { count: number(items.length) })} className="min-h-0">
      <div tabIndex={0} role="region" aria-label={text("title")} className="hidden overflow-auto outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-slate-500 md:block">
        <table className="w-full min-w-[960px] border-collapse text-start text-[11px]">
          <thead className="sticky top-0 z-[1] bg-slate-50 text-[10px] font-bold text-slate-600">
            <tr>
              <th scope="col" className="px-3 py-2 text-start">{text("lotColumn")}</th>
              <th scope="col" className="px-3 py-2 text-start">{text("productColumn")}</th>
              <th scope="col" className="px-3 py-2 text-start">{text("expiryColumn")}</th>
              <th scope="col" className="px-3 py-2 text-start">{text("dispositionColumn")}<small className="block font-normal">{text("companyScope")}</small></th>
              <th scope="col" className="px-3 py-2 text-start">{text("sellabilityColumn")}</th>
              <th scope="col" className="px-3 py-2 text-start">{text("quantityColumn")}<small className="block font-normal">{text("warehouseScope")}</small></th>
              <th scope="col" className="px-3 py-2 text-start">{text("actionColumn")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.batch_id} className="border-t border-slate-100 align-top hover:bg-slate-50/60 focus-within:bg-slate-50">
                <th scope="row" className="max-w-40 break-words px-3 py-2 text-start font-bold text-slate-900">{formatPublicBatchNumber(item.batch_number, text("noLotSupplied"))}</th>
                <td className="max-w-48 break-words px-3 py-2 font-semibold text-slate-900">{item.product_name}</td>
                <td className="px-3 py-2">{expiry(item)}</td>
                <td className="px-3 py-2"><span className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-bold ${dispositionTone(item.disposition)}`}>{text(`disposition_${item.disposition}`)}</span></td>
                <td className="px-3 py-2">{sellability(item)}</td>
                <td className="min-w-44 px-3 py-2">{quantityBlock(item)}{attentionBadges(item)}</td>
                <td className="px-3 py-2">{actionButton(item)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="divide-y divide-slate-200 md:hidden">
        {items.map((item) => (
          <article key={item.batch_id} className="min-w-0 space-y-2 p-2.5">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0 flex-1 break-words">
                <h3 className="text-xs font-bold text-slate-900">{formatPublicBatchNumber(item.batch_number, text("noLotSupplied"))}</h3>
                <p className="text-[11px] font-semibold text-slate-600">{item.product_name}</p>
              </div>
              {actionButton(item)}
            </div>
            <div className="grid min-w-0 grid-cols-2 gap-2">
              <div>{expiry(item)}</div>
              {sellability(item)}
              <div className="text-[10px]">
                <p className="font-medium text-slate-500">{text("dispositionColumn")} · {text("companyScope")}</p>
                <strong className={`mt-0.5 inline-flex rounded border px-1.5 py-0.5 ${dispositionTone(item.disposition)}`}>{text(`disposition_${item.disposition}`)}</strong>
              </div>
              <div>
                <p className="text-[10px] font-medium text-slate-500">{text("warehouseScope")}</p>
                {quantityBlock(item)}{attentionBadges(item)}
              </div>
            </div>
          </article>
        ))}
      </div>

      {continuationError ? (
        <div role="alert" className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] font-semibold text-amber-900">
          <span>{text("continuationError")}</span>
          <button type="button" onClick={onLoadMore} className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 font-bold outline-none focus-visible:ring-2 focus-visible:ring-amber-400">
            {text("retryMore")}
          </button>
        </div>
      ) : null}

      {hasMore && !continuationError ? (
        <div className="mt-2 flex justify-center">
          <button
            type="button"
            disabled={loadingMore}
            onClick={onLoadMore}
            className="inline-flex min-w-40 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-[11px] font-black text-slate-700 outline-none transition hover:bg-slate-50 disabled:cursor-wait disabled:opacity-60 focus-visible:ring-2 focus-visible:ring-slate-300"
          >
            {loadingMore ? <RefreshCcw className="h-3.5 w-3.5 animate-spin" /> : null}
            {text("loadMore")}
          </button>
        </div>
      ) : null}
    </section>
  );
}
