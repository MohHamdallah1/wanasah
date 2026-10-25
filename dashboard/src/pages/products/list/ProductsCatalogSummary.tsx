import { useTranslation } from "react-i18next";

import { apiErrorMessage } from "@/lib/apiErrors";
import { resolveI18nLocale } from "@/lib/locale";
import { formatLocaleDecimal } from "@/lib/localeNumbers";
import type { CatalogSummary } from "@/pages/products/list/catalogSummaryContract";
import type {
  ProductCommercialStatusFilter,
  ProductLifecycleFilter,
} from "@/pages/products/list/types";

const chips = [
  { key: "total", kind: "static", filter: null },
  { key: "available", kind: "static", filter: null },
  { key: "stopped", kind: "commercial", filter: "STOPPED" },
  { key: "archived", kind: "lifecycle", filter: "ARCHIVED" },
  { key: "families", kind: "static", filter: null },
] as const;

export function ProductsCatalogSummary({
  data,
  isFetching,
  error,
  lifecycleFilter,
  commercialStatusFilter,
  onLifecycleFilterChange,
  onCommercialStatusFilterChange,
  onRetry,
}: {
  data: CatalogSummary | undefined;
  isFetching: boolean;
  error: unknown;
  lifecycleFilter: ProductLifecycleFilter;
  commercialStatusFilter: ProductCommercialStatusFilter;
  onLifecycleFilterChange: (value: ProductLifecycleFilter) => void;
  onCommercialStatusFilterChange: (value: ProductCommercialStatusFilter) => void;
  onRetry: () => void;
}) {
  const { t, i18n } = useTranslation();
  const locale = resolveI18nLocale(i18n);

  return (
    <div
      dir={i18n.dir()}
      role="group"
      aria-label={t("products.summary.title")}
      aria-busy={isFetching}
      className="flex flex-wrap items-center gap-1.5 text-[11px]"
    >
      {chips.map(({ key, kind, filter }) => {
        const selected =
          kind === "commercial"
            ? commercialStatusFilter === filter
            : kind === "lifecycle"
              ? lifecycleFilter === filter
              : false;
        const className = `inline-flex min-h-8 items-center gap-2 rounded-lg border px-2 py-1 font-semibold ${
          selected
            ? "border-amber-400 bg-amber-50 text-amber-950 dark:bg-amber-950 dark:text-amber-100"
            : "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
        }`;
        const content = (
          <>
            <span>{t(`products.summary.${key}`)}</span>
            <bdi className="font-black tabular-nums">
              {data && !error
                ? formatLocaleDecimal(String(data[key]), locale, 0, 0)
                : "—"}
            </bdi>
          </>
        );

        if (kind === "commercial") {
          return (
            <button
              key={key}
              type="button"
              aria-pressed={selected}
              className={`${className} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-2`}
              onClick={() =>
                onCommercialStatusFilterChange(selected ? "" : "STOPPED")
              }
            >
              {content}
            </button>
          );
        }
        if (kind === "lifecycle") {
          return (
            <button
              key={key}
              type="button"
              aria-pressed={selected}
              className={`${className} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-2`}
              onClick={() =>
                onLifecycleFilterChange(selected ? "" : "ARCHIVED")
              }
            >
              {content}
            </button>
          );
        }
        return (
          <span key={key} className={className}>
            {content}
          </span>
        );
      })}

      {error ? (
        <span role="status" className="flex flex-wrap items-center gap-1 text-rose-700">
          {apiErrorMessage(error, t("products.summary.error"))}
          <button
            type="button"
            onClick={onRetry}
            className="rounded px-1 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
          >
            {t("common.retry")}
          </button>
        </span>
      ) : null}
    </div>
  );
}
