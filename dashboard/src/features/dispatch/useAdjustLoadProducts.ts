import { useEffect, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { adjustmentError, parseAdjustLoadInventory, type AdjustLoadItem } from "./adjustLoad";

import { DISPATCH_PRODUCT_PAGE_SIZE, useDispatchProductSearch } from "./useDispatchProductSearch";

export const ADJUST_LOAD_HYDRATION_BATCH_SIZE = DISPATCH_PRODUCT_PAGE_SIZE;
export const hasAdjustmentDraft = (value: string) => value !== "" && !/^-?0(?:\.0+)?$/.test(value);
const draftIds = (drafts: Record<string, string>) => Object.keys(drafts).filter((id) => hasAdjustmentDraft(drafts[id]));

/** The window contains current custody, explicit drafts, and at most one search page. */
export function useAdjustLoadProducts(routeId: string | undefined, search: string, drafts: Record<string, string>, scope: string | null, context = "", discoveryEnabled = true) {
  const authFetch = useAuthFetch();
  const [items, setItems] = useState<AdjustLoadItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const windowScope = routeId ? `${scope}:${routeId}:${context}` : null;
  const loadedIds = useRef(new Set<string>());
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;

  useEffect(() => {
    setItems([]); setError(null); setLoading(!!routeId); setLoadedScope(windowScope); loadedIds.current = new Set();
    if (!routeId) return;
    const controller = new AbortController();
    const read = async () => {
      const endpoint = `/dispatch/route/${routeId}/live_inventory`;
      const initial = parseAdjustLoadInventory(await authFetch(endpoint, { signal: controller.signal }));
      if (controller.signal.aborted) return;
      loadedIds.current = new Set(initial.map((item) => item.product_id));
      setItems(initial); // Show physical custody before hydrating any saved new-product drafts.
      const missing = draftIds(draftsRef.current).filter((id) => !loadedIds.current.has(id));
      for (let offset = 0; offset < missing.length; offset += ADJUST_LOAD_HYDRATION_BATCH_SIZE) {
        const batch = missing.slice(offset, offset + ADJUST_LOAD_HYDRATION_BATCH_SIZE);
        const params = new URLSearchParams();
        batch.forEach((id) => params.append("product_ids", id));
        const rows = parseAdjustLoadInventory(await authFetch(`${endpoint}?${params}`, { signal: controller.signal }));
        if (controller.signal.aborted) return;
        if (rows.length > batch.length || batch.some((id) => !rows.some((item) => item.product_id === id))) throw adjustmentError();
        setItems((current) => [...current, ...rows.filter((row) => !current.some((item) => item.product_id === row.product_id))]);
      }
    };
    void read().catch((failure) => { if (!controller.signal.aborted) setError(failure); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [authFetch, routeId, windowScope, revision]);

  const page = useDispatchProductSearch(discoveryEnabled && routeId && loadedScope === windowScope && !loading && !error ? `/dispatch/route/${routeId}/live_inventory` : null, search, scope ? `${scope}:${context}` : null);
  useEffect(() => {
    setItems((current) => {
      const keep = new Set([...loadedIds.current, ...draftIds(draftsRef.current)]);
      const pinned = current.filter((item) => keep.has(item.product_id));
      const pinnedIds = new Set(pinned.map((item) => item.product_id));
      return [...pinned, ...page.items.map((item) => item.load!).filter((item) => !pinnedIds.has(item.product_id))];
    });
  }, [page.items]);

  return { items: loadedScope === windowScope ? items : [], loading: loading || loadedScope !== windowScope,
    error: loadedScope === windowScope ? error : null, page, retry: () => setRevision((value) => value + 1) };
}
