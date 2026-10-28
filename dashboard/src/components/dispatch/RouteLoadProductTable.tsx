import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useDispatchProductSearch, type DispatchDiscoveryProduct } from "@/features/dispatch/useDispatchProductSearch";
import { mergeDispatchProductWindow } from "@/features/dispatch/productWindow";
import { formatRouteLoadQuantity, routeLoadReview, type RouteLoadUom } from "@/features/dispatch/routeLoadUom";
import type { Quantity } from "@/lib/quantity";
import { ProductSearchControls } from "./ProductSearchControls";

export function RouteLoadProductTable({ vehicleId, warehouseId, scope, current, targets, units, names, onTargetChange, onClear }: {
  vehicleId: string; warehouseId: string; scope: string | null; current: Record<string, Quantity>; targets: Record<string, Quantity>;
  units: Record<string, RouteLoadUom>; names: Record<string, string>;
  onTargetChange: (id: string, name: string, unit: RouteLoadUom, value: string) => void; onClear: () => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const endpoint = vehicleId && warehouseId ? `/dispatch/products?purpose=LOAD&vehicle_id=${encodeURIComponent(vehicleId)}&warehouse_id=${encodeURIComponent(warehouseId)}` : null;
  const page = useDispatchProductSearch(endpoint, search, scope);
  const pins: DispatchDiscoveryProduct[] = [...new Set([...Object.keys(current), ...Object.keys(targets)])]
    .map((id) => ({ id, name: names[id] || t("dispatchProductSearch.unavailable"), load: null }));
  const rows = mergeDispatchProductWindow(pins, page.items);
  return <section className="space-y-3 rounded-2xl border p-4">
    <ProductSearchControls search={search} onChange={setSearch} page={page} enabled={!!endpoint} />
    <button type="button" onClick={onClear}>{t("dispatchProductSearch.clear")}</button>
    <div className="max-h-[400px] overflow-auto"><table className="w-full text-sm">
      <thead><tr><th>{t("dispatchProductSearch.product")}</th><th>{t("dispatchRouteLoad.current")}</th>
        <th>{t("dispatchRouteLoad.target")}</th><th>{t("dispatchRouteLoad.difference")}</th><th>{t("dispatchRouteLoad.action")}</th></tr></thead>
      <tbody>{rows.map((product) => {
        const unit = units[product.id] || product.load;
        const physical = current[product.id] || "0";
        const target = targets[product.id] || "0";
        let review: ReturnType<typeof routeLoadReview> | null = null;
        try { if (unit) review = routeLoadReview(physical, target, unit); } catch { /* Preserve the editable draft. */ }
        return <tr key={product.id} data-product-id={product.id}>
          <td>{product.name}</td><td>{unit ? formatRouteLoadQuantity(physical, unit) : t("dispatchRouteLoad.loading")}</td>
          <td><label className="sr-only" htmlFor={`route-base-${product.id}`}>{t("dispatchRouteLoad.target")} — {product.name}</label>
            <input id={`route-base-${product.id}`} type="text" inputMode="decimal" disabled={!unit} value={target} aria-invalid={!!unit && !review}
              title={unit ? `${t("dispatchRouteLoad.baseInput")}: ${unit.base_uom_name}` : t("dispatchRouteLoad.loading")}
              onChange={(event) => { if (unit) onTargetChange(product.id, product.name, unit, event.target.value); }} className="w-28 rounded border p-2" />
            {unit && review && <p>{formatRouteLoadQuantity(target, unit)}</p>}</td>
          <td>{unit && review ? formatRouteLoadQuantity(review.absoluteDelta, unit) : t("dispatchRouteLoad.invalid")}</td>
          <td>{t(!review ? "dispatchRouteLoad.blocked" : review.direction === "ADD" ? "dispatchRouteLoad.add"
            : review.direction === "UNLOAD" ? "dispatchRouteLoad.unload" : "dispatchRouteLoad.unchanged")}</td>
        </tr>;
      })}</tbody>
    </table></div>
  </section>;
}
