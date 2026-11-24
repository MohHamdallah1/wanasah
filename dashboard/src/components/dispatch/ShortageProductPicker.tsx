import { useEffect, useMemo, useRef, useState, type UIEvent } from "react";
import { Check, Package, Plus, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useDispatchProductWindow } from "@/features/dispatch/useDispatchProductWindow";
import { compareShortageVehicleBase, dispatchUiText } from "@/features/dispatch/dispatchUiText";
import { apiErrorMessage } from "@/lib/apiErrors";
import { MeasuredProductPage } from "./DispatchProductWindow";
import { useShortageVehicleAvailability } from "@/features/dispatch/useShortageVehicleAvailability";
import type { ShortageDraftRow } from "@/features/dispatch/dispatchDrafts";

/** Continuous 50k-safe browsing: only 3×80 signed products are mounted at once. */
export function ShortageProductPicker({
  scope, drafted, onAdd, disabled = false, driverId = "",
}: {
  scope: string | null;
  driverId?: string;
  drafted: ShortageDraftRow[];
  onAdd: (id: string, name: string, baseUomCode?: string | null) => void;
  disabled?: boolean;
}) {
  const { i18n, t: translation } = useTranslation();
  const t = (key: Parameters<typeof dispatchUiText>[1], values?: Record<string, string | number>) =>
    dispatchUiText(i18n.language, key, values ?? {});
  const [search, setSearch] = useState("");
  // A single character cannot run a company-wide LIKE search. Keep showing
  // the blank browse until a full two-character query is supplied.
  const serverQuery = search.trim().length === 1 ? "" : search;
  const page = useDispatchProductWindow(
    disabled ? null : "/dispatch/products?purpose=SHORTAGE", serverQuery, scope, "SHORTAGE",
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastScrollTop = useRef(0);
  useEffect(() => {
    // The actor/scope and search change invalidate all old result pages.
    // Never hold the previous query's scroll position over the new catalog.
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
    lastScrollTop.current = 0;
  }, [page.queryKey]);

  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    if (!page.firstPageReady || page.loading || page.loadingWindow || page.error || disabled) return;
    const list = event.currentTarget;
    const position = list.scrollTop;
    const delta = position - lastScrollTop.current;
    lastScrollTop.current = position;
    if (delta > 0 && list.scrollHeight - position - list.clientHeight < 160 && page.hasMore) {
      page.loadMore();
    } else if (delta < 0 && position < 160 && page.hasPrevious) {
      page.loadPrevious();
    }
  };

  const pinned = useMemo(() => new Map(drafted.map(item => [item.productId, item])), [drafted]);
  const vehicle = useShortageVehicleAvailability({
    driverId, scope, productIds: page.items.map(product => product.id),
  });
  // A new query is not empty until its signed first page completes.
  const firstLoad = !page.firstPageReady && !page.pages.length;
  const hasProducts = page.items.length > 0;

  return <section data-testid="shortage-product-catalog"
    aria-label={t("shortageStudioCatalog")}
    className="flex min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div className="border-b border-slate-100 px-3 py-2.5">
      <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"/>
        <input type="search" autoComplete="off" maxLength={100} value={search}
          aria-label={t("shortageStudioSearchProduct")}
          placeholder={t("shortageStudioSearchProduct")}
          onChange={event => setSearch(event.target.value)} disabled={disabled}
          className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50 ps-10 pe-3 text-sm outline-none transition focus:border-sky-400 focus:bg-white focus:ring-2 focus:ring-sky-100" />
      </div>
      {search.trim().length === 1 && <p className="mt-1 text-[11px] text-slate-500">{t("shortageStudioSearchSecond")}</p>}
    </div>

    <div ref={scrollRef} onScroll={handleScroll}
      className="h-[23rem] min-w-0 shrink-0 overflow-y-auto overscroll-contain px-2.5 py-2.5 sm:px-3"
      aria-busy={Boolean(scope && !disabled && !page.error && (firstLoad || page.loading || page.loadingWindow))}
      aria-label={t("shortageStudioCatalog")}
      tabIndex={0}
      data-testid="shortage-visible-products">
      {!scope || disabled ? <p className="py-14 text-center text-sm text-slate-500">{t("shortageStudioCatalogUnavailable")}</p> :
        page.error ? <div role="alert" className="space-y-3 rounded-xl bg-red-50 p-4 text-sm text-red-800">
          {apiErrorMessage(page.error, translation("dispatchProductSearch.error"))}
          <button type="button" onClick={page.retry}
            className="block min-h-9 rounded-lg border border-red-300 bg-white px-3 text-xs font-bold">{translation("common.retry")}</button>
        </div> :
          firstLoad ? <div role="status" className="grid h-full place-items-center text-xs text-slate-500">
            {translation("common.loading")}
          </div> :
            !hasProducts && !page.loading ? <div className="grid place-items-center gap-2 py-12 text-center">
              <Package className="h-8 w-8 text-slate-300" aria-hidden="true"/>
              <p className="text-sm text-slate-500">{t("shortageStudioEmptyCatalog")}</p>
            </div> : <>
              {page.topSpacerHeight > 0 && <div aria-hidden="true" style={{ height: page.topSpacerHeight }}/>}
              {page.pages.map(windowPage => <MeasuredProductPage
                key={`${page.queryKey}:${windowPage.index}`} index={windowPage.index}
                onMeasure={page.registerPageHeight}
                className="grid grid-cols-1 gap-2 pb-2 sm:grid-cols-2"
              >
                {windowPage.items.map(product => {
                  const pinnedRow = pinned.get(product.id);
                  const count = pinnedRow?.quantity ?? 0;
                  const stock = vehicle.byProduct.get(product.id);
                  // Never retrofit a legacy/foreign draft row with a freshly
                  // browsed SKU's UOM without explicit new product selection.
                  const comparableUnit = pinnedRow
                    ? pinnedRow.baseUomCode && pinnedRow.baseUomCode === product.baseUomCode
                      ? pinnedRow.baseUomCode : null
                    : product.baseUomCode;
                  const result = compareShortageVehicleBase({
                    requested: count > 0 ? count : 1,
                    requestBaseUomCode: comparableUnit,
                    stock,
                    verified: vehicle.status === "VERIFIED",
                  });
                  const values = {
                    potential: result.potentialBase ?? "0",
                    outstanding: result.outstandingBase ?? "0",
                    unit: comparableUnit ?? "",
                  };
                  const quoteText = result.kind === "UNKNOWN" ? t("shortageVehicleUnknown")
                    : count > 0
                      ? result.kind === "FULL" ? t("shortageVehicleFull", values)
                        : result.kind === "PARTIAL" ? t("shortageVehiclePartial", values)
                        : t("shortageVehicleZero", values)
                      : result.kind === "ZERO" ? t("shortageVehicleNeedsSupply")
                        : t("shortageVehicleAvailable", {
                            count: stock!.available_base, unit: comparableUnit ?? "",
                          });
                  return <button key={product.id} type="button" disabled={disabled}
                    aria-label={t("shortageQuickAddOne", {product: product.name})}
                    onClick={() => onAdd(product.id, product.name, product.baseUomCode)}
                    className={`group flex min-h-[4rem] min-w-0 items-center gap-2.5 rounded-xl border px-3 py-2.5 text-start transition-colors focus-visible:ring-2 focus-visible:ring-sky-300 ${count
                      ? "border-sky-200 bg-sky-50/70 hover:bg-sky-100" :
                        "border-slate-200 bg-white hover:border-sky-300 hover:bg-sky-50"} disabled:opacity-50`}>
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${count
                      ? "bg-sky-100 text-sky-700" : "bg-slate-100 text-slate-500"}`}>
                      {count ? <Check className="h-4 w-4" aria-hidden="true"/> : <Package className="h-4 w-4" aria-hidden="true"/>}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block line-clamp-2 text-xs font-semibold leading-5 text-slate-800">{product.name}</span>
                      {count > 0 && <span className="block text-[11px] font-bold text-sky-700">
                        {t("shortageStudioAdded", {count: new Intl.NumberFormat(i18n.language.startsWith("ar") ? "ar" : "en").format(count)})}
                      </span>}
                      {product.baseUomCode && <span className="block text-[11px] text-slate-500">
                        {t("shortageVehicleBaseUnit", {unit: product.baseUomCode})}
                      </span>}
                      {driverId && <span className="block text-[11px] font-semibold text-slate-600">
                        {quoteText}
                      </span>}
                    </span>
                    <span aria-hidden="true" className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-sky-700 text-white shadow-sm group-hover:bg-sky-800">
                      <Plus className="h-4 w-4"/>
                    </span>
                  </button>;
                })}
              </MeasuredProductPage>)}
              {page.bottomSpacerHeight > 0 && <div aria-hidden="true" style={{ height: page.bottomSpacerHeight }}/>}
              {page.loadingWindow && <div role="status" className="py-2 text-center text-xs text-slate-500">
                {translation("common.loading")}
              </div>}
            </>}
    </div>
  </section>;
}
