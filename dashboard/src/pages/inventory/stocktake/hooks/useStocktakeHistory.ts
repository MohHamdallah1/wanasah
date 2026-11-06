import { useCallback, useEffect, useRef, useState } from "react";
import type { StocktakeAuthFetch } from "../types";

export type HistoryStatus = "POSTED" | "CANCELLED";
export interface HistoryItem {
  id: number; reference_number: string; stocktake_type: string; status: HistoryStatus;
  location_id: number; scope_product_name: string | null; scope_batch_number: string | null;
  started_by_name: string | null; approved_by_name: string | null;
  cancelled_by_name: string | null; counted_by_name: string | null;
  attempt_number: number | null; cancelled_after_count: boolean;
  cancellation_reason: string | null; created_at: string; finished_at: string | null;
}
export interface HistoryAttempt {
  id: number; attempt_number: number; counted_by_name: string | null;
  authorized_by_name: string | null; recount_reason: string | null;
  submitted_at: string | null; requires_independent_recount: boolean;
}
export interface HistoryLine {
  id: number; product_name: string; batch_id: number; batch_number: string | null;
  stock_status: string; line_origin: string; base_uom_name: string; base_uom_code: string;
  expected_quantity: string; actual_quantity: string; variance_quantity: string;
}
export interface HistoryAudit {
  id: number; action_type: string; actor_name: string | null; at: string | null;
  old_value: string | null; new_value: string | null;
}
export interface HistoryDetail {
  session_id: number; reference_number: string; status: HistoryStatus;
  stocktake_type: string; scope_product_name: string | null; scope_batch_number: string | null;
  cancellation_reason: string | null; cancelled_after_count: boolean;
  created_at: string; finished_at: string | null; notes: string | null;
  started_by_name: string | null; approved_by_name: string | null; cancelled_by_name: string | null;
  attempts: HistoryAttempt[]; next_cursor: string | null; audit: HistoryAudit[];
  audit_next_cursor: string | null;
}
export interface HistoryFailure {
  status: number | null; code: string | null; requestId: string | null;
  reason: string | null;
}
const safeFailure = (value: unknown): HistoryFailure => {
  const error = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const status = typeof error.status === "number" ? error.status
    : typeof error.statusCode === "number" ? error.statusCode : null;
  const context = error.context && typeof error.context === "object"
    ? error.context as Record<string, unknown> : {};
  const requestId = [error.requestId, error.request_id, context.correlation_id]
    .find(v => typeof v === "string");
  const code = typeof error.code === "string" ? error.code : null;
  const reason = status !== null && status >= 400 && status < 500
    ? (typeof error.message === "string" ? error.message : null)
    : null;
  return {
    status, code, requestId: typeof requestId === "string" ? requestId : null,
    reason,
  };
};
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid history response");
  return value as Record<string, unknown>;
};
const cursor = (value: unknown): string | null => typeof value === "string" ? value : null;
const items = (value: unknown): Record<string, unknown>[] => {
  if (!Array.isArray(value)) throw new Error("Invalid history items");
  return value.map(record);
};
const asNumber = (value: unknown): number => {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value <= 0) throw new Error("Invalid history identifier");
  return value;
};
const asString = (value: unknown): string => typeof value === "string" ? value : "";
const asOptional = (value: unknown): string | null => typeof value === "string" ? value : null;

const parseItem = (row: Record<string, unknown>, locationId: number): HistoryItem => {
  if (row.status !== "POSTED" && row.status !== "CANCELLED") throw new Error("Nonterminal history");
  if (row.location_id !== locationId) throw new Error("History location mismatch");
  return {
    id: asNumber(row.id), reference_number: asString(row.reference_number),
    stocktake_type: asString(row.stocktake_type), status: row.status,
    location_id: locationId, scope_product_name: asOptional(row.scope_product_name),
    scope_batch_number: asOptional(row.scope_batch_number),
    started_by_name: asOptional(row.started_by_name), approved_by_name: asOptional(row.approved_by_name),
    cancelled_by_name: asOptional(row.cancelled_by_name), counted_by_name: asOptional(row.counted_by_name),
    attempt_number: typeof row.attempt_number === "number" ? row.attempt_number : null,
    cancelled_after_count: row.cancelled_after_count === true,
    cancellation_reason: asOptional(row.cancellation_reason),
    created_at: asString(row.created_at), finished_at: asOptional(row.finished_at),
  };
};
const parseDetail = (raw: unknown, id: number): HistoryDetail => {
  const row = record(raw);
  if (row.session_id !== id || (row.status !== "POSTED" && row.status !== "CANCELLED")) {
    throw new Error("Invalid terminal session details");
  }
  return {
    session_id: id, reference_number: asString(row.reference_number),
    stocktake_type: asString(row.stocktake_type), scope_product_name: asOptional(row.scope_product_name),
    scope_batch_number: asOptional(row.scope_batch_number),
    status: row.status, cancellation_reason: asOptional(row.cancellation_reason),
    cancelled_after_count: row.cancelled_after_count === true,
    created_at: asString(row.created_at), finished_at: asOptional(row.finished_at),
    notes: asOptional(row.notes), started_by_name: asOptional(row.started_by_name),
    approved_by_name: asOptional(row.approved_by_name), cancelled_by_name: asOptional(row.cancelled_by_name),
    attempts: items(row.attempts).map(a => ({
      id: asNumber(a.id), attempt_number: asNumber(a.attempt_number),
      counted_by_name: asOptional(a.counted_by_name), authorized_by_name: asOptional(a.authorized_by_name),
      recount_reason: asOptional(a.recount_reason), submitted_at: asOptional(a.submitted_at),
      requires_independent_recount: a.requires_independent_recount === true,
    })),
    next_cursor: cursor(row.next_cursor),
    audit_next_cursor: cursor(row.audit_next_cursor),
    audit: items(row.audit).map(a => ({
      id: asNumber(a.id), action_type: asString(a.action_type),
      actor_name: asOptional(a.actor_name), at: asOptional(a.at),
      old_value: asOptional(a.old_value), new_value: asOptional(a.new_value),
    })),
  };
};

export function useStocktakeHistory({
  enabled, locationId, authenticatedFetch,
}: { enabled: boolean; locationId: number; authenticatedFetch: StocktakeAuthFetch }) {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [selectedAttemptId, setSelectedAttemptId] = useState<number | null>(null);
  const [lines, setLines] = useState<HistoryLine[]>([]);
  const [lineCursor, setLineCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<HistoryFailure | null>(null);
  const version = useRef(0);

  useEffect(() => {
    const seq = ++version.current;
    setHistory([]); setDetail(null); setSelectedAttemptId(null);
    setLines([]); setLineCursor(null); setNextCursor(null); setError(null);
    if (!enabled || locationId <= 0) { setBusy(false); return; }
    setBusy(true);
    void (async () => {
      try {
        const raw = record(await authenticatedFetch(
          `/warehouse/unified/stocktakes/history?location_id=${locationId}&limit=50`,
        ));
        if (seq !== version.current) return;
        setHistory(items(raw.items).map(v => parseItem(v, locationId)));
        setNextCursor(cursor(raw.next_cursor));
      } catch (failure: unknown) {
        if (seq === version.current) setError(safeFailure(failure));
      } finally {
        if (seq === version.current) setBusy(false);
      }
    })();
    return () => { version.current += 1; };
  }, [enabled, locationId, authenticatedFetch]);

  const moreHistory = useCallback(async () => {
    if (!enabled || busy || !nextCursor) return;
    const seq = ++version.current;
    setBusy(true);
    try {
      const url = `/warehouse/unified/stocktakes/history?location_id=${locationId}&limit=50&cursor=${encodeURIComponent(nextCursor)}`;
      const raw = record(await authenticatedFetch(url));
      if (seq !== version.current) return;
      const entries = items(raw.items).map(v => parseItem(v, locationId));
      setHistory(prev => [...prev, ...entries.filter(x => !prev.some(p => p.id === x.id))]);
      setNextCursor(cursor(raw.next_cursor));
    } catch (failure: unknown) { if (seq === version.current) setError(safeFailure(failure)); }
    finally { if (seq === version.current) setBusy(false); }
  }, [enabled, busy, nextCursor, locationId, authenticatedFetch]);

  const loadDetails = useCallback(async (id: number) => {
    if (!enabled) return;
    const seq = ++version.current;
    setBusy(true); setError(null); setDetail(null); setSelectedAttemptId(null); setLines([]);
    try {
      const next = parseDetail(await authenticatedFetch(`/warehouse/unified/stocktake/${id}/history`), id);
      if (seq !== version.current) return;
      setDetail(next);
    } catch (failure: unknown) { if (seq === version.current) setError(safeFailure(failure)); }
    finally { if (seq === version.current) setBusy(false); }
  }, [enabled, authenticatedFetch]);

  const moreAttempts = useCallback(async () => {
    if (!detail?.next_cursor || busy) return;
    const seq = ++version.current;
    setBusy(true);
    try {
      const raw = parseDetail(await authenticatedFetch(
        `/warehouse/unified/stocktake/${detail.session_id}/history?cursor=${encodeURIComponent(detail.next_cursor)}`,
      ), detail.session_id);
      if (seq !== version.current) return;
      setDetail(prev => prev && ({
        ...prev, next_cursor: raw.next_cursor,
        attempts: [...prev.attempts, ...raw.attempts],
      }));
    } catch (failure: unknown) { if (seq === version.current) setError(safeFailure(failure)); }
    finally { if (seq === version.current) setBusy(false); }
  }, [detail, busy, authenticatedFetch]);

  const moreAudit = useCallback(async () => {
    if (!detail?.audit_next_cursor || busy) return;
    const seq = ++version.current;
    setBusy(true);
    try {
      const url = `/warehouse/unified/stocktake/${detail.session_id}/history?audit_cursor=${encodeURIComponent(detail.audit_next_cursor)}`;
      const raw = parseDetail(await authenticatedFetch(url), detail.session_id);
      if (seq !== version.current) return;
      setDetail(prev => prev && ({
        ...prev,
        audit_next_cursor: raw.audit_next_cursor,
        audit: [...prev.audit, ...raw.audit.filter(e => !prev.audit.some(p => p.id === e.id))],
      }));
    } catch (failure: unknown) {
      if (seq === version.current) setError(safeFailure(failure));
    } finally {
      if (seq === version.current) setBusy(false);
    }
  }, [detail, busy, authenticatedFetch]);

  const loadLines = useCallback(async (attemptId: number, after?: string) => {
    if (!detail || !enabled) return;
    const seq = ++version.current;
    setBusy(true); setError(null);
    if (!after) { setSelectedAttemptId(attemptId); setLines([]); setLineCursor(null); }
    try {
      const url = `/warehouse/unified/stocktake/${detail.session_id}/history/attempts/${attemptId}/lines?limit=100` +
        (after ? `&cursor=${encodeURIComponent(after)}` : "");
      const raw = record(await authenticatedFetch(url));
      if (seq !== version.current) return;
      const mapped = items(raw.items).map(a => ({
        id: asNumber(a.id), product_name: asString(a.product_name),
        batch_id: asNumber(a.batch_id), batch_number: asOptional(a.batch_number),
        stock_status: asString(a.stock_status), line_origin: asString(a.line_origin),
        base_uom_name: asString(a.base_uom_name), base_uom_code: asString(a.base_uom_code),
        expected_quantity: asString(a.expected_quantity), actual_quantity: asString(a.actual_quantity),
        variance_quantity: asString(a.variance_quantity),
      }));
      setLines(prev => after ? [...prev, ...mapped] : mapped);
      setLineCursor(cursor(raw.next_cursor));
    } catch (failure: unknown) { if (seq === version.current) setError(safeFailure(failure)); }
    finally { if (seq === version.current) setBusy(false); }
  }, [detail, enabled, authenticatedFetch]);

  const back = useCallback(() => {
    version.current += 1;
    setDetail(null); setSelectedAttemptId(null); setLines([]); setLineCursor(null); setBusy(false); setError(null);
  }, []);

  return {
    history, nextCursor, detail, selectedAttemptId, lines, lineCursor,
    busy, error, moreHistory, loadDetails, moreAttempts, moreAudit, loadLines, back,
  };
}
