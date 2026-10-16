import { AlertTriangle, CheckCircle2, RefreshCcw } from "lucide-react";
import type { TFunction } from "i18next";

import { compareQuantity, formatCommercialQuantity } from "@/lib/quantity";
import { formatPublicBatchNumber } from "../publicBatchNumber";
import type { WarehouseBatchIndexItem } from "./batchIndexContracts";
import { batchIndexText } from "./batchIndexI18n";

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

const sellabilityTone = (value: WarehouseBatchIndexItem["sellability_state"]): string =>
  value === "SELLABLE"
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : "border-rose-200 bg-rose-50 text-rose-700";

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
  onRetry,
  onLoadMore,
  onManage,
}: Props) {
  const text = (
    key: Parameters<typeof batchIndexText>[2],
    values: Record<string, unknown> = {},
  ) => batchIndexText(t, language, key, values);
  const formatDate = (value: string | null) => {
    if (!value) return text("noDate");
    try {
      return new Intl.DateTimeFormat(locale, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        numberingSystem: "latn",
        timeZone: "UTC",
      }).format(new Date(`${value}T00:00:00Z`));
    } catch {
      return value;
    }
  };
  const number = (value: number) =>
    new Intl.NumberFormat(locale, { numberingSystem: "latn", maximumFractionDigits: 0 }).format(value);
  const expiryMeta = (item: WarehouseBatchIndexItem): string | null => {
    if (item.days_to_expiry === null) return null;
    if (item.days_to_expiry < 0) return text("expiredDays", { count: number(Math.abs(item.days_to_expiry)) });
    if (item.days_to_expiry === 0) return text("expiresToday");
    return text("daysRemaining", { count: number(item.days_to_expiry) });
  };
  const quantityView = (item: WarehouseBatchIndexItem, value: string) => {
    const displayName = t(`uom.${item.display_uom_code}`, {
      defaultValue: item.display_uom_name || item.display_uom_code,
    });
    const baseName = t(`uom.${item.base_uom_code}`, {
      defaultValue: item.base_uom_name || item.base_uom_code,
    });
    return formatCommercialQuantity(
      value,
      String(displayName),
      String(baseName),
      item.display_factor_to_base,
    );
  };
  const quantityBlock = (item: WarehouseBatchIndexItem) => {
    const rows = [
      ["onHand", item.on_hand_quantity],
      ["reserved", item.reserved_quantity],
      ["available", item.available_for_sale_quantity],
      ["unavailable", item.unavailable_quantity],
    ] as const;
    return (
      <div className="space-y-1 text-[10px] leading-4">
        {rows.map(([key, value]) => {
          const rendered = quantityView(item, value);
          return (
            <div key={key} className="flex items-start justify-between gap-2">
              <span className="text-slate-500">{text(key)}</span>
              <span className="text-end font-bold tabular-nums text-slate-800">
                {rendered.primary}
                {rendered.secondary ? (
                  <small className="ms-1 block font-medium text-slate-400">{rendered.secondary}</small>
                ) : null}
              </span>
            </div>
          );
        })}
        <div className="pt-1 text-[9px] font-semibold text-slate-400">
          {text("baseUom", {
            unit: String(t(`uom.${item.base_uom_code}`, { defaultValue: item.base_uom_name || item.base_uom_code })),
          })}
        </div>
      </div>
    );
  };
  const attentionBadges = (item: WarehouseBatchIndexItem) => {
    const values = [
      ["disposition_QUARANTINED", item.quarantined_quantity],
      ["disposition_BLOCKED", item.blocked_quantity],
      ["disposition_RECALLED", item.recalled_quantity],
      ["attention_DAMAGED", item.damaged_quantity],
      ["attention_DISPOSAL_PENDING", item.disposal_pending_quantity],
    ] as const;
    const active = values.filter(([, value]) => compareQuantity(value, "0") > 0);
    if (active.length === 0) return null;
    return (
      <div className="mt-1 flex flex-wrap gap-1">
        {active.map(([key]) => (
          <span key={key} className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[8px] font-bold text-slate-600">
            {text(key)}
          </span>
        ))}
      </div>
    );
  };
  const sellability = (item: WarehouseBatchIndexItem) => (
    <div className="space-y-1">
      <span className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-black ${sellabilityTone(item.sellability_state)}`}>
        {text(`sellability_${item.sellability_state}`)}
      </span>
      {item.sellability_reason_codes.length > 0 ? (
        <div className="space-y-0.5 text-[9px] font-semibold leading-4 text-slate-500">
          {item.sellability_reason_codes.map((code) => (
            <div key={code}>{text(`reason_${code}`)}</div>
          ))}
        </div>
      ) : (
        <div className="inline-flex items-center gap-1 text-[9px] font-semibold text-emerald-600">
          <CheckCircle2 className="h-3 w-3" />
          {text("sellability_SELLABLE")}
        </div>
      )}
    </div>
  );
  const actionButton = (item: WarehouseBatchIndexItem) =>
    canManageDisposition ? (
      <button
        type="button"
        onClick={() => onManage(item)}
        className="whitespace-nowrap rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-black text-slate-700 outline-none transition hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-slate-300"
      >
        {text("manageStatus")}
      </button>
    ) : null;

  if (loading) {
    return (
      <div className="flex min-h-48 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white text-sm font-semibold text-slate-500">
        <RefreshCcw className="h-4 w-4 animate-spin" />
        {text("loading")}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-48 flex-col items-center justify-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-center text-sm font-semibold text-red-800">
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
      <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white px-4 text-center text-sm font-semibold text-slate-500">
        {text("noRows")}
      </div>
    );
  }

  return (
    <section aria-label={text("loadedCount", { count: number(items.length) })} className="min-h-0">
      <div className="hidden overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm md:block">
        <table className="w-full min-w-[1180px] border-collapse text-start text-[11px]">
          <thead className="sticky top-0 z-[1] bg-slate-50 text-[10px] font-black text-slate-500">
            <tr>
              <th className="px-3 py-2 text-start">{text("productColumn")}</th>
              <th className="px-3 py-2 text-start">{text("skuColumn")}</th>
              <th className="px-3 py-2 text-start">{text("familyColumn")}</th>
              <th className="px-3 py-2 text-start">{text("lotColumn")}</th>
              <th className="px-3 py-2 text-start">{text("productionColumn")}</th>
              <th className="px-3 py-2 text-start">{text("expiryColumn")}</th>
              <th className="px-3 py-2 text-start">{text("dispositionColumn")}</th>
              <th className="px-3 py-2 text-start">{text("sellabilityColumn")}</th>
              <th className="px-3 py-2 text-start">{text("quantityColumn")}</th>
              {canManageDisposition ? <th className="px-3 py-2 text-start">{text("actionColumn")}</th> : null}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.batch_id} className="border-t border-slate-100 align-top hover:bg-slate-50/60">
                <td className="max-w-48 px-3 py-2.5 font-bold text-slate-900">{item.product_name}</td>
                <td className="px-3 py-2.5 font-mono text-[10px] text-slate-600">{item.sku ?? "—"}</td>
                <td className="max-w-40 px-3 py-2.5 text-slate-600">{item.family_name}</td>
                <td className="px-3 py-2.5 font-bold text-slate-800">{formatPublicBatchNumber(item.batch_number, text("noLotSupplied"))}</td>
                <td className="px-3 py-2.5 text-slate-600">{formatDate(item.production_date)}</td>
                <td className="px-3 py-2.5 text-slate-600">
                  <div>{formatDate(item.expiry_date)}</div>
                  {expiryMeta(item) ? <small className="mt-0.5 block font-semibold text-slate-400">{expiryMeta(item)}</small> : null}
                </td>
                <td className="px-3 py-2.5">
                  <span className={`inline-flex rounded-full border px-2 py-1 text-[9px] font-black ${dispositionTone(item.disposition)}`}>
                    {text(`disposition_${item.disposition}`)}
                  </span>
                  {attentionBadges(item)}
                </td>
                <td className="px-3 py-2.5">{sellability(item)}</td>
                <td className="min-w-52 px-3 py-2.5">{quantityBlock(item)}</td>
                {canManageDisposition ? <td className="px-3 py-2.5">{actionButton(item)}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-2 md:hidden">
        {items.map((item) => (
          <article key={item.batch_id} className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-black text-slate-900">{item.product_name}</h3>
                <p className="mt-0.5 truncate text-[10px] font-semibold text-slate-500">
                  {item.sku ?? "—"} · {item.family_name}
                </p>
              </div>
              <span className={`shrink-0 rounded-full border px-2 py-1 text-[9px] font-black ${sellabilityTone(item.sellability_state)}`}>
                {text(`sellability_${item.sellability_state}`)}
              </span>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
              <div><span className="block text-slate-400">{text("lotColumn")}</span><strong>{formatPublicBatchNumber(item.batch_number, text("noLotSupplied"))}</strong></div>
              <div><span className="block text-slate-400">{text("dispositionColumn")}</span><strong>{text(`disposition_${item.disposition}`)}</strong></div>
              <div><span className="block text-slate-400">{text("productionColumn")}</span><strong>{formatDate(item.production_date)}</strong></div>
              <div><span className="block text-slate-400">{text("expiryColumn")}</span><strong>{formatDate(item.expiry_date)}</strong>{expiryMeta(item) ? <small className="block text-slate-400">{expiryMeta(item)}</small> : null}</div>
            </div>
            <div className="mt-3 rounded-lg bg-slate-50 p-2">{quantityBlock(item)}</div>
            {item.sellability_reason_codes.length > 0 ? <div className="mt-2">{sellability(item)}</div> : null}
            {attentionBadges(item)}
            {canManageDisposition ? <div className="mt-3 flex justify-end">{actionButton(item)}</div> : null}
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