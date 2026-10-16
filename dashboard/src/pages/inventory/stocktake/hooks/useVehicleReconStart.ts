import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useStocktakeCopy } from "../copy";
import { executeStocktakeDurableCommand, type StocktakeDurableIdentity } from "../durableCommand";
import type { StocktakeAuthFetch, VehicleReconCandidate } from "../types";
import { getErrorMessage, parseStartSessionId, parseVehicleReconCandidatePage } from "../parsers";

interface UseVehicleReconStartArgs {
  durableIdentity: StocktakeDurableIdentity | null;
  sourceLocationId: number;
  enabled: boolean;
  authenticatedFetch: StocktakeAuthFetch;
  openSessionById: (sessionId: string) => Promise<void>;
  notifyStocktakeChanged: () => Promise<void>;
}

const OPENABLE_EXISTING_STATUSES = new Set(["COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED"]);

export function useVehicleReconStart({
  durableIdentity, sourceLocationId, enabled, authenticatedFetch, openSessionById, notifyStocktakeChanged,
}: UseVehicleReconStartArgs) {
  const { copy } = useStocktakeCopy();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<VehicleReconCandidate[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [busyWorkSessionId, setBusyWorkSessionId] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const requestSeq = useRef(0);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const resetForm = useCallback(() => {
    requestSeq.current += 1;
    setSearchInput("");
    setSearch("");
    setItems([]);
    setNextCursor(null);
    setLoading(false);
    setLoadingMore(false);
    setBusyWorkSessionId(null);
    setNotes("");
  }, []);

  const fetchCandidates = useCallback(async (cursor: string | null = null, append = false) => {
    if (!enabled) return;
    const seq = ++requestSeq.current;
    if (append) setLoadingMore(true);
    else { setLoading(true); setNextCursor(null); }

    try {
      const params = new URLSearchParams({ source_location_id: String(sourceLocationId), limit: "50" });
      if (search) params.set("search", search);
      if (cursor) params.set("cursor", cursor);
      const raw = await authenticatedFetch(`/warehouse/unified/stocktake/vehicle-recon-candidates?${params.toString()}`);
      if (seq !== requestSeq.current) return;
      const page = parseVehicleReconCandidatePage(raw);
      setItems((prev) => {
        if (!append) return page.items;
        const merged = new Map<number, VehicleReconCandidate>();
        for (const item of prev) merged.set(item.work_session_id, item);
        for (const item of page.items) merged.set(item.work_session_id, item);
        return [...merged.values()];
      });
      setNextCursor(page.next_cursor);
    } catch (error: unknown) {
      if (seq !== requestSeq.current) return;
      if (!append) { setItems([]); setNextCursor(null); }
      toast.error(getErrorMessage(error, copy.generic.vehicleCandidatesFailed));
    } finally {
      if (seq === requestSeq.current) append ? setLoadingMore(false) : setLoading(false);
    }
  }, [authenticatedFetch, copy.generic.vehicleCandidatesFailed, enabled, search, sourceLocationId]);

  useEffect(() => {
    if (!enabled) return;
    setItems([]);
    setNextCursor(null);
    void fetchCandidates(null, false);
  }, [enabled, fetchCandidates]);

  const loadMore = useCallback(() => {
    if (!nextCursor || loadingMore) return;
    void fetchCandidates(nextCursor, true);
  }, [fetchCandidates, loadingMore, nextCursor]);

  const startOrOpen = useCallback(async (candidate: VehicleReconCandidate) => {
    if (busyWorkSessionId !== null) return false;
    setBusyWorkSessionId(candidate.work_session_id);
    try {
      if (candidate.existing_stocktake_session_id) {
        if (!candidate.existing_stocktake_status || !OPENABLE_EXISTING_STATUSES.has(candidate.existing_stocktake_status)) {
          toast.error(copy.vehicle.conflict(candidate.existing_stocktake_status ?? copy.vehicle.unknown));
          return false;
        }
        await openSessionById(String(candidate.existing_stocktake_session_id));
        return true;
      }

      if (!durableIdentity) {
        toast.error(copy.generic.identityNotReady);
        return false;
      }

      const raw = await executeStocktakeDurableCommand({
        identity: durableIdentity,
        operation: "start-vehicle-recon",
        target: `${candidate.vehicle_location_id}:${candidate.work_session_id}`,
        payload: {
          location_id: candidate.vehicle_location_id,
          stocktake_type: "VEHICLE_RECON",
          related_work_session_id: candidate.work_session_id,
          notes: notes.trim() || null,
        },
        send: (body) => authenticatedFetch(
          "/warehouse/unified/stocktake/start",
          { method: "POST", body: JSON.stringify(body) },
        ),
      });
      const sid = String(parseStartSessionId(raw));
      await openSessionById(sid);
      await notifyStocktakeChanged();
      toast.success(copy.vehicle.started(candidate.vehicle_location_name, candidate.work_session_id));
      return true;
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, copy.generic.vehicleStartFailed));
      return false;
    } finally {
      setBusyWorkSessionId(null);
    }
  }, [
    authenticatedFetch, busyWorkSessionId, copy.generic.identityNotReady,
    copy.generic.vehicleStartFailed, copy.vehicle, durableIdentity, notes,
    notifyStocktakeChanged, openSessionById,
  ]);

  return {
    searchInput, setSearchInput, items, nextCursor, loading, loadingMore,
    busyWorkSessionId, notes, setNotes, loadMore, startOrOpen, resetForm,
  };
}

export type VehicleReconStartController = ReturnType<typeof useVehicleReconStart>;
