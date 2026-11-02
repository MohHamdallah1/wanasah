import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { useStocktakeCopy } from "../copy";
import { executeStocktakeDurableCommand, type StocktakeDurableIdentity } from "../durableCommand";
import type {
  StocktakeAuthFetch,
  StocktakePhase,
  StocktakeSessionContext,
  StocktakeSessionSummary,
} from "../types";
import {
  getErrorMessage,
  parseStartSessionId,
  parseStocktakeSessionContext,
} from "../parsers";

interface UseStocktakeLifecycleArgs {
  active?: boolean;
  durableIdentity: StocktakeDurableIdentity | null;
  focusSessionId?: number;
  onFocusUnavailable?: (error: unknown) => void;
  locationId: number;
  sessionKey: string;
  phaseKey: string;
  sessionId: string | null;
  sessionLocationId: number | null;
  activeSessions: StocktakeSessionSummary[];
  activeSessionsTotal: number | null;
  sessionsLoading: boolean;
  sessionsLoadFailed: boolean;
  authenticatedFetch: StocktakeAuthFetch;
  loadCountSheet: (sessionId: string, sessionLocationId?: number, isCurrent?: () => boolean) => Promise<void>;
  loadReview: (sessionId: string, sessionLocationId?: number, isCurrent?: () => boolean) => Promise<void>;
  setSessionId: (value: string | null) => void;
  setSessionLocationId: (value: number | null) => void;
  setPhase: (value: StocktakePhase) => void;
  clearRows: () => void;
  clearReview: () => void;
  notifyStocktakeChanged: () => Promise<void>;
}

export function useStocktakeLifecycle({
  active = true,
  durableIdentity,
  focusSessionId,
  onFocusUnavailable,
  locationId,
  sessionKey,
  phaseKey,
  sessionId,
  sessionLocationId,
  activeSessions,
  activeSessionsTotal,
  sessionsLoading,
  sessionsLoadFailed,
  authenticatedFetch,
  loadCountSheet,
  loadReview,
  setSessionId,
  setSessionLocationId,
  setPhase,
  clearRows,
  clearReview,
  notifyStocktakeChanged,
}: UseStocktakeLifecycleArgs) {
  const { copy } = useStocktakeCopy();
  const [locking, setLocking] = useState(false);
  const handledFocusRef = useRef<number | null>(null);
  // Session selection governs context and all following sheet/review requests.
  const sessionReadGeneration = useRef(0);

  const fetchSessionContext = useCallback(async (sid: string): Promise<StocktakeSessionContext> => {
    const params = new URLSearchParams({ anchor_location_id: String(locationId) });
    const raw = await authenticatedFetch(`/warehouse/unified/stocktake/${sid}/context?${params.toString()}`);
    return parseStocktakeSessionContext(raw, locationId);
  }, [authenticatedFetch, locationId]);

  const openResolvedSession = useCallback(async (
    sid: string,
    context: StocktakeSessionContext,
    isCurrent: () => boolean,
  ) => {
    if (!isCurrent()) return;
    localStorage.setItem(sessionKey, sid);
    setSessionLocationId(context.location_id);
    if (context.status === "PENDING_REVIEW") {
      await loadReview(sid, context.location_id, isCurrent);
      return;
    }
    if (context.status === "COUNTING" || context.status === "RECOUNT_REQUIRED") {
      await loadCountSheet(sid, context.location_id, isCurrent);
      return;
    }
    throw new Error(copy.lifecycle.unsupportedState(context.status));
  }, [copy.lifecycle, loadCountSheet, loadReview, sessionKey, setSessionLocationId]);

  const openSessionById = useCallback(async (sid: string) => {
    const generation = ++sessionReadGeneration.current;
    const context = await fetchSessionContext(sid);
    const isCurrent = () => generation === sessionReadGeneration.current;
    if (!isCurrent()) return;
    await openResolvedSession(sid, context, isCurrent);
  }, [fetchSessionContext, openResolvedSession]);

  const openServerSession = useCallback(async (session: StocktakeSessionSummary) => {
    try {
      await openSessionById(String(session.id));
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, copy.generic.sessionOpenFailed));
    }
  }, [copy.generic.sessionOpenFailed, openSessionById]);

  useEffect(() => {
    // Preserve the durable session/drafts while hidden, but never refresh
    // session context or count sheets until this tab is re-entered.
    if (!active) {
      sessionReadGeneration.current += 1;
      return;
    }
    const generation = ++sessionReadGeneration.current;
    let cancelled = false;
    const isCurrent = () => !cancelled && generation === sessionReadGeneration.current;
    const requestedFocus = focusSessionId !== undefined && handledFocusRef.current !== focusSessionId;
    const previousSession = localStorage.getItem(sessionKey);
    const previousPhase = localStorage.getItem(phaseKey);
    const sid = requestedFocus ? String(focusSessionId) : previousSession;

    if (!sid) {
      clearRows();
      clearReview();
      setSessionId(null);
      setSessionLocationId(null);
      setPhase("COUNTING");
      return;
    }

    const recover = async () => {
      try {
        const context = await fetchSessionContext(sid);
        if (!isCurrent()) return;
        if (requestedFocus && (context.session_id !== focusSessionId || !["COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED"].includes(context.status))) {
          throw Object.assign(new Error("ARCHIVE_OWNER_UNAVAILABLE"), { code: "ARCHIVE_OWNER_UNAVAILABLE" });
        }

        setSessionId(sid);
        setSessionLocationId(context.location_id);
        try {
          await openResolvedSession(sid, context, isCurrent);
          if (requestedFocus && isCurrent()) handledFocusRef.current = focusSessionId ?? null;
          return;
        } catch (error: unknown) {
          if (
            (!requestedFocus || previousSession === sid) &&
            localStorage.getItem(phaseKey) === "WAITING_INDEPENDENT" &&
            context.status === "RECOUNT_REQUIRED"
          ) {
            clearRows();
            clearReview();
            setPhase("WAITING_INDEPENDENT");
            if (requestedFocus && isCurrent()) handledFocusRef.current = focusSessionId ?? null;
            return;
          }
          throw error;
        }
      } catch (error: unknown) {
        if (!isCurrent()) return;
        if (requestedFocus) {
          handledFocusRef.current = focusSessionId ?? null;
          if (localStorage.getItem(sessionKey) === sid) {
            if (previousSession === null) localStorage.removeItem(sessionKey);
            else localStorage.setItem(sessionKey, previousSession);
            if (previousPhase === null) localStorage.removeItem(phaseKey);
            else localStorage.setItem(phaseKey, previousPhase);
          }
          onFocusUnavailable?.(error);
        } else {
          localStorage.removeItem(sessionKey);
          localStorage.removeItem(phaseKey);
        }
        setSessionId(null);
        setSessionLocationId(null);
        clearRows();
        clearReview();
        setPhase("COUNTING");
        if (!requestedFocus) toast.error(getErrorMessage(error, copy.generic.sessionRestoreFailed));
      }
    };

    void recover();
    return () => { cancelled = true; };
  }, [active, focusSessionId, onFocusUnavailable, clearReview, clearRows, copy.generic.sessionRestoreFailed, fetchSessionContext, openResolvedSession, phaseKey, sessionKey, setPhase, setSessionId, setSessionLocationId]);

  const startStocktake = useCallback(async () => {
    if (sessionsLoading || sessionsLoadFailed) {
      toast.error(copy.lifecycle.verifyBeforeStart);
      return false;
    }
    if ((activeSessionsTotal ?? activeSessions.length) > 0) {
      toast.error(copy.lifecycle.activeExists);
      return false;
    }
    if (!durableIdentity) {
      toast.error(copy.generic.identityNotReady);
      return false;
    }

    setLocking(true);
    try {
      const raw = await executeStocktakeDurableCommand({
        identity: durableIdentity,
        operation: "start-full",
        target: locationId,
        payload: {
          location_id: locationId,
          stocktake_type: "FULL_COUNT",
          notes: copy.lifecycle.fullStartNote,
        },
        send: (body) => authenticatedFetch(
          "/warehouse/unified/stocktake/start",
          { method: "POST", body: JSON.stringify(body) },
        ),
      });

      const sid = String(parseStartSessionId(raw));
      localStorage.setItem(sessionKey, sid);
      localStorage.setItem(phaseKey, "COUNTING");
      setSessionLocationId(locationId);
      setSessionId(sid);
      await loadCountSheet(sid, locationId);
      await notifyStocktakeChanged();
      toast.success(copy.lifecycle.started);
      return true;
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, copy.generic.startFailed));
      return false;
    } finally {
      setLocking(false);
    }
  }, [activeSessions.length, activeSessionsTotal, authenticatedFetch, copy.generic.identityNotReady, copy.generic.startFailed, copy.lifecycle, durableIdentity, loadCountSheet, locationId, notifyStocktakeChanged, phaseKey, sessionKey, sessionsLoadFailed, sessionsLoading, setSessionId, setSessionLocationId]);

  return {
    locking,
    openServerSession,
    openSessionById,
    startStocktake,
    selectedSessionId: sessionId ? Number(sessionId) : null,
    selectedSessionLocationId: sessionLocationId,
  };
}
