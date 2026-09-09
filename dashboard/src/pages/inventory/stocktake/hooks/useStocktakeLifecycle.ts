import {
  useCallback,
  useEffect,
  useState,
} from "react";
import { toast } from "sonner";
import type {
  StocktakeAuthFetch,
  StocktakePhase,
  StocktakeSessionSummary,
} from "../types";
import {
  getErrorMessage,
  parseStartSessionId,
} from "../parsers";

interface UseStocktakeLifecycleArgs {
  locationId: number;
  sessionKey: string;
  phaseKey: string;
  sessionId: string | null;
  activeSessions: StocktakeSessionSummary[];
  activeSessionsTotal: number | null;
  sessionsLoading: boolean;
  sessionsLoadFailed: boolean;
  authenticatedFetch: StocktakeAuthFetch;
  loadCountSheet: (sessionId: string) => Promise<void>;
  loadReview: (sessionId: string) => Promise<void>;
  setSessionId: (value: string | null) => void;
  setPhase: (value: StocktakePhase) => void;
  clearRows: () => void;
  clearReview: () => void;
  notifyStocktakeChanged: () => Promise<void>;
}

export function useStocktakeLifecycle({
  locationId,
  sessionKey,
  phaseKey,
  sessionId,
  activeSessions,
  activeSessionsTotal,
  sessionsLoading,
  sessionsLoadFailed,
  authenticatedFetch,
  loadCountSheet,
  loadReview,
  setSessionId,
  setPhase,
  clearRows,
  clearReview,
  notifyStocktakeChanged,
}: UseStocktakeLifecycleArgs) {
  const [locking, setLocking] =
    useState(false);

  const openServerSession = useCallback(
    async (
      session: StocktakeSessionSummary
    ) => {
      const sid = String(session.id);

      try {
        if (
          session.status ===
          "PENDING_REVIEW"
        ) {
          localStorage.setItem(
            sessionKey,
            sid
          );
          await loadReview(sid);
          return;
        }

        if (
          session.status === "COUNTING" ||
          session.status ===
            "RECOUNT_REQUIRED"
        ) {
          localStorage.setItem(
            sessionKey,
            sid
          );
          await loadCountSheet(sid);
          return;
        }

        toast.info(
          `الجلسة بحالة (${session.status}) ولا يمكن فتحها في شاشة العد الحالية.`
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
    [
      loadCountSheet,
      loadReview,
      sessionKey,
    ]
  );

  useEffect(() => {
    const sid =
      localStorage.getItem(sessionKey);

    if (!sid) {
      clearRows();
      clearReview();
      setSessionId(null);
      setPhase("COUNTING");
      return;
    }

    setSessionId(sid);
    let cancelled = false;

    const recover = async () => {
      try {
        if (cancelled) return;
        await loadReview(sid);
        return;
      } catch {
        // طبيعي أثناء COUNTING أو RECOUNT_REQUIRED.
      }

      try {
        if (cancelled) return;
        await loadCountSheet(sid);
      } catch (error: unknown) {
        if (cancelled) return;

        if (
          localStorage.getItem(
            phaseKey
          ) ===
          "WAITING_INDEPENDENT"
        ) {
          setPhase(
            "WAITING_INDEPENDENT"
          );
          return;
        }

        localStorage.removeItem(
          sessionKey
        );
        localStorage.removeItem(
          phaseKey
        );
        setSessionId(null);
        clearRows();
        clearReview();
        setPhase("COUNTING");

        toast.error(
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
    authenticatedFetch,
    clearReview,
    clearRows,
    loadCountSheet,
    loadReview,
    locationId,
    phaseKey,
    sessionKey,
    setPhase,
    setSessionId,
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
        setSessionId(sid);

        await loadCountSheet(sid);
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
    ]);

  return {
    locking,
    openServerSession,
    startStocktake,
    selectedSessionId:
      sessionId
        ? Number(sessionId)
        : null,
  };
}
