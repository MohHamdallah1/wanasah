import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { RotateCcw, Trash2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLoadProductSearchText } from "@/features/dispatch/useLoadProductSearchText";
import { useDispatchProductWindow } from "@/features/dispatch/useDispatchProductWindow";
import type { DispatchDiscoveryProduct } from "@/features/dispatch/useDispatchProductSearch";
import { formatRouteLoadQuantity, routeLoadReview, type RouteLoadUom } from "@/features/dispatch/routeLoadUom";
import type { Quantity } from "@/lib/quantity";
import { MeasuredProductTableBody } from "./DispatchProductWindow";
import { useDispatchWindowSentinels } from "@/features/dispatch/useDispatchWindowSentinels";

type TargetSnapshot = { scopeKey: string; values: Record<string, Quantity> };

export function RouteLoadProductTable({
  vehicleId, warehouseId, scope, current, targets, units, names,
  onTargetChange, onClear, onRestoreClear, custodyReady = true, pending = false,
  commandReady = true, actionsHost,
}: {
  vehicleId: string; warehouseId: string; scope: string | null;
  current: Record<string, Quantity>; targets: Record<string, Quantity>;
  units: Record<string, RouteLoadUom>; names: Record<string, string>;
  pending?: boolean;
  onTargetChange: (id: string, name: string, unit: RouteLoadUom, value: string) => void;
  onClear: () => void;
  onRestoreClear: (values: Record<string, Quantity>) => void;
  custodyReady?: boolean;
  commandReady?: boolean;
  actionsHost?: HTMLElement | null;
}) {
  const { t, i18n } = useTranslation();
  const isArabic = i18n.language.startsWith("ar");
  const [search, setSearch] = useLoadProductSearchText(JSON.stringify([scope, vehicleId, warehouseId]));
  const endpoint = vehicleId && warehouseId
    ? `/dispatch/products?purpose=LOAD&vehicle_id=${encodeURIComponent(vehicleId)}&warehouse_id=${encodeURIComponent(warehouseId)}`
    : null;
  const page = useDispatchProductWindow(endpoint, search, scope);
  const pinned: DispatchDiscoveryProduct[] = [...new Set([...Object.keys(current), ...Object.keys(targets)])]
    .map((id) => ({ id, name: names[id] || t("dispatchProductSearch.unavailable"), load: null }));
  const pinnedIds = useMemo(() => new Set(pinned.map((product) => product.id)), [pinned]);
  const contextSelected = !!endpoint && !!scope;
  const firstRevealReady = contextSelected && custodyReady && !pending && page.firstPageReady;
  const joinedPending = pending || (contextSelected && !firstRevealReady && !page.error);
  const { topRef, bottomRef } = useDispatchWindowSentinels(page, {
    requireUserScroll: true, enabled: firstRevealReady,
  });

  // Undo is a local UI draft snapshot, NEVER an inventory transaction or a
  // second authority. A new actor remounts the workspace; changing vehicle,
  // warehouse, or scope invalidates the previous snapshot.
  const scopeKey = JSON.stringify([scope, vehicleId, warehouseId]);
  const [clearSnapshot, setClearSnapshot] = useState<TargetSnapshot | null>(null);
  useEffect(() => setClearSnapshot(null), [scopeKey]);
  // A signed inventory refresh or another controller update must NOT let
  // an old Undo overwrite new real targets after the clear operation.
  useEffect(() => {
    if (clearSnapshot && Object.keys(targets).length !== 0) setClearSnapshot(null);
  }, [clearSnapshot, targets]);
  const canEdit = firstRevealReady && commandReady && !page.loading;
  const canUndo = canEdit && clearSnapshot?.scopeKey === scopeKey;

  const clearAll = () => {
    if (!canEdit || Object.keys(targets).length === 0) return;
    setClearSnapshot({ scopeKey, values: { ...targets } });
    onClear();
  };

  const undoClear = () => {
    if (!canUndo || !clearSnapshot) return;
    onRestoreClear({ ...clearSnapshot.values });
    setClearSnapshot(null);
  };

  const renderRow = (product: DispatchDiscoveryProduct) => {
    const unit = units[product.id] || product.load;
    const physical = current[product.id] || "0";
    const target = targets[product.id] || "0";
    let review: ReturnType<typeof routeLoadReview> | null = null;
    try { if (unit) review = routeLoadReview(physical, target, unit); } catch { /* Preserve the editable draft. */ }
    return <tr key={product.id} data-product-id={product.id} className="border-b border-slate-100 last:border-0 hover:bg-sky-50/40">
      <td className="px-3 py-3 font-semibold text-slate-700">{product.name}</td>
      <td className="px-3 py-3 text-center tabular-nums">{unit ? formatRouteLoadQuantity(physical, unit) : t("dispatchRouteLoad.loading")}</td>
      <td className="relative px-3 py-2 text-center">
        <label className="sr-only" htmlFor={`route-base-${product.id}`}>{t("dispatchRouteLoad.target")} — {product.name}</label>
        <input id={`route-base-${product.id}`} type="text" inputMode="decimal" disabled={!unit || !canEdit} value={target}
          aria-invalid={!!unit && !review}
          title={unit ? `${t("dispatchRouteLoad.baseInput")}: ${unit.base_uom_name}` : t("dispatchRouteLoad.loading")}
          onChange={(event) => {
            if (unit) {
              setClearSnapshot(null);
              onTargetChange(product.id, product.name, unit, event.target.value);
            }
          }}
          className="h-9 w-24 rounded-lg border border-slate-300 bg-white px-2 text-center tabular-nums outline-none focus:border-[#1e87bb] focus:ring-2 focus:ring-[#1e87bb]/15 disabled:bg-slate-100 sm:w-28" />
        {unit && review && <p className="mt-1 text-[11px] text-slate-500">{formatRouteLoadQuantity(target, unit)}</p>}
      </td>
      <td className="px-3 py-3 text-center tabular-nums">{unit && review ? formatRouteLoadQuantity(review.absoluteDelta, unit) : t("dispatchRouteLoad.invalid")}</td>
      <td className="px-3 py-3 text-center text-slate-600">{t(!review ? "dispatchRouteLoad.blocked" : review.direction === "ADD" ? "dispatchRouteLoad.add"
        : review.direction === "UNLOAD" ? "dispatchRouteLoad.unload" : "dispatchRouteLoad.unchanged")}</td>
    </tr>;
  };

  // These commands own the table's undo snapshot but are rendered alongside
  // the four selectors. They do not create a second toolbar or extra row.
  const actions = <div className="flex items-center justify-end gap-1.5" data-testid="dispatch-launch-load-actions">
    <button type="button" onClick={clearAll}
      disabled={!canEdit || Object.keys(targets).length === 0}
      title={isArabic ? "تصفير الحمولة المستهدفة مع إمكانية التراجع" : "Clear target quantities; undo is available"}
      className="inline-flex h-9 shrink-0 items-center gap-1 rounded-lg border border-slate-300 bg-white px-2 text-[11px] font-bold text-slate-700 hover:border-rose-300 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
      <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
      {isArabic ? "تصفير الكل" : "Clear all"}
    </button>
    <button type="button" onClick={undoClear} disabled={!canUndo}
      title={isArabic ? "استرجاع الكميات كما كانت قبل آخر تصفير" : "Restore the quantities before the last clear"}
      className="inline-flex h-9 shrink-0 items-center gap-1 rounded-lg border border-sky-200 bg-sky-50 px-2 text-[11px] font-bold text-[#166a94] hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
      <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />
      {isArabic ? "تراجع" : "Undo clear"}
    </button>
  </div>;

  // A stable, full-size workbench: signed first-page/loading/empty transitions
  // never collapse the table card or move its floating launch action.
  return <>
    {actionsHost ? createPortal(actions, actionsHost) : actionsHost === undefined ? actions : null}
    <section data-testid="dispatch-launch-products" aria-busy={joinedPending}
      data-first-window-ready={firstRevealReady ? "true" : "false"}
      className="flex min-h-[300px] w-full min-w-0 flex-1 flex-col">
      <div className="min-w-0 flex-1 overflow-x-auto">
      <table className="w-full min-w-[820px] text-sm">
        <thead><tr className="border-b border-slate-200 bg-slate-100/80 text-slate-600">
          <th className="w-[32%] px-3 py-2 text-start">
            <label className="relative block w-full max-w-[300px]">
              <span className="sr-only">{t("dispatchProductSearch.search")}</span>
              <Search aria-hidden="true" className="pointer-events-none absolute end-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input type="text" aria-label={t("dispatchProductSearch.search")}
                placeholder={t("dispatchProductSearch.search")} maxLength={100}
                value={search} disabled={!endpoint} onChange={event => setSearch(event.target.value)}
                className="h-8 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 pe-9 text-xs font-medium text-slate-700 outline-none placeholder:text-slate-400 focus:border-[#1e87bb] focus:ring-2 focus:ring-[#1e87bb]/15 disabled:bg-slate-100" />
            </label>
          </th>
          <th className="px-3 py-3 text-center">{t("dispatchRouteLoad.current")}</th>
          <th className="px-3 py-3 text-center">{t("dispatchRouteLoad.target")}</th>
          <th className="px-3 py-3 text-center">{t("dispatchRouteLoad.difference")}</th>
          <th className="px-3 py-3 text-center">{t("dispatchRouteLoad.action")}</th>
        </tr></thead>
        {!firstRevealReady && contextSelected && !page.error && <tbody data-testid="dispatch-first-window-pending" aria-hidden="true"><tr><td colSpan={5} className="h-[72px] p-0"><div className="mx-3 h-8 rounded-lg bg-slate-50" /></td></tr></tbody>}
        {page.error && <tbody><tr><td colSpan={5} className="p-3 text-sm">
          <div role="alert" className="flex items-center gap-3 text-amber-800">
            <span>{t("dispatchProductSearch.error")}</span>
            <button type="button" onClick={page.retry} className="rounded-lg border border-amber-200 px-3 py-1.5 font-semibold">
              {t("common.retry")}
            </button>
          </div>
        </td></tr></tbody>}
        {firstRevealReady && !pinned.length && page.items.length === 0 && <tbody><tr><td colSpan={5} className="p-4 text-center text-sm text-slate-500">{t("dispatchProductSearch.empty")}</td></tr></tbody>}
        {firstRevealReady && !!pinned.length && <tbody>{pinned.map(renderRow)}</tbody>}
        {firstRevealReady && page.topSpacerHeight > 0 && <tbody aria-hidden="true"><tr><td colSpan={5} style={{ height: page.topSpacerHeight }} /></tr></tbody>}
        <tbody ref={topRef} data-window-boundary="top" aria-hidden="true"><tr><td colSpan={5} className="h-px p-0" /></tr></tbody>
        {firstRevealReady && page.pages.map((windowPage) => (
          <MeasuredProductTableBody key={windowPage.index} index={windowPage.index} onMeasure={page.registerPageHeight}>
            {windowPage.items.filter((product) => !pinnedIds.has(product.id)).map(renderRow)}
          </MeasuredProductTableBody>
        ))}
        <tbody ref={bottomRef} data-window-boundary="bottom" aria-hidden="true"><tr><td colSpan={5} className="h-px p-0" /></tr></tbody>
        {firstRevealReady && page.bottomSpacerHeight > 0 && <tbody aria-hidden="true"><tr><td colSpan={5} style={{ height: page.bottomSpacerHeight }} /></tr></tbody>}
      </table>
    </div>
    </section>
  </>;
}
