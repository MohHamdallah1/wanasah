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

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => subscribeDashboardSession(() => {
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
      cursorRef.current = page.next_cursor;
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
      if (reset) {
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
      } else setError(true);
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
    try {
      const page = parseLedgerPage(await authFetch(buildLedgerCursorUrl({
        locationId, search: exactReference === null ? debouncedSearch : undefined,
        referenceType: exactReference !== null ? "AUDIT_ADJUSTMENT" : filterType,
        referenceId: exactReference ?? undefined,
      }), { signal: controller.signal }));
      if (requestId !== seq.current || scopeRef.current !== serverScope ||
        !isDashboardSessionCurrent(session)) return;
      // Existing cursor remains bound to its original keyset scope/snapshot.
      // A revalidation cannot overwrite an appended list with page one.
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
      } else if (!(failure instanceof Error && failure.name === "AbortError")) setError(true);
    } finally {
      if (requestId === seq.current) {
        pending.current = false;
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
      return;
    }
    const returning = !wasActive.current;
    wasActive.current = true;
    if (scopeRef.current !== serverScope) {
      seq.current++;
      abortRef.current?.abort();
      pending.current = false;
      scopeRef.current = serverScope;
      sessionRef.current = captureDashboardSession();
      idsSeen.current = new Set();
      cursorsSeen.current = new Set();
      cursorRef.current = null;
      setEntries([]);
      setTotal(null);
      setNextCursor(null);
      setHasMore(false);
      setVisibleScope(null);
      setDenied(false);
      void load(null, true);
    } else if (returning) {
      void revalidate();
    }
    return () => { seq.current++; abortRef.current?.abort(); pending.current = false; };
  }, [active, serverScope, load, revalidate]);

  const loadMore = useCallback(() => {
    if (!pending.current && hasMore && nextCursor && !denied && visibleScope === scopeKey) {
      void load(nextCursor, false);
    }
  }, [denied, hasMore, load, nextCursor, scopeKey, visibleScope]);

  const refresh = useCallback(() => {
    seq.current++;
    abortRef.current?.abort();
    pending.current = false;
    idsSeen.current.clear();
    cursorsSeen.current.clear();
    cursorRef.current = null;
    setEntries([]);
    setHasMore(false);
    setNextCursor(null);
    setVisibleScope(null);
    setDenied(false);
    void load(null, true);
  }, [load]);
  const retry = useCallback(() => {
    if (denied) return;
    void load(cursorRef.current, entries.length === 0);
  }, [denied, entries.length, load]);

  const visible = visibleScope === scopeKey && !denied;
  return {
    entries: visible ? entries : [], searchInput, setSearchInput, filterType,
    setFilterType, availableTypes: visible ? availableTypes : [],
    total: visible ? total : null, loading: loading || (!visible && !denied),
    loadingMore, error: visible && error, hasMore: visible && hasMore,
    loadMore, refresh, retry, scopeKey, denied,
  };
}
