import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseSourceInventoryPage } from "../parsers";
import type { TransferSourceInventoryItem, TransferSourceInventoryPage } from "../types";
import type { TransferWarehouse } from "../draftStorage";
import { compareQuantity } from "../../quantity";
import { useTransferWarehouses } from "./useTransferWarehouses";

const PAGE_SIZE = 50;
const WINDOW_PAGE_COUNT = 3;

type WindowPage = {
  index: number;
  cursor: string | null;
  items: TransferSourceInventoryItem[];
  nextCursor: string | null;
  hasMore: boolean;
};

type ProductState = {
  key: string;
  pages: WindowPage[];
  heights: Record<number, number>;
  maxVisited: number;
  total: number | null;
};

const emptyState = (key: string): ProductState => ({
  key,
  pages: [],
  heights: {},
  maxVisited: 0,
  total: null,
});

export function useTransferQueries(open: boolean, source: TransferWarehouse | null, destination: TransferWarehouse | null) {
  const fetch = useAuthFetch();
  const sources = useTransferWarehouses(open, "source", source);
  const destinations = useTransferWarehouses(open, "destination", destination);
  const ready = sources.valid && destinations.valid && source?.id !== destination?.id;
  const [productSearchInput, setProductSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<ProductState>(() => emptyState(""));
  const [loading, setLoading] = useState(false);
  const [loadingWindow, setLoadingWindow] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const cursorHistory = useRef<(string | null)[]>([null]);
  const controllerRef = useRef<AbortController | null>(null);
  const loadingWindowRef = useRef(false);
  const key = JSON.stringify([open, ready, source?.id, destination?.id, query, revision]);
  const keyRef = useRef(key);
  keyRef.current = key;

  useEffect(() => {
    const timer = setTimeout(() => {
      const clean = productSearchInput.trim();
      setQuery(clean.length >= 2 ? clean : "");
    }, 300);
    return () => clearTimeout(timer);
  }, [productSearchInput]);

  const resetProductSearch = useCallback(() => {
    setProductSearchInput("");
    setQuery("");
  }, []);

  const readSourcePage = useCallback(async (search: string, cursor: string | null, signal?: AbortSignal): Promise<TransferSourceInventoryPage> => {
    if (!source || !destination || !ready) throw new Error("TRANSFER_SOURCE_NOT_READY");
    const params = new URLSearchParams({
      location_id: String(source.id),
      destination_location_id: String(destination.id),
      transfer_purpose: "WAREHOUSE_BALANCING",
      limit: String(PAGE_SIZE),
    });
    if (search.length >= 2) params.set("search", search);
    if (cursor) params.set("cursor", cursor);
    return parseSourceInventoryPage(await fetch(`/warehouse/unified/transfer/source-inventory?${params}`, { signal }));
  }, [destination, fetch, ready, source]);

  useEffect(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    cursorHistory.current = [null];
    loadingWindowRef.current = false;
    setLoadingWindow(false);
    setError(null);
    setState(emptyState(key));
    if (!open || !ready) {
      setLoading(false);
      return () => controller.abort();
    }
    setLoading(true);
    void readSourcePage(query, null, controller.signal)
      .then((page) => {
        if (controller.signal.aborted || keyRef.current !== key) return;
        const items = page.items.filter((item) => compareQuantity(item.available_quantity, "0") > 0);
        if (page.has_more && page.next_cursor) cursorHistory.current[1] = page.next_cursor;
        setState({
          key,
          pages: [{ index: 0, cursor: null, items, nextCursor: page.next_cursor, hasMore: page.has_more }],
          heights: {},
          maxVisited: 0,
          total: page.total,
        });
      })
      .catch((failure) => {
        if (!controller.signal.aborted && keyRef.current === key) setError(failure);
      })
      .finally(() => {
        if (!controller.signal.aborted && keyRef.current === key) setLoading(false);
      });
    return () => controller.abort();
  }, [key, open, query, readSourcePage, ready]);

  const active = state.key === key ? state : emptyState(key);
  const firstPage = active.pages[0];
  const lastPage = active.pages[active.pages.length - 1];
  const hasPrevious = Boolean(firstPage && firstPage.index > 0);
  const hasMore = Boolean(lastPage && (lastPage.index < active.maxVisited || lastPage.hasMore));

  const loadWindowPage = useCallback(async (index: number, cursor: string | null, direction: "next" | "previous") => {
    const controller = controllerRef.current;
    if (!controller || controller.signal.aborted || loadingWindowRef.current || keyRef.current !== key) return;
    loadingWindowRef.current = true;
    setLoadingWindow(true);
    setError(null);
    try {
      const page = await readSourcePage(query, cursor, controller.signal);
      if (controller.signal.aborted || keyRef.current !== key) return;
      const items = page.items.filter((item) => compareQuantity(item.available_quantity, "0") > 0);
      if (page.has_more && page.next_cursor) cursorHistory.current[index + 1] = page.next_cursor;
      setState((current) => {
        if (current.key !== key) return current;
        let pages = [
          ...current.pages.filter((entry) => entry.index !== index),
          { index, cursor, items, nextCursor: page.next_cursor, hasMore: page.has_more },
        ].sort((a, b) => a.index - b.index);
        if (pages.length > WINDOW_PAGE_COUNT) {
          pages = direction === "next"
            ? pages.slice(pages.length - WINDOW_PAGE_COUNT)
            : pages.slice(0, WINDOW_PAGE_COUNT);
        }
        return {
          ...current,
          pages,
          maxVisited: Math.max(current.maxVisited, index),
          total: current.total ?? page.total,
        };
      });
    } catch (failure) {
      if (!controller.signal.aborted && keyRef.current === key) setError(failure);
    } finally {
      loadingWindowRef.current = false;
      if (!controller.signal.aborted && keyRef.current === key) setLoadingWindow(false);
    }
  }, [key, query, readSourcePage]);

  const loadMoreSourceProducts = useCallback(() => {
    if (!lastPage || !hasMore || loading || loadingWindowRef.current) return;
    const index = lastPage.index + 1;
    const cursor = cursorHistory.current[index] ?? lastPage.nextCursor;
    if (!cursor) return;
    cursorHistory.current[index] = cursor;
    void loadWindowPage(index, cursor, "next");
  }, [hasMore, lastPage, loadWindowPage, loading]);

  const loadPreviousSourceProducts = useCallback(() => {
    if (!firstPage || !hasPrevious || loading || loadingWindowRef.current) return;
    const index = firstPage.index - 1;
    const cursor = cursorHistory.current[index];
    if (cursor === undefined) return;
    void loadWindowPage(index, cursor, "previous");
  }, [firstPage, hasPrevious, loadWindowPage, loading]);

  const registerProductPageHeight = useCallback((index: number, height: number) => {
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
    for (let index = 0; index < firstIndex; index += 1) total += active.heights[index] ?? PAGE_SIZE * 58;
    return total;
  }, [active.heights, firstIndex]);
  const bottomSpacerHeight = useMemo(() => {
    let total = 0;
    for (let index = lastIndex + 1; index <= active.maxVisited; index += 1) total += active.heights[index] ?? PAGE_SIZE * 58;
    return total;
  }, [active.heights, active.maxVisited, lastIndex]);

  const sourceProducts = useMemo(() => active.pages.flatMap((page) => page.items), [active.pages]);

  return {
    sources,
    destinations,
    ready,
    sourceProducts,
    sourceProductPages: active.pages.map(({ index, items }) => ({ index, items })),
    sourceProductsLoading: loading,
    sourceProductsLoadingMore: loadingWindow,
    sourceProductsError: error,
    sourceProductsNextCursor: hasMore ? "window" : null,
    productSearchInput,
    setProductSearchInput,
    resetProductSearch,
    readSourcePage,
    loadMoreSourceProducts,
    loadPreviousSourceProducts,
    hasPreviousSourceProducts: hasPrevious,
    hasMoreSourceProducts: hasMore,
    registerProductPageHeight,
    productTopSpacerHeight: topSpacerHeight,
    productBottomSpacerHeight: bottomSpacerHeight,
    retryProducts: () => setRevision((n) => n + 1),
  };
}
