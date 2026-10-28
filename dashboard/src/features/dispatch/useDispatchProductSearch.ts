import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { adjustmentError, parseAdjustLoadInventory, type AdjustLoadItem } from "./adjustLoad";

export const DISPATCH_PRODUCT_PAGE_SIZE = 80;
export interface DispatchDiscoveryProduct { id: string; name: string; load: AdjustLoadItem | null }
interface ProductPage { items: DispatchDiscoveryProduct[]; next_cursor: string | null; has_more: boolean }
interface ProductWindow { key: string; items: DispatchDiscoveryProduct[]; nextCursor: string | null; hasMore: boolean }
const emptyPage: ProductPage = { items: [], next_cursor: null, has_more: false };

export function parseDispatchProductPage(raw: unknown, purpose: "LOAD" | "SHORTAGE" = "LOAD"): ProductPage {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw adjustmentError();
  const page = raw as Record<string, unknown>;
  if (!Array.isArray(page.items) || page.items.length > DISPATCH_PRODUCT_PAGE_SIZE || typeof page.has_more !== "boolean" ||
      (page.has_more ? typeof page.next_cursor !== "string" || !page.next_cursor || !page.items.length : page.next_cursor !== null)) throw adjustmentError();
  const seen = new Set<string>();
  const items = page.items.map((rawItem: unknown) => {
    if (!rawItem || typeof rawItem !== "object") throw adjustmentError();
    const item = rawItem as Record<string, unknown>;
    if (typeof item.id !== "string" || !/^[1-9]\d*$/.test(item.id) || !Number.isSafeInteger(Number(item.id)) ||
        typeof item.name !== "string" || !item.name || seen.has(item.id)) throw adjustmentError();
    seen.add(item.id);
    const load = item.load == null ? null : parseAdjustLoadInventory([item.load])[0];
    if (purpose === "LOAD" && !load) throw adjustmentError();
    if (load && (load.product_id !== item.id || load.product_name !== item.name)) throw adjustmentError();
    return { id: item.id, name: item.name, load };
  });
  return { items, has_more: page.has_more, next_cursor: page.next_cursor as string | null };
}

export function useDispatchProductSearch(endpoint: string | null, search: string, scope: string | null, purpose: "LOAD" | "SHORTAGE" = "LOAD") {
  const authFetch = useAuthFetch();
  const query = search.trim();
  const key = JSON.stringify([scope, endpoint, query, purpose]);
  const [window, setWindow] = useState<ProductWindow>({ key: "", items: [], nextCursor: null, hasMore: false });
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);
  const keyRef = useRef(key);
  const loadingMoreRef = useRef(false);
  keyRef.current = key;
  const active = window.key === key ? window : { key, items: [], nextCursor: null, hasMore: false };
  const valid = !!endpoint && !!scope && !(purpose === "SHORTAGE" && query.length < 2) && query.length <= 100;

  const requestUrl = useCallback((cursor: string | null) => {
    if (!endpoint) return "";
    const params = new URLSearchParams({ search: query, limit: String(DISPATCH_PRODUCT_PAGE_SIZE) });
    if (cursor) params.set("cursor", cursor);
    return `${endpoint}${endpoint.includes("?") ? "&" : "?"}${params}`;
  }, [endpoint, query]);

  useEffect(() => {
    const controller = new AbortController();
    setWindow({ key, items: [], nextCursor: null, hasMore: false });
    setError(null);
    loadingMoreRef.current = false;
    setLoadingMore(false);
    if (!valid) { setLoading(false); return () => controller.abort(); }
    setLoading(true);
    const timer = setTimeout(() => {
      void authFetch(requestUrl(null), { signal: controller.signal })
        .then((raw) => {
          if (controller.signal.aborted) return;
          const result = parseDispatchProductPage(raw, purpose);
          setWindow({ key, items: result.items, nextCursor: result.next_cursor, hasMore: result.has_more });
        })
        .catch((failure) => { if (!controller.signal.aborted) setError(failure); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, query ? 300 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [authFetch, key, purpose, query, requestUrl, revision, valid]);

  const loadMore = useCallback(() => {
    if (!valid || loading || loadingMoreRef.current || !active.hasMore || !active.nextCursor) return;
    const expectedKey = key;
    const cursor = active.nextCursor;
    const existingIds = new Set(active.items.map((item) => item.id));
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setError(null);
    void authFetch(requestUrl(cursor))
      .then((raw) => {
        const result = parseDispatchProductPage(raw, purpose);
        if (result.items.some((item) => existingIds.has(item.id))) throw adjustmentError();
        setWindow((current) => current.key !== expectedKey ? current : {
          key: expectedKey,
          items: [...current.items, ...result.items],
          nextCursor: result.next_cursor,
          hasMore: result.has_more,
        });
      })
      .catch((failure) => { if (keyRef.current === expectedKey) setError(failure); })
      .finally(() => {
        loadingMoreRef.current = false;
        if (keyRef.current === expectedKey) setLoadingMore(false);
      });
  }, [active.hasMore, active.items, active.nextCursor, authFetch, key, loading, purpose, requestUrl, valid]);

  return {
    items: active.items,
    loading,
    loadingMore,
    error,
    searchRequired: purpose === "SHORTAGE",
    hasMore: active.hasMore,
    loadMore,
    retry: () => setRevision((value) => value + 1),
  };
}
