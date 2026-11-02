import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import {
  captureDashboardSession, isDashboardSessionCurrent, subscribeDashboardSession,
  type DashboardSession,
} from "@/lib/authStorage";
import { parseLedgerPage, type LedgerEntry } from "./contracts";
import { buildLedgerCursorUrl } from "./useLedgerQuery";

const REFERENCE_PAGE_SIZE = 100;
const MAX_REFERENCE_PAGES = 50;

export interface LedgerReferenceState {
  entry: LedgerEntry | null;
  items: LedgerEntry[];
  loading: boolean;
  error: boolean;
  denied: boolean;
  open: (entry: LedgerEntry) => void;
  retry: () => void;
  close: () => void;
}

export function useLedgerReference(locationId: number, active = true): LedgerReferenceState {
  const authFetch = useAuthFetch();
  const [entry, setEntry] = useState<LedgerEntry | null>(null);
  const [items, setItems] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [denied, setDenied] = useState(false);
  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const scopeRef = useRef<{ locationId: number; session: DashboardSession } | null>(null);

  const clear = useCallback((accessLost = false) => {
    requestSeq.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    scopeRef.current = null;
    setEntry(null);
    setItems([]);
    setLoading(false);
    setError(false);
    setDenied(accessLost);
  }, []);

  const isCurrent = useCallback((scope: { locationId: number; session: DashboardSession }) =>
    active && scopeRef.current === scope && locationId === scope.locationId &&
    isDashboardSessionCurrent(scope.session), [active, locationId]);

  const load = useCallback(async (target: LedgerEntry, scope: { locationId: number; session: DashboardSession }) => {
    if (!target.reference || !isCurrent(scope)) { clear(true); return; }
    const sequence = ++requestSeq.current;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(false);
    setItems([]);

    const loaded: LedgerEntry[] = [];
    const movementIds = new Set<number>();
    const cursors = new Set<string>();
    let cursor: string | null = null;

    try {
      for (let pageIndex = 0; pageIndex < MAX_REFERENCE_PAGES; pageIndex += 1) {
        const page = parseLedgerPage(await authFetch(
          buildLedgerCursorUrl({
            locationId: scope.locationId,
            cursor,
            referenceType: target.reference_type,
            referenceId: target.reference,
            limit: REFERENCE_PAGE_SIZE,
          }),
          { signal: controller.signal },
        ));
        if (sequence !== requestSeq.current) return;
        if (!isCurrent(scope)) { clear(true); return; }

        for (const item of page.items) {
          if (movementIds.has(item.id)) throw new Error("LEDGER_REFERENCE_DUPLICATE_MOVEMENT");
          movementIds.add(item.id);
          loaded.push(item);
        }
        setItems([...loaded]);

        if (!page.has_more) return;
        if (!page.next_cursor || cursors.has(page.next_cursor)) {
          throw new Error("LEDGER_REFERENCE_CURSOR_LOOP");
        }
        cursors.add(page.next_cursor);
        cursor = page.next_cursor;
      }
      throw new Error("LEDGER_REFERENCE_PAGE_BOUND_EXCEEDED");
    } catch (failure) {
      if (sequence !== requestSeq.current) return;
      if (!isCurrent(scope)) { clear(true); return; }
      const status = Number((failure as { status?: unknown } | null)?.status);
      if (status === 401 || status === 403) {
        // A later denied page must purge even formerly authorized reference rows.
        clear(true);
        return;
      }
      if (failure instanceof Error && failure.name === "AbortError") return;
      setError(true);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (sequence === requestSeq.current) setLoading(false);
    }
  }, [authFetch, clear, isCurrent]);

  const open = useCallback((target: LedgerEntry) => {
    if (!active || !target.reference || denied) return;
    const scope = { locationId, session: captureDashboardSession() };
    scopeRef.current = scope;
    setEntry(target);
    setDenied(false);
    void load(target, scope);
  }, [active, denied, load, locationId]);

  const retry = useCallback(() => {
    const scope = scopeRef.current;
    if (entry && scope && isCurrent(scope)) void load(entry, scope);
    else if (scope) clear(true);
  }, [clear, entry, isCurrent, load]);

  useEffect(() => {
    if (!active) clear();
    const unsubscribe = subscribeDashboardSession(() => {
      const scope = scopeRef.current;
      if (scope && !isDashboardSessionCurrent(scope.session)) clear(true);
    });
    return () => { unsubscribe(); clear(); };
  }, [active, clear, locationId]);

  const scope = scopeRef.current;
  const visible = scope !== null && isCurrent(scope);
  return {
    entry: visible ? entry : null,
    items: visible ? items : [],
    loading: visible && loading,
    error: visible && error,
    denied: denied || (active && scope !== null && !visible),
    open, retry, close: () => clear(),
  };
}
