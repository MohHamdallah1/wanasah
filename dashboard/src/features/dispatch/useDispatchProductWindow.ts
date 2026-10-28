import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
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
}

type LoadDirection = "next" | "previous";

const emptyState = (key: string): WindowState => ({ key, pages: [], heights: {}, maxVisited: 0 });

export function useDispatchProductWindow(
  endpoint: string | null,
  search: string,
  scope: string | null,
  purpose: "LOAD" | "SHORTAGE" = "LOAD",
) {
  const authFetch = useAuthFetch();
  const query = search.trim();
  const key = JSON.stringify([scope, endpoint, query, purpose]);
  const valid = !!endpoint && !!scope && !(purpose === "SHORTAGE" && query.length < 2) && query.length <= 100;
  const [state, setState] = useState<WindowState>(() => emptyState(""));
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

  useEffect(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    cursorHistory.current = [null];
    loadingWindowRef.current = false;
    failedRef.current = null;
    setState(emptyState(key));
    setError(null);
    setLoadingWindow(false);
    if (!valid) {
      setLoading(false);
      return () => controller.abort();
    }
    setLoading(true);
    const timer = setTimeout(() => {
      void fetchPage(0, null, controller.signal)
        .then((page) => {
          if (controller.signal.aborted || keyRef.current !== key) return;
          if (page.hasMore && page.nextCursor) cursorHistory.current[1] = page.nextCursor;
          setState({ key, pages: [page], heights: {}, maxVisited: 0 });
        })
        .catch((failure) => {
          if (!controller.signal.aborted && keyRef.current === key) setError(failure);
        })
        .finally(() => {
          if (!controller.signal.aborted && keyRef.current === key) setLoading(false);
        });
    }, query ? 300 : 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [fetchPage, key, query, revision, valid]);

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
