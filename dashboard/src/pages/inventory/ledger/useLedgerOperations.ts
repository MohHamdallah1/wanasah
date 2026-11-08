import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseLedgerOperationFailure, type LedgerOperationFailure } from "./operationI18n";
import {
  captureDashboardSession, isDashboardSessionCurrent, subscribeDashboardSession,
  type DashboardSession,
} from "@/lib/authStorage";
import {
  buildLedgerOperationUrl, parseLedgerOperationPage, type LedgerOperation,
} from "./operationContracts";

export interface LedgerOperationQuery {
  items: LedgerOperation[];
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: boolean;
  failure: LedgerOperationFailure | null;
  authorizedProof: { scope: string; sequence: number } | null;
  denied: boolean;
  loadMore: () => void;
  retry: () => void;
  refresh: () => void;
  visibleScope: string;
}

/**
 * Parent rows are authoritative server groups. Page boundaries may split a
 * single group or return zero items with a valid continuation cursor.
 */
export function useLedgerOperations(
  locationId: number, refreshKey: number, active: boolean,
  search: string, movementType: string, exactReference: string | null,
): LedgerOperationQuery {
  const authFetch = useAuthFetch();
  const [debounced, setDebounced] = useState("");
  const [sessionVersion, setSessionVersion] = useState(0);
  const [items, setItems] = useState<LedgerOperation[]>([]);
  const [scopeVisible, setScopeVisible] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState(false);
  const [failure, setFailure] = useState<LedgerOperationFailure | null>(null);
  const [denied, setDenied] = useState(false);
  // Freshly authorized parent first-page reads, scoped to this company/warehouse.
  const [authorizedProof, setAuthorizedProof] = useState<{ scope: string; sequence: number } | null>(null);
  const proofSerial = useRef(0);
  const seq = useRef(0);
  const pending = useRef(false);
  const aborted = useRef<AbortController | null>(null);
  const scopeRef = useRef<string | null>(null);
  const sessionRef = useRef<DashboardSession | null>(null);
  const cursorRef = useRef<string | null>(null);
  const seenCursors = useRef(new Set<string>());
  const seenGroups = useRef(new Set<string>());
  const wasActive = useRef(false);
  const pageCount = useRef(0);
  const revalidationFailed = useRef(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => subscribeDashboardSession(() => {
    if (sessionRef.current && isDashboardSessionCurrent(sessionRef.current)) return;
    seq.current++;
    aborted.current?.abort();
    pending.current = false;
    scopeRef.current = null;
    sessionRef.current = null;
    setItems([]);
    setScopeVisible(null);
    setHasMore(false);
    setFailure(null);
    setDenied(false);
    setSessionVersion(x => x + 1);
  }), []);

  const visibleScope = useMemo(() => JSON.stringify([
    locationId, refreshKey, sessionVersion, exactReference !== null ? "EXACT_STK" : "FUZZY",
    exactReference ?? search.trim(), exactReference !== null ? "AUDIT_ADJUSTMENT" : movementType,
  ]), [locationId, refreshKey, sessionVersion, exactReference, search, movementType]);
  const queryScope = useMemo(() => JSON.stringify([
    locationId, refreshKey, sessionVersion, exactReference !== null ? "EXACT_STK" : "FUZZY",
    exactReference ?? debounced, exactReference !== null ? "AUDIT_ADJUSTMENT" : movementType,
  ]), [locationId, refreshKey, sessionVersion, exactReference, debounced, movementType]);

  const fetchPage = useCallback(async (cursor: string | null, reset: boolean) => {
    const session = sessionRef.current;
    if (!active || pending.current || scopeRef.current !== queryScope ||
      !session || !isDashboardSessionCurrent(session)) return;
    const requestId = ++seq.current;
    pending.current = true;
    const controller = new AbortController();
    aborted.current?.abort();
    aborted.current = controller;
    if (reset) setLoading(true);
    else setLoadingMore(true);
    setError(false);
    setFailure(null);
    try {
      const page = parseLedgerOperationPage(await authFetch(buildLedgerOperationUrl({
        locationId, cursor, search: exactReference === null ? debounced : undefined,
        referenceType: exactReference !== null ? "AUDIT_ADJUSTMENT" : movementType,
        referenceId: exactReference ?? undefined,
      }), { signal: controller.signal }));
      if (requestId !== seq.current || scopeRef.current !== queryScope ||
        !isDashboardSessionCurrent(session)) return;
      if (page.has_more && (!page.next_cursor || seenCursors.current.has(page.next_cursor))) {
        throw new Error("LEDGER_GROUP_CURSOR_STALLED");
      }
      if (page.has_more && page.next_cursor) seenCursors.current.add(page.next_cursor);
      const fresh = page.items.filter(item => {
        if (seenGroups.current.has(item.group_key)) return false;
        seenGroups.current.add(item.group_key);
        return true;
      });
      setItems(old => reset ? fresh : [...old, ...fresh]);
      pageCount.current = reset ? 1 : pageCount.current + 1;
      cursorRef.current = page.next_cursor;
      setHasMore(page.has_more);
      if (reset) {
        setScopeVisible(queryScope);
        setDenied(false);
        setAuthorizedProof({ scope: queryScope, sequence: ++proofSerial.current });
      }
    } catch (err) {
      if (requestId !== seq.current || scopeRef.current !== queryScope ||
        !isDashboardSessionCurrent(session)) return;
      if (err instanceof Error && err.name === "AbortError") return;
      const status = Number((err as { status?: unknown } | null)?.status);
      if (status === 401 || status === 403 || status === 404) {
        setItems([]);
        setScopeVisible(null);
        setHasMore(false);
        cursorRef.current = null;
        pageCount.current = 0;
        seenCursors.current.clear();
        seenGroups.current.clear();
        revalidationFailed.current = false;
        setFailure(null);
        setError(false);
        setDenied(true);
      } else {
        if (reset) setScopeVisible(queryScope);
        setFailure(parseLedgerOperationFailure(err));
        setError(true);
      }
    } finally {
      if (requestId === seq.current) {
        pending.current = false;
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [active, authFetch, debounced, exactReference, locationId, movementType, queryScope]);

  const revalidate = useCallback(async () => {
    // Return to this exact authorized scope: keep its scroll/rows while
    // rechecking the current warehouse bearer grant on the server.
    const session = sessionRef.current;
    if (!session || pending.current || !isDashboardSessionCurrent(session)) return;
    const requestId = ++seq.current;
    pending.current = true;
    const controller = new AbortController();
    aborted.current?.abort();
    aborted.current = controller;
    revalidationFailed.current = false;
    setLoadingMore(false);
    setLoading(true);
    setFailure(null);
    try {
      const page = parseLedgerOperationPage(await authFetch(buildLedgerOperationUrl({
        locationId,
        search: exactReference === null ? debounced : undefined,
        referenceType: exactReference !== null ? "AUDIT_ADJUSTMENT" : movementType,
        referenceId: exactReference ?? undefined,
      }), { signal: controller.signal }));
      if (requestId !== seq.current || scopeRef.current !== queryScope ||
        !isDashboardSessionCurrent(session)) return;
      // Only page-one lists can be safely replaced by page-one results.
      // If already appended, retain the signed original continuation snapshot.
      if (pageCount.current <= 1) {
        pageCount.current = 1;
        setItems(page.items);
        seenGroups.current = new Set(page.items.map(item => item.group_key));
        setHasMore(page.has_more);
        cursorRef.current = page.next_cursor;
        seenCursors.current = new Set(page.next_cursor ? [page.next_cursor] : []);
      }
      setScopeVisible(queryScope);
      setDenied(false);
      setAuthorizedProof({ scope: queryScope, sequence: ++proofSerial.current });
      revalidationFailed.current = false;
      setFailure(null);
      setError(false);
    } catch (failure) {
      if (requestId !== seq.current || !isDashboardSessionCurrent(session)) return;
      const status = Number((failure as { status?: unknown } | null)?.status);
      if (status === 401 || status === 403 || status === 404) {
        setItems([]);
        setScopeVisible(null);
        setHasMore(false);
        cursorRef.current = null;
        pageCount.current = 0;
        seenCursors.current.clear();
        seenGroups.current.clear();
        revalidationFailed.current = false;
        setFailure(null);
        setError(false);
        setDenied(true);
      } else if (!(failure instanceof Error && failure.name === "AbortError")) {
        revalidationFailed.current = true;
        setScopeVisible(queryScope);
        setFailure(parseLedgerOperationFailure(failure));
        setError(true);
      }
    } finally {
      if (requestId === seq.current) {
        pending.current = false;
        setLoading(false);
      }
    }
  }, [authFetch, debounced, exactReference, locationId, movementType, queryScope]);

  useEffect(() => {
    if (!active) {
      wasActive.current = false;
      seq.current++;
      aborted.current?.abort();
      pending.current = false;
      setLoadingMore(false);
      return;
    }
    const returning = !wasActive.current;
    wasActive.current = true;
    if (scopeRef.current !== queryScope) {
      seq.current++;
      aborted.current?.abort();
      pending.current = false;
      scopeRef.current = queryScope;
      sessionRef.current = captureDashboardSession();
      cursorRef.current = null;
      seenCursors.current = new Set();
      seenGroups.current = new Set();
      pageCount.current = 0;
      setFailure(null);
      setError(false);
      setItems([]);
      setHasMore(false);
      setScopeVisible(null);
      setDenied(false);
      void fetchPage(null, true);
    } else if (returning) {
      void revalidate();
    }
    return () => {
      seq.current++;
      aborted.current?.abort();
      pending.current = false;
      setLoadingMore(false);
    };
  }, [active, queryScope, fetchPage, revalidate]);

  const loadMore = useCallback(() => {
    if (active && !pending.current && !error && hasMore && cursorRef.current &&
      scopeVisible === visibleScope && !denied) {
      void fetchPage(cursorRef.current, false);
    }
  }, [active, denied, error, fetchPage, hasMore, scopeVisible, visibleScope]);
  const refresh = useCallback(() => {
    seq.current++;
    aborted.current?.abort();
    pending.current = false;
    cursorRef.current = null;
    seenCursors.current.clear();
    seenGroups.current.clear();
    pageCount.current = 0;
    setFailure(null);
    setError(false);
    revalidationFailed.current = false;
    setItems([]);
    setScopeVisible(null);
    setHasMore(false);
    void fetchPage(null, true);
  }, [fetchPage]);
  const retry = useCallback(() => {
    if (denied) return;
    if (revalidationFailed.current) { void revalidate(); return; }
    void fetchPage(cursorRef.current, items.length === 0);
  }, [denied, fetchPage, items.length, revalidate]);

  const admitted = scopeVisible === visibleScope && !denied;
  return {
    items: admitted ? items : [], loading: loading || (!admitted && !denied && !error),
    loadingMore, hasMore: admitted && hasMore, error: admitted && error,
    failure: admitted && error ? failure : null,
    denied, authorizedProof, loadMore, retry, refresh, visibleScope,
  };
}
