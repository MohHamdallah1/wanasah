import { useMemo, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Package, Plus, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useDispatchProductSearch } from "@/features/dispatch/useDispatchProductSearch";
import { dispatchUiText } from "@/features/dispatch/dispatchUiText";
import { apiErrorMessage } from "@/lib/apiErrors";

/** An authorized, paginated product shelf; initially open, no typed search required. */
export function ShortageProductPicker({
  scope, drafted, onAdd, disabled = false,
}: {
  scope: string | null;
  drafted: { productId: string; productName: string; quantity: number }[];
  onAdd: (id: string, name: string) => void;
  disabled?: boolean;
}) {
  const { i18n, t: translation } = useTranslation();
  const t = (key: Parameters<typeof dispatchUiText>[1], values?: Record<string, string | number>) =>
    dispatchUiText(i18n.language, key, values ?? {});
  const [search, setSearch] = useState("");
  // Single-character input keeps the normal shelf; two characters activates
  // authoritative company-wide server search, without guessing from page 1.
  const serverQuery = search.trim().length === 1 ? "" : search;
  const page = useDispatchProductSearch(
    disabled ? null : "/dispatch/products?purpose=SHORTAGE",
    serverQuery, scope, "SHORTAGE",
  );
  const products = page.items;
  const busy = page.loading;
  const failure = page.error;
  const counts = useMemo(() => new Map(drafted.map(item => [item.productId, item.quantity])), [drafted]);
  const numbers = new Intl.NumberFormat(i18n.language.startsWith("ar") ? "ar" : "en");

  return <section data-testid="shortage-product-catalog"
    className="flex min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div className="border-b border-slate-100 px-4 py-3 sm:px-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-base font-bold text-slate-900">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-sky-50 text-sky-700"><Package className="h-4 w-4" aria-hidden="true"/></span>
          {t("shortageStudioCatalog")}
        </h3>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
          {t("shortageStudioOnPage", { count: numbers.format(products.length) })}
        </span>
      </div>
      <div className="relative mt-3">
        <Search aria-hidden="true" className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"/>
        <input type="search" autoComplete="off" maxLength={100} value={search}
          aria-label={t("shortageStudioSearchProduct")}
          placeholder={t("shortageStudioSearchProduct")}
          onChange={event => setSearch(event.target.value)} disabled={disabled}
          className="h-11 w-full rounded-xl border border-slate-200 bg-slate-50 ps-10 pe-3 text-sm outline-none transition focus:border-sky-400 focus:bg-white focus:ring-2 focus:ring-sky-100" />
      </div>
      {search.trim().length === 1 && <p className="mt-1.5 text-[11px] text-slate-500">{t("shortageStudioSearchSecond")}</p>}
    </div>

    <div className="min-h-[14rem] max-h-[23rem] flex-1 overflow-y-auto p-2.5 sm:p-3"
      aria-busy={busy} data-testid="shortage-visible-products">
      {!scope || disabled ? <p className="py-14 text-center text-sm text-slate-500">{t("shortageStudioCatalogUnavailable")}</p> :
        failure ? <div role="alert" className="space-y-3 rounded-xl bg-red-50 p-4 text-sm text-red-800">
          {apiErrorMessage(failure, translation("dispatchProductSearch.error"))}
          <button type="button" onClick={page.retry}
            className="block min-h-9 rounded-lg border border-red-300 bg-white px-3 text-xs font-bold">{translation("common.retry")}</button>
        </div> :
          busy && !products.length ? <div role="status" className="space-y-2 px-2 py-4">
            {[0,1,2,3,4].map(i => <div key={i} className="h-12 animate-pulse rounded-xl bg-slate-100"/>)}
            <span className="sr-only">{translation("common.loading")}</span>
          </div> :
            products.length === 0 ? <div className="grid place-items-center gap-2 py-12 text-center">
              <Package className="h-8 w-8 text-slate-300" aria-hidden="true"/>
              <p className="text-sm text-slate-500">{t("shortageStudioEmptyCatalog")}</p>
            </div> : <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {products.map(product => {
                const count = counts.get(product.id) || 0;
                return <button key={product.id} type="button" disabled={disabled}
                  aria-label={t("shortageQuickAddOne", {product: product.name})}
                  onClick={() => onAdd(product.id, product.name)}
                  className={`group flex min-h-[4rem] min-w-0 items-center gap-2.5 rounded-xl border px-3 py-2.5 text-start transition-colors focus-visible:ring-2 focus-visible:ring-sky-300 ${count
                    ? "border-sky-200 bg-sky-50/70 hover:bg-sky-100" :
                      "border-slate-200 bg-white hover:border-sky-300 hover:bg-sky-50"} disabled:opacity-50`}>
                  <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${count
                    ? "bg-sky-100 text-sky-700" : "bg-slate-100 text-slate-500"}`}>
                    {count ? <Check className="h-4 w-4" aria-hidden="true"/> : <Package className="h-4 w-4" aria-hidden="true"/>}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block line-clamp-2 text-xs font-semibold leading-5 text-slate-800">{product.name}</span>
                    {count > 0 && <span className="block text-[11px] font-bold text-sky-700">{t("shortageStudioAdded", {count: numbers.format(count)})}</span>}
                  </span>
                  <span aria-hidden="true" className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-sky-700 text-white shadow-sm group-hover:bg-sky-800">
                    <Plus className="h-4 w-4"/>
                  </span>
                </button>;
              })}
            </div>}
    </div>
    {(page.hasPrevious || page.hasMore) && <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-4 py-2.5">
      <button type="button" onClick={page.previous} disabled={!page.hasPrevious || page.loading}
        className="flex min-h-9 items-center gap-1 rounded-lg border border-slate-200 px-2.5 text-xs font-bold text-slate-600 disabled:opacity-40">
        <ChevronRight aria-hidden="true" className="h-3.5 w-3.5"/>{t("shortageStudioPrevious")}
      </button>
      <span className="text-xs text-slate-500">{t("shortageStudioPage", {count: numbers.format(page.pageNumber)})}</span>
      <button type="button" onClick={page.loadMore} disabled={!page.hasMore || page.loading}
        className="flex min-h-9 items-center gap-1 rounded-lg bg-sky-50 px-2.5 text-xs font-bold text-sky-800 disabled:opacity-40">
        {t("shortageStudioNext")}<ChevronLeft aria-hidden="true" className="h-3.5 w-3.5"/>
      </button>
    </div>}
  </section>;
}
