import { useTranslation } from "react-i18next";
import { apiErrorMessage } from "@/lib/apiErrors";
import { formatLocaleDecimal } from "@/lib/localeNumbers";
import { currentLocale } from "@/i18n";
import type { useDispatchProductSearch } from "@/features/dispatch/useDispatchProductSearch";

export function ProductSearchControls({ search, onChange, page, enabled = true }: {
  search: string; onChange: (value: string) => void; page: ReturnType<typeof useDispatchProductSearch>; enabled?: boolean;
}) {
  const { t } = useTranslation();
  return <div className="space-y-2">
    <input type="text" aria-label={t("dispatchProductSearch.search")} placeholder={t("dispatchProductSearch.search")}
      maxLength={100} value={search} disabled={!enabled} onChange={(event) => onChange(event.target.value)} className="w-full rounded border p-2" />
    {page.loading && <p role="status">{t("common.loading")}</p>}
    {!!page.error && <div role="alert"><p>{apiErrorMessage(page.error, t("dispatchProductSearch.error"))}</p>
      <button type="button" onClick={page.retry}>{t("common.retry")}</button></div>}
    {!page.loading && !page.error && <p role="status">{t(!enabled ? "dispatchProductSearch.context" : page.searchRequired && search.trim().length < 2
      ? "dispatchProductSearch.hint" : page.items.length ? page.hasMore ? "dispatchProductSearch.window" : "dispatchProductSearch.end" : "dispatchProductSearch.empty")}</p>}
    <div className="flex gap-3">
      {page.hasPrevious && <button type="button" disabled={page.loading} onClick={page.previous}>{t("dispatchProductSearch.previous")}</button>}
      {page.hasMore && <button type="button" disabled={page.loading} onClick={page.loadMore}>{t("dispatchProductSearch.more")}</button>}
      {(page.hasMore || page.hasPrevious) && <span>{t("dispatchProductSearch.page", { number: formatLocaleDecimal(String(page.pageNumber), currentLocale()) })}</span>}
    </div>
  </div>;
}
