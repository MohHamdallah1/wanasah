import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { parseTransferDetail, parseTransferPage } from "../parsers";
import type { TransferDirection, TransferStatus, WarehouseTransferDetail, WarehouseTransferListItem } from "../types";
import { getErrorMessage } from "../utils";
import { useTransferTranslation } from "../i18n";

type PageState = { scope: string; items: WarehouseTransferListItem[]; cursor: string | null; history: Array<string | null>; next: string | null; total: number | null };
type Attempt = { cursor: string | null; history: Array<string | null>; phase: "first" | "refresh" | "continuation" };
export function useTransferList(locationId: number) {
  const authenticatedFetch = useAuthFetch();
  const { t } = useTransferTranslation();
  const [status, setStatus] = useState<TransferStatus | "">("");
  const [direction, setDirection] = useState<TransferDirection>("all");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState<PageState | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<{ scope: string; phase: Attempt["phase"]; message: string } | null>(null);
  const scope = JSON.stringify([locationId, status, direction, search]);
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const requestSeq = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const lastAttempt = useRef<Attempt>({ cursor: null, history: [], phase: "first" });
  const current = page?.scope === scope ? page : null;
  const [detailState, setDetail] = useState<{ locationId: number; value: WarehouseTransferDetail } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const detailRequestSeq = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const fetchPage = useCallback(async (attempt: Attempt) => {
    const seq = ++requestSeq.current;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    lastAttempt.current = attempt;
    setLoading(true);
    setFailure(null);
    try {
      const params = new URLSearchParams({ location_id: String(locationId), direction, limit: "50" });
      if (status) params.set("status", status);
      if (search) params.set("search", search);
      if (attempt.cursor) params.set("cursor", attempt.cursor);
      const raw = await authenticatedFetch(`/warehouse/unified/transfers?${params}`, { signal: controller.signal });
      if (seq !== requestSeq.current || scopeRef.current !== scope) return;
      const parsed = parseTransferPage(raw);
      if (parsed.items.some(row => row.source_location_id !== locationId && row.destination_location_id !== locationId)) {
        throw Object.assign(new Error(), { code: "TRANSFER_RESPONSE_INVALID" });
      }
      setPage(previous => ({ scope, items: parsed.items, cursor: attempt.cursor, history: attempt.history,
        next: parsed.next_cursor, total: parsed.total ?? (previous?.scope === scope ? previous.total : null) }));
    } catch (error) {
      if (seq !== requestSeq.current || scopeRef.current !== scope || controller.signal.aborted) return;
      const key = attempt.phase === "first" ? "firstFailure" : attempt.phase === "refresh" ? "refreshFailure" : "continuationFailure";
      setFailure({ scope, phase: attempt.phase, message: getErrorMessage(error, t(`inventoryTransfers.${key}`)) });
    } finally {
      if (seq === requestSeq.current && scopeRef.current === scope) setLoading(false);
    }
  }, [authenticatedFetch, locationId, direction, status, search, scope, t]);

  const invalidateList = useCallback(() => { ++requestSeq.current; abort.current?.abort(); }, []);
  const invalidateDetail = useCallback(() => { ++detailRequestSeq.current; }, []);
  useEffect(() => {
    void fetchPage({ cursor: null, history: [], phase: "first" });
    return invalidateList;
  }, [fetchPage, invalidateList]);
  useEffect(() => {
    ++detailRequestSeq.current;
    setDetail(null);
    setDetailLoading(false);
    return invalidateDetail;
  }, [locationId, invalidateDetail]);
  const openDetailById = useCallback(async (headerId: number) => {
    const seq = ++detailRequestSeq.current;
    setDetailLoading(true);
    setDetail(null);
    try {
      const raw = await authenticatedFetch(`/warehouse/unified/transfers/${headerId}`);
      if (seq !== detailRequestSeq.current) return false;
      setDetail({ locationId, value: parseTransferDetail(raw, locationId) });
      return true;
    } catch (error) {
      if (seq !== detailRequestSeq.current) return false;
      toast.error(getErrorMessage(error, t("inventoryTransfers.detailFailure")));
      return false;
    } finally { if (seq === detailRequestSeq.current) setDetailLoading(false); }
  }, [authenticatedFetch, locationId, t]);
  const resetDetail = useCallback(() => { ++detailRequestSeq.current; setDetail(null); setDetailLoading(false); }, []);
  const items = current?.items ?? [];
  const inTransitCount = items.filter(item => item.status === "IN_TRANSIT").length;
  return {
    items, status, setStatus, direction, setDirection, searchInput, setSearchInput,
    total: current?.total ?? null, loading, cursorHistory: current?.history ?? [], nextCursor: current?.next ?? null,
    failure: failure?.scope === scope ? failure : null,
    retry: () => void fetchPage(lastAttempt.current),
    detail: detailState?.locationId === locationId ? detailState.value : null, detailLoading, inTransitCount,
    openDetailById, openDetail: (transfer: WarehouseTransferListItem) => openDetailById(transfer.id),
    closeDetail: resetDetail, resetDetail,
    refreshTransfers: () => void fetchPage({ cursor: current?.cursor ?? null, history: current?.history ?? [], phase: current ? "refresh" : "first" }),
    handleNext: () => { if (current?.next && !loading) void fetchPage({ cursor: current.next, history: [...current.history, current.cursor], phase: "continuation" }); },
    handlePrevious: () => { if (current?.history.length && !loading) void fetchPage({ cursor: current.history[current.history.length - 1] ?? null, history: current.history.slice(0, -1), phase: "continuation" }); },
  };
}
