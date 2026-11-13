import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useDashboardSession } from "@/hooks/useDashboardSession";
import {
  DISPATCH_PRODUCT_PAGE_SIZE,
  parseDispatchProductPage,
  type DispatchDiscoveryProduct,
} from "./useDispatchProductSearch";
import { adjustmentError } from "./adjustLoad";

export const DISPATCH_PRODUCT_WINDOW_PAGE_COUNT = 3;

export interface DispatchProductWindowPage {
  index: number;
  items: DispatchDiscoveryProduct[];
}

interface StoredWindowPage extends DispatchProductWindowPage {
  cursor: string | null;
  nextCursor: string | null;
  hasMore: boolean;
}

interface WindowState {
  key: string;
  pages: StoredWindowPage[];
  heights: Record<number, number>;
  maxVisited: number;
  initialReady: boolean;
  fetchedAt: number;
}

type LoadDirection = "next" | "previous";

const emptyState = (key: string): WindowState => ({
  key, pages: [], heights: {}, maxVisited: 0, initialReady: false, fetchedAt: 0,
});

// A small, session-generation-fenced in-memory snapshot (not localStorage).
// Retains at most 8 windowed queries (<=3 pages each), never the entire catalog.
const warmWindows = new Map<string, WindowState>();
const MAX_WARM_WINDOWS = 8;
const WARM_TTL_MS = 5 * 60_000;
const FRESH_WINDOW_MS = 60_000;
function readWarmWindow(key: string | null): WindowState | null {
  if (!key) return null;
  const data = warmWindows.get(key);
  if (!data) return null;
  if (Date.now() - data.fetchedAt > WARM_TTL_MS) {
    warmWindows.delete(key);
    return null;
  }
  warmWindows.delete(key);
  warmWindows.set(key, data);
  return data;
}
function rememberWarmWindow(key: string | null, state: WindowState): void {
  if (!key || !state.initialReady || !state.fetchedAt) return;
  warmWindows.delete(key);
  warmWindows.set(key, state);
  while (warmWindows.size > MAX_WARM_WINDOWS) {
    const oldest = warmWindows.keys().next().value;
    if (oldest === undefined) break;
    warmWindows.delete(oldest);
  }
}

export function useDispatchProductWindow(
  endpoint: string | null,
  search: string,
  scope: string | null,
  purpose: "LOAD" | "SHORTAGE" = "LOAD",
) {
  const authFetch = useAuthFetch();
  const session = useDashboardSession();
  const query = search.trim();
  const key = JSON.stringify([session?.generation, session?.identity, scope, endpoint, query, purpose]);
  // Never share a signed discovery window across a login generation, actor,
  // warehouse, vehicle or search context. Shortage mode keeps its old behavior.
  const warmKey = purpose === "LOAD" && session && scope && endpoint ? key : null;
  const valid = !!endpoint && !!scope && !(purpose === "SHORTAGE" && query.length < 2) && query.length <= 100;
  const [state, setState] = useState<WindowState>(() => readWarmWindow(warmKey) ?? emptyState(""));
  const [loading, setLoading] = useState(false);
  const [loadingWindow, setLoadingWindow] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);
  const cursorHistory = useRef<(string | null)[]>([null]);
  const controllerRef = useRef<AbortController | null>(null);
  const loadingWindowRef = useRef(false);
  const keyRef = useRef(key);
  const failedRef = useRef<{ index: number; cursor: string | null; direction: LoadDirection } | null>(null);
  keyRef.current = key;

  const active = state.key === key ? state : emptyState(key);

  const requestUrl = useCallback((cursor: string | null) => {
    if (!endpoint) return "";
    const params = new URLSearchParams({ search: query, limit: String(DISPATCH_PRODUCT_PAGE_SIZE) });
    if (cursor) params.set("cursor", cursor);
    return `${endpoint}${endpoint.includes("?") ? "&" : "?"}${params}`;
  }, [endpoint, query]);

  const fetchPage = useCallback(async (index: number, cursor: string | null, signal: AbortSignal): Promise<StoredWindowPage> => {
    const result = parseDispatchProductPage(await authFetch(requestUrl(cursor), { signal }), purpose);
    if (result.has_more && result.next_cursor === cursor) throw adjustmentError();
    return { index, cursor, items: result.items, nextCursor: result.next_cursor, hasMore: result.has_more };
  }, [authFetch, purpose, requestUrl]);

  // Browsing another Dashboard page or dispatch tab must not lose the first
  // signed 80-row window; visibility/readiness is still enforced by the caller.
  useEffect(() => {
    const revoke = () => warmWindows.clear();
    window.addEventListener("inventory-permission-denied", revoke);
    window.addEventListener("dashboard-session-changed", revoke);
    return () => {
      window.removeEventListener("inventory-permission-denied", revoke);
      window.removeEventListener("dashboard-session-changed", revoke);
    };
  }, []);
  useEffect(() => {
    if (state.key === key) rememberWarmWindow(warmKey, state);
  }, [key, state, warmKey]);
  useEffect(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const cached = readWarmWindow(warmKey);
    cursorHistory.current = [null];
    if (cached) for (const page of cached.pages) {
      if (page.nextCursor) cursorHistory.current[page.index + 1] = page.nextCursor;
      cursorHistory.current[page.index] = page.cursor;
    }
    loadingWindowRef.current = false;
    failedRef.current = null;
    setState(cached ?? emptyState(key));
    setError(null);
    setLoadingWindow(false);
    if (!valid) {
      setLoading(false);
      return () => controller.abort();
    }
    // One-minute fresh signed presentation needs no identical second GET.
    // An older warm window stays painted while background readback revalidates.
    if (cached && Date.now() - cached.fetchedAt < FRESH_WINDOW_MS && revision === 0) {
      setLoading(false);
      return () => controller.abort();
    }
    // During stale-while-revalidate, keep rows painted but disable edits until readback.
    setLoading(!cached || Date.now() - cached.fetchedAt >= FRESH_WINDOW_MS);
    const timer = setTimeout(() => {
      void fetchPage(0, null, controller.signal)
        .then((page) => {
          if (controller.signal.aborted || keyRef.current !== key) return;
          if (page.hasMore && page.nextCursor) cursorHistory.current[1] = page.nextCursor;
          setState({ key, pages: [page], heights: {}, maxVisited: 0, initialReady: true, fetchedAt: Date.now() });
        })
        .catch((failure) => {
          if (!controller.signal.aborted && keyRef.current === key) {
            if (warmKey) warmWindows.delete(warmKey);
            setState(emptyState(key));
            setError(failure);
          }
        })
        .finally(() => {
          if (!controller.signal.aborted && keyRef.current === key) setLoading(false);
        });
    }, query ? 300 : 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [fetchPage, key, query, revision, valid, warmKey]);

  const loadWindowPage = useCallback(async (index: number, cursor: string | null, direction: LoadDirection) => {
    const controller = controllerRef.current;
    if (!controller || controller.signal.aborted || loadingWindowRef.current || keyRef.current !== key) return;
    loadingWindowRef.current = true;
    setLoadingWindow(true);
    setError(null);
    failedRef.current = null;
    try {
      const page = await fetchPage(index, cursor, controller.signal);
      if (controller.signal.aborted || keyRef.current !== key) return;
      if (page.hasMore && page.nextCursor) cursorHistory.current[index + 1] = page.nextCursor;
      setState((current) => {
        if (current.key !== key) return current;
        const without = current.pages.filter((entry) => entry.index !== index);
        let pages = [...without, page].sort((a, b) => a.index - b.index);
        if (pages.length > DISPATCH_PRODUCT_WINDOW_PAGE_COUNT) {
          pages = direction === "next"
            ? pages.slice(pages.length - DISPATCH_PRODUCT_WINDOW_PAGE_COUNT)
            : pages.slice(0, DISPATCH_PRODUCT_WINDOW_PAGE_COUNT);
        }
        return { ...current, pages, maxVisited: Math.max(current.maxVisited, index) };
      });
    } catch (failure) {
      if (!controller.signal.aborted && keyRef.current === key) {
        failedRef.current = { index, cursor, direction };
        setError(failure);
      }
    } finally {
      loadingWindowRef.current = false;
      if (!controller.signal.aborted && keyRef.current === key) setLoadingWindow(false);
    }
  }, [fetchPage, key]);

  const firstPage = active.pages[0];
  const lastPage = active.pages[active.pages.length - 1];
  const hasPrevious = !!firstPage && firstPage.index > 0;
  const hasMore = !!lastPage && (lastPage.index < active.maxVisited || lastPage.hasMore);

  const loadPrevious = useCallback(() => {
    if (!hasPrevious || !firstPage || loading || loadingWindowRef.current) return;
    const index = firstPage.index - 1;
    const cursor = cursorHistory.current[index];
    if (cursor === undefined) return;
    void loadWindowPage(index, cursor, "previous");
  }, [firstPage, hasPrevious, loadWindowPage, loading]);

  const loadMore = useCallback(() => {
    if (!hasMore || !lastPage || loading || loadingWindowRef.current) return;
    const index = lastPage.index + 1;
    const cursor = cursorHistory.current[index] ?? lastPage.nextCursor;
    if (!cursor) return;
    cursorHistory.current[index] = cursor;
    void loadWindowPage(index, cursor, "next");
  }, [hasMore, lastPage, loadWindowPage, loading]);

  const registerPageHeight = useCallback((index: number, height: number) => {
    if (!Number.isFinite(height) || height <= 0) return;
    setState((current) => {
      if (current.key !== key || current.heights[index] === height) return current;
      return { ...current, heights: { ...current.heights, [index]: height } };
    });
  }, [key]);

  const firstIndex = firstPage?.index ?? 0;
  const lastIndex = lastPage?.index ?? -1;
  const topSpacerHeight = useMemo(() => {
    let total = 0;
    for (let index = 0; index < firstIndex; index += 1) total += active.heights[index] || 0;
    return total;
  }, [active.heights, firstIndex]);
  const bottomSpacerHeight = useMemo(() => {
    let total = 0;
    for (let index = lastIndex + 1; index <= active.maxVisited; index += 1) total += active.heights[index] || 0;
    return total;
  }, [active.heights, active.maxVisited, lastIndex]);

  const items = useMemo(() => active.pages.flatMap((page) => page.items), [active.pages]);
  // An empty but completed signed first page is READY; pending, denied,
  // failed or a previous actor/vehicle/warehouse/search key is not.
  const firstPageReady = valid && active.initialReady && !error;

  const retry = useCallback(() => {
    const failed = failedRef.current;
    if (failed) {
      void loadWindowPage(failed.index, failed.cursor, failed.direction);
      return;
    }
    setRevision((value) => value + 1);
  }, [loadWindowPage]);

  return {
    mode: "windowed" as const,
    queryKey: key,
    firstPageReady,
    pages: active.pages.map(({ index, items: pageItems }) => ({ index, items: pageItems })),
    items,
    loading,
    loadingWindow,
    error,
    searchRequired: purpose === "SHORTAGE",
    hasMore,
    hasPrevious,
    loadMore,
    loadPrevious,
    registerPageHeight,
    topSpacerHeight,
    bottomSpacerHeight,
    retry,
  };
}
