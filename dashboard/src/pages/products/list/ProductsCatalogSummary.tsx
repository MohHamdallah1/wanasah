import { useTranslation } from "react-i18next";

import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import { formatLocaleDecimal } from "@/lib/localeNumbers";
import type { CatalogSummary } from "@/pages/products/list/catalogSummaryContract";
import type { ProductLifecycleFilter } from "@/pages/products/list/types";

const chips = [
  { key: "total", filter: null },
  { key: "available", filter: null },
  { key: "retiring", filter: "RETIRING" },
  { key: "sales_restricted", filter: null },
  { key: "archived", filter: "ARCHIVED" },
  { key: "families", filter: null },
] as const;

export function ProductsCatalogSummary({ data, isFetching, error, lifecycleFilter, onLifecycleFilterChange, onRetry }: {
  data: CatalogSummary | undefined;
  isFetching: boolean;
  error: unknown;
  lifecycleFilter: ProductLifecycleFilter;
  onLifecycleFilterChange: (value: ProductLifecycleFilter) => void;
  onRetry: () => void;
}) {
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);
  return (
    <div dir={i18n.dir()} role="group" aria-label={t("products.summary.title")} aria-busy={isFetching}
      className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
      <span className="text-[10px] font-semibold text-slate-500">{t("products.summary.scope")}</span>
      {chips.map(({ key, filter }) => {
        const selected = filter !== null && lifecycleFilter === filter;
        const className = `inline-flex min-h-8 items-center gap-2 rounded-lg border px-2 py-1 font-semibold ${selected
          ? "border-amber-400 bg-amber-50 text-amber-950 dark:bg-amber-950 dark:text-amber-100"
          : "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"}`;
        const content = <>
          <span>{t(`products.summary.${key}`)}</span>
          <bdi className="font-black tabular-nums">{data && !error
            ? formatLocaleDecimal(String(data[key]), locale, 0, 0) : "—"}</bdi>
        </>;
        return filter === null ? (
          <span key={key} className={className}>{content}</span>
        ) : (
          <button key={key} type="button" aria-pressed={selected} className={`${className} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-2`}
            onClick={() => onLifecycleFilterChange(selected ? "" : filter)}>{content}</button>
        );
      })}
      {error ? <span role="status" className="flex flex-wrap items-center gap-1 text-rose-700">
        {apiErrorMessage(error, t("products.summary.error"))}
        <button type="button" onClick={onRetry} className="rounded px-1 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500">{t("common.retry")}</button>
      </span> : null}
    </div>
  );
}
