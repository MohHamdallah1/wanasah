import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useStocktakeCopy } from "../copy";
import { getErrorMessage, parseStocktakeSessionPage } from "../parsers";
import type { StocktakeAuthFetch, StocktakeSessionSummary } from "../types";

interface UseStocktakeSessionsArgs {
  enabled: boolean;
  locationId: number;
  authenticatedFetch: StocktakeAuthFetch;
}

export function useStocktakeSessions({ enabled, locationId, authenticatedFetch }: UseStocktakeSessionsArgs) {
  const { copy } = useStocktakeCopy();
  const [sessions, setSessions] = useState<StocktakeSessionSummary[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const requestSeq = useRef(0);

  const fetchSessions = useCallback(async (cursor: string | null = null, append = false) => {
    if (!enabled) return;

    const seq = ++requestSeq.current;
    if (append) setLoadingMore(true);
    else { setLoading(true); setLoadFailed(false); setNextCursor(null); }

    try {
      const params = new URLSearchParams({ location_id: String(locationId), limit: "50" });
      if (cursor) params.set("cursor", cursor);
      const raw = await authenticatedFetch(`/warehouse/unified/stocktakes/active?${params.toString()}`);
      if (seq !== requestSeq.current) return;
      const page = parseStocktakeSessionPage(raw, locationId);
      setSessions((prev) => {
        if (!append) return page.items;
        const merged = new Map<number, StocktakeSessionSummary>();
        for (const item of prev) merged.set(item.id, item);
        for (const item of page.items) merged.set(item.id, item);
        return [...merged.values()];
      });
      setNextCursor(page.next_cursor);
      if (page.total !== null) setTotal(page.total);
    } catch (error: unknown) {
      if (seq !== requestSeq.current) return;
      if (!append) { setSessions([]); setTotal(null); setNextCursor(null); setLoadFailed(true); }
      toast.error(getErrorMessage(error, copy.generic.sessionsFailed));
    } finally {
      if (seq === requestSeq.current) append ? setLoadingMore(false) : setLoading(false);
    }
  }, [authenticatedFetch, copy.generic.sessionsFailed, enabled, locationId]);

  useEffect(() => {
    requestSeq.current += 1;
    setSessions([]);
    setTotal(null);
    setNextCursor(null);
    setLoading(false);
    setLoadingMore(false);
    setLoadFailed(false);
    if (enabled) void fetchSessions(null, false);
  }, [enabled, fetchSessions, locationId]);

  const refreshSessions = useCallback(() => {
    if (!enabled) return;
    void fetchSessions(null, false);
  }, [enabled, fetchSessions]);
  const loadMore = useCallback(() => {
    if (!enabled || !nextCursor || loadingMore) return;
    void fetchSessions(nextCursor, true);
  }, [enabled, fetchSessions, loadingMore, nextCursor]);

  return { sessions, total, nextCursor, loading, loadingMore, loadFailed, refreshSessions, loadMore };
}
