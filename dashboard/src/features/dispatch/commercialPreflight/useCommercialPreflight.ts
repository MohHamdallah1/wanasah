import { useCallback, useEffect, useRef, useState } from "react";
import { apiErrorStatus } from "@/lib/apiErrors";
import {
  parseCommercialPreflight, preflightSelectionValid, preflightUrl,
  type CommercialPreflight, type PreflightSelection,
} from "./contract";

type ReadinessState =
  | { key: string; status: "choose" | "loading" | "denied" | "error"; evidence: null }
  | { key: string; status: "ready" | "blocked"; evidence: CommercialPreflight };

export type PreflightReader = (path: string, options?: RequestInit) => Promise<unknown>;

export function useCommercialPreflight({
  selection, actorScope, authorized, current, fetch,
}: {
  selection: PreflightSelection;
  actorScope: string | null;
  authorized: boolean;
  current: () => boolean;
  fetch: PreflightReader;
}) {
  const key = actorScope ? JSON.stringify([actorScope, selection.zoneId,
    selection.driverId, selection.vehicleId, selection.warehouseId]) : "";
  const eligible = Boolean(actorScope && authorized && preflightSelectionValid(selection));
  const [revision, setRevision] = useState(0);
  const [stored, setStored] = useState<ReadinessState>({
    key: "", status: "choose", evidence: null,
  });
  const ref = useRef({ key, eligible, current, fetch, selection });
  ref.current = { key, eligible, current, fetch, selection };
  const seq = useRef(0);

  const read = useCallback(async (signal?: AbortSignal): Promise<CommercialPreflight | null> => {
    const captured = ref.current;
    if (!captured.eligible || !captured.current()) return null;
    const token = ++seq.current;
    setStored({ key: captured.key, status: "loading", evidence: null });
    const admitted = () =>
      !signal?.aborted && token === seq.current &&
      ref.current.key === captured.key && ref.current.eligible && ref.current.current();
    try {
      const raw = await captured.fetch(preflightUrl(captured.selection),
        { method: "GET", cache: "no-store", signal });
      if (!admitted()) return null;
      const evidence = parseCommercialPreflight(raw);
      setStored({ key: captured.key, status: evidence.ready ? "ready" : "blocked", evidence });
      return evidence;
    } catch (error) {
      if (!admitted()) return null;
      setStored({
        key: captured.key,
        status: [401, 403].includes(apiErrorStatus(error) ?? 0) ? "denied" : "error",
        evidence: null,
      });
      return null;
    }
  }, []);

  useEffect(() => {
    ++seq.current; // late results of a previous permission/context cannot become READY
    if (!eligible) {
      setStored({ key, status: "choose", evidence: null });
      return;
    }
    const controller = new AbortController();
    void read(controller.signal);
    return () => { ++seq.current; controller.abort(); };
  }, [key, eligible, revision, read]);

  const state: ReadinessState = eligible
    ? stored.key === key ? stored : { key, status: "loading", evidence: null }
    : { key, status: "choose", evidence: null };

  return {
    ...state,
    canLaunch: eligible && state.status === "ready",
    verifyBeforeLaunch: read,
    refresh: () => setRevision(n => n + 1),
  };
}
