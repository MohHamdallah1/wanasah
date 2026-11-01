import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseTransferDetail, parseTransferPage } from "../parsers";
import type { TransferStatus, WarehouseTransferDetail, WarehouseTransferListItem } from "../types";
import { getErrorMessage } from "../utils";
import { useTransferTranslation } from "../i18n";

type ListState = {
  scope: string;
  items: WarehouseTransferListItem[];
  next: string | null;
  total: number | null;
};
type Attempt = {
  cursor: string | null;
  phase: "first" | "refresh" | "continuation";
  append: boolean;
};

export function useTransferList() {
  const authenticatedFetch = useAuthFetch();
  const { t } = useTransferTranslation();
  const [status, setStatus] = useState<TransferStatus | "">("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [state, setState] = useState<ListState | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadingMoreRef = useRef(false);
  const [failure, setFailure] = useState<{ scope: string; phase: Attempt["phase"]; message: string } | null>(null);
  const scope = JSON.stringify([status, search]);
  // Keep typed (not yet debounced) search out of the old result scope.
  const searchPending = searchInput.trim() !== search;
  const searchTooShort = searchInput.trim().length === 1;
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const requestSeq = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const lastAttempt = useRef<Attempt>({ cursor: null, phase: "first", append: false });
  const current = !searchPending && !searchTooShort && state?.scope === scope ? state : null;
  const [detail, setDetail] = useState<WarehouseTransferDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const detailRequestSeq = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 1 ? clean : "");
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const fetchPage = useCallback(async (attempt: Attempt) => {
    // The API only accepts two or more characters. Never retry a short query.
    if (search.length === 1) return;
    if (attempt.append && loadingMoreRef.current) return;
    const seq = ++requestSeq.current;
    if (!attempt.append) abort.current?.abort();
    const controller = new AbortController();
    if (!attempt.append) abort.current = controller;
    lastAttempt.current = attempt;
    if (attempt.append) {
      loadingMoreRef.current = true;
      setLoadingMore(true);
    } else {
      loadingMoreRef.current = false;
      setLoadingMore(false);
      setLoading(true);
    }
    setFailure(null);
    try {
      const params = new URLSearchParams({ limit: "50" });
      if (status) params.set("status", status);
      if (search) params.set("search", search);
      if (attempt.cursor) params.set("cursor", attempt.cursor);
      const raw = await authenticatedFetch(`/warehouse/unified/transfers?${params}`, { signal: controller.signal });
      if (seq !== requestSeq.current || scopeRef.current !== scope) return;
      const parsed = parseTransferPage(raw);
      setState((previous) => {
        const previousItems = attempt.append && previous?.scope === scope ? previous.items : [];
        const items = [...new Map([...previousItems, ...parsed.items].map((row) => [row.id, row])).values()];
        return {
          scope,
          items,
          next: parsed.next_cursor,
          total: attempt.append
            ? previous?.total ?? parsed.total
            : parsed.total,
        };
      });
    } catch (error) {
      if (seq !== requestSeq.current || scopeRef.current !== scope || controller.signal.aborted) return;
      const key = attempt.phase === "first"
        ? "firstFailure"
        : attempt.phase === "refresh"
          ? "refreshFailure"
          : "continuationFailure";
      setFailure({ scope, phase: attempt.phase, message: getErrorMessage(error, t(`inventoryTransfers.${key}`)) });
    } finally {
      if (seq === requestSeq.current && scopeRef.current === scope) {
        if (attempt.append) {
          loadingMoreRef.current = false;
          setLoadingMore(false);
        } else setLoading(false);
      }
    }
  }, [authenticatedFetch, scope, search, status, t]);

  const invalidateList = useCallback(() => {
    ++requestSeq.current;
    abort.current?.abort();
    loadingMoreRef.current = false;
  }, []);
  useEffect(() => {
    if (search.length === 1) {
      invalidateList();
      setLoading(false);
      setLoadingMore(false);
      setFailure(null);
      return invalidateList;
    }
    void fetchPage({ cursor: null, phase: "first", append: false });
    return invalidateList;
  }, [fetchPage, invalidateList]);

  const invalidateDetail = useCallback(() => {
    ++detailRequestSeq.current;
  }, []);
  useEffect(() => {
    ++detailRequestSeq.current;
    setDetail(null);
    setDetailLoading(false);
    return invalidateDetail;
  }, [scope, invalidateDetail]);

  const openDetailById = useCallback(async (headerId: number) => {
    const seq = ++detailRequestSeq.current;
    setDetailLoading(true);
    setDetail(null);
    try {
      const raw = await authenticatedFetch(`/warehouse/unified/transfers/${headerId}`);
      if (seq !== detailRequestSeq.current) return false;
      setDetail(parseTransferDetail(raw));
      return true;
    } catch (error) {
      if (seq !== detailRequestSeq.current) return false;
      toast.error(getErrorMessage(error, t("inventoryTransfers.detailFailure")));
      return false;
    } finally {
      if (seq === detailRequestSeq.current) setDetailLoading(false);
    }
  }, [authenticatedFetch, t]);

  const resetDetail = useCallback(() => {
    ++detailRequestSeq.current;
    setDetail(null);
    setDetailLoading(false);
  }, []);

  const items = current?.items ?? [];
  const scopedFailure = !searchPending && !searchTooShort && failure?.scope === scope ? failure : null;
  // `loading` is flipped by the fetch effect, i.e. one commit after the render
  // that needs it. A scope with neither rows nor a failure is still owed its
  // first page, so report it as loading from the first frame; otherwise the
  // table paints "no transfers" on mount and on every filter/search change
  // before switching to "loading" and then to the rows.
  const awaitingFirstPage = !searchPending && !searchTooShort && current === null && scopedFailure === null;
  const inTransitCount = items.filter((item) => item.status === "IN_TRANSIT").length;
  const loadMore = useCallback(() => {
    if (!current?.next || loading || loadingMore) return;
    void fetchPage({ cursor: current.next, phase: "continuation", append: true });
  }, [current?.next, fetchPage, loading, loadingMore]);

  return {
    items,
    status,
    setStatus,
    searchInput,
    setSearchInput,
    searchTooShort,
    searchPending,
    total: current?.total ?? null,
    loading: searchTooShort ? false : loading || awaitingFirstPage || searchPending,
    loadingMore: !searchPending && !searchTooShort && loadingMore,
    hasMore: Boolean(current?.next),
    failure: scopedFailure,
    retry: () => {
      if (!searchPending && !searchTooShort) void fetchPage(lastAttempt.current);
    },
    detail,
    detailLoading,
    inTransitCount,
    openDetailById,
    openDetail: (transfer: WarehouseTransferListItem) => openDetailById(transfer.id),
    closeDetail: resetDetail,
    resetDetail,
    refreshTransfers: () => {
      if (!searchPending && !searchTooShort) {
        void fetchPage({ cursor: null, phase: current ? "refresh" : "first", append: false });
      }
    },
    loadMore,
  };
}
