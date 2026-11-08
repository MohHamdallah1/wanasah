import { buildLedgerCursorUrl } from "./buildLedgerCursorUrl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  captureDashboardSession, isDashboardSessionCurrent, subscribeDashboardSession,
  type DashboardSession,
} from "@/lib/authStorage";
import { parseLedgerPage, type LedgerEntry } from "./contracts";

export interface LedgerQueryState {
  entries: LedgerEntry[];
  searchInput: string;
  setSearchInput: (value: string) => void;
  filterType: string;
  setFilterType: (value: string) => void;
  availableTypes: string[];
  total: number | null;
  loading: boolean;
  loadingMore: boolean;
  error: boolean;
  hasMore: boolean;
  loadMore: () => void;
  refresh: () => void;
  retry: () => void;
  scopeKey: string;
  denied: boolean;
}

/** Append-only list over the server's signed keyset. No page numbers or client-side grouping. */
export function useLedgerQuery(
  locationId: number,
  refreshKey: number,
  active = true,
  exactReference: string | null = null,
): LedgerQueryState {
  const authFetch = useAuthFetch();
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filterType, setFilterType] = useState("ALL");
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(false);
  const [denied, setDenied] = useState(false);
  const [visibleScope, setVisibleScope] = useState<string | null>(null);
  const [sessionVersion, setSessionVersion] = useState(0);
  const seq = useRef(0);
  const pending = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const scopeRef = useRef<string | null>(null);
  const sessionRef = useRef<DashboardSession | null>(null);
  const cursorRef = useRef<string | null>(null);
  const wasActive = useRef(false);
  const cursorsSeen = useRef(new Set<string>());
  const idsSeen = useRef(new Set<number>());
  const pagesFetched = useRef(0);
  const revalidationFailed = useRef(false);
  const canceledBeforeFirstPage = useRef(false);
  // An interrupted first-page revalidation must restart even with saved pages.
  const revalidating = useRef(false);
  const interruptedRevalidation = useRef(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => subscribeDashboardSession(() => {
    // Token refresh inside the same authorized company/principal/session is
    // not a scope switch and must not discard 10k appended movements.
    if (sessionRef.current && isDashboardSessionCurrent(sessionRef.current)) return;
    seq.current++;
    abortRef.current?.abort();
    pending.current = false;
    scopeRef.current = null;
    sessionRef.current = null;
    setVisibleScope(null);
    setEntries([]);
    setNextCursor(null);
    setTotal(null);
    setHasMore(false);
    setLoadingMore(false);
    setSessionVersion(current => current + 1);
  }), []);

  // The raw search input is part of the visible scope to hide previously
  // authorized rows immediately, before debounce and the next server read.
  const scopeKey = useMemo(() =>
    JSON.stringify([locationId, refreshKey, sessionVersion,
      exactReference !== null ? "EXACT_STK" : "FUZZY",
      exactReference ?? searchInput.trim(),
      exactReference !== null ? "AUDIT_ADJUSTMENT" : filterType]),
    [locationId, refreshKey, sessionVersion, exactReference, searchInput, filterType]);
  const serverScope = useMemo(() =>
    JSON.stringify([locationId, refreshKey, sessionVersion,
      exactReference !== null ? "EXACT_STK" : "FUZZY",
      exactReference ?? debouncedSearch,
      exactReference !== null ? "AUDIT_ADJUSTMENT" : filterType]),
    [locationId, refreshKey, sessionVersion, exactReference, debouncedSearch, filterType]);

  const load = useCallback(async (cursor: string | null, reset: boolean) => {
    if (!active || pending.current || (!reset && !cursor)) return;
    const session = sessionRef.current;
    if (!session || !isDashboardSessionCurrent(session) || scopeRef.current !== serverScope) return;
    const requestId = ++seq.current;
    pending.current = true;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    if (reset) setLoading(true);
    else setLoadingMore(true);
    setError(false);
    try {
      const page = parseLedgerPage(await authFetch(buildLedgerCursorUrl({
        locationId,
        cursor,
        search: exactReference === null ? debouncedSearch : undefined,
        referenceType: exactReference !== null ? "AUDIT_ADJUSTMENT" : filterType,
        referenceId: exactReference ?? undefined,
      }), { signal: controller.signal }));
      if (requestId !== seq.current || scopeRef.current !== serverScope ||
        !isDashboardSessionCurrent(session)) return;
      if (page.has_more && (!page.next_cursor || cursorsSeen.current.has(page.next_cursor))) {
        throw new Error("LEDGER_CURSOR_STALLED");
      }
      if (page.has_more && page.next_cursor) cursorsSeen.current.add(page.next_cursor);
      // Across page boundaries a posted movement may appear twice. Never render
      // duplicate immutable movement identities.
      const fresh = page.items.filter(item => {
        if (idsSeen.current.has(item.id)) return false;
        idsSeen.current.add(item.id);
        return true;
      });
      setEntries(previous => reset ? fresh : [...previous, ...fresh]);
      pagesFetched.current = reset ? 1 : pagesFetched.current + 1;
      cursorRef.current = page.next_cursor;
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
      if (reset) {
        canceledBeforeFirstPage.current = false;
        setTotal(page.total);
        setAvailableTypes(page.available_types);
        setVisibleScope(scopeKey);
        setDenied(false);
      }
    } catch (failure) {
      if (requestId !== seq.current || scopeRef.current !== serverScope ||
        !isDashboardSessionCurrent(session)) return;
      if (failure instanceof Error && failure.name === "AbortError") return;
      const status = Number((failure as { status?: unknown } | null)?.status);
      if (status === 401 || status === 403) {
        seq.current++;
        setDenied(true);
        setEntries([]);
        idsSeen.current.clear();
        cursorsSeen.current.clear();
        cursorRef.current = null;
        setNextCursor(null);
        setHasMore(false);
        setTotal(null);
      } else {
        if (reset) setVisibleScope(scopeKey);
        setError(true);
      }
    } finally {
      if (requestId === seq.current) {
        pending.current = false;
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [active, authFetch, debouncedSearch, exactReference, filterType, locationId, scopeKey, serverScope]);

  const revalidate = useCallback(async () => {
    // Re-entering the same tab must re-check the current warehouse grant,
    // without dropping already-rendered rows, cursor or scroll position.
    const session = sessionRef.current;
    if (!session || pending.current || !isDashboardSessionCurrent(session)) return;
    const requestId = ++seq.current;
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    pending.current = true;
    setLoading(true);
    setLoadingMore(false);
    revalidating.current = true;
    interruptedRevalidation.current = false;
    revalidationFailed.current = false;
    try {
      const page = parseLedgerPage(await authFetch(buildLedgerCursorUrl({
        locationId, search: exactReference === null ? debouncedSearch : undefined,
        referenceType: exactReference !== null ? "AUDIT_ADJUSTMENT" : filterType,
        referenceId: exactReference ?? undefined,
      }), { signal: controller.signal }));
      if (requestId !== seq.current || scopeRef.current !== serverScope ||
        !isDashboardSessionCurrent(session)) return;
      // If only one page was retained, reconcile its new authoritative head.
      // For multi-page signed snapshots, preserve the entire old keyset. New
      // postings cannot be prepended without bridging through to overlap. A
      // fresh explicit Refresh starts a new snapshot without missing events.
      if (pagesFetched.current <= 1) {
        pagesFetched.current = 1;
        idsSeen.current = new Set(page.items.map(item => item.id));
        setEntries(page.items);
        cursorRef.current = page.next_cursor;
        setNextCursor(page.next_cursor);
        setHasMore(page.has_more);
        cursorsSeen.current = new Set(page.next_cursor ? [page.next_cursor] : []);
      }
      revalidationFailed.current = false;
      setVisibleScope(scopeKey);
      setError(false);
      setAvailableTypes(page.available_types);
      if (page.total !== null) setTotal(page.total);
    } catch (failure) {
      if (requestId !== seq.current || !isDashboardSessionCurrent(session)) return;
      const status = Number((failure as { status?: unknown } | null)?.status);
      if (status === 401 || status === 403) {
        setDenied(true);
        setEntries([]);
        idsSeen.current.clear();
        cursorsSeen.current.clear();
        cursorRef.current = null;
        setTotal(null);
        setHasMore(false);
        setNextCursor(null);
      } else if (!(failure instanceof Error && failure.name === "AbortError")) {
        revalidationFailed.current = true;
        setVisibleScope(scopeKey);
        setError(true);
      }
    } finally {
      if (requestId === seq.current) {
        pending.current = false;
        revalidating.current = false;
        setLoading(false);
      }
    }
  }, [authFetch, debouncedSearch, exactReference, filterType, locationId, serverScope]);

  useEffect(() => {
    if (!active) {
      wasActive.current = false;
      seq.current++;
      abortRef.current?.abort();
      pending.current = false;
      setLoadingMore(false);
      canceledBeforeFirstPage.current = pagesFetched.current === 0;
      if (revalidating.current) interruptedRevalidation.current = true;
      revalidating.current = false;
      setLoading(false);
      return;
    }
    const returning = !wasActive.current;
    wasActive.current = true;
    if (scopeRef.current !== serverScope) {
      seq.current++;
      abortRef.current?.abort();
      pending.current = false;
      setLoadingMore(false);
      revalidationFailed.current = false;
      interruptedRevalidation.current = false;
      revalidating.current = false;
      canceledBeforeFirstPage.current = false;
      scopeRef.current = serverScope;
      sessionRef.current = captureDashboardSession();
      idsSeen.current = new Set();
      pagesFetched.current = 0;
      cursorsSeen.current = new Set();
      cursorRef.current = null;
      setEntries([]);
      setTotal(null);
      setNextCursor(null);
      setHasMore(false);
      setVisibleScope(null);
      setDenied(false);
      void load(null, true);
    } else if (returning || canceledBeforeFirstPage.current || interruptedRevalidation.current || (visibleScope !== scopeKey && scopeKey === serverScope)) {
      // Raw search text is not authorized to reuse the old debounced result;
      // wait until its server scope catches up before admitting any rows.
      if (scopeKey === serverScope) {
        canceledBeforeFirstPage.current = false;
        interruptedRevalidation.current = false;
        void revalidate();
      }
    }
    return () => {
      if (pending.current && pagesFetched.current === 0) canceledBeforeFirstPage.current = true;
      if (pending.current && revalidating.current) interruptedRevalidation.current = true;
      revalidating.current = false;
      seq.current++;
      abortRef.current?.abort();
      pending.current = false;
      setLoadingMore(false);
      setLoading(false);
    };
  }, [active, serverScope, load, revalidate, scopeKey, visibleScope]);

  const loadMore = useCallback(() => {
    if (!pending.current && !error && hasMore && nextCursor && !denied && visibleScope === scopeKey) {
      void load(nextCursor, false);
    }
  }, [denied, error, hasMore, load, nextCursor, scopeKey, visibleScope]);

  const refresh = useCallback(() => {
    seq.current++;
    abortRef.current?.abort();
    pending.current = false;
    idsSeen.current.clear();
    pagesFetched.current = 0;
    cursorsSeen.current.clear();
    cursorRef.current = null;
    setEntries([]);
    setHasMore(false);
    setNextCursor(null);
    setVisibleScope(null);
    setDenied(false);
    revalidationFailed.current = false;
    void load(null, true);
  }, [load]);
  const retry = useCallback(() => {
    if (denied) return;
    if (revalidationFailed.current) { void revalidate(); return; }
    void load(cursorRef.current, entries.length === 0);
  }, [denied, entries.length, load, revalidate]);

  const visible = visibleScope === scopeKey && !denied;
  return {
    entries: visible ? entries : [], searchInput, setSearchInput, filterType,
    setFilterType, availableTypes: visible ? availableTypes : [],
    total: visible ? total : null, loading: loading || (!visible && !denied && !error),
    loadingMore, error: !denied && error && (visible || scopeRef.current === serverScope), hasMore: visible && hasMore,
    loadMore, refresh, retry, scopeKey, denied,
  };
}
