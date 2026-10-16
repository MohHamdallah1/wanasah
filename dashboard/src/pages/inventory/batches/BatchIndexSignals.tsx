import { AlertTriangle, CheckCircle2, Clock3 } from "lucide-react";
import type { TFunction } from "i18next";
import type { WarehouseBatchIndexItem } from "./batchIndexContracts";
import { batchIndexText } from "./batchIndexI18n";
import { formatBatchDate } from "./batchPresentation";

interface Props {
  t: TFunction;
  language: string;
  locale: string;
  item: WarehouseBatchIndexItem;
}

export function BatchExpirySignal({ t, language, locale, item, warningDays }: Props & { warningDays: number }) {
  const text = (key: Parameters<typeof batchIndexText>[2], values = {}) =>
    batchIndexText(t, language, key, values);
  const days = item.days_to_expiry;
  // Days are supplied by the server as of its query date. This is visual severity
  // only: neither the warning preference nor this badge decides sellability.
  const key = !item.expiry_date
    ? item.expiry_control_mode === "NONE" ? "noExpiryTracking" : "missingExpiry"
    : days === null ? "validExpiry"
      : days < 0 ? "expiry_EXPIRED"
        : days === 0 ? "expiresToday"
          : days <= warningDays ? "expiringSoon" : "validExpiry";
  const warning = key === "expiry_EXPIRED" || key === "missingExpiry";
  const soon = key === "expiringSoon" || key === "expiresToday";
  const Icon = warning ? AlertTriangle : soon ? Clock3 : CheckCircle2;
  const tone = warning ? "text-rose-800 bg-rose-50 border-rose-200"
    : soon ? "text-amber-900 bg-amber-50 border-amber-200"
      : "text-slate-600 bg-slate-50 border-slate-200";
  const number = (value: number) => new Intl.NumberFormat(locale, {
    numberingSystem: "latn", maximumFractionDigits: 0,
  }).format(value);
  return (
    <div className="space-y-0.5 text-[10px]">
      <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-bold ${tone}`}>
        <Icon aria-hidden="true" className="h-3 w-3 shrink-0" />{text(key)}
      </span>
      {item.expiry_date ? (
        <div className="tabular-nums text-slate-600">
          {formatBatchDate(item.expiry_date, locale, text("noDate"))}
          {days !== null && days !== 0 ? (
            <small className="ms-1">{text(days < 0 ? "expiredDays" : "daysRemaining", { count: number(Math.abs(days)) })}</small>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function BatchSellabilitySignal({ t, language, locale, item, allReasons = false }: Props & { allReasons?: boolean }) {
  const text = (key: Parameters<typeof batchIndexText>[2], values = {}) =>
    batchIndexText(t, language, key, values);
  const shelfCode = "MINIMUM_REMAINING_SHELF_LIFE_NOT_MET";
  // Preserve backend ordering for the primary reason; never infer a predicate.
  const primary = item.sellability_reason_codes[0];
  const reasons = allReasons ? item.sellability_reason_codes
    : item.sellability_reason_codes.filter((code) => code === primary || code === shelfCode);
  return (
    <div className="space-y-0.5 text-[10px]">
      <span className={`inline-flex rounded border px-1.5 py-0.5 font-bold ${item.sellability_state === "SELLABLE"
        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
        : "border-rose-200 bg-rose-50 text-rose-800"}`}>
        {text(`sellability_${item.sellability_state}`)}
      </span>
      {reasons.map((code) => <p key={code} className="max-w-56 leading-4 text-slate-600">{text(`reason_${code}`)}</p>)}
      {reasons.includes(shelfCode) ? (
        <p className="text-slate-500">{text("shelfLifePolicy", { count: new Intl.NumberFormat(locale, {
          numberingSystem: "latn", maximumFractionDigits: 0,
        }).format(item.minimum_remaining_shelf_life_days) })}</p>
      ) : null}
    </div>
  );
}
