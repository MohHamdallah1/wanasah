import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  getErrorMessage,
  parseStocktakeSessionPage,
} from "../parsers";
import type {
  StocktakeAuthFetch,
  StocktakeSessionSummary,
} from "../types";

interface UseStocktakeSessionsArgs {
  locationId: number;
  authenticatedFetch: StocktakeAuthFetch;
}

export function useStocktakeSessions({
  locationId,
  authenticatedFetch,
}: UseStocktakeSessionsArgs) {
  const [sessions, setSessions] = useState<
    StocktakeSessionSummary[]
  >([]);
  const [total, setTotal] = useState<number | null>(null);
  const [nextCursor, setNextCursor] =
    useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const requestSeq = useRef(0);

  const fetchSessions = useCallback(
    async (
      cursor: string | null = null,
      append = false
    ) => {
      const seq = ++requestSeq.current;

      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
        setLoadFailed(false);
        setNextCursor(null);
      }

      try {
        const params = new URLSearchParams({
          location_id: String(locationId),
          limit: "50",
        });
        if (cursor) params.set("cursor", cursor);

        const raw = await authenticatedFetch(
          `/warehouse/unified/stocktakes/active?${params.toString()}`
        );

        if (seq !== requestSeq.current) return;

        const page = parseStocktakeSessionPage(
          raw,
          locationId
        );

        setSessions((prev) => {
          if (!append) return page.items;

          const merged = new Map<
            number,
            StocktakeSessionSummary
          >();
          for (const item of prev) {
            merged.set(item.id, item);
          }
          for (const item of page.items) {
            merged.set(item.id, item);
          }
          return [...merged.values()];
        });

        setNextCursor(page.next_cursor);
        if (page.total !== null) {
          setTotal(page.total);
        }
      } catch (error: unknown) {
        if (seq !== requestSeq.current) return;

        if (!append) {
          setSessions([]);
          setTotal(null);
          setNextCursor(null);
          setLoadFailed(true);
        }

        toast.error(
          getErrorMessage(
            error,
            "فشل جلب جلسات الجرد النشطة."
          )
        );
      } finally {
        if (seq === requestSeq.current) {
          if (append) {
            setLoadingMore(false);
          } else {
            setLoading(false);
          }
        }
      }
    },
    [authenticatedFetch, locationId]
  );

  useEffect(() => {
    setSessions([]);
    setTotal(null);
    setNextCursor(null);
    void fetchSessions(null, false);
  }, [fetchSessions, locationId]);

  const refreshSessions = useCallback(() => {
    void fetchSessions(null, false);
  }, [fetchSessions]);

  const loadMore = useCallback(() => {
    if (!nextCursor || loadingMore) return;
    void fetchSessions(nextCursor, true);
  }, [
    fetchSessions,
    loadingMore,
    nextCursor,
  ]);

  return {
    sessions,
    total,
    nextCursor,
    loading,
    loadingMore,
    loadFailed,
    refreshSessions,
    loadMore,
  };
}
