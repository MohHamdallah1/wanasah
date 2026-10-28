import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useLoadProductSearchText } from "@/features/dispatch/useLoadProductSearchText";
import { useDispatchProductWindow } from "@/features/dispatch/useDispatchProductWindow";
import type { DispatchDiscoveryProduct } from "@/features/dispatch/useDispatchProductSearch";
import { formatRouteLoadQuantity, routeLoadReview, type RouteLoadUom } from "@/features/dispatch/routeLoadUom";
import type { Quantity } from "@/lib/quantity";
import { ProductSearchControls } from "./ProductSearchControls";
import {
  MeasuredProductTableBody,
  useDispatchWindowSentinels,
} from "./DispatchProductWindow";

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
  const page = useDispatchProductWindow(endpoint, search, scope);
  const pinned: DispatchDiscoveryProduct[] = [...new Set([...Object.keys(current), ...Object.keys(targets)])]
    .map((id) => ({ id, name: names[id] || t("dispatchProductSearch.unavailable"), load: null }));
  const pinnedIds = useMemo(() => new Set(pinned.map((product) => product.id)), [pinned]);
  const { topRef, bottomRef } = useDispatchWindowSentinels(page);

  const renderRow = (product: DispatchDiscoveryProduct) => {
    const unit = units[product.id] || product.load;
    const physical = current[product.id] || "0";
    const target = targets[product.id] || "0";
    let review: ReturnType<typeof routeLoadReview> | null = null;
    try { if (unit) review = routeLoadReview(physical, target, unit); } catch { /* Preserve the editable draft. */ }
    return <tr key={product.id} data-product-id={product.id} className="border-b border-slate-100">
      <td className="p-3 font-medium">{product.name}</td>
      <td className="p-3 text-center">{unit ? formatRouteLoadQuantity(physical, unit) : t("dispatchRouteLoad.loading")}</td>
      <td className="p-3 text-center">
        <label className="sr-only" htmlFor={`route-base-${product.id}`}>{t("dispatchRouteLoad.target")} — {product.name}</label>
        <input id={`route-base-${product.id}`} type="text" inputMode="decimal" disabled={!unit || !custodyReady} value={target}
          aria-invalid={!!unit && !review}
          title={unit ? `${t("dispatchRouteLoad.baseInput")}: ${unit.base_uom_name}` : t("dispatchRouteLoad.loading")}
          onChange={(event) => { if (unit) onTargetChange(product.id, product.name, unit, event.target.value); }}
          className="w-28 rounded border border-slate-300 bg-white p-2 text-center" />
        {unit && review && <p className="mt-1 text-xs text-slate-500">{formatRouteLoadQuantity(target, unit)}</p>}
      </td>
      <td className="p-3 text-center">{unit && review ? formatRouteLoadQuantity(review.absoluteDelta, unit) : t("dispatchRouteLoad.invalid")}</td>
      <td className="p-3 text-center">{t(!review ? "dispatchRouteLoad.blocked" : review.direction === "ADD" ? "dispatchRouteLoad.add"
        : review.direction === "UNLOAD" ? "dispatchRouteLoad.unload" : "dispatchRouteLoad.unchanged")}</td>
    </tr>;
  };

  return <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
    <ProductSearchControls search={search} onChange={setSearch} page={page} enabled={!!endpoint} />
    <button type="button" disabled={!custodyReady} onClick={onClear}>{t("dispatchProductSearch.clear")}</button>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-sm">
        <thead><tr className="border-b border-slate-200 bg-slate-50">
          <th className="p-3 text-start">{t("dispatchProductSearch.product")}</th>
          <th className="p-3 text-center">{t("dispatchRouteLoad.current")}</th>
          <th className="p-3 text-center">{t("dispatchRouteLoad.target")}</th>
          <th className="p-3 text-center">{t("dispatchRouteLoad.difference")}</th>
          <th className="p-3 text-center">{t("dispatchRouteLoad.action")}</th>
        </tr></thead>
        {!!pinned.length && <tbody>{pinned.map(renderRow)}</tbody>}
        {page.topSpacerHeight > 0 && <tbody aria-hidden="true"><tr><td colSpan={5} style={{ height: page.topSpacerHeight }} /></tr></tbody>}
        <tbody ref={topRef} data-window-boundary="top" aria-hidden="true"><tr><td colSpan={5} className="h-px p-0" /></tr></tbody>
        {page.pages.map((windowPage) => (
          <MeasuredProductTableBody key={windowPage.index} index={windowPage.index} onMeasure={page.registerPageHeight}>
            {windowPage.items.filter((product) => !pinnedIds.has(product.id)).map(renderRow)}
          </MeasuredProductTableBody>
        ))}
        <tbody ref={bottomRef} data-window-boundary="bottom" aria-hidden="true"><tr><td colSpan={5} className="h-px p-0" /></tr></tbody>
        {page.bottomSpacerHeight > 0 && <tbody aria-hidden="true"><tr><td colSpan={5} style={{ height: page.bottomSpacerHeight }} /></tr></tbody>}
      </table>
    </div>
  </section>;
}
