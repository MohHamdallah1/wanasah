import { useTranslation } from "react-i18next";
import { apiErrorMessage } from "@/lib/apiErrors";
import { formatLocaleDecimal } from "@/lib/localeNumbers";
import { currentLocale } from "@/i18n";
import type { useDispatchProductSearch } from "@/features/dispatch/useDispatchProductSearch";
import type { useDispatchProductWindow } from "@/features/dispatch/useDispatchProductWindow";

type ProductDiscoveryState = ReturnType<typeof useDispatchProductSearch> | ReturnType<typeof useDispatchProductWindow>;

export function ProductSearchControls({ search, onChange, page, enabled = true, pending = false, compactWindowed = false }: {
  search: string; onChange: (value: string) => void; page: ProductDiscoveryState; enabled?: boolean; pending?: boolean;
  compactWindowed?: boolean;
}) {
  const { t } = useTranslation();
  return <div className="space-y-2">
    <input type="text" aria-label={t("dispatchProductSearch.search")} placeholder={t("dispatchProductSearch.search")}
      maxLength={100} value={search} disabled={!enabled} onChange={(event) => onChange(event.target.value)}
      className="h-10 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none transition-colors placeholder:text-slate-400 focus:border-[#1e87bb] focus:ring-2 focus:ring-[#1e87bb]/15 disabled:bg-slate-100" />
    {!pending && page.loading && <p role="status">{t("common.loading")}</p>}
    {!pending && !!page.error && <div role="alert"><p>{apiErrorMessage(page.error, t("dispatchProductSearch.error"))}</p>
      <button type="button" onClick={page.retry}>{t("common.retry")}</button></div>}
    {pending ? <p data-testid="dispatch-product-read-pending" aria-busy="true" className="min-h-5" /> : null}
    {!pending && !page.loading && !page.error && (!compactWindowed || page.mode !== "windowed" || !enabled || page.searchRequired && search.trim().length < 2 || !page.items.length) && <p role="status" className="text-xs text-slate-500">{t(!enabled ? "dispatchProductSearch.context" : page.searchRequired && search.trim().length < 2
      ? "dispatchProductSearch.hint" : page.items.length ? page.mode === "windowed" ? "dispatchProductSearch.scrollWindow" : page.hasMore ? "dispatchProductSearch.window" : "dispatchProductSearch.end" : "dispatchProductSearch.empty")}</p>}
    {!pending && page.mode !== "windowed" && <div className="flex gap-3">
      {page.hasPrevious && <button type="button" disabled={page.loading} onClick={page.previous}>{t("dispatchProductSearch.previous")}</button>}
      {page.hasMore && <button type="button" disabled={page.loading} onClick={page.loadMore}>{t("dispatchProductSearch.more")}</button>}
      {(page.hasMore || page.hasPrevious) && <span>{t("dispatchProductSearch.page", { number: formatLocaleDecimal(String(page.pageNumber), currentLocale()) })}</span>}
    </div>}
    {!pending && page.mode === "windowed" && page.loadingWindow && <p role="status">{t("dispatchProductSearch.loadingWindow")}</p>}
  </div>;
}
