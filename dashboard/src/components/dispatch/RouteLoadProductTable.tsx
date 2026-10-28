import { useTranslation } from "react-i18next";
import { useLoadProductSearchText } from "@/features/dispatch/useLoadProductSearchText";
import { useDispatchProductSearch, type DispatchDiscoveryProduct } from "@/features/dispatch/useDispatchProductSearch";
import { mergeDispatchProductWindow } from "@/features/dispatch/productWindow";
import { formatRouteLoadQuantity, routeLoadReview, type RouteLoadUom } from "@/features/dispatch/routeLoadUom";
import type { Quantity } from "@/lib/quantity";
import { ProductSearchControls } from "./ProductSearchControls";
import { InfiniteProductScroll } from "./InfiniteProductScroll";

export function RouteLoadProductTable({ vehicleId, warehouseId, scope, current, targets, units, names, onTargetChange, onClear, custodyReady = true }: {
  vehicleId: string; warehouseId: string; scope: string | null; current: Record<string, Quantity>; targets: Record<string, Quantity>;
  units: Record<string, RouteLoadUom>; names: Record<string, string>;
  onTargetChange: (id: string, name: string, unit: RouteLoadUom, value: string) => void; onClear: () => void;
  custodyReady?: boolean;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useLoadProductSearchText(JSON.stringify([scope, vehicleId, warehouseId]));
  const endpoint = vehicleId && warehouseId
    ? `/dispatch/products?purpose=LOAD&vehicle_id=${encodeURIComponent(vehicleId)}&warehouse_id=${encodeURIComponent(warehouseId)}`
    : null;
  const page = useDispatchProductSearch(endpoint, search, scope);
  const pins: DispatchDiscoveryProduct[] = [...new Set([...Object.keys(current), ...Object.keys(targets)])]
    .map((id) => ({ id, name: names[id] || t("dispatchProductSearch.unavailable"), load: null }));
  const rows = mergeDispatchProductWindow(pins, page.items);

  return <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div className="border-b border-slate-100 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-black text-slate-800">{t("dispatchProductSearch.managementTitle")}</h3>
        <button
          type="button"
          disabled={!custodyReady}
          onClick={onClear}
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-bold text-red-600 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t("dispatchProductSearch.clear")}
        </button>
      </div>
      <ProductSearchControls search={search} onChange={setSearch} page={page} enabled={!!endpoint} />
    </div>

    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr className="border-b border-slate-200">
            <th className="p-3 text-start text-xs font-black">{t("dispatchProductSearch.product")}</th>
            <th className="p-3 text-center text-xs font-black">{t("dispatchRouteLoad.current")}</th>
            <th className="p-3 text-center text-xs font-black">{t("dispatchRouteLoad.target")}</th>
            <th className="p-3 text-center text-xs font-black">{t("dispatchRouteLoad.difference")}</th>
            <th className="p-3 text-center text-xs font-black">{t("dispatchRouteLoad.action")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">{rows.map((product) => {
          const unit = units[product.id] || product.load;
          const physical = current[product.id] || "0";
          const target = targets[product.id] || "0";
          let review: ReturnType<typeof routeLoadReview> | null = null;
          try { if (unit) review = routeLoadReview(physical, target, unit); } catch { /* Preserve the editable draft. */ }
          return <tr key={product.id} data-product-id={product.id} className="transition-colors hover:bg-slate-50/80">
            <td className="p-3 font-bold text-slate-800">{product.name}</td>
            <td className="p-3 text-center font-semibold text-slate-700">
              {unit ? formatRouteLoadQuantity(physical, unit) : t("dispatchRouteLoad.loading")}
            </td>
            <td className="p-3 text-center">
              <label className="sr-only" htmlFor={`route-base-${product.id}`}>{t("dispatchRouteLoad.target")} — {product.name}</label>
              <input
                id={`route-base-${product.id}`}
                type="text"
                inputMode="decimal"
                disabled={!unit || !custodyReady}
                value={target}
                aria-invalid={!!unit && !review}
                title={unit ? `${t("dispatchRouteLoad.baseInput")}: ${unit.base_uom_name}` : t("dispatchRouteLoad.loading")}
                onChange={(event) => { if (unit) onTargetChange(product.id, product.name, unit, event.target.value); }}
                className="w-28 rounded-lg border border-slate-300 bg-white p-2 text-center font-bold text-slate-800 outline-none focus:border-[#1e87bb] focus:ring-2 focus:ring-[#1e87bb]/10 disabled:bg-slate-50 disabled:text-slate-400"
              />
              {unit && review && <p className="mt-1 text-xs font-semibold text-slate-500">{formatRouteLoadQuantity(target, unit)}</p>}
            </td>
            <td className="p-3 text-center font-semibold text-slate-700">
              {unit && review ? formatRouteLoadQuantity(review.absoluteDelta, unit) : t("dispatchRouteLoad.invalid")}
            </td>
            <td className="p-3 text-center text-xs font-bold text-slate-600">
              {t(!review ? "dispatchRouteLoad.blocked" : review.direction === "ADD" ? "dispatchRouteLoad.add"
                : review.direction === "UNLOAD" ? "dispatchRouteLoad.unload" : "dispatchRouteLoad.unchanged")}
            </td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <InfiniteProductScroll page={page} />
  </section>;
}
