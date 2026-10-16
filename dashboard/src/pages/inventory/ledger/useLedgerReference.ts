import { useCallback, useEffect, useRef, useState } from "react";

import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseLedgerPage, type LedgerEntry } from "./contracts";
import { buildLedgerCursorUrl } from "./useLedgerQuery";

const REFERENCE_PAGE_SIZE = 100;
const MAX_REFERENCE_PAGES = 50;

export interface LedgerReferenceState {
  entry: LedgerEntry | null;
  items: LedgerEntry[];
  loading: boolean;
  error: boolean;
  open: (entry: LedgerEntry) => void;
  retry: () => void;
  close: () => void;
}

export function useLedgerReference(locationId: number): LedgerReferenceState {
  const authFetch = useAuthFetch();
  const [entry, setEntry] = useState<LedgerEntry | null>(null);
  const [items, setItems] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async (target: LedgerEntry) => {
    if (!target.reference) return;
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
            locationId,
            cursor,
            referenceType: target.reference_type,
            referenceId: target.reference,
            limit: REFERENCE_PAGE_SIZE,
          }),
          { signal: controller.signal },
        ));
        if (sequence !== requestSeq.current) return;

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
      if (failure instanceof Error && failure.name === "AbortError") return;
      setError(true);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (sequence === requestSeq.current) setLoading(false);
    }
  }, [authFetch, locationId]);

  const open = useCallback((target: LedgerEntry) => {
    if (!target.reference) return;
    setEntry(target);
    void load(target);
  }, [load]);

  const retry = useCallback(() => {
    if (entry) void load(entry);
  }, [entry, load]);

  const close = useCallback(() => {
    requestSeq.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setEntry(null);
    setItems([]);
    setError(false);
    setLoading(false);
  }, []);

  useEffect(() => () => {
    requestSeq.current += 1;
    abortRef.current?.abort();
  }, []);

  return { entry, items, loading, error, open, retry, close };
}
