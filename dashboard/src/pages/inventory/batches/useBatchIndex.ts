import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

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
  active = true,
}: UseBatchIndexArgs): UseBatchIndexResult {
  const authFetch = useAuthFetch();
  // Scope identity is the exact query sent to each backend reader.
  // Old filter/location rows must not paint before a replacement effect runs.
  const listScope = buildBatchIndexCursorParams(locationId, filters, expiryWarningDays).toString();
  const summaryScope = buildBatchIndexSummaryParams(locationId, filters, expiryWarningDays).toString();
  const currentScope = useRef({ list: listScope, summary: summaryScope });
  currentScope.current = { list: listScope, summary: summaryScope };
  const committedListScope = useRef<string | null>(null);
  const committedSummaryScope = useRef<string | null>(null);
  const [visibleListScope, setVisibleListScope] = useState<string | null>(null);
  const [visibleSummaryScope, setVisibleSummaryScope] = useState<string | null>(null);
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
    if (!active) return;
    const requestSeq = ++listRequestSeq.current;
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;

    setLoading(true);
    setListError(false);
    setLoadingMore(false);
    setContinuationError(false);
    if (committedListScope.current !== listScope) {
      committedListScope.current = listScope;
      setVisibleListScope(listScope);
      setItems([]);
    }
    // A previous cursor must never be used against a newly validated page.
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
      if (requestSeq !== listRequestSeq.current ||
          currentScope.current.list !== listScope || !active) return;
      if (page.location_id !== locationId) {
        throw scopeMismatch("BATCH_INDEX_LOCATION_SCOPE_MISMATCH");
      }
      setItems(page.items);
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    } catch (error) {
      if (requestSeq !== listRequestSeq.current ||
          currentScope.current.list !== listScope || !active) return;
      if (error instanceof Error && error.name === "AbortError") return;
      // A failed verification must not leave old quantities looking current.
      setItems([]);
      setNextCursor(null);
      setHasMore(false);
      setListError(true);
    } finally {
      if (listAbortRef.current === controller) listAbortRef.current = null;
      if (requestSeq === listRequestSeq.current) setLoading(false);
    }
  }, [active, authFetch, expiryWarningDays, filters, listScope, locationId]);

  const loadSummary = useCallback(async () => {
    if (!active) return;
    const requestSeq = ++summaryRequestSeq.current;
    summaryAbortRef.current?.abort();
    const controller = new AbortController();
    summaryAbortRef.current = controller;

    setSummaryLoading(true);
    setSummaryError(false);
    if (committedSummaryScope.current !== summaryScope) {
      committedSummaryScope.current = summaryScope;
      setVisibleSummaryScope(summaryScope);
      setSummary(null);
    }

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
      if (requestSeq !== summaryRequestSeq.current ||
          currentScope.current.summary !== summaryScope || !active) return;
      if (parsed.location_id !== locationId) {
        throw scopeMismatch("BATCH_INDEX_SUMMARY_LOCATION_SCOPE_MISMATCH");
      }
      setSummary(parsed);
    } catch (error) {
      if (requestSeq !== summaryRequestSeq.current ||
          currentScope.current.summary !== summaryScope || !active) return;
      if (error instanceof Error && error.name === "AbortError") return;
      setSummary(null);
      setSummaryError(true);
    } finally {
      if (summaryAbortRef.current === controller) summaryAbortRef.current = null;
      if (requestSeq === summaryRequestSeq.current) setSummaryLoading(false);
    }
  }, [active, authFetch, expiryWarningDays, filters.familyId, filters.productVariantId, filters.search, summaryScope, locationId]);

  // A returning tab must be marked as revalidating before the browser paints
  // its first frame; the network effects below remain ordinary async effects.
  useLayoutEffect(() => {
    if (!active) return;
    setLoading(true);
    setSummaryLoading(true);
  }, [active]);

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
    if (!active || visibleListScope !== listScope ||
        !nextCursor || !hasMore || loading || loadingMore) return;

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
      if (requestSeq !== listRequestSeq.current ||
          currentScope.current.list !== listScope || !active) return;
      if (page.location_id !== locationId) {
        throw scopeMismatch("BATCH_INDEX_LOCATION_SCOPE_MISMATCH");
      }
      setItems((current) => appendUniqueBatchItems(current, page.items));
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    } catch (error) {
      if (requestSeq !== listRequestSeq.current ||
          currentScope.current.list !== listScope || !active) return;
      if (error instanceof Error && error.name === "AbortError") return;
      setContinuationError(true);
    } finally {
      if (listAbortRef.current === controller) listAbortRef.current = null;
      if (requestSeq === listRequestSeq.current) setLoadingMore(false);
    }
  }, [active, authFetch, expiryWarningDays, filters, hasMore, loading, loadingMore, listScope, locationId, nextCursor, visibleListScope]);

  const refresh = useCallback(async () => {
    await Promise.all([loadFirstPage(), loadSummary()]);
  }, [loadFirstPage, loadSummary]);

  // A 403 from any inventory reader immediately revokes local disclosure;
  // the parent also revokes its independent location admission.
  useEffect(() => {
    const revoke = () => {
      listRequestSeq.current += 1;
      summaryRequestSeq.current += 1;
      listAbortRef.current?.abort();
      summaryAbortRef.current?.abort();
      committedListScope.current = null;
      committedSummaryScope.current = null;
      setVisibleListScope(null);
      setVisibleSummaryScope(null);
      setItems([]);
      setSummary(null);
      setNextCursor(null);
      setHasMore(false);
      setLoading(false);
      setSummaryLoading(false);
      setListError(true);
      setSummaryError(true);
    };
    window.addEventListener("inventory-permission-denied", revoke);
    return () => window.removeEventListener("inventory-permission-denied", revoke);
  }, []);

  const showList = active && visibleListScope === listScope;
  const showSummary = active && visibleSummaryScope === summaryScope;
  return {
    items: showList ? items : [],
    summary: showSummary ? summary : null,
    loading: active && (!showList || loading),
    listError: showList && listError,
    summaryLoading: active && (!showSummary || summaryLoading),
    summaryError: showSummary && summaryError,
    loadingMore: showList && loadingMore,
    continuationError: showList && continuationError,
    hasMore: showList && hasMore,
    nextCursor: showList ? nextCursor : null,
    loadMore,
    refresh,
    retryList: loadFirstPage,
    retrySummary: loadSummary,
  };
}