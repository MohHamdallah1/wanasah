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

export function useBatchIndex({
  locationId,
  filters,
  expiryWarningDays,
}: UseBatchIndexArgs): UseBatchIndexResult {
  const authFetch = useAuthFetch();
  const [items, setItems] = useState<WarehouseBatchIndexItem[]>([]);
  const [summary, setSummary] = useState<WarehouseBatchIndexSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [continuationError, setContinuationError] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const listRequestSeq = useRef(0);
  const summaryRequestSeq = useRef(0);
  const listAbortRef = useRef<AbortController | null>(null);
  const summaryAbortRef = useRef<AbortController | null>(null);

  const loadFirstPage = useCallback(async () => {
    const requestSeq = ++listRequestSeq.current;
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;

    setLoading(true);
    setListError(false);
    setLoadingMore(false);
    setContinuationError(false);
    setItems([]);
    setNextCursor(null);
    setHasMore(false);

    try {
      const params = buildBatchIndexCursorParams(
        locationId,
        filters,
        expiryWarningDays,
      );
      const page = parseBatchIndexCursorPage(
        await authFetch(`/warehouse/inventory/batches/cursor?${params.toString()}`, {
          signal: controller.signal,
        }),
      );
      if (requestSeq !== listRequestSeq.current) return;
      if (page.location_id !== locationId) {
        throw scopeMismatch("BATCH_INDEX_LOCATION_SCOPE_MISMATCH");
      }
      setItems(page.items);
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    } catch (error) {
      if (requestSeq !== listRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      setItems([]);
      setNextCursor(null);
      setHasMore(false);
      setListError(true);
    } finally {
      if (listAbortRef.current === controller) listAbortRef.current = null;
      if (requestSeq === listRequestSeq.current) setLoading(false);
    }
  }, [authFetch, expiryWarningDays, filters, locationId]);

  const loadSummary = useCallback(async () => {
    const requestSeq = ++summaryRequestSeq.current;
    summaryAbortRef.current?.abort();
    const controller = new AbortController();
    summaryAbortRef.current = controller;

    setSummaryLoading(true);
    setSummaryError(false);
    setSummary(null);

    try {
      const params = buildBatchIndexSummaryParams(
        locationId,
        filters,
        expiryWarningDays,
      );
      const parsed = parseBatchIndexSummary(
        await authFetch(`/warehouse/inventory/batches/summary?${params.toString()}`, {
          signal: controller.signal,
        }),
      );
      if (requestSeq !== summaryRequestSeq.current) return;
      if (parsed.location_id !== locationId) {
        throw scopeMismatch("BATCH_INDEX_SUMMARY_LOCATION_SCOPE_MISMATCH");
      }
      setSummary(parsed);
    } catch (error) {
      if (requestSeq !== summaryRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      setSummary(null);
      setSummaryError(true);
    } finally {
      if (summaryAbortRef.current === controller) summaryAbortRef.current = null;
      if (requestSeq === summaryRequestSeq.current) setSummaryLoading(false);
    }
  }, [authFetch, expiryWarningDays, filters.familyId, filters.productVariantId, filters.search, locationId]);

  useEffect(() => {
    void loadFirstPage();
    return () => {
      listRequestSeq.current += 1;
      listAbortRef.current?.abort();
      listAbortRef.current = null;
    };
  }, [loadFirstPage]);

  useEffect(() => {
    void loadSummary();
    return () => {
      summaryRequestSeq.current += 1;
      summaryAbortRef.current?.abort();
      summaryAbortRef.current = null;
    };
  }, [loadSummary]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || !hasMore || loading || loadingMore) return;

    const cursor = nextCursor;
    const requestSeq = ++listRequestSeq.current;
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;
    setLoadingMore(true);
    setContinuationError(false);

    try {
      const params = buildBatchIndexCursorParams(
        locationId,
        filters,
        expiryWarningDays,
        cursor,
      );
      const page = parseBatchIndexCursorPage(
        await authFetch(`/warehouse/inventory/batches/cursor?${params.toString()}`, {
          signal: controller.signal,
        }),
      );
      if (requestSeq !== listRequestSeq.current) return;
      if (page.location_id !== locationId) {
        throw scopeMismatch("BATCH_INDEX_LOCATION_SCOPE_MISMATCH");
      }
      setItems((current) => appendUniqueBatchItems(current, page.items));
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    } catch (error) {
      if (requestSeq !== listRequestSeq.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      setContinuationError(true);
    } finally {
      if (listAbortRef.current === controller) listAbortRef.current = null;
      if (requestSeq === listRequestSeq.current) setLoadingMore(false);
    }
  }, [authFetch, expiryWarningDays, filters, hasMore, loading, loadingMore, locationId, nextCursor]);

  const refresh = useCallback(async () => {
    await Promise.all([loadFirstPage(), loadSummary()]);
  }, [loadFirstPage, loadSummary]);

  return {
    items,
    summary,
    loading,
    listError,
    summaryLoading,
    summaryError,
    loadingMore,
    continuationError,
    hasMore,
    nextCursor,
    loadMore,
    refresh,
    retryList: loadFirstPage,
    retrySummary: loadSummary,
  };
}