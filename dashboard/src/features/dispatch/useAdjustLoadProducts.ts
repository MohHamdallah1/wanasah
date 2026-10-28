import { useEffect, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { adjustmentError, parseAdjustLoadInventory, type AdjustLoadItem } from "./adjustLoad";

export const ADJUST_LOAD_SEARCH_LIMIT = 80;
export const hasAdjustmentDraft = (value: string) => value !== "" && !/^-?0(?:\.0+)?$/.test(value);
const draftIds = (drafts: Record<string, string>) => Object.keys(drafts).filter((id) => hasAdjustmentDraft(drafts[id]));

/** The window contains current custody, explicit drafts, and at most one search page. */
export function useAdjustLoadProducts(routeId: string | undefined, search: string, drafts: Record<string, string>, scope: string | null) {
  const authFetch = useAuthFetch();
  const [items, setItems] = useState<AdjustLoadItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<unknown>(null);
  const [resultCount, setResultCount] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const windowScope = routeId ? `${scope}:${routeId}` : null;
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
      for (let offset = 0; offset < missing.length; offset += ADJUST_LOAD_SEARCH_LIMIT) {
        const batch = missing.slice(offset, offset + ADJUST_LOAD_SEARCH_LIMIT);
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

  useEffect(() => {
    const controller = new AbortController();
    setSearchError(null); setResultCount(0); setSearching(false);
    setItems((current) => {
      const keep = new Set([...loadedIds.current, ...draftIds(draftsRef.current)]);
      return current.filter((item) => keep.has(item.product_id));
    });
    const query = search.trim();
    if (!routeId || loading || error || query.length < 2 || query.length > 100) return;
    setSearching(true);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ search: query, limit: String(ADJUST_LOAD_SEARCH_LIMIT) });
      void authFetch(`/dispatch/route/${routeId}/live_inventory?${params}`, { signal: controller.signal })
        .then((raw) => {
          if (controller.signal.aborted) return;
          if (!Array.isArray(raw) || raw.length > ADJUST_LOAD_SEARCH_LIMIT) throw adjustmentError();
          const results = parseAdjustLoadInventory(raw);
          setResultCount(results.length);
          setItems((current) => {
            const keep = new Set([...loadedIds.current, ...draftIds(draftsRef.current)]);
            const pinned = current.filter((item) => keep.has(item.product_id));
            const pinnedIds = new Set(pinned.map((item) => item.product_id));
            return [...pinned, ...results.filter((item) => !pinnedIds.has(item.product_id))];
          });
        }).catch((failure) => { if (!controller.signal.aborted) setSearchError(failure); })
        .finally(() => { if (!controller.signal.aborted) setSearching(false); });
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [authFetch, routeId, windowScope, search, loading, error]);

  return { items: loadedScope === windowScope ? items : [], loading: loading || loadedScope !== windowScope,
    error: loadedScope === windowScope ? error : null, searching,
    searchError: loadedScope === windowScope ? searchError : null, resultCount, retry: () => setRevision((value) => value + 1) };
}
