import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
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
  loadCountSheet: (
    sessionId: string,
    sessionLocationId?: number
  ) => Promise<void>;
  loadReview: (
    sessionId: string,
    sessionLocationId?: number
  ) => Promise<void>;
  setSessionId: (value: string | null) => void;
  setSessionLocationId: (
    value: number | null
  ) => void;
  setPhase: (value: StocktakePhase) => void;
  clearRows: () => void;
  clearReview: () => void;
  notifyStocktakeChanged: () => Promise<void>;
}

export function useStocktakeLifecycle({
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
  const [locking, setLocking] =
    useState(false);
  const handledFocusRef = useRef<number | null>(null);

  const fetchSessionContext =
    useCallback(
      async (
        sid: string
      ): Promise<StocktakeSessionContext> => {
        const params = new URLSearchParams({
          anchor_location_id:
            String(locationId),
        });

        const raw = await authenticatedFetch(
          `/warehouse/unified/stocktake/${sid}/context?${params.toString()}`
        );

        return parseStocktakeSessionContext(
          raw,
          locationId
        );
      },
      [authenticatedFetch, locationId]
    );

  const openResolvedSession =
    useCallback(
      async (
        sid: string,
        context: StocktakeSessionContext
      ) => {
        localStorage.setItem(
          sessionKey,
          sid
        );
        setSessionLocationId(
          context.location_id
        );

        if (
          context.status ===
          "PENDING_REVIEW"
        ) {
          await loadReview(
            sid,
            context.location_id
          );
          return;
        }

        if (
          context.status === "COUNTING" ||
          context.status ===
            "RECOUNT_REQUIRED"
        ) {
          await loadCountSheet(
            sid,
            context.location_id
          );
          return;
        }

        throw new Error(
          `الجلسة بحالة (${context.status}) ولا يمكن فتحها في شاشة العد الحالية.`
        );
      },
      [
        loadCountSheet,
        loadReview,
        sessionKey,
        setSessionLocationId,
      ]
    );

  const openSessionById =
    useCallback(
      async (sid: string) => {
        const context =
          await fetchSessionContext(sid);
        await openResolvedSession(
          sid,
          context
        );
      },
      [
        fetchSessionContext,
        openResolvedSession,
      ]
    );

  const openServerSession = useCallback(
    async (
      session: StocktakeSessionSummary
    ) => {
      try {
        await openSessionById(
          String(session.id)
        );
      } catch (error: unknown) {
        toast.error(
          getErrorMessage(
            error,
            "تعذر فتح جلسة الجرد."
          )
        );
      }
    },
    [openSessionById]
  );

  useEffect(() => {
    const requestedFocus = focusSessionId !== undefined && handledFocusRef.current !== focusSessionId;
    const previousSession = localStorage.getItem(sessionKey);
    const previousPhase = localStorage.getItem(phaseKey);
    const sid =
      requestedFocus ? String(focusSessionId) : previousSession;

    if (!sid) {
      clearRows();
      clearReview();
      setSessionId(null);
      setSessionLocationId(null);
      setPhase("COUNTING");
      return;
    }

    let cancelled = false;

    const recover = async () => {
      try {
        const context =
          await fetchSessionContext(sid);

        if (cancelled) return;
        if (requestedFocus && (context.session_id !== focusSessionId || !["COUNTING", "PENDING_REVIEW", "RECOUNT_REQUIRED"].includes(context.status))) {
          throw Object.assign(new Error("ARCHIVE_OWNER_UNAVAILABLE"), { code: "ARCHIVE_OWNER_UNAVAILABLE" });
        }

        setSessionId(sid);
        setSessionLocationId(
          context.location_id
        );

        try {
          await openResolvedSession(
            sid,
            context
          );
          if (requestedFocus && !cancelled) handledFocusRef.current = focusSessionId ?? null;
          return;
        } catch (error: unknown) {
          if (
            (!requestedFocus || previousSession === sid) &&
            localStorage.getItem(
              phaseKey
            ) ===
              "WAITING_INDEPENDENT" &&
            context.status ===
              "RECOUNT_REQUIRED"
          ) {
            clearRows();
            clearReview();
            setPhase(
              "WAITING_INDEPENDENT"
            );
            if (requestedFocus && !cancelled) handledFocusRef.current = focusSessionId ?? null;
            return;
          }
          throw error;
        }
      } catch (error: unknown) {
        if (cancelled) return;

        if (requestedFocus) {
          handledFocusRef.current = focusSessionId ?? null;
          // Do not discard a different session's saved draft on stale/denied navigation.
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

        if (!requestedFocus) toast.error(
          getErrorMessage(
            error,
            "تعذر استعادة جلسة الجرد الحالية."
          )
        );
      }
    };

    void recover();

    return () => {
      cancelled = true;
    };
  }, [
    focusSessionId,
    onFocusUnavailable,
    clearReview,
    clearRows,
    fetchSessionContext,
    openResolvedSession,
    phaseKey,
    sessionKey,
    setPhase,
    setSessionId,
    setSessionLocationId,
  ]);

  const startStocktake =
    useCallback(async () => {
      if (
        sessionsLoading ||
        sessionsLoadFailed
      ) {
        toast.error(
          "لا يمكن بدء جرد شامل قبل التحقق من جلسات الجرد النشطة على السيرفر."
        );
        return false;
      }

      if (
        (
          activeSessionsTotal ??
          activeSessions.length
        ) > 0
      ) {
        toast.error(
          "يوجد جرد نشط في هذا الموقع. أغلق الجلسات النشطة قبل بدء جرد شامل."
        );
        return false;
      }

      setLocking(true);

      try {
        const raw =
          await authenticatedFetch(
            "/warehouse/unified/stocktake/start",
            {
              method: "POST",
              body: JSON.stringify({
                location_id:
                  locationId,
                stocktake_type:
                  "FULL_COUNT",
                notes:
                  "بدء جرد مركزي",
              }),
            }
          );

        const sid = String(
          parseStartSessionId(raw)
        );

        localStorage.setItem(
          sessionKey,
          sid
        );
        localStorage.setItem(
          phaseKey,
          "COUNTING"
        );
        setSessionLocationId(locationId);
        setSessionId(sid);

        await loadCountSheet(
          sid,
          locationId
        );
        await notifyStocktakeChanged();

        toast.success(
          "تم قفل المستودع وبدء عد أعمى. الرصيد المتوقع مخفي حتى تثبيت العد."
        );
        return true;
      } catch (error: unknown) {
        toast.error(
          getErrorMessage(
            error,
            "فشل بدء جلسة الجرد."
          )
        );
        return false;
      } finally {
        setLocking(false);
      }
    }, [
      activeSessions.length,
      activeSessionsTotal,
      authenticatedFetch,
      loadCountSheet,
      locationId,
      notifyStocktakeChanged,
      phaseKey,
      sessionKey,
      sessionsLoadFailed,
      sessionsLoading,
      setSessionId,
      setSessionLocationId,
    ]);

  return {
    locking,
    openServerSession,
    openSessionById,
    startStocktake,
    selectedSessionId:
      sessionId
        ? Number(sessionId)
        : null,
    selectedSessionLocationId:
      sessionLocationId,
  };
}
