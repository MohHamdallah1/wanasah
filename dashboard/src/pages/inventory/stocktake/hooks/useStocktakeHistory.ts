import { useCallback, useEffect, useRef, useState } from "react";
import type { StocktakeAuthFetch } from "../types";
import { apiErrorMessage } from "@/lib/apiErrors";
import i18n from "@/i18n";

export interface HistorySession {
  id: number; reference_number: string; status: "POSTED" | "CANCELLED";
  stocktake_type: "FULL_COUNT" | "CYCLE_COUNT"; location_id: number;
  scope_product_name: string | null; scope_batch_number: string | null;
  created_at: string; finished_at: string; started_by_name: string;
  counted_by_name: string | null; attempt_number: number | null;
  approved_by_name: string | null; cancelled_by_name: string | null;
  cancellation_reason: string | null; cancelled_after_count: boolean;
}
export interface HistoryAttempt {
  id: number; attempt_number: number; counted_by_name: string;
  submitted_at: string; recount_reason: string | null;
  authorized_by_name: string | null;
  requires_independent_recount: boolean; recount_of_attempt_id: number | null;
}
export interface HistoryLine {
  id: number; product_name: string; batch_number: string | null;
  stock_status: string; line_origin: "SNAPSHOT" | "DISCOVERED";
  base_uom_name: string; expected_quantity: string;
  actual_quantity: string; variance_quantity: string;
}
export interface HistoryAudit {
  id: number; action_type: string; actor_name: string | null;
  timestamp: string; details: Record<string, string | number | boolean>;
}
export interface HistoryMovement {
  id: number; reference_id: string; quantity: string;
  product_variant_id: number; batch_id: number;
}
export interface HistoryPage<T> {
  items: T[]; next_cursor: string | null; has_more: boolean;
}
export interface HistoryDetail {
  session: {
    id: number; reference_number: string; status: "POSTED" | "CANCELLED";
    stocktake_type: "FULL_COUNT" | "CYCLE_COUNT"; location_id: number;
    created_at: string; finished_at: string; snapshot_cutoff_at: string | null;
    scope_product_name: string | null; scope_batch_number: string | null;
    cancellation_reason: string | null; notes: string | null;
    started_by_name: string | null; approved_by_name: string | null;
    cancelled_by_name: string | null;
    cancelled_after_count: boolean; adjustment_movement_count: number;
  };
  attempts: HistoryPage<HistoryAttempt>;
  audit: HistoryPage<HistoryAudit>;
  movements: HistoryPage<HistoryMovement>;
}
const BASE = "/warehouse/unified/stocktakes/history";
const params = (locationId: number, cursor: string | null, limit = 50): string => {
  const query = new URLSearchParams({ location_id: String(locationId), limit: String(limit) });
  if (cursor) query.set("cursor", cursor);
  return query.toString();
};
function pageOf<T>(raw: unknown): HistoryPage<T> {
  if (!raw || typeof raw !== "object") throw Error("Invalid stocktake history response.");
  const data = raw as Record<string, unknown>;
  if (!Array.isArray(data.items) ||
    (data.next_cursor !== null && typeof data.next_cursor !== "string") ||
    typeof data.has_more !== "boolean") throw Error("Invalid stocktake history page.");
  return data as unknown as HistoryPage<T>;
}
interface Args {
  enabled: boolean; locationId: number; authenticatedFetch: StocktakeAuthFetch;
}
export function useStocktakeHistory({ enabled, locationId, authenticatedFetch }: Args) {
  const [sessions, setSessions] = useState<HistorySession[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [lines, setLines] = useState<HistoryLine[]>([]);
  const [linesNext, setLinesNext] = useState<string | null>(null);
  const [attemptId, setAttemptId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingLines, setLoadingLines] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef({ list: 0, detail: 0, lines: 0 });
  const fetchList = useCallback(async (cursor: string | null = null) => {
    if (!enabled) return;
    const version = ++seq.current.list;
    if (cursor) setLoadingMore(true);
    else { setLoading(true); setError(null); }
    try {
      const response = pageOf<HistorySession>(await authenticatedFetch(
        BASE + "?" + params(locationId, cursor)
      ));
      if (version !== seq.current.list) return;
      if (response.items.some(item => item.location_id !== locationId ||
        !["POSTED", "CANCELLED"].includes(item.status))) throw Error("History scope mismatch.");
      setSessions(current => cursor
        ? [...current, ...response.items.filter(item => !current.some(old => old.id === item.id))]
        : response.items);
      setNext(response.next_cursor);
    } catch (cause: unknown) {
      if (version === seq.current.list) {
        if (!cursor) { setSessions([]); setNext(null); }
        setError(apiErrorMessage(cause, i18n.t("errors.unexpected")));
      }
    } finally {
      if (version === seq.current.list) { setLoading(false); setLoadingMore(false); }
    }
  }, [authenticatedFetch, enabled, locationId]);

  const selectAttempt = useCallback(async (
    sessionId: number, nextAttemptId: number, cursor: string | null = null
  ) => {
    if (!enabled) return;
    const version = ++seq.current.lines;
    if (!cursor) { setAttemptId(nextAttemptId); setLines([]); setLinesNext(null); }
    setLoadingLines(true);
    try {
      const response = pageOf<HistoryLine>(await authenticatedFetch(
        BASE + "/" + sessionId + "/attempts/" + nextAttemptId + "/lines?" +
          params(locationId, cursor, 100)
      ));
      if (version !== seq.current.lines) return;
      setLines(current => cursor
        ? [...current, ...response.items.filter(item => !current.some(old => old.id === item.id))]
        : response.items);
      setLinesNext(response.next_cursor);
    } catch (cause: unknown) {
      if (version === seq.current.lines) setError(apiErrorMessage(cause, i18n.t("errors.unexpected")));
    } finally { if (version === seq.current.lines) setLoadingLines(false); }
  }, [authenticatedFetch, enabled, locationId]);

  const selectSession = useCallback(async (id: number) => {
    if (!enabled) return;
    const version = ++seq.current.detail;
    ++seq.current.lines;
    ++seq.current.list; // Abandon obsolete list pagination while reviewing a new session.
    setDetail(null); setLines([]); setLinesNext(null); setAttemptId(null);
    setError(null); setLoading(false); setLoadingMore(false);
    setLoadingLines(false); setLoadingDetail(true);
    try {
      const response = await authenticatedFetch(BASE + "/" + id + "?" + params(locationId, null));
      if (version !== seq.current.detail) return;
      if (!response || typeof response !== "object" || !("session" in response)) {
        throw Error("Invalid history detail.");
      }
      const loaded = response as unknown as HistoryDetail;
      if (loaded.session.id !== id || loaded.session.location_id !== locationId ||
        !["POSTED", "CANCELLED"].includes(loaded.session.status)) throw Error("History scope mismatch.");
      setDetail(loaded);
      if (loaded.attempts.items[0]) void selectAttempt(id, loaded.attempts.items[0].id);
    } catch (cause: unknown) {
      if (version === seq.current.detail) setError(apiErrorMessage(cause, i18n.t("errors.unexpected")));
    } finally { if (version === seq.current.detail) setLoadingDetail(false); }
  }, [authenticatedFetch, enabled, locationId, selectAttempt]);

  const loadDetailPage = useCallback(async (kind: "attempts" | "audit" | "movements") => {
    if (!detail || !enabled) return;
    const cursor = detail[kind].next_cursor;
    if (!cursor || loadingMore) return;
    const version = seq.current.detail;
    setLoadingMore(true);
    try {
      const response = pageOf<HistoryAttempt | HistoryAudit | HistoryMovement>(await authenticatedFetch(
        BASE + "/" + detail.session.id + "/" + kind + "?" + params(locationId, cursor)
      ));
      if (version !== seq.current.detail) return;
      setDetail(previous => {
        if (!previous || previous.session.id !== detail.session.id) return previous;
        if (kind === "attempts") {
          const nextPage = response as HistoryPage<HistoryAttempt>;
          return { ...previous, attempts: {
            ...nextPage, items: [...previous.attempts.items,
              ...nextPage.items.filter(item => !previous.attempts.items.some(old => old.id === item.id))]
          } };
        }
        if (kind === "audit") {
          const nextPage = response as HistoryPage<HistoryAudit>;
          return { ...previous, audit: {
            ...nextPage, items: [...previous.audit.items,
              ...nextPage.items.filter(item => !previous.audit.items.some(old => old.id === item.id))]
          } };
        }
        const nextPage = response as HistoryPage<HistoryMovement>;
        return { ...previous, movements: {
          ...nextPage, items: [...previous.movements.items,
            ...nextPage.items.filter(item => !previous.movements.items.some(old => old.id === item.id))]
        } };
      });
    } catch (cause: unknown) {
      if (version === seq.current.detail) setError(apiErrorMessage(cause, i18n.t("errors.unexpected")));
    } finally { if (version === seq.current.detail) setLoadingMore(false); }
  }, [authenticatedFetch, detail, enabled, locationId, loadingMore]);

  const back = useCallback(() => {
    // Invalidate all pending detail/line/list-page responses before resetting
    // every loading flag. An ignored stale finally cannot clear them itself.
    ++seq.current.list; ++seq.current.detail; ++seq.current.lines;
    setDetail(null); setLines([]); setLinesNext(null); setAttemptId(null);
    setLoading(false); setLoadingDetail(false); setLoadingLines(false);
    setLoadingMore(false); setError(null);
  }, []);
  useEffect(() => {
    ++seq.current.list; ++seq.current.detail; ++seq.current.lines;
    setSessions([]); setNext(null); setDetail(null); setLines([]); setLinesNext(null);
    setAttemptId(null); setError(null);
    setLoading(false); setLoadingMore(false); setLoadingDetail(false); setLoadingLines(false);
    if (enabled) void fetchList();
    return () => { ++seq.current.list; ++seq.current.detail; ++seq.current.lines; };
  }, [enabled, locationId, fetchList]);

  return {
    sessions, next, detail, lines, linesNext, attemptId, error,
    loading, loadingMore, loadingDetail, loadingLines,
    fetchList, selectSession, selectAttempt, loadDetailPage, back,
    loadMoreSessions: () => { if (next && !loadingMore) void fetchList(next); },
    loadMoreLines: () => { if (detail && attemptId && linesNext && !loadingLines)
      void selectAttempt(detail.session.id, attemptId, linesNext); },
  };
}
