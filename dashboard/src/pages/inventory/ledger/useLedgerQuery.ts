import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseLedgerPage, type LedgerEntry } from "./contracts";

const PAGE_SIZE = 20;

export interface LedgerQueryState {
  entries: LedgerEntry[];
  searchInput: string;
  setSearchInput: (value: string) => void;
  filterType: string;
  setFilterType: (value: string) => void;
  availableTypes: string[];
  total: number | null;
  pageIndex: number;
  loading: boolean;
  error: boolean;
  hasMore: boolean;
  canGoPrevious: boolean;
  goNext: () => void;
  goPrevious: () => void;
  refresh: () => void;
  retry: () => void;
}

export const buildLedgerCursorUrl = ({
  locationId,
  cursor,
  search,
  referenceType,
  referenceId,
  limit = PAGE_SIZE,
}: {
  locationId: number;
  cursor?: string | null;
  search?: string;
  referenceType?: string;
  referenceId?: string;
  limit?: number;
}): string => {
  const params = new URLSearchParams({
    location_id: String(locationId),
    limit: String(limit),
  });
  if (cursor) params.set("cursor", cursor);
  if (referenceId) {
    params.set("reference_id", referenceId);
    if (referenceType) params.set("reference_type", referenceType);
  } else {
    const cleanSearch = (search ?? "").trim();
    if (cleanSearch.length >= 2) params.set("search", cleanSearch);
    if (referenceType && referenceType !== "ALL") params.set("reference_type", referenceType);
  }
  return `/warehouse/ledger/cursor?${params.toString()}`;
};

export function useLedgerQuery(locationId: number, refreshKey: number): LedgerQueryState {
  const authFetch = useAuthFetch();
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filterType, setFilterType] = useState("ALL");
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([null]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const scopeKey = useMemo(
    () => `${locationId}|${debouncedSearch}|${filterType}|${refreshKey}`,
    [debouncedSearch, filterType, locationId, refreshKey],
  );

  const loadPage = useCallback(async (
    cursor: string | null,
    targetPage: number,
    clearForNewScope: boolean,
  ) => {
    const sequence = ++requestSeq.current;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(false);
    if (clearForNewScope) {
      setEntries([]);
      setTotal(null);
      setNextCursor(null);
      setHasMore(false);
    }

    try {
      const page = parseLedgerPage(await authFetch(
        buildLedgerCursorUrl({
          locationId,
          cursor,
          search: debouncedSearch,
          referenceType: filterType,
        }),
        { signal: controller.signal },
      ));
      if (sequence !== requestSeq.current) return;
      setEntries(page.items);
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
      setPageIndex(targetPage);
      if (page.total !== null) setTotal(page.total);
      if (targetPage === 0) setAvailableTypes(page.available_types);
    } catch (failure) {
      if (sequence !== requestSeq.current) return;
      if (failure instanceof Error && failure.name === "AbortError") return;
      setError(true);
      if (clearForNewScope) {
        setEntries([]);
        setNextCursor(null);
        setHasMore(false);
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (sequence === requestSeq.current) setLoading(false);
    }
  }, [authFetch, debouncedSearch, filterType, locationId]);

  const resetAndLoad = useCallback(() => {
    requestSeq.current += 1;
    abortRef.current?.abort();
    setCursorHistory([null]);
    setPageIndex(0);
    void loadPage(null, 0, true);
  }, [loadPage]);

  useEffect(() => {
    resetAndLoad();
    return () => {
      requestSeq.current += 1;
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, [resetAndLoad, scopeKey]);

  const goNext = useCallback(() => {
    if (!hasMore || !nextCursor || loading) return;
    const target = pageIndex + 1;
    setCursorHistory((current) => {
      const next = current.slice(0, target);
      next[target] = nextCursor;
      return next;
    });
    void loadPage(nextCursor, target, false);
  }, [hasMore, loadPage, loading, nextCursor, pageIndex]);

  const goPrevious = useCallback(() => {
    if (pageIndex <= 0 || loading) return;
    const target = pageIndex - 1;
    void loadPage(cursorHistory[target] ?? null, target, false);
  }, [cursorHistory, loadPage, loading, pageIndex]);

  const refresh = useCallback(() => {
    setCursorHistory([null]);
    setPageIndex(0);
    void loadPage(null, 0, false);
  }, [loadPage]);

  const retry = useCallback(() => {
    void loadPage(cursorHistory[pageIndex] ?? null, pageIndex, entries.length === 0);
  }, [cursorHistory, entries.length, loadPage, pageIndex]);

  return {
    entries,
    searchInput,
    setSearchInput,
    filterType,
    setFilterType,
    availableTypes,
    total,
    pageIndex,
    loading,
    error,
    hasMore,
    canGoPrevious: pageIndex > 0,
    goNext,
    goPrevious,
    refresh,
    retry,
  };
}
