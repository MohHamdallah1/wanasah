import { useTranslation } from "react-i18next";
import { apiErrorMessage } from "@/lib/apiErrors";
import type { useDispatchProductSearch } from "@/features/dispatch/useDispatchProductSearch";

export function ProductSearchControls({ search, onChange, page, enabled = true }: {
  search: string; onChange: (value: string) => void; page: ReturnType<typeof useDispatchProductSearch>; enabled?: boolean;
}) {
  const { t } = useTranslation();
  return <div className="space-y-2">
    <input
      type="text"
      aria-label={t("dispatchProductSearch.search")}
      placeholder={t("dispatchProductSearch.search")}
      maxLength={100}
      value={search}
      disabled={!enabled}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-[#1e87bb] focus:ring-2 focus:ring-[#1e87bb]/10 disabled:bg-slate-50 disabled:text-slate-400"
    />
    {page.loading && <p role="status" className="text-xs font-semibold text-slate-500">{t("common.loading")}</p>}
    {!!page.error && <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
      <p>{apiErrorMessage(page.error, t("dispatchProductSearch.error"))}</p>
      <button type="button" onClick={page.retry} className="shrink-0 rounded-lg border border-red-200 bg-white px-2 py-1">{t("common.retry")}</button>
    </div>}
    {!page.loading && !page.error && <p role="status" className="text-xs font-medium text-slate-500">
      {t(!enabled ? "dispatchProductSearch.context" : page.searchRequired && search.trim().length < 2
        ? "dispatchProductSearch.hint" : page.items.length ? "dispatchProductSearch.scrollHint" : "dispatchProductSearch.empty")}
    </p>}
  </div>;
}
