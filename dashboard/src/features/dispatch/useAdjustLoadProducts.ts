import { useEffect, useMemo, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { adjustmentError, parseAdjustLoadInventory, type AdjustLoadItem } from "./adjustLoad";
import { DISPATCH_PRODUCT_PAGE_SIZE } from "./useDispatchProductSearch";
import { useDispatchProductWindow } from "./useDispatchProductWindow";

export const ADJUST_LOAD_HYDRATION_BATCH_SIZE = DISPATCH_PRODUCT_PAGE_SIZE;
export const hasAdjustmentDraft = (value: string) => value !== "" && !/^-?0(?:\.0+)?$/.test(value);
const draftIds = (drafts: Record<string, string>) => Object.keys(drafts).filter((id) => hasAdjustmentDraft(drafts[id]));

/** Current custody and explicit drafts stay pinned; discovery data is a bounded three-page window. */
export function useAdjustLoadProducts(
  routeId: string | undefined,
  search: string,
  drafts: Record<string, string>,
  scope: string | null,
  context = "",
  discoveryEnabled = true,
) {
  const authFetch = useAuthFetch();
  const [pinnedItems, setPinnedItems] = useState<AdjustLoadItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const windowScope = routeId ? `${scope}:${routeId}:${context}` : null;
  const loadedIds = useRef(new Set<string>());
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;

  useEffect(() => {
    setPinnedItems([]);
    setError(null);
    setLoading(!!routeId);
    setLoadedScope(windowScope);
    loadedIds.current = new Set();
    if (!routeId) return;
    const controller = new AbortController();
    const read = async () => {
      const endpoint = `/dispatch/route/${routeId}/live_inventory`;
      const initial = parseAdjustLoadInventory(await authFetch(endpoint, { signal: controller.signal }));
      if (controller.signal.aborted) return;
      loadedIds.current = new Set(initial.map((item) => item.product_id));
      setPinnedItems(initial);
      const missing = draftIds(draftsRef.current).filter((id) => !loadedIds.current.has(id));
      for (let offset = 0; offset < missing.length; offset += ADJUST_LOAD_HYDRATION_BATCH_SIZE) {
        const batch = missing.slice(offset, offset + ADJUST_LOAD_HYDRATION_BATCH_SIZE);
        const params = new URLSearchParams();
        batch.forEach((id) => params.append("product_ids", id));
        const rows = parseAdjustLoadInventory(await authFetch(`${endpoint}?${params}`, { signal: controller.signal }));
        if (controller.signal.aborted) return;
        if (rows.length > batch.length || batch.some((id) => !rows.some((item) => item.product_id === id))) throw adjustmentError();
        setPinnedItems((current) => [...current, ...rows.filter((row) => !current.some((item) => item.product_id === row.product_id))]);
      }
    };
    void read().catch((failure) => { if (!controller.signal.aborted) setError(failure); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [authFetch, routeId, windowScope, revision]);

  const page = useDispatchProductWindow(
    discoveryEnabled && routeId && loadedScope === windowScope && !loading && !error
      ? `/dispatch/route/${routeId}/live_inventory`
      : null,
    search,
    scope ? `${scope}:${context}` : null,
  );

  const discoveredItems = useMemo(
    () => page.items.map((item) => item.load!).filter(Boolean),
    [page.items],
  );

  useEffect(() => {
    const keep = new Set([...loadedIds.current, ...draftIds(drafts)]);
    setPinnedItems((current) => {
      const byId = new Map(current.filter((item) => keep.has(item.product_id)).map((item) => [item.product_id, item]));
      discoveredItems.forEach((item) => {
        if (keep.has(item.product_id)) byId.set(item.product_id, item);
      });
      return Array.from(byId.values());
    });
  }, [discoveredItems, drafts]);

  // Restoring a saved draft is asynchronous to the initial custody read.
  // The initial read can finish before the saved IDs become available; hydrate
  // those IDs on demand without reloading the whole catalog or losing the edit.
  const draftedIds = draftIds(drafts).sort().join(",");
  useEffect(() => {
    if (!routeId || loadedScope !== windowScope || loading || error || !draftedIds) return;
    const missing = draftedIds.split(",").filter((id) =>
      !loadedIds.current.has(id) && !pinnedItems.some((row) => row.product_id === id) &&
      !discoveredItems.some((row) => row.product_id === id));
    if (!missing.length) return;
    const controller = new AbortController();
    const hydrate = async () => {
      const endpoint = `/dispatch/route/${routeId}/live_inventory`;
      const collected: AdjustLoadItem[] = [];
      for (let offset = 0; offset < missing.length; offset += ADJUST_LOAD_HYDRATION_BATCH_SIZE) {
        const batch = missing.slice(offset, offset + ADJUST_LOAD_HYDRATION_BATCH_SIZE);
        const params = new URLSearchParams();
        batch.forEach((id) => params.append("product_ids", id));
        const rows = parseAdjustLoadInventory(await authFetch(`${endpoint}?${params}`, { signal: controller.signal }));
        if (controller.signal.aborted) return;
        if (rows.length !== batch.length || batch.some((id) => !rows.some((item) => item.product_id === id)))
          throw adjustmentError();
        collected.push(...rows);
      }
      if (!controller.signal.aborted) {
        setPinnedItems((current) => {
          const present = new Set(current.map((row) => row.product_id));
          return [...current, ...collected.filter((row) => !present.has(row.product_id))];
        });
      }
    };
    void hydrate().catch((failure) => { if (!controller.signal.aborted) setError(failure); });
    return () => controller.abort();
    // Re-evaluate on draft identity, scope or initial load; not on every keypress,
    // so loading 500 products remains cursor-bounded.
  }, [authFetch, routeId, loadedScope, windowScope, loading, error, draftedIds, pinnedItems, discoveredItems]);

  const pinnedIds = useMemo(() => new Set(pinnedItems.map((item) => item.product_id)), [pinnedItems]);
  const windowItems = useMemo(
    () => discoveredItems.filter((item) => !pinnedIds.has(item.product_id)),
    [discoveredItems, pinnedIds],
  );
  const items = useMemo(() => [...pinnedItems, ...windowItems], [pinnedItems, windowItems]);

  return {
    items: loadedScope === windowScope ? items : [],
    pinnedItems: loadedScope === windowScope ? pinnedItems : [],
    windowItems: loadedScope === windowScope ? windowItems : [],
    loading: loading || loadedScope !== windowScope,
    error: loadedScope === windowScope ? error : null,
    page,
    retry: () => setRevision((value) => value + 1),
  };
}
