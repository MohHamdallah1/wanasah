import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { RotateCcw, Trash2, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLoadProductSearchText } from "@/features/dispatch/useLoadProductSearchText";
import { useDispatchProductWindow } from "@/features/dispatch/useDispatchProductWindow";
import { DISPATCH_PRODUCT_PAGE_SIZE, type DispatchDiscoveryProduct } from "@/features/dispatch/useDispatchProductSearch";
import { matchesLoadPinnedProduct } from "@/features/dispatch/loadProductSearchMatch";
import { formatRouteLoadQuantity, INVALID_ROUTE_LOAD_TARGET, routeLoadReview, routeLoadUomIdentity, type RouteLoadUom } from "@/features/dispatch/routeLoadUom";
import { composeRouteLoadTargetBase, splitRouteLoadTargetBase } from "@/features/dispatch/routeLoadTargetParts";
import type { Quantity } from "@/lib/quantity";
import { MeasuredProductTableBody } from "./DispatchProductWindow";
import { useDispatchWindowSentinels } from "@/features/dispatch/useDispatchWindowSentinels";

type TargetSnapshot = { scopeKey: string; values: Record<string, Quantity> };
type TargetInputDraft = {
  scopeKey: string;
  unitKey: string;
  originBase: string;
  sentBase: string;
  display: string;
  remainder: string;
  error: string | null;
};

// Only normalize digit glyphs for EXACT decimal input, never compute with floats.
const asciiQuantityDigits = (value: string): string => value
  .replace(/[٠-٩]/g, char => String(char.charCodeAt(0) - 0x660))
  .replace(/[۰-۹]/g, char => String(char.charCodeAt(0) - 0x6f0))
  .replace(/٫/g, ".");

export function RouteLoadProductTable({
  vehicleId, warehouseId, scope, current, targets, units, names,
  onTargetChange, onClear, onRestoreClear, custodyReady = true, pending = false,
  commandReady = true, actionsHost, intentScope = "",
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
  intentScope?: string;
}) {
  const { t, i18n } = useTranslation();
  const isArabic = i18n.language.startsWith("ar");
  const [search, setSearch] = useLoadProductSearchText(JSON.stringify([scope, vehicleId, warehouseId]));
  const endpoint = vehicleId && warehouseId
    ? `/dispatch/products?purpose=LOAD&vehicle_id=${encodeURIComponent(vehicleId)}&warehouse_id=${encodeURIComponent(warehouseId)}`
    : null;
  const page = useDispatchProductWindow(endpoint, search, scope);
  // Real vehicle/draft products appear first when unfiltered, but must not
  // bypass a typed search. Search eligibility and SKU access remain backend-owned.
  const pinned: DispatchDiscoveryProduct[] = [...new Set([...Object.keys(current), ...Object.keys(targets)])]
    .map((id) => ({ id, name: names[id] || t("dispatchProductSearch.unavailable"), load: null }))
    .filter((product) => matchesLoadPinnedProduct(product.name, search));
  const pinnedIds = useMemo(() => new Set(pinned.map((product) => product.id)), [pinned]);
  // Retain ONLY the page index of products pinned while scrolling. This lets
  // numbers stay contiguous after a page is evicted without keeping 50k SKUs.
  const numberedPinsRef = useRef({ key: "", byId: new Map<string, number>() });
  if (numberedPinsRef.current.key !== page.queryKey) {
    numberedPinsRef.current = { key: page.queryKey, byId: new Map<string, number>() };
  }
  for (const windowPage of page.pages) {
    for (const product of windowPage.items) {
      if (pinnedIds.has(product.id)) numberedPinsRef.current.byId.set(product.id, windowPage.index);
    }
  }
  const numberedPages = page.pages.map((windowPage) => {
    let next = pinned.length + windowPage.index * DISPATCH_PRODUCT_PAGE_SIZE -
      [...numberedPinsRef.current.byId].filter(([id, index]) =>
        pinnedIds.has(id) && index < windowPage.index).length;
    const items: Array<{ product: DispatchDiscoveryProduct; rowNumber: number }> = [];
    for (const product of windowPage.items) {
      if (pinnedIds.has(product.id)) continue;
      items.push({ product, rowNumber: ++next });
    }
    return { ...windowPage, items };
  });
  const contextSelected = !!endpoint && !!scope;
  const firstRevealReady = contextSelected && custodyReady && !pending && page.firstPageReady;
  const joinedPending = pending || (contextSelected && !firstRevealReady && !page.error);
  const { topRef, bottomRef } = useDispatchWindowSentinels(page, {
    requireUserScroll: true, enabled: firstRevealReady,
  });

  // Undo is a local UI draft snapshot, NEVER an inventory transaction or a
  // second authority. A new actor remounts the workspace; changing vehicle,
  // warehouse, or scope invalidates the previous snapshot.
  const scopeKey = JSON.stringify([scope, vehicleId, warehouseId, intentScope]);
  const [clearSnapshot, setClearSnapshot] = useState<TargetSnapshot | null>(null);
  const [inputDrafts, setInputDrafts] = useState<Record<string, TargetInputDraft>>({});
  useEffect(() => { setClearSnapshot(null); setInputDrafts({}); }, [scopeKey]);
  // A genuine per-SKU conversion change invalidates an already composed draft.
  // Never silently reinterpret the old BASE total using a new pack/pallet factor.
  useEffect(() => {
    for (const [id, draft] of Object.entries(inputDrafts)) {
      if (draft.scopeKey !== scopeKey || targets[id] === INVALID_ROUTE_LOAD_TARGET) continue;
      const live = page.items.find(product => product.id === id)?.load || units[id];
      if (live && draft.unitKey !== routeLoadUomIdentity(live)) {
        onTargetChange(id, names[id] || id, live, INVALID_ROUTE_LOAD_TARGET);
      }
    }
  }, [inputDrafts, scopeKey, targets, units, names, page.items, onTargetChange]);
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
    setInputDrafts({});
    onClear();
  };

  const undoClear = () => {
    if (!canUndo || !clearSnapshot) return;
    onRestoreClear({ ...clearSnapshot.values });
    setInputDrafts({});
    setClearSnapshot(null);
  };

  const onQuantityArrow = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    const kind = event.currentTarget.dataset.routeTargetInput;
    if (!kind) return;
    const candidates = Array.from(event.currentTarget.closest("table")?.querySelectorAll<HTMLInputElement>(
      `input[data-route-target-input="${kind}"]:not(:disabled)`,
    ) ?? []);
    const position = candidates.indexOf(event.currentTarget);
    const next = candidates[position + (event.key === "ArrowDown" ? 1 : -1)];
    if (!next) return;
    event.preventDefault();
    next.focus();
    next.select();
  };

  const renderRow = (product: DispatchDiscoveryProduct, rowNumber: number) => {
    const unit = page.items.find(row => row.id === product.id)?.load || units[product.id] || product.load;
    const physical = current[product.id] || "0";
    const target = targets[product.id] || "0";
    const identity = unit ? routeLoadUomIdentity(unit) : "";
    const candidate = inputDrafts[product.id];
    const useDraft = !!candidate && candidate.scopeKey === scopeKey &&
      candidate.unitKey === identity && (target === candidate.sentBase || target === candidate.originBase);
    let parts: ReturnType<typeof splitRouteLoadTargetBase> | null = null;
    try { if (unit && target !== INVALID_ROUTE_LOAD_TARGET) parts = splitRouteLoadTargetBase(target, unit); }
    catch { /* Malformed or newly changed UOM never becomes an allowed target. */ }
    const draft = useDraft ? candidate : null;
    const outerValue = draft ? draft.display : parts?.displayQuantity === "0" ? "" : parts?.displayQuantity ?? "";
    const remainderValue = draft ? draft.remainder :
      parts?.baseRemainder === "0" ? "" : parts?.baseRemainder ?? "";
    const hasDisplay = !!parts?.hasDisplayUnit || !!unit?.display_uom_name &&
      unit?.display_factor_to_base !== null && unit?.display_factor_to_base !== "1";
    const inputError = draft?.error ?? (!parts && unit && target !== "0" ? "DISPATCH_TARGET_INVALID" : null);
    const errorLabel = inputError === "DISPATCH_DISPLAY_REMAINDER_TOO_LARGE"
      ? t("dispatchRouteLoad.remainderTooLarge", { unit: unit?.display_uom_name })
      : inputError === "DISPATCH_DISPLAY_COUNT_INVALID"
        ? t("dispatchRouteLoad.displayCountInvalid")
        : t("dispatchRouteLoad.invalid");
    const editPart = (kind: "display" | "base", raw: string) => {
      if (!unit) return;
      const nextDisplay = kind === "display" ? raw : outerValue;
      const nextRemainder = kind === "base" ? raw : remainderValue;
      let sentBase = INVALID_ROUTE_LOAD_TARGET;
      let error: string | null = null;
      try {
        sentBase = composeRouteLoadTargetBase(
          asciiQuantityDigits(nextDisplay), asciiQuantityDigits(nextRemainder), unit,
        );
      } catch (failure) {
        error = failure instanceof Error ? failure.message : "DISPATCH_TARGET_INVALID";
      }
      setInputDrafts(previous => ({
        ...previous,
        [product.id]: {
          scopeKey, unitKey: identity, originBase: draft?.originBase ?? target,
          sentBase, display: nextDisplay, remainder: nextRemainder, error,
        },
      }));
      setClearSnapshot(null);
      onTargetChange(product.id, product.name, unit, sentBase);
    };
    let review: ReturnType<typeof routeLoadReview> | null = null;
    try { if (unit && !inputError) review = routeLoadReview(physical, target, unit); }
    catch { /* Keep an invalid local edit visible and block any actual movement. */ }
    return <tr key={product.id} data-product-id={product.id} className="border-b border-slate-100 last:border-0 hover:bg-sky-50/40">
      <td className="px-1 py-1.5 text-center text-xs text-slate-500 tabular-nums">{rowNumber}</td>
      <td title={product.name} className="max-w-0 overflow-hidden text-ellipsis whitespace-nowrap px-2.5 py-1.5 font-semibold text-slate-700">{product.name}</td>
      <td title={unit ? formatRouteLoadQuantity(physical, unit) : undefined} className="max-w-0 overflow-hidden text-ellipsis whitespace-nowrap px-2 py-1.5 text-center tabular-nums">{unit ? formatRouteLoadQuantity(physical, unit) : t("dispatchRouteLoad.loading")}</td>
      <td className="relative min-w-0 px-1.5 py-1 text-center">
        <div className="flex min-w-0 items-start justify-center gap-1" dir={isArabic ? "rtl" : "ltr"}>
          {hasDisplay && <label className="flex min-w-0 flex-1 flex-col gap-0.5" title={unit?.display_uom_name ?? undefined}>
            <span className="truncate text-[10px] font-semibold text-slate-600">{unit?.display_uom_name}</span>
            <input id={`route-display-${product.id}`} type="text" inputMode="numeric"
              data-route-target-input="display" onKeyDown={onQuantityArrow}
              autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
              disabled={!unit || !canEdit} value={outerValue}
              aria-label={`${t("dispatchRouteLoad.target")} — ${product.name} — ${unit?.display_uom_name}`}
              aria-invalid={!!inputError} aria-describedby={inputError ? `route-error-${product.id}` : undefined}
              onFocus={(event) => event.currentTarget.select()}
              title={unit?.display_uom_name}
              onChange={(event) => editPart("display", event.target.value)}
              className="h-8 w-full min-w-0 rounded-md border border-slate-300 bg-white px-1 text-center text-xs tabular-nums outline-none focus:border-[#1e87bb] focus:ring-2 focus:ring-[#1e87bb]/15 disabled:bg-slate-100"
              dir="ltr" />
          </label>}
          <label className="flex min-w-0 flex-1 flex-col gap-0.5" title={unit?.base_uom_name}>
            <span className="truncate text-[10px] font-semibold text-slate-600">{unit?.base_uom_name ?? t("dispatchRouteLoad.loading")}</span>
            <input id={`route-base-${product.id}`} type="text" inputMode="decimal"
              data-route-target-input="base" onKeyDown={onQuantityArrow}
              autoComplete="off" autoCorrect="off" autoCapitalize="off" spellCheck={false}
              disabled={!unit || !canEdit} value={remainderValue}
              aria-label={`${t("dispatchRouteLoad.target")} — ${product.name} — ${unit?.base_uom_name ?? t("dispatchRouteLoad.loading")}`}
              aria-invalid={!!inputError} aria-describedby={inputError ? `route-error-${product.id}` : undefined}
              onFocus={(event) => event.currentTarget.select()}
              title={unit ? `${t("dispatchRouteLoad.baseInput")}: ${unit.base_uom_name}` : t("dispatchRouteLoad.loading")}
              onChange={(event) => editPart("base", event.target.value)}
              className="h-8 w-full min-w-0 rounded-md border border-slate-300 bg-white px-1 text-center text-xs tabular-nums outline-none focus:border-[#1e87bb] focus:ring-2 focus:ring-[#1e87bb]/15 disabled:bg-slate-100"
              dir="ltr" />
          </label>
        </div>
        {inputError && <span id={`route-error-${product.id}`} role="alert" title={errorLabel}
          className="block truncate text-[10px] font-semibold text-rose-700">{errorLabel}</span>}
      </td>
      <td title={unit && review ? formatRouteLoadQuantity(review.absoluteDelta, unit) : undefined} className="max-w-0 overflow-hidden text-ellipsis whitespace-nowrap px-2 py-1.5 text-center tabular-nums">{unit && review ? formatRouteLoadQuantity(review.absoluteDelta, unit) : t("dispatchRouteLoad.invalid")}</td>
      <td className="max-w-0 overflow-hidden text-ellipsis whitespace-nowrap px-2 py-1.5 text-center text-slate-600">{t(!review ? "dispatchRouteLoad.blocked" : review.direction === "ADD" ? "dispatchRouteLoad.add"
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
      <table className="w-full min-w-[820px] table-fixed text-sm">
        <colgroup>
          <col style={{ width: "5%" }} />
          <col style={{ width: "34%" }} />
          <col style={{ width: "19%" }} />
          <col style={{ width: "18%" }} />
          <col style={{ width: "14%" }} />
          <col style={{ width: "10%" }} />
        </colgroup>
        <thead><tr className="border-b border-slate-200 bg-slate-100/80 text-slate-600">
          <th scope="col" aria-label={t("dispatchProductSearch.rowNumber")} className="px-1 py-2 text-center text-xs tabular-nums">#</th>
          <th className="px-2.5 py-2 text-start">
            <div className="relative block w-full max-w-[370px]">
              <span className="sr-only">{t("dispatchProductSearch.search")}</span>
              <Search aria-hidden="true" className="pointer-events-none absolute end-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              {search && <button type="button" aria-label={t("dispatchProductSearch.clearSearch")}
                title={t("dispatchProductSearch.clearSearch")} disabled={!endpoint}
                onClick={(event) => { event.preventDefault(); setSearch(""); }}
                className="absolute end-9 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1e87bb]">
                <X aria-hidden="true" className="h-4 w-4" />
              </button>}
              <input type="text" aria-label={t("dispatchProductSearch.search")}
                placeholder={t("dispatchProductSearch.search")} maxLength={100}
                value={search} disabled={!endpoint} onChange={event => setSearch(event.target.value)}
                className={`h-9 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 outline-none placeholder:text-slate-400 focus:border-[#1e87bb] focus:ring-2 focus:ring-[#1e87bb]/15 disabled:bg-slate-100 ${search ? "pe-[4.5rem]" : "pe-9"}`} />
            </div>
          </th>
          <th className="px-3 py-3 text-center">{t("dispatchRouteLoad.current")}</th>
          <th className="px-3 py-3 text-center">{t("dispatchRouteLoad.target")}</th>
          <th className="px-3 py-3 text-center">{t("dispatchRouteLoad.difference")}</th>
          <th className="px-3 py-3 text-center">{t("dispatchRouteLoad.action")}</th>
        </tr></thead>
        {!firstRevealReady && contextSelected && !page.error && <tbody data-testid="dispatch-first-window-pending" aria-hidden="true"><tr><td colSpan={6} className="h-[72px] p-0"><div className="mx-3 h-8 rounded-lg bg-slate-50" /></td></tr></tbody>}
        {page.error && <tbody><tr><td colSpan={6} className="p-3 text-sm">
          <div role="alert" className="flex items-center gap-3 text-amber-800">
            <span>{t("dispatchProductSearch.error")}</span>
            <button type="button" onClick={page.retry} className="rounded-lg border border-amber-200 px-3 py-1.5 font-semibold">
              {t("common.retry")}
            </button>
          </div>
        </td></tr></tbody>}
        {firstRevealReady && !pinned.length && page.items.length === 0 && <tbody><tr><td colSpan={6} className="p-4 text-center text-sm text-slate-500">{t("dispatchProductSearch.empty")}</td></tr></tbody>}
        {firstRevealReady && !!pinned.length && <tbody>{pinned.map((product, index) => renderRow(product, index + 1))}</tbody>}
        {firstRevealReady && page.topSpacerHeight > 0 && <tbody aria-hidden="true"><tr><td colSpan={6} style={{ height: page.topSpacerHeight }} /></tr></tbody>}
        <tbody ref={topRef} data-window-boundary="top" aria-hidden="true"><tr><td colSpan={6} className="h-px p-0" /></tr></tbody>
        {firstRevealReady && numberedPages.map((windowPage) => (
          <MeasuredProductTableBody key={windowPage.index} index={windowPage.index} onMeasure={page.registerPageHeight}>
            {windowPage.items.map(({ product, rowNumber }) => renderRow(product, rowNumber))}
          </MeasuredProductTableBody>
        ))}
        <tbody ref={bottomRef} data-window-boundary="bottom" aria-hidden="true"><tr><td colSpan={6} className="h-px p-0" /></tr></tbody>
        {firstRevealReady && page.bottomSpacerHeight > 0 && <tbody aria-hidden="true"><tr><td colSpan={6} style={{ height: page.bottomSpacerHeight }} /></tr></tbody>}
      </table>
    </div>
    </section>
  </>;
}
