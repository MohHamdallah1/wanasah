import { useEffect, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { adjustmentError, parseAdjustLoadInventory, type AdjustLoadItem } from "./adjustLoad";

export const DISPATCH_PRODUCT_PAGE_SIZE = 80;
export interface DispatchDiscoveryProduct { id: string; name: string; load: AdjustLoadItem | null }
interface ProductPage { items: DispatchDiscoveryProduct[]; next_cursor: string | null; has_more: boolean }
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

/** Only the current page is retained; earlier selections belong to the caller's pins. */
export function useDispatchProductSearch(endpoint: string | null, search: string, scope: string | null, purpose: "LOAD" | "SHORTAGE" = "LOAD") {
  const authFetch = useAuthFetch();
  const query = search.trim();
  const key = JSON.stringify([scope, endpoint, query, purpose]);
  const [navigation, setNavigation] = useState<{ key: string; cursors: (string | null)[]; index: number }>({ key: "", cursors: [null], index: 0 });
  const active = navigation.key === key ? navigation : { key, cursors: [null], index: 0 };
  const cursor = active.cursors[active.index];
  const [window, setWindow] = useState<{ key: string; cursor: string | null; page: ProductPage }>({ key: "", cursor: null, page: emptyPage });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);
  const page = window.key === key && window.cursor === cursor ? window.page : emptyPage;
  useEffect(() => {
    const controller = new AbortController();
    setError(null); setLoading(false);
    if (!endpoint || !scope || query.length < 2 || query.length > 100) return;
    setLoading(true);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ search: query, limit: String(DISPATCH_PRODUCT_PAGE_SIZE) });
      if (cursor) params.set("cursor", cursor);
      void authFetch(`${endpoint}${endpoint.includes("?") ? "&" : "?"}${params}`, { signal: controller.signal })
        .then((raw) => {
          if (controller.signal.aborted) return;
          const result = parseDispatchProductPage(raw, purpose);
          if (result.has_more && result.next_cursor === cursor) throw adjustmentError();
          setWindow({ key, cursor, page: result });
        }).catch((failure) => { if (!controller.signal.aborted) setError(failure); })
        .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, cursor ? 0 : 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [authFetch, endpoint, scope, key, query, cursor, purpose, revision]);
  return { items: page.items, loading, error, hasMore: page.has_more, hasPrevious: active.index > 0,
    pageNumber: active.index + 1,
    loadMore: () => { if (!loading && page.next_cursor) setNavigation({ key, cursors: [...active.cursors.slice(0, active.index + 1), page.next_cursor], index: active.index + 1 }); },
    previous: () => { if (!loading && active.index > 0) setNavigation({ ...active, index: active.index - 1 }); },
    retry: () => { setNavigation({ key, cursors: [null], index: 0 }); setRevision((value) => value + 1); },
  };
}
