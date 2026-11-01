import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  appendUniqueBatchItems,
  buildBatchIndexCursorParams,
  buildBatchIndexSummaryParams,
  parseBatchIndexCursorPage,
  parseBatchIndexSummary,
  type BatchIndexFilters,
  type WarehouseBatchIndexItem,
  type WarehouseBatchIndexSummary,
} from "./batchIndexContracts";

interface UseBatchIndexArgs {
  locationId: number;
  filters: BatchIndexFilters;
  expiryWarningDays: number;
  active?: boolean;
  refreshKey?: number;
}

export interface UseBatchIndexResult {
  items: WarehouseBatchIndexItem[];
  summary: WarehouseBatchIndexSummary | null;
  loading: boolean;
  listError: boolean;
  summaryLoading: boolean;
  summaryError: boolean;
  loadingMore: boolean;
  continuationError: boolean;
  hasMore: boolean;
  nextCursor: string | null;
  loadMore: () => Promise<void>;
  refresh: () => Promise<void>;
  retryList: () => Promise<void>;
  retrySummary: () => Promise<void>;
}

const scopeMismatch = (code: string): Error & { code: string } => {
  const error = new Error(code) as Error & { code: string };
  error.code = code;
  return error;
};

const mustDropRetainedData = (error: unknown): boolean => {
  const status = Number((error as { status?: unknown } | null)?.status);
  const code = (error as { code?: unknown } | null)?.code;
  return (
    [401, 403, 404].includes(status) ||
    code === "BATCH_INDEX_LOCATION_SCOPE_MISMATCH" ||
    code === "BATCH_INDEX_SUMMARY_LOCATION_SCOPE_MISMATCH" ||
    code === "BATCH_INDEX_RESPONSE_INVALID"
  );
};

export function useBatchIndex({
  locationId,
  filters,
  expiryWarningDays,
  active = true,
  refreshKey = 0,
}: UseBatchIndexArgs): UseBatchIndexResult {
  const authFetch = useAuthFetch();
  const [items, setItems] = useState<WarehouseBatchIndexItem[]>([]);
  const [summary, setSummary] = useState<WarehouseBatchIndexSummary | null>(null);
  const [loading, setLoading] = useState(active);
  const [listError, setListError] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(active);
  const [summaryError, setSummaryError] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [continuationError, setContinuationError] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const listRequestSeq = useRef(0);
  const summaryRequestSeq = useRef(0);
  const listAbortRef = useRef<AbortController | null>(null);
  const summaryAbortRef = useRef<AbortController | null>(null);

  // These refs separate "what the controls currently request" from the last
  // data scope that is safe to display. That prevents a one-frame flash of
  // rows from an old filter/location before the effect starts its new read.
  const visibleListScopeRef = useRef<string | null>(null);
  const visibleSummaryScopeRef = useRef<string | null>(null);
  const freshListScopeRef = useRef<string | null>(null);
  const freshSummaryScopeRef = useRef<string | null>(null);
  const freshListRefreshKeyRef = useRef<number | null>(null);
  const freshSummaryRefreshKeyRef = useRef<number | null>(null);

  const listScopeKey = buildBatchIndexCursorParams(
    locationId,
    filters,
    expiryWarningDays,
  ).toString();
  const summaryScopeKey = buildBatchIndexSummaryParams(
    locationId,
    filters,
    expiryWarningDays,
  ).toString();

  const loadFirstPage = useCallback(async () => {
    const requestScope = listScopeKey;
    const requestRefreshKey = refreshKey;
    const sameVisibleScope = visibleListScopeRef.current === requestScope;
    const requestSeq = ++listRequestSeq.current;
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;

    setLoading(true);
    setListError(false);
    setLoadingMore(false);
    setContinuationError(false);
    if (!sameVisibleScope) {
      setItems([]);
      setNextCursor(null);
      setHasMore(false);
    }

    try {
      const page = parseBatchIndexCursorPage(
        await authFetch(`/warehouse/inventory/batches/cursor?${requestScope}`, {
          signal: controller.signal,
        }),
      );
      if (requestSeq !== listRequestSeq.current) return;
      if (page.location_id !== locationId) {
        throw scopeMismatch("BATCH_INDEX_LOCATION_SCOPE_MISMATCH");
      }
      visibleListScopeRef.current = requestScope;
      freshListScopeRef.current = requestScope;
      freshListRefreshKeyRef.current = requestRefreshKey;
      setItems(page.items);
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    } catch (error) {
      if (requestSeq !== listRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;

      freshListScopeRef.current = null;
      freshListRefreshKeyRef.current = null;
      if (!sameVisibleScope || mustDropRetainedData(error)) {
        visibleListScopeRef.current = requestScope;
        setItems([]);
        setNextCursor(null);
        setHasMore(false);
      }
      setListError(true);
    } finally {
      if (listAbortRef.current === controller) listAbortRef.current = null;
      if (requestSeq === listRequestSeq.current) setLoading(false);
    }
  }, [authFetch, listScopeKey, locationId, refreshKey]);

  const loadSummary = useCallback(async () => {
    const requestScope = summaryScopeKey;
    const requestRefreshKey = refreshKey;
    const sameVisibleScope = visibleSummaryScopeRef.current === requestScope;
    const requestSeq = ++summaryRequestSeq.current;
    summaryAbortRef.current?.abort();
    const controller = new AbortController();
    summaryAbortRef.current = controller;

    setSummaryLoading(true);
    setSummaryError(false);
    if (!sameVisibleScope) setSummary(null);

    try {
      const parsed = parseBatchIndexSummary(
        await authFetch(`/warehouse/inventory/batches/summary?${requestScope}`, {
          signal: controller.signal,
        }),
      );
      if (requestSeq !== summaryRequestSeq.current) return;
      if (parsed.location_id !== locationId) {
        throw scopeMismatch("BATCH_INDEX_SUMMARY_LOCATION_SCOPE_MISMATCH");
      }
      visibleSummaryScopeRef.current = requestScope;
      freshSummaryScopeRef.current = requestScope;
      freshSummaryRefreshKeyRef.current = requestRefreshKey;
      setSummary(parsed);
    } catch (error) {
      if (requestSeq !== summaryRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;

      freshSummaryScopeRef.current = null;
      freshSummaryRefreshKeyRef.current = null;
      if (!sameVisibleScope || mustDropRetainedData(error)) {
        visibleSummaryScopeRef.current = requestScope;
        setSummary(null);
      }
      setSummaryError(true);
    } finally {
      if (summaryAbortRef.current === controller) summaryAbortRef.current = null;
      if (requestSeq === summaryRequestSeq.current) setSummaryLoading(false);
    }
  }, [authFetch, locationId, refreshKey, summaryScopeKey]);

  useEffect(() => {
    if (!active) {
      listRequestSeq.current += 1;
      listAbortRef.current?.abort();
      listAbortRef.current = null;
      setLoading(false);
      setLoadingMore(false);
      return;
    }
    if (
      freshListScopeRef.current === listScopeKey &&
      freshListRefreshKeyRef.current === refreshKey
    ) {
      setLoading(false);
      return;
    }
    void loadFirstPage();
    return () => {
      listRequestSeq.current += 1;
      listAbortRef.current?.abort();
      listAbortRef.current = null;
    };
  }, [active, listScopeKey, loadFirstPage, refreshKey]);

  useEffect(() => {
    if (!active) {
      summaryRequestSeq.current += 1;
      summaryAbortRef.current?.abort();
      summaryAbortRef.current = null;
      setSummaryLoading(false);
      return;
    }
    if (
      freshSummaryScopeRef.current === summaryScopeKey &&
      freshSummaryRefreshKeyRef.current === refreshKey
    ) {
      setSummaryLoading(false);
      return;
    }
    void loadSummary();
    return () => {
      summaryRequestSeq.current += 1;
      summaryAbortRef.current?.abort();
      summaryAbortRef.current = null;
    };
  }, [active, loadSummary, refreshKey, summaryScopeKey]);

  const loadMore = useCallback(async () => {
    if (
      !active ||
      visibleListScopeRef.current !== listScopeKey ||
      !nextCursor ||
      !hasMore ||
      loading ||
      loadingMore
    ) {
      return;
    }

    const cursor = nextCursor;
    const requestScope = listScopeKey;
    const requestSeq = ++listRequestSeq.current;
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;
    setLoadingMore(true);
    setContinuationError(false);

    try {
      const params = new URLSearchParams(requestScope);
      params.set("cursor", cursor);
      const page = parseBatchIndexCursorPage(
        await authFetch(`/warehouse/inventory/batches/cursor?${params.toString()}`, {
          signal: controller.signal,
        }),
      );
      if (
        requestSeq !== listRequestSeq.current ||
        visibleListScopeRef.current !== requestScope
      ) {
        return;
      }
      if (page.location_id !== locationId) {
        throw scopeMismatch("BATCH_INDEX_LOCATION_SCOPE_MISMATCH");
      }
      setItems((current) => appendUniqueBatchItems(current, page.items));
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    } catch (error) {
      if (requestSeq !== listRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      if (mustDropRetainedData(error)) {
        visibleListScopeRef.current = requestScope;
        freshListScopeRef.current = null;
        freshListRefreshKeyRef.current = null;
        setItems([]);
        setNextCursor(null);
        setHasMore(false);
        setListError(true);
      } else {
        setContinuationError(true);
      }
    } finally {
      if (listAbortRef.current === controller) listAbortRef.current = null;
      if (requestSeq === listRequestSeq.current) setLoadingMore(false);
    }
  }, [
    active,
    authFetch,
    hasMore,
    listScopeKey,
    loading,
    loadingMore,
    locationId,
    nextCursor,
  ]);

  const refresh = useCallback(async () => {
    if (!active) return;
    await Promise.all([loadFirstPage(), loadSummary()]);
  }, [active, loadFirstPage, loadSummary]);

  const listScopeVisible = visibleListScopeRef.current === listScopeKey;
  const summaryScopeVisible = visibleSummaryScopeRef.current === summaryScopeKey;

  return {
    items: listScopeVisible ? items : [],
    summary: summaryScopeVisible ? summary : null,
    loading: active && (!listScopeVisible || loading),
    listError: listScopeVisible ? listError : false,
    summaryLoading: active && (!summaryScopeVisible || summaryLoading),
    summaryError: summaryScopeVisible ? summaryError : false,
    loadingMore: listScopeVisible ? loadingMore : false,
    continuationError: listScopeVisible ? continuationError : false,
    hasMore: listScopeVisible ? hasMore : false,
    nextCursor: listScopeVisible ? nextCursor : null,
    loadMore,
    refresh,
    retryList: loadFirstPage,
    retrySummary: loadSummary,
  };
}
